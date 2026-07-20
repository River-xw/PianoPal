"""Per-song frequency-range narrowing for basic-pitch transcription.

The project's song library is known in advance -- not arbitrary, open-ended
audio -- so for any given reference score we know exactly which pitches it
actually uses. Narrowing basic-pitch's minimum_frequency/maximum_frequency
to that song's range (padded, so a genuine performance mistake that strays
slightly outside it isn't silently dropped) is a much tighter constraint
than the full piano range (27.5-4186Hz): an earlier sweep found bounding to
the full piano range had ZERO effect, specifically because it barely
constrains basic-pitch's search space at all. A single song's range is
usually far narrower.

Padding chosen from a real 11-piece A/B sweep (synth audio, full scoring
path), sweeping pad_semitones from 12 down to 0:

  pad=12 (1 octave): identical to no bound at all (995 correct, 60 extra) --
    too loose to constrain anything, same failure mode as the full-piano-range sweep.
  pad=6 or pad=3: identical to each other, and a clean win: extra 60->50,
    wrong_pitch 7->6, missed 22->23 (one real note lost). No reason to prefer
    3 over 6 -- picked 6 for a bit more safety margin against the boundary.
  pad=0 (exact song range, no buffer): overcorrects badly -- correct 995->962,
    missed 22->51, wrong_pitch 7->11. Some of the song's own written notes
    sit exactly at the range boundary and get clipped along with the noise.

6 semitones is the default here for that reason -- not a guess.
"""
from __future__ import annotations


def compute_song_frequency_range(reference: dict, pad_semitones: int = 6) -> tuple:
    """Returns (min_hz, max_hz) spanning the reference's actual pitch range,
    padded by `pad_semitones` on each side (default: a full octave) so a
    real performance mistake that strays outside the song's exact notes
    isn't clipped as if it were noise -- only frequencies far outside any
    plausible mistake on this song are excluded.
    """
    pitches = [note["pitch"] for note in reference["notes"]]
    if not pitches:
        raise ValueError("reference has no notes to compute a frequency range from")
    lowest = min(pitches) - pad_semitones
    highest = max(pitches) + pad_semitones
    min_hz = 440.0 * 2 ** ((lowest - 69) / 12)
    max_hz = 440.0 * 2 ** ((highest - 69) / 12)
    return min_hz, max_hz
