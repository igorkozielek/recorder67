import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    from PyQt6.QtWidgets import QApplication

from recorder.ui.window import SmartDictaphoneWindow


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
