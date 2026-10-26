"""Linux SDK policy tests; synthetic ELF payloads are never loaded or executed."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from cli_bundle import (
    LINUX_FFI_FILES,
    LINUX_TARGET,
    digest,
    verify_bundle,
    write_bundle,
)
from cli_bundle_smoke import activate, install
import cli_bundle_smoke
import ffi_bundle_smoke


class LinuxFfiBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "sdk.zip"
        self.payload = {name: b"synthetic, never loaded" for name in LINUX_FFI_FILES}
        self.payload.update(
            {
                "README.txt": b"readme",
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
            self.archive,
            self.payload,
            self.provenance,
            target=LINUX_TARGET,
            product="ffi_sdk",
        )

    def repack(self, files: dict[str, bytes], mode: int = 0o644) -> tuple[Path, str]:
        path = self.root / "repacked.zip"
        with zipfile.ZipFile(path, "w") as output:
            for name, data in files.items():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | mode) << 16
                output.writestr(info, data)
        return path, digest(path.read_bytes())

    def test_format_four_and_data_modes(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(manifest["bundle_format"], 4)
        self.assertEqual(manifest["product"], "ffi_sdk")
        self.assertEqual(manifest["abi_version"], 1)
        self.assertEqual(manifest["schema_version"], 1)
        self.assertTrue(
            all(record["mode"] == 0o644 for record in manifest["files"].values())
        )
        self.assertFalse(any(name.endswith((".dll", ".exe", ".lib")) for name in files))
        self.assertEqual(
            write_bundle(
                self.root / "repeat.zip",
                self.payload,
                self.provenance,
                target=LINUX_TARGET,
                product="ffi_sdk",
            ),
            self.checksum,
        )

    def test_missing_sdk_members(self) -> None:
        for missing in LINUX_FFI_FILES:
            with self.subTest(member=missing):
                payload = {
                    name: data for name, data in self.payload.items() if name != missing
                }
                with self.assertRaisesRegex(ValueError, "missing_required_file"):
                    write_bundle(
                        self.root / (missing.replace("/", "-") + ".zip"),
                        payload,
                        self.provenance,
                        target=LINUX_TARGET,
                        product="ffi_sdk",
                    )

    def test_wrong_product_or_target_format_rejected(self) -> None:
        for target, product, version in (
            (LINUX_TARGET, "ffi_sdk", 3),
            (LINUX_TARGET, "ffi_sdk", 2),
            (LINUX_TARGET, "cli", 4),
            ("x86_64-pc-windows-msvc", "ffi_sdk", 4),
        ):
            with self.subTest(target=target, product=product, version=version):
                files = verify_bundle(self.archive, self.checksum)
                manifest = json.loads(files["manifest.json"])
                manifest.update(target=target, product=product, bundle_format=version)
                files["manifest.json"] = json.dumps(manifest).encode()
                path, checksum = self.repack(files)
                with self.assertRaisesRegex(ValueError, "manifest_version"):
                    verify_bundle(path, checksum)

    def test_tampered_library_rejected(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        files["lib/libdaoseeker_scope_ffi.so"] = b"changed library"
        path, checksum = self.repack(files)
        with self.assertRaisesRegex(ValueError, "payload_checksum"):
            verify_bundle(path, checksum)

    def test_archive_permissions_rejected(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        for mode in (0o777, 0o4755, 0o600):
            with self.subTest(mode=mode):
                path, checksum = self.repack(files, mode)
                with self.assertRaisesRegex(ValueError, "archive_permissions"):
                    verify_bundle(path, checksum)

    def test_library_manifest_mode_rejected(self) -> None:
        for mode in (None, True, 0o755, 0o4755):
            with self.subTest(mode=mode):
                files = verify_bundle(self.archive, self.checksum)
                manifest = json.loads(files["manifest.json"])
                manifest["files"]["lib/libdaoseeker_scope_ffi.so"]["mode"] = mode
                files["manifest.json"] = json.dumps(manifest).encode()
                path, checksum = self.repack(files)
                with self.assertRaisesRegex(ValueError, "manifest_permissions"):
                    verify_bundle(path, checksum)

    def test_wrong_host_rejected_before_install(self) -> None:
        with (
            patch("cli_bundle.platform.system", return_value="Windows"),
            patch("cli_bundle.platform.machine", return_value="AMD64"),
            patch("ffi_bundle_smoke.install") as installation,
            patch("ffi_bundle_smoke.probe_sdk") as probe,
        ):
            with self.assertRaisesRegex(ValueError, "unsupported_host"):
                ffi_bundle_smoke.rehearse(self.archive, self.checksum)
            installation.assert_not_called()
            probe.assert_not_called()

    def test_cli_runner_rejects_linux_sdk_before_install(self) -> None:
        with patch("cli_bundle_smoke.install") as installation:
            with self.assertRaisesRegex(ValueError, "unsupported_product"):
                cli_bundle_smoke.rehearse(self.archive, self.checksum)
            installation.assert_not_called()

    def test_elf_dependency_policy(self) -> None:
        needed = b"0x1 (NEEDED) Shared library: [libdaoseeker_scope_ffi.so]\n"
        runpath = b"0x1d (RUNPATH) Library runpath: [$ORIGIN/../lib]\n"
        self.assertEqual(
            ffi_bundle_smoke.elf_dependencies(needed + runpath, consumer=True),
            ["libdaoseeker_scope_ffi.so"],
        )
        libc = b"0x1 (NEEDED) Shared library: [libc.so.6]\n"
        self.assertEqual(
            ffi_bundle_smoke.elf_dependencies(libc, consumer=False), ["libc.so.6"]
        )
        for output, code in (
            (b"", "elf_needed"),
            (libc + runpath, "elf_sdk_dependency"),
            (needed, "elf_runpath"),
            (needed + runpath + runpath, "elf_runpath"),
            (needed + runpath.replace(b"$ORIGIN/../lib", b"/tmp/stale"), "elf_runpath"),
            (
                needed + runpath + b"0xf (RPATH) Library rpath: [/tmp/stale]\n",
                "elf_rpath",
            ),
            (
                needed.replace(
                    b"libdaoseeker_scope_ffi.so", b"/tmp/libdaoseeker_scope_ffi.so"
                )
                + runpath,
                "elf_needed",
            ),
            (needed + needed + runpath, "elf_needed"),
        ):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, code):
                    ffi_bundle_smoke.elf_dependencies(output, consumer=True)
        with self.assertRaisesRegex(ValueError, "elf_runpath"):
            ffi_bundle_smoke.elf_dependencies(libc + runpath, consumer=False)

    def test_child_environment_does_not_mutate_parent(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "LD_LIBRARY_PATH": "stale",
                    "LD_PRELOAD": "bad",
                    "GLIBC_TUNABLES": "bad",
                },
            ),
            patch(
                "ffi_bundle_smoke.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ) as run,
        ):
            ffi_bundle_smoke.execute(["not-executed"], self.root, "elf", LINUX_TARGET)
            environment = run.call_args.kwargs["env"]
            self.assertFalse(any(key.startswith("LD_") for key in environment))
            self.assertNotIn("GLIBC_TUNABLES", environment)
            self.assertEqual(environment["LC_ALL"], "C")
            self.assertEqual(os.environ["LD_LIBRARY_PATH"], "stale")

    @unittest.skipUnless(os.name == "posix", "requires real POSIX file modes")
    def test_sdk_install_restores_modes_under_restrictive_umask(self) -> None:
        previous = os.umask(0o077)
        try:
            payload = install(self.archive, self.checksum, self.root / "a")
        finally:
            os.umask(previous)
        for name in payload:
            self.assertEqual(
                stat.S_IMODE((self.root / "a" / name).stat().st_mode), 0o644
            )
        activate(self.root, "a", payload)

    @unittest.skipUnless(os.name == "posix", "requires real POSIX file modes")
    def test_sdk_mode_tampering_preserves_active_slot(self) -> None:
        payload = install(self.archive, self.checksum, self.root / "a")
        install(self.archive, self.checksum, self.root / "b")
        activate(self.root, "b", payload)
        (self.root / "a/lib/libdaoseeker_scope_ffi.so").chmod(0o777)
        with self.assertRaisesRegex(ValueError, "installed_permissions"):
            activate(self.root, "a", payload)
        self.assertEqual((self.root / "active").read_text(), "b")


if __name__ == "__main__":
    unittest.main()
