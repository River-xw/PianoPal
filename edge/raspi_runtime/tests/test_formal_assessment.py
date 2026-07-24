from __future__ import annotations

import json

from edge.posture_capture import _write_result
from edge.practice_server import (
    FORMAL_DATA_DIR,
    _stop_posture_capture,
    _unavailable_motion_assessment,
)
from edge.raspi_runtime.cli import TRAINING_DATA_ROOT


def test_formal_and_training_roots_are_disjoint():
    assert FORMAL_DATA_DIR != TRAINING_DATA_ROOT
    assert FORMAL_DATA_DIR.name == "formal_assessments"
    assert TRAINING_DATA_ROOT.name == "training_collection"


def test_motion_capture_result_exposes_real_score(tmp_path):
    output = tmp_path / "motion.json"

    _write_result(
        output,
        total=10,
        normal=7,
        label_counts={"normal": 7, "wrist_collapse": 3},
        capture_hands=["L"],
        model_name="left_hand_posture_classifier",
        model_version="test",
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["available"] is True
    assert result["motion_score"] == 70.0
    assert result["hand_shape_score"] == 70.0
    assert result["capture_hands"] == ["L"]


def test_unavailable_motion_has_no_placeholder_score():
    result = _unavailable_motion_assessment("sensor missing")

    assert result["available"] is False
    assert result["motion_score"] is None
    assert result["hand_shape_score"] is None


def test_unavailable_motion_is_still_persisted_for_formal_audit(tmp_path):
    class SessionStub:
        posture_process = None
        motion_unavailable_reason = "sensor missing"
        posture_result_path = tmp_path / "motion_assessment.json"

    result = _stop_posture_capture(SessionStub())

    assert result["available"] is False
    assert SessionStub.posture_result_path.exists()
    assert json.loads(
        SessionStub.posture_result_path.read_text(encoding="utf-8")
    )["motion_score"] is None
