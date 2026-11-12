"""Candidate process failures retain fixed reasons without private diagnostics."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
from typing import Any
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from cli_bundle import TARGET, LINUX_TARGET
import cli_bundle_smoke as cli
import ffi_bundle_smoke as ffi


class CandidateProcessTests(unittest.TestCase):
    def invoke(self, label: str, target: str) -> None:
        if label == "cli":
            cli.probe(Path("PRIVATE-command"), "0.1.0", target)
        else:
            ffi.execute(["PRIVATE-command"], Path("."), label, target)

    def test_windows_loader_statuses_are_distinct_for_all_consumers(self) -> None:
        for status, reason in (
            (0xC0000135, "windows_dependency_missing"),
            (0xC000007B, "windows_invalid_image"),
            (0xC000012F, "windows_invalid_image"),
        ):
            for code in (status, status - 2**32):
                for label in ("cli", "c", "python", "compile"):
                    with self.subTest(code=code, label=label):
                        with (
                            patch.object(
                                subprocess,
                                "run",
                                return_value=subprocess.CompletedProcess(
                                    ["PRIVATE"], code
                                ),
                            ),
                            self.assertRaises(ValueError) as error,
                        ):
                            self.invoke(label, TARGET)
                        self.assertEqual(str(error.exception), f"{label}_{reason}")

    def test_windows_start_errors_are_redacted_and_preserve_reason(self) -> None:
        for winerror, reason in (
            (126, "windows_dependency_missing"),
            (193, "windows_invalid_image"),
            (5, "start_failed"),
        ):
            for label in ("cli", "c", "python", "compile"):
                with self.subTest(winerror=winerror, label=label):
                    failure: Any = OSError("PRIVATE path and arguments")
                    failure.winerror = winerror
                    with (
                        patch.object(subprocess, "run", side_effect=failure),
                        self.assertRaises(ValueError) as error,
                    ):
                        self.invoke(label, TARGET)
                    self.assertEqual(str(error.exception), f"{label}_{reason}")
                    self.assertNotIn(
                        "PRIVATE", "".join(traceback.format_exception(error.exception))
                    )

    def test_other_platforms_and_application_exits_are_not_loader_diagnoses(
        self,
    ) -> None:
        for target, code in (
            (TARGET, 3),
            (LINUX_TARGET, 0xC0000135),
            (LINUX_TARGET, -11),
        ):
            for label in ("cli", "c", "python", "elf"):
                with self.subTest(target=target, code=code, label=label):
                    with (
                        patch.object(
                            subprocess,
                            "run",
                            return_value=subprocess.CompletedProcess(["PRIVATE"], code),
                        ),
                        self.assertRaises(ValueError) as error,
                    ):
                        self.invoke(label, target)
                    self.assertEqual(str(error.exception), f"{label}_exit")
        with (
            patch.object(subprocess, "run", side_effect=FileNotFoundError("PRIVATE")),
            self.assertRaisesRegex(ValueError, "c_start_failed"),
        ):
            self.invoke("c", LINUX_TARGET)

    def test_timeout_is_distinct_and_does_not_echo_the_command(self) -> None:
        for label in ("cli", "c", "python", "compile"):
            with (
                patch.object(
                    subprocess,
                    "run",
                    side_effect=subprocess.TimeoutExpired("PRIVATE", 1),
                ),
                self.assertRaises(ValueError) as error,
            ):
                self.invoke(label, TARGET)
            self.assertEqual(str(error.exception), f"{label}_timeout")
            self.assertNotIn(
                "PRIVATE", "".join(traceback.format_exception(error.exception))
            )

    @unittest.skipUnless(os.name == "nt", "Windows exit status required")
    def test_real_windows_exit_status_and_clean_success(self) -> None:
        # This child deliberately returns a status; real loader acceptance is separate.
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "c_windows_dependency_missing"):
                ffi.execute(
                    [
                        sys.executable,
                        "-c",
                        "import ctypes; ctypes.windll.kernel32.ExitProcess(0xC0000135)",
                    ],
                    Path(folder),
                    "c",
                    TARGET,
                )
            self.assertEqual(
                ffi.execute(
                    [sys.executable, "-c", "print('ok')"], Path(folder), "c", TARGET
                ),
                b"ok\r\n",
            )


if __name__ == "__main__":
    unittest.main()
