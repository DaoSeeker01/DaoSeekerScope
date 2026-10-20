"""Reject false successful CPU evidence, stale reports and malformed counters."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "cpu_smoke", ROOT / "scripts/windows_cpu_smoke.py"
)
assert spec and spec.loader
cpu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpu)


class CpuEvidenceTests(unittest.TestCase):
    def test_success_metadata_domain_and_warmup_are_distinct(self) -> None:
        field = dict(
            value=0.0,
            availability="available",
            source="win32",
            reason=None,
            observed_at=1,
        )
        for value in (0, 50.0, 100):
            cpu.check_field(dict(field, value=value))
        for changes in (
            dict(value=True),
            dict(value=-1),
            dict(value=101),
            dict(value=float("nan")),
            dict(value=float("inf")),
            dict(source="sysinfo"),
            dict(observed_at=None),
            dict(observed_at=True),
            dict(reason="unknown"),
            dict(availability="unavailable"),
        ):
            with self.assertRaises(ValueError):
                cpu.check_field(dict(field, **changes))
        warmup = dict(
            field,
            value=None,
            observed_at=None,
            availability="unavailable",
            reason="temporarily_unavailable",
        )
        cpu.check_field(warmup, warmup=True)
        for changes in (
            dict(value=0),
            dict(observed_at=1),
            dict(reason="permission_denied"),
        ):
            with self.assertRaises(ValueError):
                cpu.check_field(dict(warmup, **changes), warmup=True)

    def test_sdk_coverage_status_bounds_and_delta_math(self) -> None:
        sample = dict(
            status="passed",
            groups=1,
            processors=8,
            calls=1,
            struct_size=8,
            idle=10,
            kernel=100,
            user=100,
        )
        cpu.check_sdk(sample, 1)
        current = dict(sample, idle=110, kernel=200, user=200)
        self.assertEqual(cpu.sdk_usage(sample, current), 50)
        self.assertEqual(cpu.sdk_usage(sample, dict(sample, idle=110, kernel=200)), 0)
        self.assertEqual(cpu.sdk_usage(sample, dict(sample, kernel=200)), 100)
        for changes in (
            dict(groups=2),
            dict(groups=True),
            dict(processors=0),
            dict(processors=65),
            dict(status="unsupported"),
            dict(calls=2),
            dict(struct_size=16),
            dict(idle=-1),
            dict(idle=101),
            dict(user=2**64),
        ):
            with self.assertRaises(ValueError):
                cpu.check_sdk(dict(sample, **changes), 1)
        for changes in (
            dict(processors=4),
            dict(kernel=99),
            dict(user=99),
            dict(idle=12, kernel=101),
            {},
        ):
            with self.assertRaises(ValueError):
                cpu.sdk_usage(sample, dict(sample, **changes))

    def test_failed_or_interrupted_run_replaces_old_pass_and_keeps_partial_phase(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            for error, expected in (
                (ValueError("private raw path"), 1),
                (KeyboardInterrupt(), 130),
            ):
                output.write_text('{"status":"passed"}', encoding="utf-8")

                def fail(report: dict) -> None:
                    initial = json.loads(output.read_text(encoding="utf-8"))
                    self.assertEqual(initial["status"], "failed")
                    report["observations"] = [{"partial": True}]
                    raise error

                with patch.object(cpu, "collect", side_effect=fail):
                    self.assertEqual(cpu.run(output), expected)
                report = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["observations"], [{"partial": True}])
                self.assertNotIn("private raw path", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
