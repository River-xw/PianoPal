"""MIDI parsing via pretty_midi.

Produces the same intermediate shape as musicxml_parser.parse_musicxml: a
dict with title / tempo_map / time_signature / key / duration_beats / notes
(notes carry onset_beats & dur_beats only -- seconds are derived later in
core.py). MIDI has no measure concept, so "measure" is left as None here and
filled in by core.py using the time signature.
"""
from __future__ import annotations

import os
from typing import Any

import pretty_midi

from .errors import ScoreParsingError

_DEFAULT_BPM = 120.0


def parse_midi(path: str) -> dict[str, Any]:
    try:
        pm = pretty_midi.PrettyMIDI(path)
    except Exception as exc:
        raise ScoreParsingError(f"Failed to parse MIDI file '{path}': {exc}") from exc

    resolution = pm.resolution  # ticks per quarter note

    def beats_at(time_sec: float) -> float:
        return pm.time_to_tick(time_sec) / resolution

    tempo_times, tempo_values = pm.get_tempo_changes()
    if len(tempo_times) == 0:
        tempo_map: list[dict[str, float]] = [{"beat": 0.0, "bpm": _DEFAULT_BPM}]
    else:
        tempo_map = [
            {"beat": float(beats_at(t_sec)), "bpm": float(bpm)}
            for t_sec, bpm in zip(tempo_times, tempo_values)
        ]

    notes: list[dict[str, Any]] = []
    instruments = [inst for inst in pm.instruments if not inst.is_drum]
    for inst_index, instrument in enumerate(instruments):
        hand = "R" if inst_index == 0 else "L"
        for note in instrument.notes:
            onset_beats = beats_at(note.start)
            end_beats = beats_at(note.end)
            notes.append({
                "pitch": int(note.pitch),
                "name": pretty_midi.note_number_to_name(note.pitch),
                "onset_beats": float(onset_beats),
                "dur_beats": float(end_beats - onset_beats),
                "velocity": int(note.velocity),
                "hand": hand,
                "measure": None,
            })

    if pm.time_signature_changes:
        ts0 = pm.time_signature_changes[0]
        time_signature = f"{ts0.numerator}/{ts0.denominator}"
    else:
        time_signature = "4/4"

    key_name = "C major"
    if pm.key_signature_changes:
        raw_key_name = pretty_midi.key_number_to_key_name(pm.key_signature_changes[0].key_number)
        tonic, _, mode = raw_key_name.partition(" ")
        key_name = f"{tonic} {mode.lower()}" if mode else raw_key_name

    title = os.path.splitext(os.path.basename(path))[0]

    return {
        "title": title,
        "tempo_map": tempo_map,
        "time_signature": time_signature,
        "key": key_name,
        "duration_beats": float(beats_at(pm.get_end_time())),
        "notes": notes,
    }
