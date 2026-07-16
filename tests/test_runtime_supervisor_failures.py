from __future__ import annotations

import dataclasses
import unittest
from datetime import timedelta

from tests.test_runtime_supervisor_reconciler import (
    DriverSpy,
    FIXED_NOW,
    HealthEvidence,
    Latest,
    NetworkGateSpy,
    PreparationSpy,
    RepositorySpy,
    expected_identity,
    inspection,
    reconciler,
    reconciliation_job,
)
from tools.runtime_driver import (
    AmbiguousDriverOutcome,
    DriverHealth,
    DriverInspection,
    DriverState,
    DriverTransportError,
    HealthObservation,
)
from tools.runtime_supervisor.domain import ReconciliationDecision
from tools.runtime_supervisor.health import health_deadline, health_profile_digest
from tools.runtime_supervisor.offline_identity import OfflineIdentityStorageError


class AmbiguousLaunchDriver(DriverSpy):
    def launch(self, snapshot):
        self.events.append(("launch", snapshot.identity.attempt_id))
        raise AmbiguousDriverOutcome()


class RuntimeSupervisorAmbiguousLaunchTests(unittest.TestCase):
    def run_case(
        self,
        post_launch: DriverInspection,
    ):
        events: list[object] = []
        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        repository = RepositorySpy(events, None)
        preparation = PreparationSpy(events, {"paper-attempt-2": identity})
        driver = AmbiguousLaunchDriver(
            events,
            [DriverInspection.absent(), post_launch],
        )
        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())
        return result, events

    def test_ambiguous_launch_adopts_only_exact_healthy_runtime(self) -> None:
        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        result, events = self.run_case(
            inspection(
                DriverState.RUNNING,
                health=DriverHealth.HEALTHY,
                identity=identity,
            )
        )

        self.assertIs(result.decision, ReconciliationDecision.ADOPT)
        self.assertEqual(events.count(("launch", "paper-attempt-2")), 1)
        self.assertIn(("network_active", "paper-attempt-2"), events)
        self.assertIn(("healthy", "job-1", "paper-attempt-2"), events)

    def test_ambiguous_launch_absence_is_observed_without_retry(self) -> None:
        result, events = self.run_case(DriverInspection.absent())

        self.assertIs(result.decision, ReconciliationDecision.CONTINUE_OBSERVING)
        self.assertEqual(result.failure_code, "ambiguous_launch_absent")
        self.assertEqual(events.count(("launch", "paper-attempt-2")), 1)
        self.assertFalse(any(event[0] == "blocked" for event in events))

    def test_ambiguous_launch_absence_latches_at_observation_deadline(self) -> None:
        events: list[object] = []
        identity = dataclasses.replace(
            expected_identity(),
            attempt_id="paper-attempt-2",
            container_name="runtime-paper-attempt-2",
        )
        repository = RepositorySpy(events, None)
        preparation = PreparationSpy(events, {"paper-attempt-2": identity})
        profile = preparation.resolve_health_profile(
            type("Revalidated", (), {"identity": identity})()
        )
        driver = AmbiguousLaunchDriver(
            events,
            [DriverInspection.absent(), DriverInspection.absent()],
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
            now=health_deadline(FIXED_NOW, profile),
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "ambiguous_launch_absent")
        self.assertEqual(events.count(("launch", "paper-attempt-2")), 1)
        self.assertIn(
            ("blocked", "job-1", "paper-attempt-2", "ambiguous_launch_absent"),
            events,
        )

    def test_ambiguous_launch_identity_mismatch_never_stops_unknown_object(
        self,
    ) -> None:
        wrong = dataclasses.replace(expected_identity(), image_id="sha256:" + "f" * 64)
        result, events = self.run_case(
            inspection(
                DriverState.RUNNING,
                health=DriverHealth.HEALTHY,
                identity=wrong,
            )
        )

        self.assertIs(result.decision, ReconciliationDecision.IDENTITY_MISMATCH)
        self.assertEqual(result.failure_code, "runtime_identity_mismatch")
        self.assertFalse(
            any(event[0] == "stop" for event in events if isinstance(event, tuple))
        )


class RuntimeSupervisorAmbiguousStopTests(unittest.TestCase):
    def test_ambiguous_stop_reinspects_once_and_records_only_terminal_result(
        self,
    ) -> None:
        events: list[object] = []
        identity = expected_identity()
        material = object()
        repository = RepositorySpy(
            events,
            Latest("paper-attempt-1", "stopping", "a" * 64, material),
        )
        preparation = PreparationSpy(events, {"paper-attempt-1": identity})

        class AmbiguousStopDriver(DriverSpy):
            def stop(self, expected):
                self.events.append(("stop", expected.attempt_id))
                raise AmbiguousDriverOutcome()

        driver = AmbiguousStopDriver(
            events,
            [
                inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY),
                inspection(DriverState.EXITED),
            ],
        )
        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job("stop"))

        self.assertIs(result.decision, ReconciliationDecision.STOP_EXACT)
        self.assertEqual(events.count(("stop", "paper-attempt-1")), 1)
        self.assertIn(("stopped", "job-1", "paper-attempt-1", 0), events)

    def test_ambiguous_stop_still_running_blocks_without_second_stop(self) -> None:
        events: list[object] = []
        identity = expected_identity()
        material = object()
        repository = RepositorySpy(
            events,
            Latest("paper-attempt-1", "stopping", "a" * 64, material),
        )
        preparation = PreparationSpy(events, {"paper-attempt-1": identity})

        class AmbiguousStopDriver(DriverSpy):
            def stop(self, expected):
                self.events.append(("stop", expected.attempt_id))
                raise AmbiguousDriverOutcome()

        driver = AmbiguousStopDriver(
            events,
            [
                inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY),
                inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY),
            ],
        )
        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job("stop"))

        self.assertIs(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.failure_code, "ambiguous_stop_unresolved")
        self.assertEqual(events.count(("stop", "paper-attempt-1")), 1)
        self.assertFalse(
            any(event[0] == "stopped" for event in events if isinstance(event, tuple))
        )


class RecordingRepository(RepositorySpy):
    def assert_current_lease(self, job_id, lease_owner, lease_generation):
        self.events.append(("lease", lease_owner, lease_generation))
        return super().assert_current_lease(
            job_id, lease_owner, lease_generation
        )

    def reserve_health_probe(
        self,
        job_id,
        attempt_id,
        profile_id,
        profile_digest,
        deadline_at,
        next_probe_not_before,
        lease_owner,
        lease_generation,
    ):
        self.events.append(("reserve", attempt_id))
        return super().reserve_health_probe(
            job_id,
            attempt_id,
            profile_id,
            profile_digest,
            deadline_at,
            next_probe_not_before,
            lease_owner,
            lease_generation,
        )

    def record_health_observation(
        self,
        job_id,
        attempt_id,
        result_code,
        attempts,
        last_failure_code,
        lease_owner,
        lease_generation,
    ):
        self.events.append(("health_result", result_code, attempts))
        return super().record_health_observation(
            job_id,
            attempt_id,
            result_code,
            attempts,
            last_failure_code,
            lease_owner,
            lease_generation,
        )


class RecordingDriver(DriverSpy):
    def __init__(self, events, inspections, observation=None):
        super().__init__(events, inspections)
        self.observation = observation or HealthObservation(
            DriverHealth.HEALTHY,
            1,
            None,
        )

    def probe(self, identity, profile_id):
        self.events.append(("probe", identity.attempt_id, profile_id))
        return self.observation


class RuntimeSupervisorDurableHealthTests(unittest.TestCase):
    def components(
        self, *, evidence=None, inspections=None, driver_type=RecordingDriver
    ):
        events: list[object] = []
        latest = Latest(
            "paper-attempt-1",
            "launching",
            "a" * 64,
            object(),
            health_result=evidence,
        )
        repository = RecordingRepository(events, latest)
        preparation = PreparationSpy(events, {"paper-attempt-1": expected_identity()})
        driver = driver_type(
            events,
            inspections
            or [inspection(DriverState.RUNNING, health=DriverHealth.HEALTHY)],
        )
        return events, latest, repository, preparation, driver

    def evidence(self, result_code, attempts, failure_code=None):
        profile = PreparationSpy([], {}).resolve_health_profile(
            type("Revalidated", (), {"identity": expected_identity()})()
        )
        return HealthEvidence(
            profile.profile_id,
            health_profile_digest(profile),
            health_deadline(FIXED_NOW, profile),
            FIXED_NOW + timedelta(seconds=(attempts - 1) * profile.interval_seconds),
            FIXED_NOW + timedelta(seconds=(attempts - 1) * profile.interval_seconds),
            attempts,
            result_code,
            failure_code,
        )

    def test_engine_healthy_never_bypasses_explicit_reserved_probe(self) -> None:
        events, _, repository, preparation, driver = self.components()

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.ADOPT)
        reserve = events.index(("reserve", "paper-attempt-1"))
        probe = events.index(("probe", "paper-attempt-1", "runtime-health"))
        healthy = events.index(("healthy", "job-1", "paper-attempt-1"))
        self.assertLess(reserve, probe)
        self.assertLess(probe, healthy)
        self.assertEqual(
            events.count(("probe", "paper-attempt-1", "runtime-health")),
            1,
        )

    def test_reserved_probe_is_consumed_after_crash_and_not_reused(self) -> None:
        reserved = self.evidence("health_probe_reserved", 1)
        events, _, repository, preparation, driver = self.components(evidence=reserved)

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertIs(result.decision, ReconciliationDecision.CONTINUE_OBSERVING)
        self.assertIn(("health_result", "health_probe_interrupted", 1), events)
        self.assertFalse(
            any(event[0] == "probe" for event in events if isinstance(event, tuple))
        )

    def test_one_reconcile_executes_at_most_one_probe(self) -> None:
        interrupted = self.evidence(
            "health_probe_interrupted", 1, "health_probe_interrupted"
        )
        events, _, repository, preparation, driver = self.components(
            evidence=interrupted
        )

        reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
            now=FIXED_NOW + timedelta(seconds=5),
        ).reconcile(reconciliation_job())

        self.assertEqual(
            sum(event[0] == "probe" for event in events if isinstance(event, tuple)),
            1,
        )
        self.assertIn(("health_result", "health_probe_healthy", 2), events)

    def test_probe_requires_enough_time_to_finish_before_deadline(self) -> None:
        unhealthy = self.evidence(
            "health_probe_unhealthy", 2, "health_probe_failed"
        )
        events, _, repository, preparation, driver = self.components(
            evidence=unhealthy
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
            now=FIXED_NOW + timedelta(seconds=11),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "health_window_expired_without_proof")
        self.assertFalse(
            any(event[0] in {"reserve", "probe", "healthy"} for event in events)
        )

    def test_healthy_probe_completing_after_deadline_is_not_adopted(self) -> None:
        unhealthy = self.evidence(
            "health_probe_unhealthy", 2, "health_probe_failed"
        )
        events, _, repository, preparation, driver = self.components(
            evidence=unhealthy
        )
        instants = iter(
            (
                FIXED_NOW + timedelta(seconds=10),
                FIXED_NOW + timedelta(seconds=12),
            )
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
            clock=lambda: next(instants),
        ).reconcile(reconciliation_job())

        self.assertEqual(
            result.failure_code, "health_probe_completed_after_deadline"
        )
        self.assertIn(("health_result", "health_probe_unknown", 3), events)
        self.assertNotIn(("healthy", "job-1", "paper-attempt-1"), events)

    def test_persisted_probe_schedule_must_match_ordinal(self) -> None:
        evidence = dataclasses.replace(
            self.evidence("health_probe_unhealthy", 2, "health_probe_failed"),
            next_probe_not_before=FIXED_NOW + timedelta(seconds=6),
        )
        events, _, repository, preparation, driver = self.components(
            evidence=evidence
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "health_evidence_mismatch")
        self.assertFalse(any(event[0] == "probe" for event in events))

    def test_persisted_late_healthy_evidence_is_never_adopted(self) -> None:
        evidence = self.evidence("health_probe_healthy", 1)
        evidence = dataclasses.replace(
            evidence,
            observed_at=evidence.deadline_at + timedelta(seconds=1),
        )
        events, _, repository, preparation, driver = self.components(
            evidence=evidence
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
            now=evidence.deadline_at + timedelta(seconds=100),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "health_evidence_mismatch")
        self.assertNotIn(("healthy", "job-1", "paper-attempt-1"), events)
        self.assertFalse(any(event[0] == "probe" for event in events))

    def test_definitive_exhaustion_stops_once_before_recording_failed(self) -> None:
        exhausted = self.evidence(
            "health_probe_unhealthy",
            3,
            "health_probe_failed",
        )
        events, _, repository, preparation, driver = self.components(
            evidence=exhausted,
            inspections=[
                inspection(DriverState.RUNNING, health=DriverHealth.UNHEALTHY),
                inspection(DriverState.RUNNING, health=DriverHealth.UNHEALTHY),
            ],
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
            now=FIXED_NOW + timedelta(seconds=10),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "health_retries_exhausted")
        self.assertEqual(events.count(("stop", "paper-attempt-1")), 1)
        self.assertLess(
            events.index(("stop", "paper-attempt-1")),
            events.index(
                (
                    "failed",
                    "job-1",
                    "paper-attempt-1",
                    "health_retries_exhausted",
                )
            ),
        )

    def test_restart_after_health_stop_recovers_persisted_failure_reason(self) -> None:
        exhausted = self.evidence(
            "health_probe_unhealthy",
            3,
            "health_probe_failed",
        )
        events, _, repository, preparation, driver = self.components(
            evidence=exhausted,
            inspections=[inspection(DriverState.EXITED)],
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
            now=FIXED_NOW + timedelta(seconds=10),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "health_retries_exhausted")
        self.assertFalse(
            any(event[0] == "stop" for event in events if isinstance(event, tuple))
        )
        self.assertIn(
            (
                "failed",
                "job-1",
                "paper-attempt-1",
                "health_retries_exhausted",
            ),
            events,
        )

    def test_exhaustion_with_ambiguous_stop_never_records_failed(self) -> None:
        class AmbiguousHealthStopDriver(RecordingDriver):
            def stop(self, identity):
                self.events.append(("stop", identity.attempt_id))
                raise AmbiguousDriverOutcome()

        exhausted = self.evidence(
            "health_probe_unhealthy",
            3,
            "health_probe_failed",
        )
        events, _, repository, preparation, driver = self.components(
            evidence=exhausted,
            inspections=[
                inspection(DriverState.RUNNING, health=DriverHealth.UNHEALTHY),
                inspection(DriverState.RUNNING, health=DriverHealth.UNHEALTHY),
                inspection(DriverState.RUNNING, health=DriverHealth.UNHEALTHY),
            ],
            driver_type=AmbiguousHealthStopDriver,
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
            now=FIXED_NOW + timedelta(seconds=10),
        ).reconcile(reconciliation_job())

        self.assertEqual(
            result.failure_code,
            "health_retries_exhausted_stop_unresolved",
        )
        self.assertEqual(events.count(("stop", "paper-attempt-1")), 1)
        self.assertFalse(
            any(event[0] == "failed" for event in events if isinstance(event, tuple))
        )

    def test_ambiguous_probe_never_stops_or_records_failed(self) -> None:
        events, _, repository, preparation, driver = self.components()
        driver.observation = HealthObservation(
            DriverHealth.UNKNOWN,
            1,
            "health_transport",
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "health_outcome_ambiguous")
        self.assertFalse(
            any(event[0] == "stop" for event in events if isinstance(event, tuple))
        )
        self.assertFalse(
            any(event[0] == "failed" for event in events if isinstance(event, tuple))
        )

    def test_mutated_probe_observation_is_blocked_without_stop_or_failed(self) -> None:
        events, _, repository, preparation, driver = self.components()
        mutated = HealthObservation(DriverHealth.HEALTHY, 1, None)
        object.__setattr__(mutated, "attempts", -1)
        driver.observation = mutated

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "health_observation_invalid")
        self.assertFalse(
            any(
                event[0] in {"stop", "failed"}
                for event in events
                if isinstance(event, tuple)
            )
        )

    def test_offline_publish_failure_stops_before_failure_latch(self) -> None:
        class FailingPublisher:
            def publish(self, identity):
                raise OfflineIdentityStorageError()

        events, _, repository, preparation, driver = self.components(
            inspections=[
                inspection(DriverState.RUNNING, health=DriverHealth.STARTING),
                inspection(DriverState.RUNNING, health=DriverHealth.STARTING),
            ]
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
            offline_publisher=FailingPublisher(),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "offline_identity_publish_failed")
        self.assertEqual(events.count(("stop", "paper-attempt-1")), 1)
        self.assertLess(
            events.index(("stop", "paper-attempt-1")),
            events.index(
                (
                    "failed",
                    "job-1",
                    "paper-attempt-1",
                    "offline_identity_publish_failed",
                )
            ),
        )

    def test_driver_transport_error_is_classified_without_runtime_mutation(
        self,
    ) -> None:
        class TransportDriver(RecordingDriver):
            def inspect(self, identity):
                self.events.append(("inspect", identity.attempt_id))
                raise DriverTransportError()

        events, _, repository, preparation, driver = self.components(
            driver_type=TransportDriver
        )

        result = reconciler(
            repository,
            preparation,
            driver,
            NetworkGateSpy(events),
        ).reconcile(reconciliation_job())

        self.assertEqual(result.failure_code, "runtime_transport_error")
        self.assertFalse(
            any(
                event[0] in {"launch", "stop", "probe", "failed"}
                for event in events
                if isinstance(event, tuple)
            )
        )


if __name__ == "__main__":
    unittest.main()
