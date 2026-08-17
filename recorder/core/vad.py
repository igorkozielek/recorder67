import os
import sys
import numpy as np

_silero_model = None
_silero_available = False

try:
    import torch
    import io
    import silero_vad
    jit_path = os.path.join(os.path.dirname(silero_vad.__file__), 'data', 'silero_vad.jit')
    if os.path.exists(jit_path):
        with open(jit_path, 'rb') as f:
            model_bytes = io.BytesIO(f.read())
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


def is_silero_available() -> bool:
    return _silero_available and _silero_model is not None


class SileroVADDetector:
    """
    Klasa odpowiedzialna za detekcję aktywności głosowej (Voice Activity Detection).
    """
    def __init__(self, speech_threshold: float = 0.45, default_samplerate: int = 16000):
        self.speech_threshold = speech_threshold
        self.samplerate = default_samplerate

    def process_chunk(self, audio_data: np.ndarray, samplerate: int = 16000, rms_level: float = 0.0):
        """
        Zwraca (is_speech, speech_prob).
        """
        if is_silero_available():
            try:
                import torch
                tensor_data = torch.from_numpy(audio_data.flatten()).float()
                speech_prob = _silero_model(tensor_data, samplerate).item()
                is_speech = speech_prob >= self.speech_threshold
                return is_speech, speech_prob
            except Exception:
                is_speech = rms_level > 12.0
                return is_speech, (1.0 if is_speech else 0.0)
        else:
            is_speech = rms_level > 12.0
            return is_speech, (1.0 if is_speech else 0.0)
