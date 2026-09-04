"""
Główny punkt wejścia aplikacji Inteligentnego Dyktafonu AI.
"""

import sys
import os

# Dodaj katalog główny do ścieżki Pythona
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Inicjalizacja bezpiecznego logowania (przekierowanie stdout/stderr dla wersji bez konsoli)
try:
    from recorder.core.logger import setup_app_logging, log_system_diagnostics
    setup_app_logging()
    log_system_diagnostics()
except Exception:
    pass

try:
    from recorder.core.diarizer import apply_torchaudio_patches
    apply_torchaudio_patches()
except Exception as e:
    import logging
    logging.getLogger("recorder").warning(f"Nie udało się zaaplikować łatek torchaudio: {e}")

from recorder.main import main

if __name__ == "__main__":
    main()
