import wave
import sys
from typing import List


def save_wav_file(file_path: str, frames: List[bytes], channels: int = 1, samplerate: int = 16000) -> bool:
    """
    Zapisuje surowe ramki bajtów audio (16-bit PCM) do pliku w formacie WAV.
    """
    if not frames:
        return False
    try:
        with wave.open(file_path, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)  # 16-bit PCM
            wf.setframerate(samplerate)
            wf.writeframes(b''.join(frames))
        return True
    except Exception as e:
        if sys.stderr:
            print(f"Błąd zapisu pliku WAV ({file_path}): {e}", file=sys.stderr)
        return False


class StreamingWavWriter:
    """
    Strumieniowy rejestrator WAV na dysku.
    Zapisuje ramki 16-bit PCM w partiach, dzięki czemu aplikacja nie kumuluje
    setek megabajtów audio w pamięci RAM podczas 8-godzinnych sesji nagraniowych.
    """
    def __init__(self, file_path: str, channels: int = 1, samplerate: int = 16000):
        self.file_path = file_path
        self.channels = channels
        self.samplerate = samplerate
        self._wf = None
        self._total_frames = 0
        self._open()

    def _open(self):
        try:
            self._wf = wave.open(self.file_path, 'wb')
            self._wf.setnchannels(self.channels)
            self._wf.setsampwidth(2)
            self._wf.setframerate(self.samplerate)
        except Exception as e:
            if sys.stderr:
                print(f"Błąd otwarcia StreamingWavWriter ({self.file_path}): {e}", file=sys.stderr)
            self._wf = None

    def write_frames(self, data: bytes):
        if self._wf is not None and data:
            try:
                self._wf.writeframes(data)
                self._total_frames += len(data) // (2 * self.channels)
            except Exception as e:
                if sys.stderr:
                    print(f"Błąd zapisu ramek w StreamingWavWriter: {e}", file=sys.stderr)

    @property
    def duration_seconds(self) -> float:
        if self.samplerate > 0:
            return round(self._total_frames / float(self.samplerate), 2)
        return 0.0

    def close(self) -> bool:
        if self._wf is not None:
            try:
                self._wf.close()
                self._wf = None
                return True
            except Exception as e:
                if sys.stderr:
                    print(f"Błąd zamykania pliku StreamingWavWriter: {e}", file=sys.stderr)
        return False
