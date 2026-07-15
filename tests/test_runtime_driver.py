from __future__ import annotations

import dataclasses
import subprocess
import sys
import unittest
from pathlib import Path, PurePosixPath
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
            {"network_names": ("valid-network", 1)},
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


class LaunchSnapshotTests(unittest.TestCase):
    def valid_snapshot_payload(self) -> dict[str, object]:
        from tools.runtime_driver import (
            DriverIdentity,
            EnvironmentEntry,
            HealthProfile,
            ReadOnlyMount,
            ResourceLimits,
            RuntimeUser,
            SecretMount,
            WritableStateMount,
        )

        host_root = Path.cwd().resolve() / "runtime-driver-fixtures"
        identity = DriverIdentity(
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
        return {
            "identity": identity,
            "argv": ("freqtrade", "trade", "--config", "/runtime/config/config.json"),
            "working_directory": "/freqtrade",
            "non_secret_environment": (
                EnvironmentEntry("HOME", "/runtime/home"),
            ),
            "read_only_mounts": (
                ReadOnlyMount(
                    host_root / "config.json",
                    PurePosixPath("/runtime/config/config.json"),
                ),
            ),
            "state_mount": WritableStateMount(
                host_root / "state",
                PurePosixPath("/runtime/state"),
                "phase2-spot-paper-probe-state",
            ),
            "secret_mounts": (
                SecretMount(
                    host_root / "secrets" / "api-password" / "value",
                    PurePosixPath("/run/secrets/api-password"),
                    "phase2-paper-probe-api-password",
                    "version-1",
                ),
            ),
            "runtime_user": RuntimeUser(1001, 1001, PurePosixPath("/runtime/home")),
            "internal_ports": (8080,),
            "health_profile": HealthProfile(
                profile_id="freqtrade-ping-v1",
                probe_argv=("freqtrade", "list-exchanges"),
                start_period_seconds=10,
                interval_seconds=5,
                timeout_seconds=5,
                retries=3,
            ),
            "resource_limits": ResourceLimits(1000, 536870912, 256),
        }

    def test_launch_snapshot_is_strict_and_forbids_raw_power(self) -> None:
        from tools.runtime_driver import DriverValidationError, LaunchSnapshot

        snapshot = LaunchSnapshot.model_validate(self.valid_snapshot_payload())
        self.assertEqual(snapshot.identity.instance_id, "phase2-spot-paper-probe")
        for field, value in (
            ("compose", {"services": {}}),
            ("host_port", 9000),
            ("privileged", True),
            ("restart", "unless-stopped"),
            ("labels", {"caller": "chosen"}),
        ):
            with self.subTest(field=field):
                with self.assertRaises(DriverValidationError) as raised:
                    LaunchSnapshot.model_validate(
                        {**self.valid_snapshot_payload(), field: value}
                    )
                self.assertEqual(str(raised.exception), "driver_validation_error")

    def test_snapshot_rejects_secret_environment_and_mount_escape_hatches(self) -> None:
        from tools.runtime_driver import (
            DriverValidationError,
            EnvironmentEntry,
            ReadOnlyMount,
        )

        for name in (
            "API_PASSWORD",
            "FREQTRADE__API_SERVER__JWT_SECRET_KEY",
            "FREQTRADE__API_SERVER__WS_TOKEN",
        ):
            with self.subTest(name=name):
                with self.assertRaises(DriverValidationError) as raised:
                    EnvironmentEntry(name, "private")
                self.assertEqual(str(raised.exception), "driver_validation_error")
        with self.assertRaises(DriverValidationError) as raised:
            ReadOnlyMount(
                Path.cwd().resolve() / "var" / "run" / "docker.sock",
                PurePosixPath("/var/run/docker.sock"),
            )
        self.assertEqual(str(raised.exception), "driver_validation_error")

    def test_mounts_reject_lexical_parent_components(self) -> None:
        from tools.runtime_driver import (
            DriverValidationError,
            ReadOnlyMount,
            SecretMount,
            WritableStateMount,
        )

        host_root = Path.cwd().resolve() / "runtime-driver-fixtures"
        mount_factories = (
            ("read_only", lambda source, target: ReadOnlyMount(source, target)),
            (
                "state",
                lambda source, target: WritableStateMount(
                    source,
                    target,
                    "phase2-spot-paper-probe-state",
                ),
            ),
            (
                "secret",
                lambda source, target: SecretMount(
                    source,
                    target,
                    "phase2-paper-probe-api-password",
                    "version-1",
                ),
            ),
        )
        invalid_paths = (
            (
                host_root / "config" / ".." / "config.json",
                PurePosixPath("/runtime/config/config.json"),
            ),
            (
                host_root / "config.json",
                PurePosixPath("/runtime/config/../config.json"),
            ),
        )
        for mount_kind, factory in mount_factories:
            for source, target in invalid_paths:
                with self.subTest(
                    mount_kind=mount_kind,
                    source=source,
                    target=target,
                ):
                    with self.assertRaises(DriverValidationError) as raised:
                        factory(source, target)
                    self.assertEqual(
                        str(raised.exception),
                        "driver_validation_error",
                    )

    def test_snapshot_rejects_colliding_targets(self) -> None:
        from tools.runtime_driver import (
            DriverValidationError,
            LaunchSnapshot,
            WritableStateMount,
        )

        payload = self.valid_snapshot_payload()
        payload["state_mount"] = WritableStateMount(
            Path.cwd().resolve() / "runtime-driver-fixtures" / "state",
            PurePosixPath("/runtime/config/config.json"),
            "phase2-spot-paper-probe-state",
        )
        with self.assertRaises(DriverValidationError) as raised:
            LaunchSnapshot.model_validate(payload)
        self.assertEqual(str(raised.exception), "driver_validation_error")

    def test_snapshot_rejects_state_identity_mismatch(self) -> None:
        from tools.runtime_driver import (
            DriverValidationError,
            LaunchSnapshot,
            WritableStateMount,
        )

        payload = self.valid_snapshot_payload()
        payload["state_mount"] = WritableStateMount(
            Path.cwd().resolve() / "runtime-driver-fixtures" / "state",
            PurePosixPath("/runtime/state"),
            "wrong-allocation",
        )
        with self.assertRaises(DriverValidationError) as raised:
            LaunchSnapshot.model_validate(payload)
        self.assertEqual(str(raised.exception), "driver_validation_error")

    def test_snapshot_rejects_raw_nested_values_and_boolean_limits(self) -> None:
        from tools.runtime_driver import (
            DriverValidationError,
            LaunchSnapshot,
            ResourceLimits,
        )

        payload = self.valid_snapshot_payload()
        payload["identity"] = dataclasses.asdict(payload["identity"])
        with self.assertRaises(DriverValidationError) as raised:
            LaunchSnapshot.model_validate(payload)
        self.assertEqual(str(raised.exception), "driver_validation_error")

        with self.assertRaises(DriverValidationError) as raised:
            ResourceLimits(True, 536870912, 256)
        self.assertEqual(str(raised.exception), "driver_validation_error")

    def test_protocol_has_exact_driver_neutral_methods(self) -> None:
        from tools.runtime_driver import RuntimeDriver

        self.assertEqual(
            {
                name
                for name in RuntimeDriver.__dict__
                if not name.startswith("_")
            },
            {"inspect", "launch", "stop", "probe"},
        )
