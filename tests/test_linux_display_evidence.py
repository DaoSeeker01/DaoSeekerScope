"""Synthetic EDID/display guards; no physical display or driver access."""

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import linux_display_smoke as display
from native_smoke import ROOT, ValidationFailure, check_linux_displays


def observed(value: Any, source: str = "drm") -> dict[str, Any]:
    return dict(
        value=value, availability="available", source=source, observed_at=1, reason=None
    )


def missing(state: str, reason: str, source: str = "sysfs") -> dict[str, Any]:
    return dict(
        value=None, availability=state, source=source, observed_at=None, reason=reason
    )


class DisplayGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = json.loads(
            (ROOT / "tests/fixtures/snapshot-v1.json").read_text("utf-8")
        )
        self.snapshot["dynamic"]["memory_available_bytes"] = observed(4096, "procfs")
        self.entry = dict(
            name=missing("restricted", "privacy_redacted"),
            width_pixels=missing("unsupported", "not_supported", "drm"),
            height_pixels=missing("unsupported", "not_supported", "drm"),
        )
        self.snapshot["static_info"]["displays"] = observed([self.entry])

    def test_default_redacts_and_authorized_summary_does_not_retain_name(self) -> None:
        self.assertEqual(
            display.verify(self.snapshot, [display.REDACTED])["display_summary"][
                "entries"
            ],
            1,
        )
        self.entry["name"] = observed("Unit panel A", "sysfs")
        with self.assertRaises(ValidationFailure):
            check_linux_displays(self.snapshot)
        summary = display.verify(
            self.snapshot, [("available", None, "Unit panel A")], True
        )
        self.assertEqual(summary["display_summary"]["names_available"], 1)
        self.assertNotIn("Unit panel A", str(summary))

    def test_current_resolution_must_never_come_from_modes_or_edid(self) -> None:
        for key, value in [
            ("value", 0),
            ("value", 1920),
            ("availability", "available"),
            ("source", "sysfs"),
            ("observed_at", 1),
            ("reason", None),
        ]:
            bad = copy.deepcopy(self.snapshot)
            bad["static_info"]["displays"]["value"][0]["width_pixels"][key] = value
            with self.assertRaises(ValidationFailure):
                check_linux_displays(bad)

    def test_empty_restricted_absent_and_unknown_are_distinct(self) -> None:
        self.snapshot["static_info"]["displays"] = observed([])
        self.assertEqual(check_linux_displays(self.snapshot)["entries"], 0)
        for state, reason in [
            ("restricted", "permission_denied"),
            ("unavailable", "not_present"),
            ("unavailable", "temporarily_unavailable"),
        ]:
            self.snapshot["static_info"]["displays"] = missing(state, reason, "drm")
            self.assertNotIn("entries", check_linux_displays(self.snapshot))

    def test_authorized_names_sources_limits_and_metadata(self) -> None:
        for key, value in [
            ("value", "x" * 14),
            ("value", "A\0B"),
            ("value", "🌟"),
            ("value", ""),
            ("observed_at", True),
            ("reason", "unknown"),
            ("source", "drm"),
        ]:
            self.entry["name"] = observed("Unit panel", "sysfs")
            self.entry["name"][key] = value
            with self.assertRaises(ValidationFailure):
                check_linux_displays(self.snapshot, True)
        self.entry["name"] = missing("restricted", "permission_denied")
        self.assertEqual(
            check_linux_displays(self.snapshot, True)["names_available"], 0
        )

    def test_campaign_guard_rejects_wrong_name_serial_or_unrelated_failure(
        self,
    ) -> None:
        with self.assertRaises(ValidationFailure):
            display.verify(self.snapshot, [("available", None, "fake")], True)
        self.snapshot["dynamic"]["memory_available_bytes"] = missing(
            "unavailable", "invalid_data", "procfs"
        )
        with self.assertRaises(ValidationFailure):
            display.verify(self.snapshot, [display.REDACTED])
        self.snapshot["dynamic"]["memory_available_bytes"] = observed(4096, "procfs")
        self.snapshot["static_info"]["system"]["device"]["serial_number"] = observed(
            "SYNTH_SERIAL", "sysfs"
        )
        with self.assertRaises(ValidationFailure):
            display.verify(self.snapshot, [display.REDACTED])
        raw = display.edid(b"Unit panel")
        self.assertEqual(len(raw), 128)
        self.assertEqual(sum(raw) % 256, 0)


if __name__ == "__main__":
    unittest.main()
