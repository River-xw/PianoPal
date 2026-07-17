"""Optional pre-processing for raw solo-piano mic recordings.

Everything here is OFF by default (see config.py) -- basic-pitch's model was
trained on relatively clean, raw audio, and none of these steps are known to
improve its transcription accuracy. They exist so you can A/B test them
against a real recording, not because we expect them to help by default.
Over-aggressive denoising in particular can smear or hollow out the sharp
transient attack that the model uses to place note onsets.
"""
from __future__ import annotations

import noisereduce as nr
import numpy as np
from scipy.signal import butter, sosfiltfilt

from .config import PIANO_HIGH_HZ, PIANO_LOW_HZ, AudioToPerformanceConfig


def denoise(audio: np.ndarray, sr: int, prop_decrease: float = 1.0) -> np.ndarray:
    """Spectral-gating noise reduction (steady background hiss/hum)."""
    return nr.reduce_noise(y=audio, sr=sr, prop_decrease=prop_decrease).astype(np.float32)


def bandpass_filter(
    audio: np.ndarray, sr: int,
    low_hz: float = PIANO_LOW_HZ, high_hz: float = PIANO_HIGH_HZ, order: int = 4,
) -> np.ndarray:
    """Zero-phase Butterworth band-pass restricted to the piano's own range."""
    nyquist = sr / 2.0
    high_hz = min(high_hz, nyquist - 1.0)
    sos = butter(order, [low_hz / nyquist, high_hz / nyquist], btype="band", output="sos")
    return sosfiltfilt(sos, audio).astype(np.float32)


def normalize_loudness(audio: np.ndarray, target_peak: float = 0.95) -> np.ndarray:
    """Simple peak normalization (not full loudness/LUFS normalization)."""
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-9:
        return audio
    return (audio * (target_peak / peak)).astype(np.float32)


def preprocess(audio: np.ndarray, sr: int, config: AudioToPerformanceConfig) -> np.ndarray:
    """Apply whichever steps are enabled in `config`, in a fixed, deterministic order."""
    out = np.asarray(audio, dtype=np.float32)
    if config.denoise:
        out = denoise(out, sr, config.noisereduce_prop_decrease)
    if config.bandpass:
        out = bandpass_filter(out, sr, config.bandpass_low_hz, config.bandpass_high_hz)
    if config.normalize:
        out = normalize_loudness(out, config.normalize_target_peak)
    return out
