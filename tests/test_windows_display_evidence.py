"""Synthetic CCD report guards, not real display or permission evidence."""

import copy
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import native_smoke


def observed(value: Any) -> dict[str, Any]:
    return dict(
        value=value,
        availability="available",
        source="win32",
        reason=None,
        observed_at=1,
    )


def missing(state: str, reason: str) -> dict[str, Any]:
    return dict(
        value=None, availability=state, source="win32", reason=reason, observed_at=None
    )


class DisplayGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.entry = dict(
            name=observed("Unit panel"),
            width_pixels=observed(1920),
            height_pixels=observed(1080),
        )
        self.snapshot = dict(static_info=dict(displays=observed([self.entry])))

    def test_summary_redacts_name_and_retains_signal_dimensions(self) -> None:
        summary = native_smoke.check_windows_displays(self.snapshot)
        self.assertEqual(summary["entries"], 1)
        self.assertEqual(summary["names_available"], 1)
        self.assertEqual(summary["dimensions"][0]["width_pixels"]["value"], 1920)
        self.assertNotIn("Unit panel", str(summary))

    def test_empty_restricted_unsupported_and_invalid_are_distinct(self) -> None:
        self.snapshot["static_info"]["displays"] = observed([])
        self.assertEqual(
            native_smoke.check_windows_displays(self.snapshot)["entries"], 0
        )
        for state, reason in [
            ("restricted", "permission_denied"),
            ("unsupported", "not_supported"),
            ("unavailable", "invalid_data"),
        ]:
            self.snapshot["static_info"]["displays"] = missing(state, reason)
            self.assertNotIn(
                "entries", native_smoke.check_windows_displays(self.snapshot)
            )

    def test_dimensions_are_positive_u32_and_pair_states_match(self) -> None:
        for value in [0, -1, 0x100000000, True, None, 1.5]:
            self.entry["width_pixels"] = observed(value)
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_windows_displays(self.snapshot)
        self.entry["width_pixels"] = missing("unavailable", "not_present")
        with self.assertRaises(native_smoke.ValidationFailure):
            native_smoke.check_windows_displays(self.snapshot)
        self.entry["height_pixels"] = missing("unavailable", "not_present")
        self.assertEqual(
            native_smoke.check_windows_displays(self.snapshot)["entries"], 1
        )

    def test_names_and_missing_metadata_are_strict(self) -> None:
        for value in ["", " ", "x\0y", "\ud800", "🌟" * 32, "x" * 64]:
            self.entry["name"] = observed(value)
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_windows_displays(self.snapshot)
        self.entry["name"] = missing("restricted", "permission_denied")
        self.assertEqual(
            native_smoke.check_windows_displays(self.snapshot)["names_available"], 0
        )

    def test_wrong_sources_and_collection_metadata_fail(self) -> None:
        for key, value in [
            ("source", "custom"),
            ("observed_at", True),
            ("reason", "unknown"),
            ("value", None),
        ]:
            bad = copy.deepcopy(self.snapshot)
            bad["static_info"]["displays"][key] = value
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_windows_displays(bad)


if __name__ == "__main__":
    unittest.main()
