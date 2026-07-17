"""Tests for synth.py -- primarily the "refuse to silently fall back to a
sine wave" guarantee, since that's the whole point of this tool's design.
"""
from __future__ import annotations

import pytest

from validation.errors import SynthesisError
from validation.synth import synthesize_midi_to_wav


class TestRefuseSineFallback:
    def test_no_soundfont_raises_not_silently_proceeds(self, tmp_path):
        midi_path = tmp_path / "fake.mid"
        midi_path.write_bytes(b"MThd")  # content doesn't matter, should fail before reading it
        with pytest.raises(SynthesisError, match="sine-wave"):
            synthesize_midi_to_wav(str(midi_path), None, str(tmp_path / "out.wav"))

    def test_empty_string_soundfont_raises(self, tmp_path):
        midi_path = tmp_path / "fake.mid"
        midi_path.write_bytes(b"MThd")
        with pytest.raises(SynthesisError, match="sine-wave"):
            synthesize_midi_to_wav(str(midi_path), "", str(tmp_path / "out.wav"))

    def test_nonexistent_soundfont_path_raises(self, tmp_path):
        midi_path = tmp_path / "fake.mid"
        midi_path.write_bytes(b"MThd")
        with pytest.raises(SynthesisError, match="not found"):
            synthesize_midi_to_wav(str(midi_path), str(tmp_path / "no_such.sf2"), str(tmp_path / "out.wav"))

    def test_nonexistent_midi_path_raises(self, tmp_path):
        soundfont = tmp_path / "fake.sf2"
        soundfont.write_bytes(b"not a real soundfont")
        with pytest.raises(SynthesisError, match="MIDI file not found"):
            synthesize_midi_to_wav(str(tmp_path / "no_such.mid"), str(soundfont), str(tmp_path / "out.wav"))
