#!/usr/bin/env python3
"""Synthesize a score reference with recorded BF-3738C keybank samples."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.audio_to_performance.keybank import load_keybank  # noqa: E402
from backend.score_to_reference.core import convert, to_seconds  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a MIDI/MusicXML/reference JSON using PianoPal keybank WAV samples.",
    )
    parser.add_argument("score", help="MIDI, MusicXML, or PianoPal reference JSON.")
    parser.add_argument("--keybank", required=True, help="Keybank JSON from train_keybank_from_scale.py.")
    parser.add_argument("-o", "--output", required=True, help="Output WAV path.")
    parser.add_argument("--bpm", type=int, default=None, help="Optional constant practice BPM.")
    parser.add_argument("--unsupported", choices=["error", "skip"], default="error")
    parser.add_argument("--gain", type=float, default=0.8)
    parser.add_argument("--tail-sec", type=float, default=1.0)
    return parser.parse_args()


def _load_reference(path: str, bpm: int | None) -> dict:
    if Path(path).suffix.lower() == ".json":
        reference = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        reference = convert(path)
    if bpm is not None:
        reference = to_seconds(reference, bpm)
    return reference


def _fade_out(audio: np.ndarray, sr: int, fade_sec: float = 0.02) -> np.ndarray:
    out = np.array(audio, dtype=np.float32, copy=True)
    fade_len = min(int(fade_sec * sr), len(out))
    if fade_len > 1:
        out[-fade_len:] *= np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
    return out


def main() -> int:
    args = parse_args()
    keybank = load_keybank(args.keybank)
    sr = int(keybank["sample_rate"])
    reference = _load_reference(args.score, args.bpm)
    samples = {}
    for entry in keybank["samples"]:
        audio, sample_sr = librosa.load(entry["sample_path"], sr=sr, mono=True)
        if sample_sr != sr:
            raise RuntimeError(f"unexpected sample rate for {entry['sample_path']}: {sample_sr}")
        samples[int(entry["midi"])] = np.asarray(audio, dtype=np.float32)

    unsupported = sorted({int(n["pitch"]) for n in reference.get("notes", []) if int(n["pitch"]) not in samples})
    if unsupported and args.unsupported == "error":
        raise SystemExit(
            "score contains pitches not present in this keybank: "
            f"{unsupported}. Use --unsupported skip or choose a white-key-only score."
        )

    duration_sec = float(reference.get("duration_sec", 0.0) or 0.0)
    if duration_sec <= 0 and reference.get("notes"):
        duration_sec = max(float(n["onset_sec"]) + float(n.get("dur_sec", 0.2) or 0.2) for n in reference["notes"])
    total_samples = max(1, int((duration_sec + args.tail_sec) * sr))
    mix = np.zeros(total_samples, dtype=np.float32)
    rendered = 0
    skipped = 0

    for note in reference.get("notes", []):
        pitch = int(note["pitch"])
        sample = samples.get(pitch)
        if sample is None:
            skipped += 1
            continue
        velocity = float(note.get("velocity", 80) or 80) / 100.0
        note_gain = args.gain * min(1.2, max(0.35, velocity))
        dur_sec = float(note.get("dur_sec", 0.2) or 0.2)
        max_len = max(1, int((dur_sec + 0.35) * sr))
        note_audio = _fade_out(sample[:max_len], sr) * note_gain
        start = max(0, int(round(float(note["onset_sec"]) * sr)))
        end = min(total_samples, start + len(note_audio))
        if end <= start:
            continue
        mix[start:end] += note_audio[:end - start]
        rendered += 1

    peak = float(np.max(np.abs(mix))) if len(mix) else 0.0
    if peak > 0.98:
        mix *= 0.98 / peak

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, mix, sr)
    print(f"written to {output}")
    print(f"rendered notes: {rendered}, skipped unsupported: {skipped}")
    if unsupported:
        print(f"unsupported pitches: {unsupported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
