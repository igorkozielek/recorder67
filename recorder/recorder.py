"""
Wrapper kompatybilności wstecznej dla projektu recorder67.
Projekt został podzielony na moduły:
- recorder/config.py
- recorder/core/ (vad.py, transcriber.py, diarizer.py)
- recorder/audio/ (devices.py, converter.py, capture.py)
- recorder/ui/ (window.py, workers.py, theme.py)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recorder.ui.window import SmartDictaphoneWindow
from recorder.ui.workers import SmartAudioWorker, LiveTranscriptionWorker, TranscriptionWorker
from recorder.config import SmartRecordState
from recorder.audio.devices import get_working_input_devices
from recorder.audio.converter import resample_to_16k
from recorder.audio.capture import save_wav_file

from PyQt6.QtWidgets import QApplication


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
