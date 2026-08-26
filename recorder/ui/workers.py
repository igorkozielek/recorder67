import os
import sys
import queue
import collections
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
import sounddevice as sd

from PySide6.QtCore import QThread, Signal as pyqtSignal

from recorder.config import (
    SmartRecordState,
    SAMPLE_RATE,
    AUDIO_CHANNELS,
    DEFAULT_AUTO_PAUSE_SEC,
    VAD_SPEECH_THRESHOLD,
    PRE_SPEECH_BUFFER_CHUNKS,
    RMS_SILENCE_THRESHOLD,
    DEFAULT_WHISPER_MODEL,
    SESSION_SPLIT_SILENCE_SEC,
    LIVE_BLOCK_MIN_SEC,
    LIVE_BLOCK_MAX_SEC,
    LIVE_BLOCK_SILENCE_CUT_SEC
)
from recorder.audio.capture import save_wav_file, StreamingWavWriter
from recorder.audio.converter import resample_to_16k, prepare_audio_file
from recorder.core.vad import SileroVADDetector, is_silero_available
from recorder.core.transcriber import TranscriberEngine
from recorder.core.diarizer import DiarizationEngine, format_transcript_without_diarization


class SmartAudioWorker(QThread):
    """
    Wątek przechwytywania dźwięku w czasie rzeczywistym z detekcją Silero VAD i buforowaniem.
    Obsługuje natywne próbkowanie urządzeń WASAPI / DirectSound / MME, zapobiega błędom NaN
    oraz wspiera ciągłe 8-godzinne nagrywanie ze strumieniowym zapisem na dysk i podziałem sesji.
    """
    audio_level_signal = pyqtSignal(float)             # Poziom RMS (0 - 100)
    vad_info_signal = pyqtSignal(bool, float, float)    # (is_speech, speech_prob, silence_sec)
    state_changed_signal = pyqtSignal(int)             # SmartRecordState
    phrase_signal = pyqtSignal(np.ndarray, int, float)        # Frazy audio dla transkrypcji na żywo (16kHz, samplerate, start_sec)
    rolling_block_ready_signal = pyqtSignal(int, float, float, np.ndarray)  # (block_idx, start_sec, end_sec, audio_data)
    session_split_signal = pyqtSignal(str)             # Sygnał podziału na nową sesję spotkania (powód)
    error_signal = pyqtSignal(str)

    # Parametry okna bezpiecznego cięcia w tle (Safe VAD Boundary Handoff)
    MIN_BLOCK_DURATION_SEC = LIVE_BLOCK_MIN_SEC          # Szybki podgląd po min. 15s mowy
    SAFE_SILENCE_CUT_THRESHOLD_SEC = LIVE_BLOCK_SILENCE_CUT_SEC   # Wymagane min. 1.0s ciszy potwierdzonej przez Silero VAD
    MAX_BLOCK_DURATION_SEC = LIVE_BLOCK_MAX_SEC          # Maksymalny czas bloku 45 sekund
    OVERLAP_SAMPLES = int(0.5 * 16000)      # 0.5s nakładki akustycznej na styku

    def __init__(self, samplerate=SAMPLE_RATE, channels=AUDIO_CHANNELS, device_index=None, auto_pause_sec=DEFAULT_AUTO_PAUSE_SEC):
        super().__init__()
        self.target_samplerate = 16000
        self.actual_samplerate = samplerate or 16000
        self.samplerate = 16000
        self.channels = channels
        self.device_index = device_index
        self.auto_pause_sec = auto_pause_sec
        self.session_split_silence_sec = SESSION_SPLIT_SILENCE_SEC

        self.vad_detector = SileroVADDetector(speech_threshold=VAD_SPEECH_THRESHOLD, default_samplerate=16000)
        self.state = SmartRecordState.STOPPED
        self.frames = []
        self.silence_samples_count = 0
        self.continuous_silence_samples = 0
        self.session_has_speech = False
        self.wav_writer: Optional[StreamingWavWriter] = None
        self._is_running = False

        # Buforowanie fraz mowy z pre-bufferingiem (0.45s pre-padding)
        self.current_phrase_chunks = []
        self.pre_speech_buffer = collections.deque(maxlen=PRE_SPEECH_BUFFER_CHUNKS)
        self.silence_in_phrase_samples = 0
        self.phrase_speech_detected = False

        # Asynchroniczne bloki w tle (Rolling Blocks)
        self.block_index = 1
        self.block_start_samples = 0
        self.current_block_chunks = []
        self.last_block_tail = None

    def set_auto_pause_sec(self, seconds: float):
        try:
            self.auto_pause_sec = float(seconds)
        except (ValueError, TypeError):
            self.auto_pause_sec = 5.0

    def set_session_split_silence_sec(self, seconds: float):
        try:
            self.session_split_silence_sec = float(seconds)
        except (ValueError, TypeError):
            self.session_split_silence_sec = SESSION_SPLIT_SILENCE_SEC

    def start_recording(self, device_index=None, save_wav_path: Optional[str] = None):
        self.device_index = device_index
        self.frames = []
        self.silence_samples_count = 0
        self.continuous_silence_samples = 0
        self.session_has_speech = False
        self.current_phrase_chunks = []
        self.pre_speech_buffer.clear()
        self.silence_in_phrase_samples = 0
        self.phrase_speech_detected = False

        self.block_index = 1
        self.block_start_samples = 0
        self.current_block_chunks = []
        self.last_block_tail = None

        if save_wav_path:
            self.wav_writer = StreamingWavWriter(save_wav_path, channels=1, samplerate=16000)

        self.state = SmartRecordState.RECORDING_SPEECH
        self._is_running = True
        self.state_changed_signal.emit(self.state)
        self.start()

    def rotate_session_file(self, new_wav_path: str):
        """
        Zamyka bieżący plik sesji i natychmiast otwiera nowy plik WAV na dysku
        bez przerywania ciągłego nasłuchu mikrofonu.
        """
        if self.wav_writer:
            self.wav_writer.close()
            self.wav_writer = None

        self.frames = []
        self.block_index = 1
        self.block_start_samples = 0
        self.current_block_chunks = []
        self.continuous_silence_samples = 0
        self.session_has_speech = False

        if new_wav_path:
            self.wav_writer = StreamingWavWriter(new_wav_path, channels=1, samplerate=16000)

    def get_remaining_block(self) -> Optional[tuple]:
        """Zwraca ostatni, nieprzetworzony jeszcze blok nagrania po kliknięciu Stop."""
        if not self.current_block_chunks:
            return None
        try:
            block_arr = np.concatenate(self.current_block_chunks)
            if len(block_arr) < int(0.3 * 16000):
                return None
            start_sec = round(self.block_start_samples / 16000.0, 2)
            end_sec = round((self.block_start_samples + len(block_arr)) / 16000.0, 2)
            idx = self.block_index
            self.current_block_chunks = []
            return (idx, start_sec, end_sec, block_arr)
        except Exception:
            return None

    def toggle_manual_pause(self):
        if self.state in [SmartRecordState.RECORDING_SPEECH, SmartRecordState.RECORDING_SILENCE_COUNTDOWN, SmartRecordState.AUTO_PAUSED]:
            self.state = SmartRecordState.MANUAL_PAUSED
            self.state_changed_signal.emit(self.state)
        elif self.state == SmartRecordState.MANUAL_PAUSED:
            self.state = SmartRecordState.RECORDING_SPEECH
            self.silence_samples_count = 0
            self.state_changed_signal.emit(self.state)

    def stop_recording(self):
        self.state = SmartRecordState.STOPPED
        self._is_running = False
        if self.wav_writer:
            self.wav_writer.close()
            self.wav_writer = None
        if self.phrase_speech_detected and self.current_phrase_chunks:
            try:
                phrase_arr = np.concatenate(self.current_phrase_chunks)
                if len(phrase_arr) >= int(0.3 * self.target_samplerate):
                    self.phrase_signal.emit(phrase_arr, self.target_samplerate)
            except Exception:
                pass
            self.current_phrase_chunks = []
            self.phrase_speech_detected = False
        self.state_changed_signal.emit(self.state)

    def run(self):
        actual_sr = self.target_samplerate

        # Próba odpytania urządzenia o jego domyślny / natywny samplerate
        if self.device_index is not None:
            try:
                dev_info = sd.query_devices(self.device_index)
                dev_sr = int(dev_info.get('default_samplerate', 16000))
                if dev_sr > 0:
                    actual_sr = dev_sr
            except Exception:
                actual_sr = 16000

        self.actual_samplerate = actual_sr

        def audio_callback(indata, frames_count, time_info, status):
            if not self._is_running or self.state == SmartRecordState.STOPPED:
                return

            if indata is None or len(indata) == 0:
                return

            # Bezpieczne czyszczenie NaN / Inf
            if np.isnan(indata).any() or np.isinf(indata).any():
                indata = np.nan_to_num(indata, nan=0.0, posinf=1.0, neginf=-1.0)

            # Pobranie kanału mono
            if indata.ndim > 1:
                chunk_mono = np.mean(indata, axis=1).astype(np.float32)
            else:
                chunk_mono = indata.astype(np.float32).flatten()

            # Resampling do 16kHz jeśli wejście miało np. 44.1k/48k WASAPI
            if actual_sr != 16000 and len(chunk_mono) > 0:
                chunk_16k = resample_to_16k(chunk_mono, actual_sr)
            else:
                chunk_16k = chunk_mono

            if len(chunk_16k) == 0:
                return

            chunk_flat = chunk_16k.copy().flatten()

            # 1. Poziom głośności RMS z zabezpieczeniem NaN
            norm_factor = float(np.linalg.norm(chunk_16k))
            if np.isnan(norm_factor) or np.isinf(norm_factor):
                norm_factor = 0.0
            rms = (norm_factor / np.sqrt(len(chunk_16k))) * 100.0 if len(chunk_16k) > 0 else 0.0
            if np.isnan(rms) or np.isinf(rms):
                rms = 0.0
            level = float(min(100.0, max(0.0, rms * 6.0)))
            self.audio_level_signal.emit(level)

            # 2. VAD AI (Silero VAD na próbkach 16kHz)
            is_speech, speech_prob = self.vad_detector.process_chunk(chunk_16k, samplerate=16000, rms_level=level)

            # 3. Stan VAD i liczenie ciszy
            if self.state != SmartRecordState.MANUAL_PAUSED:
                if is_speech:
                    if self.state in [SmartRecordState.AUTO_PAUSED, SmartRecordState.RECORDING_SILENCE_COUNTDOWN]:
                        self.state = SmartRecordState.RECORDING_SPEECH
                        self.state_changed_signal.emit(self.state)
                    self.silence_samples_count = 0
                    self.continuous_silence_samples = 0
                    self.session_has_speech = True
                else:
                    self.silence_samples_count += len(chunk_16k)
                    self.continuous_silence_samples += len(chunk_16k)
                    silence_sec = self.silence_samples_count / 16000.0

                    # Smart Session Splitting: Jeśli w biurze była mowa, a teraz panuje długa cisza (np. > 15 min),
                    # emitujemy sygnał automatycznego podziału na nową sesję
                    cont_silence_sec = self.continuous_silence_samples / 16000.0
                    if self.session_has_speech and cont_silence_sec >= self.session_split_silence_sec:
                        self.session_has_speech = False
                        self.continuous_silence_samples = 0
                        mins = int(self.session_split_silence_sec // 60)
                        self.session_split_signal.emit(f"Cisza w biurze > {mins} min")

                    if silence_sec < self.auto_pause_sec:
                        if self.state != SmartRecordState.RECORDING_SILENCE_COUNTDOWN:
                            self.state = SmartRecordState.RECORDING_SILENCE_COUNTDOWN
                            self.state_changed_signal.emit(self.state)
                    else:
                        if self.state != SmartRecordState.AUTO_PAUSED:
                            self.state = SmartRecordState.AUTO_PAUSED
                            self.state_changed_signal.emit(self.state)

            current_silence_sec = self.silence_samples_count / 16000.0
            self.vad_info_signal.emit(is_speech, speech_prob, current_silence_sec)

            # 4. Zapis próbek mowy 16kHz do pliku oraz buforowanie bloków
            if self.state in [SmartRecordState.RECORDING_SPEECH, SmartRecordState.RECORDING_SILENCE_COUNTDOWN]:
                audio_int16 = (chunk_16k * 32767).clip(-32768, 32767).astype(np.int16)
                raw_bytes = audio_int16.tobytes()
                self.frames.append(raw_bytes)
                if self.wav_writer:
                    self.wav_writer.write_frames(raw_bytes)
                self.current_block_chunks.append(chunk_flat)

            # Sprawdzenie warunku bezpiecznego podziału na bloki w pełnej ciszy (VAD Silence Handoff)
            if self.current_block_chunks and self.state != SmartRecordState.MANUAL_PAUSED and self.state != SmartRecordState.STOPPED:
                current_block_len = sum(len(c) for c in self.current_block_chunks)
                current_block_dur = current_block_len / 16000.0
                silence_dur = self.silence_samples_count / 16000.0

                is_ready_for_cut = (
                    (current_block_dur >= self.MIN_BLOCK_DURATION_SEC and silence_dur >= self.SAFE_SILENCE_CUT_THRESHOLD_SEC) or
                    (current_block_dur >= self.MAX_BLOCK_DURATION_SEC and silence_dur >= 0.6) or
                    (current_block_dur >= 3.0 and self.state == SmartRecordState.AUTO_PAUSED)
                )

                if is_ready_for_cut:
                    block_arr = np.concatenate(self.current_block_chunks)
                    start_sec = round(self.block_start_samples / 16000.0, 2)
                    end_sec = round((self.block_start_samples + len(block_arr)) / 16000.0, 2)
                    idx = self.block_index

                    self.rolling_block_ready_signal.emit(idx, start_sec, end_sec, block_arr)
                    self.block_start_samples += len(block_arr)
                    self.block_index += 1
                    self.current_block_chunks = []

                if is_speech:
                    if not self.phrase_speech_detected:
                        self.current_phrase_chunks.extend(list(self.pre_speech_buffer))
                        self.phrase_speech_detected = True

                    self.current_phrase_chunks.append(chunk_flat)
                    self.silence_in_phrase_samples = 0

                    total_samples = sum(len(c) for c in self.current_phrase_chunks)
                    # Jeśli mówca mówi bardzo długo bez żadnej pauzy (> 8.0s), wysyłamy bezpiecznie
                    if total_samples >= int(8.0 * 16000):
                        phrase_arr = np.concatenate(self.current_phrase_chunks)
                        tot_bytes = sum(len(f) for f in self.frames)
                        curr_audio_sec = tot_bytes / (16000.0 * 2) if tot_bytes > 0 else 0.0
                        phrase_start_sec = max(0.0, curr_audio_sec - (len(phrase_arr) / 16000.0))
                        self.phrase_signal.emit(phrase_arr, 16000, phrase_start_sec)
                        self.current_phrase_chunks = []
                        self.phrase_speech_detected = False
                else:
                    self.pre_speech_buffer.append(chunk_flat)

                    if self.phrase_speech_detected and self.current_phrase_chunks:
                        self.silence_in_phrase_samples += len(chunk_16k)
                        silence_dur = self.silence_in_phrase_samples / 16000.0
                        total_samples = sum(len(c) for c in self.current_phrase_chunks)
                        phrase_dur = total_samples / 16000.0

                        # Naturalny koniec zdania:
                        # 1. Pauza >= 0.5s i fraza ma co najmniej 1.0s mowy
                        # 2. Lub fraza trwała już > 4.5s i wystąpiła pauza >= 0.3s
                        is_sentence_boundary = (silence_dur >= 0.5 and phrase_dur >= 1.0)
                        is_long_phrase_break = (silence_dur >= 0.3 and phrase_dur >= 4.5)

                        if is_sentence_boundary or is_long_phrase_break:
                            phrase_arr = np.concatenate(self.current_phrase_chunks)
                            if len(phrase_arr) >= int(0.6 * 16000):
                                tot_bytes = sum(len(f) for f in self.frames)
                                curr_audio_sec = tot_bytes / (16000.0 * 2) if tot_bytes > 0 else 0.0
                                phrase_start_sec = max(0.0, curr_audio_sec - (len(phrase_arr) / 16000.0))
                                self.phrase_signal.emit(phrase_arr, 16000, phrase_start_sec)
                            self.current_phrase_chunks = []
                            self.phrase_speech_detected = False
                            self.silence_in_phrase_samples = 0

        # Otwarcie strumienia: najpierw próbujemy 16000, a jeśli sterownik (np. WASAPI) wymaga natywnego SR, otwieramy z actual_sr
        stream_opened = False
        rates_to_try = [actual_sr] if actual_sr != 16000 else [16000, 48000, 44100]
        if 16000 not in rates_to_try:
            rates_to_try.append(16000)

        for sr_try in rates_to_try:
            try:
                actual_sr = sr_try
                with sd.InputStream(
                    samplerate=actual_sr,
                    channels=self.channels,
                    dtype='float32',
                    device=self.device_index,
                    callback=audio_callback,
                    blocksize=1024 if actual_sr > 16000 else 512
                ):
                    stream_opened = True
                    while self._is_running:
                        self.msleep(40)
                break
            except Exception:
                continue

        if not stream_opened and self._is_running:
            self.error_signal.emit(f"Nie udało się otworzyć mikrofonu (indeks: {self.device_index}). Upewnij się, że urządzenie nie jest zablokowane.")
            self.state = SmartRecordState.STOPPED
            self.state_changed_signal.emit(self.state)

    def save_wav(self, file_path: str) -> bool:
        if self.wav_writer:
            self.wav_writer.close()
            self.wav_writer = None
            self.frames = []
            if os.path.exists(file_path) and os.path.getsize(file_path) > 44:
                return True
        saved = save_wav_file(file_path, self.frames, channels=1, samplerate=16000)
        self.frames = []
        return saved



class LiveTranscriptionWorker(QThread):
    """
    Wątek przetwarzający frazy audio w czasie rzeczywistym przy użyciu faster-whisper.
    """
    phrase_transcribed_signal = pyqtSignal(str, str)  # (time_str, phrase_text)
    status_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, model_size=DEFAULT_WHISPER_MODEL):
        super().__init__()
        self.model_size = model_size
        self.audio_queue = queue.Queue()
        self._is_running = False
        self.transcriber = TranscriberEngine(model_size=self.model_size)

    def add_phrase_chunk(self, audio_data, samplerate, start_sec: float = 0.0):
        if self._is_running:
            self.audio_queue.put((audio_data, samplerate, start_sec))

    def stop(self):
        self._is_running = False
        # Opróżnij kolejkę, aby natychmiast przerwać przetwarzanie zaległych chunków
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.task_done()
            except Exception:
                break
        self.audio_queue.put(None)

    def run(self):
        self._is_running = True
        recent_context = ""
        try:
            self.status_signal.emit(f"Ładowanie modelu Whisper ({self.model_size})...")
            self.transcriber.load_model()
            self.status_signal.emit(f"Whisper Na Żywo [{self.model_size}]: GOTOWY")

            while self._is_running:
                try:
                    item = self.audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if item is None:
                    break

                audio_data, samplerate, start_sec = item
                if audio_data is None or len(audio_data) == 0:
                    self.audio_queue.task_done()
                    continue

                # 1. Konwersja do float32 [-1.0, 1.0]
                if audio_data.dtype == np.int16:
                    audio_float = audio_data.astype(np.float32) / 32768.0
                else:
                    audio_float = audio_data.astype(np.float32)

                # 2. Resampling do 16kHz
                if samplerate != 16000:
                    audio_float = resample_to_16k(audio_float, samplerate)

                # 3. Odfiltrowanie cichego szumu tła (RMS)
                rms = np.sqrt(np.mean(audio_float ** 2)) if len(audio_float) > 0 else 0.0
                if rms < RMS_SILENCE_THRESHOLD:
                    self.audio_queue.task_done()
                    continue

                # 4. Transkrypcja frazy z pamięcią kontekstu
                phrase_text = self.transcriber.transcribe_live_chunk(audio_float, language="pl", context_prompt=recent_context)
                if phrase_text:
                    recent_context = (recent_context + " " + phrase_text).strip()[-250:]
                    m, s = int(start_sec // 60), int(start_sec % 60)
                    time_str = f"{m:02d}:{s:02d}"
                    self.phrase_transcribed_signal.emit(time_str, phrase_text)

                self.audio_queue.task_done()

        except Exception as e:
            self.error_signal.emit(f"Błąd transkrypcji na żywo: {e}")


class TranscriptionWorker(QThread):
    """
    Wątek wykonujący pełną transkrypcję z opcjonalną diaryzacją mówców (PyAnnote).
    """
    progress_signal = pyqtSignal(int, str)
    preliminary_signal = pyqtSignal(str, str, list)  # Wstępna transkrypcja z Whispera przed diaryzacją
    finished_signal = pyqtSignal(str, str, list)     # (html_text, plain_text, turns)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        audio_path: str,
        hf_token: str,
        model_size: str = DEFAULT_WHISPER_MODEL,
        enable_diarization: bool = True,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None
    ):
        super().__init__()
        self.audio_path = audio_path
        self.hf_token = hf_token
        self.model_size = model_size
        self.enable_diarization = enable_diarization
        self.num_speakers = num_speakers
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers

    def run(self):
        try:
            self.progress_signal.emit(10, f"Ładowanie modelu Whisper ({self.model_size})...")
            transcriber = TranscriberEngine(model_size=self.model_size)
            
            self.progress_signal.emit(30, "Trwa transkrypcja audio...")
            transcript_words = transcriber.transcribe_file_with_words(self.audio_path, language="pl")

            if not transcript_words:
                self.finished_signal.emit("Brak wykrytej mowy w nagraniu.", "Brak wykrytej mowy w nagraniu.", [])
                return

            # Wstępne sformatowanie transkrypcji (gwarancja braku utraty danych)
            init_html, init_plain, init_turns = format_transcript_without_diarization(transcript_words)
            self.preliminary_signal.emit(init_html, init_plain, init_turns)

            # Jeśli wyłączono diaryzację lub brak tokena HuggingFace
            if not self.enable_diarization or not self.hf_token:
                self.progress_signal.emit(100, "Gotowe!")
                self.finished_signal.emit(init_html, init_plain, init_turns)
                return

            # Pełna diaryzacja mówców (PyAnnote)
            speaker_info = ""
            if self.num_speakers:
                speaker_info = f" (dokładnie {self.num_speakers} os.)"
            elif self.max_speakers:
                speaker_info = f" (max {self.max_speakers} os.)"

            self.progress_signal.emit(60, f"Ładowanie modelu PyAnnote{speaker_info}...")
            diarizer = DiarizationEngine(hf_token=self.hf_token)

            def on_diar_progress(pct: int, msg: str):
                self.progress_signal.emit(pct, msg)

            self.progress_signal.emit(65, f"Analiza głosów mówców{speaker_info}...")
            final_html, final_plain, turns = diarizer.process(
                self.audio_path,
                transcript_words,
                batch_size=32,
                num_speakers=self.num_speakers,
                min_speakers=self.min_speakers,
                max_speakers=self.max_speakers,
                progress_callback=on_diar_progress
            )

            self.progress_signal.emit(100, "Gotowe!")
            self.finished_signal.emit(final_html, final_plain, turns)

        except Exception as e:
            self.error_signal.emit(str(e))


class FileProcessingWorker(QThread):
    """
    Wątek asynchroniczny przetwarzający wgrany z dysku plik audio lub wideo (np. .mp4 ze spotkania):
    1. Normalizacja do formatu WAV 16kHz mono (za pomocą wbudowanego imageio-ffmpeg)
    2. Transkrypcja Faster-Whisper z wybranym modelem i wskaźnikiem postępu w locie + natychmiastowy autozapis TXT
    3. Opcjonalna diaryzacja mówców PyAnnote (batch_size=32, hook postępu w UI, automatyczna aktualizacja TXT)
    """
    progress_signal = pyqtSignal(int, str)
    preliminary_signal = pyqtSignal(str, str, str, list)  # (html_text, plain_text, prepared_wav_path, turns)
    finished_signal = pyqtSignal(str, str, str, list)     # (html_text, plain_text, prepared_wav_path, turns)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        input_file_path: str,
        recordings_dir: str,
        hf_token: Optional[str] = None,
        model_size: str = DEFAULT_WHISPER_MODEL,
        enable_diarization: bool = True,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None
    ):
        super().__init__()
        self.input_file_path = input_file_path
        self.recordings_dir = recordings_dir
        self.hf_token = hf_token
        self.model_size = model_size
        self.enable_diarization = enable_diarization
        self.num_speakers = num_speakers
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers

    def run(self):
        try:
            print("\n" + "="*70)
            print(f"📂 [PLIK] Rozpoczęto przetwarzanie pliku: {self.input_file_path}")
            print("="*70)

            # ETAP 1: Konwersja i normalizacja formatu audio
            self.progress_signal.emit(5, "Etap 1/3: Ekstrakcja i normalizacja dźwięku do 16kHz WAV...")
            prepared_wav_path, duration_sec = prepare_audio_file(self.input_file_path, self.recordings_dir)

            mins = int(duration_sec // 60)
            secs = int(duration_sec % 60)
            print(f"🎵 [PLIK] Audio przygotowane: {prepared_wav_path} (Długość: {mins}m {secs}s)")
            self.progress_signal.emit(15, f"Etap 1/3: Audio gotowe ({mins}m {secs}s). Ładowanie Whisper ({self.model_size})...")

            # ETAP 2: Transkrypcja Faster-Whisper z raportowaniem postępu
            transcriber = TranscriberEngine(model_size=self.model_size)

            def on_whisper_progress(ratio: float, cur_time_sec: float):
                pct = int(20 + ratio * 40)
                cur_mins = int(cur_time_sec // 60)
                cur_secs = int(cur_time_sec % 60)
                self.progress_signal.emit(
                    pct,
                    f"Etap 2/3: Transkrypcja Whisper ({cur_mins}m {cur_secs}s / {mins}m {secs}s - {int(ratio * 100)}%)..."
                )

            self.progress_signal.emit(20, "Etap 2/3: Rozpoczynanie transkrypcji mowy...")
            transcript_words = transcriber.transcribe_file_with_words(
                prepared_wav_path,
                language="pl",
                progress_callback=on_whisper_progress,
                duration_sec=duration_sec
            )

            if not transcript_words:
                msg = "Nie wykryto zrozumiałej mowy w przesłanym pliku audio."
                print("⚠️ [PLIK] Nie wykryto słów w pliku audio.")
                self.finished_signal.emit(msg, msg, prepared_wav_path, [])
                return

            # Wczesne sformatowanie i NATYCHMIASTOWY zapis wstępnego pliku TXT na dysk
            init_html, init_plain, init_turns = format_transcript_without_diarization(transcript_words)
            
            base_name = os.path.basename(prepared_wav_path)
            file_stem = os.path.splitext(base_name)[0]
            txt_dir = self.recordings_dir.replace("recordings", "transcriptions")
            os.makedirs(txt_dir, exist_ok=True)
            txt_path = os.path.join(txt_dir, f"transkrypcja_{file_stem}.txt")
            
            try:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(init_plain)
                print(f"💾 [AUTOZAPIS] Zapisano wstępną transkrypcję do: {txt_path}")
            except Exception as save_err:
                print(f"⚠️ [AUTOZAPIS] Błąd wstępnego zapisu TXT: {save_err}")

            # Wyemitowanie wstępnego tekstu do GUI (użytkownik już ma podgląd pełnego tekstu!)
            self.preliminary_signal.emit(init_html, init_plain, prepared_wav_path, init_turns)

            # ETAP 3: Diaryzacja PyAnnote lub zakończenie
            turns = []
            if self.enable_diarization and self.hf_token and self.hf_token.strip():
                speaker_info = ""
                if self.num_speakers:
                    speaker_info = f" (dokładnie {self.num_speakers} os.)"
                elif self.max_speakers:
                    speaker_info = f" (max {self.max_speakers} os.)"

                self.progress_signal.emit(60, f"Etap 3/3: Ładowanie modelu PyAnnote{speaker_info}...")
                diarizer = DiarizationEngine(hf_token=self.hf_token.strip())

                def on_diar_progress(pct: int, msg: str):
                    self.progress_signal.emit(pct, msg)

                self.progress_signal.emit(65, f"Etap 3/3: Rozpoznawanie osób i łączenie z tekstem{speaker_info}...")
                final_html, final_plain, turns = diarizer.process(
                    prepared_wav_path,
                    transcript_words,
                    batch_size=32,
                    num_speakers=self.num_speakers,
                    min_speakers=self.min_speakers,
                    max_speakers=self.max_speakers,
                    progress_callback=on_diar_progress
                )

                # Aktualizacja pliku TXT o przypisanych mówców
                try:
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(final_plain)
                    print(f"💾 [AUTOZAPIS] Zaktualizowano plik z mówcami: {txt_path}")
                except Exception as update_err:
                    print(f"⚠️ [AUTOZAPIS] Błąd aktualizacji TXT: {update_err}")

            else:
                final_html = init_html
                final_plain = init_plain
                turns = init_turns

            print("="*70)
            print(f"🎉 [PLIK] Sukces! Przetwarzanie zakończone: {os.path.basename(prepared_wav_path)}")
            print("="*70 + "\n")

            self.progress_signal.emit(100, "Przetwarzanie zakończone pomyślnie!")
            self.finished_signal.emit(final_html, final_plain, prepared_wav_path, turns)

        except Exception as e:
            print(f"❌ [BŁĄD PRZETWARZANIA]: {e}", file=sys.stderr)
            self.error_signal.emit(str(e))


class DiarizationOnlyWorker(QThread):
    """
    Dedykowany wątek do asynchronicznego uruchamiania diaryzacji PyAnnote na istniejącym pliku audio i sesji JSON.
    Nie uruchamia Whispera – wykorzystuje gotowe słowa z zapisanego pliku sesji!
    """
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(str, str, list, str)  # (final_html, final_plain, turns, session_path)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        audio_path: str,
        transcript_words: List[Dict[str, Any]],
        hf_token: str,
        session_json_path: Optional[str] = None,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None
    ):
        super().__init__()
        self.audio_path = audio_path
        self.transcript_words = transcript_words
        self.hf_token = hf_token
        self.session_json_path = session_json_path
        self.num_speakers = num_speakers
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers

    def run(self):
        try:
            if not os.path.exists(self.audio_path):
                self.error_signal.emit("Plik audio dla tej sesji nie istnieje na dysku.")
                return

            if not self.transcript_words:
                self.error_signal.emit("Brak słów transkrypcji w sesji. Najpierw wykonaj transkrypcję.")
                return

            self.progress_signal.emit(5, "Inicjalizacja modułu diaryzacji PyAnnote...")
            from recorder.core.diarizer import DiarizationEngine
            from recorder.core.session import TranscriptionSession, get_session_path_for_audio
            from recorder.config import TRANSCRIPTIONS_DIR

            speaker_info = ""
            if self.num_speakers:
                speaker_info = f" (dokładnie {self.num_speakers} os.)"
            elif self.min_speakers and self.max_speakers:
                speaker_info = f" ({self.min_speakers}-{self.max_speakers} os.)"
            elif self.max_speakers:
                speaker_info = f" (max {self.max_speakers} os.)"

            self.progress_signal.emit(15, f"Ładowanie modelu PyAnnote{speaker_info}...")
            diarizer = DiarizationEngine(hf_token=self.hf_token.strip())

            def on_diar_progress(pct: int, msg: str):
                self.progress_signal.emit(pct, msg)

            self.progress_signal.emit(30, f"Rozpoznawanie osób i łączenie z gotowym tekstem{speaker_info}...")
            final_html, final_plain, turns = diarizer.process(
                self.audio_path,
                self.transcript_words,
                batch_size=32,
                num_speakers=self.num_speakers,
                min_speakers=self.min_speakers,
                max_speakers=self.max_speakers,
                progress_callback=on_diar_progress
            )

            # Aktualizacja pliku sesji JSON
            json_path = self.session_json_path or get_session_path_for_audio(self.audio_path, TRANSCRIPTIONS_DIR)
            session = TranscriptionSession.load_from_json(json_path) if os.path.exists(json_path) else None
            if session:
                session.has_diarization = True
                session.turns = turns
                session.speakers_detected = sorted(list(set(t.get("speaker") for t in turns if t.get("speaker"))))
                session.save_to_json(json_path)

            self.progress_signal.emit(100, "Diaryzacja zakończona pomyślnie!")
            self.finished_signal.emit(final_html, final_plain, turns, json_path or "")

        except Exception as e:
            print(f"❌ [BŁĄD DIARYZACJI]: {e}", file=sys.stderr)
            self.error_signal.emit(str(e))

