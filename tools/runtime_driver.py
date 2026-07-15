from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from enum import StrEnum
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
