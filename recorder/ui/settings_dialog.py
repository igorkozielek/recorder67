import os
import sys
from typing import Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QWidget, QTextEdit, QComboBox,
    QSlider, QSpinBox, QCheckBox, QGroupBox, QFormLayout,
    QMessageBox, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal as pyqtSignal
from PySide6.QtGui import QFont, QIcon

from recorder.config import (
    load_user_settings,
    save_user_settings,
    WHISPER_MODELS,
    DEFAULT_WHISPER_MODEL
)


class SettingsDialog(QDialog):
    """
    Nowoczesne okno ustawień aplikacji:
    - Karta 1: Słownik branżowy (słowa kluczowe), wybór Beam Size Whispera, Token HuggingFace
    - Karta 2: Mikrofon, czułość Silero VAD, auto-pauza i dzielenie sesji
    - Karta 3: Integracja chmurowa (Supabase / EMANAGER.PRO / Webhook), nazwa stanowiska
    """
    settings_saved_signal = pyqtSignal(dict)

    PRESET_KEYWORDS_IT = (
        "emanager.pro, EMANAGER.PRO, CRM, AI, Supabase, n8n, Make, webhook, API, LLM, GPT-4, Claude, Gemini, "
        "Gemini Vision, Lovable, React, Helpdesk, Subiekt GT, Subiekt, faktura proforma, zamówienia, zgłoszenia, "
        "harmonogram, kategorie, dyplomy, matryca uprawnień, recepcja, check-in, QR code, CSV, oświetleniowiec, "
        "synchronizacja, rejestr zmian, diaryzacja, transkrypcja, procesy biznesowe, architektura wzrostu"
    )

    PRESET_KEYWORDS_SALES = (
        "oferta handlowa, kosztorys, negocjacje, umowa, aneks, marża, rabat, "
        "klient, spotkanie zarządu, termin płatności, faktura VAT, zamówienie"
    )

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Ustawienia Dyktafonu AI")
        self.setMinimumSize(640, 560)
        self.resize(680, 600)
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(14)

        # Nagłówek okna
        header_layout = QHBoxLayout()
        lbl_title = QLabel("⚙️ Konfiguracja & Preferencje AI")
        lbl_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #4cc9f0;")
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # Zakładki
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2b2d42;
                background-color: #1e1e2f;
                border-radius: 8px;
                padding: 12px;
            }
            QTabBar::tab {
                background: #181824;
                color: #8d99ae;
                padding: 8px 16px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: 500;
            }
            QTabBar::tab:selected {
                background: #2b2d42;
                color: #4cc9f0;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                color: #edf2f4;
            }
        """)

        self._create_tab_dictionary()
        self._create_tab_vad()
        self._create_tab_cloud()

        main_layout.addWidget(self.tabs, stretch=1)

        # Dolny pasek przycisków
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.btn_restore_defaults = QPushButton("🔄 Przywróć Domyślne")
        self.btn_restore_defaults.setStyleSheet("""
            QPushButton {
                background-color: #2b2d42;
                color: #8d99ae;
                border: 1px solid #3d405b;
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3d405b;
                color: #edf2f4;
            }
        """)
        self.btn_restore_defaults.clicked.connect(self._restore_defaults)
        btn_bar.addWidget(self.btn_restore_defaults)

        btn_bar.addStretch()

        self.btn_cancel = QPushButton("Anuluj")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #2b2d42;
                color: #edf2f4;
                border: 1px solid #3d405b;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3d405b;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("💾 Zapisz Ustawienia")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.btn_save.clicked.connect(self._save_and_accept)
        btn_bar.addWidget(self.btn_save)

        main_layout.addLayout(btn_bar)

    def _create_tab_dictionary(self):
        """Karta 1: Słownik branżowy, Beam Size Whispera, Token HuggingFace."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        # Sekcja: Słownik Branżowy
        box_dict = QGroupBox("📚 Słownik Słów Branżowych & Nazw Własnych (Initial Prompt)")
        box_dict.setStyleSheet("QGroupBox { font-weight: bold; color: #4cc9f0; border: 1px solid #2b2d42; border-radius: 6px; margin-top: 6px; padding-top: 12px; }")
        dict_layout = QVBoxLayout(box_dict)

        lbl_dict_info = QLabel(
            "Wpisz specyficzne nazwy firm, programów, procesorów lub pojęcia branżowe "
            "(oddzielone przecinkami). Model Whisper traktuje je jako priorytetowy kontekst fonetyczny:"
        )
        lbl_dict_info.setWordWrap(True)
        lbl_dict_info.setStyleSheet("color: #8d99ae; font-size: 11px;")
        dict_layout.addWidget(lbl_dict_info)

        self.txt_keywords = QTextEdit()
        self.txt_keywords.setPlaceholderText("np. Aldent, Subiekt GT, faktura proforma, i5-11400, CRM, Helpdesk...")
        self.txt_keywords.setMaximumHeight(90)
        self.txt_keywords.setStyleSheet("""
            QTextEdit {
                background-color: #181824;
                color: #edf2f4;
                border: 1px solid #2b2d42;
                border-radius: 6px;
                padding: 8px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QTextEdit:focus {
                border: 1px solid #4cc9f0;
            }
        """)
        dict_layout.addWidget(self.txt_keywords)

        # Przyciski szablonów
        preset_layout = QHBoxLayout()
        lbl_presets = QLabel("Szybkie szablony:")
        lbl_presets.setStyleSheet("color: #8d99ae; font-size: 11px;")
        preset_layout.addWidget(lbl_presets)

        btn_preset_it = QPushButton("+ Szablon IT & Biuro")
        btn_preset_it.setStyleSheet("background: #2b2d42; color: #4cc9f0; font-size: 11px; padding: 4px 8px; border-radius: 4px;")
        btn_preset_it.clicked.connect(lambda: self._append_preset(self.PRESET_KEYWORDS_IT))
        preset_layout.addWidget(btn_preset_it)

        btn_preset_sales = QPushButton("+ Szablon Sprzedaż")
        btn_preset_sales.setStyleSheet("background: #2b2d42; color: #4cc9f0; font-size: 11px; padding: 4px 8px; border-radius: 4px;")
        btn_preset_sales.clicked.connect(lambda: self._append_preset(self.PRESET_KEYWORDS_SALES))
        preset_layout.addWidget(btn_preset_sales)

        btn_clear_dict = QPushButton("Wyczyść")
        btn_clear_dict.setStyleSheet("background: #2b2d42; color: #e63946; font-size: 11px; padding: 4px 8px; border-radius: 4px;")
        btn_clear_dict.clicked.connect(self.txt_keywords.clear)
        preset_layout.addWidget(btn_clear_dict)

        preset_layout.addStretch()
        dict_layout.addLayout(preset_layout)
        layout.addWidget(box_dict)

        # Sekcja: Dokładność Whispera (Beam Size)
        box_whisper = QGroupBox("🎯 Precyzja Transkrypcji Whispera (Beam Search)")
        box_whisper.setStyleSheet("QGroupBox { font-weight: bold; color: #4cc9f0; border: 1px solid #2b2d42; border-radius: 6px; margin-top: 6px; padding-top: 12px; }")
        whisper_layout = QVBoxLayout(box_whisper)

        beam_row = QHBoxLayout()
        lbl_beam = QLabel("Tryb przeszukiwania hipotez (Beam Size):")
        lbl_beam.setStyleSheet("color: #edf2f4; font-size: 12px;")
        beam_row.addWidget(lbl_beam)

        self.combo_beam = QComboBox()
        self.combo_beam.addItem("⚡ Szybki (Beam Size = 1) - minimalne użycie CPU", 1)
        self.combo_beam.addItem("⚖️ Zrównoważony (Beam Size = 3) - dobry balans", 3)
        self.combo_beam.addItem("🚀 Maksymalna Dokładność (Beam Size = 5) [Zalecany]", 5)
        self.combo_beam.setStyleSheet("""
            QComboBox {
                background-color: #181824;
                color: #edf2f4;
                border: 1px solid #2b2d42;
                border-radius: 6px;
                padding: 6px 12px;
                min-width: 260px;
            }
        """)
        beam_row.addWidget(self.combo_beam)
        whisper_layout.addLayout(beam_row)

        lbl_beam_desc = QLabel(
            "Większy Beam Size analizuje kilka ścieżek zdań jednocześnie, całkowicie eliminując "
            "błędy fonetyczne i przekręcanie związków frazeologicznych bez widocznego narzutu na czas."
        )
        lbl_beam_desc.setWordWrap(True)
        lbl_beam_desc.setStyleSheet("color: #8d99ae; font-size: 11px;")
        whisper_layout.addWidget(lbl_beam_desc)
        layout.addWidget(box_whisper)

        # Sekcja: Token HuggingFace
        box_hf = QGroupBox("🔑 Dostęp do Rozpoznawania Osób (PyAnnote HuggingFace)")
        box_hf.setStyleSheet("QGroupBox { font-weight: bold; color: #4cc9f0; border: 1px solid #2b2d42; border-radius: 6px; margin-top: 6px; padding-top: 12px; }")
        hf_layout = QVBoxLayout(box_hf)

        hf_input_row = QHBoxLayout()
        self.txt_hf_token = QLineEdit()
        self.txt_hf_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_hf_token.setPlaceholderText("hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self.txt_hf_token.setStyleSheet("background-color: #181824; color: #edf2f4; border: 1px solid #2b2d42; border-radius: 6px; padding: 6px 10px;")
        hf_input_row.addWidget(self.txt_hf_token, stretch=1)

        self.btn_toggle_hf = QPushButton("👁️ Pokaż")
        self.btn_toggle_hf.setStyleSheet("background-color: #2b2d42; color: #edf2f4; border: 1px solid #3d405b; border-radius: 6px; padding: 6px 12px;")
        self.btn_toggle_hf.clicked.connect(self._toggle_hf_visibility)
        hf_input_row.addWidget(self.btn_toggle_hf)
        hf_layout.addLayout(hf_input_row)

        lbl_hf_info = QLabel("Token wymagany do pobrania modeli diaryzacji mowy (pyannote/speaker-diarization-3.1).")
        lbl_hf_info.setStyleSheet("color: #8d99ae; font-size: 11px;")
        hf_layout.addWidget(lbl_hf_info)
        layout.addWidget(box_hf)

        layout.addStretch()
        self.tabs.addTab(tab, "📚 Słownik i AI")

    def _create_tab_vad(self):
        """Karta 2: Mikrofon, czułość VAD i czasy pauz."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        box_vad = QGroupBox("🎙️ Czułość Detekcji Mowy Silero VAD")
        box_vad.setStyleSheet("QGroupBox { font-weight: bold; color: #4cc9f0; border: 1px solid #2b2d42; border-radius: 6px; margin-top: 6px; padding-top: 12px; }")
        vad_layout = QVBoxLayout(box_vad)

        slider_row = QHBoxLayout()
        self.slider_vad = QSlider(Qt.Orientation.Horizontal)
        self.slider_vad.setRange(20, 60)
        self.slider_vad.setValue(42)
        self.slider_vad.setTickInterval(5)
        self.slider_vad.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_vad.valueChanged.connect(self._on_vad_slider_changed)
        slider_row.addWidget(self.slider_vad, stretch=1)

        self.lbl_vad_val = QLabel("0.42 (Zalecany / Biuro)")
        self.lbl_vad_val.setStyleSheet("color: #10b981; font-weight: bold; min-width: 140px;")
        slider_row.addWidget(self.lbl_vad_val)
        vad_layout.addLayout(slider_row)

        lbl_vad_hint = QLabel(
            "Niższa wartość (0.20-0.30): Wykrywa bardzo cichy szept (dla cichych pomieszczeń).\n"
            "Wyższa wartość (0.45-0.60): Tłumi szum otoczenia, klikanie klawiatury i hałas z korytarza."
        )
        lbl_vad_hint.setStyleSheet("color: #8d99ae; font-size: 11px;")
        vad_layout.addWidget(lbl_vad_hint)
        layout.addWidget(box_vad)

        # Sekcja: Czasy i sesje
        box_time = QGroupBox("⏱️ Zarządzanie Ciszą i Sesjami Nagrywania")
        box_time.setStyleSheet("QGroupBox { font-weight: bold; color: #4cc9f0; border: 1px solid #2b2d42; border-radius: 6px; margin-top: 6px; padding-top: 12px; }")
        time_layout = QFormLayout(box_time)
        time_layout.setSpacing(12)

        self.spin_auto_pause = QSpinBox()
        self.spin_auto_pause.setRange(1, 15)
        self.spin_auto_pause.setValue(5)
        self.spin_auto_pause.setSuffix(" sek.")
        self.spin_auto_pause.setStyleSheet("background: #181824; color: #edf2f4; border: 1px solid #2b2d42; padding: 4px 8px; border-radius: 4px;")
        time_layout.addRow(QLabel("Czas ciszy do automatycznej pauzy:"), self.spin_auto_pause)

        self.combo_session_split = QComboBox()
        self.combo_session_split.addItem("10 minut ciągłej ciszy", 600.0)
        self.combo_session_split.addItem("15 minut ciągłej ciszy (Zalecane)", 900.0)
        self.combo_session_split.addItem("30 minut ciągłej ciszy", 1800.0)
        self.combo_session_split.addItem("1 godzina ciągłej ciszy", 3600.0)
        self.combo_session_split.addItem("Wyłączone (Zawsze jedna długa sesja)", 0.0)
        self.combo_session_split.setStyleSheet("background: #181824; color: #edf2f4; border: 1px solid #2b2d42; padding: 4px 8px; border-radius: 4px;")
        time_layout.addRow(QLabel("Automatyczny podział sesji biurowych:"), self.combo_session_split)

        self.combo_timestamp_format = QComboBox()
        self.combo_timestamp_format.addItem("Tylko offset [00:12 - 00:18] (Domyślne)", "offset_only")
        self.combo_timestamp_format.addItem("Offset + Godzina realna [00:12 | 13:47:12]", "offset+clock")
        self.combo_timestamp_format.addItem("Tylko godzina realna [13:47:12 - 13:47:18]", "clock_only")
        self.combo_timestamp_format.setStyleSheet("background: #181824; color: #edf2f4; border: 1px solid #2b2d42; padding: 4px 8px; border-radius: 4px;")
        time_layout.addRow(QLabel("Format timestampów w transkrypcji:"), self.combo_timestamp_format)

        layout.addWidget(box_time)
        layout.addStretch()
        self.tabs.addTab(tab, "🎙️ Mikrofon i VAD")

    def _create_tab_cloud(self):
        """Karta 3: Chmura, Supabase, Stanowisko i Webhook."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        box_ident = QGroupBox("💻 Identyfikacja Stanowiska Komputerowego")
        box_ident.setStyleSheet("QGroupBox { font-weight: bold; color: #4cc9f0; border: 1px solid #2b2d42; border-radius: 6px; margin-top: 6px; padding-top: 12px; }")
        ident_layout = QFormLayout(box_ident)

        self.txt_device_name = QLineEdit()
        self.txt_device_name.setPlaceholderText("np. Biuro-Adrian / Sala-Konferencyjna-1")
        self.txt_device_name.setStyleSheet("background: #181824; color: #edf2f4; border: 1px solid #2b2d42; padding: 6px 10px; border-radius: 6px;")
        ident_layout.addRow(QLabel("Nazwa Stanowiska:"), self.txt_device_name)

        self.txt_org_id = QLineEdit()
        self.txt_org_id.setPlaceholderText("default_org / emanager_main")
        self.txt_org_id.setStyleSheet("background: #181824; color: #edf2f4; border: 1px solid #2b2d42; padding: 6px 10px; border-radius: 6px;")
        ident_layout.addRow(QLabel("ID Organizacji:"), self.txt_org_id)
        layout.addWidget(box_ident)

        box_sync = QGroupBox("☁️ Cel Synchronizacji Chmurowej (CRM / n8n / Supabase)")
        box_sync.setStyleSheet("QGroupBox { font-weight: bold; color: #4cc9f0; border: 1px solid #2b2d42; border-radius: 6px; margin-top: 6px; padding-top: 12px; }")
        sync_layout = QFormLayout(box_sync)

        self.combo_sync_target = QComboBox()
        self.combo_sync_target.addItem("EMANAGER.PRO (Bezpośrednio do bazy Supabase)", "emanager")
        self.combo_sync_target.addItem("Własny Webhook (n8n / Make / Zapier)", "generic_webhook")
        self.combo_sync_target.addItem("Wyłączona (Tylko pliki lokalne)", "none")
        self.combo_sync_target.setStyleSheet("background: #181824; color: #edf2f4; border: 1px solid #2b2d42; padding: 6px 10px; border-radius: 6px;")
        sync_layout.addRow(QLabel("Cel wysyłki danych:"), self.combo_sync_target)

        self.txt_supabase_url = QLineEdit()
        self.txt_supabase_url.setPlaceholderText("https://xyz.supabase.co")
        self.txt_supabase_url.setStyleSheet("background: #181824; color: #edf2f4; border: 1px solid #2b2d42; padding: 6px 10px; border-radius: 6px;")
        sync_layout.addRow(QLabel("Adres Supabase URL:"), self.txt_supabase_url)

        self.txt_supabase_key = QLineEdit()
        self.txt_supabase_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_supabase_key.setPlaceholderText("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
        self.txt_supabase_key.setStyleSheet("background: #181824; color: #edf2f4; border: 1px solid #2b2d42; padding: 6px 10px; border-radius: 6px;")
        sync_layout.addRow(QLabel("Klucz Supabase Key:"), self.txt_supabase_key)

        self.txt_webhook_url = QLineEdit()
        self.txt_webhook_url.setPlaceholderText("https://twoj-serwer-n8n.pl/webhook/meeting-ingest")
        self.txt_webhook_url.setStyleSheet("background: #181824; color: #edf2f4; border: 1px solid #2b2d42; padding: 6px 10px; border-radius: 6px;")
        sync_layout.addRow(QLabel("Adres Webhook URL:"), self.txt_webhook_url)

        self.chk_auto_sync = QCheckBox("Automatycznie wysyłaj transkrypcję po zakończeniu nagrania")
        self.chk_auto_sync.setStyleSheet("color: #edf2f4;")
        sync_layout.addRow("", self.chk_auto_sync)

        self.chk_upload_audio = QCheckBox("Dołączaj plik dźwiękowy WAV do chmury (umożliwia odsłuch)")
        self.chk_upload_audio.setStyleSheet("color: #edf2f4;")
        sync_layout.addRow("", self.chk_upload_audio)

        layout.addWidget(box_sync)
        layout.addStretch()
        self.tabs.addTab(tab, "☁️ Chmura i Stanowisko")

    def _append_preset(self, preset_text: str):
        cur = self.txt_keywords.toPlainText().strip()
        if cur:
            if not cur.endswith(","):
                cur += ","
            self.txt_keywords.setPlainText(f"{cur} {preset_text}")
        else:
            self.txt_keywords.setPlainText(preset_text)

    def _toggle_hf_visibility(self):
        if self.txt_hf_token.echoMode() == QLineEdit.EchoMode.Password:
            self.txt_hf_token.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_toggle_hf.setText("🙈 Ukryj")
        else:
            self.txt_hf_token.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_toggle_hf.setText("👁️ Pokaż")

    def _on_vad_slider_changed(self, val: int):
        f_val = val / 100.0
        if f_val < 0.32:
            desc = f"{f_val:.2f} (Wysoka czułość / Szept)"
        elif f_val <= 0.45:
            desc = f"{f_val:.2f} (Zalecany / Biuro)"
        else:
            desc = f"{f_val:.2f} (Tłumienie hałasu)"
        self.lbl_vad_val.setText(desc)

    def _load_values(self):
        """Ładuje aktualne ustawienia do kontrolek UI."""
        st = load_user_settings()

        # Słownik i AI
        self.txt_keywords.setPlainText(st.get("custom_keywords", ""))
        beam_val = int(st.get("whisper_beam_size", 5))
        idx = self.combo_beam.findData(beam_val)
        if idx != -1:
            self.combo_beam.setCurrentIndex(idx)
        self.txt_hf_token.setText(st.get("hf_token", ""))

        # VAD & Mikrofon
        vad_val = int(float(st.get("vad_speech_threshold", 0.42)) * 100)
        self.slider_vad.setValue(vad_val)
        self._on_vad_slider_changed(vad_val)

        self.spin_auto_pause.setValue(int(float(st.get("auto_pause_sec", 5.0))))

        split_sec = float(st.get("session_split_silence_sec", 900.0))
        s_idx = self.combo_session_split.findData(split_sec)
        if s_idx != -1:
            self.combo_session_split.setCurrentIndex(s_idx)

        ts_fmt = st.get("timestamp_format", "offset_only")
        ts_idx = self.combo_timestamp_format.findData(ts_fmt)
        if ts_idx != -1:
            self.combo_timestamp_format.setCurrentIndex(ts_idx)

        # Chmura & Stanowisko
        self.txt_device_name.setText(st.get("device_name", "Biuro-Stanowisko-1"))
        self.txt_org_id.setText(st.get("organization_id", "default_org"))

        target = st.get("sync_target", "emanager")
        t_idx = self.combo_sync_target.findData(target)
        if t_idx != -1:
            self.combo_sync_target.setCurrentIndex(t_idx)

        self.txt_supabase_url.setText(st.get("supabase_url", ""))
        self.txt_supabase_key.setText(st.get("supabase_key", ""))
        self.txt_webhook_url.setText(st.get("generic_webhook_url", ""))
        self.chk_auto_sync.setChecked(bool(st.get("auto_cloud_sync", True)))
        self.chk_upload_audio.setChecked(bool(st.get("sync_upload_audio", False)))

    def _restore_defaults(self):
        """Przywraca zalecane wartości domyślne."""
        reply = QMessageBox.question(
            self,
            "Przywracanie Domyślnych",
            "Czy na pewno chcesz przywrócić domyślne ustawienia?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.txt_keywords.setPlainText(self.PRESET_KEYWORDS_IT)
            self.combo_beam.setCurrentIndex(self.combo_beam.findData(5))
            self.slider_vad.setValue(42)
            self.spin_auto_pause.setValue(5)
            self.combo_session_split.setCurrentIndex(self.combo_session_split.findData(900.0))
            self.combo_timestamp_format.setCurrentIndex(self.combo_timestamp_format.findData("offset_only"))
            self.chk_auto_sync.setChecked(True)
            self.chk_upload_audio.setChecked(False)

    def _save_and_accept(self):
        """Zapisuje wartości do pliku user_settings.json i zamyka dialog."""
        new_settings = {
            "custom_keywords": self.txt_keywords.toPlainText().strip(),
            "whisper_beam_size": int(self.combo_beam.currentData() or 5),
            "hf_token": self.txt_hf_token.text().strip(),
            "vad_speech_threshold": round(self.slider_vad.value() / 100.0, 2),
            "auto_pause_sec": float(self.spin_auto_pause.value()),
            "session_split_silence_sec": float(self.combo_session_split.currentData() or 900.0),
            "timestamp_format": self.combo_timestamp_format.currentData() or "offset_only",
            "device_name": self.txt_device_name.text().strip() or "Biuro-Stanowisko-1",
            "organization_id": self.txt_org_id.text().strip() or "default_org",
            "sync_target": self.combo_sync_target.currentData() or "emanager",
            "supabase_url": self.txt_supabase_url.text().strip(),
            "supabase_key": self.txt_supabase_key.text().strip(),
            "generic_webhook_url": self.txt_webhook_url.text().strip(),
            "auto_cloud_sync": self.chk_auto_sync.isChecked(),
            "sync_upload_audio": self.chk_upload_audio.isChecked(),
        }

        success = save_user_settings(new_settings)
        if success:
            self.settings_saved_signal.emit(new_settings)
            self.accept()
        else:
            QMessageBox.critical(self, "Błąd", "Nie udało się zapisać pliku ustawień user_settings.json.")
