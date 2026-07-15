from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Mapping, Protocol, TypeVar


class DriverValidationError(ValueError):
    code = "driver_validation_error"

    def __init__(self) -> None:
        super().__init__(self.code)


_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_ENVIRONMENT_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
_SECRET_ENVIRONMENT_SEGMENTS = {
    "CREDENTIAL",
    "KEY",
    "PASSWORD",
    "SECRET",
    "TOKEN",
}
_T = TypeVar("_T")


def _require_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise DriverValidationError()
    return value


def _require_optional_observed(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or _CONTROL_CHARACTER.search(value):
        raise DriverValidationError()
    return value


def _require_tuple(value: object, *, allow_empty: bool) -> tuple:
    if not isinstance(value, tuple) or (not allow_empty and not value):
        raise DriverValidationError()
    return value


def _require_mount_paths(source: object, target: object) -> None:
    if (
        not isinstance(source, Path)
        or not source.is_absolute()
        or not isinstance(target, PurePosixPath)
        or not target.is_absolute()
    ):
        raise DriverValidationError()
    for path in (source, target):
        parts = str(path).replace("\\", "/").lower().split("/")
        if ".." in parts or "docker.sock" in parts:
            raise DriverValidationError()


class _StrictValue:
    @classmethod
    def model_validate(cls: type[_T], value: object) -> _T:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise DriverValidationError()
        allowed = {field.name for field in dataclasses.fields(cls)}
        keys = set(value)
        if keys - allowed:
            raise DriverValidationError()
        if allowed - keys:
            raise DriverValidationError()
        return cls(**dict(value))


class DriverState(StrEnum):
    ABSENT = "absent"
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    EXITED = "exited"
    UNKNOWN = "unknown"


class DriverHealth(StrEnum):
    NOT_CONFIGURED = "not_configured"
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DriverIdentity(_StrictValue):
    project_name: str
    container_name: str
    instance_id: str
    attempt_id: str
    runtime_spec_digest: str
    state_allocation_id: str
    image_id: str
    network_names: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (
            self.project_name,
            self.container_name,
            self.instance_id,
            self.attempt_id,
            self.state_allocation_id,
        ):
            _require_identifier(value)
        if not isinstance(self.runtime_spec_digest, str) or _DIGEST.fullmatch(
            self.runtime_spec_digest
        ) is None:
            raise DriverValidationError()
        if not isinstance(self.image_id, str) or _IMAGE_ID.fullmatch(self.image_id) is None:
            raise DriverValidationError()
        names = _require_tuple(self.network_names, allow_empty=False)
        if any(
            not isinstance(name, str) or _IDENTIFIER.fullmatch(name) is None for name in names
        ):
            raise DriverValidationError()
        if names != tuple(sorted(set(names))):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class DriverInspection(_StrictValue):
    state: DriverState
    container_id: str | None
    observed_project_name: str | None
    observed_container_name: str | None
    observed_instance_id: str | None
    observed_attempt_id: str | None
    observed_runtime_spec_digest: str | None
    observed_state_allocation_id: str | None
    observed_image_id: str | None
    observed_network_names: tuple[str, ...]
    health: DriverHealth
    exit_code: int | None

    @classmethod
    def absent(cls) -> "DriverInspection":
        return cls(
            state=DriverState.ABSENT,
            container_id=None,
            observed_project_name=None,
            observed_container_name=None,
            observed_instance_id=None,
            observed_attempt_id=None,
            observed_runtime_spec_digest=None,
            observed_state_allocation_id=None,
            observed_image_id=None,
            observed_network_names=(),
            health=DriverHealth.UNKNOWN,
            exit_code=None,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.state, DriverState) or not isinstance(self.health, DriverHealth):
            raise DriverValidationError()
        networks = _require_tuple(self.observed_network_names, allow_empty=True)
        if any(
            not isinstance(name, str) or not name or _CONTROL_CHARACTER.search(name)
            for name in networks
        ):
            raise DriverValidationError()
        if networks != tuple(sorted(set(networks))):
            raise DriverValidationError()
        for value in (
            self.observed_project_name,
            self.observed_container_name,
            self.observed_instance_id,
            self.observed_attempt_id,
            self.observed_runtime_spec_digest,
            self.observed_state_allocation_id,
            self.observed_image_id,
        ):
            _require_optional_observed(value)
        if self.state is DriverState.ABSENT:
            if any(
                value is not None
                for value in (
                    self.container_id,
                    self.observed_project_name,
                    self.observed_container_name,
                    self.observed_instance_id,
                    self.observed_attempt_id,
                    self.observed_runtime_spec_digest,
                    self.observed_state_allocation_id,
                    self.observed_image_id,
                    self.exit_code,
                )
            ) or networks or self.health is not DriverHealth.UNKNOWN:
                raise DriverValidationError()
            return
        if not isinstance(self.container_id, str) or _CONTAINER_ID.fullmatch(
            self.container_id
        ) is None:
            raise DriverValidationError()
        if self.state is DriverState.EXITED:
            if type(self.exit_code) is not int:
                raise DriverValidationError()
        elif self.exit_code is not None:
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class HealthProfile(_StrictValue):
    profile_id: str
    probe_argv: tuple[str, ...]
    start_period_seconds: int
    interval_seconds: int
    timeout_seconds: int
    retries: int

    def __post_init__(self) -> None:
        _require_identifier(self.profile_id)
        argv = _require_tuple(self.probe_argv, allow_empty=False)
        if any(
            not isinstance(token, str) or not token or _CONTROL_CHARACTER.search(token)
            for token in argv
        ):
            raise DriverValidationError()
        if (
            type(self.start_period_seconds) is not int
            or self.start_period_seconds < 0
            or type(self.interval_seconds) is not int
            or self.interval_seconds <= 0
            or type(self.timeout_seconds) is not int
            or self.timeout_seconds <= 0
            or self.timeout_seconds > self.interval_seconds
            or type(self.retries) is not int
            or self.retries <= 0
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class HealthObservation(_StrictValue):
    status: DriverHealth
    attempts: int
    failure_code: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, DriverHealth):
            raise DriverValidationError()
        if type(self.attempts) is not int or self.attempts < 0:
            raise DriverValidationError()
        if self.failure_code is not None:
            _require_identifier(self.failure_code)


@dataclass(frozen=True, slots=True)
class EnvironmentEntry(_StrictValue):
    name: str
    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or _ENVIRONMENT_NAME.fullmatch(self.name) is None
            or any(
                segment in _SECRET_ENVIRONMENT_SEGMENTS
                for segment in self.name.split("_")
            )
            or not isinstance(self.value, str)
            or not self.value
            or _CONTROL_CHARACTER.search(self.value)
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class ReadOnlyMount(_StrictValue):
    source: Path
    target: PurePosixPath

    def __post_init__(self) -> None:
        _require_mount_paths(self.source, self.target)


@dataclass(frozen=True, slots=True)
class WritableStateMount(_StrictValue):
    source: Path
    target: PurePosixPath
    allocation_id: str

    def __post_init__(self) -> None:
        _require_mount_paths(self.source, self.target)
        _require_identifier(self.allocation_id)


@dataclass(frozen=True, slots=True)
class SecretMount(_StrictValue):
    source: Path
    target: PurePosixPath
    secret_reference_id: str
    version: str

    def __post_init__(self) -> None:
        _require_mount_paths(self.source, self.target)
        _require_identifier(self.secret_reference_id)
        _require_identifier(self.version)


@dataclass(frozen=True, slots=True)
class RuntimeUser(_StrictValue):
    uid: int
    gid: int
    home: PurePosixPath

    def __post_init__(self) -> None:
        if (
            type(self.uid) is not int
            or self.uid <= 0
            or type(self.gid) is not int
            or self.gid <= 0
            or not isinstance(self.home, PurePosixPath)
            or not self.home.is_absolute()
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class ResourceLimits(_StrictValue):
    cpu_millis: int
    memory_bytes: int
    pids_limit: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (self.cpu_millis, self.memory_bytes, self.pids_limit)
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class LaunchSnapshot(_StrictValue):
    identity: DriverIdentity
    argv: tuple[str, ...]
    working_directory: str
    non_secret_environment: tuple[EnvironmentEntry, ...]
    read_only_mounts: tuple[ReadOnlyMount, ...]
    state_mount: WritableStateMount
    secret_mounts: tuple[SecretMount, ...]
    runtime_user: RuntimeUser
    internal_ports: tuple[int, ...]
    health_profile: HealthProfile
    resource_limits: ResourceLimits

    @classmethod
    def model_validate(cls, value: object) -> "LaunchSnapshot":
        if isinstance(value, cls):
            return value
        raise DriverValidationError()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.identity, DriverIdentity)
            or not isinstance(self.state_mount, WritableStateMount)
            or not isinstance(self.runtime_user, RuntimeUser)
            or not isinstance(self.health_profile, HealthProfile)
            or not isinstance(self.resource_limits, ResourceLimits)
        ):
            raise DriverValidationError()

        argv = _require_tuple(self.argv, allow_empty=False)
        if any(
            not isinstance(token, str) or not token or _CONTROL_CHARACTER.search(token)
            for token in argv
        ):
            raise DriverValidationError()
        if (
            not isinstance(self.working_directory, str)
            or not PurePosixPath(self.working_directory).is_absolute()
        ):
            raise DriverValidationError()

        environment = _require_tuple(self.non_secret_environment, allow_empty=True)
        if any(not isinstance(entry, EnvironmentEntry) for entry in environment):
            raise DriverValidationError()
        environment_names = tuple(entry.name for entry in environment)
        if environment_names != tuple(sorted(set(environment_names))):
            raise DriverValidationError()

        read_only_mounts = _require_tuple(self.read_only_mounts, allow_empty=True)
        if any(not isinstance(mount, ReadOnlyMount) for mount in read_only_mounts):
            raise DriverValidationError()
        read_only_targets = tuple(str(mount.target) for mount in read_only_mounts)
        if read_only_targets != tuple(sorted(set(read_only_targets))):
            raise DriverValidationError()

        secret_mounts = _require_tuple(self.secret_mounts, allow_empty=True)
        if any(not isinstance(mount, SecretMount) for mount in secret_mounts):
            raise DriverValidationError()
        secret_targets = tuple(str(mount.target) for mount in secret_mounts)
        if secret_targets != tuple(sorted(set(secret_targets))):
            raise DriverValidationError()

        all_targets = (
            *read_only_targets,
            str(self.state_mount.target),
            *secret_targets,
        )
        if len(all_targets) != len(set(all_targets)):
            raise DriverValidationError()
        if self.state_mount.allocation_id != self.identity.state_allocation_id:
            raise DriverValidationError()

        ports = _require_tuple(self.internal_ports, allow_empty=True)
        if any(type(port) is not int or port < 1 or port > 65535 for port in ports):
            raise DriverValidationError()
        if ports != tuple(sorted(set(ports))):
            raise DriverValidationError()


class _FixedDriverError(RuntimeError):
    code = "driver_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class DriverPolicyError(_FixedDriverError):
    code = "driver_policy_error"


class DriverIdentityMismatch(_FixedDriverError):
    code = "driver_identity_mismatch"


class DriverObjectOccupied(_FixedDriverError):
    code = "driver_object_occupied"


class AmbiguousDriverOutcome(_FixedDriverError):
    code = "ambiguous_driver_outcome"


class DriverTransportError(_FixedDriverError):
    code = "driver_transport_error"


class RuntimeDriver(Protocol):
    def inspect(self, identity: DriverIdentity) -> DriverInspection: ...

    def launch(self, snapshot: LaunchSnapshot) -> DriverInspection: ...

    def stop(self, identity: DriverIdentity) -> DriverInspection: ...

    def probe(
        self,
        identity: DriverIdentity,
        profile_id: str,
    ) -> HealthObservation: ...
