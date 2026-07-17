from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Callable, Protocol

from tools.runtime_driver import (
    AccessNetworkIdentityError,
    AccessNetworkMemberMismatch,
    AmbiguousDriverOutcome,
    AmbiguousNetworkOutcome,
    DriverHealth,
    DriverIdentity,
    DriverIdentityMismatch,
    DriverInspection,
    DriverPolicyError,
    DriverState,
    DriverTransportError,
    DriverValidationError,
    HealthObservation,
    HealthProfile,
    LaunchSnapshot,
    NetworkTransportError,
    PlatformControlIdentityMismatch,
    RuntimeAccessAttachmentMissing,
    RuntimeAccessNetworkGate,
    RuntimeAccessNetworkPlan,
    RuntimeDriver,
)
from tools.runtime_supervisor.domain import (
    ReconciliationAction,
    ReconciliationDecision,
    ReconciliationOutcome,
    identity_matches,
)
from tools.runtime_supervisor.health import (
    health_deadline,
    health_probe_not_before,
    health_profile_digest,
)
from tools.runtime_supervisor.offline_identity import (
    OfflineIdentityStorageError,
    OfflineIdentityValidationError,
    OfflineRuntimeIdentity,
)


_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {"pending", "validating", "launching", "healthy", "stopping"}
)
_TERMINAL_ATTEMPT_STATUSES = frozenset({"stopped", "failed"})
_START_TRANSITIONABLE_ATTEMPT_STATUSES = frozenset(
    {"pending", "validating", "launching"}
)
_PRESENT_ACTIVE_STATES = frozenset(
    {DriverState.CREATED, DriverState.STARTING, DriverState.RUNNING}
)
_TERMINAL_STATES = frozenset({DriverState.ABSENT, DriverState.EXITED})
_HEALTH_RESERVED = "health_probe_reserved"
_HEALTH_HEALTHY = "health_probe_healthy"
_HEALTH_UNHEALTHY = "health_probe_unhealthy"
_HEALTH_INTERRUPTED = "health_probe_interrupted"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class PersistedHealthResultLike(Protocol):
    profile_id: str
    profile_digest: str
    deadline_at: datetime
    next_probe_not_before: datetime
    observed_at: datetime
    attempts: int
    result_code: str
    last_failure_code: str | None


class LatestAttemptLike(Protocol):
    attempt_id: str
    status: object
    started_at: datetime | None
    health_result: PersistedHealthResultLike | None
    runtime_spec_payload_digest: str
    resolved_material: object


class AttemptViewLike(Protocol):
    started_at: datetime | None


class CurrentLeaseLike(Protocol):
    job_id: str
    instance_id: str
    expected_instance_version: int
    lease_owner: str | None
    lease_generation: int


class RepositoryPort(Protocol):
    def get_latest_attempt_material(
        self, instance_id: str
    ) -> LatestAttemptLike | None: ...

    def prepare_attempt_id(
        self,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
    ) -> str: ...

    def begin_attempt(
        self,
        job_id: str,
        attempt_id: str,
        resolved_material: object,
        lease_owner: str,
        lease_generation: int,
    ) -> AttemptViewLike: ...

    def assert_current_lease(
        self,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
    ) -> CurrentLeaseLike: ...

    def reserve_health_probe(
        self,
        job_id: str,
        attempt_id: str,
        profile_id: str,
        profile_digest: str,
        deadline_at: datetime,
        next_probe_not_before: datetime,
        lease_owner: str,
        lease_generation: int,
    ) -> PersistedHealthResultLike: ...

    def record_health_observation(
        self,
        job_id: str,
        attempt_id: str,
        result_code: str,
        attempts: int,
        last_failure_code: str | None,
        lease_owner: str,
        lease_generation: int,
    ) -> object: ...

    def record_reconciliation_blocked(
        self,
        job_id: str,
        attempt_id: str | None,
        failure_code: str,
        lease_owner: str,
        lease_generation: int,
    ) -> object: ...

    def record_healthy(
        self,
        job_id: str,
        attempt_id: str,
        lease_owner: str,
        lease_generation: int,
    ) -> object: ...

    def record_failed(
        self,
        job_id: str,
        attempt_id: str,
        failure_code: str,
        lease_owner: str,
        lease_generation: int,
    ) -> object: ...

    def record_stopped(
        self,
        job_id: str,
        attempt_id: str,
        exit_code: int | None,
        lease_owner: str,
        lease_generation: int,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ReconciliationJob:
    job_id: str
    instance_id: str
    action: ReconciliationAction
    lease_owner: str
    lease_generation: int
    instance_revision: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", ReconciliationAction(self.action))
        if (
            type(self.job_id) is not str
            or not self.job_id
            or type(self.instance_id) is not str
            or not self.instance_id
            or type(self.lease_owner) is not str
            or not self.lease_owner
            or type(self.lease_generation) is not int
            or self.lease_generation <= 0
            or type(self.instance_revision) is not int
            or self.instance_revision < 0
        ):
            raise ValueError("invalid reconciliation job")


@dataclass(frozen=True, slots=True)
class LaunchProvenance:
    launch_authority_digest: str
    root_commit: str
    backend_commit: str
    frontend_commit: str
    strategies_commit: str

    def __post_init__(self) -> None:
        if (
            type(self.launch_authority_digest) is not str
            or _DIGEST.fullmatch(self.launch_authority_digest) is None
            or any(
                type(commit) is not str or _COMMIT.fullmatch(commit) is None
                for commit in (
                    self.root_commit,
                    self.backend_commit,
                    self.frontend_commit,
                    self.strategies_commit,
                )
            )
        ):
            raise ValueError("invalid launch provenance")


@dataclass(frozen=True, slots=True)
class RevalidatedAttempt:
    identity: DriverIdentity
    resolved_material: object
    provenance: LaunchProvenance


class PreparationPort(Protocol):
    def recover_identity(self, latest: LatestAttemptLike) -> DriverIdentity: ...

    def revalidate(
        self,
        job: ReconciliationJob,
        attempt_id: str,
        latest: LatestAttemptLike | None,
    ) -> RevalidatedAttempt: ...

    def resolve_state(self, revalidated: RevalidatedAttempt) -> object: ...

    def resolve_secrets(
        self, revalidated: RevalidatedAttempt
    ) -> AbstractContextManager[object]: ...

    def compile_snapshot(
        self,
        revalidated: RevalidatedAttempt,
        state: object,
        secrets: object,
    ) -> LaunchSnapshot: ...

    def revalidate_for_runtime_action(
        self,
        revalidated: RevalidatedAttempt,
        snapshot: LaunchSnapshot,
    ) -> None: ...

    def compile_access_network_plan(
        self,
        revalidated: RevalidatedAttempt,
        container_id: str,
    ) -> RuntimeAccessNetworkPlan: ...

    def resolve_health_profile(
        self,
        revalidated: RevalidatedAttempt,
    ) -> HealthProfile: ...

    def compile_offline_identity(
        self,
        revalidated: RevalidatedAttempt,
        observed: DriverInspection,
        *,
        instance_revision: int,
        lease_generation: int,
    ) -> OfflineRuntimeIdentity: ...


class OfflineIdentityPublisher(Protocol):
    def publish(self, identity: OfflineRuntimeIdentity) -> OfflineRuntimeIdentity: ...


class RuntimeSupervisorReconciler:
    def __init__(
        self,
        repository: RepositoryPort,
        preparation: PreparationPort,
        driver: RuntimeDriver,
        access_network_gate: RuntimeAccessNetworkGate,
        offline_identity_publisher: OfflineIdentityPublisher,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._preparation = preparation
        self._driver = driver
        self._access_network_gate = access_network_gate
        self._offline_identity_publisher = offline_identity_publisher
        self._clock = clock or (lambda: datetime.now(UTC))

    def reconcile(self, job: ReconciliationJob) -> ReconciliationOutcome:
        try:
            return self._reconcile(job)
        except DriverTransportError:
            return self._block(job, None, "runtime_transport_error")
        except DriverIdentityMismatch:
            return self._block(job, None, "runtime_identity_mismatch")
        except DriverPolicyError:
            return self._block(job, None, "runtime_policy_invalid")

    def _reconcile(self, job: ReconciliationJob) -> ReconciliationOutcome:
        if not self._lease_matches_job(job):
            latest = self._repository.get_latest_attempt_material(job.instance_id)
            attempt_id = None
            if latest is not None:
                status = _status_value(latest.status)
                if status in _ACTIVE_ATTEMPT_STATUSES:
                    attempt_id = latest.attempt_id
            return self._block(job, attempt_id, "instance_revision_mismatch")
        latest = self._repository.get_latest_attempt_material(job.instance_id)
        if latest is None:
            if job.action is ReconciliationAction.STOP:
                return self._block(job, None, "stop_without_active_attempt")
            return self._launch_candidate(job, None, None)

        status = _status_value(latest.status)
        active_binding = (
            latest.attempt_id if status in _ACTIVE_ATTEMPT_STATUSES else None
        )
        try:
            expected = self._preparation.recover_identity(latest)
        except DriverTransportError:
            return self._block(job, active_binding, "runtime_transport_error")
        except DriverIdentityMismatch:
            return self._block(job, active_binding, "runtime_identity_mismatch")
        except DriverPolicyError:
            return self._block(job, active_binding, "runtime_policy_invalid")
        if (
            expected.attempt_id != latest.attempt_id
            or expected.instance_id != job.instance_id
            or expected.runtime_spec_digest != latest.runtime_spec_payload_digest
        ):
            return self._block(job, active_binding, "persisted_identity_mismatch")

        if status in _TERMINAL_ATTEMPT_STATUSES:
            if job.action is ReconciliationAction.STOP:
                return self._block(job, None, "stop_without_active_attempt")
            observed = self._driver.inspect(expected)
            if observed.state is not DriverState.ABSENT:
                return self._block(job, None, "terminal_runtime_present")
            return self._launch_candidate(job, latest, expected)
        if status not in _ACTIVE_ATTEMPT_STATUSES:
            return self._block(job, None, "attempt_status_invalid")

        try:
            revalidated = self._preparation.revalidate(
                job, latest.attempt_id, latest
            )
        except DriverTransportError:
            return self._block(job, active_binding, "runtime_transport_error")
        except DriverIdentityMismatch:
            return self._block(job, active_binding, "runtime_identity_mismatch")
        except DriverPolicyError:
            return self._block(job, active_binding, "runtime_policy_invalid")
        if revalidated.identity != expected:
            return self._block(job, active_binding, "revalidated_identity_mismatch")

        if revalidated.resolved_material != latest.resolved_material:
            return self._block(
                job,
                latest.attempt_id,
                "revalidated_material_mismatch",
            )
        if (
            job.action is ReconciliationAction.START
            and status not in _START_TRANSITIONABLE_ATTEMPT_STATUSES
        ):
            return self._block(
                job,
                latest.attempt_id,
                "active_attempt_status_inconsistent",
            )
        try:
            return self._reconcile_active(job, revalidated, latest)
        except DriverTransportError:
            return self._block(job, latest.attempt_id, "runtime_transport_error")
        except DriverIdentityMismatch:
            return self._block(
                job,
                latest.attempt_id,
                "runtime_identity_mismatch",
                ReconciliationDecision.IDENTITY_MISMATCH,
            )
        except DriverPolicyError:
            return self._block(job, latest.attempt_id, "runtime_policy_invalid")

    def _reconcile_active(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        latest: LatestAttemptLike,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        try:
            observed = self._driver.inspect(identity)
        except DriverTransportError:
            if job.action is ReconciliationAction.START:
                return self._continue_ambiguous_launch(
                    job,
                    revalidated,
                    latest.started_at,
                    "runtime_transport_error",
                )
            return self._block(
                job,
                identity.attempt_id,
                "runtime_transport_error",
            )
        except DriverIdentityMismatch:
            return self._block(
                job,
                identity.attempt_id,
                "runtime_identity_mismatch",
                ReconciliationDecision.IDENTITY_MISMATCH,
            )
        except DriverPolicyError:
            return self._block(job, identity.attempt_id, "runtime_policy_invalid")
        if observed.state is DriverState.UNKNOWN:
            return self._block(job, identity.attempt_id, "runtime_identity_unknown")
        if observed.state is not DriverState.ABSENT and not _runtime_matches(
            revalidated, observed
        ):
            return self._block(
                job,
                identity.attempt_id,
                "runtime_identity_mismatch",
                ReconciliationDecision.IDENTITY_MISMATCH,
            )

        if job.action is ReconciliationAction.STOP:
            if observed.state is DriverState.ABSENT:
                return self._record_stopped(
                    job,
                    identity.attempt_id,
                    None,
                    ReconciliationDecision.ALREADY_ABSENT,
                )
            return self._stop_exact(job, revalidated, observed)

        if observed.state is DriverState.ABSENT:
            if latest.health_result is not None:
                return self._record_terminal_failure(
                    job,
                    identity.attempt_id,
                    self._persisted_terminal_failure_code(revalidated, latest),
                )
            return self._continue_ambiguous_launch(
                job,
                revalidated,
                latest.started_at,
                "active_attempt_absent",
            )
        if observed.state is DriverState.EXITED:
            return self._record_terminal_failure(
                job,
                identity.attempt_id,
                self._persisted_terminal_failure_code(revalidated, latest),
            )
        return self._health_step(
            job,
            revalidated,
            observed,
            latest.started_at,
            latest.health_result,
        )

    def _launch_candidate(
        self,
        job: ReconciliationJob,
        terminal_latest: LatestAttemptLike | None,
        terminal_identity: DriverIdentity | None,
    ) -> ReconciliationOutcome:
        attempt_id = self._repository.prepare_attempt_id(
            job.job_id,
            job.lease_owner,
            job.lease_generation,
        )
        revalidated = self._preparation.revalidate(job, attempt_id, terminal_latest)
        if (
            revalidated.identity.attempt_id != attempt_id
            or revalidated.identity.instance_id != job.instance_id
        ):
            return self._block(job, None, "candidate_identity_mismatch")
        return self._launch_prepared(
            job,
            revalidated,
            attempt_id,
            terminal_latest,
            terminal_identity,
        )

    def _launch_prepared(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        prepared_attempt_id: str,
        terminal_latest: LatestAttemptLike | None,
        terminal_identity: DriverIdentity | None,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        begun_attempt_id: str | None = None
        pending_failure: tuple[
            str | None,
            str,
            ReconciliationDecision,
        ] | None = None
        observed: DriverInspection | None = None
        ambiguous_launch = False
        started_at: datetime | None = None
        try:
            state = self._preparation.resolve_state(revalidated)
            with self._preparation.resolve_secrets(revalidated) as secrets:
                snapshot = self._preparation.compile_snapshot(
                    revalidated,
                    state,
                    secrets,
                )
                if type(snapshot) is not LaunchSnapshot:
                    raise TypeError("launch snapshot must be a LaunchSnapshot")
                if snapshot.identity != identity:
                    pending_failure = (
                        None,
                        "compiled_snapshot_identity_mismatch",
                        ReconciliationDecision.IDENTITY_MISMATCH,
                    )
                elif (
                    snapshot.launch_authority_digest
                    != revalidated.provenance.launch_authority_digest
                ):
                    pending_failure = (
                        None,
                        "compiled_snapshot_authority_mismatch",
                        ReconciliationDecision.IDENTITY_MISMATCH,
                    )

                if pending_failure is None:
                    candidate_observed = self._driver.inspect(identity)
                    if candidate_observed.state is not DriverState.ABSENT:
                        pending_failure = (
                            None,
                            "candidate_runtime_occupied",
                            ReconciliationDecision.FAIL_LATCHED,
                        )
                if pending_failure is None and terminal_latest is not None:
                    if terminal_identity is None:
                        raise RuntimeError("terminal identity is required")
                    predecessor = self._driver.inspect(terminal_identity)
                    if predecessor.state is not DriverState.ABSENT:
                        pending_failure = (
                            None,
                            "terminal_runtime_present",
                            ReconciliationDecision.FAIL_LATCHED,
                        )

                if pending_failure is None:
                    begun = self._repository.begin_attempt(
                        job.job_id,
                        prepared_attempt_id,
                        revalidated.resolved_material,
                        job.lease_owner,
                        job.lease_generation,
                    )
                    begun_attempt_id = identity.attempt_id
                    started_at = begun.started_at
                    if not _is_utc_datetime(started_at):
                        pending_failure = (
                            identity.attempt_id,
                            "attempt_start_time_invalid",
                            ReconciliationDecision.FAIL_LATCHED,
                        )
                    elif not self._lease_matches_job(job):
                        pending_failure = (
                            identity.attempt_id,
                            "instance_revision_mismatch",
                            ReconciliationDecision.FAIL_LATCHED,
                        )
                    else:
                        try:
                            self._preparation.revalidate_for_runtime_action(
                                revalidated,
                                snapshot,
                            )
                            observed = self._driver.launch(snapshot)
                        except AmbiguousDriverOutcome:
                            ambiguous_launch = True
        except DriverTransportError:
            return self._block(job, begun_attempt_id, "runtime_transport_error")
        except DriverIdentityMismatch:
            return self._block(
                job,
                begun_attempt_id,
                "runtime_identity_mismatch",
                ReconciliationDecision.IDENTITY_MISMATCH,
            )
        except DriverPolicyError:
            return self._block(job, begun_attempt_id, "runtime_policy_invalid")

        try:
            if pending_failure is not None:
                attempt_id, failure_code, decision = pending_failure
                return self._block(job, attempt_id, failure_code, decision)
            if not _is_utc_datetime(started_at):
                raise RuntimeError("begun attempt requires UTC start time")
            if ambiguous_launch:
                try:
                    observed = self._driver.inspect(identity)
                except DriverTransportError:
                    return self._continue_ambiguous_launch(
                        job,
                        revalidated,
                        started_at,
                        "ambiguous_launch_transport",
                    )
                except (DriverIdentityMismatch, DriverPolicyError):
                    return self._block(
                        job,
                        identity.attempt_id,
                        "ambiguous_launch_identity_mismatch",
                        ReconciliationDecision.IDENTITY_MISMATCH,
                    )
                if observed.state is DriverState.ABSENT:
                    return self._continue_ambiguous_launch(
                        job,
                        revalidated,
                        started_at,
                        "ambiguous_launch_absent",
                    )
            if observed is None:
                raise RuntimeError("launch observation is required")
            return self._record_launch_observation(
                job,
                revalidated,
                observed,
                started_at,
            )
        except DriverTransportError:
            return self._block(job, begun_attempt_id, "runtime_transport_error")
        except DriverIdentityMismatch:
            return self._block(
                job,
                begun_attempt_id,
                "runtime_identity_mismatch",
                ReconciliationDecision.IDENTITY_MISMATCH,
            )
        except DriverPolicyError:
            return self._block(job, begun_attempt_id, "runtime_policy_invalid")

    def _record_launch_observation(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        observed: DriverInspection,
        started_at: datetime,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        if observed.state is DriverState.UNKNOWN:
            return self._block(job, identity.attempt_id, "runtime_identity_unknown")
        if observed.state is not DriverState.ABSENT and not _runtime_matches(
            revalidated, observed
        ):
            return self._block(
                job,
                identity.attempt_id,
                "runtime_identity_mismatch",
                ReconciliationDecision.IDENTITY_MISMATCH,
            )
        if observed.state is DriverState.ABSENT:
            return self._record_terminal_failure(
                job,
                identity.attempt_id,
                "runtime_launch_failed",
            )
        if observed.state is DriverState.EXITED:
            return self._record_terminal_failure(
                job,
                identity.attempt_id,
                "runtime_launch_failed",
            )
        return self._health_step(job, revalidated, observed, started_at, None)

    def _health_step(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        observed: DriverInspection,
        started_at: datetime | None,
        evidence: PersistedHealthResultLike | None,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        if observed.state not in _PRESENT_ACTIVE_STATES or not _runtime_matches(
            revalidated, observed
        ):
            return self._block(job, identity.attempt_id, "health_runtime_invalid")
        if not _is_utc_datetime(started_at):
            return self._block(job, identity.attempt_id, "attempt_start_time_invalid")
        offline_failure = self._publish_offline(job, revalidated, observed)
        if offline_failure is not None:
            return offline_failure

        profile = self._preparation.resolve_health_profile(revalidated)
        if type(profile) is not HealthProfile:
            return self._block(job, identity.attempt_id, "health_profile_invalid")
        try:
            profile_digest = health_profile_digest(profile)
            deadline = health_deadline(started_at, profile)
        except DriverValidationError:
            return self._block(job, identity.attempt_id, "health_profile_invalid")
        if evidence is not None and not _health_evidence_matches(
            evidence,
            profile,
            profile_digest,
            deadline,
        ):
            return self._block(job, identity.attempt_id, "health_evidence_mismatch")

        attempts = 0 if evidence is None else evidence.attempts
        result_code = None if evidence is None else evidence.result_code
        if result_code == _HEALTH_RESERVED:
            self._repository.record_health_observation(
                job.job_id,
                identity.attempt_id,
                _HEALTH_INTERRUPTED,
                attempts,
                "health_probe_interrupted",
                job.lease_owner,
                job.lease_generation,
            )
            result_code = _HEALTH_INTERRUPTED

        if result_code == _HEALTH_HEALTHY:
            return self._adopt_after_health(job, revalidated, observed)
        if attempts >= profile.retries:
            if result_code != _HEALTH_UNHEALTHY:
                return self._block(
                    job,
                    identity.attempt_id,
                    "health_outcome_ambiguous",
                )
            return self._terminate_failed_runtime(
                job,
                revalidated,
                "health_retries_exhausted",
            )

        ordinal = attempts + 1
        try:
            not_before = health_probe_not_before(started_at, profile, ordinal)
        except DriverValidationError:
            return self._block(job, identity.attempt_id, "health_schedule_invalid")
        now = self._clock()
        if not _is_utc_datetime(now):
            return self._block(job, identity.attempt_id, "health_clock_invalid")
        if now < not_before:
            return _outcome(
                job,
                ReconciliationDecision.CONTINUE_OBSERVING,
                identity.attempt_id,
            )
        if now + timedelta(seconds=profile.timeout_seconds) > deadline:
            return self._block(
                job,
                identity.attempt_id,
                "health_window_expired_without_proof",
            )

        reserved = self._repository.reserve_health_probe(
            job.job_id,
            identity.attempt_id,
            profile.profile_id,
            profile_digest,
            deadline,
            not_before,
            job.lease_owner,
            job.lease_generation,
        )
        if reserved.attempts != ordinal or reserved.result_code != _HEALTH_RESERVED:
            return self._block(job, identity.attempt_id, "health_reservation_invalid")

        if observed.state is not DriverState.RUNNING:
            observation = HealthObservation(
                DriverHealth.UNHEALTHY,
                1,
                "health_object_not_running",
            )
        else:
            if not self._lease_matches_job(job):
                return self._block(
                    job,
                    identity.attempt_id,
                    "instance_revision_mismatch",
                )
            try:
                observation = self._driver.probe(identity, profile.profile_id)
            except DriverIdentityMismatch:
                return self._block(
                    job,
                    identity.attempt_id,
                    "health_runtime_identity_changed",
                    ReconciliationDecision.IDENTITY_MISMATCH,
                )
            except DriverPolicyError:
                return self._block(
                    job,
                    identity.attempt_id,
                    "health_runtime_policy_invalid",
                )
            except DriverTransportError:
                return self._block(
                    job,
                    identity.attempt_id,
                    "health_runtime_transport_error",
                )
        return self._record_health_probe(
            job,
            revalidated,
            observed,
            profile,
            deadline,
            ordinal,
            observation,
        )

    def _record_health_probe(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        observed: DriverInspection,
        profile: HealthProfile,
        deadline: datetime,
        ordinal: int,
        observation: HealthObservation,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        try:
            if type(observation) is not HealthObservation:
                raise DriverValidationError()
            observation.__post_init__()
        except Exception:
            return self._block(
                job,
                identity.attempt_id,
                "health_observation_invalid",
            )
        if observation.attempts != 1:
            return self._block(job, identity.attempt_id, "health_observation_invalid")
        if (
            observation.status is DriverHealth.HEALTHY
            and observation.failure_code is None
        ):
            result_code = _HEALTH_HEALTHY
        elif (
            observation.status is DriverHealth.UNHEALTHY
            and observation.failure_code is not None
        ):
            result_code = _HEALTH_UNHEALTHY
        elif observation.status is DriverHealth.UNKNOWN:
            self._repository.record_health_observation(
                job.job_id,
                identity.attempt_id,
                "health_probe_unknown",
                ordinal,
                observation.failure_code or "health_probe_unknown",
                job.lease_owner,
                job.lease_generation,
            )
            return self._block(job, identity.attempt_id, "health_outcome_ambiguous")
        else:
            return self._block(job, identity.attempt_id, "health_observation_invalid")

        if result_code == _HEALTH_HEALTHY:
            completed_at = self._clock()
            if not _is_utc_datetime(completed_at) or completed_at > deadline:
                self._repository.record_health_observation(
                    job.job_id,
                    identity.attempt_id,
                    "health_probe_unknown",
                    ordinal,
                    "health_probe_completed_after_deadline",
                    job.lease_owner,
                    job.lease_generation,
                )
                return self._block(
                    job,
                    identity.attempt_id,
                    "health_probe_completed_after_deadline",
                )
        self._repository.record_health_observation(
            job.job_id,
            identity.attempt_id,
            result_code,
            ordinal,
            observation.failure_code,
            job.lease_owner,
            job.lease_generation,
        )
        if result_code == _HEALTH_HEALTHY:
            return self._adopt_after_health(job, revalidated, observed)
        if ordinal < profile.retries:
            return _outcome(
                job,
                ReconciliationDecision.CONTINUE_OBSERVING,
                identity.attempt_id,
            )
        return self._terminate_failed_runtime(
            job,
            revalidated,
            "health_retries_exhausted",
        )

    def _continue_ambiguous_launch(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        started_at: datetime | None,
        failure_code: str,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        if not _is_utc_datetime(started_at):
            return self._block(job, identity.attempt_id, failure_code)
        profile = self._preparation.resolve_health_profile(revalidated)
        if type(profile) is not HealthProfile:
            return self._block(job, identity.attempt_id, failure_code)
        try:
            deadline = health_deadline(started_at, profile)
        except DriverValidationError:
            return self._block(job, identity.attempt_id, failure_code)
        now = self._clock()
        if not _is_utc_datetime(now) or now >= deadline:
            return self._block(job, identity.attempt_id, failure_code)
        return _outcome(
            job,
            ReconciliationDecision.CONTINUE_OBSERVING,
            identity.attempt_id,
            failure_code,
        )

    def _adopt_after_health(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        probed_observation: DriverInspection,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        try:
            current = self._driver.inspect(identity)
        except DriverIdentityMismatch:
            return self._block(
                job,
                identity.attempt_id,
                "health_postcondition_identity_changed",
                ReconciliationDecision.IDENTITY_MISMATCH,
            )
        except DriverPolicyError:
            return self._block(
                job,
                identity.attempt_id,
                "health_postcondition_policy_invalid",
            )
        except DriverTransportError:
            return self._block(
                job,
                identity.attempt_id,
                "health_postcondition_transport_error",
            )
        if (
            current.state is not DriverState.RUNNING
            or not _runtime_matches(revalidated, current)
            or current.container_id != probed_observation.container_id
        ):
            return self._block(
                job,
                identity.attempt_id,
                "health_postcondition_changed",
            )
        offline_failure = self._publish_offline(job, revalidated, current)
        if offline_failure is not None:
            return offline_failure
        if not self._verify_active_access_network(revalidated, current):
            return self._block(
                job,
                identity.attempt_id,
                "runtime_access_network_invalid",
            )
        self._repository.record_healthy(
            job.job_id,
            identity.attempt_id,
            job.lease_owner,
            job.lease_generation,
        )
        return _outcome(job, ReconciliationDecision.ADOPT, identity.attempt_id)

    def _publish_offline(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        observed: DriverInspection,
    ) -> ReconciliationOutcome | None:
        try:
            identity = self._preparation.compile_offline_identity(
                revalidated,
                observed,
                instance_revision=job.instance_revision,
                lease_generation=job.lease_generation,
            )
            if type(identity) is not OfflineRuntimeIdentity:
                raise OfflineIdentityValidationError()
            if (
                identity.instance_id != revalidated.identity.instance_id
                or identity.attempt_id != revalidated.identity.attempt_id
                or identity.container_id != observed.container_id
                or identity.project_name != revalidated.identity.project_name
                or identity.container_name != revalidated.identity.container_name
                or identity.image_id != revalidated.identity.image_id
                or identity.runtime_spec_digest
                != revalidated.identity.runtime_spec_digest
                or identity.state_allocation_id
                != revalidated.identity.state_allocation_id
                or identity.network_names != revalidated.identity.network_names
                or identity.instance_revision != job.instance_revision
                or identity.lease_generation != job.lease_generation
                or identity.launch_authority_digest
                != revalidated.provenance.launch_authority_digest
                or identity.root_commit != revalidated.provenance.root_commit
                or identity.backend_commit != revalidated.provenance.backend_commit
                or identity.frontend_commit != revalidated.provenance.frontend_commit
                or identity.strategies_commit
                != revalidated.provenance.strategies_commit
                or observed.observed_launch_authority_digest
                != revalidated.provenance.launch_authority_digest
            ):
                raise OfflineIdentityValidationError()
            if not self._lease_matches_job(job):
                return self._block(
                    job,
                    revalidated.identity.attempt_id,
                    "instance_revision_mismatch",
                )
            published = self._offline_identity_publisher.publish(identity)
            if published != identity:
                raise OfflineIdentityStorageError()
        except (OfflineIdentityStorageError, OfflineIdentityValidationError):
            return self._terminate_failed_runtime(
                job,
                revalidated,
                "offline_identity_publish_failed",
            )
        return None

    def _terminate_failed_runtime(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        failure_code: str,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        try:
            observed = self._driver.inspect(identity)
        except (DriverIdentityMismatch, DriverPolicyError):
            return self._block(
                job,
                identity.attempt_id,
                f"{failure_code}_identity_mismatch",
            )
        except DriverTransportError:
            return self._block(
                job,
                identity.attempt_id,
                f"{failure_code}_transport_error",
            )
        if observed.state is DriverState.UNKNOWN:
            return self._block(job, identity.attempt_id, f"{failure_code}_ambiguous")
        if observed.state is not DriverState.ABSENT and not _runtime_matches(
            revalidated, observed
        ):
            return self._block(
                job,
                identity.attempt_id,
                f"{failure_code}_identity_mismatch",
            )
        terminal = observed
        if observed.state in _PRESENT_ACTIVE_STATES:
            if not self._lease_matches_job(job):
                return self._block(
                    job,
                    identity.attempt_id,
                    "instance_revision_mismatch",
                )
            try:
                terminal = self._driver.stop(identity)
            except AmbiguousDriverOutcome:
                try:
                    terminal = self._driver.inspect(identity)
                except (
                    DriverIdentityMismatch,
                    DriverPolicyError,
                    DriverTransportError,
                ):
                    return self._block(
                        job,
                        identity.attempt_id,
                        f"{failure_code}_stop_unresolved",
                    )
            except (DriverIdentityMismatch, DriverPolicyError, DriverTransportError):
                return self._block(
                    job,
                    identity.attempt_id,
                    f"{failure_code}_stop_unresolved",
                )
        if terminal.state not in _TERMINAL_STATES or (
            terminal.state is DriverState.EXITED
            and not _runtime_matches(revalidated, terminal)
        ):
            return self._block(
                job,
                identity.attempt_id,
                f"{failure_code}_stop_unresolved",
            )
        return self._record_terminal_failure(job, identity.attempt_id, failure_code)

    def _stop_exact(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        observed: DriverInspection,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        terminal = observed
        if observed.state is not DriverState.EXITED:
            if not self._lease_matches_job(job):
                return self._block(
                    job,
                    identity.attempt_id,
                    "instance_revision_mismatch",
                )
            try:
                terminal = self._driver.stop(identity)
            except AmbiguousDriverOutcome:
                try:
                    terminal = self._driver.inspect(identity)
                except (
                    DriverIdentityMismatch,
                    DriverPolicyError,
                    DriverTransportError,
                ):
                    return self._block(
                        job,
                        identity.attempt_id,
                        "ambiguous_stop_unresolved",
                    )
                if terminal.state not in _TERMINAL_STATES:
                    return self._block(
                        job,
                        identity.attempt_id,
                        "ambiguous_stop_unresolved",
                    )
            except (DriverIdentityMismatch, DriverPolicyError, DriverTransportError):
                return self._block(
                    job,
                    identity.attempt_id,
                    "stop_postcondition_unresolved",
                )
        if terminal.state is DriverState.ABSENT:
            return self._record_stopped(job, identity.attempt_id, None)
        if terminal.state is DriverState.EXITED and _runtime_matches(
            revalidated, terminal
        ):
            return self._record_stopped(job, identity.attempt_id, terminal.exit_code)
        return self._block(
            job,
            identity.attempt_id,
            "stop_postcondition_not_terminal",
        )

    def _verify_active_access_network(
        self,
        revalidated: RevalidatedAttempt,
        observed: DriverInspection,
    ) -> bool:
        container_id = observed.container_id
        if container_id is None:
            return False
        try:
            plan = self._preparation.compile_access_network_plan(
                revalidated,
                container_id,
            )
            if type(plan) is not RuntimeAccessNetworkPlan:
                raise DriverValidationError()
            if (
                plan.runtime_member.runtime_identity != revalidated.identity
                or plan.runtime_member.container_id != container_id
            ):
                raise DriverValidationError()
            self._access_network_gate.verify_active(plan)
        except (
            AccessNetworkIdentityError,
            AccessNetworkMemberMismatch,
            AmbiguousNetworkOutcome,
            DriverValidationError,
            NetworkTransportError,
            PlatformControlIdentityMismatch,
            RuntimeAccessAttachmentMissing,
        ):
            return False
        return True

    def _persisted_terminal_failure_code(
        self,
        revalidated: RevalidatedAttempt,
        latest: LatestAttemptLike,
    ) -> str:
        evidence = latest.health_result
        if evidence is None:
            return "runtime_observed_failed"
        profile = self._preparation.resolve_health_profile(revalidated)
        if type(profile) is not HealthProfile:
            return "runtime_observed_failed"
        try:
            digest = health_profile_digest(profile)
            if not _is_utc_datetime(latest.started_at):
                return "runtime_observed_failed"
            deadline = health_deadline(latest.started_at, profile)
        except DriverValidationError:
            return "runtime_observed_failed"
        if (
            _health_evidence_matches(evidence, profile, digest, deadline)
            and evidence.result_code == _HEALTH_UNHEALTHY
            and evidence.attempts >= profile.retries
        ):
            return "health_retries_exhausted"
        return "runtime_observed_failed"

    def _lease_matches_job(self, job: ReconciliationJob) -> bool:
        current = self._repository.assert_current_lease(
            job.job_id,
            job.lease_owner,
            job.lease_generation,
        )
        return (
            current.job_id == job.job_id
            and current.instance_id == job.instance_id
            and current.expected_instance_version == job.instance_revision
            and current.lease_owner == job.lease_owner
            and current.lease_generation == job.lease_generation
        )

    def _record_terminal_failure(
        self,
        job: ReconciliationJob,
        attempt_id: str,
        failure_code: str,
    ) -> ReconciliationOutcome:
        self._repository.record_failed(
            job.job_id,
            attempt_id,
            failure_code,
            job.lease_owner,
            job.lease_generation,
        )
        return _outcome(
            job,
            ReconciliationDecision.FAIL_LATCHED,
            attempt_id,
            failure_code,
        )

    def _record_stopped(
        self,
        job: ReconciliationJob,
        attempt_id: str,
        exit_code: int | None,
        decision: ReconciliationDecision = ReconciliationDecision.STOP_EXACT,
    ) -> ReconciliationOutcome:
        self._repository.record_stopped(
            job.job_id,
            attempt_id,
            exit_code,
            job.lease_owner,
            job.lease_generation,
        )
        return _outcome(job, decision, attempt_id)

    def _block(
        self,
        job: ReconciliationJob,
        attempt_id: str | None,
        failure_code: str,
        decision: ReconciliationDecision = ReconciliationDecision.FAIL_LATCHED,
    ) -> ReconciliationOutcome:
        self._repository.record_reconciliation_blocked(
            job.job_id,
            attempt_id,
            failure_code,
            job.lease_owner,
            job.lease_generation,
        )
        return _outcome(job, decision, attempt_id, failure_code)


def _health_evidence_matches(
    evidence: PersistedHealthResultLike,
    profile: HealthProfile,
    profile_digest: str,
    deadline: datetime,
) -> bool:
    return (
        type(evidence.profile_id) is str
        and evidence.profile_id == profile.profile_id
        and type(evidence.profile_digest) is str
        and evidence.profile_digest == profile_digest
        and _is_utc_datetime(evidence.deadline_at)
        and evidence.deadline_at == deadline
        and _is_utc_datetime(evidence.next_probe_not_before)
        and evidence.next_probe_not_before
        == deadline
        - timedelta(
            seconds=(
                profile.timeout_seconds
                + profile.interval_seconds * (profile.retries - evidence.attempts)
            )
        )
        and _is_utc_datetime(evidence.observed_at)
        and (
            evidence.result_code != _HEALTH_HEALTHY
            or evidence.observed_at <= deadline
        )
        and type(evidence.attempts) is int
        and 1 <= evidence.attempts <= profile.retries
        and evidence.result_code
        in {
            _HEALTH_RESERVED,
            _HEALTH_HEALTHY,
            _HEALTH_UNHEALTHY,
            _HEALTH_INTERRUPTED,
            "health_probe_unknown",
        }
        and (
            evidence.last_failure_code is None
            or (
                type(evidence.last_failure_code) is str
                and bool(evidence.last_failure_code)
            )
        )
        and (
            (
                evidence.result_code in {_HEALTH_RESERVED, _HEALTH_HEALTHY}
                and evidence.last_failure_code is None
            )
            or (
                evidence.result_code
                in {
                    _HEALTH_UNHEALTHY,
                    _HEALTH_INTERRUPTED,
                    "health_probe_unknown",
                }
                and evidence.last_failure_code is not None
            )
        )
    )


def _runtime_matches(
    revalidated: RevalidatedAttempt,
    observed: DriverInspection,
) -> bool:
    return (
        identity_matches(revalidated.identity, observed)
        and observed.observed_launch_authority_digest
        == revalidated.provenance.launch_authority_digest
    )


def _is_utc_datetime(value: object) -> bool:
    return (
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and value.utcoffset().total_seconds() == 0
    )


def _status_value(status: object) -> str:
    value = getattr(status, "value", status)
    if not isinstance(value, str):
        return ""
    return value


def _outcome(
    job: ReconciliationJob,
    decision: ReconciliationDecision,
    attempt_id: str | None,
    failure_code: str | None = None,
) -> ReconciliationOutcome:
    return ReconciliationOutcome(job.action, decision, attempt_id, failure_code)
