"""Container policy and report fixtures; none claim native Docker execution."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import linux_runtime_container_probe as probe
import linux_runtime_container_smoke as smoke
from cli_bundle import digest
from native_smoke import ValidationFailure


def docker_config() -> dict:
    return {
        "Config": {"User": "65534:65534"},
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "NetworkMode": "none",
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges=true"],
            "Memory": 256 * 1024 * 1024,
            "MemorySwap": 256 * 1024 * 1024,
            "PidsLimit": 32,
            "NanoCpus": 1_000_000_000,
            "Ulimits": [{"Name": "nofile", "Soft": 64, "Hard": 64}],
            "Tmpfs": {
                "/work": "rw,exec,nosuid,nodev,size=64m,uid=65534,gid=65534,mode=0700"
            },
        },
        "Mounts": [{"Type": "bind", "Destination": "/input", "RW": False}],
    }


def snapshot() -> dict:
    value = json.loads((smoke.ROOT / "tests/fixtures/snapshot-v1.json").read_bytes())
    system = value["static_info"]["system"]
    for node, field, data in (
        (system["os"], "name", "Fixture OS"),
        (system["cpu"], "brand", "Fixture CPU"),
        (system["cpu"], "logical_count", 2),
        (system["memory"], "total_usable_bytes", 1024),
    ):
        node[field] = {
            "value": data,
            "availability": "available",
            "source": "custom",
            "observed_at": 1,
            "reason": None,
        }
    system["device"]["serial_number"] = {
        "value": None,
        "availability": "restricted",
        "source": "custom",
        "observed_at": None,
        "reason": "privacy_redacted",
    }
    return value


HASHES = {"cli": "a" * 64, "library": "b" * 64, "consumer": "c" * 64}


def result(label: str) -> dict[str, Any]:
    profile = smoke.PROFILES[label]
    value: dict[str, Any] = {
        "overall": "passed",
        "expected": profile["expected"],
        "rebuilt_in_container": False,
        "runtime": {key: profile[key] for key in ("glibc", "debian", "python")},
        "binary_sha256": dict(HASHES),
        "installed_payload_files": {"cli": 3, "sdk": 4},
        "calls": {},
        "installation_storage": {
            "capacity_bytes": smoke.WORK_BYTES,
            "reserve_bytes": smoke.WORK_RESERVE,
            "available_before_copy_bytes": smoke.WORK_BYTES,
            "available_after_copy_bytes": 24 * 1024 * 1024,
        },
    }
    value["runtime"].update(
        machine="x86_64",
        uid=65534,
        kernel="fixture",
        cargo_available=False,
        rustc_available=False,
    )
    if label == "bookworm":
        outputs = {
            "cli_version": "dscope 0.1.0\n",
            "cli_json": json.dumps(snapshot()),
            "c": json.dumps(snapshot()),
            "python": "ctypes: 100 real collect/free cycles, stale copy rejection, privacy and schema passed\n",
        }
        value["calls"] = {
            key: {
                "exit_code": 0,
                "stderr_bytes": 0,
                "stdout": output,
                "missing_glibc_versions": [],
            }
            for key, output in outputs.items()
        }
    else:
        value["calls"] = {
            key: {
                "exit_code": 1,
                "stderr_bytes": 32,
                "stdout": "",
                "missing_glibc_versions": ["GLIBC_2.34"],
            }
            for key in ("cli", "c")
        }
        value["calls"]["ctypes_load"] = {
            "rejected": True,
            "missing_glibc_versions": ["GLIBC_2.34"],
        }
        value["collection_started"] = False
    return value


class RuntimeContainerTests(unittest.TestCase):
    def test_install_budget_accounts_for_two_complete_notice_trees(self) -> None:
        # Reproduce the >32 MiB logical size without creating large fixture files.
        budget = smoke.installation_budget(
            [17 * 1024 * 1024, 17 * 1024 * 1024, 17000], 20
        )
        self.assertGreater(budget["logical_bytes"], 32 * 1024 * 1024)
        self.assertLessEqual(
            budget["estimated_copy_bytes"] + budget["reserve_bytes"], smoke.WORK_BYTES
        )
        self.assertGreater(budget["estimated_copy_bytes"], budget["logical_bytes"])
        for sizes, directories in (([48 * 1024 * 1024], 1), ([49 * 1024 * 1024], 0)):
            with self.assertRaisesRegex(ValueError, "runtime_install_capacity"):
                smoke.installation_budget(sizes, directories)
        for sizes, directories, block in (
            ([-1], 0, 4096),
            ([1], -1, 4096),
            ([1], 0, 0),
            ([1], 0, 4095),
        ):
            with self.assertRaisesRegex(ValueError, "runtime_install_sizes"):
                smoke.installation_budget(sizes, directories, block)
        with self.assertRaisesRegex(ValueError, "runtime_install_sizes"):
            smoke.installation_budget([True], 0)

    def test_actual_work_space_is_checked_before_and_after_copy(self) -> None:
        budget = smoke.installation_budget([34 * 1024 * 1024], 0)
        usage = SimpleNamespace(f_blocks=16384, f_frsize=4096, f_bavail=16384)
        with patch.object(probe.os, "statvfs", return_value=usage, create=True):
            self.assertEqual(
                probe.work_space(
                    Path("unused"), budget, budget["estimated_copy_bytes"]
                )["capacity_bytes"],
                smoke.WORK_BYTES,
            )
            usage.f_bavail = 4095
            with self.assertRaisesRegex(ValueError, "runtime_work_space"):
                probe.work_space(Path("unused"), budget, 0)
            usage.f_bavail = 12000
            with self.assertRaisesRegex(ValueError, "runtime_work_space"):
                probe.work_space(Path("unused"), budget, budget["estimated_copy_bytes"])
            usage.f_blocks = 32768
            with self.assertRaisesRegex(ValueError, "runtime_work_space"):
                probe.work_space(Path("unused"), budget, 0)

    def test_report_rejects_missing_workspace_reserve(self) -> None:
        for label in ("bookworm", "bullseye"):
            value = result(label)
            value["installation_storage"]["available_after_copy_bytes"] = (
                smoke.WORK_RESERVE - 1
            )
            with self.assertRaisesRegex(ValueError, "runtime_install_storage"):
                smoke.validate_result(value, smoke.PROFILES[label], HASHES, "0.1.0")

    def test_images_are_fixed_amd64_content_digests(self) -> None:
        for profile in smoke.PROFILES.values():
            self.assertRegex(profile["image"], r"^python@sha256:[0-9a-f]{64}$")
            self.assertRegex(profile["config_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(smoke.PROFILES["bookworm"]["expected"], "runs")
        self.assertEqual(smoke.PROFILES["bullseye"]["expected"], "loader_rejects")

    def test_container_arguments_are_bounded_and_do_not_build_candidates(self) -> None:
        arguments = smoke.container_arguments(
            "fixture", Path("/fixture"), smoke.PROFILES["bookworm"], "bookworm"
        )
        self.assertIn("none", arguments)
        self.assertIn("LC_ALL=C", arguments)
        self.assertIn("256m", arguments)
        self.assertIn(
            f"type=bind,source={Path('/fixture')},target=/input,readonly", arguments
        )
        self.assertEqual(
            arguments[-4:], ["python", "-B", "/input/probe.py", "/input/bookworm.json"]
        )
        with self.assertRaisesRegex(ValueError, "unsupported_bind_path"):
            smoke.container_arguments(
                "fixture", Path("/bad,option"), smoke.PROFILES["bookworm"], "bookworm"
            )

    def test_daemon_configuration_is_verified(self) -> None:
        self.assertEqual(smoke.validate_config(docker_config())["network"], "none")
        for key, bad in (
            ("Privileged", True),
            ("ReadonlyRootfs", False),
            ("Memory", 0),
            ("MemorySwap", -1),
            ("NetworkMode", "host"),
            ("PidsLimit", 0),
            ("NanoCpus", 0),
            ("CapDrop", []),
            ("SecurityOpt", []),
        ):
            value = docker_config()
            value["HostConfig"][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                smoke.validate_config(value)
        for field, bad in (("RW", True), ("Destination", "/etc")):
            value = docker_config()
            value["Mounts"][0][field] = bad
            with self.assertRaisesRegex(ValueError, "runtime_container_mounts"):
                smoke.validate_config(value)
        value = docker_config()
        value["HostConfig"]["Tmpfs"]["/work"] = "rw,size=1g"
        with self.assertRaisesRegex(ValueError, "runtime_container_tmpfs"):
            smoke.validate_config(value)

    def test_positive_report_is_validated_and_raw_snapshots_removed(self) -> None:
        report = smoke.validate_result(
            result("bookworm"), smoke.PROFILES["bookworm"], HASHES, "0.1.0"
        )
        self.assertTrue(report["snapshot_schema_and_default_privacy"])
        self.assertEqual(report["python_collect_free_cycles"], 100)
        self.assertNotIn("Fixture CPU", json.dumps(report))
        self.assertNotIn("stdout", json.dumps(report))

    def test_positive_report_rejects_wrong_identity_hash_version_or_child_exit(
        self,
    ) -> None:
        for mutate in (
            lambda v: v["runtime"].update(glibc="9.0"),
            lambda v: v["binary_sha256"].update(cli="0" * 64),
            lambda v: v["calls"]["c"].update(exit_code=1),
            lambda v: v["calls"]["cli_version"].update(stdout="dscope old"),
            lambda v: v.update(rebuilt_in_container=True),
        ):
            value = result("bookworm")
            mutate(value)
            with self.assertRaises(ValueError):
                smoke.validate_result(
                    value, smoke.PROFILES["bookworm"], HASHES, "0.1.0"
                )

    def test_positive_report_rejects_schema_and_privacy_failure(self) -> None:
        for label in ("cli_json", "c"):
            value = result("bookworm")
            payload = json.loads(value["calls"][label]["stdout"])
            payload["static_info"]["system"]["device"]["serial_number"]["value"] = (
                "private"
            )
            value["calls"][label]["stdout"] = json.dumps(payload)
            with self.assertRaises((jsonschema.ValidationError, ValidationFailure)):
                smoke.validate_result(
                    value, smoke.PROFILES["bookworm"], HASHES, "0.1.0"
                )

    def test_negative_result_proves_loader_rejection_not_collection(self) -> None:
        report = smoke.validate_result(
            result("bullseye"), smoke.PROFILES["bullseye"], HASHES, "0.1.0"
        )
        self.assertFalse(report["collection_started"])
        self.assertEqual(
            report["missing_glibc_versions"]["ctypes_load"], ["GLIBC_2.34"]
        )
        self.assertNotIn("python_collect_free_cycles", report)

    def test_unrelated_failure_or_crash_is_not_expected_rejection(self) -> None:
        for mutate in (
            lambda v: v["calls"]["cli"].update(exit_code=0),
            lambda v: v["calls"]["c"].update(exit_code=-11),
            lambda v: v["calls"]["c"].update(missing_glibc_versions=[]),
            lambda v: v["calls"]["ctypes_load"].update(rejected=False),
            lambda v: v["calls"]["cli"].update(missing_glibc_versions=["GLIBC_2.2.5"]),
            lambda v: v["calls"]["cli"].update(missing_glibc_versions=["unrelated"]),
            lambda v: v.update(collection_started=True),
        ):
            value = result("bullseye")
            mutate(value)
            with self.assertRaises(ValueError):
                smoke.validate_result(
                    value, smoke.PROFILES["bullseye"], HASHES, "0.1.0"
                )

    def test_loader_diagnostic_parser_ignores_unrelated_messages(self) -> None:
        diagnostic = (
            b"libc.so.6: version `GLIBC_2.34' not found (required by hidden-path)"
        )
        self.assertEqual(probe.missing_glibc_versions(diagnostic), ["GLIBC_2.34"])
        for data in (
            b"GLIBC_2.34",
            b"permission denied",
            b"segmentation fault",
            b"collection error: Timeout",
        ):
            self.assertEqual(probe.missing_glibc_versions(data), [])
        with patch("linux_runtime_container_probe.MAX_OUTPUT", 2):
            with self.assertRaisesRegex(ValueError, "diagnostic_limit"):
                probe.missing_glibc_versions(diagnostic)

    def test_loader_versions_use_only_the_known_packaged_dependency_closure(
        self,
    ) -> None:
        requirements = {
            "cli": {"required_symbol_versions": {"libc.so.6": ["GLIBC_2.34"]}},
            "consumer": {"required_symbol_versions": {"libc.so.6": ["GLIBC_2.34"]}},
            "library": {
                "required_symbol_versions": {
                    "libc.so.6": ["GLIBC_2.32", "GLIBC_2.33", "GLIBC_2.34"]
                }
            },
        }
        calls = result("bullseye")["calls"]
        calls["c"]["missing_glibc_versions"] = [
            "GLIBC_2.32",
            "GLIBC_2.33",
            "GLIBC_2.34",
        ]
        smoke.validate_loader_requirements(calls, requirements)
        calls["cli"]["missing_glibc_versions"] = ["GLIBC_2.32"]
        with self.assertRaisesRegex(ValueError, "runtime_unexpected_loader_version"):
            smoke.validate_loader_requirements(calls, requirements)
        calls["cli"]["missing_glibc_versions"] = ["GLIBC_2.34"]
        calls["c"]["missing_glibc_versions"] = ["GLIBC_2.40"]
        with self.assertRaisesRegex(ValueError, "runtime_unexpected_loader_version"):
            smoke.validate_loader_requirements(calls, requirements)

    def test_candidate_copy_checks_manifest_and_every_payload(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            path = source / "payload"
            path.write_bytes(b"fixture")
            manifest = {
                "files": {
                    "payload": {
                        "size": 7,
                        "sha256": digest(b"fixture"),
                        "mode": stat.S_IMODE(path.stat().st_mode),
                    }
                }
            }
            data = json.dumps(manifest).encode()
            (source / "manifest.json").write_bytes(data)
            self.assertEqual(
                probe.install_candidate(source, root / "copy", digest(data)), 1
            )
            with self.assertRaisesRegex(ValueError, "manifest_changed"):
                probe.install_candidate(source, root / "wrong", "0" * 64)
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "installed_payload_changed"):
                probe.install_candidate(source, root / "tampered", digest(data))

    def test_wrong_host_and_remote_docker_fail_before_pull_or_execution(self) -> None:
        with (
            patch(
                "linux_runtime_container_smoke.require_runtime_host",
                side_effect=ValueError("unsupported_host"),
            ),
            patch("linux_runtime_container_smoke.run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "unsupported_host"):
                smoke.execute(Path("unused"), Path("unused"), {})
            run.assert_not_called()
        with (
            patch("linux_runtime_container_smoke.require_runtime_host"),
            patch(
                "linux_runtime_container_smoke.run",
                side_effect=[b"a" * 40, b"", b"ssh://remote"],
            ) as run,
        ):
            with self.assertRaisesRegex(ValueError, "local_docker_required"):
                smoke.execute(Path("unused"), Path("unused"), {})
            self.assertEqual(run.call_count, 3)

    def test_failed_or_interrupted_run_does_not_leave_old_pass(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "report.json"
            for failure in (ValueError("fixture_failure"), KeyboardInterrupt()):
                output.write_text('{"overall":"passed"}')
                with (
                    patch.object(
                        sys,
                        "argv",
                        [
                            "runtime",
                            "unused-cli",
                            "unused-sdk",
                            "--output",
                            str(output),
                        ],
                    ),
                    patch("linux_runtime_container_smoke.execute", side_effect=failure),
                    redirect_stderr(io.StringIO()),
                ):
                    with self.assertRaises((SystemExit, KeyboardInterrupt)):
                        smoke.main()
                report = json.loads(output.read_bytes())
                self.assertEqual(
                    report["overall"],
                    "incomplete"
                    if isinstance(failure, KeyboardInterrupt)
                    else "failed",
                )

    def test_container_is_removed_after_timeout(self) -> None:
        profile = smoke.PROFILES["bookworm"]
        calls: list[list[str]] = []

        def invoke(arguments: list[str], **kwargs: Any) -> bytes:
            calls.append(arguments)
            if arguments[:3] == ["docker", "image", "inspect"]:
                return json.dumps(
                    [
                        {
                            "Id": profile["config_digest"],
                            "Architecture": "amd64",
                            "Os": "linux",
                        }
                    ]
                ).encode()
            if arguments[:2] == ["docker", "inspect"]:
                return json.dumps([docker_config()]).encode()
            if arguments[:2] == ["docker", "start"]:
                raise subprocess.TimeoutExpired("not-executed", 300)
            return b""

        item: dict[str, Any] = {"status": "running"}
        with patch("linux_runtime_container_smoke.run", side_effect=invoke):
            with self.assertRaises(subprocess.TimeoutExpired):
                smoke.run_profile(
                    Path("fixture"), "bookworm", HASHES, "0.1.0", {}, item
                )
        self.assertEqual(calls[-1][:3], ["docker", "rm", "--force"])
        self.assertEqual(calls[-1][-1], calls[2][3])
        self.assertTrue(item["container_removed"])
        self.assertEqual(item["status"], "failed")

    def test_cleanup_failure_is_not_accepted(self) -> None:
        profile = smoke.PROFILES["bookworm"]

        def invoke(arguments: list[str], **kwargs: Any) -> bytes:
            if arguments[:3] == ["docker", "image", "inspect"]:
                return json.dumps(
                    [
                        {
                            "Id": profile["config_digest"],
                            "Architecture": "amd64",
                            "Os": "linux",
                        }
                    ]
                ).encode()
            if arguments[:2] == ["docker", "inspect"]:
                return json.dumps([docker_config()]).encode()
            if arguments[:2] in (["docker", "start"], ["docker", "rm"]):
                raise ValueError("fixture_failure")
            return b""

        item: dict[str, Any] = {"status": "running"}
        with patch("linux_runtime_container_smoke.run", side_effect=invoke):
            with self.assertRaisesRegex(ValueError, "runtime_cleanup_failed"):
                smoke.run_profile(
                    Path("fixture"), "bookworm", HASHES, "0.1.0", {}, item
                )
        self.assertFalse(item["container_removed"])
        self.assertEqual(item["status"], "failed")

    def test_inner_probe_failure_never_prints_private_errors(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            config.write_text("{}")
            for error in (
                ValueError("runtime_glibc"),
                OSError("private/path"),
                ValueError("private/path"),
            ):
                output = io.StringIO()
                with (
                    patch.object(sys, "argv", ["probe", str(config)]),
                    patch("linux_runtime_container_probe.execute", side_effect=error),
                    redirect_stdout(output),
                ):
                    probe.main()
                report = json.loads(output.getvalue())
                self.assertEqual(report["overall"], "failed")
                self.assertNotIn("private", output.getvalue())


if __name__ == "__main__":
    unittest.main()
