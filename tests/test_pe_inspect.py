"""Synthetic PE inputs are inspected as bytes and never loaded or executed."""

from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from cli_bundle import FFI_FILES, digest, write_bundle
import cli_bundle_smoke
import ffi_bundle_smoke
from pe_inspect import Image, inspect_file, inspect_pe

OPTIONAL = 0x98
SECTION = 0x188


def put(data: bytearray, offset: int, value: int, size: int = 4) -> None:
    data[offset : offset + size] = value.to_bytes(size, "little")


def fixture(*, dll: bool = False, name: bytes = b"KERNEL32.dll") -> bytearray:
    """One file-backed section, one import and one RVA-based delay import."""
    data = bytearray(0x1000)
    data[:2] = b"MZ"
    put(data, 60, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    put(data, 0x84, 0x8664, 2)
    put(data, 0x86, 1, 2)
    put(data, 0x94, 240, 2)
    put(data, 0x96, 0x2002 if dll else 2, 2)
    put(data, OPTIONAL, 0x20B, 2)
    put(data, OPTIONAL + 40, 6, 2)
    put(data, OPTIONAL + 48, 6, 2)
    put(data, OPTIONAL + 60, 0x400)
    put(data, OPTIONAL + 68, 2 if dll else 3, 2)
    put(data, OPTIONAL + 108, 16)
    data[SECTION : SECTION + 8] = b".rdata\0\0"
    data[SECTION + 8 : SECTION + 24] = struct.pack("<4I", 0x1000, 0x1000, 0xC00, 0x400)
    data[OPTIONAL + 120 : OPTIONAL + 128] = struct.pack("<2I", 0x1000, 40)
    put(data, 0x400, 0x1400)
    put(data, 0x40C, 0x1100)
    put(data, 0x410, 0x1440)
    data[0x500 : 0x501 + len(name)] = name + b"\0"
    data[OPTIONAL + 216 : OPTIONAL + 224] = struct.pack("<2I", 0x1200, 64)
    put(data, 0x600, 1)
    put(data, 0x604, 0x1300)
    data[0x700:0x70A] = b"USER32.dll"
    return data


class PeTests(unittest.TestCase):
    def test_inventory_and_explicit_evidence_limits(self) -> None:
        for dll in (False, True):
            report = inspect_pe(bytes(fixture(dll=dll)), dll=dll)
            self.assertEqual(report["direct_imports"], ["kernel32.dll"])
            self.assertEqual(report["delay_imports"], ["user32.dll"])
            self.assertEqual(report["declared_os_version"], [6, 0])
            self.assertEqual(report["declared_subsystem_version"], [6, 0])
            self.assertEqual(report["kind"], "dll" if dll else "exe")
            self.assertFalse(report["minimum_windows_verified"])
            self.assertFalse(report["transitive_or_dynamic_loads_inspected"])

    def test_header_and_import_failures(self) -> None:
        cases = [
            (60, 0xFFFFFFFF, 4, "pe_truncated"),
            (0x84, 0xAA64, 2, "pe_machine"),
            (0x86, 97, 2, "pe_sections"),
            (0x94, 111, 2, "pe_optional_size"),
            (0x96, 0x2002, 2, "pe_image_kind"),
            (OPTIONAL, 0x10B, 2, "pe_optional_magic"),
            (OPTIONAL + 60, 0x180, 4, "pe_headers"),
            (OPTIONAL + 68, 2, 2, "pe_subsystem"),
            (OPTIONAL + 108, 17, 4, "pe_directories"),
            (SECTION + 12, 0xFFFFFF00, 4, "pe_section_rva"),
            (SECTION + 20, 0x300, 4, "pe_section_offset"),
            (OPTIONAL + 120, 0, 4, "pe_import_limit"),
            (OPTIONAL + 124, 2581, 4, "pe_import_limit"),
            (OPTIONAL + 124, 20, 4, "pe_import_terminator"),
            (OPTIONAL + 120, 0x1F00, 4, "pe_unmapped_rva"),
            (0x40C, 0, 4, "pe_rva"),
            (0x600, 0, 4, "pe_delay_mode"),
            (0x600, 3, 4, "pe_delay_mode"),
        ]
        for offset, value, size, error in cases:
            with self.subTest(error=error, offset=offset):
                data = fixture()
                put(data, offset, value, size)
                with self.assertRaisesRegex(ValueError, error):
                    inspect_pe(bytes(data), dll=False)

    def test_signatures_truncation_and_no_imports(self) -> None:
        for length in (0, 63, 64, 0x83, 0x97, 0x187, 0xFFF):
            with self.subTest(length=length), self.assertRaises(ValueError):
                inspect_pe(bytes(fixture()[:length]), dll=False)
        for offset in (0, 0x80):
            data = fixture()
            data[offset] ^= 0xFF
            with self.assertRaisesRegex(ValueError, "signature"):
                inspect_pe(bytes(data), dll=False)
        data = fixture()
        data[OPTIONAL + 120 : OPTIONAL + 128] = bytes(8)
        with self.assertRaisesRegex(ValueError, "pe_imports"):
            inspect_pe(bytes(data), dll=False)

    def test_module_names_are_bounded_basenames(self) -> None:
        for name in (b"../bad.dll", b"C:\\bad.dll", b"bad\xff.dll", b"", b"x.exe"):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "pe_module_name"),
            ):
                inspect_pe(bytes(fixture(name=name)), dll=False)
        data = fixture()
        data[0x500:0x700] = b"a" * 512
        with self.assertRaisesRegex(ValueError, "pe_module_terminator"):
            inspect_pe(bytes(data), dll=False)
        # A terminator in the next file region must not complete this section's name.
        put(data, 0x40C, 0x1BFF)
        data[-1] = ord("x")
        with self.assertRaisesRegex(ValueError, "pe_module_terminator"):
            inspect_pe(bytes(data), dll=False)

    def test_section_overlap_and_virtual_tail(self) -> None:
        for rva, offset, error in (
            (0x1800, 0xE00, "pe_overlapping_rva"),
            (0x3000, 0x500, "pe_overlapping_file_range"),
        ):
            data = fixture()
            put(data, 0x86, 2, 2)
            data[SECTION + 48 : SECTION + 64] = struct.pack(
                "<4I", 0x100, rva, 0x100, offset
            )
            with self.assertRaisesRegex(ValueError, error):
                inspect_pe(bytes(data), dll=False)
        image = Image(bytes(fixture()), dll=False)
        with self.assertRaisesRegex(ValueError, "pe_unmapped_rva"):
            image.file_range(0x1C00, 1)
        self.assertEqual(image.file_range(0x100, 1), (0x100, 0x400))

    def test_empty_optional_delay_table(self) -> None:
        data = fixture()
        put(data, OPTIONAL + 108, 2)
        self.assertEqual(inspect_pe(bytes(data), dll=False)["delay_imports"], [])
        data = fixture()
        data[OPTIONAL + 216 : OPTIONAL + 224] = bytes(8)
        self.assertEqual(inspect_pe(bytes(data), dll=False)["delay_imports"], [])

    def test_import_table_limits_and_terminator(self) -> None:
        data = fixture()
        put(data, OPTIONAL + 216, 0x1200)
        put(data, OPTIONAL + 220, 32)
        with self.assertRaisesRegex(ValueError, "pe_import_terminator"):
            inspect_pe(bytes(data), dll=False)
        data = fixture()
        # A small section cannot back a declared huge import directory.
        put(data, OPTIONAL + 124, 20 * 129)
        put(data, OPTIONAL + 120, 0x1800)
        with self.assertRaisesRegex(ValueError, "pe_unmapped_rva"):
            inspect_pe(bytes(data), dll=False)
        data = fixture()
        data[OPTIONAL + 216 : OPTIONAL + 224] = bytes(8)
        put(data, OPTIONAL + 124, 20 * 129)
        descriptor = bytes(data[0x400:0x414])
        for index in range(129):
            data[0x400 + 20 * index : 0x414 + 20 * index] = descriptor
            put(data, 0x40C + 20 * index, 0x1B00)
        data[0xF00:0xF0D] = b"kernel32.dll\0"
        with self.assertRaisesRegex(ValueError, "pe_import_limit"):
            inspect_pe(bytes(data), dll=False)
        data[0xE00:0xE14] = bytes(20)
        self.assertEqual(
            inspect_pe(bytes(data), dll=False)["direct_imports"], ["kernel32.dll"]
        )

    def test_debug_runtime_is_rejected_in_both_import_tables(self) -> None:
        for name in (b"VCRUNTIME140D.dll", b"MSVCP140D.dll", b"ucrtbased.dll"):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "pe_debug_runtime"),
            ):
                inspect_pe(bytes(fixture(name=name)), dll=False)
        data = fixture()
        data[0x700:0x70E] = b"ucrtbased.dll\0"
        with self.assertRaisesRegex(ValueError, "pe_debug_runtime"):
            inspect_pe(bytes(data), dll=False)

    def test_file_read_limit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "image.exe"
            path.write_bytes(fixture())
            self.assertEqual(inspect_file(path, dll=False)["machine"], "x86_64")
            with patch("pe_inspect.MAX_IMAGE", 128):
                with self.assertRaisesRegex(ValueError, "pe_size"):
                    inspect_file(path, dll=False)

    def test_random_input_is_bounded_and_never_loaded(self) -> None:
        rng = random.Random(2710)
        for _ in range(256):
            data = fixture()
            for _ in range(8):
                data[rng.randrange(len(data))] = rng.randrange(256)
            try:
                report = inspect_pe(bytes(data), dll=False)
            except ValueError:
                continue
            self.assertLessEqual(len(report["direct_imports"]), 128)

    def test_invalid_candidate_rejected_before_install_or_execution(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            provenance = {
                "version": "0.1.0",
                "source_commit": "a" * 40,
                "source_dirty": False,
            }
            for product, runner in (
                ("cli", cli_bundle_smoke),
                ("ffi_sdk", ffi_bundle_smoke),
            ):
                # Build archives with valid checksums but invalid PE payloads.
                names = {"bin/dscope.exe"} if product == "cli" else set(FFI_FILES)
                payload = {name: b"invalid PE" for name in names}
                payload.update(
                    {
                        "README.txt": b"readme",
                        "LICENSE-MIT": b"license",
                        "THIRD_PARTY.md": b"notices",
                    }
                )
                archive = root / f"{product}.zip"
                checksum = write_bundle(archive, payload, provenance, product=product)
                self.assertEqual(checksum, digest(archive.read_bytes()))
                with (
                    patch.object(runner, "require_runtime_host"),
                    patch.object(runner, "install") as install,
                    self.assertRaisesRegex(ValueError, "pe_size"),
                ):
                    runner.rehearse(archive, checksum)
                install.assert_not_called()

    def test_sdk_requires_direct_library_import_before_running_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "active").write_text("a")
            binary = root / "a/bin/c-example.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(fixture())
            (binary.parent / "daoseeker_scope_ffi.dll").write_bytes(fixture(dll=True))
            with patch("ffi_bundle_smoke.execute", return_value=b"") as execute:
                with self.assertRaisesRegex(ValueError, "pe_sdk_dependency"):
                    ffi_bundle_smoke.probe_sdk(root, "a")
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.args[2], "compile")


if __name__ == "__main__":
    unittest.main()
