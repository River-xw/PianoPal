#!/usr/bin/env python3
"""Audio-input grading orchestration: a real recording (or a reference MIDI
synthesized to audio) -> reference.json -> basic-pitch transcription ->
scoring -> constrained-verification re-check -> viewer.

This is the audio-path sibling of scripts/grade.py (which grades an already-
symbolic performance -- a MIDI keyboard capture or a performance.json). Here
the performance comes from *audio*, so the whole transcription stack runs,
and its two known failure modes are both mitigated in the pipeline the
result actually flows through:

  * harmonic-overtone EXTRAS      -> backend.scoring's reference-aware
                                     suppress_harmonic_extras (default on)
  * OCTAVE errors in wrong_pitch  -> backend.audio_to_performance.
                                     constrained_verification, re-checking
                                     each disputed note against the raw audio
                                     among a small candidate set (this script
                                     wires it in; scoring alone can't, it has
                                     no audio)

Usage:
    python3 scripts/grade_audio.py <reference.mid/musicxml> <recording.wav>
    python3 scripts/grade_audio.py <reference.mid> --synthesize --soundfont FluidR3_GM.sf2

--synthesize renders the reference itself to audio with a real soundfont
(the round-trip path -- useful with no real recording, e.g. for the demo).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.hardware import KEYBOARD_RANGE  # noqa: E402
from backend.score_to_reference import convert as convert_score  # noqa: E402
from backend.scoring import ScoringConfig, score_performance  # noqa: E402
from backend.audio_to_performance.config import AudioToPerformanceConfig  # noqa: E402
from backend.audio_to_performance.pipeline import load_audio, transcribe  # noqa: E402
from backend.audio_to_performance.constrained_verification import (  # noqa: E402
    ConstrainedVerificationConfig,
    load_keyboard_profile,
    reverify_result,
)

VIEWER_DIR = PROJECT_ROOT / "frontend" / "viewer"


def _status_labels():
    return {"correct": 0, "timing_off": 0, "wrong_pitch": 0, "missed": 0, "extra": 0}


def _reclassify_corrected_octaves(result: dict, tol_ms: float) -> int:
    """In place: for each wrong_pitch note the audio re-check corrected to the
    reference pitch, flip its verdict to correct/timing_off (by its existing
    timing offset), then recompute summary counts + sub-scores + score with
    the SAME formula backend.scoring._summarize uses. `missed` notes are left
    as-is -- correcting one would mean fabricating a note the audio pipeline
    never emitted, which this pipeline deliberately never does. Returns the
    number of notes corrected.
    """
    corrected = 0
    for n in result["notes"]:
        v = n.get("verification")
        if not v:
            continue
        flag = v.get("flag")
        original_status = v.get("original_status")

        if flag == "corrected_octave_or_harmonic_error" and original_status == "wrong_pitch":
            # audio confirms the reference pitch was played -> flip the verdict
            offset_ms = n.get("offset_ms")
            within = offset_ms is not None and abs(offset_ms) <= tol_ms
            n["status"] = "correct" if within else "timing_off"
            n["pitch_perf"] = n.get("pitch_ref")
            corrected += 1
        else:
            # reverify_result relabels every note it inspects with its own
            # status vocabulary (reverified_different_pitch, an octave
            # "correction" of a `missed` note we won't fabricate, etc.).
            # Anything we're NOT accepting as a wrong_pitch octave fix gets
            # its original scoring status/pitch restored, so those relabels
            # never leak into the counts or the viewer.
            n["status"] = original_status
            n["pitch_perf"] = v.get("original_pitch_guess")

    _recompute_summary(result, tol_ms)
    return corrected


def _recompute_summary(result: dict, tol_ms: float) -> None:
    """Recompute summary counts/sub_scores/score from the (possibly
    reclassified) notes -- mirrors backend.scoring.score._summarize so the
    audio path stays consistent with the symbolic path's formula.
    """
    counts = _status_labels()
    for n in result["notes"]:
        if n["status"] in counts:
            counts[n["status"]] += 1

    denom_all = sum(counts.values())
    pitch = 100.0 * (counts["correct"] + counts["timing_off"]) / denom_all if denom_all else 100.0
    matched_ok = counts["correct"] + counts["timing_off"]
    rhythm = 100.0 * counts["correct"] / matched_ok if matched_ok else 100.0

    # timing_stability depends only on matched-note offset spread, which the
    # reclassification doesn't change, so keep the value scoring already computed
    timing_stability = result["summary"]["sub_scores"]["timing_stability"]

    summary = result["summary"]
    summary["counts"] = counts
    summary["sub_scores"] = {
        "pitch": round(pitch, 2), "rhythm": round(rhythm, 2),
        "timing_stability": round(timing_stability, 2),
    }
    summary["score"] = round(0.4 * pitch + 0.4 * rhythm + 0.2 * timing_stability, 2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/grade_audio.py",
        description="Grade an audio recording against a reference score, with octave re-verification.",
    )
    parser.add_argument("reference", help="Reference score: .mid/.midi/.musicxml/.xml/.mxl")
    parser.add_argument("audio", nargs="?", help="Recording (.wav/.mp3/...). Omit with --synthesize.")
    parser.add_argument("--synthesize", action="store_true", help="Render the reference to audio with a soundfont instead of using a recording.")
    parser.add_argument("--soundfont", help="Soundfont path (required with --synthesize).")
    parser.add_argument("--song-name", default=None, help="Display name for the viewer (defaults to the reference title).")
    parser.add_argument("--keyboard-range", type=int, nargs=2, default=list(KEYBOARD_RANGE), metavar=("LOW", "HIGH"), help="Physical keyboard MIDI range (default: the project's 37-key board, 48-84 -- see backend/hardware.py).")
    parser.add_argument("--keyboard-profile", default=None, help="Optional electronic-keyboard profile JSON from scripts/train_keyboard_profile.py.")
    parser.add_argument("--keyboard-profile-weight", type=float, default=0.75, help="Weight of the keyboard profile score boost during re-verification.")
    parser.add_argument("-o", "--output", default=str(VIEWER_DIR / "public" / "result.json"), help="Where to write result.json (defaults to the viewer's public/).")
    parser.add_argument("--no-reverify", action="store_true", help="Skip the constrained-verification octave re-check.")
    args = parser.parse_args(argv)

    reference = convert_score(args.reference)
    print(f"reference: {reference.get('title')}  ({len(reference['notes'])} notes)")

    # --- 37-key physical constraint (backend/hardware.py) ---
    # The keyboard can't produce pitches outside kb_range, so out-of-range
    # transcriptions from a REAL recording are guaranteed artifacts. For
    # --synthesize the audio comes from the MIDI file, not the keyboard, so
    # the filter is only safe when the reference itself fits the range.
    kb_range = tuple(args.keyboard_range)
    unplayable = [n["pitch"] for n in reference["notes"] if not (kb_range[0] <= n["pitch"] <= kb_range[1])]
    if unplayable:
        print(f"  WARNING: {len(unplayable)} reference note(s) fall outside the {kb_range} keyboard range "
              f"(pitches {sorted(set(unplayable))}) -- the student physically cannot play them as written.")
    reference_fits = not unplayable
    apply_range = (not args.synthesize) or reference_fits
    effective_range = kb_range if apply_range else None
    if not apply_range:
        print("  (keyboard-range artifact filtering disabled: synthesized audio genuinely contains out-of-range pitches)")

    cleanup_wav = None
    if args.synthesize:
        if not args.soundfont:
            parser.error("--synthesize requires --soundfont")
        from backend.validation.synth import synthesize_midi_to_wav

        # synth needs MIDI; if the reference is MusicXML, convert via music21
        ref_midi = args.reference
        if Path(args.reference).suffix.lower() not in {".mid", ".midi"}:
            from music21 import converter

            tmp_mid = tempfile.NamedTemporaryFile(suffix=".mid", delete=False)
            tmp_mid.close()
            converter.parse(args.reference).write("midi", fp=tmp_mid.name)
            ref_midi = tmp_mid.name

        tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_wav.close()
        synthesize_midi_to_wav(ref_midi, args.soundfont, tmp_wav.name)
        audio_path = tmp_wav.name
        cleanup_wav = tmp_wav.name
        print(f"synthesized audio from reference via {Path(args.soundfont).name}")
    else:
        if not args.audio:
            parser.error("provide an audio file, or use --synthesize --soundfont ...")
        audio_path = args.audio

    print("transcribing (basic-pitch)...")
    performance = transcribe(wav_path=audio_path, config=AudioToPerformanceConfig(keyboard_range=effective_range))
    print(f"  transcribed {len(performance)} notes")

    result = score_performance(reference, performance, song_name=args.song_name)
    result_dict = result.to_dict()
    print(f"  pass 1 score {result_dict['summary']['score']}  counts {result_dict['summary']['counts']}"
          f"  (harmonic extras removed: {result_dict['summary']['harmonic_extras_removed']})")

    if not args.no_reverify:
        # A wrong_pitch note is already ALIGNED to a specific reference note
        # (that's what makes it wrong_pitch rather than extra) -- it just got
        # the wrong pitch verdict. So when the raw audio confirms (via
        # constrained_verification) that the reference pitch was in fact the
        # one played, we can flip that single note's verdict in place, no
        # re-alignment. Re-running the DTW instead was tried and rejected: on
        # a corrected performance the alignment shifts unpredictably, turning
        # one resolved wrong_pitch into a stray extra+missed pair rather than
        # a clean `correct`. In-place keeps counts/score/viewer coherent and
        # preserves the per-note verification audit trail.
        print("constrained re-verification of wrong_pitch against raw audio...")
        audio, sr = load_audio(audio_path)
        cv_config = ConstrainedVerificationConfig(
            keyboard_range=effective_range,
            keyboard_profile=load_keyboard_profile(args.keyboard_profile) if args.keyboard_profile else None,
            keyboard_profile_weight=args.keyboard_profile_weight,
        )
        result_dict = reverify_result(result_dict, audio, sr, reference=reference, config=cv_config)
        corrected = _reclassify_corrected_octaves(result_dict, tol_ms=ScoringConfig().tol_ms)
        print(f"  {corrected} wrong_pitch note(s) corrected to the reference pitch by audio evidence,"
              f" {len(result_dict.get('unscored_extra_onsets', []))} unscored onset(s) flagged")

    if cleanup_wav:
        Path(cleanup_wav).unlink(missing_ok=True)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwritten to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
