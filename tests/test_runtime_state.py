from __future__ import annotations

import inspect
import os
import stat
import tempfile
import unittest
from copy import copy
from contextlib import nullcontext
from dataclasses import fields, replace
from pathlib import Path
from unittest import mock

from tools import runtime_state


class RuntimeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.base = Path(self.temporary_directory.name)
        self.state_root = self.base / "ft_userdata/runtime/instances"
        self.state_root.mkdir(parents=True)
        os.chmod(self.state_root, 0o700)
        self.runtime_uid = os.getuid() if os.name == "posix" else 1000
        self.reservation = self.make_reservation()
        self.permission_patchers: list[mock._patch] = []
        self.real_permission_helpers: dict[str, object] = {}
        if os.name == "nt":
            for name in (
                "_harden_managed_state_directory",
                "_verify_managed_state_directory",
                "_harden_managed_state_identity_file",
                "_verify_managed_state_identity_file",
            ):
                self.real_permission_helpers[name] = getattr(runtime_state, name)
                patcher = mock.patch.object(runtime_state, name)
                patcher.start()
                self.addCleanup(patcher.stop)
                self.permission_patchers.append(patcher)

    def make_reservation(
        self, **changes: object
    ) -> runtime_state.StateAllocationReservation:
        values: dict[str, object] = {
            "state_allocation_id": "allocation-1",
            "instance_id": "runtime-1",
            "layout_id": "freqtrade-state-v1",
            "provider_id": "managed-local-v1",
            "relative_path": "ft_userdata/runtime/instances/runtime-1",
            "kind": "fresh",
            "status": "reserved",
            "generation": 1,
            "restore_source_bundle_id": None,
        }
        values.update(changes)
        return runtime_state.StateAllocationReservation(**values)

    def make_existing(self, **changes: object) -> runtime_state.ExistingStateAllocation:
        values: dict[str, object] = {
            "state_allocation_id": "allocation-1",
            "instance_id": "runtime-1",
            "layout_id": "freqtrade-state-v1",
            "provider_id": "managed-local-v1",
            "relative_path": "ft_userdata/runtime/instances/runtime-1",
            "kind": "fresh",
            "status": "ready",
            "generation": 1,
            "restore_source_bundle_id": None,
        }
        values.update(changes)
        return runtime_state.ExistingStateAllocation(**values)

    def make_provisioning(
        self, **changes: object
    ) -> runtime_state.ProvisioningStateAllocation:
        values: dict[str, object] = {
            "state_allocation_id": "allocation-1",
            "instance_id": "runtime-1",
            "layout_id": "freqtrade-state-v1",
            "provider_id": "managed-local-v1",
            "relative_path": "ft_userdata/runtime/instances/runtime-1",
            "kind": "fresh",
            "status": "provisioning",
            "generation": 1,
            "restore_source_bundle_id": None,
        }
        values.update(changes)
        return runtime_state.ProvisioningStateAllocation(**values)

    def provider(
        self,
        reservation: (
            runtime_state.StateAllocationReservation
            | runtime_state.ExistingStateAllocation
            | runtime_state.ProvisioningStateAllocation
            | None
        ) = None,
        *,
        state_root: Path | None = None,
    ) -> runtime_state.ManagedStateProvider:
        return runtime_state.ManagedStateProvider(
            reservation or self.reservation,
            runtime_uid=self.runtime_uid,
            state_root=state_root or self.state_root,
        )

    def provision(
        self,
        provider: runtime_state.ManagedStateProvider | None = None,
    ) -> runtime_state.ProvisionedState:
        return (provider or self.provider()).provision(
            "runtime-1",
            "allocation-1",
            "freqtrade-state-v1",
        )

    def verify_existing(
        self,
        allocation: runtime_state.ExistingStateAllocation | None = None,
    ) -> runtime_state.ProvisionedState:
        provider = self.provider(allocation or self.make_existing())
        return provider.verify_existing(
            "runtime-1",
            "allocation-1",
            "freqtrade-state-v1",
        )

    def resume_provisioning(
        self,
        allocation: runtime_state.ProvisioningStateAllocation | None = None,
        provider: runtime_state.ManagedStateProvider | None = None,
    ) -> runtime_state.ProvisionedState:
        selected = provider or self.provider(allocation or self.make_provisioning())
        return selected.resume_provisioning(
            "runtime-1",
            "allocation-1",
            "freqtrade-state-v1",
        )

    def test_allocation_path_is_platform_derived_and_proof_is_redacted(self) -> None:
        state = self.provision()

        self.assertEqual(state.relative_path, "ft_userdata/runtime/instances/runtime-1")
        self.assertEqual(state.state_allocation_id, "allocation-1")
        self.assertEqual(state.instance_id, "runtime-1")
        self.assertEqual(state.layout_id, "freqtrade-state-v1")
        self.assertEqual(state.provider_id, "managed-local-v1")
        self.assertEqual(state.generation, 1)
        self.assertEqual(
            state.durability,
            "power-loss-posix" if os.name == "posix" else "atomic-process-crash",
        )
        self.assertNotIn(str(self.base), repr(state))

    def test_fixed_layout_and_empty_atomic_identity_are_exact(self) -> None:
        self.provision()

        allocation = self.state_root / "runtime-1"
        self.assertEqual(
            {path.name for path in allocation.iterdir()},
            {"home", "logs", "data", ".allocation-allocation-1"},
        )
        for name in ("home", "logs", "data"):
            self.assertTrue((allocation / name).is_dir())
        identity = allocation / ".allocation-allocation-1"
        self.assertTrue(identity.is_file())
        self.assertEqual(identity.read_bytes(), b"")
        self.assertFalse(
            any(path.name.endswith(".tmp") for path in allocation.iterdir())
        )
        if os.name == "posix":
            for path in (
                allocation,
                allocation / "home",
                allocation / "logs",
                allocation / "data",
            ):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
                self.assertEqual(path.stat().st_uid, self.runtime_uid)
            self.assertEqual(stat.S_IMODE(identity.stat().st_mode), 0o600)
            self.assertEqual(identity.stat().st_nlink, 1)

    def test_relative_root_is_frozen_against_cwd_changes(self) -> None:
        original_cwd = Path.cwd()
        first = self.base / "first"
        second = self.base / "second"
        (first / "state").mkdir(parents=True)
        (second / "state").mkdir(parents=True)
        os.chmod(first / "state", 0o700)
        os.chmod(second / "state", 0o700)
        try:
            os.chdir(first)
            provider = self.provider(state_root=Path("state"))
            os.chdir(second)
            self.provision(provider)
        finally:
            os.chdir(original_cwd)

        self.assertTrue((first / "state/runtime-1").is_dir())
        self.assertFalse((second / "state/runtime-1").exists())

    def test_invalid_reservation_or_call_rejects_before_filesystem_io(self) -> None:
        mutations = (
            {"state_allocation_id": "../allocation"},
            {"instance_id": "Runtime-1"},
            {"layout_id": "other-layout"},
            {"provider_id": "other-provider"},
            {"relative_path": "ft_userdata/runtime/instances/other"},
            {"kind": "restore"},
            {"status": "ready"},
            {"generation": 0},
            {"generation": True},
            {"restore_source_bundle_id": "bundle-1"},
        )
        missing_root = self.base / "does-not-exist"
        for changes in mutations:
            with self.subTest(changes=changes):
                provider = self.provider(
                    self.make_reservation(**changes),
                    state_root=missing_root,
                )
                with self.assertRaisesRegex(
                    runtime_state.StateProvisionError,
                    "^state_reservation_invalid$",
                ):
                    self.provision(provider)

        for arguments in (
            ("runtime-2", "allocation-1", "freqtrade-state-v1"),
            ("runtime-1", "allocation-2", "freqtrade-state-v1"),
            ("runtime-1", "allocation-1", "other-layout"),
        ):
            with self.subTest(arguments=arguments):
                provider = self.provider(state_root=missing_root)
                with self.assertRaisesRegex(
                    runtime_state.StateProvisionError,
                    "^state_reservation_invalid$",
                ):
                    provider.provision(*arguments)
        self.assertFalse(missing_root.exists())

    def test_public_surface_has_no_path_fault_reuse_delete_or_enumeration(self) -> None:
        parameters = tuple(
            inspect.signature(runtime_state.ManagedStateProvider.provision).parameters
        )
        self.assertEqual(
            parameters, ("self", "instance_id", "allocation_id", "layout_id")
        )
        verify_parameters = tuple(
            inspect.signature(
                runtime_state.ManagedStateProvider.verify_existing
            ).parameters
        )
        self.assertEqual(
            verify_parameters,
            ("self", "instance_id", "allocation_id", "layout_id"),
        )
        resume_parameters = tuple(
            inspect.signature(
                runtime_state.ManagedStateProvider.resume_provisioning
            ).parameters
        )
        self.assertEqual(
            resume_parameters,
            ("self", "instance_id", "allocation_id", "layout_id"),
        )
        for name in (
            "provision_with_fault",
            "reuse",
            "delete",
            "cleanup",
            "restore",
            "enumerate",
            "list",
        ):
            self.assertFalse(hasattr(runtime_state.ManagedStateProvider, name))
        self.assertEqual(
            tuple(field.name for field in fields(runtime_state.ProvisionedState)),
            (
                "state_allocation_id",
                "instance_id",
                "layout_id",
                "provider_id",
                "generation",
                "relative_path",
                "durability",
            ),
        )

    def test_mount_lease_is_attempt_scoped_live_and_redacted(self) -> None:
        provider = self.provider()
        proof = self.provision(provider)

        lease = provider.acquire_mount_lease("attempt-1", proof)
        mount = lease.mount
        self.assertEqual(
            tuple(field.name for field in fields(runtime_state.VerifiedStateMount)),
            (
                "attempt_id",
                "state_allocation_id",
                "instance_id",
                "layout_id",
                "provider_id",
                "generation",
                "relative_path",
                "source",
                "runtime_uid",
                "durability",
            ),
        )
        self.assertEqual(mount.attempt_id, "attempt-1")
        self.assertEqual(mount.state_allocation_id, "allocation-1")
        self.assertEqual(mount.source, self.state_root / "runtime-1")
        self.assertEqual(lease.revalidate_source(), mount.source)
        self.assertEqual(provider.revalidate_source(lease), mount.source)
        self.assertNotIn(str(self.base), repr(mount))
        self.assertNotIn(str(self.base), repr(lease))

        lease.close()
        lease.close()
        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_lease_invalid$",
        ):
            lease.revalidate_source()
        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_lease_invalid$",
        ):
            _ = lease.mount

    def test_mount_lease_context_closes_and_allows_later_attempt(self) -> None:
        provider = self.provider()
        proof = self.provision(provider)

        with provider.acquire_mount_lease("attempt-1", proof) as first:
            self.assertEqual(first.mount.attempt_id, "attempt-1")
            with self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_lease_invalid$",
            ):
                provider.acquire_mount_lease("attempt-2", proof)

        with provider.acquire_mount_lease("attempt-2", proof) as second:
            self.assertEqual(second.revalidate_source(), self.state_root / "runtime-1")

    def test_mount_lease_rejects_invalid_attempt_forged_proof_and_wrong_provider(
        self,
    ) -> None:
        provider = self.provider()
        proof = self.provision(provider)
        other_provider = self.provider()

        for attempt_id, candidate in (
            ("Attempt-1", proof),
            ("attempt-1", replace(proof)),
        ):
            with self.subTest(attempt_id=attempt_id, exact=candidate is proof):
                with (
                    mock.patch.object(
                        runtime_state, "_verify_existing_layout"
                    ) as verify,
                    self.assertRaisesRegex(
                        runtime_state.StateProvisionError,
                        "^state_lease_invalid$",
                    ),
                ):
                    provider.acquire_mount_lease(attempt_id, candidate)
                verify.assert_not_called()

        lease = provider.acquire_mount_lease("attempt-1", proof)
        copied = copy(lease)
        for owner, candidate in (
            (provider, copied),
            (other_provider, lease),
        ):
            with self.subTest(owner=owner is provider, exact=candidate is lease):
                with (
                    mock.patch.object(
                        runtime_state, "_verify_existing_layout"
                    ) as verify,
                    self.assertRaisesRegex(
                        runtime_state.StateProvisionError,
                        "^state_lease_invalid$",
                    ),
                ):
                    owner.revalidate_source(candidate)
                verify.assert_not_called()
        lease.close()

    def test_mount_lease_is_minted_from_returned_layout_proof_without_lone_lstat(
        self,
    ) -> None:
        provider = self.provider()
        proof = self.provision(provider)
        real_verify = runtime_state._verify_existing_layout
        real_lstat = runtime_state.os.lstat
        verification_returned = False

        def verify_layout(*args: object, **kwargs: object) -> object:
            nonlocal verification_returned
            result = real_verify(*args, **kwargs)
            verification_returned = True
            return result

        def guarded_lstat(path: object) -> os.stat_result:
            if verification_returned:
                raise AssertionError("lease mint performed a post-verification lstat")
            return real_lstat(path)

        with (
            mock.patch.object(
                runtime_state,
                "_verify_existing_layout",
                side_effect=verify_layout,
            ),
            mock.patch.object(runtime_state.os, "lstat", side_effect=guarded_lstat),
        ):
            lease = provider.acquire_mount_lease("attempt-1", proof)

        lease.close()

    def test_mount_lease_revalidation_allows_business_data_changes(self) -> None:
        provider = self.provider()
        proof = self.provision(provider)
        lease = provider.acquire_mount_lease("attempt-1", proof)
        allocation = self.state_root / "runtime-1"

        (allocation / "data/markets").mkdir()
        (allocation / "data/markets/candles.sqlite").write_bytes(b"business-data")
        (allocation / "logs/runtime.log").write_text("business-log", encoding="utf-8")

        self.assertEqual(lease.revalidate_source(), allocation)
        lease.close()

    def test_mount_lease_rejects_mutated_minted_mount_source_and_metadata(self) -> None:
        provider = self.provider()
        proof = self.provision(provider)
        mutations = (
            ("source", self.base / "caller-controlled-state"),
            ("generation", True),
            ("durability", "arbitrary"),
            ("relative_path", "ft_userdata/runtime/instances/caller"),
        )

        for field_name, value in mutations:
            with self.subTest(field=field_name):
                lease = provider.acquire_mount_lease("attempt-1", proof)
                mount = lease.mount
                object.__setattr__(mount, field_name, value)

                with (
                    mock.patch.object(
                        runtime_state,
                        "_verify_existing_layout",
                    ) as verify_layout,
                    self.assertRaisesRegex(
                        runtime_state.StateProvisionError,
                        "^state_lease_verification_failed$",
                    ),
                ):
                    _ = lease.mount
                verify_layout.assert_not_called()

                with (
                    mock.patch.object(
                        runtime_state,
                        "_verify_existing_layout",
                    ) as verify_layout,
                    self.assertRaisesRegex(
                        runtime_state.StateProvisionError,
                        "^state_lease_verification_failed$",
                    ),
                ):
                    lease.revalidate_source()
                verify_layout.assert_not_called()

                with self.assertRaisesRegex(
                    runtime_state.StateProvisionError,
                    "^state_lease_verification_failed$",
                ):
                    lease.close()

        replacement = provider.acquire_mount_lease("attempt-2", proof)
        self.assertEqual(replacement.revalidate_source(), self.state_root / "runtime-1")
        replacement.close()

    def test_mount_lease_revalidation_rejects_component_identity_replacement(
        self,
    ) -> None:
        provider = self.provider()
        proof = self.provision(provider)
        lease = provider.acquire_mount_lease("attempt-1", proof)
        allocation = self.state_root / "runtime-1"
        original = allocation / "data"
        displaced = allocation / "data-displaced"
        original.rename(displaced)
        original.mkdir(mode=0o700)
        if os.name == "posix":
            os.chmod(original, 0o700)

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_lease_verification_failed$",
        ) as raised:
            lease.revalidate_source()
        self.assertNotIn(str(self.base), str(raised.exception))
        lease.close()

    def test_mount_lease_revalidation_rejects_allocation_identity_replacement(
        self,
    ) -> None:
        provider = self.provider()
        proof = self.provision(provider)
        lease = provider.acquire_mount_lease("attempt-1", proof)
        allocation = self.state_root / "runtime-1"
        displaced = self.state_root / "runtime-1-displaced"
        allocation.rename(displaced)
        allocation.mkdir(mode=0o700)
        for name in ("home", "logs", "data"):
            (allocation / name).mkdir(mode=0o700)
        marker = allocation / ".allocation-allocation-1"
        marker.write_bytes(b"")
        if os.name == "posix":
            os.chmod(marker, 0o600)

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_lease_verification_failed$",
        ):
            lease.revalidate_source()
        lease.close()

    def test_mount_lease_revalidation_rejects_allocation_marker_replacement(
        self,
    ) -> None:
        provider = self.provider()
        proof = self.provision(provider)
        lease = provider.acquire_mount_lease("attempt-1", proof)
        marker = self.state_root / "runtime-1/.allocation-allocation-1"
        displaced = marker.with_name(".allocation-original")
        marker.rename(displaced)
        marker.write_bytes(b"")
        if os.name == "posix":
            os.chmod(marker, 0o600)

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_lease_verification_failed$",
        ):
            provider.revalidate_source(lease)
        lease.close()

    def test_existing_allocation_is_a_closed_frozen_value(self) -> None:
        allocation = self.make_existing()

        self.assertEqual(
            tuple(
                field.name for field in fields(runtime_state.ExistingStateAllocation)
            ),
            (
                "state_allocation_id",
                "instance_id",
                "layout_id",
                "provider_id",
                "relative_path",
                "kind",
                "status",
                "generation",
                "restore_source_bundle_id",
            ),
        )
        with self.assertRaises((AttributeError, TypeError)):
            allocation.status = "reserved"  # type: ignore[misc]
        with self.assertRaises((AttributeError, TypeError)):
            allocation.unexpected = "authority"  # type: ignore[attr-defined]

    def test_provisioning_allocation_is_a_closed_frozen_value(self) -> None:
        allocation = self.make_provisioning()

        self.assertEqual(
            tuple(
                field.name
                for field in fields(runtime_state.ProvisioningStateAllocation)
            ),
            (
                "state_allocation_id",
                "instance_id",
                "layout_id",
                "provider_id",
                "relative_path",
                "kind",
                "status",
                "generation",
                "restore_source_bundle_id",
            ),
        )
        with self.assertRaises((AttributeError, TypeError)):
            allocation.status = "ready"  # type: ignore[misc]
        with self.assertRaises((AttributeError, TypeError)):
            allocation.unexpected = "authority"  # type: ignore[attr-defined]

    def test_provider_methods_reject_the_other_allocation_lifecycle(self) -> None:
        existing_provider = self.provider(self.make_existing())
        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_reservation_invalid$",
        ):
            self.provision(existing_provider)

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_existing_invalid$",
        ):
            self.provider().verify_existing(
                "runtime-1",
                "allocation-1",
                "freqtrade-state-v1",
            )

        provisioning_provider = self.provider(self.make_provisioning())
        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_reservation_invalid$",
        ):
            self.provision(provisioning_provider)
        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_existing_invalid$",
        ):
            provisioning_provider.verify_existing(
                "runtime-1",
                "allocation-1",
                "freqtrade-state-v1",
            )
        for provider in (
            self.provider(),
            self.provider(self.make_existing()),
        ):
            with self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_invalid$",
            ):
                self.resume_provisioning(provider=provider)

    def test_invalid_provisioning_allocation_rejects_before_filesystem_io(self) -> None:
        mutations = (
            {"state_allocation_id": "../allocation"},
            {"instance_id": "Runtime-1"},
            {"layout_id": "other-layout"},
            {"provider_id": "other-provider"},
            {"relative_path": "ft_userdata/runtime/instances/other"},
            {"kind": "restored"},
            {"status": "ready"},
            {"generation": 0},
            {"generation": True},
            {"restore_source_bundle_id": "bundle-1"},
        )
        missing_root = self.base / "missing-provisioning-root"
        for changes in mutations:
            with self.subTest(changes=changes):
                provider = self.provider(
                    self.make_provisioning(**changes),
                    state_root=missing_root,
                )
                with self.assertRaisesRegex(
                    runtime_state.StateProvisionError,
                    "^state_provisioning_invalid$",
                ):
                    self.resume_provisioning(provider=provider)
        provider = self.provider(self.make_provisioning(), state_root=missing_root)
        for arguments in (
            ("runtime-2", "allocation-1", "freqtrade-state-v1"),
            ("runtime-1", "allocation-2", "freqtrade-state-v1"),
            ("runtime-1", "allocation-1", "other-layout"),
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(
                    runtime_state.StateProvisionError,
                    "^state_provisioning_invalid$",
                ):
                    provider.resume_provisioning(*arguments)
        self.assertFalse(missing_root.exists())

    def test_resume_provisioning_creates_missing_layout_and_issues_closable_lease(
        self,
    ) -> None:
        provider = self.provider(self.make_provisioning())

        proof = self.resume_provisioning(provider=provider)

        self.assertEqual(
            {path.name for path in (self.state_root / "runtime-1").iterdir()},
            {"home", "logs", "data", ".allocation-allocation-1"},
        )
        lease = provider.acquire_mount_lease("attempt-1", proof)
        with lease:
            self.assertEqual(lease.mount.source, self.state_root / "runtime-1")
        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_lease_invalid$",
        ):
            _ = lease.mount

    def test_resume_provisioning_verifies_complete_layout_without_mutation(self) -> None:
        expected = self.provision()
        provider = self.provider(self.make_provisioning())
        allocation = self.state_root / "runtime-1"
        before = {
            path.relative_to(self.state_root): (
                path.stat().st_dev,
                path.stat().st_ino,
                path.stat().st_mode,
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in (allocation, *allocation.iterdir())
        }

        with (
            mock.patch.object(runtime_state.os, "mkdir") as mkdir,
            mock.patch.object(runtime_state.os, "rename") as rename,
            mock.patch.object(runtime_state.os, "chmod") as chmod,
            mock.patch.object(runtime_state, "_publish_no_replace") as publish,
            mock.patch.object(runtime_state, "_quarantine_owned_allocation") as quarantine,
        ):
            actual = self.resume_provisioning(provider=provider)

        after = {
            path.relative_to(self.state_root): (
                path.stat().st_dev,
                path.stat().st_ino,
                path.stat().st_mode,
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in (allocation, *allocation.iterdir())
        }
        self.assertEqual(actual, expected)
        self.assertEqual(after, before)
        lease = provider.acquire_mount_lease("attempt-resume", actual)
        lease.close()
        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_lease_invalid$",
        ):
            _ = lease.mount
        for mutation in (mkdir, rename, chmod, publish, quarantine):
            mutation.assert_not_called()

    def test_resume_provisioning_rejects_allocation_rename_substitution(self) -> None:
        self.provision()
        replacement_reservation = self.make_reservation(
            state_allocation_id="allocation-2",
            instance_id="runtime-2",
            relative_path="ft_userdata/runtime/instances/runtime-2",
        )
        self.provider(replacement_reservation).provision(
            "runtime-2",
            "allocation-2",
            "freqtrade-state-v1",
        )
        allocation = self.state_root / "runtime-1"
        replacement = self.state_root / "runtime-2"
        displaced = self.state_root / "displaced-runtime-1"
        original_verify = runtime_state._verify_existing_layout

        def substitute(*args: object, **kwargs: object):
            os.rename(allocation, displaced)
            os.rename(replacement, allocation)
            os.rename(
                allocation / ".allocation-allocation-2",
                allocation / ".allocation-allocation-1",
            )
            return original_verify(*args, **kwargs)

        with (
            mock.patch.object(
                runtime_state,
                "_verify_existing_layout",
                side_effect=substitute,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_verification_failed$",
            ),
        ):
            self.resume_provisioning()

        self.assertTrue(displaced.is_dir())
        self.assertTrue(allocation.is_dir())
        self.assertFalse((self.state_root / ".allocation-1.quarantine").exists())

    def test_resume_provisioning_rejects_component_rename_substitution(self) -> None:
        self.provision()
        component = self.state_root / "runtime-1/home"
        displaced = self.base / "displaced-home"
        original_verify = runtime_state._verify_existing_layout

        def substitute(*args: object, **kwargs: object):
            os.rename(component, displaced)
            os.mkdir(component, 0o700)
            if os.name == "posix":
                os.chmod(component, 0o700)
            return original_verify(*args, **kwargs)

        with (
            mock.patch.object(
                runtime_state,
                "_verify_existing_layout",
                side_effect=substitute,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_verification_failed$",
            ),
        ):
            self.resume_provisioning()

        self.assertTrue(displaced.is_dir())
        self.assertTrue(component.is_dir())
        self.assertFalse((self.state_root / ".allocation-1.quarantine").exists())

    def test_resume_provisioning_rejects_marker_rename_substitution(self) -> None:
        self.provision()
        marker = self.state_root / "runtime-1/.allocation-allocation-1"
        displaced = self.base / "displaced-marker"
        original_verify = runtime_state._verify_existing_layout

        def substitute(*args: object, **kwargs: object):
            os.rename(marker, displaced)
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            if os.name == "posix":
                os.chmod(marker, 0o600)
            return original_verify(*args, **kwargs)

        with (
            mock.patch.object(
                runtime_state,
                "_verify_existing_layout",
                side_effect=substitute,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_verification_failed$",
            ),
        ):
            self.resume_provisioning()

        self.assertTrue(displaced.is_file())
        self.assertTrue(marker.is_file())
        self.assertFalse((self.state_root / ".allocation-1.quarantine").exists())

    def test_resume_provisioning_rejects_marker_owner_metadata_drift(self) -> None:
        self.provision()
        marker = self.state_root / "runtime-1/.allocation-allocation-1"
        status = os.lstat(marker)
        drifted = mock.Mock(
            st_dev=status.st_dev,
            st_ino=status.st_ino,
            st_mode=status.st_mode,
            st_uid=getattr(status, "st_uid", 0) + 1,
            st_gid=getattr(status, "st_gid", 0),
            st_file_attributes=getattr(status, "st_file_attributes", None),
            st_reparse_tag=getattr(status, "st_reparse_tag", None),
            st_nlink=status.st_nlink,
            st_size=status.st_size,
        )

        with (
            mock.patch.object(
                runtime_state,
                "_verified_identity_file_status",
                return_value=drifted,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_verification_failed$",
            ),
        ):
            self.resume_provisioning()

        self.assertTrue(marker.is_file())
        self.assertFalse((self.state_root / ".allocation-1.quarantine").exists())

    def test_resume_provisioning_classifies_partial_without_mutation(self) -> None:
        allocation = self.state_root / "runtime-1"
        allocation.mkdir()
        (allocation / "home").mkdir()
        before = tuple(sorted(path.name for path in allocation.iterdir()))

        with (
            mock.patch.object(runtime_state.os, "rename") as rename,
            mock.patch.object(runtime_state, "_publish_no_replace") as publish,
            mock.patch.object(runtime_state, "_quarantine_owned_allocation") as quarantine,
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_partial$",
            ),
        ):
            self.resume_provisioning()

        self.assertEqual(tuple(sorted(path.name for path in allocation.iterdir())), before)
        rename.assert_not_called()
        publish.assert_not_called()
        quarantine.assert_not_called()

    def test_resume_provisioning_partial_requires_managed_directory_evidence(self) -> None:
        allocation = self.state_root / "runtime-1"
        allocation.mkdir()
        (allocation / "home").mkdir()

        for target in (allocation, allocation / "home"):
            with self.subTest(target=target):

                def reject_target(path: Path, _runtime_uid: int) -> None:
                    if Path(path) == target:
                        raise OSError("acl unavailable")

                with (
                    mock.patch.object(
                        runtime_state,
                        "_verify_managed_state_directory",
                        side_effect=reject_target,
                    ),
                    self.assertRaisesRegex(
                        runtime_state.StateProvisionError,
                        "^state_provisioning_verification_failed$",
                    ),
                ):
                    self.resume_provisioning()

        self.assertTrue((allocation / "home").is_dir())
        self.assertFalse((self.state_root / ".allocation-1.quarantine").exists())

    def test_resume_provisioning_partial_marker_requires_managed_file_evidence(
        self,
    ) -> None:
        allocation = self.state_root / "runtime-1"
        allocation.mkdir()
        marker = allocation / ".allocation-allocation-1"
        marker.touch()

        with (
            mock.patch.object(
                runtime_state,
                "_verify_managed_state_identity_file",
                side_effect=OSError("acl unavailable"),
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_verification_failed$",
            ),
        ):
            self.resume_provisioning()

        self.assertTrue(marker.is_file())
        self.assertFalse((self.state_root / ".allocation-1.quarantine").exists())

    def test_resume_provisioning_classifies_foreign_and_reparse_without_mutation(
        self,
    ) -> None:
        allocation = self.state_root / "runtime-1"
        allocation.mkdir()
        foreign = allocation / "foreign-evidence"
        foreign.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_provisioning_foreign$",
        ):
            self.resume_provisioning()
        self.assertEqual(foreign.read_text(encoding="utf-8"), "keep")

    def test_resume_provisioning_classifies_partial_reparse_as_foreign(self) -> None:
        allocation = self.state_root / "runtime-1"
        allocation.mkdir()
        component = allocation / "home"
        component.mkdir()

        real_lstat = os.lstat

        def reparse_component(path: Path) -> os.stat_result:
            status = real_lstat(path)
            if Path(path) != component:
                return status
            return mock.Mock(
                st_mode=status.st_mode,
                st_dev=status.st_dev,
                st_ino=status.st_ino,
                st_file_attributes=getattr(
                    stat,
                    "FILE_ATTRIBUTE_REPARSE_POINT",
                    0x0400,
                ),
            )

        with (
            mock.patch.object(runtime_state.os, "lstat", side_effect=reparse_component),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_foreign$",
            ),
        ):
            self.resume_provisioning()
        self.assertTrue(component.is_dir())

    @unittest.skipUnless(os.name == "posix", "POSIX allocation symlink recovery")
    def test_resume_provisioning_rejects_allocation_symlink_without_root_escape(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        evidence = outside / "keep"
        evidence.write_text("foreign", encoding="utf-8")
        (self.state_root / "runtime-1").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_provisioning_foreign$",
        ):
            self.resume_provisioning()

        self.assertEqual(evidence.read_text(encoding="utf-8"), "foreign")
        self.assertFalse((outside / "home").exists())

    def test_resume_provisioning_classifies_quarantine_without_mutation(self) -> None:
        quarantine = self.state_root / ".allocation-1.quarantine"
        quarantine.mkdir()
        evidence = quarantine / "keep"
        evidence.write_text("quarantined", encoding="utf-8")

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_provisioning_quarantined$",
        ):
            self.resume_provisioning()

        self.assertEqual(evidence.read_text(encoding="utf-8"), "quarantined")
        self.assertFalse((self.state_root / "runtime-1").exists())

    def test_resume_provisioning_maps_owned_creation_failure_to_quarantine(self) -> None:
        calls = 0
        real_sync = runtime_state._sync_directory

        def fail_first_sync(path: Path, *args: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("creation fault")
            real_sync(path, *args)

        with (
            mock.patch.object(
                runtime_state,
                "_sync_directory",
                side_effect=fail_first_sync,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_quarantined$",
            ),
        ):
            self.resume_provisioning()

        self.assertFalse((self.state_root / "runtime-1").exists())
        self.assertTrue(
            (self.state_root / ".allocation-1.quarantine/runtime-1").is_dir()
        )

    def test_resume_missing_rejects_marker_metadata_drift_and_quarantines_owned(
        self,
    ) -> None:
        identity = self.state_root / "runtime-1/.allocation-allocation-1"
        published = False
        real_lstat = runtime_state.os.lstat
        real_publish = runtime_state._publish_no_replace

        def publish(source: Path, destination: Path) -> None:
            nonlocal published
            real_publish(source, destination)
            published = True

        def drift_identity(path: Path) -> os.stat_result:
            status = real_lstat(path)
            if not published or Path(path) != identity:
                return status
            return mock.Mock(
                st_dev=status.st_dev,
                st_ino=status.st_ino,
                st_mode=status.st_mode,
                st_uid=getattr(status, "st_uid", 0),
                st_gid=getattr(status, "st_gid", 0) + 1,
                st_file_attributes=getattr(status, "st_file_attributes", 0),
                st_reparse_tag=getattr(status, "st_reparse_tag", 0),
                st_nlink=status.st_nlink,
                st_size=status.st_size,
            )

        with (
            mock.patch.object(
                runtime_state,
                "_publish_no_replace",
                side_effect=publish,
            ),
            mock.patch.object(
                runtime_state.os,
                "lstat",
                side_effect=drift_identity,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_quarantined$",
            ),
        ):
            self.resume_provisioning()

        self.assertFalse((self.state_root / "runtime-1").exists())
        self.assertTrue(
            (self.state_root / ".allocation-1.quarantine/runtime-1").is_dir()
        )

    def test_resume_missing_rejects_component_metadata_drift_and_quarantines_owned(
        self,
    ) -> None:
        component = self.state_root / "runtime-1/home"
        calls = 0
        real_validate = runtime_state._validated_directory_status

        def drift_component(path: Path, runtime_uid: int) -> os.stat_result:
            nonlocal calls
            status = real_validate(path, runtime_uid)
            if Path(path) != component:
                return status
            calls += 1
            if calls == 1:
                return status
            return mock.Mock(
                st_dev=status.st_dev,
                st_ino=status.st_ino,
                st_mode=status.st_mode,
                st_uid=getattr(status, "st_uid", 0),
                st_gid=getattr(status, "st_gid", 0) + 1,
                st_file_attributes=getattr(status, "st_file_attributes", 0),
                st_reparse_tag=getattr(status, "st_reparse_tag", 0),
            )

        with (
            mock.patch.object(
                runtime_state,
                "_validated_directory_status",
                side_effect=drift_component,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provisioning_quarantined$",
            ),
        ):
            self.resume_provisioning()

        self.assertFalse((self.state_root / "runtime-1").exists())
        self.assertTrue(
            (self.state_root / ".allocation-1.quarantine/runtime-1").is_dir()
        )

    def test_resume_provisioning_transient_verification_failure_is_not_quarantine(
        self,
    ) -> None:
        self.provision()
        allocation = self.state_root / "runtime-1"
        before = tuple(sorted(path.name for path in allocation.iterdir()))
        real_lstat = runtime_state.os.lstat

        def transient_component_lstat(path: Path) -> os.stat_result:
            if Path(path) == allocation / "home":
                raise PermissionError("transient")
            return real_lstat(path)

        failures = (
            mock.patch.object(
                runtime_state,
                "_verify_existing_layout",
                side_effect=OSError("transient"),
            ),
            mock.patch.object(
                runtime_state.os,
                "lstat",
                side_effect=transient_component_lstat,
            ),
        )
        for failure in failures:
            with self.subTest(failure=failure.attribute):
                with (
                    failure,
                    mock.patch.object(runtime_state.os, "rename") as rename,
                    mock.patch.object(
                        runtime_state, "_quarantine_owned_allocation"
                    ) as quarantine,
                    self.assertRaisesRegex(
                        runtime_state.StateProvisionError,
                        "^state_provisioning_verification_failed$",
                    ),
                ):
                    self.resume_provisioning()

                self.assertEqual(
                    tuple(sorted(path.name for path in allocation.iterdir())), before
                )
                self.assertFalse(
                    (self.state_root / ".allocation-1.quarantine").exists()
                )
                rename.assert_not_called()
                quarantine.assert_not_called()

    def test_windows_resume_hardens_only_missing_layout_and_verifies_existing(self) -> None:
        with (
            mock.patch.object(runtime_state, "_is_windows", return_value=True),
            mock.patch.object(
                runtime_state, "_harden_managed_state_directory"
            ) as harden_directory,
            mock.patch.object(
                runtime_state, "_verify_managed_state_directory"
            ) as verify_directory,
            mock.patch.object(
                runtime_state, "_harden_managed_state_identity_file"
            ) as harden_identity,
            mock.patch.object(
                runtime_state, "_verify_managed_state_identity_file"
            ) as verify_identity,
        ):
            created = self.resume_provisioning()
            self.assertEqual(created.durability, "atomic-process-crash")
            self.assertGreaterEqual(harden_directory.call_count, 4)
            harden_identity.assert_called_once()
            self.assertGreaterEqual(verify_directory.call_count, 5)
            verify_identity.assert_called()

            harden_directory.reset_mock()
            harden_identity.reset_mock()
            verify_directory.reset_mock()
            verify_identity.reset_mock()

            resumed = self.resume_provisioning()

        self.assertEqual(resumed, created)
        harden_directory.assert_not_called()
        harden_identity.assert_not_called()
        self.assertGreaterEqual(verify_directory.call_count, 5)
        verify_identity.assert_called()

    def test_invalid_existing_allocation_rejects_before_filesystem_io(self) -> None:
        mutations = (
            {"state_allocation_id": "../allocation"},
            {"instance_id": "Runtime-1"},
            {"layout_id": "other-layout"},
            {"provider_id": "other-provider"},
            {"relative_path": "ft_userdata/runtime/instances/other"},
            {"kind": "restored"},
            {"status": "reserved"},
            {"generation": 0},
            {"generation": True},
            {"restore_source_bundle_id": "bundle-1"},
        )
        missing_root = self.base / "does-not-exist"
        for changes in mutations:
            with self.subTest(changes=changes):
                provider = self.provider(
                    self.make_existing(**changes),
                    state_root=missing_root,
                )
                with self.assertRaisesRegex(
                    runtime_state.StateProvisionError,
                    "^state_existing_invalid$",
                ):
                    provider.verify_existing(
                        "runtime-1",
                        "allocation-1",
                        "freqtrade-state-v1",
                    )

        provider = self.provider(self.make_existing(), state_root=missing_root)
        for arguments in (
            ("runtime-2", "allocation-1", "freqtrade-state-v1"),
            ("runtime-1", "allocation-2", "freqtrade-state-v1"),
            ("runtime-1", "allocation-1", "other-layout"),
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(
                    runtime_state.StateProvisionError,
                    "^state_existing_invalid$",
                ):
                    provider.verify_existing(*arguments)
        self.assertFalse(missing_root.exists())

    def test_verify_existing_root_failure_is_fixed_and_redacted(self) -> None:
        missing_root = self.base / "missing-existing-root"
        provider = self.provider(self.make_existing(), state_root=missing_root)

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_existing_verification_failed$",
        ) as raised:
            provider.verify_existing(
                "runtime-1",
                "allocation-1",
                "freqtrade-state-v1",
            )

        self.assertNotIn(str(missing_root), str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertFalse(missing_root.exists())

    def test_verify_existing_returns_proof_without_mutating_managed_state(self) -> None:
        expected = self.provision()
        allocation = self.state_root / "runtime-1"
        business_data = allocation / "data/strategy.sqlite"
        business_data.write_bytes(b"opaque-business-data")
        business_log = allocation / "logs/runtime.log"
        business_log.write_text("opaque-business-log", encoding="utf-8")
        before = {
            path.relative_to(self.state_root): (
                path.stat().st_dev,
                path.stat().st_ino,
                path.stat().st_mode,
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in (allocation, *allocation.iterdir())
        }

        with (
            mock.patch.object(runtime_state.os, "mkdir") as mkdir,
            mock.patch.object(runtime_state.os, "rename") as rename,
            mock.patch.object(runtime_state.os, "chmod") as chmod,
            mock.patch.object(
                runtime_state,
                "_harden_managed_state_directory",
            ) as harden_directory,
            mock.patch.object(
                runtime_state,
                "_harden_managed_state_identity_file",
            ) as harden_identity,
            mock.patch.object(runtime_state, "_sync_directory") as sync_directory,
            mock.patch.object(runtime_state, "_sync_descriptor") as sync_descriptor,
            mock.patch.object(runtime_state, "_publish_no_replace") as publish,
            mock.patch.object(
                runtime_state, "_quarantine_owned_allocation"
            ) as quarantine,
        ):
            actual = self.verify_existing()

        after = {
            path.relative_to(self.state_root): (
                path.stat().st_dev,
                path.stat().st_ino,
                path.stat().st_mode,
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in (allocation, *allocation.iterdir())
        }
        self.assertEqual(actual, expected)
        self.assertEqual(after, before)
        self.assertEqual(business_data.read_bytes(), b"opaque-business-data")
        self.assertEqual(
            business_log.read_text(encoding="utf-8"), "opaque-business-log"
        )
        for mutation in (
            mkdir,
            rename,
            chmod,
            harden_directory,
            harden_identity,
            sync_directory,
            sync_descriptor,
            publish,
            quarantine,
        ):
            mutation.assert_not_called()

    def test_verify_existing_rejects_structure_identity_and_permission_drift(
        self,
    ) -> None:
        cases = ("structure", "identity", "permission")
        for index, case in enumerate(cases, start=1):
            with self.subTest(case=case):
                instance_id = f"runtime-existing-{index}"
                allocation_id = f"allocation-existing-{index}"
                reservation = self.make_reservation(
                    state_allocation_id=allocation_id,
                    instance_id=instance_id,
                    relative_path=f"ft_userdata/runtime/instances/{instance_id}",
                )
                self.provider(reservation).provision(
                    instance_id,
                    allocation_id,
                    "freqtrade-state-v1",
                )
                path = self.state_root / instance_id
                if case == "structure":
                    (path / "unexpected").write_text("evidence", encoding="utf-8")
                elif case == "identity":
                    marker = path / f".allocation-{allocation_id}"
                    marker.write_text("forged", encoding="utf-8")
                else:
                    os.chmod(path / "data", 0o755)

                permission_check = nullcontext()
                if case == "permission" and os.name == "nt":

                    def reject_data(target: Path, runtime_uid: int) -> None:
                        del runtime_uid
                        if Path(target) == path / "data":
                            raise ValueError("permission drift")

                    permission_check = mock.patch.object(
                        runtime_state,
                        "_verify_managed_state_directory",
                        side_effect=reject_data,
                    )

                existing = self.make_existing(
                    state_allocation_id=allocation_id,
                    instance_id=instance_id,
                    relative_path=f"ft_userdata/runtime/instances/{instance_id}",
                )
                with permission_check:
                    with self.assertRaisesRegex(
                        runtime_state.StateProvisionError,
                        "^state_existing_verification_failed$",
                    ) as raised:
                        self.provider(existing).verify_existing(
                            instance_id,
                            allocation_id,
                            "freqtrade-state-v1",
                        )
                self.assertNotIn(str(path), str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)

    def test_verify_existing_detects_allocation_replacement(self) -> None:
        self.provision()
        allocation = self.state_root / "runtime-1"
        displaced = self.state_root / "runtime-1-displaced"
        real_validate = runtime_state._validated_directory_status
        replaced = False

        def replace_after_data(path: Path, runtime_uid: int) -> os.stat_result:
            nonlocal replaced
            result = real_validate(path, runtime_uid)
            if path.name == "data" and not replaced:
                replaced = True
                os.rename(allocation, displaced)
                allocation.mkdir()
                os.chmod(allocation, 0o700)
            return result

        with (
            mock.patch.object(
                runtime_state,
                "_validated_directory_status",
                side_effect=replace_after_data,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_existing_verification_failed$",
            ),
        ):
            self.verify_existing()

        self.assertTrue(replaced)
        self.assertTrue(displaced.is_dir())

    def test_verify_existing_allows_business_data_created_during_validation(
        self,
    ) -> None:
        self.provision()
        allocation = self.state_root / "runtime-1"
        business_data = allocation / "data/live.sqlite-wal"
        real_validate = runtime_state._validated_directory_status
        data_validations = 0

        def create_business_data(path: Path, runtime_uid: int) -> os.stat_result:
            nonlocal data_validations
            if path == allocation / "data":
                data_validations += 1
                if data_validations == 2:
                    business_data.write_bytes(b"legitimate-runtime-write")
            status = real_validate(path, runtime_uid)
            if path == allocation / "data" and data_validations == 2:
                return mock.Mock(
                    st_dev=status.st_dev,
                    st_ino=status.st_ino,
                    st_mode=status.st_mode,
                    st_uid=getattr(status, "st_uid", None),
                    st_gid=getattr(status, "st_gid", None),
                    st_file_attributes=getattr(
                        status,
                        "st_file_attributes",
                        None,
                    ),
                    st_reparse_tag=getattr(status, "st_reparse_tag", None),
                    st_nlink=status.st_nlink,
                    st_size=status.st_size + 1,
                )
            return status

        with mock.patch.object(
            runtime_state,
            "_validated_directory_status",
            side_effect=create_business_data,
        ):
            state = self.verify_existing()

        self.assertEqual(state.state_allocation_id, "allocation-1")
        self.assertEqual(business_data.read_bytes(), b"legitimate-runtime-write")
        self.assertEqual(data_validations, 2)

    def test_verify_existing_rejects_top_level_member_added_after_initial_scan(
        self,
    ) -> None:
        self.provision()
        allocation = self.state_root / "runtime-1"
        real_verify_identity = runtime_state._verify_managed_state_identity_file
        identity_validations = 0

        def add_member_during_final_identity_check(
            path: Path, runtime_uid: int
        ) -> None:
            nonlocal identity_validations
            real_verify_identity(path, runtime_uid)
            identity_validations += 1
            if identity_validations == 3:
                (allocation / "unexpected").write_text("evidence", encoding="utf-8")

        with (
            mock.patch.object(
                runtime_state,
                "_verify_managed_state_identity_file",
                side_effect=add_member_during_final_identity_check,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_existing_verification_failed$",
            ),
        ):
            self.verify_existing()

        self.assertEqual(identity_validations, 3)

    def test_verify_existing_identity_descriptor_closes_on_success_and_failure(
        self,
    ) -> None:
        self.provision()
        identity = self.state_root / "runtime-1/.allocation-allocation-1"
        real_open = os.open

        for failure in (False, True):
            with self.subTest(failure=failure):
                descriptors: list[int] = []

                def capture(path: Path, flags: int, *args: object) -> int:
                    descriptor = real_open(path, flags, *args)
                    if Path(path) == identity:
                        descriptors.append(descriptor)
                    return descriptor

                read = mock.DEFAULT
                if failure:
                    read = mock.Mock(side_effect=OSError("read fault"))
                with mock.patch.object(runtime_state.os, "open", side_effect=capture):
                    if failure:
                        with (
                            mock.patch.object(runtime_state.os, "read", new=read),
                            self.assertRaisesRegex(
                                runtime_state.StateProvisionError,
                                "^state_existing_verification_failed$",
                            ),
                        ):
                            self.verify_existing()
                    else:
                        self.verify_existing()

                self.assertEqual(len(descriptors), 1)
                with self.assertRaises(OSError):
                    os.fstat(descriptors[0])

    def test_invalid_root_is_rejected_without_path_disclosure(self) -> None:
        invalid = self.base / "invalid-root"
        invalid.write_text("not a directory", encoding="utf-8")
        provider = self.provider(state_root=invalid)

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_root_invalid$",
        ) as raised:
            self.provision(provider)

        self.assertNotIn(str(invalid), str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)

    def test_reparse_root_is_rejected_before_permission_proof(self) -> None:
        reparse = mock.Mock(
            st_mode=stat.S_IFDIR | 0o700,
            st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400),
        )
        with (
            mock.patch.object(runtime_state.os, "lstat", return_value=reparse),
            mock.patch.object(
                runtime_state,
                "_verify_managed_state_directory",
            ) as verify,
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_root_invalid$",
            ),
        ):
            self.provision()
        verify.assert_not_called()

    def test_preexisting_allocation_is_never_adopted_or_changed(self) -> None:
        allocation = self.state_root / "runtime-1"
        allocation.mkdir()
        marker = allocation / "keep"
        marker.write_text("unchanged", encoding="utf-8")

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_allocation_exists$",
        ):
            self.provision()

        self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
        self.assertFalse((self.state_root / ".allocation-1.quarantine").exists())

    def test_partial_failure_quarantines_only_owned_allocation(self) -> None:
        unrelated = self.state_root / "unrelated"
        unrelated.mkdir()
        marker = unrelated / "keep"
        marker.write_text("unchanged", encoding="utf-8")

        real_sync = runtime_state._sync_directory
        calls = 0

        def fail_once(path: Path, *args: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("fault")
            real_sync(path, *args)

        with (
            mock.patch.object(runtime_state, "_sync_directory", side_effect=fail_once),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provision_failed$",
            ),
        ):
            self.provision()

        quarantine = self.state_root / ".allocation-1.quarantine/runtime-1"
        self.assertTrue(quarantine.is_dir())
        self.assertFalse((self.state_root / "runtime-1").exists())
        self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")

    def test_preexisting_quarantine_is_never_reused(self) -> None:
        quarantine = self.state_root / ".allocation-1.quarantine"
        quarantine.mkdir()
        marker = quarantine / "keep"
        marker.write_text("unchanged", encoding="utf-8")

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_allocation_exists$",
        ):
            self.provision()

        self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
        self.assertFalse((self.state_root / "runtime-1").exists())

    def test_hardening_failure_after_exclusive_create_is_quarantined(self) -> None:
        def harden(path: Path, runtime_uid: int) -> None:
            del runtime_uid
            if path.name == "runtime-1":
                raise ValueError("fault")

        with (
            mock.patch.object(
                runtime_state,
                "_harden_managed_state_directory",
                side_effect=harden,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provision_failed$",
            ),
        ):
            self.provision()

        self.assertTrue(
            (self.state_root / ".allocation-1.quarantine/runtime-1").is_dir()
        )

    def test_quarantine_rename_failure_retains_evidence_and_fails_closed(self) -> None:
        real_sync = runtime_state._sync_directory
        real_publish = runtime_state._publish_no_replace
        sync_calls = 0

        def fail_provision_once(path: Path, *args: object) -> None:
            nonlocal sync_calls
            sync_calls += 1
            if sync_calls == 1:
                raise OSError("provision fault")
            real_sync(path, *args)

        def fail_quarantine_rename(source: Path, destination: Path) -> None:
            if destination.parent.name == ".allocation-1.quarantine":
                raise OSError("quarantine fault")
            real_publish(source, destination)

        with (
            mock.patch.object(
                runtime_state, "_sync_directory", side_effect=fail_provision_once
            ),
            mock.patch.object(
                runtime_state,
                "_publish_no_replace",
                side_effect=fail_quarantine_rename,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_quarantine_failed$",
            ),
        ):
            self.provision()

        self.assertTrue((self.state_root / "runtime-1").is_dir())
        self.assertTrue((self.state_root / ".allocation-1.quarantine").is_dir())

    def test_quarantine_barrier_failure_retains_moved_evidence_and_fails_closed(
        self,
    ) -> None:
        real_sync = runtime_state._sync_directory
        sync_calls = 0

        def fail_provision_and_quarantine(path: Path, *args: object) -> None:
            nonlocal sync_calls
            sync_calls += 1
            if sync_calls <= 2:
                raise OSError("sync fault")
            real_sync(path, *args)

        with (
            mock.patch.object(
                runtime_state,
                "_sync_directory",
                side_effect=fail_provision_and_quarantine,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_quarantine_failed$",
            ),
        ):
            self.provision()

        self.assertFalse((self.state_root / "runtime-1").exists())
        self.assertTrue(
            (self.state_root / ".allocation-1.quarantine/runtime-1").is_dir()
        )

    def test_replaced_allocation_is_not_quarantined(self) -> None:
        displaced = self.state_root / "owned-displaced"
        replacement_marker = "replacement"
        invoked = 0

        def replace_then_fail(path: Path, *args: object) -> None:
            nonlocal invoked
            del path, args
            invoked += 1
            allocation = self.state_root / "runtime-1"
            os.rename(allocation, displaced)
            allocation.mkdir()
            (allocation / replacement_marker).write_text("keep", encoding="utf-8")
            raise OSError("fault")

        with (
            mock.patch.object(
                runtime_state, "_sync_directory", side_effect=replace_then_fail
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_quarantine_failed$",
            ),
        ):
            self.provision()

        self.assertEqual(invoked, 1)
        self.assertTrue((self.state_root / f"runtime-1/{replacement_marker}").is_file())
        self.assertTrue(displaced.is_dir())
        self.assertFalse((self.state_root / ".allocation-1.quarantine").exists())

    def test_final_validation_rejects_unknown_component_and_quarantines(self) -> None:
        real_sync = runtime_state._sync_directory
        added = False

        def add_unknown(path: Path, *args: object) -> None:
            nonlocal added
            real_sync(path, *args)
            if not added:
                added = True
                (self.state_root / "runtime-1/unexpected").write_text(
                    "evidence", encoding="utf-8"
                )

        with (
            mock.patch.object(
                runtime_state, "_sync_directory", side_effect=add_unknown
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provision_failed$",
            ),
        ):
            self.provision()

        self.assertTrue(
            (
                self.state_root / ".allocation-1.quarantine/runtime-1/unexpected"
            ).is_file()
        )

    def test_identity_descriptor_closes_on_success_and_failure(self) -> None:
        descriptors: list[int] = []
        real_sync = runtime_state._sync_descriptor

        def capture(descriptor: int) -> None:
            descriptors.append(descriptor)
            real_sync(descriptor)

        with mock.patch.object(runtime_state, "_sync_descriptor", side_effect=capture):
            self.provision()
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

        second_reservation = self.make_reservation(
            state_allocation_id="allocation-2",
            instance_id="runtime-2",
            relative_path="ft_userdata/runtime/instances/runtime-2",
        )
        failed_descriptors: list[int] = []

        def capture_then_fail(descriptor: int) -> None:
            failed_descriptors.append(descriptor)
            raise OSError("fault")

        with (
            mock.patch.object(
                runtime_state, "_sync_descriptor", side_effect=capture_then_fail
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provision_failed$",
            ),
        ):
            self.provider(second_reservation).provision(
                "runtime-2", "allocation-2", "freqtrade-state-v1"
            )
        self.assertEqual(len(failed_descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(failed_descriptors[0])

    def test_identity_publish_race_never_overwrites_competing_target(self) -> None:
        real_publish = runtime_state._publish_no_replace
        competitor = b"competitor-must-survive"

        def race(source: Path, destination: Path) -> None:
            if destination.name == ".allocation-allocation-1":
                destination.write_bytes(competitor)
            real_publish(source, destination)

        with (
            mock.patch.object(runtime_state, "_publish_no_replace", side_effect=race),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provision_failed$",
            ),
        ):
            self.provision()

        quarantined = (
            self.state_root
            / ".allocation-1.quarantine/runtime-1/.allocation-allocation-1"
        )
        self.assertEqual(quarantined.read_bytes(), competitor)

    def test_identity_publish_rejects_source_inode_substitution(self) -> None:
        real_publish = runtime_state._publish_no_replace
        displaced_name: str | None = None
        synced_identity: tuple[int, int] | None = None
        substitute_identity: tuple[int, int] | None = None

        def substitute_source(source: Path, destination: Path) -> None:
            nonlocal displaced_name, substitute_identity, synced_identity
            if destination.name == ".allocation-allocation-1":
                displaced = self.state_root / ".synced-source-evidence"
                os.rename(source, displaced)
                displaced_name = displaced.name
                displaced_status = displaced.stat()
                synced_identity = displaced_status.st_dev, displaced_status.st_ino

                descriptor = os.open(
                    source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                if os.name == "nt":
                    harden = self.real_permission_helpers[
                        "_harden_managed_state_identity_file"
                    ]
                    harden(source, self.runtime_uid)
                else:
                    os.chmod(source, 0o600)
                substitute_status = source.stat()
                substitute_identity = (
                    substitute_status.st_dev,
                    substitute_status.st_ino,
                )
            real_publish(source, destination)

        with (
            mock.patch.object(
                runtime_state,
                "_publish_no_replace",
                side_effect=substitute_source,
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provision_failed$",
            ),
        ):
            self.provision()

        self.assertIsNotNone(displaced_name)
        self.assertNotEqual(synced_identity, substitute_identity)
        quarantine = self.state_root / ".allocation-1.quarantine/runtime-1"
        published = quarantine / ".allocation-allocation-1"
        displaced = self.state_root / str(displaced_name)
        published_status = published.stat()
        displaced_status = displaced.stat()
        self.assertEqual(
            (published_status.st_dev, published_status.st_ino),
            substitute_identity,
        )
        self.assertEqual(
            (displaced_status.st_dev, displaced_status.st_ino),
            synced_identity,
        )

    def test_quarantine_publish_race_never_replaces_competing_destination(self) -> None:
        real_publish = runtime_state._publish_no_replace
        real_sync = runtime_state._sync_directory
        competitor_identity: tuple[int, int] | None = None
        sync_calls = 0

        def fail_once(path: Path, *args: object) -> None:
            nonlocal sync_calls
            sync_calls += 1
            if sync_calls == 1:
                raise OSError("provision fault")
            real_sync(path, *args)

        def race(source: Path, destination: Path) -> None:
            nonlocal competitor_identity
            if destination.parent.name == ".allocation-1.quarantine":
                destination.mkdir()
                status = destination.stat()
                competitor_identity = status.st_dev, status.st_ino
            real_publish(source, destination)

        with (
            mock.patch.object(runtime_state, "_sync_directory", side_effect=fail_once),
            mock.patch.object(runtime_state, "_publish_no_replace", side_effect=race),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_quarantine_failed$",
            ),
        ):
            self.provision()

        destination = self.state_root / ".allocation-1.quarantine/runtime-1"
        status = destination.stat()
        self.assertEqual((status.st_dev, status.st_ino), competitor_identity)
        self.assertTrue((self.state_root / "runtime-1").is_dir())

    def test_keyboard_interrupt_and_system_exit_are_never_translated(self) -> None:
        cases = (
            ("_sync_directory", KeyboardInterrupt("stop")),
            ("_validate_final_layout", SystemExit(7)),
        )
        for target, error in cases:
            with self.subTest(target=target):
                reservation = self.make_reservation(
                    state_allocation_id=f"allocation-{target.removeprefix('_')}",
                    instance_id=f"runtime-{target.removeprefix('_')}",
                    relative_path=(
                        "ft_userdata/runtime/instances/"
                        f"runtime-{target.removeprefix('_')}"
                    ),
                )
                provider = self.provider(reservation)
                expected = type(error)
                with (
                    mock.patch.object(runtime_state, target, side_effect=error),
                    self.assertRaises(expected),
                ):
                    provider.provision(
                        reservation.instance_id,
                        reservation.state_allocation_id,
                        "freqtrade-state-v1",
                    )

    def test_quarantine_never_swallows_control_flow_exception(self) -> None:
        calls = 0

        def interrupt_quarantine(path: Path, *args: object) -> None:
            nonlocal calls
            del path, args
            calls += 1
            if calls == 1:
                raise OSError("provision fault")
            raise KeyboardInterrupt("stop")

        with (
            mock.patch.object(
                runtime_state,
                "_sync_directory",
                side_effect=interrupt_quarantine,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.provision()

    def test_allocation_replaced_at_final_root_barrier_never_returns_proof(
        self,
    ) -> None:
        real_sync = runtime_state._sync_directory
        displaced = self.state_root / "owned-at-barrier"
        replacement = self.state_root / "runtime-1"
        replaced = False

        def replace_at_root(path: Path, *args: object) -> None:
            nonlocal replaced
            if path == self.state_root and not replaced:
                replaced = True
                os.rename(replacement, displaced)
                replacement.mkdir()
                (replacement / "competitor").write_text("keep", encoding="utf-8")
            real_sync(path, *args)

        with (
            mock.patch.object(
                runtime_state, "_sync_directory", side_effect=replace_at_root
            ),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_quarantine_failed$",
            ),
        ):
            self.provision()

        self.assertTrue(replaced)
        self.assertEqual(
            (replacement / "competitor").read_text(encoding="utf-8"), "keep"
        )
        self.assertTrue(displaced.is_dir())
        self.assertFalse((self.state_root / ".allocation-1.quarantine").exists())

    @unittest.skipUnless(os.name == "posix", "POSIX symlink-parent integration")
    def test_symlinked_state_root_parent_is_rejected_before_allocation_io(self) -> None:
        outside = self.base / "outside"
        escaped_root = outside / "instances"
        escaped_root.mkdir(parents=True)
        os.chmod(escaped_root, 0o700)
        linked_parent = self.base / "linked-parent"
        linked_parent.symlink_to(outside, target_is_directory=True)
        provider = self.provider(state_root=linked_parent / "instances")

        with self.assertRaisesRegex(
            runtime_state.StateProvisionError,
            "^state_root_invalid$",
        ):
            self.provision(provider)

        self.assertFalse((escaped_root / "runtime-1").exists())

    def test_reparse_state_root_parent_is_rejected_before_allocation_io(self) -> None:
        parent = self.state_root.parent
        real_lstat = os.lstat

        def reparse_parent(path: Path) -> os.stat_result:
            status = real_lstat(path)
            if Path(path) != parent:
                return status
            return mock.Mock(
                st_mode=status.st_mode,
                st_dev=status.st_dev,
                st_ino=status.st_ino,
                st_nlink=status.st_nlink,
                st_size=status.st_size,
                st_file_attributes=getattr(
                    stat,
                    "FILE_ATTRIBUTE_REPARSE_POINT",
                    0x0400,
                ),
            )

        with (
            mock.patch.object(runtime_state.os, "lstat", side_effect=reparse_parent),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_root_invalid$",
            ),
        ):
            self.provision()
        self.assertFalse((self.state_root / "runtime-1").exists())

    @unittest.skipUnless(os.name == "posix", "POSIX durability ordering")
    def test_posix_durability_barriers_have_required_order(self) -> None:
        events: list[str] = []
        real_sync_descriptor = runtime_state._sync_descriptor
        real_sync_directory = runtime_state._sync_directory
        real_publish = runtime_state._publish_no_replace
        real_validate = runtime_state._validate_final_layout

        def sync_descriptor(descriptor: int) -> None:
            events.append("identity-file-sync")
            real_sync_descriptor(descriptor)

        def publish(source: Path, destination: Path) -> None:
            if destination.name == ".allocation-allocation-1":
                events.append("identity-rename")
            real_publish(source, destination)

        def sync_directory(path: Path, *args: object) -> None:
            events.append(f"directory-sync:{path.name}")
            real_sync_directory(path, *args)

        def validate(*args: object, **kwargs: object) -> None:
            events.append("final-validation")
            real_validate(*args, **kwargs)

        with (
            mock.patch.object(
                runtime_state, "_sync_descriptor", side_effect=sync_descriptor
            ),
            mock.patch.object(
                runtime_state, "_sync_directory", side_effect=sync_directory
            ),
            mock.patch.object(
                runtime_state, "_publish_no_replace", side_effect=publish
            ),
            mock.patch.object(
                runtime_state, "_validate_final_layout", side_effect=validate
            ),
        ):
            self.provision()

        self.assertLess(
            events.index("identity-file-sync"), events.index("identity-rename")
        )
        self.assertLess(
            events.index("identity-rename"), events.index("directory-sync:runtime-1")
        )
        self.assertLess(
            events.index("directory-sync:runtime-1"), events.index("final-validation")
        )
        for name in ("home", "logs", "data"):
            self.assertIn(f"directory-sync:{name}", events)
        self.assertEqual(events[-1], "directory-sync:instances")

    def test_windows_uses_owner_only_acl_and_honest_durability(self) -> None:
        reservation = self.make_reservation(
            state_allocation_id="allocation-2",
            instance_id="runtime-2",
            relative_path="ft_userdata/runtime/instances/runtime-2",
        )
        with (
            mock.patch.object(runtime_state, "_is_windows", return_value=True),
            mock.patch.object(
                runtime_state, "_harden_managed_state_directory"
            ) as harden_dir,
            mock.patch.object(
                runtime_state, "_verify_managed_state_directory"
            ) as verify_dir,
            mock.patch.object(
                runtime_state, "_harden_managed_state_identity_file"
            ) as harden_file,
            mock.patch.object(
                runtime_state, "_verify_managed_state_identity_file"
            ) as verify_file,
        ):
            result = self.provider(reservation).provision(
                "runtime-2", "allocation-2", "freqtrade-state-v1"
            )

        self.assertEqual(result.durability, "atomic-process-crash")
        self.assertGreaterEqual(harden_dir.call_count, 4)
        self.assertGreaterEqual(verify_dir.call_count, 5)
        harden_file.assert_called_once()
        verify_file.assert_called()

    @unittest.skipUnless(os.name == "nt", "Windows ACL integration test")
    def test_windows_real_acl_protects_every_managed_layout_path(self) -> None:
        harden_directory = self.real_permission_helpers[
            "_harden_managed_state_directory"
        ]
        harden_directory(self.state_root, self.runtime_uid)
        with (
            mock.patch.object(
                runtime_state,
                "_harden_managed_state_directory",
                new=harden_directory,
            ),
            mock.patch.object(
                runtime_state,
                "_verify_managed_state_directory",
                new=self.real_permission_helpers["_verify_managed_state_directory"],
            ),
            mock.patch.object(
                runtime_state,
                "_harden_managed_state_identity_file",
                new=self.real_permission_helpers["_harden_managed_state_identity_file"],
            ),
            mock.patch.object(
                runtime_state,
                "_verify_managed_state_identity_file",
                new=self.real_permission_helpers["_verify_managed_state_identity_file"],
            ),
        ):
            self.provision()

        self.assertTrue((self.state_root / "runtime-1/home").is_dir())


if __name__ == "__main__":
    unittest.main()
