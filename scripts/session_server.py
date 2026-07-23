#!/usr/bin/env python3
"""Session orchestrator for the frontend's "pick a song, get guided, get
graded" flow -- the DEV-MACHINE / SSH-based FALLBACK.

The preferred deployment now runs edge/practice_server.py directly ON the
Raspberry Pi (once the Pi has its own backend/ + deps), so there's no SSH
hop at all and none of the SSH job-control flakiness this version had to
work around. Keep this one for the case where the Pi can't run the grading
pipeline itself (no deps installed there) and the dev machine has to do the
conversion + grading over SSH instead. The two expose the same HTTP API and
the same frontend talks to either.

The browser can't SSH/scp to the Raspberry Pi or run the Python grading
pipeline (only installed on this machine) itself, so this local server is
the one thing the frontend talks to. It owns exactly one session at a time:

    GET  /api/songs                 -> song library + any imported songs
    POST /api/songs/import          -> body = raw MIDI bytes, header
                                        X-Song-Title = display name
    POST /api/session/start         -> {"song_id": "...", "speed": 1.0}
    GET  /api/session/status        -> merged Pi status + local phase
    POST /api/session/control       -> {"action": ..., "value": ...}
                                        forwarded to the Pi's guide server
    POST /api/session/stop          -> end the session early

On start: converts the song's MIDI to a guide JSON (edge/ws2812_guide_song.py
format, with the pitch-threshold hand fallback for single-track MIDI --
see backend/audio_to_performance/README.md's note on this), scp's it to the
Pi, and starts ws2812_guide_song.py there with --http-port and
--record-output so the LED guide and the Pi's own microphone recording are
started by the same command and stay in sync.

A background thread polls the Pi's /status; once that connection starts
failing (the Pi's script's main() returned -- song finished, or was quit),
it scp's the recording back, runs grade_audio_reference_constrained.py
--mode reference-grid against the same song, and writes the result to
frontend/viewer/public/result.json -- which the viewer already auto-loads
on load, so the frontend just needs to poll /api/session/status and swap to
the result view once phase == "done".

Run:
    ./backend/audio_to_performance/.venv/bin/python3 scripts/session_server.py
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.audio_to_performance.keybank import WHITE_KEY_MIDIS  # noqa: E402
from backend.score_to_reference.core import convert  # noqa: E402

PI_HOST = "pianopal@192.168.137.87"
PI_HTTP_PORT = 8765
PI_REMOTE_DIR = "~/PianoPal/edge"
LOCAL_VENV_PYTHON = str(REPO_ROOT / "backend/audio_to_performance/.venv/bin/python3")
KEYBOARD_PROFILE = str(REPO_ROOT / "data/bf3738c_keybank/bf3738c_white_profile.json")
RESULT_JSON = REPO_ROOT / "frontend/viewer/public/result.json"
DEBUG_JSON = REPO_ROOT / "frontend/viewer/public/last_debug.json"
CUSTOM_SONGS_DIR = REPO_ROOT / "data/custom_songs"
SCRATCH_DIR = REPO_ROOT / "data/session_scratch"
SONG_LIBRARY_DIR = REPO_ROOT / "docs/piano_music"
POLL_INTERVAL_SEC = 1.0

WHITE_KEY_SET = set(WHITE_KEY_MIDIS)


def _is_white_key_only(reference: dict) -> bool:
    return all(int(n["pitch"]) in WHITE_KEY_SET for n in reference.get("notes", []))


def _apply_pitch_hand_fallback(reference: dict, threshold: int = 60) -> dict:
    """See backend/audio_to_performance/README.md: single-track MIDI files
    put every note in one instrument, so midi_parser.py's track-index-based
    hand tagging can't distinguish hands -- reassign by a pitch threshold
    (below middle C = left/bass, at or above = right/melody) when the file
    genuinely has no real multi-track hand split."""
    notes = reference["notes"]
    if len({n.get("hand") for n in notes}) > 1:
        return reference
    for n in notes:
        n["hand"] = "L" if int(n["pitch"]) < threshold else "R"
    return reference


def _list_library_songs() -> list[dict]:
    songs = []
    for path in sorted(SONG_LIBRARY_DIR.glob("*.mid")):
        try:
            ref = convert(str(path))
        except Exception:
            continue
        songs.append({
            "id": f"library:{path.stem}",
            "title": ref.get("title") or path.stem,
            "notes": len(ref.get("notes", [])),
            "white_keys_only": _is_white_key_only(ref),
            "source": "library",
        })
    return songs


def _list_custom_songs() -> list[dict]:
    songs = []
    if not CUSTOM_SONGS_DIR.exists():
        return songs
    for path in sorted(CUSTOM_SONGS_DIR.glob("*.mid")):
        try:
            ref = convert(str(path))
        except Exception:
            continue
        songs.append({
            "id": f"custom:{path.stem}",
            "title": ref.get("title") or path.stem,
            "notes": len(ref.get("notes", [])),
            "white_keys_only": _is_white_key_only(ref),
            "source": "custom",
        })
    return songs


def _resolve_song_path(song_id: str) -> Path:
    source, _, stem = song_id.partition(":")
    base = SONG_LIBRARY_DIR if source == "library" else CUSTOM_SONGS_DIR
    path = base / f"{stem}.mid"
    if not path.exists():
        raise FileNotFoundError(song_id)
    return path


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    # Explicit stdin=DEVNULL matters: this server is itself typically
    # launched via `nohup ... &` without its own `< /dev/null`, so its
    # stdin can be a hung-up fd inherited from whatever launched it (the
    # same class of issue ws2812_guide_song.py had on the Pi side) --
    # without this, ssh/scp children inheriting that fd were failing
    # silently (returncode 0, no output) instead of raising a clear error.
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=kwargs.pop("timeout", 30),
        stdin=subprocess.DEVNULL, **kwargs,
    )


def _run_with_retries(
    cmd: list[str], attempts: int = 3, delay_sec: float = 2.0,
    success_check=None, **kwargs,
) -> subprocess.CompletedProcess:
    """The Pi's WiFi connection has intermittent multi-second blips
    unrelated to anything this server does (seen repeatedly just testing
    plain `ssh ... echo` by hand) -- a single failed ssh/scp isn't proof of
    a real problem, so retry a few times before giving up.

    `success_check`, if given, replaces the default "returncode == 0" test --
    needed for the backgrounding ssh launch command, which has been observed
    to occasionally return 0 with empty stdout (the remote shell accepted
    the connection but the backgrounded job died before `echo started`)."""
    check = success_check or (lambda r: r.returncode == 0)
    result = None
    for attempt in range(1, attempts + 1):
        try:
            result = _run(cmd, **kwargs)
        except subprocess.TimeoutExpired:
            result = None
        if result is not None and check(result):
            return result
        if attempt < attempts:
            time.sleep(delay_sec)
    return result if result is not None else subprocess.CompletedProcess(cmd, 255, "", "all retries timed out")


class Session:
    """The one active session, if any. Not thread-safe by itself -- callers
    take `LOCK` (module-level) around any read/mutate sequence."""

    def __init__(self, song_id: str, song_path: Path, reference: dict, speed: float):
        self.song_id = song_id
        self.song_path = song_path
        self.reference = reference
        self.speed = speed
        self.phase = "starting"  # starting -> guiding -> grading -> done -> error
        self.error = None
        self.pi_recording_path = f"/tmp/session_{uuid.uuid4().hex[:8]}.wav"
        self.remote_guide_json = f"guide_{uuid.uuid4().hex[:8]}.json"
        self.song_end = 0.0
        self.white_keys_only = False


LOCK = threading.Lock()
CURRENT: Session | None = None


def _pi_status() -> dict | None:
    try:
        with urllib.request.urlopen(f"http://{PI_HOST.split('@')[1]}:{PI_HTTP_PORT}/status", timeout=2) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def _pi_control(action: str, value=None) -> bool:
    body = json.dumps({"action": action} if value is None else {"action": action, "value": value}).encode()
    req = urllib.request.Request(
        f"http://{PI_HOST.split('@')[1]}:{PI_HTTP_PORT}/control", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=2)
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _start_session(song_id: str, speed: float) -> Session:
    song_path = _resolve_song_path(song_id)
    reference = convert(str(song_path))
    reference = _apply_pitch_hand_fallback(reference)
    white_keys_only = _is_white_key_only(reference)

    session = Session(song_id, song_path, reference, speed)
    song_end = max(
        (float(n["onset_sec"]) + float(n.get("dur_sec", 0.2) or 0.2) for n in reference["notes"]),
        default=0.0,
    )
    session.song_end = song_end
    session.white_keys_only = white_keys_only

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    local_guide_json = SCRATCH_DIR / f"{song_id.replace(':', '_')}_guide.json"
    local_guide_json.write_text(json.dumps({
        "title": reference.get("title", song_id), "tempo_bpm": reference.get("tempo_bpm"),
        "notes": reference["notes"],
    }), encoding="utf-8")

    _run_with_retries(["scp", str(local_guide_json), f"{PI_HOST}:{PI_REMOTE_DIR}/{session.remote_guide_json}"])

    # Cleanup and launch are two SEPARATE ssh calls, not one chained
    # `pkill; ... & echo started` command -- empirically, combining a pkill
    # (even one that matches nothing) with a backgrounded job in the SAME
    # remote shell invocation made ssh report success (returncode 0) with
    # completely empty output while the backgrounded job never actually
    # started, reproducibly, even though either half alone was reliable.
    # Splitting them sidesteps whatever shell/job-control interaction that is.
    _run_with_retries(["ssh", PI_HOST, "pkill -f 'ws2812_guide_son[g]'; sleep 0.3; true"], timeout=10)

    # setsid fully detaches the child into its own session (no controlling
    # terminal at all), which -- empirically, after a plain `cmd & echo
    # started` background chain was found to sometimes let ssh report
    # success while the child died within the same second with no output
    # at all -- is reliable where plain job-control backgrounding wasn't.
    # `python3 -u` disables stdout buffering: without it, a killed/crashed
    # process's buffered prints are lost, which is what made the earlier
    # failures look like silent hangs instead of showing a real error.
    remote_cmd = (
        f"cd {PI_REMOTE_DIR} && "
        f"setsid python3 -u ws2812_guide_song.py {session.remote_guide_json} "
        f"--http-port {PI_HTTP_PORT} --speed {speed} --record-output {session.pi_recording_path} "
        f"< /dev/null > /tmp/guide_session.log 2>&1 & echo started"
    )
    result = _run_with_retries(
        ["ssh", PI_HOST, remote_cmd], timeout=25,
        success_check=lambda r: r.returncode == 0 and "started" in r.stdout,
    )
    if "started" not in result.stdout:
        session.phase = "error"
        session.error = f"failed to start on Pi: {result.stdout} {result.stderr}"
        return session

    session.phase = "guiding"
    return session


def _finish_session(session: Session) -> None:
    session.phase = "grading"
    local_recording = SCRATCH_DIR / f"recording_{uuid.uuid4().hex[:8]}.wav"
    scp_result = _run_with_retries(["scp", f"{PI_HOST}:{session.pi_recording_path}", str(local_recording)], timeout=30)
    if scp_result.returncode != 0 or not local_recording.exists():
        session.phase = "error"
        session.error = f"could not fetch recording from Pi: {scp_result.stderr}"
        return

    cmd = [
        LOCAL_VENV_PYTHON, str(REPO_ROOT / "scripts/grade_audio_reference_constrained.py"),
        str(session.song_path), str(local_recording),
        "--keyboard-profile", KEYBOARD_PROFILE,
        "--mode", "reference-grid",
        "-o", str(RESULT_JSON),
        "--debug-output", str(DEBUG_JSON),
    ]
    if session.white_keys_only:
        cmd.append("--white-keys-only")

    grade_result = _run(cmd, timeout=120)
    if grade_result.returncode != 0:
        session.phase = "error"
        combined = (grade_result.stdout or "") + (grade_result.stderr or "")
        session.error = f"grading failed: {combined[-2000:]}"
        return

    session.phase = "done"


CONSECUTIVE_MISSES_TO_FINISH = 4  # ~4 seconds of no response, not just one blip


def _monitor_loop() -> None:
    misses = 0
    while True:
        time.sleep(POLL_INTERVAL_SEC)
        with LOCK:
            session = CURRENT
        if session is None or session.phase != "guiding":
            misses = 0
            continue
        status = _pi_status()
        if status is not None:
            misses = 0
            continue
        # The Pi's own network connection has had multi-second blips before
        # (unrelated to this session), so one missed poll isn't proof the
        # guide process actually ended -- only treat it as "the Pi's HTTP
        # server stopped responding because ws2812_guide_song.py's main()
        # returned" (song finished naturally, or was quit -- either way its
        # recorder.stop() already ran, so the file on the Pi is complete)
        # after several consecutive misses in a row.
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

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Song-Title")
            self.end_headers()

        def do_GET(self):
            if self.path == "/api/songs":
                self._json({"songs": _list_library_songs() + _list_custom_songs()})
            elif self.path == "/api/session/status":
                self._status()
            else:
                self._json({"error": "not found"}, 404)

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
                pi_status = _pi_status()
                if pi_status:
                    payload["song_pos"] = pi_status.get("song_pos")
                    payload["speed"] = pi_status.get("speed", session.speed)
                    payload["paused"] = pi_status.get("paused")
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
                    convert(str(dest))  # validate it's a real, parseable MIDI before accepting
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
                        CURRENT = _start_session(payload["song_id"], float(payload.get("speed", 1.0)))
                    except Exception as exc:
                        self._json({"error": str(exc)}, 400)
                        return
                self._json({"phase": CURRENT.phase})
                return

            if self.path == "/api/session/control":
                payload = json.loads(raw or b"{}")
                ok = _pi_control(payload.get("action"), payload.get("value"))
                self._json({"ok": ok})
                return

            if self.path == "/api/session/stop":
                with LOCK:
                    session = CURRENT
                if session is not None and session.phase == "guiding":
                    _pi_control("quit")
                self._json({"ok": True})
                return

            self._json({"error": "not found"}, 404)

        def log_message(self, fmt, *args):
            pass

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local session orchestrator for the frontend guided-practice flow.")
    parser.add_argument("--port", type=int, default=8900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    threading.Thread(target=_monitor_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), _make_handler())
    print(f"session server on :{args.port}  (GET /api/songs, POST /api/session/start, ...)")
    print(f"Pi target: {PI_HOST}:{PI_HTTP_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
