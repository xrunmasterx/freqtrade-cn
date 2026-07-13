from __future__ import annotations

import inspect
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import bootstrap_runtime, runtime_secrets
from tools.runtime_secrets import (
    LocalFileSecretProvider,
    SecretMaterialError,
    SecretMaterialRequirement,
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
        if os.name == "nt":
            permissions = mock.patch.object(runtime_secrets, "_verify_secret_permissions")
            self.permission_proof = permissions.start()
            self.addCleanup(permissions.stop)
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

    def test_accepts_only_no_newline_one_lf_or_one_crlf(self) -> None:
        requirement = self.requirements[0]
        for ending in (b"", b"\n", b"\r\n"):
            with self.subTest(ending=ending):
                self.write_secret(requirement, self.values[requirement.identity], ending=ending)
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

    def test_rejects_invalid_constructor_requirements_before_filesystem_io(self) -> None:
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
                self.assertRaisesRegex(SecretMaterialError, "^secret identity is invalid$"),
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
                self.assertRaisesRegex(SecretMaterialError, "^secret identity is invalid$"),
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
        parameters = tuple(inspect.signature(LocalFileSecretProvider.resolve).parameters)
        self.assertEqual(parameters, ("self", "reference_id", "version_id"))
        for name in ("list", "list_requirements", "requirements", "enumerate"):
            self.assertFalse(hasattr(self.provider, name))

        with (
            mock.patch.object(Path, "iterdir", side_effect=AssertionError("scan")),
            mock.patch.object(runtime_secrets.os, "scandir", side_effect=AssertionError("scan")),
            mock.patch.object(runtime_secrets.os, "listdir", side_effect=AssertionError("scan")),
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

        def raced_lstat(path: os.PathLike[str] | str) -> os.stat_result | SimpleNamespace:
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
        os.chmod(target, 0o644)
        replacement.write_text("z" * 32, encoding="utf-8")
        os.chmod(replacement, 0o600)

        def prove_replacement_permissions(path: Path, runtime_uid: int) -> None:
            os.replace(path, displaced)
            os.replace(replacement, path)
            try:
                bootstrap_runtime._verify_secret_permissions(path, runtime_uid)
            finally:
                os.replace(path, replacement)
                os.replace(displaced, path)

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

    @unittest.skipUnless(os.name == "nt", "Windows share-lock test")
    def test_windows_descriptor_blocks_replacement_during_acl_proof(self) -> None:
        target = self.secret_path(self.requirements[0])
        displaced = target.with_name("displaced")
        attempted_paths: list[Path] = []

        def prove_acl_while_locked(path: Path, runtime_uid: int) -> None:
            del runtime_uid
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
    def test_windows_descriptor_conversion_failure_closes_handle_and_redacts(self) -> None:
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
                self.write_secret(requirement, "x" * (minimums[requirement.secret_class] - 1))
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
