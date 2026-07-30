from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from edge.posture_feedback import (
    POSTURE_CUES,
    PostureFeedbackGate,
    write_posture_feedback_event,
)
from edge.practice_server import _latest_posture_feedback
from edge.practice_server import (
    _play_posture_feedback_on_pi,
    _posture_voice_output,
    _set_posture_voice_muted,
)
import edge.practice_server as practice_server_module


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_feedback_requires_a_stable_prediction_streak():
    gate = PostureFeedbackGate(
        consecutive_predictions=3,
        cooldown_seconds=10,
    )

    assert gate.observe(
        hand="L",
        label="finger_collapse",
        confidence=0.9,
        monotonic_now=1,
    ) is None
    assert gate.observe(
        hand="L",
        label="finger_collapse",
        confidence=0.9,
        monotonic_now=2,
    ) is None
    event = gate.observe(
        hand="L",
        label="finger_collapse",
        confidence=0.9,
        monotonic_now=3,
        unix_ms_now=1000,
    )

    assert event is not None
    assert event["cue_id"] == "curve_fingers"
    assert event["message"] == "Keep your fingers gently curved."
    assert event["event_id"] == "1000-L-curve_fingers"


def test_normal_or_low_confidence_prediction_resets_the_streak():
    gate = PostureFeedbackGate(consecutive_predictions=2)

    assert gate.observe(
        hand="L",
        label="wrist_arch",
        confidence=0.9,
    ) is None
    assert gate.observe(
        hand="L",
        label="normal",
        confidence=0.9,
    ) is None
    assert gate.observe(
        hand="L",
        label="wrist_arch",
        confidence=0.9,
    ) is None
    assert gate.observe(
        hand="L",
        label="wrist_arch",
        confidence=0.5,
    ) is None
    assert gate.observe(
        hand="L",
        label="wrist_arch",
        confidence=0.9,
    ) is None


def test_feedback_enforces_a_global_cooldown():
    gate = PostureFeedbackGate(
        consecutive_predictions=1,
        cooldown_seconds=10,
    )

    first = gate.observe(
        hand="L",
        label="wrist_arch",
        confidence=0.9,
        monotonic_now=20,
        unix_ms_now=1000,
    )
    blocked = gate.observe(
        hand="L",
        label="finger_collapse",
        confidence=0.9,
        monotonic_now=25,
        unix_ms_now=2000,
    )
    second = gate.observe(
        hand="L",
        label="finger_collapse",
        confidence=0.9,
        monotonic_now=30,
        unix_ms_now=3000,
    )

    assert first is not None
    assert blocked is None
    assert second is not None


def test_every_model_cue_has_a_generated_wav_asset():
    model = json.loads(
        (
            REPO_ROOT
            / "models/gesture/left_hand_posture_classifier.json"
        ).read_text(encoding="utf-8")
    )
    assert set(model["classes"]) - {"normal"} == set(POSTURE_CUES)

    for cue in POSTURE_CUES.values():
        asset = (
            REPO_ROOT
            / "frontend/viewer/public"
            / cue.audio_src.lstrip("/")
        )
        assert asset.exists()
        assert asset.stat().st_size > 4096


def test_feedback_event_is_published_and_exposed_for_learn_mode(tmp_path):
    output = tmp_path / "motion_feedback.json"
    event = {
        "schema_version": "posture_feedback_event_v1",
        "event_id": "1000-L-curve_fingers",
        "audio_src": "/audio/posture/curve-fingers.wav",
        "message": "Keep your fingers gently curved.",
    }
    write_posture_feedback_event(output, event)

    session = SimpleNamespace(
        mode="learn",
        posture_feedback_path=output,
    )
    assert _latest_posture_feedback(session) == event
    assert not output.with_name("motion_feedback.json.tmp").exists()
    assert json.loads(output.read_text(encoding="utf-8")) == event

    session.mode = "perform"
    assert _latest_posture_feedback(session) is None


def test_configured_pi_speaker_plays_each_event_once(
    tmp_path, monkeypatch
):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio_path = audio_dir / "curve-fingers.wav"
    audio_path.write_bytes(b"RIFF voice")
    commands = []

    class FakeProcess:
        def __init__(self, command, **_kwargs):
            commands.append(command)
            self.terminated = False

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self):
            self.terminated = True

    monkeypatch.setattr(
        practice_server_module,
        "POSTURE_AUDIO_DIR",
        audio_dir,
    )
    monkeypatch.setattr(
        practice_server_module,
        "PLAYBACK_DEVICE",
        "plughw:CARD=Device,DEV=0",
    )
    monkeypatch.setattr(
        practice_server_module.subprocess,
        "Popen",
        FakeProcess,
    )
    session = SimpleNamespace(
        posture_voice_muted=False,
        posture_voice_process=None,
        last_posture_voice_event_id=None,
    )
    event = {
        "event_id": "event-1",
        "audio_src": "/audio/posture/curve-fingers.wav",
    }

    assert _posture_voice_output() == "pi"
    _play_posture_feedback_on_pi(session, event)
    _play_posture_feedback_on_pi(session, event)

    assert commands == [[
        "aplay",
        "-q",
        "-D",
        "plughw:CARD=Device,DEV=0",
        str(audio_path),
    ]]

    _set_posture_voice_muted(session, True)
    assert session.posture_voice_process.terminated is True
    _set_posture_voice_muted(session, False)
    assert session.last_posture_voice_event_id is None
