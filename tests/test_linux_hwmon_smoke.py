"""Evidence guards with synthetic snapshots; no Docker or physical sensors."""

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import linux_hwmon_smoke as smoke


def observed(value=None, state="available", reason=None):
    return {
        "value": value,
        "availability": state,
        "reason": reason,
        "source": "hwmon",
        "observed_at": 1000 if state == "available" else None,
    }


def snapshot():
    data = json.loads(
        (smoke.ROOT / "tests/fixtures/snapshot-v1.json").read_text("utf-8")
    )
    data["dynamic"]["memory_available_bytes"] = {**observed(512), "source": "procfs"}
    data["dynamic"]["sensors"] = observed(
        [
            {
                "label": observed(None, "restricted", "privacy_redacted"),
                "temperature_celsius": observed(42.5),
            }
        ]
    )
    cap = next(c for c in data["capabilities"] if c["field"] == "sensors")
    cap.update(level="partial", source="hwmon", reason=None)
    return data


class EvidenceGuards(unittest.TestCase):
    def test_nvme_missing_kelvin_is_not_a_published_temperature(self):
        data = snapshot()
        field = data["dynamic"]["sensors"]["value"][0]["temperature_celsius"]
        for expected in [smoke.ABSENT, smoke.INVALID]:
            field.update(observed(-273.15))
            with self.assertRaises(smoke.ValidationFailure):
                smoke.verify(data, [expected])
            field.update(observed(None, expected[0], expected[1]))
            smoke.verify(data, [expected])
        field.update(observed(0.0))
        smoke.verify(data, [("available", None, 0.0)])

    def test_states_and_empty_or_unsupported_are_distinct(self):
        good = ("available", None, 42.5)
        self.assertTrue(smoke.verify(snapshot(), [good])["schema_validated"])
        for values, expected in [
            ([], []),
            (
                [
                    {
                        "label": observed(None, "restricted", "privacy_redacted"),
                        "temperature_celsius": observed(
                            None, "unsupported", "not_supported"
                        ),
                    }
                ],
                [smoke.UNSUPPORTED],
            ),
        ]:
            data = snapshot()
            data["dynamic"]["sensors"] = observed(values)
            smoke.verify(data, expected)
        for state, reason, value in [smoke.DENIED, smoke.INVALID, smoke.ABSENT]:
            data = snapshot()
            data["dynamic"]["sensors"] = observed(value, state, reason)
            cap = next(c for c in data["capabilities"] if c["field"] == "sensors")
            cap.update(
                level="restricted" if state == "restricted" else "partial",
                reason=reason,
            )
            smoke.verify(data, (state, reason, value))

    def test_wrong_value_source_time_count_and_capability_fail(self):
        base = snapshot()
        variants = []
        for field, value in [
            ("value", 0.0),
            ("source", "sysinfo"),
            ("observed_at", None),
            ("reason", "unknown"),
        ]:
            data = copy.deepcopy(base)
            data["dynamic"]["sensors"]["value"][0]["temperature_celsius"][field] = value
            variants.append(data)
        data = copy.deepcopy(base)
        data["dynamic"]["sensors"]["value"] = []
        variants.append(data)
        data = copy.deepcopy(base)
        next(c for c in data["capabilities"] if c["field"] == "sensors")["level"] = (
            "supported"
        )
        variants.append(data)
        for data in variants:
            with self.assertRaises(smoke.ValidationFailure):
                smoke.verify(data, [("available", None, 42.5)])

    def test_private_label_and_identifier_leak_fail(self):
        for field in ["label", "identifier"]:
            data = snapshot()
            data["dynamic"]["sensors"]["value"][0][field] = observed(smoke.PRIVATE)
            with self.assertRaises(smoke.ValidationFailure):
                smoke.verify(data, [("available", None, 42.5)])

    def test_incomplete_or_failed_process_is_not_acceptance(self):
        for effect in [smoke.ValidationFailure("probe: process_failed"), None]:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "report.json"
                with (
                    patch.object(sys, "argv", ["smoke", "--output", str(output)]),
                    patch.object(smoke, "execute", side_effect=effect),
                    patch.object(sys, "stdout", io.StringIO()),
                ):
                    self.assertEqual(smoke.main(), 1)
                self.assertEqual(
                    json.loads(output.read_text("utf-8"))["overall"], "failed"
                )

    def test_interruption_clears_old_success(self):
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
