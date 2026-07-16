from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_runtime_snapshot import valid_authority
from tools.runtime_driver import (
    AmbiguousDriverOutcome,
    DriverHealth,
    DriverIdentityMismatch,
    DriverObjectOccupied,
    DriverPolicyError,
    DriverState,
    DriverValidationError,
    HealthProfile,
)
from tools.runtime_preparation_lease import ActiveLaunchAuthorityLease
from tools.runtime_snapshot import compile_launch_snapshot

try:
    from tools.safe_compose_driver import SafeComposeRuntimeDriver
except ImportError:
    SafeComposeRuntimeDriver = None  # type: ignore[assignment,misc]


DOCKER = Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")
COMPOSE = Path("C:/Program Files/Docker/Docker/resources/bin/docker-compose.exe")
APPROVED_ENVIRONMENT = {
    "DOCKER_CONTEXT": "desktop-linux",
    "DOCKER_HOST": "npipe:////./pipe/docker_engine",
    "SYSTEMROOT": "C:/Windows",
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

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def driver(
        self,
        runner,
        *,
        environment=None,
        resolver=None,
        temporary_directory=None,
    ):
        return SafeComposeRuntimeDriver(
            docker_executable=DOCKER,
            compose_executable=COMPOSE,
            environment=(APPROVED_ENVIRONMENT if environment is None else environment),
            approved_docker_host=APPROVED_ENVIRONMENT["DOCKER_HOST"],
            approved_docker_context=APPROVED_ENVIRONMENT["DOCKER_CONTEXT"],
            approved_system_root=APPROVED_ENVIRONMENT["SYSTEMROOT"],
            working_directory=Path(self.temporary.name),
            temporary_directory=(
                Path(self.temporary.name)
                if temporary_directory is None
                else temporary_directory
            ),
            authority_resolver=self.resolver if resolver is None else resolver,
            command_runner=runner,
        )

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
        self.assertEqual(revalidate.call_count, 3)
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
        self.assertEqual(revalidate.call_count, 2)
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
                [None, None],
            ),
            (
                "lease_drift",
                DockerRunner(self.snapshot, [None, None, created, created]),
                [None, None, OSError("changed source")],
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
        self.assertEqual(validation.call_count, 3)
        self.assertEqual(len(runner.compose_commands("create")), 1)
        self.assertFalse(runner.commands(("container", "start")))

    def test_actual_render_rejects_unmodeled_nested_behavior(self) -> None:
        def mutation(name):
            def transform(document_text):
                document = json.loads(document_text)
                service = document["services"]["runtime"]
                if name == "health_disable":
                    service["healthcheck"]["disable"] = True
                elif name == "network_alias":
                    network = next(iter(service["networks"]))
                    service["networks"][network] = {"aliases": ["platform-control"]}
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
            "network_alias",
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
