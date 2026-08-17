import sys
import queue
import collections
from datetime import datetime
import numpy as np
import sounddevice as sd

try:
    from PySide6.QtCore import QThread, Signal as pyqtSignal
except ImportError:
    from PyQt6.QtCore import QThread, pyqtSignal

from recorder.config import (
    SmartRecordState,
    SAMPLE_RATE,
    AUDIO_CHANNELS,
    DEFAULT_AUTO_PAUSE_SEC,
    VAD_SPEECH_THRESHOLD,
    PRE_SPEECH_BUFFER_CHUNKS,
    RMS_SILENCE_THRESHOLD,
    DEFAULT_WHISPER_MODEL
)
from recorder.audio.capture import save_wav_file
from recorder.audio.converter import resample_to_16k
from recorder.core.vad import SileroVADDetector, is_silero_available
from recorder.core.transcriber import TranscriberEngine
from recorder.core.diarizer import DiarizationEngine, format_transcript_without_diarization



class SmartAudioWorker(QThread):
    """
    Wątek przechwytywania dźwięku w czasie rzeczywistym z detekcją Silero VAD i buforowaniem.
    """
    audio_level_signal = pyqtSignal(float)             # Poziom RMS (0 - 100)
    vad_info_signal = pyqtSignal(bool, float, float)    # (is_speech, speech_prob, silence_sec)
    state_changed_signal = pyqtSignal(int)             # SmartRecordState
    phrase_signal = pyqtSignal(np.ndarray, int)        # Frazy audio dla transkrypcji na żywo
    error_signal = pyqtSignal(str)

    def __init__(self, samplerate=SAMPLE_RATE, channels=AUDIO_CHANNELS, device_index=None, auto_pause_sec=DEFAULT_AUTO_PAUSE_SEC):
        super().__init__()
        self.samplerate = samplerate
        self.channels = channels
        self.device_index = device_index
        self.auto_pause_sec = auto_pause_sec

        self.vad_detector = SileroVADDetector(speech_threshold=VAD_SPEECH_THRESHOLD, default_samplerate=self.samplerate)
        self.state = SmartRecordState.STOPPED
        self.frames = []
        self.silence_samples_count = 0
        self._is_running = False

        # Buforowanie fraz mowy z pre-bufferingiem (0.2s pre-padding)
        self.current_phrase_chunks = []
        self.pre_speech_buffer = collections.deque(maxlen=PRE_SPEECH_BUFFER_CHUNKS)
        self.silence_in_phrase_samples = 0
        self.phrase_speech_detected = False

    def set_auto_pause_sec(self, seconds: float):
        self.auto_pause_sec = float(seconds)

    def start_recording(self, device_index=None):
        self.device_index = device_index
        self.frames = []
        self.silence_samples_count = 0
        self.current_phrase_chunks = []
        self.pre_speech_buffer.clear()
        self.silence_in_phrase_samples = 0
        self.phrase_speech_detected = False
        self.state = SmartRecordState.RECORDING_SPEECH
        self._is_running = True
        self.state_changed_signal.emit(self.state)
        self.start()

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
        if self.phrase_speech_detected and self.current_phrase_chunks:
            phrase_arr = np.concatenate(self.current_phrase_chunks)
            if len(phrase_arr) >= int(0.3 * self.samplerate):
                self.phrase_signal.emit(phrase_arr, self.samplerate)
            self.current_phrase_chunks = []
            self.phrase_speech_detected = False
        self.state_changed_signal.emit(self.state)

    def run(self):
        def audio_callback(indata, frames_count, time_info, status):
            if status and sys.stderr:
                print(f"Status audio: {status}", file=sys.stderr)

            if not self._is_running or self.state == SmartRecordState.STOPPED:
                return

            # 1. Poziom głośności RMS
            norm_factor = np.linalg.norm(indata)
            rms = (norm_factor / np.sqrt(len(indata))) * 100
            level = min(100.0, float(rms * 6.0))
            self.audio_level_signal.emit(level)

            # 2. VAD AI (Silero VAD na próbkach 16kHz)
            is_speech, speech_prob = self.vad_detector.process_chunk(indata, samplerate=self.samplerate, rms_level=level)

            # 3. Logika Auto-Pause & Auto-Resume
            if self.state != SmartRecordState.MANUAL_PAUSED:
                if is_speech:
                    if self.state in [SmartRecordState.AUTO_PAUSED, SmartRecordState.RECORDING_SILENCE_COUNTDOWN]:
                        self.state = SmartRecordState.RECORDING_SPEECH
                        self.state_changed_signal.emit(self.state)
                    self.silence_samples_count = 0
                else:
                    self.silence_samples_count += len(indata)
                    silence_sec = self.silence_samples_count / self.samplerate

                    if self.state in [SmartRecordState.RECORDING_SPEECH, SmartRecordState.RECORDING_SILENCE_COUNTDOWN]:
                        if silence_sec < self.auto_pause_sec:
                            if self.state != SmartRecordState.RECORDING_SILENCE_COUNTDOWN:
                                self.state = SmartRecordState.RECORDING_SILENCE_COUNTDOWN
                                self.state_changed_signal.emit(self.state)
                        else:
                            self.state = SmartRecordState.AUTO_PAUSED
                            self.state_changed_signal.emit(self.state)

                            frames_to_remove = int((self.auto_pause_sec * self.samplerate) / len(indata))
                            if len(self.frames) > frames_to_remove:
                                self.frames = self.frames[:-frames_to_remove]

            current_silence_sec = self.silence_samples_count / self.samplerate
            self.vad_info_signal.emit(is_speech, speech_prob, current_silence_sec)

            # 4. Zapis próbek oraz buforowanie fraz mowy na żywo (z 0.2s pre-bufferingiem)
            if self.state in [SmartRecordState.RECORDING_SPEECH, SmartRecordState.RECORDING_SILENCE_COUNTDOWN]:
                if indata.dtype != np.int16:
                    audio_int16 = (indata * 32767).clip(-32768, 32767).astype(np.int16)
                    self.frames.append(audio_int16.tobytes())
                else:
                    self.frames.append(indata.tobytes())

                chunk_flat = indata.copy().flatten()
                if is_speech:
                    if not self.phrase_speech_detected:
                        # Dołącz pre-buffer (poprzednie ~0.2s), aby nie ucinać pierwszych fonemów
                        self.current_phrase_chunks.extend(list(self.pre_speech_buffer))
                        self.phrase_speech_detected = True

                    self.current_phrase_chunks.append(chunk_flat)
                    self.silence_in_phrase_samples = 0

                    # Jeśli ciągła mowa trwa ponad 3.0 sekundy, wyślij wyciętą frazę
                    total_samples = sum(len(c) for c in self.current_phrase_chunks)
                    if total_samples >= int(3.0 * self.samplerate):
                        phrase_arr = np.concatenate(self.current_phrase_chunks)
                        self.phrase_signal.emit(phrase_arr, self.samplerate)
                        self.current_phrase_chunks = []
                        self.phrase_speech_detected = False
                else:
                    self.pre_speech_buffer.append(chunk_flat)

                    if self.phrase_speech_detected and self.current_phrase_chunks:
                        self.silence_in_phrase_samples += len(indata)
                        silence_dur = self.silence_in_phrase_samples / self.samplerate
                        if silence_dur >= 0.4:  # 0.4s ciszy po wypowiedzi = koniec frazy
                            phrase_arr = np.concatenate(self.current_phrase_chunks)
                            if len(phrase_arr) >= int(0.3 * self.samplerate):
                                self.phrase_signal.emit(phrase_arr, self.samplerate)
                            self.current_phrase_chunks = []
                            self.phrase_speech_detected = False
                            self.silence_in_phrase_samples = 0

        try:
            self.samplerate = 16000
            with sd.InputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                dtype='float32',
                device=self.device_index,
                callback=audio_callback,
                blocksize=512
            ):
                while self._is_running:
                    self.msleep(40)
        except Exception as e:
            self.error_signal.emit(f"Błąd otwarcia strumienia audio:\n{str(e)}")
            self.state = SmartRecordState.STOPPED
            self.state_changed_signal.emit(self.state)

    def save_wav(self, file_path: str) -> bool:
        return save_wav_file(file_path, self.frames, channels=self.channels, samplerate=self.samplerate)


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

    def add_phrase_chunk(self, audio_data, samplerate):
        if self._is_running:
            self.audio_queue.put((audio_data, samplerate))

    def stop(self):
        self._is_running = False
        self.audio_queue.put(None)

    def run(self):
        self._is_running = True
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

                audio_data, samplerate = item
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

                # 4. Transkrypcja frazy
                phrase_text = self.transcriber.transcribe_live_chunk(audio_float, language="pl")
                if phrase_text:
                    time_str = datetime.now().strftime("%H:%M:%S")
                    self.phrase_transcribed_signal.emit(time_str, phrase_text)

                self.audio_queue.task_done()

        except Exception as e:
            self.error_signal.emit(f"Błąd transkrypcji na żywo: {e}")


class TranscriptionWorker(QThread):
    """
    Wątek wykonujący pełną transkrypcję z opcjonalną diaryzacją mówców (PyAnnote).
    """
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(str, str, list)  # (html_text, plain_text, turns)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        audio_path: str,
        hf_token: str,
        model_size: str = DEFAULT_WHISPER_MODEL,
        enable_diarization: bool = True,
        num_speakers: int = None
    ):
        super().__init__()
        self.audio_path = audio_path
        self.hf_token = hf_token
        self.model_size = model_size
        self.enable_diarization = enable_diarization
        self.num_speakers = num_speakers

    def run(self):
        try:
            self.progress_signal.emit(10, f"Ładowanie modelu Whisper ({self.model_size})...")
            transcriber = TranscriberEngine(model_size=self.model_size)
            
            self.progress_signal.emit(30, "Trwa transkrypcja audio...")
            transcript_words = transcriber.transcribe_file_with_words(self.audio_path, language="pl")

            if not transcript_words:
                self.finished_signal.emit("Brak wykrytej mowy w nagraniu.", "Brak wykrytej mowy w nagraniu.", [])
                return

            # Jeśli wyłączono diaryzację lub brak tokena HuggingFace
            if not self.enable_diarization or not self.hf_token:
                self.progress_signal.emit(90, "Formatowanie transkrypcji...")
                final_html, final_plain, turns = format_transcript_without_diarization(transcript_words)
                self.progress_signal.emit(100, "Gotowe!")
                self.finished_signal.emit(final_html, final_plain, turns)
                return

            # Pełna diaryzacja mówców (PyAnnote)
            speaker_info = f" ({self.num_speakers} os.)" if self.num_speakers else ""
            self.progress_signal.emit(60, f"Ładowanie modelu PyAnnote{speaker_info}...")
            diarizer = DiarizationEngine(hf_token=self.hf_token)

            self.progress_signal.emit(75, f"Analiza głosów mówców{speaker_info}...")
            final_html, final_plain, turns = diarizer.process(
                self.audio_path,
                transcript_words,
                num_speakers=self.num_speakers
            )

            self.progress_signal.emit(100, "Gotowe!")
            self.finished_signal.emit(final_html, final_plain, turns)

        except Exception as e:
            self.error_signal.emit(str(e))


class FileProcessingWorker(QThread):
    """
    Wątek asynchroniczny przetwarzający wgrany z dysku plik audio lub wideo (np. .mp4 ze spotkania):
    1. Normalizacja do formatu WAV 16kHz mono (za pomocą wbudowanego imageio-ffmpeg)
    2. Transkrypcja Faster-Whisper ze wskaźnikiem postępu w locie
    3. Diaryzacja mówców PyAnnote (z batch_size=32 dla długich plików 1-2h)
    """
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(str, str, str, list)  # (html_text, plain_text, prepared_wav_path, turns)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        input_file_path: str,
        recordings_dir: str,
        hf_token: Optional[str] = None,
        model_size: str = DEFAULT_WHISPER_MODEL,
        enable_diarization: bool = True,
        num_speakers: Optional[int] = None
    ):
        super().__init__()
        self.input_file_path = input_file_path
        self.recordings_dir = recordings_dir
        self.hf_token = hf_token
        self.model_size = model_size
        self.enable_diarization = enable_diarization
        self.num_speakers = num_speakers

    def run(self):
        try:
            from recorder.audio.converter import prepare_audio_file

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
                language="pl"
            )

            if not transcript_words:
                msg = "Nie wykryto zrozumiałej mowy w przesłanym pliku audio."
                print("⚠️ [PLIK] Nie wykryto słów w pliku audio.")
                self.finished_signal.emit(msg, msg, prepared_wav_path, [])
                return

            # ETAP 3: Diaryzacja PyAnnote lub czysta transkrypcja Whisper
            if self.enable_diarization and self.hf_token and self.hf_token.strip():
                spk_info = f" ({self.num_speakers} os.)" if self.num_speakers else ""
                self.progress_signal.emit(65, f"Etap 3/3: Ładowanie modelu PyAnnote{spk_info}...")
                diarizer = DiarizationEngine(hf_token=self.hf_token.strip())

                self.progress_signal.emit(75, f"Etap 3/3: Rozpoznawanie osób i łączenie z tekstem{spk_info}...")
                final_html, final_plain, turns = diarizer.process(
                    prepared_wav_path,
                    transcript_words,
                    num_speakers=self.num_speakers,
                    batch_size=32
                )
            else:
                self.progress_signal.emit(85, "Formatowanie transkrypcji...")
                final_html, final_plain, turns = format_transcript_without_diarization(transcript_words)

            print("="*70)
            print(f"🎉 [PLIK] Sukces! Przetwarzanie zakończone: {os.path.basename(prepared_wav_path)}")
            print("="*70 + "\n")

            self.progress_signal.emit(100, "Przetwarzanie zakończone pomyślnie!")
            self.finished_signal.emit(final_html, final_plain, prepared_wav_path, turns)

        except Exception as e:
            print(f"❌ [BŁĄD PRZETWARZANIA]: {e}", file=sys.stderr)
            self.error_signal.emit(str(e))


