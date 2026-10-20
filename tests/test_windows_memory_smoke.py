"""Evidence guard fixtures, not native Windows failure injection."""

import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import windows_memory_smoke as memory


def field(value: int) -> dict:
    return dict(
        value=value,
        availability="available",
        source="win32",
        observed_at=1,
        reason=None,
    )


class MemoryEvidence(unittest.TestCase):
    def test_observed_source_state_time_and_zero(self) -> None:
        snapshot: dict = dict(
            schema_version=1,
            static_info=dict(system=dict(memory=dict(total_usable_bytes=field(100)))),
            dynamic=dict(memory_available_bytes=field(0)),
        )
        self.assertEqual(memory.check_snapshot(snapshot)["available"]["value"], 0)
        for key, value in [
            ("value", True),
            ("value", -1),
            ("value", 101),
            ("value", 2**64),
            ("source", "sysinfo"),
            ("observed_at", None),
            ("availability", "unavailable"),
            ("reason", "permission_denied"),
        ]:
            bad = copy.deepcopy(snapshot)
            bad["dynamic"]["memory_available_bytes"][key] = value
            with self.assertRaises(ValueError):
                memory.check_snapshot(bad)
        snapshot["static_info"]["system"]["memory"]["total_usable_bytes"] = field(0)
        with self.assertRaises(ValueError):
            memory.check_snapshot(snapshot)

    def test_sdk_bounds_layout_and_command_sequence(self) -> None:
        sample = dict(
            status=0,
            struct_size=64,
            calls=2,
            held_bytes=memory.PRESSURE,
            total=100,
            available=0,
        )
        memory.check_sdk(sample, 2, memory.PRESSURE)
        for key, value in [
            ("status", 5),
            ("status", False),
            ("struct_size", 32),
            ("calls", 1),
            ("held_bytes", 0),
            ("total", 0),
            ("available", 101),
            ("available", -1),
        ]:
            bad = {**sample, key: value}
            with self.assertRaises(ValueError):
                memory.check_sdk(bad, 2, memory.PRESSURE)

    def test_failure_or_interrupt_replaces_stale_success_and_keeps_partial_phases(
        self,
    ) -> None:
        for failure, expected, code in [
            (ValueError("private error"), "failed", 1),
            (KeyboardInterrupt(), "interrupted", 130),
        ]:
            with tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / "report.json"
                output.write_text('{"overall":"passed"}')

                def fail(report: dict) -> None:
                    report["phases"]["baseline"] = {"status": "passed"}
                    raise failure

                with (
                    patch.object(sys, "argv", ["probe", "--output", str(output)]),
                    patch.object(memory, "collect", side_effect=fail),
                    patch.object(sys, "stdout", io.StringIO()),
                ):
                    self.assertEqual(memory.main(), code)
                report = json.loads(output.read_text())
                self.assertEqual(report["overall"], expected)
                self.assertIn("baseline", report["phases"])
                self.assertNotIn("private", json.dumps(report))
