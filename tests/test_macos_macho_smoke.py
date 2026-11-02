"""Synthetic Mach-O bytes and Apple tool text; no execution of fixture images."""

import json
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import macos_macho_smoke as macho


def string_command(command: int, name: bytes, header: int = 24) -> bytes:
    size = (header + len(name) + 1 + 7) // 8 * 8
    return (
        struct.pack("<3I", command, size, header)
        + bytes(header - 12)
        + name
        + bytes(size - header - len(name))
    )


def fixture(
    kind: str = "executable", legacy: bool = False, extra: bytes = b""
) -> bytes:
    build = (
        struct.pack("<4I", 0x24, 16, 11 << 16, 26 << 16)
        if legacy
        else struct.pack("<6I", 0x32, 24, 1, 11 << 16, 26 << 16, 0)
    )
    commands = build + string_command(0xC, b"/usr/lib/libSystem.B.dylib")
    count = 2
    if kind == "dylib":
        commands += string_command(0xD, b"@rpath/libtest.dylib")
        count += 1
    if extra:
        commands += extra
        count += 1
    return (
        struct.pack(
            "<8I",
            0xFEEDFACF,
            0x100000C,
            0,
            2 if kind == "executable" else 6,
            count,
            len(commands),
            0,
            0,
        )
        + commands
    )


TOOL = b"""/private/build/test:
Load command 0
      cmd LC_BUILD_VERSION
  cmdsize 24
 platform MACOS
    minos 11.0
      sdk 26.0
   ntools 0
Load command 1
          cmd LC_LOAD_DYLIB
      cmdsize 56
         name /usr/lib/libSystem.B.dylib (offset 24)
   time stamp 0 Thu Jan  1 00:00:00 1970
      current version 1.0.0
compatibility version 1.0.0
"""


class MachoTests(unittest.TestCase):
    def test_header_and_both_version_commands_match_tool_metadata(self) -> None:
        oracle = macho.parse_otool(TOOL)
        for legacy in (False, True):
            metadata = macho.inspect(fixture(legacy=legacy), "arm64", "executable")
            self.assertTrue(
                all(metadata[key] == value for key, value in oracle.items())
            )
        data = bytearray(fixture())
        struct.pack_into("<II", data, 4, 0x1000007, 3)
        self.assertEqual(
            macho.inspect(bytes(data), "x86_64", "executable")["architecture"], "x86_64"
        )

    def test_ids_weak_reexports_rpaths_and_path_redaction(self) -> None:
        for command in (0x80000018, 0x8000001F, 0x80000023):
            metadata = macho.inspect(
                fixture(
                    "dylib", extra=string_command(command, b"/PRIVATE/secret.dylib")
                ),
                "arm64",
                "dylib",
            )
            rendered = json.dumps(macho.summary(metadata))
            self.assertNotIn("PRIVATE", rendered)
            self.assertNotIn("secret", rendered)
            self.assertIn("<redacted>", rendered)
        metadata = macho.inspect(
            fixture(extra=string_command(0x8000001C, b"/PRIVATE/build", 12)),
            "arm64",
            "executable",
        )
        self.assertEqual(macho.summary(metadata)["rpath_kinds"], ["absolute"])
        self.assertNotIn("PRIVATE", json.dumps(macho.summary(metadata)))

    def test_bad_headers_counts_sizes_architectures_and_platforms(self) -> None:
        original = fixture()
        for offset, value in (
            (0, 0xCAFEBABE),
            (4, 7),
            (8, 2),
            (12, 1),
            (16, 0),
            (16, 4097),
            (20, 0xFFFFFFFF),
            (28, 1),
            (36, 7),
            (36, 0x100000),
            (40, 2),
            (44, 0),
            (52, 65),
        ):
            data = bytearray(original)
            struct.pack_into("<I", data, offset, value)
            with (
                self.subTest(offset=offset, value=value),
                self.assertRaises(ValueError),
            ):
                macho.inspect(bytes(data), "arm64", "executable")
        for invalid_image in (
            original[:31],
            original[:-1],
            fixture(extra=struct.pack("<6I", 0x32, 24, 1, 11 << 16, 0, 0)),
            fixture(extra=struct.pack("<2I", 0x27, 8)),
            fixture(extra=string_command(0xD, b"bad-id")),
        ):
            with self.assertRaises(ValueError):
                macho.inspect(invalid_image, "arm64", "executable")

    def test_strings_are_bounded_terminated_utf8_and_inside_their_command(self) -> None:
        for raw in (b"", b"\xff", b"bad\nname", b"x" * 4097):
            with self.assertRaises(ValueError):
                macho.inspect(
                    fixture(extra=string_command(0xC, raw)), "arm64", "executable"
                )
        for offset in (0, 8, 23, 0xFFFFFFFF):
            command = bytearray(string_command(0xC, b"test"))
            struct.pack_into("<I", command, 8, offset)
            with self.assertRaises(ValueError):
                macho.inspect(fixture(extra=bytes(command)), "arm64", "executable")
        bad_padding = string_command(0xC, b"test")[:-1] + b"x"
        with self.assertRaises(ValueError):
            macho.inspect(fixture(extra=bad_padding), "arm64", "executable")

    def test_tool_rejects_missing_duplicate_and_foreign_metadata(self) -> None:
        for output in (
            b"",
            TOOL.replace(b"minos 11.0", b"minos n/a"),
            TOOL.replace(b"MACOS", b"IOS"),
            TOOL + b"Load command 2" + TOOL.split(b"Load command 0", 1)[1],
            TOOL.replace(b"minos 11.0", b"minos 11.0\n minos 12.0"),
        ):
            with self.assertRaises(ValueError):
                macho.parse_otool(output)
        legacy = TOOL.replace(b"LC_BUILD_VERSION", b"LC_VERSION_MIN_MACOSX").replace(
            b"minos", b"version"
        )
        self.assertEqual(macho.parse_otool(legacy), macho.parse_otool(TOOL))

    def test_seeded_mutations_never_raise_struct_or_unicode_errors(self) -> None:
        generator = random.Random(20261102)
        original = fixture()
        for _ in range(512):
            data = bytearray(original)
            for _ in range(generator.randint(1, 8)):
                data[generator.randrange(len(data))] = generator.randrange(256)
            try:
                macho.inspect(bytes(data), "arm64", "executable")
            except ValueError:
                pass

    def test_native_observer_checks_all_images_until_the_end(self) -> None:
        for mutate_first in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binaries = root / "target/debug"
                binaries.mkdir(parents=True)
                cli = binaries / "dscope"
                cli.write_bytes(fixture())
                (binaries / "libdaoseeker_scope_ffi.dylib").write_bytes(
                    fixture("dylib")
                )

                def tool(arguments: list[str]) -> bytes:
                    if "-archs" in arguments:
                        return b"arm64\n"
                    if arguments[-1].endswith(".dylib"):
                        if mutate_first:
                            cli.write_bytes(
                                fixture() + b"modified after first comparison"
                            )
                        return (
                            TOOL
                            + b"Load command 2\n cmd LC_ID_DYLIB\n name @rpath/libtest.dylib (offset 24)\n"
                        )
                    return TOOL

                with (
                    patch.object(macho, "ROOT", root),
                    patch.object(macho.platform, "system", return_value="Darwin"),
                    patch.object(macho.platform, "machine", return_value="arm64"),
                    patch.object(
                        macho,
                        "source",
                        return_value={"revision": "fixture", "status": ""},
                    ),
                    patch.object(macho, "run", side_effect=tool),
                ):
                    if mutate_first:
                        with self.assertRaises(ValueError):
                            macho.collect()
                    else:
                        report = macho.collect()
                        self.assertEqual(report["overall"], "passed")
                        self.assertFalse(report["images_executed"])
                        self.assertNotIn(directory, json.dumps(report))

    def test_failures_and_interruptions_invalidate_old_reports(self) -> None:
        for error, state, raised in (
            (ValueError("PRIVATE"), "failed", SystemExit),
            (KeyboardInterrupt(), "incomplete", KeyboardInterrupt),
        ):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "report.json"
                output.write_text('{"overall":"passed"}', encoding="utf-8")
                with (
                    patch.object(sys, "argv", ["macho", "--output", str(output)]),
                    patch.object(macho, "collect", side_effect=error),
                ):
                    with self.assertRaises(raised):
                        macho.main()
                report = json.loads(output.read_bytes())
                self.assertEqual(report["overall"], state)
                self.assertNotIn("PRIVATE", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
