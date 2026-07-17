"""validation: round-trip transcription validation (reference MIDI ->
real-soundfont synthesis -> audio_to_performance -> diff report), built to
isolate and quantify basic-pitch's octave-error rate by piano register.

Note: `roundtrip` is intentionally NOT re-exported here (only `from
backend.validation.roundtrip import run_roundtrip`, not `from backend.validation import
run_roundtrip`) -- this module also doubles as the `python -m
validation.roundtrip` CLI entry point, and eagerly importing it here as a
package member causes Python's harmless-but-noisy "found in sys.modules
... prior to execution" RuntimeWarning when run that way.
"""
from .compare import NoteDiff, match_notes
from .errors import SynthesisError, ValidationError
from .report import aggregate_reports, build_report
from .synth import synthesize_midi_to_wav

__all__ = [
    "match_notes",
    "NoteDiff",
    "build_report",
    "aggregate_reports",
    "synthesize_midi_to_wav",
    "ValidationError",
    "SynthesisError",
]
