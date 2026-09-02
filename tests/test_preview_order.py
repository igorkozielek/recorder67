import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from recorder.config import load_user_settings, get_preview_order, is_auto_scroll_chronological
from recorder.core.session import TranscriptionSession
from recorder.core.speakers import format_turns


def test_config_defaults():
    settings = load_user_settings()
    assert "preview_order" in settings
    assert "auto_scroll_chronological" in settings
    assert get_preview_order() in ("newest_first", "chronological")
    assert isinstance(is_auto_scroll_chronological(), bool)
    print("Test konfiguracji domyslnych: Sukces!")


def test_session_preview_order():
    turns = [
        {"start": 10.0, "end": 15.0, "speaker": "Bartek", "text": "Pierwsza wypowiedz ze spotkania."},
        {"start": 20.0, "end": 25.0, "speaker": "Ania", "text": "Druga wypowiedz w srodku rozmowy."},
        {"start": 30.0, "end": 35.0, "speaker": "Bartek", "text": "Najnowsza wypowiedz na samym koncu."},
    ]

    session = TranscriptionSession(turns=turns)

    # 1. Eksport TXT MUSI ZAWSZE byc scisle chronologiczny (od pierwszej do ostatniej)
    plain = session.export_to_plain_text()
    first_idx = plain.find("Pierwsza wypowiedz")
    mid_idx = plain.find("Druga wypowiedz")
    last_idx = plain.find("Najnowsza wypowiedz")
    assert first_idx < mid_idx < last_idx, "Blad! Eksport TXT nie jest chronologiczny!"
    print("Test nienaruszalnosci chronologii TXT w sesji: Sukces!")

    # 2. Eksport HTML w trybie 'newest_first' (najnowsza na samej gorze)
    html_newest = session.export_to_html(reverse_order=True)
    h_first_idx = html_newest.find("Pierwsza wypowiedz")
    h_mid_idx = html_newest.find("Druga wypowiedz")
    h_last_idx = html_newest.find("Najnowsza wypowiedz")
    assert h_last_idx < h_mid_idx < h_first_idx, "Blad! W trybie newest_first najnowsza wypowiedz nie jest pierwsza w HTML!"
    print("Test HTML newest_first w sesji: Sukces (najnowsza u gory)!")

    # 3. Eksport HTML w trybie 'chronological' (chronologiczny od poczatku)
    html_chrono = session.export_to_html(reverse_order=False)
    c_first_idx = html_chrono.find("Pierwsza wypowiedz")
    c_mid_idx = html_chrono.find("Druga wypowiedz")
    c_last_idx = html_chrono.find("Najnowsza wypowiedz")
    assert c_first_idx < c_mid_idx < c_last_idx, "Blad! W trybie chronological HTML nie jest chronologiczny!"
    print("Test HTML chronological w sesji: Sukces (od poczatku)!")


def test_format_turns_preview_order():
    turns = [
        {"start": 5.0, "end": 10.0, "speaker": "Tomasz", "text": "Poczatek narady."},
        {"start": 50.0, "end": 55.0, "speaker": "Piotr", "text": "Koniec narady."},
    ]

    # Tryb newest_first:
    html_rev, plain_rev = format_turns(turns, reverse_order=True)
    # Plain jest zawsze chronologiczny:
    assert plain_rev.find("Poczatek narady") < plain_rev.find("Koniec narady")
    # HTML ma najnowsza u gory:
    assert html_rev.find("Koniec narady") < html_rev.find("Poczatek narady")
    print("Test format_turns newest_first: Sukces!")

    # Tryb chronological:
    html_chr, plain_chr = format_turns(turns, reverse_order=False)
    assert plain_chr.find("Poczatek narady") < plain_chr.find("Koniec narady")
    assert html_chr.find("Poczatek narady") < html_chr.find("Koniec narady")
    print("Test format_turns chronological: Sukces!")


if __name__ == "__main__":
    test_config_defaults()
    test_session_preview_order()
    test_format_turns_preview_order()
    print("\nWszystkie testy kolejnosci podgladu zakonczone sukcesem!")
