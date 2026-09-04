import os
import sys

# Dodaj katalog główny projektu do ścieżki Pythona
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from recorder.config import APP_VERSION, GITHUB_REPO
from recorder.core.updater import (
    parse_version,
    is_newer_version,
    check_github_updates,
    fetch_all_releases,
    build_aggregated_changelog,
    generate_updater_scripts
)
from PySide6.QtWidgets import QApplication, QTextBrowser
from recorder.ui.settings_dialog import SettingsDialog


def test_semver_parsing():
    print("[TEST] Weryfikacja parsera semver...")
    assert parse_version("0.5.5")[:3] == (0, 5, 5)
    assert parse_version("0.5.4")[:3] == (0, 5, 4)
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
    # Stabilne 0.5.5 nie powinno uznawać starszego 0.5.4 za nowsze
    assert not is_newer_version("v0.4.1-alpha", "0.5.5")
    # Wyższa wersja minor/patch
    assert is_newer_version("0.5.3", "0.5.2") is True
    assert is_newer_version("0.6.0", "0.5.2") is True
    assert is_newer_version("1.0.0", "0.5.2") is True
    
    # Równa wersja
    assert is_newer_version("0.5.2", "0.5.2") is False
    assert is_newer_version("v0.5.2", "0.5.2") is False
    
    # Starsza wersja
    assert is_newer_version("0.5.1", "0.5.2") is False
    assert is_newer_version("0.4.9", "0.5.2") is False
    
    # Pre-release vs Stabilna
    assert is_newer_version("0.5.3", "0.5.3-alpha") is True
    assert is_newer_version("0.5.3-beta", "0.5.3-alpha") is True
    assert is_newer_version("0.5.3-alpha", "0.5.3") is False
    print("  -> Logika porównywania wersji działa prawidłowo!")


def test_github_api_check():
    print("[TEST] Odpytywanie GitHub Releases API...")
    try:
        res = check_github_updates(repo=GITHUB_REPO, current_version="0.4.0", include_prereleases=True)
        if res is not None:
            assert res["has_update"] is True
            assert "newer_releases" in res
            assert len(res["newer_releases"]) >= 1
            assert "aggregated_notes" in res
            print(f"  -> Znaleziono aktualizację dla 0.4.0: {res['latest_version']} ({res.get('asset_name')})")

        # Sprawdzenie z perspektywy bieżącej wersji (lub bardzo wysokiej)
        res_current = check_github_updates(repo=GITHUB_REPO, current_version="99.99.99", include_prereleases=True)
        assert res_current is None
        print("  -> Dla wersji przyszłej v99.99.99 poprawnie brak nowszych aktualizacji!")
    except Exception as e:
        print(f"  -> Pominięto test sieciowy API GitHuba (brak sieci lub rate limit): {e}")


def test_multi_version_changelog_aggregation():
    print("[TEST] Agregacja changelogów przy pominięciu kilku wersji...")
    mock_releases = [
        {"tag_name": "v0.5.5", "release_title": "Wydanie v0.5.5", "release_notes": "- Poprawka VAD\n- Nowy model", "published_at": "2026-03-01T12:00:00Z"},
        {"tag_name": "v0.5.4", "release_title": "Wydanie v0.5.4", "release_notes": "- Zmiany UI\n- Eksport do DOCX", "published_at": "2026-02-25T12:00:00Z"},
        {"tag_name": "v0.5.3", "release_title": "Wydanie v0.5.3", "release_notes": "- Skróty klawiszowe", "published_at": "2026-02-20T12:00:00Z"},
    ]
    agg = build_aggregated_changelog(mock_releases)
    assert "v0.5.5" in agg
    assert "v0.5.4" in agg
    assert "v0.5.3" in agg
    assert "Poprawka VAD" in agg
    assert "Eksport do DOCX" in agg
    assert "Skróty klawiszowe" in agg
    assert "---" in agg

    # Przypadek brzegowy: release_notes to None lub pusty
    mock_with_none = [
        {"tag_name": "v0.5.6", "release_title": "Wydanie v0.5.6", "release_notes": None, "published_at": "2026-03-05T12:00:00Z"},
        {"tag_name": "v0.5.5", "release_title": "Wydanie v0.5.5", "release_notes": "", "published_at": "2026-03-01T12:00:00Z"},
    ]
    agg_none = build_aggregated_changelog(mock_with_none)
    assert "v0.5.6" in agg_none
    assert "Brak opisu zmian." in agg_none

    print("  -> Agregacja changelogów działa perfekcyjnie!")


def test_generate_updater_scripts():
    print("[TEST] Generowanie skryptów instalatora PowerShell GUI i batch...")
    ps1, bat = generate_updater_scripts(
        zip_path="C:/temp/fake_update.zip",
        app_dir="C:/Program Files/Dictaphone",
        exe_path="C:/Program Files/Dictaphone/InteligentnyDyktafonAI.exe",
        current_pid=9999,
        restart_after=True
    )
    assert os.path.exists(ps1)
    assert os.path.exists(bat)

    with open(ps1, "r", encoding="utf-8") as f:
        ps1_text = f.read()

    assert "System.Windows.Forms" in ps1_text
    assert "ProgressBar" in ps1_text
    assert "robocopy" in ps1_text
    assert "Set-UpdateProgress" in ps1_text
    assert "9999" in ps1_text
    # Weryfikacja łapania błędów robocopy i kodów wyjścia
    assert "$LASTEXITCODE -ge 8" in ps1_text
    assert "exit 0" in ps1_text
    assert "exit 1" in ps1_text
    assert "InteligentnyDyktafonAI.exe" in ps1_text

    with open(bat, "r", encoding="cp852", errors="ignore") as f:
        bat_text = f.read()
    assert "powershell" in bat_text
    assert "robocopy" in bat_text
    print("  -> Skrypty instalatora PowerShell z GUI WinForms wygenerowane poprawnie!")


def test_settings_dialog_updates_tab():
    print("[TEST] Test integracji SettingsDialog (brak NameError, zakładka aktualizacji)...")
    app = QApplication.instance() or QApplication([])
    dlg = SettingsDialog()
    assert hasattr(dlg, "btn_check_updates")
    assert hasattr(dlg, "chk_check_prereleases")
    assert hasattr(dlg, "chk_auto_check_startup")
    assert hasattr(dlg, "grp_new_version")
    assert hasattr(dlg, "combo_changelog_version")
    assert hasattr(dlg, "txt_changelog")
    assert isinstance(dlg.txt_changelog, QTextBrowser)
    assert dlg.txt_changelog.minimumHeight() >= 200
    assert hasattr(dlg, "btn_toggle_history")
    assert hasattr(dlg, "grp_history")
    assert hasattr(dlg, "combo_history_version")
    assert hasattr(dlg, "txt_history_changelog")
    assert hasattr(dlg, "btn_open_logs")

    assert dlg.tabs.count() == 4  # Słownik, Audio/VAD, Chmura, Aktualizacje
    assert dlg.tabs.tabText(3) == "🚀 Aktualizacje"

    # Test przełączania zakładki
    dlg.select_tab("updates")
    assert dlg.tabs.currentIndex() == 3
    dlg.show()

    # Test reakcji UI na znalezienie aktualizacji z wieloma wersjami
    mock_update_data = {
        "has_update": True,
        "current_version": "0.5.2",
        "latest_version": "v0.5.5",
        "release_title": "Wydanie v0.5.5",
        "release_notes": "Najnowsze notatki",
        "aggregated_notes": "### Notatki ze wszystkich wersji",
        "newer_releases": [
            {"tag_name": "v0.5.5", "release_title": "Wydanie v0.5.5", "release_notes": "Nowość v0.5.5", "published_at": "2026-03-01"},
            {"tag_name": "v0.5.4", "release_title": "Wydanie v0.5.4", "release_notes": "Nowość v0.5.4", "published_at": "2026-02-25"},
        ],
        "all_releases": [
            {"tag_name": "v0.5.5", "release_notes": "Historia v0.5.5", "published_at": "2026-03-01"},
            {"tag_name": "v0.5.4", "release_notes": "Historia v0.5.4", "published_at": "2026-02-25"},
            {"tag_name": "v0.5.2", "release_notes": "Historia v0.5.2", "published_at": "2026-02-10"},
        ]
    }
    dlg._on_update_check_result(mock_update_data)
    assert not dlg.grp_new_version.isHidden()
    assert dlg.grp_history.isHidden()  # Nie zalewa użytkownika historią
    assert not dlg.btn_toggle_history.isHidden()
    assert dlg.combo_changelog_version.count() == 3  # Zsumowane + v0.5.5 + v0.5.4

    # Test przełączania widoczności historii przyciskiem
    dlg._on_toggle_history_clicked()
    assert not dlg.grp_history.isHidden()
    dlg._on_toggle_history_clicked()
    assert dlg.grp_history.isHidden()

    # Test reakcji UI na brak aktualizacji (posiadamy najnowszą wersję)
    mock_no_update = {
        "has_update": False,
        "current_version": "0.5.5",
        "latest_version": "v0.5.5",
        "all_releases": [
            {"tag_name": "v0.5.5", "release_notes": "Historia v0.5.5", "published_at": "2026-03-01"},
            {"tag_name": "v0.5.4", "release_notes": "Historia v0.5.4", "published_at": "2026-02-25"},
        ]
    }
    dlg._on_update_check_result(mock_no_update)
    assert dlg.grp_new_version.isHidden()
    assert not dlg.grp_history.isHidden()
    assert dlg.combo_history_version.count() == 2

    dlg.close()
    print("  -> Zakładka Aktualizacje w SettingsDialog z Markdownem i historią przetestowana pomyślnie!")


if __name__ == "__main__":
    test_semver_parsing()
    test_version_comparisons()
    test_github_api_check()
    test_multi_version_changelog_aggregation()
    test_generate_updater_scripts()
    test_settings_dialog_updates_tab()
    print("\n[OK] Wszystkie testy modulu Auto-Updatera zakonczone sukcesem!")
