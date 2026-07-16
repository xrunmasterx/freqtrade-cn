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
    AmbiguousDriverOutcome,
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


_SERVICE_NAME = "runtime"
_INSPECT_TIMEOUT_SECONDS = 15
_RENDER_TIMEOUT_SECONDS = 30
_CREATE_TIMEOUT_SECONDS = 60
_START_TIMEOUT_SECONDS = 60
_STOP_TIMEOUT_SECONDS = 60
_MAX_HEALTH_START_PERIOD_SECONDS = 300
_MAX_HEALTH_INTERVAL_SECONDS = 300
_MAX_HEALTH_TIMEOUT_SECONDS = 60
_MAX_HEALTH_RETRIES = 20
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
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


def _compose_document(rendered: RenderedContainerPolicy) -> str:
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
        "networks": {name: None for name in rendered.network_names},
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
            or set(definition) != {"external", "name"}
            or definition.get("external") is not True
            or definition.get("name") != name
        ):
            raise DriverPolicyError()
    expected_mounts = {str(mount.target): mount for mount in expected.mounts}
    raw_mounts = service.get("volumes")
    if type(raw_mounts) is not list:
        raise DriverPolicyError()
    actual_mounts = []
    for raw_mount in raw_mounts:
        if (
            type(raw_mount) is not dict
            or set(raw_mount) != {"bind", "read_only", "source", "target", "type"}
            or raw_mount.get("type") != "bind"
        ):
            raise DriverPolicyError()
        source = raw_mount.get("source")
        target = raw_mount.get("target")
        expected_mount = expected_mounts.get(target)
        bind = raw_mount.get("bind")
        if (
            expected_mount is None
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
                raw_mount.get("read_only"),
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
    if (
        set(health) != {"interval", "retries", "start_period", "test", "timeout"}
        or any(value not in (None, {}) for value in networks.values())
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
            memory_bytes=service.get("mem_limit"),
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
        self._command_runner = command_runner

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
        except (DriverValidationError, DriverPolicyError):
            raise
        except Exception:
            raise DriverPolicyError() from None

        actual_render: RenderedContainerPolicy | None = None

        def validate_actual(path: Path) -> None:
            nonlocal actual_render
            try:
                actual_render = _parse_actual_render(path, snapshot, authority)
                validate_rendered_snapshot(actual_render, snapshot, authority)
            except (DriverValidationError, DriverPolicyError):
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
            except (DriverValidationError, DriverPolicyError):
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
                override=_compose_document(expected_render),
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
        except (DriverValidationError, DriverPolicyError, DriverObjectOccupied):
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
        return observed.inspection

    def stop(self, identity: DriverIdentity) -> DriverInspection:
        if type(identity) is not DriverIdentity:
            raise DriverValidationError()
        self._validate_docker_execution_context()
        observation = self._inspect_engine(identity)
        if observation is None:
            return DriverInspection.absent()
        if not self._matches_runtime(observation, identity):
            raise DriverIdentityMismatch()
        if observation.inspection.state is DriverState.EXITED:
            return observation.inspection
        container_id = observation.inspection.container_id
        final_observation = self._inspect_engine(identity)
        if (
            container_id is None
            or final_observation is None
            or final_observation.inspection.container_id != container_id
            or not self._matches_runtime(final_observation, identity)
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
        if not self._matches_runtime(terminal, identity):
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
            and inspection.observed_network_names == identity.network_names
        )

    @classmethod
    def _matches_runtime(
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
