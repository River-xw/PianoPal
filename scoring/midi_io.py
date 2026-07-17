"""Load a MIDI recording as a flat performance note list.

No sensor/onset-detection code here by design: this assumes an ideal capture
path where a MIDI keyboard already gives clean, precise note events.
"""
from __future__ import annotations

import pretty_midi


def midi_to_performance(path: str) -> list:
    """Return a time-sorted list of {pitch, onset_sec, dur_sec, velocity}."""
    pm = pretty_midi.PrettyMIDI(path)
    notes = []
    for instrument in pm.instruments:
        if instrument.is_drum:
            continue
        for note in instrument.notes:
            notes.append({
                "pitch": int(note.pitch),
                "onset_sec": float(note.start),
                "dur_sec": float(note.end - note.start),
                "velocity": int(note.velocity),
            })
    notes.sort(key=lambda n: (n["onset_sec"], n["pitch"]))
    return notes
