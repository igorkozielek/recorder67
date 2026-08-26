import os
import sys
import types
from typing import List, Dict, Any, Tuple, Optional, Callable
import numpy as np
import soundfile as sf
from recorder.config import (
    get_hardware_acceleration_info,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_BEAM_SIZE,
    DEFAULT_INITIAL_PROMPT,
    get_full_initial_prompt,
    get_beam_size
)
from recorder.audio.converter import preprocess_speech_audio, highpass_filter_audio, normalize_audio


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


import re
from collections import Counter

# Wyrażenia halucynacyjne z korpusu treningowego (np. plansze końcowe YouTube / Amara.org / angielskie prompty)
HALLUCINATION_TRIGGERS = [
    "amara.org", "napisy stworzone przez", "subtitles", "dziękuję za obejrzenie",
    "dziękuję za uwagę", "dziękuje za oglądanie", "dziękuję za oglądanie",
    "w tym filmie przeczytam", "w tym filmie", "zobaczymy gdzie tu jest",
    "poniżej znajduje się", "to jest poniżej", "śpiewa", "muzyka", "subskrybuj",
    "do zobaczenia w kolejnym", "zostaw łapkę w górę", "miłego oglądania",
    "the user", "stop what you are doing", "write for the user",
    "searching web", "search the web", "hadi doyalım"
]

NON_SPEECH_SOUNDS = {
    "uch", "uh", "uhm", "mhm", "yhm", "eee", "aaa", "ehm", "mmm",
    "uff", "ach", "och", "oj", "uhuhu", "ehehe", "aha", "hm", "hmm",
    "ha", "haha", "hahaha", "kof", "cough", "he", "hehe", "hi", "ehe"
}

ISOLATED_NOISE_GREETINGS = {
    "dzień dobry", "dzień dobry.", "dzień dobry!", "dzień dobry?",
    "dzień dobry dzień dobry", "dzień dobry dzień dobry.", "dzień dobry dzień dobry!",
    "dziękuję", "dziękuję.", "dziękuję!", "dzięki", "dzięki.", "dzięki!",
    "dzięki za oglądanie", "dzięki za oglądanie.", "dzięki za oglądanie!",
    "dziękuję za oglądanie", "dziękuję za oglądanie.", "dziękuję za oglądanie!",
    "dziękuję za uwagę", "dziękuję za uwagę.", "dziękuje za uwagę.", "dziękuje za uwagę",
    "do widzenia", "do widzenia.", "do widzenia!", "pozdrawiam", "pozdrawiam.", "pozdrawiam!",
    "koniec", "koniec.", "koniec!"
}


def clean_repeated_text(text: str) -> str:
    """
    Ogólne, algorytmiczne usuwanie zapętleń słów, fraz (1-gramów, 2-gramów, 3-gramów),
    jąkania, powtarzających się ciągów cyfr i wielokropków oraz normalizacja spacji.
    """
    if not text:
        return ""
    
    # 1. Wykrywanie ciągów powtarzających się samych cyfr (np. "10 10 10 10 11 11 12 15 15 15")
    words = text.split()
    digit_words = [w.strip(".,!?:;") for w in words if w.strip(".,!?:;").isdigit()]
    if len(digit_words) >= 5 and (len(digit_words) / max(1, len(words))) > 0.5:
        return ""

    cleaned = text

    # 2. Usuwanie zapętleń słów z wielokropkami (np. '...pośle... ...pośle... ...pośle...')
    cleaned = re.sub(r'(?:\.{2,}\s*)?([A-Za-z0-9ĄąĆćĘęŁłŃńÓóŚśŹźŻż\'-]+)(?:\.{2,})?(?:\s*(?:\.{2,}\s*)?\1(?:\.{2,})?){2,}', r'\1', cleaned, flags=re.IGNORECASE)

    # 3. Usuwanie pojedynczego słowa powtórzonego wielokrotnie z interpunkcją (np. 'Uch, uch, uch...' lub 'dobra, dobra, dobra')
    cleaned = re.sub(r'\b([A-Za-z0-9ĄąĆćĘęŁłŃńÓóŚśŹźŻż\'-]+)(?:\s*[\,\.\?\!]\s*|\s+)(?:\1(?:\s*[\,\.\?\!]\s*|\s+))+\1(?:\b|[\,\.\?\!]*)', r'\1', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b([A-Za-z0-9ĄąĆćĘęŁłŃńÓóŚśŹźŻż\'-]+)(?:[\,\.\?\!]*)?(?:\s+\1(?:[\,\.\?\!]*)?){2,}', r'\1', cleaned, flags=re.IGNORECASE)

    # 3.5 Zabezpieczenie przed halucynacyjnymi ciągami "niech, niech, niech", "ha, ha, ha", "tak, tak, tak" oddzielonymi interpunkcją
    cleaned = re.sub(r'\b([A-Za-z0-9ĄąĆćĘęŁłŃńÓóŚśŹźŻż\'-]{1,15})(?:[\,\.\?\!]\s*|\s+)(?:\1(?:[\,\.\?\!]\s*|\s+)){2,}', r'\1 ', cleaned, flags=re.IGNORECASE)

    # 4. Usuwanie fraz 2-3 słów powtórzonych wielokrotnie (np. 'nie ma, nie ma, nie ma' -> 'nie ma')
    cleaned = re.sub(r'\b([A-Za-z0-9ĄąĆćĘęŁłŃńÓóŚśŹźŻż\'-]+(?:\s+[A-Za-z0-9ĄąĆćĘęŁłŃńÓóŚśŹźŻż\'-]+){1,2})(?:[\,\.\?\!]*)?(?:\s*[\,\.\?\!]*\s*\1(?:[\,\.\?\!]*)?){1,}', r'\1', cleaned, flags=re.IGNORECASE)

    # 5. Normalizacja spacji wokół liczb, godzin, łączników i apostrofów (np. '11 .30' -> '11.30', 'CRM -a' -> 'CRM-a')
    cleaned = re.sub(r'(\d+)\s*([\.,])\s*(\d+)', r'\1\2\3', cleaned)
    cleaned = re.sub(r'([A-Za-z0-9ĄąĆćĘęŁłŃńÓóŚśŹźŻż]+)\s*([\'\-])\s*([A-Za-z0-9ĄąĆćĘęŁłŃńÓóŚśŹźŻż]+)', r'\1\2\3', cleaned)

    # 6. Czyszczenie zwielokrotnionych wielokropków i białych znaków
    cleaned = re.sub(r'(\s*\.{2,}\s*){2,}', ' ... ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def filter_repeated_words_list(words: List[Dict[str, Any]], max_consecutive: int = 2) -> List[Dict[str, Any]]:
    """
    Filtruje listę słów (ze znacznikami start/end), zapobiegając dodawaniu patologicznych pętli
    powtórzeń pojedynczych słów (1-gram) oraz par słów (2-gram, np. 100x 'nie ma').
    """
    if not words or len(words) <= 2:
        return words or []

    # 1. Filtrowanie pętli 1-słownych (np. 50x 'niech')
    stage1 = []
    current_norm = None
    repeat_count = 0

    for w in words:
        w_text = w.get("word", "") if isinstance(w, dict) else getattr(w, "word", str(w))
        norm = re.sub(r'[^\w]', '', str(w_text)).strip().lower()
        if not norm:
            stage1.append(w)
            continue

        if norm == current_norm:
            repeat_count += 1
        else:
            current_norm = norm
            repeat_count = 1

        if repeat_count <= max_consecutive:
            stage1.append(w)

    if len(stage1) < 4:
        return stage1

    # 2. Filtrowanie pętli 2-słownych (np. 'nie ma, nie ma, nie ma...')
    stage2 = []
    i = 0
    while i < len(stage1):
        if i + 3 < len(stage1):
            w1_norm = re.sub(r'[^\w]', '', str(stage1[i].get("word", "") if isinstance(stage1[i], dict) else getattr(stage1[i], "word", ""))).strip().lower()
            w2_norm = re.sub(r'[^\w]', '', str(stage1[i+1].get("word", "") if isinstance(stage1[i+1], dict) else getattr(stage1[i+1], "word", ""))).strip().lower()
            w3_norm = re.sub(r'[^\w]', '', str(stage1[i+2].get("word", "") if isinstance(stage1[i+2], dict) else getattr(stage1[i+2], "word", ""))).strip().lower()
            w4_norm = re.sub(r'[^\w]', '', str(stage1[i+3].get("word", "") if isinstance(stage1[i+3], dict) else getattr(stage1[i+3], "word", ""))).strip().lower()

            # Wykrycie powtórzenia 2-gramu: (A, B) == (A, B)
            if w1_norm and w2_norm and w1_norm == w3_norm and w2_norm == w4_norm:
                # Dodaj parę początkową
                stage2.append(stage1[i])
                stage2.append(stage1[i+1])
                i += 2
                # Pomiń wszystkie kolejne identyczne pary powtórzeń (A, B)
                while i + 1 < len(stage1):
                    next_w1 = re.sub(r'[^\w]', '', str(stage1[i].get("word", "") if isinstance(stage1[i], dict) else getattr(stage1[i], "word", ""))).strip().lower()
                    next_w2 = re.sub(r'[^\w]', '', str(stage1[i+1].get("word", "") if isinstance(stage1[i+1], dict) else getattr(stage1[i+1], "word", ""))).strip().lower()
                    if next_w1 == w1_norm and next_w2 == w2_norm:
                        i += 2
                    else:
                        break
                continue

        stage2.append(stage1[i])
        i += 1

    return stage2


def is_hallucination(raw_text: str, cleaned_text: Optional[str] = None) -> bool:
    """
    Kompleksowe wykrywanie halucynacji Whispera:
    1. Jeśli surowy segment to czysta pętla powtórzeń w ciszy (np. 15x 'KONIEC' lub 10x 'niech') -> ODRZUCA.
    2. Jeśli segment zawierał wartościowe zdanie i pętlę na końcu -> ZACHOWUJE (dzięki ocenie zróżnicowania słów).
    3. Wykrywa plansze YouTube, odgłosy tła i samotne pozdrowienia w ciszy.
    """
    if not raw_text or not raw_text.strip():
        return True

    effective_cleaned = cleaned_text if cleaned_text is not None else clean_repeated_text(raw_text)
    lower_raw = raw_text.lower().strip()
    lower_cleaned = effective_cleaned.lower().strip()

    raw_tokens = [re.sub(r'[^\w]', '', w) for w in lower_raw.split()]
    raw_tokens = [w for w in raw_tokens if w]

    cleaned_tokens = [re.sub(r'[^\w]', '', w) for w in lower_cleaned.split()]
    cleaned_tokens = [w for w in cleaned_tokens if w]

    if not cleaned_tokens or len(lower_cleaned) < 2 or lower_cleaned in {".", "...", ",", "?", "!"}:
        return True

    # 1. Sprawdzenie czy tekst składa się wyłącznie z odgłosów/westchnień/onomatopei
    if all(w in NON_SPEECH_SOUNDS for w in cleaned_tokens):
        return True

    # 2. Wykrywanie CZYSTEJ halucynacji w ciszy (gdy surowy tekst miał wiele słów, ale to było 1-2 słowa w kółko)
    if len(raw_tokens) >= 5:
        unique_raw = set(raw_tokens)
        raw_unique_ratio = len(unique_raw) / len(raw_tokens)
        counts = Counter(raw_tokens)
        most_common_word, most_common_count = counts.most_common(1)[0]
        raw_dominance = most_common_count / len(raw_tokens)

        # Jeśli jedno słowo stanowi > 70% surowego bloku i unikalnych słów jest <= 2
        # Oznacza to, że cały segment był pustą pętlą Whispera na szumie (np. 15x 'KONIEC' lub 10x 'niech')
        if raw_dominance >= 0.70 and len(unique_raw) <= 2:
            return True

        # Jeśli po wyczyszczeniu drastycznie spadła liczba słów (np. z 10 słów do 1), to był czysty spam
        if len(cleaned_tokens) <= 1 and len(raw_tokens) >= 4:
            return True

    # 3. Analiza zróżnicowania w wyczyszczonym tekście
    if len(cleaned_tokens) >= 4:
        unique_ratio = len(set(cleaned_tokens)) / len(cleaned_tokens)
        if unique_ratio < 0.38:
            return True
        c_counts = Counter(cleaned_tokens)
        most_common_count = c_counts.most_common(1)[0][1]
        threshold = 0.6 if len(cleaned_tokens) < 15 else 0.55
        if (most_common_count / len(cleaned_tokens)) > threshold:
            return True

    # 4. Odrzucanie samotnych, krótkich powitań/podziękowań generowanych z szumu w ciszy (<= 4 słowa)
    if len(cleaned_tokens) <= 4:
        for tr in ISOLATED_NOISE_GREETINGS:
            if tr in lower_cleaned or tr in lower_raw:
                return True
        for h in HALLUCINATION_TRIGGERS:
            if h in lower_cleaned or h in lower_raw:
                return True

    return False


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


    def transcribe_live_chunk(self, audio_float: np.ndarray, language: str = "pl", context_prompt: str = "", beam_size: Optional[int] = None) -> str:
        """
        Transkrybuje krótki fragment audio (16kHz float32 mono) w locie z pamięcią kontekstu,
        filtrem szumów i wyszukiwaniem wiązkowym (beam search).
        """
        if self._model is None:
            self.load_model()

        if len(audio_float) < int(0.4 * 16000):
            return ""

        # Oczyszczenie pasma i normalizacja fragmentu na żywo
        filtered_audio = highpass_filter_audio(audio_float, sr=16000, cutoff_hz=80.0)
        norm_audio = normalize_audio(filtered_audio, target_peak=0.92)

        # Dynamiczny słownik z ustawień aplikacji
        initial_prompt = get_full_initial_prompt(context_prompt)
        effective_beam = beam_size if beam_size is not None else get_beam_size()

        segments, _ = self._model.transcribe(
            norm_audio,
            language=language,
            beam_size=effective_beam,
            temperature=0.0,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.2,
            vad_filter=True,
            vad_parameters=dict(
                threshold=0.35,
                min_speech_duration_ms=200,
                min_silence_duration_ms=400,
                speech_pad_ms=300
            ),
            initial_prompt=initial_prompt
        )

        phrase_text = "".join([segment.text for segment in segments]).strip()
        cleaned_phrase = clean_repeated_text(phrase_text)
        if not cleaned_phrase or is_hallucination(phrase_text, cleaned_phrase):
            return ""

        return cleaned_phrase

    def transcribe_file_with_words(
        self,
        audio_path: str,
        language: str = "pl",
        progress_callback: Optional[Callable[[float, float], None]] = None,
        duration_sec: float = 0.0,
        beam_size: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Transkrybuje cały plik audio i zwraca listę słów z precyzyjnymi timestampami word-level.
        Wczytuje dźwięk bezpośrednio przez soundfile (jako tablicę float32), oczyszcza pasmo (High-Pass 80Hz)
        oraz normalizuje głośność mowy, gwarantując najwyższą dokładność modelu Whisper.
        """
        if self._model is None:
            self.load_model()

        # Bezpieczne wczytanie tablicy float32 przez soundfile z pełnym preprocessingiem mowy
        audio_arr, sr = sf.read(audio_path, dtype='float32')
        audio_arr = preprocess_speech_audio(audio_arr, orig_sr=sr)

        effective_beam = beam_size if beam_size is not None else get_beam_size()
        total_duration = duration_sec if duration_sec > 0 else (len(audio_arr) / 16000.0)
        mins = int(total_duration // 60)
        secs = int(total_duration % 60)
        print(f"[WHISPER] Rozpoczęto pełną transkrypcję pliku (VAD buffer=400ms, beam_size={effective_beam}): {os.path.basename(audio_path)} (Długość: {mins}m {secs}s)...")

        initial_prompt = get_full_initial_prompt()

        # Transkrypcja nagrania z bezpiecznym buforem VAD (odcięcie szumów w ciszy, brak ucinania mowy)
        segments, _ = self._model.transcribe(
            audio_arr,
            word_timestamps=True,
            language=language,
            beam_size=effective_beam,
            temperature=0.0,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            vad_filter=True,
            vad_parameters=dict(
                threshold=0.35,
                min_speech_duration_ms=200,
                min_silence_duration_ms=400,
                speech_pad_ms=400
            ),
            initial_prompt=initial_prompt
        )

        transcript_words = []
        last_logged_pct = -1
        first_speech_logged = False

        for segment in segments:
            raw_text = segment.text.strip() if segment.text else ""
            seg_text = clean_repeated_text(raw_text)
            if not seg_text or is_hallucination(raw_text, seg_text):
                continue

            # Logowanie pierwszej wykrytej mowy
            if not first_speech_logged:
                first_speech_logged = True
                s_mins = int(segment.start // 60)
                s_secs = int(segment.start % 60)
                e_mins = int(segment.end // 60)
                e_secs = int(segment.end % 60)
                safe_snippet = seg_text[:70].encode('ascii', errors='replace').decode('ascii')
                print(f"[WHISPER] Pierwsza wykryta mowa: [{s_mins:02d}:{s_secs:02d} - {e_mins:02d}:{e_secs:02d}] (od {segment.start:.1f}s): \"{safe_snippet}...\"")

            # 1. Sprawdzamy czy Whisper wygenerował dokładne znaczniki słów dla tego segmentu
            has_valid_words = False
            if segment.words:
                valid_words = [
                    w for w in segment.words
                    if w.word and w.start is not None and w.end is not None
                ]
                if valid_words:
                    has_valid_words = True
                    filtered_valid = filter_repeated_words_list(valid_words, max_consecutive=2)
                    for word in filtered_valid:
                        transcript_words.append({
                            "word": word.word if hasattr(word, "word") else word.get("word", ""),
                            "start": word.start if hasattr(word, "start") else word.get("start", 0.0),
                            "end": word.end if hasattr(word, "end") else word.get("end", 0.0)
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

