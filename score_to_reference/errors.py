"""Typed errors for the score_to_reference module."""


class ScoreReferenceError(Exception):
    """Base class for all score_to_reference errors."""


class UnsupportedFormatError(ScoreReferenceError):
    """Raised when the input file extension is not one of the supported formats."""


class OpticalMusicRecognitionNotSupportedError(ScoreReferenceError):
    """Raised when a PDF is passed in. OMR is explicitly out of scope."""


class ScoreParsingError(ScoreReferenceError):
    """Raised when a supported file fails to parse into a note list."""
