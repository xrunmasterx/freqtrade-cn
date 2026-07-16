from __future__ import annotations

import inspect
import json
import os
import shutil
import stat
import tempfile
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import bootstrap_runtime, runtime_secrets
from tools.runtime_secrets import (
    LocalFileSecretProvider,
    SecretMaterialError,
    SecretMaterialRequirement,
    SecretSourceIdentity,
    VerifiedSecretMount,
    VerifiedSecretMountLease,
)


class RuntimeSecretProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "runtime-secrets"
        self.runtime_uid = getattr(os, "getuid", lambda: 1000)()
        self.requirements = (
            SecretMaterialRequirement("api-password", "v1", "api_password"),
            SecretMaterialRequirement("jwt-secret", "v2", "jwt_secret"),
            SecretMaterialRequirement("ws-token", "v3", "ws_token"),
        )
        self.values = {
            ("api-password", "v1"): "a" * 32,
            ("jwt-secret", "v2"): "b" * 48,
            ("ws-token", "v3"): "c" * 32,
        }
        for requirement in self.requirements:
            self.write_secret(requirement, self.values[requirement.identity])
        self.secret_permission_patcher = None
        self.directory_permission_patcher = None
        if os.name == "nt":
            self.secret_permission_patcher = mock.patch.object(
                runtime_secrets, "_verify_secret_permissions"
            )
            self.permission_proof = self.secret_permission_patcher.start()
            self.addCleanup(self.secret_permission_patcher.stop)
            self.directory_permission_patcher = mock.patch.object(
                runtime_secrets,
                "_verify_windows_trusted_paths_permissions",
            )
            self.directory_permission_patcher.start()
            self.addCleanup(self.directory_permission_patcher.stop)
        self.provider = self.make_provider()

    def make_provider(
        self,
        requirements: tuple[SecretMaterialRequirement, ...] | None = None,
        *,
        root: Path | None = None,
    ) -> LocalFileSecretProvider:
        return LocalFileSecretProvider(
            requirements if requirements is not None else self.requirements,
            runtime_uid=self.runtime_uid,
            secret_root=root if root is not None else self.root,
        )

    def secret_path(self, requirement: SecretMaterialRequirement) -> Path:
        return self.root / requirement.reference_id / requirement.version_id / "value"

    def write_secret(
        self,
        requirement: SecretMaterialRequirement,
        value: str | bytes,
        *,
        ending: bytes = b"\n",
    ) -> Path:
        path = self.secret_path(requirement)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = value.encode("utf-8") if isinstance(value, str) else value
        path.write_bytes(content + ending)
        os.chmod(path, 0o600)
        return path

    def assert_closed(self, descriptor: int) -> None:
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    @staticmethod
    def changed_identity(status: os.stat_result) -> SimpleNamespace:
        values = {
            name: getattr(status, name)
            for name in (
                "st_mode",
                "st_dev",
                "st_ino",
                "st_nlink",
                "st_size",
            )
        }
        values["st_ino"] += 1
        if hasattr(status, "st_uid"):
            values["st_uid"] = status.st_uid
        if hasattr(status, "st_file_attributes"):
            values["st_file_attributes"] = status.st_file_attributes
        return SimpleNamespace(**values)

    @staticmethod
    def changed_permissions(
        status: os.stat_result,
        *,
        mode: int,
        uid: int,
    ) -> SimpleNamespace:
        values = {
            name: getattr(status, name)
            for name in (
                "st_dev",
                "st_ino",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        }
        values["st_mode"] = stat.S_IFREG | mode
        values["st_uid"] = uid
        if hasattr(status, "st_file_attributes"):
            values["st_file_attributes"] = status.st_file_attributes
        return SimpleNamespace(**values)

    def test_returns_owned_descriptor_at_offset_zero_and_closes_context(self) -> None:
        secret_value = self.values[("api-password", "v1")]

        with self.provider.resolve("api-password", "v1") as handle:
            descriptor = handle.descriptor
            self.assertEqual(handle.reference_id, "api-password")
            self.assertEqual(handle.version_id, "v1")
            self.assertEqual(os.lseek(descriptor, 0, os.SEEK_CUR), 0)
            self.assertFalse(os.get_inheritable(descriptor))
            self.assertEqual(os.read(descriptor, 4096), (secret_value + "\n").encode())
            rendered = repr(handle)
            self.assertNotIn(secret_value, rendered)
            self.assertNotIn(str(self.root), rendered)
            self.assertNotIn(str(descriptor), rendered)
            self.assertFalse(hasattr(handle, "__dict__"))
            with self.assertRaises(TypeError):
                json.dumps(handle)

        self.assert_closed(descriptor)
        handle.close()
        for accessor in (
            lambda: handle.descriptor,
            lambda: handle.reference_id,
            lambda: handle.version_id,
        ):
            with self.assertRaisesRegex(
                SecretMaterialError, "^secret material handle is closed$"
            ):
                accessor()

    def test_success_closes_every_peer_descriptor(self) -> None:
        opened: list[int] = []
        real_open = runtime_secrets._open_secret_descriptor

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        with mock.patch.object(
            runtime_secrets, "_open_secret_descriptor", side_effect=recording_open
        ):
            handle = self.provider.resolve("api-password", "v1")

        self.assertEqual(len(opened), 3)
        selected = handle.descriptor
        for descriptor in opened:
            if descriptor != selected:
                self.assert_closed(descriptor)
        os.fstat(selected)
        handle.close()
        self.assert_closed(selected)

    def test_handle_close_oserror_preserves_legacy_error_and_can_retry(self) -> None:
        handle = self.provider.resolve("api-password", "v1")
        descriptor = handle.descriptor
        real_close = os.close
        calls = 0

        def fail_twice(opened_descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls <= 2:
                raise OSError("injected close failure")
            real_close(opened_descriptor)

        with (
            mock.patch.object(
                runtime_secrets.os,
                "close",
                side_effect=fail_twice,
            ),
            self.assertRaisesRegex(
                SecretMaterialError,
                "^secret material handle is closed$",
            ) as caught,
        ):
            handle.close()

        self.assertNotIn(str(self.root), str(caught.exception))
        self.assertFalse(handle._closed)
        self.assertEqual(handle.descriptor, descriptor)
        os.fstat(descriptor)

        handle.close()
        self.assert_closed(descriptor)
        with self.assertRaisesRegex(
            SecretMaterialError,
            "^secret material handle is closed$",
        ):
            _ = handle.descriptor

    def test_resolve_mounts_returns_sorted_frozen_provider_metadata(self) -> None:
        provider = self.make_provider(tuple(reversed(self.requirements)))
        opened: list[int] = []
        real_open = runtime_secrets._open_secret_descriptor

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        with mock.patch.object(
            runtime_secrets, "_open_secret_descriptor", side_effect=recording_open
        ):
            lease = provider.resolve_mounts("attempt-1")

        self.assertIsInstance(lease, VerifiedSecretMountLease)
        self.assertEqual(
            tuple(mount.secret_class for mount in lease.mounts),
            ("api_password", "jwt_secret", "ws_token"),
        )
        self.assertEqual(len(opened), len(self.requirements))
        for descriptor in opened:
            os.fstat(descriptor)
        for mount in lease.mounts:
            self.assertIsInstance(mount, VerifiedSecretMount)
            self.assertEqual(mount.attempt_id, "attempt-1")
            self.assertEqual(mount.provider_id, "local-file-v1")
            requirement = next(
                item
                for item in self.requirements
                if item.secret_class == mount.secret_class
            )
            self.assertEqual(mount.reference_id, requirement.reference_id)
            self.assertEqual(mount.version_id, requirement.version_id)
            self.assertEqual(mount.source, self.secret_path(requirement).absolute())
            self.assertIsInstance(mount.source_identity, SecretSourceIdentity)
            self.assertEqual(
                tuple(field.name for field in fields(mount)),
                (
                    "attempt_id",
                    "provider_id",
                    "reference_id",
                    "version_id",
                    "secret_class",
                    "source",
                    "source_identity",
                ),
            )
            with self.assertRaises(FrozenInstanceError):
                mount.source = self.root  # type: ignore[misc]
            self.assertFalse(hasattr(mount, "descriptor"))
        self.assertFalse(hasattr(lease, "descriptor"))
        self.assertFalse(hasattr(lease, "__dict__"))
        with self.assertRaises(TypeError):
            json.dumps(lease)

        rendered = repr((lease, lease.mounts, lease.mounts[0].source_identity))
        for secret in (
            *self.values.values(),
            str(self.root),
            *(item.reference_id for item in self.requirements),
            *(item.version_id for item in self.requirements),
            *(str(descriptor) for descriptor in opened),
        ):
            self.assertNotIn(secret, rendered)

        lease.close()
        for descriptor in opened:
            self.assert_closed(descriptor)

    def test_mount_lease_revalidates_with_fresh_descriptors_and_closes(self) -> None:
        opened: list[int] = []
        real_open = runtime_secrets._open_secret_descriptor

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        with mock.patch.object(
            runtime_secrets, "_open_secret_descriptor", side_effect=recording_open
        ):
            with self.provider.resolve_mounts("attempt-1") as lease:
                retained = tuple(opened)
                self.assertEqual(lease.revalidate_sources(), lease.mounts)
                temporary = tuple(opened[len(retained) :])
                self.assertEqual(len(temporary), len(self.requirements))
                for descriptor in retained:
                    os.fstat(descriptor)
                for descriptor in temporary:
                    self.assert_closed(descriptor)

        for descriptor in retained:
            self.assert_closed(descriptor)
        lease.close()
        for accessor in (lambda: lease.mounts, lease.revalidate_sources):
            with self.assertRaisesRegex(SecretMaterialError, "^secret_lease_closed$"):
                accessor()

    def test_mount_lease_rejects_invalid_attempt_and_forged_capability(self) -> None:
        with (
            mock.patch.object(runtime_secrets.os, "lstat") as lstat,
            self.assertRaisesRegex(
                SecretMaterialError, "^secret_lease_identity_invalid$"
            ),
        ):
            self.provider.resolve_mounts("../attempt")
        lstat.assert_not_called()

        genuine = self.provider.resolve_mounts("attempt-1")
        forged = object.__new__(VerifiedSecretMountLease)
        object.__setattr__(forged, "_provider", self.provider)
        object.__setattr__(forged, "_token", object())
        object.__setattr__(forged, "_closed", False)
        for action in (
            lambda: forged.mounts,
            forged.__enter__,
            forged.revalidate_sources,
            forged.close,
        ):
            with self.assertRaisesRegex(
                SecretMaterialError, "^secret_lease_identity_invalid$"
            ):
                action()

        issued_mount = genuine.mounts[0]
        object.__setattr__(issued_mount, "attempt_id", "attempt-other")
        with self.assertRaisesRegex(
            SecretMaterialError, "^secret_lease_identity_invalid$"
        ):
            _ = genuine.mounts
        with self.assertRaisesRegex(
            SecretMaterialError, "^secret_lease_identity_invalid$"
        ):
            genuine.revalidate_sources()
        genuine.close()

    def test_mount_bundle_base_exception_closes_unreturned_descriptor(self) -> None:
        opened: list[int] = []
        real_open = runtime_secrets._open_secret_descriptor

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        with (
            mock.patch.object(
                runtime_secrets,
                "_open_secret_descriptor",
                side_effect=recording_open,
            ),
            mock.patch.object(
                runtime_secrets,
                "_read_validated_value",
                side_effect=KeyboardInterrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.provider.resolve_mounts("attempt-1")

        self.assertEqual(len(opened), 1)
        self.assert_closed(opened[0])

    def test_resolve_base_exception_closes_previously_opened_peers(self) -> None:
        opened: list[int] = []
        calls = 0
        real_open = runtime_secrets._open_secret_material

        def interrupt_second_open(*args: object) -> tuple[int, str]:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            descriptor, value = real_open(*args)
            opened.append(descriptor)
            return descriptor, value

        with (
            mock.patch.object(
                runtime_secrets,
                "_open_secret_material",
                side_effect=interrupt_second_open,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.provider.resolve("api-password", "v1")

        self.assertEqual(len(opened), 1)
        self.assert_closed(opened[0])

    def test_mount_lease_close_attempts_every_descriptor_before_control_error(
        self,
    ) -> None:
        opened: list[int] = []
        real_open = runtime_secrets._open_secret_descriptor
        real_close = os.close

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        with mock.patch.object(
            runtime_secrets,
            "_open_secret_descriptor",
            side_effect=recording_open,
        ):
            lease = self.provider.resolve_mounts("attempt-close-interrupted")

        attempted: list[int] = []

        def interrupt_first_close(descriptor: int) -> None:
            attempted.append(descriptor)
            if len(attempted) == 1:
                raise KeyboardInterrupt
            real_close(descriptor)

        with (
            mock.patch.object(
                runtime_secrets.os,
                "close",
                side_effect=interrupt_first_close,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            lease.close()

        self.assertEqual(attempted, [opened[0], opened[0], *opened[1:]])
        self.assertFalse(lease._closed)
        self.assertEqual(len(self.provider._active_mount_leases), 1)
        for descriptor in opened:
            self.assert_closed(descriptor)
        lease.close()
        self.assertTrue(lease._closed)
        self.assertFalse(self.provider._active_mount_leases)

    def test_mount_lease_close_oserror_retains_recoverable_registry(self) -> None:
        opened: list[int] = []
        real_open = runtime_secrets._open_secret_descriptor
        real_close = os.close

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        with mock.patch.object(
            runtime_secrets,
            "_open_secret_descriptor",
            side_effect=recording_open,
        ):
            lease = self.provider.resolve_mounts("attempt-close-oserror")

        attempted: list[int] = []

        def fail_first_descriptor_twice(descriptor: int) -> None:
            attempted.append(descriptor)
            if descriptor == opened[0] and attempted.count(descriptor) <= 2:
                raise OSError("injected close failure")
            real_close(descriptor)

        with (
            mock.patch.object(
                runtime_secrets.os,
                "close",
                side_effect=fail_first_descriptor_twice,
            ),
            self.assertRaisesRegex(
                SecretMaterialError,
                "^secret_lease_close_failed$",
            ),
        ):
            lease.close()

        self.assertEqual(attempted, [opened[0], opened[0], *opened[1:]])
        self.assertFalse(lease._closed)
        self.assertEqual(len(self.provider._active_mount_leases), 1)
        os.fstat(opened[0])
        for descriptor in opened[1:]:
            self.assert_closed(descriptor)

        lease.close()
        self.assertTrue(lease._closed)
        self.assertFalse(self.provider._active_mount_leases)
        for descriptor in opened:
            self.assert_closed(descriptor)

    def test_mount_bundle_rejects_unsafe_ancestor_permissions(self) -> None:
        rejected = self.secret_path(self.requirements[0]).parent.parent
        real_verify = runtime_secrets._verify_secret_directory_chain_permissions

        def reject_reference(
            components: tuple[tuple[Path, os.stat_result], ...],
            runtime_uid: int,
        ) -> None:
            if any(Path(path) == rejected for path, _ in components):
                raise SecretMaterialError("secret permissions are invalid")
            real_verify(components, runtime_uid)

        with (
            mock.patch.object(
                runtime_secrets,
                "_verify_secret_directory_chain_permissions",
                side_effect=reject_reference,
            ),
            self.assertRaisesRegex(
                SecretMaterialError,
                "^secret_lease_source_changed$",
            ),
        ):
            self.provider.resolve_mounts("attempt-1")

    @unittest.skipUnless(os.name == "nt", "Windows ACL integration test")
    def test_mount_bundle_windows_real_acl_mints_and_revalidates(self) -> None:
        assert self.secret_permission_patcher is not None
        assert self.directory_permission_patcher is not None
        requirement = self.requirements[0]
        source = self.secret_path(requirement)
        bootstrap_runtime._harden_windows_trusted_directory_permissions(self.root)
        bootstrap_runtime._run_windows_acl("harden", source)
        self.secret_permission_patcher.stop()
        self.directory_permission_patcher.stop()
        provider = self.make_provider((requirement,))

        with provider.resolve_mounts("attempt-windows-real-acl") as lease:
            self.assertEqual(lease.revalidate_sources(), lease.mounts)

    @unittest.skipIf(os.name == "nt", "POSIX permission semantics only")
    def test_mount_bundle_posix_rejects_group_writable_ancestor(self) -> None:
        ancestor = self.secret_path(self.requirements[0]).parent.parent
        original_mode = stat.S_IMODE(os.lstat(ancestor).st_mode)
        os.chmod(ancestor, original_mode | 0o020)
        self.addCleanup(os.chmod, ancestor, original_mode)

        with self.assertRaisesRegex(
            SecretMaterialError,
            "^secret_lease_source_changed$",
        ):
            self.provider.resolve_mounts("attempt-1")

    def test_mount_lease_rejects_duplicate_class_before_filesystem_io(self) -> None:
        duplicate_class = (
            SecretMaterialRequirement("api-password", "v1", "api_password"),
            SecretMaterialRequirement("api-password-2", "v2", "api_password"),
        )
        provider = self.make_provider(duplicate_class)
        with (
            mock.patch.object(runtime_secrets.os, "lstat") as lstat,
            self.assertRaisesRegex(
                SecretMaterialError, "^secret_lease_identity_invalid$"
            ),
        ):
            provider.resolve_mounts("attempt-1")
        lstat.assert_not_called()

    def test_mount_bundle_source_failure_closes_descriptors_and_is_redacted(
        self,
    ) -> None:
        invalid = self.requirements[-1]
        self.write_secret(invalid, b"invalid\x00material", ending=b"")
        opened: list[int] = []
        real_open = runtime_secrets._open_secret_descriptor

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        with (
            mock.patch.object(
                runtime_secrets, "_open_secret_descriptor", side_effect=recording_open
            ),
            self.assertRaisesRegex(
                SecretMaterialError, "^secret_lease_source_changed$"
            ) as raised,
        ):
            self.provider.resolve_mounts("attempt-1")
        self.assertEqual(len(opened), len(self.requirements))
        for descriptor in opened:
            self.assert_closed(descriptor)
        rendered = repr(raised.exception)
        for secret in (
            *self.values.values(),
            str(self.root),
            invalid.reference_id,
            invalid.version_id,
            *(str(descriptor) for descriptor in opened),
        ):
            self.assertNotIn(secret, rendered)

    def test_mount_lease_rejects_ancestor_identity_drift_without_leakage(self) -> None:
        lease = self.provider.resolve_mounts("attempt-1")
        reference_directory = self.secret_path(self.requirements[0]).parent.parent
        real_lstat = os.lstat
        real_open = runtime_secrets._open_secret_descriptor
        opened: list[int] = []

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        def drifted_lstat(path: os.PathLike[str] | str) -> object:
            status = real_lstat(path)
            if Path(path) != reference_directory:
                return status
            values = {
                name: getattr(status, name)
                for name in dir(status)
                if name.startswith("st_")
            }
            values["st_ino"] = status.st_ino + 1
            return SimpleNamespace(**values)

        try:
            with (
                mock.patch.object(
                    runtime_secrets.os, "lstat", side_effect=drifted_lstat
                ),
                mock.patch.object(
                    runtime_secrets,
                    "_open_secret_descriptor",
                    side_effect=recording_open,
                ),
                self.assertRaisesRegex(
                    SecretMaterialError, "^secret_lease_source_changed$"
                ) as raised,
            ):
                lease.revalidate_sources()
            self.assertTrue(opened)
            for descriptor in opened:
                self.assert_closed(descriptor)
            rendered = repr(raised.exception)
            for secret in (
                *self.values.values(),
                str(self.root),
                *(item.reference_id for item in self.requirements),
                *(item.version_id for item in self.requirements),
                *(str(descriptor) for descriptor in opened),
            ):
                self.assertNotIn(secret, rendered)
        finally:
            lease.close()

    @unittest.skipUnless(os.name == "nt", "Windows mount lease lock test")
    def test_mount_lease_windows_blocks_replacement_until_close(self) -> None:
        target = self.secret_path(self.requirements[0])
        displaced = target.with_name("displaced")
        lease = self.provider.resolve_mounts("attempt-1")
        try:
            with self.assertRaises(OSError):
                os.replace(target, displaced)
        finally:
            lease.close()
        os.replace(target, displaced)
        os.replace(displaced, target)

    @unittest.skipIf(os.name == "nt", "POSIX source mutation test")
    def test_mount_lease_rejects_content_permission_and_replacement_drift(self) -> None:
        requirement = self.requirements[0]
        target = self.secret_path(requirement)
        cases = ("content", "permission", "replacement")
        for case in cases:
            with self.subTest(case=case):
                self.write_secret(requirement, self.values[requirement.identity])
                lease = self.provider.resolve_mounts("attempt-1")
                displaced = target.with_name("displaced")
                replacement = target.with_name("replacement")
                try:
                    if case == "content":
                        target.write_text("z" * 32 + "\n", encoding="utf-8")
                        os.chmod(target, 0o600)
                    elif case == "permission":
                        os.chmod(target, 0o644)
                    else:
                        replacement.write_text("z" * 32 + "\n", encoding="utf-8")
                        os.chmod(replacement, 0o600)
                        os.replace(target, displaced)
                        os.replace(replacement, target)
                    with self.assertRaisesRegex(
                        SecretMaterialError, "^secret_lease_source_changed$"
                    ):
                        lease.revalidate_sources()
                finally:
                    lease.close()
                    if displaced.exists():
                        if target.exists():
                            target.unlink()
                        os.replace(displaced, target)
                    replacement.unlink(missing_ok=True)
                    if target.exists():
                        os.chmod(target, 0o600)

    def test_accepts_only_no_newline_one_lf_or_one_crlf(self) -> None:
        requirement = self.requirements[0]
        for ending in (b"", b"\n", b"\r\n"):
            with self.subTest(ending=ending):
                self.write_secret(
                    requirement, self.values[requirement.identity], ending=ending
                )
                with self.provider.resolve(*requirement.identity) as handle:
                    self.assertEqual(os.lseek(handle.descriptor, 0, os.SEEK_CUR), 0)

    def test_rejects_python_and_unicode_line_boundaries(self) -> None:
        requirement = self.requirements[0]
        line_boundaries = (
            "\v",
            "\f",
            "\x1c",
            "\x1d",
            "\x1e",
            "\x85",
            "\u2028",
            "\u2029",
        )

        def resolve_and_close() -> None:
            with self.provider.resolve(*requirement.identity):
                pass

        for boundary in line_boundaries:
            with self.subTest(boundary=ascii(boundary)):
                self.write_secret(requirement, "a" * 32 + boundary, ending=b"")
                with self.assertRaisesRegex(
                    SecretMaterialError, "^secret content is invalid$"
                ):
                    resolve_and_close()

    def test_rejects_invalid_constructor_requirements_before_filesystem_io(
        self,
    ) -> None:
        invalid_cases = (
            (),
            (SecretMaterialRequirement("api-password", "v1", "unknown"),),
            (
                SecretMaterialRequirement("api-password", "v1", "api_password"),
                SecretMaterialRequirement("api-password", "v2", "jwt_secret"),
            ),
            (
                SecretMaterialRequirement("api-password", "v1", "api_password"),
                SecretMaterialRequirement("api-password", "v1", "api_password"),
            ),
        )
        for requirements in invalid_cases:
            with (
                self.subTest(requirements=requirements),
                mock.patch.object(runtime_secrets.os, "lstat") as lstat,
                self.assertRaisesRegex(
                    SecretMaterialError, "^secret identity is invalid$"
                ),
            ):
                self.make_provider(requirements, root=self.root / "missing")
            lstat.assert_not_called()

    def test_requirement_fields_use_the_closed_identifier_grammar(self) -> None:
        invalid_values = ("", "Upper", "../escape", "-leading", "a" * 129)
        for field in ("reference_id", "version_id", "secret_class"):
            for value in invalid_values:
                arguments = {
                    "reference_id": "api-password",
                    "version_id": "v1",
                    "secret_class": "api_password",
                }
                arguments[field] = value
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaisesRegex(
                        SecretMaterialError, "^secret identity is invalid$"
                    ),
                ):
                    SecretMaterialRequirement(**arguments)

    def test_unknown_and_malformed_identity_fail_without_filesystem_io(self) -> None:
        for identity in (("../outside", "v1"), ("api-password", "unknown")):
            with (
                self.subTest(identity=identity),
                mock.patch.object(runtime_secrets.os, "lstat") as lstat,
                self.assertRaisesRegex(
                    SecretMaterialError, "^secret identity is invalid$"
                ),
            ):
                self.provider.resolve(*identity)
            lstat.assert_not_called()

    def test_relative_root_is_frozen_when_provider_is_constructed(self) -> None:
        original_cwd = Path.cwd()
        location_a = Path(self.temporary_directory.name) / "location-a"
        location_b = Path(self.temporary_directory.name) / "location-b"
        location_a.mkdir()
        location_b.mkdir()
        shutil.copytree(self.root, location_a / "relative-secrets")
        try:
            os.chdir(location_a)
            provider = self.make_provider(root=Path("relative-secrets"))
            os.chdir(location_b)
            with provider.resolve("api-password", "v1") as handle:
                self.assertEqual(
                    os.read(handle.descriptor, 4096),
                    (self.values[("api-password", "v1")] + "\n").encode(),
                )
        finally:
            os.chdir(original_cwd)

    def test_resolve_has_no_caller_controlled_path_or_policy_surface(self) -> None:
        parameters = tuple(
            inspect.signature(LocalFileSecretProvider.resolve).parameters
        )
        self.assertEqual(parameters, ("self", "reference_id", "version_id"))
        for name in ("list", "list_requirements", "requirements", "enumerate"):
            self.assertFalse(hasattr(self.provider, name))

        with (
            mock.patch.object(Path, "iterdir", side_effect=AssertionError("scan")),
            mock.patch.object(
                runtime_secrets.os, "scandir", side_effect=AssertionError("scan")
            ),
            mock.patch.object(
                runtime_secrets.os, "listdir", side_effect=AssertionError("scan")
            ),
            self.provider.resolve("api-password", "v1") as handle,
        ):
            self.assertEqual(handle.reference_id, "api-password")

    def test_missing_and_non_regular_components_fail_with_stable_error(self) -> None:
        target = self.secret_path(self.requirements[0])
        cases = (self.root, target.parent.parent, target.parent, target)
        for component in cases:
            with self.subTest(component=component):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory) / "secrets"
                    provider = self.make_provider(root=root)
                    relative = component.relative_to(self.root)
                    missing = root / relative
                    missing.parent.mkdir(parents=True, exist_ok=True)
                    if missing.name == "value":
                        missing.mkdir()
                    with self.assertRaisesRegex(
                        SecretMaterialError, "^secret path is not a regular file$"
                    ):
                        provider.resolve("api-password", "v1")

    def test_rejects_root_reference_version_and_file_link_or_reparse(self) -> None:
        target = self.secret_path(self.requirements[0])
        components = (self.root, target.parent.parent, target.parent, target)
        real_check = runtime_secrets._is_link_or_reparse
        for component in components:
            with (
                self.subTest(component=component),
                mock.patch.object(
                    runtime_secrets,
                    "_is_link_or_reparse",
                    side_effect=lambda path, status, component=component: (
                        path == component or real_check(path, status)
                    ),
                ),
                self.assertRaisesRegex(
                    SecretMaterialError, "^secret path is not a regular file$"
                ),
            ):
                self.provider.resolve("api-password", "v1")

    def test_rejects_real_file_symlink_escape_when_host_allows_it(self) -> None:
        target = self.secret_path(self.requirements[0])
        outside = Path(self.temporary_directory.name) / "outside"
        outside.write_text("x" * 32, encoding="utf-8")
        target.unlink()
        try:
            target.symlink_to(outside)
            simulation = None
        except OSError:
            target.write_text("x" * 32, encoding="utf-8")
            simulation = mock.patch.object(
                runtime_secrets,
                "_is_link_or_reparse",
                side_effect=lambda path, status: path == target,
            )

        if target.is_symlink():
            with self.assertRaisesRegex(
                SecretMaterialError, "^secret path is not a regular file$"
            ):
                self.provider.resolve("api-password", "v1")
        else:
            assert simulation is not None
            with (
                simulation,
                self.assertRaisesRegex(
                    SecretMaterialError, "^secret path is not a regular file$"
                ),
            ):
                self.provider.resolve("api-password", "v1")

    def test_rejects_hardlink_and_non_regular_value(self) -> None:
        requirement = self.requirements[0]
        target = self.secret_path(requirement)
        peer = target.with_name("hardlink-peer")
        os.link(target, peer)
        with self.assertRaisesRegex(
            SecretMaterialError, "^secret path is not a regular file$"
        ):
            self.provider.resolve(*requirement.identity)
        peer.unlink()

        target.unlink()
        target.mkdir()
        with self.assertRaisesRegex(
            SecretMaterialError, "^secret path is not a regular file$"
        ):
            self.provider.resolve(*requirement.identity)

    def test_rejects_pre_open_descriptor_identity_replacement(self) -> None:
        target = self.secret_path(self.requirements[0])
        real_fstat = os.fstat
        opened_target: list[int] = []
        real_open = runtime_secrets._open_secret_descriptor

        def open_file(path: Path) -> int:
            descriptor = real_open(path)
            if Path(path) == target:
                opened_target.append(descriptor)
            return descriptor

        def changed_fstat(descriptor: int) -> os.stat_result | SimpleNamespace:
            status = real_fstat(descriptor)
            if descriptor in opened_target:
                return self.changed_identity(status)
            return status

        with (
            mock.patch.object(
                runtime_secrets, "_open_secret_descriptor", side_effect=open_file
            ),
            mock.patch.object(runtime_secrets.os, "fstat", side_effect=changed_fstat),
            self.assertRaisesRegex(
                SecretMaterialError, "^secret path is not a regular file$"
            ),
        ):
            self.provider.resolve("api-password", "v1")
        for descriptor in opened_target:
            self.assert_closed(descriptor)

    def test_rejects_post_validation_identity_replacement(self) -> None:
        target = self.secret_path(self.requirements[0])
        real_lstat = os.lstat
        target_calls = 0

        def raced_lstat(
            path: os.PathLike[str] | str,
        ) -> os.stat_result | SimpleNamespace:
            nonlocal target_calls
            status = real_lstat(path)
            if Path(path) == target:
                target_calls += 1
                if target_calls > 1:
                    return self.changed_identity(status)
            return status

        with (
            mock.patch.object(runtime_secrets.os, "lstat", side_effect=raced_lstat),
            self.assertRaisesRegex(
                SecretMaterialError, "^secret path is not a regular file$"
            ),
        ):
            self.provider.resolve("api-password", "v1")

    def test_translates_posix_mode_and_owner_failures_without_details(self) -> None:
        target = self.secret_path(self.requirements[0])
        secret_value = self.values[self.requirements[0].identity]
        cases = (
            SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=self.runtime_uid),
            SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=self.runtime_uid + 1),
        )
        for permission_status in cases:
            with (
                self.subTest(permission_status=permission_status),
                mock.patch.object(
                    runtime_secrets,
                    "_verify_secret_permissions",
                    wraps=bootstrap_runtime._verify_secret_permissions,
                ),
                mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
                mock.patch.object(Path, "stat", return_value=permission_status),
                self.assertRaisesRegex(
                    SecretMaterialError, "^secret permissions are invalid$"
                ) as raised,
            ):
                self.provider.resolve("api-password", "v1")
            rendered = repr(raised.exception)
            self.assertNotIn(secret_value, rendered)
            self.assertNotIn(str(target), rendered)
            self.assertNotIn("0600", rendered)

    def test_translates_windows_acl_failure_without_details(self) -> None:
        target = self.secret_path(self.requirements[0])
        secret_value = self.values[self.requirements[0].identity]
        with (
            mock.patch.object(
                runtime_secrets,
                "_verify_secret_permissions",
                wraps=bootstrap_runtime._verify_secret_permissions,
            ),
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=True),
            mock.patch.object(
                bootstrap_runtime,
                "_run_windows_acl",
                side_effect=ValueError(f"ACL failed for {target}: {secret_value}"),
            ),
            self.assertRaisesRegex(
                SecretMaterialError, "^secret permissions are invalid$"
            ) as raised,
        ):
            self.provider.resolve("api-password", "v1")
        self.assertEqual(str(raised.exception), "secret permissions are invalid")
        self.assertIsNone(raised.exception.__cause__)

    def test_posix_descriptor_permissions_reject_bad_opened_mode_or_owner(self) -> None:
        target = self.secret_path(self.requirements[0])
        real_open = os.open
        real_lstat = os.lstat
        real_fstat = os.fstat
        cases = (
            (0o644, self.runtime_uid),
            (0o600, self.runtime_uid + 1),
        )
        for mode, uid in cases:
            opened_target: set[int] = set()
            opened_status = self.changed_permissions(
                real_lstat(target),
                mode=mode,
                uid=uid,
            )

            def open_file(path: os.PathLike[str] | str, flags: int) -> int:
                descriptor = real_open(path, flags)
                if Path(path) == target:
                    opened_target.add(descriptor)
                return descriptor

            def lstat_file(
                path: os.PathLike[str] | str,
            ) -> os.stat_result | SimpleNamespace:
                if Path(path) == target:
                    return opened_status
                return real_lstat(path)

            def fstat_file(descriptor: int) -> os.stat_result | SimpleNamespace:
                if descriptor in opened_target:
                    return opened_status
                return real_fstat(descriptor)

            with (
                self.subTest(mode=oct(mode), uid=uid),
                mock.patch.object(
                    runtime_secrets,
                    "_is_windows",
                    return_value=False,
                    create=True,
                ),
                mock.patch.object(runtime_secrets.os, "open", side_effect=open_file),
                mock.patch.object(runtime_secrets.os, "lstat", side_effect=lstat_file),
                mock.patch.object(runtime_secrets.os, "fstat", side_effect=fstat_file),
                mock.patch.object(runtime_secrets, "_verify_secret_permissions"),
                self.assertRaisesRegex(
                    SecretMaterialError, "^secret permissions are invalid$"
                ),
            ):
                with self.provider.resolve("api-password", "v1"):
                    pass

    @unittest.skipIf(os.name == "nt", "POSIX rename race test")
    def test_posix_descriptor_permissions_reject_path_acl_aba(self) -> None:
        requirement = self.requirements[0]
        target = self.secret_path(requirement)
        displaced = target.with_name("displaced")
        replacement = target.with_name("replacement")
        self.write_secret(requirement, self.values[requirement.identity])
        replacement.write_text("z" * 32, encoding="utf-8")
        os.chmod(replacement, 0o600)
        proof_calls = 0

        def prove_replacement_permissions(path: Path, runtime_uid: int) -> None:
            nonlocal proof_calls
            proof_calls += 1
            original_displaced = False
            replacement_installed = False
            try:
                os.replace(path, displaced)
                original_displaced = True
                os.replace(replacement, path)
                replacement_installed = True
                bootstrap_runtime._verify_secret_permissions(path, runtime_uid)
                os.chmod(displaced, 0o644)
            finally:
                if replacement_installed:
                    os.replace(path, replacement)
                if original_displaced:
                    os.replace(displaced, path)

        try:
            with (
                mock.patch.object(
                    runtime_secrets,
                    "_verify_secret_permissions",
                    side_effect=prove_replacement_permissions,
                ),
                self.assertRaisesRegex(
                    SecretMaterialError, "^secret permissions are invalid$"
                ),
            ):
                with self.provider.resolve(*requirement.identity):
                    pass
        finally:
            if displaced.exists():
                if target.exists():
                    os.replace(target, replacement)
                os.replace(displaced, target)
            for path in (target, replacement):
                if path.exists():
                    os.chmod(path, 0o600)
        self.assertEqual(proof_calls, 1)
        self.assertTrue(target.is_file())
        self.assertTrue(replacement.is_file())
        self.assertFalse(displaced.exists())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(replacement.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "nt", "Windows share-lock test")
    def test_windows_descriptor_blocks_replacement_during_acl_proof(self) -> None:
        target = self.secret_path(self.requirements[0])
        displaced = target.with_name("displaced")
        attempted_paths: list[Path] = []

        def prove_acl_while_locked(path: Path, runtime_uid: int) -> None:
            del runtime_uid
            if path.name != "value":
                return
            attempted_paths.append(path)
            with self.assertRaises(OSError):
                os.replace(path, path.with_name("displaced"))

        with (
            mock.patch.object(
                runtime_secrets,
                "_open_windows_locked",
                wraps=runtime_secrets._open_windows_locked,
            ) as locked_open,
            mock.patch.object(
                runtime_secrets,
                "_verify_secret_permissions",
                side_effect=prove_acl_while_locked,
            ),
            self.provider.resolve("api-password", "v1") as handle,
        ):
            self.assertEqual(len(attempted_paths), 3)
            self.assertEqual(locked_open.call_count, 3)
            with self.assertRaises(OSError):
                os.replace(target, displaced)
            descriptor = handle.descriptor
            os.fstat(descriptor)

        os.replace(target, displaced)
        os.replace(displaced, target)

    @unittest.skipUnless(os.name == "nt", "Windows HANDLE ownership test")
    def test_windows_descriptor_conversion_failure_closes_handle_and_redacts(
        self,
    ) -> None:
        import msvcrt

        target = self.secret_path(self.requirements[0])
        displaced = target.with_name("displaced")
        secret_value = self.values[self.requirements[0].identity]
        with (
            mock.patch.object(
                msvcrt,
                "open_osfhandle",
                side_effect=ValueError(f"conversion failed: {target}: {secret_value}"),
            ),
            self.assertRaisesRegex(
                SecretMaterialError, "^secret path is not a regular file$"
            ) as raised,
        ):
            self.provider.resolve("api-password", "v1")
        self.assertNotIn(str(target), repr(raised.exception))
        self.assertNotIn(secret_value, repr(raised.exception))
        os.replace(target, displaced)
        os.replace(displaced, target)

    def test_rejects_invalid_content_with_stable_redacted_error(self) -> None:
        requirement = self.requirements[0]
        secret_value = "value-that-must-never-appear-in-errors"
        cases = (
            (b"", b""),
            (b"\xff", b""),
            (("a" * 32 + "\x00" + secret_value).encode(), b""),
            (("a" * 32 + "\n" + secret_value).encode(), b""),
            (("a" * 32).encode(), b"\n\n"),
            (b"a" * 31, b""),
            (b"a" * 4097, b""),
            (("é" * 2049).encode("utf-8"), b""),
        )
        for content, ending in cases:
            with self.subTest(size=len(content), ending=ending):
                self.write_secret(requirement, content, ending=ending)
                with self.assertRaisesRegex(
                    SecretMaterialError, "^secret content is invalid$"
                ) as raised:
                    self.provider.resolve(*requirement.identity)
                rendered = repr(raised.exception)
                self.assertNotIn(secret_value, rendered)
                self.assertNotIn(str(self.root), rendered)

    def test_enforces_each_secret_class_minimum(self) -> None:
        minimums = {"api_password": 32, "jwt_secret": 48, "ws_token": 32}
        for requirement in self.requirements:
            with self.subTest(secret_class=requirement.secret_class):
                self.write_secret(
                    requirement, "x" * (minimums[requirement.secret_class] - 1)
                )
                with self.assertRaisesRegex(
                    SecretMaterialError, "^secret content is invalid$"
                ):
                    self.provider.resolve(*requirement.identity)
                self.write_secret(requirement, self.values[requirement.identity])

    def test_duplicate_normalized_values_close_every_descriptor(self) -> None:
        repeated = "same-required-value-that-must-remain-private" * 2
        self.write_secret(self.requirements[0], repeated, ending=b"\n")
        self.write_secret(self.requirements[1], repeated, ending=b"\r\n")
        opened: list[int] = []
        real_open = runtime_secrets._open_secret_descriptor

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        with (
            mock.patch.object(
                runtime_secrets, "_open_secret_descriptor", side_effect=recording_open
            ),
            self.assertRaisesRegex(
                SecretMaterialError, "^required secret values must be distinct$"
            ) as raised,
        ):
            self.provider.resolve("api-password", "v1")
        self.assertNotIn(repeated, repr(raised.exception))
        self.assertEqual(len(opened), 3)
        for descriptor in opened:
            self.assert_closed(descriptor)

    def test_content_failure_closes_the_open_descriptor(self) -> None:
        requirement = self.requirements[0]
        self.write_secret(requirement, b"invalid\x00material", ending=b"")
        opened: list[int] = []
        real_open = runtime_secrets._open_secret_descriptor

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        with (
            mock.patch.object(
                runtime_secrets, "_open_secret_descriptor", side_effect=recording_open
            ),
            self.assertRaisesRegex(SecretMaterialError, "^secret content is invalid$"),
        ):
            self.provider.resolve(*requirement.identity)
        self.assertEqual(len(opened), 1)
        self.assert_closed(opened[0])


if __name__ == "__main__":
    unittest.main()
