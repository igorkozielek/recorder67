import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from recorder.ui.windows_integration import setup_windows_app_identity, get_app_icon_path
from recorder.ui.theme import setup_dark_palette, DARK_THEME_QSS
from recorder.ui.window import SmartDictaphoneWindow


def main():
    setup_windows_app_identity()

    app = QApplication(sys.argv)
    app.setApplicationName("Inteligentny Dyktafon AI")
    app.setApplicationDisplayName("Inteligentny Dyktafon AI")

    ico_path = get_app_icon_path("ico")
    if ico_path and os.path.exists(ico_path):
        app.setWindowIcon(QIcon(ico_path))

    setup_dark_palette(app)
    app.setStyleSheet(DARK_THEME_QSS)
    window = SmartDictaphoneWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    ret = app.exec()
    sys.exit(ret)


if __name__ == "__main__":
    main()
