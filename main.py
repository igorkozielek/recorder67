import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from recorder.ui.theme import setup_dark_palette, DARK_THEME_QSS
from recorder.ui.window import SmartDictaphoneWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Inteligentny Dyktafon AI")
    setup_dark_palette(app)
    app.setStyleSheet(DARK_THEME_QSS)
    window = SmartDictaphoneWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
