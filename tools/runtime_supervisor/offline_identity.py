from __future__ import annotations

import ctypes
import errno
import json
import os
import re
import secrets
import stat
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Protocol

from tools.runtime_driver import DriverIdentity


_SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT_ID = re.compile(r"[0-9a-f]{40}")
_MAX_IDENTITY_BYTES = 16 * 1024
_MAX_ENGINE_DOCUMENT_BYTES = 256 * 1024
_MAX_LOG_BYTES = 256 * 1024
_MAX_LOG_LINES = 500
_READ_TIMEOUT_SECONDS = 15
_LOG_TIMEOUT_SECONDS = 30
_STOP_TIMEOUT_SECONDS = 60
_STOP_GRACE_SECONDS = 30
_IMAGE_LABEL_PREFIX = "org.freqtrade-cn.revision."
_IDENTITY_LABELS = {
    "attempt_id": "io.freqtrade.runtime.attempt-id",
    "container_name": "io.freqtrade.runtime.container-name",
    "image_id": "io.freqtrade.runtime.image-id",
    "instance_id": "io.freqtrade.runtime.instance-id",
    "launch_authority_digest": "io.freqtrade.runtime.launch-authority-digest",
    "project_name": "io.freqtrade.runtime.project-name",
    "runtime_spec_digest": "io.freqtrade.runtime.runtime-spec-digest",
    "state_allocation_id": "io.freqtrade.runtime.state-allocation-id",
}


class _FixedOfflineError(RuntimeError):
    code = "offline_identity_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class OfflineIdentityValidationError(_FixedOfflineError):
    code = "offline_identity_validation_error"


class OfflineIdentityStorageError(_FixedOfflineError):
    code = "offline_identity_storage_error"


class OfflineIdentityMismatch(_FixedOfflineError):
    code = "offline_identity_mismatch"


class OfflineEmergencyPolicyError(_FixedOfflineError):
    code = "offline_emergency_policy_error"


class OfflineEmergencyTransportError(_FixedOfflineError):
    code = "offline_emergency_transport_error"


class OfflineEmergencyAmbiguousOutcome(_FixedOfflineError):
    code = "offline_emergency_ambiguous_outcome"


def _require_identifier(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise OfflineIdentityValidationError()
    return value


def _require_match(value: object, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise OfflineIdentityValidationError()
    return value


@dataclass(frozen=True, slots=True)
class OfflineRuntimeIdentity:
    schema_version: int
    instance_revision: int
    lease_generation: int
    instance_id: str
    attempt_id: str
    container_id: str
    project_name: str
    container_name: str
    compose_service: str
    image_id: str
    runtime_spec_digest: str
    launch_authority_digest: str
    state_allocation_id: str
    network_names: tuple[str, ...]
    root_commit: str
    backend_commit: str
    frontend_commit: str
    strategies_commit: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != _SCHEMA_VERSION:
            raise OfflineIdentityValidationError()
        if (
            type(self.instance_revision) is not int
            or self.instance_revision < 0
            or type(self.lease_generation) is not int
            or self.lease_generation < 1
        ):
            raise OfflineIdentityValidationError()
        for value in (
            self.instance_id,
            self.attempt_id,
            self.project_name,
            self.container_name,
            self.state_allocation_id,
        ):
            _require_identifier(value)
        if self.attempt_id == "current":
            raise OfflineIdentityValidationError()
        if self.compose_service != "runtime":
            raise OfflineIdentityValidationError()
        _require_match(self.container_id, _CONTAINER_ID)
        _require_match(self.image_id, _IMAGE_ID)
        _require_match(self.runtime_spec_digest, _DIGEST)
        _require_match(self.launch_authority_digest, _DIGEST)
        for value in (
            self.root_commit,
            self.backend_commit,
            self.frontend_commit,
            self.strategies_commit,
        ):
            _require_match(value, _COMMIT_ID)
        if (
            type(self.network_names) is not tuple
            or not self.network_names
            or any(
                type(name) is not str or _IDENTIFIER.fullmatch(name) is None
                for name in self.network_names
            )
            or self.network_names != tuple(sorted(set(self.network_names)))
        ):
            raise OfflineIdentityValidationError()

    @classmethod
    def from_driver_identity(
        cls,
        driver_identity: DriverIdentity,
        *,
        container_id: str,
        instance_revision: int,
        lease_generation: int,
        launch_authority_digest: str,
        root_commit: str,
        backend_commit: str,
        frontend_commit: str,
        strategies_commit: str,
    ) -> OfflineRuntimeIdentity:
        if type(driver_identity) is not DriverIdentity:
            raise OfflineIdentityValidationError()
        try:
            driver_identity.__post_init__()
        except Exception:
            raise OfflineIdentityValidationError() from None
        return cls(
            schema_version=_SCHEMA_VERSION,
            instance_revision=instance_revision,
            lease_generation=lease_generation,
            instance_id=driver_identity.instance_id,
            attempt_id=driver_identity.attempt_id,
            container_id=container_id,
            project_name=driver_identity.project_name,
            container_name=driver_identity.container_name,
            compose_service="runtime",
            image_id=driver_identity.image_id,
            runtime_spec_digest=driver_identity.runtime_spec_digest,
            launch_authority_digest=launch_authority_digest,
            state_allocation_id=driver_identity.state_allocation_id,
            network_names=driver_identity.network_names,
            root_commit=root_commit,
            backend_commit=backend_commit,
            frontend_commit=frontend_commit,
            strategies_commit=strategies_commit,
        )

    @classmethod
    def from_canonical_bytes(cls, payload: bytes) -> OfflineRuntimeIdentity:
        if type(payload) is not bytes or not 0 < len(payload) <= _MAX_IDENTITY_BYTES:
            raise OfflineIdentityValidationError()
        try:
            text = payload.decode("utf-8")
            document = json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
            if type(document) is not dict:
                raise ValueError
            expected_keys = {
                "schema_version",
                "instance_revision",
                "lease_generation",
                "instance_id",
                "attempt_id",
                "container_id",
                "project_name",
                "container_name",
                "compose_service",
                "image_id",
                "runtime_spec_digest",
                "launch_authority_digest",
                "state_allocation_id",
                "network_names",
                "root_commit",
                "backend_commit",
                "frontend_commit",
                "strategies_commit",
            }
            if set(document) != expected_keys or type(document["network_names"]) is not list:
                raise ValueError
            value = cls(
                schema_version=document["schema_version"],
                instance_revision=document["instance_revision"],
                lease_generation=document["lease_generation"],
                instance_id=document["instance_id"],
                attempt_id=document["attempt_id"],
                container_id=document["container_id"],
                project_name=document["project_name"],
                container_name=document["container_name"],
                compose_service=document["compose_service"],
                image_id=document["image_id"],
                runtime_spec_digest=document["runtime_spec_digest"],
                launch_authority_digest=document["launch_authority_digest"],
                state_allocation_id=document["state_allocation_id"],
                network_names=tuple(document["network_names"]),
                root_commit=document["root_commit"],
                backend_commit=document["backend_commit"],
                frontend_commit=document["frontend_commit"],
                strategies_commit=document["strategies_commit"],
            )
        except (
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise OfflineIdentityValidationError() from None
        if value.to_canonical_bytes() != payload:
            raise OfflineIdentityValidationError()
        return value

    def to_canonical_bytes(self) -> bytes:
        try:
            self.__post_init__()
        except Exception:
            raise OfflineIdentityValidationError() from None
        document = {
            "schema_version": self.schema_version,
            "instance_revision": self.instance_revision,
            "lease_generation": self.lease_generation,
            "instance_id": self.instance_id,
            "attempt_id": self.attempt_id,
            "container_id": self.container_id,
            "project_name": self.project_name,
            "container_name": self.container_name,
            "compose_service": self.compose_service,
            "image_id": self.image_id,
            "runtime_spec_digest": self.runtime_spec_digest,
            "launch_authority_digest": self.launch_authority_digest,
            "state_allocation_id": self.state_allocation_id,
            "network_names": list(self.network_names),
            "root_commit": self.root_commit,
            "backend_commit": self.backend_commit,
            "frontend_commit": self.frontend_commit,
            "strategies_commit": self.strategies_commit,
        }
        return (
            json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n"
        ).encode("ascii")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for name, value in pairs:
        if type(name) is not str or name in document:
            raise ValueError
        document[name] = value
    return document


def _reject_json_constant(_value: str) -> None:
    raise ValueError


class OfflineIdentityStore:
    def __init__(self, root: Path) -> None:
        if (
            not isinstance(root, Path)
            or not root.is_absolute()
            or ".." in root.parts
        ):
            raise OfflineIdentityStorageError()
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def publish(self, identity: OfflineRuntimeIdentity) -> OfflineRuntimeIdentity:
        if type(identity) is not OfflineRuntimeIdentity:
            raise OfflineIdentityValidationError()
        payload = identity.to_canonical_bytes()
        try:
            root_status = _verify_secure_directory(self._root)
            instance_root = self._root / identity.instance_id
            _ensure_secure_instance_directory(instance_root)
            _require_same_path(root_status, _verify_secure_directory(self._root))
            with _instance_publish_lock(instance_root):
                attempts_root = instance_root / "attempts"
                _ensure_secure_instance_directory(attempts_root)
                attempt_path = attempts_root / f"{identity.attempt_id}.json"
                current_path = instance_root / "current.json"
                current_payload = _read_optional_secure_file(current_path)
                if current_payload is not None:
                    current = OfflineRuntimeIdentity.from_canonical_bytes(
                        current_payload
                    )
                    if current.instance_id != identity.instance_id:
                        raise OSError
                    current_version = (
                        current.instance_revision,
                        current.lease_generation,
                    )
                    incoming_version = (
                        identity.instance_revision,
                        identity.lease_generation,
                    )
                    if incoming_version < current_version or (
                        incoming_version == current_version
                        and current_payload != payload
                    ):
                        raise OSError

                _publish_immutable_file(attempt_path, payload)
                if _read_secure_file(attempt_path) != payload:
                    raise OSError
                if current_payload != payload:
                    _replace_projection(current_path, payload)
                if _read_secure_file(current_path) != payload:
                    raise OSError
            _require_same_path(root_status, _verify_secure_directory(self._root))
        except OfflineIdentityValidationError:
            raise
        except (OSError, RuntimeError, ValueError):
            raise OfflineIdentityStorageError() from None
        return identity

    def load_current(self, instance_id: str) -> OfflineRuntimeIdentity:
        _require_identifier(instance_id)
        return self._load(self._root / instance_id / "current.json", instance_id, None)

    def load_attempt(self, instance_id: str, attempt_id: str) -> OfflineRuntimeIdentity:
        _require_identifier(instance_id)
        _require_identifier(attempt_id)
        return self._load(
            self._root / instance_id / "attempts" / f"{attempt_id}.json",
            instance_id,
            attempt_id,
        )

    def _load(
        self,
        path: Path,
        instance_id: str,
        attempt_id: str | None,
    ) -> OfflineRuntimeIdentity:
        try:
            root_status = _verify_secure_directory(self._root)
            _verify_secure_directory(path.parent)
            payload = _read_secure_file(path)
            value = OfflineRuntimeIdentity.from_canonical_bytes(payload)
            if value.instance_id != instance_id or (
                attempt_id is not None and value.attempt_id != attempt_id
            ):
                raise OfflineIdentityValidationError()
            _require_same_path(root_status, _verify_secure_directory(self._root))
            return value
        except OfflineIdentityValidationError:
            raise
        except (OSError, RuntimeError, ValueError):
            raise OfflineIdentityStorageError() from None


def _verify_secure_directory(path: Path) -> os.stat_result:
    _verify_no_link_or_reparse_ancestry(path)
    status = os.lstat(path)
    if _is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
        raise OSError
    _verify_security(path, status)
    after = os.lstat(path)
    if not _same_path_snapshot(status, after):
        raise OSError
    return after


def _verify_no_link_or_reparse_ancestry(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise OSError
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        status = os.lstat(current)
        if _is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
            raise OSError


def _ensure_secure_instance_directory(path: Path) -> None:
    parent_status = _verify_secure_directory(path.parent)
    try:
        if os.name == "posix":
            os.mkdir(path, 0o700)
        else:
            os.mkdir(path)
        if os.name == "posix":
            os.chmod(path, 0o700)
        _sync_directory(path.parent)
    except FileExistsError:
        pass
    _verify_secure_directory(path)
    _require_same_path(parent_status, _verify_secure_directory(path.parent))


def _read_optional_secure_file(path: Path) -> bytes | None:
    try:
        return _read_secure_file(path)
    except FileNotFoundError:
        return None


@contextmanager
def _instance_publish_lock(instance_root: Path) -> Iterator[None]:
    _verify_secure_directory(instance_root)
    path = instance_root / ".publish.lock"
    descriptor: int | None = None
    created = False
    flags = os.O_RDWR
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    try:
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            _sync_directory(instance_root)
        except FileExistsError:
            descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        named = _verify_secure_regular_file(path)
        if not _same_path_snapshot(opened, named):
            raise OSError
        with _exclusive_file_lock(descriptor):
            locked = os.fstat(descriptor)
            named_locked = _verify_secure_regular_file(path)
            if not _same_path_snapshot(locked, named_locked):
                raise OSError
            yield
            if not _same_path_snapshot(
                os.fstat(descriptor),
                _verify_secure_regular_file(path),
            ):
                raise OSError
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            _verify_secure_regular_file(path)


@contextmanager
def _exclusive_file_lock(descriptor: int) -> Iterator[None]:
    if os.name == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        return
    if os.name == "nt":
        overlapped = _lock_windows_file(descriptor)
        try:
            yield
        finally:
            _unlock_windows_file(descriptor, overlapped)
        return
    raise OSError(errno.ENOTSUP, "file locking is unsupported")


def _lock_windows_file(descriptor: int) -> ctypes.Structure:
    import msvcrt
    from ctypes import wintypes

    class Overlapped(ctypes.Structure):
        _fields_ = (
            ("internal", ctypes.c_size_t),
            ("internal_high", ctypes.c_size_t),
            ("offset", wintypes.DWORD),
            ("offset_high", wintypes.DWORD),
            ("event", wintypes.HANDLE),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    lock = kernel32.LockFileEx
    lock.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(Overlapped),
    )
    lock.restype = wintypes.BOOL
    overlapped = Overlapped()
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
    if not lock(
        handle,
        0x00000002,
        0,
        0xFFFFFFFF,
        0xFFFFFFFF,
        ctypes.byref(overlapped),
    ):
        raise OSError(ctypes.get_last_error(), "file lock failed")
    return overlapped


def _unlock_windows_file(descriptor: int, overlapped: ctypes.Structure) -> None:
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    unlock = kernel32.UnlockFileEx
    unlock.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    unlock.restype = wintypes.BOOL
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
    if not unlock(handle, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(overlapped)):
        raise OSError(ctypes.get_last_error(), "file unlock failed")


def _publish_immutable_file(path: Path, payload: bytes) -> None:
    _verify_secure_directory(path.parent)
    try:
        existing = _read_secure_file(path)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if existing != payload:
            raise OSError
        return

    temporary = _write_temporary_file(path.parent, payload)
    try:
        try:
            _rename_no_replace(temporary, path)
        except FileExistsError:
            if _read_secure_file(path) != payload:
                raise OSError
        _sync_directory(path.parent)
    finally:
        _remove_temporary_if_owned(temporary)


def _replace_projection(path: Path, payload: bytes) -> None:
    _verify_secure_directory(path.parent)
    try:
        _verify_secure_regular_file(path)
    except FileNotFoundError:
        pass
    temporary = _write_temporary_file(path.parent, payload)
    try:
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        _remove_temporary_if_owned(temporary)


def _write_temporary_file(parent: Path, payload: bytes) -> Path:
    temporary = parent / f".offline-{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
            flags |= getattr(os, name, 0)
        descriptor = os.open(temporary, flags, 0o600)
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError
            offset += written
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise OSError
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        _remove_temporary_if_owned(temporary)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _verify_secure_regular_file(temporary)
    return temporary


def _read_secure_file(path: Path) -> bytes:
    before = _verify_secure_regular_file(path)
    if before.st_size <= 0 or before.st_size > _MAX_IDENTITY_BYTES:
        raise OSError
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not _same_path_snapshot(before, opened):
            raise OSError
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 4096))
            if not chunk:
                raise OSError
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise OSError
        after = os.fstat(descriptor)
        if not _same_path_snapshot(opened, after):
            raise OSError
    finally:
        os.close(descriptor)
    named_after = _verify_secure_regular_file(path)
    if not _same_path_snapshot(after, named_after):
        raise OSError
    return b"".join(chunks)


def _verify_secure_regular_file(path: Path) -> os.stat_result:
    status = os.lstat(path)
    if (
        _is_link_or_reparse(status)
        or not stat.S_ISREG(status.st_mode)
        or status.st_nlink != 1
    ):
        raise OSError
    _verify_security(path, status)
    after = os.lstat(path)
    if not _same_path_snapshot(status, after):
        raise OSError
    return after


def _remove_temporary_if_owned(path: Path) -> None:
    try:
        status = os.lstat(path)
        if (
            path.name.startswith(".offline-")
            and path.name.endswith(".tmp")
            and not _is_link_or_reparse(status)
            and stat.S_ISREG(status.st_mode)
            and status.st_nlink == 1
        ):
            os.unlink(path)
    except FileNotFoundError:
        pass


def _rename_no_replace(source: Path, destination: Path) -> None:
    if os.name == "nt":
        os.rename(source, destination)
        return
    if os.name != "posix":
        raise OSError(errno.ENOTSUP, "atomic no-replace publish is unsupported")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError):
        raise OSError(errno.ENOTSUP, "atomic no-replace publish is unsupported") from None
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _sync_directory(path: Path) -> None:
    before = _verify_secure_directory(path)
    if os.name == "nt":
        _flush_windows_directory(path)
    elif os.name == "posix":
        flags = os.O_RDONLY
        for name in ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW"):
            value = getattr(os, name, None)
            if value is None:
                raise OSError(errno.ENOTSUP, "directory sync is unsupported")
            flags |= value
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not _same_path_snapshot(before, opened):
                raise OSError
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    else:
        raise OSError(errno.ENOTSUP, "directory sync is unsupported")
    _require_same_path(before, _verify_secure_directory(path))


def _flush_windows_directory(path: Path) -> None:
    from ctypes import wintypes

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
    flush = kernel32.FlushFileBuffers
    flush.argtypes = (wintypes.HANDLE,)
    flush.restype = wintypes.BOOL
    close = kernel32.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    handle = create_file(
        str(path),
        0x40000000,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise OSError(ctypes.get_last_error(), "directory open failed")
    try:
        if not flush(handle):
            raise OSError(ctypes.get_last_error(), "directory flush failed")
    finally:
        close(handle)


def _verify_security(path: Path, status: os.stat_result) -> None:
    if os.name == "posix":
        effective_uid = os.geteuid()
        if status.st_uid != effective_uid or stat.S_IMODE(status.st_mode) & 0o022:
            raise OSError
        return
    if os.name == "nt":
        _verify_windows_security(path)
        return
    raise OSError(errno.ENOTSUP, "filesystem security verification is unsupported")


def _verify_windows_security(path: Path) -> None:
    from ctypes import wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = (("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD))

    class TokenUser(ctypes.Structure):
        _fields_ = (("user", SidAndAttributes),)

    class AclSizeInformation(ctypes.Structure):
        _fields_ = (
            ("ace_count", wintypes.DWORD),
            ("acl_bytes_in_use", wintypes.DWORD),
            ("acl_bytes_free", wintypes.DWORD),
        )

    class AceHeader(ctypes.Structure):
        _fields_ = (
            ("ace_type", ctypes.c_ubyte),
            ("ace_flags", ctypes.c_ubyte),
            ("ace_size", ctypes.c_ushort),
        )

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_int,
    )
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.CreateWellKnownSid.argtypes = (
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.CreateWellKnownSid.restype = wintypes.BOOL
    advapi32.IsValidSid.argtypes = (ctypes.c_void_p,)
    advapi32.IsValidSid.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = (ctypes.c_void_p,)
    advapi32.GetLengthSid.restype = wintypes.DWORD
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi32.GetNamedSecurityInfoW(
        str(path),
        1,
        0x00000001 | 0x00000004,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result != 0 or not owner.value or not dacl.value or not descriptor.value:
        raise OSError(result, "security descriptor query failed")
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(),
            0x0008,
            ctypes.byref(token),
        ):
            raise OSError(ctypes.get_last_error(), "process token query failed")
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if required.value == 0:
            raise OSError(ctypes.get_last_error(), "token user query failed")
        token_buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            1,
            token_buffer,
            required,
            ctypes.byref(required),
        ):
            raise OSError(ctypes.get_last_error(), "token user query failed")
        current_sid = ctypes.cast(token_buffer, ctypes.POINTER(TokenUser)).contents.user.sid
        trusted_owner_buffers = tuple(
            _well_known_sid(advapi32, sid_type) for sid_type in (22, 26)
        )
        trusted_owner_sids = (
            current_sid,
            *(ctypes.cast(buffer, ctypes.c_void_p) for buffer in trusted_owner_buffers),
        )
        trusted_sid_values = frozenset(
            _windows_sid_bytes(advapi32, sid) for sid in trusted_owner_sids
        )
        if _windows_sid_bytes(advapi32, owner) not in trusted_sid_values:
            raise OSError

        information = AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(information),
            ctypes.sizeof(information),
            2,
        ):
            raise OSError(ctypes.get_last_error(), "ACL query failed")
        dangerous = (
            0x10000000
            | 0x40000000
            | 0x00010000
            | 0x00040000
            | 0x00080000
            | 0x00000002
            | 0x00000004
            | 0x00000010
            | 0x00000040
            | 0x00000100
        )
        allow_ace_types = frozenset({0x00, 0x05, 0x09, 0x0B})
        known_non_allow_ace_types = frozenset(
            {
                0x01,
                0x02,
                0x03,
                0x06,
                0x07,
                0x08,
                0x0A,
                0x0C,
                0x0D,
                0x0E,
                0x0F,
                0x10,
                0x11,
                0x12,
                0x13,
                0x14,
                0x15,
            }
        )
        for index in range(information.ace_count):
            ace_pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
                raise OSError(ctypes.get_last_error(), "ACE query failed")
            if not ace_pointer.value:
                raise OSError
            header = ctypes.cast(ace_pointer, ctypes.POINTER(AceHeader)).contents
            if header.ace_type in known_non_allow_ace_types:
                continue
            if header.ace_type not in allow_ace_types or header.ace_size < 12:
                raise OSError
            mask = wintypes.DWORD.from_address(ace_pointer.value + 4).value
            sid_offset = 8
            if header.ace_type in {0x05, 0x0B}:
                object_flags = wintypes.DWORD.from_address(
                    ace_pointer.value + 8
                ).value
                if object_flags & ~0x00000003:
                    raise OSError
                sid_offset = 12
                if object_flags & 0x00000001:
                    sid_offset += 16
                if object_flags & 0x00000002:
                    sid_offset += 16
            if sid_offset + 8 > header.ace_size:
                raise OSError
            sid = ctypes.c_void_p(ace_pointer.value + sid_offset)
            sid_value = _windows_sid_bytes(advapi32, sid)
            sid_length = len(sid_value)
            if sid_length == 0 or sid_offset + sid_length > header.ace_size:
                raise OSError
            if mask & dangerous and sid_value not in trusted_sid_values:
                raise OSError
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.LocalFree(descriptor)


def _well_known_sid(advapi32: object, sid_type: int) -> ctypes.Array[ctypes.c_char]:
    from ctypes import wintypes

    size = wintypes.DWORD(68)
    buffer = ctypes.create_string_buffer(size.value)
    if not advapi32.CreateWellKnownSid(
        sid_type,
        None,
        buffer,
        ctypes.byref(size),
    ):
        raise OSError(ctypes.get_last_error(), "well-known SID query failed")
    return buffer


def _windows_sid_bytes(advapi32: object, sid: object) -> bytes:
    if not advapi32.IsValidSid(sid):
        raise OSError
    length = advapi32.GetLengthSid(sid)
    if length == 0 or length > 68:
        raise OSError
    return ctypes.string_at(sid, length)


def _is_link_or_reparse(status: os.stat_result) -> bool:
    if stat.S_ISLNK(status.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return bool(getattr(status, "st_file_attributes", 0) & reparse_flag)


def _same_path_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_file_attributes",
        "st_reparse_tag",
    )
    return all(
        getattr(left, field, None) == getattr(right, field, None) for field in fields
    )


def _require_same_path(left: os.stat_result, right: os.stat_result) -> None:
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_file_attributes",
        "st_reparse_tag",
    )
    if not all(
        getattr(left, field, None) == getattr(right, field, None)
        for field in fields
    ):
        raise OSError


class EmergencyRuntimeState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    EXITED = "exited"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EmergencyRuntimeStatus:
    instance_id: str
    attempt_id: str
    state: EmergencyRuntimeState
    health: str
    networks_match: bool


@dataclass(frozen=True, slots=True)
class EmergencyRuntimeInspection:
    instance_id: str
    attempt_id: str
    container_id: str
    project_name: str
    container_name: str
    image_id: str
    runtime_spec_digest: str
    state_allocation_id: str
    state: EmergencyRuntimeState
    health: str
    exit_code: int | None
    observed_network_names: tuple[str, ...]
    networks_match: bool


@dataclass(frozen=True, slots=True)
class _EngineObservation:
    state: EmergencyRuntimeState
    health: str
    exit_code: int | None
    observed_network_names: tuple[str, ...]


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


class BinaryProcess(Protocol):
    stdout: BinaryIO | None
    stderr: BinaryIO | None
    returncode: int | None

    def wait(self, timeout: int | None = None) -> int: ...

    def kill(self) -> None: ...


ProcessSpawner = Callable[..., BinaryProcess]


class _BoundedProcessOutput:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._stdout = bytearray()
        self._total = 0
        self.exceeded = False
        self.failed = False

    def append(self, data: bytes, *, is_stdout: bool) -> bool:
        if type(data) is not bytes:
            self.fail()
            return True
        with self._lock:
            remaining = self._limit - self._total
            accepted = min(len(data), max(remaining, 0))
            if is_stdout and accepted:
                self._stdout.extend(data[:accepted])
            self._total += accepted
            if accepted != len(data):
                self.exceeded = True
            return self.exceeded

    def fail(self) -> None:
        with self._lock:
            self.failed = True

    def stdout(self) -> bytes:
        with self._lock:
            return bytes(self._stdout)


class OfflineEmergencyController:
    def __init__(
        self,
        store: OfflineIdentityStore,
        *,
        docker_executable: Path,
        working_directory: Path,
        process_runner: ProcessRunner = subprocess.run,
        process_spawner: ProcessSpawner = subprocess.Popen,
    ) -> None:
        if (
            type(store) is not OfflineIdentityStore
            or not isinstance(docker_executable, Path)
            or not docker_executable.is_absolute()
            or ".." in docker_executable.parts
            or not isinstance(working_directory, Path)
            or not working_directory.is_absolute()
            or ".." in working_directory.parts
            or not callable(process_runner)
            or not callable(process_spawner)
        ):
            raise OfflineEmergencyPolicyError()
        self._store = store
        self._docker_executable = docker_executable
        self._working_directory = working_directory
        self._process_runner = process_runner
        self._process_spawner = process_spawner
        self._environment = _minimal_local_environment()

    def status(self, instance_id: str) -> EmergencyRuntimeStatus:
        identity = self._store.load_current(instance_id)
        observed = self._inspect_exact(identity)
        return EmergencyRuntimeStatus(
            instance_id=identity.instance_id,
            attempt_id=identity.attempt_id,
            state=observed.state,
            health=observed.health,
            networks_match=observed.observed_network_names == identity.network_names,
        )

    def inspect(self, instance_id: str) -> EmergencyRuntimeInspection:
        identity = self._store.load_current(instance_id)
        observed = self._inspect_exact(identity)
        return _public_inspection(identity, observed)

    def logs(self, instance_id: str, *, tail: int = 100) -> str:
        if type(tail) is not int or not 1 <= tail <= _MAX_LOG_LINES:
            raise OfflineEmergencyPolicyError()
        identity = self._store.load_current(instance_id)
        self._inspect_exact(identity)
        return self._run_bounded_logs(
            (
                str(self._docker_executable),
                "container",
                "logs",
                "--tail",
                str(tail),
                identity.container_id,
            ),
            timeout=_LOG_TIMEOUT_SECONDS,
        )

    def stop_exact(self, instance_id: str) -> EmergencyRuntimeInspection:
        identity = self._store.load_current(instance_id)
        observed = self._inspect_exact(identity)
        if observed.state is EmergencyRuntimeState.EXITED:
            return _public_inspection(identity, observed)
        self._inspect_exact(identity)
        try:
            completed = self._process_runner(
                [
                    str(self._docker_executable),
                    "container",
                    "stop",
                    "--time",
                    str(_STOP_GRACE_SECONDS),
                    identity.container_id,
                ],
                cwd=self._working_directory,
                env=self._environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=_STOP_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise OfflineEmergencyAmbiguousOutcome() from None
        if completed.returncode != 0:
            raise OfflineEmergencyAmbiguousOutcome()
        try:
            terminal = self._inspect_exact(identity)
        except (
            OfflineEmergencyTransportError,
            OfflineIdentityMismatch,
            OfflineIdentityValidationError,
            OfflineIdentityStorageError,
        ):
            raise OfflineEmergencyAmbiguousOutcome() from None
        if terminal.state is not EmergencyRuntimeState.EXITED:
            raise OfflineEmergencyAmbiguousOutcome()
        return _public_inspection(identity, terminal)

    def _inspect_exact(self, identity: OfflineRuntimeIdentity) -> _EngineObservation:
        container = self._run_read_only(
            (
                str(self._docker_executable),
                "container",
                "inspect",
                identity.container_id,
            ),
            timeout=_READ_TIMEOUT_SECONDS,
        )
        image = self._run_read_only(
            (
                str(self._docker_executable),
                "image",
                "inspect",
                identity.image_id,
            ),
            timeout=_READ_TIMEOUT_SECONDS,
        )
        container_document = _single_engine_document(container.stdout)
        image_document = _single_engine_document(image.stdout)
        return _validate_engine_identity(identity, container_document, image_document)

    def _run_read_only(
        self,
        command: tuple[str, ...],
        *,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = self._process_runner(
                list(command),
                cwd=self._working_directory,
                env=self._environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise OfflineEmergencyTransportError() from None
        if completed.returncode != 0:
            raise OfflineEmergencyTransportError()
        return completed

    def _run_bounded_logs(
        self,
        command: tuple[str, ...],
        *,
        timeout: int,
    ) -> str:
        try:
            process = self._process_spawner(
                list(command),
                cwd=self._working_directory,
                env=self._environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
            )
        except OSError:
            raise OfflineEmergencyTransportError() from None
        if process.stdout is None or process.stderr is None:
            _kill_and_wait(process)
            _close_process_pipes(process)
            raise OfflineEmergencyTransportError()

        output = _BoundedProcessOutput(_MAX_LOG_BYTES)
        readers = (
            threading.Thread(
                target=_read_bounded_pipe,
                args=(process, process.stdout, output, True),
                daemon=True,
            ),
            threading.Thread(
                target=_read_bounded_pipe,
                args=(process, process.stderr, output, False),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        try:
            return_code = process.wait(timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            _kill_and_wait(process)
            for reader in readers:
                reader.join(timeout=1)
            _close_process_pipes(process)
            raise OfflineEmergencyTransportError() from None
        for reader in readers:
            reader.join(timeout=1)
        if any(reader.is_alive() for reader in readers):
            _kill_and_wait(process)
            for reader in readers:
                reader.join(timeout=1)
            _close_process_pipes(process)
            raise OfflineEmergencyTransportError()
        _close_process_pipes(process)
        if output.exceeded or output.failed:
            _kill_and_wait(process)
            raise OfflineEmergencyTransportError()
        if type(return_code) is not int or return_code != 0:
            raise OfflineEmergencyTransportError()
        return output.stdout().decode("utf-8", errors="replace")


def _read_bounded_pipe(
    process: BinaryProcess,
    pipe: BinaryIO,
    output: _BoundedProcessOutput,
    is_stdout: bool,
) -> None:
    try:
        while True:
            chunk = pipe.read(8192)
            if not chunk:
                return
            if output.append(chunk, is_stdout=is_stdout):
                try:
                    process.kill()
                except OSError:
                    output.fail()
                return
    except (OSError, TypeError, ValueError):
        output.fail()
        try:
            process.kill()
        except OSError:
            pass


def _kill_and_wait(process: BinaryProcess) -> None:
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _close_process_pipes(process: BinaryProcess) -> None:
    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except OSError:
                pass


def _minimal_local_environment() -> dict[str, str]:
    if os.name != "nt":
        return {}
    system_root = os.environ.get("SYSTEMROOT")
    if type(system_root) is not str or not system_root:
        raise OfflineEmergencyPolicyError()
    return {"SYSTEMROOT": system_root}


def _single_engine_document(payload: str) -> dict:
    if type(payload) is not str or len(payload.encode("utf-8")) > _MAX_ENGINE_DOCUMENT_BYTES:
        raise OfflineEmergencyTransportError()
    try:
        document = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise OfflineEmergencyTransportError() from None
    if type(document) is not list or len(document) != 1 or type(document[0]) is not dict:
        raise OfflineEmergencyTransportError()
    return document[0]


def _validate_engine_identity(
    identity: OfflineRuntimeIdentity,
    container: dict,
    image: dict,
) -> _EngineObservation:
    config = container.get("Config")
    state = container.get("State")
    network_settings = container.get("NetworkSettings")
    labels = config.get("Labels") if type(config) is dict else None
    networks = network_settings.get("Networks") if type(network_settings) is dict else None
    if (
        type(labels) is not dict
        or any(type(name) is not str or type(value) is not str for name, value in labels.items())
        or type(state) is not dict
        or type(networks) is not dict
        or any(type(name) is not str or _IDENTIFIER.fullmatch(name) is None for name in networks)
    ):
        raise OfflineEmergencyTransportError()
    expected_labels = {
        "com.docker.compose.project": identity.project_name,
        "com.docker.compose.service": identity.compose_service,
        _IDENTITY_LABELS["attempt_id"]: identity.attempt_id,
        _IDENTITY_LABELS["container_name"]: identity.container_name,
        _IDENTITY_LABELS["image_id"]: identity.image_id,
        _IDENTITY_LABELS["instance_id"]: identity.instance_id,
        _IDENTITY_LABELS["launch_authority_digest"]: identity.launch_authority_digest,
        _IDENTITY_LABELS["project_name"]: identity.project_name,
        _IDENTITY_LABELS["runtime_spec_digest"]: identity.runtime_spec_digest,
        _IDENTITY_LABELS["state_allocation_id"]: identity.state_allocation_id,
    }
    if (
        container.get("Id") != identity.container_id
        or container.get("Name") != f"/{identity.container_name}"
        or container.get("Image") != identity.image_id
        or any(labels.get(name) != value for name, value in expected_labels.items())
    ):
        raise OfflineIdentityMismatch()

    image_config = image.get("Config")
    image_labels = image_config.get("Labels") if type(image_config) is dict else None
    expected_image_labels = {
        f"{_IMAGE_LABEL_PREFIX}root": identity.root_commit,
        f"{_IMAGE_LABEL_PREFIX}backend": identity.backend_commit,
        f"{_IMAGE_LABEL_PREFIX}frontend": identity.frontend_commit,
    }
    if (
        image.get("Id") != identity.image_id
        or type(image_labels) is not dict
        or {
            name: value
            for name, value in image_labels.items()
            if type(name) is str and name.startswith(_IMAGE_LABEL_PREFIX)
        }
        != expected_image_labels
    ):
        raise OfflineIdentityMismatch()

    raw_state = state.get("Status")
    runtime_state = {
        "created": EmergencyRuntimeState.CREATED,
        "running": EmergencyRuntimeState.RUNNING,
        "exited": EmergencyRuntimeState.EXITED,
    }.get(raw_state, EmergencyRuntimeState.UNKNOWN)
    raw_health = state.get("Health")
    health = raw_health.get("Status") if type(raw_health) is dict else "not_configured"
    if health not in {"not_configured", "starting", "healthy", "unhealthy"}:
        health = "unknown"
    exit_code = state.get("ExitCode") if runtime_state is EmergencyRuntimeState.EXITED else None
    if exit_code is not None and type(exit_code) is not int:
        raise OfflineEmergencyTransportError()
    return _EngineObservation(
        state=runtime_state,
        health=health,
        exit_code=exit_code,
        observed_network_names=tuple(sorted(networks)),
    )


def _public_inspection(
    identity: OfflineRuntimeIdentity,
    observed: _EngineObservation,
) -> EmergencyRuntimeInspection:
    return EmergencyRuntimeInspection(
        instance_id=identity.instance_id,
        attempt_id=identity.attempt_id,
        container_id=identity.container_id,
        project_name=identity.project_name,
        container_name=identity.container_name,
        image_id=identity.image_id,
        runtime_spec_digest=identity.runtime_spec_digest,
        state_allocation_id=identity.state_allocation_id,
        state=observed.state,
        health=observed.health,
        exit_code=observed.exit_code,
        observed_network_names=observed.observed_network_names,
        networks_match=observed.observed_network_names == identity.network_names,
    )
