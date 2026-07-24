#!/usr/bin/env python3
"""Practice-session server, meant to run ON the Raspberry Pi itself --
serves the frontend's built static files AND the session API from one
process, so a browser on any device on the LAN (the dev Mac included) is
purely a viewer: no SSH, no scp, no local Python/Node needed there at all.

This replaces scripts/session_server.py's SSH-based version once the Pi has
its own copy of backend/ (see docs/VALIDATION_GUIDE.md-adjacent setup notes)
-- ws2812_guide_song.py, the recording, and the grading step are all local
subprocess calls / file reads on the SAME machine now, which also sidesteps
the whole class of SSH job-control/backgrounding flakiness that the
SSH-based orchestrator had to work around.

    GET  /                           -> the built frontend (edge/frontend_dist/)
    GET  /api/songs?username=&mode=  -> song library + any imported songs + last_song_id (曲目記憶,
                                        this user's most recent piece in this mode, or null)
    POST /api/songs/import           -> body = raw MIDI bytes, header X-Song-Title
    POST /api/session/start          -> {"song_id", "speed", "username", "mode": "learn"|"perform",
                                          "brightness"?, "full_range"?,          # learn-mode LED config
                                          "loop_start_measure"?, "loop_end_measure"?}  # 分段循環練習 (learn only)
                                        -> {"phase": ..., "session_id": "..."}
    GET  /api/session/status         -> merged guide status + local phase (+ session_id/mode/tempo_bpm/practice_only)
    POST /api/session/control        -> {"action": ..., "value": ...}
    POST /api/session/stop           -> end the session early
    GET  /result.json, /last_debug.json  -> latest grading output (whoever it was; internal/diagnostic)
    GET  /api/history?username=&mode=&song_id=&limit=  -> {"sessions": [...], "profile": {total_sessions,
                                        recent_avg_score, most_frequent_piece}} (backend.db.sqlite)
    GET  /api/history/<session_id>   -> that session's full graded result.json
    DELETE /api/history/<session_id> -> delete a history record + its result file

Segmented-loop practice (`loop_start_measure`/`loop_end_measure` both given, learn mode only) is a
practice aid, not a graded attempt: ws2812_guide_song.py loops the LED guide between those two
measures indefinitely (until the user stops it), and the session is never scored or written to
history at all (see Session.practice_only / _finish_session).

learn (LED-guided, lenient weights) vs perform (no LED guidance, strict
weights, see MODE_SCORE_WEIGHTS) share the same scoring engine
(backend.scoring.score_performance) -- only the ScoringConfig weight preset
and whether ws2812_guide_song.py is told --no-leds differ.

Run (on the Pi):
    python3 edge/practice_server.py
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.audio_to_performance.keybank import WHITE_KEY_MIDIS  # noqa: E402
from backend.db import sqlite as db  # noqa: E402
from backend.score_to_reference.core import convert  # noqa: E402

GUIDE_HTTP_PORT = 8765
KEYBOARD_PROFILE = str(REPO_ROOT / "data/bf3738c_keybank/bf3738c_white_profile.json")
SONG_LIBRARY_DIR = REPO_ROOT / "docs/piano_music"
CUSTOM_SONGS_DIR = REPO_ROOT / "data/custom_songs"
FORMAL_DATA_DIR = REPO_ROOT / "data/formal_assessments"
FORMAL_SESSIONS_DIR = FORMAL_DATA_DIR / "sessions"
LATEST_DIR = FORMAL_DATA_DIR / "latest"
FRONTEND_DIST_DIR = Path(__file__).resolve().parent / "frontend_dist"
LATEST_RESULT_JSON = LATEST_DIR / "result.json"
LATEST_DEBUG_JSON = LATEST_DIR / "last_debug.json"
# Prefer a stable ALSA card name (for example
# ``plughw:CARD=Device,DEV=0``) supplied by the Pi's service/start command.
# Numeric card indexes can change whenever USB devices are reconnected.
RECORD_DEVICE = os.environ.get("PIANOPAL_RECORD_DEVICE", "plughw:2,0")
# When set, learn-mode metronome clicks are rendered by the Pi instead of
# the remote browser. This is intentionally opt-in because many installations
# use a browser-local speaker or do not want audible clicks in mic recordings.
PLAYBACK_DEVICE = os.environ.get("PIANOPAL_PLAYBACK_DEVICE")
GUIDE_LEAD_IN_SEC = 3.0
POSTURE_READY_TIMEOUT_SEC = float(
    os.environ.get("PIANOPAL_POSTURE_READY_TIMEOUT_SEC", "20")
)
POSTURE_READY_POLL_SEC = 0.1
POLL_INTERVAL_SEC = 1.0
CONSECUTIVE_MISSES_TO_FINISH = 4
# Both are required for a formal scored attempt. The server also waits for
# valid BLE packets from every requested hand before starting the guide/audio,
# so a missing motion dimension can never silently enter formal history.
BLE_CONFIG_PATH = REPO_ROOT / "edge/microbit_rpi_comm/raspberry/config.json"
POSTURE_MODEL_CANDIDATES = (
    # Prefer the portable export on the Pi: it avoids requiring the exact
    # scikit-learn/joblib version used on the training machine.
    REPO_ROOT / "models/gesture/left_hand_posture_classifier.json",
    REPO_ROOT / "models/gesture/left_hand_posture_classifier.joblib",
)


def _configured_posture_hands() -> tuple[str, ...]:
    raw = os.environ.get("PIANOPAL_POSTURE_HANDS", "L")
    requested = raw.upper().replace(",", " ").split()
    invalid = sorted(set(requested) - {"L", "R"})
    if invalid:
        raise ValueError(
            f"PIANOPAL_POSTURE_HANDS only accepts L/R, got {invalid}"
        )
    hands = tuple(dict.fromkeys(requested))
    if not hands:
        raise ValueError("PIANOPAL_POSTURE_HANDS must request at least one hand")
    return hands


# The shipped classifier is left-hand-only, so production defaults to L.
# Right-hand BLE/storage is already supported; after a compatible model is
# trained, launch with PIANOPAL_POSTURE_HANDS="L,R" to enable both without a
# server code change.
POSTURE_HANDS = _configured_posture_hands()

DEFAULT_MODE = "learn"
# learn (LED-guided) is lenient -- pitch/hand-shape weighted high, timing
# uniformity low; perform (no LED guidance) is a stricter, balanced blend of
# all three, per the product spec. Both share score_performance() unchanged;
# only these weight presets differ. hand_shape is real when a BLE posture rig
# and trained model are configured; otherwise it is explicitly unavailable
# and the available score weights are renormalized.
MODE_SCORE_WEIGHTS = {
    "learn": {"pitch": 0.6, "rhythm": 0.15, "timing_stability": 0.0, "hand_shape": 0.25},
    "perform": {"pitch": 0.4, "rhythm": 0.3, "timing_stability": 0.15, "hand_shape": 0.15},
}
WHITE_KEY_SET = set(WHITE_KEY_MIDIS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_white_key_only(reference: dict) -> bool:
    return all(int(n["pitch"]) in WHITE_KEY_SET for n in reference.get("notes", []))


def _safe_username(name: str) -> str:
    """A display name -> a filesystem-safe stem, so entering it can never
    escape the formal sessions directory (path traversal via '..'/'/') or collide with an
    unrelated file. Keeps letters (including CJK -- \\w is unicode-aware in
    Python 3), digits, underscore, and hyphen; everything else (spaces,
    slashes, dots, ...) collapses to '_'.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("username is required")
    safe = re.sub(r"[^\w\-]+", "_", name).strip("_")[:64]
    if not safe:
        raise ValueError("username has no valid characters")
    return safe


def _resolve_posture_model_path() -> Path | None:
    return next((path for path in POSTURE_MODEL_CANDIDATES if path.exists()), None)


def _unavailable_motion_assessment(reason: str) -> dict:
    return {
        "schema_version": "formal_motion_assessment_v1",
        "available": False,
        "hand_shape_score": None,
        "motion_score": None,
        "total_predictions": 0,
        "normal_predictions": 0,
        "label_counts": {},
        "capture_hands": list(POSTURE_HANDS),
        "model_name": None,
        "model_version": None,
        "score_formula": "normal_predictions / total_predictions * 100",
        "error": reason,
    }


def _persist_motion_assessment(session: "Session", assessment: dict) -> dict:
    session.posture_result_path.parent.mkdir(parents=True, exist_ok=True)
    session.posture_result_path.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return assessment


def _apply_pitch_hand_fallback(reference: dict, threshold: int = 60) -> dict:
    """See backend/audio_to_performance/README.md: single-track MIDI files
    put every note in one instrument, so hand tagging can't distinguish
    hands -- reassign by a pitch threshold when there's no real hand split."""
    notes = reference["notes"]
    if len({n.get("hand") for n in notes}) > 1:
        return reference
    for n in notes:
        n["hand"] = "L" if int(n["pitch"]) < threshold else "R"
    return reference


def _list_songs(directory: Path, source: str) -> list[dict]:
    songs = []
    if not directory.exists():
        return songs
    for path in sorted(directory.glob("*.mid")):
        try:
            ref = convert(str(path))
        except Exception:
            continue
        songs.append({
            "id": f"{source}:{path.stem}", "title": ref.get("title") or path.stem,
            "notes": len(ref.get("notes", [])), "white_keys_only": _is_white_key_only(ref),
            "source": source,
        })
    return songs


def _resolve_song_path(song_id: str) -> Path:
    source, _, stem = song_id.partition(":")
    base = SONG_LIBRARY_DIR if source == "library" else CUSTOM_SONGS_DIR
    path = base / f"{stem}.mid"
    if not path.exists():
        raise FileNotFoundError(song_id)
    return path


class Session:
    def __init__(
        self, session_id: str, song_id: str, song_path: Path, reference: dict,
        speed: float, username: str, mode: str, practice_only: bool = False,
    ):
        self.session_id = session_id
        self.song_id = song_id
        self.song_path = song_path
        self.reference = reference
        self.speed = speed
        self.username = username
        self.mode = mode
        self.practice_only = practice_only  # segmented-loop practice: no grading/history, see _finish_session
        self.phase = "starting"  # starting -> guiding -> grading -> done -> error
        self.error = None
        self.session_dir = FORMAL_SESSIONS_DIR / _safe_username(username) / session_id
        self.recording_path = self.session_dir / "performance.wav"
        self.guide_json_path = self.session_dir / "guide.json"
        self.posture_result_path = self.session_dir / "motion_assessment.json"
        self.posture_ready_path = self.session_dir / "motion_ready.json"
        self.posture_log_path = self.session_dir / "motion_capture.log"
        self.result_path = self.session_dir / "result.json"
        self.debug_path = self.session_dir / "audio_debug.json"
        self.song_end = 0.0
        self.tempo_bpm = None
        self.white_keys_only = False
        self.process: subprocess.Popen | None = None
        self.posture_process: subprocess.Popen | None = None
        self.motion_unavailable_reason: str | None = None


LOCK = threading.Lock()
CURRENT: Session | None = None


def _guide_status() -> dict | None:
    try:
        with urllib.request.urlopen(f"http://localhost:{GUIDE_HTTP_PORT}/status", timeout=2) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def _guide_control(action: str, value=None) -> bool:
    body = json.dumps({"action": action} if value is None else {"action": action, "value": value}).encode()
    req = urllib.request.Request(
        f"http://localhost:{GUIDE_HTTP_PORT}/control", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=2)
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _terminate_process(process: subprocess.Popen | None, timeout: float = 5.0) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _posture_failure_detail(session: Session) -> str:
    if session.posture_result_path.exists():
        try:
            result = json.loads(
                session.posture_result_path.read_text(encoding="utf-8")
            )
            if result.get("error"):
                return str(result["error"])
        except (json.JSONDecodeError, OSError):
            pass
    if session.posture_log_path.exists():
        try:
            log = session.posture_log_path.read_text(
                encoding="utf-8", errors="replace"
            ).strip()
            if log:
                return log[-800:]
        except OSError:
            pass
    return "no valid sensor packets were received"


def _start_posture_capture_and_wait(
    session: Session,
    posture_model_path: Path,
    timeout_sec: float = POSTURE_READY_TIMEOUT_SEC,
) -> None:
    """Start formal motion capture and block until every requested hand has
    streamed at least one valid packet.

    The guide, microphone, and formal DB row are deliberately not started
    before this returns. A failed/timeout BLE connection therefore cannot
    create a scored attempt with a silently missing motion dimension.
    """
    session.posture_ready_path.unlink(missing_ok=True)
    session.posture_result_path.unlink(missing_ok=True)
    posture_cmd = [
        sys.executable,
        "-u",
        str(Path(__file__).resolve().parent / "posture_capture.py"),
        "--ble-config",
        str(BLE_CONFIG_PATH),
        "--posture-model",
        str(posture_model_path),
        "--hands",
        *POSTURE_HANDS,
        "--start-delay-sec",
        str(GUIDE_LEAD_IN_SEC),
        "--ready-output",
        str(session.posture_ready_path),
        "-o",
        str(session.posture_result_path),
    ]
    with session.posture_log_path.open("w", encoding="utf-8") as posture_log:
        session.posture_process = subprocess.Popen(
            posture_cmd,
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=posture_log,
            stderr=subprocess.STDOUT,
        )

    deadline = time.monotonic() + max(0.0, timeout_sec)
    while time.monotonic() < deadline:
        if session.posture_ready_path.exists():
            try:
                ready = json.loads(
                    session.posture_ready_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                time.sleep(POSTURE_READY_POLL_SEC)
                continue
            ready_hands = set(ready.get("capture_hands", []))
            if ready.get("ready") is True and ready_hands.issuperset(
                POSTURE_HANDS
            ):
                return
        if (
            session.posture_process is not None
            and session.posture_process.poll() is not None
        ):
            detail = _posture_failure_detail(session)
            raise RuntimeError(f"motion sensor connection failed: {detail}")
        time.sleep(POSTURE_READY_POLL_SEC)

    _terminate_process(session.posture_process)
    detail = _posture_failure_detail(session)
    raise TimeoutError(
        "motion sensors were not ready within "
        f"{timeout_sec:.0f}s for hands {list(POSTURE_HANDS)}: {detail}"
    )


def _start_session(
    song_id: str, speed: float, username: str, mode: str,
    brightness: float = 0.25, full_range: bool = False,
    loop_start_measure: int | None = None, loop_end_measure: int | None = None,
) -> Session:
    safe_name = _safe_username(username)  # raises ValueError if missing/unusable -- fail fast, before touching anything
    if mode not in MODE_SCORE_WEIGHTS:
        raise ValueError(f"unknown mode {mode!r}, expected one of {sorted(MODE_SCORE_WEIGHTS)}")
    # 分段循環練習 only makes sense for the LED-guided learn mode -- perform
    # mode has no LED guidance to loop, and its whole point is one clean take.
    practice_only = mode == "learn" and loop_start_measure is not None and loop_end_measure is not None
    song_path = _resolve_song_path(song_id)
    reference = _apply_pitch_hand_fallback(convert(str(song_path)))
    session_id = uuid.uuid4().hex[:12]
    session = Session(session_id, song_id, song_path, reference, speed, username, mode, practice_only)
    session.song_end = max(
        (float(n["onset_sec"]) + float(n.get("dur_sec", 0.2) or 0.2) for n in reference["notes"]),
        default=0.0,
    )
    session.white_keys_only = _is_white_key_only(reference)
    session.tempo_bpm = reference.get("tempo_bpm")

    session.session_dir.mkdir(parents=True, exist_ok=True)
    session.guide_json_path.write_text(json.dumps({
        "title": reference.get("title", song_id), "tempo_bpm": reference.get("tempo_bpm"),
        "notes": reference["notes"],
    }), encoding="utf-8")

    subprocess.run(["pkill", "-f", "ws2812_guide_son[g]"], capture_output=True)
    subprocess.run(["pkill", "-f", "posture_captur[e]"], capture_output=True)
    time.sleep(0.5)

    # Formal scored attempts require motion streaming to be ready before the
    # guide countdown and microphone start. Segmented-loop practice is not
    # formally scored and intentionally skips this gate.
    posture_model_path = _resolve_posture_model_path()
    if practice_only:
        session.motion_unavailable_reason = (
            "segmented practice is not formally scored"
        )
    elif not BLE_CONFIG_PATH.exists():
        raise RuntimeError(
            f"BLE configuration unavailable: {BLE_CONFIG_PATH}"
        )
    elif posture_model_path is None:
        raise RuntimeError("trained motion model is unavailable")
    else:
        _start_posture_capture_and_wait(session, posture_model_path)

    now = _now_iso()
    db.create_user(safe_name, username, now)
    db.create_piece(song_id, reference.get("title", song_id), None, None, now)
    if not practice_only:
        db.create_practice_session(
            session_id, safe_name, song_id, now, mode=mode
        )

    guide_cmd = [
        sys.executable, "-u", str(Path(__file__).resolve().parent / "ws2812_guide_song.py"),
        str(session.guide_json_path),
        "--http-port", str(GUIDE_HTTP_PORT),
        "--speed", str(speed),
        "--lead-in-sec", str(GUIDE_LEAD_IN_SEC),
        "--record-output", str(session.recording_path),
        "--record-device", RECORD_DEVICE,
    ]
    if mode == "perform":
        guide_cmd.append("--no-leds")  # 演奏模式: timing/recording only, no visual guidance
    else:
        guide_cmd += ["--brightness", str(brightness)]
        if PLAYBACK_DEVICE:
            guide_cmd += ["--metronome-device", PLAYBACK_DEVICE]
        if full_range:
            guide_cmd.append("--full-range")
        if practice_only:
            guide_cmd += [
                "--loop-start-measure", str(loop_start_measure),
                "--loop-end-measure", str(loop_end_measure),
            ]
    session.process = subprocess.Popen(
        guide_cmd,
        cwd=str(Path(__file__).resolve().parent),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    session.phase = "guiding"
    return session


def _stop_posture_capture(session: Session) -> dict:
    """Terminate this session's posture_capture.py (if one was started) and
    return its formal aggregate result. Missing hardware/model/predictions are
    explicit unavailable results, never a placeholder score."""
    if session.posture_process is None:
        return _persist_motion_assessment(
            session,
            _unavailable_motion_assessment(
                session.motion_unavailable_reason or "motion recognition was not started"
            ),
        )

    if session.posture_process.poll() is None:
        session.posture_process.terminate()
        try:
            session.posture_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            session.posture_process.kill()
            session.posture_process.wait()

    if not session.posture_result_path.exists():
        return _persist_motion_assessment(
            session,
            _unavailable_motion_assessment("motion recognition produced no result"),
        )
    try:
        posture_result = json.loads(session.posture_result_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _persist_motion_assessment(
            session,
            _unavailable_motion_assessment("motion recognition result was unreadable"),
        )
    score = posture_result.get("motion_score", posture_result.get("hand_shape_score"))
    posture_result["motion_score"] = float(score) if score is not None else None
    posture_result["hand_shape_score"] = posture_result["motion_score"]
    posture_result["available"] = posture_result["motion_score"] is not None
    return _persist_motion_assessment(session, posture_result)


def _finish_session(session: Session) -> None:
    if session.practice_only:
        _stop_posture_capture(session)
        # Segmented-loop practice has no single well-defined "performance" to
        # grade against the full-song reference -- it's a practice aid, not a
        # graded attempt, so it never touches grading/history at all.
        session.phase = "done"
        return

    session.phase = "grading"
    motion_assessment = _stop_posture_capture(session)
    if session.process is not None and session.process.poll() is None:
        session.process.wait(timeout=10)

    if not session.recording_path.exists():
        session.phase = "error"
        session.error = "no recording file was produced"
        db.finish_practice_session(session.session_id, _now_iso(), None, None, status="error")
        return

    weights = MODE_SCORE_WEIGHTS[session.mode]
    cmd = [
        sys.executable, str(REPO_ROOT / "scripts/grade_audio_reference_constrained.py"),
        str(session.song_path), str(session.recording_path),
        "--keyboard-profile", KEYBOARD_PROFILE,
        "--mode", "reference-dtw",
        "--score-weight-pitch", str(weights["pitch"]),
        "--score-weight-rhythm", str(weights["rhythm"]),
        "--score-weight-timing-stability", str(weights["timing_stability"]),
        "--score-weight-hand-shape", str(weights["hand_shape"]),
        # Always on: this keyboard's profile only ever covers white keys, and
        # grade_audio_reference_constrained.py now excludes any resulting
        # unsupported-pitch (e.g. black-key) reference note entirely from
        # scoring rather than counting it as missed -- so this is safe for
        # both all-white and mixed-pitch songs, not just gated on
        # session.white_keys_only (which stays around purely as the "含黑鍵"
        # display hint in the song list).
        "--white-keys-only",
        "-o", str(session.result_path),
        "--debug-output", str(session.debug_path),
    ]
    if motion_assessment["motion_score"] is not None:
        cmd += ["--hand-shape-score", str(motion_assessment["motion_score"])]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        session.phase = "error"
        session.error = f"grading failed: {(result.stdout + result.stderr)[-2000:]}"
        db.finish_practice_session(session.session_id, _now_iso(), None, None, status="error")
        return

    result_payload = json.loads(session.result_path.read_text(encoding="utf-8"))
    result_payload["summary"]["motion_assessment"] = motion_assessment
    result_payload.setdefault("pipeline", {})["motion_recognition"] = {
        "model_name": motion_assessment.get("model_name"),
        "model_version": motion_assessment.get("model_version"),
        "capture_hands": motion_assessment.get("capture_hands", []),
        "available": motion_assessment["available"],
    }
    result_payload["session"] = {
        "id": session.session_id,
        "mode": session.mode,
        "data_kind": "formal_assessment",
    }
    session.result_path.write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_RESULT_JSON.write_bytes(session.result_path.read_bytes())
    if session.debug_path.exists():
        LATEST_DEBUG_JSON.write_bytes(session.debug_path.read_bytes())

    now = _now_iso()
    for artifact_type, path in (
        ("performance_audio", session.recording_path),
        ("motion_assessment", session.posture_result_path),
        ("audio_scoring_debug", session.debug_path),
        ("guide_reference", session.guide_json_path),
        ("result_json", session.result_path),
    ):
        if path.exists():
            db.add_artifact(
                uuid.uuid4().hex[:12],
                session.session_id,
                artifact_type,
                str(path),
                now,
            )
    db.finish_practice_session(session.session_id, now, result_payload["summary"]["score"], result_payload["summary"])

    session.phase = "done"


def _monitor_loop() -> None:
    misses = 0
    while True:
        time.sleep(POLL_INTERVAL_SEC)
        with LOCK:
            session = CURRENT
        if session is None or session.phase != "guiding":
            misses = 0
            continue
        if session.process is not None and session.process.poll() is not None:
            # the guide process exited (song finished or was quit) --
            # recorder.stop() already ran inside it, file is complete
            _finish_session(session)
            misses = 0
            continue
        status = _guide_status()
        if status is not None:
            misses = 0
            continue
        misses += 1
        if misses >= CONSECUTIVE_MISSES_TO_FINISH:
            misses = 0
            _finish_session(session)


def _make_handler():
    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_file(self, path: Path):
            if not path.exists() or not path.is_file():
                self._json({"error": "not found"}, 404)
                return
            body = path.read_bytes()
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Song-Title")
            self.end_headers()

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/api/songs":
                self._songs(urllib.parse.parse_qs(parsed.query))
            elif parsed.path == "/api/session/status":
                self._status()
            elif parsed.path in ("/result.json", "/last_debug.json"):
                path = LATEST_RESULT_JSON if parsed.path == "/result.json" else LATEST_DEBUG_JSON
                self._serve_file(path)
            elif parsed.path == "/api/history":
                self._history_list(urllib.parse.parse_qs(parsed.query))
            elif parsed.path.startswith("/api/history/"):
                self._history_detail(parsed.path[len("/api/history/"):])
            elif parsed.path.startswith("/api/songs/") and parsed.path.endswith("/reference"):
                song_id = urllib.parse.unquote(parsed.path[len("/api/songs/"):-len("/reference")])
                self._song_reference(song_id)
            elif parsed.path == "/" or parsed.path == "":
                self._serve_file(FRONTEND_DIST_DIR / "index.html")
            else:
                candidate = FRONTEND_DIST_DIR / parsed.path.lstrip("/")
                if candidate.exists() and candidate.is_file():
                    self._serve_file(candidate)
                else:
                    self._serve_file(FRONTEND_DIST_DIR / "index.html")  # SPA fallback

        def _songs(self, query: dict):
            songs = _list_songs(SONG_LIBRARY_DIR, "library") + _list_songs(CUSTOM_SONGS_DIR, "custom")
            username = (query.get("username") or [""])[0]
            mode = (query.get("mode") or [None])[0]
            last_song_id = None
            if username:
                try:
                    safe_name = _safe_username(username)
                except ValueError:
                    safe_name = None
                if safe_name is not None:
                    recent = db.get_recent_sessions(safe_name, limit=1, mode=mode)
                    last_song_id = recent[0]["piece_id"] if recent else None
            self._json({"songs": songs, "last_song_id": last_song_id})

        def _song_reference(self, song_id: str):
            """A song's reference notes (not a performance/result) -- used by
            the frontend's 分段循環練習 measure picker to show notation before
            a session starts, so the user can see what they're selecting."""
            try:
                song_path = _resolve_song_path(song_id)
            except FileNotFoundError:
                self._json({"error": "not found"}, 404)
                return
            try:
                reference = _apply_pitch_hand_fallback(convert(str(song_path)))
            except Exception as exc:
                self._json({"error": str(exc)}, 400)
                return
            notes = [
                {
                    "measure": n.get("measure"), "hand": n.get("hand"),
                    "pitch_ref": n["pitch"], "dur_beats": n.get("dur_beats"),
                    "onset_ref_sec": n["onset_sec"],
                }
                for n in reference["notes"]
            ]
            measure_count = max((n["measure"] or 1 for n in notes), default=0)
            self._json({"notes": notes, "measure_count": measure_count})

        def _history_list(self, query: dict):
            username = (query.get("username") or [""])[0]
            try:
                safe_name = _safe_username(username)
            except ValueError:
                self._json({"error": "username is required"}, 400)
                return
            mode = (query.get("mode") or [None])[0]
            song_id = (query.get("song_id") or [None])[0]
            limit = int((query.get("limit") or ["20"])[0])
            sessions = db.get_recent_sessions(safe_name, limit=limit, mode=mode, piece_id=song_id)
            for s in sessions:
                s["summary"] = json.loads(s["summary_json"]) if s.get("summary_json") else None
                del s["summary_json"]
            profile = {
                "total_sessions": db.count_sessions(safe_name),
                "recent_avg_score": db.recent_average_score(safe_name),
                "most_frequent_piece": db.most_frequent_piece(safe_name),
            }
            self._json({"sessions": sessions, "profile": profile})

        def _history_detail(self, session_id: str):
            row = db.get_session(session_id)
            if row is None:
                self._json({"error": "not found"}, 404)
                return
            artifacts = db.get_session_artifacts(session_id)
            result_artifact = next((a for a in artifacts if a["artifact_type"] == "result_json"), None)
            if result_artifact is None:
                self._json({"error": "no result recorded for this session"}, 404)
                return
            self._serve_file(Path(result_artifact["uri"]))

        def _history_delete(self, session_id: str):
            row = db.get_session(session_id)
            if row is None:
                self._json({"error": "not found"}, 404)
                return
            for artifact in db.get_session_artifacts(session_id):
                if artifact["artifact_type"] in {
                    "performance_audio",
                    "motion_assessment",
                    "audio_scoring_debug",
                    "guide_reference",
                    "result_json",
                }:
                    Path(artifact["uri"]).unlink(missing_ok=True)
            session_dir = FORMAL_SESSIONS_DIR / _safe_username(row["user_id"]) / session_id
            if session_dir.exists():
                try:
                    session_dir.rmdir()
                    session_dir.parent.rmdir()
                except OSError:
                    pass
            db.delete_session(session_id)
            self._json({"ok": True})

        def do_DELETE(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path.startswith("/api/history/"):
                self._history_delete(parsed.path[len("/api/history/"):])
                return
            self._json({"error": "not found"}, 404)

        def _status(self):
            with LOCK:
                session = CURRENT
            if session is None:
                self._json({"phase": "idle"})
                return
            payload = {
                "phase": session.phase, "error": session.error,
                "session_id": session.session_id, "mode": session.mode,
                "song_id": session.song_id, "song_end": round(session.song_end, 2),
                "speed": session.speed, "tempo_bpm": session.tempo_bpm,
                "practice_only": session.practice_only,
                "metronome_output": (
                    "pi" if session.mode == "learn" and PLAYBACK_DEVICE else "browser"
                ),
                "metronome_muted": False,
                "capture": {
                    "audio_recording": False,
                    "motion_recognition": (
                        "unavailable"
                        if session.posture_process is None
                        else ("running" if session.posture_process.poll() is None else "finished")
                    ),
                    "motion_unavailable_reason": session.motion_unavailable_reason,
                },
            }
            if session.phase == "guiding":
                status = _guide_status()
                if status:
                    payload["song_pos"] = status.get("song_pos")
                    payload["speed"] = status.get("speed", session.speed)
                    payload["paused"] = status.get("paused")
                    payload["metronome_output"] = status.get(
                        "metronome_output", payload["metronome_output"]
                    )
                    payload["metronome_muted"] = bool(
                        status.get("metronome_muted", False)
                    )
                    payload["capture"]["audio_recording"] = bool(status.get("recording"))
            self._json(payload)

        def do_POST(self):
            global CURRENT
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""

            if self.path == "/api/songs/import":
                title = self.headers.get("X-Song-Title", "imported")
                CUSTOM_SONGS_DIR.mkdir(parents=True, exist_ok=True)
                song_id = f"{uuid.uuid4().hex[:8]}_{title}".replace(" ", "_")
                dest = CUSTOM_SONGS_DIR / f"{song_id}.mid"
                dest.write_bytes(raw)
                try:
                    convert(str(dest))
                except Exception as exc:
                    dest.unlink(missing_ok=True)
                    self._json({"error": f"could not parse MIDI: {exc}"}, 400)
                    return
                self._json({"id": f"custom:{song_id}"})
                return

            if self.path == "/api/session/start":
                payload = json.loads(raw or b"{}")
                with LOCK:
                    if CURRENT is not None and CURRENT.phase in ("starting", "guiding", "grading"):
                        self._json({"error": "a session is already running"}, 409)
                        return
                    try:
                        loop_start = payload.get("loop_start_measure")
                        loop_end = payload.get("loop_end_measure")
                        CURRENT = _start_session(
                            payload["song_id"], float(payload.get("speed", 1.0)),
                            payload.get("username", ""), payload.get("mode", DEFAULT_MODE),
                            brightness=float(payload.get("brightness", 0.25)),
                            full_range=bool(payload.get("full_range", False)),
                            loop_start_measure=int(loop_start) if loop_start is not None else None,
                            loop_end_measure=int(loop_end) if loop_end is not None else None,
                        )
                    except Exception as exc:
                        self._json({"error": str(exc)}, 400)
                        return
                self._json({"phase": CURRENT.phase, "session_id": CURRENT.session_id})
                return

            if self.path == "/api/session/control":
                payload = json.loads(raw or b"{}")
                ok = _guide_control(payload.get("action"), payload.get("value"))
                self._json({"ok": ok})
                return

            if self.path == "/api/session/stop":
                with LOCK:
                    session = CURRENT
                if session is not None and session.phase == "guiding":
                    _guide_control("quit")
                self._json({"ok": True})
                return

            self._json({"error": "not found"}, 404)

        def log_message(self, fmt, *args):
            pass

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Practice-session server, meant to run on the Pi.")
    parser.add_argument("--port", type=int, default=8900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db.init_db()
    threading.Thread(target=_monitor_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), _make_handler())
    print(f"practice server on :{args.port}  (frontend + /api/songs, /api/session/*)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
