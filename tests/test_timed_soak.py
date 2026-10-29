"""Timed-memory protocol fixtures; native time trials run separately."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

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
    def test_native_units_and_duration_plans(self) -> None:
        for system in ("Windows", "Linux", "Darwin"):
            for seconds in (120, 600, 3600):
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
        for value in ("0", "60", "119", "121", "3601", "-120", "abc"):
            with self.assertRaises(argparse.ArgumentTypeError):
                soak.duration(value)

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
