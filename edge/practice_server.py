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
    GET  /api/songs                  -> song library + any imported songs
    POST /api/songs/import           -> body = raw MIDI bytes, header X-Song-Title
    POST /api/session/start          -> {"song_id": "...", "speed": 1.0, "username": "..."}
    GET  /api/session/status         -> merged guide status + local phase
    POST /api/session/control        -> {"action": ..., "value": ...}
    POST /api/session/stop           -> end the session early
    GET  /result.json, /last_debug.json  -> latest grading output (whoever it was)
    GET  /api/results/<username>     -> that specific user's latest grading output

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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.audio_to_performance.keybank import WHITE_KEY_MIDIS  # noqa: E402
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

WHITE_KEY_SET = set(WHITE_KEY_MIDIS)


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
    def __init__(self, song_id: str, song_path: Path, reference: dict, speed: float, username: str):
        self.song_id = song_id
        self.song_path = song_path
        self.reference = reference
        self.speed = speed
        self.username = username
        self.phase = "starting"  # starting -> guiding -> grading -> done -> error
        self.error = None
        self.recording_path = SCRATCH_DIR / f"recording_{uuid.uuid4().hex[:8]}.wav"
        self.guide_json_path = SCRATCH_DIR / f"guide_{uuid.uuid4().hex[:8]}.json"
        self.song_end = 0.0
        self.white_keys_only = False
        self.process: subprocess.Popen | None = None


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


def _start_session(song_id: str, speed: float, username: str) -> Session:
    _safe_username(username)  # raises ValueError if missing/unusable -- fail fast, before touching anything
    song_path = _resolve_song_path(song_id)
    reference = _apply_pitch_hand_fallback(convert(str(song_path)))
    session = Session(song_id, song_path, reference, speed, username)
    session.song_end = max(
        (float(n["onset_sec"]) + float(n.get("dur_sec", 0.2) or 0.2) for n in reference["notes"]),
        default=0.0,
    )
    session.white_keys_only = _is_white_key_only(reference)

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    session.guide_json_path.write_text(json.dumps({
        "title": reference.get("title", song_id), "tempo_bpm": reference.get("tempo_bpm"),
        "notes": reference["notes"],
    }), encoding="utf-8")

    subprocess.run(["pkill", "-f", "ws2812_guide_son[g]"], capture_output=True)
    time.sleep(0.3)
    session.process = subprocess.Popen(
        [
            "python3", "-u", str(Path(__file__).resolve().parent / "ws2812_guide_song.py"),
            str(session.guide_json_path),
            "--http-port", str(GUIDE_HTTP_PORT),
            "--speed", str(speed),
            "--record-output", str(session.recording_path),
            "--record-device", RECORD_DEVICE,
        ],
        cwd=str(Path(__file__).resolve().parent),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    session.phase = "guiding"
    return session


def _finish_session(session: Session) -> None:
    session.phase = "grading"
    if session.process is not None and session.process.poll() is None:
        session.process.wait(timeout=10)

    if not session.recording_path.exists():
        session.phase = "error"
        session.error = "no recording file was produced"
        return

    cmd = [
        "python3", str(REPO_ROOT / "scripts/grade_audio_reference_constrained.py"),
        str(session.song_path), str(session.recording_path),
        "--keyboard-profile", KEYBOARD_PROFILE,
        "--mode", "reference-dtw",
        "-o", str(RESULT_JSON),
        "--debug-output", str(DEBUG_JSON),
    ]
    if session.white_keys_only:
        cmd.append("--white-keys-only")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        session.phase = "error"
        session.error = f"grading failed: {(result.stdout + result.stderr)[-2000:]}"
        return

    # Also keep a copy under this user's own name, so two people's scores
    # never overwrite each other -- RESULT_JSON/DEBUG_JSON above stay as a
    # "whoever was graded most recently" convenience mirror.
    try:
        safe_name = _safe_username(session.username)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"{safe_name}.json").write_bytes(RESULT_JSON.read_bytes())
        (RESULTS_DIR / f"{safe_name}_debug.json").write_bytes(DEBUG_JSON.read_bytes())
    except (ValueError, OSError):
        pass  # per-user copy is a nice-to-have; don't fail the session over it

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
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Song-Title")
            self.end_headers()

        def do_GET(self):
            if self.path == "/api/songs":
                self._json({"songs": _list_songs(SONG_LIBRARY_DIR, "library") + _list_songs(CUSTOM_SONGS_DIR, "custom")})
            elif self.path == "/api/session/status":
                self._status()
            elif self.path in ("/result.json", "/last_debug.json"):
                self._serve_file(SCRATCH_DIR / self.path.lstrip("/"))
            elif self.path.startswith("/api/results/"):
                raw_name = urllib.parse.unquote(self.path[len("/api/results/"):])
                try:
                    safe_name = _safe_username(raw_name)
                except ValueError:
                    self._json({"error": "invalid username"}, 400)
                    return
                self._serve_file(RESULTS_DIR / f"{safe_name}.json")
            elif self.path == "/" or self.path == "":
                self._serve_file(FRONTEND_DIST_DIR / "index.html")
            else:
                candidate = FRONTEND_DIST_DIR / self.path.lstrip("/")
                if candidate.exists() and candidate.is_file():
                    self._serve_file(candidate)
                else:
                    self._serve_file(FRONTEND_DIST_DIR / "index.html")  # SPA fallback

        def _status(self):
            with LOCK:
                session = CURRENT
            if session is None:
                self._json({"phase": "idle"})
                return
            payload = {
                "phase": session.phase, "error": session.error,
                "song_id": session.song_id, "song_end": round(session.song_end, 2),
                "speed": session.speed,
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
                        CURRENT = _start_session(
                            payload["song_id"], float(payload.get("speed", 1.0)), payload.get("username", "")
                        )
                    except Exception as exc:
                        self._json({"error": str(exc)}, 400)
                        return
                self._json({"phase": CURRENT.phase})
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
