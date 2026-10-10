"""Report guards: fixtures here are unit inputs, never native machine evidence."""

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import native_smoke


class EvidenceGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads(
            (native_smoke.ROOT / "tests/fixtures/snapshot-v1.json").read_text("utf-8")
        )

    def test_network_report_rejects_names_and_preserves_redacted_counters(self) -> None:
        self.fixture["static_info"]["system"]["os"]["name"] = {
            "availability": "available",
            "value": "Unit OS",
            "source": "custom",
            "observed_at": 1,
            "reason": None,
        }
        self.fixture["dynamic"]["networks"] = {
            "availability": "available",
            "source": "procfs",
            "observed_at": 1,
            "reason": None,
            "value": [
                {
                    "interface_name": {
                        "value": None,
                        "availability": "restricted",
                        "source": "procfs",
                        "observed_at": None,
                        "reason": "privacy_redacted",
                    },
                    "received_bytes": {
                        "value": 0,
                        "availability": "available",
                        "source": "procfs",
                        "observed_at": 1,
                        "reason": None,
                    },
                    "transmitted_bytes": {
                        "value": 2**64 - 1,
                        "availability": "available",
                        "source": "procfs",
                        "observed_at": 1,
                        "reason": None,
                    },
                }
            ],
        }
        selected = native_smoke.check_snapshot(self.fixture)
        self.assertEqual(
            selected["dynamic.networks"], self.fixture["dynamic"]["networks"]
        )
        for key, value in [
            ("value", "private-name"),
            ("availability", "unavailable"),
            ("observed_at", 1),
            ("reason", "unknown"),
        ]:
            bad = copy.deepcopy(self.fixture)
            bad["dynamic"]["networks"]["value"][0]["interface_name"][key] = value
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_snapshot(bad)

    def test_available_minimum_and_privacy_metadata_are_preserved(self) -> None:
        # Golden fixture has no OS read; explicitly supply a unit-only observation.
        self.fixture["static_info"]["system"]["os"]["name"] = {
            "availability": "available",
            "value": "Unit OS",
            "source": "custom",
            "observed_at": 1,
            "reason": None,
        }
        self.assertEqual(
            native_smoke.check_snapshot(self.fixture)["cpu.logical_count"]["value"], 4
        )
        self.assertEqual(
            native_smoke.check_snapshot(self.fixture)["dynamic.batteries"],
            self.fixture["dynamic"]["batteries"],
        )
        for value in [0, -1, True, None, "4"]:
            bad = copy.deepcopy(self.fixture)
            bad["static_info"]["system"]["cpu"]["logical_count"]["value"] = value
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_snapshot(bad)

        for key, value in [
            ("value", "private"),
            ("availability", "unavailable"),
            ("reason", "unknown"),
        ]:
            bad = copy.deepcopy(self.fixture)
            bad["static_info"]["system"]["device"]["serial_number"][key] = value
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_snapshot(bad)

    def test_real_network_gate_distinguishes_sources_and_bad_counter_states(
        self,
    ) -> None:
        for source in ("procfs", "win32", "sysctl"):
            counter = {
                "availability": "available",
                "source": source,
                "value": 0,
                "observed_at": 1,
                "reason": None,
            }
            observations: dict[str, Any] = {
                "dynamic.networks": {
                    "availability": "available",
                    "source": source,
                    "value": [
                        {
                            "received_bytes": counter,
                            "transmitted_bytes": {
                                **counter,
                                "value": 2**64 - 1,
                            },
                        }
                    ],
                }
            }
            native_smoke.check_real_network(observations, source)
            for key, value in [
                ("availability", "restricted"),
                ("source", "custom"),
                ("value", -1),
                ("value", 2**64),
                ("value", True),
                ("observed_at", None),
                ("reason", "unknown"),
            ]:
                bad = copy.deepcopy(observations)
                bad["dynamic.networks"]["value"][0]["received_bytes"][key] = value
                with self.assertRaises(native_smoke.ValidationFailure):
                    native_smoke.check_real_network(bad, source)
            for key, value in [
                ("source", "custom"),
                ("availability", "unsupported"),
                ("value", []),
            ]:
                bad = copy.deepcopy(observations)
                bad["dynamic.networks"][key] = value
                with self.assertRaises(native_smoke.ValidationFailure):
                    native_smoke.check_real_network(bad, source)

    def test_malformed_and_oversized_data_fail(self) -> None:
        for data in [b"null", b"[]", b"bad", b"\xff", b"[" * 512]:
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.decode(data)
        with self.assertRaises(native_smoke.ValidationFailure):
            native_smoke.decode(b" " * (native_smoke.MAX_JSON_BYTES + 1))
        with self.assertRaises(native_smoke.ValidationFailure):
            native_smoke.check_snapshot({})

    def test_process_failure_writes_failed_report_and_returns_nonzero(self) -> None:
        def fail(_directory, report):
            report["checks"]["cli"] = "running"
            raise native_smoke.ValidationFailure("cli: process_failed")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with (
                patch.object(sys, "argv", ["native_smoke", "--output", str(output)]),
                patch.object(native_smoke, "collect", side_effect=fail),
                patch.object(sys, "stdout", io.StringIO()),
            ):
                self.assertEqual(native_smoke.main(), 1)
            report = json.loads(output.read_text("utf-8"))
            self.assertEqual(report["overall"], "failed")
            self.assertEqual(
                report["checks"],
                {"cli": "failed", "c_abi": "not_run", "python_ffi": "not_run"},
            )

    def test_interruption_replaces_previous_success_with_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            output.write_text('{"overall":"passed"}', encoding="utf-8")
            with (
                patch.object(sys, "argv", ["native_smoke", "--output", str(output)]),
                patch.object(native_smoke, "collect", side_effect=KeyboardInterrupt),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    native_smoke.main()
            report = json.loads(output.read_text("utf-8"))
            self.assertEqual(report["overall"], "incomplete")
            self.assertNotIn("artifact_sha256", report)


if __name__ == "__main__":
    unittest.main()
