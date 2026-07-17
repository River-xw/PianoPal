"""Dataclasses for the scoring pipeline's internal and output shapes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

Status = Literal["correct", "timing_off", "wrong_pitch", "missed", "extra"]
Timing = Literal["accurate", "rush", "drag"]
TempoTrend = Literal["accelerating", "steady", "decelerating"]

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_pitch_to_name(pitch: int) -> str:
    """60 -> 'C4' (middle C), matching score_to_reference's naming convention."""
    octave = pitch // 12 - 1
    return f"{_NOTE_NAMES[pitch % 12]}{octave}"


@dataclass
class PerformanceNote:
    pitch: int
    onset_sec: float
    dur_sec: Optional[float] = None
    velocity: Optional[int] = None


@dataclass
class NoteResult:
    ref_index: Optional[int]
    perf_index: Optional[int]
    pitch_ref: Optional[int]
    pitch_perf: Optional[int]
    name: Optional[str]
    onset_ref_sec: Optional[float]
    onset_perf_sec: Optional[float]
    offset_ms: Optional[float]
    status: Status
    timing: Optional[Timing]
    measure: Optional[int]
    hand: Optional[str]
    dur_beats: Optional[float] = None


@dataclass
class ScoringSummary:
    score: float
    sub_scores: dict
    global_tempo_ratio: Optional[float]
    tempo_trend: TempoTrend
    counts: dict


@dataclass
class ScoringResult:
    summary: ScoringSummary
    notes: list
    song_name: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "song_name": self.song_name,
            "summary": {
                "score": self.summary.score,
                "sub_scores": self.summary.sub_scores,
                "global_tempo_ratio": self.summary.global_tempo_ratio,
                "tempo_trend": self.summary.tempo_trend,
                "counts": self.summary.counts,
            },
            "notes": [
                {
                    "ref_index": n.ref_index,
                    "perf_index": n.perf_index,
                    "pitch_ref": n.pitch_ref,
                    "pitch_perf": n.pitch_perf,
                    "name": n.name,
                    "onset_ref_sec": n.onset_ref_sec,
                    "onset_perf_sec": n.onset_perf_sec,
                    "offset_ms": n.offset_ms,
                    "status": n.status,
                    "timing": n.timing,
                    "measure": n.measure,
                    "hand": n.hand,
                    "dur_beats": n.dur_beats,
                }
                for n in self.notes
            ],
        }
