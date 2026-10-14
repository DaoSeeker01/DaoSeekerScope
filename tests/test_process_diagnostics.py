"""Synthetic subprocess failures validate diagnostics, never hardware support."""

import ast
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import native_smoke as smoke


class ProcessDiagnostics(unittest.TestCase):
    def test_existing_container_callers_keep_accepted_fixed_labels(self) -> None:
        labels: set[str] = set()
        for name in ("linux_container_smoke.py", "linux_dynamic_smoke.py"):
            tree = ast.parse((smoke.ROOT / "scripts" / name).read_text("utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "run"
                ):
                    label = ast.literal_eval(node.args[1])
                    self.assertIsInstance(label, str)
                    labels.add(label)
        result = subprocess.CompletedProcess([], 0, b"unit", b"")
        for label in labels:
            with patch.object(smoke.subprocess, "run", return_value=result):
                self.assertEqual(smoke.run(["unit-command"], label), b"unit")

    def test_cli_codes_require_exact_bounded_messages_and_expected_exit(self) -> None:
        for token, code in smoke.SCOPE_ERRORS.items():
            message = b"dscope: collection error: " + token + b"\r\n"
            self.assertEqual(smoke.scope_error("cli_text_cpu", 3, message), code)
            self.assertEqual(smoke.scope_error("storage_text", 3, message), code)
            for bad in [
                message + b"private-id",
                b"private-id\n" + message,
                message + b"\n",
                b"x" * 513,
                b"\xff" + message,
            ]:
                self.assertIsNone(smoke.scope_error("cli_text_cpu", 3, bad))
            self.assertIsNone(smoke.scope_error("cli_text_cpu", 2, message))
            self.assertIsNone(smoke.scope_error("python_ffi", 3, message))

    def test_c_error_codes_are_classified_without_copying_stderr_or_args(self) -> None:
        for message, code in smoke.C_ERRORS.items():
            self.assertEqual(smoke.scope_error("c_abi", 2, message + b"\n"), code)
            self.assertIsNone(smoke.scope_error("c_abi", 3, message))
        diagnostics: dict = {}
        result = subprocess.CompletedProcess(
            ["private-path"], 3, b"private-stdout", b"private-stderr"
        )
        with (
            patch.object(smoke.subprocess, "run", return_value=result),
            self.assertRaises(smoke.ProcessFailure) as caught,
        ):
            smoke.run(
                ["private-path", "private-argument"], "cli_text_memory", diagnostics
            )
        encoded = json.dumps(diagnostics)
        self.assertNotIn("private", encoded)
        self.assertEqual(caught.exception.diagnostic["return_code"], 3)
        self.assertIsNone(caught.exception.diagnostic["scope_error"])
        self.assertEqual(diagnostics["cli_text_memory"]["status"], "failed")

    def test_timeout_and_missing_process_preserve_sanitized_cause(self) -> None:
        for error, category in [
            (
                subprocess.TimeoutExpired(
                    ["private-path"],
                    60,
                    output=b"private-output",
                    stderr=b"private-stderr",
                ),
                "timeout",
            ),
            (
                FileNotFoundError(2, "private-system-error", "private-path"),
                "process_unavailable",
            ),
        ]:
            with patch.object(smoke.subprocess, "run", side_effect=error):
                command = ["private-path"]
                try:
                    smoke.run(command, "cli_text_cpu")
                except smoke.ProcessFailure as failure:
                    self.assertEqual(failure.diagnostic["failure_category"], category)
                    self.assertIsNone(failure.diagnostic["scope_error"])
                    self.assertIsNone(failure.diagnostic["return_code"])
                    self.assertIsNone(failure.__context__)
                    self.assertNotIn(
                        "private", "".join(traceback.format_exception(failure))
                    )
                else:
                    self.fail("failure required")

    def test_output_limits_and_untrusted_labels_do_not_leak(self) -> None:
        for stdout, stderr in [
            (b"x" * (smoke.MAX_JSON_BYTES + 2), b""),
            (b"", b"x" * (smoke.MAX_JSON_BYTES + 1)),
        ]:
            result = subprocess.CompletedProcess([], 0, stdout, stderr)
            with (
                patch.object(smoke.subprocess, "run", return_value=result),
                self.assertRaises(smoke.ProcessFailure) as caught,
            ):
                smoke.run([], "cli")
            self.assertEqual(
                caught.exception.diagnostic["failure_category"], "output_limit"
            )
        with (
            patch.object(smoke.subprocess, "run") as child,
            self.assertRaises(smoke.ValidationFailure) as invalid_label,
        ):
            smoke.run(["private-path"], "private-label")
        child.assert_not_called()
        self.assertEqual(str(invalid_label.exception), "process: invalid_label")

    def test_actual_child_failure_has_fixed_scope_code_and_no_raw_data(self) -> None:
        diagnostics: dict = {}
        with self.assertRaises(smoke.ProcessFailure) as caught:
            smoke.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.write('private-id'); sys.stderr.write('dscope: collection error: Timeout\\n'); sys.exit(3)",
                ],
                "cli_text_cpu",
                diagnostics,
            )
        self.assertEqual(caught.exception.diagnostic["scope_error"], "timeout")
        self.assertNotIn("private-id", json.dumps(diagnostics))
        self.assertEqual(
            smoke.run(
                [sys.executable, "-c", "print('ok')"], "cli", diagnostics
            ).strip(),
            b"ok",
        )
        self.assertEqual(diagnostics["cli"]["status"], "passed")

    def partial_collect(self, _directory: Path, report: dict) -> None:
        # Keep the first command's presentation result when the second command fails.
        cpu = b"CPU: Fixture CPU (Custom)\nArchitecture: x86_64 (Custom)\nLogical CPUs: 4 (Custom)\nPhysical cores: 2 (Custom)\nUsage percent: 0 (Procfs)\n"
        with patch.object(
            smoke.subprocess,
            "run",
            side_effect=[
                subprocess.CompletedProcess([], 0, cpu, b""),
                subprocess.CompletedProcess(
                    [], 3, b"", b"dscope: collection error: Timeout\n"
                ),
            ],
        ):
            smoke.collect_cli_text(Path("private-cli-path"), report)

    def test_report_keeps_partial_progress_failure_detail_and_no_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with (
                patch.object(sys, "argv", ["native_smoke", "--output", str(output)]),
                patch.object(smoke, "collect", side_effect=self.partial_collect),
                patch.object(sys, "stdout", io.StringIO()),
            ):
                self.assertEqual(smoke.main(), 1)
            report = json.loads(output.read_text())
            self.assertEqual(report["failure"], "cli_text_memory: process_failed")
            self.assertEqual(report["failure_detail"]["scope_error"], "timeout")
            self.assertEqual(report["checks"]["cli_text"], "failed")
            self.assertEqual(set(report["observations"]["cli_text"]), {"cpu"})
            self.assertEqual(
                report["processes"]["cli_text_system"]["status"], "not_run"
            )
            self.assertNotIn("private", json.dumps(report))

    def test_interruption_keeps_partial_progress_without_old_success(self) -> None:
        def interrupt(_directory: Path, report: dict) -> None:
            report["checks"]["cli_text"] = "running"
            report["observations"]["cli_text"] = {"cpu": {"available_fields": 5}}
            report["processes"]["cli_text_memory"] = {"status": "running"}
            raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            output.write_text('{"overall":"passed"}')
            with (
                patch.object(sys, "argv", ["native_smoke", "--output", str(output)]),
                patch.object(smoke, "collect", side_effect=interrupt),
                self.assertRaises(KeyboardInterrupt),
            ):
                smoke.main()
            report = json.loads(output.read_text())
            self.assertEqual(report["overall"], "incomplete")
            self.assertIn("cpu", report["observations"]["cli_text"])
            self.assertEqual(
                report["processes"]["cli_text_memory"]["status"], "interrupted"
            )


if __name__ == "__main__":
    unittest.main()
