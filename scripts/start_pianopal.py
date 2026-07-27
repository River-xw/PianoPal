#!/usr/bin/env python3
"""Start PianoPal's active backend orchestrator and optional Vite frontend."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
# Support the tracked scripts/ location and a standalone copy placed directly
# in the repository root on the Raspberry Pi.
REPO_ROOT = SCRIPT_DIR if (SCRIPT_DIR / "edge").is_dir() else SCRIPT_DIR.parent
VIEWER_DIR = REPO_ROOT / "frontend/viewer"
VENV_PYTHON = REPO_ROOT / "backend/audio_to_performance/.venv/bin/python3"


@dataclass
class Service:
    name: str
    command: list[str]
    cwd: Path
    health_url: str
    env: dict[str, str]
    process: subprocess.Popen[bytes] | None = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the PianoPal session API and frontend with one command."
    )
    parser.add_argument(
        "--backend",
        choices=("practice", "ssh"),
        default="practice",
        help="practice: Pi-native orchestrator; ssh: dev-machine fallback",
    )
    parser.add_argument("--api-port", type=int, default=8900)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument(
        "--no-frontend", action="store_true", help="start only the session API"
    )
    parser.add_argument(
        "--without-motion",
        action="store_true",
        help="allow practice sessions without BLE posture sensors",
    )
    parser.add_argument(
        "--python",
        help="Python executable for the backend (defaults to the audio venv when present)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify all services become healthy, then stop them and exit",
    )
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    return parser.parse_args()


def _python_executable(explicit: str | None) -> str:
    if explicit:
        resolved = shutil.which(explicit) if "/" not in explicit else explicit
        if not resolved or not Path(resolved).is_file():
            raise RuntimeError(f"Python executable not found: {explicit}")
        return str(resolved)
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _wait_healthy(service: Service, deadline: float) -> None:
    last_error = "no response"
    while time.monotonic() < deadline:
        assert service.process is not None
        returncode = service.process.poll()
        if returncode is not None:
            raise RuntimeError(f"{service.name} exited during startup ({returncode})")
        try:
            with urllib.request.urlopen(service.health_url, timeout=1.0) as response:
                if 200 <= response.status < 400:
                    return
                last_error = f"HTTP {response.status}"
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"{service.name} health check failed: {last_error}")


def _get_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=3.0) as response:
            return json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc


def _smoke_test(args: argparse.Namespace) -> None:
    query = "/api/songs?username=startup-check&mode=learn"
    backend_payload = _get_json(f"http://127.0.0.1:{args.api_port}{query}")
    songs = backend_payload.get("songs")
    if not isinstance(songs, list) or not songs:
        raise RuntimeError("backend song library is empty or invalid")
    print(f"verified backend API: {len(songs)} songs", flush=True)

    if not args.no_frontend:
        proxied_payload = _get_json(f"http://127.0.0.1:{args.frontend_port}{query}")
        if proxied_payload.get("songs") != songs:
            raise RuntimeError("frontend API proxy response differs from backend")
        print("verified frontend API proxy", flush=True)


def _stop_service(service: Service) -> None:
    process = service.process
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def _services(args: argparse.Namespace) -> list[Service]:
    python = _python_executable(args.python)
    backend_script = (
        REPO_ROOT / "edge/practice_server.py"
        if args.backend == "practice"
        else REPO_ROOT / "scripts/session_server.py"
    )
    backend_env = os.environ.copy()
    if args.without_motion:
        backend_env["PIANOPAL_REQUIRE_MOTION"] = "0"
    services = [
        Service(
            name=f"backend:{args.backend}",
            command=[python, "-u", str(backend_script), "--port", str(args.api_port)],
            cwd=REPO_ROOT,
            health_url=f"http://127.0.0.1:{args.api_port}/api/session/status",
            env=backend_env,
        )
    ]
    if not args.no_frontend:
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm not found")
        if not (VIEWER_DIR / "node_modules").is_dir():
            raise RuntimeError("frontend dependencies missing; run: cd frontend/viewer && npm ci")
        frontend_env = os.environ.copy()
        frontend_env["SESSION_SERVER"] = f"127.0.0.1:{args.api_port}"
        services.append(
            Service(
                name="frontend",
                command=[npm, "run", "dev", "--", "--host", "0.0.0.0", "--port", str(args.frontend_port)],
                cwd=VIEWER_DIR,
                health_url=f"http://127.0.0.1:{args.frontend_port}/",
                env=frontend_env,
            )
        )
    return services


def main() -> int:
    args = _parse_args()
    if args.api_port == args.frontend_port and not args.no_frontend:
        raise SystemExit("API and frontend ports must differ")
    ports = [args.api_port] + ([] if args.no_frontend else [args.frontend_port])
    occupied = [str(port) for port in ports if not _port_is_free(port)]
    if occupied:
        raise SystemExit(f"ports already in use: {', '.join(occupied)}")

    try:
        services = _services(args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        for service in services:
            print(f"starting {service.name}: {' '.join(service.command)}", flush=True)
            service.process = subprocess.Popen(
                service.command,
                cwd=service.cwd,
                env=service.env,
                start_new_session=True,
            )
            _wait_healthy(service, time.monotonic() + args.startup_timeout)
            print(f"ready {service.name}: {service.health_url}", flush=True)

        if args.check:
            _smoke_test(args)
            print("all services healthy", flush=True)
            return 0

        print(
            f"PianoPal ready: http://127.0.0.1:{args.frontend_port}/"
            if not args.no_frontend
            else f"PianoPal API ready: http://127.0.0.1:{args.api_port}/",
            flush=True,
        )
        while not stopping:
            for service in services:
                assert service.process is not None
                returncode = service.process.poll()
                if returncode is not None:
                    raise RuntimeError(f"{service.name} exited ({returncode})")
            time.sleep(0.5)
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        for service in reversed(services):
            _stop_service(service)


if __name__ == "__main__":
    raise SystemExit(main())
