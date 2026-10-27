"""GNU readelf policy fixtures are text only, not Linux runtime evidence."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import BinaryIO, cast
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from cli_bundle import LINUX_TARGET
import cli_bundle_smoke
import elf_inspect
from elf_inspect import inspect_elf, linux_environment, version_requirements

NEEDED = b"""Dynamic section at offset 0x100 contains 2 entries:
 0x01 (NEEDED) Shared library: [libc.so.6]
 0x01 (NEEDED) Shared library: [libgcc_s.so.1]
"""
VERSIONS = b"""Version needs section '.gnu.version_r' contains 2 entries:
 Addr: 0x000000001000 Offset: 0x001000 Link: 5 (.dynstr)
  000000: Version: 1 File: libc.so.6 Cnt: 3
  0x0010: Name: GLIBC_2.9 Flags: none Version: 2
  0x0020: Name: GLIBC_2.34 Flags: none Version: 3
  0x0030: Name: GLIBC_ABI_DT_RELR Flags: none Version: 4
  0x0040: Version: 1 File: libgcc_s.so.1 Cnt: 1
  0x0050: Name: GCC_3.0 Flags: none Version: 5
"""
OUTPUT = NEEDED + VERSIONS


class ElfTests(unittest.TestCase):
    def test_requirements_and_limits_are_explicit(self) -> None:
        report = inspect_elf(OUTPUT)
        self.assertEqual(report["highest_glibc_numeric_requirement"], "GLIBC_2.34")
        self.assertIn(
            "GLIBC_ABI_DT_RELR", report["required_symbol_versions"]["libc.so.6"]
        )
        self.assertEqual(
            report["required_symbol_versions"]["libgcc_s.so.1"], ["GCC_3.0"]
        )
        self.assertFalse(report["minimum_glibc_or_distribution_verified"])
        self.assertFalse(report["transitive_or_runtime_loads_inspected"])

    def test_version_definitions_do_not_become_requirements(self) -> None:
        definitions = b"Version definition section '.gnu.version_d' contains 1 entry:\nName: GLIBC_99.0\n"
        self.assertEqual(
            inspect_elf(NEEDED + definitions + VERSIONS), inspect_elf(OUTPUT)
        )
        self.assertEqual(inspect_elf(OUTPUT + definitions), inspect_elf(OUTPUT))

    def test_absent_malformed_or_duplicated_sections_fail(self) -> None:
        for output in (
            NEEDED,
            OUTPUT + VERSIONS,
            OUTPUT.replace(b"contains 2 entries", b"contains 0 entries"),
            OUTPUT.replace(b"contains 2 entries", b"contains 65 entries"),
        ):
            with self.subTest(output=output), self.assertRaises(ValueError):
                inspect_elf(output)

    def test_file_and_auxiliary_counts_must_match(self) -> None:
        for before, after in (
            (b"contains 2 entries", b"contains 1 entry"),
            (b"Cnt: 3", b"Cnt: 2"),
            (b"Cnt: 3", b"Cnt: 4"),
            (b"Cnt: 3", b"Cnt: 257"),
            (b"Cnt: 1", b"Cnt: 0"),
        ):
            with (
                self.subTest(after=after),
                self.assertRaisesRegex(ValueError, "elf_version_count"),
            ):
                inspect_elf(OUTPUT.replace(before, after))
        with self.assertRaisesRegex(ValueError, "elf_version_count"):
            inspect_elf(OUTPUT[: OUTPUT.rindex(b"  0x0050:")])

    def test_unknown_path_or_repeated_file_fails(self) -> None:
        for name in (b"other.so", b"/usr/lib/libc.so.6", b"libgcc_s.so.1"):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "elf_version_file"),
            ):
                inspect_elf(OUTPUT.replace(b"File: libc.so.6", b"File: " + name))

    def test_invalid_or_private_version_fails(self) -> None:
        for before, after, code in (
            (b"GLIBC_2.9", b"GLIBC_PRIVATE", "elf_private_glibc"),
            (b"GLIBC_2.9", b"GLIBC_2.34", "elf_version_duplicate"),
            (b"GLIBC_2.9", b"../bad", "elf_version_entry"),
            (b"GLIBC_2.9", b"x" * 129, "elf_version_entry"),
            (b"Flags: none", b"Flags:", "elf_version_entry"),
        ):
            with self.subTest(after=after), self.assertRaisesRegex(ValueError, code):
                inspect_elf(OUTPUT.replace(before, after, 1))

    def test_singular_section_and_numeric_maximum(self) -> None:
        output = (
            NEEDED
            + b"""Version needs section '.gnu.version_r' contains 1 entry:
 000000: Version: 1 File: libc.so.6 Cnt: 2
 0x0010: Name: GLIBC_2.9 Flags: WEAK Version: 2
 0x0020: Name: GLIBC_2.10 Flags: none Version: 3
"""
        )
        report = inspect_elf(output)
        self.assertEqual(report["highest_glibc_numeric_requirement"], "GLIBC_2.10")
        self.assertEqual(
            report["direct_dependencies_without_version_entries"], ["libgcc_s.so.1"]
        )
        report = inspect_elf(
            output.replace(b"GLIBC_2.9", b"GLIBC_ABI_A").replace(
                b"GLIBC_2.10", b"GLIBC_ABI_B"
            )
        )
        self.assertIsNone(report["highest_glibc_numeric_requirement"])

    def test_sdk_keeps_origin_runpath_contract(self) -> None:
        tags = b"0x01 (NEEDED) Shared library: [libdaoseeker_scope_ffi.so]\n0x1d (RUNPATH) Library runpath: [$ORIGIN/../lib]\n"
        output = NEEDED + tags + VERSIONS
        report = inspect_elf(output, consumer=True)
        self.assertIn(
            "libdaoseeker_scope_ffi.so",
            report["direct_dependencies_without_version_entries"],
        )
        with self.assertRaisesRegex(ValueError, "elf_runpath"):
            inspect_elf(output)

    def test_output_and_total_version_limits(self) -> None:
        with patch("elf_inspect.MAX_OUTPUT", 64):
            with self.assertRaisesRegex(ValueError, "elf_output_limit"):
                inspect_elf(OUTPUT)
        files = [f"library{i}.so" for i in range(5)]
        entries = []
        for library in files:
            entries.append(f"000000: Version: 1 File: {library} Cnt: 256\n")
            entries.extend(
                f"0x0010: Name: VERSION_{i} Flags: none Version: {i + 2}\n"
                for i in range(256)
            )
        output = (
            "Version needs section '.gnu.version_r' contains 5 entries:\n"
            + "".join(entries)
        ).encode()
        with self.assertRaisesRegex(ValueError, "elf_version_count"):
            version_requirements(output, files)

    def test_child_environment_does_not_mutate_parent(self) -> None:
        original = {
            "LD_PRELOAD": "bad",
            "LD_LIBRARY_PATH": "stale",
            "LD_AUDIT": "bad",
            "GLIBC_TUNABLES": "bad",
            "LC_ALL": "zh_CN",
            "PATH": "keep",
        }
        self.assertEqual(linux_environment(original), {"LC_ALL": "C", "PATH": "keep"})
        self.assertEqual(original["LD_PRELOAD"], "bad")

    def test_cli_children_use_clean_environment(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (
                patch.dict(os.environ, {"LD_PRELOAD": "bad", "GLIBC_TUNABLES": "bad"}),
                patch(
                    "cli_bundle_smoke.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("not-executed", 30),
                ) as run,
                self.assertRaises(subprocess.TimeoutExpired),
            ):
                cli_bundle_smoke.probe(root / "dscope", "0.1.0", LINUX_TARGET)
            self.assertNotIn("LD_PRELOAD", run.call_args.kwargs["env"])
            self.assertNotIn("GLIBC_TUNABLES", run.call_args.kwargs["env"])
            self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")

    def test_cli_inspection_failure_prevents_activation_and_execution(self) -> None:
        payload = {"manifest.json": json.dumps({"target": LINUX_TARGET}).encode()}
        with (
            patch("cli_bundle_smoke.verify_bundle", return_value=payload),
            patch("cli_bundle_smoke.require_runtime_host"),
            patch("cli_bundle_smoke.install"),
            patch(
                "cli_bundle_smoke.inspect_elf_file",
                side_effect=ValueError("elf_version_count"),
            ),
            patch("cli_bundle_smoke.activate") as activate,
            patch("cli_bundle_smoke.probe_selected") as execute,
            self.assertRaisesRegex(ValueError, "elf_version_count"),
        ):
            cli_bundle_smoke.rehearse(Path("not-opened.zip"), "unused")
        activate.assert_not_called()
        execute.assert_not_called()

    def test_readelf_process_success_failure_and_timeout(self) -> None:
        def run(
            arguments: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[bytes]:
            cast(BinaryIO, kwargs["stdout"]).write(OUTPUT)
            return subprocess.CompletedProcess(arguments, 0)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dscope"
            with patch("elf_inspect.subprocess.run", side_effect=run) as process:
                self.assertEqual(
                    elf_inspect.inspect_file(path)["highest_glibc_numeric_requirement"],
                    "GLIBC_2.34",
                )
            self.assertEqual(
                process.call_args.args[0][:4],
                ["readelf", "--wide", "--dynamic", "--version-info"],
            )
            with patch(
                "elf_inspect.subprocess.run",
                return_value=subprocess.CompletedProcess([], 1),
            ):
                with self.assertRaisesRegex(ValueError, "elf_exit"):
                    elf_inspect.inspect_file(path)
            with patch(
                "elf_inspect.subprocess.run",
                side_effect=subprocess.TimeoutExpired("readelf", 30),
            ):
                with self.assertRaises(subprocess.TimeoutExpired):
                    elf_inspect.inspect_file(path)

    @unittest.skipUnless(
        sys.platform == "linux", "requires native GNU/Linux cc and readelf"
    )
    def test_native_readelf_version_format(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "library.c"
            source.write_text(
                '#include <stdio.h>\nint probe(void) { return puts("probe"); }\n',
                encoding="ascii",
            )
            binary = root / "library.so"
            subprocess.run(
                [
                    "cc",
                    "-shared",
                    "-fPIC",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(source),
                    "-o",
                    str(binary),
                ],
                check=True,
                capture_output=True,
                timeout=60,
                env=linux_environment(os.environ),
            )
            report = elf_inspect.inspect_file(binary)
            self.assertIn("libc.so.6", report["direct_dependencies"])
            self.assertIn("libc.so.6", report["required_symbol_versions"])
            self.assertIsNotNone(report["highest_glibc_numeric_requirement"])
            self.assertFalse(report["minimum_glibc_or_distribution_verified"])


if __name__ == "__main__":
    unittest.main()
