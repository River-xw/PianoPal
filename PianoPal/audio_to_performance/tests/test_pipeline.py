"""End-to-end sanity check: synthesize a short piano-ish WAV from known
notes (additive-sine synth -- no soundfont/fluidsynth dependency needed),
run it through the real pipeline (including actual basic-pitch inference),
and check the transcribed performance recovers roughly the right note count
and pitches for clearly-separated notes.

Transcription is not pixel-perfect even on clean synthetic audio, so
assertions here are deliberately loose (tolerance on pitch, count) rather
than exact-match -- this is a sanity check that the plumbing works
end-to-end, not a precision benchmark of basic-pitch itself.
"""
from __future__ import annotations

import numpy as np
import pytest

from audio_to_performance.config import AudioToPerformanceConfig
from audio_to_performance.pipeline import transcribe

SR = 44100

# (midi_pitch, onset_sec, dur_sec, velocity) -- a simple, clearly-separated
# C major triad played as a broken chord, one note at a time
TEST_NOTES = [
    (60, 0.0, 0.6, 100),  # C4
    (64, 0.8, 0.6, 100),  # E4
    (67, 1.6, 0.6, 100),  # G4
    (72, 2.4, 0.6, 100),  # C5
]


def _midi_to_freq(pitch: int) -> float:
    return 440.0 * 2 ** ((pitch - 69) / 12)


def _synth_note(freq_hz: float, duration_sec: float, sr: int, velocity: int) -> np.ndarray:
    n = int(duration_sec * sr)
    t = np.arange(n) / sr
    # a few harmonics for a slightly richer, piano-ish timbre than a bare sine
    wave = (
        1.00 * np.sin(2 * np.pi * freq_hz * t)
        + 0.50 * np.sin(2 * np.pi * 2 * freq_hz * t)
        + 0.25 * np.sin(2 * np.pi * 3 * freq_hz * t)
    )
    envelope = np.exp(-3.0 * t)  # fast decay, piano-like
    attack_n = max(1, int(0.005 * sr))
    envelope[:attack_n] *= np.linspace(0, 1, attack_n)
    return (wave * envelope * (velocity / 127.0) * 0.3).astype(np.float32)


def synth_notes(notes: list, sr: int = SR) -> np.ndarray:
    total_dur = max(onset + dur for _, onset, dur, _ in notes) + 1.0
    track = np.zeros(int(total_dur * sr), dtype=np.float32)
    for pitch, onset, dur, velocity in notes:
        note_wave = _synth_note(_midi_to_freq(pitch), dur + 0.3, sr, velocity)
        start = int(onset * sr)
        end = min(len(track), start + len(note_wave))
        track[start:end] += note_wave[: end - start]
    peak = np.max(np.abs(track))
    if peak > 0:
        track = track / peak * 0.9
    return track


@pytest.fixture(scope="module")
def synthesized_audio():
    return synth_notes(TEST_NOTES)


class TestEndToEndTranscription:
    def test_recovers_roughly_the_right_notes(self, synthesized_audio, tmp_path):
        midi_out = tmp_path / "transcribed.mid"
        performance = transcribe(
            audio=synthesized_audio, samplerate=SR,
            config=AudioToPerformanceConfig(),
            save_midi_path=str(midi_out),
        )

        print("\ninput notes:      ", [(p, round(o, 2)) for p, o, _, _ in TEST_NOTES])
        print("transcribed notes:", [(n["pitch"], round(n["onset_sec"], 2)) for n in performance])

        assert midi_out.exists()
        # loose count tolerance -- transcription can merge/split notes at the margins
        assert abs(len(performance) - len(TEST_NOTES)) <= 2

        expected_pitches = {p for p, _, _, _ in TEST_NOTES}
        detected_pitches = {n["pitch"] for n in performance}
        # each expected pitch should have a detected note within +/- 1 semitone
        for expected in expected_pitches:
            assert any(abs(detected - expected) <= 1 for detected in detected_pitches), (
                f"expected pitch {expected} not found in {sorted(detected_pitches)}"
            )

    def test_output_is_time_sorted(self, synthesized_audio):
        performance = transcribe(audio=synthesized_audio, samplerate=SR)
        onsets = [n["onset_sec"] for n in performance]
        assert onsets == sorted(onsets)

    def test_output_matches_performance_json_schema(self, synthesized_audio):
        performance = transcribe(audio=synthesized_audio, samplerate=SR)
        assert len(performance) > 0
        for note in performance:
            assert set(note.keys()) == {"pitch", "onset_sec", "dur_sec", "velocity"}
            assert isinstance(note["pitch"], int)
            assert isinstance(note["onset_sec"], float)
