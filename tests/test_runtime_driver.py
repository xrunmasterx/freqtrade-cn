from __future__ import annotations

import dataclasses
import subprocess
import sys
import unittest
from unittest import mock


class RuntimeDriverIdentityTests(unittest.TestCase):
    def valid_identity(self):
        from tools.runtime_driver import DriverIdentity

        return DriverIdentity(
            project_name="runtime-phase2-paper-probe",
            container_name="runtime-phase2-paper-probe-attempt-1",
            instance_id="phase2-spot-paper-probe",
            attempt_id="phase2-spot-paper-probe-attempt-1",
            runtime_spec_digest="a" * 64,
            state_allocation_id="phase2-spot-paper-probe-state",
            image_id="sha256:" + "b" * 64,
            network_names=(
                "runtime-phase2-paper-probe-access",
                "runtime-phase2-paper-probe-private",
            ),
        )

    def test_identity_is_frozen_and_rejects_noncanonical_values(self) -> None:
        identity = self.valid_identity()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.instance_id = "other"

        from tools.runtime_driver import DriverIdentity

        invalid = (
            {"runtime_spec_digest": "A" * 64},
            {"image_id": "repo:tag"},
            {"network_names": ("z-network", "a-network")},
            {"network_names": ("same", "same")},
            {"network_names": []},
            {"project_name": ""},
        )
        original = dataclasses.asdict(identity)
        for mutation in invalid:
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    DriverIdentity(**{**original, **mutation})

    def test_absent_and_partial_observations_are_representable(self) -> None:
        from tools.runtime_driver import DriverHealth, DriverInspection, DriverState

        absent = DriverInspection.absent()
        self.assertEqual(absent.state, DriverState.ABSENT)
        self.assertIsNone(absent.container_id)

        observed = DriverInspection(
            state=DriverState.RUNNING,
            container_id="c" * 64,
            observed_project_name="wrong-project",
            observed_container_name="runtime-phase2-paper-probe-attempt-1",
            observed_instance_id=None,
            observed_attempt_id="wrong-attempt",
            observed_runtime_spec_digest=None,
            observed_state_allocation_id=None,
            observed_image_id="sha256:" + "d" * 64,
            observed_network_names=("unexpected-network",),
            health=DriverHealth.UNKNOWN,
            exit_code=None,
        )
        self.assertIsNone(observed.observed_instance_id)
        self.assertEqual(observed.observed_attempt_id, "wrong-attempt")

    def test_inspection_state_invariants_fail_closed(self) -> None:
        from tools.runtime_driver import DriverHealth, DriverInspection, DriverState

        with self.assertRaises(ValueError):
            DriverInspection(
                state=DriverState.ABSENT,
                container_id="c" * 64,
                observed_project_name=None,
                observed_container_name=None,
                observed_instance_id=None,
                observed_attempt_id=None,
                observed_runtime_spec_digest=None,
                observed_state_allocation_id=None,
                observed_image_id=None,
                observed_network_names=(),
                health=DriverHealth.UNKNOWN,
                exit_code=None,
            )
        with self.assertRaises(ValueError):
            DriverInspection(
                state=DriverState.EXITED,
                container_id="c" * 64,
                observed_project_name=None,
                observed_container_name=None,
                observed_instance_id=None,
                observed_attempt_id=None,
                observed_runtime_spec_digest=None,
                observed_state_allocation_id=None,
                observed_image_id=None,
                observed_network_names=(),
                health=DriverHealth.UNKNOWN,
                exit_code=None,
            )

    def test_health_contract_uses_argv_and_redacted_failure_code(self) -> None:
        from tools.runtime_driver import DriverHealth, HealthObservation, HealthProfile

        profile = HealthProfile(
            profile_id="freqtrade-ping-v1",
            probe_argv=("freqtrade", "list-exchanges"),
            start_period_seconds=10,
            interval_seconds=5,
            timeout_seconds=5,
            retries=3,
        )
        self.assertEqual(profile.probe_argv[0], "freqtrade")
        with self.assertRaises(ValueError):
            HealthProfile(
                profile_id="freqtrade-ping-v1",
                probe_argv="freqtrade list-exchanges",
                start_period_seconds=10,
                interval_seconds=5,
                timeout_seconds=5,
                retries=3,
            )
        with self.assertRaises(ValueError):
            HealthProfile(
                profile_id="freqtrade-ping-v1",
                probe_argv=("freqtrade",),
                start_period_seconds=0,
                interval_seconds=5,
                timeout_seconds=6,
                retries=1,
            )
        with self.assertRaises(ValueError):
            HealthProfile(
                profile_id="freqtrade-ping-v1",
                probe_argv=("freqtrade",),
                start_period_seconds=0,
                interval_seconds=5,
                timeout_seconds=5,
                retries=True,
            )

        observation = HealthObservation(
            status=DriverHealth.UNHEALTHY,
            attempts=3,
            failure_code="health_timeout",
        )
        self.assertEqual(observation.failure_code, "health_timeout")

    def test_action_errors_have_only_fixed_redacted_messages(self) -> None:
        from tools.runtime_driver import (
            AmbiguousDriverOutcome,
            DriverIdentityMismatch,
            DriverObjectOccupied,
            DriverPolicyError,
            DriverTransportError,
            DriverValidationError,
        )

        expected = {
            DriverValidationError: "driver_validation_error",
            DriverPolicyError: "driver_policy_error",
            DriverIdentityMismatch: "driver_identity_mismatch",
            DriverObjectOccupied: "driver_object_occupied",
            AmbiguousDriverOutcome: "ambiguous_driver_outcome",
            DriverTransportError: "driver_transport_error",
        }
        for error_type, message in expected.items():
            with self.subTest(error_type=error_type):
                self.assertEqual(str(error_type()), message)
                with self.assertRaises(TypeError):
                    error_type("private detail")

    def test_import_performs_no_io(self) -> None:
        script = "import tools.runtime_driver; print('import_ok')"
        completed = subprocess.run(
            [sys.executable, "-S", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "import_ok\n")
