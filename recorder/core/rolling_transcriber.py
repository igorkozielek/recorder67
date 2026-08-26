import os
import sys
import queue
import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime
from PySide6.QtCore import QThread, Signal as pyqtSignal

from recorder.core.transcriber import TranscriberEngine, is_hallucination, clean_repeated_text
from recorder.core.diarizer import format_transcript_without_diarization
from recorder.core.speakers import format_turns, suggest_speaker_names
from recorder.config import (
    DEFAULT_WHISPER_MODEL,
    DEFAULT_BEAM_SIZE,
    DEFAULT_INITIAL_PROMPT,
    get_env_variable
)
from recorder.audio.converter import highpass_filter_audio, normalize_audio


class RollingBlock:
    """
    Struktura reprezentująca pojedynczy zamknięty blok nagrania audio w sesji.
    """
    def __init__(self, block_index: int, start_sec: float, end_sec: float, audio_float: np.ndarray):
        self.block_index = block_index
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.audio_float = audio_float
        self.turns: List[Dict[str, Any]] = []
        self.plain_text: str = ""
        self.html_text: str = ""
        self.is_processed: bool = False


class RollingTranscriptionWorker(QThread):
    """
    Wątek asynchronicznego przetwarzania bloków transkrypcji w tle (Rolling Background Transcriber).
    Przelicza czasy lokalne słów na globalną oś czasu spotkania i na bieżąco aktualizuje transkrypcję.
    """
    block_processed_signal = pyqtSignal(int, float, float, list, str, str)  # (block_idx, processed_sec, total_sec, all_turns, full_plain, full_html)
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str, str, list)  # (final_html, final_plain, all_turns)
    error_signal = pyqtSignal(str)

    def __init__(self, model_size: str = DEFAULT_WHISPER_MODEL, txt_save_path: Optional[str] = None):
        super().__init__()
        self.model_size = model_size
        self.txt_save_path = txt_save_path
        self.block_queue: queue.Queue = queue.Queue()
        self._is_running: bool = False
        self.transcriber = TranscriberEngine(model_size=self.model_size)
        
        self.processed_blocks: List[RollingBlock] = []
        self.all_turns: List[Dict[str, Any]] = []
        self.total_processed_seconds: float = 0.0
        self.latest_session_seconds: float = 0.0

    def add_block(self, block_index: int, start_sec: float, end_sec: float, audio_float: np.ndarray):
        """Dodaje nowy zamknięty blok audio do kolejki przetwarzania w tle."""
        if self._is_running:
            block = RollingBlock(block_index, start_sec, end_sec, audio_float)
            self.latest_session_seconds = max(self.latest_session_seconds, end_sec)
            self.block_queue.put(block)

    def update_session_time(self, current_sec: float):
        """Aktualizuje bieżący czas sesji ze stopera."""
        self.latest_session_seconds = max(self.latest_session_seconds, float(current_sec))

    def stop_and_finalize(self, final_block: Optional[RollingBlock] = None):
        """Zgłasza zakończenie nagrywania i zamyka kolejkę po przetworzeniu ewentualnego ostatniego bloku."""
        self._is_running = False
        if final_block:
            self.block_queue.put(final_block)
        self.block_queue.put(None)

    def run(self):
        self._is_running = True
        try:
            self.status_signal.emit(f"Inicjalizacja silnika Whisper ({self.model_size})...")
            self.transcriber.load_model()
            self.status_signal.emit("Silnik transkrypcji w tle: GOTOWY")

            while True:
                try:
                    block: Optional[RollingBlock] = self.block_queue.get(timeout=0.3)
                except queue.Empty:
                    if not self._is_running:
                        break
                    continue

                if block is None:
                    break

                # 1. Przetworzenie bloku audio
                self._process_single_block(block)
                self.block_queue.task_done()

            # 2. Finalizacja całego spotkania po zakończeniu kolejki
            final_html, final_plain, turns = self._compile_full_transcript()
            self._save_to_txt_file(final_plain)
            self.finished_signal.emit(final_html, final_plain, turns)

        except Exception as e:
            self.error_signal.emit(f"Błąd przetwarzania w tle: {e}")

    def _process_single_block(self, block: RollingBlock):
        """Transkrybuje pojedynczy blok i mapuje jego słowa na globalną oś czasu."""
        audio_data = block.audio_float
        if audio_data is None or len(audio_data) < int(1.0 * 16000):
            block.is_processed = True
            self.processed_blocks.append(block)
            return

        # Dźwięk w formacie float32 mono 16kHz (zawsze 1D)
        if audio_data.dtype == np.int16:
            audio_float = (audio_data.astype(np.float32) / 32768.0).flatten()
        else:
            audio_float = audio_data.astype(np.float32).flatten()

        if len(audio_float) < int(1.0 * 16000):
            block.is_processed = True
            self.processed_blocks.append(block)
            return

        # Oczyszczenie pasma i normalizacja głośności bloku
        audio_clean = highpass_filter_audio(audio_float, sr=16000, cutoff_hz=80.0)
        audio_norm = normalize_audio(audio_clean, target_peak=0.92)

        custom_kw = get_env_variable("CUSTOM_KEYWORDS", "")
        extra_ctx = f", {custom_kw}" if custom_kw else ""
        initial_prompt = f"{DEFAULT_INITIAL_PROMPT}{extra_ctx}"

        transcript_words = []

        try:
            # Transkrypcja bloku z word-level timestamps i beam search
            segments, _ = self.transcriber._model.transcribe(
                audio_norm,
                word_timestamps=True,
                language="pl",
                beam_size=DEFAULT_BEAM_SIZE,
                temperature=0.0,
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.4,
                vad_filter=True,
                vad_parameters=dict(
                    threshold=0.35,
                    min_speech_duration_ms=200,
                    min_silence_duration_ms=400,
                    speech_pad_ms=400
                ),
                initial_prompt=initial_prompt
            )

            for segment in segments:
                raw_text = segment.text.strip() if segment.text else ""
                seg_text = clean_repeated_text(raw_text)
                if not seg_text or is_hallucination(seg_text):
                    continue

                # Jeśli segment ma dokładne słowa
                if segment.words:
                    for w in segment.words:
                        w_text = w.word.strip()
                        if w_text:
                            # Globalne timestampy: start_sec całego bloku + lokalny start słowa
                            g_start = round(block.start_sec + float(w.start), 2)
                            g_end = round(block.start_sec + float(w.end), 2)
                            transcript_words.append({
                                "word": w.word,
                                "start": g_start,
                                "end": g_end,
                                "probability": getattr(w, "probability", 1.0)
                            })
                else:
                    # Fallback estymacji słów
                    words = seg_text.split()
                    if words:
                        w_dur = (segment.end - segment.start) / max(1, len(words))
                        for i, w_str in enumerate(words):
                            w_start = round(block.start_sec + segment.start + (i * w_dur), 2)
                            w_end = round(w_start + w_dur, 2)
                            transcript_words.append({
                                "word": (" " + w_str if i > 0 else w_str),
                                "start": w_start,
                                "end": w_end,
                                "probability": 0.9
                            })
        except Exception as trans_err:
            print(f"[ROLLING] Pominięto fragment bloku #{block.index}: {trans_err}")

        # Formatowanie słów tego bloku do turnów
        block.words = transcript_words
        if transcript_words:
            _, _, block_turns = format_transcript_without_diarization(transcript_words)
            block.turns = block_turns

        block.is_processed = True
        self.processed_blocks.append(block)
        self.total_processed_seconds = max(self.total_processed_seconds, block.end_sec)

        # Scalanie całościowej transkrypcji
        full_html, full_plain, all_turns = self._compile_full_transcript()
        self.all_turns = all_turns

        # Zapis do pliku TXT oraz sesji JSON w czasie rzeczywistym
        self._save_to_txt_file(full_plain)
        self._save_to_session_file(all_turns)

        # Emitowanie sygnału aktualizacji do UI
        self.block_processed_signal.emit(
            block.block_index,
            self.total_processed_seconds,
            max(self.latest_session_seconds, self.total_processed_seconds),
            all_turns,
            full_plain,
            full_html
        )

    def _compile_full_transcript(self):
        """Kompiluje wszystkie przetworzone bloki w jedną spójną transkrypcję."""
        combined_turns = []
        for b in sorted(self.processed_blocks, key=lambda x: x.start_sec):
            combined_turns.extend(b.turns)

        if not combined_turns:
            return "Brak zarejestrowanej mowy.", "Brak zarejestrowanej mowy.", []

        full_html = ""
        full_plain = ""
        for t in combined_turns:
            spk = t.get("speaker", "Mówca")
            st = t.get("start", 0.0)
            en = t.get("end", 0.0)
            txt = t.get("text", "")
            
            # Formatowanie minut i sekund: [MM:SS - MM:SS]
            s_min, s_sec = int(st // 60), int(st % 60)
            e_min, e_sec = int(en // 60), int(en % 60)
            time_label = f"{s_min:02d}:{s_sec:02d} - {e_min:02d}:{e_sec:02d}"

            full_html += f"<b>[{time_label}] {spk}:</b> {txt}<br><br>"
            full_plain += f"[{time_label}] {spk}: {txt}\n\n"

        return full_html, full_plain, combined_turns

    def _save_to_txt_file(self, content: str):
        """Bezpiecznie zapisuje bieżącą transkrypcję do pliku TXT na dysku."""
        if not self.txt_save_path or not content:
            return
        try:
            with open(self.txt_save_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
        except Exception:
            pass

    def _save_to_session_file(self, turns: list):
        """Automatycznie tworzy i zapisuje plik sesji JSON z kompletem słów z Whispera."""
        if not self.txt_save_path:
            return
        try:
            from recorder.core.session import TranscriptionSession, get_session_path_for_txt
            json_path = get_session_path_for_txt(self.txt_save_path)

            all_words = []
            for b in sorted(self.processed_blocks, key=lambda x: x.start_sec):
                if hasattr(b, "words") and b.words:
                    all_words.extend(b.words)

            session = TranscriptionSession.load_from_json(json_path) or TranscriptionSession()
            session.has_transcription = True
            session.whisper_model = self.model_size
            session.duration_sec = self.total_processed_seconds
            session.turns = turns or []
            session.words = all_words
            session.save_to_json(json_path)
        except Exception:
            pass
