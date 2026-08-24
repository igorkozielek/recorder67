"""
Moduł Core AI - Czyste przetwarzanie modeli VAD, Faster-Whisper oraz PyAnnote bez zależności od GUI.
"""

from .vad import SileroVADDetector, is_silero_available
from .transcriber import TranscriberEngine

__all__ = [
    "SileroVADDetector",
    "is_silero_available",
    "TranscriberEngine",
    "DiarizationEngine",
]


def __getattr__(name):
    if name == "DiarizationEngine":
        from .diarizer import DiarizationEngine
        return DiarizationEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
