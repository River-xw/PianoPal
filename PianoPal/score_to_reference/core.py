"""Core convert()/to_seconds() logic: builds the canonical score reference dict.

Design: beats are the source of truth. onset_beats/dur_beats come straight
from the parsers (tempo-independent); onset_sec/dur_sec/duration_sec are
always *derived* by integrating through a tempo map, never stored as an
independent fact. That is what makes to_seconds() able to safely rescale the
whole reference to any practice BPM.
"""
from __future__ import annotations

import copy
import os
from typing import Any

from .errors import OpticalMusicRecognitionNotSupportedError, UnsupportedFormatError
from .midi_parser import parse_midi
from .musicxml_parser import parse_musicxml

_MUSICXML_EXTENSIONS = {".musicxml", ".xml", ".mxl"}
_MIDI_EXTENSIONS = {".mid", ".midi"}
_PDF_EXTENSIONS = {".pdf"}


def _beats_per_measure(time_signature: str) -> float:
    numerator_str, denominator_str = time_signature.split("/")
    numerator, denominator = float(numerator_str), float(denominator_str)
    return numerator * 4.0 / denominator


def _beats_to_seconds(beat: float, tempo_map: list[dict[str, float]]) -> float:
    """Integrate elapsed seconds through a piecewise-constant tempo map."""
    seconds = 0.0
    prev_beat = 0.0
    prev_bpm = tempo_map[0]["bpm"]
    for entry in tempo_map[1:]:
        if entry["beat"] >= beat:
            break
        seconds += (entry["beat"] - prev_beat) * 60.0 / prev_bpm
        prev_beat = entry["beat"]
        prev_bpm = entry["bpm"]
    seconds += (beat - prev_beat) * 60.0 / prev_bpm
    return seconds


def convert(path: str) -> dict[str, Any]:
    """Convert a MIDI or MusicXML score file into a canonical JSON-able reference dict."""
    ext = os.path.splitext(path)[1].lower()

    if ext in _PDF_EXTENSIONS:
        raise OpticalMusicRecognitionNotSupportedError(
            "PDF input is not supported (no optical music recognition). "
            "Export a .musicxml or .mid file from MuseScore first, then convert that."
        )
    if ext in _MUSICXML_EXTENSIONS:
        parsed = parse_musicxml(path)
    elif ext in _MIDI_EXTENSIONS:
        parsed = parse_midi(path)
    else:
        supported = sorted(_MUSICXML_EXTENSIONS | _MIDI_EXTENSIONS)
        raise UnsupportedFormatError(
            f"Unsupported file extension '{ext}'. Supported extensions: {supported}."
        )

    tempo_map = parsed["tempo_map"]
    time_signature = parsed["time_signature"]
    beats_per_measure = _beats_per_measure(time_signature)
    tempo_bpm = int(round(tempo_map[0]["bpm"]))

    notes: list[dict[str, Any]] = []
    for raw_note in parsed["notes"]:
        onset_beats = raw_note["onset_beats"]
        dur_beats = raw_note["dur_beats"]
        measure = raw_note["measure"]
        if measure is None:
            measure = int(onset_beats // beats_per_measure) + 1
        onset_sec = _beats_to_seconds(onset_beats, tempo_map)
        end_sec = _beats_to_seconds(onset_beats + dur_beats, tempo_map)
        notes.append({
            "pitch": raw_note["pitch"],
            "name": raw_note["name"],
            "onset_beats": onset_beats,
            "onset_sec": onset_sec,
            "dur_beats": dur_beats,
            "dur_sec": end_sec - onset_sec,
            "velocity": raw_note["velocity"],
            "hand": raw_note["hand"],
            "measure": measure,
        })

    notes.sort(key=lambda n: (n["onset_beats"], n["pitch"]))

    duration_beats = parsed["duration_beats"]
    duration_sec = _beats_to_seconds(duration_beats, tempo_map)

    return {
        "title": parsed["title"],
        "tempo_bpm": tempo_bpm,
        "tempo_map": tempo_map,
        "time_signature": time_signature,
        "key": parsed["key"],
        "duration_beats": duration_beats,
        "duration_sec": duration_sec,
        "notes": notes,
    }


def to_seconds(reference: dict[str, Any], bpm: int) -> dict[str, Any]:
    """Return a copy of `reference` with every *_sec field rescaled to a constant target BPM.

    Practice tempo is a fixed metronome click, so seconds are a direct linear
    function of beats: sec = beats * 60 / bpm. This intentionally ignores any
    original tempo_map variability -- once the user practices to a constant
    click, the score's original tempo changes no longer apply.
    """
    if bpm <= 0:
        raise ValueError(f"bpm must be positive, got {bpm}")

    rescaled = copy.deepcopy(reference)
    factor = 60.0 / bpm

    for note in rescaled["notes"]:
        note["onset_sec"] = note["onset_beats"] * factor
        note["dur_sec"] = note["dur_beats"] * factor

    rescaled["duration_sec"] = rescaled["duration_beats"] * factor
    rescaled["tempo_bpm"] = bpm

    return rescaled
