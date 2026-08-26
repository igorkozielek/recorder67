import os
import sys
import subprocess
from datetime import datetime
from typing import Tuple
import numpy as np
import soundfile as sf


def mix_to_mono(audio_arr: np.ndarray) -> np.ndarray:
    """
    Inteligentnie miksuje wielokanałowe audio do mono:
    - Jeśli jeden kanał jest wyraźnie głośniejszy (np. mikrofon stereo/combo nagrywał tylko na lewym kanale),
      wybiera dominujący kanał zamiast tłumić go przez uśrednianie z ciszą.
    - W przeciwnym razie wylicza średnią arytmetyczną z kanałów.
    """
    if audio_arr.ndim <= 1:
        return audio_arr.astype(np.float32)

    num_channels = audio_arr.shape[1] if audio_arr.ndim > 1 else 1
    if num_channels == 1:
        return audio_arr[:, 0].astype(np.float32) if audio_arr.ndim > 1 else audio_arr.astype(np.float32)

    # Oblicz RMS dla każdego kanału
    channel_rms = [float(np.sqrt(np.mean(audio_arr[:, ch] ** 2))) for ch in range(num_channels)]
    max_rms = max(channel_rms)
    min_rms = min(channel_rms)

    # Jeśli jeden kanał to cisza (< 15% głośności drugiego), bierzemy kanał z sygnałem
    if max_rms > 0.001 and min_rms < (0.15 * max_rms):
        best_ch = int(np.argmax(channel_rms))
        return audio_arr[:, best_ch].astype(np.float32)

    # Standardowy miks średniej
    return np.mean(audio_arr, axis=1).astype(np.float32)


def highpass_filter_audio(audio_arr: np.ndarray, sr: int = 16000, cutoff_hz: float = 80.0) -> np.ndarray:
    """
    Stosuje filtr górnoprzepustowy (High-Pass ~80Hz) eliminujący dudnienia biurka,
    podmuchy powietrza i przydźwięk sieciowy 50Hz, nie zniekształcając pasma mowy ludzkiej (100Hz - 8kHz).
    """
    if len(audio_arr) < 16:
        return audio_arr.astype(np.float32)
    try:
        from scipy.signal import butter, sosfilt
        sos = butter(2, cutoff_hz, btype='highpass', fs=sr, output='sos')
        filtered = sosfilt(sos, audio_arr).astype(np.float32)
        return np.nan_to_num(filtered, nan=0.0, posinf=1.0, neginf=-1.0)
    except Exception:
        # Lekki fallback IIR 1st-order: y[n] = alpha * (y[n-1] + x[n] - x[n-1])
        rc = 1.0 / (2.0 * np.pi * cutoff_hz)
        dt = 1.0 / sr
        alpha = rc / (rc + dt)
        filtered = np.empty_like(audio_arr, dtype=np.float32)
        filtered[0] = audio_arr[0]
        for i in range(1, len(audio_arr)):
            filtered[i] = alpha * (filtered[i-1] + audio_arr[i] - audio_arr[i-1])
        return filtered


def normalize_audio(audio_arr: np.ndarray, target_peak: float = 0.92) -> np.ndarray:
    """
    Normalizuje poziom głośności tablicy audio (Peak Normalization), jeśli sygnał jest cichy (np. cichy dyktafon).
    Zapobiega wycinaniu cichych głosów przez Silero VAD i ułatwia transkrypcję modelowi Whisper.
    """
    if len(audio_arr) == 0:
        return audio_arr.astype(np.float32)

    max_val = float(np.max(np.abs(audio_arr)))
    if 0.0001 < max_val < 0.75:
        scale = min(target_peak / max_val, 8.0)
        return (audio_arr * scale).astype(np.float32)
    elif max_val >= 1.0:
        return (audio_arr / (max_val + 1e-6) * target_peak).astype(np.float32)
    return audio_arr.astype(np.float32)


def preprocess_speech_audio(audio_arr: np.ndarray, orig_sr: int = 16000) -> np.ndarray:
    """
    Kompleksowy preprocessing mowy: miks do mono, resampling do 16kHz, filtr High-Pass 80Hz i normalizacja głośności.
    """
    mono = mix_to_mono(audio_arr)
    if orig_sr != 16000:
        resampled = resample_to_16k(mono, orig_sr)
    else:
        resampled = mono
    filtered = highpass_filter_audio(resampled, sr=16000, cutoff_hz=80.0)
    normalized = normalize_audio(filtered, target_peak=0.92)
    return normalized


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


def get_embedded_ffmpeg_exe() -> str:
    """
    Pobiera ścieżkę do wbudowanego w paczkę Pythona pliku binarnego FFmpeg (z imageio-ffmpeg).
    Nie wymaga instalowania FFmpeg w systemie Windows ani dodawania do PATH.
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


def prepare_audio_file(input_path: str, output_dir: str) -> Tuple[str, float]:
    """
    Wczytuje dowolny plik audio LUB wideo (np. .mp4 ze spotkań Zoom/Teams/Google Meet, .mkv, .mov, .mp3, .m4a),
    automatycznie ekstrahuje dźwięk, konwertuje go do mono 16kHz PCM_16 z automatyczną normalizacją głośności
    i zapisuje jako plik WAV w `output_dir`.
    
    Działa w 100% samowystarczalnie – bez konieczności ręcznego instalowania FFmpeg w systemie Windows!
    Zwraca: (sciezka_do_pliku_wav, czas_trwania_sekundy).
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Wybrany plik nie istnieje: {input_path}")

    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_base = "".join(c for c in base_name if c.isalnum() or c in (' ', '_', '-')).strip()
    if not safe_base:
        safe_base = "wgrany_plik"
    
    target_filename = f"plik_{safe_base}_{timestamp}.wav"
    target_path = os.path.join(output_dir, target_filename)

    # 1. METODA A: Ekstrakcja za pomocą wbudowanego imageio-ffmpeg (obsługuje dowolne MP4, MKV, MOV, WEBM, M4A, MP3)
    ffmpeg_exe = get_embedded_ffmpeg_exe()
    if ffmpeg_exe and os.path.exists(ffmpeg_exe):
        try:
            # -vn = ignoruj wideo, -ac 1 = mono, -ar 16000 = 16kHz, -f wav = format wav PCM_16
            cmd = [
                ffmpeg_exe,
                "-y",
                "-i", input_path,
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                "-acodec", "pcm_s16le",
                "-f", "wav",
                target_path
            ]
            # Uruchomienie bez pokazywania okna konsoli
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                check=True
            )

            if os.path.exists(target_path) and os.path.getsize(target_path) > 44:
                # Wczytanie i kompleksowy preprocessing audio
                data, sr = sf.read(target_path, dtype='float32')
                data_proc = preprocess_speech_audio(data, orig_sr=sr)
                sf.write(target_path, data_proc, 16000, subtype='PCM_16')

                duration_sec = len(data_proc) / 16000.0
                if duration_sec < 0.2:
                    raise ValueError("Plik nie zawiera wystarczającej ilości danych dźwiękowych (mniej niż 0.2 sekundy).")
                return target_path, duration_sec
        except Exception as ffmpeg_err:
            if sys.stderr:
                print(f"Błąd ekstrakcji FFmpeg: {ffmpeg_err}", file=sys.stderr)

    # 2. METODA B: Odczyt przez soundfile (dla czystych plików WAV, FLAC, OGG, MP3)
    try:
        data, sr = sf.read(input_path, dtype='float32')
        audio_proc = preprocess_speech_audio(data, orig_sr=sr)
        duration_sec = len(audio_proc) / 16000.0
        if duration_sec < 0.2:
            raise ValueError("Plik audio jest zbyt krótki (mniej niż 0.2 sekundy).")

        sf.write(target_path, audio_proc, 16000, subtype='PCM_16')
        return target_path, duration_sec
    except Exception:
        pass

    # 3. METODA C: Odczyt przez scipy.io.wavfile
    try:
        from scipy.io import wavfile
        sr, data = wavfile.read(input_path)
        if data.dtype == np.int16:
            data_float = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data_float = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            data_float = (data.astype(np.float32) - 128.0) / 128.0
        else:
            data_float = data.astype(np.float32)

        audio_proc = preprocess_speech_audio(data_float, orig_sr=sr)
        duration_sec = len(audio_proc) / 16000.0
        if duration_sec < 0.2:
            raise ValueError("Plik audio jest zbyt krótki (mniej niż 0.2 sekundy).")

        sf.write(target_path, audio_proc, 16000, subtype='PCM_16')
        return target_path, duration_sec
    except Exception:
        raise ValueError(
            f"Nie udało się odczytać ścieżki dźwiękowej z pliku '{os.path.basename(input_path)}'.\n\n"
            f"Upewnij się, że plik zawiera ścieżkę dźwiękową (MP4, MKV, MOV, WAV, MP3, M4A, FLAC, OGG)."
        )
