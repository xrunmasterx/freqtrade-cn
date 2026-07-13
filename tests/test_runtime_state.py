from __future__ import annotations

import inspect
import os
import stat
import tempfile
import unittest
from dataclasses import fields
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

    def make_reservation(self, **changes: object) -> runtime_state.StateAllocationReservation:
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

    def provider(
        self,
        reservation: runtime_state.StateAllocationReservation | None = None,
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
        self.assertFalse(any(path.name.endswith(".tmp") for path in allocation.iterdir()))
        if os.name == "posix":
            for path in (allocation, allocation / "home", allocation / "logs", allocation / "data"):
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
        parameters = tuple(inspect.signature(runtime_state.ManagedStateProvider.provision).parameters)
        self.assertEqual(parameters, ("self", "instance_id", "allocation_id", "layout_id"))
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
            mock.patch.object(runtime_state, "_sync_directory", side_effect=fail_provision_once),
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

    def test_quarantine_barrier_failure_retains_moved_evidence_and_fails_closed(self) -> None:
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
            mock.patch.object(runtime_state, "_sync_directory", side_effect=replace_then_fail),
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
                (self.state_root / "runtime-1/unexpected").write_text("evidence", encoding="utf-8")

        with (
            mock.patch.object(runtime_state, "_sync_directory", side_effect=add_unknown),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_provision_failed$",
            ),
        ):
            self.provision()

        self.assertTrue(
            (self.state_root / ".allocation-1.quarantine/runtime-1/unexpected").is_file()
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
            mock.patch.object(runtime_state, "_sync_descriptor", side_effect=capture_then_fail),
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

                descriptor = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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

    def test_allocation_replaced_at_final_root_barrier_never_returns_proof(self) -> None:
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
            mock.patch.object(runtime_state, "_sync_directory", side_effect=replace_at_root),
            self.assertRaisesRegex(
                runtime_state.StateProvisionError,
                "^state_quarantine_failed$",
            ),
        ):
            self.provision()

        self.assertTrue(replaced)
        self.assertEqual((replacement / "competitor").read_text(encoding="utf-8"), "keep")
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
            mock.patch.object(runtime_state, "_sync_descriptor", side_effect=sync_descriptor),
            mock.patch.object(runtime_state, "_sync_directory", side_effect=sync_directory),
            mock.patch.object(runtime_state, "_publish_no_replace", side_effect=publish),
            mock.patch.object(runtime_state, "_validate_final_layout", side_effect=validate),
        ):
            self.provision()

        self.assertLess(events.index("identity-file-sync"), events.index("identity-rename"))
        self.assertLess(events.index("identity-rename"), events.index("directory-sync:runtime-1"))
        self.assertLess(events.index("directory-sync:runtime-1"), events.index("final-validation"))
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
            mock.patch.object(runtime_state, "_harden_managed_state_directory") as harden_dir,
            mock.patch.object(runtime_state, "_verify_managed_state_directory") as verify_dir,
            mock.patch.object(runtime_state, "_harden_managed_state_identity_file") as harden_file,
            mock.patch.object(runtime_state, "_verify_managed_state_identity_file") as verify_file,
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
        harden_directory = self.real_permission_helpers["_harden_managed_state_directory"]
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
