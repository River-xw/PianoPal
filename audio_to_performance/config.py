"""Tunable settings for the audio_to_performance pipeline, in one place."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

PIANO_LOW_HZ = 27.5    # A0, lowest note on a standard piano
PIANO_HIGH_HZ = 4186.0  # C8, highest note on a standard piano


@dataclass
class AudioToPerformanceConfig:
    # --- pre-processing (all OFF by default) ---
    # basic-pitch's model was trained on relatively raw audio; denoising,
    # band-pass filtering, and loudness normalization can all suppress or
    # distort the transient attack information the model relies on to place
    # onsets accurately. Turn these on deliberately and A/B test -- don't
    # assume "more cleanup" means "better transcription."
    denoise: bool = False
    bandpass: bool = False
    normalize: bool = False

    bandpass_low_hz: float = PIANO_LOW_HZ
    bandpass_high_hz: float = PIANO_HIGH_HZ
    noisereduce_prop_decrease: float = 1.0
    normalize_target_peak: float = 0.95

    # --- basic-pitch transcription params ---
    onset_threshold: float = 0.5
    frame_threshold: float = 0.3
    minimum_note_length_ms: float = 58.0
    minimum_frequency: Optional[float] = None
    maximum_frequency: Optional[float] = None
    melodia_trick: bool = True

    # --- post-processing (OFF by default) ---
    # basic-pitch's own overtones/sustain-pedal resonance sometimes get
    # transcribed as spurious extra notes at a harmonic interval from a real
    # one. See postprocess.py's docstring for the evidence behind this
    # heuristic and why a flat velocity cutoff was rejected in favor of it.
    suppress_harmonics: bool = False
    harmonic_window_sec: float = 0.35
    harmonic_velocity_ratio: float = 0.75

    # a held note's decay can get misread as a second re-attack of the same
    # pitch partway through its own sustain -- a different failure mode from
    # harmonic bleed (same pitch, not a harmonic interval), so it needs its
    # own suppression pass. See postprocess.suppress_note_splits.
    suppress_split_notes: bool = False
    note_split_velocity_ratio: float = 0.7
