# Antigravity Agent Rules - Recorder67 (Biuro AI Assistant)

- Główny cel projektu oraz aktualny stan i roadmapa znajdują się w pliku [PROJECT_GOAL.md](file:///c:/Users/adria/source/repos/igorkozielek/recorder67/PROJECT_GOAL.md).
- Projekt realizuje koncepcję **Ambient AI** dla biura: automatyczne nagrywanie z detekcją mowy (Silero VAD), lokalna transkrypcja (Faster-Whisper), diaryzacja mówców, synchronizacja z Supabase oraz analiza biznesowa (zadania, wąskie gardła, optymalizacje) przez n8n / LLM.
- **Sprzęt testowy:** Hollyland LARK MAX 2 Combo (4 person).
- Założenia są dynamiczne i mogą być modyfikowane oraz rozbudowywane w pliku `PROJECT_GOAL.md` w miarę postępu prac i testów.

---

### Kluczowe Zasady Projektowe, Uczenia się i Prywatności (Learned Lessons):

0. **Samouczenie i Aktualizacja Reguł Agenta:**
   - Asystent ma stałą zgodę na proaktywne zapisywanie nowo zdobytej wiedzy, wniosków, ustaleń technicznych i preferencji użytkownika bezpośrednio w pliku `.antigravity/rules.md` (lub odpowiednich plikach reguł/skills), aby zachować ciągłość kontekstu między sesjami i nie wymagać ponownych instrukcji od użytkownika.

1. **Bezwzględna Ochrona Prywatności i Danych Biznesowych / Klientów:**
   - Pod żadnym pozorem nie umieszczać fragmentów rzeczywistych rozmów biznesowych z klientami w kodzie źródłowym, komentarzach, docstringach, testach jednostkowych ani w commitach.
   - Wszelkie przykłady dialogów, imion i poleceń w kodzie muszą być w 100% zanonimizowane i generyczne (np. Jan, Piotr, Tomasz, Anna).
   - Katalogi tymczasowe, pliki `.txt`, nagrania `.wav` oraz folder `scratch/` muszą pozostać wykluczone w `.gitignore`.

2. **Git Workflow i Autonomia Użytkownika:**
   - Nie commitować bezpośrednio do gałęzi `master` ani nie dokonywać automatycznego merge'a do `master`, chyba że użytkownik wyraźnie o to poprosi.
   - Zadaniem asystenta jest przygotowanie czystego kodu, rozwiązanie konfliktów w plikach i podanie użytkownikowi gotowych komend do zatwierdzenia.

3. **Optymalizacje Techniczne Audio / AI w Środowisku Windows:**
   - Unikać zależności od zewnętrznego systemowego `ffmpeg` w transkrypcji plików – stosować wbudowane mechanizmy `soundfile` do bezpośredniego wczytywania tablic float32 do `faster-whisper`.
   - Stosować `apply_av_patches()` oraz `apply_torchaudio_patches()` omijające ograniczenia DLL w Windows (AppLocker/PyTorch 2.6+ `weights_only`).
   - W pipeline PyAnnote stosować `batch_size=32` dla efektywnego przetwarzania długich nagrań (1–2h).
