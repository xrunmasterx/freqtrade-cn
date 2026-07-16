from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
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
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise DriverValidationError()
    return value


def _require_optional_observed(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or _CONTROL_CHARACTER.search(value):
        raise DriverValidationError()
    return value


def _require_tuple(value: object, *, allow_empty: bool) -> tuple:
    if type(value) is not tuple or (not allow_empty and not value):
        raise DriverValidationError()
    return value


def _require_mount_paths(source: object, target: object) -> None:
    if (
        type(source) is not type(Path())
        or not source.is_absolute()
        or type(target) is not PurePosixPath
        or not target.is_absolute()
    ):
        raise DriverValidationError()
    for path in (source, target):
        parts = str(path).replace("\\", "/").lower().split("/")
        if ".." in parts or "docker.sock" in parts:
            raise DriverValidationError()


def _require_container_path(value: object) -> PurePosixPath:
    if type(value) is not PurePosixPath or not value.is_absolute():
        raise DriverValidationError()
    normalized = str(value).replace("\\", "/").lower()
    if ".." in normalized.split("/") or "docker.sock" in normalized:
        raise DriverValidationError()
    return value


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


class AccessNetworkState(StrEnum):
    ABSENT = "absent"
    PRESENT = "present"


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
        if (
            type(self.runtime_spec_digest) is not str
            or _DIGEST.fullmatch(self.runtime_spec_digest) is None
        ):
            raise DriverValidationError()
        if type(self.image_id) is not str or _IMAGE_ID.fullmatch(self.image_id) is None:
            raise DriverValidationError()
        names = _require_tuple(self.network_names, allow_empty=False)
        if any(
            type(name) is not str or _IDENTIFIER.fullmatch(name) is None
            for name in names
        ):
            raise DriverValidationError()
        if names != tuple(sorted(set(names))):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class PlatformControlIdentity(_StrictValue):
    container_id: str
    container_name: str
    image_id: str
    compose_project: str
    compose_service: str
    identity_revision: str

    @classmethod
    def model_validate(cls, value: object) -> "PlatformControlIdentity":
        if type(value) is cls:
            return value
        raise DriverValidationError()

    def __post_init__(self) -> None:
        if (
            type(self.container_id) is not str
            or _CONTAINER_ID.fullmatch(self.container_id) is None
            or type(self.image_id) is not str
            or _IMAGE_ID.fullmatch(self.image_id) is None
            or self.compose_service != "platform-control"
            or self.identity_revision != "platform-control-v1"
        ):
            raise DriverValidationError()
        for value in (
            self.container_name,
            self.compose_project,
            self.compose_service,
            self.identity_revision,
        ):
            _require_identifier(value)


@dataclass(frozen=True, slots=True)
class AccessNetworkIdentity(_StrictValue):
    instance_id: str
    network_name: str
    policy_digest: str
    internal: bool
    requires_upstream_access: bool
    requires_platform_control: bool

    @classmethod
    def model_validate(cls, value: object) -> "AccessNetworkIdentity":
        if type(value) is cls:
            return value
        raise DriverValidationError()

    def __post_init__(self) -> None:
        _require_identifier(self.instance_id)
        _require_identifier(self.network_name)
        if (
            type(self.policy_digest) is not str
            or _DIGEST.fullmatch(self.policy_digest) is None
            or type(self.internal) is not bool
            or type(self.requires_upstream_access) is not bool
            or type(self.requires_platform_control) is not bool
            or self.internal is self.requires_upstream_access
            or not self.requires_platform_control
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class RuntimeAccessMemberIdentity(_StrictValue):
    container_id: str
    runtime_identity: DriverIdentity
    compose_service: str
    runtime_alias: str

    @classmethod
    def model_validate(cls, value: object) -> "RuntimeAccessMemberIdentity":
        if type(value) is cls:
            return value
        raise DriverValidationError()

    def __post_init__(self) -> None:
        if (
            type(self.container_id) is not str
            or _CONTAINER_ID.fullmatch(self.container_id) is None
            or type(self.runtime_identity) is not DriverIdentity
            or self.compose_service != "runtime"
        ):
            raise DriverValidationError()
        for value in (self.compose_service, self.runtime_alias):
            _require_identifier(value)

    @property
    def container_name(self) -> str:
        return self.runtime_identity.container_name

    @property
    def compose_project(self) -> str:
        return self.runtime_identity.project_name

    @property
    def attempt_id(self) -> str:
        return self.runtime_identity.attempt_id


@dataclass(frozen=True, slots=True)
class RuntimeAccessNetworkPlan(_StrictValue):
    access_identity: AccessNetworkIdentity
    runtime_member: RuntimeAccessMemberIdentity

    @classmethod
    def model_validate(cls, value: object) -> "RuntimeAccessNetworkPlan":
        if type(value) is cls:
            return value
        raise DriverValidationError()

    def __post_init__(self) -> None:
        if (
            type(self.access_identity) is not AccessNetworkIdentity
            or type(self.runtime_member) is not RuntimeAccessMemberIdentity
            or self.access_identity.instance_id
            != self.runtime_member.runtime_identity.instance_id
            or self.access_identity.network_name
            not in self.runtime_member.runtime_identity.network_names
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class AccessNetworkLabel(_StrictValue):
    name: str
    value: str

    @classmethod
    def model_validate(cls, value: object) -> "AccessNetworkLabel":
        if type(value) is cls:
            return value
        raise DriverValidationError()

    def __post_init__(self) -> None:
        _require_identifier(self.name)
        if (
            type(self.value) is not str
            or not self.value
            or len(self.value) > 256
            or _CONTROL_CHARACTER.search(self.value)
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class AccessNetworkMember(_StrictValue):
    container_id: str
    container_name: str
    endpoint_id: str | None
    aliases: tuple[str, ...] | None
    dns_names: tuple[str, ...] | None

    @classmethod
    def model_validate(cls, value: object) -> "AccessNetworkMember":
        if type(value) is cls:
            return value
        raise DriverValidationError()

    def __post_init__(self) -> None:
        if (
            type(self.container_id) is not str
            or _CONTAINER_ID.fullmatch(self.container_id) is None
            or (
                self.endpoint_id is not None
                and (
                    type(self.endpoint_id) is not str
                    or _CONTAINER_ID.fullmatch(self.endpoint_id) is None
                )
            )
        ):
            raise DriverValidationError()
        _require_identifier(self.container_name)
        for values in (self.aliases, self.dns_names):
            if values is None:
                continue
            entries = _require_tuple(values, allow_empty=True)
            if any(
                type(value) is not str
                or not value
                or _CONTROL_CHARACTER.search(value)
                for value in entries
            ):
                raise DriverValidationError()
            if entries != tuple(sorted(set(entries))):
                raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class AccessNetworkObservation(_StrictValue):
    state: AccessNetworkState
    network_id: str | None
    observed_name: str | None
    observed_driver: str | None
    observed_scope: str | None
    observed_internal: bool | None
    observed_attachable: bool | None
    observed_ingress: bool | None
    observed_config_only: bool | None
    observed_labels: tuple[AccessNetworkLabel, ...]
    members: tuple[AccessNetworkMember, ...]

    @classmethod
    def model_validate(cls, value: object) -> "AccessNetworkObservation":
        if type(value) is cls:
            return value
        raise DriverValidationError()

    @classmethod
    def absent(cls) -> "AccessNetworkObservation":
        return cls(
            state=AccessNetworkState.ABSENT,
            network_id=None,
            observed_name=None,
            observed_driver=None,
            observed_scope=None,
            observed_internal=None,
            observed_attachable=None,
            observed_ingress=None,
            observed_config_only=None,
            observed_labels=(),
            members=(),
        )

    def __post_init__(self) -> None:
        if type(self.state) is not AccessNetworkState:
            raise DriverValidationError()
        labels = _require_tuple(self.observed_labels, allow_empty=True)
        members = _require_tuple(self.members, allow_empty=True)
        if (
            any(type(label) is not AccessNetworkLabel for label in labels)
            or tuple(label.name for label in labels)
            != tuple(sorted(set(label.name for label in labels)))
            or any(type(member) is not AccessNetworkMember for member in members)
            or tuple(member.container_id for member in members)
            != tuple(sorted(set(member.container_id for member in members)))
        ):
            raise DriverValidationError()
        observed_values = (
            self.observed_name,
            self.observed_driver,
            self.observed_scope,
            self.observed_internal,
            self.observed_attachable,
            self.observed_ingress,
            self.observed_config_only,
        )
        if self.state is AccessNetworkState.ABSENT:
            if (
                self.network_id is not None
                or any(value is not None for value in observed_values)
                or labels
                or members
            ):
                raise DriverValidationError()
            return
        if (
            type(self.network_id) is not str
            or _CONTAINER_ID.fullmatch(self.network_id) is None
            or any(type(value) is not str or not value for value in observed_values[:3])
            or any(type(value) is not bool for value in observed_values[3:])
        ):
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
        if not isinstance(self.state, DriverState) or not isinstance(
            self.health, DriverHealth
        ):
            raise DriverValidationError()
        networks = _require_tuple(self.observed_network_names, allow_empty=True)
        if any(
            type(name) is not str or not name or _CONTROL_CHARACTER.search(name)
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
            if (
                any(
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
                )
                or networks
                or self.health is not DriverHealth.UNKNOWN
            ):
                raise DriverValidationError()
            return
        if (
            type(self.container_id) is not str
            or _CONTAINER_ID.fullmatch(self.container_id) is None
        ):
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
            type(token) is not str or not token or _CONTROL_CHARACTER.search(token)
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
            type(self.name) is not str
            or _ENVIRONMENT_NAME.fullmatch(self.name) is None
            or any(
                segment in _SECRET_ENVIRONMENT_SEGMENTS
                for segment in self.name.split("_")
            )
            or type(self.value) is not str
            or not self.value
            or _CONTROL_CHARACTER.search(self.value)
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class ReadOnlyMount(_StrictValue):
    source: Path = field(repr=False)
    target: PurePosixPath

    def __post_init__(self) -> None:
        _require_mount_paths(self.source, self.target)


@dataclass(frozen=True, slots=True)
class WritableStateMount(_StrictValue):
    source: Path = field(repr=False)
    target: PurePosixPath
    allocation_id: str

    def __post_init__(self) -> None:
        _require_mount_paths(self.source, self.target)
        _require_identifier(self.allocation_id)


@dataclass(frozen=True, slots=True)
class SecretMount(_StrictValue):
    source: Path = field(repr=False)
    target: PurePosixPath
    secret_reference_id: str
    version: str

    def __post_init__(self) -> None:
        _require_mount_paths(self.source, self.target)
        _require_identifier(self.secret_reference_id)
        _require_identifier(self.version)


@dataclass(frozen=True, slots=True)
class SecretPathEnvironmentBinding(_StrictValue):
    name: str
    target: PurePosixPath

    @classmethod
    def model_validate(cls, value: object) -> "SecretPathEnvironmentBinding":
        if type(value) is cls:
            return value
        raise DriverValidationError()

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or _ENVIRONMENT_NAME.fullmatch(self.name) is None
            or not self.name.endswith("_FILE")
        ):
            raise DriverValidationError()
        _require_container_path(self.target)


@dataclass(frozen=True, slots=True)
class RuntimeNetworkBinding(_StrictValue):
    role: str
    network_name: str
    runtime_alias: str
    policy_digest: str
    internal: bool
    requires_upstream_access: bool
    requires_platform_control: bool

    @classmethod
    def model_validate(cls, value: object) -> "RuntimeNetworkBinding":
        if type(value) is cls:
            return value
        raise DriverValidationError()

    def __post_init__(self) -> None:
        for value in (self.role, self.network_name, self.runtime_alias):
            _require_identifier(value)
        if (
            type(self.policy_digest) is not str
            or _DIGEST.fullmatch(self.policy_digest) is None
            or type(self.internal) is not bool
            or type(self.requires_upstream_access) is not bool
            or type(self.requires_platform_control) is not bool
            or self.internal is self.requires_upstream_access
            or (self.role == "access" and not self.requires_platform_control)
        ):
            raise DriverValidationError()


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
            or type(self.home) is not PurePosixPath
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
    launch_authority_digest: str
    argv: tuple[str, ...]
    working_directory: str
    non_secret_environment: tuple[EnvironmentEntry, ...]
    read_only_mounts: tuple[ReadOnlyMount, ...]
    state_mount: WritableStateMount
    secret_mounts: tuple[SecretMount, ...]
    secret_path_environment_bindings: tuple[SecretPathEnvironmentBinding, ...]
    runtime_user: RuntimeUser
    internal_ports: tuple[int, ...]
    health_profile: HealthProfile
    resource_limits: ResourceLimits
    network_bindings: tuple[RuntimeNetworkBinding, ...]

    @property
    def secret_path_environment(
        self,
    ) -> tuple[SecretPathEnvironmentBinding, ...]:
        return self.secret_path_environment_bindings

    @classmethod
    def model_validate(cls, value: object) -> "LaunchSnapshot":
        if type(value) is cls:
            return value
        raise DriverValidationError()

    def __post_init__(self) -> None:
        if (
            type(self.identity) is not DriverIdentity
            or type(self.state_mount) is not WritableStateMount
            or type(self.runtime_user) is not RuntimeUser
            or type(self.health_profile) is not HealthProfile
            or type(self.resource_limits) is not ResourceLimits
        ):
            raise DriverValidationError()
        if (
            type(self.launch_authority_digest) is not str
            or _DIGEST.fullmatch(self.launch_authority_digest) is None
        ):
            raise DriverValidationError()

        argv = _require_tuple(self.argv, allow_empty=False)
        if any(
            type(token) is not str or not token or _CONTROL_CHARACTER.search(token)
            for token in argv
        ):
            raise DriverValidationError()
        if (
            type(self.working_directory) is not str
            or not PurePosixPath(self.working_directory).is_absolute()
        ):
            raise DriverValidationError()

        environment = _require_tuple(self.non_secret_environment, allow_empty=True)
        if any(type(entry) is not EnvironmentEntry for entry in environment):
            raise DriverValidationError()
        environment_names = tuple(entry.name for entry in environment)
        if environment_names != tuple(sorted(set(environment_names))):
            raise DriverValidationError()

        read_only_mounts = _require_tuple(self.read_only_mounts, allow_empty=True)
        if any(type(mount) is not ReadOnlyMount for mount in read_only_mounts):
            raise DriverValidationError()
        read_only_targets = tuple(str(mount.target) for mount in read_only_mounts)
        if read_only_targets != tuple(sorted(set(read_only_targets))):
            raise DriverValidationError()

        secret_mounts = _require_tuple(self.secret_mounts, allow_empty=True)
        if any(type(mount) is not SecretMount for mount in secret_mounts):
            raise DriverValidationError()
        secret_targets = tuple(str(mount.target) for mount in secret_mounts)
        if secret_targets != tuple(sorted(set(secret_targets))):
            raise DriverValidationError()

        secret_path_bindings = _require_tuple(
            self.secret_path_environment_bindings,
            allow_empty=True,
        )
        if any(
            type(binding) is not SecretPathEnvironmentBinding
            for binding in secret_path_bindings
        ):
            raise DriverValidationError()
        binding_names = tuple(binding.name for binding in secret_path_bindings)
        binding_targets = tuple(str(binding.target) for binding in secret_path_bindings)
        if (
            binding_names != tuple(sorted(set(binding_names)))
            or binding_targets != tuple(sorted(set(binding_targets)))
            or set(binding_names) & set(environment_names)
            or any(secret_targets.count(target) != 1 for target in binding_targets)
        ):
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

        network_bindings = _require_tuple(self.network_bindings, allow_empty=False)
        if any(
            type(binding) is not RuntimeNetworkBinding
            for binding in network_bindings
        ):
            raise DriverValidationError()
        binding_roles = tuple(binding.role for binding in network_bindings)
        binding_names = tuple(binding.network_name for binding in network_bindings)
        if (
            binding_roles != tuple(sorted(set(binding_roles)))
            or binding_roles.count("access") != 1
            or len(binding_names) != len(set(binding_names))
            or tuple(sorted(binding_names)) != self.identity.network_names
        ):
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


class AccessNetworkIdentityError(_FixedDriverError):
    code = "access_network_identity_mismatch"


class AccessNetworkMemberMismatch(_FixedDriverError):
    code = "access_network_member_mismatch"


class PlatformControlIdentityMismatch(_FixedDriverError):
    code = "platform_control_identity_mismatch"


class RuntimeAccessAttachmentMissing(_FixedDriverError):
    code = "runtime_access_attachment_missing"


class AmbiguousNetworkOutcome(_FixedDriverError):
    code = "ambiguous_network_outcome"


class NetworkTransportError(_FixedDriverError):
    code = "network_transport_error"


class RuntimeDriver(Protocol):
    def inspect(self, identity: DriverIdentity) -> DriverInspection: ...

    def launch(self, snapshot: LaunchSnapshot) -> DriverInspection: ...

    def stop(self, identity: DriverIdentity) -> DriverInspection: ...

    def probe(
        self,
        identity: DriverIdentity,
        profile_id: str,
    ) -> HealthObservation: ...


class RuntimeAccessNetworkDriver(Protocol):
    def inspect_access_network(
        self,
        identity: AccessNetworkIdentity,
        platform_control: PlatformControlIdentity,
        runtime: RuntimeAccessMemberIdentity | None,
    ) -> AccessNetworkObservation: ...

    def ensure_access_network(
        self,
        identity: AccessNetworkIdentity,
        platform_control: PlatformControlIdentity,
        runtime: RuntimeAccessMemberIdentity | None = None,
    ) -> AccessNetworkObservation: ...

    def verify_created_access_network(
        self,
        identity: AccessNetworkIdentity,
        platform_control: PlatformControlIdentity,
        runtime: RuntimeAccessMemberIdentity,
    ) -> AccessNetworkObservation: ...

    def verify_active_access_network(
        self,
        identity: AccessNetworkIdentity,
        platform_control: PlatformControlIdentity,
        runtime: RuntimeAccessMemberIdentity,
    ) -> AccessNetworkObservation: ...

    def remove_access_network_if_empty(
        self,
        identity: AccessNetworkIdentity,
    ) -> AccessNetworkObservation: ...


class PlatformControlIdentityProvider(Protocol):
    def resolve_platform_control_identity(self) -> PlatformControlIdentity: ...


class RuntimeAccessNetworkGate(Protocol):
    def verify_active(self, plan: RuntimeAccessNetworkPlan) -> None: ...
