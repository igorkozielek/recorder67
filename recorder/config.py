import os
from pathlib import Path

# Ścieżki główne
BASE_DIR = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = os.path.join(os.getcwd(), "recordings")
TRANSCRIPTIONS_DIR = os.path.join(os.getcwd(), "transcriptions")

os.makedirs(RECORDINGS_DIR, exist_ok=True)
os.makedirs(TRANSCRIPTIONS_DIR, exist_ok=True)

# Parametry audio i VAD
SAMPLE_RATE = 16000  # Wymuszone 16000 Hz dla Silero VAD i Whisper
AUDIO_CHANNELS = 1
DEFAULT_AUTO_PAUSE_SEC = 5.0
VAD_SPEECH_THRESHOLD = 0.45
PRE_SPEECH_BUFFER_CHUNKS = 6  # ~0.2s próbek przed wyznaczoną mową
RMS_SILENCE_THRESHOLD = 0.003

# Stany nagrywania
class SmartRecordState:
    STOPPED = 0
    RECORDING_SPEECH = 1
    RECORDING_SILENCE_COUNTDOWN = 2
    AUTO_PAUSED = 3
    MANUAL_PAUSED = 4


def get_hf_token() -> str:
    """
    Pobiera token HuggingFace z pliku .env lub zmiennych środowiskowych.
    """
    # 1. Sprawdzenie zmiennej środowiskowej
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token:
        return token.strip()

    # 2. Sprawdzenie pliku .env w bieżącym katalogu lub w katalogu głównym projektu
    env_paths = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(BASE_DIR, ".env"),
        os.path.join(os.path.dirname(__file__), ".env"),
    ]

    for env_path in env_paths:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.startswith("HF_TOKEN="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
                        elif line.startswith("HUGGING_FACE_HUB_TOKEN="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
            except Exception:
                pass

    return ""
