"""Tunable settings for the audio_to_performance pipeline, in one place."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.hardware import KEYBOARD_RANGE

PIANO_LOW_HZ = 27.5    # A0, lowest note on a standard piano
PIANO_HIGH_HZ = 4186.0  # C8, highest note on a standard piano


@dataclass
class AudioToPerformanceConfig:
    # --- pre-processing (all OFF by default) ---
    # basic-pitch's model was trained on relatively raw audio; denoising,
    # band-pass filtering, and loudness normalization can all suppress or
    # distort the transient attack information the model relies on to place
    # onsets accurately. Turn these on deliberately and A/B test -- don't
    # assume "more cleanup" means "better transcription."
    denoise: bool = False
    bandpass: bool = False
    normalize: bool = False

    bandpass_low_hz: float = PIANO_LOW_HZ
    bandpass_high_hz: float = PIANO_HIGH_HZ
    noisereduce_prop_decrease: float = 1.0
    normalize_target_peak: float = 0.95

    # --- basic-pitch transcription params ---
    # Tuned against validation/roundtrip.py's round-trip octave-error harness
    # (known-good MIDI -> real soundfont -> transcribe -> diff against truth)
    # over 3 real pieces (Fur Elise, Bach Prelude BWV846, Maple Leaf Rag;
    # 3748 combined reference notes). Raising both thresholds from the
    # basic-pitch defaults (0.5/0.3) and disabling melodia_trick cut the
    # octave-error rate 16.9% -> 11.4% and wrong_pitch 28.8% -> 20.4%, at the
    # cost of missed notes rising 2.4% -> ~9.7% (still far below the ~72%
    # miss rate that generic onset detection had before this pipeline
    # existed). melodia_trick made no measurable difference to octave
    # errors on its own -- it's off here because combined with the stricter
    # thresholds it also trimmed spurious "extra" notes (494 -> 366).
    # minimum_frequency/maximum_frequency bounded to the piano's range had
    # zero effect in the sweep (basic-pitch already stays in-range
    # internally) so they're left unset rather than added as a no-op knob.
    #
    # RE-VALIDATED after the downstream artifact stack landed (37-key range
    # filter + scoring's reference-aware harmonic-extras filter + constrained
    # octave re-verification): reverting to the looser 0.5/0.3+melodia
    # defaults through that FULL path recovered 16 missed notes (23 -> 7 of
    # 1024) but flooded extras 48 -> 307 -- the flood is mostly non-octave
    # spurious detections that no reference-aware filter can safely remove.
    # For a practice coach, phantom notes shown to the student are worse
    # than a 2% miss rate, so strict stays.
    onset_threshold: float = 0.6
    frame_threshold: float = 0.4
    minimum_note_length_ms: float = 58.0
    minimum_frequency: Optional[float] = None
    maximum_frequency: Optional[float] = None
    melodia_trick: bool = False

    # --- post-processing (OFF by default) ---
    # basic-pitch's own overtones/sustain-pedal resonance sometimes get
    # transcribed as spurious extra notes at a harmonic interval from a real
    # one. See postprocess.py's docstring for the evidence behind this
    # heuristic and why a flat velocity cutoff was rejected in favor of it.
    suppress_harmonics: bool = False
    harmonic_window_sec: float = 0.35
    harmonic_velocity_ratio: float = 0.75

    # a held note's decay can get misread as a second re-attack of the same
    # pitch partway through its own sustain -- a different failure mode from
    # harmonic bleed (same pitch, not a harmonic interval), so it needs its
    # own suppression pass. See postprocess.suppress_note_splits.
    suppress_split_notes: bool = False
    note_split_velocity_ratio: float = 0.7

    # --- physical keyboard constraint (ON by default) ---
    # The project's keyboard has 37 keys (MIDI 48-84, see backend/hardware.py)
    # -- it physically cannot produce a note outside that range, so any
    # out-of-range transcription from a recording of it is a guaranteed
    # artifact and is dropped. NOT a heuristic, unlike the filters above.
    # Set to None when transcribing audio that did NOT come from the physical
    # keyboard (e.g. validation/roundtrip's synthesized renderings of
    # arbitrary MIDI files, which may genuinely exceed the range).
    keyboard_range: Optional[tuple] = KEYBOARD_RANGE
