"""Reject invalid group evidence and wrong unweighted/per-group-reset math."""

from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "cpu_groups_smoke", ROOT / "scripts/windows_cpu_groups_smoke.py"
)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def sample() -> dict[str, Any]:
    return dict(
        status="passed",
        calls=1,
        groups=2,
        processors=65,
        caller_affinity_unchanged=True,
        group_info_size=48,
        group_info_offset=32,
        samples=[
            dict(processors=64, mask=2**64 - 1, idle=0, kernel=0, user=0),
            dict(processors=1, mask=1, idle=0, kernel=0, user=0),
        ],
    )


class GroupEvidenceTests(unittest.TestCase):
    def test_sdk_metadata_and_group_counters_are_not_forged_success(self) -> None:
        good = sample()
        probe.check_sdk(good, 1)
        metadata_changes: list[dict[str, Any]] = [
            dict(groups=0),
            dict(groups=True),
            dict(groups=17),
            dict(processors=64),
            dict(calls=2),
            dict(status="unsupported"),
            dict(caller_affinity_unchanged=False),
            dict(group_info_size=44),
            dict(group_info_offset=24),
            dict(samples=[]),
        ]
        for changes in metadata_changes:
            with self.assertRaises(ValueError):
                probe.check_sdk(dict(good, **changes), 1)
        counter_changes: list[dict[str, Any]] = [
            dict(processors=0),
            dict(processors=65),
            dict(processors=True),
            dict(idle=-1),
            dict(idle=1),
            dict(user=2**64),
            dict(kernel=True),
            dict(mask=0),
            dict(mask=2**64),
            dict(mask=True),
            dict(mask=1),
        ]
        for changes in counter_changes:
            bad = sample()
            bad["samples"][0].update(changes)
            with self.assertRaises(ValueError):
                probe.check_sdk(bad, 1)

    def test_weighted_math_and_resets_are_checked_per_group(self) -> None:
        first = sample()
        last = sample()
        last["samples"][0].update(kernel=100)
        last["samples"][1].update(idle=900, kernel=900)
        self.assertEqual(probe.sdk_usage(first, last), 10)
        first["samples"][0].update(idle=20, kernel=100, user=100)
        last["samples"][0].update(idle=20, kernel=99, user=100)
        last["samples"][1].update(kernel=10000, user=10000)
        with self.assertRaises(ValueError):
            probe.sdk_usage(first, last)
        first, last = sample(), sample()
        last["samples"][1].update(mask=2, kernel=100)
        with self.assertRaises(ValueError):
            probe.sdk_usage(first, last)

    def test_failed_runs_replace_stale_success_without_raw_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            output.write_text('{"status":"passed"}', encoding="utf-8")
            with patch.object(
                probe, "collect", side_effect=RuntimeError("private raw error")
            ):
                self.assertEqual(probe.run(output), 1)
            report = json.loads(output.read_text("utf-8"))
            self.assertEqual(report["status"], "failed")
            self.assertNotIn("private raw error", output.read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
