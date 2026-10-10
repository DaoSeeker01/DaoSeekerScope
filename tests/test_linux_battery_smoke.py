"""Synthetic evidence guard fixtures; these tests do not run Docker or hardware."""

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import linux_battery_smoke as smoke


def observed(value=None, state="available", reason=None):
    return {
        "value": value,
        "availability": state,
        "reason": reason,
        "source": "sysfs",
        "observed_at": 1000 if state == "available" else None,
    }


def snapshot():
    data = json.loads(
        (smoke.ROOT / "tests/fixtures/snapshot-v1.json").read_text("utf-8")
    )
    data["dynamic"]["memory_available_bytes"] = {**observed(512), "source": "procfs"}
    data["dynamic"]["batteries"] = observed(
        [{"charge_percent": observed(50.0), "on_ac_power": observed(True)}]
    )
    cap = next(c for c in data["capabilities"] if c["field"] == "batteries")
    cap.update(level="partial", source="sysfs", reason=None)
    return data


class EvidenceGuards(unittest.TestCase):
    def test_denied_fixture_can_be_rewritten_by_its_owner_for_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AC").mkdir()
            smoke.write_attribute(root, "AC", "online", b"1", 0)
            smoke.write_attribute(root, "AC", "online", b"2")
            self.assertEqual((root / "AC/online").read_bytes(), b"2")
            smoke.write_attribute(root, "AC", "online", b"0", 0)
            smoke.write_attribute(root, "AC", "online", b"1")
            self.assertEqual((root / "AC/online").read_bytes(), b"1")

    def test_available_empty_missing_and_restricted_stay_distinct(self):
        for expectation in [[], smoke.ABSENT, smoke.DENIED]:
            data = snapshot()
            data["dynamic"]["batteries"] = (
                observed([])
                if isinstance(expectation, list)
                else observed(None, expectation[0], expectation[1])
            )
            cap = next(c for c in data["capabilities"] if c["field"] == "batteries")
            cap.update(
                level="restricted" if expectation == smoke.DENIED else "partial",
                reason=None if isinstance(expectation, list) else expectation[1],
            )
            self.assertTrue(smoke.verify(data, expectation)["schema_validated"])
            bad = copy.deepcopy(data)
            bad["dynamic"]["batteries"]["value"] = [{}]
            with self.assertRaises(smoke.ValidationFailure):
                smoke.verify(bad, expectation)

    def test_wrong_field_state_type_or_stale_value_is_rejected(self):
        data = snapshot()
        self.assertTrue(
            smoke.verify(data, [(smoke.GOOD, smoke.TRUE)])["healthy_memory"]
        )
        for field, key, value in [
            ("charge_percent", "value", 51.0),
            ("charge_percent", "observed_at", None),
            ("charge_percent", "source", "sysinfo"),
            ("on_ac_power", "value", 1),
        ]:
            bad = copy.deepcopy(data)
            bad["dynamic"]["batteries"]["value"][0][field][key] = value
            with self.assertRaises(smoke.ValidationFailure):
                smoke.verify(bad, [(smoke.GOOD, smoke.TRUE)])
        with self.assertRaises(smoke.ValidationFailure):
            smoke.verify(data, [(smoke.INVALID, smoke.TRUE)])

    def test_capability_privacy_and_unrelated_field_failures_are_rejected(self):
        for kind in ["capability", "privacy", "memory", "identifier"]:
            data = snapshot()
            if kind == "capability":
                next(c for c in data["capabilities"] if c["field"] == "batteries")[
                    "level"
                ] = "supported"
            elif kind == "privacy":
                data["static_info"]["system"]["device"]["serial_number"] = observed(
                    "private"
                )
            elif kind == "memory":
                data["dynamic"]["memory_available_bytes"] = observed(
                    None, "unavailable", "not_present"
                )
            else:
                data["dynamic"]["batteries"]["value"][0]["identifier"] = smoke.PRIVATE
            with self.assertRaises(smoke.ValidationFailure):
                smoke.verify(data, [(smoke.GOOD, smoke.TRUE)])

    def test_process_failure_and_incomplete_campaign_return_nonzero(self):
        for side_effect in [smoke.ValidationFailure("probe: process_failed"), None]:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "report.json"
                with (
                    patch.object(sys, "argv", ["smoke", "--output", str(output)]),
                    patch.object(smoke, "execute", side_effect=side_effect),
                    patch.object(sys, "stdout", io.StringIO()),
                ):
                    self.assertEqual(smoke.main(), 1)
                data = json.loads(output.read_text("utf-8"))
                self.assertEqual(data["overall"], "failed")
                self.assertEqual(data["samples"], {})

    def test_interruption_does_not_preserve_old_success(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            output.write_text('{"overall":"passed"}', encoding="utf-8")
            with (
                patch.object(sys, "argv", ["smoke", "--output", str(output)]),
                patch.object(smoke, "execute", side_effect=KeyboardInterrupt),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    smoke.main()
            self.assertEqual(
                json.loads(output.read_text("utf-8"))["overall"], "incomplete"
            )


if __name__ == "__main__":
    unittest.main()
