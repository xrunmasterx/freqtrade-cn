from __future__ import annotations

import dataclasses
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.runtime_supervisor.offline_identity import (
    EmergencyRuntimeState,
    OfflineEmergencyAmbiguousOutcome,
    OfflineEmergencyController,
    OfflineEmergencyPolicyError,
    OfflineEmergencyTransportError,
    OfflineIdentityMismatch,
    OfflineIdentityStore,
    OfflineIdentityStorageError,
    OfflineIdentityValidationError,
    OfflineRuntimeIdentity,
)


CONTAINER_ID = "1" * 64
IMAGE_ID = "sha256:" + "2" * 64
IMAGE_LABEL_PREFIX = "org.freqtrade-cn.revision."


def secure_windows_directory(path: Path) -> None:
    if os.name != "nt":
        return
    username = os.environ.get("USERNAME")
    if not username:
        raise AssertionError("USERNAME is required for the Windows ACL test fixture")
    completed = subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{username}:(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError("failed to create the fixed Windows ACL test fixture")


def identity(**changes: object) -> OfflineRuntimeIdentity:
    values: dict[str, object] = {
        "schema_version": 1,
        "instance_revision": 1,
        "lease_generation": 1,
        "instance_id": "paper-instance",
        "attempt_id": "paper-attempt-1",
        "container_id": CONTAINER_ID,
        "project_name": "runtime-paper",
        "container_name": "runtime-paper-attempt-1",
        "compose_service": "runtime",
        "image_id": IMAGE_ID,
        "runtime_spec_digest": "3" * 64,
        "launch_authority_digest": "4" * 64,
        "state_allocation_id": "paper-state",
        "network_names": ("runtime-access", "runtime-private"),
        "root_commit": "a" * 40,
        "backend_commit": "b" * 40,
        "frontend_commit": "c" * 40,
        "strategies_commit": "d" * 40,
    }
    values.update(changes)
    return OfflineRuntimeIdentity(**values)


def container_document(
    expected: OfflineRuntimeIdentity,
    *,
    state: str = "running",
    networks: tuple[str, ...] | None = None,
    label_changes: dict[str, str] | None = None,
) -> dict:
    labels = {
        "com.docker.compose.project": expected.project_name,
        "com.docker.compose.service": expected.compose_service,
        "io.freqtrade.runtime.attempt-id": expected.attempt_id,
        "io.freqtrade.runtime.container-name": expected.container_name,
        "io.freqtrade.runtime.image-id": expected.image_id,
        "io.freqtrade.runtime.instance-id": expected.instance_id,
        "io.freqtrade.runtime.launch-authority-digest": (
            expected.launch_authority_digest
        ),
        "io.freqtrade.runtime.project-name": expected.project_name,
        "io.freqtrade.runtime.runtime-spec-digest": expected.runtime_spec_digest,
        "io.freqtrade.runtime.state-allocation-id": expected.state_allocation_id,
    }
    labels.update(label_changes or {})
    observed_networks = expected.network_names if networks is None else networks
    return {
        "Id": expected.container_id,
        "Name": f"/{expected.container_name}",
        "Image": expected.image_id,
        "Config": {"Labels": labels, "Env": ["PRIVATE=must-not-escape"]},
        "Mounts": [{"Source": "C:/private/host/path"}],
        "State": {
            "Status": state,
            "ExitCode": 0,
            "Health": {"Status": "healthy"},
        },
        "NetworkSettings": {
            "Networks": {name: {} for name in observed_networks},
        },
    }


def image_document(expected: OfflineRuntimeIdentity) -> dict:
    return {
        "Id": expected.image_id,
        "Config": {
            "Labels": {
                f"{IMAGE_LABEL_PREFIX}root": expected.root_commit,
                f"{IMAGE_LABEL_PREFIX}backend": expected.backend_commit,
                f"{IMAGE_LABEL_PREFIX}frontend": expected.frontend_commit,
            }
        },
    }


class FakeDocker:
    def __init__(self, expected: OfflineRuntimeIdentity) -> None:
        self.expected = expected
        self.container = container_document(expected)
        self.image = image_document(expected)
        self.commands: list[tuple[str, ...]] = []
        self.kwargs: list[dict] = []
        self.stop_returncode = 0

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        frozen = tuple(command)
        self.commands.append(frozen)
        self.kwargs.append(dict(kwargs))
        if frozen[1:3] == ("container", "inspect"):
            return subprocess.CompletedProcess(command, 0, json.dumps([self.container]), "")
        if frozen[1:3] == ("image", "inspect"):
            return subprocess.CompletedProcess(command, 0, json.dumps([self.image]), "")
        if frozen[1:3] == ("container", "logs"):
            return subprocess.CompletedProcess(command, 0, "line-one\nline-two\n", "")
        if frozen[1:3] == ("container", "stop"):
            if self.stop_returncode == 0:
                networks = tuple(self.container["NetworkSettings"]["Networks"])
                self.container = container_document(
                    self.expected,
                    state="exited",
                    networks=networks,
                )
            return subprocess.CompletedProcess(command, self.stop_returncode, "", "private")
        raise AssertionError(f"unexpected command: {frozen!r}")


class FakeLogProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self.killed = False
        self.wait_calls = 0

    def wait(self, timeout: int | None = None) -> int:
        self.wait_calls += 1
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakeLogSpawner:
    def __init__(self, process: FakeLogProcess) -> None:
        self.process = process
        self.commands: list[tuple[str, ...]] = []
        self.kwargs: list[dict] = []

    def __call__(self, command: list[str], **kwargs: object) -> FakeLogProcess:
        self.commands.append(tuple(command))
        self.kwargs.append(dict(kwargs))
        return self.process


class OfflineIdentityValueTests(unittest.TestCase):
    def test_identity_accepts_sha1_and_sha256_git_object_ids(self) -> None:
        for length in (40, 64):
            with self.subTest(length=length):
                value = identity(
                    root_commit="a" * length,
                    backend_commit="b" * length,
                    frontend_commit="c" * length,
                    strategies_commit="d" * length,
                )
                self.assertEqual(len(value.root_commit), length)

    def test_identity_is_frozen_strict_and_canonical(self) -> None:
        value = identity()
        canonical = value.to_canonical_bytes()

        self.assertEqual(OfflineRuntimeIdentity.from_canonical_bytes(canonical), value)
        self.assertEqual(canonical[-1:], b"\n")
        self.assertNotIn(b"secret", canonical.lower())
        self.assertNotIn(b"path", canonical.lower())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.instance_id = "other"

        document = json.loads(canonical)
        document["secret_path"] = "C:/private"
        with self.assertRaisesRegex(
            OfflineIdentityValidationError,
            "^offline_identity_validation_error$",
        ):
            OfflineRuntimeIdentity.from_canonical_bytes(
                json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
                + b"\n"
            )

    def test_parser_rejects_noncanonical_duplicate_and_invalid_values(self) -> None:
        canonical = identity().to_canonical_bytes()
        noncanonical = json.dumps(json.loads(canonical), indent=2).encode() + b"\n"
        duplicate = canonical.replace(
            b'{"attempt_id":',
            b'{"attempt_id":"paper-attempt-1","attempt_id":',
            1,
        )

        for payload in (noncanonical, duplicate, b"{}\n", b"[]\n", b"\xff"):
            with self.subTest(payload=payload[:20]):
                with self.assertRaises(OfflineIdentityValidationError):
                    OfflineRuntimeIdentity.from_canonical_bytes(payload)

        for changes in (
            {"instance_revision": -1},
            {"instance_revision": True},
            {"lease_generation": 0},
            {"lease_generation": True},
            {"attempt_id": "current"},
            {"container_id": "short"},
            {"image_id": "repo:latest"},
            {"network_names": ("z", "a")},
            {"network_names": ("same", "same")},
            {"root_commit": "A" * 40},
            {"root_commit": "a" * 41},
            {"root_commit": "a" * 63},
            {"compose_service": "other"},
            {"schema_version": True},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(OfflineIdentityValidationError):
                    identity(**changes)

    def test_import_under_python_s_performs_no_io(self) -> None:
        script = r"""
import builtins
import pathlib
import socket
import subprocess

def forbidden(*args, **kwargs):
    raise AssertionError("import-time I/O")

builtins.open = forbidden
pathlib.Path.open = forbidden
pathlib.Path.read_bytes = forbidden
pathlib.Path.read_text = forbidden
pathlib.Path.write_bytes = forbidden
pathlib.Path.write_text = forbidden
socket.socket = forbidden
subprocess.Popen = forbidden
subprocess.run = forbidden

import tools.runtime_supervisor.offline_identity
print("import_ok")
"""
        completed = subprocess.run(
            [sys.executable, "-S", "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "import_ok\n")


class OfflineIdentityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / "offline-identities"
        self.root.mkdir(mode=0o700 if os.name == "posix" else 0o777)
        secure_windows_directory(self.root)
        if os.name == "posix":
            self.root.chmod(0o700)
        self.store = OfflineIdentityStore(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_publish_writes_immutable_attempt_and_atomic_current_projection(self) -> None:
        first = identity()
        second = identity(
            instance_revision=2,
            attempt_id="paper-attempt-2",
            container_id="5" * 64,
            container_name="runtime-paper-attempt-2",
        )

        self.assertEqual(self.store.publish(first), first)
        self.assertEqual(self.store.publish(first), first)
        self.assertEqual(self.store.load_attempt(first.instance_id, first.attempt_id), first)
        self.assertEqual(self.store.load_current(first.instance_id), first)

        self.store.publish(second)
        self.assertEqual(self.store.load_current(first.instance_id), second)
        self.assertEqual(self.store.load_attempt(first.instance_id, first.attempt_id), first)
        self.assertEqual(self.store.load_attempt(second.instance_id, second.attempt_id), second)
        instance_root = self.root / first.instance_id
        self.assertEqual(
            {path.name for path in instance_root.iterdir()},
            {".publish.lock", "attempts", "current.json"},
        )
        self.assertEqual(
            {path.name for path in (instance_root / "attempts").iterdir()},
            {"paper-attempt-1.json", "paper-attempt-2.json"},
        )

    def test_current_projection_is_monotonic_and_same_version_is_idempotent(self) -> None:
        current = identity(instance_revision=2, attempt_id="paper-attempt-2")
        stale = identity(instance_revision=1, attempt_id="paper-attempt-1")
        same_version_conflict = identity(
            instance_revision=2,
            attempt_id="paper-attempt-conflict",
            container_id="5" * 64,
            container_name="runtime-paper-conflict",
        )

        self.assertEqual(self.store.publish(current), current)
        self.assertEqual(self.store.publish(current), current)
        for rejected in (stale, same_version_conflict):
            with self.subTest(rejected=rejected.attempt_id):
                with self.assertRaises(OfflineIdentityStorageError):
                    self.store.publish(rejected)

        self.assertEqual(self.store.load_current(current.instance_id), current)
        attempts = self.root / current.instance_id / "attempts"
        self.assertEqual(
            {path.name for path in attempts.iterdir()},
            {"paper-attempt-2.json"},
        )

    def test_cross_process_publish_lock_preserves_the_highest_revision(self) -> None:
        script = r"""
import sys
from pathlib import Path

from tests.test_runtime_offline_identity import identity
from tools.runtime_supervisor.offline_identity import (
    OfflineIdentityStorageError,
    OfflineIdentityStore,
)

root = Path(sys.argv[1])
revision = int(sys.argv[2])
sys.stdin.buffer.read(1)
value = identity(
    instance_revision=revision,
    attempt_id=f"paper-attempt-{revision}",
    container_id=str(revision + 1) * 64,
    container_name=f"runtime-paper-attempt-{revision}",
)
try:
    OfflineIdentityStore(root).publish(value)
except OfflineIdentityStorageError:
    pass
"""
        processes = [
            subprocess.Popen(
                [sys.executable, "-S", "-c", script, str(self.root), str(revision)],
                cwd=Path(__file__).resolve().parents[1],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for revision in (1, 2)
        ]
        for process in processes:
            self.assertIsNotNone(process.stdin)
            process.stdin.write(b"x")
            process.stdin.close()
        for process in processes:
            return_code = process.wait(timeout=10)
            stderr = process.stderr.read().decode("utf-8", errors="replace")
            process.stderr.close()
            process.stdout.close()
            self.assertEqual(return_code, 0, stderr)

        self.assertEqual(
            self.store.load_current("paper-instance").instance_revision,
            2,
        )

    def test_conflicting_attempt_is_never_overwritten(self) -> None:
        first = identity()
        self.store.publish(first)
        conflicting = dataclasses.replace(first, strategies_commit="e" * 40)

        with self.assertRaisesRegex(
            OfflineIdentityStorageError,
            "^offline_identity_storage_error$",
        ):
            self.store.publish(conflicting)

        self.assertEqual(self.store.load_attempt(first.instance_id, first.attempt_id), first)
        self.assertEqual(self.store.load_current(first.instance_id), first)

    def test_fsync_failure_publishes_no_attempt_or_current(self) -> None:
        with mock.patch(
            "tools.runtime_supervisor.offline_identity.os.fsync",
            side_effect=OSError,
        ):
            with self.assertRaises(OfflineIdentityStorageError):
                self.store.publish(identity())

        instance_root = self.root / "paper-instance"
        self.assertFalse((instance_root / "paper-attempt-1.json").exists())
        self.assertFalse((instance_root / "current.json").exists())

    def test_current_replace_failure_keeps_attempt_but_no_partial_projection(self) -> None:
        with mock.patch(
            "tools.runtime_supervisor.offline_identity.os.replace",
            side_effect=OSError,
        ):
            with self.assertRaises(OfflineIdentityStorageError):
                self.store.publish(identity())

        self.assertEqual(
            self.store.load_attempt("paper-instance", "paper-attempt-1"),
            identity(),
        )
        self.assertFalse((self.root / "paper-instance" / "current.json").exists())

    def test_attempt_namespace_cannot_alias_current_projection(self) -> None:
        with self.assertRaises(OfflineIdentityValidationError):
            identity(attempt_id="current")

    @unittest.skipUnless(os.name == "nt", "Windows DACL contract")
    def test_named_untrusted_writer_acl_fails_closed(self) -> None:
        completed = subprocess.run(
            [
                "icacls",
                str(self.root),
                "/grant",
                "*S-1-5-19:(OI)(CI)M",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        with self.assertRaises(OfflineIdentityStorageError):
            self.store.publish(identity())

    @unittest.skipUnless(os.name == "posix", "POSIX mode contract")
    def test_world_writable_root_fails_closed(self) -> None:
        self.root.chmod(0o777)
        with self.assertRaises(OfflineIdentityStorageError):
            self.store.publish(identity())

    def test_symlink_root_fails_closed_when_supported(self) -> None:
        target = Path(self.temporary.name).resolve() / "target"
        target.mkdir()
        link = Path(self.temporary.name).resolve() / "offline-link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")

        with self.assertRaises(OfflineIdentityStorageError):
            OfflineIdentityStore(link).publish(identity())


class OfflineEmergencyControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / "offline-identities"
        self.root.mkdir(mode=0o700 if os.name == "posix" else 0o777)
        secure_windows_directory(self.root)
        if os.name == "posix":
            self.root.chmod(0o700)
        self.expected = identity()
        self.store = OfflineIdentityStore(self.root)
        self.store.publish(self.expected)
        self.runner = FakeDocker(self.expected)
        self.log_process = FakeLogProcess(b"line-one\nline-two\n")
        self.log_spawner = FakeLogSpawner(self.log_process)
        executable = Path(self.temporary.name).resolve() / "docker.exe"
        self.controller = OfflineEmergencyController(
            self.store,
            docker_executable=executable,
            working_directory=Path(self.temporary.name).resolve(),
            process_runner=self.runner,
            process_spawner=self.log_spawner,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_status_and_inspect_return_only_redacted_fixed_projections(self) -> None:
        status = self.controller.status(self.expected.instance_id)
        inspected = self.controller.inspect(self.expected.instance_id)

        self.assertIs(status.state, EmergencyRuntimeState.RUNNING)
        self.assertTrue(status.networks_match)
        self.assertEqual(inspected.container_id, self.expected.container_id)
        self.assertEqual(inspected.image_id, self.expected.image_id)
        self.assertFalse(hasattr(inspected, "mounts"))
        self.assertFalse(hasattr(inspected, "environment"))
        self.assertNotIn("PRIVATE=must-not-escape", repr(inspected))
        self.assertNotIn("C:/private/host/path", repr(inspected))

        for kwargs in self.runner.kwargs:
            environment = kwargs["env"]
            self.assertNotIn("PATH", environment)
            self.assertFalse(any(name.startswith("DOCKER_") for name in environment))

    def test_bounded_logs_use_only_exact_full_id_and_fixed_flags(self) -> None:
        logs = self.controller.logs(self.expected.instance_id, tail=50)

        self.assertEqual(logs, "line-one\nline-two\n")
        self.assertEqual(
            self.log_spawner.commands,
            [
                (
                    str(Path(self.temporary.name).resolve() / "docker.exe"),
                    "container",
                    "logs",
                    "--tail",
                    "50",
                    self.expected.container_id,
                )
            ],
        )
        self.assertEqual(self.log_spawner.kwargs[0]["stdout"], subprocess.PIPE)
        self.assertEqual(self.log_spawner.kwargs[0]["stderr"], subprocess.PIPE)
        self.assertIs(self.log_spawner.kwargs[0]["text"], False)
        for tail in (0, -1, 501, True, "50"):
            with self.subTest(tail=tail):
                with self.assertRaises(OfflineEmergencyPolicyError):
                    self.controller.logs(self.expected.instance_id, tail=tail)

    def test_logs_enforce_a_hard_combined_byte_limit_before_returning(self) -> None:
        for stdout, stderr in (
            (b"x" * ((256 * 1024) + 1), b""),
            (b"", b"x" * ((256 * 1024) + 1)),
        ):
            with self.subTest(stream="stdout" if stdout else "stderr"):
                process = FakeLogProcess(stdout, stderr)
                spawner = FakeLogSpawner(process)
                controller = OfflineEmergencyController(
                    self.store,
                    docker_executable=Path(self.temporary.name).resolve() / "docker.exe",
                    working_directory=Path(self.temporary.name).resolve(),
                    process_runner=self.runner,
                    process_spawner=spawner,
                )

                with self.assertRaisesRegex(
                    OfflineEmergencyTransportError,
                    "^offline_emergency_transport_error$",
                ):
                    controller.logs(self.expected.instance_id)

                self.assertTrue(process.killed)
                self.assertGreaterEqual(process.wait_calls, 1)

    def test_network_drift_does_not_block_exact_stop(self) -> None:
        self.runner.container = container_document(
            self.expected,
            networks=("runtime-access", "unexpected-network"),
        )

        result = self.controller.stop_exact(self.expected.instance_id)

        self.assertIs(result.state, EmergencyRuntimeState.EXITED)
        self.assertFalse(result.networks_match)
        stop_commands = [
            command for command in self.runner.commands if command[1:3] == ("container", "stop")
        ]
        self.assertEqual(
            stop_commands,
            [
                (
                    str(Path(self.temporary.name).resolve() / "docker.exe"),
                    "container",
                    "stop",
                    "--time",
                    "30",
                    self.expected.container_id,
                )
            ],
        )
        self.assertNotIn(self.expected.container_name, stop_commands[0])

    def test_every_immutable_mismatch_performs_zero_stop(self) -> None:
        mismatches = (
            {"io.freqtrade.runtime.instance-id": "other-instance"},
            {"io.freqtrade.runtime.attempt-id": "other-attempt"},
            {"io.freqtrade.runtime.runtime-spec-digest": "9" * 64},
            {"io.freqtrade.runtime.launch-authority-digest": "8" * 64},
            {"com.docker.compose.project": "other-project"},
            {"com.docker.compose.service": "other-service"},
        )
        for changes in mismatches:
            with self.subTest(changes=changes):
                runner = FakeDocker(self.expected)
                runner.container = container_document(
                    self.expected,
                    label_changes=changes,
                )
                controller = OfflineEmergencyController(
                    self.store,
                    docker_executable=Path(self.temporary.name).resolve() / "docker.exe",
                    working_directory=Path(self.temporary.name).resolve(),
                    process_runner=runner,
                )
                with self.assertRaisesRegex(
                    OfflineIdentityMismatch,
                    "^offline_identity_mismatch$",
                ):
                    controller.stop_exact(self.expected.instance_id)
                self.assertFalse(
                    any(command[1:3] == ("container", "stop") for command in runner.commands)
                )

    def test_image_commit_mismatch_performs_zero_stop(self) -> None:
        self.runner.image["Config"]["Labels"][f"{IMAGE_LABEL_PREFIX}backend"] = "f" * 40

        with self.assertRaises(OfflineIdentityMismatch):
            self.controller.stop_exact(self.expected.instance_id)

        self.assertFalse(
            any(command[1:3] == ("container", "stop") for command in self.runner.commands)
        )

    def test_stop_failure_is_ambiguous_and_never_retried(self) -> None:
        self.runner.stop_returncode = 1

        with self.assertRaisesRegex(
            OfflineEmergencyAmbiguousOutcome,
            "^offline_emergency_ambiguous_outcome$",
        ):
            self.controller.stop_exact(self.expected.instance_id)

        self.assertEqual(
            sum(
                command[1:3] == ("container", "stop")
                for command in self.runner.commands
            ),
            1,
        )

    def test_relative_docker_path_is_rejected_before_runner(self) -> None:
        with self.assertRaisesRegex(
            OfflineEmergencyPolicyError,
            "^offline_emergency_policy_error$",
        ):
            OfflineEmergencyController(
                self.store,
                docker_executable=Path("docker.exe"),
                working_directory=Path(self.temporary.name).resolve(),
                process_runner=self.runner,
            )
        self.assertEqual(self.runner.commands, [])

    def test_public_action_surface_is_closed(self) -> None:
        public_methods = {
            name
            for name, value in OfflineEmergencyController.__dict__.items()
            if not name.startswith("_") and callable(value)
        }
        self.assertEqual(public_methods, {"status", "inspect", "logs", "stop_exact"})


if __name__ == "__main__":
    unittest.main()
