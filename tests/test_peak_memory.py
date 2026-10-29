"""Synthetic counter/runner regressions; actual SDK measurements run separately."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import peak_memory as probe


def observation(mode: str = "cached", system: str = "Windows") -> dict[str, Any]:
    multiplier = 1024 if system == "Linux" else 1
    calibration = mode in ("calibrate", "resident_calibrate")
    calls = [0, 0, 0] if calibration else probe.STAGES[mode]
    samples = []
    for index, count in enumerate(calls):
        peak = 8 * 1024 * 1024
        if index and calibration:
            peak += probe.PRESSURE
        samples.append(
            {
                "phase": (
                    ["baseline", "touched", "freed"][index]
                    if calibration
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
        "pressure_bytes": probe.PRESSURE if calibration else 0,
        "samples": samples,
    }


def current_observation(
    mode: str = "cached", system: str = "Linux", strategy: str | None = None
) -> dict[str, Any]:
    data = observation(mode, system)
    strategy = strategy or ("linux_fork" if system == "Linux" else "direct")
    data.update(
        format=2,
        launch={
            "strategy": strategy,
            "launcher_pid": 101,
            "measurement_pid": 201 if strategy == "linux_fork" else 101,
            "parent_death_signal": 9 if strategy == "linux_fork" else 0,
        },
    )
    if mode in ("synthetic", "over_limit", "growth_synthetic"):
        data["workload"] = {
            "synthetic_data": True,
            "backends": 2,
            "sensors_generated": 100,
            "networks_generated": 1025 if mode == "over_limit" else 1024,
            "max_entries": 1024,
            "first_batch_refreshes": 0,
            "second_batch_refreshes": 100,
            "json_roundtrip": True,
        }
        if mode == "growth_synthetic":
            del data["workload"]["first_batch_refreshes"]
            del data["workload"]["second_batch_refreshes"]
            data["workload"].update(refreshes_per_batch=100, batches=60)
    return data


def resident_observation(
    mode: str = "growth_cached", system: str = "Windows"
) -> dict[str, Any]:
    data = current_observation(mode, system)
    factor = 4096 if system == "Linux" else 1
    data.update(
        resident_metric={
            "Windows": "working_set_size",
            "Linux": "proc_statm_resident",
            "Darwin": "mach_task_basic_resident",
        }[system],
        resident_raw_unit="pages" if system == "Linux" else "bytes",
        resident_multiplier=factor,
    )
    if mode != "resident_calibrate":
        data["growth_plan"] = {
            "warmup_calls": 1000 if mode == "growth_cached" else 10,
            "tail_budget_bytes": probe.TAIL_BUDGET,
        }
    for index, sample in enumerate(data["samples"]):
        value = 8 * 1024 * 1024 + (
            probe.PRESSURE if mode == "resident_calibrate" and index == 1 else 0
        )
        sample.update(resident_raw=value // factor, resident_bytes=value)
    return data


class PeakMemory(unittest.TestCase):
    def test_resident_calibration_and_growth_modes_on_all_platforms(self) -> None:
        for system in ("Windows", "Linux", "Darwin"):
            for mode in ("resident_calibrate", "growth_cached", "growth_synthetic"):
                item = {"observation": resident_observation(mode, system)}
                with self.subTest(system=system, mode=mode):
                    probe.accept_resident_entry(item, mode, system)
                    self.assertTrue(item["accepted"])

    def test_current_residency_can_fall_while_historical_peak_stays_high(self) -> None:
        data = resident_observation()
        for sample in data["samples"]:
            sample["peak_raw"] = sample["peak_bytes"] = 128 * 1024 * 1024
        data["samples"][-1].update(
            resident_raw=4 * 1024 * 1024, resident_bytes=4 * 1024 * 1024
        )
        analysis = probe.resident_analysis(data, "growth_cached", "Windows")
        self.assertEqual(analysis["net_change_bytes"], -4 * 1024 * 1024)
        self.assertTrue(analysis["within_budget"])

    def test_peak_alone_cannot_be_accepted_as_current_resident_measurement(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "resident_metric"):
            probe.resident_analysis(
                current_observation("growth_cached", "Windows"),
                "growth_cached",
                "Windows",
            )

    def test_exceeded_budget_is_retained_and_rejected(self) -> None:
        data = resident_observation()
        value = 8 * 1024 * 1024 + probe.TAIL_BUDGET + 1
        data["samples"][-1].update(resident_raw=value, resident_bytes=value)
        item: dict[str, Any] = {"observation": data, "accepted": True}
        with self.assertRaisesRegex(ValueError, "resident_budget_exceeded"):
            probe.accept_resident_entry(item, "growth_cached", "Windows")
        self.assertFalse(item["accepted"])
        self.assertEqual(item["analysis"]["tail_range_bytes"], probe.TAIL_BUDGET + 1)

    def test_budget_and_warmup_cannot_be_changed_to_hide_growth(self) -> None:
        for key, value in (
            ("tail_budget_bytes", probe.TAIL_BUDGET * 2),
            ("warmup_calls", 5000),
        ):
            data = resident_observation()
            data["growth_plan"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                probe.resident_analysis(data, "growth_cached", "Windows")

    def test_missing_checkpoints_are_not_accepted(self) -> None:
        data = resident_observation()
        data["samples"].pop(4)
        with self.assertRaisesRegex(ValueError, "stages"):
            probe.resident_analysis(data, "growth_cached", "Windows")

    def test_resident_units_and_counter_ranges_are_strict(self) -> None:
        for key, value in (
            ("resident_raw", True),
            ("resident_bytes", -1),
            ("resident_raw", 2**64),
            ("resident_bytes", "1"),
        ):
            data = resident_observation(system="Linux")
            data["samples"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                probe.resident_analysis(data, "growth_cached", "Linux")
        data = resident_observation(system="Darwin")
        data["resident_multiplier"] = 1024
        with self.assertRaisesRegex(ValueError, "resident_multiplier"):
            probe.resident_analysis(data, "growth_cached", "Darwin")

    def test_calibration_without_visible_current_increase_is_rejected(self) -> None:
        data = resident_observation("resident_calibrate")
        for sample in data["samples"]:
            sample.update(resident_raw=8 * 1024 * 1024, resident_bytes=8 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, "resident_calibration_growth"):
            probe.resident_analysis(data, "resident_calibrate", "Windows")

    def test_tail_range_checks_middle_spikes_not_only_endpoints(self) -> None:
        data = resident_observation()
        data["samples"][4].update(
            resident_raw=128 * 1024 * 1024, resident_bytes=128 * 1024 * 1024
        )
        analysis = probe.resident_analysis(data, "growth_cached", "Windows")
        self.assertEqual(analysis["net_change_bytes"], 0)
        self.assertFalse(analysis["within_budget"])

    def test_synthetic_profiles_have_their_own_bounded_stages(self) -> None:
        for system in ("Windows", "Linux", "Darwin"):
            for mode in ("synthetic", "over_limit"):
                with self.subTest(system=system, mode=mode):
                    probe.validate(current_observation(mode, system), mode, system)

    def test_synthetic_profile_without_fixture_disclosure_is_rejected(self) -> None:
        data = current_observation("synthetic")
        del data["workload"]
        with self.assertRaisesRegex(ValueError, "synthetic_workload"):
            probe.validate(data, "synthetic", "Linux")

    def test_synthetic_scale_cannot_be_relabelled_as_a_smaller_or_unbounded_run(
        self,
    ) -> None:
        for key in (
            "backends",
            "sensors_generated",
            "networks_generated",
            "max_entries",
            "second_batch_refreshes",
        ):
            for invalid in (True, -1, 0, 2**64):
                data = current_observation("synthetic")
                data["workload"][key] = invalid
                with (
                    self.subTest(key=key, invalid=invalid),
                    self.assertRaisesRegex(ValueError, "synthetic_scale"),
                ):
                    probe.validate(data, "synthetic", "Linux")

    def test_over_limit_profile_must_report_generated_1025_not_retained_entries(
        self,
    ) -> None:
        data = current_observation("over_limit")
        data["workload"]["networks_generated"] = 1024
        with self.assertRaisesRegex(ValueError, "synthetic_scale"):
            probe.validate(data, "over_limit", "Linux")

    def test_fixture_label_and_roundtrip_checks_are_required(self) -> None:
        for key in ("synthetic_data", "json_roundtrip"):
            data = current_observation("synthetic")
            data["workload"][key] = False
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "synthetic_contract"),
            ):
                probe.validate(data, "synthetic", "Linux")

    def test_native_stages_cannot_be_substituted_for_synthetic_stages(self) -> None:
        data = current_observation("synthetic")
        data["samples"] = observation("cached")["samples"]
        with self.assertRaisesRegex(ValueError, "stages"):
            probe.validate(data, "synthetic", "Linux")

    def test_pidfd_cleanup_closes_handle_even_when_signal_fails(self) -> None:
        for error in (None, ProcessLookupError(), PermissionError()):
            with (
                self.subTest(error=type(error).__name__),
                patch.object(
                    probe.signal, "pidfd_send_signal", create=True, side_effect=error
                ) as send,
                patch.object(probe.os, "close") as close,
            ):
                if isinstance(error, PermissionError):
                    with self.assertRaises(PermissionError):
                        probe.close_worker_handle(123, stop=True)
                else:
                    probe.close_worker_handle(123, stop=True)
                send.assert_called_once_with(123, 9)
                close.assert_called_once_with(123)

    def test_unowned_pidfd_is_closed_without_signalling(self) -> None:
        with (
            patch.object(probe.signal, "pidfd_send_signal", create=True) as send,
            patch.object(probe.os, "close") as close,
        ):
            probe.close_worker_handle(123, stop=False)
            send.assert_not_called()
            close.assert_called_once_with(123)

    def test_legacy_report_cannot_claim_current_launch_acceptance(self) -> None:
        with self.assertRaisesRegex(ValueError, "current_format_required"):
            probe.validate(
                observation(system="Linux"),
                "cached",
                "Linux",
                expected_launch="linux_fork",
            )

    def test_current_format_for_all_platforms_and_modes(self) -> None:
        for system in ("Windows", "Linux", "Darwin"):
            for mode in ("calibrate", "cached", "fresh"):
                with self.subTest(system=system, mode=mode):
                    data = current_observation(mode, system)
                    probe.validate(
                        data, mode, system, expected_launch=data["launch"]["strategy"]
                    )

    def test_invalid_pids_and_missing_death_signal_are_rejected(self) -> None:
        for key in ("launcher_pid", "measurement_pid", "parent_death_signal"):
            for value in (None, True, 0, -1, 2**32):
                data = current_observation()
                data["launch"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    probe.validate(
                        data, "cached", "Linux", expected_launch="linux_fork"
                    )

    def test_direct_or_same_pid_cannot_claim_isolation(self) -> None:
        data = current_observation(strategy="direct")
        with self.assertRaisesRegex(ValueError, "launch_strategy"):
            probe.validate(data, "cached", "Linux", expected_launch="linux_fork")
        data = current_observation()
        data["launch"]["measurement_pid"] = data["launch"]["launcher_pid"]
        with self.assertRaisesRegex(ValueError, "launch_contract"):
            probe.validate(data, "cached", "Linux", expected_launch="linux_fork")

    def test_pressure_control_requires_visible_mask_and_isolated_baseline(self) -> None:
        direct = current_observation(strategy="direct")
        isolated = current_observation()
        for sample in direct["samples"]:
            sample["peak_bytes"] += probe.LAUNCH_PRESSURE
            sample["peak_raw"] = sample["peak_bytes"] // 1024
        probe.check_launch_control(direct, isolated)
        for invalid in (deepcopy(direct), deepcopy(isolated)):
            invalid["launch"]["strategy"] = "direct"
            invalid["launch"]["measurement_pid"] = 101
            invalid["launch"]["parent_death_signal"] = 0
            with self.assertRaises(ValueError):
                probe.check_launch_control(invalid, invalid)
        with self.assertRaisesRegex(ValueError, "launch_pressure_mask"):
            probe.check_launch_control(current_observation(strategy="direct"), isolated)

    def test_proc_state_handles_spaces_and_parentheses_in_comm(self) -> None:
        fields = ["S", "101"] + ["0"] * 17 + ["999"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stat"
            path.write_bytes(b"201 (name with ) bracket) " + " ".join(fields).encode())
            with patch.object(probe, "Path", return_value=path):
                self.assertEqual(
                    probe.process_state(201),
                    {"state": "S", "parent_pid": 101, "start_ticks": 999},
                )
            path.write_bytes(b"x" * 8193)
            with patch.object(probe, "Path", return_value=path):
                with self.assertRaisesRegex(ValueError, "process_stat_limit"):
                    probe.process_state(201)

    def test_proc_state_missing_process_is_gone(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(probe, "Path", return_value=Path(folder) / "missing"):
                self.assertIsNone(probe.process_state(201))

    def lifecycle_process(self) -> MagicMock:
        process = MagicMock()
        process.pid = 101
        process.poll.return_value = -9
        data = {
            "format": 2,
            "lifecycle": True,
            "launch": current_observation()["launch"],
        }
        process.communicate.side_effect = subprocess.TimeoutExpired(
            "probe", 3, output=json.dumps(data).encode()
        )
        return process

    def test_lifecycle_reaps_launcher_and_records_stopped_worker(self) -> None:
        process = self.lifecycle_process()
        identity = {"state": "S", "parent_pid": 101, "start_ticks": 22}
        zombie = dict(identity, state="Z")
        with (
            patch.object(probe.subprocess, "Popen") as popen,
            patch.object(probe, "process_state", side_effect=[identity, zombie, None]),
            patch.object(probe, "open_worker_handle", return_value=123),
            patch.object(probe, "close_worker_handle") as close,
        ):
            popen.return_value.__enter__.return_value = process
            result = probe.linux_lifecycle(Path("probe"))
        self.assertTrue(result["passed"])
        self.assertFalse(result["worker_running"])
        self.assertEqual(result["worker_exit_state"], "zombie_waiting_for_reaper")
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)
        close.assert_called_once_with(123, stop=True)

    def test_recycled_worker_pid_is_never_signalled(self) -> None:
        process = self.lifecycle_process()
        identity = {"state": "S", "parent_pid": 101, "start_ticks": 22}
        replacement = dict(identity, start_ticks=23)
        with (
            patch.object(probe.subprocess, "Popen") as popen,
            patch.object(
                probe, "process_state", side_effect=[identity, replacement, replacement]
            ),
            patch.object(probe, "open_worker_handle", return_value=123),
            patch.object(probe, "close_worker_handle") as close,
            patch.object(probe.os, "kill") as kill,
        ):
            popen.return_value.__enter__.return_value = process
            result = probe.linux_lifecycle(Path("probe"))
        self.assertEqual(result["worker_exit_state"], "pid_reused_original_gone")
        kill.assert_not_called()
        close.assert_called_once_with(123, stop=True)

    def test_worker_that_survives_parent_is_failure_and_is_cleaned_up(self) -> None:
        process = self.lifecycle_process()
        identity = {"state": "S", "parent_pid": 101, "start_ticks": 22}
        with (
            patch.object(probe.subprocess, "Popen") as popen,
            patch.object(probe, "process_state", return_value=identity),
            patch.object(probe.time, "monotonic", side_effect=[0, 6]),
            patch.object(probe, "open_worker_handle", return_value=123),
            patch.object(probe, "close_worker_handle") as close,
        ):
            popen.return_value.__enter__.return_value = process
            with self.assertRaisesRegex(ValueError, "worker_survived_launcher"):
                probe.linux_lifecycle(Path("probe"))
        close.assert_called_once_with(123, stop=True)

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
