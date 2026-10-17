"""Synthetic guards; physical macOS APIs are tested separately by native CI."""

import copy
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from native_smoke import ROOT, ValidationFailure, check_macos_displays
from macos_display_probe import compare, error
import macos_display_probe as probe_script


def available(value: Any) -> dict[str, Any]:
    return dict(
        value=value,
        availability="available",
        source="apple_api",
        observed_at=1,
        reason=None,
    )


def missing(reason: str, state: str = "unavailable") -> dict[str, Any]:
    return dict(
        value=None,
        availability=state,
        source="apple_api",
        observed_at=None,
        reason=reason,
    )


class MacosDisplayGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = json.loads(
            (ROOT / "tests/fixtures/snapshot-v1.json").read_text("utf-8")
        )
        self.entry = dict(
            name=missing("not_supported", "unsupported"),
            width_pixels=available(3840),
            height_pixels=available(2160),
        )
        self.snapshot["static_info"]["displays"] = available([self.entry])

    def report(self) -> dict[str, Any]:
        summary = check_macos_displays(self.snapshot)
        return dict(
            overall="passed",
            git_dirty=False,
            git_revision="synthetic",
            observations={
                k: {"static.display_summary": copy.deepcopy(summary)}
                for k in ("cli", "c_abi")
            },
        )

    def test_mode_pixels_have_explicit_metadata_and_never_fabricate_names(self) -> None:
        summary = check_macos_displays(self.snapshot)
        self.assertEqual(summary["dimensions_available"], 1)
        self.assertEqual(summary["names_available"], 0)
        self.entry["name"] = available("1234")
        with self.assertRaises(ValidationFailure):
            check_macos_displays(self.snapshot)

    def test_zero_overflow_partial_pairs_and_wrong_sources_are_rejected(self) -> None:
        for key, value in [
            ("value", 0),
            ("value", 2**32),
            ("value", True),
            ("source", "sysctl"),
            ("observed_at", True),
            ("reason", "unknown"),
        ]:
            bad = copy.deepcopy(self.snapshot)
            bad["static_info"]["displays"]["value"][0]["width_pixels"][key] = value
            with self.assertRaises(ValidationFailure):
                check_macos_displays(bad)
        for key in ("width_pixels", "height_pixels"):
            self.entry[key] = missing("temporarily_unavailable")
        self.assertEqual(check_macos_displays(self.snapshot)["dimensions_available"], 0)

    def test_empty_unavailable_and_unsupported_are_not_device_read_success(
        self,
    ) -> None:
        self.snapshot["static_info"]["displays"] = available([])
        self.assertEqual(check_macos_displays(self.snapshot)["entries"], 0)
        for code in (1002, 1006, 1011, 1000):
            state, reason = error(code)
            self.snapshot["static_info"]["displays"] = missing(reason, state)
            self.assertNotIn("entries", check_macos_displays(self.snapshot))
            probe = dict(status=code, entries=None, dimensions=None)
            self.assertEqual(compare(probe, self.report())["status"], "passed")

    def test_independent_sdk_comparison_rejects_mismatch_and_extra_identifiers(
        self,
    ) -> None:
        probe = dict(
            status=0, entries=1, dimensions=[dict(width=3840, height=2160, reason=None)]
        )
        self.assertEqual(compare(probe, self.report())["status"], "passed")
        for bad in [
            dict(probe, id=1),
            dict(probe, entries=2),
            dict(probe, status=True),
            dict(probe, dimensions=[dict(width=1920, height=1080, reason=None)]),
            dict(probe, dimensions=[dict(width=0, height=0, reason=None)]),
        ]:
            with self.assertRaises(ValidationFailure):
                compare(bad, self.report())

    def test_sdk_missing_mode_and_dirty_or_failed_reports_are_distinct(self) -> None:
        for path, value in [
            ("source", "sysctl"),
            ("observed_at", True),
            ("availability", "unsupported"),
        ]:
            bad = self.report()
            bad["observations"]["cli"]["static.display_summary"]["dimensions"][0][
                "width_pixels"
            ][path] = value
            with self.assertRaises(ValidationFailure):
                compare(
                    dict(
                        status=0,
                        entries=1,
                        dimensions=[dict(width=3840, height=2160, reason=None)],
                    ),
                    bad,
                )
        for key in ("width_pixels", "height_pixels"):
            self.entry[key] = missing("invalid_data")
        probe = dict(
            status=0,
            entries=1,
            dimensions=[dict(width=None, height=None, reason="invalid_data")],
        )
        self.assertEqual(compare(probe, self.report())["status"], "passed")
        for key, value in [("git_dirty", True), ("overall", "incomplete")]:
            with self.assertRaises(ValidationFailure):
                compare(probe, dict(self.report(), **{key: value}))

    def test_failed_comparison_replaces_old_success_and_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "target").mkdir()
            output = root / "target/macos-display-comparison.json"
            output.write_text('{"status":"passed"}', "utf-8")
            with (
                patch.object(probe_script, "ROOT", root),
                patch.object(probe_script, "read", side_effect=[self.report(), {}]),
                patch.object(
                    probe_script.subprocess, "check_output", return_value="synthetic\n"
                ),
            ):
                self.assertEqual(probe_script.main(), 1)
            self.assertEqual(json.loads(output.read_text("utf-8"))["status"], "failed")


if __name__ == "__main__":
    unittest.main()
