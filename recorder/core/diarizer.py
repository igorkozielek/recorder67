import os
import sys
import gc
import types
from typing import List, Dict, Any, Tuple, Optional, Callable


def patch_torch_dynamo():
    """
    Ustawia bezpieczne atrybuty pomocnicze tylko wtedy, gdy moduł TorchDynamo jest już obecny.
    Nie inicjuje importu `torch._dynamo`, żeby nie uruchamiać ciężkiej kaskady importów przy starcie.
    """
    try:
        mod = sys.modules.get("torch._dynamo.utils")
        if mod:
            if not hasattr(mod, "NP_SUPPORTED_MODULES"):
                mod.NP_SUPPORTED_MODULES = ()
            if not hasattr(mod, "NP_TO_TNP_MODULE"):
                mod.NP_TO_TNP_MODULE = {}
    except Exception:
        pass


def apply_torchaudio_patches():
    """
    Kompleksowe łatki dla torchaudio, PyTorch 2.6+ i TorchDynamo omijające błędy brakujących bibliotek C/FFmpeg
    oraz wymuszające kompatybilność weights_only.
    """
    patch_torch_dynamo()
    import torch
    import torchaudio

    if not hasattr(torchaudio, 'list_audio_backends'):
        torchaudio.list_audio_backends = lambda: ["soundfile", "sox"]

    if not hasattr(torchaudio, 'AudioMetaData'):
        class DummyAudioMetaData:
            pass
        torchaudio.AudioMetaData = DummyAudioMetaData

    # Łatka na torchaudio.load (omijanie torchcodec i FFmpeg za pomocą soundfile)
    import soundfile as sf
    def _patched_torchaudio_load(filepath, frame_offset=0, num_frames=-1, **kwargs):
        start = frame_offset if frame_offset > 0 else 0
        stop = (start + num_frames) if num_frames > 0 else None
        wav, sr = sf.read(filepath, start=start, stop=stop, dtype='float32')
        wav_tensor = torch.from_numpy(wav)
        if wav_tensor.dim() == 1:
            wav_tensor = wav_tensor.unsqueeze(0)
        else:
            wav_tensor = wav_tensor.t()
        return wav_tensor, sr

    torchaudio.load = _patched_torchaudio_load

    # Łatka na torchaudio.info (pobieranie metadanych pliku przez soundfile)
    def _patched_torchaudio_info(filepath, **kwargs):
        sf_info = sf.info(filepath)
        class AudioInfo:
            def __init__(self, s_info):
                self.sample_rate = s_info.samplerate
                self.num_frames = s_info.frames
                self.num_channels = s_info.channels
                self.bits_per_sample = 16
                self.encoding = "PCM_S"
        return AudioInfo(sf_info)

    torchaudio.info = _patched_torchaudio_info

    # Łatka na PyTorch 2.6+ (wymuszenie weights_only=False dla bezpiecznych modeli HuggingFace)
    import torch.serialization
    _orig_load = torch.load
    def _patched_load(*args, **kwargs):
        kwargs['weights_only'] = False
        return _orig_load(*args, **kwargs)

    torch.load = _patched_load
    torch.serialization.load = _patched_load


def join_words_clean(words_list: List[Any]) -> str:
    """
    Łączy listę słów w spójne zdanie z zachowaniem prawidłowych spacji i interpunkcji.
    Nigdy nie skleja słów bez spacji (zapobiega 'Mówiliśmyżeosobno').
    """
    if not words_list:
        return ""
    result = []
    for w in words_list:
        w_str = str(w)
        if not w_str:
            continue
        if w_str.startswith(" "):
            result.append(w_str)
        elif w_str in {".", ",", "!", "?", ":", ";", "...", "%"} or (len(w_str) == 1 and not w_str.isalnum()):
            result.append(w_str)
        else:
            if result and not result[-1].endswith(" "):
                result.append(" " + w_str)
            else:
                result.append(w_str)
    return "".join(result).strip()


class DiarizationEngine:
    """
    Silnik diaryzacji mówców bazujący na PyAnnote.audio z optymalizacją batch_size dla długich plików (1-2h).
    """
    def __init__(self, hf_token: str = None):
        self.hf_token = hf_token
        self._pipeline = None

    def load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline

        if self.hf_token:
            os.environ["HF_TOKEN"] = self.hf_token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = self.hf_token

        apply_torchaudio_patches()

        import torch
        from pyannote.audio import Pipeline
        from recorder.config import get_hardware_acceleration_info

        hw_info = get_hardware_acceleration_info()
        if not hw_info.get("is_cuda", False):
            safe_threads = hw_info.get("cpu_threads", 5)
            torch.set_num_threads(safe_threads)
            print(f"👥 [PYANNOTE] Ustawiono {safe_threads} wątków roboczych PyTorch na CPU.")

        print("👥 [PYANNOTE] Ładowanie modelu 'pyannote/speaker-diarization-3.1'...")
        pipeline = None
        try:
            pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=self.hf_token)
        except TypeError:
            try:
                pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=self.hf_token)
            except TypeError:
                pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")

        if pipeline is None:
            raise ValueError("Nie udało się załadować modelu PyAnnote. Sprawdź poprawność tokenu HuggingFace.")

        device_name = "CUDA (GPU)" if torch.cuda.is_available() else "CPU"
        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))

        print(f"✅ [PYANNOTE] Model załadowany pomyślnie na: {device_name}!")
        self._pipeline = pipeline
        return self._pipeline

    def process(
        self,
        audio_path: str,
        transcript_words: List[Dict[str, Any]],
        batch_size: int = 32,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        """
        Główna metoda przetwarzania diaryzacji audio z word-level alignmentem.
        """
        if not transcript_words:
            print("⚠️ [PYANNOTE] Brak słów transkrypcji do dopasowania.")
            return format_transcript_without_diarization([])

        pipeline = self.load_pipeline()
        diarize_kwargs = {}
        if batch_size > 1:
            diarize_kwargs["batch_size"] = batch_size

        if num_speakers is not None and num_speakers > 0:
            diarize_kwargs["num_speakers"] = int(num_speakers)
        else:
            if min_speakers is not None and min_speakers > 0:
                diarize_kwargs["min_speakers"] = int(min_speakers)
            if max_speakers is not None and max_speakers > 0:
                diarize_kwargs["max_speakers"] = int(max_speakers)

        if progress_callback:
            def _pyannote_hook(step_name, step_artifact, file=None, total=None, completed=None):
                try:
                    step_labels = {
                        "segmentation": "Segmentacja i detekcja głosu",
                        "embeddings": "Ekstrakcja cech mówców (Embeddings)",
                        "discrete_diarization": "Klastrowanie i analiza osób",
                        "speaker_counting": "Weryfikacja liczby uczestników"
                    }
                    step_desc = step_labels.get(step_name, str(step_name))
                    if total and completed is not None:
                        pct_step = int((completed / total) * 100)
                        if step_name == "segmentation":
                            overall = int(60 + (completed / total) * 15)
                        elif step_name in ("embeddings", "speaker_counting"):
                            overall = int(75 + (completed / total) * 15)
                        else:
                            overall = int(90 + (completed / total) * 8)
                        progress_callback(min(98, overall), f"Etap 3/3: {step_desc} ({pct_step}% - {completed}/{total})...")
                    else:
                        progress_callback(70, f"Etap 3/3: {step_desc}...")
                except Exception:
                    pass

            diarize_kwargs["hook"] = _pyannote_hook

        print(f"⏳ [PYANNOTE] Rozpoczęto analizę głosów (parametry: {diarize_kwargs}) dla pliku: {os.path.basename(audio_path)}...")

        try:
            diarization = pipeline(audio_path, **diarize_kwargs)
        except Exception as err:
            print(f"⚠️ [PYANNOTE] Błąd wywołania z parametrami ({err}), ponawianie bezpieczne...")
            try:
                fallback_kwargs = {k: v for k, v in diarize_kwargs.items() if k in ("num_speakers", "min_speakers", "max_speakers", "hook")}
                diarization = pipeline(audio_path, **fallback_kwargs)
            except Exception as pipe_err:
                print(f"❌ [PYANNOTE] Błąd diaryzacji: {pipe_err}")
                diarization = None

        if diarization is None:
            return format_transcript_without_diarization(transcript_words)

        diar_segments = []
        speakers_detected = set()
        try:
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                speakers_detected.add(speaker)
                diar_segments.append((turn.start, turn.end, speaker))
        except Exception:
            pass

        if not diar_segments:
            print("⚠️ [PYANNOTE] Nie wykryto segmentów mówców. Powrót do transkrypcji ciągłej.")
            return format_transcript_without_diarization(transcript_words)

        # Dopasowanie słów do mówcy
        word_speaker_tags = []
        prev_speaker = diar_segments[0][2] if diar_segments else "SPEAKER_00"

        for w in transcript_words:
            w_start = float(w.get("start", 0.0))
            w_end = float(w.get("end", w_start + 0.1))
            mid = (w_start + w_end) / 2.0

            best_spk = None
            max_overlap = 0.0

            for seg_start, seg_end, seg_spk in diar_segments:
                overlap = max(0.0, min(w_end, seg_end) - max(w_start, seg_start))
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_spk = seg_spk

            if best_spk is not None and max_overlap >= 0.04:
                assigned_spk = best_spk
            else:
                nearest_spk = None
                nearest_dist = 1.2
                for seg_start, seg_end, seg_spk in diar_segments:
                    dist = min(abs(mid - seg_start), abs(mid - seg_end))
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest_spk = seg_spk
                if nearest_spk:
                    assigned_spk = nearest_spk
                else:
                    assigned_spk = prev_speaker

            prev_speaker = assigned_spk
            word_speaker_tags.append((w.get("word", ""), w_start, w_end, assigned_spk))

        # Grupowanie słów w tury
        turns = []
        if word_speaker_tags:
            cur_spk = word_speaker_tags[0][3]
            cur_start = word_speaker_tags[0][1]
            cur_end = word_speaker_tags[0][2]
            cur_words = []

            for w_text, w_s, w_e, w_spk in word_speaker_tags:
                pause = max(0.0, w_s - cur_end)
                turn_dur = max(0.0, cur_end - cur_start)
                last_word_ends_sentence = any(cur_words) and str(cur_words[-1]).rstrip().endswith((".", "!", "?"))

                speaker_changed = (w_spk != cur_spk)
                pause_split = (pause > 0.8)
                sentence_split = (last_word_ends_sentence and pause > 0.4 and len(cur_words) >= 3)
                duration_split = (turn_dur >= 18.0 and last_word_ends_sentence)

                if cur_words and (speaker_changed or pause_split or sentence_split or duration_split):
                    sentence = join_words_clean(cur_words)
                    if sentence:
                        turns.append({
                            "start": cur_start,
                            "end": cur_end,
                            "speaker": cur_spk,
                            "text": sentence
                        })
                    cur_spk = w_spk
                    cur_start = w_s
                    cur_words = []

                cur_words.append(w_text)
                cur_end = w_e

            if cur_words:
                sentence = join_words_clean(cur_words)
                if sentence:
                    turns.append({
                        "start": cur_start,
                        "end": cur_end,
                        "speaker": cur_spk,
                        "text": sentence
                    })

        final_html = ""
        final_plain = ""
        for t in turns:
            spk = t["speaker"]
            s_txt = t["text"]
            st = t["start"]
            en = t["end"]
            final_html += f"<b>[{st:.1f}s - {en:.1f}s] {spk}:</b> {s_txt}<br><br>"
            final_plain += f"[{st:.1f}s - {en:.1f}s] {spk}: {s_txt}\n\n"

        print(f"✅ [PYANNOTE] Diaryzacja zakończona! Wykryto mówców: {', '.join(sorted(speakers_detected)) if speakers_detected else 'Brak'}")

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()

        if not final_html or not turns:
            return format_transcript_without_diarization(transcript_words)

        return final_html, final_plain, turns


def format_transcript_without_diarization(transcript_words: List[Dict[str, Any]]) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Szybko grupuje słowa w czytelne bloki zdań z timestampami (gdy diaryzacja mówców jest wyłączona).
    Zwraca (final_html, final_plain, turns).
    """
    if not transcript_words:
        return "Brak zarejestrowanej mowy.", "Brak zarejestrowanej mowy.", []

    chunks = []
    current_chunk_words = []
    chunk_start = transcript_words[0]["start"]
    last_end = transcript_words[0]["end"]

    for w in transcript_words:
        w_word = w.get("word", "")
        w_start = w.get("start", last_end)
        w_end = w.get("end", w_start)

        is_long_pause = (w_start - last_end) > 1.2
        is_sentence_end = any(current_chunk_words) and str(current_chunk_words[-1]).rstrip().endswith((".", "!", "?")) and len(current_chunk_words) >= 8

        if current_chunk_words and (is_long_pause or is_sentence_end):
            text = join_words_clean(current_chunk_words)
            if text:
                chunks.append((chunk_start, last_end, text))
            current_chunk_words = []
            chunk_start = w_start

        current_chunk_words.append(w_word)
        last_end = w_end

    if current_chunk_words:
        text = join_words_clean(current_chunk_words)
        if text:
            chunks.append((chunk_start, last_end, text))

    final_html = ""
    final_plain = ""
    turns = []

    for start_t, end_t, text in chunks:
        turns.append({
            "start": start_t,
            "end": end_t,
            "speaker": "Mówca",
            "text": text
        })
        final_html += f"<b>[{start_t:.1f}s - {end_t:.1f}s]:</b> {text}<br><br>"
        final_plain += f"[{start_t:.1f}s - {end_t:.1f}s]: {text}\n\n"

    return final_html, final_plain, turns
