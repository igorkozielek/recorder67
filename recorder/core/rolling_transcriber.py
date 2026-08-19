import os
import sys
import queue
import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime
from PySide6.QtCore import QThread, Signal as pyqtSignal

from recorder.core.transcriber import TranscriberEngine
from recorder.core.diarizer import format_transcript_without_diarization
from recorder.core.speakers import format_turns, suggest_speaker_names
from recorder.config import DEFAULT_WHISPER_MODEL


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
        if audio_data is None or len(audio_data) < int(0.5 * 16000):
            block.is_processed = True
            self.processed_blocks.append(block)
            return

        # Dźwięk w formacie float32 mono 16kHz
        if audio_data.dtype == np.int16:
            audio_float = audio_data.astype(np.float32) / 32768.0
        else:
            audio_float = audio_data.astype(np.float32)

        # Transkrypcja bloku z word-level timestamps
        segments, _ = self.transcriber._model.transcribe(
            audio_float,
            word_timestamps=True,
            language="pl",
            beam_size=1,
            vad_filter=False,
            initial_prompt="CRM, Helpdesk, Subiekt, synchronizacja, harmonogram, rejestr zmian, zgłoszenia, zamówienia."
        )

        transcript_words = []
        for segment in segments:
            seg_text = segment.text.strip() if segment.text else ""
            if not seg_text:
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

        # Formatowanie słów tego bloku do turnów
        if transcript_words:
            _, _, block_turns = format_transcript_without_diarization(transcript_words)
            block.turns = block_turns

        block.is_processed = True
        self.processed_blocks.append(block)
        self.total_processed_seconds = max(self.total_processed_seconds, block.end_sec)

        # Scalanie całościowej transkrypcji
        full_html, full_plain, all_turns = self._compile_full_transcript()
        self.all_turns = all_turns

        # Zapis do pliku TXT w czasie rzeczywistym
        self._save_to_txt_file(full_plain)

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
