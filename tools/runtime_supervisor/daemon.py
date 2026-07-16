from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import re
import stat
import time
from typing import Callable, Protocol

from tools.runtime_supervisor.domain import (
    ReconciliationAction,
    ReconciliationDecision,
    ReconciliationOutcome,
)
from tools.runtime_supervisor.reconciler import ReconciliationJob


_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}")
MAX_RECONCILIATION_MUTATION_WINDOW_SECONDS = 600
LEASE_SAFETY_MARGIN_SECONDS = 300
MINIMUM_LEASE_SECONDS = (
    MAX_RECONCILIATION_MUTATION_WINDOW_SECONDS + LEASE_SAFETY_MARGIN_SECONDS
)
_TERMINAL_DECISIONS = frozenset(
    {
        ReconciliationDecision.ADOPT,
        ReconciliationDecision.STOP_EXACT,
        ReconciliationDecision.ALREADY_ABSENT,
        ReconciliationDecision.FAIL_LATCHED,
        ReconciliationDecision.IDENTITY_MISMATCH,
    }
)


class SupervisorDaemonError(RuntimeError):
    pass


class ClaimedJobLike(Protocol):
    job_id: str
    instance_id: str
    requested_action: object
    expected_instance_version: int
    status: object
    lease_owner: str | None
    lease_generation: int
    failure_code: str | None


class SupervisorRepositoryPort(Protocol):
    def claim_next_job(
        self,
        lease_owner: str,
        lease_seconds: int,
    ) -> ClaimedJobLike | None: ...

    def reclaim_reconciliation_job(
        self,
        job_id: str,
        lease_owner: str,
        lease_seconds: int,
    ) -> ClaimedJobLike: ...

    def renew_lease(
        self,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
        lease_seconds: int,
    ) -> ClaimedJobLike: ...

    def list_jobs(self, instance_id: str) -> tuple[ClaimedJobLike, ...]: ...


class ReconcilerPort(Protocol):
    def reconcile(self, job: ReconciliationJob) -> ReconciliationOutcome: ...


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _reconciliation_action(value: object) -> ReconciliationAction:
    normalized = _enum_value(value)
    if normalized in {"start", "retry"}:
        return ReconciliationAction.START
    if normalized == "stop":
        return ReconciliationAction.STOP
    raise SupervisorDaemonError("unsupported_runtime_action")


def _require_job(
    job: ClaimedJobLike,
    *,
    lease_owner: str,
    expected_job_id: str | None = None,
    expected_generation: int | None = None,
) -> ClaimedJobLike:
    try:
        values_valid = (
            type(job.job_id) is str
            and _IDENTIFIER.fullmatch(job.job_id) is not None
            and type(job.instance_id) is str
            and _IDENTIFIER.fullmatch(job.instance_id) is not None
            and type(job.expected_instance_version) is int
            and job.expected_instance_version >= 0
            and type(job.lease_generation) is int
            and job.lease_generation >= 1
            and job.lease_owner == lease_owner
        )
    except AttributeError:
        values_valid = False
    if not values_valid:
        raise SupervisorDaemonError("supervisor_job_invalid")
    if expected_job_id is not None and job.job_id != expected_job_id:
        raise SupervisorDaemonError("supervisor_job_changed")
    if (
        expected_generation is not None
        and job.lease_generation != expected_generation
    ):
        raise SupervisorDaemonError("supervisor_lease_changed")
    return job


def _require_stale_job(job: ClaimedJobLike) -> ClaimedJobLike:
    try:
        valid = (
            type(job.job_id) is str
            and _IDENTIFIER.fullmatch(job.job_id) is not None
            and type(job.instance_id) is str
            and _IDENTIFIER.fullmatch(job.instance_id) is not None
            and type(job.expected_instance_version) is int
            and job.expected_instance_version >= 0
            and type(job.lease_generation) is int
            and job.lease_generation >= 1
            and job.lease_owner is None
            and _enum_value(job.status) == "needs_reconciliation"
            and job.failure_code == "stale_lease"
        )
    except AttributeError:
        valid = False
    if not valid:
        raise SupervisorDaemonError("unsafe_reconciliation_job")
    _reconciliation_action(job.requested_action)
    return job


class RuntimeSupervisorDaemon:
    def __init__(
        self,
        repository: SupervisorRepositoryPort,
        reconciler: ReconcilerPort,
        *,
        lease_owner: str = "runtime-supervisor",
        lease_seconds: int = 900,
        poll_interval_seconds: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if (
            type(lease_owner) is not str
            or _IDENTIFIER.fullmatch(lease_owner) is None
            or type(lease_seconds) is not int
            or not MINIMUM_LEASE_SECONDS <= lease_seconds <= 3600
            or type(poll_interval_seconds) not in {int, float}
            or isinstance(poll_interval_seconds, bool)
            or not 0 < poll_interval_seconds <= 60
            or not callable(sleeper)
        ):
            raise ValueError("invalid supervisor daemon configuration")
        self._repository = repository
        self._reconciler = reconciler
        self._lease_owner = lease_owner
        self._lease_seconds = lease_seconds
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._sleeper = sleeper
        self._active_job: ClaimedJobLike | None = None
        self._poisoned = False

    def run_once(self) -> ReconciliationOutcome | None:
        if self._poisoned:
            raise SupervisorDaemonError("supervisor_daemon_poisoned")
        try:
            return self._run_once()
        except SupervisorDaemonError:
            self._active_job = None
            self._poisoned = True
            raise
        except Exception:
            self._active_job = None
            self._poisoned = True
            raise SupervisorDaemonError("supervisor_daemon_failed") from None

    def _run_once(self) -> ReconciliationOutcome | None:
        job = self._active_job
        if job is None:
            try:
                job = self._repository.claim_next_job(
                    self._lease_owner,
                    self._lease_seconds,
                )
            except Exception:
                raise SupervisorDaemonError("supervisor_repository_unavailable") from None
            if job is None:
                return None
            status = _enum_value(getattr(job, "status", None))
            if status == "needs_reconciliation":
                stale = _require_stale_job(job)
                try:
                    job = self._repository.reclaim_reconciliation_job(
                        job.job_id,
                        self._lease_owner,
                        self._lease_seconds,
                    )
                except Exception:
                    raise SupervisorDaemonError("supervisor_reclaim_failed") from None
                if (
                    job.job_id != stale.job_id
                    or job.instance_id != stale.instance_id
                    or _enum_value(job.requested_action)
                    != _enum_value(stale.requested_action)
                    or job.expected_instance_version
                    != stale.expected_instance_version
                    or job.lease_generation != stale.lease_generation + 1
                    or _enum_value(job.status) != "running"
                    or job.failure_code is not None
                ):
                    raise SupervisorDaemonError("supervisor_reclaim_changed")
            job = _require_job(job, lease_owner=self._lease_owner)
            if _enum_value(job.status) not in {"claimed", "running"}:
                raise SupervisorDaemonError("supervisor_job_invalid")
            self._active_job = job

        expected_job_id = job.job_id
        expected_generation = job.lease_generation
        try:
            renewed = self._repository.renew_lease(
                expected_job_id,
                self._lease_owner,
                expected_generation,
                self._lease_seconds,
            )
        except Exception:
            self._active_job = None
            raise SupervisorDaemonError("supervisor_lease_lost") from None
        renewed = _require_job(
            renewed,
            lease_owner=self._lease_owner,
            expected_job_id=expected_job_id,
            expected_generation=expected_generation,
        )
        if (
            _enum_value(renewed.status) != "running"
            or renewed.failure_code is not None
            or renewed.instance_id != job.instance_id
            or renewed.expected_instance_version != job.expected_instance_version
            or _enum_value(renewed.requested_action)
            != _enum_value(job.requested_action)
        ):
            self._active_job = None
            raise SupervisorDaemonError("supervisor_job_changed")
        reconciliation_job = ReconciliationJob(
            job_id=renewed.job_id,
            instance_id=renewed.instance_id,
            action=_reconciliation_action(renewed.requested_action),
            lease_owner=self._lease_owner,
            lease_generation=renewed.lease_generation,
            instance_revision=renewed.expected_instance_version,
        )
        try:
            outcome = self._reconciler.reconcile(reconciliation_job)
        except Exception:
            self._active_job = None
            raise SupervisorDaemonError("supervisor_reconciliation_failed") from None
        if type(outcome) is not ReconciliationOutcome:
            self._active_job = None
            raise SupervisorDaemonError("supervisor_outcome_invalid")
        if outcome.action is not reconciliation_job.action:
            self._active_job = None
            raise SupervisorDaemonError("supervisor_outcome_invalid")
        if outcome.decision is ReconciliationDecision.CONTINUE_OBSERVING:
            self._active_job = renewed
        elif outcome.decision in _TERMINAL_DECISIONS:
            self._verify_terminal_job(renewed, outcome)
            self._active_job = None
        else:
            self._active_job = None
            raise SupervisorDaemonError("supervisor_outcome_invalid")
        return outcome

    def _verify_terminal_job(
        self,
        expected: ClaimedJobLike,
        outcome: ReconciliationOutcome,
    ) -> None:
        try:
            jobs = self._repository.list_jobs(expected.instance_id)
        except Exception:
            raise SupervisorDaemonError("supervisor_terminal_unverified") from None
        matches = tuple(job for job in jobs if job.job_id == expected.job_id)
        if len(matches) != 1:
            raise SupervisorDaemonError("supervisor_terminal_unverified")
        current = matches[0]
        status = _enum_value(current.status)
        if outcome.decision in {
            ReconciliationDecision.ADOPT,
            ReconciliationDecision.STOP_EXACT,
            ReconciliationDecision.ALREADY_ABSENT,
        }:
            durable_result_matches = (
                status == "succeeded" and current.failure_code is None
            )
        elif outcome.decision is ReconciliationDecision.IDENTITY_MISMATCH:
            durable_result_matches = (
                status == "needs_reconciliation"
                and current.failure_code == outcome.failure_code
                and outcome.failure_code is not None
            )
        else:
            durable_result_matches = (
                status in {"failed", "needs_reconciliation"}
                and current.failure_code == outcome.failure_code
                and outcome.failure_code is not None
            )
        if (
            current.instance_id != expected.instance_id
            or _enum_value(current.requested_action)
            != _enum_value(expected.requested_action)
            or current.expected_instance_version != expected.expected_instance_version
            or current.lease_generation != expected.lease_generation
            or not durable_result_matches
            or current.lease_owner is not None
        ):
            raise SupervisorDaemonError("supervisor_terminal_unverified")

    def run(self, stop_requested: Callable[[], bool]) -> None:
        if not callable(stop_requested):
            raise ValueError("stop_requested must be callable")
        while not stop_requested():
            self.run_once()
            self._sleeper(self._poll_interval_seconds)

    def reconcile_one_job(
        self,
        stop_requested: Callable[[], bool],
    ) -> ReconciliationOutcome | None:
        if not callable(stop_requested):
            raise ValueError("stop_requested must be callable")
        while not stop_requested():
            outcome = self.run_once()
            if outcome is None or outcome.decision is not ReconciliationDecision.CONTINUE_OBSERVING:
                return outcome
            self._sleeper(self._poll_interval_seconds)
        return None


@dataclass(slots=True)
class SupervisorProcessLock:
    path: Path
    _descriptor: int | None = None

    def __post_init__(self) -> None:
        if type(self.path) is not type(Path()) or not self.path.is_absolute():
            raise ValueError("supervisor lock path must be absolute")

    def acquire(self) -> None:
        if self._descriptor is not None:
            raise SupervisorDaemonError("supervisor_lock_invalid")
        descriptor: int | None = None
        try:
            parent = os.lstat(self.path.parent)
            if (
                not stat.S_ISDIR(parent.st_mode)
                or bool(
                    getattr(parent, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                )
                or (
                    os.name != "nt"
                    and (parent.st_uid != os.getuid() or parent.st_mode & 0o022)
                )
            ):
                raise SupervisorDaemonError("supervisor_lock_invalid")
            before = None
            try:
                before = os.lstat(self.path)
            except FileNotFoundError:
                pass
            if before is not None and (
                not stat.S_ISREG(before.st_mode)
                or bool(
                    getattr(before, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                )
            ):
                raise SupervisorDaemonError("supervisor_lock_invalid")
            flags = os.O_RDWR | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.path, flags, 0o600)
            current = os.fstat(descriptor)
            if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                raise SupervisorDaemonError("supervisor_lock_invalid")
            if os.name != "nt" and (
                current.st_uid != os.getuid() or current.st_mode & 0o077
            ):
                raise SupervisorDaemonError("supervisor_lock_invalid")
            if before is not None and (
                getattr(before, "st_dev", None),
                getattr(before, "st_ino", None),
            ) != (
                getattr(current, "st_dev", None),
                getattr(current, "st_ino", None),
            ):
                raise SupervisorDaemonError("supervisor_lock_invalid")
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            self._lock_descriptor(descriptor)
            after = os.fstat(descriptor)
            path_after = os.lstat(self.path)
            if (
                getattr(current, "st_dev", None),
                getattr(current, "st_ino", None),
            ) != (
                getattr(after, "st_dev", None),
                getattr(after, "st_ino", None),
            ) or (
                getattr(path_after, "st_dev", None),
                getattr(path_after, "st_ino", None),
            ) != (
                getattr(after, "st_dev", None),
                getattr(after, "st_ino", None),
            ) or not stat.S_ISREG(path_after.st_mode) or bool(
                getattr(path_after, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                raise SupervisorDaemonError("supervisor_lock_invalid")
            self._descriptor = descriptor
        except SupervisorDaemonError:
            if descriptor is not None:
                os.close(descriptor)
            raise
        except OSError as error:
            if descriptor is not None:
                os.close(descriptor)
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise SupervisorDaemonError("supervisor_already_running") from None
            raise SupervisorDaemonError("supervisor_lock_invalid") from None

    @staticmethod
    def _lock_descriptor(descriptor: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError:
                raise SupervisorDaemonError("supervisor_already_running") from None
            return
        import fcntl

        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SupervisorDaemonError("supervisor_already_running") from None

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
            self._descriptor = None

    def require_held(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            raise SupervisorDaemonError("supervisor_lock_invalid")
        try:
            current = os.fstat(descriptor)
            named = os.lstat(self.path)
        except OSError:
            raise SupervisorDaemonError("supervisor_lock_invalid") from None
        if (
            not stat.S_ISREG(current.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (
                getattr(current, "st_dev", None),
                getattr(current, "st_ino", None),
            )
            != (
                getattr(named, "st_dev", None),
                getattr(named, "st_ino", None),
            )
        ):
            raise SupervisorDaemonError("supervisor_lock_invalid")

    def __enter__(self) -> SupervisorProcessLock:
        self.acquire()
        return self

    def __exit__(self, *_exception: object) -> None:
        self.release()
