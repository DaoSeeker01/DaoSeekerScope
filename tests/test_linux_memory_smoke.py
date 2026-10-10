"""Evidence guards; actual permission/freshness evidence comes from Linux CI."""

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import linux_memory_smoke as smoke


def snapshot(memory=smoke.HEALTHY_MEMORY, uptime=smoke.HEALTHY_UPTIME):
    data = json.loads(
        (smoke.ROOT / "tests/fixtures/snapshot-v1.json").read_text("utf-8")
    )
    total = data["static_info"]["system"]["memory"]["total_usable_bytes"]
    total.update(
        value=1048576,
        availability="available",
        source="procfs",
        reason=None,
        observed_at=1000,
    )
    for field, expected in [
        ("memory_available_bytes", memory),
        ("runtime.uptime_seconds", uptime),
    ]:
        state, reason, value = expected
        item = (
            data["dynamic"]["runtime"]["uptime_seconds"]
            if field.startswith("runtime.")
            else data["dynamic"][field]
        )
        item.update(
            value=value,
            availability=state,
            source="procfs",
            reason=reason,
            observed_at=1000 if state == "available" else None,
        )
        for cap in data["capabilities"]:
            if cap["field"] == field:
                cap.update(
                    level="restricted" if state == "restricted" else "supported",
                    source="procfs",
                    reason=reason,
                )
    return data


class MemoryEvidenceGuards(unittest.TestCase):
    def test_old_values_and_fallback_uptime_cannot_substitute_for_failure(self):
        expected = {
            "memory_available_bytes": smoke.INVALID,
            "runtime.uptime_seconds": smoke.INVALID,
        }
        with self.assertRaises(smoke.ValidationFailure):
            smoke.verify(snapshot(), expected)
        smoke.verify(snapshot(smoke.INVALID, smoke.INVALID), expected)
        smoke.verify(
            snapshot(("available", None, 0), ("available", None, 0)),
            {key: ("available", None, 0) for key in expected},
        )

    def test_restriction_and_recovery_metadata_are_checked(self):
        expected = {
            "memory_available_bytes": smoke.DENIED,
            "runtime.uptime_seconds": smoke.HEALTHY_UPTIME,
        }
        data = snapshot(smoke.DENIED)
        smoke.verify(data, expected)
        for wrong in ["unknown", "not_present", "invalid_data"]:
            bad = copy.deepcopy(data)
            bad["dynamic"]["memory_available_bytes"]["reason"] = wrong
            with self.assertRaises(smoke.ValidationFailure):
                smoke.verify(bad, expected)
        recovered = snapshot()
        for cap in recovered["capabilities"]:
            if cap["field"] == "memory_available_bytes":
                cap["level"] = "restricted"
        with self.assertRaises(smoke.ValidationFailure):
            smoke.verify(recovered, {"memory_available_bytes": smoke.HEALTHY_MEMORY})

    def test_unavailable_cannot_retain_timestamp(self):
        data = snapshot(smoke.INVALID)
        data["dynamic"]["memory_available_bytes"]["observed_at"] = 1000
        with self.assertRaises(smoke.ValidationFailure):
            smoke.verify(data, {"memory_available_bytes": smoke.INVALID})

    def test_failure_and_interruption_do_not_reuse_passed_report(self):
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
