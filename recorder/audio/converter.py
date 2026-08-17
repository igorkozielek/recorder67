import os
import sys
import subprocess
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
    automatycznie ekstrahuje dźwięk, konwertuje go do mono 16kHz PCM_16 i zapisuje jako plik WAV w `output_dir`.
    
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
                info = sf.info(target_path)
                duration_sec = info.duration
                if duration_sec < 0.2:
                    raise ValueError("Plik nie zawiera wystarczającej ilości danych dźwiękowych (mniej niż 0.2 sekundy).")
                return target_path, duration_sec
        except Exception as ffmpeg_err:
            if sys.stderr:
                print(f"Błąd ekstrakcji FFmpeg: {ffmpeg_err}", file=sys.stderr)

    # 2. METODA B: Odczyt przez soundfile (dla czystych plików WAV, FLAC, OGG, MP3)
    try:
        data, sr = sf.read(input_path, dtype='float32')
        if data.ndim > 1:
            data = np.mean(data, axis=1)

        if sr != 16000:
            audio_16k = resample_to_16k(data, sr)
        else:
            audio_16k = data.astype(np.float32)

        duration_sec = len(audio_16k) / 16000.0
        if duration_sec < 0.2:
            raise ValueError("Plik audio jest zbyt krótki (mniej niż 0.2 sekundy).")

        sf.write(target_path, audio_16k, 16000, subtype='PCM_16')
        return target_path, duration_sec
    except Exception as sf_err:
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

        if data_float.ndim > 1:
            data_float = np.mean(data_float, axis=1)

        if sr != 16000:
            audio_16k = resample_to_16k(data_float, sr)
        else:
            audio_16k = data_float

        duration_sec = len(audio_16k) / 16000.0
        if duration_sec < 0.2:
            raise ValueError("Plik audio jest zbyt krótki (mniej niż 0.2 sekundy).")

        sf.write(target_path, audio_16k, 16000, subtype='PCM_16')
        return target_path, duration_sec
    except Exception:
        raise ValueError(
            f"Nie udało się odczytać ścieżki dźwiękowej z pliku '{os.path.basename(input_path)}'.\n\n"
            f"Upewnij się, że plik zawiera ścieżkę dźwiękową (MP4, MKV, MOV, WAV, MP3, M4A, FLAC, OGG)."
        )
