"""Synthetic CLI text guards; not device evidence or a public text parser."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import native_smoke as smoke


class StorageText(unittest.TestCase):
    def text(
        self, source: str, capacity: str = "4.00 KiB (4096 bytes; Sysfs)"
    ) -> bytes:
        return (
            "Storage: 2 entries\n"
            "Storage entry 1\n"
            f"Name: Restricted ({source}, Some(PrivacyRedacted))\n"
            f"Capacity: Restricted ({source}, Some(PermissionDenied))\n"
            "Storage entry 2\n"
            f"Name: Restricted ({source}, Some(PrivacyRedacted))\n"
            f"Capacity: {capacity}\n"
            "Entries are OS objects, including virtual devices; capacities may overlap.\n"
        ).encode()

    def test_real_guard_keeps_exact_bytes_and_isolates_field_failure(self) -> None:
        for source in ["Win32", "Sysfs", "Iokit"]:
            result = smoke.check_storage_text(
                self.text(source, f"4.00 KiB (4096 bytes; {source})"), source
            )
            self.assertEqual(result["entry_count"], 2)
            self.assertEqual(result["available_capacity_bytes"], [4096])
            self.assertTrue(result["names_redacted"])
            self.assertNotIn("raw_text", result)
        for source in ["Win32", "Iokit"]:
            smoke.check_storage_text(
                self.text(source, f"1 B (1 bytes; {source})"), source
            )

    def test_privacy_source_layout_and_overflow_are_rejected(self) -> None:
        valid = self.text("Sysfs")
        for data in [
            valid.replace(
                b"Name: Restricted (Sysfs, Some(PrivacyRedacted))",
                b"Name: private-device",
            ),
            valid.replace(b"Storage: 2", b"Storage: 3"),
            valid.replace(b"Storage entry 2", b"Storage entry 9"),
            valid.replace(b"4096 bytes", b"18446744073709551616 bytes"),
            valid.replace(b"4096 bytes; Sysfs", b"4096 bytes; Iokit"),
            valid.replace(b"4096 bytes", b"-1 bytes"),
            valid.replace(b"4.00 KiB", b"4.00 GB"),
            valid.replace(b"capacities may overlap", b"physical total"),
            b"\xff",
        ]:
            with self.assertRaises(smoke.ValidationFailure):
                smoke.check_storage_text(data, "Sysfs")
        with self.assertRaises(smoke.ValidationFailure):
            smoke.check_storage_text(
                self.text("Iokit", "8.00 EiB (9223372036854775808 bytes; Iokit)"),
                "Iokit",
            )

    def test_zero_empty_missing_and_oversize_are_not_real_read_evidence(self) -> None:
        for data in [
            self.text("Sysfs", "0 B (0 bytes; Sysfs)"),
            b"Storage: 0 entries\nNo storage entries visible to this backend.\n",
            b"Storage: Unsupported (Custom, Some(NotSupported))\n",
            b"x" * (smoke.MAX_JSON_BYTES + 1),
        ]:
            with self.assertRaises(smoke.ValidationFailure):
                smoke.check_storage_text(data, "Sysfs")


if __name__ == "__main__":
    unittest.main()
