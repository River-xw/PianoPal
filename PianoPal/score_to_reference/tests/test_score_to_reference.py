"""Tests for score_to_reference. Generates tiny MusicXML/MIDI fixtures via music21."""
from __future__ import annotations

import json

import pytest
from music21 import clef, key, meter, metadata, note, stream, tempo

from score_to_reference import (
    OpticalMusicRecognitionNotSupportedError,
    UnsupportedFormatError,
    convert,
    to_seconds,
)


def _build_sample_score() -> stream.Score:
    """RH (treble): C4 D4 E4 F4 (quarters, m1) then G4 (whole, m2).
    LH (bass): C3 (whole, m1) then C3 (whole, m2).
    120 BPM, 4/4, C major.
    """
    score = stream.Score()
    score.metadata = metadata.Metadata(title="Test Sample")

    rh = stream.Part(id="RH")
    rh.insert(0, clef.TrebleClef())
    rh.insert(0, meter.TimeSignature("4/4"))
    rh.insert(0, key.Key("C"))
    rh.insert(0, tempo.MetronomeMark(number=120))
    for i, pitch_name in enumerate(["C4", "D4", "E4", "F4"]):
        n = note.Note(pitch_name, quarterLength=1.0)
        n.volume.velocity = 90
        rh.insert(float(i), n)
    g4 = note.Note("G4", quarterLength=4.0)
    g4.volume.velocity = 90
    rh.insert(4.0, g4)

    lh = stream.Part(id="LH")
    lh.insert(0, clef.BassClef())
    lh.insert(0, meter.TimeSignature("4/4"))
    c3_m1 = note.Note("C3", quarterLength=4.0)
    c3_m1.volume.velocity = 70
    lh.insert(0.0, c3_m1)
    c3_m2 = note.Note("C3", quarterLength=4.0)
    c3_m2.volume.velocity = 70
    lh.insert(4.0, c3_m2)

    score.insert(0, rh)
    score.insert(0, lh)
    return score


@pytest.fixture()
def sample_musicxml_path(tmp_path):
    score = _build_sample_score()
    path = tmp_path / "sample.musicxml"
    score.write("musicxml", fp=str(path))
    return str(path)


@pytest.fixture()
def sample_midi_path(tmp_path):
    score = _build_sample_score()
    path = tmp_path / "sample.mid"
    score.write("midi", fp=str(path))
    return str(path)


class TestMusicXMLConvert:
    def test_pitch_and_onset_extraction(self, sample_musicxml_path):
        ref = convert(sample_musicxml_path)
        pairs = {(n["name"], n["onset_beats"]) for n in ref["notes"]}
        assert ("C4", 0.0) in pairs
        assert ("D4", 1.0) in pairs
        assert ("E4", 2.0) in pairs
        assert ("F4", 3.0) in pairs
        assert ("G4", 4.0) in pairs
        assert ("C3", 0.0) in pairs
        assert ("C3", 4.0) in pairs

    def test_tempo_time_signature_key(self, sample_musicxml_path):
        ref = convert(sample_musicxml_path)
        assert ref["tempo_bpm"] == 120
        assert ref["time_signature"] == "4/4"
        assert ref["key"] == "C major"

    def test_beats_to_seconds_at_score_tempo(self, sample_musicxml_path):
        ref = convert(sample_musicxml_path)
        c4 = next(n for n in ref["notes"] if n["name"] == "C4")
        d4 = next(n for n in ref["notes"] if n["name"] == "D4")
        assert c4["onset_sec"] == pytest.approx(0.0)
        assert d4["onset_sec"] == pytest.approx(0.5)  # 1 beat @ 120bpm = 0.5s
        assert c4["dur_sec"] == pytest.approx(0.5)

    def test_tempo_rescale_halves_onset_sec_when_bpm_doubles(self, sample_musicxml_path):
        ref = convert(sample_musicxml_path)
        rescaled = to_seconds(ref, bpm=240)
        d4_before = next(n for n in ref["notes"] if n["name"] == "D4")
        d4_after = next(n for n in rescaled["notes"] if n["name"] == "D4")
        assert d4_after["onset_sec"] == pytest.approx(d4_before["onset_sec"] / 2)
        assert rescaled["duration_sec"] == pytest.approx(ref["duration_sec"] / 2)
        assert rescaled["tempo_bpm"] == 240
        # original reference must be untouched (to_seconds returns a copy)
        assert ref["tempo_bpm"] == 120

    def test_hand_tagging_from_clef(self, sample_musicxml_path):
        ref = convert(sample_musicxml_path)
        c4 = next(n for n in ref["notes"] if n["name"] == "C4")
        c3 = next(n for n in ref["notes"] if n["name"] == "C3" and n["onset_beats"] == 0.0)
        assert c4["hand"] == "R"
        assert c3["hand"] == "L"

    def test_measure_numbers(self, sample_musicxml_path):
        ref = convert(sample_musicxml_path)
        c4 = next(n for n in ref["notes"] if n["name"] == "C4")
        g4 = next(n for n in ref["notes"] if n["name"] == "G4")
        assert c4["measure"] == 1
        assert g4["measure"] == 2

    def test_deterministic_sort_order(self, sample_musicxml_path):
        ref = convert(sample_musicxml_path)
        pairs = [(n["onset_beats"], n["pitch"]) for n in ref["notes"]]
        assert pairs == sorted(pairs)

    def test_output_is_json_serializable(self, sample_musicxml_path):
        ref = convert(sample_musicxml_path)
        json.dumps(ref)  # must not raise


class TestMidiConvert:
    def test_pitch_and_onset_extraction(self, sample_midi_path):
        ref = convert(sample_midi_path)
        names = {n["name"] for n in ref["notes"]}
        assert {"C4", "D4", "E4", "F4", "G4", "C3"}.issubset(names)

    def test_tempo_rescale_halves_onset_sec_when_bpm_doubles(self, sample_midi_path):
        ref = convert(sample_midi_path)
        rescaled = to_seconds(ref, bpm=ref["tempo_bpm"] * 2)
        before = sorted(ref["notes"], key=lambda n: (n["onset_beats"], n["pitch"]))
        after = sorted(rescaled["notes"], key=lambda n: (n["onset_beats"], n["pitch"]))
        for b, a in zip(before, after):
            assert a["onset_sec"] == pytest.approx(b["onset_sec"] / 2, abs=1e-6)

    def test_deterministic_sort_order(self, sample_midi_path):
        ref = convert(sample_midi_path)
        pairs = [(n["onset_beats"], n["pitch"]) for n in ref["notes"]]
        assert pairs == sorted(pairs)


class TestErrors:
    def test_pdf_raises_omr_not_supported(self, tmp_path):
        pdf_path = tmp_path / "score.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        with pytest.raises(OpticalMusicRecognitionNotSupportedError):
            convert(str(pdf_path))

    def test_unknown_extension_raises_unsupported_format(self, tmp_path):
        txt_path = tmp_path / "score.txt"
        txt_path.write_text("not a score")
        with pytest.raises(UnsupportedFormatError):
            convert(str(txt_path))
