"""CLI presentation fixtures only; these do not prove hardware availability."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import native_smoke as smoke


class CliText(unittest.TestCase):
    def test_display_pixel_meaning_and_redacted_evidence(self) -> None:
        footer = (
            "Entries are OS display views, not a physical monitor count.\n"
            "Pixel dimensions do not identify panel-native resolution.\n"
        )
        for source, prefix, name in [
            ("Win32", "Signal ", "Fixture screen (Win32)"),
            ("AppleApi", "Mode ", "Unsupported (AppleApi, Some(NotSupported))"),
            ("Custom", "", "Fixture screen (Custom)"),
        ]:
            width = prefix + "width" if prefix else "Width"
            height = prefix + "height" if prefix else "Height"
            data = (
                f"Displays: 1 entries ({source})\nDisplay entry 1\nName: {name}\n"
                f"{width} pixels: 1920 ({source})\n{height} pixels: 1080 ({source})\n"
                + footer
            ).encode()
            result = smoke.check_cli_text("display", data)
            self.assertEqual(result["entry_count"], 1)
            self.assertEqual(
                result["available_fields"], 2 if source == "AppleApi" else 3
            )
            self.assertEqual(len(result["output_sha256"]), 64)
            self.assertNotIn("Fixture", str(result))
            for bad in [
                data.replace(b"1920", b"0"),
                data.replace(b"1920", b"4294967296"),
                data.replace(b"1920", b"NaN"),
                data.replace(b"1920", b"-1"),
                data.replace(b"Display entry 1", b"Display entry 2"),
                data.replace(b"Displays: 1", b"Displays: 2"),
                data.replace(b"pixels: 1920", b"pixels: 1920x1080"),
                data.replace(b"\nName: ", b"\nName: \x1b[31m"),
                data + b"extra\n",
            ]:
                with self.assertRaises(smoke.ValidationFailure):
                    smoke.check_cli_text("display", bad)
            if prefix:
                with self.assertRaises(smoke.ValidationFailure):
                    smoke.check_cli_text("display", data.replace(prefix.encode(), b""))

    def test_display_privacy_missing_dimensions_and_empty_are_distinct(self) -> None:
        data = (
            "Displays: 1 entries (Drm)\nDisplay entry 1\n"
            "Name: Restricted (Sysfs, Some(PrivacyRedacted))\n"
            "Width pixels: Unsupported (Drm, Some(NotSupported))\n"
            "Height pixels: Unsupported (Drm, Some(NotSupported))\n"
            "Entries are OS display views, not a physical monitor count.\n"
            "Pixel dimensions do not identify panel-native resolution.\n"
        ).encode()
        result = smoke.check_cli_text("display", data)
        self.assertEqual(result["available_fields"], 0)
        self.assertEqual(result["missing_fields"], 3)
        with self.assertRaises(smoke.ValidationFailure):
            smoke.check_cli_text(
                "display",
                data.replace(
                    b"Restricted (Sysfs, Some(PrivacyRedacted))",
                    b"private-name (Sysfs)",
                ),
            )
        empty = smoke.check_cli_text(
            "display",
            b"Displays: 0 entries (AppleApi)\nNo display entries visible to this backend.\n",
        )
        self.assertEqual(empty["entry_count"], 0)
        self.assertEqual(empty["collection_state"], "Available")
        for state in ["Unavailable", "Restricted", "Unsupported", "NotApplicable"]:
            missing = smoke.check_cli_text(
                "display", f"Displays: {state} (Custom, Some(NotSupported))\n".encode()
            )
            self.assertIsNone(missing["entry_count"])
            self.assertEqual(missing["collection_state"], state)
        for bad in [
            b"",
            b"\xff",
            data[:-1],
            data.replace(b"1 entries", b"1025 entries"),
        ]:
            with self.assertRaises(smoke.ValidationFailure):
                smoke.check_cli_text("display", bad)

    def test_scalar_sources_zero_and_missing_values(self) -> None:
        valid = (
            "OS usable total bytes: 8589934592 (Sysinfo)\n"
            "Installed bytes: Restricted (Sysfs, Some(PermissionDenied))\n"
            "Available bytes: 0 (Procfs)\n"
        ).encode()
        result = smoke.check_cli_text("memory", valid)
        self.assertEqual(result["available_fields"], 2)
        self.assertEqual(result["missing_fields"], 1)
        self.assertNotIn("raw_text", result)
        for bad in [
            valid.replace(b" (Sysinfo)", b""),
            valid.replace(b"Procfs", b"Invented"),
            valid.replace(b"Available bytes: 0", b"Available bytes: -1"),
            valid.replace(
                b"Available bytes: 0", b"Available bytes: 18446744073709551616"
            ),
            valid.replace(b"Some(PermissionDenied)", b"Some(Invented)"),
            valid + b"unexpected\n",
            b"\xff",
            b"x" * (smoke.MAX_JSON_BYTES + 1),
        ]:
            with self.assertRaises(smoke.ValidationFailure):
                smoke.check_cli_text("memory", bad)

    def test_numbered_collections_keep_field_failure_and_empty_missing_distinct(
        self,
    ) -> None:
        battery = (
            "Batteries: 2 entries (Sysfs)\n"
            "Battery entry 1\n"
            "Charge percent: Unavailable (Sysfs, Some(InvalidData))\n"
            "AC power: false (Sysfs)\n"
            "Battery entry 2\n"
            "Charge percent: 0 (Sysfs)\n"
            "AC power: false (Sysfs)\n"
        ).encode()
        self.assertEqual(smoke.check_cli_text("battery", battery)["entry_count"], 2)
        empty = smoke.check_cli_text("gpu", b"GPU: 0 entries (Custom)\n")
        missing = smoke.check_cli_text(
            "gpu", b"GPU: Unsupported (Custom, Some(NotSupported))\n"
        )
        self.assertEqual(empty["entry_count"], 0)
        self.assertIsNone(missing["entry_count"])
        self.assertEqual(empty["collection_state"], "Available")
        self.assertEqual(missing["collection_state"], "Unsupported")
        for bad in [
            battery.replace(b"Battery entry 2", b"Battery entry 1"),
            battery.replace(b"Batteries: 2", b"Batteries: 3"),
            battery.replace(b"Charge percent: 0", b"Charge percent: 101"),
            battery.replace(b"Charge percent: 0", b"Charge percent: NaN"),
            battery.replace(b"AC power: false", b"AC power: 0"),
        ]:
            with self.assertRaises(smoke.ValidationFailure):
                smoke.check_cli_text("battery", bad)

    def test_privacy_and_capability_reasons(self) -> None:
        sensor = (
            "Sensors: 1 entries (Hwmon)\nSensor entry 1\n"
            "Label: Restricted (Hwmon, Some(PrivacyRedacted))\n"
            "Temperature Celsius: -10.5 (Hwmon)\n"
        ).encode()
        self.assertEqual(smoke.check_cli_text("sensors", sensor)["available_fields"], 1)
        with self.assertRaises(smoke.ValidationFailure):
            smoke.check_cli_text(
                "sensors",
                sensor.replace(
                    b"Restricted (Hwmon, Some(PrivacyRedacted))",
                    b"private-label (Hwmon)",
                ),
            )
        caps = b"cpu_usage_percent: Partial (Procfs, TemporarilyUnavailable)\ngpus: Unsupported (Custom, NotSupported)\n"
        smoke.check_cli_text("capabilities", caps)
        with self.assertRaises(smoke.ValidationFailure):
            smoke.check_cli_text(
                "capabilities", caps.replace(b"NotSupported", b"Some(NotSupported)")
            )
        with self.assertRaises(smoke.ValidationFailure):
            smoke.check_cli_text("capabilities", caps.replace(b"Custom", b"Invented"))


if __name__ == "__main__":
    unittest.main()
