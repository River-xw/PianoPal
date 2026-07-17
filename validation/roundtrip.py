"""Round-trip validation: reference.mid -> (real-soundfont synthesis) ->
synth.wav -> (existing audio_to_performance pipeline) -> transcribed.mid ->
diff report.

Isolates transcription error from everything else that could cause a
mismatch in a real recording (no real playing, no mic noise, no timing
variance, no room acoustics) -- if an octave error shows up here, it's
coming from the transcription model itself, not from any of those other
sources. See synth.py for why this deliberately requires a real piano
soundfont rather than a sine-wave stand-in.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from audio_to_performance.config import AudioToPerformanceConfig  # noqa: E402
from audio_to_performance.pipeline import transcribe  # noqa: E402
from scoring.midi_io import midi_to_performance  # noqa: E402

from .compare import match_notes  # noqa: E402
from .report import build_report  # noqa: E402
from .synth import synthesize_midi_to_wav  # noqa: E402

SCORE_EXTENSIONS = {".musicxml", ".xml", ".mxl"}
MIDI_EXTENSIONS = {".mid", ".midi"}


def _ensure_midi(reference_path: str) -> tuple:
    """Returns (midi_path, cleanup_flag). Converts a MusicXML score to a
    temporary MIDI via music21 if needed (FluidSynth renders MIDI, not
    MusicXML) -- everything downstream treats the reference as MIDI either way.
    """
    ext = Path(reference_path).suffix.lower()
    if ext in MIDI_EXTENSIONS:
        return reference_path, False
    if ext in SCORE_EXTENSIONS:
        from music21 import converter

        score = converter.parse(reference_path)
        tmp = tempfile.NamedTemporaryFile(suffix=".mid", delete=False)
        tmp.close()
        score.write("midi", fp=tmp.name)
        return tmp.name, True
    raise ValueError(f"Unsupported reference file extension '{ext}' (expected .mid/.musicxml/.xml/.mxl)")


def run_roundtrip(
    reference_path: str,
    soundfont_path: str,
    onset_tol_sec: float = 0.1,
    save_synth_wav: Optional[str] = None,
    save_transcribed_midi: Optional[str] = None,
    audio_config: Optional[AudioToPerformanceConfig] = None,
) -> dict:
    """Runs the full round-trip for one reference file and returns a report
    dict (see report.build_report for its shape).
    """
    midi_path, cleanup_midi = _ensure_midi(reference_path)

    wav_path = save_synth_wav
    cleanup_wav = False
    if wav_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        wav_path = tmp.name
        cleanup_wav = True

    try:
        synthesize_midi_to_wav(midi_path, soundfont_path, wav_path)
        ref_notes = midi_to_performance(midi_path)
        transcribed_notes = transcribe(
            wav_path=wav_path, config=audio_config, save_midi_path=save_transcribed_midi
        )
    finally:
        if cleanup_midi:
            Path(midi_path).unlink(missing_ok=True)
        if cleanup_wav:
            Path(wav_path).unlink(missing_ok=True)

    diffs = match_notes(ref_notes, transcribed_notes, onset_tol_sec)
    return build_report(diffs, reference_file=reference_path)


def collect_reference_files(paths: list) -> list:
    """Expands a list of files/directories into a flat, sorted list of
    reference score/MIDI files (recursing into directories).
    """
    valid_exts = MIDI_EXTENSIONS | SCORE_EXTENSIONS
    collected: list = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for ext in valid_exts:
                collected.extend(str(f) for f in path.rglob(f"*{ext}"))
        elif path.is_file():
            collected.append(str(path))
    return sorted(set(collected))


if __name__ == "__main__":
    # deferred import: avoids a circular import at module-load time (cli.py
    # imports this module), and lets `python -m validation.roundtrip ...`
    # work directly, matching this tool's documented invocation.
    from .cli import main

    raise SystemExit(main())
