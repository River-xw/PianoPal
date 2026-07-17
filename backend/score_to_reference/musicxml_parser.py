"""MusicXML parsing via music21.

Produces the same intermediate shape as midi_parser.parse_midi: a dict with
title / tempo_map / time_signature / key / duration_beats / notes (notes carry
onset_beats & dur_beats only -- seconds are derived later in core.py).
"""
from __future__ import annotations

import os
from typing import Any

from music21 import chord as m21chord
from music21 import clef as m21clef
from music21 import converter
from music21 import key as m21key
from music21 import meter as m21meter
from music21 import tempo as m21tempo

from .errors import ScoreParsingError

_DEFAULT_VELOCITY = 64
_DEFAULT_BPM = 120.0


def _hand_for_part(part_index: int, part: Any) -> str:
    """Best-effort R/L hand tagging: prefer clef, fall back to part order."""
    clefs = part.recurse().getElementsByClass(m21clef.Clef)
    first_clef = clefs.first() if len(clefs) else None
    if isinstance(first_clef, m21clef.BassClef):
        return "L"
    if isinstance(first_clef, m21clef.TrebleClef):
        return "R"
    return "R" if part_index == 0 else "L"


def _extract_key_name(score: Any) -> str:
    key_elements = score.flatten().getElementsByClass(m21key.Key)
    key_obj = key_elements.first() if len(key_elements) else None

    if key_obj is None:
        ks_elements = score.flatten().getElementsByClass(m21key.KeySignature)
        if len(ks_elements):
            key_obj = ks_elements.first().asKey("major")

    if key_obj is None:
        try:
            key_obj = score.analyze("key")
        except Exception:
            key_obj = None

    if key_obj is None:
        return "C major"
    return f"{key_obj.tonic.name} {key_obj.mode}"


def _extract_tempo_map(score: Any) -> list[dict[str, float]]:
    tempo_map: list[dict[str, float]] = []
    for mm in score.flatten().getElementsByClass(m21tempo.MetronomeMark):
        bpm = mm.getQuarterBPM()
        if bpm:
            tempo_map.append({"beat": float(mm.offset), "bpm": float(bpm)})
    if not tempo_map:
        tempo_map = [{"beat": 0.0, "bpm": _DEFAULT_BPM}]
    tempo_map.sort(key=lambda entry: entry["beat"])
    return tempo_map


def parse_musicxml(path: str) -> dict[str, Any]:
    try:
        score = converter.parse(path)
    except Exception as exc:  # music21 raises many internal exception types
        raise ScoreParsingError(f"Failed to parse MusicXML file '{path}': {exc}") from exc

    parts = list(score.parts) if len(score.parts) else [score]

    notes: list[dict[str, Any]] = []
    for part_index, part in enumerate(parts):
        hand = _hand_for_part(part_index, part)
        for element in part.flatten().notes:
            pitches = element.pitches if isinstance(element, m21chord.Chord) else [element.pitch]
            velocity = element.volume.velocity
            for pitch in pitches:
                notes.append({
                    "pitch": int(pitch.midi),
                    "name": pitch.nameWithOctave,
                    "onset_beats": float(element.offset),
                    "dur_beats": float(element.duration.quarterLength),
                    "velocity": int(velocity) if velocity is not None else _DEFAULT_VELOCITY,
                    "hand": hand,
                    "measure": element.measureNumber if element.measureNumber is not None else 1,
                })

    ts_elements = score.flatten().getElementsByClass(m21meter.TimeSignature)
    time_signature = ts_elements.first().ratioString if len(ts_elements) else "4/4"

    title = None
    if score.metadata is not None:
        title = score.metadata.title
    if not title:
        title = os.path.splitext(os.path.basename(path))[0]

    return {
        "title": title,
        "tempo_map": _extract_tempo_map(score),
        "time_signature": time_signature,
        "key": _extract_key_name(score),
        "duration_beats": float(score.highestTime),
        "notes": notes,
    }
