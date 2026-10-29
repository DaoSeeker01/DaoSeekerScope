"""Measure release C ABI process high-water memory in three separate processes."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import tempfile
import time
from typing import Any

import jsonschema

from native_smoke import check_snapshot

ROOT = Path(__file__).resolve().parent.parent
PRESSURE = 64 * 1024 * 1024
LAUNCH_PRESSURE = 128 * 1024 * 1024
STAGES = {
    "cached": [0, 1, 100, 300],
    "fresh": [0, 1, 10, 30],
    "synthetic": [0, 1, 2],
    "over_limit": [0, 1, 2],
}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(f"peak_memory: {code}")


def run(arguments: list[str], timeout: int = 180) -> bytes:
    # Bound captured output and caller wait. Never copy raw child errors to evidence.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            arguments, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=timeout
        )
        require(result.returncode == 0, "child_failed")
        stdout.seek(0)
        output = stdout.read(2 * 1024 * 1024 + 1)
        require(len(output) <= 2 * 1024 * 1024, "output_limit")
        return output


def source_state() -> tuple[str, str]:
    return (
        run(["git", "rev-parse", "HEAD"], 10).decode().strip(),
        run(["git", "status", "--porcelain"], 10).decode().strip(),
    )


def validate_launch(data: Any, expected: str) -> dict[str, Any]:
    require(
        isinstance(data, dict) and data.get("strategy") == expected, "launch_strategy"
    )
    for key in ("launcher_pid", "measurement_pid"):
        require(type(data.get(key)) is int and 0 < data[key] <= 2**31 - 1, "launch_pid")
    require(type(data.get("parent_death_signal")) is int, "parent_death_signal")
    require(
        (
            data["measurement_pid"] != data["launcher_pid"]
            if expected == "linux_fork"
            else data["measurement_pid"] == data["launcher_pid"]
        )
        and data["parent_death_signal"] == (9 if expected == "linux_fork" else 0),
        "launch_contract",
    )
    return data


def validate(
    data: Any, mode: str, system: str, *, expected_launch: str | None = None
) -> dict[str, Any]:
    require(isinstance(data, dict), "object")
    require(type(data.get("format")) is int and data["format"] in (1, 2), "format")
    if expected_launch is not None:
        require(data["format"] == 2, "current_format_required")
    if data["format"] == 2:
        launch = expected_launch or ("linux_fork" if system == "Linux" else "direct")
        validate_launch(data.get("launch"), launch)
    require(data.get("mode") == mode, "mode")
    if mode in ("synthetic", "over_limit"):
        workload = data.get("workload")
        require(isinstance(workload, dict), "synthetic_workload")
        require(
            workload.get("synthetic_data") is True
            and workload.get("json_roundtrip") is True,
            "synthetic_contract",
        )
        for key, expected in {
            "backends": 2,
            "sensors_generated": 100,
            "networks_generated": 1025 if mode == "over_limit" else 1024,
            "max_entries": 1024,
            "first_batch_refreshes": 0,
            "second_batch_refreshes": 100,
        }.items():
            require(
                type(workload.get(key)) is int and workload[key] == expected,
                "synthetic_scale",
            )
    metric, unit, multiplier = {
        "Windows": ("peak_working_set", "bytes", 1),
        "Linux": ("ru_maxrss", "kibibytes", 1024),
        "Darwin": ("ru_maxrss", "bytes", 1),
    }[system]
    require(data.get("metric") == metric and data.get("raw_unit") == unit, "metric")
    require(
        type(data.get("multiplier")) is int and data["multiplier"] == multiplier,
        "unit_multiplier",
    )
    require(
        type(data.get("pressure_bytes")) is int
        and data["pressure_bytes"] == (PRESSURE if mode == "calibrate" else 0),
        "pressure",
    )
    samples = data.get("samples")
    stages = [0, 0, 0] if mode == "calibrate" else STAGES[mode]
    require(isinstance(samples, list) and len(samples) == len(stages), "stages")
    previous_peak = 0
    for index, (sample, calls) in enumerate(zip(samples, stages, strict=True)):
        require(isinstance(sample, dict), "sample")
        for key in ("calls", "peak_raw", "peak_bytes", "elapsed_ns", "max_json_bytes"):
            require(type(sample.get(key)) is int, "counter_type")
        expected_phase = (
            ["baseline", "touched", "freed"][index]
            if mode == "calibrate"
            else ("baseline" if index == 0 else "collected")
        )
        require(sample.get("phase") == expected_phase, "phase")
        require(sample["calls"] == calls, "calls")
        raw, peak = sample["peak_raw"], sample["peak_bytes"]
        require(0 < raw <= (2**64 - 1) // multiplier, "raw_range")
        require(peak == raw * multiplier and peak >= previous_peak, "peak_counter")
        previous_peak = peak
        require(0 <= sample["elapsed_ns"] <= 600 * 10**9, "elapsed_range")
        require(0 <= sample["max_json_bytes"] <= 1024 * 1024, "json_range")
        if calls == 0:
            require(sample["elapsed_ns"] == sample["max_json_bytes"] == 0, "idle")
        else:
            require(sample["max_json_bytes"] > 0, "json_empty")
    if mode == "calibrate":
        growth = samples[1]["peak_bytes"] - samples[0]["peak_bytes"]
        # Tolerate baseline/OS noise, while rejecting a missing or extra 1024 factor.
        require(PRESSURE // 2 <= growth <= PRESSURE * 2, "calibration_growth")
    return data


def check_launch_control(direct: dict[str, Any], isolated: dict[str, Any]) -> None:
    """Require a visible dirty-parent counter and a separate small C baseline."""
    validate(direct, "cached", "Linux", expected_launch="direct")
    validate(isolated, "cached", "Linux", expected_launch="linux_fork")
    old = direct["samples"][0]["peak_bytes"]
    new = isolated["samples"][0]["peak_bytes"]
    require(
        old >= LAUNCH_PRESSURE and old - new >= LAUNCH_PRESSURE // 2,
        "launch_pressure_mask",
    )


def process_state(pid: int) -> dict[str, Any] | None:
    """Read bounded Linux state/start time; never signal a recycled PID."""
    try:
        with Path(f"/proc/{pid}/stat").open("rb") as stream:
            raw = stream.read(8193)
    except FileNotFoundError:
        return None
    require(len(raw) <= 8192, "process_stat_limit")
    fields = raw.rsplit(b")", 1)[-1].split()
    require(len(fields) >= 20, "process_stat")
    return {
        "state": fields[0].decode("ascii"),
        "parent_pid": int(fields[1]),
        "start_ticks": int(fields[19]),
    }


def open_worker_handle(pid: int) -> int:
    """Linux pidfd identifies the original process even if its PID is recycled."""
    return int(getattr(os, "pidfd_open")(pid, 0))


def close_worker_handle(handle: int, *, stop: bool) -> None:
    try:
        if stop:
            try:
                getattr(signal, "pidfd_send_signal")(handle, 9)  # Linux SIGKILL
            except ProcessLookupError:
                pass
    finally:
        os.close(handle)


def linux_lifecycle(probe: Path) -> dict[str, Any]:
    """Kill only the owned launcher and verify its waiting child stops running."""
    worker = 0
    handle: int | None = None
    owned = False
    identity: dict[str, Any] | None = None
    with subprocess.Popen(
        [str(probe), "lifecycle"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        try:
            try:
                process.communicate(timeout=3)
                raise ValueError("peak_memory: lifecycle_early_exit")
            except subprocess.TimeoutExpired as error:
                require(
                    isinstance(error.output, bytes) and len(error.output) <= 1024,
                    "lifecycle_output",
                )
                data = json.loads(error.output)
            require(
                type(data.get("format")) is int
                and data["format"] == 2
                and data.get("lifecycle") is True,
                "lifecycle_header",
            )
            launch = validate_launch(data.get("launch"), "linux_fork")
            require(launch["launcher_pid"] == process.pid, "lifecycle_launcher")
            worker = launch["measurement_pid"]
            handle = open_worker_handle(worker)
            identity = process_state(worker)
            require(
                identity is not None
                and identity["parent_pid"] == process.pid
                and identity["state"] != "Z",
                "lifecycle_worker",
            )
            owned = True
            process.kill()
            process.wait(timeout=5)
            deadline = time.monotonic() + 5
            while True:
                current = process_state(worker)
                if current is None:
                    state = "gone"
                    break
                if (
                    identity is not None
                    and current["start_ticks"] != identity["start_ticks"]
                ):
                    state = "pid_reused_original_gone"
                    break
                if current["state"] == "Z":
                    state = "zombie_waiting_for_reaper"
                    break
                require(time.monotonic() < deadline, "worker_survived_launcher")
                time.sleep(0.02)
            return {
                "passed": True,
                "launch": launch,
                "worker_exit_state": state,
                "worker_running": False,
                "launcher_reaped": True,
            }
        finally:
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            finally:
                if handle is not None:
                    close_worker_handle(handle, stop=owned)


def linux_launch_control(probe: Path, result: dict[str, Any]) -> None:
    """Hold/touch 128 MiB in Python while executing both launch paths."""
    held = bytearray(LAUNCH_PRESSURE)
    try:
        for offset in range(0, len(held), 4096):
            held[offset] = 1
        direct = json.loads(run([str(probe), "cached", "--direct"]))
        isolated = json.loads(run([str(probe), "cached"]))
        result.update(
            held_bytes=len(held), direct=direct, isolated=isolated, accepted=False
        )
        check_launch_control(direct, isolated)
        result["accepted"] = True
    finally:
        del held


def fingerprint(paths: list[Path]) -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def verify_unchanged(
    initial: tuple[str, str], binaries: list[Path], hashes: dict[str, str]
) -> None:
    require(fingerprint(binaries) == hashes, "binaries_changed")
    require(source_state() == initial, "source_changed")


def compile_probe(
    system: str, directory: Path, *, synthetic: bool = False
) -> tuple[Path, str]:
    """Compile the same OS metric implementation against a selected probe library."""
    name = "synthetic-memory-probe" if synthetic else "ffi-memory-probe"
    probe = directory / (name + (".exe" if system == "Windows" else ""))
    if system == "Windows":
        command = [
            "pwsh",
            "-NoProfile",
            "-File",
            "scripts/build_c_example.ps1",
            "-SyntheticMemoryProbe" if synthetic else "-PeakMemoryProbe",
            "-PeakMemoryDirectory",
            str(directory),
        ]
    else:
        command = [
            "cc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-std=c11",
            *(["-DDSCOPE_SYNTHETIC"] if synthetic else []),
            "docs/research/ffi_memory_probe.c",
            f"-L{directory}",
            "-lsynthetic_memory" if synthetic else "-ldaoseeker_scope_ffi",
            f"-Wl,-rpath,{directory}",
            "-o",
            str(probe),
        ]
    output = run(command).decode("utf-8")
    if system == "Windows":
        version = re.search(r"^c_compiler_version=([0-9. ]+)\r?$", output, re.MULTILINE)
        require(version is not None, "c_compiler_version")
        compiler = version[1].strip() if version else ""
    else:
        compiler = run(["cc", "--version"], 10).decode().splitlines()[0][:256]
    return probe, compiler


def measure(report: dict[str, Any]) -> None:
    initial = source_state()
    require(not initial[1], "dirty_checkout")
    system = platform.system()
    require(system in ("Windows", "Linux", "Darwin"), "unsupported_host")
    rustc = run(["rustc", "-vV"], 10).decode().strip()
    host = next(
        (line[6:] for line in rustc.splitlines() if line.startswith("host: ")), ""
    )
    require(re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", host) is not None, "rust_host")
    report.update(
        git_revision=initial[0],
        git_dirty=False,
        system=system,
        os_release=platform.release(),
        machine=platform.machine(),
        profile="release",
        probe_format=2,
        features="default serde; target desktop backend",
        rustc=rustc,
        target=host,
        scope="process lifetime high-water; not allocator bytes or leak proof",
        options={"timeout_ms": 2000, "max_entries": 128, "sensitive": False},
    )
    run(
        [
            "cargo",
            "build",
            "--locked",
            "--release",
            "--target-dir",
            "target/peak-memory-build",
            "--target",
            host,
            "-p",
            "daoseeker-scope-ffi",
            "-p",
            "daoseeker-scope-cli",
        ],
        900,
    )
    release = ROOT / "target/peak-memory-build" / host / "release"
    suffix = ".exe" if system == "Windows" else ""
    library = (
        release
        / {
            "Windows": "daoseeker_scope_ffi.dll",
            "Linux": "libdaoseeker_scope_ffi.so",
            "Darwin": "libdaoseeker_scope_ffi.dylib",
        }[system]
    )
    cli = release / f"dscope{suffix}"
    probe, compiler = compile_probe(system, release)
    report["c_compiler"] = compiler
    report["c_build"] = (
        "MSVC /W4 /WX /O2 /std:c11; release import library; Psapi.lib"
        if system == "Windows"
        else "cc -O2 -Wall -Wextra -Werror -std=c11; release shared library and rpath"
    )
    run(
        [
            "cargo",
            "build",
            "--locked",
            "--release",
            "--target-dir",
            "target/peak-memory-build",
            "--target",
            host,
            "-p",
            "daoseeker-scope",
            "--example",
            "synthetic_memory",
        ],
        900,
    )
    synthetic_directory = release / "examples"
    synthetic, synthetic_compiler = compile_probe(
        system, synthetic_directory, synthetic=True
    )
    require(synthetic_compiler == compiler, "compiler_changed")
    synthetic_library = (
        synthetic_directory
        / {
            "Windows": "synthetic_memory.dll",
            "Linux": "libsynthetic_memory.so",
            "Darwin": "libsynthetic_memory.dylib",
        }[system]
    )
    report["synthetic_scope"] = (
        "two Custom fixture backends; not hardware evidence or production FFI performance"
    )
    binaries = [probe, library, cli, synthetic, synthetic_library]
    hashes = fingerprint(binaries)
    report["binary_sha256"] = hashes
    snapshot = json.loads(run([str(cli), "--json"]))
    schema = json.loads((ROOT / "docs/schema/snapshot-v1.schema.json").read_bytes())
    jsonschema.validate(snapshot, schema)
    check_snapshot(snapshot)
    hardware = snapshot["static_info"]["system"]
    report["hardware"] = {
        "cpu_brand": hardware["cpu"]["brand"],
        "logical_count": hardware["cpu"]["logical_count"],
        "total_usable_bytes": hardware["memory"]["total_usable_bytes"],
    }
    report["snapshot_schema_and_privacy"] = True
    modes: dict[str, Any] = {}
    report["measurements"] = modes
    for mode in ("calibrate", "cached", "fresh"):
        # Separate processes: the 64 MiB calibration must not raise workload peaks.
        data = json.loads(run([str(probe), mode]))
        modes[mode] = {"accepted": False, "observation": data}
        validate(
            data,
            mode,
            system,
            expected_launch="linux_fork" if system == "Linux" else "direct",
        )
        modes[mode]["accepted"] = True
    if system == "Linux":
        report["phase"] = "launch_control"
        report["launch_control"] = {"accepted": False}
        linux_launch_control(probe, report["launch_control"])
        report["phase"] = "lifecycle"
        report["lifecycle"] = linux_lifecycle(probe)
    report["phase"] = "synthetic"
    synthetic_modes: dict[str, Any] = {}
    report["synthetic_measurements"] = synthetic_modes
    for mode in ("calibrate", "synthetic", "over_limit"):
        data = json.loads(run([str(synthetic), mode]))
        synthetic_modes[mode] = {"accepted": False, "observation": data}
        validate(
            data,
            mode,
            system,
            expected_launch="linux_fork" if system == "Linux" else "direct",
        )
        synthetic_modes[mode]["accepted"] = True
    verify_unchanged(initial, binaries, hashes)
    report["source_and_binaries_unchanged"] = True
    report["phase"] = "complete"


def main() -> None:
    output = ROOT / "target/peak-memory-evidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "overall": "incomplete",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    output.write_text(json.dumps(report) + "\n", encoding="utf-8", newline="\n")
    try:
        measure(report)
        report["overall"] = "passed"
    except Exception:
        report["overall"] = "failed"
        raise
    finally:
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )


if __name__ == "__main__":
    main()
