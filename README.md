# Recorder67 - Asystent Biurowy Ambient AI

System ciągłego monitorowania mowy, lokalnej transkrypcji AI oraz analizy biznesowej dla optymalizacji procesów biurowych.

Szczegółowy opis architektury, statusu prac (zrobione vs do zrobienia) oraz założeń znajduje się w dokumencie:
👉 **[PROJECT_GOAL.md](PROJECT_GOAL.md)**

---

## 🚀 Szybki Start

### 1. Instalacja zależności
```bash
pip install -r requirements.txt
```

### 2. Konfiguracja Tokena Hugging Face (dla Diaryzacji PyAnnote)
Skopiuj plik `.env.example` do `.env` i wklej swój klucz:
```bash
copy .env.example .env
```
W pliku `.env`:
```env
HF_TOKEN=hf_twoj_token_tutaj
```

### 3. Uruchomienie aplikacji
```bash
python main.py
```
*(Alternatywnie: `python recorder/recorder.py` lub `python recorder/main.py`)*

---

## 📁 Struktura Projektu

```text
recorder67/
├── main.py                    # Punkt startowy aplikacji
├── .env                       # Klucze API / HuggingFace Token (ignorowany przez git)
├── .env.example               # Przykładowa konfiguracja środowiska
├── PROJECT_GOAL.md            # Pamięć projektu i roadmapa
├── requirements.txt           # Zależności Python
│
└── recorder/
    ├── config.py              # Konfiguracja, stałe i wczytywanie tokena z .env
    │
    ├── core/                  # Czysta logika AI (bez zależności od GUI)
    │   ├── vad.py             # Detekcja mowy Silero VAD AI
    │   ├── transcriber.py     # Transkrypcja Faster-Whisper
    │   └── diarizer.py        # Diaryzacja mówców PyAnnote
    │
    ├── audio/                 # Obsługa sprzętu i przetwarzanie dźwięku
    │   ├── devices.py         # Filtrowanie mikrofonów (ignorowanie błędnych WDM-KS)
    │   ├── converter.py       # Resampling audio do 16 kHz
    │   └── capture.py         # Zapis bufora do formatu WAV
    │
    └── ui/                    # Interfejs graficzny PyQt6
        ├── window.py          # Główne okno SmartDictaphoneWindow
        ├── workers.py         # Wątki robocze QThread
        └── theme.py           # Motyw ciemny i arkusz stylów QSS
```
