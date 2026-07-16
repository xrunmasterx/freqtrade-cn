from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from tools.runtime_driver import (
    AccessNetworkIdentityError,
    AccessNetworkMemberMismatch,
    AmbiguousNetworkOutcome,
    DriverIdentity,
    DriverInspection,
    DriverState,
    DriverValidationError,
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
    decide_reconciliation,
    identity_matches,
)


_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {"pending", "validating", "launching", "healthy", "stopping"}
)
_TERMINAL_ATTEMPT_STATUSES = frozenset({"stopped", "failed"})
_START_TRANSITIONABLE_ATTEMPT_STATUSES = frozenset(
    {"pending", "validating", "launching"}
)


class LatestAttemptLike(Protocol):
    attempt_id: str
    status: object
    runtime_spec_payload_digest: str
    resolved_material: object


class RepositoryPort(Protocol):
    def get_latest_attempt_material(
        self, instance_id: str
    ) -> LatestAttemptLike | None: ...

    def prepare_attempt_id(self, job_id: str) -> str: ...

    def begin_attempt(
        self, job_id: str, attempt_id: str, resolved_material: object
    ) -> object: ...

    def record_reconciliation_blocked(
        self, job_id: str, attempt_id: str | None, failure_code: str
    ) -> object: ...

    def record_healthy(self, job_id: str, attempt_id: str) -> object: ...

    def record_failed(
        self, job_id: str, attempt_id: str, failure_code: str
    ) -> object: ...

    def record_stopped(
        self, job_id: str, attempt_id: str, exit_code: int | None
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ReconciliationJob:
    job_id: str
    instance_id: str
    action: ReconciliationAction

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", ReconciliationAction(self.action))


@dataclass(frozen=True, slots=True)
class RevalidatedAttempt:
    identity: DriverIdentity
    resolved_material: object


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

    def compile_access_network_plan(
        self,
        revalidated: RevalidatedAttempt,
        container_id: str,
    ) -> RuntimeAccessNetworkPlan: ...


class RuntimeSupervisorReconciler:
    def __init__(
        self,
        repository: RepositoryPort,
        preparation: PreparationPort,
        driver: RuntimeDriver,
        access_network_gate: RuntimeAccessNetworkGate,
    ) -> None:
        self._repository = repository
        self._preparation = preparation
        self._driver = driver
        self._access_network_gate = access_network_gate

    def reconcile(self, job: ReconciliationJob) -> ReconciliationOutcome:
        latest = self._repository.get_latest_attempt_material(job.instance_id)
        if latest is None:
            if job.action is ReconciliationAction.STOP:
                return self._block(job, None, "stop_without_active_attempt")
            return self._launch_candidate(job, None, None)

        expected = self._preparation.recover_identity(latest)
        status = _status_value(latest.status)
        active_binding = (
            latest.attempt_id if status in _ACTIVE_ATTEMPT_STATUSES else None
        )
        if (
            expected.attempt_id != latest.attempt_id
            or expected.instance_id != job.instance_id
            or expected.runtime_spec_digest != latest.runtime_spec_payload_digest
        ):
            return self._block(
                job, active_binding, "persisted_identity_mismatch"
            )

        revalidated = self._preparation.revalidate(job, latest.attempt_id, latest)
        if revalidated.identity != expected:
            return self._block(
                job, active_binding, "revalidated_identity_mismatch"
            )

        if status in _ACTIVE_ATTEMPT_STATUSES:
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
            return self._reconcile_active(job, revalidated, status)
        if status not in _TERMINAL_ATTEMPT_STATUSES:
            return self._block(job, None, "attempt_status_invalid")

        if job.action is ReconciliationAction.STOP:
            return self._block(job, None, "stop_without_active_attempt")
        observed = self._driver.inspect(expected)
        if observed.state is not DriverState.ABSENT:
            return self._block(job, None, "terminal_runtime_present")
        return self._launch_candidate(job, latest, expected)

    def _reconcile_active(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        status: str,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        observed = self._driver.inspect(identity)
        if (
            job.action is ReconciliationAction.START
            and observed.state is DriverState.ABSENT
            and status != "launching"
        ):
            return self._block(job, identity.attempt_id, "active_attempt_absent")
        decision = decide_reconciliation(job.action, identity, observed)

        if decision is ReconciliationDecision.ADOPT:
            if not self._verify_active_access_network(job, revalidated, observed):
                return self._block(
                    job,
                    identity.attempt_id,
                    "runtime_access_network_invalid",
                )
            self._repository.record_healthy(job.job_id, identity.attempt_id)
            return _outcome(job, decision, identity.attempt_id)
        if decision is ReconciliationDecision.CONTINUE_OBSERVING:
            return _outcome(job, decision, identity.attempt_id)
        if decision is ReconciliationDecision.ALREADY_ABSENT:
            self._repository.record_stopped(job.job_id, identity.attempt_id, None)
            return _outcome(job, decision, identity.attempt_id)
        if decision is ReconciliationDecision.STOP_EXACT:
            return self._stop_exact(job, identity, observed)
        if decision is ReconciliationDecision.LAUNCH:
            return self._launch_prepared(job, revalidated, begin=False)
        if decision is ReconciliationDecision.IDENTITY_MISMATCH:
            return self._block(
                job,
                identity.attempt_id,
                "runtime_identity_mismatch",
                ReconciliationDecision.IDENTITY_MISMATCH,
            )
        if observed.state is DriverState.UNKNOWN:
            return self._block(job, identity.attempt_id, "runtime_identity_unknown")

        self._repository.record_failed(
            job.job_id, identity.attempt_id, "runtime_observed_failed"
        )
        return _outcome(
            job,
            ReconciliationDecision.FAIL_LATCHED,
            identity.attempt_id,
            "runtime_observed_failed",
        )

    def _stop_exact(
        self,
        job: ReconciliationJob,
        identity: DriverIdentity,
        observed: DriverInspection,
    ) -> ReconciliationOutcome:
        terminal = observed
        if observed.state is not DriverState.EXITED:
            terminal = self._driver.stop(identity)

        if terminal.state is DriverState.ABSENT:
            self._repository.record_stopped(job.job_id, identity.attempt_id, None)
            return _outcome(
                job, ReconciliationDecision.STOP_EXACT, identity.attempt_id
            )
        if terminal.state is DriverState.EXITED and identity_matches(identity, terminal):
            self._repository.record_stopped(
                job.job_id, identity.attempt_id, terminal.exit_code
            )
            return _outcome(
                job, ReconciliationDecision.STOP_EXACT, identity.attempt_id
            )
        return self._block(
            job, identity.attempt_id, "stop_postcondition_not_terminal"
        )

    def _launch_candidate(
        self,
        job: ReconciliationJob,
        terminal_latest: LatestAttemptLike | None,
        terminal_identity: DriverIdentity | None,
    ) -> ReconciliationOutcome:
        attempt_id = self._repository.prepare_attempt_id(job.job_id)
        revalidated = self._preparation.revalidate(job, attempt_id, terminal_latest)
        if (
            revalidated.identity.attempt_id != attempt_id
            or revalidated.identity.instance_id != job.instance_id
        ):
            return self._block(job, None, "candidate_identity_mismatch")
        return self._launch_prepared(
            job,
            revalidated,
            begin=True,
            prepared_attempt_id=attempt_id,
            terminal_latest=terminal_latest,
            terminal_identity=terminal_identity,
        )

    def _launch_prepared(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        *,
        begin: bool,
        prepared_attempt_id: str | None = None,
        terminal_latest: LatestAttemptLike | None = None,
        terminal_identity: DriverIdentity | None = None,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        state = self._preparation.resolve_state(revalidated)
        with self._preparation.resolve_secrets(revalidated) as secrets:
            snapshot = self._preparation.compile_snapshot(revalidated, state, secrets)
            if not isinstance(snapshot, LaunchSnapshot):
                raise TypeError("launch snapshot must be a LaunchSnapshot")
            if snapshot.identity != identity:
                return self._block(
                    job,
                    None if begin else identity.attempt_id,
                    "compiled_snapshot_identity_mismatch",
                    ReconciliationDecision.IDENTITY_MISMATCH,
                )

            if not begin:
                current = self._driver.inspect(identity)
                if current.state is not DriverState.ABSENT:
                    return self._record_launch_observation(
                        job,
                        revalidated,
                        current,
                    )

            if begin:
                if prepared_attempt_id is None:
                    raise RuntimeError("prepared attempt ID is required")
                candidate_observed = self._driver.inspect(identity)
                if candidate_observed.state is not DriverState.ABSENT:
                    return self._block(
                        job, None, "candidate_runtime_occupied"
                    )
                if terminal_latest is not None:
                    if terminal_identity is None:
                        raise RuntimeError("terminal identity is required")
                    predecessor = self._driver.inspect(terminal_identity)
                    if predecessor.state is not DriverState.ABSENT:
                        return self._block(
                            job,
                            None,
                            "terminal_runtime_present",
                        )
                self._repository.begin_attempt(
                    job.job_id, prepared_attempt_id, revalidated.resolved_material
                )

            observed = self._driver.launch(snapshot)
            return self._record_launch_observation(job, revalidated, observed)

    def _record_launch_observation(
        self,
        job: ReconciliationJob,
        revalidated: RevalidatedAttempt,
        observed: DriverInspection,
    ) -> ReconciliationOutcome:
        identity = revalidated.identity
        if observed.state is DriverState.UNKNOWN:
            return self._block(job, identity.attempt_id, "runtime_identity_unknown")
        if observed.state is not DriverState.ABSENT and not identity_matches(
            identity, observed
        ):
            return self._block(
                job,
                identity.attempt_id,
                "runtime_identity_mismatch",
                ReconciliationDecision.IDENTITY_MISMATCH,
            )

        decision = decide_reconciliation(
            ReconciliationAction.START, identity, observed
        )
        if decision is ReconciliationDecision.ADOPT:
            if not self._verify_active_access_network(job, revalidated, observed):
                return self._block(
                    job,
                    identity.attempt_id,
                    "runtime_access_network_invalid",
                )
            self._repository.record_healthy(job.job_id, identity.attempt_id)
            return _outcome(job, decision, identity.attempt_id)
        if decision is ReconciliationDecision.CONTINUE_OBSERVING:
            return _outcome(job, decision, identity.attempt_id)

        self._repository.record_failed(
            job.job_id, identity.attempt_id, "runtime_launch_failed"
        )
        return _outcome(
            job,
            ReconciliationDecision.FAIL_LATCHED,
            identity.attempt_id,
            "runtime_launch_failed",
        )

    def _verify_active_access_network(
        self,
        job: ReconciliationJob,
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

    def _block(
        self,
        job: ReconciliationJob,
        attempt_id: str | None,
        failure_code: str,
        decision: ReconciliationDecision = ReconciliationDecision.FAIL_LATCHED,
    ) -> ReconciliationOutcome:
        self._repository.record_reconciliation_blocked(
            job.job_id, attempt_id, failure_code
        )
        return _outcome(
            job,
            decision,
            attempt_id,
            failure_code,
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
