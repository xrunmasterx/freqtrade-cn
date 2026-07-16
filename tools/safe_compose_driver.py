from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Protocol

from tools.compose_runtime import (
    ComposeActionUncertain,
    _run_validated_snapshot_launch,
)
from tools.runtime_driver import (
    AccessNetworkIdentity,
    AccessNetworkIdentityError,
    AccessNetworkLabel,
    AccessNetworkMember,
    AccessNetworkMemberMismatch,
    AccessNetworkObservation,
    AccessNetworkState,
    AmbiguousDriverOutcome,
    AmbiguousNetworkOutcome,
    DriverHealth,
    DriverIdentity,
    DriverIdentityMismatch,
    DriverInspection,
    DriverObjectOccupied,
    DriverPolicyError,
    DriverState,
    DriverTransportError,
    DriverValidationError,
    HealthObservation,
    HealthProfile,
    LaunchSnapshot,
    NetworkTransportError,
    PlatformControlIdentity,
    PlatformControlIdentityProvider,
    PlatformControlIdentityMismatch,
    RuntimeAccessAttachmentMissing,
    RuntimeAccessMemberIdentity,
    RuntimeAccessNetworkDriver,
)
from tools.runtime_preparation_lease import ActiveLaunchAuthorityLease
from tools.runtime_snapshot import (
    LaunchCompilationAuthority,
    RenderedContainerPolicy,
    RenderedEnvironmentEntry,
    RenderedLabel,
    RenderedMount,
    RenderedMountKind,
    validate_launch_snapshot,
    validate_rendered_snapshot,
)
from tools.runtime_access_network import (
    AccessNetworkAction,
    decide_access_network_preparation,
    decide_access_network_removal,
    decide_active_access_network,
    compile_access_network_identity,
    compile_runtime_access_member,
    expected_access_network_labels,
)


_SERVICE_NAME = "runtime"
_INSPECT_TIMEOUT_SECONDS = 15
_RENDER_TIMEOUT_SECONDS = 30
_CREATE_TIMEOUT_SECONDS = 60
_START_TIMEOUT_SECONDS = 60
_STOP_TIMEOUT_SECONDS = 60
_NETWORK_MUTATION_TIMEOUT_SECONDS = 60
_MAX_HEALTH_START_PERIOD_SECONDS = 300
_MAX_HEALTH_INTERVAL_SECONDS = 300
_MAX_HEALTH_TIMEOUT_SECONDS = 60
_MAX_HEALTH_RETRIES = 20
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
_NETWORK_ID = re.compile(r"[0-9a-f]{64}")
_NETWORK_OBSERVATION_ERRORS = (
    AccessNetworkIdentityError,
    AccessNetworkMemberMismatch,
    DriverValidationError,
    NetworkTransportError,
    PlatformControlIdentityMismatch,
)
_ALLOWED_ENVIRONMENT_NAMES = frozenset({"DOCKER_CONTEXT", "DOCKER_HOST", "SYSTEMROOT"})
_FORBIDDEN_ENVIRONMENT_NAMES = frozenset(
    {
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "DOCKER_TLS_VERIFY",
        "HOME",
        "PATH",
        "USERPROFILE",
    }
)
_FORBIDDEN_PROBE_EXECUTABLES = frozenset({"bash", "cmd", "powershell", "pwsh", "sh"})
_ALLOWED_PROBE_EXECUTABLES = frozenset({"curl"})
_APPROVED_PROBE_ARGV_BY_ID = {
    "freqtrade-ping-v1": (
        "curl",
        "-fsS",
        "http://127.0.0.1:8080/api/v1/ping",
    )
}
_ALLOWED_SERVICE_KEYS = frozenset(
    {
        "cap_drop",
        "command",
        "container_name",
        "cpus",
        "entrypoint",
        "environment",
        "expose",
        "healthcheck",
        "image",
        "labels",
        "mem_limit",
        "networks",
        "pids_limit",
        "privileged",
        "pull_policy",
        "read_only",
        "restart",
        "security_opt",
        "user",
        "volumes",
        "working_dir",
    }
)
_IDENTITY_LABELS = {
    "attempt": "io.freqtrade.runtime.attempt-id",
    "container": "io.freqtrade.runtime.container-name",
    "image": "io.freqtrade.runtime.image-id",
    "instance": "io.freqtrade.runtime.instance-id",
    "launch": "io.freqtrade.runtime.launch-authority-digest",
    "project": "io.freqtrade.runtime.project-name",
    "spec": "io.freqtrade.runtime.runtime-spec-digest",
    "state": "io.freqtrade.runtime.state-allocation-id",
}
_PLATFORM_CONTROL_LABELS = {
    "io.freqtrade.platform.identity-revision": "platform-control-v1",
    "io.freqtrade.platform.role": "platform-control",
}


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


class DriverAuthorityResolver(Protocol):
    def resolve_active_launch(
        self,
        identity: DriverIdentity,
        launch_authority_digest: str,
    ) -> ActiveLaunchAuthorityLease: ...

    def resolve_health_profile(
        self,
        identity: DriverIdentity,
        profile_id: str,
    ) -> HealthProfile: ...

@dataclass(frozen=True, slots=True)
class _EngineObservation:
    inspection: DriverInspection
    launch_authority_digest: str | None
    compose_project: str | None
    compose_service: str | None


def _labels(snapshot: LaunchSnapshot) -> tuple[RenderedLabel, ...]:
    values = {
        _IDENTITY_LABELS["attempt"]: snapshot.identity.attempt_id,
        _IDENTITY_LABELS["container"]: snapshot.identity.container_name,
        _IDENTITY_LABELS["image"]: snapshot.identity.image_id,
        _IDENTITY_LABELS["instance"]: snapshot.identity.instance_id,
        _IDENTITY_LABELS["launch"]: snapshot.launch_authority_digest,
        _IDENTITY_LABELS["project"]: snapshot.identity.project_name,
        _IDENTITY_LABELS["spec"]: snapshot.identity.runtime_spec_digest,
        _IDENTITY_LABELS["state"]: snapshot.identity.state_allocation_id,
    }
    return tuple(RenderedLabel(name, values[name]) for name in sorted(values))


def _render_snapshot_policy(
    snapshot: LaunchSnapshot,
    authority: LaunchCompilationAuthority,
) -> RenderedContainerPolicy:
    material_mounts = tuple(
        RenderedMount(
            RenderedMountKind.MATERIAL,
            policy.role,
            mount.source,
            mount.target,
            True,
        )
        for policy, mount in zip(
            authority.policies.material_mounts,
            snapshot.read_only_mounts,
            strict=True,
        )
    )
    state_mount = RenderedMount(
        RenderedMountKind.STATE,
        authority.policies.state_mount.role,
        snapshot.state_mount.source,
        snapshot.state_mount.target,
        False,
    )
    secret_mounts = tuple(
        RenderedMount(
            RenderedMountKind.SECRET,
            policy.secret_class,
            mount.source,
            mount.target,
            True,
        )
        for policy, mount in zip(
            authority.policies.secret_mounts,
            snapshot.secret_mounts,
            strict=True,
        )
    )
    environment = tuple(
        RenderedEnvironmentEntry(entry.name, entry.value)
        for entry in snapshot.non_secret_environment
    ) + tuple(
        RenderedEnvironmentEntry(binding.name, str(binding.target))
        for binding in snapshot.secret_path_environment_bindings
    )
    return RenderedContainerPolicy(
        identity=snapshot.identity,
        image_id=snapshot.identity.image_id,
        argv=snapshot.argv,
        working_directory=PurePosixPath(snapshot.working_directory),
        environment=environment,
        mounts=(*material_mounts, state_mount, *secret_mounts),
        runtime_user=snapshot.runtime_user,
        internal_ports=snapshot.internal_ports,
        health_profile=snapshot.health_profile,
        resource_limits=snapshot.resource_limits,
        network_names=snapshot.identity.network_names,
        restart="no",
        network_mode=None,
        pid_mode=None,
        ipc_mode=None,
        privileged=False,
        devices=(),
        cap_add=(),
        cap_drop=("ALL",),
        security_options=("no-new-privileges:true",),
        read_only_root_filesystem=True,
        published_ports=(),
        labels=_labels(snapshot),
    )


def _compose_document(
    rendered: RenderedContainerPolicy,
    snapshot: LaunchSnapshot,
) -> str:
    bindings = {binding.network_name: binding for binding in snapshot.network_bindings}
    if tuple(sorted(bindings)) != rendered.network_names:
        raise DriverPolicyError()
    service = {
        "cap_drop": list(rendered.cap_drop),
        "command": [],
        "container_name": rendered.identity.container_name,
        "cpus": f"{Decimal(rendered.resource_limits.cpu_millis) / 1000:.3f}",
        "entrypoint": list(rendered.argv),
        "environment": {entry.name: entry.value for entry in rendered.environment},
        "expose": [str(port) for port in rendered.internal_ports],
        "healthcheck": {
            "interval": f"{rendered.health_profile.interval_seconds}s",
            "retries": rendered.health_profile.retries,
            "start_period": f"{rendered.health_profile.start_period_seconds}s",
            "test": ["CMD", *rendered.health_profile.probe_argv],
            "timeout": f"{rendered.health_profile.timeout_seconds}s",
        },
        "image": rendered.image_id,
        "labels": {label.name: label.value for label in rendered.labels},
        "mem_limit": rendered.resource_limits.memory_bytes,
        "networks": {
            name: {"aliases": [bindings[name].runtime_alias]}
            for name in rendered.network_names
        },
        "pids_limit": rendered.resource_limits.pids_limit,
        "privileged": False,
        "pull_policy": "never",
        "read_only": rendered.read_only_root_filesystem,
        "restart": rendered.restart,
        "security_opt": list(rendered.security_options),
        "user": f"{rendered.runtime_user.uid}:{rendered.runtime_user.gid}",
        "volumes": [
            {
                "bind": {"create_host_path": False},
                "read_only": mount.read_only,
                "source": str(mount.source),
                "target": str(mount.target),
                "type": "bind",
            }
            for mount in rendered.mounts
        ],
        "working_dir": str(rendered.working_directory),
    }
    document = {
        "networks": {
            name: {"external": True, "name": name} for name in rendered.network_names
        },
        "services": {_SERVICE_NAME: service},
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"


def _seconds(value: object) -> int:
    if type(value) is not str or not value.endswith("s"):
        raise DriverPolicyError()
    number = value[:-1]
    if not number.isdecimal():
        raise DriverPolicyError()
    return int(number)


def _parse_actual_render(
    path: Path,
    snapshot: LaunchSnapshot,
    authority: LaunchCompilationAuthority,
) -> RenderedContainerPolicy:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, RecursionError):
        raise DriverPolicyError() from None
    if (
        type(document) is not dict
        or set(document) - {"name", "networks", "services"}
        or type(document.get("services")) is not dict
        or type(document.get("networks")) is not dict
    ):
        raise DriverPolicyError()
    services = document["services"]
    if set(services) != {_SERVICE_NAME} or type(services[_SERVICE_NAME]) is not dict:
        raise DriverPolicyError()
    service = services[_SERVICE_NAME]
    if (
        set(service) - _ALLOWED_SERVICE_KEYS
        or service.get("container_name") != snapshot.identity.container_name
    ):
        raise DriverPolicyError()
    if service.get("command") != []:
        raise DriverPolicyError()

    expected = _render_snapshot_policy(snapshot, authority)
    actual_network_definitions = document["networks"]
    if set(actual_network_definitions) != set(expected.network_names):
        raise DriverPolicyError()
    for name in expected.network_names:
        definition = actual_network_definitions[name]
        if (
            type(definition) is not dict
            or set(definition)
            not in ({"external", "name"}, {"external", "ipam", "name"})
            or definition.get("external") is not True
            or definition.get("name") != name
            or ("ipam" in definition and definition["ipam"] != {})
        ):
            raise DriverPolicyError()
    expected_mounts = {str(mount.target): mount for mount in expected.mounts}
    raw_mounts = service.get("volumes")
    if type(raw_mounts) is not list:
        raise DriverPolicyError()
    actual_mounts = []
    for raw_mount in raw_mounts:
        if type(raw_mount) is not dict or raw_mount.get("type") != "bind":
            raise DriverPolicyError()
        source = raw_mount.get("source")
        target = raw_mount.get("target")
        expected_mount = expected_mounts.get(target)
        bind = raw_mount.get("bind")
        expected_keys = {"bind", "source", "target", "type"}
        if expected_mount is not None and expected_mount.read_only:
            expected_keys.add("read_only")
        if (
            expected_mount is None
            or set(raw_mount) not in (expected_keys, expected_keys | {"read_only"})
            or raw_mount.get("read_only", False) is not expected_mount.read_only
            or type(source) is not str
            or type(bind) is not dict
            or set(bind) != {"create_host_path"}
            or bind.get("create_host_path") is not False
        ):
            raise DriverPolicyError()
        actual_mounts.append(
            RenderedMount(
                expected_mount.kind,
                expected_mount.role,
                Path(source),
                PurePosixPath(target),
                raw_mount.get("read_only", False),
            )
        )

    environment = service.get("environment")
    labels = service.get("labels")
    health = service.get("healthcheck")
    networks = service.get("networks")
    if (
        type(environment) is not dict
        or type(labels) is not dict
        or type(health) is not dict
        or type(networks) is not dict
    ):
        raise DriverPolicyError()
    expected_network_attachments = {
        binding.network_name: {"aliases": [binding.runtime_alias]}
        for binding in snapshot.network_bindings
    }
    if (
        set(health) != {"interval", "retries", "start_period", "test", "timeout"}
        or networks != expected_network_attachments
        or ("name" in document and document["name"] != snapshot.identity.project_name)
    ):
        raise DriverPolicyError()
    if set(environment) != {entry.name for entry in expected.environment} or set(
        labels
    ) != {label.name for label in expected.labels}:
        raise DriverPolicyError()
    test = health.get("test")
    if type(test) is not list or not test or test[0] != "CMD":
        raise DriverPolicyError()
    try:
        cpu_millis = int(Decimal(str(service.get("cpus"))) * 1000)
    except (InvalidOperation, ValueError):
        raise DriverPolicyError() from None
    memory_bytes = service.get("mem_limit")
    if type(memory_bytes) is str:
        if not memory_bytes.isascii() or not memory_bytes.isdecimal():
            raise DriverPolicyError()
        memory_bytes = int(memory_bytes)
    if type(memory_bytes) is not int or memory_bytes <= 0:
        raise DriverPolicyError()

    rendered = RenderedContainerPolicy(
        identity=snapshot.identity,
        image_id=service.get("image"),
        argv=tuple(service.get("entrypoint", ())),
        working_directory=PurePosixPath(service.get("working_dir", "")),
        environment=tuple(
            RenderedEnvironmentEntry(entry.name, environment.get(entry.name))
            for entry in expected.environment
        ),
        mounts=tuple(actual_mounts),
        runtime_user=snapshot.runtime_user.__class__(
            *[int(value) for value in service.get("user", ":").split(":")],
            snapshot.runtime_user.home,
        ),
        internal_ports=tuple(sorted(int(port) for port in service.get("expose", ()))),
        health_profile=HealthProfile(
            profile_id=snapshot.health_profile.profile_id,
            probe_argv=tuple(test[1:]),
            start_period_seconds=_seconds(health.get("start_period")),
            interval_seconds=_seconds(health.get("interval")),
            timeout_seconds=_seconds(health.get("timeout")),
            retries=health.get("retries"),
        ),
        resource_limits=snapshot.resource_limits.__class__(
            cpu_millis=cpu_millis,
            memory_bytes=memory_bytes,
            pids_limit=service.get("pids_limit"),
        ),
        network_names=tuple(sorted(networks)),
        restart=service.get("restart"),
        network_mode=service.get("network_mode"),
        pid_mode=service.get("pid"),
        ipc_mode=service.get("ipc"),
        privileged=service.get("privileged", False),
        devices=tuple(service.get("devices", ())),
        cap_add=tuple(service.get("cap_add", ())),
        cap_drop=tuple(service.get("cap_drop", ())),
        security_options=tuple(service.get("security_opt", ())),
        read_only_root_filesystem=service.get("read_only", False),
        published_ports=tuple(service.get("ports", ())),
        labels=tuple(
            RenderedLabel(name, labels[name])
            for name in sorted(labels)
            if name.startswith("io.freqtrade.runtime.")
        ),
    )
    if service.get("pull_policy") != "never":
        raise DriverPolicyError()
    return rendered


class SafePlatformControlIdentityProvider(PlatformControlIdentityProvider):
    def __init__(
        self,
        *,
        docker_executable: Path,
        environment: Mapping[str, str],
        approved_docker_host: str,
        approved_docker_context: str,
        approved_system_root: str | None,
        working_directory: Path,
        expected_image_id: str,
        command_runner: ProcessRunner = subprocess.run,
    ) -> None:
        self._docker_executable = docker_executable
        self._environment = dict(environment)
        self._approved_docker_host = approved_docker_host
        self._approved_docker_context = approved_docker_context
        self._approved_system_root = approved_system_root
        self._working_directory = working_directory
        self._expected_image_id = expected_image_id
        self._command_runner = command_runner

    def resolve_platform_control_identity(self) -> PlatformControlIdentity:
        self._validate_execution_context()
        listed = self._run_read_only(
            (
                str(self._docker_executable),
                "container",
                "ls",
                "--all",
                "--no-trunc",
                "--filter",
                "name=^/freqtrade-cn-platform-control$",
                "--format",
                "{{.ID}}",
            )
        )
        identifiers = tuple(line for line in listed.stdout.splitlines() if line)
        if len(identifiers) != 1 or _CONTAINER_ID.fullmatch(identifiers[0]) is None:
            raise PlatformControlIdentityMismatch()
        container_id = identifiers[0]
        inspected = self._run_read_only(
            (
                str(self._docker_executable),
                "container",
                "inspect",
                container_id,
            )
        )
        try:
            payload = json.loads(inspected.stdout)
            if (
                type(payload) is not list
                or len(payload) != 1
                or type(payload[0]) is not dict
            ):
                raise ValueError
            document = payload[0]
            config = document.get("Config")
            labels = config.get("Labels") if type(config) is dict else None
        except (TypeError, ValueError, json.JSONDecodeError):
            raise NetworkTransportError() from None
        if (
            document.get("Id") != container_id
            or document.get("Name", "").removeprefix("/")
            != "freqtrade-cn-platform-control"
            or document.get("Image") != self._expected_image_id
            or type(labels) is not dict
            or labels.get("com.docker.compose.project") != "freqtrade-cn"
            or labels.get("com.docker.compose.service") != "platform-control"
            or labels.get("io.freqtrade.platform.role")
            != _PLATFORM_CONTROL_LABELS["io.freqtrade.platform.role"]
            or labels.get("io.freqtrade.platform.identity-revision")
            != _PLATFORM_CONTROL_LABELS["io.freqtrade.platform.identity-revision"]
        ):
            raise PlatformControlIdentityMismatch()
        return PlatformControlIdentity(
            container_id=container_id,
            container_name="freqtrade-cn-platform-control",
            image_id=self._expected_image_id,
            compose_project="freqtrade-cn",
            compose_service="platform-control",
            identity_revision="platform-control-v1",
        )

    def _validate_execution_context(self) -> None:
        if (
            type(self._docker_executable) is not type(Path())
            or not self._docker_executable.is_absolute()
            or ".." in self._docker_executable.parts
            or type(self._working_directory) is not type(Path())
            or not self._working_directory.is_absolute()
            or not self._working_directory.is_dir()
            or self._working_directory.is_symlink()
            or type(self._environment) is not dict
            or any(
                type(name) is not str or type(value) is not str or not value
                for name, value in self._environment.items()
            )
        ):
            raise DriverPolicyError()
        folded = {str(name).casefold(): name for name in self._environment}
        if (
            len(folded) != len(self._environment)
            or any(
                name.casefold() in folded for name in _FORBIDDEN_ENVIRONMENT_NAMES
            )
            or any(
                name.upper() not in _ALLOWED_ENVIRONMENT_NAMES
                for name in self._environment
            )
            or self._approved_docker_host
            not in ("npipe:////./pipe/docker_engine", "unix:///var/run/docker.sock")
            or self._environment.get("DOCKER_HOST") != self._approved_docker_host
            or self._environment.get("DOCKER_CONTEXT")
            != self._approved_docker_context
            or self._environment.get("SYSTEMROOT") != self._approved_system_root
        ):
            raise DriverPolicyError()

    def _run_read_only(
        self,
        command: tuple[str, ...],
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = self._command_runner(
                list(command),
                cwd=self._working_directory,
                env=self._environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=_INSPECT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise NetworkTransportError() from None
        if completed.returncode != 0:
            raise NetworkTransportError()
        return completed


class SafeComposeRuntimeDriver:
    def __init__(
        self,
        *,
        docker_executable: Path,
        compose_executable: Path,
        environment: Mapping[str, str],
        approved_docker_host: str,
        approved_docker_context: str,
        approved_system_root: str | None,
        working_directory: Path,
        temporary_directory: Path,
        authority_resolver: DriverAuthorityResolver,
        platform_control_identity_provider: PlatformControlIdentityProvider,
        access_network_driver: RuntimeAccessNetworkDriver | None = None,
        command_runner: ProcessRunner = subprocess.run,
    ) -> None:
        self._docker_executable = docker_executable
        self._compose_executable = compose_executable
        self._environment = dict(environment)
        self._approved_docker_host = approved_docker_host
        self._approved_docker_context = approved_docker_context
        self._approved_system_root = approved_system_root
        self._working_directory = working_directory
        self._temporary_directory = temporary_directory
        self._authority_resolver = authority_resolver
        self._platform_control_identity_provider = (
            platform_control_identity_provider
        )
        self._access_network_driver = (
            self if access_network_driver is None else access_network_driver
        )
        self._command_runner = command_runner

    def inspect_access_network(
        self,
        identity: AccessNetworkIdentity,
        platform_control: PlatformControlIdentity,
        runtime: RuntimeAccessMemberIdentity | None,
    ) -> AccessNetworkObservation:
        if (
            type(identity) is not AccessNetworkIdentity
            or type(platform_control) is not PlatformControlIdentity
            or (runtime is not None and type(runtime) is not RuntimeAccessMemberIdentity)
        ):
            raise DriverValidationError()
        self._validate_docker_execution_context()
        self._inspect_platform_control(platform_control)
        if runtime is not None:
            self._inspect_runtime_member(runtime)
        return self._inspect_access_network(identity, platform_control, runtime)

    def ensure_access_network(
        self,
        identity: AccessNetworkIdentity,
        platform_control: PlatformControlIdentity,
        runtime: RuntimeAccessMemberIdentity | None = None,
    ) -> AccessNetworkObservation:
        if runtime is not None and type(runtime) is not RuntimeAccessMemberIdentity:
            raise DriverValidationError()
        created = False
        connected = False
        created_network_id: str | None = None
        for _step in range(3):
            try:
                observed = self.inspect_access_network(
                    identity,
                    platform_control,
                    runtime,
                )
            except _NETWORK_OBSERVATION_ERRORS:
                if created or connected:
                    raise AmbiguousNetworkOutcome() from None
                raise
            if (
                created_network_id is not None
                and observed.network_id != created_network_id
            ):
                raise AmbiguousNetworkOutcome()
            action = decide_access_network_preparation(
                identity,
                platform_control,
                observed,
                runtime,
            )
            if action is AccessNetworkAction.READY:
                return observed
            if action is AccessNetworkAction.CREATE:
                if created:
                    raise AmbiguousNetworkOutcome()
                try:
                    final = self.inspect_access_network(
                        identity,
                        platform_control,
                        runtime,
                    )
                except _NETWORK_OBSERVATION_ERRORS:
                    if created or connected:
                        raise AmbiguousNetworkOutcome() from None
                    raise
                if final.state is not AccessNetworkState.ABSENT:
                    raise AmbiguousNetworkOutcome()
                command = [
                    str(self._docker_executable),
                    "network",
                    "create",
                    "--driver",
                    "bridge",
                    "--scope",
                    "local",
                ]
                if identity.internal:
                    command.append("--internal")
                for label in expected_access_network_labels(identity):
                    command.extend(("--label", f"{label.name}={label.value}"))
                command.append(identity.network_name)
                completed = self._run_network_mutation(tuple(command))
                if (
                    completed.returncode != 0
                    or _NETWORK_ID.fullmatch(completed.stdout.strip()) is None
                ):
                    raise AmbiguousNetworkOutcome()
                created_network_id = completed.stdout.strip()
                created = True
                continue
            if action is AccessNetworkAction.CONNECT_PLATFORM_CONTROL:
                if connected or observed.network_id is None:
                    raise AmbiguousNetworkOutcome()
                try:
                    final = self.inspect_access_network(
                        identity,
                        platform_control,
                        runtime,
                    )
                except _NETWORK_OBSERVATION_ERRORS:
                    if created or connected:
                        raise AmbiguousNetworkOutcome() from None
                    raise
                if (
                    final.network_id != observed.network_id
                    or decide_access_network_preparation(
                        identity,
                        platform_control,
                        final,
                        runtime,
                    )
                    is not AccessNetworkAction.CONNECT_PLATFORM_CONTROL
                ):
                    raise AmbiguousNetworkOutcome()
                try:
                    self._inspect_platform_control(platform_control)
                except _NETWORK_OBSERVATION_ERRORS:
                    if created or connected:
                        raise AmbiguousNetworkOutcome() from None
                    raise
                completed = self._run_network_mutation(
                    (
                        str(self._docker_executable),
                        "network",
                        "connect",
                        "--alias",
                        "platform-control",
                        observed.network_id,
                        platform_control.container_id,
                    )
                )
                if completed.returncode != 0:
                    raise AmbiguousNetworkOutcome()
                connected = True
                continue
            raise AmbiguousNetworkOutcome()
        raise AmbiguousNetworkOutcome()

    def verify_created_access_network(
        self,
        identity: AccessNetworkIdentity,
        platform_control: PlatformControlIdentity,
        runtime: RuntimeAccessMemberIdentity,
    ) -> AccessNetworkObservation:
        observed = self.inspect_access_network(identity, platform_control, runtime)
        if (
            decide_active_access_network(
                identity,
                platform_control,
                runtime,
                observed,
            )
            is not AccessNetworkAction.READY
        ):
            raise RuntimeAccessAttachmentMissing()
        platform_member = next(
            member
            for member in observed.members
            if member.container_id == platform_control.container_id
        )
        if platform_member.endpoint_id is None:
            raise RuntimeAccessAttachmentMissing()
        return observed

    def verify_active_access_network(
        self,
        identity: AccessNetworkIdentity,
        platform_control: PlatformControlIdentity,
        runtime: RuntimeAccessMemberIdentity,
    ) -> AccessNetworkObservation:
        observed = self.verify_created_access_network(
            identity,
            platform_control,
            runtime,
        )
        if any(member.endpoint_id is None for member in observed.members):
            raise RuntimeAccessAttachmentMissing()
        return observed

    def remove_access_network_if_empty(
        self,
        identity: AccessNetworkIdentity,
    ) -> AccessNetworkObservation:
        if type(identity) is not AccessNetworkIdentity:
            raise DriverValidationError()
        self._validate_docker_execution_context()
        observed = self._inspect_access_network(identity, None, None)
        action = decide_access_network_removal(identity, observed)
        if action is AccessNetworkAction.ALREADY_ABSENT:
            return observed
        if action is not AccessNetworkAction.REMOVE or observed.network_id is None:
            raise AmbiguousNetworkOutcome()
        final = self._inspect_access_network(identity, None, None)
        if final != observed:
            raise AmbiguousNetworkOutcome()
        completed = self._run_network_mutation(
            (
                str(self._docker_executable),
                "network",
                "rm",
                observed.network_id,
            )
        )
        if completed.returncode != 0:
            raise AmbiguousNetworkOutcome()
        try:
            removed = self._inspect_access_network(identity, None, None)
        except _NETWORK_OBSERVATION_ERRORS:
            raise AmbiguousNetworkOutcome() from None
        if removed.state is not AccessNetworkState.ABSENT:
            raise AmbiguousNetworkOutcome()
        return AccessNetworkObservation.absent()

    def inspect(self, identity: DriverIdentity) -> DriverInspection:
        if type(identity) is not DriverIdentity:
            raise DriverValidationError()
        self._validate_docker_execution_context()
        observation = self._inspect_engine(identity)
        if observation is None:
            return DriverInspection.absent()
        if (
            observation.compose_project != identity.project_name
            or observation.compose_service != _SERVICE_NAME
        ):
            return self._unknown(observation.inspection)
        return observation.inspection

    def launch(self, snapshot: LaunchSnapshot) -> DriverInspection:
        if type(snapshot) is not LaunchSnapshot:
            raise DriverValidationError()
        self._validate_compose_launch_context()
        if self._inspect_engine(snapshot.identity) is not None:
            raise DriverObjectOccupied()
        try:
            lease = self._authority_resolver.resolve_active_launch(
                snapshot.identity,
                snapshot.launch_authority_digest,
            )
        except Exception:
            raise DriverPolicyError() from None
        if type(lease) is not ActiveLaunchAuthorityLease:
            raise DriverPolicyError()
        authority = lease.authority
        if authority.identity != snapshot.identity:
            raise DriverPolicyError()
        try:
            lease.revalidate_for_runtime_action()
            validate_launch_snapshot(snapshot, authority)
            expected_render = _render_snapshot_policy(snapshot, authority)
            validate_rendered_snapshot(expected_render, snapshot, authority)
            platform_control = (
                self._platform_control_identity_provider.resolve_platform_control_identity()
            )
            if type(platform_control) is not PlatformControlIdentity:
                raise DriverPolicyError()
            access_identity = compile_access_network_identity(snapshot)
        except (
            AccessNetworkIdentityError,
            AccessNetworkMemberMismatch,
            AmbiguousNetworkOutcome,
            DriverValidationError,
            DriverPolicyError,
            NetworkTransportError,
            PlatformControlIdentityMismatch,
        ):
            raise
        except Exception:
            raise DriverPolicyError() from None

        actual_render: RenderedContainerPolicy | None = None

        def validate_actual(path: Path) -> None:
            nonlocal actual_render
            try:
                actual_render = _parse_actual_render(path, snapshot, authority)
                validate_rendered_snapshot(actual_render, snapshot, authority)
            except (
                AccessNetworkIdentityError,
                AccessNetworkMemberMismatch,
                AmbiguousNetworkOutcome,
                DriverValidationError,
                DriverPolicyError,
                NetworkTransportError,
                PlatformControlIdentityMismatch,
            ):
                raise
            except Exception:
                raise DriverPolicyError() from None

        def validate_before_create() -> None:
            try:
                self._validate_compose_launch_context()
                validate_launch_snapshot(snapshot, authority)
                if actual_render is None:
                    raise DriverPolicyError()
                validate_rendered_snapshot(actual_render, snapshot, authority)
                lease.revalidate_for_runtime_action()
                self._access_network_driver.ensure_access_network(
                    access_identity,
                    platform_control,
                )
                lease.revalidate_for_runtime_action()
            except (
                AccessNetworkIdentityError,
                AccessNetworkMemberMismatch,
                AmbiguousNetworkOutcome,
                DriverValidationError,
                DriverPolicyError,
                NetworkTransportError,
                PlatformControlIdentityMismatch,
            ):
                raise
            except Exception:
                raise DriverPolicyError() from None
            if self._inspect_engine(snapshot.identity) is not None:
                raise DriverObjectOccupied()

        try:
            created = _run_validated_snapshot_launch(
                service=_SERVICE_NAME,
                project_name=snapshot.identity.project_name,
                root=self._working_directory,
                compose_command=(str(self._compose_executable),),
                compose_files=(),
                profiles=(),
                override=_compose_document(expected_render, snapshot),
                environment=self._environment,
                validate_pre_render=self._validate_compose_launch_context,
                validate_rendered_snapshot=validate_actual,
                validate_pre_action=validate_before_create,
                action_arguments=(
                    "create",
                    "--no-recreate",
                    "--no-build",
                    "--pull",
                    "never",
                    _SERVICE_NAME,
                ),
                render_timeout_seconds=_RENDER_TIMEOUT_SECONDS,
                action_timeout_seconds=_CREATE_TIMEOUT_SECONDS,
                capture_output=True,
                temporary_directory=self._temporary_directory,
                process_runner=self._command_runner,
            )
        except ComposeActionUncertain:
            raise AmbiguousDriverOutcome() from None
        except subprocess.TimeoutExpired:
            raise DriverTransportError() from None
        except OSError:
            raise DriverTransportError() from None
        except (
            AccessNetworkIdentityError,
            AccessNetworkMemberMismatch,
            AmbiguousNetworkOutcome,
            DriverValidationError,
            DriverPolicyError,
            DriverObjectOccupied,
            NetworkTransportError,
            PlatformControlIdentityMismatch,
        ):
            raise
        except ValueError:
            raise DriverPolicyError() from None
        if created.returncode != 0:
            raise AmbiguousDriverOutcome()

        try:
            created_observation = self._inspect_engine(snapshot.identity)
        except DriverTransportError:
            raise AmbiguousDriverOutcome() from None
        if (
            created_observation is None
            or created_observation.inspection.state is not DriverState.CREATED
            or not self._matches(
                created_observation,
                snapshot.identity,
                snapshot.launch_authority_digest,
            )
        ):
            raise AmbiguousDriverOutcome()
        container_id = created_observation.inspection.container_id
        if container_id is None:
            raise AmbiguousDriverOutcome()
        try:
            runtime_member = compile_runtime_access_member(snapshot, container_id)
            self._access_network_driver.verify_created_access_network(
                access_identity,
                platform_control,
                runtime_member,
            )
        except Exception:
            raise AmbiguousDriverOutcome() from None
        try:
            final_created = self._inspect_engine(snapshot.identity)
        except DriverTransportError:
            raise AmbiguousDriverOutcome() from None
        if final_created is None:
            raise AmbiguousDriverOutcome()
        if (
            final_created.inspection.state is not DriverState.CREATED
            or final_created.inspection.container_id != container_id
        ):
            raise AmbiguousDriverOutcome()
        if not self._matches(
            final_created,
            snapshot.identity,
            snapshot.launch_authority_digest,
        ):
            raise DriverIdentityMismatch()
        try:
            self._validate_docker_execution_context()
            validate_launch_snapshot(snapshot, authority)
            if actual_render is None:
                raise DriverPolicyError()
            validate_rendered_snapshot(actual_render, snapshot, authority)
            lease.revalidate_for_runtime_action()
            self._access_network_driver.verify_created_access_network(
                access_identity,
                platform_control,
                runtime_member,
            )
        except Exception:
            raise AmbiguousDriverOutcome() from None
        started = self._run_mutation(
            (str(self._docker_executable), "container", "start", container_id),
            timeout=_START_TIMEOUT_SECONDS,
        )
        if started.returncode != 0:
            raise AmbiguousDriverOutcome()
        try:
            observed = self._inspect_engine(snapshot.identity)
        except DriverTransportError:
            raise AmbiguousDriverOutcome() from None
        if observed is None or not self._matches(
            observed,
            snapshot.identity,
            snapshot.launch_authority_digest,
        ):
            raise AmbiguousDriverOutcome()
        try:
            self._access_network_driver.verify_active_access_network(
                access_identity,
                platform_control,
                runtime_member,
            )
        except Exception:
            raise AmbiguousDriverOutcome() from None
        return observed.inspection

    def stop(self, identity: DriverIdentity) -> DriverInspection:
        if type(identity) is not DriverIdentity:
            raise DriverValidationError()
        self._validate_docker_execution_context()
        observation = self._inspect_engine(identity)
        if observation is None:
            return DriverInspection.absent()
        if not self._matches_immutable_runtime(observation, identity):
            raise DriverIdentityMismatch()
        if observation.inspection.state is DriverState.EXITED:
            return observation.inspection
        container_id = observation.inspection.container_id
        final_observation = self._inspect_engine(identity)
        if (
            container_id is None
            or final_observation is None
            or final_observation.inspection.container_id != container_id
            or not self._matches_immutable_runtime(final_observation, identity)
        ):
            raise DriverIdentityMismatch()
        self._validate_docker_execution_context()
        stopped = self._run_mutation(
            (str(self._docker_executable), "container", "stop", container_id),
            timeout=_STOP_TIMEOUT_SECONDS,
        )
        if stopped.returncode != 0:
            raise AmbiguousDriverOutcome()
        try:
            terminal = self._inspect_engine(identity)
        except DriverTransportError:
            raise AmbiguousDriverOutcome() from None
        if terminal is None:
            return DriverInspection.absent()
        if not self._matches_immutable_runtime(terminal, identity):
            raise DriverIdentityMismatch()
        if terminal.inspection.state is not DriverState.EXITED:
            raise AmbiguousDriverOutcome()
        return terminal.inspection

    def probe(
        self,
        identity: DriverIdentity,
        profile_id: str,
    ) -> HealthObservation:
        if type(identity) is not DriverIdentity or type(profile_id) is not str:
            raise DriverValidationError()
        self._validate_docker_execution_context()
        observation = self._inspect_engine(identity)
        if observation is None:
            return HealthObservation(DriverHealth.UNKNOWN, 0, "health_object_absent")
        if not self._matches_runtime(observation, identity):
            raise DriverIdentityMismatch()
        if observation.inspection.state is not DriverState.RUNNING:
            return HealthObservation(
                DriverHealth.UNKNOWN,
                0,
                "health_object_not_running",
            )
        try:
            profile = self._authority_resolver.resolve_health_profile(
                identity,
                profile_id,
            )
        except Exception:
            raise DriverPolicyError() from None
        self._validate_health_profile(profile, profile_id)
        final_observation = self._inspect_engine(identity)
        if (
            final_observation is None
            or final_observation.inspection.container_id
            != observation.inspection.container_id
            or not self._matches_runtime(final_observation, identity)
        ):
            raise DriverIdentityMismatch()
        container_id = final_observation.inspection.container_id
        if container_id is None:
            raise DriverIdentityMismatch()
        try:
            final_profile = self._authority_resolver.resolve_health_profile(
                identity,
                profile_id,
            )
        except Exception:
            raise DriverPolicyError() from None
        self._validate_health_profile(final_profile, profile_id)
        if final_profile != profile:
            raise DriverPolicyError()
        execution_observation = self._inspect_engine(identity)
        if (
            execution_observation is None
            or execution_observation.inspection.container_id != container_id
            or not self._matches_runtime(execution_observation, identity)
        ):
            raise DriverIdentityMismatch()
        if execution_observation.inspection.state is not DriverState.RUNNING:
            return HealthObservation(
                DriverHealth.UNKNOWN,
                0,
                "health_object_not_running",
            )
        container_id = execution_observation.inspection.container_id
        if container_id is None:
            raise DriverIdentityMismatch()
        self._validate_health_profile(final_profile, profile_id)
        if final_profile != profile:
            raise DriverPolicyError()
        self._validate_docker_execution_context()
        try:
            completed = self._command_runner(
                [
                    str(self._docker_executable),
                    "container",
                    "exec",
                    container_id,
                    *final_profile.probe_argv,
                ],
                cwd=self._working_directory,
                env=self._environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=final_profile.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return HealthObservation(DriverHealth.UNHEALTHY, 1, "health_timeout")
        except OSError:
            return HealthObservation(DriverHealth.UNKNOWN, 1, "health_transport")
        if completed.returncode == 0:
            return HealthObservation(DriverHealth.HEALTHY, 1, None)
        return HealthObservation(DriverHealth.UNHEALTHY, 1, "health_probe_failed")

    def _validate_docker_execution_context(self) -> None:
        if (
            type(self._docker_executable) is not type(Path())
            or not self._docker_executable.is_absolute()
            or ".." in self._docker_executable.parts
        ):
            raise DriverPolicyError()
        if type(self._environment) is not dict or any(
            type(name) is not str or type(value) is not str or not value
            for name, value in self._environment.items()
        ):
            raise DriverPolicyError()
        if (
            type(self._working_directory) is not type(Path())
            or not self._working_directory.is_absolute()
            or not self._working_directory.is_dir()
            or self._working_directory.is_symlink()
        ):
            raise DriverPolicyError()
        folded = {str(name).casefold(): name for name in self._environment}
        if len(folded) != len(self._environment):
            raise DriverPolicyError()
        if any(name.casefold() in folded for name in _FORBIDDEN_ENVIRONMENT_NAMES):
            raise DriverPolicyError()
        if any(
            name.upper() not in _ALLOWED_ENVIRONMENT_NAMES for name in self._environment
        ):
            raise DriverPolicyError()
        if (
            self._approved_docker_host
            not in ("npipe:////./pipe/docker_engine", "unix:///var/run/docker.sock")
            or self._environment.get("DOCKER_HOST") != self._approved_docker_host
            or self._environment.get("DOCKER_CONTEXT") != self._approved_docker_context
            or self._environment.get("SYSTEMROOT") != self._approved_system_root
        ):
            raise DriverPolicyError()

    def _validate_compose_launch_context(self) -> None:
        self._validate_docker_execution_context()
        if (
            type(self._compose_executable) is not type(Path())
            or not self._compose_executable.is_absolute()
            or ".." in self._compose_executable.parts
            or type(self._temporary_directory) is not type(Path())
            or not self._temporary_directory.is_absolute()
            or not self._temporary_directory.is_dir()
            or self._temporary_directory.is_symlink()
        ):
            raise DriverPolicyError()

    def _inspect_platform_control(
        self,
        identity: PlatformControlIdentity,
    ) -> dict:
        document = self._container_document_by_id(identity.container_id)
        config = document.get("Config")
        labels = config.get("Labels") if type(config) is dict else None
        if (
            document.get("Id") != identity.container_id
            or document.get("Name", "").removeprefix("/") != identity.container_name
            or document.get("Image") != identity.image_id
            or type(labels) is not dict
            or labels.get("com.docker.compose.project") != identity.compose_project
            or labels.get("com.docker.compose.service") != identity.compose_service
            or labels.get("io.freqtrade.platform.role")
            != _PLATFORM_CONTROL_LABELS["io.freqtrade.platform.role"]
            or labels.get("io.freqtrade.platform.identity-revision")
            != identity.identity_revision
        ):
            raise PlatformControlIdentityMismatch()
        return document

    def _inspect_runtime_member(
        self,
        runtime: RuntimeAccessMemberIdentity,
    ) -> dict:
        document = self._container_document_by_id(runtime.container_id)
        try:
            observation = self._observation_from_document(document)
        except DriverTransportError:
            raise NetworkTransportError() from None
        if (
            observation.inspection.container_id != runtime.container_id
            or not self._matches_runtime(observation, runtime.runtime_identity)
            or observation.compose_project != runtime.compose_project
            or observation.compose_service != runtime.compose_service
        ):
            raise AccessNetworkIdentityError()
        return document

    def _container_document_by_id(self, container_id: str) -> dict:
        if type(container_id) is not str or _CONTAINER_ID.fullmatch(container_id) is None:
            raise DriverValidationError()
        completed = self._run_network_read_only(
            (
                str(self._docker_executable),
                "container",
                "inspect",
                container_id,
            )
        )
        try:
            payload = json.loads(completed.stdout)
            if (
                type(payload) is not list
                or len(payload) != 1
                or type(payload[0]) is not dict
                or payload[0].get("Id") != container_id
            ):
                raise ValueError
            return payload[0]
        except (TypeError, ValueError, json.JSONDecodeError):
            raise NetworkTransportError() from None

    def _inspect_access_network(
        self,
        identity: AccessNetworkIdentity,
        platform_control: PlatformControlIdentity | None,
        runtime: RuntimeAccessMemberIdentity | None,
    ) -> AccessNetworkObservation:
        listed = self._run_network_read_only(
            (
                str(self._docker_executable),
                "network",
                "ls",
                "--no-trunc",
                "--filter",
                f"name=^{re.escape(identity.network_name)}$",
                "--format",
                "{{.ID}}",
            )
        )
        identifiers = tuple(line for line in listed.stdout.splitlines() if line)
        if not identifiers:
            return AccessNetworkObservation.absent()
        if len(identifiers) != 1 or _NETWORK_ID.fullmatch(identifiers[0]) is None:
            raise NetworkTransportError()
        network_id = identifiers[0]
        inspected = self._run_network_read_only(
            (
                str(self._docker_executable),
                "network",
                "inspect",
                network_id,
            )
        )
        try:
            payload = json.loads(inspected.stdout)
            if (
                type(payload) is not list
                or len(payload) != 1
                or type(payload[0]) is not dict
                or payload[0].get("Id") != network_id
            ):
                raise ValueError
            document = payload[0]
        except (TypeError, ValueError, json.JSONDecodeError):
            raise NetworkTransportError() from None

        active = document.get("Containers")
        labels = document.get("Labels")
        options = document.get("Options")
        ipam = document.get("IPAM")
        config_from = document.get("ConfigFrom")
        if (
            type(active) is not dict
            or type(labels) is not dict
            or options
            not in (
                {},
                {
                    "com.docker.network.enable_ipv4": "true",
                    "com.docker.network.enable_ipv6": "false",
                },
            )
            or type(ipam) is not dict
            or ipam.get("Driver") != "default"
            or ipam.get("Options") not in (None, {})
            or type(ipam.get("Config")) is not list
            or config_from not in (None, {}, {"Network": ""})
            or ("EnableIPv4" in document and document["EnableIPv4"] is not True)
            or ("EnableIPv6" in document and document["EnableIPv6"] is not False)
        ):
            raise NetworkTransportError()
        for config in ipam["Config"]:
            if (
                type(config) is not dict
                or not set(config) <= {"Gateway", "Subnet"}
                or type(config.get("Subnet")) is not str
                or ("Gateway" in config and type(config["Gateway"]) is not str)
            ):
                raise NetworkTransportError()

        configured = self._run_network_read_only(
            (
                str(self._docker_executable),
                "container",
                "ls",
                "--all",
                "--no-trunc",
                "--filter",
                f"network={network_id}",
                "--format",
                "{{.ID}}\t{{.Names}}",
            )
        )
        configured_names: dict[str, str] = {}
        for line in configured.stdout.splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if (
                len(parts) != 2
                or _CONTAINER_ID.fullmatch(parts[0]) is None
                or not parts[1]
                or parts[0] in configured_names
            ):
                raise NetworkTransportError()
            configured_names[parts[0]] = parts[1]
        active_ids = set(active)
        if (
            any(_CONTAINER_ID.fullmatch(value) is None for value in active_ids)
            or not active_ids <= set(configured_names)
        ):
            raise NetworkTransportError()

        known = {
            value.container_id: value
            for value in (platform_control, runtime)
            if value is not None
        }
        members: list[AccessNetworkMember] = []
        for container_id in sorted(configured_names):
            active_endpoint = active.get(container_id)
            if active_endpoint is not None and type(active_endpoint) is not dict:
                raise NetworkTransportError()
            endpoint_id = (
                active_endpoint.get("EndpointID") if active_endpoint is not None else None
            )
            if (
                active_endpoint is not None
                and active_endpoint.get("Name") != configured_names[container_id]
            ):
                raise NetworkTransportError()
            if endpoint_id == "":
                endpoint_id = None
            if (
                endpoint_id is not None
                and (
                    type(endpoint_id) is not str
                    or _CONTAINER_ID.fullmatch(endpoint_id) is None
                )
            ):
                raise NetworkTransportError()
            aliases: tuple[str, ...] | None = None
            dns_names: tuple[str, ...] | None = None
            if container_id in known:
                container_document = (
                    self._inspect_platform_control(platform_control)
                    if platform_control is not None
                    and container_id == platform_control.container_id
                    else self._inspect_runtime_member(runtime)
                )
                settings = container_document.get("NetworkSettings")
                networks = settings.get("Networks") if type(settings) is dict else None
                endpoint = networks.get(identity.network_name) if type(networks) is dict else None
                if (
                    type(endpoint) is not dict
                    or endpoint.get("NetworkID") != network_id
                ):
                    raise AccessNetworkIdentityError()
                configured_endpoint_id = endpoint.get("EndpointID")
                if configured_endpoint_id == "":
                    configured_endpoint_id = None
                if configured_endpoint_id != endpoint_id:
                    raise AccessNetworkIdentityError()
                aliases = self._network_names_tuple(endpoint.get("Aliases"))
                dns_names = self._network_names_tuple(endpoint.get("DNSNames"))
            members.append(
                AccessNetworkMember(
                    container_id=container_id,
                    container_name=configured_names[container_id],
                    endpoint_id=endpoint_id,
                    aliases=aliases,
                    dns_names=dns_names,
                )
            )

        return AccessNetworkObservation(
            state=AccessNetworkState.PRESENT,
            network_id=network_id,
            observed_name=document.get("Name"),
            observed_driver=document.get("Driver"),
            observed_scope=document.get("Scope"),
            observed_internal=document.get("Internal"),
            observed_attachable=document.get("Attachable"),
            observed_ingress=document.get("Ingress"),
            observed_config_only=document.get("ConfigOnly"),
            observed_labels=tuple(
                AccessNetworkLabel(name, labels[name]) for name in sorted(labels)
            ),
            members=tuple(members),
        )

    @staticmethod
    def _network_names_tuple(value: object) -> tuple[str, ...] | None:
        if value is None:
            return None
        if type(value) is not list or any(type(item) is not str for item in value):
            raise NetworkTransportError()
        if len(value) != len(set(value)):
            raise NetworkTransportError()
        return tuple(sorted(set(value)))

    def _run_network_read_only(
        self,
        command: tuple[str, ...],
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self._run_read_only(command)
        except DriverTransportError:
            raise NetworkTransportError() from None

    def _run_network_mutation(
        self,
        command: tuple[str, ...],
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self._run_mutation(
                command,
                timeout=_NETWORK_MUTATION_TIMEOUT_SECONDS,
            )
        except AmbiguousDriverOutcome:
            raise AmbiguousNetworkOutcome() from None

    def _inspect_engine(
        self,
        identity: DriverIdentity,
    ) -> _EngineObservation | None:
        listed = self._run_read_only(
            (
                str(self._docker_executable),
                "container",
                "ls",
                "--all",
                "--no-trunc",
                "--filter",
                f"name=^/{identity.container_name}$",
                "--format",
                "{{.ID}}",
            )
        )
        identifiers = tuple(line for line in listed.stdout.splitlines() if line)
        if not identifiers:
            return None
        if len(identifiers) != 1 or _CONTAINER_ID.fullmatch(identifiers[0]) is None:
            raise DriverTransportError()
        container_id = identifiers[0]
        inspected = self._run_read_only(
            (
                str(self._docker_executable),
                "container",
                "inspect",
                container_id,
            )
        )
        try:
            payload = json.loads(inspected.stdout)
            if (
                type(payload) is not list
                or len(payload) != 1
                or type(payload[0]) is not dict
            ):
                raise ValueError
            document = payload[0]
            if document.get("Id") != container_id:
                raise ValueError
            return self._observation_from_document(document)
        except (DriverValidationError, TypeError, ValueError, json.JSONDecodeError):
            raise DriverTransportError() from None

    def _observation_from_document(self, document: dict) -> _EngineObservation:
        config = document.get("Config")
        state = document.get("State")
        network_settings = document.get("NetworkSettings")
        if (
            type(config) is not dict
            or type(state) is not dict
            or type(network_settings) is not dict
            or type(config.get("Labels")) is not dict
            or type(network_settings.get("Networks")) is not dict
        ):
            raise DriverTransportError()
        labels = config["Labels"]
        raw_state = state.get("Status")
        driver_state = {
            "created": DriverState.CREATED,
            "running": DriverState.RUNNING,
            "exited": DriverState.EXITED,
        }.get(raw_state, DriverState.UNKNOWN)
        raw_health = state.get("Health")
        health_value = raw_health.get("Status") if type(raw_health) is dict else None
        health = {
            None: DriverHealth.NOT_CONFIGURED,
            "starting": DriverHealth.STARTING,
            "healthy": DriverHealth.HEALTHY,
            "unhealthy": DriverHealth.UNHEALTHY,
        }.get(health_value, DriverHealth.UNKNOWN)
        if driver_state is DriverState.UNKNOWN:
            health = DriverHealth.UNKNOWN
        inspection = DriverInspection(
            state=driver_state,
            container_id=document.get("Id"),
            observed_project_name=labels.get(_IDENTITY_LABELS["project"]),
            observed_container_name=document.get("Name", "").removeprefix("/"),
            observed_instance_id=labels.get(_IDENTITY_LABELS["instance"]),
            observed_attempt_id=labels.get(_IDENTITY_LABELS["attempt"]),
            observed_runtime_spec_digest=labels.get(_IDENTITY_LABELS["spec"]),
            observed_state_allocation_id=labels.get(_IDENTITY_LABELS["state"]),
            observed_image_id=document.get("Image"),
            observed_network_names=tuple(sorted(network_settings["Networks"])),
            health=health,
            exit_code=state.get("ExitCode")
            if driver_state is DriverState.EXITED
            else None,
        )
        return _EngineObservation(
            inspection=inspection,
            launch_authority_digest=labels.get(_IDENTITY_LABELS["launch"]),
            compose_project=labels.get("com.docker.compose.project"),
            compose_service=labels.get("com.docker.compose.service"),
        )

    def _run_read_only(
        self, command: tuple[str, ...]
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = self._command_runner(
                list(command),
                cwd=self._working_directory,
                env=self._environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=_INSPECT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise DriverTransportError() from None
        if completed.returncode != 0:
            raise DriverTransportError()
        return completed

    def _run_mutation(
        self,
        command: tuple[str, ...],
        *,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self._command_runner(
                list(command),
                cwd=self._working_directory,
                env=self._environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise AmbiguousDriverOutcome() from None

    @staticmethod
    def _matches_public_identity(
        inspection: DriverInspection,
        identity: DriverIdentity,
    ) -> bool:
        return (
            inspection.observed_project_name == identity.project_name
            and inspection.observed_container_name == identity.container_name
            and inspection.observed_instance_id == identity.instance_id
            and inspection.observed_attempt_id == identity.attempt_id
            and inspection.observed_runtime_spec_digest == identity.runtime_spec_digest
            and inspection.observed_state_allocation_id == identity.state_allocation_id
            and inspection.observed_image_id == identity.image_id
        )

    @classmethod
    def _matches_immutable_runtime(
        cls,
        observation: _EngineObservation,
        identity: DriverIdentity,
    ) -> bool:
        return (
            cls._matches_public_identity(observation.inspection, identity)
            and observation.compose_project == identity.project_name
            and observation.compose_service == _SERVICE_NAME
        )

    @classmethod
    def _matches_runtime(
        cls,
        observation: _EngineObservation,
        identity: DriverIdentity,
    ) -> bool:
        return (
            cls._matches_immutable_runtime(observation, identity)
            and observation.inspection.observed_network_names
            == identity.network_names
        )

    @classmethod
    def _matches(
        cls,
        observation: _EngineObservation,
        identity: DriverIdentity,
        launch_authority_digest: str,
    ) -> bool:
        return (
            cls._matches_runtime(observation, identity)
            and observation.launch_authority_digest == launch_authority_digest
        )

    @staticmethod
    def _unknown(inspection: DriverInspection) -> DriverInspection:
        return DriverInspection(
            state=DriverState.UNKNOWN,
            container_id=inspection.container_id,
            observed_project_name=inspection.observed_project_name,
            observed_container_name=inspection.observed_container_name,
            observed_instance_id=inspection.observed_instance_id,
            observed_attempt_id=inspection.observed_attempt_id,
            observed_runtime_spec_digest=inspection.observed_runtime_spec_digest,
            observed_state_allocation_id=inspection.observed_state_allocation_id,
            observed_image_id=inspection.observed_image_id,
            observed_network_names=inspection.observed_network_names,
            health=DriverHealth.UNKNOWN,
            exit_code=None,
        )

    @staticmethod
    def _validate_health_profile(profile: HealthProfile, profile_id: str) -> None:
        if type(profile) is not HealthProfile or profile.profile_id != profile_id:
            raise DriverPolicyError()
        try:
            profile.__post_init__()
        except Exception:
            raise DriverPolicyError() from None
        executable = PurePosixPath(profile.probe_argv[0]).name.casefold()
        if (
            executable in _FORBIDDEN_PROBE_EXECUTABLES
            or executable not in _ALLOWED_PROBE_EXECUTABLES
            or _APPROVED_PROBE_ARGV_BY_ID.get(profile.profile_id) != profile.probe_argv
            or profile.start_period_seconds > _MAX_HEALTH_START_PERIOD_SECONDS
            or profile.interval_seconds > _MAX_HEALTH_INTERVAL_SECONDS
            or profile.timeout_seconds > _MAX_HEALTH_TIMEOUT_SECONDS
            or profile.retries > _MAX_HEALTH_RETRIES
        ):
            raise DriverPolicyError()
