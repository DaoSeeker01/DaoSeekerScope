"""Check finite cached C ABI handle/FD growth with an independent positive control."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
from typing import Any

import peak_memory as peak

ROOT = Path(__file__).resolve().parent.parent
METRICS = {
    "Windows": "process_handle_count",
    "Linux": "proc_self_fd_count",
    "Darwin": "fcntl_fd_count_0_65535",
}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(f"resource_regression: {code}")


def integer(value: Any, maximum: int = 1048576) -> bool:
    return type(value) is int and 0 <= value <= maximum


def analyse(data: Any, mode: str, system: str) -> dict[str, Any]:
    """Validate the fixed protocol without accepting changed plans or hidden spikes."""
    require(isinstance(data, dict), "object")
    require(type(data.get("format")) is int and data["format"] == 1, "format")
    require(
        data.get("mode") == mode and data.get("metric") == METRICS[system],
        "mode_metric",
    )
    if mode == "calibrate":
        require(
            type(data.get("opened_resources")) is int
            and data["opened_resources"] == 32,
            "calibration_plan",
        )
        counts = data.get("counts")
        require(
            isinstance(counts, list)
            and len(counts) == 3
            and all(integer(value) for value in counts),
            "calibration_counts",
        )
        require(
            counts[1] - counts[0] == 32 and counts[2] == counts[0], "calibration_delta"
        )
        return {"opened_delta": 32, "closed_delta": 0, "passed": True}
    require(mode in ("cached", "control"), "workload_mode")
    for field, value in {
        "warmup_calls": 100,
        "total_calls": 1000,
        "interval_calls": 100,
        "tail_budget": 8,
        "control_resources": 16 if mode == "control" else 0,
    }.items():
        require(type(data.get(field)) is int and data[field] == value, "plan_changed")
    require(data.get("completed") is True, "incomplete")
    require(
        integer(data.get("max_json_bytes")) and data["max_json_bytes"] > 0,
        "json_length",
    )
    samples = data.get("samples")
    require(isinstance(samples, list) and len(samples) == 10, "samples")
    values = []
    for index, sample in enumerate(samples, 1):
        require(isinstance(sample, dict), "sample")
        require(
            type(sample.get("calls")) is int and sample["calls"] == index * 100, "calls"
        )
        require(integer(sample.get("count")), "count")
        values.append(sample["count"])
    span = max(values) - min(values)
    return {
        "tail_samples": 10,
        "first_count": values[0],
        "last_count": values[-1],
        "net_change": values[-1] - values[0],
        "tail_range": span,
        "budget": 8,
        "within_budget": span <= 8,
    }


def compile_probe(system: str, folder: Path) -> tuple[Path, str]:
    probe = folder / (
        "ffi-resource-probe.exe" if system == "Windows" else "ffi-resource-probe"
    )
    if system == "Windows":
        output = peak.run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                "scripts/build_c_example.ps1",
                "-ResourceProbe",
                "-PeakMemoryDirectory",
                str(folder),
            ]
        ).decode()
        version = re.search(r"^c_compiler_version=([0-9. ]+)\r?$", output, re.MULTILINE)
        require(version is not None, "c_compiler_version")
        compiler = version[1].strip() if version else ""
    else:
        peak.run(
            [
                "cc",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-std=c11",
                "docs/research/ffi_resource_probe.c",
                f"-L{folder}",
                "-ldaoseeker_scope_ffi",
                f"-Wl,-rpath,{folder}",
                "-o",
                str(probe),
            ]
        )
        compiler = peak.run(["cc", "--version"], 10).decode().splitlines()[0][:256]
    return probe, compiler


def measure(report: dict[str, Any]) -> None:
    initial = peak.source_state()
    require(not initial[1], "dirty_checkout")
    system = platform.system()
    require(system in METRICS, "platform")
    rustc = peak.run(["rustc", "-vV"], 10).decode().strip()
    host = next(line[6:] for line in rustc.splitlines() if line.startswith("host: "))
    require(
        host
        == {
            "Windows": "x86_64-pc-windows-msvc",
            "Linux": "x86_64-unknown-linux-gnu",
            "Darwin": "aarch64-apple-darwin",
        }[system],
        "native_target",
    )
    # Share the identical release build with the preceding timed trial in CI.
    build = ROOT / "target/timed-soak-build"
    peak.run(
        [
            "cargo",
            "build",
            "--locked",
            "--offline",
            "--release",
            "--target",
            host,
            "--target-dir",
            str(build),
            "-p",
            "daoseeker-scope-ffi",
        ],
        900,
    )
    folder = build / host / "release"
    probe, compiler = compile_probe(system, folder)
    library = (
        folder
        / {
            "Windows": "daoseeker_scope_ffi.dll",
            "Linux": "libdaoseeker_scope_ffi.so",
            "Darwin": "libdaoseeker_scope_ffi.dylib",
        }[system]
    )
    binaries = [probe, library]
    hashes = peak.fingerprint(binaries)
    report.update(
        source_before={"revision": initial[0], "status": initial[1]},
        system=system,
        os_release=platform.release(),
        target=host,
        rustc=rustc,
        c_compiler=compiler,
        profile="release; default serde",
        binary_sha256=hashes,
        options={
            "default_cached_collector": True,
            "sensitive": False,
            "timeout_ms": 2000,
        },
        scope="finite process handle/FD sampling; macOS checks only FD 0..65535; not Mach ports, GDI/USER objects, allocator or long-duration proof",
        observations={},
        analyses={},
    )
    for mode in ("calibrate", "cached", "control"):
        data = json.loads(peak.run([str(probe), mode], 210))
        report["observations"][mode] = data
        result = analyse(data, mode, system)
        report["analyses"][mode] = result
        require(
            result.get("passed", result.get("within_budget")) is (mode != "control"),
            "calibration_or_budget_or_control",
        )
    peak.verify_unchanged(initial, binaries, hashes)
    report["source_after"] = {"revision": initial[0], "status": initial[1]}
    report["checked_at"] = datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/resource-evidence.json"
    )
    options = parser.parse_args()
    report: dict[str, Any] = {"format": 1, "overall": "incomplete"}
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_bytes((json.dumps(report) + "\n").encode())
    try:
        measure(report)
        report["overall"] = "passed"
    except Exception:
        report["overall"] = "failed"
        raise
    finally:
        options.output.write_bytes(
            (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
        )


if __name__ == "__main__":
    main()
