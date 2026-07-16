from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_safe_compose_driver import (
    APPROVED_ENVIRONMENT,
    APPROVED_SYSTEM_ROOT,
    COMPOSE,
    DOCKER,
    AuthorityResolver,
    _active_lease,
    _container_document,
)
from tests.test_runtime_snapshot import valid_authority
from tools.runtime_driver import (
    AccessNetworkIdentity,
    AccessNetworkIdentityError,
    AccessNetworkLabel,
    AccessNetworkMember,
    AccessNetworkMemberMismatch,
    AccessNetworkObservation,
    AccessNetworkState,
    AmbiguousNetworkOutcome,
    DriverValidationError,
    PlatformControlIdentity,
    RuntimeAccessAttachmentMissing,
    RuntimeAccessMemberIdentity,
    RuntimeAccessNetworkDriver,
)
from tools.safe_compose_driver import SafeComposeRuntimeDriver
from tools.runtime_snapshot import compile_launch_snapshot
from tools.runtime_supervisor.writer_guard import (
    SupervisorDockerWriterGuard,
    SupervisorWriterGuardError,
)
from tools.runtime_supervisor.daemon import SupervisorProcessLock

try:
    from tools.runtime_access_network import (
        AccessNetworkAction,
        compile_access_network_identity,
        compile_runtime_access_member,
        decide_access_network_preparation,
        decide_access_network_removal,
        expected_access_network_labels,
    )
except (ImportError, ModuleNotFoundError) as error:
    RUNTIME_ACCESS_NETWORK_IMPORT_ERROR = error
else:
    RUNTIME_ACCESS_NETWORK_IMPORT_ERROR = None


def access_identity() -> AccessNetworkIdentity:
    return compile_access_network_identity(
        compile_launch_snapshot(valid_authority())
    )


def platform_control_identity() -> PlatformControlIdentity:
    return PlatformControlIdentity(
        container_id="c" * 64,
        container_name="freqtrade-cn-platform-control",
        image_id="sha256:" + "d" * 64,
        compose_project="freqtrade-cn",
        compose_service="platform-control",
        identity_revision="platform-control-v1",
    )


def observation(
    *,
    members: tuple[AccessNetworkMember, ...] = (),
) -> AccessNetworkObservation:
    identity = access_identity()
    return AccessNetworkObservation(
        state=AccessNetworkState.PRESENT,
        network_id="e" * 64,
        observed_name=identity.network_name,
        observed_driver="bridge",
        observed_scope="local",
        observed_internal=identity.internal,
        observed_attachable=False,
        observed_ingress=False,
        observed_config_only=False,
        observed_labels=expected_access_network_labels(identity),
        members=members,
    )


class RuntimeAccessNetworkContractTests(unittest.TestCase):
    def test_module_imports_without_site_packages(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import tools.runtime_access_network; print('ok')",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "ok\n")

    def test_compiles_the_one_access_binding_without_io(self) -> None:
        snapshot = compile_launch_snapshot(valid_authority())
        identity = compile_access_network_identity(snapshot)

        self.assertEqual(identity.instance_id, snapshot.identity.instance_id)
        self.assertEqual(identity.network_name, snapshot.network_bindings[0].network_name)
        self.assertFalse(identity.internal)
        self.assertTrue(identity.requires_upstream_access)
        self.assertTrue(identity.requires_platform_control)
        member = compile_runtime_access_member(snapshot, "a" * 64)
        self.assertIsInstance(member, RuntimeAccessMemberIdentity)
        self.assertEqual(member.runtime_alias, snapshot.network_bindings[0].runtime_alias)
        self.assertEqual(member.container_id, "a" * 64)

    def test_missing_access_role_fails_closed(self) -> None:
        snapshot = compile_launch_snapshot(valid_authority())
        private = dataclasses.replace(
            snapshot.network_bindings[0],
            role="private",
        )
        with self.assertRaisesRegex(
            DriverValidationError,
            "^driver_validation_error$",
        ):
            dataclasses.replace(snapshot, network_bindings=(private,))

    def test_contract_values_are_frozen_and_reject_mapping_ingress(self) -> None:
        identity = access_identity()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.network_name = "other"
        for value in (
            identity,
            platform_control_identity(),
            AccessNetworkLabel("io.freqtrade.runtime-network.role", "access"),
            AccessNetworkMember(
                "f" * 64,
                "runtime-worker",
                "1" * 64,
                ("runtime-worker",),
                None,
            ),
            observation(),
        ):
            with self.subTest(value=type(value).__name__):
                self.assertIs(type(value).model_validate(value), value)
                with self.assertRaises(DriverValidationError):
                    type(value).model_validate(dataclasses.asdict(value))

    def test_network_protocol_exposes_only_bounded_operations(self) -> None:
        self.assertEqual(
            {
                name
                for name in RuntimeAccessNetworkDriver.__dict__
                if not name.startswith("_")
            },
            {
                "inspect_access_network",
                "ensure_access_network",
                "verify_created_access_network",
                "verify_active_access_network",
                "remove_access_network_if_empty",
            },
        )

    def test_two_instances_never_share_an_access_network(self) -> None:
        first = compile_launch_snapshot(valid_authority())
        second_instance = "paper-probe-2"
        network_digest = hashlib.sha256(second_instance.encode("utf-8")).hexdigest()
        first_identity = compile_access_network_identity(first)
        second_identity = dataclasses.replace(
            first_identity,
            instance_id=second_instance,
            network_name=f"runtime-{network_digest[:24]}-access",
        )
        self.assertNotEqual(
            first_identity.network_name,
            second_identity.network_name,
        )


@unittest.skipIf(
    RUNTIME_ACCESS_NETWORK_IMPORT_ERROR is not None,
    "runtime access network contract is missing",
)
class RuntimeAccessNetworkDecisionTests(unittest.TestCase):
    def test_absent_network_is_created_and_empty_network_is_removed(self) -> None:
        identity = access_identity()
        platform = platform_control_identity()
        self.assertIs(
            decide_access_network_preparation(
                identity,
                platform,
                AccessNetworkObservation.absent(),
                runtime=None,
            ),
            AccessNetworkAction.CREATE,
        )
        self.assertIs(
            decide_access_network_removal(identity, observation()),
            AccessNetworkAction.REMOVE,
        )

    def test_platform_control_is_connected_only_after_exact_network_validation(self) -> None:
        identity = access_identity()
        platform = platform_control_identity()
        self.assertIs(
            decide_access_network_preparation(
                identity,
                platform,
                observation(),
                runtime=None,
            ),
            AccessNetworkAction.CONNECT_PLATFORM_CONTROL,
        )
        ready = observation(
            members=(
                AccessNetworkMember(
                    platform.container_id,
                    platform.container_name,
                    "2" * 64,
                    ("platform-control",),
                    None,
                ),
            )
        )
        self.assertIs(
            decide_access_network_preparation(
                identity,
                platform,
                ready,
                runtime=None,
            ),
            AccessNetworkAction.READY,
        )

    def test_unknown_member_fails_closed_without_a_repair_decision(self) -> None:
        identity = access_identity()
        platform = platform_control_identity()
        observed = observation(
            members=(
                AccessNetworkMember(
                    "a" * 64,
                    "unknown",
                    "3" * 64,
                    None,
                    None,
                ),
                AccessNetworkMember(
                    platform.container_id,
                    platform.container_name,
                    "2" * 64,
                    ("platform-control",),
                    None,
                ),
            )
        )
        with self.assertRaisesRegex(
            AccessNetworkMemberMismatch,
            "^access_network_member_mismatch$",
        ):
            decide_access_network_preparation(
                identity,
                platform,
                observed,
                runtime=None,
            )
        with self.assertRaisesRegex(
            AccessNetworkMemberMismatch,
            "^access_network_member_mismatch$",
        ):
            decide_access_network_removal(identity, observed)

    def test_network_identity_drift_fails_before_member_decisions(self) -> None:
        identity = access_identity()
        platform = platform_control_identity()
        changed = dataclasses.replace(observation(), observed_internal=True)
        with self.assertRaisesRegex(
            AccessNetworkIdentityError,
            "^access_network_identity_mismatch$",
        ):
            decide_access_network_preparation(
                identity,
                platform,
                changed,
                runtime=None,
            )


class NetworkEngineRunner:
    def __init__(self, snapshot, platform) -> None:
        self.snapshot = snapshot
        self.platform = platform
        self.network_id = "e" * 64
        self.network = None
        self.containers = {
            platform.container_id: self._platform_document(),
        }
        self.configured: dict[str, str] = {}
        self.active: dict[str, dict[str, object]] = {}
        self.calls = []
        self.create_fault = None
        self.replace_created_id = None
        self.post_mutation_read_fault = None
        self.platform_inspect_fault_after = None
        self.platform_inspect_count = 0

    def _platform_document(self):
        return {
            "Id": self.platform.container_id,
            "Name": f"/{self.platform.container_name}",
            "Image": self.platform.image_id,
            "Config": {
                "Labels": {
                    "com.docker.compose.project": self.platform.compose_project,
                    "com.docker.compose.service": self.platform.compose_service,
                    "io.freqtrade.platform.identity-revision": (
                        self.platform.identity_revision
                    ),
                    "io.freqtrade.platform.role": "platform-control",
                }
            },
            "State": {"Status": "running", "ExitCode": 0},
            "NetworkSettings": {"Networks": {}},
        }

    def create_exact_network(self, identity):
        self.network = {
            "Id": self.network_id,
            "Name": identity.network_name,
            "Scope": "local",
            "Driver": "bridge",
            "Internal": identity.internal,
            "Attachable": False,
            "Ingress": False,
            "ConfigOnly": False,
            "ConfigFrom": {"Network": ""},
            "EnableIPv4": True,
            "EnableIPv6": False,
            "IPAM": {
                "Driver": "default",
                "Options": None,
                "Config": [
                    {"Subnet": "172.31.0.0/16", "Gateway": "172.31.0.1"}
                ],
            },
            "Options": {},
            "Labels": {
                label.name: label.value
                for label in expected_access_network_labels(identity)
            },
            "Containers": self.active,
        }

    def attach_platform(self, identity):
        self.configured[self.platform.container_id] = self.platform.container_name
        endpoint_id = "1" * 64
        self.active[self.platform.container_id] = {
            "Name": self.platform.container_name,
            "EndpointID": endpoint_id,
        }
        self.containers[self.platform.container_id]["NetworkSettings"]["Networks"][
            identity.network_name
        ] = {
            "NetworkID": self.network_id,
            "EndpointID": endpoint_id,
            "Aliases": ["platform-control"],
            "DNSNames": ["platform-control", self.platform.container_id[:12]],
        }

    def attach_runtime(self, identity, runtime, *, active):
        document = _container_document(self.snapshot, status="running" if active else "created")
        document["Id"] = runtime.container_id
        document["Name"] = f"/{runtime.container_name}"
        endpoint_id = "2" * 64 if active else ""
        document["NetworkSettings"]["Networks"] = {
            identity.network_name: {
                "NetworkID": self.network_id,
                "EndpointID": endpoint_id,
                "Aliases": [runtime.runtime_alias],
                "DNSNames": [runtime.runtime_alias, runtime.container_id[:12]],
            }
        }
        self.containers[runtime.container_id] = document
        self.configured[runtime.container_id] = runtime.container_name
        if active:
            self.active[runtime.container_id] = {
                "Name": runtime.container_name,
                "EndpointID": endpoint_id,
            }

    def add_unknown_stopped(self, identity):
        container_id = "b" * 64
        self.configured[container_id] = "unknown-runtime"
        self.containers[container_id] = {
            "Id": container_id,
            "Name": "/unknown-runtime",
            "Image": "sha256:" + "f" * 64,
            "Config": {"Labels": {}},
            "State": {"Status": "exited", "ExitCode": 0},
            "NetworkSettings": {
                "Networks": {
                    identity.network_name: {
                        "NetworkID": self.network_id,
                        "EndpointID": "",
                        "Aliases": ["unknown-runtime"],
                    }
                }
            },
        }

    def __call__(self, command, **kwargs):
        self.calls.append((tuple(command), kwargs))
        args = command[1:]
        if args[:2] == ["container", "inspect"]:
            if args[2] == self.platform.container_id:
                self.platform_inspect_count += 1
                if (
                    self.platform_inspect_fault_after is not None
                    and self.platform_inspect_count
                    >= self.platform_inspect_fault_after
                ):
                    raise OSError("lost platform-control inspection")
            document = self.containers.get(args[2])
            if document is None:
                return subprocess.CompletedProcess(command, 1, "", "missing")
            return subprocess.CompletedProcess(command, 0, json.dumps([document]), "")
        if args[:2] == ["network", "ls"]:
            if (
                self.post_mutation_read_fault is not None
                and any(
                    previous[1:3]
                    in (("network", "create"), ("network", "connect"), ("network", "rm"))
                    for previous, _kwargs in self.calls[:-1]
                )
            ):
                raise self.post_mutation_read_fault
            stdout = "" if self.network is None else f"{self.network_id}\n"
            return subprocess.CompletedProcess(command, 0, stdout, "")
        if args[:2] == ["network", "inspect"]:
            if self.network is None or args[2] != self.network_id:
                return subprocess.CompletedProcess(command, 1, "", "missing")
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps([self.network]),
                "",
            )
        if args[:2] == ["container", "ls"] and "network=" in " ".join(args):
            stdout = "".join(
                f"{container_id}\t{self.configured[container_id]}\n"
                for container_id in sorted(self.configured)
            )
            return subprocess.CompletedProcess(command, 0, stdout, "")
        if args[:2] == ["network", "create"]:
            if self.create_fault is not None:
                raise self.create_fault
            identity = access_identity()
            self.create_exact_network(identity)
            created_id = self.network_id
            if self.replace_created_id is not None:
                self.network_id = self.replace_created_id
                self.network["Id"] = self.replace_created_id
            return subprocess.CompletedProcess(command, 0, f"{created_id}\n", "")
        if args[:2] == ["network", "connect"]:
            self.attach_platform(access_identity())
            return subprocess.CompletedProcess(command, 0, "", "")
        if args[:2] == ["network", "rm"]:
            self.network = None
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected command: {command}")

    def mutations(self):
        return [
            command
            for command, _kwargs in self.calls
            if command[1:3]
            in (("network", "create"), ("network", "connect"), ("network", "rm"))
        ]


class SafeComposeAccessNetworkAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.authority = valid_authority()
        self.snapshot = compile_launch_snapshot(self.authority)
        self.access = compile_access_network_identity(self.snapshot)
        self.platform = platform_control_identity()
        self.lease = _active_lease(self.authority)
        self.resolver = AuthorityResolver(self.authority, self.lease)
        self.writer_authority = SupervisorProcessLock(
            Path(self.temporary.name) / "supervisor.lock"
        )
        self.writer_authority.acquire()
        self.addCleanup(self.writer_authority.release)
        self.writer_guard = SupervisorDockerWriterGuard()
        self.writer_guard.activate(self.writer_authority)

    def driver(self, runner):
        return SafeComposeRuntimeDriver(
            docker_executable=DOCKER,
            compose_executable=COMPOSE,
            environment=APPROVED_ENVIRONMENT,
            approved_docker_host=APPROVED_ENVIRONMENT["DOCKER_HOST"],
            approved_docker_context=APPROVED_ENVIRONMENT["DOCKER_CONTEXT"],
            approved_system_root=APPROVED_SYSTEM_ROOT,
            working_directory=Path(self.temporary.name),
            temporary_directory=Path(self.temporary.name),
            authority_resolver=self.resolver,
            platform_control_identity_provider=self.resolver,
            writer_guard=self.writer_guard,
            writer_authority=self.writer_authority,
            command_runner=runner,
        )

    def test_revoked_guard_blocks_network_mutations_before_runner(self) -> None:
        runner = mock.Mock()
        driver = self.driver(runner)
        self.writer_guard.revoke(self.writer_authority)

        for operation in (
            lambda: driver.ensure_access_network(self.access, self.platform),
            lambda: driver.remove_access_network_if_empty(self.access),
        ):
            with self.subTest(operation=operation), self.assertRaises(
                SupervisorWriterGuardError
            ):
                operation()

        self.assertEqual(runner.mock_calls, [])

    def test_revocation_after_read_only_inspection_blocks_network_create(self) -> None:
        engine = NetworkEngineRunner(self.snapshot, self.platform)

        def runner(command, **kwargs):
            result = engine(command, **kwargs)
            if command[1:3] == ["network", "ls"]:
                self.writer_guard.revoke(self.writer_authority)
            return result

        with self.assertRaises(SupervisorWriterGuardError):
            self.driver(runner).ensure_access_network(self.access, self.platform)

        self.assertEqual(engine.mutations(), [])

    def test_ensure_creates_then_connects_only_exact_platform_control(self) -> None:
        runner = NetworkEngineRunner(self.snapshot, self.platform)
        observed = self.driver(runner).ensure_access_network(
            self.access,
            self.platform,
        )

        self.assertEqual(
            tuple(member.container_id for member in observed.members),
            (self.platform.container_id,),
        )
        mutations = runner.mutations()
        self.assertEqual(len(mutations), 2)
        create, connect = mutations
        self.assertEqual(create[:5], (str(DOCKER), "network", "create", "--driver", "bridge"))
        self.assertNotIn("--attachable", create)
        self.assertNotIn("--internal", create)
        self.assertEqual(
            connect,
            (
                str(DOCKER),
                "network",
                "connect",
                "--alias",
                "platform-control",
                runner.network_id,
                self.platform.container_id,
            ),
        )
        self.assertTrue(
            all(kwargs["env"] == APPROVED_ENVIRONMENT for _command, kwargs in runner.calls)
        )

    def test_stopped_unknown_member_blocks_every_network_mutation(self) -> None:
        runner = NetworkEngineRunner(self.snapshot, self.platform)
        runner.create_exact_network(self.access)
        runner.attach_platform(self.access)
        runner.add_unknown_stopped(self.access)
        with self.assertRaisesRegex(
            AccessNetworkMemberMismatch,
            "^access_network_member_mismatch$",
        ):
            self.driver(runner).ensure_access_network(self.access, self.platform)
        self.assertEqual(runner.mutations(), [])

    def test_restart_reconciliation_connects_only_platform_control(self) -> None:
        runner = NetworkEngineRunner(self.snapshot, self.platform)
        runner.create_exact_network(self.access)
        runtime = compile_runtime_access_member(self.snapshot, "a" * 64)
        runner.attach_runtime(self.access, runtime, active=True)

        observed = self.driver(runner).ensure_access_network(
            self.access,
            self.platform,
            runtime,
        )

        self.assertEqual(
            {member.container_id for member in observed.members},
            {self.platform.container_id, runtime.container_id},
        )
        self.assertEqual(
            runner.mutations(),
            [
                (
                    str(DOCKER),
                    "network",
                    "connect",
                    "--alias",
                    "platform-control",
                    runner.network_id,
                    self.platform.container_id,
                )
            ],
        )

    def test_restart_reconciliation_never_mutates_for_stale_runtime(self) -> None:
        runner = NetworkEngineRunner(self.snapshot, self.platform)
        runner.create_exact_network(self.access)
        stale = compile_runtime_access_member(self.snapshot, "a" * 64)
        runner.attach_runtime(self.access, stale, active=True)
        current = compile_runtime_access_member(self.snapshot, "b" * 64)
        runner.attach_runtime(self.access, current, active=True)

        with self.assertRaisesRegex(
            AccessNetworkMemberMismatch,
            "^access_network_member_mismatch$",
        ):
            self.driver(runner).ensure_access_network(
                self.access,
                self.platform,
                current,
            )

        self.assertEqual(runner.mutations(), [])

    def test_created_and_active_runtime_require_exact_attempt_alias(self) -> None:
        runner = NetworkEngineRunner(self.snapshot, self.platform)
        runner.create_exact_network(self.access)
        runner.attach_platform(self.access)
        runtime = compile_runtime_access_member(self.snapshot, "a" * 64)
        runner.attach_runtime(self.access, runtime, active=False)
        created = self.driver(runner).verify_created_access_network(
            self.access,
            self.platform,
            runtime,
        )
        self.assertIsNone(
            next(
                member.endpoint_id
                for member in created.members
                if member.container_id == runtime.container_id
            )
        )

        runner.active[runtime.container_id] = {
            "Name": runtime.container_name,
            "EndpointID": "2" * 64,
        }
        runner.containers[runtime.container_id]["NetworkSettings"]["Networks"][
            self.access.network_name
        ]["EndpointID"] = "2" * 64
        active = self.driver(runner).verify_active_access_network(
            self.access,
            self.platform,
            runtime,
        )
        self.assertTrue(all(member.endpoint_id is not None for member in active.members))

        runner.containers[runtime.container_id]["NetworkSettings"]["Networks"][
            self.access.network_name
        ]["Aliases"] = [runtime.container_name]
        with self.assertRaisesRegex(
            AccessNetworkMemberMismatch,
            "^access_network_member_mismatch$",
        ):
            self.driver(runner).verify_active_access_network(
                self.access,
                self.platform,
                runtime,
            )

    def test_created_gate_requires_an_active_platform_control_endpoint(self) -> None:
        runner = NetworkEngineRunner(self.snapshot, self.platform)
        runner.create_exact_network(self.access)
        runner.attach_platform(self.access)
        runtime = compile_runtime_access_member(self.snapshot, "a" * 64)
        runner.attach_runtime(self.access, runtime, active=False)
        runner.active.pop(self.platform.container_id)
        platform_network = runner.containers[self.platform.container_id][
            "NetworkSettings"
        ]["Networks"][self.access.network_name]
        platform_network["EndpointID"] = ""

        with self.assertRaisesRegex(
            RuntimeAccessAttachmentMissing,
            "^runtime_access_attachment_missing$",
        ):
            self.driver(runner).verify_created_access_network(
                self.access,
                self.platform,
                runtime,
            )

    def test_remove_uses_full_id_only_when_configured_and_active_sets_are_empty(self) -> None:
        runner = NetworkEngineRunner(self.snapshot, self.platform)
        runner.create_exact_network(self.access)
        removed = self.driver(runner).remove_access_network_if_empty(self.access)
        self.assertIs(removed.state, AccessNetworkState.ABSENT)
        self.assertEqual(
            runner.mutations(),
            [(str(DOCKER), "network", "rm", runner.network_id)],
        )

    def test_network_mutation_timeout_is_ambiguous_and_not_retried(self) -> None:
        runner = NetworkEngineRunner(self.snapshot, self.platform)
        runner.create_fault = subprocess.TimeoutExpired([str(DOCKER)], 1)
        with self.assertRaisesRegex(
            AmbiguousNetworkOutcome,
            "^ambiguous_network_outcome$",
        ):
            self.driver(runner).ensure_access_network(self.access, self.platform)
        creates = [
            command
            for command, _kwargs in runner.calls
            if command[1:3] == ("network", "create")
        ]
        self.assertEqual(len(creates), 1)

    def test_post_create_same_name_network_must_keep_the_returned_full_id(self) -> None:
        runner = NetworkEngineRunner(self.snapshot, self.platform)
        runner.replace_created_id = "f" * 64
        with self.assertRaisesRegex(
            AmbiguousNetworkOutcome,
            "^ambiguous_network_outcome$",
        ):
            self.driver(runner).ensure_access_network(self.access, self.platform)
        self.assertEqual(len(runner.mutations()), 1)
        self.assertEqual(runner.mutations()[0][1:3], ("network", "create"))

    def test_post_mutation_observation_failure_is_always_ambiguous(self) -> None:
        create_runner = NetworkEngineRunner(self.snapshot, self.platform)
        create_runner.post_mutation_read_fault = OSError("lost")
        with self.assertRaisesRegex(
            AmbiguousNetworkOutcome,
            "^ambiguous_network_outcome$",
        ):
            self.driver(create_runner).ensure_access_network(
                self.access,
                self.platform,
            )

        remove_runner = NetworkEngineRunner(self.snapshot, self.platform)
        remove_runner.create_exact_network(self.access)
        remove_runner.post_mutation_read_fault = OSError("lost")
        with self.assertRaisesRegex(
            AmbiguousNetworkOutcome,
            "^ambiguous_network_outcome$",
        ):
            self.driver(remove_runner).remove_access_network_if_empty(self.access)
        self.assertEqual(
            len(
                [
                    command
                    for command in remove_runner.mutations()
                    if command[1:3] == ("network", "rm")
                ]
            ),
            1,
        )

        platform_runner = NetworkEngineRunner(self.snapshot, self.platform)
        platform_runner.platform_inspect_fault_after = 5
        with self.assertRaisesRegex(
            AmbiguousNetworkOutcome,
            "^ambiguous_network_outcome$",
        ):
            self.driver(platform_runner).ensure_access_network(
                self.access,
                self.platform,
            )
        self.assertEqual(
            [command[1:3] for command in platform_runner.mutations()],
            [("network", "create")],
        )


if __name__ == "__main__":
    unittest.main()
