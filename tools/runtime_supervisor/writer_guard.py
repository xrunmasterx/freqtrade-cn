from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator

from tools.runtime_driver import DriverPolicyError


_UNBOUND = object()


class SupervisorWriterGuardError(DriverPolicyError):
    code = "supervisor_writer_guard_invalid"


class SupervisorDockerWriterGuard:
    """Binds Docker mutation authority to one held Supervisor process lock."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._authority: object = _UNBOUND
        self._active = False
        self._revoked = False

    def activate(self, process_authority: object) -> SupervisorDockerWriterGuard:
        self._require_identity_authority(process_authority)
        with self._lock:
            if self._revoked or (
                self._authority is not _UNBOUND
                and self._authority is not process_authority
            ):
                raise SupervisorWriterGuardError()
            self._authority = process_authority
            self._active = True
        return self

    def require_active(self, process_authority: object) -> None:
        self._require_identity_authority(process_authority)
        with self._lock:
            self._require_active_locked(process_authority)

    def revoke(self, process_authority: object) -> None:
        self._require_identity_authority(process_authority)
        with self._lock:
            if self._authority is not process_authority:
                raise SupervisorWriterGuardError()
            if self._revoked:
                return
            if not self._active:
                raise SupervisorWriterGuardError()
            self._active = False
            self._revoked = True

    @contextmanager
    def mutation_scope(self, process_authority: object) -> Iterator[None]:
        self._require_identity_authority(process_authority)
        self._lock.acquire()
        try:
            self._require_active_locked(process_authority)
            yield
        finally:
            self._lock.release()

    def _require_active_locked(self, process_authority: object) -> None:
        if (
            not self._active
            or self._revoked
            or self._authority is not process_authority
        ):
            raise SupervisorWriterGuardError()

    @staticmethod
    def _require_identity_authority(process_authority: object) -> None:
        from tools.runtime_supervisor.daemon import (
            SupervisorDaemonError,
            SupervisorProcessLock,
        )

        if type(process_authority) is not SupervisorProcessLock:
            raise SupervisorWriterGuardError()
        try:
            process_authority.require_held()
        except SupervisorDaemonError:
            raise SupervisorWriterGuardError() from None
