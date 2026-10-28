"""Synthetic counter/runner regressions; actual SDK measurements run separately."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import peak_memory as probe


def observation(mode: str = "cached", system: str = "Windows") -> dict[str, Any]:
    multiplier = 1024 if system == "Linux" else 1
    calls = [0, 0, 0] if mode == "calibrate" else probe.STAGES[mode]
    samples = []
    for index, count in enumerate(calls):
        peak = 8 * 1024 * 1024
        if index and mode == "calibrate":
            peak += probe.PRESSURE
        samples.append(
            {
                "phase": (
                    ["baseline", "touched", "freed"][index]
                    if mode == "calibrate"
                    else ("baseline" if index == 0 else "collected")
                ),
                "calls": count,
                "peak_raw": peak // multiplier,
                "peak_bytes": peak,
                "elapsed_ns": 1000 if count else 0,
                "max_json_bytes": 5000 if count else 0,
            }
        )
    return {
        "format": 1,
        "mode": mode,
        "metric": "peak_working_set" if system == "Windows" else "ru_maxrss",
        "raw_unit": "kibibytes" if system == "Linux" else "bytes",
        "multiplier": multiplier,
        "pressure_bytes": probe.PRESSURE if mode == "calibrate" else 0,
        "samples": samples,
    }


class PeakMemory(unittest.TestCase):
    def test_all_platform_units_and_modes(self) -> None:
        for system in ("Windows", "Linux", "Darwin"):
            for mode in ("calibrate", "cached", "fresh"):
                with self.subTest(system=system, mode=mode):
                    probe.validate(observation(mode, system), mode, system)

    def test_linux_kib_and_darwin_bytes_cannot_be_interchanged(self) -> None:
        for system in ("Linux", "Darwin"):
            data = observation(system=system)
            data["multiplier"] = 1 if system == "Linux" else 1024
            with (
                self.subTest(system=system),
                self.assertRaisesRegex(ValueError, "unit_multiplier"),
            ):
                probe.validate(data, "cached", system)

    def test_booleans_negative_and_oversized_counters_rejected(self) -> None:
        for key in ("calls", "peak_raw", "peak_bytes", "elapsed_ns", "max_json_bytes"):
            for value in (True, -1, 2**65, "1", None):
                data = observation()
                data["samples"][1][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    probe.validate(data, "cached", "Windows")

    def test_truncated_stages_and_wrong_calls_are_not_accepted(self) -> None:
        for calls in (None, 99, 301):
            data = observation()
            if calls is None:
                data["samples"].pop()
            else:
                data["samples"][2]["calls"] = calls
            with self.subTest(calls=calls), self.assertRaises(ValueError):
                probe.validate(data, "cached", "Windows")

    def test_peak_cannot_decrease_after_free(self) -> None:
        data = observation("calibrate")
        data["samples"][2]["peak_raw"] = data["samples"][2]["peak_bytes"] = 1
        with self.assertRaisesRegex(ValueError, "peak_counter"):
            probe.validate(data, "calibrate", "Windows")

    def test_missing_or_double_unit_conversion_rejected(self) -> None:
        for factor in (1 / 1024, 1024):
            data = observation("calibrate")
            for sample in data["samples"]:
                sample["peak_raw"] = sample["peak_bytes"] = int(
                    sample["peak_bytes"] * factor
                )
            with (
                self.subTest(factor=factor),
                self.assertRaisesRegex(ValueError, "calibration_growth"),
            ):
                probe.validate(data, "calibrate", "Windows")

    def test_calibration_with_no_increase_is_not_a_measurement_pass(self) -> None:
        data = observation("calibrate")
        data["samples"][1] = deepcopy(data["samples"][0])
        data["samples"][1]["phase"] = "touched"
        with self.assertRaisesRegex(ValueError, "calibration_growth"):
            probe.validate(data, "calibrate", "Windows")

    def test_collected_json_cannot_be_empty(self) -> None:
        data = observation()
        data["samples"][1]["max_json_bytes"] = 0
        with self.assertRaisesRegex(ValueError, "json_empty"):
            probe.validate(data, "cached", "Windows")

    def test_source_normalization(self) -> None:
        with patch.object(probe, "run", side_effect=[b"a" * 40 + b"\n", b"\n"]):
            self.assertEqual(probe.source_state(), ("a" * 40, ""))

    def test_source_or_binary_mutation_invalidates_measurement(self) -> None:
        initial = ("a" * 40, "")
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "probe"
            binary.write_bytes(b"original")
            hashes = probe.fingerprint([binary])
            for current in (("b" * 40, ""), ("a" * 40, " M file")):
                with patch.object(probe, "source_state", return_value=current):
                    with self.assertRaisesRegex(ValueError, "source_changed"):
                        probe.verify_unchanged(initial, [binary], hashes)
            binary.write_bytes(b"replacement")
            with self.assertRaisesRegex(ValueError, "binaries_changed"):
                probe.verify_unchanged(initial, [binary], hashes)

    def test_failure_and_interruption_invalidate_old_pass_without_raw_error(
        self,
    ) -> None:
        for failure in (
            ValueError("private device"),
            KeyboardInterrupt(),
            subprocess.TimeoutExpired("private", 180),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                tempfile.TemporaryDirectory() as folder,
            ):
                root = Path(folder)
                output = root / "target/peak-memory-evidence.json"
                output.parent.mkdir()
                output.write_text('{"overall":"passed"}', encoding="utf-8")

                def fail(report: dict[str, Any]) -> None:
                    self.assertEqual(
                        json.loads(output.read_bytes())["overall"], "incomplete"
                    )
                    raise failure

                with (
                    patch.object(probe, "ROOT", root),
                    patch.object(probe, "measure", side_effect=fail),
                ):
                    with self.assertRaises(type(failure)):
                        probe.main()
                report = output.read_text(encoding="utf-8")
                self.assertNotEqual(json.loads(report)["overall"], "passed")
                self.assertNotIn("private", report)

    def test_runner_timeout_is_explicit_and_preserved(self) -> None:
        with patch.object(
            probe.subprocess, "run", side_effect=subprocess.TimeoutExpired("probe", 7)
        ) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                probe.run(["probe"], 7)
            self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_child_failure_does_not_expose_stderr(self) -> None:
        def failed(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            kwargs["stderr"].write(b"private device")
            return subprocess.CompletedProcess(arguments, 1)

        with patch.object(probe.subprocess, "run", side_effect=failed):
            with self.assertRaisesRegex(ValueError, "^peak_memory: child_failed$"):
                probe.run(["probe"])

    def test_oversized_child_output_rejected(self) -> None:
        def oversized(
            arguments: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess:
            kwargs["stdout"].write(b"x" * (2 * 1024 * 1024 + 1))
            return subprocess.CompletedProcess(arguments, 0)

        with patch.object(probe.subprocess, "run", side_effect=oversized):
            with self.assertRaisesRegex(ValueError, "output_limit"):
                probe.run(["probe"])
