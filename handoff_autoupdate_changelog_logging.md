# Handoff & Release Notes: Auto-Updater z Paskiem Postępu, Bogaty Changelog Markdown i Bezpieczne Logowanie EXE

**Gałąź git:** `feature/ui-updater-changelog-and-logging`  
**Baza wyjściowa:** `master` (commit `f59f3f4`)  
**Status testów:** 28/28 testów zdanych w 100% (kod 0)  
**Środowisko docelowe:** Windows 10/11 x64, PySide6, PyInstaller (EXE bez okna konsoli), PowerShell WinForms GUI.

---

## 1. Kontekst i Wymagania (Dlaczego powstał ten branch?)

Użytkownik zgłosił zestaw 3 kluczowych usprawnień UX, interfejsu oraz stabilności działania aplikacji dyktafonu:

1. **Brak widocznej informacji o postępie podczas instalacji aktualizacji (Auto-Updater):**
   - Po kliknięciu „Zaktualizuj i zrestartuj teraz” aplikacja natychmiast znikała, a ukryty proces wsadowy w tle rozpakowywał paczkę ZIP i podmieniał pliki.
   - Użytkownik nie miał pojęcia, czy cokolwiek się dzieje, czy proces się zawiesił, czy nastąpił crash, dopóki program samoczynnie nie wstał po kilkunastu sekundach. Brakowało paska postępu i czytelnych komunikatów o etapach aktualizacji.
2. **Niewystarczające okienko z opisem zmian (Changelog) w zakładce ustawień:**
   - Pole tekstowe miało sztywny limit wysokości `maximumHeight(130)` (~5 linijek tekstu), przez co dłuższe opisy wydań były ucięte i wymagały uciążliwego przewijania.
   - Jeśli użytkownik był o kilka wersji do tyłu (np. z `v0.5.1` do `v0.5.5`), aplikacja pokazywała tylko opis najnowszego wydania — brakowało możliwości podejrzenia zsumowanych zmian ze wszystkich pominiętych wydań.
   - Brakowało możliwości przeglądania historii wydań i changelogów, jeśli użytkownik posiadał już najnowszą wersję programu.
   - Opisy na GitHubie tworzone są w formacie Markdown (`#`, `**bold**`, `- list`, linki), a kontrolka wyświetlała je jako surowy, niesformatowany tekst (`setPlainText`).
3. **Pojawiające się czarne okno konsoli w zbudowanym `.exe` oraz brak logowania diagnostycznego:**
   - Skompilowany plik `InteligentnyDyktafonAI.exe` uruchamiał czarne okno konsoli Windows cmd (`console=True`), co wyglądało nieprofesjonalnie dla użytkowników końcowych.
   - Po wyłączeniu konsoli (`console=False` / `--noconsole`) należało zapewnić bezpieczny zapis wyjścia (`print`, błędy, `sys.stdout`, `sys.stderr`) do plików `.log` na dysku, aby w przyszłości ułatwić diagnostykę problemów.
   - Logi diagnostyczne na starcie miały zbierać konfigurację użytkownika (`user_settings.json`), jednak z **bezwzględnym zachowaniem bezpieczeństwa** (maskowanie kluczy API, takich jak `hf_token`, `supabase_key`, haseł i webhooków).

---

## 2. Wprowadzone Rozwiązania i Architektura

### A. Graficzny Aktualizator z Paskiem Postępu (PowerShell WinForms GUI)
- **Plik:** [`recorder/core/updater.py`](file:///c:/Users/adw18/source/repos/igorkozielek/recorder67/recorder/core/updater.py)
- **Natywne okno postępu Windows Forms:** Stworzono funkcję `generate_updater_scripts()`, która generuje dedykowany skrypt PowerShell `run_app_update.ps1`. Uruchamia on nowoczesne, ciemne okno GUI (`#1a1a26`, akcent `#4cc9f0`, pasek postępu) z parametrem `TopMost = $true`.
- **Dynamiczne etapy instalacji:** Pasek postępu płynnie informuje użytkownika o każdym kroku:
  1. `12%`: Oczekiwanie na zamknięcie aplikacji (zwalnianie blokad plików PID).
  2. `25%`: Przygotowanie katalogu roboczego i czyszczenie starych plików tymczasowych.
  3. `45%`: Rozpakowywanie paczki ZIP (`tar -xf` z fallbackiem do `Expand-Archive`).
  4. `75%`: Bezpieczna podmiana plików w katalogu programu za pomocą `robocopy /e /np /r:5 /w:1`.
  5. `95%`: Usuwanie archiwum ZIP i katalogu roboczego.
  6. `100%`: Finalizacja i samoczynne uruchomienie zaktualizowanego pliku `.exe`.
- **Dynamiczne wykrywanie podkatalogów paczki ZIP:** Skrypt automatycznie wyszukuje plik wykonywalny `InteligentnyDyktafonAI.exe` w wypakowanej strukturze katalogów (niezależnie od tego, czy paczka ZIP zawiera pliki bezpośrednio w korzeniu, czy w podfolderze o dowolnej nazwie np. `InteligentnyDyktafonAI-v0.5.6-Windows`).
- **Prawidłowa obsługa kodów błędów robocopy i exit code PowerShella:**
  - W Windows robocopy zwraca kod 1 przy pomyślnym skopiowaniu plików. Dodano jawne `exit 0` na końcu bloku `try`, co eliminuje fałszywe wykrycie błędu przez skrypt nadrzędny.
  - Dodano detekcję krytycznych błędów robocopy (`$LASTEXITCODE -ge 8`, np. brak uprawnień zapisu w `C:\Program Files`), co powoduje wejście w blok `catch`, wyświetlenie czytelnego czerwonego komunikatu o błędzie dla użytkownika oraz zwrócenie kodu wyjścia 1.
- **Rzeczywisty i spójny fallback wsadowy (`run_app_update.bat`):** `apply_in_place_update` uruchamia nadrzędny proces wsadowy w trybie ukrytym (`CREATE_NO_WINDOW`), który wywołuje GUI PowerShell, a w razie blokady execution policy natychmiast przełącza się na awaryjną procedurę kopiowania bez przerywania aktualizacji.

### B. Przestronny Changelog Markdown i Wielowersyjna Agregacja
- **Pliki:** [`recorder/ui/settings_dialog.py`](file:///c:/Users/adw18/source/repos/igorkozielek/recorder67/recorder/ui/settings_dialog.py), [`recorder/core/updater.py`](file:///c:/Users/adw18/source/repos/igorkozielek/recorder67/recorder/core/updater.py)
- **Zamiana na `QTextBrowser` z bogatym Markdownem:** Zastąpiono `QTextEdit` kontrolką `QTextBrowser` z obsługą `setMarkdown()`. Usunięto restrykcyjne ograniczenie 130px i nadano przestronną minimalną wysokość `240px` z dopasowanym ciemnym motywem oraz aktywnymi hiperłączami (`setOpenExternalLinks(True)`).
- **Agregacja wydań (`build_aggregated_changelog`):** Gdy użytkownik pominął kilka wydań, `check_github_updates` zbiera listę wszystkich brakujących wersji (`newer_releases`) i łączy ich notatki w jeden spójny dokument Markdown z zabezpieczeniem przed wartościami `None`.
- **Przełącznik wersji w UI (`combo_changelog_version`):** Użytkownik widzi rozwijaną listę:
  - Opcja domyślna: `📋 Zsumowane zmiany ze wszystkich brakujących wydań (v0.5.x ➔ v0.5.y)`
  - Opcje szczegółowe: poszczególne wydania z osobna.
- **Pełna historia wydań (`grp_history`) i przycisk rozwinięcia (`btn_toggle_history`):**
  - Jeśli użytkownik posiada najnowszą wersję programu, sekcja historii jest widoczna domyślnie.
  - Jeśli dostępna jest nowa wersja, historia jest domyślnie zwinięta, a użytkownik może ją jednym kliknięciem rozwinąć przyciskiem `📜 Pokaż także historię starszych wydań...` bez zalewania ekranu niepotrzebnym chaosem.
- **Obsługa mniejszych ekranów (`QScrollArea`):** Całą zakładkę aktualizacji osadzono w elastycznym `QScrollArea`, zapobiegając ucinaniu przycisków akceptacji okna na małych monitorach lub przy skalowaniu DPI > 100%.

### C. Wersja Produkcyjna bez Konsoli i Centralne Logowanie z Maskowaniem Danych
- **Pliki:** [`recorder/core/logger.py`](file:///c:/Users/adw18/source/repos/igorkozielek/recorder67/recorder/core/logger.py), [`scripts/build_exe.py`](file:///c:/Users/adw18/source/repos/igorkozielek/recorder67/scripts/build_exe.py), [`InteligentnyDyktafonAI.spec`](file:///c:/Users/adw18/source/repos/igorkozielek/recorder67/InteligentnyDyktafonAI.spec), [`recorder/config.py`](file:///c:/Users/adw18/source/repos/igorkozielek/recorder67/recorder/config.py), [`run.py`](file:///c:/Users/adw18/source/repos/igorkozielek/recorder67/run.py), [`recorder/main.py`](file:///c:/Users/adw18/source/repos/igorkozielek/recorder67/recorder/main.py), [`main.py`](file:///c:/Users/adw18/source/repos/igorkozielek/recorder67/main.py)
- **Wyłączenie okna konsoli w EXE:**
  - W `InteligentnyDyktafonAI.spec` ustawiono `console=False`.
  - W `scripts/build_exe.py` dodano parametr `"--noconsole"`.
- **Pełny wrapper strumieni `StdStreamLogger`:**
  - W trybie GUI bez konsoli w Windowsie `sys.stdout` ma wartość `None`. Wrapper `StdStreamLogger` przechwytuje każde wywołanie `print(...)` oraz błędy bibliotek i przekazuje je do rotującego pliku dziennika.
  - Zaimplementowano właściwości `.encoding` oraz metodę `.fileno()`, eliminując potencjalne awarie bibliotek zewnętrznych (PyTorch, Rich, Colorama).
  - Dodano pełne przywracanie oryginalnych strumieni w `shutdown_app_logging()`.
- **Rotujące pliki dziennika (`logs/app.log`):**
  - Ścieżka bazowa wyznaczana niezależnie od bieżącego `cwd` (w oparciu o katalog aplikacji).
  - `RotatingFileHandler` z limitem 10 MB i historią 5 kopii zapasowych, kodowanie UTF-8.
- **Bezpieczna sanityzacja i maskowanie danych (`sanitize_settings`):**
  - Funkcja automatycznie wykrywa klucze poufne (`hf_token`, `supabase_key`, tokeny webhooków, hasła, sekrety).
  - Maskuje poświadczenia `user:pass@` w connection stringach i adresach URL baz danych.
  - Rekurencyjnie przetwarza zagnieżdżone słowniki oraz listy struktur.
  - Długie tokeny API (np. `hf_...`, `sb_secret_...`) są częściowo maskowane (np. `hf_m***Ihc (len 37)`), co pozwala zweryfikować poprawność klucza bez ujawniania sekretu.
  - Zabezpieczono raport diagnostyczny przed wielokrotnym duplikowaniem wpisów przy starcie.
- **Przycisk dostępu do logów w UI:** W zakładce Aktualizacje dodano przycisk `📁 Otwórz folder z logami` otwierający katalog `logs/` w Eksploratorze Windows.

---

## 3. Zestaw Testów Automatycznych

Na gałęzi zaimplementowano pełen zestaw 28 testów jednostkowych:

1. `tests/test_logging_and_diagnostics.py::test_settings_sanitization_masks_all_secrets`: Weryfikacja 100% skuteczności maskowania tokenów HuggingFace, Supabase, webhooków, haseł, adresów URL z poświadczeniami i zagnieżdżonych list.
2. `tests/test_logging_and_diagnostics.py::test_sanitize_value_corner_cases`: Test przypadków brzegowych (puste stringi, wartości numeryczne, None, krótkie klucze, connection stringi db).
3. `tests/test_logging_and_diagnostics.py::test_setup_app_logging_and_file_creation`: Weryfikacja tworzenia pliku logu i zapisu zdarzeń INFO/WARNING.
4. `tests/test_logging_and_diagnostics.py::test_stdout_redirection_to_log`: Sprawdzenie przechwytywania wywołań `print()` przez `StdStreamLogger`.
5. `tests/test_logging_and_diagnostics.py::test_system_diagnostics_logging`: Weryfikacja zrzutu raportu sprzętowo-systemowego bez wycieku sekretów.
6. `tests/test_logging_and_diagnostics.py::test_build_spec_and_script_configured_for_noconsole`: Test integralności `InteligentnyDyktafonAI.spec` (`console=False`) oraz `scripts/build_exe.py` (`--noconsole`).
7. `tests/test_logging_and_diagnostics.py::test_std_stream_logger_features_and_restoration`: Test właściwości kodowania, fileno, czyszczenia buforów oraz czystego przywracania strumieni po wyłączeniu loggera.
8. `tests/test_updater.py::test_semver_parsing`: Weryfikacja parsera semver.
9. `tests/test_updater.py::test_version_comparisons`: Porównywanie wersji stabilnych i pre-release.
10. `tests/test_updater.py::test_github_api_check`: Zapytania do API GitHub Releases dla wersji bieżącej i starszej z odpornością na brak sieci.
11. `tests/test_updater.py::test_multi_version_changelog_aggregation`: Weryfikacja łączenia changelogów przy przeskoku o kilka wersji oraz odporności na notatki o wartości `None`.
12. `tests/test_updater.py::test_generate_updater_scripts`: Sprawdzenie generowania skryptów PowerShell GUI z paskiem postępu, dynamicznym wyszukiwaniem plików exe, weryfikacją kodów robocopy i fallbackiem batch.
13. `tests/test_updater.py::test_settings_dialog_updates_tab`: Test obecności kontrolek UI (`QTextBrowser`, scroll area, comboboxy wyboru wersji i historii, przycisk pokazywania historii, przycisk logów).
14. `tests/test_live_streaming_sync.py` (4 testy): Zgodność strumieniowania WAV, payloadów i konfiguracji live.
15. `tests/test_modular_diarization.py` (1 test): Cykl życia sesji i diaryzacji.
16. `tests/test_preview_order.py` (3 testy): Kolejność podglądu wypowiedzi i konfiguracja.
17. `tests/test_rolling.py` (1 test): Tworzenie bloków transkrypcji w locie.
18. `tests/test_silence_alert.py` (5 testów): Strażnik ciszy, alerty dźwiękowe, toasty powiadomień.
19. `tests/test_speakers_dedup.py` (1 test): Deduplikacja mówców.

---

## 4. Gotowy Wpis do Wydania (Changelog do Release Notes)

```markdown
### 🚀 Nowoczesny Auto-Updater z Paskiem Postępu
- **Wizualny pasek postępu aktualizacji:** Zastąpiono niewidoczny proces aktualizacji w tle dedykowanym graficznym oknem instalatora (PowerShell WinForms GUI).
- **Czytelne komunikaty o stanie:** Użytkownik widzi procentowy postęp oraz dokładne informacje o kolejnych krokach (zwalnianie plików, rozpakowywanie archiwum ZIP, bezpieczna podmiana plików przez robocopy, samoczynny restart programu).
- **Inteligentne wyszukiwanie plików programu:** Instalator samoczynnie odnajduje pliki wykonywalne aplikacji w dowolnej strukturze podkatalogów archiwum ZIP.
- **Pełna odporność na błędy:** Skrypt posiada wbudowany fallback wsadowy w razie restrykcji systemowych dla PowerShell oraz wyraźnie sygnalizuje ewentualne błędy uprawnień.

### 📜 Bogaty Changelog Markdown i Przeglądarka Historii Wydań
- **Pełne formatowanie Markdown w oknie ustawień:** Opisy wydań są teraz renderowane przez bogaty silnik `QTextBrowser` z obsługą nagłówków, list punktowanych, pogrubień oraz klikalnych linków otwierających się bezpośrednio w przeglądarce.
- **Większe okno opisu:** Zwiększono wysokość okna changelogu do min. 240px, a całą zakładkę wyposażono w płynne przewijanie na mniejszych monitorach.
- **Agregacja pominiętych aktualizacji:** Jeśli użytkownik zaktualizuje program po pominięciu kilku wydań, aplikacja automatycznie łączy changelogi wszystkich brakujących wersji w jeden czytelny raport lub pozwala przeglądać je selektywnie za pomocą listy rozwijanej.
- **Przeglądanie historii wydań:** Użytkownik może w każdej chwili przejrzeć pełną historię wydań i zmian programu w zakładce Aktualizacje — zarówno będąc na najnowszej wersji, jak i rozwijając historię przyciskiem przy dostępnej aktualizacji.

### 🛡️ Wydanie Produkcyjne bez Konsoli i Bezpieczne Logowanie Zdarzeń
- **Czysty interfejs (Brak okna konsoli cmd):** Skompilowana aplikacja `.exe` uruchamia się jako czysta aplikacja okienkowa Windows (`console=False` / `--noconsole`).
- **Centralny system zapisu logów:** Wyjście z konsoli (`print`, komunikaty bibliotek i nieobsłużone wyjątki) jest automatycznie strumieniowane do rotującego pliku dziennika `logs/app.log` (do 10 MB z automatyczną rotacją 5 kopii zapasowych).
- **100% bezpieczeństwa danych wrażliwych:** Raporty diagnostyczne i zrzuty konfiguracji automatycznie wykrywają oraz maskują klucze API (`hf_token`, `supabase_key`, tokeny webhooków, hasła i connection stringi baz danych), gwarantując pełne bezpieczeństwo przy przekazywaniu logów do diagnostyki.
- **Szybki dostęp:** Dodano przycisk `📁 Otwórz folder z logami` bezpośrednio w zakładce Aktualizacje.
```

---

## 5. Instrukcja Scalenia w 3. Czacie (Handoff do Wydania Nowej Wersji)

W nowym (trzecim) czacie integracyjnym należy:
1. Pobrać gałąź `perf/investigate-long-recording-slowdown` (optymalizacja sesji 4h-8h).
2. Pobrać gałąź `feature/ui-updater-changelog-and-logging` (niniejsza gałąź: auto-updater, changelog markdown, logging bez konsoli).
3. Wykonać merge gałęzi do wspólnego brancha release'owego:
   - Zwrócić uwagę na brak konfliktów w `recorder/ui/settings_dialog.py` oraz `recorder/ui/window.py` (obie gałęzie dotykały różnych fragmentów tych plików).
4. Uruchomić pełny zestaw testów obu gałęzi:
   `env\Scripts\pytest -v` (wszystkie testy stabilności długich sesji + wszystkie testy changelogu/updatera/logowania).
5. Podbić wersję do nowego wydania (np. `v0.6.0`) i skompilować release produkcyjny za pomocą `python scripts/build_exe.py`.
