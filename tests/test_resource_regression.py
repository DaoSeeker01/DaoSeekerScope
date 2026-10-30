"""Protocol fixtures; OS calibration and real collect/free run separately."""

import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import resource_regression as resource


def observation(mode: str = "cached", system: str = "Windows") -> dict[str, Any]:
    base: dict[str, Any] = {
        "format": 1,
        "mode": mode,
        "metric": resource.METRICS[system],
    }
    if mode == "calibrate":
        return base | {"opened_resources": 32, "counts": [10, 42, 10]}
    return base | {
        "warmup_calls": 100,
        "total_calls": 1000,
        "interval_calls": 100,
        "tail_budget": 8,
        "control_resources": 16 if mode == "control" else 0,
        "max_json_bytes": 1000,
        "completed": True,
        "samples": [
            {
                "calls": index * 100,
                "count": 10 + (16 if mode == "control" and index > 1 else 0),
            }
            for index in range(1, 11)
        ],
    }


class ResourceRegressionTests(unittest.TestCase):
    def test_native_metrics_calibrate_and_detect_control(self) -> None:
        for system in resource.METRICS:
            for mode in ("calibrate", "cached", "control"):
                result = resource.analyse(observation(mode, system), mode, system)
                self.assertIs(
                    result.get("passed", result.get("within_budget")), mode != "control"
                )

    def test_bad_calibration_and_failed_close(self) -> None:
        for counts in (
            [10, 41, 10],
            [10, 42, 11],
            [10, 42],
            [True, 33, True],
            [10, -1, 10],
        ):
            data = observation("calibrate")
            data["counts"] = counts
            with self.assertRaises(ValueError):
                resource.analyse(data, "calibrate", "Windows")

    def test_plan_and_metric_changes(self) -> None:
        for key, value in (
            ("format", True),
            ("mode", "control"),
            ("metric", "unknown"),
            ("warmup_calls", 200),
            ("total_calls", 500),
            ("interval_calls", 1),
            ("tail_budget", 9),
            ("control_resources", 16),
            ("completed", 1),
            ("max_json_bytes", 1048577),
        ):
            data = observation()
            data[key] = value
            with self.assertRaises(ValueError):
                resource.analyse(data, "cached", "Windows")

    def test_missing_duplicate_reversed_and_invalid_samples(self) -> None:
        for change in (
            "missing",
            "duplicate",
            "reverse",
            "boolean",
            "negative",
            "huge",
        ):
            data = observation()
            samples = data["samples"]
            if change == "missing":
                samples.pop()
            elif change == "duplicate":
                samples[2] = samples[1]
            elif change == "reverse":
                samples.reverse()
            else:
                samples[2]["count"] = {
                    "boolean": True,
                    "negative": -1,
                    "huge": 1048577,
                }[change]
            with self.assertRaises(ValueError):
                resource.analyse(data, "cached", "Windows")

    def test_drop_allowed_but_spike_not_hidden(self) -> None:
        data = observation()
        data["samples"][-1]["count"] = 9
        self.assertEqual(resource.analyse(data, "cached", "Windows")["net_change"], -1)
        data["samples"][4]["count"] = 19
        result = resource.analyse(data, "cached", "Windows")
        self.assertFalse(result["within_budget"])
        self.assertEqual(result["tail_range"], 10)

    def test_boundary_and_zero_counts(self) -> None:
        data = observation()
        data["samples"][4]["count"] = 18
        self.assertTrue(resource.analyse(data, "cached", "Windows")["within_budget"])
        for sample in data["samples"]:
            sample["count"] = 0
        self.assertTrue(resource.analyse(data, "cached", "Windows")["within_budget"])

    def test_failure_and_interrupt_replace_old_success(self) -> None:
        for error, state in (
            (ValueError("test"), "failed"),
            (KeyboardInterrupt(), "incomplete"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "resources.json"
                output.write_text('{"overall":"passed"}', encoding="utf-8")
                with (
                    patch.object(sys, "argv", ["resources", "--output", str(output)]),
                    patch.object(resource, "measure", side_effect=error),
                ):
                    with self.assertRaises(type(error)):
                        resource.main()
                self.assertEqual(json.loads(output.read_bytes())["overall"], state)


if __name__ == "__main__":
    unittest.main()
