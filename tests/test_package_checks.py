"""A failed or interrupted packaging run must not leave a previous success report."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_packages


class PackageEvidence(unittest.TestCase):
    def test_successful_stderr_does_not_pollute_machine_readable_stdout(self) -> None:
        code = """import sys
sys.stderr.write("cargo diagnostic\\n")
print('{"ok":true}')
"""
        output = check_packages.run([sys.executable, "-c", code])
        self.assertEqual(json.loads(output), {"ok": True})

    def test_independent_consumer_rejects_feature_unification_and_extra_roots(
        self,
    ) -> None:
        metadata: dict[str, Any] = {
            "workspace_members": ["consumer"],
            "packages": [{"name": "daoseeker-scope-core", "id": "opaque-core-id"}],
            "resolve": {
                "nodes": [
                    {
                        "id": "opaque-core-id",
                        "features": ["default"],
                        "deps": [],
                    }
                ]
            },
        }
        self.assertEqual(
            check_packages.check_consumer_core_features(
                metadata, serde_enabled=False, schema_enabled=False
            ),
            ["default"],
        )
        node = metadata["resolve"]["nodes"][0]
        node["features"] = ["default", "serde"]
        with self.assertRaisesRegex(ValueError, "core features changed"):
            check_packages.check_consumer_core_features(
                metadata, serde_enabled=False, schema_enabled=False
            )
        check_packages.check_consumer_core_features(
            metadata, serde_enabled=True, schema_enabled=False
        )
        node["features"] = []
        node["deps"] = [{"dep_kinds": [{"kind": None}]}]
        with self.assertRaisesRegex(ValueError, "bare core has a dependency"):
            check_packages.check_consumer_core_features(
                metadata, serde_enabled=False, schema_enabled=False
            )
        node["deps"] = []
        metadata["workspace_members"].append("other-package")
        with self.assertRaisesRegex(ValueError, "workspace is not isolated"):
            check_packages.check_consumer_core_features(
                metadata, serde_enabled=False, schema_enabled=False
            )

    def test_consumer_lock_pins_version_source_and_checksum(self) -> None:
        pinned = b"""[[package]]
name="third-party"
version="1.0.0"
source="registry+example"
checksum="abc"
"""
        baseline = check_packages.third_party_lock_entries(pinned)
        new_application = b"""[[package]]
name="consumer"
version="0.0.0"
"""
        self.assertEqual(
            check_packages.third_party_lock_entries(new_application + pinned), baseline
        )
        for before, after in [
            (b"1.0.0", b"1.0.1"),
            (b"registry+example", b"registry+other"),
            (b'checksum="abc"', b'checksum="def"'),
        ]:
            with self.subTest(change=after):
                self.assertFalse(
                    check_packages.third_party_lock_entries(
                        pinned.replace(before, after)
                    )
                    <= baseline
                )

    def test_revision_is_a_commit_id_without_command_terminator(self) -> None:
        with patch.object(check_packages, "run", side_effect=["a" * 40 + "\n", ""]):
            self.assertEqual(check_packages.source_state(), ("a" * 40, ""))

    def test_source_revision_or_worktree_change_is_not_accepted(self) -> None:
        initial = ("a" * 40, "")
        for current in (("b" * 40, ""), ("a" * 40, " M source.rs")):
            with (
                self.subTest(current=current),
                patch.object(check_packages, "source_state", return_value=current),
            ):
                with self.assertRaisesRegex(ValueError, "source checkout changed"):
                    check_packages.verify_source(initial)
        with patch.object(check_packages, "source_state", return_value=initial):
            check_packages.verify_source(initial)

    def test_failure_or_interruption_invalidates_previous_pass(self) -> None:
        for failure in (
            ValueError("private details"),
            OSError("private path"),
            subprocess.TimeoutExpired("private command", 900),
            KeyboardInterrupt(),
        ):
            with (
                self.subTest(error=type(failure).__name__),
                tempfile.TemporaryDirectory() as folder,
            ):
                root = Path(folder)
                output = root / "target/package-evidence.json"
                output.parent.mkdir()
                output.write_text(json.dumps({"overall": "passed"}), encoding="utf-8")

                def fail(*args: object) -> None:
                    self.assertEqual(
                        json.loads(output.read_bytes())["overall"], "incomplete"
                    )
                    raise failure

                with (
                    patch.object(check_packages, "ROOT", root),
                    patch.object(sys, "argv", ["check_packages"]),
                    patch.object(check_packages, "check_packages", side_effect=fail),
                ):
                    with self.assertRaises(type(failure)):
                        check_packages.main()
                report = json.loads(output.read_bytes())
                self.assertIn(report["overall"], ("failed", "incomplete"))
                self.assertNotIn("private", str(report))
