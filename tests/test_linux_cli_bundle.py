"""Linux bundle policy tests use synthetic bytes; no Linux executable is fabricated."""

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from cli_bundle import (
    LINUX_TARGET,
    TARGET,
    digest,
    file_mode,
    native_target,
    verify_bundle,
    write_bundle,
)
from cli_bundle_smoke import activate, install, rehearse


class LinuxCliBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "linux.zip"
        self.payload = {
            "bin/dscope": b"synthetic bytes, never executed",
            "README.txt": b"instructions",
            "LICENSE-MIT": b"license",
            "THIRD_PARTY.md": b"upstream notices",
        }
        self.provenance = {
            "version": "0.1.0",
            "source_commit": "a" * 40,
            "source_dirty": False,
        }
        self.checksum = write_bundle(
            self.archive, self.payload, self.provenance, target=LINUX_TARGET
        )

    def repack(
        self,
        files: dict[str, bytes],
        *,
        mode: int = 0o755,
        system: int = 3,
        typed: bool = True,
    ) -> tuple[Path, str]:
        path = self.root / "repacked.zip"
        with zipfile.ZipFile(path, "w") as output:
            for name, data in files.items():
                info = zipfile.ZipInfo(name)
                info.create_system = system
                bits = mode if name == "bin/dscope" else 0o644
                info.external_attr = ((stat.S_IFREG if typed else 0) | bits) << 16
                output.writestr(info, data)
        return path, digest(path.read_bytes())

    def test_roundtrip_manifest_and_zip_modes(self) -> None:
        payload = verify_bundle(self.archive, self.checksum)
        manifest = json.loads(payload["manifest.json"])
        self.assertEqual(manifest["bundle_format"], 2)
        self.assertEqual(manifest["target"], LINUX_TARGET)
        for name, record in manifest["files"].items():
            self.assertEqual(record["mode"], file_mode(name, LINUX_TARGET))
        repeated = self.root / "repeated.zip"
        self.assertEqual(
            write_bundle(repeated, self.payload, self.provenance, target=LINUX_TARGET),
            self.checksum,
        )

    def test_missing_mode_rejected(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        manifest = json.loads(files["manifest.json"])
        del manifest["files"]["bin/dscope"]["mode"]
        files["manifest.json"] = json.dumps(manifest).encode()
        path, checksum = self.repack(files)
        with self.assertRaisesRegex(ValueError, "manifest_permissions"):
            verify_bundle(path, checksum)

    def test_dangerous_or_wrong_manifest_modes_rejected(self) -> None:
        for mode in (True, 0o4755, 0o777, 0o644):
            with self.subTest(mode=mode):
                files = verify_bundle(self.archive, self.checksum)
                manifest = json.loads(files["manifest.json"])
                manifest["files"]["bin/dscope"]["mode"] = mode
                files["manifest.json"] = json.dumps(manifest).encode()
                path, checksum = self.repack(files)
                with self.assertRaisesRegex(ValueError, "manifest_permissions"):
                    verify_bundle(path, checksum)

    def test_zip_modes_rejected_even_with_new_outer_checksum(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        for mode in (0o644, 0o777, 0o4755):
            with self.subTest(mode=mode):
                path, checksum = self.repack(files, mode=mode)
                with self.assertRaisesRegex(ValueError, "archive_permissions"):
                    verify_bundle(path, checksum)

    def test_dos_header_cannot_claim_posix_modes(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        path, checksum = self.repack(files, system=0)
        with self.assertRaisesRegex(ValueError, "archive_permissions"):
            verify_bundle(path, checksum)

    def test_missing_regular_file_type_rejected(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        path, checksum = self.repack(files, typed=False)
        with self.assertRaisesRegex(ValueError, "archive_permissions"):
            verify_bundle(path, checksum)

    def test_format_downgrade_rejected(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        manifest = json.loads(files["manifest.json"])
        manifest["bundle_format"] = 1
        files["manifest.json"] = json.dumps(manifest).encode()
        path, checksum = self.repack(files)
        with self.assertRaisesRegex(ValueError, "manifest_version"):
            verify_bundle(path, checksum)

    def test_native_target_must_match_real_runtime(self) -> None:
        for target, system, machine in (
            (TARGET, "Windows", "AMD64"),
            (LINUX_TARGET, "Linux", "x86_64"),
        ):
            with (
                patch("cli_bundle.platform.system", return_value=system),
                patch("cli_bundle.platform.machine", return_value=machine),
            ):
                self.assertEqual(
                    native_target(f"rustc\r\nhost: {target}\r\nrelease: 1.96.0\r\n"),
                    target,
                )
        for host in ("x86_64-unknown-linux-musl", "aarch64-apple-darwin", TARGET):
            with (
                patch("cli_bundle.platform.system", return_value="Linux"),
                patch("cli_bundle.platform.machine", return_value="x86_64"),
            ):
                with self.assertRaisesRegex(ValueError, "unsupported_host"):
                    native_target(f"host: {host}\n")

    def test_wrong_host_rejected_before_install_or_probe(self) -> None:
        with (
            patch("cli_bundle.platform.system", return_value="Windows"),
            patch("cli_bundle.platform.machine", return_value="AMD64"),
            patch("cli_bundle_smoke.install") as installation,
            patch("cli_bundle_smoke.probe") as execution,
        ):
            with self.assertRaisesRegex(ValueError, "unsupported_host"):
                rehearse(self.archive, self.checksum)
            installation.assert_not_called()
            execution.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "requires real POSIX file modes")
    def test_installed_mode_corruption_preserves_active_slot(self) -> None:
        payload = install(self.archive, self.checksum, self.root / "a")
        install(self.archive, self.checksum, self.root / "b")
        activate(self.root, "b", payload)
        (self.root / "a/bin/dscope").chmod(0o644)
        with self.assertRaisesRegex(ValueError, "installed_permissions"):
            activate(self.root, "a", payload)
        self.assertEqual((self.root / "active").read_text(), "b")

    @unittest.skipUnless(os.name == "posix", "requires real POSIX file modes")
    def test_install_modes_survive_restrictive_umask(self) -> None:
        # Process-local and restored before any other test, not a system setting.
        previous = os.umask(0o077)
        try:
            payload = install(self.archive, self.checksum, self.root / "a")
        finally:
            os.umask(previous)
        for name in payload:
            self.assertEqual(
                stat.S_IMODE((self.root / "a" / name).stat().st_mode),
                file_mode(name, LINUX_TARGET),
            )
        activate(self.root, "a", payload)


if __name__ == "__main__":
    unittest.main()
