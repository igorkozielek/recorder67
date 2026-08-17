import os
import sys
from datetime import datetime
from typing import Tuple
import numpy as np
import soundfile as sf


def resample_to_16k(audio_arr: np.ndarray, orig_sr: int) -> np.ndarray:
    """
    Interpoluje tablicę audio z pierwotnej częstotliwości próbkowania do 16000 Hz.
    """
    if orig_sr == 16000 or len(audio_arr) == 0:
        return audio_arr.astype(np.float32)
    num_target = int(len(audio_arr) * 16000 / orig_sr)
    x_old = np.linspace(0, 1, len(audio_arr), endpoint=False)
    x_new = np.linspace(0, 1, num_target, endpoint=False)
    return np.interp(x_new, x_old, audio_arr).astype(np.float32)


def read_audio_data(file_path: str) -> Tuple[np.ndarray, int]:
    """
    Bezpiecznie odczytuje dane audio z dowolnego pliku audio LUB wideo (np. .mp4, .mkv, .mov, .webm)
    bez wymagania zewnętrznego narzędzia FFmpeg w PATH.
    Automatycznie ekstrahuje samą ścieżkę dźwiękową ze strumienia multimedialnego.
    Zwraca (audio_float32_mono, sample_rate).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Plik nie istnieje: {file_path}")

    # 1. Próba odczytu przez soundfile (najszybsza dla czystych plików audio WAV, FLAC, OGG, MP3)
    try:
        data, sr = sf.read(file_path, dtype='float32')
        if data.ndim > 1:
            data = np.mean(data, axis=1)  # konwersja do mono
        return data, sr
    except Exception:
        pass

    # 2. Próba odczytu przez PyAV (obsługuje wideo MP4, MKV, MOV, WEBM oraz kontenery M4A, AAC, MP3)
    try:
        import av
        container = av.open(file_path)
        audio_stream = next((s for s in container.streams if s.type == 'audio'), None)
        if audio_stream is None:
            raise ValueError("Plik multimedialny nie zawiera żadnej ścieżki dźwiękowej (audio).")

        frames = []
        for frame in container.decode(audio_stream):
            arr = frame.to_ndarray()
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            elif arr.ndim == 2 and arr.shape[0] > arr.shape[1] and arr.shape[1] <= 8:
                arr = arr.T
            frames.append(arr)

        if not frames:
            raise ValueError("Nie udało się zdekodować żadnych próbek audio ze strumienia.")

        full_arr = np.concatenate(frames, axis=1)
        sr = audio_stream.rate or audio_stream.codec_context.sample_rate or 16000

        # Sprowadzenie typu danych do znormalizowanego float32 [-1.0, 1.0]
        if full_arr.dtype == np.int16:
            full_arr = full_arr.astype(np.float32) / 32768.0
        elif full_arr.dtype == np.int32:
            full_arr = full_arr.astype(np.float32) / 2147483648.0
        elif full_arr.dtype == np.uint8:
            full_arr = (full_arr.astype(np.float32) - 128.0) / 128.0
        else:
            full_arr = full_arr.astype(np.float32)

        # Miksowanie kanałów do mono (średnia z kanałów)
        if full_arr.ndim > 1:
            mono_arr = np.mean(full_arr, axis=0)
        else:
            mono_arr = full_arr

        return mono_arr, sr
    except Exception as av_err:
        pass

    # 3. Ostateczna próba przez scipy.io.wavfile (dla niestandardowych nagłówków WAV)
    try:
        from scipy.io import wavfile
        sr, data = wavfile.read(file_path)
        if data.dtype == np.int16:
            data_float = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data_float = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            data_float = (data.astype(np.float32) - 128.0) / 128.0
        else:
            data_float = data.astype(np.float32)

        if data_float.ndim > 1:
            data_float = np.mean(data_float, axis=1)

        return data_float, sr
    except Exception:
        raise ValueError(
            f"Nie udało się odczytać dźwięku z pliku '{os.path.basename(file_path)}'.\n"
            f"Upewnij się, że plik zawiera ścieżkę dźwiękową (WAV, MP3, MP4, M4A, FLAC, OGG, MKV, MOV)."
        )


def prepare_audio_file(input_path: str, output_dir: str) -> Tuple[str, float]:
    """
    Wczytuje dowolny plik audio LUB wideo (np. .mp4 ze spotkania Zoom/Teams),
    automatycznie ekstrahuje dźwięk, konwertuje go do mono 16kHz float32 i zapisuje jako standardowy
    plik WAV w `output_dir`.
    Zwraca: (sciezka_do_pliku_wav, czas_trwania_sekundy).
    """
    os.makedirs(output_dir, exist_ok=True)
    audio_data, sr = read_audio_data(input_path)

    # Resampling do 16000 Hz
    if sr != 16000:
        audio_16k = resample_to_16k(audio_data, sr)
    else:
        audio_16k = audio_data.astype(np.float32)

    duration_sec = len(audio_16k) / 16000.0
    if duration_sec < 0.2:
        raise ValueError("Plik nie zawiera wystarczającej ilości danych dźwiękowych (mniej niż 0.2 sekundy).")

    # Generowanie czytelnej i bezpiecznej nazwy pliku docelowego
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_base = "".join(c for c in base_name if c.isalnum() or c in (' ', '_', '-')).strip()
    if not safe_base:
        safe_base = "wgrany_plik"
    
    target_filename = f"plik_{safe_base}_{timestamp}.wav"
    target_path = os.path.join(output_dir, target_filename)

    # Zapis w standardowym formacie 16-bit PCM WAV (16kHz mono)
    sf.write(target_path, audio_16k, 16000, subtype='PCM_16')

    return target_path, duration_sec
