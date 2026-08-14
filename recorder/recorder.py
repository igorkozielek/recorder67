import os
import sys
import time
import wave
import numpy as np
from datetime import datetime

import sounddevice as sd
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QFont, QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QProgressBar, QListWidget,
    QListWidgetItem, QFileDialog, QGroupBox, QMessageBox, QFrame,
    QSlider, QLineEdit, QTextEdit, QScrollArea
)

# Ładowanie Silero VAD z obsługą strumienia pamięci (BytesIO)
SILERO_AVAILABLE = False
silero_model = None

try:
    import torch
    import io
    import silero_vad
    jit_path = os.path.join(os.path.dirname(silero_vad.__file__), 'data', 'silero_vad.jit')
    if os.path.exists(jit_path):
        with open(jit_path, 'rb') as f:
            model_bytes = io.BytesIO(f.read())
            silero_model = torch.jit.load(model_bytes)
            silero_model.eval()
            SILERO_AVAILABLE = True
            print("Sukces: Model Silero VAD AI został pomyślnie załadowany do pamięci!")
    else:
        from silero_vad import load_silero_vad
        silero_model = load_silero_vad()
        SILERO_AVAILABLE = True
except Exception as e:
    print(f"Informacja VAD: {e}")

class SmartRecordState:
    STOPPED = 0
    RECORDING_SPEECH = 1
    RECORDING_SILENCE_COUNTDOWN = 2
    AUTO_PAUSED = 3
    MANUAL_PAUSED = 4

class TranscriptionWorker(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, audio_path, hf_token):
        super().__init__()
        self.audio_path = audio_path
        self.hf_token = hf_token

    def run(self):
        try:
            # 1. Zabezpieczenie zmiennych środowiskowych dla HuggingFace
            if self.hf_token:
                os.environ["HF_TOKEN"] = self.hf_token
                os.environ["HUGGING_FACE_HUB_TOKEN"] = self.hf_token

            self.progress_signal.emit(5, "Ładowanie modelu Whisper (Transkrypcja)...")
            from faster_whisper import WhisperModel
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute_type = "float16" if device == "cuda" else "default"

            model = WhisperModel("small", device=device, compute_type=compute_type)

            self.progress_signal.emit(20, "Trwa transkrypcja audio...")
            segments, info = model.transcribe(self.audio_path, word_timestamps=True, language="pl")

            transcript_words = []
            for segment in segments:
                if segment.words:
                    for word in segment.words:
                        if word.word and word.start is not None and word.end is not None:
                            transcript_words.append({
                                "word": word.word,
                                "start": word.start,
                                "end": word.end
                            })

            if not transcript_words:
                self.finished_signal.emit("Brak wykrytej mowy w nagraniu.")
                return

            self.progress_signal.emit(50, "Ładowanie modelu PyAnnote (Diaryzacja)...")

            # 2. Kompleksowe łatki dla torchaudio i PyTorch 2.6+
            import torchaudio
            if not hasattr(torchaudio, 'list_audio_backends'):
                torchaudio.list_audio_backends = lambda: ["soundfile", "sox"]
            if not hasattr(torchaudio, 'AudioMetaData'):
                class DummyAudioMetaData:
                    pass
                torchaudio.AudioMetaData = DummyAudioMetaData

            # Łatka na torchaudio.load (omijanie torchcodec i FFmpeg za pomocą soundfile)
            import soundfile as sf
            def _patched_torchaudio_load(filepath, frame_offset=0, num_frames=-1, **kwargs):
                start = frame_offset if frame_offset > 0 else 0
                stop = (start + num_frames) if num_frames > 0 else None
                wav, sr = sf.read(filepath, start=start, stop=stop, dtype='float32')
                wav_tensor = torch.from_numpy(wav)
                if wav_tensor.dim() == 1:
                    wav_tensor = wav_tensor.unsqueeze(0)
                else:
                    wav_tensor = wav_tensor.t()
                return wav_tensor, sr

            torchaudio.load = _patched_torchaudio_load

            # Łatka na torchaudio.info (pobieranie metadanych pliku przez soundfile)
            def _patched_torchaudio_info(filepath, **kwargs):
                sf_info = sf.info(filepath)
                class AudioInfo:
                    def __init__(self, s_info):
                        self.sample_rate = s_info.samplerate
                        self.num_frames = s_info.frames
                        self.num_channels = s_info.channels
                        self.bits_per_sample = 16
                        self.encoding = "PCM_S"
                return AudioInfo(sf_info)

            torchaudio.info = _patched_torchaudio_info

            # Łatka na PyTorch 2.6+ (wymuszenie weights_only=False niezależnie od przekazanych parametrów)
            import torch
            import torch.serialization
            _orig_load = torch.load
            def _patched_load(*args, **kwargs):
                kwargs['weights_only'] = False
                return _orig_load(*args, **kwargs)
            
            torch.load = _patched_load
            torch.serialization.load = _patched_load

            from pyannote.audio import Pipeline

            # Fallback dla różnych wersji PyAnnote / huggingface_hub
            pipeline = None
            try:
                pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=self.hf_token)
            except TypeError:
                try:
                    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=self.hf_token)
                except TypeError:
                    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")

            if pipeline is None:
                raise ValueError("Nie udało się załadować modelu PyAnnote. Sprawdź poprawność tokenu HuggingFace.")

            if torch.cuda.is_available():
                pipeline.to(torch.device("cuda"))

            self.progress_signal.emit(60, "Analiza głosów mówców (to potrwa chwilę)...")
            diarization = pipeline(self.audio_path)

            self.progress_signal.emit(90, "Scalanie tekstu i mówców...")

            final_text = ""
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                # Dopasowanie słów po punkcie środkowym (znacznie odporniejsze)
                words_in_turn = []
                for w in transcript_words:
                    mid_point = (w["start"] + w["end"]) / 2.0
                    if turn.start <= mid_point <= turn.end:
                        words_in_turn.append(w["word"])

                if words_in_turn:
                    sentence = "".join(words_in_turn).strip()
                    final_text += f"<b>[{turn.start:.1f}s - {turn.end:.1f}s] {speaker}:</b> {sentence}<br><br>"

            if not final_text:
                final_text = "Transkrypcja zakończona, ale nie udało się zmapować głosów do słów."

            self.progress_signal.emit(100, "Gotowe!")
            self.finished_signal.emit(final_text)

        except Exception as e:
            self.error_signal.emit(str(e))


def get_working_input_devices():
    """
    Pobiera listę pracujących urządzeń wejściowych, ignorując surowe WDM-KS
    powodujące błędy PortAudio w Windows.
    """
    valid_devices = []
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()

        for idx, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                hostapi_name = hostapis[dev['hostapi']]['name'] if dev['hostapi'] < len(hostapis) else ""
                # WDM-KS na Windows powoduje błąd "Blocking API not supported" w PortAudio
                if "WDM-KS" in hostapi_name:
                    continue

                valid_devices.append({
                    'index': idx,
                    'name': dev['name'],
                    'hostapi': hostapi_name,
                    'channels': dev['max_input_channels'],
                    'samplerate': int(dev['default_samplerate'])
                })
    except Exception as e:
        print(f"Błąd wykrywania urządzeń: {e}")

    return valid_devices


class SmartAudioWorker(QThread):
    """
    Silnik przechwytywania dźwięku w czasie rzeczywistym z detekcją VAD.
    """
    audio_level_signal = pyqtSignal(float)             # Poziom RMS (0 - 100)
    vad_info_signal = pyqtSignal(bool, float, float)    # (is_speech, speech_prob, silence_sec)
    state_changed_signal = pyqtSignal(int)             # SmartRecordState
    error_signal = pyqtSignal(str)

    def __init__(self, samplerate=16000, channels=1, device_index=None, auto_pause_sec=5.0):
        super().__init__()
        self.samplerate = samplerate
        self.channels = channels
        self.device_index = device_index
        self.auto_pause_sec = auto_pause_sec

        self.state = SmartRecordState.STOPPED
        self.frames = []
        self.silence_samples_count = 0
        self._is_running = False
        self.speech_threshold = 0.45

    def set_auto_pause_sec(self, seconds):
        self.auto_pause_sec = float(seconds)

    def start_recording(self, device_index=None):
        self.device_index = device_index
        self.frames = []
        self.silence_samples_count = 0
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

            # 2. VAD AI (Silero VAD)
            is_speech = False
            speech_prob = 0.0

            if SILERO_AVAILABLE and silero_model is not None:
                try:
                    tensor_data = torch.from_numpy(indata.flatten()).float()
                    speech_prob = silero_model(tensor_data, self.samplerate).item()
                    is_speech = speech_prob >= self.speech_threshold
                except Exception:
                    is_speech = level > 12.0
                    speech_prob = 1.0 if is_speech else 0.0
            else:
                is_speech = level > 12.0
                speech_prob = 1.0 if is_speech else 0.0

            # 3. Logika Auto-Pause & Auto-Resume
            if self.state != SmartRecordState.MANUAL_PAUSED:
                if is_speech:
                    if self.state == SmartRecordState.AUTO_PAUSED:
                        self.state = SmartRecordState.RECORDING_SPEECH
                        self.state_changed_signal.emit(self.state)
                    elif self.state == SmartRecordState.RECORDING_SILENCE_COUNTDOWN:
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

            # 4. Zapis próbek
            if self.state in [SmartRecordState.RECORDING_SPEECH, SmartRecordState.RECORDING_SILENCE_COUNTDOWN]:
                if indata.dtype != np.int16:
                    audio_int16 = (indata * 32767).clip(-32768, 32767).astype(np.int16)
                    self.frames.append(audio_int16.tobytes())
                else:
                    self.frames.append(indata.tobytes())

        try:
            # Ustalenie próbkowania zgodnego z wybranym urządzeniem
            target_sr = self.samplerate
            if self.device_index is not None:
                try:
                    dev_info = sd.query_devices(self.device_index)
                    native_sr = int(dev_info.get('default_samplerate', 16000))
                    if native_sr > 0:
                        target_sr = native_sr
                except Exception:
                    pass

            self.samplerate = target_sr

            with sd.InputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                dtype='float32',
                device=self.device_index,
                callback=audio_callback,
                blocksize=512 if self.samplerate == 16000 else 1024
            ):
                while self._is_running:
                    self.msleep(40)
        except Exception as e:
            self.error_signal.emit(f"Błąd otwarcia strumienia audio:\n{str(e)}")
            self.state = SmartRecordState.STOPPED
            self.state_changed_signal.emit(self.state)

    def save_wav(self, file_path):
        if not self.frames:
            return False
        try:
            with wave.open(file_path, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2) # 16-bit PCM
                wf.setframerate(self.samplerate)
                wf.writeframes(b''.join(self.frames))
            return True
        except Exception as e:
            if sys.stderr:
                print(f"Błąd zapisu pliku WAV: {e}", file=sys.stderr)
            return False


class SmartDictaphoneWindow(QMainWindow):
    """
    Główne okno Inteligentnego Dyktafonu AI.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inteligentny Dyktafon AI - Wykrywanie Mowy (VAD)")
        self.resize(750, 900)
        self.setMinimumSize(600, 700)

        self.recordings_dir = os.path.join(os.getcwd(), "recordings")
        os.makedirs(self.recordings_dir, exist_ok=True)

        self.recorded_seconds = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._on_timer_tick)

        self.worker = SmartAudioWorker(samplerate=16000, auto_pause_sec=5.0)
        self.worker.audio_level_signal.connect(self._update_audio_level)
        self.worker.vad_info_signal.connect(self._update_vad_info)
        self.worker.state_changed_signal.connect(self._on_worker_state_changed)
        self.worker.error_signal.connect(self._handle_audio_error)

        self._init_ui()
        self._apply_theme()
        self._refresh_audio_devices()
        self._refresh_recordings_list()

    def _init_ui(self):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(scroll_area)

        main_widget = QWidget()
        scroll_area.setWidget(main_widget)

        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(22, 22, 22, 22)

        # NAGŁÓWEK
        header_layout = QVBoxLayout()
        title = QLabel("🎙️ Inteligentny Dyktafon AI")
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        subtitle = QLabel("System oparty na WYKRYWANIU MOWY (Silero VAD AI)")
        subtitle.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        subtitle.setStyleSheet("color: #4cc9f0;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        main_layout.addLayout(header_layout)

        # WYBÓR MIKROFONU
        device_box = QGroupBox("Urządzenie Wejściowe (Mikrofon)")
        device_layout = QHBoxLayout(device_box)
        self.combo_devices = QComboBox()
        self.btn_refresh_dev = QPushButton("🔄")
        self.btn_refresh_dev.setFixedWidth(40)
        self.btn_refresh_dev.setToolTip("Odśwież listę mikrofonów")
        self.btn_refresh_dev.clicked.connect(self._refresh_audio_devices)

        device_layout.addWidget(self.combo_devices, stretch=1)
        device_layout.addWidget(self.btn_refresh_dev)
        main_layout.addWidget(device_box)

        # PANEL MONITORINGU
        display_frame = QFrame()
        display_frame.setObjectName("DisplayFrame")
        display_layout = QVBoxLayout(display_frame)
        display_layout.setContentsMargins(18, 18, 18, 18)

        self.lbl_status_badge = QLabel("ZATRZYMANY")
        self.lbl_status_badge.setObjectName("StatusStopped")
        self.lbl_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status_badge.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        display_layout.addWidget(self.lbl_status_badge, alignment=Qt.AlignmentFlag.AlignCenter)

        self.lbl_timer = QLabel("00:00:00")
        self.lbl_timer.setFont(QFont("Consolas", 36, QFont.Weight.Bold))
        self.lbl_timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_timer.setMinimumHeight(50)
        self.lbl_timer.setStyleSheet("color: #edf2f4; margin: 4px 0;")
        display_layout.addWidget(self.lbl_timer)

        silence_header_layout = QHBoxLayout()
        self.lbl_silence_title = QLabel("Brak mowy (Auto-Pauza przy 5.0 s):")
        self.lbl_silence_title.setFont(QFont("Segoe UI", 9))
        self.lbl_silence_val = QLabel("0.0 s / 5.0 s")
        self.lbl_silence_val.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.lbl_silence_val.setStyleSheet("color: #f59e0b;")

        silence_header_layout.addWidget(self.lbl_silence_title)
        silence_header_layout.addStretch()
        silence_header_layout.addWidget(self.lbl_silence_val)
        display_layout.addLayout(silence_header_layout)

        self.progress_silence = QProgressBar()
        self.progress_silence.setRange(0, 50)
        self.progress_silence.setValue(0)
        self.progress_silence.setTextVisible(False)
        self.progress_silence.setFixedHeight(10)
        self.progress_silence.setObjectName("SilenceProgress")
        display_layout.addWidget(self.progress_silence)

        meter_layout = QHBoxLayout()
        lbl_mic_icon = QLabel("🔊 Poziom sygnału:")
        lbl_mic_icon.setFont(QFont("Segoe UI", 9))
        self.progress_vu = QProgressBar()
        self.progress_vu.setRange(0, 100)
        self.progress_vu.setValue(0)
        self.progress_vu.setTextVisible(False)
        self.progress_vu.setFixedHeight(10)
        
        meter_layout.addWidget(lbl_mic_icon)
        meter_layout.addWidget(self.progress_vu)
        display_layout.addLayout(meter_layout)

        self.lbl_vad_detail = QLabel("VAD: Oczekiwanie na uruchomienie...")
        self.lbl_vad_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_vad_detail.setStyleSheet("color: #8d99ae; font-size: 11px; margin-top: 4px;")
        display_layout.addWidget(self.lbl_vad_detail)

        main_layout.addWidget(display_frame)

        # SUWAK PROGU
        slider_box = QGroupBox("Ustawienia Automatycznego Wstrzymywania")
        slider_layout = QHBoxLayout(slider_box)

        lbl_thresh = QLabel("Próg braku mowy:")
        self.lbl_thresh_val = QLabel("5.0 s")
        self.lbl_thresh_val.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_thresh_val.setStyleSheet("color: #4cc9f0;")

        self.slider_silence = QSlider(Qt.Orientation.Horizontal)
        self.slider_silence.setRange(1, 10)
        self.slider_silence.setValue(5)
        self.slider_silence.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_silence.setTickInterval(1)
        self.slider_silence.valueChanged.connect(self._on_silence_slider_changed)

        slider_layout.addWidget(lbl_thresh)
        slider_layout.addWidget(self.slider_silence, stretch=1)
        slider_layout.addWidget(self.lbl_thresh_val)
        main_layout.addWidget(slider_box)

        # PRZYCISKI STEROWANIA
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(12)

        self.btn_start = QPushButton("⏺ Start Inteligentnego Nagrywania")
        self.btn_start.setObjectName("BtnStart")
        self.btn_start.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.btn_start.setMinimumHeight(48)
        self.btn_start.clicked.connect(self._on_start_clicked)

        self.btn_pause = QPushButton("⏸ Pauza Ręczna")
        self.btn_pause.setObjectName("BtnPause")
        self.btn_pause.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.btn_pause.setMinimumHeight(48)
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._on_pause_clicked)

        self.btn_stop = QPushButton("⏹ Stop i Zapisz")
        self.btn_stop.setObjectName("BtnStop")
        self.btn_stop.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.btn_stop.setMinimumHeight(48)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop_clicked)

        controls_layout.addWidget(self.btn_start)
        controls_layout.addWidget(self.btn_pause)
        controls_layout.addWidget(self.btn_stop)
        main_layout.addLayout(controls_layout)

        # LISTA NAGRAŃ
        recordings_box = QGroupBox("Historia Zapisanych Nagrań")
        recordings_layout = QVBoxLayout(recordings_box)

        path_layout = QHBoxLayout()
        self.lbl_path = QLabel(f"Folder: {self.recordings_dir}")
        self.lbl_path.setStyleSheet("color: #8d99ae; font-size: 11px;")
        btn_change_dir = QPushButton("Zmień folder")
        btn_change_dir.setFont(QFont("Segoe UI", 8))
        btn_change_dir.clicked.connect(self._on_change_dir_clicked)

        path_layout.addWidget(self.lbl_path, stretch=1)
        path_layout.addWidget(btn_change_dir)
        recordings_layout.addLayout(path_layout)

        self.list_recordings = QListWidget()
        self.list_recordings.setFixedHeight(100)
        self.list_recordings.itemDoubleClicked.connect(self._on_recording_double_clicked)
        recordings_layout.addWidget(self.list_recordings)

        btn_open_folder = QPushButton("📁 Otwórz folder nagrań w eksploratorze")
        btn_open_folder.clicked.connect(self._on_open_folder_clicked)
        recordings_layout.addWidget(btn_open_folder)

        main_layout.addWidget(recordings_box, stretch=1)

        # TRANSKRYPCJA I DIARYZACJA
        transcription_box = QGroupBox("AI Transkrypcja i Rozpoznawanie Głosów (Offline)")
        transcription_layout = QVBoxLayout(transcription_box)

        token_layout = QHBoxLayout()
        lbl_token = QLabel("HuggingFace Token:")
        self.input_token = QLineEdit()
        self.input_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_token.setPlaceholderText("Wklej tutaj token wygenerowany na HuggingFace (hf_...)")
        
        # Opcjonalne ładowanie tokenu z ukrytego pliku .env (żeby nie wklejać ręcznie)
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if line.startswith("HF_TOKEN="):
                        self.input_token.setText(line.strip().split("=")[1])

        token_layout.addWidget(lbl_token)
        token_layout.addWidget(self.input_token)
        transcription_layout.addLayout(token_layout)

        self.progress_transcription = QProgressBar()
        self.progress_transcription.setRange(0, 100)
        self.progress_transcription.setValue(0)
        self.progress_transcription.setTextVisible(True)
        self.progress_transcription.setFormat("Oczekuje na start (wpisz token powyżej)...")
        transcription_layout.addWidget(self.progress_transcription)

        self.text_transcript = QTextEdit()
        self.text_transcript.setReadOnly(True)
        self.text_transcript.setMinimumHeight(220)
        self.text_transcript.setPlaceholderText("Tutaj pojawi się transkrypcja z podziałem na role po zakończeniu nagrywania. Pamiętaj, że proces ten rozpoczyna się automatycznie po kliknięciu 'Stop i Zapisz' (jeśli podano token).")
        transcription_layout.addWidget(self.text_transcript)

        main_layout.addWidget(transcription_box)

    def _apply_theme(self):
        qss = """
        QMainWindow {
            background-color: #111216;
        }
        QWidget {
            color: #edf2f4;
            font-family: 'Segoe UI', sans-serif;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #272a38;
            border-radius: 8px;
            margin-top: 8px;
            padding-top: 12px;
            background-color: #171820;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
            color: #4cc9f0;
        }
        QComboBox {
            background-color: #222533;
            border: 1px solid #33374c;
            border-radius: 6px;
            padding: 6px 10px;
            color: #edf2f4;
        }
        QFrame#DisplayFrame {
            background-color: #171820;
            border: 1px solid #272a38;
            border-radius: 10px;
        }
        QLabel#StatusStopped {
            background-color: #272a38;
            color: #8d99ae;
            padding: 4px 14px;
            border-radius: 12px;
        }
        QLabel#StatusSpeech {
            background-color: #10b981;
            color: #ffffff;
            padding: 4px 14px;
            border-radius: 12px;
        }
        QLabel#StatusCountdown {
            background-color: #0284c7;
            color: #ffffff;
            padding: 4px 14px;
            border-radius: 12px;
        }
        QLabel#StatusAutoPaused {
            background-color: #f59e0b;
            color: #ffffff;
            padding: 4px 14px;
            border-radius: 12px;
        }
        QLabel#StatusManualPaused {
            background-color: #6b7280;
            color: #ffffff;
            padding: 4px 14px;
            border-radius: 12px;
        }
        QProgressBar {
            background-color: #222533;
            border-radius: 5px;
            border: none;
        }
        QProgressBar::chunk {
            background-color: #10b981;
            border-radius: 5px;
        }
        QProgressBar#SilenceProgress::chunk {
            background-color: #f59e0b;
            border-radius: 5px;
        }
        QPushButton {
            background-color: #222533;
            border: 1px solid #33374c;
            border-radius: 6px;
            padding: 6px 12px;
            color: #edf2f4;
        }
        QPushButton:hover {
            background-color: #33374c;
        }
        QPushButton:disabled {
            background-color: #161720;
            color: #495057;
            border-color: #212430;
        }
        QPushButton#BtnStart {
            background-color: #dc2626;
            border: none;
            color: #ffffff;
        }
        QPushButton#BtnStart:hover {
            background-color: #ef4444;
        }
        QPushButton#BtnPause {
            background-color: #d97706;
            border: none;
            color: #ffffff;
        }
        QPushButton#BtnPause:hover {
            background-color: #f59e0b;
        }
        QPushButton#BtnStop {
            background-color: #4b5563;
            border: none;
            color: #ffffff;
        }
        QPushButton#BtnStop:hover {
            background-color: #6b7280;
        }
        QListWidget {
            background-color: #111216;
            border: 1px solid #272a38;
            border-radius: 6px;
        }
        QListWidget::item {
            padding: 6px;
            border-bottom: 1px solid #171820;
        }
        QListWidget::item:hover {
            background-color: #222533;
        }
        QSlider::groove:horizontal {
            height: 6px;
            background: #222533;
            border-radius: 3px;
        }
        QSlider::sub-page:horizontal {
            background: #4cc9f0;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #edf2f4;
            width: 14px;
            margin-top: -4px;
            margin-bottom: -4px;
            border-radius: 7px;
        }
        QLineEdit {
            background-color: #222533;
            border: 1px solid #33374c;
            border-radius: 6px;
            padding: 6px 10px;
            color: #edf2f4;
        }
        QTextEdit {
            background-color: #111216;
            border: 1px solid #272a38;
            border-radius: 6px;
            padding: 8px;
            color: #edf2f4;
            font-size: 13px;
            line-height: 1.5;
        }
        """
        self.setStyleSheet(qss)

    def _refresh_audio_devices(self):
        self.combo_devices.clear()
        devices = get_working_input_devices()

        if devices:
            for dev in devices:
                label = f"{dev['name']} ({dev['hostapi']})"
                self.combo_devices.addItem(label, userData=dev['index'])
        else:
            self.combo_devices.addItem("⚠️ BRAK MIKROFONU (Podłącz urządzenie w Windows)", userData=None)

    def _refresh_recordings_list(self):
        self.list_recordings.clear()
        if not os.path.exists(self.recordings_dir):
            return

        files = [f for f in os.listdir(self.recordings_dir) if f.endswith(".wav")]
        files.sort(reverse=True)

        for filename in files:
            full_path = os.path.join(self.recordings_dir, filename)
            size_kb = os.path.getsize(full_path) / 1024
            mtime = datetime.fromtimestamp(os.path.getmtime(full_path)).strftime("%Y-%m-%d %H:%M:%S")
            
            item = QListWidgetItem(f"🎵 {filename}  ({size_kb:.1f} KB, {mtime})")
            item.setData(Qt.ItemDataRole.UserRole, full_path)
            self.list_recordings.addItem(item)

    def _on_silence_slider_changed(self, value):
        self.lbl_thresh_val.setText(f"{value}.0 s")
        self.lbl_silence_title.setText(f"Brak mowy (Auto-Pauza przy {value}.0 s):")
        self.lbl_silence_val.setText(f"0.0 s / {value}.0 s")
        self.progress_silence.setRange(0, value * 10)
        self.worker.set_auto_pause_sec(value)

    def _on_start_clicked(self):
        selected_index = self.combo_devices.currentData()

        if selected_index is None:
            QMessageBox.warning(
                self,
                "Brak Mikrofonu",
                "W systemie Windows nie wykryto aktywnego mikrofonu.\n\n"
                "Upewnij się, że mikrofon jest podłączony i włączony w:\n"
                "Ustawienia Windows -> System -> Dźwięk (Wejście),\n"
                "a następnie kliknij przycisk 🔄 Odśwież."
            )
            return

        self.recorded_seconds = 0
        self.lbl_timer.setText("00:00:00")

        threshold_sec = self.slider_silence.value()
        self.worker.set_auto_pause_sec(threshold_sec)
        self.worker.start_recording(device_index=selected_index)
        self.timer.start()

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸ Pauza Ręczna")
        self.btn_stop.setEnabled(True)
        self.combo_devices.setEnabled(False)
        self.slider_silence.setEnabled(False)

    def _on_pause_clicked(self):
        self.worker.toggle_manual_pause()

    def _on_stop_clicked(self):
        self.timer.stop()
        self.worker.stop_recording()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"inteligentne_nagranie_{timestamp}.wav"
        save_path = os.path.join(self.recordings_dir, filename)

        saved = self.worker.save_wav(save_path)

        self.progress_vu.setValue(0)
        self.progress_silence.setValue(0)
        self.lbl_silence_val.setText(f"0.0 s / {self.slider_silence.value()}.0 s")
        self.lbl_vad_detail.setText("VAD: Oczekiwanie na uruchomienie...")

        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ Pauza Ręczna")
        self.btn_stop.setEnabled(False)
        self.combo_devices.setEnabled(True)
        self.slider_silence.setEnabled(True)

        if saved:
            self._refresh_recordings_list()
            QMessageBox.information(self, "Zapisano Nagranie", f"Pomyślnie zapisano plik audio:\n{filename}")
            
            token = self.input_token.text().strip()
            if token:
                self.btn_start.setEnabled(False)
                self.progress_transcription.setValue(0)
                self.progress_transcription.setFormat("Inicjalizacja sztucznej inteligencji...")
                self.text_transcript.clear()
                
                self.transcription_thread = TranscriptionWorker(save_path, token)
                self.transcription_thread.progress_signal.connect(self._on_transcription_progress)
                self.transcription_thread.finished_signal.connect(self._on_transcription_finished)
                self.transcription_thread.error_signal.connect(self._on_transcription_error)
                self.transcription_thread.start()
            else:
                self.text_transcript.setText("Transkrypcja pominięta - brak podanego tokenu HuggingFace.")
        else:
            QMessageBox.warning(self, "Brak Nagrania", "Nie zarejestrowano mowy do zapisu.")

    def _on_transcription_progress(self, value, text):
        self.progress_transcription.setValue(value)
        self.progress_transcription.setFormat(f"{value}% - {text}")

    def _on_transcription_finished(self, text):
        self.progress_transcription.setValue(100)
        self.progress_transcription.setFormat("Transkrypcja zakończona!")
        self.text_transcript.setHtml(text)
        self.btn_start.setEnabled(True)

    def _on_transcription_error(self, err_msg):
        self.progress_transcription.setValue(0)
        self.progress_transcription.setFormat("Błąd transkrypcji!")
        QMessageBox.critical(self, "Błąd AI", f"Wystąpił błąd podczas przetwarzania:\n{err_msg}")
        self.btn_start.setEnabled(True)

    def _on_timer_tick(self):
        if self.worker.state in [SmartRecordState.RECORDING_SPEECH, SmartRecordState.RECORDING_SILENCE_COUNTDOWN]:
            self.recorded_seconds += 1
            hrs = self.recorded_seconds // 3600
            mins = (self.recorded_seconds % 3600) // 60
            secs = self.recorded_seconds % 60
            self.lbl_timer.setText(f"{hrs:02d}:{mins:02d}:{secs:02d}")

    def _update_audio_level(self, level):
        self.progress_vu.setValue(int(level))

    def _update_vad_info(self, is_speech, speech_prob, current_silence_sec):
        threshold = self.slider_silence.value()
        val_tenths = int(min(current_silence_sec, threshold) * 10)
        self.progress_silence.setValue(val_tenths)
        self.lbl_silence_val.setText(f"{current_silence_sec:.1f} s / {threshold}.0 s")

        vad_mode_str = "Silero VAD AI" if SILERO_AVAILABLE else "Detekcja Energii"
        if is_speech:
            self.lbl_vad_detail.setText(f"🗣️ VAD: DETEKCJA MOWY (Prawdopodobieństwo: {speech_prob*100:.0f}%, Tryb: {vad_mode_str})")
            self.lbl_vad_detail.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px;")
        else:
            self.lbl_vad_detail.setText(f"🔇 VAD: Brak mowy / Szum tła (Tryb: {vad_mode_str})")
            self.lbl_vad_detail.setStyleSheet("color: #8d99ae; font-size: 11px;")

    def _on_worker_state_changed(self, state):
        if state == SmartRecordState.STOPPED:
            self.lbl_status_badge.setText("ZATRZYMANY")
            self.lbl_status_badge.setObjectName("StatusStopped")
        elif state == SmartRecordState.RECORDING_SPEECH:
            self.lbl_status_badge.setText("🟢 NAGRYWANIE (WYKRYTO MOWĘ)")
            self.lbl_status_badge.setObjectName("StatusSpeech")
        elif state == SmartRecordState.RECORDING_SILENCE_COUNTDOWN:
            self.lbl_status_badge.setText("⏳ ODLICZANIE BRAKU MOWY (NAGRYWANIE)")
            self.lbl_status_badge.setObjectName("StatusCountdown")
        elif state == SmartRecordState.AUTO_PAUSED:
            self.lbl_status_badge.setText("🟡 AUTOMATYCZNIE WSTRZYMANO (BRAK MOWY > 5s)")
            self.lbl_status_badge.setObjectName("StatusAutoPaused")
        elif state == SmartRecordState.MANUAL_PAUSED:
            self.lbl_status_badge.setText("⏸ WSTRZYMANO RĘCZNIE")
            self.lbl_status_badge.setObjectName("StatusManualPaused")
            self.btn_pause.setText("▶ Wznów Ręcznie")

        self.lbl_status_badge.setStyle(self.lbl_status_badge.style())

    def _handle_audio_error(self, err_msg):
        self._on_stop_clicked()
        QMessageBox.critical(
            self,
            "Urządzenie Audio",
            f"{err_msg}\n\n"
            "Upewnij się, że mikrofon jest podłączony w Windows i sprawny."
        )

    def _on_change_dir_clicked(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Wybierz katalog zapisu nagrań", self.recordings_dir)
        if dir_path:
            self.recordings_dir = dir_path
            self.lbl_path.setText(f"Folder: {self.recordings_dir}")
            self._refresh_recordings_list()

    def _on_recording_double_clicked(self, item):
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if file_path and os.path.exists(file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))

    def _on_open_folder_clicked(self):
        if os.path.exists(self.recordings_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.recordings_dir))

    def closeEvent(self, event):
        if self.worker.state != SmartRecordState.STOPPED:
            self.worker.stop_recording()
        self.worker.wait(1000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Inteligentny Dyktafon AI")
    window = SmartDictaphoneWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
