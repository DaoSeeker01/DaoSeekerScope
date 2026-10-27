"""A failed or interrupted packaging run must not leave a previous success report."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_packages


class PackageEvidence(unittest.TestCase):
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
