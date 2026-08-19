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


# Wyrażenia halucynacyjne z korpusu treningowego (np. plansze końcowe YouTube / Amara.org)
HALLUCINATION_TRIGGERS = [
    "amara.org", "napisy stworzone przez", "subtitles", "dziękuję za obejrzenie",
    "dziękuję za uwagę", "w tym filmie przeczytam", "w tym filmie", "zobaczymy gdzie tu jest",
    "poniżej znajduje się", "to jest poniżej", "śpiewa", "muzyka", "subskrybuj",
    "do zobaczenia w kolejnym", "zostaw łapkę w górę", "miłego oglądania"
]


def is_hallucination(text: str) -> bool:
    """Sprawdza czy rozpoznany tekst zawiera znane halucynacje z korpusu YouTube/napisów."""
    if not text:
        return True
    lower_txt = text.lower().strip()
    if len(lower_txt) < 2 or lower_txt in {".", "...", ",", "?", "!", "dziękuję.", "dziękuję"}:
        return True
    return any(h in lower_txt for h in HALLUCINATION_TRIGGERS)


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

        print(f"[WHISPER] Ladowanie modelu '{self.model_size}' (urzadzenie: {self.device.upper()}, precyzja: {self.compute_type})...")
        self._model = WhisperModel(**init_kwargs)
        print(f"[WHISPER] Model '{self.model_size}' zostal pomyslnie zaladowany do pamieci!")
        return self._model


    def transcribe_live_chunk(self, audio_float: np.ndarray, language: str = "pl", context_prompt: str = "") -> str:
        """
        Transkrybuje krótki fragment audio (16kHz float32 mono) w locie z pamięcią kontekstu i ochroną przed halucynacjami.
        """
        if self._model is None:
            self.load_model()

        if len(audio_float) < int(0.4 * 16000):
            return ""

        # W Whisperze initial_prompt służy WYŁĄCZNIE jako kontekst poprzednich słów mowy.
        # Wstrzykiwanie sztucznych zdań instruktażowych powodowało ich powtarzanie przez dekoder przy ciszy.
        prompt = context_prompt.strip()[-150:] if (context_prompt and len(context_prompt.strip()) > 3) else None

        segments, _ = self._model.transcribe(
            audio_float,
            language=language,
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.2,
            vad_filter=True,
            vad_parameters=dict(
                threshold=0.4,
                min_speech_duration_ms=250,
                min_silence_duration_ms=400,
                speech_pad_ms=200
            ),
            initial_prompt=prompt
        )

        phrase_text = "".join([segment.text for segment in segments]).strip()
        if is_hallucination(phrase_text):
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
        Zawiera bezpieczny fallback: jeśli Whisper nie wygeneruje word-timestamps dla danego segmentu,
        słowa są automatycznie estymowane na osi czasu segmentu, gwarantując brak ucinania tekstu z początku nagrania.
        """
        if self._model is None:
            self.load_model()

        # Bezpieczne wczytanie tablicy float32 przez soundfile
        audio_arr, sr = sf.read(audio_path, dtype='float32')
        if audio_arr.ndim > 1:
            audio_arr = np.mean(audio_arr, axis=1)

        total_duration = duration_sec if duration_sec > 0 else (len(audio_arr) / float(sr))
        mins = int(total_duration // 60)
        secs = int(total_duration % 60)
        print(f"[WHISPER] Rozpoczęto pełną transkrypcję pliku (VAD filter=OFF [100% audio od 0.0s], beam_size={beam_size}): {os.path.basename(audio_path)} (Długość: {mins}m {secs}s)...")

        from recorder.config import get_env_variable
        custom_kw = get_env_variable("CUSTOM_KEYWORDS", "")
        extra_ctx = f", {custom_kw}" if custom_kw else ""

        initial_prompt = f"CRM, Helpdesk, Subiekt, synchronizacja, harmonogram, rejestr zmian, zgłoszenia, zamówienia{extra_ctx}."

        # Transkrypcja całego nagrania bez wycinania przez filtr VAD (gwarancja braku ucinania początku)
        segments, _ = self._model.transcribe(
            audio_arr,
            word_timestamps=True,
            language=language,
            beam_size=beam_size,
            vad_filter=False,
            initial_prompt=initial_prompt
        )

        transcript_words = []
        last_logged_pct = -1
        first_speech_logged = False

        for segment in segments:
            seg_text = segment.text.strip() if segment.text else ""
            if not seg_text or is_hallucination(seg_text):
                continue

            # Logowanie pierwszej wykrytej mowy
            if not first_speech_logged:
                first_speech_logged = True
                s_mins = int(segment.start // 60)
                s_secs = int(segment.start % 60)
                e_mins = int(segment.end // 60)
                e_secs = int(segment.end % 60)
                print(f"🎙️ [WHISPER] Pierwsza wykryta mowa: [{s_mins:02d}:{s_secs:02d} - {e_mins:02d}:{e_secs:02d}] (od {segment.start:.1f}s): \"{seg_text[:70]}...\"")

            # 1. Sprawdzamy czy Whisper wygenerował dokładne znaczniki słów dla tego segmentu
            has_valid_words = False
            if segment.words:
                valid_words = [
                    w for w in segment.words
                    if w.word and w.start is not None and w.end is not None
                ]
                if valid_words:
                    has_valid_words = True
                    for word in valid_words:
                        transcript_words.append({
                            "word": word.word,
                            "start": word.start,
                            "end": word.end
                        })

            # 2. Bezpieczny Fallback: jeśli z powodu cichego głosu/szumu segment nie ma word-timestamps,
            # estymujemy timestampy słów z segment.start i segment.end, aby NIGDY nie zgubić tekstu!
            if not has_valid_words and seg_text:
                raw_words = seg_text.split()
                if raw_words:
                    seg_dur = max(0.1, segment.end - segment.start)
                    step = seg_dur / len(raw_words)
                    for i, rw in enumerate(raw_words):
                        w_s = segment.start + (i * step)
                        w_e = segment.start + ((i + 1) * step)
                        transcript_words.append({
                            "word": (" " + rw) if i > 0 else rw,
                            "start": round(w_s, 3),
                            "end": round(w_e, 3)
                        })

            cur_time = segment.end
            ratio = min(1.0, max(0.0, cur_time / total_duration)) if total_duration > 0 else 0.0

            # Logowanie do konsoli co 10%
            pct = int(ratio * 100)
            if pct // 10 > last_logged_pct:
                last_logged_pct = pct // 10
                c_mins = int(cur_time // 60)
                c_secs = int(cur_time % 60)
                print(f"   [WHISPER Postęp] {pct}% ({c_mins}m {c_secs}s / {mins}m {secs}s)")

            if progress_callback:
                progress_callback(ratio, cur_time)

        print(f"[WHISPER] Transkrypcja zakończona! Rozpoznano łącznie {len(transcript_words)} słów.")
        return transcript_words

