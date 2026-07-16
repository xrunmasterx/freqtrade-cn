from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tools.bootstrap_runtime import (
    _is_windows,
    _verify_secret_permissions,
    _verify_windows_trusted_paths_permissions,
)


DEFAULT_SECRET_ROOT = Path("ft_userdata/secrets/runtime")

_IDENTIFIER_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_MINIMUM_CLASS_LENGTHS: Final = {
    "api_password": 32,
    "jwt_secret": 48,
    "ws_token": 32,
}
_MAXIMUM_MATERIAL_LENGTH: Final = 4096
_PROVIDER_ID: Final = "local-file-secret-v1"
_ADDITIONAL_LINE_BOUNDARIES: Final = (
    "\v",
    "\f",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
)

_IDENTITY_ERROR: Final = "secret identity is invalid"
_PATH_ERROR: Final = "secret path is not a regular file"
_PERMISSIONS_ERROR: Final = "secret permissions are invalid"
_CONTENT_ERROR: Final = "secret content is invalid"
_DISTINCT_ERROR: Final = "required secret values must be distinct"
_CLOSED_ERROR: Final = "secret material handle is closed"
_LEASE_IDENTITY_ERROR: Final = "secret_lease_identity_invalid"
_LEASE_CLOSED_ERROR: Final = "secret_lease_closed"
_LEASE_SOURCE_CHANGED_ERROR: Final = "secret_lease_source_changed"
_LEASE_CLOSE_ERROR: Final = "secret_lease_close_failed"


class SecretMaterialError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SecretMaterialRequirement:
    reference_id: str
    version_id: str
    secret_class: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value)
            for value in (self.reference_id, self.version_id, self.secret_class)
        ):
            raise SecretMaterialError(_IDENTITY_ERROR)

    @property
    def identity(self) -> tuple[str, str]:
        return self.reference_id, self.version_id


@dataclass(frozen=True, slots=True, repr=False)
class _SecretPathIdentity:
    device: int | None
    inode: int | None
    mode: int | None
    link_count: int | None
    size: int | None
    modified_ns: int | None
    changed_ns: int | None
    owner_uid: int | None
    owner_gid: int | None
    file_attributes: int | None


@dataclass(frozen=True, slots=True, repr=False)
class SecretSourceIdentity:
    root: _SecretPathIdentity
    reference_directory: _SecretPathIdentity
    version_directory: _SecretPathIdentity
    value_file: _SecretPathIdentity

    def __repr__(self) -> str:
        return "<SecretSourceIdentity>"


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedSecretMount:
    attempt_id: str
    provider_id: str
    reference_id: str
    version_id: str
    secret_class: str
    source: Path
    source_identity: SecretSourceIdentity

    def __post_init__(self) -> None:
        identifiers = (
            self.attempt_id,
            self.provider_id,
            self.reference_id,
            self.version_id,
            self.secret_class,
        )
        if (
            not all(
                isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value)
                for value in identifiers
            )
            or self.provider_id != _PROVIDER_ID
            or not isinstance(self.source, Path)
            or not self.source.is_absolute()
            or not isinstance(self.source_identity, SecretSourceIdentity)
        ):
            raise SecretMaterialError(_LEASE_IDENTITY_ERROR)

    def __repr__(self) -> str:
        return "<VerifiedSecretMount>"


@dataclass(frozen=True, slots=True)
class _ActiveSecretMount:
    requirement: SecretMaterialRequirement
    source: Path
    source_identity: SecretSourceIdentity
    descriptor: int


@dataclass(frozen=True, slots=True)
class _ActiveSecretLease:
    lease: VerifiedSecretMountLease
    attempt_id: str
    mounts: tuple[VerifiedSecretMount, ...]
    active_mounts: tuple[_ActiveSecretMount, ...]


class VerifiedSecretMountLease:
    __slots__ = ("_closed", "_provider", "_token")

    def __init__(
        self,
        provider: LocalFileSecretProvider,
        token: object,
    ) -> None:
        if not isinstance(provider, LocalFileSecretProvider):
            raise SecretMaterialError(_LEASE_IDENTITY_ERROR)
        self._provider = provider
        self._token = token
        self._closed = False

    @property
    def mounts(self) -> tuple[VerifiedSecretMount, ...]:
        self._require_open()
        return self._provider._lease_mounts(self)

    def revalidate_sources(self) -> tuple[VerifiedSecretMount, ...]:
        self._require_open()
        return self._provider._revalidate_mount_lease(self)

    def close(self) -> None:
        if self._closed:
            return
        self._provider._close_mount_lease(self)

    def __enter__(self) -> VerifiedSecretMountLease:
        self._require_open()
        self._provider._lease_mounts(self)
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        return f"<VerifiedSecretMountLease {state}>"

    def _require_open(self) -> None:
        if self._closed:
            raise SecretMaterialError(_LEASE_CLOSED_ERROR)


class SecretMaterialHandle:
    __slots__ = ("_closed", "_descriptor", "_reference_id", "_version_id")

    def __init__(self, reference_id: str, version_id: str, descriptor: int) -> None:
        self._reference_id = reference_id
        self._version_id = version_id
        self._descriptor = descriptor
        self._closed = False

    @property
    def reference_id(self) -> str:
        self._require_open()
        return self._reference_id

    @property
    def version_id(self) -> str:
        self._require_open()
        return self._version_id

    @property
    def descriptor(self) -> int:
        self._require_open()
        return self._descriptor

    def close(self) -> None:
        if self._closed:
            return
        descriptor = self._descriptor
        try:
            _close_descriptors([descriptor])
        except SecretMaterialError:
            raise SecretMaterialError(_CLOSED_ERROR) from None
        self._closed = True
        self._descriptor = -1

    def __enter__(self) -> SecretMaterialHandle:
        self._require_open()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        return f"<SecretMaterialHandle {state}>"

    def _require_open(self) -> None:
        if self._closed:
            raise SecretMaterialError(_CLOSED_ERROR)


class LocalFileSecretProvider:
    __slots__ = (
        "_active_mount_leases",
        "_requirements",
        "_requirements_by_identity",
        "_runtime_uid",
        "_secret_root",
    )

    def __init__(
        self,
        requirements: tuple[SecretMaterialRequirement, ...],
        *,
        runtime_uid: int,
        secret_root: Path = DEFAULT_SECRET_ROOT,
    ) -> None:
        if not isinstance(requirements, tuple) or not requirements:
            raise SecretMaterialError(_IDENTITY_ERROR)
        if type(runtime_uid) is not int or runtime_uid < 0:
            raise SecretMaterialError(_IDENTITY_ERROR)

        requirements_by_identity: dict[tuple[str, str], SecretMaterialRequirement] = {}
        reference_ids: set[str] = set()
        for requirement in requirements:
            if not isinstance(requirement, SecretMaterialRequirement):
                raise SecretMaterialError(_IDENTITY_ERROR)
            if requirement.secret_class not in _MINIMUM_CLASS_LENGTHS:
                raise SecretMaterialError(_IDENTITY_ERROR)
            if requirement.reference_id in reference_ids:
                raise SecretMaterialError(_IDENTITY_ERROR)
            if requirement.identity in requirements_by_identity:
                raise SecretMaterialError(_IDENTITY_ERROR)
            reference_ids.add(requirement.reference_id)
            requirements_by_identity[requirement.identity] = requirement

        self._requirements = requirements
        self._requirements_by_identity = requirements_by_identity
        self._runtime_uid = runtime_uid
        self._active_mount_leases: dict[object, _ActiveSecretLease] = {}
        try:
            self._secret_root = Path(os.path.abspath(os.fspath(secret_root)))
        except (OSError, TypeError, ValueError):
            raise SecretMaterialError(_PATH_ERROR) from None

    def resolve(self, reference_id: str, version_id: str) -> SecretMaterialHandle:
        identity = (reference_id, version_id)
        if not all(
            isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value)
            for value in identity
        ):
            raise SecretMaterialError(_IDENTITY_ERROR)
        selected_requirement = self._requirements_by_identity.get(identity)
        if selected_requirement is None:
            raise SecretMaterialError(_IDENTITY_ERROR)

        descriptors: list[int | None] = []
        values: list[str] = []
        try:
            for requirement in self._requirements:
                descriptor, value = _open_secret_material(
                    self._secret_root,
                    requirement,
                    self._runtime_uid,
                )
                descriptors.append(descriptor)
                values.append(value)

            _verify_distinct_values(values)
            selected_index = self._requirements.index(selected_requirement)
            selected_descriptor = descriptors[selected_index]
            if selected_descriptor is None:
                raise SecretMaterialError(_PATH_ERROR)

            for index, descriptor in enumerate(descriptors):
                if index == selected_index or descriptor is None:
                    continue
                os.close(descriptor)
                descriptors[index] = None

            os.lseek(selected_descriptor, 0, os.SEEK_SET)
            handle = SecretMaterialHandle(reference_id, version_id, selected_descriptor)
            descriptors[selected_index] = None
            return handle
        except SecretMaterialError:
            _close_descriptors(descriptors)
            raise
        except OSError:
            _close_descriptors(descriptors)
            raise SecretMaterialError(_PATH_ERROR) from None
        except BaseException:
            _close_descriptors(descriptors)
            raise

    def resolve_mounts(self, attempt_id: str) -> VerifiedSecretMountLease:
        if (
            not isinstance(attempt_id, str)
            or _IDENTIFIER_PATTERN.fullmatch(attempt_id) is None
        ):
            raise SecretMaterialError(_LEASE_IDENTITY_ERROR)
        requirements = tuple(
            sorted(
                self._requirements,
                key=lambda requirement: (
                    requirement.secret_class,
                    requirement.reference_id,
                    requirement.version_id,
                ),
            )
        )
        secret_classes = tuple(requirement.secret_class for requirement in requirements)
        if len(secret_classes) != len(set(secret_classes)):
            raise SecretMaterialError(_LEASE_IDENTITY_ERROR)

        active_mounts: list[_ActiveSecretMount] = []
        values: list[str] = []
        try:
            for requirement in requirements:
                descriptor, value, source, source_identity = (
                    _open_verified_secret_material(
                        self._secret_root,
                        requirement,
                        self._runtime_uid,
                    )
                )
                active_mounts.append(
                    _ActiveSecretMount(
                        requirement=requirement,
                        source=source,
                        source_identity=source_identity,
                        descriptor=descriptor,
                    )
                )
                values.append(value)
            _verify_distinct_values(values)
            mounts = tuple(
                VerifiedSecretMount(
                    attempt_id=attempt_id,
                    provider_id=_PROVIDER_ID,
                    reference_id=active.requirement.reference_id,
                    version_id=active.requirement.version_id,
                    secret_class=active.requirement.secret_class,
                    source=active.source,
                    source_identity=active.source_identity,
                )
                for active in active_mounts
            )
            token = object()
            lease = VerifiedSecretMountLease(self, token)
            self._active_mount_leases[token] = _ActiveSecretLease(
                lease=lease,
                attempt_id=attempt_id,
                mounts=mounts,
                active_mounts=tuple(active_mounts),
            )
            active_mounts = []
            return lease
        except SecretMaterialError:
            _close_descriptors([mount.descriptor for mount in active_mounts])
            raise SecretMaterialError(_LEASE_SOURCE_CHANGED_ERROR) from None
        except (OSError, TypeError, ValueError):
            _close_descriptors([mount.descriptor for mount in active_mounts])
            raise SecretMaterialError(_LEASE_SOURCE_CHANGED_ERROR) from None
        except BaseException:
            _close_descriptors([mount.descriptor for mount in active_mounts])
            raise

    def _revalidate_mount_lease(
        self, lease: VerifiedSecretMountLease
    ) -> tuple[VerifiedSecretMount, ...]:
        record = self._require_intact_mount_lease(lease)
        active_mounts = record.active_mounts

        temporary_descriptors: list[int | None] = []
        values: list[str] = []
        try:
            for active in active_mounts:
                descriptor, value, source, source_identity = (
                    _open_verified_secret_material(
                        self._secret_root,
                        active.requirement,
                        self._runtime_uid,
                    )
                )
                temporary_descriptors.append(descriptor)
                if source != active.source or source_identity != active.source_identity:
                    raise SecretMaterialError(_LEASE_SOURCE_CHANGED_ERROR)
                retained_status = os.fstat(active.descriptor)
                if _path_identity(retained_status) != active.source_identity.value_file:
                    raise SecretMaterialError(_LEASE_SOURCE_CHANGED_ERROR)
                values.append(value)
            _verify_distinct_values(values)
        except (OSError, SecretMaterialError, TypeError, ValueError):
            _close_descriptors(temporary_descriptors)
            raise SecretMaterialError(_LEASE_SOURCE_CHANGED_ERROR) from None
        except BaseException:
            _close_descriptors(temporary_descriptors)
            raise
        _close_descriptors(temporary_descriptors)
        return record.mounts

    def _lease_mounts(
        self,
        lease: VerifiedSecretMountLease,
    ) -> tuple[VerifiedSecretMount, ...]:
        return self._require_intact_mount_lease(lease).mounts

    def _active_mount_lease(
        self,
        lease: VerifiedSecretMountLease,
    ) -> _ActiveSecretLease:
        if type(lease) is not VerifiedSecretMountLease:
            raise SecretMaterialError(_LEASE_IDENTITY_ERROR)
        try:
            provider = lease._provider
            token = lease._token
            closed = lease._closed
        except AttributeError:
            raise SecretMaterialError(_LEASE_IDENTITY_ERROR) from None
        record = self._active_mount_leases.get(token)
        if (
            provider is not self
            or closed
            or record is None
            or record.lease is not lease
        ):
            raise SecretMaterialError(_LEASE_IDENTITY_ERROR)
        return record

    def _require_intact_mount_lease(
        self,
        lease: VerifiedSecretMountLease,
    ) -> _ActiveSecretLease:
        record = self._active_mount_lease(lease)
        if (
            not record.mounts
            or len(record.mounts) != len(record.active_mounts)
            or any(
                not isinstance(mount, VerifiedSecretMount)
                or mount.attempt_id != record.attempt_id
                or mount.provider_id != _PROVIDER_ID
                or mount.reference_id != active.requirement.reference_id
                or mount.version_id != active.requirement.version_id
                or mount.secret_class != active.requirement.secret_class
                or mount.source != active.source
                or mount.source_identity != active.source_identity
                for mount, active in zip(
                    record.mounts,
                    record.active_mounts,
                    strict=True,
                )
            )
        ):
            raise SecretMaterialError(_LEASE_IDENTITY_ERROR)
        return record

    def _close_mount_lease(self, lease: VerifiedSecretMountLease) -> None:
        record = self._active_mount_lease(lease)
        _close_descriptors(
            [mount.descriptor for mount in record.active_mounts],
            expected_identities=[
                mount.source_identity.value_file for mount in record.active_mounts
            ],
        )
        del self._active_mount_leases[lease._token]
        lease._closed = True


def _open_secret_material(
    secret_root: Path,
    requirement: SecretMaterialRequirement,
    runtime_uid: int,
) -> tuple[int, str]:
    descriptor, value, _, _ = _open_verified_secret_material(
        secret_root,
        requirement,
        runtime_uid,
    )
    return descriptor, value


def _open_verified_secret_material(
    secret_root: Path,
    requirement: SecretMaterialRequirement,
    runtime_uid: int,
) -> tuple[int, str, Path, SecretSourceIdentity]:
    path = secret_root / requirement.reference_id / requirement.version_id / "value"
    before = _capture_path_state(secret_root, path, runtime_uid)
    descriptor: int | None = None
    try:
        descriptor = _open_secret_descriptor(path)
        opened_status = os.fstat(descriptor)
        _require_regular_single_link(opened_status)
        _verify_open_descriptor_permissions(opened_status, runtime_uid)
        if not _same_file_snapshot(before[-1], opened_status):
            raise SecretMaterialError(_PATH_ERROR)

        try:
            _verify_secret_permissions(path, runtime_uid)
        except (OSError, ValueError):
            raise SecretMaterialError(_PERMISSIONS_ERROR) from None

        value = _read_validated_value(
            descriptor, opened_status, requirement.secret_class
        )
        after = _capture_path_state(secret_root, path, runtime_uid)
        after_opened_status = os.fstat(descriptor)
        _verify_open_descriptor_permissions(after_opened_status, runtime_uid)
        if not all(
            _same_identity(previous, current)
            for previous, current in zip(before[:-1], after[:-1], strict=True)
        ):
            raise SecretMaterialError(_PATH_ERROR)
        if not _same_file_snapshot(before[-1], after[-1]):
            raise SecretMaterialError(_PATH_ERROR)
        if not _same_file_snapshot(opened_status, after_opened_status):
            raise SecretMaterialError(_PATH_ERROR)
        if not _same_file_snapshot(after[-1], after_opened_status):
            raise SecretMaterialError(_PATH_ERROR)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor, value, path, _source_identity(after)
    except SecretMaterialError:
        if descriptor is not None:
            _close_descriptors([descriptor])
        raise
    except OSError:
        if descriptor is not None:
            _close_descriptors([descriptor])
        raise SecretMaterialError(_PATH_ERROR) from None
    except BaseException:
        if descriptor is not None:
            _close_descriptors([descriptor])
        raise


def _capture_path_state(
    secret_root: Path,
    path: Path,
    runtime_uid: int,
) -> tuple[os.stat_result, ...]:
    reference_directory = path.parent.parent
    version_directory = path.parent
    components = (secret_root, reference_directory, version_directory, path)
    statuses: list[os.stat_result] = []
    directory_components: list[tuple[Path, os.stat_result]] = []
    try:
        for index, component in enumerate(components):
            status = os.lstat(component)
            if _is_link_or_reparse(component, status):
                raise SecretMaterialError(_PATH_ERROR)
            if index < len(components) - 1:
                if not stat.S_ISDIR(status.st_mode):
                    raise SecretMaterialError(_PATH_ERROR)
                directory_components.append((component, status))
            else:
                _require_regular_single_link(status)
            statuses.append(status)
        _verify_secret_directory_chain_permissions(
            tuple(directory_components),
            runtime_uid,
        )

        absolute_root = Path(os.path.abspath(secret_root))
        absolute_path = Path(os.path.abspath(path))
        absolute_path.relative_to(absolute_root)
        resolved_root = secret_root.resolve(strict=True)
        path.resolve(strict=True).relative_to(resolved_root)
    except SecretMaterialError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise SecretMaterialError(_PATH_ERROR) from None
    return tuple(statuses)


def _verify_secret_directory_permissions(
    path: Path,
    status: os.stat_result,
    runtime_uid: int,
) -> None:
    try:
        if (
            getattr(status, "st_uid", None) != runtime_uid
            or stat.S_IMODE(status.st_mode) & 0o022
        ):
            raise ValueError
    except (OSError, ValueError):
        raise SecretMaterialError(_PERMISSIONS_ERROR) from None


def _verify_secret_directory_chain_permissions(
    components: tuple[tuple[Path, os.stat_result], ...],
    runtime_uid: int,
) -> None:
    if not components:
        raise SecretMaterialError(_PERMISSIONS_ERROR)
    try:
        if _is_windows():
            _verify_windows_trusted_paths_permissions(
                tuple(path for path, _ in components)
            )
            return
        for path, status in components:
            _verify_secret_directory_permissions(path, status, runtime_uid)
    except (OSError, ValueError):
        raise SecretMaterialError(_PERMISSIONS_ERROR) from None


def _path_identity(status: os.stat_result) -> _SecretPathIdentity:
    return _SecretPathIdentity(
        device=getattr(status, "st_dev", None),
        inode=getattr(status, "st_ino", None),
        mode=getattr(status, "st_mode", None),
        link_count=getattr(status, "st_nlink", None),
        size=getattr(status, "st_size", None),
        modified_ns=getattr(status, "st_mtime_ns", None),
        changed_ns=getattr(status, "st_ctime_ns", None),
        owner_uid=getattr(status, "st_uid", None),
        owner_gid=getattr(status, "st_gid", None),
        file_attributes=getattr(status, "st_file_attributes", None),
    )


def _source_identity(statuses: tuple[os.stat_result, ...]) -> SecretSourceIdentity:
    if len(statuses) != 4:
        raise SecretMaterialError(_PATH_ERROR)
    identities = tuple(_path_identity(status) for status in statuses)
    return SecretSourceIdentity(
        root=identities[0],
        reference_directory=identities[1],
        version_directory=identities[2],
        value_file=identities[3],
    )


def _require_regular_single_link(status: os.stat_result) -> None:
    if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
        raise SecretMaterialError(_PATH_ERROR)


def _is_link_or_reparse(path: Path, status: os.stat_result) -> bool:
    del path
    if stat.S_ISLNK(status.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return bool(getattr(status, "st_file_attributes", 0) & reparse_flag)


def _read_only_flags() -> int:
    flags = os.O_RDONLY
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= getattr(os, flag_name, 0)
    return flags


def _open_secret_descriptor(path: Path) -> int:
    if _is_windows():
        return _open_windows_locked(path)
    return os.open(path, _read_only_flags())


def _open_windows_locked(path: Path) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    generic_read = 0x80000000
    file_share_read = 0x00000001
    open_existing = 3
    file_attribute_normal = 0x00000080
    file_flag_open_reparse_point = 0x00200000

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        str(path),
        generic_read,
        file_share_read,
        None,
        open_existing,
        file_attribute_normal | file_flag_open_reparse_point,
        None,
    )
    invalid_handle = wintypes.HANDLE(-1).value
    if handle == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    descriptor_flags = os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT
    try:
        return msvcrt.open_osfhandle(handle, descriptor_flags)
    except (OSError, ValueError):
        close_handle(handle)
        raise OSError from None
    except BaseException:
        close_handle(handle)
        raise


def _verify_open_descriptor_permissions(
    status: os.stat_result, runtime_uid: int
) -> None:
    if _is_windows():
        return
    if stat.S_IMODE(status.st_mode) != 0o600 or status.st_uid != runtime_uid:
        raise SecretMaterialError(_PERMISSIONS_ERROR)


def _read_validated_value(
    descriptor: int,
    opened_status: os.stat_result,
    secret_class: str,
) -> str:
    if opened_status.st_size > _MAXIMUM_MATERIAL_LENGTH + 2:
        raise SecretMaterialError(_CONTENT_ERROR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        content = bytearray()
        read_limit = _MAXIMUM_MATERIAL_LENGTH + 3
        while len(content) < read_limit:
            chunk = os.read(descriptor, read_limit - len(content))
            if not chunk:
                break
            content.extend(chunk)
    except OSError:
        raise SecretMaterialError(_CONTENT_ERROR) from None
    if len(content) > _MAXIMUM_MATERIAL_LENGTH + 2:
        raise SecretMaterialError(_CONTENT_ERROR)

    raw_value = bytes(content)
    if raw_value.endswith(b"\r\n"):
        raw_value = raw_value[:-2]
    elif raw_value.endswith(b"\n"):
        raw_value = raw_value[:-1]
    if (
        not raw_value
        or b"\x00" in raw_value
        or b"\n" in raw_value
        or b"\r" in raw_value
    ):
        raise SecretMaterialError(_CONTENT_ERROR)
    if len(raw_value) > _MAXIMUM_MATERIAL_LENGTH:
        raise SecretMaterialError(_CONTENT_ERROR)
    try:
        value = raw_value.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise SecretMaterialError(_CONTENT_ERROR) from None
    if any(boundary in value for boundary in _ADDITIONAL_LINE_BOUNDARIES):
        raise SecretMaterialError(_CONTENT_ERROR)
    minimum_length = _MINIMUM_CLASS_LENGTHS[secret_class]
    if not minimum_length <= len(value) <= _MAXIMUM_MATERIAL_LENGTH:
        raise SecretMaterialError(_CONTENT_ERROR)
    return value


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    return all(
        getattr(left, field, None) == getattr(right, field, None) for field in fields
    )


def _verify_distinct_values(values: list[str]) -> None:
    for index, value in enumerate(values):
        if any(value == previous for previous in values[:index]):
            raise SecretMaterialError(_DISTINCT_ERROR)


def _close_descriptors(
    descriptors: list[int | None],
    *,
    expected_identities: list[_SecretPathIdentity] | None = None,
) -> None:
    if expected_identities is not None and len(expected_identities) != len(descriptors):
        raise SecretMaterialError(_LEASE_IDENTITY_ERROR)
    first_control_error: BaseException | None = None
    first_close_error: SecretMaterialError | None = None
    for index, descriptor in enumerate(descriptors):
        if descriptor is None:
            continue
        expected_identity = (
            expected_identities[index]
            if expected_identities is not None
            else _open_descriptor_identity(descriptor)
        )
        if expected_identity is None or not _descriptor_matches_identity(
            descriptor,
            expected_identity,
        ):
            continue
        error = _close_verified_descriptor(descriptor, expected_identity)
        if error is None:
            continue
        if isinstance(error, Exception):
            if first_close_error is None:
                first_close_error = SecretMaterialError(_LEASE_CLOSE_ERROR)
        elif first_control_error is None:
            first_control_error = error
    if first_control_error is not None:
        raise first_control_error
    if first_close_error is not None:
        raise first_close_error


def _close_verified_descriptor(
    descriptor: int,
    expected_identity: _SecretPathIdentity,
) -> BaseException | None:
    first_error: BaseException
    try:
        os.close(descriptor)
        return None
    except BaseException as error:
        first_error = error
        if not _descriptor_matches_identity(descriptor, expected_identity):
            return first_error if not isinstance(first_error, Exception) else None

    try:
        os.close(descriptor)
        return first_error if not isinstance(first_error, Exception) else None
    except BaseException as retry_error:
        if not _descriptor_matches_identity(descriptor, expected_identity):
            return first_error if not isinstance(first_error, Exception) else None
        if not isinstance(first_error, Exception):
            return first_error
        if not isinstance(retry_error, Exception):
            return retry_error
        return SecretMaterialError(_LEASE_CLOSE_ERROR)


def _open_descriptor_identity(descriptor: int) -> _SecretPathIdentity | None:
    try:
        return _path_identity(os.fstat(descriptor))
    except OSError:
        return None


def _descriptor_matches_identity(
    descriptor: int,
    expected: _SecretPathIdentity,
) -> bool:
    current = _open_descriptor_identity(descriptor)
    return current is not None and (
        current.device,
        current.inode,
        stat.S_IFMT(current.mode or 0),
    ) == (
        expected.device,
        expected.inode,
        stat.S_IFMT(expected.mode or 0),
    )
