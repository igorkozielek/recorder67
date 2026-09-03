import os
import sys

# Ustawienie ścieżki do projektu
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from recorder.core.speakers import analyze_speakers, suggest_speaker_names, format_speaker_stats


def test_speakers_deduplication():
    # Symulacja dialogu z 4 mówcami: Bartek, Łukasz, Ania, Jola
    turns = [
        {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00", "text": "Dzień dobry, hej, Bartosz z tej strony."},
        {"start": 5.5, "end": 10.0, "speaker": "SPEAKER_01", "text": "Bartek, zaloguj mnie na tamto konto."},
        {"start": 10.5, "end": 15.0, "speaker": "SPEAKER_02", "text": "Ania, a ty możesz udostępnić ekran?"},
        {"start": 15.5, "end": 20.0, "speaker": "SPEAKER_03", "text": "Jola, nie widziałaś tego filmu?"},
        {"start": 20.5, "end": 25.0, "speaker": "SPEAKER_01", "text": "Łukasz powiedział, że te kółka są do dupy."},
    ]

    analysis = analyze_speakers(turns)
    assert len(analysis) == 4

    suggestions = suggest_speaker_names(turns)
    assigned_values = [v for k, v in suggestions.items() if not v.startswith("SPEAKER_")]

    # Gwarancja unikalności: brak duplikatów imion!
    assert len(assigned_values) == len(set(assigned_values)), f"Wykryto duplikaty imion: {assigned_values}"
    print(f"[OK] Test Unikalności Mówców: Sukces! Przypisania: {suggestions}")

    # Test formatowania statystyk
    stats_str = format_speaker_stats(count=42, total_duration_sec=860.0)
    assert "42 wypowiedzi" in stats_str
    assert "14m 20s" in stats_str
    print("[OK] Test format_speaker_stats: Sukces!")


if __name__ == "__main__":
    test_speakers_deduplication()
