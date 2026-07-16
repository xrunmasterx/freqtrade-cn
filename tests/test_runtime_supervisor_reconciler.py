from __future__ import annotations

import dataclasses
import subprocess
import sys
import unittest
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from tools.runtime_driver import (
    DriverHealth,
    DriverIdentity,
    DriverIdentityMismatch,
    DriverInspection,
    DriverPolicyError,
    DriverState,
    DriverTransportError,
    EnvironmentEntry,
    HealthProfile,
    LaunchSnapshot,
    ResourceLimits,
    RuntimeNetworkBinding,
    RuntimeAccessNetworkPlan,
    RuntimeAccessAttachmentMissing,
    RuntimeUser,
    SecretMount,
    SecretPathEnvironmentBinding,
    WritableStateMount,
)
from tools.runtime_supervisor.offline_identity import OfflineRuntimeIdentity


ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 7, 16, 1, 2, 3, tzinfo=UTC)


def launch_provenance() -> object:
    from tools.runtime_supervisor.reconciler import LaunchProvenance

    return LaunchProvenance(
        launch_authority_digest="c" * 64,
        root_commit="1" * 40,
        backend_commit="2" * 40,
        frontend_commit="3" * 40,
        strategies_commit="4" * 40,
    )


def expected_identity() -> DriverIdentity:
    return DriverIdentity(
        project_name="runtime-paper",
        container_name="runtime-paper-attempt-1",
        instance_id="paper-instance",
        attempt_id="paper-attempt-1",
        runtime_spec_digest="a" * 64,
        state_allocation_id="paper-state",
        image_id="sha256:" + "b" * 64,
        network_names=("runtime-access", "runtime-private"),
    )


def inspection(
    state: DriverState,
    *,
    health: DriverHealth = DriverHealth.UNKNOWN,
    identity: DriverIdentity | None = None,
) -> DriverInspection:
    if state is DriverState.ABSENT:
        return DriverInspection.absent()

    observed = identity or expected_identity()
    return DriverInspection(
        state=state,
        container_id="c" * 64,
        observed_project_name=observed.project_name,
        observed_container_name=observed.container_name,
        observed_instance_id=observed.instance_id,
        observed_attempt_id=observed.attempt_id,
        observed_runtime_spec_digest=observed.runtime_spec_digest,
        observed_launch_authority_digest="c" * 64,
        observed_state_allocation_id=observed.state_allocation_id,
        observed_image_id=observed.image_id,
        observed_network_names=observed.network_names,
        health=health,
        exit_code=0 if state is DriverState.EXITED else None,
    )


def launch_snapshot(identity: DriverIdentity) -> LaunchSnapshot:
    return LaunchSnapshot(
        identity=identity,
        launch_authority_digest="c" * 64,
        argv=("freqtrade", "trade"),
        working_directory="/freqtrade",
        non_secret_environment=(EnvironmentEntry(name="MODE", value="paper"),),
        read_only_mounts=(),
        state_mount=WritableStateMount(
            source=ROOT / "state",
            target=PurePosixPath("/freqtrade/user_data"),
            allocation_id=identity.state_allocation_id,
        ),
        secret_mounts=(
            SecretMount(
                source=ROOT / "secret",
                target=PurePosixPath("/run/secrets/api"),
                secret_reference_id="api-secret",
                version="secret-v1",
            ),
        ),
        secret_path_environment_bindings=(
            SecretPathEnvironmentBinding(
                name="FT_API_SECRET_FILE",
                target=PurePosixPath("/run/secrets/api"),
            ),
        ),
        runtime_user=RuntimeUser(
            uid=1000, gid=1000, home=PurePosixPath("/home/runtime")
        ),
        internal_ports=(8080,),
        health_profile=HealthProfile(
            profile_id="runtime-health",
            probe_argv=("probe",),
            start_period_seconds=0,
            interval_seconds=5,
            timeout_seconds=1,
            retries=3,
        ),
        resource_limits=ResourceLimits(
            cpu_millis=1000,
            memory_bytes=1024,
            pids_limit=64,
        ),
        network_bindings=tuple(
            RuntimeNetworkBinding(
                role="access" if index == 0 else f"private-{index}",
                network_name=network_name,
                runtime_alias=identity.container_name,
                policy_digest="d" * 64,
                internal=index > 0,
                requires_upstream_access=index == 0,
                requires_platform_control=index == 0,
            )
            for index, network_name in enumerate(identity.network_names)
        ),
    )


@dataclass(frozen=True)
class Latest:
    attempt_id: str
    status: str
    runtime_spec_payload_digest: str
    resolved_material: object
    started_at: datetime = FIXED_NOW
    health_result: object | None = None


@dataclass(frozen=True)
class AttemptView:
    started_at: datetime | None = FIXED_NOW


@dataclass(frozen=True)
class CurrentLease:
    job_id: str
    instance_id: str
    expected_instance_version: int
    lease_owner: str
    lease_generation: int


@dataclass(frozen=True)
class HealthEvidence:
    profile_id: str
    profile_digest: str
    deadline_at: datetime
    next_probe_not_before: datetime
    observed_at: datetime
    attempts: int
    result_code: str
    last_failure_code: str | None


class SecretContext(AbstractContextManager[object]):
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def __enter__(self) -> object:
        self.events.append("secret_enter")
        return object()

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.events.append("secret_close")


class RepositorySpy:
    def __init__(self, events: list[object], latest: Latest | None) -> None:
        self.events = events
        self.latest = latest
        self.prepared_attempt_id = "paper-attempt-2"
        self.current_instance_revision = 7
        self.health_evidence = (
            latest.health_result
            if latest is not None and isinstance(latest.health_result, HealthEvidence)
            else None
        )

    def assert_current_lease(
        self, job_id: str, lease_owner: str, lease_generation: int
    ) -> object:
        return CurrentLease(
            job_id,
            "paper-instance",
            self.current_instance_revision,
            lease_owner,
            lease_generation,
        )

    def get_latest_attempt_material(self, instance_id: str) -> Latest | None:
        self.events.append(("latest", instance_id))
        return self.latest

    def prepare_attempt_id(
        self, job_id: str, lease_owner: str, lease_generation: int
    ) -> str:
        self.events.append(("prepare_attempt_id", job_id))
        return self.prepared_attempt_id

    def begin_attempt(
        self,
        job_id: str,
        attempt_id: str,
        resolved_material: object,
        lease_owner: str,
        lease_generation: int,
    ) -> AttemptView:
        self.events.append(("begin", job_id, attempt_id, resolved_material))
        return AttemptView()

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
    ) -> HealthEvidence:
        attempts = (
            1 if self.health_evidence is None else self.health_evidence.attempts + 1
        )
        self.health_evidence = HealthEvidence(
            profile_id,
            profile_digest,
            deadline_at,
            next_probe_not_before,
            next_probe_not_before,
            attempts,
            "health_probe_reserved",
            None,
        )
        return self.health_evidence

    def record_health_observation(
        self,
        job_id: str,
        attempt_id: str,
        result_code: str,
        attempts: int,
        last_failure_code: str | None,
        lease_owner: str,
        lease_generation: int,
    ) -> object:
        if self.health_evidence is not None:
            self.health_evidence = dataclasses.replace(
                self.health_evidence,
                result_code=result_code,
                attempts=attempts,
                last_failure_code=last_failure_code,
            )
        return object()

    def record_reconciliation_blocked(
        self,
        job_id: str,
        attempt_id: str | None,
        failure_code: str,
        lease_owner: str,
        lease_generation: int,
    ) -> None:
        self.events.append(("blocked", job_id, attempt_id, failure_code))

    def record_healthy(
        self,
        job_id: str,
        attempt_id: str,
        lease_owner: str,
        lease_generation: int,
    ) -> None:
        self.events.append(("healthy", job_id, attempt_id))

    def record_failed(
        self,
        job_id: str,
        attempt_id: str,
        failure_code: str,
        lease_owner: str,
        lease_generation: int,
    ) -> None:
        self.events.append(("failed", job_id, attempt_id, failure_code))

    def record_stopped(
        self,
        job_id: str,
        attempt_id: str,
        exit_code: int | None,
        lease_owner: str,
        lease_generation: int,
    ) -> None:
        self.events.append(("stopped", job_id, attempt_id, exit_code))


class PreparationSpy:
    def __init__(
        self, events: list[object], identities: dict[str, DriverIdentity]
    ) -> None:
        self.events = events
        self.identities = identities
        self.resolved_material = object()
        self.snapshot_override: object | None = None
        self.access_plan_override: RuntimeAccessNetworkPlan | None = None

    def recover_identity(self, latest: Latest) -> DriverIdentity:
        self.events.append(("recover_identity", latest.attempt_id))
        return self.identities[latest.attempt_id]

    def revalidate(
        self,
        job: object,
        attempt_id: str,
        latest: Latest | None,
    ) -> object:
        from tools.runtime_supervisor.reconciler import RevalidatedAttempt

        self.events.append(
            ("revalidate", attempt_id, None if latest is None else latest.attempt_id)
        )
        material = (
            latest.resolved_material if latest is not None else self.resolved_material
        )
        return RevalidatedAttempt(
            self.identities[attempt_id], material, launch_provenance()
        )

    def resolve_state(self, revalidated: object) -> object:
        self.events.append("state")
        return object()

    def resolve_secrets(self, revalidated: object) -> AbstractContextManager[object]:
        self.events.append("resolve_secrets")
        return SecretContext(self.events)

    def compile_snapshot(
        self, revalidated: Any, state: object, secrets: object
    ) -> LaunchSnapshot:
        self.events.append("compile")
        if self.snapshot_override is not None:
            return self.snapshot_override  # type: ignore[return-value]
        return launch_snapshot(revalidated.identity)

    def compile_access_network_plan(
        self,
        revalidated: Any,
        container_id: str,
    ) -> RuntimeAccessNetworkPlan:
        from tools.runtime_access_network import compile_runtime_access_network_plan

        self.events.append(("compile_access_network", revalidated.identity.attempt_id))
        if self.access_plan_override is not None:
            return self.access_plan_override
        return compile_runtime_access_network_plan(
            launch_snapshot(revalidated.identity),
            container_id,
        )

    def resolve_health_profile(self, revalidated: Any) -> HealthProfile:
        return launch_snapshot(revalidated.identity).health_profile

    def compile_offline_identity(
        self,
        revalidated: Any,
        observed: DriverInspection,
        *,
        instance_revision: int,
        lease_generation: int,
    ) -> OfflineRuntimeIdentity:
        if observed.container_id is None:
            raise AssertionError("present observation requires a container ID")
        return OfflineRuntimeIdentity.from_driver_identity(
            revalidated.identity,
            container_id=observed.container_id,
            instance_revision=instance_revision,
            lease_generation=lease_generation,
            launch_authority_digest="c" * 64,
            root_commit="1" * 40,
            backend_commit="2" * 40,
            frontend_commit="3" * 40,
            strategies_commit="4" * 40,
        )


class OfflinePublisherSpy:
    def publish(self, identity: OfflineRuntimeIdentity) -> OfflineRuntimeIdentity:
        return identity


def reconciliation_job(action: str = "start") -> object:
    from tools.runtime_supervisor.reconciler import ReconciliationJob

    return ReconciliationJob(
        "job-1",
        "paper-instance",
        action,
        "worker-1",
        1,
        7,
    )


def reconciler(
    repository: object,
    preparation: object,
    driver: object,
    network_gate: object,
    *,
    offline_publisher: object | None = None,
    now: datetime = FIXED_NOW,
    clock: Callable[[], datetime] | None = None,
) -> object:
    from tools.runtime_supervisor.reconciler import RuntimeSupervisorReconciler

    return RuntimeSupervisorReconciler(
        repository,
        preparation,
        driver,
        network_gate,
        (OfflinePublisherSpy() if offline_publisher is None else offline_publisher),
        clock=(lambda: now) if clock is None else clock,
    )


class NetworkGateSpy:
    def __init__(self, events: list[object], fault: Exception | None = None) -> None:
        self.events = events
        self.fault = fault

    def verify_active(self, plan: RuntimeAccessNetworkPlan) -> None:
        self.events.append(("network_active", plan.runtime_member.attempt_id))
        if self.fault is not None:
            raise self.fault


class DriverSpy:
    def __init__(
        self, events: list[object], inspections: list[DriverInspection]
    ) -> None:
        self.events = events
        self.inspections = inspections
        self.launch_result: DriverInspection | None = None
        self.stop_result = inspection(DriverState.EXITED)
        self.current = DriverInspection.absent()

    def inspect(self, identity: DriverIdentity) -> DriverInspection:
        self.events.append(("inspect", identity.attempt_id))
        if self.inspections:
            self.current = self.inspections.pop(0)
        return self.current

    def launch(self, snapshot: LaunchSnapshot) -> DriverInspection:
        self.events.append(("launch", snapshot.identity.attempt_id))
        self.current = self.launch_result or inspection(
            DriverState.RUNNING,
            health=DriverHealth.HEALTHY,
            identity=snapshot.identity,
        )
        return self.current

    def stop(self, identity: DriverIdentity) -> DriverInspection:
        self.events.append(("stop", identity.attempt_id))
        self.current = self.stop_result
        return self.current

    def probe(self, identity: DriverIdentity, profile_id: str) -> object:
        from tools.runtime_driver import HealthObservation

        return HealthObservation(DriverHealth.HEALTHY, 1, None)


def run_reconciliation(
    action: str,
    latest: Latest | None,
    inspections: list[DriverInspection],
) -> tuple[object, list[object], RepositorySpy, PreparationSpy, DriverSpy]:
    from tools.runtime_supervisor.reconciler import (
        ReconciliationJob,
        RuntimeSupervisorReconciler,
    )

    events: list[object] = []
    identities = {
        "paper-attempt-1": expected_identity(),
        "paper-attempt-2": dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        ),
    }
    repository = RepositorySpy(events, latest)
    preparation = PreparationSpy(events, identities)
    driver = DriverSpy(events, inspections)
    result = RuntimeSupervisorReconciler(
        repository,
        preparation,
        driver,
        NetworkGateSpy(events),
        OfflinePublisherSpy(),
        clock=lambda: FIXED_NOW,
    ).reconcile(
        ReconciliationJob(
            job_id="job-1",
            instance_id="paper-instance",
            action=action,
            lease_owner="worker-1",
            lease_generation=1,
            instance_revision=7,
        )
    )
    return result, events, repository, preparation, driver


class RuntimeSupervisorDecisionTests(unittest.TestCase):
    def test_action_aware_reconciliation_matrix(self) -> None:
        from tools.runtime_supervisor.domain import (
            ReconciliationAction,
            ReconciliationDecision,
            decide_reconciliation,
        )

        cases = (
            (
                ReconciliationAction.START,
                DriverState.ABSENT,
                DriverHealth.UNKNOWN,
                ReconciliationDecision.LAUNCH,
            ),
            (
                ReconciliationAction.STOP,
                DriverState.ABSENT,
                DriverHealth.UNKNOWN,
                ReconciliationDecision.ALREADY_ABSENT,
            ),
            (
                ReconciliationAction.START,
                DriverState.CREATED,
                DriverHealth.UNKNOWN,
                ReconciliationDecision.CONTINUE_OBSERVING,
            ),
            (
                ReconciliationAction.START,
                DriverState.STARTING,
                DriverHealth.STARTING,
                ReconciliationDecision.CONTINUE_OBSERVING,
            ),
            (
                ReconciliationAction.START,
                DriverState.RUNNING,
                DriverHealth.STARTING,
                ReconciliationDecision.CONTINUE_OBSERVING,
            ),
            (
                ReconciliationAction.START,
                DriverState.RUNNING,
                DriverHealth.HEALTHY,
                ReconciliationDecision.ADOPT,
            ),
            (
                ReconciliationAction.START,
                DriverState.RUNNING,
                DriverHealth.NOT_CONFIGURED,
                ReconciliationDecision.FAIL_LATCHED,
            ),
            (
                ReconciliationAction.START,
                DriverState.RUNNING,
                DriverHealth.UNHEALTHY,
                ReconciliationDecision.FAIL_LATCHED,
            ),
            (
                ReconciliationAction.START,
                DriverState.RUNNING,
                DriverHealth.UNKNOWN,
                ReconciliationDecision.FAIL_LATCHED,
            ),
            (
                ReconciliationAction.START,
                DriverState.EXITED,
                DriverHealth.UNKNOWN,
                ReconciliationDecision.FAIL_LATCHED,
            ),
            (
                ReconciliationAction.STOP,
                DriverState.CREATED,
                DriverHealth.UNKNOWN,
                ReconciliationDecision.STOP_EXACT,
            ),
            (
                ReconciliationAction.STOP,
                DriverState.STARTING,
                DriverHealth.STARTING,
                ReconciliationDecision.STOP_EXACT,
            ),
            (
                ReconciliationAction.STOP,
                DriverState.RUNNING,
                DriverHealth.HEALTHY,
                ReconciliationDecision.STOP_EXACT,
            ),
            (
                ReconciliationAction.STOP,
                DriverState.EXITED,
                DriverHealth.UNKNOWN,
                ReconciliationDecision.STOP_EXACT,
            ),
        )
        identity = expected_identity()
        for action, state, health, expected in cases:
            with self.subTest(action=action, state=state, health=health):
                self.assertIs(
                    decide_reconciliation(
                        action,
                        identity,
                        inspection(state, health=health),
                    ),
                    expected,
                )

    def test_every_identity_field_mismatch_fails_closed(self) -> None:
        from tools.runtime_supervisor.domain import (
            ReconciliationAction,
            ReconciliationDecision,
            decide_reconciliation,
        )

        identity = expected_identity()
        mutations = {
            "project_name": "other-project",
            "container_name": "other-container",
            "instance_id": "other-instance",
            "attempt_id": "other-attempt",
            "runtime_spec_digest": "d" * 64,
            "state_allocation_id": "other-state",
            "image_id": "sha256:" + "e" * 64,
            "network_names": ("other-network",),
        }
        original = dataclasses.asdict(identity)
        for field, value in mutations.items():
            with self.subTest(field=field):
                observed = DriverIdentity(**{**original, field: value})
                self.assertIs(
                    decide_reconciliation(
                        ReconciliationAction.START,
                        identity,
                        inspection(
                            DriverState.RUNNING,
                            health=DriverHealth.HEALTHY,
                            identity=observed,
                        ),
                    ),
                    ReconciliationDecision.IDENTITY_MISMATCH,
                )

    def test_unknown_state_precedes_identity_comparison_for_both_actions(self) -> None:
        from tools.runtime_supervisor.domain import (
            ReconciliationAction,
            ReconciliationDecision,
            decide_reconciliation,
        )

        identity = expected_identity()
        mismatched = dataclasses.replace(identity, attempt_id="other-attempt")
        for action in ReconciliationAction:
            for observed in (identity, mismatched):
                with self.subTest(action=action, observed=observed.attempt_id):
                    self.assertIs(
                        decide_reconciliation(
                            action,
                            identity,
                            inspection(DriverState.UNKNOWN, identity=observed),
                        ),
                        ReconciliationDecision.FAIL_LATCHED,
                    )

    def test_reconciliation_outcome_is_frozen(self) -> None:
        from tools.runtime_supervisor.domain import (
            ReconciliationAction,
            ReconciliationDecision,
            ReconciliationOutcome,
        )

        outcome = ReconciliationOutcome(
            action=ReconciliationAction.START,
            decision=ReconciliationDecision.ADOPT,
            attempt_id="paper-attempt-1",
            failure_code=None,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            outcome.decision = ReconciliationDecision.FAIL_LATCHED


class RuntimeSupervisorOrchestrationTests(unittest.TestCase):
    def test_instance_revision_mismatch_blocks_before_runtime_or_offline_mutation(
        self,
    ) -> None:
        events: list[object] = []
        latest = Latest("paper-attempt-1", "launching", "a" * 64, object())
        repository = RepositorySpy(events, latest)
        repository.current_instance_revision = 8

        class RecordingPublisher:
            def publish(self, identity: object) -> object:
                events.append("offline_publish")
                return identity

        result = reconciler(
            repository,
            PreparationSpy(events, {"paper-attempt-1": expected_identity()}),
            DriverSpy(events, []),
            NetworkGateSpy(events),
            offline_publisher=RecordingPublisher(),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "instance_revision_mismatch")
        self.assertEqual(result.attempt_id, "paper-attempt-1")
        self.assertEqual(
            events[-1],
            (
                "blocked",
                "job-1",
                "paper-attempt-1",
                "instance_revision_mismatch",
            ),
        )
        self.assertFalse(
            any(
                event == "offline_publish"
                or (isinstance(event, tuple) and event[0] in {"inspect", "launch", "stop"})
                for event in events
            )
        )

    def test_active_preparation_driver_errors_keep_attempt_binding(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        cases = (
            ("recover", DriverTransportError(), "runtime_transport_error"),
            ("recover", DriverIdentityMismatch(), "runtime_identity_mismatch"),
            ("revalidate", DriverPolicyError(), "runtime_policy_invalid"),
        )
        for boundary, fault, failure_code in cases:
            with self.subTest(boundary=boundary, failure_code=failure_code):
                events: list[object] = []
                latest = Latest(
                    "paper-attempt-1", "launching", "a" * 64, object()
                )

                class FaultingPreparation(PreparationSpy):
                    def recover_identity(self, material: Latest) -> DriverIdentity:
                        if boundary == "recover":
                            raise fault
                        return super().recover_identity(material)

                    def revalidate(self, *args: Any, **kwargs: Any) -> object:
                        if boundary == "revalidate":
                            raise fault
                        return super().revalidate(*args, **kwargs)

                repository = RepositorySpy(events, latest)
                preparation = FaultingPreparation(
                    events, {"paper-attempt-1": expected_identity()}
                )
                result = reconciler(
                    repository,
                    preparation,
                    DriverSpy(events, []),
                    NetworkGateSpy(events),
                ).reconcile(reconciliation_job())

                self.assertIs(
                    result.decision, ReconciliationDecision.FAIL_LATCHED
                )
                self.assertEqual(result.attempt_id, "paper-attempt-1")
                self.assertEqual(
                    events[-1],
                    ("blocked", "job-1", "paper-attempt-1", failure_code),
                )

    def test_active_health_preparation_errors_keep_attempt_binding(self) -> None:
        cases = (
            ("health", DriverPolicyError(), "runtime_policy_invalid"),
            ("offline", DriverTransportError(), "runtime_transport_error"),
        )
        for boundary, fault, failure_code in cases:
            with self.subTest(boundary=boundary):
                events: list[object] = []
                latest = Latest(
                    "paper-attempt-1", "launching", "a" * 64, object()
                )

                class FaultingPreparation(PreparationSpy):
                    def resolve_health_profile(self, revalidated: Any) -> HealthProfile:
                        if boundary == "health":
                            raise fault
                        return super().resolve_health_profile(revalidated)

                    def compile_offline_identity(
                        self, *args: Any, **kwargs: Any
                    ) -> OfflineRuntimeIdentity:
                        if boundary == "offline":
                            raise fault
                        return super().compile_offline_identity(*args, **kwargs)

                result = reconciler(
                    RepositorySpy(events, latest),
                    FaultingPreparation(
                        events, {"paper-attempt-1": expected_identity()}
                    ),
                    DriverSpy(
                        events,
                        [
                            inspection(
                                DriverState.RUNNING,
                                health=DriverHealth.STARTING,
                            )
                        ],
                    ),
                    NetworkGateSpy(events),
                ).reconcile(reconciliation_job())

                self.assertEqual(result.attempt_id, "paper-attempt-1")
                self.assertEqual(result.failure_code, failure_code)
                self.assertEqual(
                    events[-1],
                    ("blocked", "job-1", "paper-attempt-1", failure_code),
                )

    def test_begun_attempt_health_error_keeps_new_attempt_binding(self) -> None:
        events: list[object] = []
        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )

        class FaultingPreparation(PreparationSpy):
            def resolve_health_profile(self, revalidated: Any) -> HealthProfile:
                raise DriverPolicyError()

        result = reconciler(
            RepositorySpy(events, None),
            FaultingPreparation(events, {"paper-attempt-2": identity}),
            DriverSpy(events, [DriverInspection.absent()]),
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.attempt_id, "paper-attempt-2")
        self.assertEqual(result.failure_code, "runtime_policy_invalid")
        self.assertIn(
            ("blocked", "job-1", "paper-attempt-2", "runtime_policy_invalid"),
            events,
        )

    def test_runtime_authority_mismatch_blocks_before_probe_or_adopt(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        events: list[object] = []
        latest = Latest("paper-attempt-1", "launching", "a" * 64, object())
        repository = RepositorySpy(events, latest)
        preparation = PreparationSpy(events, {"paper-attempt-1": expected_identity()})
        wrong_authority = dataclasses.replace(
            inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY),
            observed_launch_authority_digest="d" * 64,
        )
        driver = DriverSpy(events, [wrong_authority])

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.IDENTITY_MISMATCH)
        self.assertEqual(result.failure_code, "runtime_identity_mismatch")
        self.assertFalse(
            any(event[0] in {"healthy", "probe", "stop"} for event in events)
        )

    def test_compiled_snapshot_must_match_resolved_launch_authority(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        events: list[object] = []
        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        repository = RepositorySpy(events, None)
        preparation = PreparationSpy(events, {"paper-attempt-2": identity})
        preparation.snapshot_override = dataclasses.replace(
            launch_snapshot(identity), launch_authority_digest="d" * 64
        )
        driver = DriverSpy(events, [])

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.IDENTITY_MISMATCH)
        self.assertEqual(result.failure_code, "compiled_snapshot_authority_mismatch")
        self.assertFalse(any(event[0] == "launch" for event in events))

    def test_offline_identity_component_provenance_must_match(self) -> None:
        class WrongProvenancePreparation(PreparationSpy):
            def compile_offline_identity(self, *args: Any, **kwargs: Any):
                identity = super().compile_offline_identity(*args, **kwargs)
                return dataclasses.replace(identity, backend_commit="f" * 40)

        events: list[object] = []
        latest = Latest("paper-attempt-1", "launching", "a" * 64, object())
        repository = RepositorySpy(events, latest)
        preparation = WrongProvenancePreparation(
            events, {"paper-attempt-1": expected_identity()}
        )
        driver = DriverSpy(
            events,
            [
                inspection(DriverState.RUNNING, health=DriverHealth.STARTING),
                inspection(DriverState.RUNNING, health=DriverHealth.STARTING),
            ],
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "offline_identity_publish_failed")
        self.assertEqual(events.count(("stop", "paper-attempt-1")), 1)

    def test_new_start_obeys_trust_boundary_order_and_records_launch_result(
        self,
    ) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        result, events, _, preparation, _ = run_reconciliation(
            "start",
            None,
            [
                DriverInspection.absent(),
            ],
        )

        self.assertIs(result.decision, ReconciliationDecision.ADOPT)
        self.assertEqual(result.attempt_id, "paper-attempt-2")
        self.assertIsNone(result.failure_code)
        self.assertEqual(
            events,
            [
                ("latest", "paper-instance"),
                ("prepare_attempt_id", "job-1"),
                ("revalidate", "paper-attempt-2", None),
                "state",
                "resolve_secrets",
                "secret_enter",
                "compile",
                ("inspect", "paper-attempt-2"),
                ("begin", "job-1", "paper-attempt-2", preparation.resolved_material),
                ("launch", "paper-attempt-2"),
                ("inspect", "paper-attempt-2"),
                ("compile_access_network", "paper-attempt-2"),
                ("network_active", "paper-attempt-2"),
                ("healthy", "job-1", "paper-attempt-2"),
                "secret_close",
            ],
        )

    def test_active_healthy_attempt_is_adopted_without_driver_mutation(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        material = object()
        latest = Latest("paper-attempt-1", "launching", "a" * 64, material)
        result, events, _, _, _ = run_reconciliation(
            "start",
            latest,
            [inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY)],
        )
        self.assertIs(result.decision, ReconciliationDecision.ADOPT)
        self.assertEqual(
            events,
            [
                ("latest", "paper-instance"),
                ("recover_identity", "paper-attempt-1"),
                ("revalidate", "paper-attempt-1", "paper-attempt-1"),
                ("inspect", "paper-attempt-1"),
                ("inspect", "paper-attempt-1"),
                ("compile_access_network", "paper-attempt-1"),
                ("network_active", "paper-attempt-1"),
                ("healthy", "job-1", "paper-attempt-1"),
            ],
        )

    def test_active_adopt_requires_a_valid_access_network(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        events: list[object] = []
        material = object()
        latest = Latest("paper-attempt-1", "launching", "a" * 64, material)
        repository = RepositorySpy(events, latest)
        preparation = PreparationSpy(
            events,
            {"paper-attempt-1": expected_identity()},
        )
        driver = DriverSpy(
            events,
            [inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY)],
        )
        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events, RuntimeAccessAttachmentMissing()),
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "runtime_access_network_invalid")
        self.assertNotIn(("healthy", "job-1", "paper-attempt-1"), events)
        self.assertEqual(
            events[-1],
            (
                "blocked",
                "job-1",
                "paper-attempt-1",
                "runtime_access_network_invalid",
            ),
        )

    def test_launch_adopt_requires_a_valid_access_network(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        events: list[object] = []
        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        repository = RepositorySpy(events, None)
        preparation = PreparationSpy(events, {"paper-attempt-2": identity})
        driver = DriverSpy(events, [DriverInspection.absent()])
        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events, RuntimeAccessAttachmentMissing()),
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "runtime_access_network_invalid")
        self.assertNotIn(("healthy", "job-1", "paper-attempt-2"), events)
        self.assertIn(
            (
                "blocked",
                "job-1",
                "paper-attempt-2",
                "runtime_access_network_invalid",
            ),
            events,
        )
        self.assertEqual(events[-1], "secret_close")

    def test_active_adopt_rejects_a_plan_for_another_runtime_identity(self) -> None:
        from tools.runtime_access_network import compile_runtime_access_network_plan
        from tools.runtime_supervisor.domain import ReconciliationDecision

        events: list[object] = []
        material = object()
        latest = Latest("paper-attempt-1", "launching", "a" * 64, material)
        repository = RepositorySpy(events, latest)
        preparation = PreparationSpy(
            events,
            {"paper-attempt-1": expected_identity()},
        )
        wrong_identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-other",
            container_name="runtime-paper-attempt-other",
        )
        preparation.access_plan_override = compile_runtime_access_network_plan(
            launch_snapshot(wrong_identity),
            "e" * 64,
        )
        driver = DriverSpy(
            events,
            [inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY)],
        )
        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "runtime_access_network_invalid")
        self.assertFalse(
            any(event[0] in ("network_active", "healthy") for event in events)
        )

    def test_launch_adopt_rejects_a_plan_for_another_container_id(self) -> None:
        from tools.runtime_access_network import compile_runtime_access_network_plan
        from tools.runtime_supervisor.domain import ReconciliationDecision

        events: list[object] = []
        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        repository = RepositorySpy(events, None)
        preparation = PreparationSpy(events, {"paper-attempt-2": identity})
        preparation.access_plan_override = compile_runtime_access_network_plan(
            launch_snapshot(identity),
            "e" * 64,
        )
        driver = DriverSpy(events, [DriverInspection.absent()])
        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "runtime_access_network_invalid")
        self.assertFalse(
            any(event[0] in ("network_active", "healthy") for event in events)
        )

    def test_active_absent_attempt_is_observed_without_relaunch(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        material = object()
        latest = Latest("paper-attempt-1", "launching", "a" * 64, material)
        result, events, _, _, _ = run_reconciliation(
            "start", latest, [DriverInspection.absent()]
        )

        self.assertIs(result.decision, ReconciliationDecision.CONTINUE_OBSERVING)
        self.assertEqual(result.failure_code, "active_attempt_absent")
        self.assertNotIn(("launch", "paper-attempt-1"), events)
        self.assertNotIn(("prepare_attempt_id", "job-1"), events)
        self.assertFalse(
            any(event[0] == "begin" for event in events if isinstance(event, tuple))
        )
        self.assertFalse(any(event[0] == "blocked" for event in events))

    def test_active_absent_attempt_never_performs_a_second_inspection_or_launch(
        self,
    ) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        latest = Latest("paper-attempt-1", "launching", "a" * 64, object())
        result, events, _, _, driver = run_reconciliation(
            "start",
            latest,
            [
                DriverInspection.absent(),
                inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY),
            ],
        )
        self.assertIs(result.decision, ReconciliationDecision.CONTINUE_OBSERVING)
        self.assertEqual(result.failure_code, "active_attempt_absent")
        self.assertEqual(len(driver.inspections), 1)
        self.assertFalse(
            any(event[0] == "launch" for event in events if isinstance(event, tuple))
        )

    def test_healthy_start_is_blocked_and_pending_absence_is_observed(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        cases = (
            (
                "healthy",
                inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY),
                "active_attempt_status_inconsistent",
            ),
            ("pending", DriverInspection.absent(), "active_attempt_absent"),
        )
        for status, observed, failure_code in cases:
            with self.subTest(status=status):
                latest = Latest("paper-attempt-1", status, "a" * 64, object())
                result, events, _, _, _ = run_reconciliation(
                    "start", latest, [observed]
                )
                expected_decision = (
                    ReconciliationDecision.FAIL_LATCHED
                    if status == "healthy"
                    else ReconciliationDecision.CONTINUE_OBSERVING
                )
                self.assertIs(result.decision, expected_decision)
                self.assertEqual(result.failure_code, failure_code)
                if status == "healthy":
                    self.assertEqual(
                        events[-1],
                        ("blocked", "job-1", "paper-attempt-1", failure_code),
                    )
                else:
                    self.assertFalse(any(event[0] == "blocked" for event in events))
                self.assertFalse(
                    any(
                        event[0] in ("healthy", "launch")
                        for event in events
                        if isinstance(event, tuple)
                    )
                )

    def test_active_stop_absent_records_stopped_without_driver_mutation(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        latest = Latest("paper-attempt-1", "stopping", "a" * 64, object())
        result, events, _, _, _ = run_reconciliation(
            "stop", latest, [DriverInspection.absent()]
        )

        self.assertIs(result.decision, ReconciliationDecision.ALREADY_ABSENT)
        self.assertEqual(events[-1], ("stopped", "job-1", "paper-attempt-1", None))
        self.assertFalse(
            any(event[0] == "stop" for event in events if isinstance(event, tuple))
        )

    def test_unknown_active_attempt_is_blocked_without_driver_mutation(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        latest = Latest("paper-attempt-1", "launching", "a" * 64, object())
        result, events, _, _, _ = run_reconciliation(
            "start",
            latest,
            [inspection(DriverState.UNKNOWN)],
        )

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "runtime_identity_unknown")
        self.assertEqual(
            events[-1],
            ("blocked", "job-1", "paper-attempt-1", "runtime_identity_unknown"),
        )
        self.assertFalse(
            any(
                event[0] in ("launch", "stop")
                for event in events
                if isinstance(event, tuple)
            )
        )

    def test_active_transition_has_no_invented_result_and_mismatch_is_blocked(
        self,
    ) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        latest = Latest("paper-attempt-1", "launching", "a" * 64, object())
        result, events, _, _, _ = run_reconciliation(
            "start",
            latest,
            [inspection(DriverState.STARTING, health=DriverHealth.STARTING)],
        )
        self.assertIs(result.decision, ReconciliationDecision.CONTINUE_OBSERVING)
        self.assertFalse(
            any(
                event[0] in ("healthy", "failed", "stopped", "blocked")
                for event in events
                if isinstance(event, tuple)
            )
        )

        mismatched = dataclasses.replace(
            expected_identity(), image_id="sha256:" + "f" * 64
        )
        result, events, _, _, _ = run_reconciliation(
            "start",
            latest,
            [
                inspection(
                    DriverState.RUNNING,
                    health=DriverHealth.HEALTHY,
                    identity=mismatched,
                )
            ],
        )
        self.assertIs(result.decision, ReconciliationDecision.IDENTITY_MISMATCH)
        self.assertEqual(result.failure_code, "runtime_identity_mismatch")
        self.assertEqual(
            events[-1],
            ("blocked", "job-1", "paper-attempt-1", "runtime_identity_mismatch"),
        )

    def test_exact_active_failure_is_recorded_failed(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        latest = Latest("paper-attempt-1", "launching", "a" * 64, object())
        result, events, _, _, _ = run_reconciliation(
            "start",
            latest,
            [inspection(DriverState.EXITED)],
        )

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "runtime_observed_failed")
        self.assertEqual(
            events[-1],
            ("failed", "job-1", "paper-attempt-1", "runtime_observed_failed"),
        )

    def test_stop_without_active_attempt_is_blocked(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        result, events, _, _, _ = run_reconciliation("stop", None, [])

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "stop_without_active_attempt")
        self.assertEqual(
            events,
            [
                ("latest", "paper-instance"),
                ("blocked", "job-1", None, "stop_without_active_attempt"),
            ],
        )

    def test_stop_with_terminal_latest_is_blocked_without_an_attempt_binding(
        self,
    ) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        latest = Latest("paper-attempt-1", "stopped", "a" * 64, object())
        result, events, _, _, _ = run_reconciliation("stop", latest, [])

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "stop_without_active_attempt")
        self.assertEqual(
            events[-1],
            ("blocked", "job-1", None, "stop_without_active_attempt"),
        )
        self.assertFalse(
            any(event[0] == "inspect" for event in events if isinstance(event, tuple))
        )

    def test_revalidated_identity_mismatch_uses_status_appropriate_binding(
        self,
    ) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision
        from tools.runtime_supervisor.reconciler import (
            RevalidatedAttempt,
        )

        class MismatchingPreparation(PreparationSpy):
            def revalidate(
                self, job: object, attempt_id: str, latest: Latest | None
            ) -> object:
                self.events.append(("revalidate", attempt_id, latest.attempt_id))
                return RevalidatedAttempt(
                    dataclasses.replace(
                        self.identities[attempt_id], image_id="sha256:" + "f" * 64
                    ),
                    latest.resolved_material,
                    launch_provenance(),
                )

        for status, expected_binding in (
            ("launching", "paper-attempt-1"),
            ("stopped", None),
            ("invalid", None),
        ):
            with self.subTest(status=status):
                events: list[object] = []
                latest = Latest("paper-attempt-1", status, "a" * 64, object())
                repository = RepositorySpy(events, latest)
                preparation = MismatchingPreparation(
                    events, {"paper-attempt-1": expected_identity()}
                )
                driver = DriverSpy(events, [])
                result = reconciler(
                    repository, preparation, driver, NetworkGateSpy(events)
                ).reconcile(reconciliation_job())
                self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
                self.assertEqual(result.failure_code, "revalidated_identity_mismatch")
                self.assertEqual(
                    events[-1],
                    (
                        "blocked",
                        "job-1",
                        expected_binding,
                        "revalidated_identity_mismatch",
                    ),
                )

    def test_active_attempt_requires_unchanged_resolved_material(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision
        from tools.runtime_supervisor.reconciler import (
            RevalidatedAttempt,
        )

        class ChangedMaterialPreparation(PreparationSpy):
            def revalidate(
                self, job: object, attempt_id: str, latest: Latest | None
            ) -> RevalidatedAttempt:
                self.events.append(("revalidate", attempt_id, latest.attempt_id))
                return RevalidatedAttempt(
                    self.identities[attempt_id],
                    object(),
                    launch_provenance(),
                )

        events: list[object] = []
        latest = Latest("paper-attempt-1", "launching", "a" * 64, object())
        repository = RepositorySpy(events, latest)
        preparation = ChangedMaterialPreparation(
            events,
            {"paper-attempt-1": expected_identity()},
        )
        driver = DriverSpy(events, [])

        result = reconciler(
            repository, preparation, driver, NetworkGateSpy(events)
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "revalidated_material_mismatch")
        self.assertEqual(
            events[-1],
            (
                "blocked",
                "job-1",
                "paper-attempt-1",
                "revalidated_material_mismatch",
            ),
        )
        self.assertFalse(
            any(
                event == "state"
                or event == "resolve_secrets"
                or event == "compile"
                or (
                    isinstance(event, tuple)
                    and event[0] in ("inspect", "launch", "stop")
                )
                for event in events
            )
        )

    def test_recovered_identity_must_match_repository_owned_identity(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        mismatches = (
            dataclasses.replace(expected_identity(), attempt_id="other-attempt"),
            dataclasses.replace(expected_identity(), instance_id="other-instance"),
            dataclasses.replace(expected_identity(), runtime_spec_digest="f" * 64),
        )
        for status, expected_binding in (
            ("launching", "paper-attempt-1"),
            ("stopped", None),
        ):
            for recovered in mismatches:
                with self.subTest(status=status, recovered=recovered):
                    events: list[object] = []
                    latest = Latest("paper-attempt-1", status, "a" * 64, object())
                    repository = RepositorySpy(events, latest)
                    preparation = PreparationSpy(events, {"paper-attempt-1": recovered})
                    driver = DriverSpy(events, [])
                    result = reconciler(
                        repository, preparation, driver, NetworkGateSpy(events)
                    ).reconcile(reconciliation_job())
                    self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
                    self.assertEqual(result.failure_code, "persisted_identity_mismatch")
                    self.assertEqual(
                        events[-1],
                        (
                            "blocked",
                            "job-1",
                            expected_binding,
                            "persisted_identity_mismatch",
                        ),
                    )
                    self.assertFalse(
                        any(
                            event[0] in ("inspect", "begin", "launch")
                            for event in events
                            if isinstance(event, tuple)
                        )
                    )

    def test_candidate_identity_must_keep_prepared_attempt_and_job_instance(
        self,
    ) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision
        from tools.runtime_supervisor.reconciler import (
            RevalidatedAttempt,
        )

        class CandidateIdentityPreparation(PreparationSpy):
            def __init__(
                self,
                events: list[object],
                identities: dict[str, DriverIdentity],
                candidate_identity: DriverIdentity,
            ) -> None:
                super().__init__(events, identities)
                self.candidate_identity = candidate_identity

            def revalidate(
                self, job: object, attempt_id: str, latest: Latest | None
            ) -> object:
                self.events.append(("revalidate", attempt_id, None))
                return RevalidatedAttempt(
                    self.candidate_identity,
                    self.resolved_material,
                    launch_provenance(),
                )

        valid = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        for candidate in (
            dataclasses.replace(valid, attempt_id="other-attempt"),
            dataclasses.replace(valid, instance_id="other-instance"),
        ):
            with self.subTest(candidate=candidate):
                events: list[object] = []
                repository = RepositorySpy(events, None)
                preparation = CandidateIdentityPreparation(
                    events, {"paper-attempt-2": valid}, candidate
                )
                driver = DriverSpy(events, [])
                result = reconciler(
                    repository, preparation, driver, NetworkGateSpy(events)
                ).reconcile(reconciliation_job())
                self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
                self.assertEqual(result.failure_code, "candidate_identity_mismatch")
                self.assertEqual(
                    events[-1],
                    ("blocked", "job-1", None, "candidate_identity_mismatch"),
                )
                self.assertFalse(
                    any(
                        event[0] in ("state", "inspect", "begin", "launch")
                        for event in events
                        if isinstance(event, tuple)
                    )
                )

    def test_terminal_attempt_is_an_identity_gate_and_never_adopted(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        latest = Latest("paper-attempt-1", "stopped", "a" * 64, object())
        result, events, _, _, _ = run_reconciliation(
            "start",
            latest,
            [inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY)],
        )

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "terminal_runtime_present")
        self.assertEqual(
            events[-1], ("blocked", "job-1", None, "terminal_runtime_present")
        )
        self.assertFalse(
            any(
                event[0] in ("healthy", "launch", "stop")
                for event in events
                if isinstance(event, tuple)
            )
        )

    def test_terminal_attempt_is_rechecked_after_preparation_before_begin(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        latest = Latest("paper-attempt-1", "failed", "a" * 64, object())
        result, events, _, _, _ = run_reconciliation(
            "start",
            latest,
            [
                DriverInspection.absent(),
                DriverInspection.absent(),
                inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY),
            ],
        )

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "terminal_runtime_present")
        self.assertEqual(
            events[-2:],
            [("blocked", "job-1", None, "terminal_runtime_present"), "secret_close"],
        )
        self.assertFalse(
            any(
                event[0] in ("begin", "launch")
                for event in events
                if isinstance(event, tuple)
            )
        )

    def test_candidate_collision_is_blocked_even_when_exact_and_healthy(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        candidate = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        result, events, _, _, _ = run_reconciliation(
            "start",
            None,
            [
                inspection(
                    DriverState.RUNNING, health=DriverHealth.HEALTHY, identity=candidate
                )
            ],
        )

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "candidate_runtime_occupied")
        self.assertEqual(
            events[-2:],
            [("blocked", "job-1", None, "candidate_runtime_occupied"), "secret_close"],
        )
        self.assertFalse(
            any(
                event[0] in ("healthy", "begin", "launch")
                for event in events
                if isinstance(event, tuple)
            )
        )

    def test_stop_exact_records_only_truthful_terminal_postcondition(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        latest = Latest("paper-attempt-1", "healthy", "a" * 64, object())
        result, events, _, _, driver = run_reconciliation(
            "stop",
            latest,
            [inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY)],
        )

        self.assertIs(result.decision, ReconciliationDecision.STOP_EXACT)
        self.assertEqual(
            events[-2:],
            [("stop", "paper-attempt-1"), ("stopped", "job-1", "paper-attempt-1", 0)],
        )

        driver.stop_result = inspection(
            DriverState.RUNNING, health=DriverHealth.HEALTHY
        )
        result = reconciler(
            RepositorySpy(events := [], latest),
            PreparationSpy(events, {"paper-attempt-1": expected_identity()}),
            driver := DriverSpy(
                events, [inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY)]
            ),
            NetworkGateSpy(events),
        )
        driver.stop_result = inspection(
            DriverState.RUNNING, health=DriverHealth.HEALTHY
        )
        outcome = result.reconcile(reconciliation_job("stop"))
        self.assertIs(outcome.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(outcome.failure_code, "stop_postcondition_not_terminal")
        self.assertEqual(
            events[-1],
            ("blocked", "job-1", "paper-attempt-1", "stop_postcondition_not_terminal"),
        )

    def test_secret_context_closes_when_begin_attempt_raises(self) -> None:

        class FailingRepository(RepositorySpy):
            def begin_attempt(
                self,
                job_id: str,
                attempt_id: str,
                resolved_material: object,
                lease_owner: str,
                lease_generation: int,
            ) -> None:
                super().begin_attempt(
                    job_id,
                    attempt_id,
                    resolved_material,
                    lease_owner,
                    lease_generation,
                )
                raise RuntimeError("begin failed")

        events: list[object] = []
        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        repository = FailingRepository(events, None)
        preparation = PreparationSpy(events, {"paper-attempt-2": identity})
        driver = DriverSpy(events, [DriverInspection.absent()])
        with self.assertRaisesRegex(RuntimeError, "begin failed"):
            reconciler(
                repository, preparation, driver, NetworkGateSpy(events)
            ).reconcile(reconciliation_job())
        self.assertEqual(events[-1], "secret_close")
        self.assertFalse(
            any(event[0] == "launch" for event in events if isinstance(event, tuple))
        )

    def test_secret_context_closes_at_every_later_failing_boundary(self) -> None:

        class FailingPreparation(PreparationSpy):
            def compile_snapshot(
                self, revalidated: Any, state: object, secrets: object
            ) -> LaunchSnapshot:
                self.events.append("compile")
                raise RuntimeError("compile failed")

        class FailingDriver(DriverSpy):
            def launch(self, snapshot: LaunchSnapshot) -> DriverInspection:
                self.events.append(("launch", snapshot.identity.attempt_id))
                raise RuntimeError("launch failed")

        class FailingResultRepository(RepositorySpy):
            def record_healthy(
                self,
                job_id: str,
                attempt_id: str,
                lease_owner: str,
                lease_generation: int,
            ) -> None:
                super().record_healthy(
                    job_id,
                    attempt_id,
                    lease_owner,
                    lease_generation,
                )
                raise RuntimeError("result failed")

        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        cases = (
            (RepositorySpy, FailingPreparation, DriverSpy, "compile failed"),
            (RepositorySpy, PreparationSpy, FailingDriver, "launch failed"),
            (
                FailingResultRepository,
                PreparationSpy,
                DriverSpy,
                "result failed",
            ),
        )
        for repository_type, preparation_type, driver_type, message in cases:
            with self.subTest(message=message):
                events: list[object] = []
                repository = repository_type(events, None)
                preparation = preparation_type(events, {"paper-attempt-2": identity})
                driver = driver_type(events, [DriverInspection.absent()])
                with self.assertRaisesRegex(RuntimeError, message):
                    reconciler(
                        repository, preparation, driver, NetworkGateSpy(events)
                    ).reconcile(reconciliation_job())
                self.assertEqual(events[-1], "secret_close")

    def test_preparation_failures_never_reach_the_driver(self) -> None:

        class RevalidationFailure(PreparationSpy):
            def revalidate(
                self, job: object, attempt_id: str, latest: Latest | None
            ) -> object:
                self.events.append("revalidation_failed")
                raise RuntimeError("revalidation failed")

        class StateFailure(PreparationSpy):
            def resolve_state(self, revalidated: object) -> object:
                self.events.append("state_failed")
                raise RuntimeError("state failed")

        class SecretFailure(PreparationSpy):
            def resolve_secrets(
                self, revalidated: object
            ) -> AbstractContextManager[object]:
                self.events.append("secret_failed")
                raise RuntimeError("secret failed")

        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        cases = (
            (RevalidationFailure, "revalidation failed"),
            (StateFailure, "state failed"),
            (SecretFailure, "secret failed"),
        )
        for preparation_type, message in cases:
            with self.subTest(message=message):
                events: list[object] = []
                repository = RepositorySpy(events, None)
                preparation = preparation_type(events, {"paper-attempt-2": identity})
                driver = DriverSpy(events, [])
                with self.assertRaisesRegex(RuntimeError, message):
                    reconciler(
                        repository, preparation, driver, NetworkGateSpy(events)
                    ).reconcile(reconciliation_job())
                self.assertFalse(
                    any(
                        event[0] in ("inspect", "launch", "stop")
                        for event in events
                        if isinstance(event, tuple)
                    )
                )

    def test_external_snapshot_mapping_is_rejected_and_secret_is_closed(self) -> None:

        events: list[object] = []
        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        repository = RepositorySpy(events, None)
        preparation = PreparationSpy(events, {"paper-attempt-2": identity})
        preparation.snapshot_override = {"identity": dataclasses.asdict(identity)}
        driver = DriverSpy(events, [])

        with self.assertRaisesRegex(TypeError, "LaunchSnapshot"):
            reconciler(
                repository, preparation, driver, NetworkGateSpy(events)
            ).reconcile(reconciliation_job())
        self.assertEqual(events[-1], "secret_close")
        self.assertFalse(
            any(event[0] == "inspect" for event in events if isinstance(event, tuple))
        )

    def test_candidate_snapshot_identity_mismatch_has_no_attempt_binding(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        events: list[object] = []
        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        repository = RepositorySpy(events, None)
        preparation = PreparationSpy(events, {"paper-attempt-2": identity})
        preparation.snapshot_override = launch_snapshot(
            dataclasses.replace(identity, image_id="sha256:" + "f" * 64)
        )
        driver = DriverSpy(events, [])
        result = reconciler(
            repository, preparation, driver, NetworkGateSpy(events)
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.IDENTITY_MISMATCH)
        self.assertEqual(result.failure_code, "compiled_snapshot_identity_mismatch")
        self.assertEqual(
            events[-2:],
            [
                (
                    "blocked",
                    "job-1",
                    None,
                    "compiled_snapshot_identity_mismatch",
                ),
                "secret_close",
            ],
        )

    def test_launch_post_observation_records_only_definitive_results(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        cases = (
            (
                inspection(
                    DriverState.STARTING,
                    health=DriverHealth.STARTING,
                    identity=identity,
                ),
                ReconciliationDecision.CONTINUE_OBSERVING,
                None,
            ),
            (
                inspection(DriverState.EXITED, identity=identity),
                ReconciliationDecision.FAIL_LATCHED,
                "runtime_launch_failed",
            ),
        )
        for observed, expected_decision, failure_code in cases:
            with self.subTest(observed=observed.state):
                events: list[object] = []
                repository = RepositorySpy(events, None)
                preparation = PreparationSpy(events, {"paper-attempt-2": identity})
                driver = DriverSpy(events, [DriverInspection.absent()])
                driver.launch_result = observed
                result = reconciler(
                    repository, preparation, driver, NetworkGateSpy(events)
                ).reconcile(reconciliation_job())
                self.assertIs(result.decision, expected_decision)
                self.assertEqual(result.failure_code, failure_code)
                result_events = [
                    event
                    for event in events
                    if isinstance(event, tuple)
                    and event[0] in ("healthy", "failed", "stopped", "blocked")
                ]
                if failure_code is None:
                    self.assertEqual(result_events, [])
                else:
                    self.assertEqual(
                        result_events,
                        [
                            (
                                "failed",
                                "job-1",
                                "paper-attempt-2",
                                failure_code,
                            )
                        ],
                    )

    def test_import_under_python_s_performs_no_io(self) -> None:
        script = r"""
import builtins
import pathlib
import socket
import subprocess

def forbidden(*args, **kwargs):
    raise AssertionError("import-time I/O")

builtins.open = forbidden
pathlib.Path.open = forbidden
pathlib.Path.read_bytes = forbidden
pathlib.Path.read_text = forbidden
pathlib.Path.write_bytes = forbidden
pathlib.Path.write_text = forbidden
pathlib.Path.mkdir = forbidden
socket.socket = forbidden
subprocess.Popen = forbidden
subprocess.run = forbidden

import tools.runtime_supervisor
import tools.runtime_supervisor.domain
import tools.runtime_supervisor.reconciler
"""
        result = subprocess.run(
            [sys.executable, "-S", "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
