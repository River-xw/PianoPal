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
SCRATCH_DIR = REPO_ROOT / "data/session_scratch"
FRONTEND_DIST_DIR = Path(__file__).resolve().parent / "frontend_dist"
RESULT_JSON = SCRATCH_DIR / "result.json"
DEBUG_JSON = SCRATCH_DIR / "last_debug.json"
RESULTS_DIR = SCRATCH_DIR / "results"
RECORD_DEVICE = "plughw:2,0"
POLL_INTERVAL_SEC = 1.0
CONSECUTIVE_MISSES_TO_FINISH = 4
# Both existence-checked at session start, not required -- a machine with no
# IMU rig set up (no config.json, only the committed .example.json) just
# never starts edge/posture_capture.py at all and keeps using
# HAND_SHAPE_PLACEHOLDER_SCORE, same as before this was wired in.
BLE_CONFIG_PATH = REPO_ROOT / "edge/microbit_rpi_comm/raspberry/config.json"
POSTURE_MODEL_PATH = REPO_ROOT / "models/gesture/left_hand_posture_classifier.joblib"

DEFAULT_MODE = "learn"
# learn (LED-guided) is lenient -- pitch/hand-shape weighted high, timing
# uniformity low; perform (no LED guidance) is a stricter, balanced blend of
# all three, per the product spec. Both share score_performance() unchanged;
# only these weight presets differ. hand_shape is real when a BLE posture rig
# is configured (see edge/posture_capture.py -- run in both modes, since it's
# an orthogonal concern from the LED *visual* guidance that differs per
# mode), and falls back to HAND_SHAPE_PLACEHOLDER_SCORE otherwise.
MODE_SCORE_WEIGHTS = {
    "learn": {"pitch": 0.6, "rhythm": 0.15, "timing_stability": 0.0, "hand_shape": 0.25},
    "perform": {"pitch": 0.4, "rhythm": 0.3, "timing_stability": 0.15, "hand_shape": 0.15},
}
HAND_SHAPE_PLACEHOLDER_SCORE = 100.0

WHITE_KEY_SET = set(WHITE_KEY_MIDIS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_white_key_only(reference: dict) -> bool:
    return all(int(n["pitch"]) in WHITE_KEY_SET for n in reference.get("notes", []))


def _safe_username(name: str) -> str:
    """A display name -> a filesystem-safe stem, so entering it can never
    escape RESULTS_DIR (path traversal via '..'/'/') or collide with an
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
        self.recording_path = SCRATCH_DIR / f"recording_{uuid.uuid4().hex[:8]}.wav"
        self.guide_json_path = SCRATCH_DIR / f"guide_{uuid.uuid4().hex[:8]}.json"
        self.song_end = 0.0
        self.tempo_bpm = None
        self.white_keys_only = False
        self.process: subprocess.Popen | None = None
        self.posture_process: subprocess.Popen | None = None
        self.posture_result_path = SCRATCH_DIR / f"posture_{uuid.uuid4().hex[:8]}.json"


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

    now = _now_iso()
    db.create_user(safe_name, username, now)
    db.create_piece(song_id, reference.get("title", song_id), None, None, now)
    if not practice_only:
        db.create_practice_session(session_id, safe_name, song_id, now, mode=mode)

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    session.guide_json_path.write_text(json.dumps({
        "title": reference.get("title", song_id), "tempo_bpm": reference.get("tempo_bpm"),
        "notes": reference["notes"],
    }), encoding="utf-8")

    subprocess.run(["pkill", "-f", "ws2812_guide_son[g]"], capture_output=True)
    time.sleep(0.3)
    guide_cmd = [
        "python3", "-u", str(Path(__file__).resolve().parent / "ws2812_guide_song.py"),
        str(session.guide_json_path),
        "--http-port", str(GUIDE_HTTP_PORT),
        "--speed", str(speed),
        "--record-output", str(session.recording_path),
        "--record-device", RECORD_DEVICE,
    ]
    if mode == "perform":
        guide_cmd.append("--no-leds")  # 演奏模式: timing/recording only, no visual guidance
    else:
        guide_cmd += ["--brightness", str(brightness)]
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

    subprocess.run(["pkill", "-f", "posture_captur[e]"], capture_output=True)
    if BLE_CONFIG_PATH.exists():
        posture_cmd = [
            "python3", "-u", str(Path(__file__).resolve().parent / "posture_capture.py"),
            "--ble-config", str(BLE_CONFIG_PATH),
            "-o", str(session.posture_result_path),
        ]
        if POSTURE_MODEL_PATH.exists():
            posture_cmd += ["--posture-model", str(POSTURE_MODEL_PATH)]
        session.posture_process = subprocess.Popen(
            posture_cmd,
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    # else: no IMU rig configured on this machine -- session.posture_process
    # stays None, _finish_session() falls back to HAND_SHAPE_PLACEHOLDER_SCORE.

    session.phase = "guiding"
    return session


def _stop_posture_capture(session: Session) -> float:
    """Terminate this session's posture_capture.py (if one was started) and
    return its computed hand_shape_score, or HAND_SHAPE_PLACEHOLDER_SCORE if
    none was running, it didn't produce a usable result, or it never
    collected any predictions (e.g. BLE never connected)."""
    if session.posture_process is None:
        return HAND_SHAPE_PLACEHOLDER_SCORE

    if session.posture_process.poll() is None:
        session.posture_process.terminate()
        try:
            session.posture_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            session.posture_process.kill()
            session.posture_process.wait()

    if not session.posture_result_path.exists():
        return HAND_SHAPE_PLACEHOLDER_SCORE
    try:
        posture_result = json.loads(session.posture_result_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return HAND_SHAPE_PLACEHOLDER_SCORE
    score = posture_result.get("hand_shape_score")
    return float(score) if score is not None else HAND_SHAPE_PLACEHOLDER_SCORE


def _finish_session(session: Session) -> None:
    hand_shape_score = _stop_posture_capture(session)

    if session.practice_only:
        # Segmented-loop practice has no single well-defined "performance" to
        # grade against the full-song reference -- it's a practice aid, not a
        # graded attempt, so it never touches grading/history at all.
        session.phase = "done"
        return

    session.phase = "grading"
    if session.process is not None and session.process.poll() is None:
        session.process.wait(timeout=10)

    if not session.recording_path.exists():
        session.phase = "error"
        session.error = "no recording file was produced"
        db.finish_practice_session(session.session_id, _now_iso(), None, None, status="error")
        return

    weights = MODE_SCORE_WEIGHTS[session.mode]
    cmd = [
        "python3", str(REPO_ROOT / "scripts/grade_audio_reference_constrained.py"),
        str(session.song_path), str(session.recording_path),
        "--keyboard-profile", KEYBOARD_PROFILE,
        "--mode", "reference-dtw",
        "--score-weight-pitch", str(weights["pitch"]),
        "--score-weight-rhythm", str(weights["rhythm"]),
        "--score-weight-timing-stability", str(weights["timing_stability"]),
        "--score-weight-hand-shape", str(weights["hand_shape"]),
        "--hand-shape-score", str(hand_shape_score),
        "-o", str(RESULT_JSON),
        "--debug-output", str(DEBUG_JSON),
    ]
    if session.white_keys_only:
        cmd.append("--white-keys-only")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        session.phase = "error"
        session.error = f"grading failed: {(result.stdout + result.stderr)[-2000:]}"
        db.finish_practice_session(session.session_id, _now_iso(), None, None, status="error")
        return

    # Keep a PERMANENT, per-session copy for history (RESULT_JSON/DEBUG_JSON
    # above get overwritten by the next session regardless of user -- fine
    # as an internal "whoever was graded most recently" diagnostic, but
    # useless for history) -- registered as a DB artifact so GET
    # /api/history/<session_id> can find it later.
    safe_name = _safe_username(session.username)
    session_result_path = RESULTS_DIR / safe_name / f"{session.session_id}.json"
    session_result_path.parent.mkdir(parents=True, exist_ok=True)
    session_result_path.write_bytes(RESULT_JSON.read_bytes())

    result_payload = json.loads(RESULT_JSON.read_text(encoding="utf-8"))
    now = _now_iso()
    db.add_artifact(uuid.uuid4().hex[:12], session.session_id, "result_json", str(session_result_path), now)
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
                self._serve_file(SCRATCH_DIR / parsed.path.lstrip("/"))
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
                if artifact["artifact_type"] == "result_json":
                    Path(artifact["uri"]).unlink(missing_ok=True)
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
            }
            if session.phase == "guiding":
                status = _guide_status()
                if status:
                    payload["song_pos"] = status.get("song_pos")
                    payload["speed"] = status.get("speed", session.speed)
                    payload["paused"] = status.get("paused")
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
