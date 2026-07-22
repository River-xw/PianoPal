"""audio_to_performance: transcribe a solo-piano recording into a performance.json.

WAV/MP3/M4A -> [optional denoise/bandpass/normalize] -> basic-pitch (a trained
neural transcription model, not generic onset detection) -> MIDI ->
scoring.midi_io.midi_to_performance() -> performance.json.

This is a DL-model pipeline: run it on a laptop/cloud worker, not the
Raspberry Pi (see transcribe.py).
"""
from .config import AudioToPerformanceConfig
from .errors import AudioToPerformanceError, TranscriptionError, UnsupportedAudioError


def __getattr__(name):
    if name == "transcribe":
        from .pipeline import transcribe

        return transcribe
    raise AttributeError(name)

__all__ = [
    "AudioToPerformanceConfig",
    "transcribe",
    "AudioToPerformanceError",
    "UnsupportedAudioError",
    "TranscriptionError",
]
