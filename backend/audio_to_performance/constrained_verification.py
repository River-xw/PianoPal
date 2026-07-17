"""Constrained, harmonic-aware re-verification of basic-pitch's wrong_pitch/
missed notes -- a layer ON TOP OF the existing pipeline (transcribe.py,
pipeline.py), not a replacement for it.

Why: basic-pitch does free (unconstrained) polyphonic transcription across
the whole piano range, which makes it prone to OCTAVE ERRORS -- 2*f0
physically coincides with the octave-up note, and piano inharmonicity can
make a harmonic stronger than the fundamental in the low registers (see
validation/roundtrip.py, which quantifies this). But we already know what
note SHOULD be there from reference.json. So instead of trusting basic-
pitch's raw note list blindly, for each disputed note we go back to the raw
audio and check evidence among only a small, physically-plausible candidate
set (the expected pitch, its likely octave/near-miss confusions) -- a much
easier, better-conditioned problem than open-ended transcription, and one
where we can explicitly model "this is probably just a harmonic of that
other candidate" rather than picking whichever bin has the most energy.

Two independent mechanisms:
  1. Candidate-constrained re-verification of wrong_pitch/missed notes
     (get_candidates, score_candidate, reverify_note, reverify_result).
  2. A separate, pitch-agnostic scan for onsets that don't correspond to any
     known note at all (scan_unexpected_onsets) -- (1) structurally can't
     see these, since it only ever looks where the reference/result already
     expects something.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

import librosa
import numpy as np

# --- config -----------------------------------------------------------------


@dataclass
class ConstrainedVerificationConfig:
    # candidate generation: {ref_pitch + offset for offset in candidate_semitone_offsets}
    candidate_semitone_offsets: tuple = (0, 12, -12, 24, -24, 1, -1, 2, -2)

    # TODO: set keyboard_range=(lowest_pitch, highest_pitch) once the physical
    # keyboard is measured; this narrows candidates and reduces false
    # octave-confusion matches for notes near our actual range boundary.
    # None (no filtering) for now since we don't know the range yet.
    keyboard_range: Optional[tuple] = None

    # harmonic-aware scoring: a candidate that's the octave-up of another,
    # stronger candidate is treated as probably just that candidate's
    # harmonic, not an independently played note, when its own energy is
    # below this ratio of the lower candidate's energy.
    harmonic_energy_discount_ratio: float = 0.4
    harmonic_discount_factor: float = 0.15  # multiply score by this when discounted (heavy penalty, not zero)

    # winner must account for at least this fraction of total scored "mass"
    # across all candidates, else the result is inconclusive (relative, not
    # absolute, so it isn't thrown off by recording loudness/velocity).
    min_confidence_ratio: float = 0.3

    # which scoring statuses get re-verified at all
    trigger_statuses: frozenset = field(default_factory=lambda: frozenset({"wrong_pitch", "missed"}))

    # audio window extracted around a note's expected (reference) onset
    onset_window_sec: float = 0.15

    # CQT parameters for the per-note candidate scoring
    cqt_fmin_hz: float = 27.5  # A0
    cqt_bins_per_octave: int = 36  # finer than 12 for sharper fundamental/harmonic discrimination
    cqt_n_octaves: int = 8

    # step 4: flag a detected onset if it's more than this far (seconds)
    # from every reference onset AND every already-scored performance onset
    onset_gap_sec: float = 0.2


# --- candidate generation ----------------------------------------------------


def get_candidates(
    ref_pitch: int,
    keyboard_range: Optional[tuple] = None,
    config: Optional[ConstrainedVerificationConfig] = None,
) -> list:
    """Candidate MIDI pitches to check audio evidence for, instead of
    trusting basic-pitch's full-range guess: the expected pitch plus its
    likely octave and near-miss confusions.
    """
    config = config or ConstrainedVerificationConfig()
    candidates = sorted({ref_pitch + offset for offset in config.candidate_semitone_offsets})
    if keyboard_range is not None:
        low, high = keyboard_range
        candidates = [p for p in candidates if low <= p <= high]
    return candidates


# --- harmonic-aware CQT scoring ----------------------------------------------


def _midi_to_hz(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


@dataclass
class CQTFrame:
    """A single aggregated CQT time-frame (magnitude per bin), self-
    describing so pitch<->bin lookups don't need external context. Lets
    tests construct fake evidence directly without computing a real CQT.
    """

    magnitudes: np.ndarray
    fmin_hz: float
    bins_per_octave: int

    def energy_at_pitch(self, pitch: int) -> float:
        freq_hz = _midi_to_hz(pitch)
        if freq_hz <= 0 or self.fmin_hz <= 0:
            return 0.0
        bin_index = int(round(self.bins_per_octave * np.log2(freq_hz / self.fmin_hz)))
        if 0 <= bin_index < len(self.magnitudes):
            return float(self.magnitudes[bin_index])
        return 0.0


def _compute_cqt_frame(audio_window: np.ndarray, sr: int, config: ConstrainedVerificationConfig) -> CQTFrame:
    n_bins = config.cqt_bins_per_octave * config.cqt_n_octaves
    min_len = 2 ** 6  # librosa.cqt needs a minimally-sized input
    if audio_window is None or len(audio_window) < min_len:
        return CQTFrame(np.zeros(n_bins), config.cqt_fmin_hz, config.cqt_bins_per_octave)
    cqt = librosa.cqt(
        audio_window, sr=sr, fmin=config.cqt_fmin_hz,
        bins_per_octave=config.cqt_bins_per_octave, n_bins=n_bins,
    )
    magnitudes = np.abs(cqt).mean(axis=1)
    return CQTFrame(magnitudes, config.cqt_fmin_hz, config.cqt_bins_per_octave)


def score_candidate(
    cqt_frame: CQTFrame,
    candidate_pitch: int,
    ref_pitch: int,
    all_candidates: list,
    config: Optional[ConstrainedVerificationConfig] = None,
) -> float:
    """Evidence score for one candidate pitch: its own fundamental energy,
    heavily discounted if it's plausibly just the octave-up harmonic of
    another, stronger candidate rather than an independently played note.
    """
    config = config or ConstrainedVerificationConfig()
    energy = cqt_frame.energy_at_pitch(candidate_pitch)
    score = energy

    lower_octave_pitch = candidate_pitch - 12
    if lower_octave_pitch in all_candidates and lower_octave_pitch != candidate_pitch:
        lower_energy = cqt_frame.energy_at_pitch(lower_octave_pitch)
        if lower_energy > 0 and energy < config.harmonic_energy_discount_ratio * lower_energy:
            score *= config.harmonic_discount_factor

    return float(score)


# --- per-note re-verification ------------------------------------------------


def reverify_note(
    note: dict,
    audio_window: Optional[np.ndarray],
    sr: Optional[int] = None,
    config: Optional[ConstrainedVerificationConfig] = None,
    cqt_frame: Optional[CQTFrame] = None,
) -> dict:
    """Re-examines one wrong_pitch/missed note against constrained,
    harmonic-aware audio evidence. Pass a pre-computed `cqt_frame` directly
    (e.g. in tests) to skip audio/CQT extraction entirely; otherwise
    `audio_window` + `sr` are used to compute one.
    """
    config = config or ConstrainedVerificationConfig()
    if cqt_frame is None:
        if audio_window is None or sr is None:
            raise ValueError("reverify_note needs either cqt_frame, or both audio_window and sr")
        cqt_frame = _compute_cqt_frame(audio_window, sr, config)

    updated = dict(note)
    ref_pitch = note["pitch_ref"]
    original_status = note["status"]
    original_pitch_guess = note.get("pitch_perf")

    candidates = get_candidates(ref_pitch, config.keyboard_range, config)
    scores = {c: score_candidate(cqt_frame, c, ref_pitch, candidates, config) for c in candidates}

    total = sum(scores.values())
    winner = max(scores, key=scores.get)
    confidence = (scores[winner] / total) if total > 0 else 0.0

    verification = {
        "original_status": original_status,
        "original_pitch_guess": original_pitch_guess,
        "candidates_scored": {c: round(s, 6) for c, s in scores.items()},
        "winner": winner,
        "confidence": round(confidence, 4),
    }

    if confidence < config.min_confidence_ratio:
        verification["new_status"] = original_status
        verification["flag"] = "reverification_inconclusive"
        # status/pitch_perf intentionally untouched -- never silently guess.
    elif winner == ref_pitch:
        updated["status"] = "corrected_octave_or_harmonic_error"
        updated["pitch_perf"] = ref_pitch
        verification["new_status"] = "corrected_octave_or_harmonic_error"
        verification["flag"] = "corrected_octave_or_harmonic_error"
    elif original_pitch_guess is not None and winner == original_pitch_guess:
        verification["new_status"] = original_status
        verification["flag"] = "confirmed_genuine"
        # basic-pitch's original guess holds up -- leave status unchanged.
    else:
        updated["status"] = "reverified_different_pitch"
        updated["pitch_perf"] = winner
        verification["new_status"] = "reverified_different_pitch"
        verification["flag"] = "reverified_different_pitch"

    updated["verification"] = verification
    return updated


def reverify_result(
    result: dict,
    audio: np.ndarray,
    sr: int,
    reference: Optional[dict] = None,
    config: Optional[ConstrainedVerificationConfig] = None,
) -> dict:
    """Runs reverify_note over every trigger-status note in `result`, and
    (if `reference` is given) scan_unexpected_onsets over the whole
    recording. Returns a new, augmented result; never mutates the input.
    """
    config = config or ConstrainedVerificationConfig()
    augmented = copy.deepcopy(result)
    half_window = config.onset_window_sec

    for i, note in enumerate(augmented["notes"]):
        if note["status"] not in config.trigger_statuses:
            note.setdefault("verification", None)
            continue

        onset = note.get("onset_ref_sec")
        if onset is None:
            note["verification"] = {
                "original_status": note["status"], "original_pitch_guess": note.get("pitch_perf"),
                "candidates_scored": {}, "winner": None, "confidence": 0.0,
                "new_status": note["status"], "flag": "reverification_inconclusive",
            }
            continue

        start_sample = max(0, int((onset - half_window) * sr))
        end_sample = max(start_sample, int((onset + half_window) * sr))
        window = audio[start_sample:end_sample]
        augmented["notes"][i] = reverify_note(note, window, sr, config)

    reference_for_scan = reference if reference is not None else {
        "notes": [
            {"onset_sec": n["onset_ref_sec"]}
            for n in augmented["notes"] if n.get("onset_ref_sec") is not None
        ]
    }
    augmented["unscored_extra_onsets"] = scan_unexpected_onsets(audio, sr, reference_for_scan, result, config)
    return augmented


# --- independent unexpected-onset scan ---------------------------------------


def _flag_unexpected_onsets(onset_times: list, known_onsets: list, config: ConstrainedVerificationConfig) -> list:
    """Pure logic given already-detected onset times -- separated out from
    scan_unexpected_onsets so it's testable without synthesizing real audio.
    """
    flagged = []
    for t in onset_times:
        gap = min((abs(t - known) for known in known_onsets), default=float("inf"))
        if gap > config.onset_gap_sec:
            flagged.append({
                "onset_sec": float(t),
                "nearest_known_onset_gap_sec": None if gap == float("inf") else float(gap),
                "flag": "possible_unscored_extra_onset",
            })
    return flagged


def scan_unexpected_onsets(
    audio: np.ndarray,
    sr: int,
    reference: dict,
    existing_result: dict,
    config: Optional[ConstrainedVerificationConfig] = None,
) -> list:
    """Plain onset-strength scan over the WHOLE audio (no pitch/harmonic
    analysis -- just "was there a percussive attack here"), catching onsets
    that don't correspond to any reference note or any onset the scorer
    already knows about. Informational only: we don't know these onsets'
    pitch confidently, so this never invents a scored note by itself.
    """
    config = config or ConstrainedVerificationConfig()
    onset_env = librosa.onset.onset_strength(y=audio, sr=sr)
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr).tolist()

    known_onsets = [n["onset_sec"] for n in reference.get("notes", [])]
    known_onsets += [
        n["onset_perf_sec"] for n in existing_result.get("notes", [])
        if n.get("onset_perf_sec") is not None
    ]
    return _flag_unexpected_onsets(onset_times, known_onsets, config)


# --- CLI ----------------------------------------------------------------------


def main(argv=None) -> int:
    import argparse
    import json

    import soundfile as sf

    parser = argparse.ArgumentParser(
        prog="python -m backend.audio_to_performance.constrained_verification",
        description=(
            "Re-verify basic-pitch's wrong_pitch/missed notes against constrained, "
            "harmonic-aware audio evidence, and scan for unscored extra onsets."
        ),
    )
    parser.add_argument("result", help="Path to scoring's result.json")
    parser.add_argument("audio", help="Path to the original recording (wav)")
    parser.add_argument("--reference", default=None, help="Path to reference.json (optional; falls back to result.json's own onset_ref_sec values).")
    parser.add_argument("--keyboard-range", type=int, nargs=2, default=None, metavar=("LOW", "HIGH"), help="Physical keyboard's MIDI pitch range, once known.")
    parser.add_argument("-o", "--output", required=True, help="Path to write the augmented result JSON.")
    args = parser.parse_args(argv)

    with open(args.result, "r", encoding="utf-8") as fh:
        result = json.load(fh)

    reference = None
    if args.reference:
        with open(args.reference, "r", encoding="utf-8") as fh:
            reference = json.load(fh)

    audio, sr = sf.read(args.audio, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    config = ConstrainedVerificationConfig(
        keyboard_range=tuple(args.keyboard_range) if args.keyboard_range else None,
    )

    augmented = reverify_result(result, audio, sr, reference=reference, config=config)

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(augmented, fh, indent=2)

    print(f"Augmented result written to {args.output}")
    print(f"unscored_extra_onsets: {len(augmented['unscored_extra_onsets'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
