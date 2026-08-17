import numpy as np
from typing import List, Dict, Any, Tuple
from recorder.config import get_hardware_acceleration_info, DEFAULT_WHISPER_MODEL


class TranscriberEngine:
    """
    Silnik transkrypcji mowy oparty na faster-whisper ze wsparciem dla akceleracji CPU (int8) oraz CUDA (float16).
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

        from faster_whisper import WhisperModel

        init_kwargs = {
            "model_size_or_path": self.model_size,
            "device": self.device,
            "compute_type": self.compute_type
        }
        if self.device == "cpu" and self.cpu_threads:
            init_kwargs["cpu_threads"] = self.cpu_threads

        self._model = WhisperModel(**init_kwargs)
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
