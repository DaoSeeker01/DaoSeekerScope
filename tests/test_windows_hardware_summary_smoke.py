"""Guard summary evidence against malformed success, hidden IDs and stale reports."""

from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "summary_probe", ROOT / "scripts/windows_hardware_summary_smoke.py"
)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def sdk() -> dict[str, Any]:
    return dict(
        status="passed",
        calls=1,
        queries=6,
        buffer_bytes=4096,
        token_elevated=False,
        fields={
            path: dict(code=0, kind=1, bytes=10, value="Acme") for path in probe.FIELDS
        },
    )


def snapshot() -> dict[str, Any]:
    result: dict[str, Any] = dict(
        schema_version=1,
        static_info={"system": {"device": {}, "motherboard": {}, "firmware": {}}},
        capabilities=[],
    )
    for path in probe.FIELDS:
        _, part, field = path.split(".")
        result["static_info"]["system"][part][field] = dict(
            value="Acme",
            availability="available",
            source="win32",
            observed_at=7,
            reason=None,
        )
        result["capabilities"].append(dict(field=path, level="partial", source="win32"))
    result["static_info"]["system"]["device"]["serial_number"] = dict(
        value=None,
        availability="restricted",
        source="custom",
        observed_at=None,
        reason="privacy_redacted",
    )
    return result


class SummaryEvidenceTests(unittest.TestCase):
    def test_sdk_metadata_is_typed_bounded_and_fixed_whitelist(self) -> None:
        probe.check_sdk(sdk(), 1)
        changes: list[dict[str, Any]] = [
            dict(calls=True),
            dict(calls=2),
            dict(queries=7),
            dict(buffer_bytes=8192),
            dict(token_elevated=0),
            dict(status="failed"),
            dict(fields={}),
        ]
        for change in changes:
            with self.assertRaises(ValueError):
                probe.check_sdk(dict(sdk(), **change), 1)
        extra = sdk()
        extra["fields"]["system.device.serial_number"] = dict(
            code=0, kind=1, bytes=10, value="Acme"
        )
        with self.assertRaises(ValueError):
            probe.check_sdk(extra, 1)

    def test_missing_permission_unsupported_invalid_and_unicode_stay_distinct(
        self,
    ) -> None:
        for code, state, reason in [
            (2, "unavailable", "not_present"),
            (5, "restricted", "permission_denied"),
            (50, "unsupported", "not_supported"),
            (234, "unavailable", "invalid_data"),
            (1018, "unavailable", "temporarily_unavailable"),
            (999, "unavailable", "unknown"),
        ]:
            self.assertEqual(
                probe.expected(dict(code=code, kind=None, bytes=None, value=None)),
                (state, None, reason),
            )
        for text in ["Acme", "观微 🦀", "0", "unKnown"]:
            self.assertEqual(
                probe.expected(
                    dict(
                        code=0,
                        kind=1,
                        bytes=len(text.encode("utf-16-le")) + 2,
                        value=text,
                    )
                ),
                ("available", text, None),
            )
        for text in [
            "",
            "\tAcme",
            "A\0B",
            "Unknown",
            "System Product Name",
            "To Be Filled By O.E.M.",
            "观" * 1500,
        ]:
            self.assertEqual(
                probe.expected(
                    dict(
                        code=0,
                        kind=1,
                        bytes=len(text.encode("utf-16-le")) + 2,
                        value=text,
                    )
                ),
                ("unavailable", None, "invalid_data"),
            )
        for item in [
            dict(code=0, kind=1, bytes=9, value="Acme"),
            dict(code=0, kind=2, bytes=10, value="Acme"),
            dict(code=0, kind=1, bytes=10, value=None),
        ]:
            self.assertEqual(
                probe.expected(item), ("unavailable", None, "invalid_data")
            )
        with self.assertRaises(ValueError):
            probe.expected(dict(code=True, kind=None, bytes=None, value=None))
        with self.assertRaises(ValueError):
            probe.expected(dict(code=5, kind=1, bytes=10, value="Acme"))

    def test_public_fields_capabilities_and_privacy_are_checked(self) -> None:
        original = snapshot()
        probe.compare(original, sdk())
        for key, value in [
            ("source", "sysinfo"),
            ("value", "Other"),
            ("reason", "unknown"),
            ("observed_at", True),
            ("availability", "unsupported"),
        ]:
            bad = copy.deepcopy(original)
            bad["static_info"]["system"]["firmware"]["version"][key] = value
            with self.assertRaises(ValueError):
                probe.compare(bad, sdk())
        bad = copy.deepcopy(original)
        bad["capabilities"][0]["level"] = "supported"
        with self.assertRaises(ValueError):
            probe.compare(bad, sdk())
        bad = copy.deepcopy(original)
        bad["static_info"]["system"]["device"]["serial_number"]["value"] = "sensitive"
        with self.assertRaises(ValueError):
            probe.compare(bad, sdk())

    def test_failed_run_overwrites_success_without_raw_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            output.write_text('{"status":"passed"}', encoding="utf-8")
            with patch.object(
                probe,
                "collect",
                side_effect=RuntimeError("private path and raw system error"),
            ):
                self.assertEqual(probe.run(output), 1)
            self.assertEqual(json.loads(output.read_text())["status"], "failed")
            self.assertNotIn("private", output.read_text())


if __name__ == "__main__":
    unittest.main()
