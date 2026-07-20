"""Per-key spectral fingerprints, learned directly from a recording of THIS
specific instrument -- for when an instrument's timbre doesn't match what
basic-pitch was trained on (a real acoustic piano).

Motivation, and an important correction: an early test recording
(twinkle_take1.m4a) was believed to be the project's actual 37-key toy
keyboard and scored 12/100 (1 of 69 notes correct) on basic-pitch. Direct
spectral analysis showed a striking pattern -- low-register notes had
almost no energy at their true fundamental frequency, with the dominant
peak sitting on a harmonic instead (2x-5x the fundamental). BUT that
recording was later found to be a phone recording of a COMPUTER playing
the reference MIDI through its own speakers, not the physical keyboard --
so the missing-fundamental finding is real (it's a genuine property of
*that* audio) but is NOT confirmed to describe the actual toy keyboard's
timbre. The real instrument's response is still unclarified pending a
proper recording of it. See data/computer_midi_playback_fingerprints.json
and data/experiments/computer_midi_playback/ for that (mislabeled but
kept, as a proof-of-concept dataset) recording and its results.

The mechanism this module builds is still exactly what's needed once a
real recording of the actual keyboard exists: an instrument's odd acoustic
response, if FIXED (same keys, same electronics every time) rather than
random noise, doesn't need to be modeled or understood theoretically -- it
can be learned empirically. Record the instrument playing known pieces,
extract each key's actual observed spectral shape as a template, and match
future recordings against those templates instead of (or alongside)
basic-pitch's generic, real-piano-trained judgment.

Honest limitation: templates can only be built for keys that actually
appear in the training recording(s) provided. A single short piece will
cover a handful of the keys, not all 37 -- more recordings (ideally a
chromatic scale, or several pieces spanning the full range) improve
coverage. See constrained_verification.score_candidate for how a missing
template for a candidate falls back to the generic harmonic-aware scoring.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import librosa
import numpy as np

from .constrained_verification import CQTFrame, ConstrainedVerificationConfig, _compute_cqt_frame

DEFAULT_EVENT_WINDOW_SEC = 0.06     # reference notes closer than this = one chord event
DEFAULT_ONSET_MATCH_TOL_SEC = 1.5   # generous -- a live take's tempo isn't locked to the reference
DEFAULT_SEGMENT_DUR_SEC = 0.30


@dataclass
class LabeledSegment:
    pitch: int
    onset_sec: float          # the segment's position in the RECORDING, not the reference
    cqt_frame: CQTFrame


def _group_into_single_note_events(notes: list, window_sec: float) -> list:
    """Reference notes within `window_sec` of each other are one chord event.
    Only events with EXACTLY one note are usable as clean single-pitch
    template material -- a chord's audio can't be attributed to one pitch.
    """
    ordered = sorted(notes, key=lambda n: n["onset_sec"])
    events: list = []
    for note in ordered:
        if events and note["onset_sec"] - events[-1][0]["onset_sec"] < window_sec:
            events[-1].append(note)
        else:
            events.append([note])
    return [event for event in events if len(event) == 1]


def _detect_onsets_sec(audio: np.ndarray, sr: int) -> np.ndarray:
    onset_env = librosa.onset.onset_strength(y=audio, sr=sr)
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, backtrack=True)
    return librosa.frames_to_time(onset_frames, sr=sr)


def _align_events_to_onsets(single_note_events: list, onset_times: np.ndarray, tol_sec: float) -> list:
    """Sequential nearest-onset alignment: the piece is monotonic (no
    reordering), so a simple greedy nearest-available-onset match per event,
    in reference order, is sufficient -- this is audio ONSET detection (an
    amplitude-attack signal), not pitch detection, so it stays reliable even
    on an unfamiliar timbre; that's what makes it safe to bootstrap
    pitch templates from.

    Returns (pitch, onset_time_in_recording) pairs, one per successfully
    aligned event -- events with no sufficiently close onset are dropped
    rather than guessed.
    """
    used: set = set()
    aligned = []
    for event in single_note_events:
        ref_onset = event[0]["onset_sec"]
        best_idx, best_dist = None, None
        for i, t in enumerate(onset_times):
            if i in used:
                continue
            dist = abs(t - ref_onset)
            if best_dist is None or dist < best_dist:
                best_idx, best_dist = i, dist
        if best_idx is not None and best_dist <= tol_sec:
            used.add(best_idx)
            aligned.append((event[0]["pitch"], float(onset_times[best_idx])))
    return aligned


def extract_labeled_segments(
    reference: dict,
    audio: np.ndarray,
    sr: int,
    config: Optional[ConstrainedVerificationConfig] = None,
    event_window_sec: float = DEFAULT_EVENT_WINDOW_SEC,
    onset_match_tol_sec: float = DEFAULT_ONSET_MATCH_TOL_SEC,
    segment_dur_sec: float = DEFAULT_SEGMENT_DUR_SEC,
) -> list:
    """A recording of `reference` played on the target instrument -> a list
    of LabeledSegment, one per single-note reference event that could be
    matched to a real onset in the recording. This is the raw material
    build_templates() aggregates into per-pitch fingerprints.
    """
    config = config or ConstrainedVerificationConfig()
    single_note_events = _group_into_single_note_events(reference["notes"], event_window_sec)
    onset_times = _detect_onsets_sec(audio, sr)
    aligned = _align_events_to_onsets(single_note_events, onset_times, onset_match_tol_sec)

    win_samples = int(segment_dur_sec * sr)
    segments = []
    for pitch, onset_sec in aligned:
        start = int(onset_sec * sr)
        window = audio[start:start + win_samples]
        frame = _compute_cqt_frame(window, sr, config)
        segments.append(LabeledSegment(pitch=pitch, onset_sec=onset_sec, cqt_frame=frame))
    return segments


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 1e-12 else vec


def build_templates(segments: list) -> dict:
    """Average (normalized) CQT magnitude vectors per pitch across all
    occurrences of that pitch, into one L2-normalized template per pitch.
    More occurrences -> a more robust template; a pitch seen only once
    still gets a template, just a less-averaged one.
    """
    by_pitch: dict = {}
    for seg in segments:
        by_pitch.setdefault(seg.pitch, []).append(_normalize(seg.cqt_frame.magnitudes))

    templates = {}
    for pitch, vectors in by_pitch.items():
        templates[pitch] = _normalize(np.mean(vectors, axis=0))
    return templates


def save_templates(templates: dict, path: str, config: Optional[ConstrainedVerificationConfig] = None, instrument_id: str = "unknown") -> None:
    config = config or ConstrainedVerificationConfig()
    payload = {
        "instrument_id": instrument_id,
        "cqt_fmin_hz": config.cqt_fmin_hz,
        "cqt_bins_per_octave": config.cqt_bins_per_octave,
        "cqt_n_octaves": config.cqt_n_octaves,
        "templates": {str(pitch): vec.tolist() for pitch, vec in templates.items()},
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def load_templates(path: str) -> dict:
    """Returns {pitch (int): normalized numpy vector}. Raises ValueError if
    the file's CQT layout doesn't match what ConstrainedVerificationConfig's
    defaults would produce -- comparing templates built with a different
    fmin/bins_per_octave/n_octaves to a live CQTFrame is meaningless
    (different bin layouts), so this fails loudly instead of silently
    misclassifying everything.
    """
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    default_config = ConstrainedVerificationConfig()
    for field in ("cqt_fmin_hz", "cqt_bins_per_octave", "cqt_n_octaves"):
        if payload.get(field) != getattr(default_config, field):
            raise ValueError(
                f"Template file's {field}={payload.get(field)} does not match "
                f"ConstrainedVerificationConfig's default {getattr(default_config, field)} -- "
                "rebuild the templates with matching CQT settings before using them."
            )

    return {int(pitch): np.array(vec, dtype=float) for pitch, vec in payload["templates"].items()}
