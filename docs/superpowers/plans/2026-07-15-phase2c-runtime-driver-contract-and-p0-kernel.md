# Phase 2C RuntimeDriver Contract and P0 Kernel Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the final driver-neutral RuntimeDriver contract and extract the existing P0 validated Compose launch kernel without enabling a dynamic Docker actor before the complete Task 4 snapshot compiler and validator exist.

**Architecture:** Task 1A is split into observation/health contracts and the final typed LaunchSnapshot/RuntimeDriver protocol. Task 1B then performs a behavior-preserving extraction of the current P0 temporary-snapshot execution kernel. The existing CLI remains the only production caller; `SafeComposeRuntimeDriver` is deliberately deferred to Task 4B.

**Tech Stack:** Python 3.14 standard library, frozen/slots dataclasses, `typing.Protocol`, standard-library `unittest`, Docker Compose command construction under mocks, Git.

## Global Constraints

- Follow the approved design in `docs/superpowers/specs/2026-07-15-phase2c-runtime-driver-contract-design.md`.
- Root-side Task 1 contracts must import and run under `python -S`; do not add Pydantic or any third-party dependency.
- `tools.runtime_driver` import performs no filesystem, environment, Git, Docker, database, network, clock, or subprocess I/O.
- Expected identity and observed state remain separate; never synthesize inspection or health from a launch subprocess return code.
- Do not create `SafeComposeRuntimeDriver` or any dynamic Docker actor in this plan.
- Preserve every existing `tools.compose_runtime` CLI, P0 launch, and emergency `stop/down/ps/logs` behavior.
- Preserve exact image inspection, committed build identity, checkout cleanliness, control-drift checks, temporary snapshot cleanup, and fixed `--no-build --no-deps` launch flags.
- Construct subprocess commands as argument sequences only; no shell interpolation and no Docker SDK.
- No real Docker lifecycle action, exchange connection, real order, exchange write, destructive recovery, database migration, service/port change, or compatibility-service removal.
- Touch only the files explicitly listed by each task. Do not implement Phase 2C Tasks 2–7.

---

## File Structure

- Create `tools/runtime_driver.py`: pure enums, immutable DTOs, strict validation helpers, stable/redacted driver errors, and the `RuntimeDriver` protocol. It contains no concrete runtime-engine adapter.
- Create `tests/test_runtime_driver.py`: pure contract, validation, immutability, protocol, and no-import-I/O tests.
- Modify `tools/compose_runtime.py`: extract one internal validated-snapshot execution kernel while retaining all public functions and return types.
- Modify `tests/test_compose_runtime.py`: prove the legacy launch delegates to the extracted kernel and preserve existing P0/emergency coverage.

---

### Task 1: Driver identity, inspection, health, and error contracts

**Files:**
- Create: `tools/runtime_driver.py`
- Create: `tests/test_runtime_driver.py`

**Interfaces:**
- Produces: `DriverState`, `DriverHealth`, `DriverIdentity`, `DriverInspection`, `HealthProfile`, `HealthObservation`.
- Produces the fixed validation error `DriverValidationError` and fixed action error types: `DriverPolicyError`, `DriverIdentityMismatch`, `DriverObjectOccupied`, `AmbiguousDriverOutcome`, `DriverTransportError`.
- Produces internal strict-construction and validation helpers consumed by Task 2 in the same module.
- Does not produce `LaunchSnapshot` or `RuntimeDriver` until Task 2.

- [ ] **Step 1: Write RED tests for identity, observation, health, errors, and import purity**

Create `tests/test_runtime_driver.py` with these initial tests:

```python
from __future__ import annotations

import dataclasses
import subprocess
import sys
import unittest
from unittest import mock


class RuntimeDriverIdentityTests(unittest.TestCase):
    def valid_identity(self):
        from tools.runtime_driver import DriverIdentity

        return DriverIdentity(
            project_name="runtime-phase2-paper-probe",
            container_name="runtime-phase2-paper-probe-attempt-1",
            instance_id="phase2-spot-paper-probe",
            attempt_id="phase2-spot-paper-probe-attempt-1",
            runtime_spec_digest="a" * 64,
            state_allocation_id="phase2-spot-paper-probe-state",
            image_id="sha256:" + "b" * 64,
            network_names=(
                "runtime-phase2-paper-probe-access",
                "runtime-phase2-paper-probe-private",
            ),
        )

    def test_identity_is_frozen_and_rejects_noncanonical_values(self) -> None:
        identity = self.valid_identity()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.instance_id = "other"

        from tools.runtime_driver import DriverIdentity

        invalid = (
            {"runtime_spec_digest": "A" * 64},
            {"image_id": "repo:tag"},
            {"network_names": ("z-network", "a-network")},
            {"network_names": ("same", "same")},
            {"network_names": []},
            {"project_name": ""},
        )
        original = dataclasses.asdict(identity)
        for mutation in invalid:
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    DriverIdentity(**{**original, **mutation})

    def test_absent_and_partial_observations_are_representable(self) -> None:
        from tools.runtime_driver import DriverHealth, DriverInspection, DriverState

        absent = DriverInspection.absent()
        self.assertEqual(absent.state, DriverState.ABSENT)
        self.assertIsNone(absent.container_id)

        observed = DriverInspection(
            state=DriverState.RUNNING,
            container_id="c" * 64,
            observed_project_name="wrong-project",
            observed_container_name="runtime-phase2-paper-probe-attempt-1",
            observed_instance_id=None,
            observed_attempt_id="wrong-attempt",
            observed_runtime_spec_digest=None,
            observed_state_allocation_id=None,
            observed_image_id="sha256:" + "d" * 64,
            observed_network_names=("unexpected-network",),
            health=DriverHealth.UNKNOWN,
            exit_code=None,
        )
        self.assertIsNone(observed.observed_instance_id)
        self.assertEqual(observed.observed_attempt_id, "wrong-attempt")

    def test_inspection_state_invariants_fail_closed(self) -> None:
        from tools.runtime_driver import DriverHealth, DriverInspection, DriverState

        with self.assertRaises(ValueError):
            DriverInspection(
                state=DriverState.ABSENT,
                container_id="c" * 64,
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
        with self.assertRaises(ValueError):
            DriverInspection(
                state=DriverState.EXITED,
                container_id="c" * 64,
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

    def test_health_contract_uses_argv_and_redacted_failure_code(self) -> None:
        from tools.runtime_driver import DriverHealth, HealthObservation, HealthProfile

        profile = HealthProfile(
            profile_id="freqtrade-ping-v1",
            probe_argv=("freqtrade", "list-exchanges"),
            start_period_seconds=10,
            interval_seconds=5,
            timeout_seconds=5,
            retries=3,
        )
        self.assertEqual(profile.probe_argv[0], "freqtrade")
        with self.assertRaises(ValueError):
            HealthProfile(
                profile_id="freqtrade-ping-v1",
                probe_argv="freqtrade list-exchanges",
                start_period_seconds=10,
                interval_seconds=5,
                timeout_seconds=5,
                retries=3,
            )
        with self.assertRaises(ValueError):
            HealthProfile(
                profile_id="freqtrade-ping-v1",
                probe_argv=("freqtrade",),
                start_period_seconds=0,
                interval_seconds=5,
                timeout_seconds=6,
                retries=1,
            )
        with self.assertRaises(ValueError):
            HealthProfile(
                profile_id="freqtrade-ping-v1",
                probe_argv=("freqtrade",),
                start_period_seconds=0,
                interval_seconds=5,
                timeout_seconds=5,
                retries=True,
            )

        observation = HealthObservation(
            status=DriverHealth.UNHEALTHY,
            attempts=3,
            failure_code="health_timeout",
        )
        self.assertEqual(observation.failure_code, "health_timeout")

    def test_action_errors_have_only_fixed_redacted_messages(self) -> None:
        from tools.runtime_driver import (
            AmbiguousDriverOutcome,
            DriverIdentityMismatch,
            DriverObjectOccupied,
            DriverPolicyError,
            DriverTransportError,
            DriverValidationError,
        )

        expected = {
            DriverValidationError: "driver_validation_error",
            DriverPolicyError: "driver_policy_error",
            DriverIdentityMismatch: "driver_identity_mismatch",
            DriverObjectOccupied: "driver_object_occupied",
            AmbiguousDriverOutcome: "ambiguous_driver_outcome",
            DriverTransportError: "driver_transport_error",
        }
        for error_type, message in expected.items():
            with self.subTest(error_type=error_type):
                self.assertEqual(str(error_type()), message)
                with self.assertRaises(TypeError):
                    error_type("private detail")

    def test_import_performs_no_io(self) -> None:
        script = "import tools.runtime_driver; print('import_ok')"
        completed = subprocess.run(
            [sys.executable, "-S", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "import_ok\n")
```

- [ ] **Step 2: Run RED and verify the failure reason**

Run:

```powershell
python -S -m unittest tests.test_runtime_driver -v
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'tools.runtime_driver'`. Do not accept a syntax error, fixture error, or dependency error as RED.

- [ ] **Step 3: Implement the minimal pure contract**

Create `tools/runtime_driver.py`. Use these exact public names and fields:

```python
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
        if any(_IDENTIFIER.fullmatch(name) is None for name in names):
            raise DriverValidationError()
        if names != tuple(sorted(set(names))):
            raise DriverValidationError()
```

Then add `DriverInspection`, `HealthProfile`, and `HealthObservation` with the exact fields shown in Step 1. Enforce these exact invariants:

```python
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
```

Use the following exact health validation:

```python
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
```

Finally add the five no-argument fixed-message action exception classes. `DriverValidationError` already follows the same public fixed-code rule while subclassing `ValueError`. Use a shared private base for action errors only to avoid repeating `__str__`; it must not accept arbitrary detail:

```python
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
```

- [ ] **Step 4: Run GREEN for Task 1**

Run:

```powershell
python -S -m unittest tests.test_runtime_driver -v
python -S -m unittest tests.test_compose_runtime tests.test_committed_build tests.test_image_provenance -v
git diff --check
```

Expected: all new contract tests pass; the unchanged P0 baseline remains 59/59 green; `git diff --check` prints nothing.

- [ ] **Step 5: Commit Task 1**

```powershell
git add tools/runtime_driver.py tests/test_runtime_driver.py
git commit -m "feat(runtime): define driver identity contract"
```

Expected: one root commit containing only the two listed files.

---

### Task 2: Final LaunchSnapshot value objects and RuntimeDriver protocol

**Files:**
- Modify: `tools/runtime_driver.py`
- Modify: `tests/test_runtime_driver.py`

**Interfaces:**
- Consumes: Task 1 `_StrictValue`, `DriverIdentity`, `DriverInspection`, `HealthProfile`, `HealthObservation`.
- Produces: `EnvironmentEntry`, `ReadOnlyMount`, `WritableStateMount`, `SecretMount`, `RuntimeUser`, `ResourceLimits`, `LaunchSnapshot`.
- Produces exact protocol:

```python
class RuntimeDriver(Protocol):
    def inspect(self, identity: DriverIdentity) -> DriverInspection: ...
    def launch(self, snapshot: LaunchSnapshot) -> DriverInspection: ...
    def stop(self, identity: DriverIdentity) -> DriverInspection: ...
    def probe(
        self,
        identity: DriverIdentity,
        profile: HealthProfile,
    ) -> HealthObservation: ...
```

- Does not produce a concrete driver.

**User-approved Architecture Resolution A / Task 4 handoff:** `LaunchSnapshot` is an
internal post-compilation value and is never accepted or deserialized from a public API,
PostgreSQL, RuntimeSpec JSON, or generic external mappings. Task 2 validation is
structural/canonical only; these dataclasses do not prove provenance or classify secrets.
Task 4 accepts only committed closed AdapterTemplate/policy plus typed RuntimeSpec,
state-allocation, and secret references, and it alone emits argv, environment entries, and
resolved mount sources. Task 4 must:

- restrict read-only sources to compiler-owned or allowlisted material roots and reject
  host-directory exposure, Docker sockets, devices, named pipes, and untyped secrets;
- resolve sources and reject material-root escape through parent components, symlinks,
  junctions, or reparse points;
- derive argv only from a committed executable/argument template, without shell
  interpolation, caller command strings, or embedded secrets;
- enforce a per-template closed environment-name allowlist and source values only from
  typed non-secret fields or committed constants;
- resolve secrets only as provider-produced `SecretMount` values;
- recheck all gates in the final snapshot validator, which the future concrete driver calls
  immediately before mutation.

No `SafeComposeRuntimeDriver` exists until these gates and mutation tests pass. Task 4
acceptance mutations cover parent-directory Docker socket exposure, `ReadOnlyMount`
secret-role bypass, source-root or symlink/junction/reparse escape, shell argv, raw
credential argv, non-allowlisted or raw-secret environment entries, and external
`LaunchSnapshot` deserialization. This records the approved resolution of the review
finding; it is not a claim that Task 2 alone establishes provenance.

- [ ] **Step 1: Extend RED tests for the final snapshot contract**

Append tests that construct nested typed values and pass them through `LaunchSnapshot.model_validate()`:

```python
from pathlib import Path, PurePosixPath


class LaunchSnapshotTests(unittest.TestCase):
    def valid_snapshot_payload(self) -> dict[str, object]:
        from tools.runtime_driver import (
            DriverIdentity,
            EnvironmentEntry,
            HealthProfile,
            ReadOnlyMount,
            ResourceLimits,
            RuntimeUser,
            SecretMount,
            WritableStateMount,
        )

        host_root = Path.cwd().resolve() / "runtime-driver-fixtures"
        identity = DriverIdentity(
            project_name="runtime-phase2-paper-probe",
            container_name="runtime-phase2-paper-probe-attempt-1",
            instance_id="phase2-spot-paper-probe",
            attempt_id="phase2-spot-paper-probe-attempt-1",
            runtime_spec_digest="a" * 64,
            state_allocation_id="phase2-spot-paper-probe-state",
            image_id="sha256:" + "b" * 64,
            network_names=(
                "runtime-phase2-paper-probe-access",
                "runtime-phase2-paper-probe-private",
            ),
        )
        return {
            "identity": identity,
            "argv": ("freqtrade", "trade", "--config", "/runtime/config/config.json"),
            "working_directory": "/freqtrade",
            "non_secret_environment": (
                EnvironmentEntry("HOME", "/runtime/home"),
            ),
            "read_only_mounts": (
                ReadOnlyMount(
                    host_root / "config.json",
                    PurePosixPath("/runtime/config/config.json"),
                ),
            ),
            "state_mount": WritableStateMount(
                host_root / "state",
                PurePosixPath("/runtime/state"),
                "phase2-spot-paper-probe-state",
            ),
            "secret_mounts": (
                SecretMount(
                    host_root / "secrets" / "api-password" / "value",
                    PurePosixPath("/run/secrets/api-password"),
                    "phase2-paper-probe-api-password",
                    "version-1",
                ),
            ),
            "runtime_user": RuntimeUser(1001, 1001, PurePosixPath("/runtime/home")),
            "internal_ports": (8080,),
            "health_profile": HealthProfile(
                profile_id="freqtrade-ping-v1",
                probe_argv=("freqtrade", "list-exchanges"),
                start_period_seconds=10,
                interval_seconds=5,
                timeout_seconds=5,
                retries=3,
            ),
            "resource_limits": ResourceLimits(1000, 536870912, 256),
        }

    def test_launch_snapshot_is_strict_and_forbids_raw_power(self) -> None:
        from tools.runtime_driver import DriverValidationError, LaunchSnapshot

        snapshot = LaunchSnapshot.model_validate(self.valid_snapshot_payload())
        self.assertEqual(snapshot.identity.instance_id, "phase2-spot-paper-probe")
        for field, value in (
            ("compose", {"services": {}}),
            ("host_port", 9000),
            ("privileged", True),
            ("restart", "unless-stopped"),
            ("labels", {"caller": "chosen"}),
        ):
            with self.subTest(field=field):
                with self.assertRaises(DriverValidationError) as raised:
                    LaunchSnapshot.model_validate(
                        {**self.valid_snapshot_payload(), field: value}
                    )
                self.assertEqual(str(raised.exception), "driver_validation_error")

    def test_snapshot_rejects_secret_environment_and_mount_escape_hatches(self) -> None:
        from tools.runtime_driver import (
            DriverValidationError,
            EnvironmentEntry,
            ReadOnlyMount,
        )

        for name in (
            "API_PASSWORD",
            "FREQTRADE__API_SERVER__JWT_SECRET_KEY",
            "FREQTRADE__API_SERVER__WS_TOKEN",
        ):
            with self.subTest(name=name):
                with self.assertRaises(DriverValidationError) as raised:
                    EnvironmentEntry(name, "private")
                self.assertEqual(str(raised.exception), "driver_validation_error")
        with self.assertRaises(DriverValidationError) as raised:
            ReadOnlyMount(
                Path.cwd().resolve() / "var" / "run" / "docker.sock",
                PurePosixPath("/var/run/docker.sock"),
            )
        self.assertEqual(str(raised.exception), "driver_validation_error")

    def test_mounts_reject_lexical_parent_components(self) -> None:
        from tools.runtime_driver import (
            DriverValidationError,
            ReadOnlyMount,
            SecretMount,
            WritableStateMount,
        )

        host_root = Path.cwd().resolve() / "runtime-driver-fixtures"
        mount_factories = (
            ("read_only", lambda source, target: ReadOnlyMount(source, target)),
            (
                "state",
                lambda source, target: WritableStateMount(
                    source,
                    target,
                    "phase2-spot-paper-probe-state",
                ),
            ),
            (
                "secret",
                lambda source, target: SecretMount(
                    source,
                    target,
                    "phase2-paper-probe-api-password",
                    "version-1",
                ),
            ),
        )
        invalid_paths = (
            (
                host_root / "config" / ".." / "config.json",
                PurePosixPath("/runtime/config/config.json"),
            ),
            (
                host_root / "config.json",
                PurePosixPath("/runtime/config/../config.json"),
            ),
        )
        for mount_kind, factory in mount_factories:
            for source, target in invalid_paths:
                with self.subTest(
                    mount_kind=mount_kind,
                    source=source,
                    target=target,
                ):
                    with self.assertRaises(DriverValidationError) as raised:
                        factory(source, target)
                    self.assertEqual(
                        str(raised.exception),
                        "driver_validation_error",
                    )

    def test_snapshot_rejects_colliding_targets(self) -> None:
        from tools.runtime_driver import (
            DriverValidationError,
            LaunchSnapshot,
            WritableStateMount,
        )

        payload = self.valid_snapshot_payload()
        payload["state_mount"] = WritableStateMount(
            Path.cwd().resolve() / "runtime-driver-fixtures" / "state",
            PurePosixPath("/runtime/config/config.json"),
            "phase2-spot-paper-probe-state",
        )
        with self.assertRaises(DriverValidationError) as raised:
            LaunchSnapshot.model_validate(payload)
        self.assertEqual(str(raised.exception), "driver_validation_error")

    def test_snapshot_rejects_state_identity_mismatch(self) -> None:
        from tools.runtime_driver import (
            DriverValidationError,
            LaunchSnapshot,
            WritableStateMount,
        )

        payload = self.valid_snapshot_payload()
        payload["state_mount"] = WritableStateMount(
            Path.cwd().resolve() / "runtime-driver-fixtures" / "state",
            PurePosixPath("/runtime/state"),
            "wrong-allocation",
        )
        with self.assertRaises(DriverValidationError) as raised:
            LaunchSnapshot.model_validate(payload)
        self.assertEqual(str(raised.exception), "driver_validation_error")

    def test_snapshot_rejects_raw_nested_values_and_boolean_limits(self) -> None:
        from tools.runtime_driver import (
            DriverValidationError,
            LaunchSnapshot,
            ResourceLimits,
        )

        payload = self.valid_snapshot_payload()
        payload["identity"] = dataclasses.asdict(payload["identity"])
        with self.assertRaises(DriverValidationError) as raised:
            LaunchSnapshot.model_validate(payload)
        self.assertEqual(str(raised.exception), "driver_validation_error")

        with self.assertRaises(DriverValidationError) as raised:
            ResourceLimits(True, 536870912, 256)
        self.assertEqual(str(raised.exception), "driver_validation_error")

    def test_protocol_has_exact_driver_neutral_methods(self) -> None:
        from tools.runtime_driver import RuntimeDriver

        self.assertEqual(
            {
                name
                for name in RuntimeDriver.__dict__
                if not name.startswith("_")
            },
            {"inspect", "launch", "stop", "probe"},
        )
```

- [ ] **Step 2: Run RED and verify missing names**

Run:

```powershell
python -S -m unittest tests.test_runtime_driver.LaunchSnapshotTests -v
```

Expected: FAIL importing `EnvironmentEntry` or `LaunchSnapshot`. Existing Task 1 tests must still pass when run separately.

- [ ] **Step 3: Implement nested immutable values and LaunchSnapshot**

Append these exact public dataclass fields to `tools/runtime_driver.py`:

```python
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class EnvironmentEntry(_StrictValue):
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class ReadOnlyMount(_StrictValue):
    source: Path
    target: PurePosixPath


@dataclass(frozen=True, slots=True)
class WritableStateMount(_StrictValue):
    source: Path
    target: PurePosixPath
    allocation_id: str


@dataclass(frozen=True, slots=True)
class SecretMount(_StrictValue):
    source: Path
    target: PurePosixPath
    secret_reference_id: str
    version: str


@dataclass(frozen=True, slots=True)
class RuntimeUser(_StrictValue):
    uid: int
    gid: int
    home: PurePosixPath


@dataclass(frozen=True, slots=True)
class ResourceLimits(_StrictValue):
    cpu_millis: int
    memory_bytes: int
    pids_limit: int


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
```

Implement explicit `__post_init__` validation with these exact rules:

- Environment names match `[A-Z_][A-Z0-9_]*`; split the name on `_` and reject any exact segment in `{"KEY", "SECRET", "PASSWORD", "TOKEN", "CREDENTIAL"}`. Values are non-empty strings without control characters.
- Every mount source is an absolute `Path`; every target is an absolute `PurePosixPath`. Reject any source or target whose slash-normalized lowercase parts contain `..` or `docker.sock`; this is lexical validation and performs no filesystem I/O.
- Read-only, writable-state, and secret target paths must be pairwise unique.
- Writable state `allocation_id` must equal `identity.state_allocation_id`.
- Secret reference/version values use `_require_identifier`; secret mounts stay a tuple and may be empty only when the compiled template requires no secrets.
- UID and GID are integers greater than zero; HOME is an absolute POSIX path.
- `cpu_millis`, `memory_bytes`, and `pids_limit` are positive integers.
- `argv` is a non-empty tuple of non-empty strings without control characters.
- `working_directory` is an absolute `PurePosixPath` represented as a string.
- Environment entries are sorted uniquely by name.
- Read-only and secret mounts are sorted uniquely by string target.
- Internal ports are a sorted unique tuple of integers in `1..65535`; an empty tuple is allowed.
- Every nested top-level value is already an instance of its declared type. `model_validate` does not accept raw nested dicts and raises `DriverValidationError` whose fixed public string is `driver_validation_error`; this avoids building a second general validation framework or leaking internal validation detail.
- Boolean values are rejected anywhere the contract requires an integer (`exit_code`, health counts/bounds, UID/GID, resource limits, and ports).

Add the exact four-method protocol after all DTO definitions:

```python
class RuntimeDriver(Protocol):
    def inspect(self, identity: DriverIdentity) -> DriverInspection: ...

    def launch(self, snapshot: LaunchSnapshot) -> DriverInspection: ...

    def stop(self, identity: DriverIdentity) -> DriverInspection: ...

    def probe(
        self,
        identity: DriverIdentity,
        profile: HealthProfile,
    ) -> HealthObservation: ...
```

Do not add a concrete class, Docker imports, subprocess calls, repository paths, or Compose service fields.

- [ ] **Step 4: Run GREEN and the full Task 1A gate**

Run:

```powershell
python -S -m unittest tests.test_runtime_driver -v
python -S -m unittest tests.test_compose_runtime tests.test_committed_build tests.test_image_provenance -v
python -S -c "import tools.runtime_driver; print('import_ok')"
git diff --check
```

Expected: all runtime-driver tests pass; existing P0 baseline remains 59/59; import prints exactly `import_ok`; diff check prints nothing.

- [ ] **Step 5: Commit Task 2**

```powershell
git add tools/runtime_driver.py tests/test_runtime_driver.py
git commit -m "feat(runtime): define immutable launch snapshot"
```

Expected: one commit containing only the two listed files and building on Task 1.

---

### Task 3: Extract the behavior-preserving P0 validated-snapshot kernel

**Files:**
- Modify: `tools/compose_runtime.py`
- Modify: `tests/test_compose_runtime.py`

**Interfaces:**
- Consumes the current private `_validate_launch(...)` and existing legacy service/image/commit inputs.
- Produces private `_run_validated_snapshot_launch(...)` with no public API change.
- Preserves `launch_reviewed_service(service: str, root: Path) -> subprocess.CompletedProcess[str]`.
- Does not import or instantiate `RuntimeDriver`/`LaunchSnapshot`; the concrete adapter remains Task 4B.

- [ ] **Step 1: Write RED delegation and ordering tests**

Add a test that patches the new helper before it exists and proves the legacy launcher supplies only the already-resolved P0 material:

```python
def test_legacy_launch_delegates_to_extracted_snapshot_kernel(self) -> None:
    completed = subprocess.CompletedProcess([], 0, "", "")
    with (
        mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
        mock.patch.object(
            compose_runtime,
            "_run_validated_snapshot_launch",
            return_value=completed,
        ) as kernel,
    ):
        result = compose_runtime._launch_inspected_image(
            "freqtrade",
            self.root,
            MANIFEST,
            INSPECTED_IMAGE.image_id,
            COMMIT_IDENTITY,
        )

    self.assertIs(result, completed)
    arguments = kernel.call_args.kwargs
    self.assertEqual(arguments["service"], "freqtrade")
    self.assertEqual(arguments["root"], self.root)
    self.assertEqual(arguments["manifest"], MANIFEST)
    self.assertEqual(arguments["image_id"], INSPECTED_IMAGE.image_id)
    self.assertEqual(arguments["commit_identity"], COMMIT_IDENTITY)
    self.assertIn("services:", arguments["override"])
```

The RED must fail because `mock.patch.object` cannot find the real helper. Do not use `create=True`; a fabricated mock attribute would let the delegation test pass without production code.

Add a direct helper test using mocked `_validate_launch` and `subprocess.run`:

```python
def test_extracted_kernel_validates_before_fixed_action_and_cleans_snapshot(self) -> None:
    completed = subprocess.CompletedProcess([], 0, "", "")
    events: list[str] = []
    snapshot_path: Path | None = None

    def validate(
        root,
        manifest,
        command_prefix,
        override,
        environment,
        service,
        image_id,
        snapshot,
        commit_identity,
    ) -> None:
        nonlocal snapshot_path
        snapshot_path = snapshot
        events.append("validate")
        snapshot_path.write_text('{"services":{}}\n', encoding="utf-8")

    def run(command, **kwargs):
        events.append("action")
        self.assertIn("--no-build", command)
        self.assertIn("--no-deps", command)
        self.assertEqual(command[-1], "freqtrade")
        return completed

    with (
        mock.patch.object(compose_runtime, "_validate_launch", side_effect=validate),
        mock.patch.object(compose_runtime.subprocess, "run", side_effect=run),
    ):
        result = compose_runtime._run_validated_snapshot_launch(
            service="freqtrade",
            root=self.root,
            manifest=MANIFEST,
            image_id=INSPECTED_IMAGE.image_id,
            commit_identity=COMMIT_IDENTITY,
            override="services: {}\n",
        )

    self.assertIs(result, completed)
    self.assertEqual(events, ["validate", "action"])
    self.assertIsNotNone(snapshot_path)
    self.assertFalse(snapshot_path.exists())
```

- [ ] **Step 2: Run RED and verify the real missing helper**

Run:

```powershell
python -S -m unittest tests.test_compose_runtime.ComposeRuntimeTests.test_legacy_launch_delegates_to_extracted_snapshot_kernel tests.test_compose_runtime.ComposeRuntimeTests.test_extracted_kernel_validates_before_fixed_action_and_cleans_snapshot -v
```

Expected: FAIL because `_run_validated_snapshot_launch` does not exist. Do not accept a passing mock-only test as RED.

- [ ] **Step 3: Extract the internal kernel without changing public behavior**

In `tools/compose_runtime.py`, move only the temporary-directory ownership, `_validate_launch` call, and final fixed Compose action from `_launch_inspected_image` into:

```python
def _run_validated_snapshot_launch(
    *,
    service: str,
    root: Path,
    manifest: dict[str, Any],
    image_id: str,
    commit_identity: CommitIdentity,
    override: str,
) -> subprocess.CompletedProcess[str]:
    render_command = [
        "docker",
        "compose",
        "--project-name",
        "freqtrade-cn",
        "-f",
        str(root / "docker-compose.yml"),
        "-f",
        "-",
    ]
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("FREQTRADE_RUNTIME_") and not key.startswith("COMPOSE_")
    }
    with tempfile.TemporaryDirectory(prefix="compose-launch-") as directory:
        snapshot = Path(directory) / "compose.validated.json"
        _validate_launch(
            root,
            manifest,
            render_command,
            override,
            environment,
            service,
            image_id,
            snapshot,
            commit_identity,
        )
        return subprocess.run(
            [
                "docker",
                "compose",
                "--project-name",
                "freqtrade-cn",
                "-f",
                str(snapshot),
                "up",
                "--detach",
                "--wait",
                "--wait-timeout",
                str(COMPOSE_WAIT_TIMEOUT_SECONDS),
                "--force-recreate",
                "--no-build",
                "--no-deps",
                service,
            ],
            cwd=root,
            env=environment,
            input=None,
            text=True,
            capture_output=False,
            check=False,
        )
```

Reduce `_launch_inspected_image` to identity/override preparation plus delegation:

```python
def _launch_inspected_image(
    service: str,
    root: Path,
    manifest: dict[str, Any],
    image_id: str,
    commit_identity: CommitIdentity,
) -> subprocess.CompletedProcess[str]:
    identity = verify_runtime(root, manifest, verify_platform_secrets=False)
    override = _launch_override(manifest, identity, service, image_id)
    return _run_validated_snapshot_launch(
        service=service,
        root=root,
        manifest=manifest,
        image_id=image_id,
        commit_identity=commit_identity,
        override=override,
    )
```

Do not change `_validate_launch`, `launch_reviewed_service`, `run_compose`, argument parsing, environment filtering, emergency functions, error messages, Compose flags, timeouts, or return types.

- [ ] **Step 4: Run GREEN and the whole Task 1A/1B acceptance gate**

Run:

```powershell
python -S -m unittest tests.test_runtime_driver tests.test_compose_runtime tests.test_committed_build tests.test_image_provenance -v
python -S -m unittest discover -s tests -p "test_*.py"
git diff --check
git status --short
```

Expected:

- all focused tests pass;
- the full root suite passes with only documented platform/environment skips;
- no real Docker lifecycle action runs because action boundaries remain mocked/skipped;
- diff check prints nothing;
- status shows only the two Task 3 files before commit.

- [ ] **Step 5: Commit Task 3**

```powershell
git add tools/compose_runtime.py tests/test_compose_runtime.py
git commit -m "refactor(runtime): extract validated compose launch kernel"
```

Expected: one behavior-preserving root commit containing only the two listed files.

---

## Whole-plan acceptance

After all three task reviews are clean, run:

```powershell
python -S -m unittest tests.test_runtime_driver tests.test_compose_runtime tests.test_committed_build tests.test_image_provenance -v
python -S -m unittest discover -s tests -p "test_*.py"
python -S -c "import tools.runtime_driver; print('import_ok')"
$base = git merge-base origin/main HEAD
git diff --check $base HEAD
git status --short
```

Acceptance requires:

1. exact immutable contracts and strict unknown-field rejection;
2. no concrete driver or new dynamic Docker authority;
3. import purity under `python -S`;
4. existing P0/emergency behavior unchanged;
5. one extracted kernel used by the legacy launch path;
6. full root tests green;
7. clean worktree after commits;
8. independent per-task and whole-branch reviews with no open Critical or Important finding.
