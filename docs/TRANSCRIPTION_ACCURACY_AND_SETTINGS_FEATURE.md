# Instrukcja Integracji: Dokładność Transkrypcji & Panel Ustawień GUI

Niniejszy dokument opisuje wdrożone zmiany na gałęzi `feature/whisper-large-turbo-and-accuracy` w celu ich bezproblemowej integracji z inną gałęzią (np. `feature/live-office-supabase-sync`) przez innego agenta lub developera w Antigravity.

---

## 1. Informacje o Gałęzi i Commitach Git

* **Gałąź źródłowa:** `feature/whisper-large-turbo-and-accuracy`
* **Punkt startowy (Baza):** `master` (commit `d5e31e9`)
* **Commity na tej gałęzi:**
  1. `1a83899`: `feat(transcription): boost accuracy with large-v3-turbo, beam_size=5, audio preprocessing and rich domain prompt`
  2. `c336324`: `feat(ui): add modern SettingsDialog with industry dictionary, whisper beam size, VAD sensitivity and cloud sync options`

---

## 2. Główne Funkcjonalności Wdrożone na tej Gałęzi

### A. Dedykowane Okno Ustawień w GUI (`SettingsDialog`)
* **Lokalizacja:** `recorder/ui/settings_dialog.py`
* **Przycisk w UI:** Przycisk `⚙️ Ustawienia` w prawym górnym rogu nagłówka (`recorder/ui/window.py`).
* **Trwałość Konfiguracji:** Plik `user_settings.json` (w katalogu roboczym) z automatyczną inicjalizacją z `.env` / domyślnych stałych i zabezpieczeniem w `.gitignore`.
* **3 Zakładki Konfiguracyjne:**
  1. **📚 Słownik i AI:**
     - Wieloliniowy edytor słownika branżowego (nazwy firm, programów, skrótów, pojęć), który dynamicznie zasila `initial_prompt` Whispera w locie bez restartu aplikacji.
     - Przyciski szybkiego dodawania szablonów: `+ Szablon IT & Biuro`, `+ Szablon Sprzedaż`.
     - Wybór precyzji Whispera: *⚡ Szybki (Beam=1)*, *⚖️ Zrównoważony (Beam=3)*, *🚀 Maksymalna Dokładność (Beam=5)*.
     - Pole na token HuggingFace (`HF_TOKEN`) z przełącznikiem widoczności hasła (👁️).
  2. **🎙️ Mikrofon i VAD:**
     - Suwak czułości wykrywania mowy Silero VAD (`VAD_SPEECH_THRESHOLD` w zakresie 0.20 – 0.60 z dynamicznym opisem progu).
     - Regulacja czasu ciszy do auto-pauzy (1–15 s).
     - Wybór progu ciszy dla podziału sesji biurowej (`SESSION_SPLIT_SILENCE_SEC`: 10 min, 15 min, 30 min, 1h, wyłączone).
  3. **☁️ Chmura i Stanowisko:**
     - Nazwa stanowiska komputerowego (`DEVICE_NAME`).
     - Identyfikator organizacji (`ORGANIZATION_ID`).
     - Cel synchronizacji (`SYNC_TARGET`: `emanager`, `generic_webhook`, `none`).
     - Adres i klucz Supabase oraz URL Webhooka.
     - Przełączniki automatycznej wysyłki i dołączania pliku `.wav`.

---

### B. Zwiększenie Dokładności Transkrypcji
1. **Domyślny Model `large-v3-turbo`:**
   - Ustawiony jako domyślny w `recorder/config.py` (`DEFAULT_WHISPER_MODEL = "large-v3-turbo"`).
   - Wersja turbo posiada zaledwie 4 warstwy dekodera, dzięki czemu działa bardzo szybko na CPU w trybie `int8`, zapewniając jednocześnie najwyższą wierność języka polskiego.
2. **Wyszukiwanie Wiązkowe (`beam_size=5`):**
   - Zastosowane w transkrypcji na żywo (`transcribe_live_chunk`), blokach w tle (`RollingTranscriptionWorker`) i pełnej transkrypcji plików (`transcribe_file_with_words`).
   - Eliminuje halucynacje fonetyczne (np. *„okadania paszał”* $\rightarrow$ *„z przymrużeniem oka na nie patrzał”*).
3. **Preprocessing i Filtracja Pasma Audio (High-Pass ~80Hz):**
   - Nowe funkcje w `recorder/audio/converter.py`: `highpass_filter_audio()` oraz `preprocess_speech_audio()`.
   - Odcinają dudnienia biurka, podmuchy powietrza i przydźwięk sieciowy 50Hz przed analizą przez Whisper / Silero VAD.

---

## 3. Wykaz Plików Zmodyfikowanych i Utworzonych

```
recorder/
├── audio/
│   └── converter.py                  # [MODIFIED] Dodano highpass_filter_audio, preprocess_speech_audio, poprawiono normalize_audio
├── config.py                         # [MODIFIED] Dodano load_user_settings, save_user_settings, dynamiczne gettery, model large-v3-turbo
├── core/
│   ├── rolling_transcriber.py        # [MODIFIED] Dynamiczny get_full_initial_prompt, get_beam_size, audio preprocessing bloków
│   └── transcriber.py                # [MODIFIED] Dynamiczny prompt, beam search, preprocessing w transcribe_file_with_words i live chunk
└── ui/
    ├── __init__.py                   # [MODIFIED] Eksport SettingsDialog
    ├── settings_dialog.py            # [NEW] Komponent okna dialogowego ustawień (3 zakładki)
    └── window.py                     # [MODIFIED] Przycisk '⚙️ Ustawienia' w nagłówku, metoda _open_settings_dialog
.gitignore                            # [MODIFIED] Dodano user_settings.json
```

---

## 4. Instrukcja Scalenia dla Drugiego Agenta (Merge / Integration Guide)

Jeśli pracujesz na innej gałęzi (np. `feature/live-office-supabase-sync`), możesz włączyć te zmiany w jeden z poniższych sposobów:

### Opcja A: Zwykłe scalenie gałęzi (Zalecane)
```bash
git checkout feature/live-office-supabase-sync
git merge feature/whisper-large-turbo-and-accuracy
```

### Opcja B: Cherry-pick konkretnych commitów
```bash
git checkout feature/live-office-supabase-sync
git cherry-pick 1a83899
git cherry-pick c336324
```

### Na co uważać przy ewentualnych konfliktach:
1. **`recorder/config.py`:**
   - Upewnij się, że zachowano metody `load_user_settings()`, `save_user_settings()`, `get_custom_keywords()`, `get_beam_size()`, `get_full_initial_prompt()` oraz `DEFAULT_WHISPER_MODEL = "large-v3-turbo"`.
   - `get_cloud_sync_config()` powinno korzystać z `st = load_user_settings()` z fallbackiem do zmiennych `.env`.
2. **`recorder/ui/window.py`:**
   - W nagłówku (`_init_ui`) powinien znajdować się przycisk `self.btn_settings` podłączony do `self._open_settings_dialog`.
3. **`recorder/core/rolling_transcriber.py` i `transcriber.py`:**
   - Initial prompt powinien być generowany przez `get_full_initial_prompt()` zamiast sztywnego stringa.
