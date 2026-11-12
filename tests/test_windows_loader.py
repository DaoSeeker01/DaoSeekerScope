"""Loader harness cleanup tests never execute their synthetic image payloads."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import windows_loader_smoke as loader


class WindowsLoaderTests(unittest.TestCase):
    def test_unexpected_child_failure_restores_library_and_error_mode(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "sdk.zip"
            (root / "SHA256SUMS").write_text("0" * 64 + "  sdk.zip\n")
            original = b"synthetic DLL, never loaded"
            payload = {
                "manifest.json": json.dumps(
                    {
                        "target": loader.TARGET,
                        "product": "ffi_sdk",
                        "source_commit": "a" * 40,
                        "source_dirty": False,
                    }
                ).encode(),
                "bin/daoseeker_scope_ffi.dll": original,
                "schema/snapshot-v1.schema.json": b"{}",
            }

            def install(*args):
                binary = root / "a/bin"
                binary.mkdir(parents=True)
                (binary / "daoseeker_scope_ffi.dll").write_bytes(original)
                (binary / "c-example.exe").write_bytes(b"never executed")
                return payload

            kernel = Mock()
            kernel.GetErrorMode.return_value = 0x40
            directory = Mock()
            directory.__enter__ = Mock(return_value=str(root))
            directory.__exit__ = Mock(return_value=False)
            with (
                patch.object(loader, "require_runtime_host"),
                patch.object(loader, "source_state", return_value=("a" * 40, "")),
                patch.object(loader, "install", side_effect=install),
                patch.object(loader, "activate"),
                patch.object(loader, "probe_sdk", return_value={}),
                patch.object(
                    loader.tempfile, "TemporaryDirectory", return_value=directory
                ),
                patch.object(loader.ctypes, "WinDLL", return_value=kernel, create=True),
                patch.object(loader, "execute", side_effect=ValueError("c_exit")),
                self.assertRaisesRegex(ValueError, "loader_unexpected_failure"),
            ):
                loader.collect(archive)
            self.assertEqual(
                (root / "a/bin/daoseeker_scope_ffi.dll").read_bytes(), original
            )
            self.assertFalse((root / "held.dll").exists())
            self.assertEqual(
                kernel.SetErrorMode.call_args_list, [call(0x43), call(0x40)]
            )

    def test_failure_or_interruption_cannot_leave_an_old_pass(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.json"
            for failure, state in (
                (ValueError("PRIVATE"), "failed"),
                (KeyboardInterrupt(), "incomplete"),
            ):
                report.write_text('{"overall":"passed"}')
                with (
                    patch.object(
                        sys, "argv", ["loader", "sdk.zip", "--output", str(report)]
                    ),
                    patch.object(loader, "collect", side_effect=failure),
                    self.assertRaises(type(failure)),
                ):
                    loader.main()
                self.assertEqual(json.loads(report.read_bytes())["overall"], state)
                self.assertNotIn("PRIVATE", report.read_text())


if __name__ == "__main__":
    unittest.main()
