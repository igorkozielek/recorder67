import os
import sys

# Dodaj katalog główny projektu do ścieżki Pythona
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from recorder.config import APP_VERSION, GITHUB_REPO
from recorder.core.updater import parse_version, is_newer_version, check_github_updates
from PySide6.QtWidgets import QApplication
from recorder.ui.settings_dialog import SettingsDialog


def test_semver_parsing():
    print("[TEST] Weryfikacja parsera semver...")
    assert parse_version("0.5.3")[:3] == (0, 5, 3)
    assert parse_version("0.5.2")[:3] == (0, 5, 2)
    assert parse_version("0.5.1")[:3] == (0, 5, 1)
    assert parse_version("0.5.0")[:3] == (0, 5, 0)
    assert parse_version("v0.5.0")[:3] == (0, 5, 0)
    assert parse_version("v0.4.1-alpha")[:3] == (0, 4, 1)
    assert parse_version("v0.4.1-alpha")[3] < parse_version("v0.4.1")[3]  # alpha < stable
    print("  -> Parser semver działa prawidłowo!")


def test_version_comparisons():
    print("[TEST] Weryfikacja logiki porównywania wersji...")
    # Stabilne 0.5.3 nie powinno uznawać starszego 0.5.2 ani 0.5.1 za nowsze
    assert not is_newer_version("v0.4.1-alpha", "0.5.3")
    assert not is_newer_version("v0.5.0", "0.5.3")
    assert not is_newer_version("v0.5.1", "0.5.3")
    assert not is_newer_version("v0.5.2", "0.5.3")

    # Wersja 0.5.4 powinna być uznana za nowszą niż 0.5.3
    assert is_newer_version("v0.5.4", "0.5.3")
    assert is_newer_version("0.6.0-alpha", "0.5.3")

    # Jeśli jesteśmy na 0.4.0, 0.5.2 jest nowsze
    assert is_newer_version("v0.5.2", "0.4.0")
    print("  -> Logika porównywania wersji działa prawidłowo!")


def test_github_api_check():
    print("[TEST] Odpytywanie GitHub Releases API...")
    # Symulacja sprawdzenia z perspektywy wersji 0.4.0 (powinno znaleźć v0.5.2)
    res = check_github_updates(repo=GITHUB_REPO, current_version="0.4.0", include_prereleases=True)
    assert res is not None
    assert res["has_update"] is True
    print(f"  -> Znaleziono aktualizację dla 0.4.0: {res['latest_version']} ({res['asset_name']})")

    # Sprawdzenie z perspektywy bieżącej wersji 0.5.3 (brak nowszej wersji na GitHubie)
    res_curr = check_github_updates(repo=GITHUB_REPO, current_version="0.5.3", include_prereleases=True)
    assert res_curr is None
    print("  -> Dla bieżącej wersji v0.5.3 poprawnie brak nowszych aktualizacji!")


def test_settings_dialog_updates_tab():
    print("[TEST] Test integracji SettingsDialog (brak NameError, zakładka aktualizacji)...")
    app = QApplication.instance() or QApplication([])
    dlg = SettingsDialog()
    assert hasattr(dlg, "btn_check_updates")
    assert hasattr(dlg, "chk_check_prereleases")
    assert hasattr(dlg, "chk_auto_check_startup")
    assert hasattr(dlg, "grp_new_version")
    assert dlg.tabs.count() == 4  # Słownik, Audio/VAD, Chmura, Aktualizacje
    assert dlg.tabs.tabText(3) == "🚀 Aktualizacje"

    # Test przełączania zakładki
    dlg.select_tab("updates")
    assert dlg.tabs.currentIndex() == 3
    dlg.close()
    print("  -> Zakładka Aktualizacje w SettingsDialog zainicjalizowana pomyślnie!")


if __name__ == "__main__":
    test_semver_parsing()
    test_version_comparisons()
    test_github_api_check()
    test_settings_dialog_updates_tab()
    print("\n🎉 Wszystkie testy modułu Auto-Updatera zakończone sukcesem!")
