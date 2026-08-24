import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from recorder.core.session import (
    TranscriptionSession,
    get_session_path_for_txt,
    get_session_path_for_audio
)


def test_session_lifecycle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        json_path = os.path.join(tmp_dir, "transkrypcja_20260820_120000.json")
        txt_path = os.path.join(tmp_dir, "transkrypcja_20260820_120000.txt")
        audio_path = os.path.join(tmp_dir, "inteligentne_nagranie_20260820_120000.wav")

        # 1. Tworzenie sesji z transkrypcją bez diaryzacji
        session = TranscriptionSession(
            source_audio=audio_path,
            prepared_wav=audio_path,
            duration_sec=125.5,
            whisper_model="large-v3-turbo",
            has_transcription=True,
            has_diarization=False,
            words=[
                {"word": "Cześć", "start": 0.0, "end": 0.5, "probability": 0.98},
                {"word": "wszystkim", "start": 0.6, "end": 1.1, "probability": 0.95}
            ],
            turns=[
                {"start": 0.0, "end": 1.1, "speaker": "Mówca", "text": "Cześć wszystkim"}
            ]
        )

        assert session.get_status_badge() == "[📝 Tylko tekst]"
        ok = session.save_to_json(json_path)
        assert ok is True
        assert os.path.exists(json_path)

        # 2. Wczytanie sesji i wykonanie diaryzacji (symulacja DiarizationOnlyWorker)
        loaded = TranscriptionSession.load_from_json(json_path)
        assert loaded is not None
        assert loaded.has_transcription is True
        assert loaded.has_diarization is False
        assert len(loaded.words) == 2

        # Aktualizacja o wykrytych mówców
        loaded.has_diarization = True
        loaded.speakers_detected = ["SPEAKER_00", "SPEAKER_01"]
        loaded.turns = [
            {"start": 0.0, "end": 0.5, "speaker": "SPEAKER_00", "text": "Cześć"},
            {"start": 0.6, "end": 1.1, "speaker": "SPEAKER_01", "text": "wszystkim"}
        ]
        loaded.update_speaker_mapping({"SPEAKER_00": "Bartek", "SPEAKER_01": "Ania"})
        assert loaded.get_status_badge() == "[👥 Mówcy (2 os.)]"
        loaded.save_to_json(json_path)

        # 3. Weryfikacja eksportu tekstu z mapowaniem mówców
        reloaded = TranscriptionSession.load_from_json(json_path)
        plain = reloaded.export_to_plain_text()
        assert "Bartek: Cześć" in plain
        assert "Ania: wszystkim" in plain
        print(f"✅ Test Eksportu Tekstu z Mówcami:\n{plain}")

        # 4. Sprawdzenie helperów ścieżek
        assert get_session_path_for_txt(txt_path) == json_path
        print("✅ Test ścieżek i cyklu życia sesji: Sukces!")


if __name__ == "__main__":
    test_session_lifecycle()
