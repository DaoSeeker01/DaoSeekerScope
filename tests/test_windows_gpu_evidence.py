"""Synthetic DXGI report guard tests; these are not hardware evidence."""

import copy
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import native_smoke


def available(value: Any) -> dict[str, Any]:
    return dict(
        value=value, availability="available", source="dxgi", observed_at=1, reason=None
    )


class GpuGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = {
            "static_info": {
                "gpus": available(
                    [
                        {
                            "name": available("Unit adapter"),
                            "dedicated_memory_bytes": available(0),
                        },
                        {
                            "name": available("Unit adapter 2"),
                            "dedicated_memory_bytes": available(2**64 - 1),
                        },
                    ]
                )
            }
        }

    def test_exact_memory_without_retaining_names(self) -> None:
        summary = native_smoke.check_windows_gpu(self.snapshot)
        self.assertEqual(summary["dedicated_video_memory_bytes"], [0, 2**64 - 1])
        self.assertEqual(summary["names_available"], 2)
        self.assertNotIn("Unit adapter", str(summary))

    def test_empty_is_available_and_missing_does_not_become_empty(self) -> None:
        self.snapshot["static_info"]["gpus"] = available([])
        self.assertEqual(native_smoke.check_windows_gpu(self.snapshot)["entries"], 0)
        for state, reason in [
            ("restricted", "permission_denied"),
            ("unsupported", "not_supported"),
            ("unavailable", "timeout"),
        ]:
            self.snapshot["static_info"]["gpus"] = dict(
                value=None,
                availability=state,
                source="dxgi",
                observed_at=None,
                reason=reason,
            )
            self.assertNotIn("entries", native_smoke.check_windows_gpu(self.snapshot))

    def test_invalid_memory_metadata(self) -> None:
        for key, value in [
            ("value", -1),
            ("value", 2**64),
            ("value", True),
            ("source", "sysinfo"),
            ("reason", "unknown"),
            ("observed_at", None),
            ("availability", "unavailable"),
        ]:
            bad = copy.deepcopy(self.snapshot)
            bad["static_info"]["gpus"]["value"][0]["dedicated_memory_bytes"][key] = (
                value
            )
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_windows_gpu(bad)

    def test_invalid_name_and_field_isolation(self) -> None:
        for value in ["", "\n", "x" * 128, "\ud800", None]:
            bad = copy.deepcopy(self.snapshot)
            bad["static_info"]["gpus"]["value"][0]["name"]["value"] = value
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_windows_gpu(bad)
        self.snapshot["static_info"]["gpus"]["value"][0]["name"] = dict(
            value=None,
            availability="unavailable",
            source="dxgi",
            observed_at=None,
            reason="invalid_data",
        )
        summary = native_smoke.check_windows_gpu(self.snapshot)
        self.assertEqual(summary["names_available"], 1)
        self.assertEqual(summary["dedicated_video_memory_bytes"], [0, 2**64 - 1])

    def test_collection_source_limit_and_missing_metadata(self) -> None:
        for key, value in [
            ("source", "sysinfo"),
            ("value", [{}] * 129),
            ("reason", "unknown"),
            ("observed_at", True),
            ("availability", "unsupported"),
        ]:
            bad = copy.deepcopy(self.snapshot)
            bad["static_info"]["gpus"][key] = value
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_windows_gpu(bad)
        self.snapshot["static_info"]["gpus"] = dict(
            value=None,
            availability="unsupported",
            source="custom",
            observed_at=None,
            reason="not_supported",
        )
        self.assertEqual(
            native_smoke.check_windows_gpu(self.snapshot)["source"], "custom"
        )


if __name__ == "__main__":
    unittest.main()
