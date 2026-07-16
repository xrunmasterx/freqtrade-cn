from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from tools.runtime_driver import DriverValidationError, HealthProfile
from tools.runtime_supervisor.health import (
    health_deadline,
    health_probe_not_before,
    health_profile_digest,
)


ROOT = Path(__file__).resolve().parents[1]


def profile() -> HealthProfile:
    return HealthProfile(
        profile_id="runtime-health",
        probe_argv=("probe",),
        start_period_seconds=30,
        interval_seconds=10,
        timeout_seconds=2,
        retries=3,
    )


class RuntimeSupervisorHealthTests(unittest.TestCase):
    def test_profile_digest_is_deterministic_and_binds_every_field(self) -> None:
        first = profile()
        self.assertEqual(health_profile_digest(first), health_profile_digest(first))
        mutations = (
            HealthProfile("other", first.probe_argv, 30, 10, 2, 3),
            HealthProfile(first.profile_id, ("other",), 30, 10, 2, 3),
            HealthProfile(first.profile_id, first.probe_argv, 31, 10, 2, 3),
            HealthProfile(first.profile_id, first.probe_argv, 30, 11, 2, 3),
            HealthProfile(first.profile_id, first.probe_argv, 30, 10, 3, 3),
            HealthProfile(first.profile_id, first.probe_argv, 30, 10, 2, 4),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertNotEqual(
                    health_profile_digest(first), health_profile_digest(mutation)
                )

    def test_schedule_is_anchored_to_persisted_start_time(self) -> None:
        started_at = datetime(2026, 7, 16, 1, 2, 3, tzinfo=UTC)
        self.assertEqual(
            health_probe_not_before(started_at, profile(), 1),
            datetime(2026, 7, 16, 1, 2, 33, tzinfo=UTC),
        )
        self.assertEqual(
            health_probe_not_before(started_at, profile(), 3),
            datetime(2026, 7, 16, 1, 2, 53, tzinfo=UTC),
        )
        self.assertEqual(
            health_deadline(started_at, profile()),
            datetime(2026, 7, 16, 1, 2, 55, tzinfo=UTC),
        )

    def test_rejects_untrusted_types_and_non_utc_schedule_inputs(self) -> None:
        class HealthProfileSubclass(HealthProfile):
            pass

        value = profile()
        with self.assertRaises(DriverValidationError):
            health_profile_digest(
                HealthProfileSubclass(
                    value.profile_id,
                    value.probe_argv,
                    value.start_period_seconds,
                    value.interval_seconds,
                    value.timeout_seconds,
                    value.retries,
                )
            )
        mutated = profile()
        object.__setattr__(mutated, "retries", 0)
        with self.assertRaises(DriverValidationError):
            health_profile_digest(mutated)
        for started_at, ordinal in (
            (datetime(2026, 7, 16, 1, 2, 3), 1),
            (
                datetime(
                    2026,
                    7,
                    16,
                    1,
                    2,
                    3,
                    tzinfo=timezone(timedelta(hours=8)),
                ),
                1,
            ),
            (datetime(2026, 7, 16, 1, 2, 3, tzinfo=UTC), 0),
            (datetime(2026, 7, 16, 1, 2, 3, tzinfo=UTC), 4),
            (datetime(2026, 7, 16, 1, 2, 3, tzinfo=UTC), True),
        ):
            with self.subTest(started_at=started_at, ordinal=ordinal):
                with self.assertRaises(DriverValidationError):
                    health_probe_not_before(started_at, value, ordinal)

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

import tools.runtime_supervisor.health
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
