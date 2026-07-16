from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread
from unittest import mock

from tests.test_runtime_snapshot import valid_authority
from tools.runtime_driver import (
    AmbiguousDriverOutcome,
    AmbiguousNetworkOutcome,
    DriverHealth,
    DriverIdentityMismatch,
    DriverObjectOccupied,
    DriverPolicyError,
    DriverState,
    DriverValidationError,
    HealthProfile,
    PlatformControlIdentity,
    PlatformControlIdentityMismatch,
)
from tools.runtime_preparation_lease import ActiveLaunchAuthorityLease
from tools.runtime_snapshot import compile_launch_snapshot
from tools.runtime_supervisor.writer_guard import (
    SupervisorDockerWriterGuard,
    SupervisorWriterGuardError,
)
from tools.runtime_supervisor.daemon import SupervisorProcessLock

try:
    from tools.safe_compose_driver import (
        SafeComposeRuntimeDriver,
        SafePlatformControlIdentityProvider,
    )
except ImportError:
    SafeComposeRuntimeDriver = None  # type: ignore[assignment,misc]
    SafePlatformControlIdentityProvider = None  # type: ignore[assignment,misc]


if os.name == "nt":
    DOCKER = Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")
    COMPOSE = Path("C:/Program Files/Docker/Docker/resources/bin/docker-compose.exe")
    APPROVED_SYSTEM_ROOT = "C:/Windows"
    APPROVED_ENVIRONMENT = {
        "DOCKER_CONTEXT": "desktop-linux",
        "DOCKER_HOST": "npipe:////./pipe/docker_engine",
        "SYSTEMROOT": APPROVED_SYSTEM_ROOT,
    }
else:
    DOCKER = Path("/usr/bin/docker")
    COMPOSE = Path("/usr/local/bin/docker-compose")
    APPROVED_SYSTEM_ROOT = None
    APPROVED_ENVIRONMENT = {
        "DOCKER_CONTEXT": "default",
        "DOCKER_HOST": "unix:///var/run/docker.sock",
    }


def _active_lease(authority):
    lease = object.__new__(ActiveLaunchAuthorityLease)
    object.__setattr__(lease, "authority", authority)
    object.__setattr__(lease, "material_lease", object())
    object.__setattr__(lease, "state_lease", object())
    object.__setattr__(lease, "secret_lease", object())
    return lease


class AuthorityResolver:
    def __init__(self, authority, lease) -> None:
        self.authority = authority
        self.lease = lease

    def resolve_active_launch(self, identity, launch_authority_digest):
        if identity != self.authority.identity:
            raise DriverPolicyError()
        return self.lease

    def resolve_launch_authority_digest(self, identity):
        if identity != self.authority.identity:
            raise DriverPolicyError()
        return compile_launch_snapshot(self.authority).launch_authority_digest

    def resolve_health_profile(self, identity, profile_id):
        if identity != self.authority.identity:
            raise DriverPolicyError()
        profile = self.authority.policies.health_profile
        if profile.profile_id != profile_id:
            raise DriverPolicyError()
        return profile

    def resolve_platform_control_identity(self):
        return PlatformControlIdentity(
            container_id="d" * 64,
            container_name="freqtrade-cn-platform-control",
            image_id="sha256:" + "e" * 64,
            compose_project="freqtrade-cn",
            compose_service="platform-control",
            identity_revision="platform-control-v1",
        )


class NetworkDriverSpy:
    def __init__(self, *, faults=None) -> None:
        self.events = []
        self.faults = {} if faults is None else dict(faults)

    def _record(self, name, *values):
        self.events.append((name, *values))
        fault = self.faults.get(name)
        if fault is not None:
            raise fault

    def ensure_access_network(self, identity, platform_control, runtime=None):
        self._record("ensure", identity, platform_control, runtime)

    def verify_created_access_network(self, identity, platform_control, runtime):
        self._record("verify_created", identity, platform_control, runtime)

    def verify_active_access_network(self, identity, platform_control, runtime):
        self._record("verify_active", identity, platform_control, runtime)

    def inspect_access_network(self, identity, platform_control, runtime):
        raise AssertionError("launch must use bounded network operations")

    def remove_access_network_if_empty(self, identity):
        raise AssertionError("launch must not remove a network")


class PlatformIdentityRunner:
    def __init__(self, *, image_id: str | None = None) -> None:
        self.container_id = "d" * 64
        self.image_id = image_id or "sha256:" + "e" * 64
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((tuple(command), kwargs))
        if command[1:3] == ["container", "ls"]:
            return subprocess.CompletedProcess(
                command,
                0,
                self.container_id + "\n",
                "",
            )
        if command[1:3] == ["container", "inspect"]:
            document = {
                "Id": self.container_id,
                "Name": "/freqtrade-cn-platform-control",
                "Image": self.image_id,
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "freqtrade-cn",
                        "com.docker.compose.service": "platform-control",
                        "io.freqtrade.platform.identity-revision": (
                            "platform-control-v1"
                        ),
                        "io.freqtrade.platform.role": "platform-control",
                    }
                },
            }
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps([document]),
                "",
            )
        raise AssertionError(f"unexpected command: {command}")


class SafePlatformControlIdentityProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.expected_image_id = "sha256:" + "e" * 64

    def provider(self, runner):
        return SafePlatformControlIdentityProvider(
            docker_executable=DOCKER,
            environment=APPROVED_ENVIRONMENT,
            approved_docker_host=APPROVED_ENVIRONMENT["DOCKER_HOST"],
            approved_docker_context=APPROVED_ENVIRONMENT["DOCKER_CONTEXT"],
            approved_system_root=APPROVED_SYSTEM_ROOT,
            working_directory=Path(self.temporary.name),
            expected_image_id=self.expected_image_id,
            command_runner=runner,
        )

    def test_resolves_only_the_fixed_full_platform_identity(self) -> None:
        runner = PlatformIdentityRunner()

        identity = self.provider(runner).resolve_platform_control_identity()

        self.assertEqual(identity.container_id, runner.container_id)
        self.assertEqual(identity.image_id, self.expected_image_id)
        self.assertEqual(
            runner.calls[1][0],
            (str(DOCKER), "container", "inspect", runner.container_id),
        )
        self.assertTrue(
            all(kwargs["env"] == APPROVED_ENVIRONMENT for _command, kwargs in runner.calls)
        )

    def test_rejects_a_same_name_replacement_with_the_wrong_image(self) -> None:
        runner = PlatformIdentityRunner(image_id="sha256:" + "f" * 64)

        with self.assertRaisesRegex(
            PlatformControlIdentityMismatch,
            "^platform_control_identity_mismatch$",
        ):
            self.provider(runner).resolve_platform_control_identity()


class SupervisorDockerWriterGuardTests(unittest.TestCase):
    def test_guard_binds_only_one_object_identity_and_revocation_is_final(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = SupervisorProcessLock(Path(directory) / "first.lock")
            different_authority = SupervisorProcessLock(
                Path(directory) / "second.lock"
            )
            authority.acquire()
            different_authority.acquire()
            try:
                guard = SupervisorDockerWriterGuard()

                self.assertIs(guard.activate(authority), guard)
                guard.require_active(authority)
                with guard.mutation_scope(authority):
                    pass
                with self.assertRaises(SupervisorWriterGuardError):
                    guard.require_active(different_authority)
                with self.assertRaises(SupervisorWriterGuardError):
                    guard.revoke(different_authority)

                guard.revoke(authority)
                guard.revoke(authority)
                with self.assertRaises(SupervisorWriterGuardError):
                    guard.require_active(authority)
                with self.assertRaises(SupervisorWriterGuardError):
                    guard.activate(authority)
            finally:
                different_authority.release()
                authority.release()

    def test_guard_rejects_string_and_path_authority_derivation(self) -> None:
        for authority in ("supervisor.lock", Path("supervisor.lock")):
            with self.subTest(authority=authority), self.assertRaises(
                SupervisorWriterGuardError
            ):
                SupervisorDockerWriterGuard().activate(authority)

    def test_guard_rejects_an_unheld_process_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = SupervisorProcessLock(Path(directory) / "supervisor.lock")
            with self.assertRaises(SupervisorWriterGuardError):
                SupervisorDockerWriterGuard().activate(authority)

    def test_mutation_scope_allows_only_one_writer_at_a_time(self) -> None:
        guard = SupervisorDockerWriterGuard()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        authority = SupervisorProcessLock(Path(temporary.name) / "supervisor.lock")
        authority.acquire()
        self.addCleanup(authority.release)
        guard.activate(authority)
        first_entered = Event()
        release_first = Event()
        second_started = Event()
        second_entered = Event()

        def first_writer() -> None:
            with guard.mutation_scope(authority):
                first_entered.set()
                release_first.wait(timeout=1)

        def second_writer() -> None:
            second_started.set()
            with guard.mutation_scope(authority):
                second_entered.set()

        first = Thread(target=first_writer)
        second = Thread(target=second_writer)
        first.start()
        self.assertTrue(first_entered.wait(timeout=1))
        second.start()
        self.assertTrue(second_started.wait(timeout=1))
        self.assertFalse(second_entered.wait(timeout=0.05))
        release_first.set()
        first.join(timeout=1)
        second.join(timeout=1)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertTrue(second_entered.is_set())


def _container_document(
    snapshot,
    *,
    authority_digest=None,
    attempt_id=None,
    status="running",
):
    labels = {
        "com.docker.compose.project": snapshot.identity.project_name,
        "com.docker.compose.service": "runtime",
        "io.freqtrade.runtime.attempt-id": (
            snapshot.identity.attempt_id if attempt_id is None else attempt_id
        ),
        "io.freqtrade.runtime.container-name": snapshot.identity.container_name,
        "io.freqtrade.runtime.image-id": snapshot.identity.image_id,
        "io.freqtrade.runtime.instance-id": snapshot.identity.instance_id,
        "io.freqtrade.runtime.launch-authority-digest": (
            snapshot.launch_authority_digest
            if authority_digest is None
            else authority_digest
        ),
        "io.freqtrade.runtime.project-name": snapshot.identity.project_name,
        "io.freqtrade.runtime.runtime-spec-digest": (
            snapshot.identity.runtime_spec_digest
        ),
        "io.freqtrade.runtime.state-allocation-id": (
            snapshot.identity.state_allocation_id
        ),
    }
    return {
        "Id": "c" * 64,
        "Name": f"/{snapshot.identity.container_name}",
        "Image": snapshot.identity.image_id,
        "Config": {"Labels": labels},
        "State": {"Status": status, "ExitCode": 0},
        "NetworkSettings": {
            "Networks": {name: {} for name in snapshot.identity.network_names}
        },
    }


class DockerRunner:
    def __init__(
        self,
        snapshot,
        inspections,
        *,
        create_result=None,
        render_transform=None,
        inspection_callback=None,
    ) -> None:
        self.snapshot = snapshot
        self.inspections = list(inspections)
        self.create_result = create_result
        self.render_transform = render_transform
        self.inspection_callback = inspection_callback
        self.calls = []
        self._current = None
        self.inspection_count = 0

    def __call__(self, command, **kwargs):
        self.calls.append((tuple(command), kwargs))
        if command[1:5] == ["container", "ls", "--all", "--no-trunc"]:
            self._current = self.inspections.pop(0)
            self.inspection_count += 1
            if isinstance(self._current, BaseException):
                raise self._current
            if self.inspection_callback is not None:
                self.inspection_callback(self.inspection_count, self._current)
            stdout = "" if self._current is None else f"{self._current['Id']}\n"
            return subprocess.CompletedProcess(command, 0, stdout, "")
        if command[1:3] == ["container", "inspect"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps([self._current]), ""
            )
        if command[0] == str(COMPOSE) and "config" in command:
            output = kwargs["input"]
            if self.render_transform is not None:
                output = self.render_transform(output)
            return subprocess.CompletedProcess(command, 0, output, "")
        if command[0] == str(COMPOSE) and "create" in command:
            if isinstance(self.create_result, BaseException):
                raise self.create_result
            return self.create_result or subprocess.CompletedProcess(command, 0, "", "")
        if command[1:3] == ["container", "start"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:3] == ["container", "stop"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:3] == ["container", "exec"]:
            return subprocess.CompletedProcess(command, 0, "secret raw output", "")
        raise AssertionError(f"unexpected command shape: {command[1:3]}")

    def commands(self, prefix):
        return [
            call for call, _kwargs in self.calls if call[1 : 1 + len(prefix)] == prefix
        ]

    def compose_commands(self, action):
        return [
            call
            for call, _kwargs in self.calls
            if call[0] == str(COMPOSE) and action in call
        ]


@unittest.skipIf(SafeComposeRuntimeDriver is None, "safe compose driver is missing")
class SafeComposeDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.authority = valid_authority()
        self.snapshot = compile_launch_snapshot(self.authority)
        self.lease = _active_lease(self.authority)
        self.resolver = AuthorityResolver(self.authority, self.lease)
        self.network_driver = NetworkDriverSpy()
        self.writer_authority = SupervisorProcessLock(
            Path(self.temporary.name) / "supervisor.lock"
        )
        self.writer_authority.acquire()
        self.writer_guard = SupervisorDockerWriterGuard()
        self.writer_guard.activate(self.writer_authority)

    def tearDown(self) -> None:
        try:
            self.writer_guard.revoke(self.writer_authority)
        except SupervisorWriterGuardError:
            pass
        self.writer_authority.release()
        self.temporary.cleanup()

    def driver(
        self,
        runner,
        *,
        environment=None,
        resolver=None,
        temporary_directory=None,
        writer_guard=None,
        writer_authority=None,
    ):
        return SafeComposeRuntimeDriver(
            docker_executable=DOCKER,
            compose_executable=COMPOSE,
            environment=(APPROVED_ENVIRONMENT if environment is None else environment),
            approved_docker_host=APPROVED_ENVIRONMENT["DOCKER_HOST"],
            approved_docker_context=APPROVED_ENVIRONMENT["DOCKER_CONTEXT"],
            approved_system_root=APPROVED_SYSTEM_ROOT,
            working_directory=Path(self.temporary.name),
            temporary_directory=(
                Path(self.temporary.name)
                if temporary_directory is None
                else temporary_directory
            ),
            authority_resolver=self.resolver if resolver is None else resolver,
            platform_control_identity_provider=self.resolver,
            access_network_driver=self.network_driver,
            writer_guard=(
                self.writer_guard if writer_guard is None else writer_guard
            ),
            writer_authority=(
                self.writer_authority
                if writer_authority is None
                else writer_authority
            ),
            command_runner=runner,
        )

    def test_constructor_requires_the_exact_active_writer_guard(self) -> None:
        runner = mock.Mock()

        with self.assertRaises(DriverPolicyError):
            self.driver(runner, writer_guard=object())
        with self.assertRaises(SupervisorWriterGuardError):
            self.driver(
                runner,
                writer_authority=SupervisorProcessLock(
                    Path(self.temporary.name) / "unheld.lock"
                ),
            )

        self.assertEqual(runner.mock_calls, [])

    def test_revoked_guard_blocks_launch_and_stop_before_runner(self) -> None:
        runner = mock.Mock()
        driver = self.driver(runner)
        self.writer_guard.revoke(self.writer_authority)

        for operation in (
            lambda: driver.launch(self.snapshot),
            lambda: driver.stop(self.snapshot.identity),
        ):
            with self.subTest(operation=operation), self.assertRaises(
                SupervisorWriterGuardError
            ):
                operation()

        self.assertEqual(runner.mock_calls, [])

    def test_revocation_during_render_blocks_compose_create(self) -> None:
        runner = DockerRunner(self.snapshot, [None, None])

        def revoke_after_render(payload):
            self.writer_guard.revoke(self.writer_authority)
            return payload

        runner.render_transform = revoke_after_render

        with mock.patch.object(
            ActiveLaunchAuthorityLease,
            "revalidate_for_runtime_action",
            return_value=None,
        ), self.assertRaises(SupervisorWriterGuardError):
            self.driver(runner).launch(self.snapshot)

        self.assertEqual(runner.compose_commands("create"), [])

    def test_launch_uses_one_safe_action_and_real_post_action_inspection(self) -> None:
        created = _container_document(self.snapshot, status="created")
        observed = _container_document(self.snapshot)
        runner = DockerRunner(
            self.snapshot,
            [None, None, created, created, observed],
        )
        events = []
        with mock.patch.object(
            ActiveLaunchAuthorityLease,
            "revalidate_for_runtime_action",
            side_effect=lambda: events.append("lease"),
        ) as revalidate:
            result = self.driver(runner).launch(self.snapshot)

        self.assertIs(result.state, DriverState.RUNNING)
        self.assertEqual(result.container_id, "c" * 64)
        self.assertEqual(revalidate.call_count, 4)
        self.assertEqual(
            [event[0] for event in self.network_driver.events],
            [
                "ensure",
                "verify_created",
                "verify_created",
                "verify_active",
            ],
        )
        compose = runner.compose_commands("create")
        self.assertEqual(len(compose), 1)
        command, kwargs = next(
            (command, kwargs)
            for command, kwargs in runner.calls
            if command[0] == str(COMPOSE) and "create" in command
        )
        self.assertNotIn("--force-recreate", command)
        self.assertIn("--no-recreate", command)
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["env"], APPROVED_ENVIRONMENT)
        starts = runner.commands(("container", "start"))
        self.assertEqual(starts, [(str(DOCKER), "container", "start", "c" * 64)])
        _config_command, config_kwargs = next(
            (command, kwargs)
            for command, kwargs in runner.calls
            if command[0] == str(COMPOSE) and "config" in command
        )
        compose_document = json.loads(config_kwargs["input"])
        binding = self.snapshot.network_bindings[0]
        self.assertEqual(
            compose_document["services"]["runtime"]["networks"],
            {binding.network_name: {"aliases": [binding.runtime_alias]}},
        )

    def test_mapping_ingress_fails_before_docker_or_authority_resolution(self) -> None:
        runner = mock.Mock()
        resolver = mock.Mock()
        with self.assertRaisesRegex(DriverValidationError, "^driver_validation_error$"):
            self.driver(runner, resolver=resolver).launch({})
        runner.assert_not_called()
        resolver.resolve_active_launch.assert_not_called()

    def test_execution_context_poison_fails_before_docker(self) -> None:
        mutations = (
            {"PATH": "attacker"},
            {"Path": "attacker"},
            {"DOCKER_HOST": "tcp://attacker:2375"},
            {"DOCKER_CONTEXT": "attacker"},
            {"DOCKER_CONFIG": "attacker"},
            {"docker_config": "attacker"},
            {"DOCKER_TLS_VERIFY": "1"},
            {"DOCKER_CERT_PATH": "attacker"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                runner = mock.Mock()
                environment = dict(APPROVED_ENVIRONMENT)
                environment.update(mutation)
                with self.assertRaisesRegex(DriverPolicyError, "^driver_policy_error$"):
                    self.driver(runner, environment=environment).launch(self.snapshot)
                runner.assert_not_called()

    def test_driver_owns_an_immutable_environment_copy(self) -> None:
        environment = dict(APPROVED_ENVIRONMENT)
        runner = DockerRunner(self.snapshot, [None])
        driver = self.driver(runner, environment=environment)
        environment["DOCKER_HOST"] = "tcp://attacker:2375"

        self.assertIs(driver.inspect(self.snapshot.identity).state, DriverState.ABSENT)
        self.assertTrue(runner.calls)
        self.assertTrue(
            all(
                kwargs["env"] == APPROVED_ENVIRONMENT
                for _command, kwargs in runner.calls
            )
        )

    def test_occupied_locator_fails_before_authority_or_mutation(self) -> None:
        runner = DockerRunner(self.snapshot, [_container_document(self.snapshot)])
        with self.assertRaisesRegex(DriverObjectOccupied, "^driver_object_occupied$"):
            self.driver(runner).launch(self.snapshot)
        self.assertFalse(runner.compose_commands("create"))

    def test_locator_is_rechecked_after_render_and_lease_before_action(self) -> None:
        occupied = _container_document(self.snapshot, attempt_id="wrong-attempt")
        runner = DockerRunner(self.snapshot, [None, occupied])
        with (
            mock.patch.object(
                ActiveLaunchAuthorityLease,
                "revalidate_for_runtime_action",
            ) as revalidate,
            self.assertRaisesRegex(DriverObjectOccupied, "^driver_object_occupied$"),
        ):
            self.driver(runner).launch(self.snapshot)
        self.assertEqual(revalidate.call_count, 3)
        self.assertFalse(runner.compose_commands("create"))

    def test_closed_lease_fails_before_action_with_fixed_error(self) -> None:
        runner = DockerRunner(self.snapshot, [None, None])
        with (
            mock.patch.object(
                ActiveLaunchAuthorityLease,
                "revalidate_for_runtime_action",
                side_effect=OSError("C:/secret/path"),
            ),
            self.assertRaisesRegex(DriverPolicyError, "^driver_policy_error$"),
        ):
            self.driver(runner).launch(self.snapshot)
        self.assertFalse(runner.compose_commands("config"))
        self.assertFalse(runner.compose_commands("create"))

    def test_timeout_after_action_boundary_is_ambiguous_and_not_retried(self) -> None:
        runner = DockerRunner(
            self.snapshot,
            [None, None],
            create_result=subprocess.TimeoutExpired([str(COMPOSE)], 1),
        )
        with (
            mock.patch.object(
                ActiveLaunchAuthorityLease,
                "revalidate_for_runtime_action",
            ),
            self.assertRaisesRegex(
                AmbiguousDriverOutcome, "^ambiguous_driver_outcome$"
            ),
        ):
            self.driver(runner).launch(self.snapshot)
        self.assertEqual(len(runner.compose_commands("create")), 1)

    def test_post_create_failures_are_ambiguous_and_never_start(self) -> None:
        created = _container_document(self.snapshot, status="created")
        cases = (
            (
                "inspect_transport",
                DockerRunner(self.snapshot, [None, None, OSError("lost")]),
                [None, None, None],
            ),
            (
                "lease_drift",
                DockerRunner(self.snapshot, [None, None, created, created]),
                [None, None, None, OSError("changed source")],
            ),
        )
        for name, runner, lease_effects in cases:
            with self.subTest(name=name):
                with (
                    mock.patch.object(
                        ActiveLaunchAuthorityLease,
                        "revalidate_for_runtime_action",
                        side_effect=lease_effects,
                    ),
                    self.assertRaisesRegex(
                        AmbiguousDriverOutcome,
                        "^ambiguous_driver_outcome$",
                    ),
                ):
                    self.driver(runner).launch(self.snapshot)
                self.assertEqual(len(runner.compose_commands("create")), 1)
                self.assertFalse(runner.commands(("container", "start")))

    def test_post_create_requires_exact_created_state_until_start(self) -> None:
        created = _container_document(self.snapshot, status="created")
        for name, inspections in (
            (
                "first_state_running",
                [None, None, _container_document(self.snapshot, status="running")],
            ),
            (
                "first_state_exited",
                [None, None, _container_document(self.snapshot, status="exited")],
            ),
            (
                "first_state_unknown",
                [None, None, _container_document(self.snapshot, status="paused")],
            ),
            (
                "final_state_running",
                [None, None, created, _container_document(self.snapshot)],
            ),
            (
                "final_state_exited",
                [
                    None,
                    None,
                    created,
                    _container_document(self.snapshot, status="exited"),
                ],
            ),
            (
                "final_state_unknown",
                [
                    None,
                    None,
                    created,
                    _container_document(self.snapshot, status="paused"),
                ],
            ),
            ("final_absent", [None, None, created, None]),
        ):
            with self.subTest(name=name):
                runner = DockerRunner(self.snapshot, inspections)
                with (
                    mock.patch.object(
                        ActiveLaunchAuthorityLease,
                        "revalidate_for_runtime_action",
                    ),
                    self.assertRaisesRegex(
                        AmbiguousDriverOutcome,
                        "^ambiguous_driver_outcome$",
                    ),
                ):
                    self.driver(runner).launch(self.snapshot)
                self.assertEqual(len(runner.compose_commands("create")), 1)
                self.assertFalse(runner.commands(("container", "start")))

    def test_post_create_snapshot_drift_is_ambiguous_and_never_starts(self) -> None:
        created = _container_document(self.snapshot, status="created")

        def mutate_after_create(count, _observation):
            if count == 3:
                object.__setattr__(self.snapshot, "network_bindings", ())

        runner = DockerRunner(
            self.snapshot,
            [None, None, created],
            inspection_callback=mutate_after_create,
        )
        with (
            mock.patch.object(
                ActiveLaunchAuthorityLease,
                "revalidate_for_runtime_action",
            ),
            self.assertRaisesRegex(
                AmbiguousDriverOutcome,
                "^ambiguous_driver_outcome$",
            ),
        ):
            self.driver(runner).launch(self.snapshot)

        self.assertEqual(len(runner.compose_commands("create")), 1)
        self.assertFalse(runner.commands(("container", "start")))

    def test_final_created_inspection_precedes_last_lease_gate(self) -> None:
        created = _container_document(self.snapshot, status="created")
        revoked = False

        def revoke_after_final_created(count, _observation):
            nonlocal revoked
            if count == 4:
                revoked = True

        def revalidate():
            if revoked:
                raise OSError("source revoked")

        runner = DockerRunner(
            self.snapshot,
            [None, None, created, created],
            inspection_callback=revoke_after_final_created,
        )
        with (
            mock.patch.object(
                ActiveLaunchAuthorityLease,
                "revalidate_for_runtime_action",
                side_effect=revalidate,
            ) as validation,
            self.assertRaisesRegex(
                AmbiguousDriverOutcome,
                "^ambiguous_driver_outcome$",
            ),
        ):
            self.driver(runner).launch(self.snapshot)
        self.assertEqual(validation.call_count, 4)
        self.assertEqual(len(runner.compose_commands("create")), 1)
        self.assertFalse(runner.commands(("container", "start")))

    def test_created_network_gate_failure_prevents_container_start(self) -> None:
        created = _container_document(self.snapshot, status="created")
        runner = DockerRunner(self.snapshot, [None, None, created])
        self.network_driver = NetworkDriverSpy(
            faults={"verify_created": RuntimeError("invalid created topology")}
        )

        with (
            mock.patch.object(
                ActiveLaunchAuthorityLease,
                "revalidate_for_runtime_action",
            ),
            self.assertRaisesRegex(
                AmbiguousDriverOutcome,
                "^ambiguous_driver_outcome$",
            ),
        ):
            self.driver(runner).launch(self.snapshot)

        self.assertEqual(
            [event[0] for event in self.network_driver.events],
            ["ensure", "verify_created"],
        )
        self.assertFalse(runner.commands(("container", "start")))

    def test_active_network_gate_failure_never_returns_launch_success(self) -> None:
        created = _container_document(self.snapshot, status="created")
        observed = _container_document(self.snapshot)
        runner = DockerRunner(
            self.snapshot,
            [None, None, created, created, observed],
        )
        self.network_driver = NetworkDriverSpy(
            faults={"verify_active": RuntimeError("invalid active topology")}
        )

        with (
            mock.patch.object(
                ActiveLaunchAuthorityLease,
                "revalidate_for_runtime_action",
            ),
            self.assertRaisesRegex(
                AmbiguousDriverOutcome,
                "^ambiguous_driver_outcome$",
            ),
        ):
            self.driver(runner).launch(self.snapshot)

        self.assertEqual(len(runner.commands(("container", "start"))), 1)
        self.assertEqual(
            [event[0] for event in self.network_driver.events],
            [
                "ensure",
                "verify_created",
                "verify_created",
                "verify_active",
            ],
        )

    def test_actual_render_rejects_unmodeled_nested_behavior(self) -> None:
        def mutation(name):
            def transform(document_text):
                document = json.loads(document_text)
                service = document["services"]["runtime"]
                if name == "health_disable":
                    service["healthcheck"]["disable"] = True
                elif name == "network_wrong_alias":
                    network = next(iter(service["networks"]))
                    service["networks"][network] = {"aliases": ["platform-control"]}
                elif name == "network_missing_alias":
                    network = next(iter(service["networks"]))
                    service["networks"][network] = {}
                elif name == "network_extra_alias":
                    network = next(iter(service["networks"]))
                    service["networks"][network]["aliases"].append("attacker")
                elif name == "bind_propagation":
                    service["volumes"][0]["bind"]["propagation"] = "rshared"
                elif name == "network_attachable":
                    network = next(iter(document["networks"]))
                    document["networks"][network]["attachable"] = True
                elif name == "default_command":
                    service["command"] = None
                return json.dumps(document)

            return transform

        for name in (
            "health_disable",
            "network_wrong_alias",
            "network_missing_alias",
            "network_extra_alias",
            "bind_propagation",
            "network_attachable",
            "default_command",
        ):
            with self.subTest(name=name):
                runner = DockerRunner(
                    self.snapshot,
                    [None],
                    render_transform=mutation(name),
                )
                with (
                    mock.patch.object(
                        ActiveLaunchAuthorityLease,
                        "revalidate_for_runtime_action",
                    ),
                    self.assertRaisesRegex(
                        DriverPolicyError,
                        "^driver_policy_error$",
                    ),
                ):
                    self.driver(runner).launch(self.snapshot)
                self.assertFalse(runner.compose_commands("create"))

    def test_actual_render_accepts_only_known_compose_normalizations(self) -> None:
        def normalize(document_text):
            document = json.loads(document_text)
            for definition in document["networks"].values():
                definition["ipam"] = {}
            for mount in document["services"]["runtime"]["volumes"]:
                if mount["read_only"] is False:
                    del mount["read_only"]
            service = document["services"]["runtime"]
            service["mem_limit"] = str(service["mem_limit"])
            return json.dumps(document)

        created = _container_document(self.snapshot, status="created")
        observed = _container_document(self.snapshot)
        runner = DockerRunner(
            self.snapshot,
            [None, None, created, created, observed],
            render_transform=normalize,
        )
        with mock.patch.object(
            ActiveLaunchAuthorityLease,
            "revalidate_for_runtime_action",
        ):
            result = self.driver(runner).launch(self.snapshot)

        self.assertIs(result.state, DriverState.RUNNING)
        self.assertEqual(len(runner.compose_commands("create")), 1)

    def test_actual_render_rejects_behavioral_compose_network_and_mount_changes(
        self,
    ) -> None:
        def mutation(name):
            def transform(document_text):
                document = json.loads(document_text)
                service = document["services"]["runtime"]
                if name == "network_ipam":
                    network = next(iter(document["networks"]))
                    document["networks"][network]["ipam"] = {
                        "config": [{"subnet": "10.0.0.0/24"}]
                    }
                elif name == "readonly_omitted":
                    mount = next(
                        value for value in service["volumes"] if value["read_only"]
                    )
                    del mount["read_only"]
                elif name == "memory_suffix":
                    service["mem_limit"] = "512m"
                return json.dumps(document)

            return transform

        for name in ("network_ipam", "readonly_omitted", "memory_suffix"):
            with self.subTest(name=name):
                runner = DockerRunner(
                    self.snapshot,
                    [None],
                    render_transform=mutation(name),
                )
                with (
                    mock.patch.object(
                        ActiveLaunchAuthorityLease,
                        "revalidate_for_runtime_action",
                    ),
                    self.assertRaisesRegex(
                        DriverPolicyError,
                        "^driver_policy_error$",
                    ),
                ):
                    self.driver(runner).launch(self.snapshot)
                self.assertFalse(runner.compose_commands("create"))
                self.assertEqual(self.network_driver.events, [])

    def test_ambiguous_network_preparation_is_not_reclassified_or_retried(
        self,
    ) -> None:
        runner = DockerRunner(self.snapshot, [None])
        self.network_driver = NetworkDriverSpy(
            faults={"ensure": AmbiguousNetworkOutcome()}
        )

        with (
            mock.patch.object(
                ActiveLaunchAuthorityLease,
                "revalidate_for_runtime_action",
            ),
            self.assertRaisesRegex(
                AmbiguousNetworkOutcome,
                "^ambiguous_network_outcome$",
            ),
        ):
            self.driver(runner).launch(self.snapshot)

        self.assertEqual(
            [event[0] for event in self.network_driver.events],
            ["ensure"],
        )
        self.assertFalse(runner.compose_commands("create"))

    def test_stop_requires_exact_identity_and_uses_only_full_container_id(self) -> None:
        wrong = _container_document(self.snapshot, attempt_id="wrong-attempt")
        runner = DockerRunner(self.snapshot, [wrong])
        with self.assertRaisesRegex(
            DriverIdentityMismatch, "^driver_identity_mismatch$"
        ):
            self.driver(runner).stop(self.snapshot.identity)
        self.assertFalse(runner.commands(("container", "stop")))

        running = _container_document(self.snapshot)
        exited = _container_document(self.snapshot, status="exited")
        runner = DockerRunner(self.snapshot, [running, running, exited])
        result = self.driver(runner).stop(self.snapshot.identity)
        stop = runner.commands(("container", "stop"))
        self.assertEqual(len(stop), 1)
        self.assertEqual(stop[0][-1], "c" * 64)
        self.assertIs(result.state, DriverState.EXITED)
        self.assertFalse(any("rm" in command for command, _kwargs in runner.calls))

    def test_exact_stop_remains_available_when_network_topology_is_polluted(self) -> None:
        running = _container_document(self.snapshot)
        running["NetworkSettings"]["Networks"]["rogue-network"] = {}
        exited = _container_document(self.snapshot, status="exited")
        exited["NetworkSettings"]["Networks"]["rogue-network"] = {}
        runner = DockerRunner(self.snapshot, [running, running, exited])

        result = self.driver(runner).stop(self.snapshot.identity)

        self.assertIs(result.state, DriverState.EXITED)
        self.assertEqual(
            runner.commands(("container", "stop")),
            [(str(DOCKER), "container", "stop", "c" * 64)],
        )
        self.assertFalse(
            any(
                command[1:3] == ("network", "disconnect")
                for command, _kwargs in runner.calls
            )
        )

    def test_inspect_and_exact_stop_do_not_require_authority_resolver(self) -> None:
        running = _container_document(self.snapshot)
        exited = _container_document(self.snapshot, status="exited")
        resolver = mock.Mock()
        resolver.resolve_launch_authority_digest.side_effect = OSError(
            "database offline"
        )

        inspect_runner = DockerRunner(self.snapshot, [running])
        observed = self.driver(inspect_runner, resolver=resolver).inspect(
            self.snapshot.identity
        )
        self.assertIs(observed.state, DriverState.RUNNING)

        stop_runner = DockerRunner(self.snapshot, [running, running, exited])
        terminal = self.driver(stop_runner, resolver=resolver).stop(
            self.snapshot.identity
        )
        self.assertIs(terminal.state, DriverState.EXITED)
        resolver.resolve_launch_authority_digest.assert_not_called()

    def test_inspect_and_exact_stop_do_not_require_launch_scratch(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        scratch_path = Path(scratch.name)
        scratch.cleanup()
        running = _container_document(self.snapshot)
        exited = _container_document(self.snapshot, status="exited")

        inspect_runner = DockerRunner(self.snapshot, [running])
        observed = self.driver(
            inspect_runner,
            temporary_directory=scratch_path,
        ).inspect(self.snapshot.identity)
        self.assertIs(observed.state, DriverState.RUNNING)

        stop_runner = DockerRunner(self.snapshot, [running, running, exited])
        terminal = self.driver(
            stop_runner,
            temporary_directory=scratch_path,
        ).stop(self.snapshot.identity)
        self.assertIs(terminal.state, DriverState.EXITED)

        launch_runner = mock.Mock()
        with self.assertRaisesRegex(DriverPolicyError, "^driver_policy_error$"):
            self.driver(
                launch_runner,
                temporary_directory=scratch_path,
            ).launch(self.snapshot)
        launch_runner.assert_not_called()

    def test_probe_uses_exact_catalog_profile_once_and_discards_raw_output(
        self,
    ) -> None:
        running = _container_document(self.snapshot)
        runner = DockerRunner(self.snapshot, [running, running, running])
        result = self.driver(runner).probe(
            self.snapshot.identity,
            self.snapshot.health_profile.profile_id,
        )
        self.assertIs(result.status, DriverHealth.HEALTHY)
        self.assertEqual(result.attempts, 1)
        self.assertIsNone(result.failure_code)
        probes = runner.commands(("container", "exec"))
        self.assertEqual(len(probes), 1)
        self.assertEqual(
            probes[0][-len(self.snapshot.health_profile.probe_argv) :],
            self.snapshot.health_profile.probe_argv,
        )
        self.assertNotIn("secret raw output", repr(result))

    def test_probe_rechecks_running_identity_after_final_profile_resolution(
        self,
    ) -> None:
        running = _container_document(self.snapshot)
        for name, final_observation in (
            ("absent", None),
            ("exited", _container_document(self.snapshot, status="exited")),
            ("unknown", _container_document(self.snapshot, status="paused")),
        ):
            with self.subTest(name=name):
                runner = DockerRunner(
                    self.snapshot,
                    [running, running, final_observation],
                )
                if final_observation is None:
                    with self.assertRaisesRegex(
                        DriverIdentityMismatch,
                        "^driver_identity_mismatch$",
                    ):
                        self.driver(runner).probe(
                            self.snapshot.identity,
                            self.snapshot.health_profile.profile_id,
                        )
                else:
                    result = self.driver(runner).probe(
                        self.snapshot.identity,
                        self.snapshot.health_profile.profile_id,
                    )
                    self.assertIs(result.status, DriverHealth.UNKNOWN)
                    self.assertEqual(result.attempts, 0)
                    self.assertEqual(
                        result.failure_code,
                        "health_object_not_running",
                    )
                self.assertFalse(runner.commands(("container", "exec")))

    def test_probe_revalidates_profile_after_final_identity_inspection(self) -> None:
        running = _container_document(self.snapshot)
        profile = self.authority.policies.health_profile

        def mutate_profile(count, _observation):
            if count == 3:
                object.__setattr__(profile, "probe_argv", ("sh", "-c", "injected"))
                object.__setattr__(profile, "timeout_seconds", 999)

        runner = DockerRunner(
            self.snapshot,
            [running, running, running],
            inspection_callback=mutate_profile,
        )
        with self.assertRaisesRegex(DriverPolicyError, "^driver_policy_error$"):
            self.driver(runner).probe(
                self.snapshot.identity,
                self.snapshot.health_profile.profile_id,
            )
        self.assertFalse(runner.commands(("container", "exec")))

    def test_probe_rejects_unknown_or_unsafe_profile_before_execution(self) -> None:
        running = _container_document(self.snapshot)
        runner = DockerRunner(self.snapshot, [running])
        with self.assertRaisesRegex(DriverPolicyError, "^driver_policy_error$"):
            self.driver(runner).probe(self.snapshot.identity, "unknown-profile")
        self.assertFalse(runner.commands(("container", "exec")))

        class CredentialResolver(AuthorityResolver):
            def resolve_health_profile(self, identity, profile_id):
                return HealthProfile(
                    profile_id,
                    ("curl", "--token", "sentinel"),
                    0,
                    1,
                    1,
                    1,
                )

        runner = DockerRunner(self.snapshot, [running])
        resolver = CredentialResolver(self.authority, self.lease)
        with self.assertRaisesRegex(DriverPolicyError, "^driver_policy_error$"):
            self.driver(runner, resolver=resolver).probe(
                self.snapshot.identity,
                self.snapshot.health_profile.profile_id,
            )
        self.assertFalse(runner.commands(("container", "exec")))

        class UnsafeResolver(AuthorityResolver):
            def resolve_health_profile(self, identity, profile_id):
                return HealthProfile(profile_id, ("sh", "-c", "secret"), 0, 1, 1, 1)

        runner = DockerRunner(self.snapshot, [running])
        resolver = UnsafeResolver(self.authority, self.lease)
        with self.assertRaisesRegex(DriverPolicyError, "^driver_policy_error$"):
            self.driver(runner, resolver=resolver).probe(
                self.snapshot.identity,
                self.snapshot.health_profile.profile_id,
            )
        self.assertFalse(runner.commands(("container", "exec")))


if __name__ == "__main__":
    unittest.main()
