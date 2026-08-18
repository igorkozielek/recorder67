import os
import sys
import types
from typing import List, Dict, Any, Tuple, Optional, Callable
import numpy as np
import soundfile as sf
from recorder.config import get_hardware_acceleration_info, DEFAULT_WHISPER_MODEL


def apply_av_patches():
    """
    Omija błąd ładowania DLL w pakiecie 'av' na Windowsie (AppLocker/Security Control),
    tworząc bezpieczną atrapę modułu w sys.modules.
    """
    if 'av' not in sys.modules:
        av_mock = types.ModuleType('av')
        sys.modules['av'] = av_mock
        sys.modules['av.audio'] = types.ModuleType('av.audio')
        sys.modules['av.video'] = types.ModuleType('av.video')


class TranscriberEngine:
    """
    Silnik transkrypcji mowy oparty na faster-whisper z bezpiecznym wczytywaniem audio przez soundfile
    oraz wsparciem dla akceleracji CPU (int8) i CUDA (float16).
    """
    def __init__(
        self,
        model_size: str = DEFAULT_WHISPER_MODEL,
        device: str = None,
        compute_type: str = None,
        cpu_threads: int = None
    ):
        self.model_size = model_size
        hw_info = get_hardware_acceleration_info()
        self.device = device or hw_info["device"]
        self.compute_type = compute_type or hw_info["compute_type"]
        self.cpu_threads = cpu_threads or hw_info.get("cpu_threads", 4)
        self._model = None

    def load_model(self):
        """
        Ładuje model Whisper do pamięci z optymalnym typem obliczeń (CUDA float16 lub CPU int8).
        """
        if self._model is not None:
            return self._model

        apply_av_patches()

        from faster_whisper import WhisperModel

        init_kwargs = {
            "model_size_or_path": self.model_size,
            "device": self.device,
            "compute_type": self.compute_type
        }
        if self.device == "cpu" and self.cpu_threads:
            init_kwargs["cpu_threads"] = self.cpu_threads

        print(f"🎙️ [WHISPER] Ładowanie modelu '{self.model_size}' (urządzenie: {self.device.upper()}, precyzja: {self.compute_type})...")
        self._model = WhisperModel(**init_kwargs)
        print(f"✅ [WHISPER] Model '{self.model_size}' został pomyślnie załadowany do pamięci!")
        return self._model

    def transcribe_live_chunk(self, audio_float: np.ndarray, language: str = "pl") -> str:
        """
        Transkrybuje krótki fragment audio (16kHz float32 mono) w locie.
        """
        if self._model is None:
            self.load_model()

        segments, _ = self._model.transcribe(
            audio_float,
            language=language,
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=250),
            initial_prompt="Poniżej znajduje się polska wypowiedź dyktowana do notatek biurowych."
        )

        phrase_text = "".join([segment.text for segment in segments]).strip()
        
        # Odrzucanie artefaktów lub pustych znaków
        ignored_phrases = {".", "...", ",", "Dziękuję.", "Śpiewa", "Napisy:", "Subtitles"}
        if phrase_text in ignored_phrases:
            return ""

        return phrase_text

    def transcribe_file_with_words(
        self,
        audio_path: str,
        language: str = "pl",
        progress_callback: Optional[Callable[[float, float], None]] = None,
        duration_sec: float = 0.0,
        beam_size: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Transkrybuje cały plik audio i zwraca listę słów z precyzyjnymi timestampami word-level.
        Wczytuje dźwięk bezpośrednio przez soundfile (jako tablicę float32), eliminując zależność od biblioteki av.
        Optymalizacja CPU: vad_filter=True (Silero VAD pomija ciszę z zachowaniem 100% synchronizacji czasu)
        oraz beam_size=1 (3x szybsza inferencja na procesorze).
        """
        if self._model is None:
            self.load_model()

        # Bezpieczne wczytanie tablicy float32 przez soundfile
        audio_arr, sr = sf.read(audio_path, dtype='float32')
        if audio_arr.ndim > 1:
            audio_arr = np.mean(audio_arr, axis=1)

        initial_prompt = (
            "Transkrypcja oficjalnych i roboczych spotkań biznesowych, narad biurowych, "
            "dyskusji projektowych oraz ustaleń technicznych w języku polskim. "
            "Prawidłowa polska pisownia, interpunkcja, wielkie litery i podział na zdania."
        )

        # Przekazanie tablicy numpy bezpośrednio do modelu Whisper z filtrem VAD i promptem kontekstowym
        segments, _ = self._model.transcribe(
            audio_arr,
            word_timestamps=True,
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400),
            initial_prompt=initial_prompt
        )



        transcript_words = []
        last_logged_pct = -1

        for segment in segments:
            if segment.words:
                for word in segment.words:
                    if word.word and word.start is not None and word.end is not None:
                        transcript_words.append({
                            "word": word.word,
                            "start": word.start,
                            "end": word.end
                        })

            cur_time = segment.end
            ratio = min(1.0, max(0.0, cur_time / total_duration)) if total_duration > 0 else 0.0
            
            # Logowanie do konsoli co 10%
            pct = int(ratio * 100)
            if pct // 10 > last_logged_pct:
                last_logged_pct = pct // 10
                c_mins = int(cur_time // 60)
                c_secs = int(cur_time % 60)
                print(f"   [WHISPER Postęp] {pct}% ({c_mins}m {c_secs}s / {mins}m {secs}s) -> Ostatnia fraza: \"{segment.text.strip()}\"")

            if progress_callback:
                progress_callback(ratio, cur_time)

        print(f"✅ [WHISPER] Transkrypcja zakończona! Rozpoznano {len(transcript_words)} słów.")
        return transcript_words
