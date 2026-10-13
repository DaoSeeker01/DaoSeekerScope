"""CLI presentation fixtures only; these do not prove hardware availability."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import native_smoke as smoke


class CliText(unittest.TestCase):
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
