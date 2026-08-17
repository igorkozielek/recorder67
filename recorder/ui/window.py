import os
import sys
from datetime import datetime

try:
    from PySide6.QtCore import Qt, QTimer, QUrl
    from PySide6.QtGui import QFont, QDesktopServices
    from PySide6.QtWidgets import (
        QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QComboBox, QProgressBar, QListWidget,
        QListWidgetItem, QGroupBox, QMessageBox, QFrame,
        QSlider, QLineEdit, QTextEdit, QScrollArea, QFileDialog
    )
except ImportError:
    from PyQt6.QtCore import Qt, QTimer, QUrl
    from PyQt6.QtGui import QFont, QDesktopServices
    from PyQt6.QtWidgets import (
        QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QComboBox, QProgressBar, QListWidget,
        QListWidgetItem, QGroupBox, QMessageBox, QFrame,
        QSlider, QLineEdit, QTextEdit, QScrollArea, QFileDialog
    )

from recorder.config import (
    SmartRecordState,
    RECORDINGS_DIR,
    TRANSCRIPTIONS_DIR,
    get_hf_token,
    SAMPLE_RATE,
    DEFAULT_AUTO_PAUSE_SEC
)
from recorder.audio.devices import get_working_input_devices
from recorder.core.vad import is_silero_available
from recorder.ui.theme import DARK_THEME_QSS
from recorder.ui.workers import (
    SmartAudioWorker,
    LiveTranscriptionWorker,
    TranscriptionWorker,
    FileProcessingWorker
)
from recorder.core.speakers import analyze_speakers, suggest_speaker_names, format_turns


class SmartDictaphoneWindow(QMainWindow):
    """
    Główne okno aplikacji Inteligentnego Dyktafonu AI (Ambient AI & Recorder).
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inteligentny Dyktafon AI - Wykrywanie Mowy (VAD)")
        self.resize(780, 920)
        self.setMinimumSize(620, 720)

        self.recordings_dir = RECORDINGS_DIR
        self.transcriptions_dir = TRANSCRIPTIONS_DIR

        self.last_audio_save_path = None
        self.recorded_seconds = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._on_timer_tick)

        self.live_transcription_worker = None
        self.live_plain_text_lines = []
        self.transcription_thread = None
        self.file_processing_worker = None

        # Stan mapowania mówców
        self.current_turns = []
        self.current_txt_path = None
        self.speaker_inputs = {}

        self.worker = SmartAudioWorker(samplerate=SAMPLE_RATE, auto_pause_sec=DEFAULT_AUTO_PAUSE_SEC)
        self.worker.audio_level_signal.connect(self._update_audio_level)
        self.worker.vad_info_signal.connect(self._update_vad_info)
        self.worker.state_changed_signal.connect(self._on_worker_state_changed)
        self.worker.error_signal.connect(self._handle_audio_error)

        self._init_ui()
        self._apply_theme()
        self._refresh_audio_devices()
        self._refresh_recordings_list()
        self._refresh_transcriptions_list()

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
        controls_layout.setSpacing(10)

        self.btn_start = QPushButton("⏺ Start Nagrywania")
        self.btn_start.setObjectName("BtnStart")
        self.btn_start.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.btn_start.setMinimumHeight(48)
        self.btn_start.clicked.connect(self._on_start_clicked)

        self.btn_pause = QPushButton("⏸ Pauza")
        self.btn_pause.setObjectName("BtnPause")
        self.btn_pause.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.btn_pause.setMinimumHeight(48)
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._on_pause_clicked)

        self.btn_stop = QPushButton("⏹ Stop i Zapisz")
        self.btn_stop.setObjectName("BtnStop")
        self.btn_stop.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.btn_stop.setMinimumHeight(48)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop_clicked)

        self.btn_upload = QPushButton("📂 Prześlij Plik Audio")
        self.btn_upload.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.btn_upload.setMinimumHeight(48)
        self.btn_upload.setStyleSheet("background-color: #3a0ca3; color: #ffffff; border-radius: 8px; padding: 0 14px;")
        self.btn_upload.setToolTip("Wgraj gotowy plik audio (WAV, MP3, M4A, FLAC, OGG, AAC) do transkrypcji i diaryzacji")
        self.btn_upload.clicked.connect(self._on_upload_file_clicked)

        controls_layout.addWidget(self.btn_start, stretch=3)
        controls_layout.addWidget(self.btn_pause, stretch=2)
        controls_layout.addWidget(self.btn_stop, stretch=2)
        controls_layout.addWidget(self.btn_upload, stretch=3)
        main_layout.addLayout(controls_layout)

        # WYGENEROWANE WYJŚCIA (Master GroupBox)
        outputs_box = QGroupBox("Wygenerowane Wyjścia i Transkrypcje")
        outputs_main_layout = QVBoxLayout(outputs_box)

        # Token + Pasek Postępu AI
        token_layout = QHBoxLayout()
        lbl_token = QLabel("HuggingFace Token:")
        self.input_token = QLineEdit()
        self.input_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_token.setPlaceholderText("Wklej tutaj token wygenerowany na HuggingFace (hf_...)")
        
        # Automatyczne załadowanie tokena z .env lub config
        loaded_token = get_hf_token()
        if loaded_token:
            self.input_token.setText(loaded_token)

        token_layout.addWidget(lbl_token)
        token_layout.addWidget(self.input_token)
        outputs_main_layout.addLayout(token_layout)

        self.progress_transcription = QProgressBar()
        self.progress_transcription.setRange(0, 100)
        self.progress_transcription.setValue(0)
        self.progress_transcription.setTextVisible(True)
        self.progress_transcription.setFormat("Oczekuje na nagranie lub plik...")
        outputs_main_layout.addWidget(self.progress_transcription)

        # UKŁAD DWUKOLUMNOWY: LEWA = NAGRANIA AUDIO, PRAWA = TRANSKRYPCJE TEKSTOWE
        columns_layout = QHBoxLayout()

        # LEWA KOLUMNA: NAGRANIA AUDIO (.wav)
        left_box = QGroupBox("🎵 Nagrania Audio (.wav)")
        left_layout = QVBoxLayout(left_box)

        self.lbl_path_audio = QLabel(f"Folder: {self.recordings_dir}")
        self.lbl_path_audio.setStyleSheet("color: #8d99ae; font-size: 11px;")
        left_layout.addWidget(self.lbl_path_audio)

        self.list_recordings = QListWidget()
        self.list_recordings.setFixedHeight(110)
        self.list_recordings.itemDoubleClicked.connect(self._on_recording_double_clicked)
        left_layout.addWidget(self.list_recordings)

        btn_open_audio_folder = QPushButton("📁 Otwórz folder nagrań")
        btn_open_audio_folder.clicked.connect(self._on_open_folder_clicked)
        left_layout.addWidget(btn_open_audio_folder)

        columns_layout.addWidget(left_box, stretch=1)

        # PRAWA KOLUMNA: TRANSKRYPCJE TEKSTOWE (.txt)
        right_box = QGroupBox("📄 Transkrypcje Tekstowe (.txt)")
        right_layout = QVBoxLayout(right_box)

        self.lbl_path_txt = QLabel(f"Folder: {self.transcriptions_dir}")
        self.lbl_path_txt.setStyleSheet("color: #8d99ae; font-size: 11px;")
        right_layout.addWidget(self.lbl_path_txt)

        self.list_transcriptions = QListWidget()
        self.list_transcriptions.setFixedHeight(110)
        self.list_transcriptions.itemDoubleClicked.connect(self._on_transcription_double_clicked)
        right_layout.addWidget(self.list_transcriptions)

        btn_open_txt_folder = QPushButton("📁 Otwórz folder transkrypcji")
        btn_open_txt_folder.clicked.connect(self._on_open_txt_folder_clicked)
        right_layout.addWidget(btn_open_txt_folder)

        columns_layout.addWidget(right_box, stretch=1)

        outputs_main_layout.addLayout(columns_layout)

        # PANEL MAPOWANIA I WERYFIKACJI MÓWCÓW
        self.speaker_box = QGroupBox("👥 Przypisanie i Korekta Mówców (Weryfikacja)")
        self.speaker_box.setStyleSheet("QGroupBox { border: 1px solid #4361ee; margin-top: 10px; font-weight: bold; }")
        speaker_main_layout = QVBoxLayout(self.speaker_box)
        speaker_main_layout.setContentsMargins(12, 14, 12, 12)
        speaker_main_layout.setSpacing(10)

        lbl_spk_info = QLabel("🤖 Program przeanalizował dialogi i zasugerował imiona. Zweryfikuj je lub popraw przed zapisem:")
        lbl_spk_info.setStyleSheet("color: #4cc9f0; font-size: 11px;")
        speaker_main_layout.addWidget(lbl_spk_info)

        self.speaker_rows_layout = QVBoxLayout()
        self.speaker_rows_layout.setSpacing(8)
        speaker_main_layout.addLayout(self.speaker_rows_layout)

        self.btn_apply_speakers = QPushButton("✅ Zastosuj Imiona Mówców i Zapisz Zmiany")
        self.btn_apply_speakers.setFixedHeight(36)
        self.btn_apply_speakers.setStyleSheet("background-color: #2b9348; color: #ffffff; font-weight: bold; border-radius: 6px;")
        self.btn_apply_speakers.clicked.connect(self._on_apply_speakers_clicked)
        speaker_main_layout.addWidget(self.btn_apply_speakers)

        self.speaker_box.setVisible(False)
        outputs_main_layout.addWidget(self.speaker_box)

        # PODGLĄD AKTYWNEJ TRANSKRYPCJI
        self.text_transcript = QTextEdit()
        self.text_transcript.setReadOnly(True)
        self.text_transcript.setMinimumHeight(220)
        self.text_transcript.setPlaceholderText("Tutaj pojawi się transkrypcja z podziałem na role po zakończeniu nagrywania / wgraniu pliku...")
        outputs_main_layout.addWidget(self.text_transcript)

        main_layout.addWidget(outputs_box)

    def _apply_theme(self):
        self.setStyleSheet(DARK_THEME_QSS)

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

        self.live_plain_text_lines = []
        self.text_transcript.clear()
        self.text_transcript.setPlaceholderText("Transkrypcja na żywo: Wypowiedzi będą pojawiać się tutaj automatycznie...")
        self.progress_transcription.setValue(0)
        self.progress_transcription.setFormat("Inicjalizacja transkrypcji na żywo...")

        # Uruchomienie wątku transkrypcji na żywo
        self.live_transcription_worker = LiveTranscriptionWorker(model_size="small")
        self.live_transcription_worker.phrase_transcribed_signal.connect(self._on_live_phrase_received)
        self.live_transcription_worker.status_signal.connect(self._on_live_status_changed)
        self.live_transcription_worker.error_signal.connect(self._on_live_error)
        self.live_transcription_worker.start()

        self.worker.phrase_signal.connect(self.live_transcription_worker.add_phrase_chunk)

        threshold_sec = self.slider_silence.value()
        self.worker.set_auto_pause_sec(threshold_sec)
        self.worker.start_recording(device_index=selected_index)
        self.timer.start()

        self.btn_start.setEnabled(False)
        self.btn_upload.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸ Pauza")
        self.btn_stop.setEnabled(True)
        self.combo_devices.setEnabled(False)
        self.slider_silence.setEnabled(False)

    def _on_live_phrase_received(self, time_str, text_phrase):
        html_line = f"<b>[{time_str}]:</b> {text_phrase}<br>"
        plain_line = f"[{time_str}]: {text_phrase}"
        self.live_plain_text_lines.append(plain_line)
        
        self.text_transcript.append(html_line)
        sb = self.text_transcript.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_live_status_changed(self, text):
        self.progress_transcription.setFormat(f"Transkrypcja na Żywo: {text}")
        self.progress_transcription.setValue(100)

    def _on_live_error(self, err_msg):
        self.progress_transcription.setFormat("Błąd transkrypcji na żywo!")
        if sys.stderr:
            print(f"Błąd transkrypcji na żywo: {err_msg}", file=sys.stderr)

    def _on_pause_clicked(self):
        self.worker.toggle_manual_pause()

    def _on_stop_clicked(self):
        self.timer.stop()
        self.worker.stop_recording()

        if self.live_transcription_worker is not None:
            try:
                self.worker.phrase_signal.disconnect(self.live_transcription_worker.add_phrase_chunk)
            except Exception:
                pass
            self.live_transcription_worker.stop()
            self.live_transcription_worker.wait(2000)
            self.live_transcription_worker = None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"inteligentne_nagranie_{timestamp}.wav"
        save_path = os.path.join(self.recordings_dir, filename)

        saved = self.worker.save_wav(save_path)

        self.progress_vu.setValue(0)
        self.progress_silence.setValue(0)
        self.lbl_silence_val.setText(f"0.0 s / {self.slider_silence.value()}.0 s")
        self.lbl_vad_detail.setText("VAD: Oczekiwanie na uruchomienie...")

        self.btn_start.setEnabled(True)
        self.btn_upload.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ Pauza")
        self.btn_stop.setEnabled(False)
        self.combo_devices.setEnabled(True)
        self.slider_silence.setEnabled(True)

        if saved:
            self.last_audio_save_path = save_path
            self._refresh_recordings_list()

            # Natychmiastowy zapis transkrypcji na żywo do pliku TXT
            txt_filename = f"transkrypcja_{timestamp}.txt"
            txt_path = os.path.join(self.transcriptions_dir, txt_filename)
            live_text_content = "\n\n".join(self.live_plain_text_lines) if self.live_plain_text_lines else "Brak zarejestrowanej mowy."
            try:
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(live_text_content)
                self._refresh_transcriptions_list()
            except Exception as e:
                if sys.stderr:
                    print(f"Błąd zapisu pliku TXT na żywo: {e}", file=sys.stderr)

            QMessageBox.information(self, "Zapisano Nagranie", f"Pomyślnie zapisano plik audio:\n{filename}\noraz notatki z transkrypcji na żywo!")
            
            token = self.input_token.text().strip()
            if token:
                self.progress_transcription.setValue(0)
                self.progress_transcription.setFormat("Trwa analiza głosów i diaryzacja w tle...")
                
                self.transcription_thread = TranscriptionWorker(save_path, token)
                self.transcription_thread.progress_signal.connect(self._on_transcription_progress)
                self.transcription_thread.finished_signal.connect(self._on_transcription_finished)
                self.transcription_thread.error_signal.connect(self._on_transcription_error)
                self.transcription_thread.start()
        else:
            QMessageBox.warning(self, "Brak Nagrania", "Nie zarejestrowano mowy do zapisu.")

    def _on_upload_file_clicked(self):
        """
        Obsługa wgrywania zewnętrznego pliku audio (WAV, MP3, M4A, FLAC, OGG, AAC)
        bez konieczności posiadania zewnętrznego narzędzia FFmpeg w systemie Windows.
        """
        file_filter = (
            "Wszystkie Obsługiwane (*.mp4 *.mkv *.mov *.webm *.wav *.mp3 *.m4a *.flac *.ogg *.aac *.wma);;"
            "Nagrania Wideo (*.mp4 *.mkv *.mov *.webm);;"
            "Nagrania Audio (*.wav *.mp3 *.m4a *.flac *.ogg *.aac *.wma);;"
            "Wszystkie pliki (*.*)"
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Wybierz plik audio do transkrypcji",
            "",
            file_filter
        )

        if not file_path:
            return

        # Walidacja pliku (czy istnieje i czy rozmiar > 0)
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            QMessageBox.warning(self, "Niepoprawny Plik", "Wybrany plik jest pusty lub nie istnieje na dysku.")
            return

        token = self.input_token.text().strip()
        filename = os.path.basename(file_path)

        # Blokowanie kontrolek na czas przetwarzania pliku
        self.btn_start.setEnabled(False)
        self.btn_upload.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.combo_devices.setEnabled(False)

        self.text_transcript.clear()
        self.text_transcript.setPlaceholderText(f"Trwa przetwarzanie pliku '{filename}'...\nProszę czekać, operacja odbywa się asynchronicznie.")
        self.progress_transcription.setValue(0)
        self.progress_transcription.setFormat(f"Inicjalizacja przetwarzania: {filename}")

        self.file_processing_worker = FileProcessingWorker(
            input_file_path=file_path,
            recordings_dir=self.recordings_dir,
            hf_token=token if token else None
        )
        self.file_processing_worker.progress_signal.connect(self._on_file_progress)
        self.file_processing_worker.finished_signal.connect(self._on_file_finished)
        self.file_processing_worker.error_signal.connect(self._on_file_error)
        self.file_processing_worker.start()

    def _on_file_progress(self, value: int, text: str):
        self.progress_transcription.setValue(value)
        self.progress_transcription.setFormat(f"{value}% - {text}")

    def _on_file_finished(self, html_text: str, plain_text: str, prepared_wav_path: str, turns: list = None):
        self.progress_transcription.setValue(100)
        self.progress_transcription.setFormat("Przetwarzanie pliku zakończone!")
        self.text_transcript.setHtml(html_text)

        # Odblokowanie kontrolek
        self.btn_start.setEnabled(True)
        self.btn_upload.setEnabled(True)
        self.combo_devices.setEnabled(True)

        self.last_audio_save_path = prepared_wav_path
        self._refresh_recordings_list()

        # Zapis transkrypcji do pliku TXT
        base_name = os.path.basename(prepared_wav_path)
        file_stem = os.path.splitext(base_name)[0]
        txt_filename = f"transkrypcja_{file_stem}.txt"
        txt_path = os.path.join(self.transcriptions_dir, txt_filename)
        self.current_txt_path = txt_path
        self.current_turns = turns or []

        # Wypełnienie panelu mapowania mówców
        self._populate_speaker_mapping(self.current_turns)

        # Jeśli wykryto pewne sugestie imion, automatycznie aktualizujemy treść
        suggestions = suggest_speaker_names(self.current_turns) if self.current_turns else {}
        if suggestions and any(k != v for k, v in suggestions.items()):
            auto_html, auto_plain = format_turns(self.current_turns, suggestions)
            self.text_transcript.setHtml(auto_html)
            plain_text = auto_plain

        try:
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(plain_text)
            self._refresh_transcriptions_list()
        except Exception as e:
            if sys.stderr:
                print(f"Błąd zapisu pliku TXT: {e}", file=sys.stderr)

        QMessageBox.information(
            self,
            "Plik Przetworzony",
            f"Pomyślnie przetworzono plik audio!\n\n"
            f"Zapisano audio 16kHz:\n{os.path.basename(prepared_wav_path)}\n\n"
            f"Zapisano transkrypcję:\n{txt_filename}"
        )

    def _on_file_error(self, err_msg: str):
        self.progress_transcription.setValue(0)
        self.progress_transcription.setFormat("Błąd przetwarzania pliku!")
        self.btn_start.setEnabled(True)
        self.btn_upload.setEnabled(True)
        self.combo_devices.setEnabled(True)
        QMessageBox.critical(self, "Błąd Przetwarzania Pliku", f"Wystąpił błąd podczas przetwarzania pliku audio:\n\n{err_msg}")

    def _on_transcription_progress(self, value, text):
        self.progress_transcription.setValue(value)
        self.progress_transcription.setFormat(f"{value}% - {text}")

    def _on_transcription_finished(self, html_text: str, plain_text: str, turns: list = None):
        self.progress_transcription.setValue(100)
        self.progress_transcription.setFormat("Transkrypcja zakończona!")
        self.text_transcript.setHtml(html_text)
        self.btn_start.setEnabled(True)
        self.btn_upload.setEnabled(True)

        if self.last_audio_save_path:
            base_name = os.path.basename(self.last_audio_save_path)
            file_stem = os.path.splitext(base_name)[0]
            txt_filename = f"transkrypcja_{file_stem.replace('inteligentne_nagranie_', '')}.txt"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            txt_filename = f"transkrypcja_{timestamp}.txt"

        txt_path = os.path.join(self.transcriptions_dir, txt_filename)
        self.current_txt_path = txt_path
        self.current_turns = turns or []

        # Wypełnienie panelu mapowania mówców
        self._populate_speaker_mapping(self.current_turns)

        suggestions = suggest_speaker_names(self.current_turns) if self.current_turns else {}
        if suggestions and any(k != v for k, v in suggestions.items()):
            auto_html, auto_plain = format_turns(self.current_turns, suggestions)
            self.text_transcript.setHtml(auto_html)
            plain_text = auto_plain

        try:
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(plain_text)
            self._refresh_transcriptions_list()
        except Exception as e:
            if sys.stderr:
                print(f"Błąd zapisu pliku TXT: {e}", file=sys.stderr)

    def _populate_speaker_mapping(self, turns: list):
        """
        Dynamicznie buduje listę wykrytych mówców w panelu weryfikacji.
        """
        while self.speaker_rows_layout.count():
            child = self.speaker_rows_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                while child.layout().count():
                    subchild = child.layout().takeAt(0)
                    if subchild.widget():
                        subchild.widget().deleteLater()

        self.speaker_inputs.clear()

        if not turns:
            self.speaker_box.setVisible(False)
            return

        speakers = sorted(list(set(t.get("speaker", "") for t in turns if t.get("speaker"))))
        has_diarization = any(spk.startswith("SPEAKER_") for spk in speakers)

        if not has_diarization or len(speakers) == 0:
            self.speaker_box.setVisible(False)
            return

        analysis = analyze_speakers(turns)

        for spk_id in speakers:
            s_data = analysis.get(spk_id, {})
            count = s_data.get("count", 0)
            sample_text = s_data.get("sample", "")
            suggested_name = s_data.get("suggested_name", "")
            clue = s_data.get("clue", "")

            if len(sample_text) > 55:
                sample_text = sample_text[:52] + "..."

            card_frame = QFrame()
            card_frame.setStyleSheet("QFrame { background-color: #1a1b26; border: 1px solid #33374b; border-radius: 6px; padding: 6px 10px; }")
            card_layout = QVBoxLayout(card_frame)
            card_layout.setContentsMargins(4, 4, 4, 4)
            card_layout.setSpacing(4)

            top_row = QHBoxLayout()
            top_row.setSpacing(10)

            lbl_spk = QLabel(f"<b>{spk_id}</b> ({count} wypowiedzi)")
            lbl_spk.setMinimumWidth(160)
            lbl_spk.setFont(QFont("Segoe UI", 9))

            edit_name = QLineEdit()
            edit_name.setPlaceholderText("Wpisz imię / rolę (np. Jan, Piotr, Klient)")
            edit_name.setText(suggested_name)
            edit_name.setStyleSheet("background-color: #2b2d42; color: #edf2f4; border: 1px solid #4cc9f0; border-radius: 4px; padding: 4px 8px; font-weight: bold;")

            self.speaker_inputs[spk_id] = edit_name

            top_row.addWidget(lbl_spk)
            top_row.addWidget(edit_name, stretch=1)
            card_layout.addLayout(top_row)

            # Dolny wiersz: Wskazówka kontekstowa z dowodem oraz próbka wypowiedzi
            bottom_row = QHBoxLayout()
            bottom_row.setSpacing(10)

            lbl_clue = QLabel(clue)
            lbl_clue.setStyleSheet("color: #4cc9f0; font-size: 11px;")

            lbl_sample = QLabel(f"Próbka: <i>„{sample_text}”</i>" if sample_text else "")
            lbl_sample.setStyleSheet("color: #8d99ae; font-size: 11px;")

            bottom_row.addWidget(lbl_clue, stretch=2)
            bottom_row.addWidget(lbl_sample, stretch=3)
            card_layout.addLayout(bottom_row)

            self.speaker_rows_layout.addWidget(card_frame)

        self.speaker_box.setVisible(True)

    def _on_apply_speakers_clicked(self):
        """
        Zatwierdza nowe nazwy mówców wprowadzone przez użytkownika i aktualizuje podgląd oraz plik TXT.
        """
        if not self.current_turns:
            return

        mapping = {}
        for spk_id, edit in self.speaker_inputs.items():
            val = edit.text().strip()
            mapping[spk_id] = val if val else spk_id

        html_text, plain_text = format_turns(self.current_turns, mapping)
        self.text_transcript.setHtml(html_text)

        if self.current_txt_path:
            try:
                with open(self.current_txt_path, 'w', encoding='utf-8') as f:
                    f.write(plain_text)
                self._refresh_transcriptions_list()
                QMessageBox.information(
                    self,
                    "Zaktualizowano Mówców",
                    "Pomyślnie zaktualizowano imiona mówców w podglądzie oraz w zapisanym pliku transkrypcji!"
                )
            except Exception as e:
                QMessageBox.warning(self, "Błąd Zapisu", f"Nie udało się zaktualizować pliku TXT:\n{e}")

    def _refresh_transcriptions_list(self):
        self.list_transcriptions.clear()
        if not os.path.exists(self.transcriptions_dir):
            return

        files = [f for f in os.listdir(self.transcriptions_dir) if f.endswith(".txt")]
        files.sort(reverse=True)

        for filename in files:
            full_path = os.path.join(self.transcriptions_dir, filename)
            size_kb = os.path.getsize(full_path) / 1024
            mtime = datetime.fromtimestamp(os.path.getmtime(full_path)).strftime("%Y-%m-%d %H:%M:%S")

            item = QListWidgetItem(f"📄 {filename}  ({size_kb:.1f} KB, {mtime})")
            item.setData(Qt.ItemDataRole.UserRole, full_path)
            self.list_transcriptions.addItem(item)

    def _on_transcription_double_clicked(self, item):
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                html_content = content.replace("\n", "<br>")
                self.text_transcript.setHtml(html_content)
            except Exception as e:
                QMessageBox.warning(self, "Błąd Odczytu", f"Nie udało się otworzyć pliku:\n{e}")

    def _on_open_txt_folder_clicked(self):
        if os.path.exists(self.transcriptions_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.transcriptions_dir))

    def _on_transcription_error(self, err_msg):
        self.progress_transcription.setValue(0)
        self.progress_transcription.setFormat("Błąd transkrypcji!")
        QMessageBox.critical(self, "Błąd AI", f"Wystąpił błąd podczas przetwarzania:\n{err_msg}")
        self.btn_start.setEnabled(True)
        self.btn_upload.setEnabled(True)

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

        vad_mode_str = "Silero VAD AI" if is_silero_available() else "Detekcja Energii"
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
