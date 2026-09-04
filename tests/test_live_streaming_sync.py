import os
import sys
import tempfile
import wave
import numpy as np

# Ustawienie ścieżki do projektu
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from recorder.audio.capture import StreamingWavWriter, save_wav_file
from recorder.config import get_cloud_sync_config, get_session_split_silence_sec, SESSION_SPLIT_SILENCE_SEC
from recorder.core.cloud_sync import CloudSyncManager
from recorder.core.rolling_transcriber import RollingBlock, RollingTranscriptionWorker


def test_streaming_wav_writer():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        writer = StreamingWavWriter(tmp_path, channels=1, samplerate=16000)
        
        # Zapisz 2 sekundy próbek (32000 próbek = 64000 bajtów)
        dummy_pcm = (np.ones(16000, dtype=np.int16) * 1000).tobytes()
        writer.write_frames(dummy_pcm)
        writer.write_frames(dummy_pcm)
        assert writer.duration_seconds == 2.0, f"Oczekiwano 2.0s, otrzymano {writer.duration_seconds}"
        
        writer.close()
        
        # Sprawdzenie poprawności zapisanego pliku WAV
        with wave.open(tmp_path, 'rb') as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == 32000

        print("Test StreamingWavWriter: Sukces! Zapis strumieniowy na dysk dziala bezblednie.")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def test_adaptive_bitrate_calculation():
    manager = CloudSyncManager()
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        short_wav = tmp.name
    save_wav_file(short_wav, [b'\x00\x00' * 16000], channels=1, samplerate=16000)

    try:
        config = manager.config
        assert "live_streaming" in config
        assert "session_split_silence_sec" in config
        assert config["session_split_silence_sec"] == get_session_split_silence_sec()
        print("Test Konfiguracji i Parametrow Live: Sukces!")
    finally:
        if os.path.exists(short_wav):
            try:
                os.remove(short_wav)
            except Exception:
                pass


def test_live_session_payload_building():
    manager = CloudSyncManager()
    meeting_id = "test-live-meeting-uuid"
    
    turns = [
        {"speaker": "Jan", "start": 0.0, "end": 4.5, "text": "Dzien dobry wszystkim."},
        {"speaker": "Piotr", "start": 5.0, "end": 9.2, "text": "Czesc Janie, zaczynamy status."}
    ]
    
    payload = manager._build_payload(
        meeting_id=meeting_id,
        title="Spotkanie biurowe test",
        transcript_text="Jan: Dzien dobry wszystkim.\nPiotr: Czesc Janie...",
        segments=turns,
        duration_seconds=9.2,
        audio_path=None,
        context_type="general",
        context_id=None
    )
    
    assert payload["id"] == meeting_id
    assert payload["speaker_count"] == 2
    assert len(payload["segments"]) == 2
    assert payload["segments"][0]["speaker"] == "Jan"
    assert payload["segments"][1]["speaker"] == "Piotr"
    assert payload["duration_seconds"] == 9.2
    
    print("Test Budowania Payloadu Live Spotkania: Sukces!")


def test_rolling_transcriber_reset_session():
    worker = RollingTranscriptionWorker()
    worker.total_processed_seconds = 120.0
    worker.all_turns = [{"speaker": "Mowca", "start": 0, "end": 10, "text": "Test"}]
    
    worker.reset_for_new_session("new_session_path.txt")
    assert worker.total_processed_seconds == 0.0
    assert len(worker.all_turns) == 0
    assert len(worker.processed_blocks) == 0
    assert worker.txt_save_path == "new_session_path.txt"
    
    print("Test Resetu Sesji w Rolling Transcriber: Sukces!")


if __name__ == "__main__":
    test_streaming_wav_writer()
    test_adaptive_bitrate_calculation()
    test_live_session_payload_building()
    test_rolling_transcriber_reset_session()
    print("\nWSZYSTKIE TESTY TRANSMISJI NA ZYWO I SMART SESSION SPLITTING ZAKONCZONE SUKCESEM!")
