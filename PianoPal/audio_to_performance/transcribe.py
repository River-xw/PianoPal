"""Wraps Spotify's basic-pitch -- a trained neural network for polyphonic
piano transcription (handles chords properly, unlike generic spectral-flux
onset detection).

IMPORTANT: this runs a deep-learning model. Assume this function executes on
a laptop or a cloud worker, NOT the Raspberry Pi itself -- the Pi side should
only record audio and upload/forward it somewhere this can run. Do not call
`transcribe_to_midi` from Pi-resident code.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict

from .config import AudioToPerformanceConfig
from .errors import TranscriptionError


def transcribe_to_midi(
    audio_path: Optional[str] = None,
    audio: Optional[np.ndarray] = None,
    samplerate: Optional[int] = None,
    config: Optional[AudioToPerformanceConfig] = None,
    save_midi_path: Optional[str] = None,
):
    """Run basic-pitch on either a file path or an in-memory (audio, samplerate)
    pair, returning a pretty_midi.PrettyMIDI. Writes it to `save_midi_path` if given.
    """
    config = config or AudioToPerformanceConfig()
    if audio_path is None and audio is None:
        raise ValueError("must provide either audio_path or (audio, samplerate)")

    cleanup_path: Optional[str] = None
    if audio_path is None:
        if samplerate is None:
            raise ValueError("samplerate is required when passing a raw audio array")
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        sf.write(tmp.name, audio, samplerate)
        audio_path = tmp.name
        cleanup_path = tmp.name

    try:
        _, midi_data, _ = predict(
            audio_path,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            onset_threshold=config.onset_threshold,
            frame_threshold=config.frame_threshold,
            minimum_note_length=config.minimum_note_length_ms,
            minimum_frequency=config.minimum_frequency,
            maximum_frequency=config.maximum_frequency,
            melodia_trick=config.melodia_trick,
        )
    except Exception as exc:
        raise TranscriptionError(f"basic-pitch transcription failed: {exc}") from exc
    finally:
        if cleanup_path:
            Path(cleanup_path).unlink(missing_ok=True)

    if save_midi_path:
        midi_data.write(save_midi_path)

    return midi_data
