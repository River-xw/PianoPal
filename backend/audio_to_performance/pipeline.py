"""Glue: audio (wav/mp3/m4a path, or a raw array) -> [optional pre-processing]
-> basic-pitch transcription -> MIDI -> scoring.midi_io.midi_to_performance()
-> performance.json.

Reuses the *exact same* MIDI-to-performance conversion the real MIDI-keyboard
input path uses (scoring/midi_io.py), so a transcribed recording and a real
MIDI keyboard recording produce byte-identical output shapes -- there is
exactly one place that defines what a performance.json note looks like.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import librosa
import numpy as np

from backend.scoring.midi_io import midi_to_performance

from .config import AudioToPerformanceConfig
from .errors import UnsupportedAudioError
from .postprocess import filter_impossible_pitches, suppress_harmonic_artifacts, suppress_note_splits
from .preprocess import preprocess
from .transcribe import transcribe_to_midi

TARGET_SR = 44100
SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}


def load_audio(path: str) -> tuple[np.ndarray, int]:
    """Decode any supported audio file and resample to TARGET_SR mono."""
    ext = Path(path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedAudioError(
            f"Unsupported audio extension '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}."
        )
    try:
        audio, sr = librosa.load(path, sr=TARGET_SR, mono=True)
    except Exception as exc:
        raise UnsupportedAudioError(f"Failed to read audio file '{path}': {exc}") from exc
    return audio.astype(np.float32), sr


def transcribe(
    wav_path: Optional[str] = None,
    audio: Optional[np.ndarray] = None,
    samplerate: Optional[int] = None,
    config: Optional[AudioToPerformanceConfig] = None,
    save_midi_path: Optional[str] = None,
) -> list:
    """Convert a solo-piano recording into a performance.json-shaped list.

    Provide either `wav_path` (a file on disk) or `audio`+`samplerate` (an
    in-memory array, e.g. straight off a live-recording buffer).
    """
    config = config or AudioToPerformanceConfig()

    if wav_path is not None:
        audio_data, sr = load_audio(wav_path)
    elif audio is not None and samplerate is not None:
        audio_data = np.asarray(audio, dtype=np.float32)
        sr = samplerate
        if sr != TARGET_SR:
            audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=TARGET_SR)
            sr = TARGET_SR
    else:
        raise ValueError("must provide wav_path, or both audio and samplerate")

    processed = preprocess(audio_data, sr, config)

    midi_path = save_midi_path
    cleanup_midi = False
    if midi_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".mid", delete=False)
        tmp.close()
        midi_path = tmp.name
        cleanup_midi = True

    try:
        transcribe_to_midi(audio=processed, samplerate=sr, config=config, save_midi_path=midi_path)
        performance = midi_to_performance(midi_path)
    finally:
        if cleanup_midi:
            Path(midi_path).unlink(missing_ok=True)

    # hard physical constraint first (not a heuristic): the 37-key keyboard
    # can't produce notes outside its range, so out-of-range transcriptions
    # are artifacts by definition. See config.keyboard_range for when to
    # disable this (audio not sourced from the physical keyboard).
    if config.keyboard_range is not None:
        performance = filter_impossible_pitches(performance, config.keyboard_range)

    if config.suppress_harmonics:
        performance = suppress_harmonic_artifacts(
            performance, config.harmonic_window_sec, config.harmonic_velocity_ratio
        )
    if config.suppress_split_notes:
        performance = suppress_note_splits(performance, config.note_split_velocity_ratio)

    return performance
