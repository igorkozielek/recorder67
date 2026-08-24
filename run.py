"""
Główny punkt wejścia aplikacji Inteligentnego Dyktafonu AI.
"""

import sys
import os

# Dodaj katalog główny do ścieżki Pythona
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Automatyczne łatki kompatybilności PyTorch i torchaudio
try:
    from recorder.core.diarizer import apply_torchaudio_patches
    apply_torchaudio_patches()
except Exception:
    pass

from recorder.main import main

if __name__ == "__main__":
    main()
