"""Timed-memory protocol fixtures; native time trials run separately."""

import argparse
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
from typing import Any
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import timed_soak as soak


def records(system: str = "Windows", seconds: int = 120) -> list[Any]:
    factor = 4096 if system == "Linux" else 1
    metric, unit, multiplier, resident, resident_unit = {
        "Windows": ("peak_working_set", "bytes", 1, "working_set_size", "bytes"),
        "Linux": ("ru_maxrss", "kibibytes", 1024, "proc_statm_resident", "pages"),
        "Darwin": ("ru_maxrss", "bytes", 1, "mach_task_basic_resident", "bytes"),
    }[system]
    header = {
        "record": "header",
        "format": 1,
        "mode": "soak_cached",
        "duration_seconds": seconds,
        "checkpoint_seconds": 60,
        "call_interval_ms": 100,
        "warmup_seconds": 300 if seconds >= 600 else 60,
        "tail_budget_bytes": soak.BUDGET,
        "metric": metric,
        "raw_unit": unit,
        "multiplier": multiplier,
        "resident_metric": resident,
        "resident_raw_unit": resident_unit,
        "resident_multiplier": factor,
        "launch": {
            "strategy": "linux_fork" if system == "Linux" else "direct",
            "launcher_pid": 100,
            "measurement_pid": 101 if system == "Linux" else 100,
            "parent_death_signal": 9 if system == "Linux" else 0,
        },
    }
    result: list[Any] = [header]
    for index in range(seconds // 60 + 1):
        memory = 8 * 1024 * 1024 + index * 4096
        result.append(
            {
                "record": "sample",
                "ordinal": index,
                "observation": {
                    "phase": "collected" if index else "baseline",
                    "calls": index * 500,
                    "peak_raw": memory // multiplier,
                    "peak_bytes": memory,
                    "resident_raw": memory // factor,
                    "resident_bytes": memory,
                    "elapsed_ns": index * 60 * 10**9,
                    "max_json_bytes": 12345 if index else 0,
                },
            }
        )
    result.append(
        {
            "record": "complete",
            "calls": seconds // 60 * 500,
            "samples": seconds // 60 + 1,
        }
    )
    return result


class TimedSoakTests(unittest.TestCase):
    def test_real_child_is_reaped_after_cancel_marker(self) -> None:
        # Exercise OS process cleanup without a hardware read or a long trial.
        native_spawn = subprocess.Popen
        children = []

        def spawn(_arguments: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
            child = native_spawn(
                [sys.executable, "-c", "import time; time.sleep(2)"], **kwargs
            )
            children.append(child)
            return child

        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryFile() as output,
            tempfile.TemporaryFile() as error,
        ):
            marker = Path(directory) / "cancel"
            timer = threading.Timer(0.05, marker.touch)
            report: dict[str, Any] = {}
            timer.start()
            try:
                with patch.object(soak.subprocess, "Popen", side_effect=spawn):
                    with self.assertRaises(soak.TrialCancelled):
                        soak.run_trial(
                            Path("probe"),
                            120,
                            output,
                            error,
                            report,
                            cancel_file=marker,
                        )
                self.assertEqual(len(children), 1)
                self.assertIsNotNone(children[0].poll())
                self.assertTrue(report["probe_exit_confirmed"])
            finally:
                timer.cancel()
                timer.join()

    def test_native_units_and_duration_plans(self) -> None:
        for system in ("Windows", "Linux", "Darwin"):
            for seconds in (120, 600, 3600, 86400):
                result = soak.analyse(records(system, seconds), seconds, system)
                self.assertTrue(result["within_budget"])
                self.assertEqual(result["elapsed_ns"], seconds * 10**9)

    def test_incomplete_duplicate_and_out_of_order_records_fail(self) -> None:
        value = records()
        for bad in (
            value[:-1],
            value + [value[-1]],
            value[:2] + value[3:],
            value[:1] + list(reversed(value[1:-1])) + value[-1:],
        ):
            with self.assertRaises(ValueError):
                soak.analyse(bad, 120, "Windows")

    def test_changed_budget_warmup_and_boolean_counters_fail(self) -> None:
        for key, replacement in (
            ("tail_budget_bytes", soak.BUDGET + 1),
            ("warmup_seconds", 0),
            ("format", True),
            ("duration_seconds", 600),
        ):
            value = records()
            value[0][key] = replacement
            with self.assertRaisesRegex(ValueError, "plan_changed"):
                soak.analyse(value, 120, "Windows")
        value = records()
        value[2]["observation"]["calls"] = True
        with self.assertRaises(ValueError):
            soak.analyse(value, 120, "Windows")

    def test_early_late_and_frozen_workloads_fail(self) -> None:
        for field, value in (
            ("elapsed_ns", 59 * 10**9),
            ("elapsed_ns", 66 * 10**9),
            ("calls", 0),
            ("calls", 100000),
            ("max_json_bytes", 1024 * 1024 + 1),
        ):
            data = records()
            data[2]["observation"][field] = value
            with self.assertRaises(ValueError):
                soak.analyse(data, 120, "Windows")

    def test_metrics_conversions_and_completion_are_checked(self) -> None:
        for change in ("metric", "resident", "peak", "completion", "units"):
            data = records("Linux")
            if change == "metric":
                data[0]["metric"] = "unknown"
            elif change == "units":
                data[0]["resident_multiplier"] = 3
            elif change == "resident":
                data[2]["observation"]["resident_bytes"] += 1
            elif change == "peak":
                data[3]["observation"]["peak_bytes"] = 1
            else:
                data[-1]["calls"] += 1
            with self.assertRaises(ValueError):
                soak.analyse(data, 120, "Linux")

    def test_rss_drop_is_allowed_but_mid_run_excursion_remains_a_failure(self) -> None:
        data = records(seconds=600)
        for sample in data[1:-1]:
            sample["observation"]["peak_raw"] = sample["observation"]["peak_bytes"] = (
                64 * 1024 * 1024
            )
        first = data[6]["observation"]["resident_bytes"]
        data[-2]["observation"]["resident_bytes"] = data[-2]["observation"][
            "resident_raw"
        ] = first - 4096
        self.assertLess(soak.analyse(data, 600, "Windows")["net_change_bytes"], 0)
        data[8]["observation"]["resident_bytes"] = data[8]["observation"][
            "resident_raw"
        ] = first + soak.BUDGET + 1
        result = soak.analyse(data, 600, "Windows")
        self.assertFalse(result["within_budget"])
        self.assertGreater(result["tail_range_bytes"], soak.BUDGET)

    def test_duration_input_is_bounded(self) -> None:
        self.assertEqual(soak.duration("3600"), 3600)
        self.assertEqual(soak.duration("86400"), 86400)
        for value in (
            "0",
            "60",
            "119",
            "121",
            "3601",
            "86401",
            "86460",
            "999999",
            "-120",
            "abc",
        ):
            with self.assertRaises(argparse.ArgumentTypeError):
                soak.duration(value)

    def test_day_trace_fits_limit_and_requires_every_checkpoint(self) -> None:
        value = records(seconds=86400)
        raw = b"\n".join(json.dumps(item).encode() for item in value) + b"\n"
        self.assertEqual(len(value), 1443)
        self.assertLess(len(raw), soak.MAX_TRACE)
        self.assertEqual(soak.analyse(value, 86400, "Windows")["tail_samples"], 1436)
        with self.assertRaises(ValueError):
            soak.analyse(value[:-1], 86400, "Windows")
        value[721]["observation"]["resident_raw"] += soak.BUDGET
        value[721]["observation"]["resident_bytes"] += soak.BUDGET
        self.assertFalse(soak.analyse(value, 86400, "Windows")["within_budget"])

    def test_finished_probe_has_confirmed_exit_without_termination(self) -> None:
        child = Mock(pid=123)
        child.wait.return_value = 0
        report: dict[str, Any] = {"overall": "incomplete"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            with patch.object(soak.subprocess, "Popen", return_value=child):
                self.assertEqual(
                    soak.run_trial(
                        Path("probe"),
                        120,
                        io.BytesIO(),
                        io.BytesIO(),
                        report,
                        report_path=path,
                    ),
                    0,
                )
            progress = json.loads(path.read_bytes())
            self.assertEqual(progress["probe_pid"], 123)
            self.assertEqual(progress["overall"], "incomplete")
        self.assertTrue(report["probe_exit_confirmed"])
        child.kill.assert_not_called()

    def test_cancel_and_interrupt_terminate_and_confirm_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "stop"
            marker.touch()
            for requested in ("cancel", "interrupt", "already_exited"):
                child = Mock(pid=123)
                child.wait.side_effect = (
                    [KeyboardInterrupt(), -9] if requested == "interrupt" else [-9]
                )
                if requested == "already_exited":
                    child.kill.side_effect = PermissionError()
                report: dict[str, Any] = {}
                with patch.object(soak.subprocess, "Popen", return_value=child):
                    with self.assertRaises(
                        KeyboardInterrupt
                        if requested == "interrupt"
                        else soak.TrialCancelled
                    ):
                        soak.run_trial(
                            Path("probe"),
                            120,
                            io.BytesIO(),
                            io.BytesIO(),
                            report,
                            cancel_file=None if requested == "interrupt" else marker,
                        )
                child.kill.assert_called_once()
                self.assertTrue(report["probe_exit_confirmed"])
                self.assertTrue(marker.exists())

    def test_deadline_and_unconfirmed_termination_are_failures(self) -> None:
        child = Mock(pid=123)
        child.wait.return_value = -9
        report: dict[str, Any] = {}
        with (
            patch.object(soak.subprocess, "Popen", return_value=child),
            patch.object(soak.time, "monotonic", side_effect=[0, 181]),
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                soak.run_trial(Path("probe"), 120, io.BytesIO(), io.BytesIO(), report)
        self.assertTrue(report["probe_exit_confirmed"])
        child.kill.assert_called_once()
        child = Mock(pid=456)
        child.wait.side_effect = [
            KeyboardInterrupt(),
            subprocess.TimeoutExpired("probe", 10),
        ]
        report = {}
        with patch.object(soak.subprocess, "Popen", return_value=child):
            with self.assertRaisesRegex(ValueError, "probe_cleanup_unconfirmed"):
                soak.run_trial(Path("probe"), 120, io.BytesIO(), io.BytesIO(), report)
        self.assertFalse(report["probe_exit_confirmed"])
        self.assertEqual(report["probe_pid"], 456)

    def test_existing_cancel_marker_invalidates_old_pass_without_building(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"
            marker = Path(directory) / "stop"
            marker.touch()
            output.write_text('{"overall":"passed"}', encoding="utf-8")
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "timed_soak",
                        "--output",
                        str(output),
                        "--cancel-file",
                        str(marker),
                    ],
                ),
                patch.object(soak, "measure") as measure,
            ):
                with self.assertRaises(soak.TrialCancelled):
                    soak.main()
            measure.assert_not_called()
            self.assertEqual(json.loads(output.read_bytes())["overall"], "cancelled")

    def test_failed_and_interrupted_trials_invalidate_old_pass(self) -> None:
        for error, expected in (
            (ValueError("test"), "failed"),
            (KeyboardInterrupt(), "incomplete"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "trial.json"
                output.write_text('{"overall":"passed"}', encoding="utf-8")
                with (
                    patch.object(sys, "argv", ["timed_soak", "--output", str(output)]),
                    patch.object(soak, "measure", side_effect=error),
                ):
                    with self.assertRaises(type(error)):
                        soak.main()
                self.assertEqual(json.loads(output.read_bytes())["overall"], expected)


if __name__ == "__main__":
    unittest.main()
