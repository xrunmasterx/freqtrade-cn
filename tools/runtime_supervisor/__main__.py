from __future__ import annotations

import argparse
from pathlib import Path
import signal
import sys
from threading import Event
from typing import Sequence

from tools.runtime_supervisor.daemon import (
    RuntimeSupervisorDaemon,
    SupervisorDaemonError,
    SupervisorProcessLock,
)
from tools.runtime_supervisor.writer_guard import SupervisorDockerWriterGuard


SUPERVISOR_LOCK_PATH = Path("/run/freqtrade-runtime-supervisor/supervisor.lock")
PRODUCTION_ASSEMBLY_ENABLED = False


class _ClosedArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, _message: str) -> None:
        self.exit(2, "invalid_arguments\n")


def _parser() -> argparse.ArgumentParser:
    parser = _ClosedArgumentParser(prog="runtime-supervisor")
    parser.add_argument("command", choices=("run", "reconcile-once"))
    return parser


def _assemble_supervisor(
    writer_guard: SupervisorDockerWriterGuard,
    writer_authority: SupervisorProcessLock,
) -> RuntimeSupervisorDaemon:
    del writer_guard, writer_authority
    raise SupervisorDaemonError("runtime_supervisor_not_enabled")


class _SignalStop:
    def __init__(self) -> None:
        self._event = Event()
        self._previous: dict[int, object] = {}

    def requested(self) -> bool:
        return self._event.is_set()

    def _request(self, _signum: int, _frame: object) -> None:
        self._event.set()

    def __enter__(self) -> _SignalStop:
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self._request)
        return self

    def __exit__(self, *_exception: object) -> None:
        for signum, handler in self._previous.items():
            signal.signal(signum, handler)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not PRODUCTION_ASSEMBLY_ENABLED:
        sys.stderr.write("runtime_supervisor_not_enabled\n")
        return 78
    if sys.platform != "linux":
        sys.stderr.write("runtime_supervisor_unsupported_platform\n")
        return 78

    try:
        process_lock = SupervisorProcessLock(SUPERVISOR_LOCK_PATH)
        writer_guard = SupervisorDockerWriterGuard()
        with process_lock:
            writer_guard.activate(process_lock)
            try:
                daemon = _assemble_supervisor(writer_guard, process_lock)
                if type(daemon) is not RuntimeSupervisorDaemon:
                    raise SupervisorDaemonError("runtime_supervisor_not_enabled")
                with _SignalStop() as stop:
                    if arguments.command == "run":
                        daemon.run(stop.requested)
                    else:
                        daemon.reconcile_one_job(stop.requested)
            finally:
                writer_guard.revoke(process_lock)
    except SupervisorDaemonError as error:
        if str(error) == "runtime_supervisor_not_enabled":
            sys.stderr.write("runtime_supervisor_not_enabled\n")
            return 78
        sys.stderr.write("runtime_supervisor_failed\n")
        return 75
    except Exception:
        sys.stderr.write("runtime_supervisor_failed\n")
        return 75
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
