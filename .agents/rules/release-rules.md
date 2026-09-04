# Reguły Przygotowania Wydań i Bezpieczeństwa (recorder67)

## 1. Świadoma Ocena Dokumentacji Przed Wydaniem
* Przed utworzeniem taga wydania (`git tag v*`) agent ma obowiązek ocenić zakres zmian w wydaniu:
  * **Nowe funkcje / zmiany UI / zmiany zachowania aplikacji:** Zaktualizuj `README.md` oraz `PROJECT_GOAL.md` (sekcja ZROBIONE) przed utworzeniem taga.
  * **Drobne poprawki / hotfixy techniczne:** Pełna aktualizacja dokumentacji nie jest wymagana, chyba że poprawka zmienia instrukcję uruchomienia lub konfigurację.

## 2. Bezpieczeństwo i Czystość Repozytorium
* **Zero Prawdziwych Danych w Testach:** Do testów używaj wyłącznie jawnych atrap (mocków, np. `hf_mock_test_token_...`). Nigdy nie kopiuj wartości z lokalnego `.env`.
* **Czystość Gita:** Robocze notatki transferowe (np. `handoff*.md`) trzymaj poza gitem (objęte regułą w `.gitignore`).
