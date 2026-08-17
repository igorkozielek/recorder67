import os
import sys
import gc
from typing import List, Dict, Any, Tuple


def apply_torchaudio_patches():
    """
    Kompleksowe łatki dla torchaudio i PyTorch 2.6+ omijające błędy brakujących bibliotek C/FFmpeg
    oraz wymuszające kompatybilność weights_only.
    """
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

    def process(self, audio_path: str, transcript_words: List[Dict[str, Any]], batch_size: int = 32) -> Tuple[str, str]:
        """
        Wykonuje analizę mówców i łączy wypowiedzi z transkrypcją słów.
        Optymalizacja: wykorzystanie batch_size=32 dla efektywnego przetwarzania długich plików (1-2h).
        Zwraca (final_html, final_plain).
        """
        pipeline = self.load_pipeline()

        print(f"⏳ [PYANNOTE] Rozpoczęto analizę głosów (batch_size={batch_size}) dla pliku: {os.path.basename(audio_path)}...")
        try:
            diarization = pipeline(audio_path, batch_size=batch_size)
        except TypeError:
            diarization = pipeline(audio_path)

        final_html = ""
        final_plain = ""
        speakers_detected = set()

        for turn, _, speaker in diarization.itertracks(yield_label=True):
            speakers_detected.add(speaker)
            # Dopasowanie słów po punkcie środkowym (odporniejsze na przesunięcia czasowe)
            words_in_turn = []
            for w in transcript_words:
                mid_point = (w["start"] + w["end"]) / 2.0
                if turn.start <= mid_point <= turn.end:
                    words_in_turn.append(w["word"])

            if words_in_turn:
                sentence = "".join(words_in_turn).strip()
                final_html += f"<b>[{turn.start:.1f}s - {turn.end:.1f}s] {speaker}:</b> {sentence}<br><br>"
                final_plain += f"[{turn.start:.1f}s - {turn.end:.1f}s] {speaker}: {sentence}\n\n"

        print(f"✅ [PYANNOTE] Diaryzacja zakończona! Wykryto mówców: {', '.join(sorted(speakers_detected)) if speakers_detected else 'Brak'}")

        # Zwolnienie pamięci podręcznej PyTorch i Garbage Collector
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()

        if not final_html:
            fallback_msg = "Transkrypcja zakończona, ale nie udało się zmapować głosów do słów."
            return fallback_msg, fallback_msg

        return final_html, final_plain
