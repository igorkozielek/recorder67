import os
import sys
import numpy as np

_silero_model = None
_silero_available = False

try:
    import torch
    import io
    import warnings
    import silero_vad
    jit_path = os.path.join(os.path.dirname(silero_vad.__file__), 'data', 'silero_vad.jit')
    if os.path.exists(jit_path):
        with open(jit_path, 'rb') as f:
            model_bytes = io.BytesIO(f.read())
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _silero_model = torch.jit.load(model_bytes)
            _silero_model.eval()
            _silero_available = True
            print("Sukces: Model Silero VAD AI został pomyślnie załadowany do pamięci!")
    else:
        from silero_vad import load_silero_vad
        _silero_model = load_silero_vad()
        _silero_available = True
except Exception as e:
    print(f"Informacja VAD: {e}")


import threading
_silero_lock = threading.Lock()

def is_silero_available() -> bool:
    return _silero_available and _silero_model is not None


class SileroVADDetector:
    """
    Klasa odpowiedzialna za detekcję aktywności głosowej (Voice Activity Detection)
    z użyciem sieci neuronowej Silero VAD. Obsługuje dowolne rozmiary próbek wejściowych
    dzięki wewnętrznemu buforowaniu do wymaganych okien (512 próbek / 32ms @ 16kHz).
    """
    def __init__(self, speech_threshold: float = 0.35, default_samplerate: int = 16000):
        self.speech_threshold = speech_threshold
        self.samplerate = default_samplerate
        self._buffer = np.array([], dtype=np.float32)
        self._last_speech_prob = 0.0

    def reset(self):
        """Czyści wewnętrzny bufor próbek."""
        self._buffer = np.array([], dtype=np.float32)
        self._last_speech_prob = 0.0

    def process_chunk(self, audio_data: np.ndarray, samplerate: int = 16000, rms_level: float = 0.0):
        """
        Analizuje fragment audio i zwraca (is_speech, speech_prob).
        Bezpiecznie przetwarza pakiety o dowolnej długości (thread-safe).
        """
        if audio_data is None or len(audio_data) == 0:
            return (self._last_speech_prob >= self.speech_threshold), self._last_speech_prob

        flat_audio = audio_data.flatten().astype(np.float32)
        self._buffer = np.append(self._buffer, flat_audio)

        # Obliczenie RMS bieżącego fragmentu
        norm = float(np.linalg.norm(flat_audio))
        chunk_rms = (norm / np.sqrt(len(flat_audio))) if len(flat_audio) > 0 else 0.0

        if is_silero_available():
            while len(self._buffer) >= 512:
                chunk_512 = self._buffer[:512]
                self._buffer = self._buffer[512:]
                try:
                    import torch
                    tensor_data = torch.from_numpy(chunk_512).float()
                    with _silero_lock:
                        self._last_speech_prob = float(_silero_model(tensor_data, 16000).item())
                except Exception:
                    pass
        else:
            if len(self._buffer) > 2048:
                self._buffer = self._buffer[-512:]
            self._last_speech_prob = 1.0 if rms_level > 5.0 or chunk_rms > 0.02 else 0.0

        # Mowa wykryta gdy Silero VAD przekracza próg lub przy słyszalnym poziomie głośności
        is_speech = (self._last_speech_prob >= self.speech_threshold) or (rms_level > 4.0) or (chunk_rms > 0.01)
        return is_speech, self._last_speech_prob
