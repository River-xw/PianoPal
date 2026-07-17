"""Unit tests for preprocess.py using synthetic sine waves (no audio files needed)."""
from __future__ import annotations

import numpy as np
import pytest

from backend.audio_to_performance.preprocess import bandpass_filter, denoise, normalize_loudness

SR = 44100


def _sine(freq_hz: float, duration_sec: float, sr: int = SR, amplitude: float = 1.0) -> np.ndarray:
    t = np.arange(int(duration_sec * sr)) / sr
    return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def _band_energy(signal: np.ndarray, freq_hz: float, sr: int = SR, tolerance_hz: float = 5.0) -> float:
    spectrum = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(len(signal), 1.0 / sr)
    band = (freqs > freq_hz - tolerance_hz) & (freqs < freq_hz + tolerance_hz)
    return float(spectrum[band].sum())


class TestBandpassFilter:
    def test_removes_rumble_keeps_piano_range_tone(self):
        # 5Hz rumble (well below piano's lowest note, 27.5Hz -- a 4th-order
        # Butterworth's rolloff is gradual, not a brick wall, so the test
        # frequency needs real distance from the cutoff) + a clean 440Hz tone
        signal = _sine(5, 1.0, amplitude=1.0) + _sine(440, 1.0, amplitude=1.0)
        filtered = bandpass_filter(signal, SR)

        rumble_before = _band_energy(signal, 5)
        rumble_after = _band_energy(filtered, 5)
        tone_before = _band_energy(signal, 440)
        tone_after = _band_energy(filtered, 440)

        assert rumble_after < rumble_before * 0.05  # rumble almost entirely removed
        assert tone_after > tone_before * 0.9        # tone essentially preserved

    def test_removes_ultrasonic_keeps_piano_range_tone(self):
        # 10kHz (above piano's highest note, 4186Hz) + a clean 1000Hz tone
        signal = _sine(10000, 1.0, amplitude=1.0) + _sine(1000, 1.0, amplitude=1.0)
        filtered = bandpass_filter(signal, SR)

        high_before = _band_energy(signal, 10000)
        high_after = _band_energy(filtered, 10000)
        tone_before = _band_energy(signal, 1000)
        tone_after = _band_energy(filtered, 1000)

        assert high_after < high_before * 0.05
        assert tone_after > tone_before * 0.9

    def test_deterministic(self):
        signal = _sine(440, 0.5) + _sine(20, 0.5)
        a = bandpass_filter(signal, SR)
        b = bandpass_filter(signal, SR)
        np.testing.assert_array_equal(a, b)


class TestNormalizeLoudness:
    def test_scales_peak_to_target(self):
        signal = _sine(440, 0.5, amplitude=0.1)
        normalized = normalize_loudness(signal, target_peak=0.95)
        assert np.max(np.abs(normalized)) == pytest.approx(0.95, abs=1e-4)

    def test_silence_is_left_alone(self):
        silence = np.zeros(1000, dtype=np.float32)
        assert np.max(np.abs(normalize_loudness(silence))) == 0.0

    def test_deterministic(self):
        signal = _sine(440, 0.5, amplitude=0.3)
        a = normalize_loudness(signal)
        b = normalize_loudness(signal)
        np.testing.assert_array_equal(a, b)


class TestDenoise:
    def test_reduces_added_white_noise(self):
        rng = np.random.default_rng(0)
        tone = _sine(440, 1.0, amplitude=0.8)
        noisy = tone + rng.normal(0, 0.05, size=tone.shape).astype(np.float32)

        cleaned = denoise(noisy, SR)

        # the tone itself should still dominate the spectrum after denoising
        tone_energy = _band_energy(cleaned, 440)
        assert tone_energy > 0

    def test_deterministic(self):
        tone = _sine(440, 0.5, amplitude=0.5)
        a = denoise(tone, SR)
        b = denoise(tone, SR)
        np.testing.assert_array_equal(a, b)
