"""Negative archive tests never execute the synthetic executable payload."""

import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from cli_bundle import (
    MAX_FILE,
    dependency_payload,
    digest,
    safe_name,
    verify_bundle,
    write_bundle,
)
from cli_bundle_smoke import activate, install
import cli_bundle_smoke


class CliBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "candidate.zip"
        self.payload = {
            "bin/dscope.exe": b"synthetic, never executed",
            "LICENSE-MIT": b"synthetic license",
            "THIRD_PARTY.md": b"synthetic notices",
            "README.txt": b"synthetic instructions",
        }
        self.provenance = {
            "version": "0.1.0",
            "source_commit": "a" * 40,
            "source_dirty": False,
        }
        self.checksum = write_bundle(self.archive, self.payload, self.provenance)

    def repack(self, files: dict[str, bytes]) -> tuple[Path, str]:
        path = self.root / "changed.zip"
        with zipfile.ZipFile(path, "w") as output:
            for name, data in files.items():
                output.writestr(name, data)
        return path, digest(path.read_bytes())

    def test_roundtrip_and_repeatable_archive(self) -> None:
        payload = verify_bundle(self.archive, self.checksum)
        self.assertEqual(payload["bin/dscope.exe"], self.payload["bin/dscope.exe"])
        other = self.root / "repeat.zip"
        self.assertEqual(
            write_bundle(other, self.payload, self.provenance), self.checksum
        )

    def test_checksum_rejects_before_install(self) -> None:
        with self.assertRaisesRegex(ValueError, "archive_checksum"):
            install(self.archive, "0" * 64, self.root / "new")
        self.assertFalse((self.root / "new").exists())

    def test_payload_corruption_even_with_new_archive_checksum(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        files["bin/dscope.exe"] = b"changed"
        path, checksum = self.repack(files)
        with self.assertRaisesRegex(ValueError, "payload_checksum"):
            verify_bundle(path, checksum)

    def test_extra_and_missing_members(self) -> None:
        for name in ("extra", "LICENSE-MIT"):
            files = verify_bundle(self.archive, self.checksum)
            if name == "extra":
                files[name] = b"unlisted"
            else:
                del files[name]
            path, checksum = self.repack(files)
            with self.assertRaisesRegex(ValueError, "manifest_files"):
                verify_bundle(path, checksum)

    def test_unsafe_names(self) -> None:
        for name in (
            "../escape",
            "/root",
            "a/../b",
            "C:/file",
            "a\\b",
            "a//b",
            "a/./b",
            "NUL",
            "a/con.txt",
            "a.",
            "",
            "a/",
        ):
            self.assertFalse(safe_name(name), name)
        files = verify_bundle(self.archive, self.checksum)
        files["../escape"] = b"bad"
        path, checksum = self.repack(files)
        with self.assertRaisesRegex(ValueError, "unsafe_member"):
            verify_bundle(path, checksum)
        self.assertFalse((self.root.parent / "escape").exists())

    def test_case_collision(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        files["BIN/dscope.exe"] = b"duplicate"
        path, checksum = self.repack(files)
        with self.assertRaisesRegex(ValueError, "unsafe_member"):
            verify_bundle(path, checksum)

    def test_file_directory_collision(self) -> None:
        files = verify_bundle(self.archive, self.checksum)
        files["BIN"] = b"conflicts with bin/dscope.exe"
        path, checksum = self.repack(files)
        with self.assertRaisesRegex(ValueError, "member_path_conflict"):
            verify_bundle(path, checksum)

    def test_failed_rerun_overwrites_previous_pass(self) -> None:
        report = self.root / "report.json"
        report.write_text('{"overall":"passed"}')
        (self.root / "SHA256SUMS").write_text("bad sidecar")
        with patch.object(
            sys, "argv", ["smoke", str(self.archive), "--output", str(report)]
        ):
            with self.assertRaisesRegex(ValueError, "checksum_sidecar"):
                cli_bundle_smoke.main()
        self.assertEqual(json.loads(report.read_text())["overall"], "failed")

    def test_special_file_rejected(self) -> None:
        path = self.root / "special.zip"
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(path, "w") as output:
            output.writestr(info, b"../outside")
        with self.assertRaisesRegex(ValueError, "special_member"):
            verify_bundle(path, digest(path.read_bytes()))

    def test_declared_oversized_member(self) -> None:
        raw = bytearray(self.archive.read_bytes())
        offset = raw.index(b"PK\x01\x02")
        raw[offset + 24 : offset + 28] = (MAX_FILE + 1).to_bytes(4, "little")
        path = self.root / "oversized.zip"
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "file_limit"):
            verify_bundle(path, digest(raw))

    def test_manifest_version_and_duplicate_keys(self) -> None:
        for replacement in (b'{"bundle_format":1,"bundle_format":1}', b"[]"):
            files = verify_bundle(self.archive, self.checksum)
            files["manifest.json"] = replacement
            path, checksum = self.repack(files)
            with self.assertRaises(ValueError):
                verify_bundle(path, checksum)
        files = verify_bundle(self.archive, self.checksum)
        manifest = json.loads(files["manifest.json"])
        manifest["bundle_format"] = True
        files["manifest.json"] = json.dumps(manifest).encode()
        path, checksum = self.repack(files)
        with self.assertRaisesRegex(ValueError, "manifest_version"):
            verify_bundle(path, checksum)

    def test_existing_install_and_failed_activation_preserve_pointer(self) -> None:
        payload = install(self.archive, self.checksum, self.root / "a")
        activate(self.root, "a", payload)
        with self.assertRaises(FileExistsError):
            install(self.archive, self.checksum, self.root / "a")
        (self.root / "a/bin/dscope.exe").write_bytes(b"bad installed bytes")
        with self.assertRaisesRegex(ValueError, "installed_corruption"):
            activate(self.root, "a", payload)
        self.assertEqual((self.root / "active").read_text(), "a")

    def test_missing_dependency_license_fails_closed(self) -> None:
        metadata = {
            "packages": [
                {"id": "cli", "name": "daoseeker-scope-cli", "source": None},
                {
                    "id": "dep",
                    "name": "dep",
                    "version": "1",
                    "source": "registry+test",
                    "license": "MIT",
                    "manifest_path": str(self.root / "Cargo.toml"),
                },
            ],
            "resolve": {
                "nodes": [
                    {
                        "id": "cli",
                        "deps": [{"pkg": "dep", "dep_kinds": [{"kind": None}]}],
                    },
                    {"id": "dep", "deps": []},
                ]
            },
        }
        with self.assertRaisesRegex(ValueError, "missing_dependency_notice"):
            dependency_payload(metadata)
        (self.root / "NOTICE").write_bytes(b"copyright notice alone")
        with self.assertRaisesRegex(ValueError, "missing_dependency_license"):
            dependency_payload(metadata)
        (self.root / "LICENSE-MIT").write_bytes(b"upstream full text")
        payload = dependency_payload(metadata)
        self.assertEqual(payload["licenses/dep-1/LICENSE-MIT"], b"upstream full text")


if __name__ == "__main__":
    unittest.main()
