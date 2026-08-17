"""
Style QSS oraz definicje wizualne dla aplikacji Recorder67.
Wymusza spójny, profesjonalny ciemny motyw niezależnie od ustawień motywu w systemie Windows.
"""

try:
    from PySide6.QtGui import QPalette, QColor
    from PySide6.QtWidgets import QApplication
except ImportError:
    from PyQt6.QtGui import QPalette, QColor
    from PyQt6.QtWidgets import QApplication

DARK_THEME_QSS = """
/* Główne okna i kontenery bazowe */
QMainWindow, QDialog, QMessageBox {
    background-color: #111216;
    color: #edf2f4;
}

QScrollArea, 
QScrollArea > QWidget, 
QScrollArea > QWidget > QWidget, 
QScrollArea QWidget#MainContainerWidget {
    background-color: #111216;
    border: none;
}

QWidget {
    color: #edf2f4;
    font-family: 'Segoe UI', sans-serif;
}

/* Suwaki przewijania (Scrollbary) */
QScrollBar:vertical {
    border: none;
    background: #111216;
    width: 10px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #2b2e3d;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #3b4055;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: none;
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    border: none;
    background: #111216;
    height: 10px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background: #2b2e3d;
    min-width: 20px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal:hover {
    background: #3b4055;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    border: none;
    background: none;
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}

/* Panele i ramki */
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
QComboBox QAbstractItemView {
    background-color: #222533;
    border: 1px solid #33374c;
    selection-background-color: #33374c;
    color: #edf2f4;
}

QFrame#DisplayFrame {
    background-color: #171820;
    border: 1px solid #272a38;
    border-radius: 10px;
}

/* Etykiety statusu nagrywania */
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

/* Paski postępu */
QProgressBar {
    background-color: #222533;
    border-radius: 5px;
    border: none;
    text-align: center;
    color: #edf2f4;
}
QProgressBar::chunk {
    background-color: #10b981;
    border-radius: 5px;
}
QProgressBar#SilenceProgress::chunk {
    background-color: #f59e0b;
    border-radius: 5px;
}

/* Przyciski sterowania */
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
QPushButton#BtnResume {
    background-color: #059669;
    border: none;
    color: #ffffff;
}
QPushButton#BtnResume:hover {
    background-color: #10b981;
}
QPushButton#BtnStop {
    background-color: #4b5563;
    border: none;
    color: #ffffff;
}
QPushButton#BtnStop:hover {
    background-color: #6b7280;
}

/* Listy plików */
QListWidget {
    background-color: #111216;
    border: 1px solid #272a38;
    border-radius: 6px;
    color: #edf2f4;
}
QListWidget::item {
    padding: 6px;
    border-bottom: 1px solid #171820;
}
QListWidget::item:hover {
    background-color: #222533;
}
QListWidget::item:selected {
    background-color: #272a38;
    color: #4cc9f0;
}

/* Suwak progu ciszy */
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

/* Pola edycyjne i tekstowe */
QLineEdit {
    background-color: #222533;
    border: 1px solid #33374c;
    border-radius: 6px;
    padding: 6px 10px;
    color: #edf2f4;
}
QLineEdit:focus {
    border-color: #4cc9f0;
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

/* Okna dialogowe i komunikaty */
QMessageBox QLabel {
    color: #edf2f4;
}
QToolTip {
    background-color: #222533;
    color: #edf2f4;
    border: 1px solid #33374c;
    padding: 4px;
    border-radius: 4px;
}
"""


def setup_dark_palette(app):
    """
    Konfiguruje spójną, ciemną paletę QPalette dla całej aplikacji Qt.
    Wymusza styl Fusion, zapobiegając jasnym tłom przy jasnym motywie systemu Windows.
    """
    try:
        app.setStyle("Fusion")
    except Exception:
        pass

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#111216"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#edf2f4"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#171820"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#222533"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#222533"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#edf2f4"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#edf2f4"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#222533"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#edf2f4"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#4cc9f0"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#111216"))
    
    # Obsługa wyszarzonych elementów
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#6b7280"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#6b7280"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#495057"))

    app.setPalette(palette)
