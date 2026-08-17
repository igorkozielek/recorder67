import numpy as np
from typing import List, Dict, Any, Tuple


class TranscriberEngine:
    """
    Silnik transkrypcji mowy oparty na faster-whisper.
    """
    def __init__(self, model_size: str = "small"):
        self.model_size = model_size
        self._model = None

    def load_model(self):
        """
        Ładuje model Whisper do pamięci (CUDA jeśli dostępna, w przeciwnym razie CPU).
        """
        if self._model is not None:
            return self._model

        from faster_whisper import WhisperModel
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "default"

        self._model = WhisperModel(self.model_size, device=device, compute_type=compute_type)
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
            beam_size=5,
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

    def transcribe_file_with_words(self, audio_path: str, language: str = "pl") -> List[Dict[str, Any]]:
        """
        Transkrybuje cały plik audio i zwraca listę słów z precyzyjnymi timestampami word-level.
        """
        if self._model is None:
            self.load_model()

        segments, _ = self._model.transcribe(audio_path, word_timestamps=True, language=language)

        transcript_words = []
        for segment in segments:
            if segment.words:
                for word in segment.words:
                    if word.word and word.start is not None and word.end is not None:
                        transcript_words.append({
                            "word": word.word,
                            "start": word.start,
                            "end": word.end
                        })
        return transcript_words
