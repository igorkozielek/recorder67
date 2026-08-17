"""
Style QSS oraz definicje wizualne dla aplikacji Recorder67.
"""

DARK_THEME_QSS = """
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
