"""score_to_reference: convert a music score into one canonical practice reference.

One reference, three consumers: WS2812B LED key-guidance, the falling-note
rhythm game, and rhythm/pitch (DTW) scoring.
"""
from .core import convert, to_seconds
from .db import save_to_db
from .errors import (
    OpticalMusicRecognitionNotSupportedError,
    ScoreParsingError,
    ScoreReferenceError,
    UnsupportedFormatError,
)

__all__ = [
    "convert",
    "to_seconds",
    "save_to_db",
    "ScoreReferenceError",
    "UnsupportedFormatError",
    "OpticalMusicRecognitionNotSupportedError",
    "ScoreParsingError",
]
