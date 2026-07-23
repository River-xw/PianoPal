#!/usr/bin/env python3
"""Validate the audio grading pipeline against CONTROLLED, known-ground-truth
error cases synthesized from real keybank samples -- not ad-hoc real human
recordings.

Why: real recordings have too many uncontrolled variables at once (loudness,
technique, how legato/separated the notes are, actual timing) to cleanly
attribute a score difference to "the algorithm caught a wrong note" versus
"this take was just harder to transcribe than that one" -- exactly the
ambiguity that made the earlier normal-vs-mistake real-recording comparison
inconclusive on its own (see project history / grading pipeline notes).

This script instead starts from the SAME clean reference, applies a
deliberate, precisely-known perturbation (specific notes swapped to a wrong
pitch, specific notes omitted, specific extra notes inserted, plus a
realistic-but-known tempo rubato curve applied to everything), renders it to
audio with the real keybank samples (so timbre/hardware quirks are
authentic), grades it with the production pipeline, and checks the graded
result against the exact ground truth -- a real precision/recall number
instead of "this recording felt harder to score than that one".

Usage:
    ./backend/audio_to_performance/.venv/bin/python3 \\
        scripts/validate_grading_with_synthetic_errors.py
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.audio_to_performance.keybank import WHITE_KEY_MIDIS  # noqa: E402
from backend.score_to_reference import convert as convert_score  # noqa: E402
from backend.scoring.models import midi_pitch_to_name  # noqa: E402

REFERENCE_MIDI = REPO_ROOT / "docs/piano_music/twinkle_twinkle.mid"
KEYBANK_JSON = REPO_ROOT / "data/bf3738c_keybank/bf3738c_white_keybank.json"
KEYBOARD_PROFILE = REPO_ROOT / "data/bf3738c_keybank/bf3738c_white_profile.json"
PYTHON_VENV = REPO_ROOT / "backend/audio_to_performance/.venv/bin/python3"
SCRATCH_DIR = REPO_ROOT / "data/session_scratch/synthetic_error_validation"

WHITE_KEYS = sorted(WHITE_KEY_MIDIS)


# --- ground-truth error injection --------------------------------------------


@dataclass
class ErrorSpec:
    kind: str  # "wrong_pitch" | "missed" | "extra"
    note_index: int | None = None       # into the ORIGINAL notes list (wrong_pitch/missed)
    new_pitch: int | None = None        # for wrong_pitch
    insert_pitch: int | None = None     # for extra
    insert_onset_sec: float | None = None


@dataclass
class GroundTruth:
    wrong_pitch: dict = field(default_factory=dict)   # ref_index -> injected wrong pitch
    missed: set = field(default_factory=set)          # ref_index set
    extra: list = field(default_factory=list)         # [(pitch, onset_sec), ...]


def build_tempo_warp(duration_sec: float, num_segments: int = 6, max_variation: float = 0.18, seed: int = 0):
    """A monotonic, piecewise-linear time-warp function simulating realistic
    rubato: `num_segments` equal chunks of the piece, each played at its own
    random local tempo ratio (uniform in [1-variation, 1+variation]), with
    the FIRST segment additionally biased faster -- matching the "rushes the
    opening, settles down" pattern actually observed across every real
    recording tested (see backend/scoring/align.py's TempoCurve boundary-fix
    notes). Returns warp(t) -> t'; the inverse local ratio at any t is also
    exposed via `local_ratio(t)` for scaling note durations consistently.
    """
    rng = random.Random(seed)
    segment_len = duration_sec / num_segments
    ratios = [rng.uniform(1 - max_variation, 1 + max_variation) for _ in range(num_segments)]
    ratios[0] *= 0.82  # opening rush, matching real recordings

    boundaries = [i * segment_len for i in range(num_segments + 1)]
    warped_boundaries = [0.0]
    for i in range(num_segments):
        warped_boundaries.append(warped_boundaries[-1] + segment_len * ratios[i])

    def segment_index(t: float) -> int:
        return min(int(t / segment_len), num_segments - 1) if segment_len > 0 else 0

    def warp(t: float) -> float:
        idx = segment_index(t)
        local_t = t - boundaries[idx]
        return warped_boundaries[idx] + local_t * ratios[idx]

    def local_ratio(t: float) -> float:
        return ratios[segment_index(t)]

    return warp, local_ratio


def inject_errors(reference: dict, specs: list[ErrorSpec], tempo_warp=None, local_ratio=None) -> tuple[dict, GroundTruth]:
    """Returns (performance_reference, ground_truth). performance_reference
    is a full reference-JSON-shaped dict (same schema as backend.score_to_
    reference's output) representing what was ACTUALLY played -- feed it to
    synthesize_reference_from_keybank.py. Grade the resulting audio against
    the ORIGINAL (unmodified) reference MIDI, never against this one.
    """
    notes = deepcopy(reference["notes"])
    gt = GroundTruth()

    missed_indices = set()
    for spec in specs:
        if spec.kind == "wrong_pitch":
            notes[spec.note_index]["pitch"] = spec.new_pitch
            notes[spec.note_index]["name"] = midi_pitch_to_name(spec.new_pitch)
            gt.wrong_pitch[spec.note_index] = spec.new_pitch
        elif spec.kind == "missed":
            missed_indices.add(spec.note_index)
            gt.missed.add(spec.note_index)

    kept = [n for i, n in enumerate(notes) if i not in missed_indices]

    for spec in specs:
        if spec.kind == "extra":
            nearest_measure = min(
                kept, key=lambda n: abs(n["onset_sec"] - spec.insert_onset_sec)
            )["measure"] if kept else 1
            kept.append({
                "pitch": spec.insert_pitch, "name": midi_pitch_to_name(spec.insert_pitch),
                "onset_sec": spec.insert_onset_sec, "dur_sec": 0.3, "velocity": 70,
                "hand": "R", "measure": nearest_measure,
            })
            gt.extra.append((spec.insert_pitch, spec.insert_onset_sec))
    kept.sort(key=lambda n: n["onset_sec"])

    # Ground-truth extra onsets must reflect the POST-warp time (what's
    # actually in the rendered audio) -- comparing against the pre-warp
    # onset here previously made every injected extra look "uncaught" even
    # when the algorithm correctly found it, since the warp can shift later
    # notes by more than a second.
    if tempo_warp is not None:
        for n in kept:
            ratio = local_ratio(n["onset_sec"])
            n["onset_sec"] = tempo_warp(n["onset_sec"])
            n["dur_sec"] = float(n.get("dur_sec", 0.2) or 0.2) * ratio

    warped_extra = []
    for pitch, onset in gt.extra:
        warped_extra.append((pitch, tempo_warp(onset) if tempo_warp is not None else onset))
    gt.extra = warped_extra

    performance_reference = {**reference, "notes": kept}
    return performance_reference, gt


# --- test case scenarios ------------------------------------------------------


def make_scenarios(reference: dict) -> dict[str, tuple[list[ErrorSpec], bool]]:
    """name -> (error_specs, apply_tempo_warp). Note indices chosen as FRACTIONS
    through the (time-sorted) note list, not hardcoded absolute positions, so
    the same scenario set works on any white-keys-only song of any length,
    not just the 69-note piece this was first built against."""
    notes = sorted(reference["notes"], key=lambda n: n["onset_sec"])
    n = len(notes)

    def at(frac: float) -> int:
        return max(0, min(n - 1, int(round(frac * (n - 1)))))

    def wrong(frac, step_delta):
        # Shift by a number of WHITE-KEY steps (diatonic), not semitones --
        # a raw semitone offset can land on a black key the keybank has no
        # sample for at all (e.g. E3+2 semitones = F#3), which isn't even a
        # playable "wrong note" scenario on this white-keys-only keyboard.
        i = at(frac)
        current = notes[i]["pitch"]
        idx = WHITE_KEYS.index(current)
        new_idx = max(0, min(len(WHITE_KEYS) - 1, idx + step_delta))
        if WHITE_KEYS[new_idx] == current:
            new_idx = max(0, min(len(WHITE_KEYS) - 1, idx + step_delta * 2))
        return ErrorSpec("wrong_pitch", note_index=i, new_pitch=WHITE_KEYS[new_idx])

    def missed(frac):
        return ErrorSpec("missed", note_index=at(frac))

    def extra_between(frac):
        i = at(frac)
        j = min(i + 1, n - 1)
        if j == i:
            j = max(0, i - 1)
        onset = (notes[i]["onset_sec"] + notes[j]["onset_sec"]) / 2
        # a white key clearly different from both neighbors, so it reads as
        # a genuine extra note rather than coincidentally repeating one
        neighbors = {notes[i]["pitch"], notes[j]["pitch"]}
        pitch = next(p for p in WHITE_KEYS if p not in neighbors)
        return ErrorSpec("extra", insert_pitch=pitch, insert_onset_sec=onset)

    return {
        "clean_with_rubato": ([], True),
        "wrong_pitch_only": (
            [wrong(0.05, 2), wrong(0.20, -2), wrong(0.40, 4), wrong(0.65, -1), wrong(0.85, 2)], True
        ),
        "missed_only": ([missed(0.08), missed(0.25), missed(0.45), missed(0.70), missed(0.90)], True),
        "extra_only": ([extra_between(0.12), extra_between(0.32), extra_between(0.75)], True),
        "mixed_realistic": (
            [wrong(0.15, 2), wrong(0.55, -2), missed(0.20), missed(0.80), extra_between(0.40)], True
        ),
    }


# --- synth + grade + compare --------------------------------------------------


def synthesize(performance_reference: dict, out_wav: Path) -> None:
    perf_json = out_wav.with_suffix(".perf.json")
    perf_json.write_text(json.dumps(performance_reference), encoding="utf-8")
    cmd = [
        str(PYTHON_VENV), str(REPO_ROOT / "scripts/synthesize_reference_from_keybank.py"),
        str(perf_json), "--keybank", str(KEYBANK_JSON), "-o", str(out_wav),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"synthesis failed: {result.stdout}\n{result.stderr}")


def grade(reference_midi: Path, audio_wav: Path, out_json: Path) -> dict:
    cmd = [
        str(PYTHON_VENV), str(REPO_ROOT / "scripts/grade_audio_reference_constrained.py"),
        str(reference_midi), str(audio_wav),
        "--keyboard-profile", str(KEYBOARD_PROFILE), "--white-keys-only",
        "-o", str(out_json),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"grading failed: {result.stdout}\n{result.stderr}")
    return json.loads(out_json.read_text(encoding="utf-8"))


def compare(result: dict, gt: GroundTruth) -> dict:
    by_ref_index = {n["ref_index"]: n for n in result["notes"] if n.get("ref_index") is not None}
    total_ref_notes = sum(1 for n in result["notes"] if n.get("ref_index") is not None)
    injected_indices = set(gt.wrong_pitch) | gt.missed

    wrong_pitch_hits = sum(
        1 for i in gt.wrong_pitch
        if by_ref_index.get(i) and by_ref_index[i]["status"] == "wrong_pitch"
        and by_ref_index[i].get("pitch_perf") == gt.wrong_pitch[i]
    )
    missed_hits = sum(1 for i in gt.missed if by_ref_index.get(i) and by_ref_index[i]["status"] == "missed")

    false_positives = [
        n for n in result["notes"]
        if n.get("ref_index") is not None and n["ref_index"] not in injected_indices
        and n["status"] not in ("correct", "timing_off")
    ]

    extra_notes = [n for n in result["notes"] if n["status"] == "extra"]
    extra_hits = 0
    for pitch, onset in gt.extra:
        if any(n.get("pitch_perf") == pitch and n.get("onset_perf_sec") is not None
               and abs(n["onset_perf_sec"] - onset) < 1.0 for n in extra_notes):
            extra_hits += 1

    return {
        "score": result["summary"]["score"],
        "counts": result["summary"]["counts"],
        "wrong_pitch_injected": len(gt.wrong_pitch), "wrong_pitch_caught": wrong_pitch_hits,
        "missed_injected": len(gt.missed), "missed_caught": missed_hits,
        "extra_injected": len(gt.extra), "extra_caught": extra_hits,
        "false_positives_on_clean_notes": len(false_positives),
        "false_positive_ref_indices": [n["ref_index"] for n in false_positives],
        "clean_notes_total": total_ref_notes - len(injected_indices),
    }


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference", default=str(REFERENCE_MIDI),
        help="White-keys-only reference MIDI to validate against (default: twinkle_twinkle).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reference_midi = Path(args.reference)
    song_label = reference_midi.stem
    scratch_dir = SCRATCH_DIR / song_label
    scratch_dir.mkdir(parents=True, exist_ok=True)

    reference = convert_score(str(reference_midi))
    # convert_score already returns onset-sorted notes (verified empirically
    # across songs); sorting explicitly here guarantees make_scenarios()'s
    # fractional note-index selection and inject_errors()'s indexing agree,
    # instead of silently relying on that being true.
    reference["notes"].sort(key=lambda note: note["onset_sec"])

    duration = max(float(n["onset_sec"]) + float(n.get("dur_sec", 0.2) or 0.2) for n in reference["notes"])
    tempo_warp, local_ratio = build_tempo_warp(duration, num_segments=6, max_variation=0.18, seed=7)

    scenarios = make_scenarios(reference)

    reports = {}
    for name, (specs, use_warp) in scenarios.items():
        print(f"=== {song_label} / {name} ===")
        perf_ref, gt = inject_errors(
            reference, specs,
            tempo_warp=tempo_warp if use_warp else None,
            local_ratio=local_ratio if use_warp else None,
        )
        wav_path = scratch_dir / f"{name}.wav"
        result_path = scratch_dir / f"{name}_result.json"
        synthesize(perf_ref, wav_path)
        result = grade(reference_midi, wav_path, result_path)
        report = compare(result, gt)
        reports[name] = report
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print()

    print(f"=== summary ({song_label}) ===")
    for name, r in reports.items():
        print(
            f"{name:20s} score={r['score']:6.2f}  "
            f"wrong_pitch {r['wrong_pitch_caught']}/{r['wrong_pitch_injected']}  "
            f"missed {r['missed_caught']}/{r['missed_injected']}  "
            f"extra {r['extra_caught']}/{r['extra_injected']}  "
            f"false_pos={r['false_positives_on_clean_notes']}/{r['clean_notes_total']}"
        )

    summary_path = scratch_dir / "summary.json"
    summary_path.write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwritten to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
