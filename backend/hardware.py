"""Physical hardware constraints -- single source of truth.

The project's keyboard has 37 keys. Assumed layout: C3..C6, MIDI 48..84
(the standard 37-key C-to-C span, and the same example range used when the
camera calibration was specified). If the keyboard is octave-shifted from
that, fix it HERE and every consumer (transcription range filtering, octave-
candidate generation, grading scripts) follows.

Why this matters everywhere downstream: audio has an inherent octave
ambiguity (harmonics at 2x/4x the fundamental), but the keyboard physically
cannot produce a note outside its own key range -- so any transcribed pitch
outside [48, 84] in a recording OF THIS KEYBOARD is a guaranteed
transcription artifact, and any octave-error candidate outside it is
impossible and should never be considered.

Note the qualifier "of this keyboard": audio synthesized from an arbitrary
MIDI file (the round-trip/demo path) may genuinely contain out-of-range
pitches, so consumers must only assume the constraint when the audio source
is the physical keyboard (or a reference that itself fits the range) --
see scripts/grade_audio.py for how that decision is made.
"""

KEYBOARD_NUM_KEYS = 37
KEYBOARD_LOWEST_PITCH = 48   # C3
KEYBOARD_HIGHEST_PITCH = 84  # C6
KEYBOARD_RANGE = (KEYBOARD_LOWEST_PITCH, KEYBOARD_HIGHEST_PITCH)
