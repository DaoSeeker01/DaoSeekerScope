"""Synthetic archive provenance tests, independent of license approval."""

import gzip
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import notice_archive
import notice_audit
from cli_bundle import digest

MANIFEST = b'[package]\nname = "sample"\nversion = "1.0.0"\nlicense = "MIT"\nrepository = "https://github.com/example/sample"\n'
VCS = {"git": {"sha1": "a" * 40}, "path_in_vcs": "crates/sample"}


def archive_bytes(entries: list[tuple[str, bytes | None]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content in entries:
            member = tarfile.TarInfo(name)
            if content is None:
                member.type = tarfile.SYMTYPE
                member.linkname = "outside-private"
                archive.addfile(member)
            else:
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


class NoticeArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        base = self.root / "registry/src/test/sample-1.0.0"
        base.mkdir(parents=True)
        self.archive = self.root / "registry/cache/test/sample-1.0.0.crate"
        self.archive.parent.mkdir(parents=True)
        self.package: dict[str, Any] = {
            "id": "sample",
            "name": "sample",
            "version": "1.0.0",
            "source": "registry+test",
            "license": "MIT",
            "manifest_path": str(base / "Cargo.toml"),
        }
        self.entries: list[tuple[str, bytes | None]] = [
            ("sample-1.0.0/Cargo.toml", MANIFEST),
            ("sample-1.0.0/.cargo_vcs_info.json", json.dumps(VCS).encode()),
        ]

    def verify(self, entries: list[tuple[str, bytes | None]]) -> dict[str, Any]:
        data = archive_bytes(entries)
        self.archive.write_bytes(data)
        return notice_archive.provenance(self.package, digest(data))

    def test_locked_archive_binds_identity_vcs_and_original_notice_bytes(self) -> None:
        report = self.verify(
            self.entries + [("sample-1.0.0/LICENSE-MIT", b"upstream original text")]
        )
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["vcs"]["revision"], "a" * 40)
        self.assertEqual(
            report["vcs"]["source_url"],
            "https://github.com/example/sample/tree/" + "a" * 40 + "/crates/sample",
        )
        self.assertEqual(
            report["root_notices"],
            [
                {
                    "name": "LICENSE-MIT",
                    "bytes": 22,
                    "sha256": digest(b"upstream original text"),
                }
            ],
        )
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_verifying_missing_materials_keeps_the_packaging_gate_blocked(self) -> None:
        self.verify(self.entries)
        metadata: dict[str, Any] = {
            "packages": [
                {"id": "cli", "name": "daoseeker-scope-cli", "source": None},
                self.package,
            ],
            "resolve": {
                "nodes": [
                    {
                        "id": "cli",
                        "deps": [{"pkg": "sample", "dep_kinds": [{"kind": None}]}],
                    },
                    {"id": "sample", "deps": []},
                ]
            },
        }
        checksum = digest(self.archive.read_bytes())
        report = notice_audit.inventory(
            metadata,
            "daoseeker-scope-cli",
            archive_checksums={("sample", "1.0.0", "registry+test"): checksum},
        )
        self.assertEqual(report["packager_notice_gate"], "blocked")
        package = report["packages"][0]
        self.assertEqual(package["errors"], ["missing_dependency_notice"])
        self.assertEqual(package["archive_provenance"]["status"], "verified")
        self.assertEqual(package["archive_provenance"]["root_notices"], [])
        self.assertEqual(report["legal_review"], "not_performed")
        other_base = self.root / "registry/src/test/other-1.0.0"
        other_base.mkdir()
        other = {
            **self.package,
            "id": "zzz",
            "name": "other",
            "manifest_path": str(other_base / "Cargo.toml"),
        }
        metadata["packages"].append(other)
        metadata["resolve"]["nodes"][0]["deps"].append(
            {"pkg": "zzz", "dep_kinds": [{"kind": None}]}
        )
        metadata["resolve"]["nodes"].append({"id": "zzz", "deps": []})
        mixed = notice_audit.inventory(
            metadata,
            "daoseeker-scope-cli",
            archive_checksums={
                ("sample", "1.0.0", "registry+test"): checksum,
                ("other", "1.0.0", "registry+test"): "b" * 64,
            },
        )
        self.assertEqual(mixed["blocking_packages"], 2)
        self.assertEqual(
            mixed["packages"][0]["archive_provenance"]["status"], "verified"
        )
        self.assertEqual(
            mixed["packages"][1]["archive_provenance"]["status"], "unavailable"
        )

    def test_missing_checksum_and_mismatched_archive_stop_before_parsing(self) -> None:
        with patch.object(notice_archive, "read_notice") as read:
            result = notice_archive.provenance(self.package, None)
        read.assert_not_called()
        self.assertEqual(result["reason"], "missing_lock_checksum")
        self.archive.write_bytes(b"corrupt content")
        with patch.object(notice_archive, "inspect") as inspect:
            result = notice_archive.provenance(self.package, "b" * 64)
        inspect.assert_not_called()
        self.assertEqual(result["reason"], "archive_checksum_mismatch")
        result = notice_archive.provenance(self.package, digest(b"corrupt content"))
        self.assertEqual(
            result, {"status": "invalid", "reason": "archive_metadata_invalid"}
        )

    def test_command_flag_reaches_the_audit_entry_point(self) -> None:
        output = self.root / "report.json"
        with (
            patch.object(
                sys,
                "argv",
                [
                    "notice_audit",
                    "--target",
                    "aarch64-apple-darwin",
                    "--offline",
                    "--verify-archives",
                    "--output",
                    str(output),
                ],
            ),
            patch.object(
                notice_audit, "audit", return_value={"overall": "completed"}
            ) as audit,
            patch.object(sys, "stdout", io.StringIO()),
        ):
            notice_audit.main()
        audit.assert_called_once_with(
            "aarch64-apple-darwin", offline=True, verify_archives=True
        )
        self.assertEqual(json.loads(output.read_bytes())["overall"], "completed")

    def test_unavailable_cache_and_read_errors_are_redacted(self) -> None:
        result = notice_archive.provenance(self.package, "b" * 64)
        self.assertEqual(result["status"], "unavailable")
        with patch.object(
            notice_archive, "read_notice", side_effect=ValueError("PRIVATE")
        ):
            result = notice_archive.provenance(self.package, "b" * 64)
        self.assertEqual(
            result, {"status": "unavailable", "reason": "archive_read_failed"}
        )

    def test_bad_package_identity_and_unsafe_or_duplicate_members_are_rejected(
        self,
    ) -> None:
        for extra in [
            ("../private", b"text"),
            ("/private", b"text"),
            ("other-1.0.0/LICENSE", b"text"),
            ("sample-1.0.0/./Cargo.toml", MANIFEST),
            ("sample-1.0.0/NOTICE", None),
            self.entries[0],
        ]:
            with self.subTest(extra=extra[0]):
                self.assertEqual(
                    self.verify(self.entries + [extra])["status"], "invalid"
                )
        for replacement in [
            MANIFEST.replace(b"1.0.0", b"2.0.0"),
            MANIFEST.replace(b'"MIT"', b'"other"'),
            b"package = []",
        ]:
            self.assertEqual(
                self.verify([("sample-1.0.0/Cargo.toml", replacement)])["status"],
                "invalid",
            )

    def test_invalid_vcs_metadata_is_rejected_without_local_path_disclosure(
        self,
    ) -> None:
        cases: list[Any] = [
            [],
            {"git": []},
            {"git": {"sha1": "invalid"}, "path_in_vcs": "crates/sample"},
            {"git": {"sha1": "a" * 40, "dirty": True}, "path_in_vcs": "crates/sample"},
        ]
        for path in ("../PRIVATE", "/PRIVATE", "C:\\PRIVATE", "crates/\nPRIVATE"):
            cases.append({"git": {"sha1": "a" * 40}, "path_in_vcs": path})
        for vcs in cases:
            with self.subTest(vcs=vcs):
                result = self.verify(
                    [
                        self.entries[0],
                        ("sample-1.0.0/.cargo_vcs_info.json", json.dumps(vcs).encode()),
                    ]
                )
                self.assertEqual(
                    result, {"status": "invalid", "reason": "archive_metadata_invalid"}
                )

    def test_duplicate_vcs_fields_are_rejected(self) -> None:
        duplicate = (
            '{"git":{"sha1":"'
            + "a" * 40
            + '","sha1":"'
            + "b" * 40
            + '"},"path_in_vcs":""}'
        ).encode()
        result = self.verify(
            [self.entries[0], ("sample-1.0.0/.cargo_vcs_info.json", duplicate)]
        )
        self.assertEqual(result["status"], "invalid")

    def test_invalid_deflate_stream_is_a_per_package_error(self) -> None:
        data = b"\x1f\x8b\x08\x00" + b"\x00" * 6 + b"\x07" + b"\x00" * 8
        self.archive.write_bytes(data)
        self.assertEqual(
            notice_archive.provenance(self.package, digest(data)),
            {"status": "invalid", "reason": "archive_metadata_invalid"},
        )

    def test_missing_vcs_does_not_hide_a_verified_archive_or_invent_revision(
        self,
    ) -> None:
        result = self.verify([self.entries[0]])
        self.assertEqual(result["status"], "verified")
        self.assertIsNone(result["vcs"])

    def test_decompression_member_count_and_text_limits_are_enforced(self) -> None:
        with patch.object(notice_archive, "MAX_MEMBERS", 1):
            self.assertEqual(self.verify(self.entries)["status"], "invalid")
        with patch.object(notice_archive, "MAX_TEXT", 16):
            self.assertEqual(self.verify(self.entries)["status"], "invalid")
        data = gzip.compress(b"x" * 1024)
        self.archive.write_bytes(data)
        with (
            patch.object(notice_archive, "MAX_EXPANDED", 512),
            patch.object(notice_archive.tarfile, "open") as open_tar,
        ):
            result = notice_archive.provenance(self.package, digest(data))
        open_tar.assert_not_called()
        self.assertEqual(result["status"], "invalid")
        with patch.object(notice_archive, "MAX_ARCHIVE", 4):
            self.assertEqual(
                notice_archive.provenance(self.package, digest(data))["status"],
                "unavailable",
            )


if __name__ == "__main__":
    unittest.main()
