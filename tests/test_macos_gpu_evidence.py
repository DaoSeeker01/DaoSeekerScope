"""Synthetic Metal report guards; these tests do not access any GPU."""

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
        source="apple_api",
        reason=None,
        observed_at=1,
    )


def missing(state: str, reason: str) -> dict[str, Any]:
    return dict(
        value=None,
        availability=state,
        source="apple_api",
        reason=reason,
        observed_at=None,
    )


class MetalGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.entry = dict(
            name=observed("Unit 🌟 GPU"),
            dedicated_memory_bytes=missing("not_applicable", "not_present"),
        )
        self.snapshot = dict(static_info=dict(gpus=observed([self.entry])))

    def test_summary_redacts_names_and_keeps_memory_semantics(self) -> None:
        summary = native_smoke.check_macos_gpu(self.snapshot)
        self.assertEqual(summary["names_available"], 1)
        self.assertEqual(summary["unified_memory"], 1)
        self.assertNotIn("Unit", str(summary))
        self.entry["dedicated_memory_bytes"] = missing("unsupported", "not_supported")
        self.assertEqual(
            native_smoke.check_macos_gpu(self.snapshot)["dedicated_memory_unsupported"],
            1,
        )

    def test_no_fabricated_capacity_or_budget(self) -> None:
        for capacity in [0, 123456, None]:
            bad = copy.deepcopy(self.snapshot)
            bad["static_info"]["gpus"]["value"][0]["dedicated_memory_bytes"] = observed(
                capacity
            )
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_macos_gpu(bad)

    def test_names_are_bounded_utf16_and_strict_unicode(self) -> None:
        for value in ["", " \n", "x\0y", "\ud800", "🌟" * 513, "x" * 1025]:
            self.entry["name"] = observed(value)
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_macos_gpu(self.snapshot)
        self.entry["name"] = observed("🌟" * 512)
        self.assertEqual(
            native_smoke.check_macos_gpu(self.snapshot)["names_available"], 1
        )

    def test_empty_invalid_and_failed_field_are_distinct(self) -> None:
        self.entry["name"] = missing("unavailable", "invalid_data")
        self.assertEqual(
            native_smoke.check_macos_gpu(self.snapshot)["names_available"], 0
        )
        self.snapshot["static_info"]["gpus"] = observed([])
        self.assertEqual(native_smoke.check_macos_gpu(self.snapshot)["entries"], 0)
        self.snapshot["static_info"]["gpus"] = missing("unavailable", "invalid_data")
        self.assertNotIn("entries", native_smoke.check_macos_gpu(self.snapshot))

    def test_wrong_source_time_reason_and_missing_keys_fail(self) -> None:
        for key, value in [
            ("source", "custom"),
            ("observed_at", True),
            ("reason", "unknown"),
        ]:
            self.entry["name"] = observed("GPU")
            self.entry["name"][key] = value
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_macos_gpu(self.snapshot)
        del self.entry["name"]["source"]
        with self.assertRaises(native_smoke.ValidationFailure):
            native_smoke.check_macos_gpu(self.snapshot)


if __name__ == "__main__":
    unittest.main()
