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
