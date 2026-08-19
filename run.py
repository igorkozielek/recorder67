"""
Główny punkt wejścia aplikacji Inteligentnego Dyktafonu AI.
"""

import sys
import os

# Dodaj katalog główny do ścieżki Pythona
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recorder.main import main

if __name__ == "__main__":
    main()
