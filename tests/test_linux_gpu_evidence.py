"""Synthetic GPU report guards; no real driver or device observations."""

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import linux_gpu_smoke
import native_smoke


def observed(value: Any, source: str = "drm") -> dict[str, Any]:
    return dict(
        value=value, availability="available", source=source, reason=None, observed_at=1
    )


class GpuGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = json.loads(
            (native_smoke.ROOT / "tests/fixtures/snapshot-v1.json").read_text("utf-8")
        )
        self.snapshot["dynamic"]["memory_available_bytes"] = observed(4096, "procfs")
        self.entry: dict[str, Any] = dict(
            name=observed("Unit GPU", "sysfs"),
            dedicated_memory_bytes=dict(
                value=None,
                availability="unsupported",
                source="drm",
                reason="not_supported",
                observed_at=None,
            ),
        )
        self.snapshot["static_info"]["gpus"] = observed([self.entry])

    def test_summary_preserves_states_without_retaining_names(self) -> None:
        result = linux_gpu_smoke.verify(
            self.snapshot, [("available", None, "Unit GPU")]
        )
        self.assertEqual(result["gpu_summary"]["entries"], 1)
        self.assertNotIn("Unit GPU", str(result))
        self.entry["name"]["source"] = "procfs"
        self.assertEqual(
            native_smoke.check_linux_gpu(self.snapshot)["names_available"], 1
        )

    def test_memory_must_not_be_promoted_to_zero_or_shared_vram(self) -> None:
        for field, value in [
            ("value", 0),
            ("availability", "available"),
            ("reason", None),
            ("source", "sysfs"),
            ("observed_at", 1),
        ]:
            bad = copy.deepcopy(self.snapshot)
            bad["static_info"]["gpus"]["value"][0]["dedicated_memory_bytes"][field] = (
                value
            )
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_linux_gpu(bad)

    def test_invalid_names_sources_and_metadata_are_rejected(self) -> None:
        for key, value in [
            ("value", ""),
            ("value", "a\0b"),
            ("value", "x" * 4097),
            ("value", "\ud800"),
            ("source", "drm"),
            ("observed_at", True),
            ("reason", "unknown"),
        ]:
            bad = copy.deepcopy(self.snapshot)
            bad["static_info"]["gpus"]["value"][0]["name"][key] = value
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_linux_gpu(bad)

    def test_empty_absent_restricted_and_unsupported_name_stay_distinct(self) -> None:
        self.snapshot["static_info"]["gpus"] = observed([])
        self.assertEqual(native_smoke.check_linux_gpu(self.snapshot)["entries"], 0)
        for state, reason in [
            ("unavailable", "not_present"),
            ("restricted", "permission_denied"),
        ]:
            self.snapshot["static_info"]["gpus"] = dict(
                value=None,
                availability=state,
                source="drm",
                reason=reason,
                observed_at=None,
            )
            self.assertNotIn("entries", native_smoke.check_linux_gpu(self.snapshot))
        self.entry["name"] = dict(
            value=None,
            availability="unsupported",
            source="drm",
            reason="not_supported",
            observed_at=None,
        )
        self.snapshot["static_info"]["gpus"] = observed([self.entry])
        self.assertEqual(
            native_smoke.check_linux_gpu(self.snapshot)["names_available"], 0
        )

    def test_container_guard_rejects_wrong_expected_model_and_unrelated_failure(
        self,
    ) -> None:
        with self.assertRaises(native_smoke.ValidationFailure):
            linux_gpu_smoke.verify(self.snapshot, [("available", None, "Wrong model")])
        self.snapshot["dynamic"]["memory_available_bytes"]["availability"] = (
            "unavailable"
        )
        with self.assertRaises(native_smoke.ValidationFailure):
            linux_gpu_smoke.verify(self.snapshot, [("available", None, "Unit GPU")])


if __name__ == "__main__":
    unittest.main()
