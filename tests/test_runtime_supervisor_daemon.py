from __future__ import annotations

import tempfile
import unittest
import io
from contextlib import redirect_stderr
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools.runtime_supervisor.daemon import (
    MINIMUM_LEASE_SECONDS,
    RuntimeSupervisorDaemon,
    SupervisorDaemonError,
    SupervisorProcessLock,
)
from tools.runtime_supervisor import __main__ as supervisor_main
from tools.runtime_supervisor.domain import (
    ReconciliationAction,
    ReconciliationDecision,
    ReconciliationOutcome,
)


@dataclass(frozen=True, slots=True)
class _Job:
    job_id: str
    instance_id: str
    requested_action: str
    expected_instance_version: int
    status: str = "claimed"
    lease_owner: str | None = "runtime-supervisor"
    lease_generation: int = 1
    failure_code: str | None = None


class _Repository:
    def __init__(self, jobs: list[_Job]) -> None:
        self.jobs = jobs
        self.claimed: dict[str, _Job] = {}
        self.claim_count = 0
        self.reclaim_count = 0
        self.renewed: list[tuple[str, int]] = []
        self.fail_renew = False

    def claim_next_job(self, lease_owner: str, lease_seconds: int) -> _Job | None:
        self.claim_count += 1
        if not self.jobs:
            return None
        job = self.jobs.pop(0)
        self.claimed[job.job_id] = job
        return job

    def reclaim_reconciliation_job(
        self,
        job_id: str,
        lease_owner: str,
        lease_seconds: int,
    ) -> _Job:
        self.reclaim_count += 1
        job = _Job(
            job_id=job_id,
            instance_id="paper-instance",
            requested_action="start",
            expected_instance_version=0,
            status="running",
            lease_owner=lease_owner,
            lease_generation=2,
        )
        self.claimed[job_id] = job
        return job

    def renew_lease(
        self,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
        lease_seconds: int,
    ) -> _Job:
        if self.fail_renew:
            raise RuntimeError("lease lost")
        self.renewed.append((job_id, lease_generation))
        current = self.claimed[job_id]
        job = replace(
            current,
            status="running",
            lease_owner=lease_owner,
            lease_generation=lease_generation,
        )
        self.claimed[job_id] = job
        return job

    def list_jobs(self, instance_id: str) -> tuple[_Job, ...]:
        return tuple(
            replace(job, status="succeeded", lease_owner=None)
            for job in self.claimed.values()
            if job.instance_id == instance_id
        )


class _Reconciler:
    def __init__(self, outcomes: list[ReconciliationOutcome]) -> None:
        self.outcomes = outcomes
        self.jobs: list[object] = []

    def reconcile(self, job: object) -> ReconciliationOutcome:
        self.jobs.append(job)
        return self.outcomes.pop(0)


def _outcome(decision: ReconciliationDecision) -> ReconciliationOutcome:
    return ReconciliationOutcome(
        action=ReconciliationAction.START,
        decision=decision,
        attempt_id="paper-attempt" if decision is not ReconciliationDecision.LAUNCH else None,
        failure_code=None,
    )


class RuntimeSupervisorDaemonTests(unittest.TestCase):
    def test_continue_observing_retains_one_job_and_renews_before_each_step(self) -> None:
        first = _Job("job-one", "paper-instance", "start", 0)
        second = replace(first, job_id="job-two")
        repository = _Repository([first, second])
        reconciler = _Reconciler(
            [
                _outcome(ReconciliationDecision.CONTINUE_OBSERVING),
                _outcome(ReconciliationDecision.ADOPT),
                _outcome(ReconciliationDecision.ADOPT),
            ]
        )
        daemon = RuntimeSupervisorDaemon(repository, reconciler)

        daemon.run_once()
        daemon.run_once()
        daemon.run_once()

        self.assertEqual(repository.claim_count, 2)
        self.assertEqual(
            repository.renewed,
            [("job-one", 1), ("job-one", 1), ("job-two", 1)],
        )
        self.assertEqual(
            [job.job_id for job in reconciler.jobs],
            ["job-one", "job-one", "job-two"],
        )

    def test_expired_claim_is_reclaimed_before_renew_or_reconcile(self) -> None:
        stale = _Job(
            "job-stale",
            "paper-instance",
            "start",
            0,
            status="needs_reconciliation",
            lease_owner=None,
            lease_generation=1,
            failure_code="stale_lease",
        )
        repository = _Repository([stale])
        reconciler = _Reconciler([_outcome(ReconciliationDecision.ADOPT)])

        RuntimeSupervisorDaemon(repository, reconciler).run_once()

        self.assertEqual(repository.reclaim_count, 1)
        self.assertEqual(repository.renewed, [("job-stale", 2)])
        self.assertEqual(reconciler.jobs[0].lease_generation, 2)

    def test_stale_reclaim_requires_an_unowned_exact_stale_job(self) -> None:
        stale = _Job(
            "job-stale",
            "paper-instance",
            "start",
            0,
            status="needs_reconciliation",
            lease_owner="unexpected-owner",
            lease_generation=1,
            failure_code="stale_lease",
        )
        repository = _Repository([stale])
        reconciler = _Reconciler([_outcome(ReconciliationDecision.ADOPT)])

        with self.assertRaisesRegex(
            SupervisorDaemonError,
            "unsafe_reconciliation_job",
        ):
            RuntimeSupervisorDaemon(repository, reconciler).run_once()

        self.assertEqual(repository.reclaim_count, 0)
        self.assertEqual(repository.renewed, [])
        self.assertEqual(reconciler.jobs, [])

    def test_reclaim_and_renew_must_return_exact_running_state(self) -> None:
        stale = _Job(
            "job-stale",
            "paper-instance",
            "start",
            0,
            status="needs_reconciliation",
            lease_owner=None,
            lease_generation=1,
            failure_code="stale_lease",
        )
        repository = _Repository([stale])
        repository.reclaim_reconciliation_job = mock.Mock(
            return_value=replace(
                stale,
                status="claimed",
                lease_owner="runtime-supervisor",
                lease_generation=2,
                failure_code=None,
            )
        )
        reconciler = _Reconciler([_outcome(ReconciliationDecision.ADOPT)])
        with self.assertRaisesRegex(
            SupervisorDaemonError,
            "supervisor_reclaim_changed",
        ):
            RuntimeSupervisorDaemon(repository, reconciler).run_once()
        self.assertEqual(reconciler.jobs, [])

        repository = _Repository(
            [_Job("job-one", "paper-instance", "start", 0)]
        )
        original_renew = repository.renew_lease

        def invalid_renew(*args: object, **kwargs: object) -> _Job:
            return replace(original_renew(*args, **kwargs), status="succeeded")

        repository.renew_lease = invalid_renew  # type: ignore[method-assign]
        reconciler = _Reconciler([_outcome(ReconciliationDecision.ADOPT)])
        with self.assertRaisesRegex(
            SupervisorDaemonError,
            "supervisor_job_changed",
        ):
            RuntimeSupervisorDaemon(repository, reconciler).run_once()
        self.assertEqual(reconciler.jobs, [])

    def test_retry_is_the_only_action_normalized_to_start(self) -> None:
        retry = _Job("job-retry", "paper-instance", "retry", 7)
        repository = _Repository([retry])
        reconciler = _Reconciler([_outcome(ReconciliationDecision.ADOPT)])

        RuntimeSupervisorDaemon(repository, reconciler).run_once()

        job = reconciler.jobs[0]
        self.assertIs(job.action, ReconciliationAction.START)
        self.assertEqual(job.instance_revision, 7)

    def test_lease_renewal_failure_performs_zero_reconciliation(self) -> None:
        repository = _Repository([_Job("job-one", "paper-instance", "start", 0)])
        repository.fail_renew = True
        reconciler = _Reconciler([_outcome(ReconciliationDecision.ADOPT)])

        with self.assertRaisesRegex(SupervisorDaemonError, "supervisor_lease_lost"):
            daemon = RuntimeSupervisorDaemon(repository, reconciler)
            daemon.run_once()

        self.assertEqual(reconciler.jobs, [])
        with self.assertRaisesRegex(
            SupervisorDaemonError, "supervisor_daemon_poisoned"
        ):
            daemon.run_once()
        self.assertEqual(repository.claim_count, 1)
        self.assertEqual(reconciler.jobs, [])

    def test_rejects_unbounded_configuration_and_non_start_stop_actions(self) -> None:
        repository = _Repository([])
        reconciler = _Reconciler([])
        for values in (
            {"lease_seconds": 0},
            {"lease_seconds": MINIMUM_LEASE_SECONDS - 1},
            {"lease_seconds": 3601},
            {"poll_interval_seconds": 0},
            {"poll_interval_seconds": 61},
            {"lease_owner": "INVALID"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                RuntimeSupervisorDaemon(repository, reconciler, **values)

        repository = _Repository([_Job("job-retire", "paper-instance", "retire", 0)])
        with self.assertRaisesRegex(SupervisorDaemonError, "unsupported_runtime_action"):
            RuntimeSupervisorDaemon(repository, reconciler).run_once()
        self.assertEqual(reconciler.jobs, [])

    def test_run_is_serial_and_stops_at_the_requested_boundary(self) -> None:
        repository = _Repository([])
        reconciler = _Reconciler([])
        stop = SimpleNamespace(calls=0)

        def stop_requested() -> bool:
            stop.calls += 1
            return stop.calls > 2

        sleeps: list[float] = []
        RuntimeSupervisorDaemon(
            repository,
            reconciler,
            sleeper=sleeps.append,
        ).run(stop_requested)

        self.assertEqual(repository.claim_count, 2)
        self.assertEqual(sleeps, [1.0, 1.0])

    def test_launch_decision_is_not_a_durable_terminal_outcome(self) -> None:
        repository = _Repository(
            [
                _Job("job-one", "paper-instance", "start", 0),
                _Job("job-two", "paper-instance", "start", 0),
            ]
        )
        reconciler = _Reconciler([_outcome(ReconciliationDecision.LAUNCH)])
        daemon = RuntimeSupervisorDaemon(repository, reconciler)

        with self.assertRaisesRegex(SupervisorDaemonError, "supervisor_outcome_invalid"):
            daemon.run_once()
        with self.assertRaisesRegex(SupervisorDaemonError, "supervisor_daemon_poisoned"):
            daemon.run_once()

        self.assertEqual(repository.claim_count, 1)
        self.assertEqual(len(reconciler.jobs), 1)

    def test_reconcile_one_job_polls_only_the_retained_job_to_terminal(self) -> None:
        repository = _Repository(
            [
                _Job("job-one", "paper-instance", "start", 0),
                _Job("job-two", "paper-instance", "start", 0),
            ]
        )
        reconciler = _Reconciler(
            [
                _outcome(ReconciliationDecision.CONTINUE_OBSERVING),
                _outcome(ReconciliationDecision.ADOPT),
            ]
        )
        sleeps: list[float] = []
        outcome = RuntimeSupervisorDaemon(
            repository,
            reconciler,
            sleeper=sleeps.append,
        ).reconcile_one_job(lambda: False)

        self.assertIsNotNone(outcome)
        self.assertIs(outcome.decision, ReconciliationDecision.ADOPT)
        self.assertEqual(repository.claim_count, 1)
        self.assertEqual(sleeps, [1.0])


class SupervisorProcessLockTests(unittest.TestCase):
    def test_second_writer_is_rejected_until_the_first_releases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "supervisor.lock"
            first = SupervisorProcessLock(path)
            second = SupervisorProcessLock(path)
            with first:
                with self.assertRaisesRegex(
                    SupervisorDaemonError, "supervisor_already_running"
                ):
                    second.acquire()
            with second:
                self.assertTrue(path.is_file())

    def test_relative_or_symlink_lock_path_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            SupervisorProcessLock(Path("relative.lock"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.lock"
            target.write_bytes(b"0")
            link = root / "link.lock"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            with self.assertRaisesRegex(
                SupervisorDaemonError, "supervisor_lock_invalid"
            ):
                SupervisorProcessLock(link).acquire()

    def test_symlink_lock_parent_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlink creation is unavailable")
            with self.assertRaisesRegex(
                SupervisorDaemonError,
                "supervisor_lock_invalid",
            ):
                SupervisorProcessLock(link / "supervisor.lock").acquire()


class RuntimeSupervisorMainTests(unittest.TestCase):
    def test_unconfigured_production_assembly_fails_closed(self) -> None:
        for command in ("run", "reconcile-once"):
            with (
                self.subTest(command=command),
                mock.patch.object(supervisor_main, "SupervisorProcessLock") as lock,
                mock.patch.object(
                    supervisor_main,
                    "SupervisorDockerWriterGuard",
                ) as writer_guard,
                mock.patch.object(supervisor_main, "_assemble_supervisor") as assemble,
            ):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    code = supervisor_main.main([command])
            self.assertEqual(code, 78)
            self.assertEqual(stderr.getvalue(), "runtime_supervisor_not_enabled\n")
            lock.assert_not_called()
            writer_guard.assert_not_called()
            assemble.assert_not_called()

    def test_machine_readable_production_boundary_remains_closed(self) -> None:
        self.assertIs(supervisor_main.PRODUCTION_ASSEMBLY_ENABLED, False)
        self.assertIs(
            supervisor_main.INTERNAL_PERSISTED_ASSEMBLY_SEAM_AVAILABLE,
            True,
        )
        self.assertIs(supervisor_main.HOST_RUNTIME_MUTATION_BRIDGE_ENABLED, False)

    def test_unknown_arguments_fail_without_loading_assembly(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as error:
                supervisor_main.main(["run", "--docker-host", "untrusted"])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(stderr.getvalue(), "invalid_arguments\n")

    def test_enabled_entrypoint_rejects_unsupported_platform_without_traceback(self) -> None:
        stderr = io.StringIO()
        with (
            redirect_stderr(stderr),
            mock.patch.object(supervisor_main, "PRODUCTION_ASSEMBLY_ENABLED", True),
            mock.patch.object(supervisor_main.sys, "platform", "win32"),
        ):
            code = supervisor_main.main(["run"])
        self.assertEqual(code, 78)
        self.assertEqual(
            stderr.getvalue(),
            "runtime_supervisor_unsupported_platform\n",
        )

    def test_unexpected_entrypoint_failure_is_redacted(self) -> None:
        stderr = io.StringIO()
        with (
            redirect_stderr(stderr),
            mock.patch.object(supervisor_main, "PRODUCTION_ASSEMBLY_ENABLED", True),
            mock.patch.object(supervisor_main.sys, "platform", "linux"),
            mock.patch.object(
                supervisor_main,
                "SupervisorProcessLock",
                side_effect=ValueError("sensitive-path"),
            ),
        ):
            code = supervisor_main.main(["run"])
        self.assertEqual(code, 75)
        self.assertEqual(stderr.getvalue(), "runtime_supervisor_failed\n")


if __name__ == "__main__":
    unittest.main()
