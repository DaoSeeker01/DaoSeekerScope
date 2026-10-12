"""Synthetic storage guards; not physical or kernel-permission evidence."""

import copy
import json
from pathlib import Path
import sys
import unittest
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import linux_storage_smoke as storage
import native_smoke


class StorageGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = json.loads(
            (native_smoke.ROOT / "tests/fixtures/snapshot-v1.json").read_text("utf-8")
        )
        self.snapshot["dynamic"]["memory_available_bytes"] = self.observed(4096)
        self.entry: dict[str, Any] = {
            "name": {
                "value": None,
                "source": "sysfs",
                "availability": "restricted",
                "reason": "privacy_redacted",
                "observed_at": None,
            },
            "capacity_bytes": self.observed(4096),
        }
        self.snapshot["static_info"]["storage"] = self.observed([self.entry])

    @staticmethod
    def observed(value: Any) -> dict[str, Any]:
        return {
            "value": value,
            "source": "sysfs",
            "availability": "available",
            "observed_at": 1,
            "reason": None,
        }

    def test_zero_is_valid_but_insufficient_native_evidence(self) -> None:
        self.entry["capacity_bytes"]["value"] = 0
        storage.verify(self.snapshot, [("available", None, 0)])
        with self.assertRaises(native_smoke.ValidationFailure):
            native_smoke.check_real_storage(
                {"static.storage": self.snapshot["static_info"]["storage"]}
            )
        self.entry["capacity_bytes"]["value"] = 4096
        native_smoke.check_real_storage(
            {"static.storage": self.snapshot["static_info"]["storage"]}
        )

    def test_privacy_metadata_and_units_are_checked(self) -> None:
        for field, key, value in [
            ("name", "value", "private-label"),
            ("capacity_bytes", "source", "custom"),
            ("capacity_bytes", "observed_at", None),
            ("capacity_bytes", "value", True),
        ]:
            bad = copy.deepcopy(self.snapshot)
            bad["static_info"]["storage"]["value"][0][field][key] = value
            with self.assertRaises(native_smoke.ValidationFailure):
                storage.verify(bad, [("available", None, 4096)])
        for bad_capacity in [True, -1, 4097, 2**64]:
            self.entry["capacity_bytes"]["value"] = bad_capacity
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_real_storage(
                    {"static.storage": self.snapshot["static_info"]["storage"]}
                )

    def test_empty_and_denied_are_distinct_and_not_native_evidence(self) -> None:
        self.snapshot["static_info"]["storage"] = self.observed([])
        storage.verify(self.snapshot, [])
        with self.assertRaises(native_smoke.ValidationFailure):
            native_smoke.check_real_storage(
                {"static.storage": self.snapshot["static_info"]["storage"]}
            )
        self.snapshot["static_info"]["storage"] = {
            "value": None,
            "source": "sysfs",
            "availability": "restricted",
            "reason": "permission_denied",
            "observed_at": None,
        }
        storage.verify(self.snapshot, storage.DENIED)

    def test_windows_geometry_keeps_exact_bytes_and_distinct_sources(self) -> None:
        collection = self.snapshot["static_info"]["storage"]
        collection["source"] = "setupapi"
        self.entry["name"]["source"] = "win32"
        self.entry["capacity_bytes"]["source"] = "win32"
        self.entry["capacity_bytes"]["value"] = 1
        observations = {"static.storage": collection}
        native_smoke.check_real_storage(observations, "win32")
        for invalid in [0, True, -1, 2**63]:
            self.entry["capacity_bytes"]["value"] = invalid
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_real_storage(observations, "win32")
        self.entry["capacity_bytes"]["value"] = 4096
        for wrong_source in ["custom", "win32", "sysfs"]:
            collection["source"] = wrong_source
            with self.assertRaises(native_smoke.ValidationFailure):
                native_smoke.check_real_storage(observations, "win32")
        collection["source"] = "setupapi"
        with self.assertRaises(native_smoke.ValidationFailure):
            native_smoke.check_real_storage(observations)
        with self.assertRaises(native_smoke.ValidationFailure):
            native_smoke.check_real_storage(observations, "custom")


if __name__ == "__main__":
    unittest.main()
