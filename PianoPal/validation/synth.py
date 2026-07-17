"""Synthesizes audio from a reference MIDI using a REAL piano soundfont via
FluidSynth -- deliberately does NOT fall back to a sine-wave synth.

Why this matters: a sine wave has no harmonics/overtones. The bug this whole
`validation` module exists to investigate -- basic-pitch transcribing a note
one octave higher than ground truth -- is suspected to be a harmonic/overtone
confusion (a strong 2nd-harmonic energy peak getting mistaken for the
fundamental). A sine-wave rendering would never reproduce that, since it has
no overtone content to confuse the model. Silently substituting one would
make every round-trip test "clean" regardless of whether the bug is real,
which is worse than no tool at all. So: no soundfont/no FluidSynth -> raise,
don't proceed.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .errors import SynthesisError

SAMPLE_RATE = 44100

_NO_SOUNDFONT_MESSAGE = (
    "No soundfont provided. This tool deliberately does NOT fall back to a "
    "sine-wave synth: a sine wave has no harmonics/overtones, so it could never "
    "reproduce a harmonic-confusion octave-error bug -- it would just make every "
    "round-trip test look clean regardless of whether the bug is real. Provide a "
    "real piano soundfont with --soundfont (e.g. FluidR3_GM.sf2, a free General "
    "MIDI soundfont -- we can't bundle one; download it separately)."
)


def synthesize_midi_to_wav(
    midi_path: str,
    soundfont_path: Optional[str],
    output_wav_path: str,
    sample_rate: int = SAMPLE_RATE,
) -> None:
    """Render `midi_path` to a WAV file at `output_wav_path` using a real
    piano soundfont. Raises SynthesisError (never silently substitutes a
    sine wave) if no usable soundfont/synthesis backend is available.
    """
    if not soundfont_path:
        raise SynthesisError(_NO_SOUNDFONT_MESSAGE)
    if not Path(soundfont_path).exists():
        raise SynthesisError(f"Soundfont not found at '{soundfont_path}'.")
    if not Path(midi_path).exists():
        raise SynthesisError(f"MIDI file not found at '{midi_path}'.")

    try:
        _synthesize_via_pyfluidsynth(midi_path, soundfont_path, output_wav_path, sample_rate)
        return
    except ImportError:
        pass

    fluidsynth_bin = shutil.which("fluidsynth")
    if fluidsynth_bin:
        _synthesize_via_cli(fluidsynth_bin, midi_path, soundfont_path, output_wav_path, sample_rate)
        return

    raise SynthesisError(
        "Neither the `pyfluidsynth` Python package nor the `fluidsynth` CLI binary "
        "is available. Install one of them (e.g. `pip install pyfluidsynth` and/or "
        "`brew install fluid-synth`) plus a real soundfont. A sine-wave fallback is "
        "deliberately not provided -- see this module's docstring for why."
    )


def _synthesize_via_pyfluidsynth(midi_path, soundfont_path, output_wav_path, sample_rate):
    import pretty_midi
    import soundfile as sf

    midi = pretty_midi.PrettyMIDI(midi_path)
    audio = midi.fluidsynth(fs=sample_rate, sf2_path=soundfont_path)
    sf.write(output_wav_path, audio, sample_rate)


def _synthesize_via_cli(fluidsynth_bin, midi_path, soundfont_path, output_wav_path, sample_rate):
    cmd = [
        fluidsynth_bin, "-ni", soundfont_path, midi_path,
        "-F", output_wav_path, "-r", str(sample_rate),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SynthesisError(f"fluidsynth CLI failed (exit {result.returncode}): {result.stderr}")
    if not Path(output_wav_path).exists():
        raise SynthesisError("fluidsynth CLI reported success but produced no output file.")
