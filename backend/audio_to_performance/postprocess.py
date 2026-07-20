"""Post-processing on the TRANSCRIBED note list (after basic-pitch, after
scoring.midi_io.midi_to_performance -- this operates on performance.json-
shaped dicts, not audio).

NOTE (harmonic extras): the PREFERRED fix for overtone "extra" notes now
lives in backend.scoring (config.suppress_harmonic_extras, on by default) --
it runs AFTER alignment, so it only touches notes already classified `extra`
and can't delete a real note. The velocity-based `suppress_harmonic_artifacts`
below is reference-FREE (it can't tell a genuine arrangement octave from an
artifact), and on an 11-piece real-music A/B it removed 94 extras but also
turned 66 correctly-played notes into `missed` -- a bad trade. It's kept
here for the no-reference case and stays OFF by default. See the scoring
filter first.

Two distinct artifact patterns, found by cross-referencing a real
transcription's "extra" notes (no reference counterpart) against a real
scored performance:

1. Harmonic/overtone bleed: 84% of extras fall within 150ms of a real,
   correctly-matched note, and 58% of THOSE are an octave/fifth/fourth away
   from it, at a noticeably lower velocity (median 50 vs 73 for genuine
   notes) -- the piano's own overtones or sustain-pedal resonance read as a
   separate new onset. See `suppress_harmonic_artifacts`.

   A flat velocity cutoff was tried first and rejected: real vs spurious
   velocity distributions overlap enough that no single threshold removes
   most artifacts without also cutting a meaningful share of real (quiet)
   notes. Requiring BOTH timing proximity AND a harmonic interval is far
   more targeted.

   Interval set is {5, 7, 12, 19}: perfect fourth, perfect fifth, octave, and
   octave+fifth (a compound fifth -- the 3rd harmonic one octave up, a
   strong, natural overtone; confirmed on a real transcription as an
   isolated, disconnected-from-the-melody quiet note a 19-semitone compound
   fifth above the real one).

   Default window widened from an initial 0.1s to 0.35s: on that same real
   case, the compound-fifth artifact consistently appeared ~0.3s *after* the
   note causing it, not at the same instant like most octave/fifth bleed --
   sympathetic resonance apparently takes a moment to build up to where the
   model reads it as a new onset. Checked this doesn't cost much: widening
   the window to 0.35s on a second, more complex piece reclassified 2 real
   notes as wrong_pitch (a real but small cost) while still removing several
   more genuine artifacts, net positive on both pieces tested.

   Deliberately NOT included: major third / compound major third (4 or 16
   semitones) intervals, even though a specific case (an E5 overtone of a
   sustained C4/C5) was traced to exactly this. A major third is one of the
   most common intervals in ordinary tonal harmony (it's the middle note of
   most major triads) -- adding it here would risk deleting real chord
   tones in other pieces far more often than it catches genuine overtones.
   That category of extra is a known, accepted remaining limitation.

2. Note splitting: a single sustained note's decaying amplitude can dip and
   recover in a way the model reads as a second re-attack of the *same*
   pitch partway through its own sustain -- e.g. a reference note held for a
   full second shows up as two transcribed onsets of the same pitch, the
   second one quieter. This is NOT a harmonic-interval case (same pitch =
   interval 0) so it needed a separate rule with a different time window:
   the split can occur anywhere within the original note's sustained
   duration, not just within a fixed ~100ms. See `suppress_note_splits`.

Both are off by default (like everything in preprocess.py) -- heuristics
that trade a little recall for suppressing artifacts; A/B test on real
recordings before assuming they help.
"""
from __future__ import annotations

from typing import Optional

HARMONIC_INTERVALS = {12, 7, 5, 19}  # octave, perfect fifth, perfect fourth, octave+fifth (semitones)


def suppress_harmonic_artifacts(
    notes: list,
    window_sec: float = 0.35,
    velocity_ratio: float = 0.75,
    intervals: Optional[set] = None,
) -> list:
    """Drop a note if, within `window_sec` of a louder note, it sits at a
    harmonic interval (octave/5th/4th) from it and is quieter than
    `velocity_ratio` of that louder note's velocity. Returns a new,
    time-sorted list; does not mutate the input.
    """
    intervals = intervals if intervals is not None else HARMONIC_INTERVALS
    ordered = sorted(notes, key=lambda n: n["onset_sec"])
    suppressed = set()

    for i, note in enumerate(ordered):
        for j in range(i + 1, len(ordered)):
            other = ordered[j]
            if other["onset_sec"] - note["onset_sec"] > window_sec:
                break
            if i in suppressed and j in suppressed:
                continue
            interval = abs(note["pitch"] - other["pitch"])
            if interval not in intervals:
                continue

            if note["velocity"] >= other["velocity"]:
                louder_vel, quieter_idx = note["velocity"], j
            else:
                louder_vel, quieter_idx = other["velocity"], i

            quieter_vel = ordered[quieter_idx]["velocity"]
            if quieter_vel <= louder_vel * velocity_ratio:
                suppressed.add(quieter_idx)

    return [n for idx, n in enumerate(ordered) if idx not in suppressed]


def suppress_note_splits(notes: list, velocity_ratio: float = 0.7) -> list:
    """Drop a note if it's the SAME pitch as an earlier, louder note and its
    onset falls within that earlier note's own sustained duration -- a
    'split' where a held note's decay got misread as a second re-attack of
    the same key. Unlike harmonic bleed, this uses the earlier note's own
    duration as the window (a split can occur anywhere within a held note,
    not just in the first ~100ms), not a fixed time window.
    """
    ordered = sorted(notes, key=lambda n: n["onset_sec"])
    suppressed = set()

    for i, note in enumerate(ordered):
        if i in suppressed:
            continue
        note_end = note["onset_sec"] + note["dur_sec"]
        for j in range(i + 1, len(ordered)):
            other = ordered[j]
            if other["onset_sec"] > note_end:
                break
            if j in suppressed or other["pitch"] != note["pitch"]:
                continue
            if other["velocity"] <= note["velocity"] * velocity_ratio:
                suppressed.add(j)

    return [n for idx, n in enumerate(ordered) if idx not in suppressed]


def filter_impossible_pitches(notes: list, keyboard_range: tuple) -> list:
    """Drop transcribed notes outside the physical keyboard's pitch range.

    Unlike every other filter in this file, this one isn't a heuristic: a
    37-key keyboard physically cannot produce MIDI 36 or 96, so when the
    audio source IS that keyboard, an out-of-range transcription is a
    guaranteed artifact (usually sub-octave/harmonic ghosts of a real note).

    Callers must only apply it when the audio really came from the physical
    keyboard (or from a reference that itself fits the range) -- synthesized
    audio from an arbitrary MIDI can genuinely contain out-of-range pitches.
    See backend/hardware.py and scripts/grade_audio.py.
    """
    low, high = keyboard_range
    return [n for n in notes if low <= n["pitch"] <= high]
