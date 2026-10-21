"""Memory evidence guards reject fabricated success and preserve failure reports."""

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
    "mach_memory", ROOT / "scripts/macos_memory_smoke.py"
)
assert spec and spec.loader
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)


def field(value: int, source: str) -> dict:
    return dict(
        value=value, source=source, availability="available", observed_at=1, reason=None
    )


def sdk() -> dict:
    return dict(
        status="passed",
        calls=1,
        total=65536,
        page_size=4096,
        active=1,
        inactive=2,
        free=3,
        speculative=2,
        available=24576,
        requested_words=38,
        returned_words=38,
        sdk_struct_size=160,
        rev1_prefix_bytes=152,
        released_host=True,
    )


class MachMemoryEvidenceTests(unittest.TestCase):
    def test_field_domains_sources_missing_states_and_genuine_zero(self) -> None:
        self.assertEqual(memory.observed(field(0, "apple_api"), "apple_api"), 0)
        self.assertEqual(
            memory.observed(field(2**64 - 1, "sysctl"), "sysctl", True), 2**64 - 1
        )
        for changes in (
            dict(value=True),
            dict(value=-1),
            dict(value=2**64),
            dict(value=1.0),
            dict(value=None),
            dict(source="sysinfo"),
            dict(availability="restricted"),
            dict(reason="permission_denied"),
            dict(observed_at=None),
            dict(observed_at=True),
        ):
            with self.assertRaises(ValueError):
                memory.observed(dict(field(100, "apple_api"), **changes), "apple_api")
        with self.assertRaises(ValueError):
            memory.observed(field(0, "sysctl"), "sysctl", True)

    def test_sdk_checks_revision_prefix_units_cleanup_and_no_double_speculative(
        self,
    ) -> None:
        memory.check_sdk(sdk(), 1)
        memory.check_sdk(dict(sdk(), sdk_struct_size=152), 1)
        memory.check_sdk(
            dict(sdk(), active=0, inactive=0, free=0, speculative=0, available=0), 1
        )
        for changes in (
            dict(returned_words=37),
            dict(requested_words=40),
            dict(rev1_prefix_bytes=160),
            dict(sdk_struct_size=144),
            dict(sdk_struct_size=153),
            dict(released_host=False),
            dict(released_host=1),
            dict(status="failed"),
            dict(calls=2),
            dict(calls=True),
            dict(page_size=0),
            dict(page_size=3),
            dict(active=True),
            dict(free=-1),
            dict(active=2**32),
            dict(speculative=4),
            dict(available=32768),
            dict(total=24575),
            dict(total=2**64),
            dict(page_size=1 << 63),
        ):
            with self.assertRaises(ValueError):
                memory.check_sdk(dict(sdk(), **changes), 1)
        large = dict(
            sdk(),
            active=2**32 - 1,
            inactive=2**32 - 1,
            free=2**32 - 1,
            speculative=0,
            total=2**64 - 1,
            available=3 * (2**32 - 1) * 4096,
        )
        memory.check_sdk(large, 1)

    def test_snapshot_checks_semantics_without_requiring_volatile_values_to_differ(
        self,
    ) -> None:
        snapshot: dict[str, Any] = dict(
            schema_version=1,
            static_info=dict(
                system=dict(memory=dict(total_usable_bytes=field(65536, "sysctl")))
            ),
            dynamic=dict(memory_available_bytes=field(24576, "apple_api")),
        )
        first = memory.check_snapshot(snapshot)
        self.assertEqual(memory.check_snapshot(snapshot), first)
        for value in (65537, -1, None):
            snapshot["dynamic"]["memory_available_bytes"]["value"] = value
            with self.assertRaises(ValueError):
                memory.check_snapshot(snapshot)
        snapshot["dynamic"]["memory_available_bytes"] = field(0, "apple_api")
        memory.check_snapshot(snapshot)
        snapshot["schema_version"] = True
        with self.assertRaises(ValueError):
            memory.check_snapshot(snapshot)

    def test_failed_or_interrupted_run_overwrites_old_pass_without_private_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            for error, code in [
                (ValueError("private path"), 1),
                (KeyboardInterrupt(), 130),
            ]:
                output.write_text('{"status":"passed"}', encoding="utf-8")

                def fail(report: dict) -> None:
                    self.assertEqual(
                        json.loads(output.read_text("utf-8"))["status"], "failed"
                    )
                    report["observations"] = [
                        {"status": "running", "rust": {"available": {"value": None}}}
                    ]
                    raise error

                with patch.object(memory, "collect", side_effect=fail):
                    self.assertEqual(memory.run(output), code)
                raw = output.read_text("utf-8")
                report = json.loads(raw)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["observations"][0]["status"], "running")
                self.assertNotIn("private path", raw)
                self.assertTrue(
                    any("cached" in limit for limit in report["limitations"])
                )


if __name__ == "__main__":
    unittest.main()
