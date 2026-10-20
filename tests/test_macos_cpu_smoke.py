"""Mach CPU evidence: unsigned counters, ownership, statuses and partial failures."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "mach_cpu", ROOT / "scripts/macos_cpu_smoke.py"
)
assert spec and spec.loader
cpu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpu)


def sdk(ticks: list[list[int]]) -> dict:
    return dict(
        status="passed",
        calls=1,
        processors=len(ticks),
        word_count=len(ticks) * 4,
        word_size=4,
        pointer_size=8,
        released_array=True,
        released_host=True,
        ticks=ticks,
    )


class MachCpuEvidenceTests(unittest.TestCase):
    def test_observations_never_turn_warmup_or_missing_count_into_a_value(self) -> None:
        field = dict(
            value=0.0,
            availability="available",
            source="apple_api",
            reason=None,
            observed_at=1,
        )
        for value in (0, 50.0, 100):
            cpu.check_field(dict(field, value=value))
        for changes in (
            dict(source="sysinfo"),
            dict(value=True),
            dict(value=-1),
            dict(value=101),
            dict(value=float("nan")),
            dict(value=float("inf")),
            dict(observed_at=None),
            dict(reason="unknown"),
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
        cpu.check_field(warmup, True)
        with self.assertRaises(ValueError):
            cpu.check_field(dict(warmup, value=0), True)
        for count in (1, 1024):
            self.assertEqual(cpu.check_count(dict(field, value=count)), count)
        for bad_count in (None, True, 0, 1025):
            with self.assertRaises(ValueError):
                cpu.check_count(dict(field, value=bad_count))

    def test_sdk_unsigned_words_shapes_and_both_cleanup_results(self) -> None:
        changes: dict[str, Any]
        sample = sdk([[0, 2**31, 2**32 - 1, 1]])
        cpu.check_sdk(sample, 1)
        for changes in (
            dict(processors=True),
            dict(processors=0),
            dict(processors=1025),
            dict(calls=2),
            dict(word_count=3),
            dict(word_size=8),
            dict(pointer_size=4),
            dict(released_array=False),
            dict(released_host=False),
            dict(released_host=1),
            dict(ticks=[]),
            dict(ticks=[[0, 0, 0]]),
            dict(ticks=[[-1, 0, 0, 0]]),
            dict(ticks=[[2**32, 0, 0, 0]]),
            dict(ticks=[[True, 0, 0, 0]]),
        ):
            with self.assertRaises(ValueError):
                cpu.check_sdk(dict(sample, **changes), 1)

    def test_weighted_percent_and_per_processor_resets(self) -> None:
        previous = sdk([[0, 0, 0, 0], [0, 0, 0, 0]])
        self.assertEqual(
            cpu.sdk_usage(previous, sdk([[0, 0, 100, 0], [900, 0, 0, 0]])), 90
        )
        self.assertEqual(cpu.sdk_usage(sdk([[0, 0, 0, 0]]), sdk([[0, 0, 100, 0]])), 0)
        self.assertEqual(cpu.sdk_usage(sdk([[0, 0, 0, 0]]), sdk([[0, 0, 0, 100]])), 100)
        with self.assertRaises(ValueError):
            cpu.sdk_usage(previous, previous)
        with self.assertRaises(ValueError):
            cpu.sdk_usage(previous, sdk([[1, 1, 1, 1]]))
        with self.assertRaises(ValueError):
            cpu.sdk_usage(
                sdk([[2**32 - 1, 0, 0, 0], [0, 0, 0, 0]]),
                sdk([[0, 0, 0, 0], [2**32 - 1] * 4]),
            )

    def test_failure_or_interrupt_replaces_stale_pass_and_retains_filtered_phase(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            for error, code in (
                (ValueError("private system path"), 1),
                (KeyboardInterrupt(), 130),
            ):
                output.write_text('{"status":"passed"}', encoding="utf-8")

                def fail(report: dict) -> None:
                    self.assertEqual(
                        json.loads(output.read_text(encoding="utf-8"))["status"],
                        "failed",
                    )
                    report["observations"] = [
                        {"status": "running", "cpu": {"value": None}}
                    ]
                    raise error

                with patch.object(cpu, "collect", side_effect=fail):
                    self.assertEqual(cpu.run(output), code)
                report = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["observations"][0]["status"], "running")
                self.assertNotIn(
                    "private system path", output.read_text(encoding="utf-8")
                )


if __name__ == "__main__":
    unittest.main()
