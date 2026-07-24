"""Tests for audio_reference.py -- synthetic (hand-built) candidate-event
lists, no real audio needed.

Regression test for a real crash: compare_candidate_event_sequences() called
the private backend.scoring.score._summarize() without its (later-added)
required tol_ms argument, so any demo-audio-vs-student grading call raised
TypeError on every invocation. There was no prior test coverage of this
function at all, which is how it went unnoticed.
"""
from __future__ import annotations

from backend.audio_to_performance.audio_reference import compare_candidate_event_sequences


def _event(onset_sec: float, pitch: int) -> dict:
    return {
        "onset_sec": onset_sec,
        "pitch": pitch,
        "confidence": 0.9,
        "candidates": [{"pitch": pitch, "score": 0.9}],
    }


def test_identical_sequences_score_perfectly():
    events = [_event(0.0, 60), _event(0.5, 62), _event(1.0, 64)]
    result = compare_candidate_event_sequences(events, events)
    assert result["summary"]["score"] == 100.0
    assert result["summary"]["counts"] == {
        "correct": 3, "timing_off": 0, "wrong_pitch": 0, "missed": 0, "extra": 0,
    }


def test_missing_note_is_scored_not_crashed():
    demo = [_event(0.0, 60), _event(0.5, 62), _event(1.0, 64)]
    student = [_event(0.0, 60), _event(1.0, 64)]
    result = compare_candidate_event_sequences(demo, student)
    assert result["summary"]["counts"]["missed"] == 1
    assert result["summary"]["score"] < 100.0
