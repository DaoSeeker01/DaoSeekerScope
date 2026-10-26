"""SDK archive tests use synthetic payloads and never load a fabricated DLL."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from cli_bundle import FFI_FILES, LINUX_TARGET, digest, verify_bundle, write_bundle
import cli_bundle_smoke
import ffi_bundle_smoke


class FfiBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "sdk.zip"
        self.payload = {name: b"synthetic data, never executed" for name in FFI_FILES}
        self.payload.update(
            {
                "README.txt": b"instructions",
                "LICENSE-MIT": b"license",
                "THIRD_PARTY.md": b"notices",
            }
        )
        self.provenance = {
            "version": "0.1.0",
            "source_commit": "a" * 40,
            "source_dirty": False,
        }
        self.checksum = write_bundle(
            self.archive, self.payload, self.provenance, product="ffi_sdk"
        )

    def repack(self, files: dict[str, bytes]) -> tuple[Path, str]:
        path = self.root / "changed.zip"
        with zipfile.ZipFile(path, "w") as bundle:
            for name, data in files.items():
                bundle.writestr(name, data)
        return path, digest(path.read_bytes())

    def test_sdk_roundtrip_and_repeatable_archive(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(manifest["product"], "ffi_sdk")
        self.assertEqual(manifest["bundle_format"], 3)
        self.assertEqual(manifest["abi_version"], 1)
        other = self.root / "other.zip"
        self.assertEqual(
            write_bundle(other, self.payload, self.provenance, product="ffi_sdk"),
            self.checksum,
        )

    def test_required_sdk_files(self) -> None:
        for name in FFI_FILES:
            with self.subTest(name=name):
                payload = {
                    key: value for key, value in self.payload.items() if key != name
                }
                with self.assertRaisesRegex(ValueError, "missing_required_file"):
                    write_bundle(
                        self.root / (name.replace("/", "-") + ".zip"),
                        payload,
                        self.provenance,
                        product="ffi_sdk",
                    )

    def test_linux_ffi_not_claimed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_ffi_target"):
            write_bundle(
                self.root / "linux.zip",
                self.payload,
                self.provenance,
                target=LINUX_TARGET,
                product="ffi_sdk",
            )
        self.assertFalse((self.root / "linux.zip").exists())

    def test_format_cannot_impersonate_cli(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        manifest = json.loads(files["manifest.json"])
        del manifest["product"]
        files["manifest.json"] = json.dumps(manifest).encode()
        path, checksum = self.repack(files)
        with self.assertRaisesRegex(ValueError, "manifest_version"):
            verify_bundle(path, checksum)

    def test_unknown_product_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_product"):
            write_bundle(
                self.root / "unknown.zip",
                self.payload,
                self.provenance,
                product="unknown",
            )

    def test_tampered_header_and_library_rejected(self) -> None:
        for name in (
            "bindings/daoseeker_scope.h",
            "lib/daoseeker_scope_ffi.dll.lib",
            "bin/daoseeker_scope_ffi.dll",
        ):
            files = verify_bundle(self.archive, self.checksum)
            files[name] = b"changed"
            path, checksum = self.repack(files)
            with self.assertRaisesRegex(ValueError, "payload_checksum"):
                verify_bundle(path, checksum)

    def test_cli_runner_rejects_sdk_before_install(self) -> None:
        with patch("cli_bundle_smoke.install") as install:
            with self.assertRaisesRegex(ValueError, "unsupported_product"):
                cli_bundle_smoke.rehearse(self.archive, self.checksum)
            install.assert_not_called()

    def test_sdk_runner_rejects_cli_before_execution(self) -> None:
        payload = {
            "bin/dscope.exe": b"fake",
            "LICENSE-MIT": b"license",
            "README.txt": b"readme",
            "THIRD_PARTY.md": b"notices",
        }
        cli = self.root / "cli.zip"
        checksum = write_bundle(cli, payload, self.provenance)
        with patch("ffi_bundle_smoke.probe_sdk") as probe:
            with self.assertRaisesRegex(ValueError, "unsupported_product"):
                ffi_bundle_smoke.rehearse(cli, checksum)
            probe.assert_not_called()

    def test_failed_report_overwrites_pass(self) -> None:
        output = self.root / "report.json"
        output.write_text('{"overall":"passed"}')
        (self.root / "SHA256SUMS").write_text("invalid")
        with patch.object(
            sys, "argv", ["ffi", str(self.archive), "--output", str(output)]
        ):
            with self.assertRaisesRegex(ValueError, "checksum_sidecar"):
                ffi_bundle_smoke.main()
        self.assertEqual(json.loads(output.read_bytes())["overall"], "failed")


if __name__ == "__main__":
    unittest.main()
