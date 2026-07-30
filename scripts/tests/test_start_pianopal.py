from __future__ import annotations

import argparse
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import start_pianopal


def _args(mode: str, *, no_frontend: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        frontend_mode=mode,
        no_frontend=no_frontend,
    )


class FrontendPlanTest(unittest.TestCase):
    def test_external_mode_never_requires_npm(self) -> None:
        with mock.patch.object(start_pianopal.shutil, "which", return_value=None):
            start, note = start_pianopal._frontend_plan(_args("external"))

        self.assertFalse(start)
        self.assertIn("external", note)

    def test_deprecated_no_frontend_alias_selects_external(self) -> None:
        start, _ = start_pianopal._frontend_plan(
            _args("local", no_frontend=True)
        )

        self.assertFalse(start)

    def test_auto_mode_skips_vite_without_npm_or_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            viewer = Path(temporary_directory)
            with (
                mock.patch.object(start_pianopal, "VIEWER_DIR", viewer),
                mock.patch.object(
                    start_pianopal.shutil, "which", return_value=None
                ),
            ):
                start, note = start_pianopal._frontend_plan(_args("auto"))

        self.assertFalse(start)
        self.assertIn("npm", note)
        self.assertIn("node_modules", note)

    def test_local_mode_reports_how_to_use_external_frontend(self) -> None:
        with mock.patch.object(start_pianopal.shutil, "which", return_value=None):
            with self.assertRaisesRegex(
                RuntimeError, "--frontend-mode external"
            ):
                start_pianopal._frontend_plan(_args("local"))

    def test_auto_mode_starts_vite_when_requirements_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            viewer = Path(temporary_directory)
            (viewer / "node_modules").mkdir()
            with (
                mock.patch.object(start_pianopal, "VIEWER_DIR", viewer),
                mock.patch.object(
                    start_pianopal.shutil,
                    "which",
                    return_value="/usr/bin/npm",
                ),
            ):
                start, note = start_pianopal._frontend_plan(_args("auto"))

        self.assertTrue(start)
        self.assertIn("auto-detected", note)

    def test_explicit_public_host_is_preserved(self) -> None:
        self.assertEqual(
            start_pianopal._detect_public_host("192.168.137.87"),
            "192.168.137.87",
        )

    def test_pi_backend_hardware_defaults_are_applied(self) -> None:
        args = argparse.Namespace(
            python="/usr/bin/python3",
            backend="practice",
            api_port=8900,
            frontend_port=5173,
            without_motion=False,
        )
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                start_pianopal,
                "RUNNING_AS_ROOT_COPY",
                True,
            ),
        ):
            service = start_pianopal._services(
                args,
                start_frontend=False,
            )[0]

        for name, value in start_pianopal.BACKEND_ENV_DEFAULTS.items():
            self.assertEqual(service.env[name], value)

    def test_explicit_hardware_environment_overrides_default(self) -> None:
        args = argparse.Namespace(
            python="/usr/bin/python3",
            backend="practice",
            api_port=8900,
            frontend_port=5173,
            without_motion=False,
        )
        with (
            mock.patch.dict(
                os.environ,
                {"PIANOPAL_POSTURE_HANDS": "L"},
                clear=True,
            ),
            mock.patch.object(
                start_pianopal,
                "RUNNING_AS_ROOT_COPY",
                True,
            ),
        ):
            service = start_pianopal._services(
                args,
                start_frontend=False,
            )[0]

        self.assertEqual(service.env["PIANOPAL_POSTURE_HANDS"], "L")


if __name__ == "__main__":
    unittest.main()
