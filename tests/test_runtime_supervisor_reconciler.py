from __future__ import annotations

import dataclasses
import subprocess
import sys
import unittest
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from tools.runtime_driver import (
    DriverHealth,
    DriverIdentity,
    DriverInspection,
    DriverState,
    EnvironmentEntry,
    HealthProfile,
    LaunchSnapshot,
    ResourceLimits,
    RuntimeUser,
    SecretMount,
    SecretPathEnvironmentBinding,
    WritableStateMount,
)


ROOT = Path(__file__).resolve().parents[1]


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
    )


@dataclass(frozen=True)
class Latest:
    attempt_id: str
    status: str
    runtime_spec_payload_digest: str
    resolved_material: object


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

    def get_latest_attempt_material(self, instance_id: str) -> Latest | None:
        self.events.append(("latest", instance_id))
        return self.latest

    def prepare_attempt_id(self, job_id: str) -> str:
        self.events.append(("prepare_attempt_id", job_id))
        return self.prepared_attempt_id

    def begin_attempt(
        self, job_id: str, attempt_id: str, resolved_material: object
    ) -> None:
        self.events.append(("begin", job_id, attempt_id, resolved_material))

    def record_reconciliation_blocked(
        self, job_id: str, attempt_id: str | None, failure_code: str
    ) -> None:
        self.events.append(("blocked", job_id, attempt_id, failure_code))

    def record_healthy(self, job_id: str, attempt_id: str) -> None:
        self.events.append(("healthy", job_id, attempt_id))

    def record_failed(self, job_id: str, attempt_id: str, failure_code: str) -> None:
        self.events.append(("failed", job_id, attempt_id, failure_code))

    def record_stopped(
        self, job_id: str, attempt_id: str, exit_code: int | None
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
        return RevalidatedAttempt(self.identities[attempt_id], material)

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


class DriverSpy:
    def __init__(
        self, events: list[object], inspections: list[DriverInspection]
    ) -> None:
        self.events = events
        self.inspections = inspections
        self.launch_result: DriverInspection | None = None
        self.stop_result = inspection(DriverState.EXITED)

    def inspect(self, identity: DriverIdentity) -> DriverInspection:
        self.events.append(("inspect", identity.attempt_id))
        return self.inspections.pop(0)

    def launch(self, snapshot: LaunchSnapshot) -> DriverInspection:
        self.events.append(("launch", snapshot.identity.attempt_id))
        return self.launch_result or inspection(
            DriverState.RUNNING,
            health=DriverHealth.HEALTHY,
            identity=snapshot.identity,
        )

    def stop(self, identity: DriverIdentity) -> DriverInspection:
        self.events.append(("stop", identity.attempt_id))
        return self.stop_result


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
    result = RuntimeSupervisorReconciler(repository, preparation, driver).reconcile(
        ReconciliationJob(job_id="job-1", instance_id="paper-instance", action=action)
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
                ("healthy", "job-1", "paper-attempt-1"),
            ],
        )

    def test_active_absent_attempt_relaunches_without_creating_another_attempt(
        self,
    ) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        material = object()
        latest = Latest("paper-attempt-1", "launching", "a" * 64, material)
        result, events, _, _, _ = run_reconciliation(
            "start", latest, [DriverInspection.absent(), DriverInspection.absent()]
        )

        self.assertIs(result.decision, ReconciliationDecision.ADOPT)
        self.assertIn(("launch", "paper-attempt-1"), events)
        self.assertNotIn(("prepare_attempt_id", "job-1"), events)
        self.assertFalse(
            any(event[0] == "begin" for event in events if isinstance(event, tuple))
        )
        self.assertEqual(events[-1], "secret_close")

    def test_active_relaunch_rechecks_locator_after_preparation(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision

        latest = Latest("paper-attempt-1", "launching", "a" * 64, object())
        mismatched = dataclasses.replace(
            expected_identity(), image_id="sha256:" + "f" * 64
        )
        cases = (
            (
                inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY),
                ReconciliationDecision.ADOPT,
                None,
            ),
            (
                inspection(
                    DriverState.RUNNING,
                    health=DriverHealth.HEALTHY,
                    identity=mismatched,
                ),
                ReconciliationDecision.IDENTITY_MISMATCH,
                "runtime_identity_mismatch",
            ),
            (
                inspection(DriverState.UNKNOWN),
                ReconciliationDecision.FAIL_LATCHED,
                "runtime_identity_unknown",
            ),
        )
        for second_observation, decision, failure_code in cases:
            with self.subTest(second_observation=second_observation.state):
                result, events, _, _, _ = run_reconciliation(
                    "start",
                    latest,
                    [DriverInspection.absent(), second_observation],
                )
                self.assertIs(result.decision, decision)
                self.assertEqual(result.failure_code, failure_code)
                self.assertFalse(
                    any(
                        event[0] == "launch"
                        for event in events
                        if isinstance(event, tuple)
                    )
                )
                self.assertEqual(events[-1], "secret_close")
                if failure_code is None:
                    self.assertIn(("healthy", "job-1", "paper-attempt-1"), events)
                else:
                    self.assertIn(
                        (
                            "blocked",
                            "job-1",
                            "paper-attempt-1",
                            failure_code,
                        ),
                        events,
                    )

    def test_healthy_attempt_start_and_nonlaunching_absence_are_blocked(self) -> None:
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
                self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
                self.assertEqual(result.failure_code, failure_code)
                self.assertEqual(
                    events[-1],
                    ("blocked", "job-1", "paper-attempt-1", failure_code),
                )
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
            ReconciliationJob,
            RevalidatedAttempt,
            RuntimeSupervisorReconciler,
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
                result = RuntimeSupervisorReconciler(
                    repository, preparation, driver
                ).reconcile(ReconciliationJob("job-1", "paper-instance", "start"))
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
            ReconciliationJob,
            RevalidatedAttempt,
            RuntimeSupervisorReconciler,
        )

        class ChangedMaterialPreparation(PreparationSpy):
            def revalidate(
                self, job: object, attempt_id: str, latest: Latest | None
            ) -> RevalidatedAttempt:
                self.events.append(("revalidate", attempt_id, latest.attempt_id))
                return RevalidatedAttempt(
                    self.identities[attempt_id],
                    object(),
                )

        events: list[object] = []
        latest = Latest("paper-attempt-1", "launching", "a" * 64, object())
        repository = RepositorySpy(events, latest)
        preparation = ChangedMaterialPreparation(
            events,
            {"paper-attempt-1": expected_identity()},
        )
        driver = DriverSpy(events, [])

        result = RuntimeSupervisorReconciler(repository, preparation, driver).reconcile(
            ReconciliationJob("job-1", "paper-instance", "start")
        )

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
        from tools.runtime_supervisor.reconciler import (
            ReconciliationJob,
            RuntimeSupervisorReconciler,
        )

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
                    result = RuntimeSupervisorReconciler(
                        repository, preparation, driver
                    ).reconcile(ReconciliationJob("job-1", "paper-instance", "start"))
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
            ReconciliationJob,
            RevalidatedAttempt,
            RuntimeSupervisorReconciler,
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
                    self.candidate_identity, self.resolved_material
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
                result = RuntimeSupervisorReconciler(
                    repository, preparation, driver
                ).reconcile(ReconciliationJob("job-1", "paper-instance", "start"))
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
        result = __import__(
            "tools.runtime_supervisor.reconciler",
            fromlist=["RuntimeSupervisorReconciler"],
        ).RuntimeSupervisorReconciler(
            RepositorySpy(events := [], latest),
            PreparationSpy(events, {"paper-attempt-1": expected_identity()}),
            driver := DriverSpy(
                events, [inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY)]
            ),
        )
        driver.stop_result = inspection(
            DriverState.RUNNING, health=DriverHealth.HEALTHY
        )
        outcome = result.reconcile(
            __import__(
                "tools.runtime_supervisor.reconciler", fromlist=["ReconciliationJob"]
            ).ReconciliationJob("job-1", "paper-instance", "stop")
        )
        self.assertIs(outcome.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(outcome.failure_code, "stop_postcondition_not_terminal")
        self.assertEqual(
            events[-1],
            ("blocked", "job-1", "paper-attempt-1", "stop_postcondition_not_terminal"),
        )

    def test_secret_context_closes_when_begin_attempt_raises(self) -> None:
        from tools.runtime_supervisor.reconciler import (
            ReconciliationJob,
            RuntimeSupervisorReconciler,
        )

        class FailingRepository(RepositorySpy):
            def begin_attempt(
                self, job_id: str, attempt_id: str, resolved_material: object
            ) -> None:
                super().begin_attempt(job_id, attempt_id, resolved_material)
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
            RuntimeSupervisorReconciler(repository, preparation, driver).reconcile(
                ReconciliationJob("job-1", "paper-instance", "start")
            )
        self.assertEqual(events[-1], "secret_close")
        self.assertFalse(
            any(event[0] == "launch" for event in events if isinstance(event, tuple))
        )

    def test_secret_context_closes_at_every_later_failing_boundary(self) -> None:
        from tools.runtime_supervisor.reconciler import (
            ReconciliationJob,
            RuntimeSupervisorReconciler,
        )

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
            def record_healthy(self, job_id: str, attempt_id: str) -> None:
                super().record_healthy(job_id, attempt_id)
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
                    RuntimeSupervisorReconciler(
                        repository, preparation, driver
                    ).reconcile(ReconciliationJob("job-1", "paper-instance", "start"))
                self.assertEqual(events[-1], "secret_close")

    def test_preparation_failures_never_reach_the_driver(self) -> None:
        from tools.runtime_supervisor.reconciler import (
            ReconciliationJob,
            RuntimeSupervisorReconciler,
        )

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
                    RuntimeSupervisorReconciler(
                        repository, preparation, driver
                    ).reconcile(ReconciliationJob("job-1", "paper-instance", "start"))
                self.assertFalse(
                    any(
                        event[0] in ("inspect", "launch", "stop")
                        for event in events
                        if isinstance(event, tuple)
                    )
                )

    def test_external_snapshot_mapping_is_rejected_and_secret_is_closed(self) -> None:
        from tools.runtime_supervisor.reconciler import (
            ReconciliationJob,
            RuntimeSupervisorReconciler,
        )

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
            RuntimeSupervisorReconciler(repository, preparation, driver).reconcile(
                ReconciliationJob("job-1", "paper-instance", "start")
            )
        self.assertEqual(events[-1], "secret_close")
        self.assertFalse(
            any(event[0] == "inspect" for event in events if isinstance(event, tuple))
        )

    def test_candidate_snapshot_identity_mismatch_has_no_attempt_binding(self) -> None:
        from tools.runtime_supervisor.domain import ReconciliationDecision
        from tools.runtime_supervisor.reconciler import (
            ReconciliationJob,
            RuntimeSupervisorReconciler,
        )

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
        result = RuntimeSupervisorReconciler(repository, preparation, driver).reconcile(
            ReconciliationJob("job-1", "paper-instance", "start")
        )

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
        from tools.runtime_supervisor.reconciler import (
            ReconciliationJob,
            RuntimeSupervisorReconciler,
        )

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
                result = RuntimeSupervisorReconciler(
                    repository, preparation, driver
                ).reconcile(ReconciliationJob("job-1", "paper-instance", "start"))
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
