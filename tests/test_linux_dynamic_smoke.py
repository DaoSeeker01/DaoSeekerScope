"""CPU evidence guards, distinct from actual container execution."""

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import linux_dynamic_smoke as smoke


def snapshot(state="available", reason=None, value=50.0):
    data = json.loads(
        (smoke.ROOT / "tests/fixtures/snapshot-v1.json").read_text("utf-8")
    )
    data["dynamic"]["cpu_usage_percent"] = {
        "value": value,
        "availability": state,
        "source": "procfs",
        "reason": reason,
        "observed_at": 1000 if state == "available" else None,
    }
    data["dynamic"]["memory_available_bytes"] = {
        "value": 1024,
        "availability": "available",
        "source": "sysinfo",
        "reason": None,
        "observed_at": 1000,
    }
    for cap in data["capabilities"]:
        if cap["field"] == "cpu_usage_percent":
            cap.update(
                level="restricted" if state == "restricted" else "supported",
                source="procfs",
                reason=reason,
            )
    return data


class DynamicEvidenceGuards(unittest.TestCase):
    def test_stale_percent_and_zero_cannot_substitute_for_read_failure(self):
        for value in [0.0, 50.0]:
            with self.assertRaises(smoke.ValidationFailure):
                smoke.verify(snapshot(value=value), "unavailable", "invalid_data", None)
        smoke.verify(
            snapshot("unavailable", "invalid_data", None),
            "unavailable",
            "invalid_data",
            None,
        )
        smoke.verify(snapshot(value=0.0), "available", None, 0.0)

    def test_recovery_must_restore_capability_and_unavailable_timestamp(self):
        data = snapshot()
        for cap in data["capabilities"]:
            if cap["field"] == "cpu_usage_percent":
                cap["level"] = "restricted"
        with self.assertRaises(smoke.ValidationFailure):
            smoke.verify(data, "available", None, 50.0)
        bad = snapshot("unavailable", "temporarily_unavailable", None)
        bad["dynamic"]["cpu_usage_percent"]["observed_at"] = 1000
        with self.assertRaises(smoke.ValidationFailure):
            smoke.verify(bad, "unavailable", "temporarily_unavailable", None)

    def test_permission_absence_and_data_errors_cannot_be_interchanged(self):
        data = snapshot("restricted", "permission_denied", None)
        smoke.verify(data, "restricted", "permission_denied", None)
        for wrong in ["invalid_data", "not_present", "unknown"]:
            bad = copy.deepcopy(data)
            bad["dynamic"]["cpu_usage_percent"]["reason"] = wrong
            with self.assertRaises(smoke.ValidationFailure):
                smoke.verify(bad, "restricted", "permission_denied", None)

    def test_failure_and_interruption_cannot_reuse_successful_report(self):
        for error in [smoke.ValidationFailure("probe: failed"), KeyboardInterrupt()]:
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "report.json"
                output.write_text('{"overall":"passed"}', encoding="utf-8")
                with (
                    patch.object(sys, "argv", ["smoke", "--output", str(output)]),
                    patch.object(smoke, "execute", side_effect=error),
                    patch("sys.stdout", io.StringIO()),
                ):
                    if isinstance(error, KeyboardInterrupt):
                        with self.assertRaises(KeyboardInterrupt):
                            smoke.main()
                        expected = "incomplete"
                    else:
                        self.assertEqual(smoke.main(), 1)
                        expected = "failed"
                self.assertEqual(
                    json.loads(output.read_text("utf-8"))["overall"], expected
                )


if __name__ == "__main__":
    unittest.main()
