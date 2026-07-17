"""Typed errors for the audio_to_performance module."""


class AudioToPerformanceError(Exception):
    """Base class for all audio_to_performance errors."""


class UnsupportedAudioError(AudioToPerformanceError):
    """Raised when the input file can't be read as audio, or has an unsupported extension."""


class TranscriptionError(AudioToPerformanceError):
    """Raised when basic-pitch transcription itself fails."""
