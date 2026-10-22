"""Reject invalid or stale success evidence without requiring a Windows host."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "uptime_smoke", ROOT / "scripts/windows_uptime_smoke.py"
)
assert spec and spec.loader
uptime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uptime)


class UptimeEvidenceTests(unittest.TestCase):
    def test_zero_floor_brackets_and_full_integer_domain(self) -> None:
        field = dict(
            value=0,
            availability="available",
            source="win32",
            reason=None,
            observed_at=1,
        )
        uptime.check_field(field, 0, 999)
        uptime.check_field(dict(field, value=1), 999, 1000)
        uptime.check_field(dict(field, value=(2**64 - 1) // 1000), 2**64 - 1, 2**64 - 1)
        for changes in (
            dict(value=True),
            dict(value=0.0),
            dict(value=-1),
            dict(value=2),
            dict(source="sysinfo"),
            dict(reason="unknown"),
            dict(availability="unavailable"),
            dict(observed_at=None),
            dict(observed_at=True),
            dict(observed_at=-1),
        ):
            with self.assertRaises(ValueError):
                uptime.check_field(dict(field, **changes), 0, 1000)
        for before, after in ((-1, 1000), (1000, 999), (0, 2**64), (True, 1000)):
            with self.assertRaises(ValueError):
                uptime.check_field(field, before, after)

    def test_sdk_call_counts_and_u64_values(self) -> None:
        sample = dict(milliseconds=0, calls=1)
        self.assertEqual(uptime.check_sdk(sample, 1), 0)
        for changes in (
            dict(milliseconds=True),
            dict(milliseconds=-1),
            dict(milliseconds=2**64),
            dict(milliseconds=1.0),
            dict(calls=2),
            dict(calls=True),
        ):
            with self.assertRaises(ValueError):
                uptime.check_sdk(dict(sample, **changes), 1)

    def test_failed_and_interrupted_runs_replace_stale_passed_report(self) -> None:
        for error, code in (
            (RuntimeError("private error"), 1),
            (KeyboardInterrupt(), 130),
        ):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "evidence.json"
                output.write_text('{"status":"passed"}', encoding="utf-8")
                with patch.object(uptime, "collect", side_effect=error):
                    self.assertEqual(uptime.run(output), code)
                report = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "failed")
                self.assertNotIn("private error", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
