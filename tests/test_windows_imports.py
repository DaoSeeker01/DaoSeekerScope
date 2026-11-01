"""DUMPBIN text fixtures and source guards do not execute synthetic images."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import windows_imports_smoke as oracle
from cli_bundle import write_bundle
from test_pe_inspect import fixture

OUTPUT = b"""Dump of file synthetic.exe
  Section contains the following imports:
    KERNEL32.dll
       140008040 Import Address Table
       140008000 Import Name Table
                0 time date stamp
                0 Index of first forwarder reference
                0 GetTickCount64
                  Ordinal 7
  Section contains the following delay load imports:
    USER32.dll
         00000001 Characteristics
        140008400 Address of HMODULE
        140008500 Import Address Table
        140008600 Import Name Table
                0 time date stamp
        1400010A4 1D5 GetSystemMetrics
  Summary
    1000 .rdata
"""


class WindowsImportTests(unittest.TestCase):
    def test_dumpbin_named_ordinal_delay_and_metadata_like_name(self) -> None:
        result = oracle.parse_dumpbin(OUTPUT)
        self.assertEqual(
            result["direct_symbols"]["kernel32.dll"],
            {"names": ["GetTickCount64"], "ordinals": [7]},
        )
        self.assertEqual(
            result["delay_symbols"]["user32.dll"]["names"], ["GetSystemMetrics"]
        )
        changed = OUTPUT.replace(b"0 GetTickCount64", b"1 Characteristics")
        self.assertEqual(
            oracle.parse_dumpbin(changed)["direct_symbols"]["kernel32.dll"]["names"],
            ["Characteristics"],
        )
        self.assertEqual(
            oracle.parse_dumpbin(OUTPUT.replace(b"Ordinal 7", b"Ordinal 65535"))[
                "direct_symbols"
            ]["kernel32.dll"]["ordinals"],
            [65535],
        )
        self.assertEqual(
            oracle.parse_dumpbin(
                OUTPUT.replace(b"synthetic.exe", b"non-ascii-\xff.exe")
            ),
            result,
        )

    def test_dumpbin_incomplete_invalid_symbols_and_counts_fail(self) -> None:
        for data in (
            b"",
            OUTPUT.replace(b"  Summary", b"  Truncated"),
            OUTPUT.replace(b"Ordinal 7", b"Ordinal 65536"),
            OUTPUT.replace(b"GetTickCount64", b"bad\xffname"),
            OUTPUT.replace(b"Index of first forwarder reference", b"unknown metadata"),
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                oracle.parse_dumpbin(data)
        for name, value in (
            ("MAX_OUTPUT", 8),
            ("MAX_SYMBOLS", 1),
            ("MAX_TOTAL_SYMBOLS", 2),
            ("MAX_SYMBOL_NAME", 2),
        ):
            with (
                self.subTest(limit=name),
                patch.object(oracle, name, value),
                self.assertRaises(ValueError),
            ):
                oracle.parse_dumpbin(OUTPUT)

    def test_comparison_and_changed_image_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.exe"
            path.write_bytes(fixture())
            with patch.object(oracle, "run", return_value=OUTPUT):
                self.assertTrue(
                    oracle.compare(path, Path("unused"), dll=False)["matched"]
                )
            with patch.object(
                oracle,
                "run",
                return_value=OUTPUT.replace(b"GetTickCount64", b"getTickCount64"),
            ):
                with self.assertRaisesRegex(ValueError, "pe_symbol_oracle_mismatch"):
                    oracle.compare(path, Path("unused"), dll=False)

            def changed(*args: object) -> bytes:
                path.write_bytes(b"changed after inspection")
                return OUTPUT

            with patch.object(oracle, "run", side_effect=changed):
                with self.assertRaisesRegex(ValueError, "pe_oracle_image_changed"):
                    oracle.compare(path, Path("unused"), dll=False)

    def test_stale_candidate_rejected_before_compiler_or_dumpbin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target").mkdir()
            archive = root / "cli.zip"
            payload = {
                "bin/dscope.exe": b"not executed",
                "LICENSE-MIT": b"synthetic",
                "README.txt": b"synthetic",
                "THIRD_PARTY.md": b"synthetic",
            }
            checksum = write_bundle(
                archive,
                payload,
                {"version": "0.1.0", "source_commit": "b" * 40, "source_dirty": False},
            )
            (root / "SHA256SUMS").write_text(f"{checksum}  cli.zip\n", encoding="ascii")
            with (
                patch.object(oracle, "ROOT", root),
                patch.object(oracle, "require_runtime_host"),
                patch.object(
                    oracle,
                    "source_state",
                    return_value={"revision": "a" * 40, "status": ""},
                ),
                patch.object(oracle, "run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "pe_oracle_candidate_source"):
                    oracle.collect(archive, archive)
                run.assert_not_called()

    def test_failure_or_interruption_invalidates_previous_report(self) -> None:
        for error, state in (
            (ValueError("PRIVATE"), "failed"),
            (KeyboardInterrupt(), "incomplete"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "report.json"
                output.write_text('{"overall":"passed"}', encoding="ascii")
                with (
                    patch.object(
                        sys,
                        "argv",
                        ["probe", "cli.zip", "sdk.zip", "--output", str(output)],
                    ),
                    patch.object(oracle, "collect", side_effect=error),
                ):
                    with self.assertRaises(type(error)):
                        oracle.main()
                report = json.loads(output.read_bytes())
                self.assertEqual(report["overall"], state)
                self.assertNotIn("PRIVATE", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
