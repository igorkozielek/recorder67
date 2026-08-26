import os
import sys
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QProgressBar, QListWidget,
    QListWidgetItem, QGroupBox, QMessageBox, QFrame,
    QSlider, QLineEdit, QTextEdit, QScrollArea, QFileDialog, QCheckBox,
    QSizePolicy
)

from recorder.config import (
    SmartRecordState,
    RECORDINGS_DIR,
    TRANSCRIPTIONS_DIR,
    get_hf_token,
    SAMPLE_RATE,
    DEFAULT_AUTO_PAUSE_SEC,
    WHISPER_MODELS,
    DEFAULT_WHISPER_MODEL,
    get_hardware_acceleration_info,
    SPEAKER_COUNT_OPTIONS,
    get_recommended_profile
)
from recorder.audio.devices import get_working_input_devices
from recorder.core.vad import is_silero_available
from recorder.ui.theme import DARK_THEME_QSS, setup_dark_palette
from recorder.ui.workers import (
    SmartAudioWorker,
    TranscriptionWorker,
    FileProcessingWorker,
    DiarizationOnlyWorker
)
from recorder.core.rolling_transcriber import RollingTranscriptionWorker, RollingBlock
from recorder.core.speakers import (
    analyze_speakers,
    suggest_speaker_names,
    format_turns,
    parse_txt_to_turns,
    format_speaker_stats
)
from recorder.core.session import (
    TranscriptionSession,
    get_session_path_for_txt,
    get_session_path_for_audio,
    find_existing_session_for_audio
)
from recorder.core.cloud_sync import CloudSyncManager



class SmartDictaphoneWindow(QMainWindow):
    """
    Główne okno aplikacji Inteligentnego Dyktafonu AI (Ambient AI & Recorder).
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inteligentny Dyktafon AI - Wykrywanie Mowy (VAD)")
        self.resize(780, 950)
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
        self.last_plain_text = ""
        self.current_meeting_id = None
        self.synced_segment_count = 0
        self._active_threads = []

        # Moduł Cloud Sync (Supabase / EMANAGER.PRO / Webhook)
        self.cloud_sync = CloudSyncManager()
        self.cloud_sync.signals.sync_started.connect(self._on_sync_started)
        self.cloud_sync.signals.sync_finished.connect(self._on_sync_finished)
        self.cloud_sync.signals.offline_queued.connect(self._on_offline_queued)
        self.cloud_sync.signals.live_session_started.connect(self._on_live_session_started)
        self.cloud_sync.signals.live_block_synced.connect(self._on_live_block_synced)
        self.cloud_sync.signals.live_session_finalized.connect(self._on_live_session_finalized)

        self.worker = SmartAudioWorker(samplerate=SAMPLE_RATE, auto_pause_sec=DEFAULT_AUTO_PAUSE_SEC)
        self.worker.audio_level_signal.connect(self._update_audio_level)
        self.worker.vad_info_signal.connect(self._update_vad_info)
        self.worker.state_changed_signal.connect(self._on_worker_state_changed)
        self.worker.session_split_signal.connect(self._on_session_split_triggered)
        self.worker.error_signal.connect(self._handle_audio_error)

        self._init_ui()
        self._apply_theme()
        self._refresh_audio_devices()
        self._refresh_recordings_list()
        self._refresh_transcriptions_list()

        # Uruchomienie przetwarzania zaległej kolejki offline
        self.cloud_sync.process_offline_queue_async()


    def _init_ui(self):
        scroll_area = QScrollArea()
        scroll_area.setObjectName("MainScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(scroll_area)

        main_widget = QWidget()
        main_widget.setObjectName("MainContainerWidget")
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

        # WYBÓR MODELU FASTER-WHISPER I AKCELERACJA SPRZĘTOWA
        model_box = QGroupBox("Model Transkrypcji AI (Faster-Whisper)")
        model_layout = QVBoxLayout(model_box)

        model_row = QHBoxLayout()
        lbl_model_prefix = QLabel("Wybierz model:")
        lbl_model_prefix.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        self.combo_models = QComboBox()
        
        for m_id, m_info in WHISPER_MODELS.items():
            self.combo_models.addItem(m_info["label"], userData=m_id)

        default_idx = self.combo_models.findData(DEFAULT_WHISPER_MODEL)
        if default_idx != -1:
            self.combo_models.setCurrentIndex(default_idx)

        self.combo_models.currentIndexChanged.connect(self._on_model_selection_changed)

        self.btn_auto_detect = QPushButton("🎯 Auto-dopasuj")
        self.btn_auto_detect.setToolTip("Automatycznie dopasuj model i parametry do parametrów Twojego komputera")
        self.btn_auto_detect.clicked.connect(self._on_auto_detect_clicked)

        model_row.addWidget(lbl_model_prefix)
        model_row.addWidget(self.combo_models, stretch=1)
        model_row.addWidget(self.btn_auto_detect)
        model_layout.addLayout(model_row)

        self.lbl_model_desc = QLabel(WHISPER_MODELS.get(DEFAULT_WHISPER_MODEL, {}).get("desc", ""))
        self.lbl_model_desc.setStyleSheet("color: #8d99ae; font-size: 11px; margin-top: 2px;")
        model_layout.addWidget(self.lbl_model_desc)

        hw_info = get_hardware_acceleration_info()
        self.lbl_hw_badge = QLabel(hw_info["badge_text"])
        self.lbl_hw_badge.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px; margin-top: 4px;")
        model_layout.addWidget(self.lbl_hw_badge)

        main_layout.addWidget(model_box)

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

        self.btn_pause = QPushButton("⏸ Wstrzymaj Ręcznie")
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
        self.btn_upload.setToolTip("Wgraj gotowy plik audio (WAV, MP3, M4A, FLAC, OGG, AAC, MP4, MKV) do transkrypcji i diaryzacji")
        self.btn_upload.clicked.connect(self._on_upload_file_clicked)

        controls_layout.addWidget(self.btn_start, stretch=3)
        controls_layout.addWidget(self.btn_pause, stretch=2)
        controls_layout.addWidget(self.btn_stop, stretch=2)
        controls_layout.addWidget(self.btn_upload, stretch=3)
        main_layout.addLayout(controls_layout)

        # WYGENEROWANE WYJŚCIA (Master GroupBox)
        outputs_box = QGroupBox("Wygenerowane Wyjścia i Transkrypcje")
        outputs_main_layout = QVBoxLayout(outputs_box)

        # Opcje Diaryzacji i Liczby Osób
        diarization_row = QHBoxLayout()
        self.check_enable_diarization = QCheckBox("Włącz diaryzację mówców (PyAnnote AI - podział na osoby)")
        self.check_enable_diarization.setChecked(True)
        self.check_enable_diarization.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        self.check_enable_diarization.toggled.connect(self._on_diarization_toggled)

        lbl_speakers = QLabel("Liczba osób:")
        lbl_speakers.setStyleSheet("color: #8d99ae; font-size: 11px;")
        self.combo_speakers = QComboBox()
        for label, count_val in SPEAKER_COUNT_OPTIONS:
            self.combo_speakers.addItem(label, userData=count_val)

        diarization_row.addWidget(self.check_enable_diarization, stretch=1)
        diarization_row.addWidget(lbl_speakers)
        diarization_row.addWidget(self.combo_speakers)
        outputs_main_layout.addLayout(diarization_row)

        # Token + Pasek Postępu AI
        token_layout = QHBoxLayout()
        lbl_token = QLabel("HuggingFace Token:")
        self.input_token = QLineEdit()
        self.input_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_token.setPlaceholderText("Wklej tutaj token HuggingFace (hf_...) - wymagany tylko do diaryzacji")
        
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

        txt_actions_layout = QHBoxLayout()
        txt_actions_layout.setSpacing(6)

        btn_open_txt_folder = QPushButton("📁 Folder")
        btn_open_txt_folder.setFixedHeight(32)
        btn_open_txt_folder.clicked.connect(self._on_open_txt_folder_clicked)

        self.btn_run_diarization = QPushButton("👥 Rozpoznaj Mówców (PyAnnote)")
        self.btn_run_diarization.setFixedHeight(32)
        self.btn_run_diarization.setStyleSheet("background-color: #7209b7; color: #ffffff; font-weight: bold; border-radius: 4px; padding: 0 10px;")
        self.btn_run_diarization.setToolTip("Uruchamia analizę mówców PyAnnote w tle dla zaznaczonego nagrania bez ponownej transkrypcji Whispera")
        self.btn_run_diarization.clicked.connect(self._on_run_diarization_clicked)

        txt_actions_layout.addWidget(btn_open_txt_folder, stretch=1)
        txt_actions_layout.addWidget(self.btn_run_diarization, stretch=2)
        right_layout.addLayout(txt_actions_layout)

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

        # Przewijalny obszar dla mówców (zapewnia doskonałą widoczność dla 3-6 osób jednocześnie)
        speaker_scroll = QScrollArea()
        speaker_scroll.setWidgetResizable(True)
        speaker_scroll.setFrameShape(QFrame.Shape.NoFrame)
        speaker_scroll.setMinimumHeight(160)
        speaker_scroll.setMaximumHeight(320)
        speaker_scroll.setStyleSheet("background: transparent;")

        speaker_scroll_widget = QWidget()
        speaker_scroll_widget.setStyleSheet("background: transparent;")
        self.speaker_rows_layout = QVBoxLayout(speaker_scroll_widget)
        self.speaker_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.speaker_rows_layout.setSpacing(8)
        speaker_scroll.setWidget(speaker_scroll_widget)

        speaker_main_layout.addWidget(speaker_scroll)

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

        # PASEK SYNCHRONIZACJI CHMUROWEJ (CLOUD SYNC / EMANAGER.PRO / CRM)
        cloud_bar_layout = QHBoxLayout()
        cloud_bar_layout.setContentsMargins(4, 4, 4, 4)

        sync_target_name = self.cloud_sync.config.get("sync_target", "emanager").upper()
        self.lbl_cloud_status = QLabel(f"☁️ Integracja: {sync_target_name} (Gotowa)")
        self.lbl_cloud_status.setStyleSheet("color: #4cc9f0; font-size: 11px; font-weight: bold;")

        self.btn_manual_sync = QPushButton(f"☁️ Wyślij do {sync_target_name}")
        self.btn_manual_sync.setFixedHeight(30)
        self.btn_manual_sync.setStyleSheet("background-color: #4361ee; color: #ffffff; font-weight: bold; border-radius: 4px; padding: 0 12px;")
        self.btn_manual_sync.setEnabled(False)
        self.btn_manual_sync.clicked.connect(self._on_manual_sync_clicked)

        cloud_bar_layout.addWidget(self.lbl_cloud_status, stretch=1)
        cloud_bar_layout.addWidget(self.btn_manual_sync)
        outputs_main_layout.addLayout(cloud_bar_layout)

        main_layout.addWidget(outputs_box)


    def _apply_theme(self):
        app = QApplication.instance()
        if app:
            setup_dark_palette(app)
            app.setStyleSheet(DARK_THEME_QSS)
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

    def _on_model_selection_changed(self, index):
        model_id = self.combo_models.currentData()
        if model_id in WHISPER_MODELS:
            self.lbl_model_desc.setText(WHISPER_MODELS[model_id]["desc"])

    def _on_auto_detect_clicked(self):
        profile = get_recommended_profile()
        rec_model = profile["recommended_model"]
        idx = self.combo_models.findData(rec_model)
        if idx != -1:
            self.combo_models.setCurrentIndex(idx)
        QMessageBox.information(self, profile["title"], profile["message"])

    def _on_diarization_toggled(self, checked):
        self.input_token.setEnabled(checked)
        self.combo_speakers.setEnabled(checked)

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

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_live_timestamp = timestamp
        self.current_live_txt_path = os.path.join(self.transcriptions_dir, f"transkrypcja_{timestamp}.txt")
        self.current_live_wav_path = os.path.join(self.recordings_dir, f"inteligentne_nagranie_{timestamp}.wav")
        self.synced_segment_count = 0
        try:
            with open(self.current_live_txt_path, 'w', encoding='utf-8') as f:
                f.write(f"=== TRANSKRYPCJA NA ŻYWO (Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===\n\n")
            self._refresh_transcriptions_list()
        except Exception:
            pass

        selected_model = self.combo_models.currentData() or DEFAULT_WHISPER_MODEL

        # Inicjalizacja sesji w Supabase dla transmisji na żywo do CRM
        if self.cloud_sync.config.get("live_streaming") and self.cloud_sync.config.get("auto_sync"):
            self.current_meeting_id = self.cloud_sync.start_live_session_async(
                title=f"Spotkanie biurowe {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            target_name = self.cloud_sync.config.get("sync_target", "CRM").upper()
            self.lbl_cloud_status.setText(f"🟢 Transmisja na żywo do {target_name} aktywna...")
            self.lbl_cloud_status.setStyleSheet("color: #4cc9f0; font-size: 11px; font-weight: bold;")

        # Ustawienie estetycznego komunikatu oczekiwania na pierwszy zweryfikowany blok mowy
        self.text_transcript.setHtml(
            "<div style='color: #4cc9f0; font-size: 13px; padding: 10px;'>"
            "🎙️ <b>Trwa inteligentne nagrywanie spotkania (Transmisja na żywo do CRM)...</b><br>"
            "<span style='color: #94a3b8; font-size: 11px;'>"
            "Mowa jest na bieżąco przetwarzana w tle z pełnym kontekstem zdań. "
            "Zweryfikowane wypowiedzi pojawią się automatycznie w CRM po naturalnych pauzach w rozmowie."
            "</span></div>"
        )

        # Uruchomienie silnika asynchronicznego przetwarzania bloków w tle (Rolling Background Transcriber)
        self.rolling_worker = RollingTranscriptionWorker(
            model_size=selected_model,
            txt_save_path=self.current_live_txt_path
        )
        self._active_threads.append(self.rolling_worker)
        self.rolling_worker.block_processed_signal.connect(self._on_rolling_block_processed)
        self.rolling_worker.status_signal.connect(self._on_rolling_status)
        self.rolling_worker.finished_signal.connect(self._on_rolling_finished)
        self.rolling_worker.error_signal.connect(self._on_rolling_error)
        self.rolling_worker.start()

        self.worker.rolling_block_ready_signal.connect(self.rolling_worker.add_block)

        threshold_sec = self.slider_silence.value()
        self.worker.set_auto_pause_sec(threshold_sec)
        self.worker.start_recording(device_index=selected_index, save_wav_path=self.current_live_wav_path)
        self.timer.start()

        self.btn_start.setEnabled(False)
        self.btn_upload.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸ Wstrzymaj Ręcznie")
        self.btn_pause.setObjectName("BtnPause")
        self.btn_pause.style().unpolish(self.btn_pause)
        self.btn_pause.style().polish(self.btn_pause)
        self.btn_pause.update()

        self.btn_stop.setEnabled(True)
        self.combo_devices.setEnabled(False)
        self.combo_models.setEnabled(False)
        self.btn_auto_detect.setEnabled(False)
        self.check_enable_diarization.setEnabled(False)
        self.combo_speakers.setEnabled(False)
        self.input_token.setEnabled(False)
        self.slider_silence.setEnabled(False)

    def _on_rolling_block_processed(self, block_idx, proc_sec, tot_sec, all_turns, full_plain, full_html):
        """Odebranie przetworzonego w tle bloku mowy z pełnymi word-level timestampami i synchronizacja na żywo."""
        self.current_turns = all_turns or []
        self.last_plain_text = full_plain
        self.text_transcript.setHtml(full_html)
        self._populate_speaker_mapping(self.current_turns)

        # Transmisja na żywo nowych segmentów do Supabase / CRM
        if self.cloud_sync.config.get("live_streaming") and self.cloud_sync.config.get("auto_sync") and self.current_meeting_id:
            new_segments = (all_turns or [])[self.synced_segment_count:]
            if new_segments:
                spk_cnt = len(set(t.get("speaker", "Mówca") for t in (all_turns or []) if t.get("speaker")))
                self.cloud_sync.append_live_segments_async(
                    meeting_id=self.current_meeting_id,
                    new_segments=new_segments,
                    full_transcript=full_plain,
                    duration_seconds=tot_sec,
                    speaker_count=max(1, spk_cnt)
                )
                self.synced_segment_count = len(all_turns)

        # Aktualizacja paska postępu
        pct = int(min(98, max(5, (proc_sec / max(1.0, tot_sec)) * 100)))
        p_min, p_sec = int(proc_sec // 60), int(proc_sec % 60)
        t_min, t_sec = int(tot_sec // 60), int(tot_sec % 60)
        self.progress_transcription.setValue(pct)
        self.progress_transcription.setFormat(f"🟢 Przetworzono w tle: {p_min:02d}:{p_sec:02d} / {t_min:02d}:{t_sec:02d} (Blok #{block_idx} na żywo)")

    def _on_rolling_status(self, text):
        if self.worker.state in [SmartRecordState.RECORDING_SPEECH, SmartRecordState.RECORDING_SILENCE_COUNTDOWN]:
            self.progress_transcription.setFormat(f"Transkrypcja w tle: {text}")

    def _on_rolling_error(self, err_msg):
        if sys.stderr:
            print(f"Błąd transkrypcji w tle: {err_msg}", file=sys.stderr)

    def _on_pause_clicked(self):
        self.worker.toggle_manual_pause()

    def _on_stop_clicked(self):
        self.timer.stop()
        self.worker.stop_recording()
        self.worker.wait()

        # Odłączenie sygnału bloków
        try:
            self.worker.rolling_block_ready_signal.disconnect(self.rolling_worker.add_block)
        except Exception:
            pass

        timestamp = getattr(self, "current_live_timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))
        filename = f"inteligentne_nagranie_{timestamp}.wav"
        save_path = os.path.join(self.recordings_dir, filename)

        saved = self.worker.save_wav(save_path)
        self.last_audio_save_path = save_path if saved else None

        self.progress_vu.setValue(0)
        self.progress_silence.setValue(0)
        self.lbl_silence_val.setText(f"0.0 s / {self.slider_silence.value()}.0 s")
        self.lbl_vad_detail.setText("VAD: Oczekiwanie na uruchomienie...")

        self.btn_start.setEnabled(True)
        self.btn_upload.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ Wstrzymaj Ręcznie")
        self.btn_pause.setObjectName("BtnPause")
        self.btn_pause.style().unpolish(self.btn_pause)
        self.btn_pause.style().polish(self.btn_pause)
        self.btn_pause.update()

        self.btn_stop.setEnabled(False)
        self.combo_devices.setEnabled(True)
        self.combo_models.setEnabled(True)
        self.btn_auto_detect.setEnabled(True)
        self.check_enable_diarization.setEnabled(True)
        is_diar = self.check_enable_diarization.isChecked()
        self.combo_speakers.setEnabled(is_diar)
        self.input_token.setEnabled(is_diar)
        self.slider_silence.setEnabled(True)

        if saved:
            self._refresh_recordings_list()
            self._refresh_transcriptions_list()

            # Pobranie ostatniego nieprzetworzonego fragmentu audio
            remaining = self.worker.get_remaining_block()
            final_block = None
            if remaining:
                r_idx, r_start, r_end, r_audio = remaining
                final_block = RollingBlock(r_idx, r_start, r_end, r_audio)

            self.progress_transcription.setFormat("Finalizowanie ostatniego fragmentu rozmowy w tle...")
            self.progress_transcription.setValue(95)

            # Przekazanie ostatniego fragmentu do finalizacji
            if getattr(self, "rolling_worker", None) is not None:
                self.rolling_worker.stop_and_finalize(final_block)
        else:
            QMessageBox.warning(self, "Brak Nagrania", "Nie zarejestrowano mowy do zapisu.")

    def _on_rolling_finished(self, final_html: str, final_plain: str, all_turns: list):
        """Zakończenie przetwarzania w tle po kliknięciu Stop."""
        if hasattr(self, "rolling_worker") and self.rolling_worker in self._active_threads:
            self._active_threads.remove(self.rolling_worker)

        self.current_turns = all_turns or []
        self.last_plain_text = final_plain
        self.text_transcript.setHtml(final_html)
        self._populate_speaker_mapping(self.current_turns)

        enable_diar = self.check_enable_diarization.isChecked()
        token = self.input_token.text().strip()
        spk_cfg = self.combo_speakers.currentData() or {}
        num_spk = spk_cfg.get("num_speakers")
        min_spk = spk_cfg.get("min_speakers")
        max_spk = spk_cfg.get("max_speakers")

        # Jeśli użytkownik zażądał diaryzacji mówców PyAnnote
        if enable_diar and token and self.last_audio_save_path and self.current_turns:
            self.progress_transcription.setFormat("Trwa analiza głosów i podział na mówców (PyAnnote)...")
            self.progress_transcription.setValue(96)

            self.transcription_thread = TranscriptionWorker(
                self.last_audio_save_path,
                token,
                model_size=self.combo_models.currentData() or DEFAULT_WHISPER_MODEL,
                enable_diarization=True,
                num_speakers=num_spk,
                min_speakers=min_spk,
                max_speakers=max_spk
            )
            self._active_threads.append(self.transcription_thread)
            self.transcription_thread.progress_signal.connect(self._on_transcription_progress)
            self.transcription_thread.finished_signal.connect(self._on_transcription_finished)
            self.transcription_thread.error_signal.connect(self._on_transcription_error)
            self.transcription_thread.start()
        else:
            self._on_transcription_finished(final_html, final_plain, self.current_turns)


    def _on_upload_file_clicked(self):
        """
        Obsługa wgrywania zewnętrznego pliku audio/wideo (WAV, MP3, M4A, FLAC, OGG, AAC, MP4, MKV)
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

        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            QMessageBox.warning(self, "Niepoprawny Plik", "Wybrany plik jest pusty lub nie istnieje na dysku.")
            return

        token = self.input_token.text().strip()
        filename = os.path.basename(file_path)
        selected_model = self.combo_models.currentData() or DEFAULT_WHISPER_MODEL
        enable_diar = self.check_enable_diarization.isChecked()
        spk_cfg = self.combo_speakers.currentData() or {}
        num_spk = spk_cfg.get("num_speakers")
        min_spk = spk_cfg.get("min_speakers")
        max_spk = spk_cfg.get("max_speakers")

        # Blokowanie kontrolek na czas przetwarzania pliku
        self.btn_start.setEnabled(False)
        self.btn_upload.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.combo_devices.setEnabled(False)
        self.combo_models.setEnabled(False)
        self.btn_auto_detect.setEnabled(False)
        self.check_enable_diarization.setEnabled(False)
        self.combo_speakers.setEnabled(False)
        self.input_token.setEnabled(False)

        self.text_transcript.clear()
        self.text_transcript.setPlaceholderText(f"Trwa przetwarzanie pliku '{filename}'...\nProszę czekać, operacja odbywa się asynchronicznie.")
        self.progress_transcription.setValue(0)
        self.progress_transcription.setFormat(f"Inicjalizacja przetwarzania: {filename}")

        self.file_processing_worker = FileProcessingWorker(
            input_file_path=file_path,
            recordings_dir=self.recordings_dir,
            hf_token=token if token else None,
            model_size=selected_model,
            enable_diarization=enable_diar,
            num_speakers=num_spk,
            min_speakers=min_spk,
            max_speakers=max_spk
        )
        self._active_threads.append(self.file_processing_worker)
        self.file_processing_worker.progress_signal.connect(self._on_file_progress)
        self.file_processing_worker.preliminary_signal.connect(self._on_file_preliminary_transcript)
        self.file_processing_worker.finished_signal.connect(self._on_file_finished)
        self.file_processing_worker.error_signal.connect(self._on_file_error)
        self.file_processing_worker.start()

    def _on_preliminary_transcript(self, html_text: str, plain_text: str, turns: list = None):
        self.text_transcript.setHtml(html_text)
        self.current_turns = turns or []
        self._populate_speaker_mapping(self.current_turns)

    def _on_file_preliminary_transcript(self, html_text: str, plain_text: str, prepared_wav_path: str, turns: list = None):
        self.text_transcript.setHtml(html_text)
        base_name = os.path.basename(prepared_wav_path)
        file_stem = os.path.splitext(base_name)[0]
        txt_filename = f"transkrypcja_{file_stem}.txt"
        self.current_txt_path = os.path.join(self.transcriptions_dir, txt_filename)
        self.current_turns = turns or []
        self._refresh_transcriptions_list()
        self._populate_speaker_mapping(self.current_turns)

    def _on_file_progress(self, value: int, text: str):
        self.progress_transcription.setValue(value)
        self.progress_transcription.setFormat(f"{value}% - {text}")

    def _on_file_finished(self, html_text: str, plain_text: str, prepared_wav_path: str, turns: list = None):
        if hasattr(self, "file_processing_worker") and self.file_processing_worker in self._active_threads:
            self._active_threads.remove(self.file_processing_worker)

        self.progress_transcription.setValue(100)
        self.progress_transcription.setFormat("Przetwarzanie pliku zakończone!")
        self.text_transcript.setHtml(html_text)

        # Odblokowanie kontrolek
        self.btn_start.setEnabled(True)
        self.btn_upload.setEnabled(True)
        self.combo_devices.setEnabled(True)
        self.combo_models.setEnabled(True)
        self.btn_auto_detect.setEnabled(True)
        self.check_enable_diarization.setEnabled(True)
        is_diar = self.check_enable_diarization.isChecked()
        self.combo_speakers.setEnabled(is_diar)
        self.input_token.setEnabled(is_diar)

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

            # Zapis / Aktualizacja pliku sesji JSON
            json_path = get_session_path_for_txt(txt_path)
            try:
                has_diar = any(t.get("speaker", "").startswith("SPEAKER_") for t in (turns or []))
                session = TranscriptionSession.load_from_json(json_path) or TranscriptionSession()
                session.has_transcription = True
                session.has_diarization = has_diar
                session.prepared_wav = prepared_wav_path
                session.source_audio = prepared_wav_path
                session.turns = self.current_turns
                session.save_to_json(json_path)
            except Exception:
                pass

            self._refresh_transcriptions_list()
        except Exception as e:
            if sys.stderr:
                print(f"Błąd zapisu pliku TXT: {e}", file=sys.stderr)

        self.last_plain_text = plain_text
        self.btn_manual_sync.setEnabled(True)

        # Automatyczna synchronizacja z chmurą / EMANAGER.PRO
        if self.cloud_sync.config.get("auto_sync"):
            self._trigger_cloud_sync(
                plain_text=plain_text,
                turns=self.current_turns,
                audio_path=prepared_wav_path,
                title=f"Plik: {base_name}",
                silent=True
            )

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
        self.combo_models.setEnabled(True)
        self.btn_auto_detect.setEnabled(True)
        self.check_enable_diarization.setEnabled(True)
        is_diar = self.check_enable_diarization.isChecked()
        self.combo_speakers.setEnabled(is_diar)
        self.input_token.setEnabled(is_diar)
        QMessageBox.critical(self, "Błąd Przetwarzania Pliku", f"Wystąpił błąd podczas przetwarzania pliku audio:\n\n{err_msg}")

    def _on_transcription_progress(self, value, text):
        self.progress_transcription.setValue(value)
        self.progress_transcription.setFormat(f"{value}% - {text}")

    def _on_transcription_finished(self, html_text: str, plain_text: str, turns: list = None):
        if hasattr(self, "transcription_thread") and self.transcription_thread in self._active_threads:
            self._active_threads.remove(self.transcription_thread)

        self.progress_transcription.setValue(100)
        self.progress_transcription.setFormat("Transkrypcja zakończona!")
        self.text_transcript.setHtml(html_text)
        self.btn_start.setEnabled(True)
        self.btn_upload.setEnabled(True)
        self.combo_devices.setEnabled(True)
        self.combo_models.setEnabled(True)
        self.btn_auto_detect.setEnabled(True)
        self.check_enable_diarization.setEnabled(True)
        is_diar = self.check_enable_diarization.isChecked()
        self.combo_speakers.setEnabled(is_diar)
        self.input_token.setEnabled(is_diar)

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

        # Sprawdzenie czy w wynikach są klastry diaryzacji (SPEAKER_XX)
        has_diarization = any(t.get("speaker", "").startswith("SPEAKER_") for t in self.current_turns)

        if has_diarization:
            # Wypełnienie panelu mapowania mówców
            self._populate_speaker_mapping(self.current_turns)

            suggestions = suggest_speaker_names(self.current_turns) if self.current_turns else {}
            if suggestions and any(k != v for k, v in suggestions.items()):
                auto_html, auto_plain = format_turns(self.current_turns, suggestions)
                self.text_transcript.setHtml(auto_html)
                plain_text = auto_plain
        else:
            # Gdy diaryzacja jest wyłączona: panel mapowania jest ukryty, a w transkrypcji pozostaje neutralny 'Mówca'
            self.speaker_box.setVisible(False)

        try:
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(plain_text)

            # Zapis / Aktualizacja pliku sesji JSON
            json_path = get_session_path_for_txt(txt_path)
            try:
                session = TranscriptionSession.load_from_json(json_path) or TranscriptionSession()
                session.has_transcription = True
                session.has_diarization = has_diarization
                if self.last_audio_save_path:
                    session.prepared_wav = self.last_audio_save_path
                    session.source_audio = self.last_audio_save_path
                session.turns = self.current_turns
                session.save_to_json(json_path)
            except Exception:
                pass

            self._refresh_transcriptions_list()
        except Exception as e:
            if sys.stderr:
                print(f"Błąd zapisu pliku TXT: {e}", file=sys.stderr)

        self.last_plain_text = plain_text
        self.btn_manual_sync.setEnabled(True)

        # Automatyczna synchronizacja z chmurą / EMANAGER.PRO
        if self.cloud_sync.config.get("auto_sync"):
            self._trigger_cloud_sync(
                plain_text=plain_text,
                turns=self.current_turns,
                audio_path=self.last_audio_save_path,
                title=f"Nagranie: {txt_filename}",
                silent=True
            )

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

        # Analiza dowodów i autosugestie
        suggestions = suggest_speaker_names(turns)
        evidence = analyze_speakers(turns)

        for spk_id in speakers:
            suggested_name = suggestions.get(spk_id, spk_id)
            ev = evidence.get(spk_id, {})
            clue = ev.get("clue", "Brak jednoznacznego dowodu w tekście")
            sample_text = ev.get("sample", "")
            spk_count = ev.get("count", 0)
            spk_dur = ev.get("total_duration", 0.0)
            stats_text = format_speaker_stats(spk_count, spk_dur)

            card_frame = QFrame()
            card_frame.setStyleSheet("background-color: #1a1a2e; border: 1px solid #3d3d5c; border-radius: 8px; padding: 6px;")
            card_layout = QVBoxLayout(card_frame)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(6)

            # Nagłówek karty: ID Mówcy + Licznik wypowiedzi i łączny czas mowy
            header_row = QHBoxLayout()
            lbl_spk = QLabel(f"🏷️ <b>{spk_id}</b>")
            lbl_spk.setStyleSheet("color: #edf2f4; font-size: 12px; font-weight: bold;")

            lbl_stats = QLabel(f"📊 {stats_text}")
            lbl_stats.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold;")
            lbl_stats.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            header_row.addWidget(lbl_spk)
            header_row.addStretch(1)
            header_row.addWidget(lbl_stats)
            card_layout.addLayout(header_row)

            # Wiersz inputów: Pole Imienia + Pole Roli / Firmy
            input_row = QHBoxLayout()
            input_row.setSpacing(8)

            edit_name = QLineEdit()
            edit_name.setPlaceholderText("Imię / Nazwisko (np. Ania, Bartek)...")
            edit_name.setText(suggested_name if suggested_name != spk_id else "")
            edit_name.setStyleSheet("background-color: #2b2d42; color: #edf2f4; border: 1px solid #4cc9f0; border-radius: 4px; padding: 5px 8px; font-weight: bold; font-size: 12px;")

            edit_role = QLineEdit()
            edit_role.setPlaceholderText("Rola / Dział (np. Kierownik, Sprzedaż, IT)...")
            edit_role.setStyleSheet("background-color: #2b2d42; color: #f59e0b; border: 1px solid #f59e0b; border-radius: 4px; padding: 5px 8px; font-size: 11px;")

            self.speaker_inputs[spk_id] = {
                "name": edit_name,
                "role": edit_role
            }

            input_row.addWidget(edit_name, stretch=3)
            input_row.addWidget(edit_role, stretch=2)
            card_layout.addLayout(input_row)

            # Dolny wiersz: Wskazówka kontekstowa z dowodem oraz próbka wypowiedzi
            bottom_row = QHBoxLayout()
            bottom_row.setSpacing(10)

            lbl_clue = QLabel(f"💡 {clue}")
            lbl_clue.setStyleSheet("color: #4cc9f0; font-size: 11px;")
            lbl_clue.setWordWrap(True)

            lbl_sample = QLabel(f"Próbka: <i>„{sample_text}”</i>" if sample_text else "")
            lbl_sample.setStyleSheet("color: #8d99ae; font-size: 11px;")
            lbl_sample.setWordWrap(True)

            bottom_row.addWidget(lbl_clue, stretch=2)
            bottom_row.addWidget(lbl_sample, stretch=3)
            card_layout.addLayout(bottom_row)

            self.speaker_rows_layout.addWidget(card_frame)

        self.speaker_box.setVisible(True)

    def _on_apply_speakers_clicked(self):
        """
        Zatwierdza nowe nazwy i role mówców wprowadzone przez użytkownika i aktualizuje podgląd oraz plik TXT.
        """
        if not self.current_turns:
            return

        mapping = {}
        for spk_id, fields in self.speaker_inputs.items():
            if isinstance(fields, dict):
                name_val = fields["name"].text().strip()
                role_val = fields["role"].text().strip()
                
                # Scalanie: np. "Łukasz (emanager)" lub samo "Łukasz"
                if name_val and role_val:
                    label = f"{name_val} ({role_val})"
                elif name_val:
                    label = name_val
                elif role_val:
                    label = f"{spk_id} ({role_val})"
                else:
                    label = spk_id
            else:
                val = fields.text().strip()
                label = val if val else spk_id

            mapping[spk_id] = label

        # Zaktualizuj etykiety mówców w turns
        for t in self.current_turns:
            orig_spk = t.get("speaker")
            if orig_spk in mapping:
                t["speaker"] = mapping[orig_spk]

        html_text, plain_text = format_turns(self.current_turns, mapping)
        self.text_transcript.setHtml(html_text)
        self.last_plain_text = plain_text

        if self.current_txt_path:
            try:
                with open(self.current_txt_path, 'w', encoding='utf-8') as f:
                    f.write(plain_text)
                self._refresh_transcriptions_list()

                # Ponowna synchronizacja z chmurą ze zweryfikowanymi imionami
                self._trigger_cloud_sync(
                    plain_text=plain_text,
                    turns=self.current_turns,
                    audio_path=self.last_audio_save_path,
                    title=f"Zweryfikowano: {os.path.basename(self.current_txt_path or 'Spotkanie')}",
                    silent=False
                )

                QMessageBox.information(
                    self,
                    "Zaktualizowano Mówców",
                    "Pomyślnie zaktualizowano imiona mówców w podglądzie, pliku TXT oraz przesłano aktualizację do chmury!"
                )
            except Exception as e:
                QMessageBox.warning(self, "Błąd Zapisu", f"Nie udało się zaktualizować pliku TXT:\n{e}")

    def _trigger_cloud_sync(self, plain_text: str, turns: list, audio_path: Optional[str] = None, title: Optional[str] = None, silent: bool = False):
        """Wysyła sesję do menedżera synchronizacji CloudSyncManager."""
        if not plain_text or not plain_text.strip():
            if not silent:
                QMessageBox.warning(self, "Brak Treści", "Brak tekstu transkrypcji do wysłania.")
            return

        # Rzeczywista długość nagrania: priorytet 1 to plik audio, priorytet 2 stoper, priorytet 3 ostatni segment
        duration = 0.0
        if audio_path and os.path.exists(audio_path):
            try:
                import soundfile as sf
                info = sf.info(audio_path)
                duration = float(info.duration)
            except Exception:
                pass

        if duration <= 0.0 and self.recorded_seconds > 0:
            duration = float(self.recorded_seconds)

        if duration <= 0.0 and turns:
            try:
                duration = max(float(t.get("end", 0.0)) for t in turns)
            except Exception:
                pass

        # Przekształć turns na segmenty dla API
        segments = []
        for t in (turns or []):
            segments.append({
                "speaker": t.get("speaker", "Mówca"),
                "start": t.get("start", 0.0),
                "end": t.get("end", 0.0),
                "text": t.get("text", "")
            })

        self.current_meeting_id = self.cloud_sync.sync_meeting_async(
            title=title or f"Spotkanie {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            transcript_text=plain_text,
            segments=segments,
            duration_seconds=duration,
            audio_path=audio_path,
            context_type="general",
            meeting_id=self.current_meeting_id
        )

        # Zapisz meeting_id do pliku sesji JSON, aby późniejsze operacje (np. modułowa diaryzacja) aktualizowały dokładnie ten sam rekord
        if getattr(self, "current_txt_path", None):
            try:
                json_path = get_session_path_for_txt(self.current_txt_path)
                sess = TranscriptionSession.load_from_json(json_path) or TranscriptionSession()
                sess.meeting_id = self.current_meeting_id
                sess.save_to_json(json_path)
            except Exception:
                pass

    def _on_manual_sync_clicked(self):
        """Ręczne wywołanie wysyłki z przycisku w UI."""
        if not self.last_plain_text:
            QMessageBox.warning(self, "Brak Transkrypcji", "Wykonaj nagranie lub wczytaj transkrypcję przed wysłaniem.")
            return

        self._trigger_cloud_sync(
            plain_text=self.last_plain_text,
            turns=self.current_turns,
            audio_path=self.last_audio_save_path,
            title=f"Ręczny Eksport: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            silent=False
        )

    def _on_sync_started(self, meeting_id: str):
        target_name = self.cloud_sync.config.get("sync_target", "emanager").upper()
        self.lbl_cloud_status.setText(f"☁️ Synchronizacja z {target_name} w toku...")
        self.lbl_cloud_status.setStyleSheet("color: #f59e0b; font-size: 11px; font-weight: bold;")
        self.btn_manual_sync.setEnabled(False)

    def _on_sync_finished(self, meeting_id: str, success: bool, message: str):
        target_name = self.cloud_sync.config.get("sync_target", "emanager").upper()
        self.btn_manual_sync.setEnabled(True)
        if success:
            self.lbl_cloud_status.setText(f"☁️ Zsynchronizowano z {target_name} ✅")
            self.lbl_cloud_status.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold;")
        else:
            self.lbl_cloud_status.setText(f"☁️ Zapisano lokalnie (kolejka offline)")
            self.lbl_cloud_status.setStyleSheet("color: #f59e0b; font-size: 11px; font-weight: bold;")

    def _on_offline_queued(self, meeting_id: str, message: str):
        self.lbl_cloud_status.setText(f"☁️ Zapisano w kolejce offline ⏳")
        self.lbl_cloud_status.setStyleSheet("color: #f59e0b; font-size: 11px; font-weight: bold;")
        self.btn_manual_sync.setEnabled(True)

    def _on_live_session_started(self, meeting_id: str):
        target_name = self.cloud_sync.config.get("sync_target", "CRM").upper()
        self.lbl_cloud_status.setText(f"🟢 Transmisja na żywo do {target_name} aktywna (ID: {meeting_id[:8]}...)")
        self.lbl_cloud_status.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold;")

    def _on_live_block_synced(self, meeting_id: str, count: int):
        target_name = self.cloud_sync.config.get("sync_target", "CRM").upper()
        self.lbl_cloud_status.setText(f"🟢 Transmisja do {target_name}: +{count} wypowiedzi na żywo")
        self.lbl_cloud_status.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold;")

    def _on_live_session_finalized(self, meeting_id: str, success: bool, msg: str):
        target_name = self.cloud_sync.config.get("sync_target", "CRM").upper()
        if success:
            self.lbl_cloud_status.setText(f"☁️ Zakończono sesję w {target_name} ✅")
            self.lbl_cloud_status.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold;")
        else:
            self.lbl_cloud_status.setText(f"☁️ Sesja zapisana lokalnie (kolejka offline)")
            self.lbl_cloud_status.setStyleSheet("color: #f59e0b; font-size: 11px; font-weight: bold;")

    def _on_session_split_triggered(self, reason: str):
        """
        Automatycznie zamyka bieżące spotkanie (upload audio do Storage, status='completed')
        i rozpoczyna nowe spotkanie w Supabase bez przerywania ciągłego nasłuchu mikrofonu.
        """
        print(f"[SMART SESSION] Podział sesji wywołany przez: {reason}")
        # 1. Finalizacja poprzedniej sesji w Supabase
        if self.current_meeting_id and self.last_plain_text:
            self.cloud_sync.finalize_live_session_async(
                meeting_id=self.current_meeting_id,
                final_transcript=self.last_plain_text,
                duration_seconds=float(self.recorded_seconds),
                audio_path=getattr(self, "current_live_wav_path", None),
                turns=self.current_turns,
                title=f"Spotkanie biurowe {getattr(self, 'current_live_timestamp', '')}"
            )

        # 2. Generowanie nowych ścieżek dla kolejnego spotkania
        new_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_live_timestamp = new_timestamp
        self.current_live_wav_path = os.path.join(self.recordings_dir, f"inteligentne_nagranie_{new_timestamp}.wav")
        self.current_live_txt_path = os.path.join(self.transcriptions_dir, f"transkrypcja_{new_timestamp}.txt")
        try:
            with open(self.current_live_txt_path, 'w', encoding='utf-8') as f:
                f.write(f"=== NOWE SPOTKANIE BIUROWE (Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===\n\n")
            self._refresh_transcriptions_list()
        except Exception:
            pass

        # 3. Rotacja rejestratora audio i transkrypcji w tle
        self.worker.rotate_session_file(self.current_live_wav_path)
        if hasattr(self, "rolling_worker") and self.rolling_worker is not None:
            self.rolling_worker.reset_for_new_session(self.current_live_txt_path)

        self.synced_segment_count = 0
        self.current_turns = []
        self.last_plain_text = ""
        self.recorded_seconds = 0
        self.lbl_timer.setText("00:00:00")

        # 4. Start nowej sesji w Supabase
        if self.cloud_sync.config.get("live_streaming") and self.cloud_sync.config.get("auto_sync"):
            self.current_meeting_id = self.cloud_sync.start_live_session_async(
                title=f"Spotkanie biurowe {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )

        target_name = self.cloud_sync.config.get("sync_target", "CRM").upper()
        self.lbl_cloud_status.setText(f"🟢 Nowa sesja spotkania w {target_name} ({reason})")
        self.lbl_cloud_status.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold;")

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

            json_path = get_session_path_for_txt(full_path)
            badge = ""
            if os.path.exists(json_path):
                sess = TranscriptionSession.load_from_json(json_path)
                if sess:
                    badge = f"  {sess.get_status_badge()}"

            item = QListWidgetItem(f"📄 {filename}{badge}  ({size_kb:.1f} KB, {mtime})")
            item.setData(Qt.ItemDataRole.UserRole, full_path)
            self.list_transcriptions.addItem(item)

    def _on_run_diarization_clicked(self):
        """Uruchamia modułową analizę mówców (PyAnnote) dla zaznaczonego nagrania bez ponownego uruchamiania Whispera."""
        target_txt = None
        current_item = self.list_transcriptions.currentItem()
        if current_item:
            target_txt = current_item.data(Qt.ItemDataRole.UserRole)
        elif self.current_txt_path and os.path.exists(self.current_txt_path):
            target_txt = self.current_txt_path

        if not target_txt or not os.path.exists(target_txt):
            QMessageBox.warning(self, "Wybierz Transkrypcję", "Wybierz z listy po prawej stronie transkrypcję, dla której chcesz wykonać podział na mówców.")
            return

        token = self.input_token.text().strip()
        if not token:
            QMessageBox.warning(
                self,
                "Wymagany Token HuggingFace",
                "Do uruchomienia modułu diaryzacji PyAnnote wymagany jest bezpłatny token HuggingFace.\n\n"
                "Wklej swój token w polu 'HuggingFace Token' i spróbuj ponownie."
            )
            self.input_token.setFocus()
            return

        # Poszukiwanie odpowiadającego pliku audio WAV i sesji JSON
        json_path = get_session_path_for_txt(target_txt)
        session = TranscriptionSession.load_from_json(json_path) if os.path.exists(json_path) else None

        wav_path = None
        if session and session.prepared_wav and os.path.exists(session.prepared_wav):
            wav_path = session.prepared_wav
        elif session and session.source_audio and os.path.exists(session.source_audio):
            wav_path = session.source_audio
        else:
            # Dopasowanie po nazwie pliku w katalogu recordings/
            txt_basename = os.path.basename(target_txt)
            clean_stem = txt_basename.replace("transkrypcja_", "").replace(".txt", "")
            for rec_name in os.listdir(self.recordings_dir):
                if clean_stem in rec_name and rec_name.endswith(".wav"):
                    wav_path = os.path.join(self.recordings_dir, rec_name)
                    break

        if not wav_path or not os.path.exists(wav_path):
            # Użytkownik może wskazać plik audio ręcznie
            QMessageBox.information(
                self,
                "Wskaż Plik Audio",
                f"Nie odnaleziono automatycznie pliku nagrania dla:\n{os.path.basename(target_txt)}\n\n"
                "Wskaż plik audio (.wav, .mp3, .m4a) odpowiadający tej transkrypcji."
            )
            wav_path, _ = QFileDialog.getOpenFileName(
                self,
                "Wybierz plik audio do diaryzacji",
                self.recordings_dir,
                "Pliki Audio (*.wav *.mp3 *.m4a *.flac *.ogg);;Wszystkie (*.*)"
            )
            if not wav_path:
                return

        # Pobranie słów z sesji JSON lub estymacja z pliku TXT
        words = []
        if session and session.words:
            words = session.words
        else:
            try:
                with open(target_txt, 'r', encoding='utf-8') as f:
                    txt_content = f.read()
                parsed_turns = parse_txt_to_turns(txt_content)
                for t in parsed_turns:
                    t_words = t.get("text", "").split()
                    st = t.get("start", 0.0)
                    en = t.get("end", st + 1.0)
                    dur = (en - st) / max(1, len(t_words))
                    for i, w_str in enumerate(t_words):
                        words.append({
                            "word": (" " + w_str if i > 0 else w_str),
                            "start": round(st + (i * dur), 2),
                            "end": round(st + ((i + 1) * dur), 2),
                            "probability": 0.95
                        })
            except Exception:
                pass

        if not words:
            QMessageBox.warning(self, "Brak Treści", "Nie udało się odczytać słów z wybranej transkrypcji.")
            return

        spk_cfg = self.combo_speakers.currentData() or {}
        num_spk = spk_cfg.get("num_speakers")
        min_spk = spk_cfg.get("min_speakers")
        max_spk = spk_cfg.get("max_speakers")

        # Blokowanie kontrolek
        self.btn_start.setEnabled(False)
        self.btn_upload.setEnabled(False)
        self.btn_run_diarization.setEnabled(False)
        self.progress_transcription.setValue(5)
        self.progress_transcription.setFormat("Uruchamianie analizy osób PyAnnote (w tle)...")

        self.current_txt_path = target_txt
        self.last_audio_save_path = wav_path
        if session and getattr(session, "meeting_id", None):
            self.current_meeting_id = session.meeting_id
        elif wav_path:
            stem = os.path.splitext(os.path.basename(wav_path))[0].replace("inteligentne_nagranie_", "")
            self.current_meeting_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"recorder67_{stem}"))

        self.diarization_thread = DiarizationOnlyWorker(
            audio_path=wav_path,
            transcript_words=words,
            hf_token=token,
            session_json_path=json_path,
            num_speakers=num_spk,
            min_speakers=min_spk,
            max_speakers=max_spk
        )
        self._active_threads.append(self.diarization_thread)
        self.diarization_thread.progress_signal.connect(self._on_file_progress)
        self.diarization_thread.finished_signal.connect(self._on_diarization_only_finished)
        self.diarization_thread.error_signal.connect(self._on_transcription_error)
        self.diarization_thread.start()

    def _on_diarization_only_finished(self, html_text: str, plain_text: str, turns: list, session_path: str):
        if hasattr(self, "diarization_thread") and self.diarization_thread in self._active_threads:
            self._active_threads.remove(self.diarization_thread)

        self.progress_transcription.setValue(100)
        self.progress_transcription.setFormat("Diaryzacja mówców zakończona pomyślnie!")
        self.text_transcript.setHtml(html_text)
        self.current_turns = turns or []
        self.last_plain_text = plain_text

        # Aktualizacja pliku TXT
        if self.current_txt_path:
            try:
                with open(self.current_txt_path, 'w', encoding='utf-8') as f:
                    f.write(plain_text)
            except Exception:
                pass

        # Odświeżenie UI i panelu weryfikacji
        self._refresh_transcriptions_list()
        self._populate_speaker_mapping(self.current_turns)

        self.btn_start.setEnabled(True)
        self.btn_upload.setEnabled(True)
        self.btn_run_diarization.setEnabled(True)
        self.btn_manual_sync.setEnabled(True)

        # Bezpieczna synchronizacja z chmurą / EMANAGER.PRO (aktualizacja rekordów mówców metodą PATCH)
        if self.cloud_sync.config.get("auto_sync"):
            self._trigger_cloud_sync(
                plain_text=plain_text,
                turns=self.current_turns,
                audio_path=self.last_audio_save_path,
                title=None,
                silent=True
            )

        QMessageBox.information(
            self,
            "Diaryzacja Zakończona",
            f"Pomyślnie wykonano podział na mówców!\n\n"
            f"Wykryto osób: {len(set(t.get('speaker') for t in turns if t.get('speaker')))}\n"
            f"Zaktualizowano plik:\n{os.path.basename(self.current_txt_path or '')}"
        )

    def _on_transcription_double_clicked(self, item):
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                turns = parse_txt_to_turns(content)
                self.current_turns = turns or []
                self.last_plain_text = content
                self.current_txt_path = file_path

                # Odczytaj meeting_id z sesji JSON lub wylicz deterministyczny identyfikator
                json_path = get_session_path_for_txt(file_path)
                sess = TranscriptionSession.load_from_json(json_path) if os.path.exists(json_path) else None
                if sess and getattr(sess, "meeting_id", None):
                    self.current_meeting_id = sess.meeting_id
                elif sess and getattr(sess, "prepared_wav", None):
                    self.last_audio_save_path = sess.prepared_wav
                    stem = os.path.splitext(os.path.basename(sess.prepared_wav))[0].replace("inteligentne_nagranie_", "")
                    self.current_meeting_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"recorder67_{stem}"))
                else:
                    txt_stem = os.path.splitext(os.path.basename(file_path))[0].replace("transkrypcja_", "")
                    self.current_meeting_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"recorder67_{txt_stem}"))

                if turns:
                    self._populate_speaker_mapping(turns)
                    html_content, _ = format_turns(turns)
                    self.text_transcript.setHtml(html_content)
                else:
                    self.speaker_box.setVisible(False)
                    html_content = content.replace("\n", "<br>")
                    self.text_transcript.setHtml(html_content)

                self.btn_manual_sync.setEnabled(True)
                target_name = self.cloud_sync.config.get("sync_target", "emanager").upper()
                self.lbl_cloud_status.setText(f"☁️ Wczytano plik: {os.path.basename(file_path)} (Gotowy do wysłania)")
                self.lbl_cloud_status.setStyleSheet("color: #4cc9f0; font-size: 11px; font-weight: bold;")
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
        self.combo_devices.setEnabled(True)
        self.combo_models.setEnabled(True)
        self.btn_auto_detect.setEnabled(True)
        self.check_enable_diarization.setEnabled(True)
        is_diar = self.check_enable_diarization.isChecked()
        self.combo_speakers.setEnabled(is_diar)
        self.input_token.setEnabled(is_diar)

    def _on_timer_tick(self):
        # Czas nagrania (stoper i pasek) nalicza się TYLKO gdy mowa jest aktywnie nagrywana
        is_active_recording = self.worker.state in [SmartRecordState.RECORDING_SPEECH, SmartRecordState.RECORDING_SILENCE_COUNTDOWN]

        if is_active_recording:
            self.recorded_seconds += 1
            hrs = self.recorded_seconds // 3600
            mins = (self.recorded_seconds % 3600) // 60
            secs = self.recorded_seconds % 60
            self.lbl_timer.setText(f"{hrs:02d}:{mins:02d}:{secs:02d}")

            if getattr(self, "rolling_worker", None) is not None:
                self.rolling_worker.update_session_time(self.recorded_seconds)
                proc_sec = self.rolling_worker.total_processed_seconds
                if proc_sec > 0:
                    pct = int(min(98, max(5, (proc_sec / max(1.0, float(self.recorded_seconds))) * 100)))
                    p_min, p_sec = int(proc_sec // 60), int(proc_sec % 60)
                    t_min, t_sec = int(self.recorded_seconds // 60), int(self.recorded_seconds % 60)
                    self.progress_transcription.setValue(pct)
                    self.progress_transcription.setFormat(f"🟢 Przetworzono w tle: {p_min:02d}:{p_sec:02d} / {t_min:02d}:{t_sec:02d} ({pct}%)")
                else:
                    # Informacja o aktywnym buforowaniu mowy przed zamknięciem pierwszego bloku (min. 2 min)
                    t_min, t_sec = int(self.recorded_seconds // 60), int(self.recorded_seconds % 60)
                    if self.recorded_seconds < 120:
                        pct = int((self.recorded_seconds / 120.0) * 100)
                        self.progress_transcription.setValue(min(95, max(5, pct)))
                        self.progress_transcription.setFormat(f"🎙️ Zbieranie mowy do bloku #1: {t_min:02d}:{t_sec:02d} / 02:00...")
                    else:
                        self.progress_transcription.setValue(95)
                        self.progress_transcription.setFormat(f"🎙️ Nagrywanie: {t_min:02d}:{t_sec:02d} (Oczekiwanie na pauzę w mowie na cięcie bloku)...")
        elif self.worker.state == SmartRecordState.AUTO_PAUSED:
            # W stanie Auto-Pauzy stoper stoi w miejscu i pasek nie ucieka do przodu
            t_min, t_sec = int(self.recorded_seconds // 60), int(self.recorded_seconds % 60)
            proc_sec = getattr(self.rolling_worker, "total_processed_seconds", 0.0) if getattr(self, "rolling_worker", None) else 0.0
            if proc_sec > 0:
                p_min, p_sec = int(proc_sec // 60), int(proc_sec % 60)
                self.progress_transcription.setFormat(f"⏸️ Auto-Pauza (Cisza): {p_min:02d}:{p_sec:02d} / {t_min:02d}:{t_sec:02d}")
            else:
                self.progress_transcription.setFormat(f"⏸️ Auto-Pauza (Cisza): {t_min:02d}:{t_sec:02d} nagrania")

    def _update_audio_level(self, level):
        try:
            if level is None or level != level:
                val = 0
            else:
                val = int(max(0.0, min(100.0, float(level))))
            self.progress_vu.setValue(val)
        except Exception:
            self.progress_vu.setValue(0)

    def _update_vad_info(self, is_speech, speech_prob, current_silence_sec):
        if self.worker.state == SmartRecordState.MANUAL_PAUSED:
            self.progress_silence.setValue(0)
            self.lbl_vad_detail.setText("⏸ Nagrywanie wstrzymane ręcznie (kliknij 'Wznów Nagrywanie', aby kontynuować)")
            self.lbl_vad_detail.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 11px;")
            return

        try:
            threshold = float(self.slider_silence.value())
            if current_silence_sec is None or current_silence_sec != current_silence_sec:
                current_silence_sec = 0.0
            val_tenths = int(max(0.0, min(float(current_silence_sec), threshold)) * 10)
            self.progress_silence.setValue(val_tenths)
            self.lbl_silence_val.setText(f"{float(current_silence_sec):.1f} s / {threshold:.1f} s")
        except Exception:
            self.progress_silence.setValue(0)

        vad_mode_str = "Silero VAD AI" if is_silero_available() else "Detekcja Energii"
        prob_pct = int(speech_prob * 100) if (speech_prob and speech_prob == speech_prob) else 0
        if is_speech:
            self.lbl_vad_detail.setText(f"🗣️ VAD: DETEKCJA MOWY ({prob_pct}% pewności AI, Tryb: {vad_mode_str})")
            self.lbl_vad_detail.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px;")
        else:
            self.lbl_vad_detail.setText(f"🔇 VAD: Cisza / Szum tła ({prob_pct}% pewności AI, Tryb: {vad_mode_str})")
            self.lbl_vad_detail.setStyleSheet("color: #8d99ae; font-size: 11px;")

    def _on_worker_state_changed(self, state):
        thresh_val = self.slider_silence.value()
        if state == SmartRecordState.STOPPED:
            self.lbl_status_badge.setText("ZATRZYMANY")
            self.lbl_status_badge.setObjectName("StatusStopped")
            self.btn_pause.setText("⏸ Wstrzymaj Ręcznie")
            self.btn_pause.setObjectName("BtnPause")
        elif state == SmartRecordState.RECORDING_SPEECH:
            self.lbl_status_badge.setText("🟢 NAGRYWANIE (WYKRYTO MOWĘ)")
            self.lbl_status_badge.setObjectName("StatusSpeech")
            self.btn_pause.setText("⏸ Wstrzymaj Ręcznie")
            self.btn_pause.setObjectName("BtnPause")
        elif state == SmartRecordState.RECORDING_SILENCE_COUNTDOWN:
            self.lbl_status_badge.setText("⏳ ODLICZANIE BRAKU MOWY (NAGRYWANIE)")
            self.lbl_status_badge.setObjectName("StatusCountdown")
            self.btn_pause.setText("⏸ Wstrzymaj Ręcznie")
            self.btn_pause.setObjectName("BtnPause")
        elif state == SmartRecordState.AUTO_PAUSED:
            self.lbl_status_badge.setText(f"🟡 AUTOMATYCZNIE WSTRZYMANO (BRAK MOWY > {thresh_val}s)")
            self.lbl_status_badge.setObjectName("StatusAutoPaused")
            self.btn_pause.setText("⏸ Wstrzymaj Ręcznie")
            self.btn_pause.setObjectName("BtnPause")
        elif state == SmartRecordState.MANUAL_PAUSED:
            self.lbl_status_badge.setText("⏸ WSTRZYMANO RĘCZNIE")
            self.lbl_status_badge.setObjectName("StatusManualPaused")
            self.btn_pause.setText("▶ Wznów Nagrywanie")
            self.btn_pause.setObjectName("BtnResume")

        self.lbl_status_badge.style().unpolish(self.lbl_status_badge)
        self.lbl_status_badge.style().polish(self.lbl_status_badge)
        self.lbl_status_badge.update()

        self.btn_pause.style().unpolish(self.btn_pause)
        self.btn_pause.style().polish(self.btn_pause)
        self.btn_pause.update()

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
        try:
            self.timer.stop()
            if self.worker.state != SmartRecordState.STOPPED:
                self.worker.stop_recording()
            self.worker.wait(1000)

            if self.live_transcription_worker is not None:
                self.live_transcription_worker.stop()
                self.live_transcription_worker.wait(1000)
                self.live_transcription_worker = None

            if self.transcription_thread is not None and self.transcription_thread.isRunning():
                self.transcription_thread.quit()
                self.transcription_thread.wait(1000)

            if self.file_processing_worker is not None and self.file_processing_worker.isRunning():
                self.file_processing_worker.quit()
                self.file_processing_worker.wait(1000)
        except Exception:
            pass
        event.accept()
