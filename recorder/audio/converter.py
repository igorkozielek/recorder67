import numpy as np


def resample_to_16k(audio_arr: np.ndarray, orig_sr: int) -> np.ndarray:
    """
    Interpoluje tablicę audio z pierwotnej częstotliwości próbkowania do 16000 Hz.
    """
    if orig_sr == 16000 or len(audio_arr) == 0:
        return audio_arr
    num_target = int(len(audio_arr) * 16000 / orig_sr)
    x_old = np.linspace(0, 1, len(audio_arr), endpoint=False)
    x_new = np.linspace(0, 1, num_target, endpoint=False)
    return np.interp(x_new, x_old, audio_arr).astype(np.float32)
