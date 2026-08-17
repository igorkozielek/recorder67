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


# Dostępne modele Faster-Whisper z opisem dla UI
WHISPER_MODELS = {
    "small": {
        "id": "small",
        "name": "small",
        "label": "⚡ small (Szybki / Niski narzut CPU)",
        "desc": "Zalecany na słabsze procesory (niski narzut pamięci ~350MB, b. szybka transkrypcja na żywo)"
    },
    "medium": {
        "id": "medium",
        "name": "medium",
        "label": "⚖️ medium (Zrównoważony)",
        "desc": "Dobra jakość języka polskiego, umiarkowane zużycie CPU/GPU (~900MB RAM)"
    },
    "large-v3-turbo": {
        "id": "large-v3-turbo",
        "name": "large-v3-turbo",
        "label": "🚀 large-v3-turbo (Zalecany / Wysoka jakość)",
        "desc": "Najlepszy stosunek jakości do prędkości (4x szybszy niż standardowy large, ~1.2GB RAM)"
    },
    "large-v3": {
        "id": "large-v3",
        "name": "large-v3",
        "label": "🎯 large-v3 (Maksymalna precyzja)",
        "desc": "Najwyższa dokładność słów i interpunkcji (zalecana dedykowana karta graficzna NVIDIA)"
    },
    "base": {
        "id": "base",
        "name": "base",
        "label": "🪶 base (Ultralekki)",
        "desc": "Minimalne wymagania sprzętowe, mniejsza precyzja dla trudniejszych słów"
    }
}

DEFAULT_WHISPER_MODEL = "small"


def get_hardware_acceleration_info() -> dict:
    """
    Automatycznie wykrywa dostępne zasoby sprzętowe (CUDA GPU vs CPU)
    i dobiera optymalny typ obliczeń (compute_type) oraz liczbę wątków.
    """
    cuda_available = False
    gpu_name = ""
    try:
        import torch
        if torch.cuda.is_available():
            cuda_available = True
            gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        cuda_available = False

    if cuda_available:
        return {
            "device": "cuda",
            "compute_type": "float16",
            "cpu_threads": 4,
            "is_cuda": True,
            "badge_text": f"🚀 Akceleracja: NVIDIA GPU ({gpu_name}) • float16",
            "summary": "GPU (CUDA float16)"
        }
    else:
        # Na CPU dobieramy liczbę wątków z zachowaniem zapasu na UI i Silero VAD
        total_cores = os.cpu_count() or 4
        # Np. dla 6 rdzeni (i5-8500) -> 4 wątki; dla 4 rdzeni -> 3 wątki; min 1
        safe_threads = max(1, min(6, total_cores - 1 if total_cores > 2 else total_cores))
        return {
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": safe_threads,
            "is_cuda": False,
            "badge_text": f"💻 Akceleracja: CPU ({safe_threads} wątków, int8 AVX)",
            "summary": f"CPU (int8 - {safe_threads} thr)"
        }


# Opcje wyboru liczby osób dla PyAnnote
SPEAKER_COUNT_OPTIONS = [
    ("Auto (Dowolna liczba)", None),
    ("1 osoba (Monolog)", 1),
    ("2 osoby (Dialog)", 2),
    ("3 osoby", 3),
    ("4 osoby", 4),
    ("5 osób", 5),
]


def get_recommended_profile() -> dict:
    """
    Analizuje konfigurację sprzętową i zwraca rekomendowany model oraz uzasadnienie.
    """
    hw = get_hardware_acceleration_info()
    cores = os.cpu_count() or 4

    if hw["is_cuda"]:
        return {
            "recommended_model": "large-v3-turbo",
            "title": "Wykryto kartę NVIDIA (CUDA)",
            "message": (
                f"Wykryto akcelerację GPU: {hw['badge_text']}.\n\n"
                "Ustawiono rekomendowany model: 'large-v3-turbo' (float16),\n"
                "który zapewnia najwyższą precyzję transkrypcji języka polskiego przy błyskawicznym czasie działania."
            )
        }
    else:
        # Maszyna CPU (np. i5-8500 6-core)
        if cores >= 6:
            rec_model = "small"
            return {
                "recommended_model": rec_model,
                "title": "Wykryto wydajny procesor CPU",
                "message": (
                    f"Wykryto procesor CPU z {cores} wątkami/rdzeniami (Brak dedykowanej karty NVIDIA).\n\n"
                    f"Ustawiono zoptymalizowany model: '{rec_model}' w trybie int8 ({hw['cpu_threads']} wątki robocze).\n\n"
                    "Zapewnia on płynną transkrypcję na żywo bez opóźnień.\n"
                    "(Jeśli zależy Ci na wyższej precyzji, możesz również ręcznie wybrać model 'medium' lub 'large-v3-turbo')."
                )
            }
        else:
            rec_model = "small"
            return {
                "recommended_model": rec_model,
                "title": "Wykryto procesor CPU",
                "message": (
                    f"Wykryto procesor CPU z {cores} wątkami.\n\n"
                    f"Ustawiono lekki model: '{rec_model}' (int8) dla zachowania płynności działania systemu."
                )
            }


