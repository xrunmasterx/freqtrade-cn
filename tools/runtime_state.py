from __future__ import annotations

import errno
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from tools.bootstrap_runtime import (
    _harden_managed_state_directory,
    _harden_managed_state_identity_file,
    _is_windows,
    _verify_managed_state_directory,
    _verify_managed_state_identity_file,
)


DEFAULT_STATE_ROOT = Path("ft_userdata/runtime/instances")

DurabilityLevel = Literal["atomic-process-crash", "power-loss-posix"]

_IDENTIFIER_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_PROVIDER_ID: Final = "managed-local-v1"
_LAYOUT_ID: Final = "freqtrade-state-v1"
_LAYOUT_DIRECTORIES: Final = ("home", "logs", "data")

_RESERVATION_ERROR: Final = "state_reservation_invalid"
_ROOT_ERROR: Final = "state_root_invalid"
_EXISTS_ERROR: Final = "state_allocation_exists"
_PROVISION_ERROR: Final = "state_provision_failed"
_QUARANTINE_ERROR: Final = "state_quarantine_failed"


class StateProvisionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StateAllocationReservation:
    state_allocation_id: str
    instance_id: str
    layout_id: str
    provider_id: str
    relative_path: str
    kind: str
    status: str
    generation: int
    restore_source_bundle_id: str | None


@dataclass(frozen=True, slots=True)
class ProvisionedState:
    state_allocation_id: str
    instance_id: str
    layout_id: str
    provider_id: str
    generation: int
    relative_path: str
    durability: DurabilityLevel


class ManagedStateProvider:
    __slots__ = ("_reservation", "_runtime_uid", "_state_root")

    def __init__(
        self,
        reservation: StateAllocationReservation,
        *,
        runtime_uid: int,
        state_root: Path = DEFAULT_STATE_ROOT,
    ) -> None:
        self._reservation = reservation
        self._runtime_uid = runtime_uid
        try:
            self._state_root = Path(os.path.abspath(os.fspath(state_root)))
        except (OSError, TypeError, ValueError):
            raise StateProvisionError(_ROOT_ERROR) from None

    def provision(
        self,
        instance_id: str,
        allocation_id: str,
        layout_id: str,
    ) -> ProvisionedState:
        reservation = self._reservation
        if not _reservation_is_valid(
            reservation,
            self._runtime_uid,
            instance_id,
            allocation_id,
            layout_id,
        ):
            raise StateProvisionError(_RESERVATION_ERROR)

        root_status = _validate_root(self._state_root, self._runtime_uid)
        allocation = self._state_root / instance_id
        quarantine = self._state_root / f".{allocation_id}.quarantine"
        if os.path.lexists(allocation) or os.path.lexists(quarantine):
            raise StateProvisionError(_EXISTS_ERROR)
        try:
            os.mkdir(allocation, 0o700)
        except FileExistsError:
            raise StateProvisionError(_EXISTS_ERROR) from None
        except OSError:
            raise StateProvisionError(_PROVISION_ERROR) from None

        allocation_status: os.stat_result | None = None
        try:
            allocation_status = os.lstat(allocation)
            _require_directory(allocation_status)
            _harden_managed_state_directory(allocation, self._runtime_uid)
            allocation_status = _validated_directory_status(
                allocation,
                self._runtime_uid,
            )
            _require_root_identity(self._state_root, root_status, self._runtime_uid)
            component_statuses = _create_layout(
                allocation,
                allocation_id,
                self._runtime_uid,
            )
            _validate_final_layout(
                self._state_root,
                root_status,
                allocation,
                allocation_status,
                allocation_id,
                component_statuses,
                self._runtime_uid,
            )
            root_barrier_status = _validated_directory_status(
                self._state_root,
                self._runtime_uid,
            )
            if not _same_identity(root_status, root_barrier_status):
                raise OSError
            _sync_directory(self._state_root, root_barrier_status)
            _require_root_identity(self._state_root, root_status, self._runtime_uid)
            final_allocation_status = _validated_directory_status(
                allocation,
                self._runtime_uid,
            )
            if not _same_identity(allocation_status, final_allocation_status):
                raise OSError
        except Exception:
            if _quarantine_owned_allocation(
                self._state_root,
                root_status,
                allocation,
                allocation_status,
                allocation_id,
                instance_id,
                self._runtime_uid,
            ):
                raise StateProvisionError(_PROVISION_ERROR) from None
            raise StateProvisionError(_QUARANTINE_ERROR) from None

        return ProvisionedState(
            state_allocation_id=allocation_id,
            instance_id=instance_id,
            layout_id=layout_id,
            provider_id=reservation.provider_id,
            generation=reservation.generation,
            relative_path=reservation.relative_path,
            durability=(
                "atomic-process-crash" if _is_windows() else "power-loss-posix"
            ),
        )


def _reservation_is_valid(
    reservation: object,
    runtime_uid: object,
    instance_id: object,
    allocation_id: object,
    layout_id: object,
) -> bool:
    if not isinstance(reservation, StateAllocationReservation):
        return False
    identifiers = (
        reservation.state_allocation_id,
        reservation.instance_id,
        reservation.layout_id,
        reservation.provider_id,
        instance_id,
        allocation_id,
        layout_id,
    )
    if not all(
        isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value)
        for value in identifiers
    ):
        return False
    expected_relative_path = f"ft_userdata/runtime/instances/{reservation.instance_id}"
    return (
        reservation.state_allocation_id == allocation_id
        and reservation.instance_id == instance_id
        and reservation.layout_id == layout_id == _LAYOUT_ID
        and reservation.provider_id == _PROVIDER_ID
        and reservation.relative_path == expected_relative_path
        and reservation.kind == "fresh"
        and reservation.status == "reserved"
        and type(reservation.generation) is int
        and reservation.generation >= 1
        and reservation.restore_source_bundle_id is None
        and type(runtime_uid) is int
        and runtime_uid >= 0
    )


def _validate_root(state_root: Path, runtime_uid: int) -> os.stat_result:
    try:
        before = _capture_directory_ancestry(state_root)
        _verify_managed_state_directory(state_root, runtime_uid)
        after = _capture_directory_ancestry(state_root)
        if len(before) != len(after) or any(
            not _same_identity(previous, current)
            for previous, current in zip(before, after, strict=True)
        ):
            raise OSError
        state_root.resolve(strict=True)
        return after[-1]
    except (OSError, RuntimeError, ValueError):
        raise StateProvisionError(_ROOT_ERROR) from None


def _require_root_identity(
    state_root: Path,
    expected: os.stat_result,
    runtime_uid: int,
) -> None:
    before = _capture_directory_ancestry(state_root)
    _verify_managed_state_directory(state_root, runtime_uid)
    after = _capture_directory_ancestry(state_root)
    if (
        len(before) != len(after)
        or any(
            not _same_identity(previous, current)
            for previous, current in zip(before, after, strict=True)
        )
        or not _same_identity(expected, after[-1])
    ):
        raise OSError


def _capture_directory_ancestry(path: Path) -> tuple[os.stat_result, ...]:
    statuses: list[os.stat_result] = []
    for component in (*reversed(path.parents), path):
        status = os.lstat(component)
        _require_directory(status)
        statuses.append(status)
    return tuple(statuses)


def _create_layout(
    allocation: Path,
    allocation_id: str,
    runtime_uid: int,
) -> dict[str, os.stat_result]:
    statuses: dict[str, os.stat_result] = {}
    for name in _LAYOUT_DIRECTORIES:
        path = allocation / name
        os.mkdir(path, 0o700)
        _harden_managed_state_directory(path, runtime_uid)
        statuses[name] = _validated_directory_status(path, runtime_uid)
        _sync_directory(path, statuses[name])

    identity_name = f".allocation-{allocation_id}"
    identity = allocation / identity_name
    temporary = allocation / f".{identity_name}.{secrets.token_hex(8)}.tmp"
    descriptor: int | None = None
    synced_status: os.stat_result | None = None
    try:
        descriptor = os.open(temporary, _exclusive_write_flags(), 0o600)
        _harden_managed_state_identity_file(temporary, runtime_uid)
        opened = os.fstat(descriptor)
        _require_empty_identity_file(opened)
        _verify_managed_state_identity_file(temporary, runtime_uid)
        named = os.lstat(temporary)
        _require_empty_identity_file(named)
        if not _same_snapshot(opened, named):
            raise OSError
        _sync_descriptor(descriptor)
        after = os.fstat(descriptor)
        _require_empty_identity_file(after)
        if not _same_snapshot(opened, after):
            raise OSError
        synced_status = after
    finally:
        if descriptor is not None:
            os.close(descriptor)

    _publish_no_replace(temporary, identity)
    identity_status = os.lstat(identity)
    _require_empty_identity_file(identity_status)
    if synced_status is None or not _same_snapshot(synced_status, identity_status):
        raise OSError
    _verify_managed_state_identity_file(identity, runtime_uid)
    statuses[identity_name] = identity_status
    allocation_barrier_status = _validated_directory_status(allocation, runtime_uid)
    _sync_directory(allocation, allocation_barrier_status)
    return statuses


def _validate_final_layout(
    state_root: Path,
    root_status: os.stat_result,
    allocation: Path,
    allocation_status: os.stat_result,
    allocation_id: str,
    component_statuses: dict[str, os.stat_result],
    runtime_uid: int,
) -> None:
    _require_root_identity(state_root, root_status, runtime_uid)
    if os.path.lexists(state_root / f".{allocation_id}.quarantine"):
        raise OSError
    current_allocation = _validated_directory_status(allocation, runtime_uid)
    if not _same_identity(allocation_status, current_allocation):
        raise OSError
    try:
        allocation.resolve(strict=True).relative_to(state_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        raise OSError from None

    identity_name = f".allocation-{allocation_id}"
    expected_names = {*_LAYOUT_DIRECTORIES, identity_name}
    with os.scandir(allocation) as entries:
        if {entry.name for entry in entries} != expected_names:
            raise OSError

    for name in _LAYOUT_DIRECTORIES:
        status = _validated_directory_status(allocation / name, runtime_uid)
        if not _same_identity(component_statuses[name], status):
            raise OSError

    identity = allocation / identity_name
    status = os.lstat(identity)
    _require_empty_identity_file(status)
    if not _same_identity(component_statuses[identity_name], status):
        raise OSError
    _verify_managed_state_identity_file(identity, runtime_uid)
    descriptor: int | None = None
    try:
        descriptor = os.open(identity, _read_only_flags())
        opened = os.fstat(descriptor)
        _require_empty_identity_file(opened)
        if not _same_snapshot(status, opened) or os.read(descriptor, 1) != b"":
            raise OSError
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _quarantine_owned_allocation(
    state_root: Path,
    root_status: os.stat_result,
    allocation: Path,
    allocation_status: os.stat_result | None,
    allocation_id: str,
    instance_id: str,
    runtime_uid: int,
) -> bool:
    if allocation_status is None:
        return False
    try:
        _require_root_identity(state_root, root_status, runtime_uid)
        current = os.lstat(allocation)
        _require_directory(current)
        if not _same_identity(allocation_status, current):
            return False

        container = state_root / f".{allocation_id}.quarantine"
        destination = container / instance_id
        os.mkdir(container, 0o700)
        _harden_managed_state_directory(container, runtime_uid)
        _validated_directory_status(container, runtime_uid)
        current = os.lstat(allocation)
        _require_directory(current)
        if not _same_identity(allocation_status, current):
            return False
        _publish_no_replace(allocation, destination)
        moved = os.lstat(destination)
        _require_directory(moved)
        if not _same_identity(allocation_status, moved) or os.path.lexists(allocation):
            return False
        container_barrier_status = _validated_directory_status(container, runtime_uid)
        _sync_directory(container, container_barrier_status)
        root_barrier_status = _validated_directory_status(state_root, runtime_uid)
        if not _same_identity(root_status, root_barrier_status):
            return False
        _sync_directory(state_root, root_barrier_status)
        _require_root_identity(state_root, root_status, runtime_uid)
        moved_after = os.lstat(destination)
        _require_directory(moved_after)
        if not _same_identity(allocation_status, moved_after):
            return False
        return True
    except Exception:
        return False


def _validated_directory_status(path: Path, runtime_uid: int) -> os.stat_result:
    status = os.lstat(path)
    _require_directory(status)
    _verify_managed_state_directory(path, runtime_uid)
    after = os.lstat(path)
    _require_directory(after)
    if not _same_snapshot(status, after):
        raise OSError
    return after


def _require_directory(status: os.stat_result) -> None:
    if _is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
        raise OSError


def _require_empty_identity_file(status: os.stat_result) -> None:
    if (
        _is_link_or_reparse(status)
        or not stat.S_ISREG(status.st_mode)
        or status.st_nlink != 1
        or status.st_size != 0
    ):
        raise OSError


def _is_link_or_reparse(status: os.stat_result) -> bool:
    if stat.S_ISLNK(status.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return bool(getattr(status, "st_file_attributes", 0) & reparse_flag)


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size")
    return all(getattr(left, field, None) == getattr(right, field, None) for field in fields)


def _exclusive_write_flags() -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    return flags


def _read_only_flags() -> int:
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    return flags


def _publish_no_replace(source: Path, destination: Path) -> None:
    if _is_windows():
        os.rename(source, destination)
        return
    if os.name != "posix":
        raise OSError(errno.ENOTSUP, "atomic no-replace publish is unsupported")

    import ctypes

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
    at_fdcwd = -100
    rename_noreplace = 1
    result = renameat2(
        at_fdcwd,
        os.fsencode(source),
        at_fdcwd,
        os.fsencode(destination),
        rename_noreplace,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _sync_descriptor(descriptor: int) -> None:
    os.fsync(descriptor)


def _sync_directory(path: Path, expected: os.stat_result) -> None:
    named_before = os.lstat(path)
    _require_directory(named_before)
    if not _same_identity(expected, named_before):
        raise OSError
    if _is_windows():
        named_after = os.lstat(path)
        _require_directory(named_after)
        if not _same_snapshot(named_before, named_after):
            raise OSError
        return
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory is None:
        raise OSError(errno.ENOTSUP, "directory sync proof is unsupported")
    flags = os.O_RDONLY | no_follow | directory | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        opened_before = os.fstat(descriptor)
        _require_directory(opened_before)
        if not _same_snapshot(named_before, opened_before):
            raise OSError
        os.fsync(descriptor)
        opened_after = os.fstat(descriptor)
        _require_directory(opened_after)
        if not _same_snapshot(opened_before, opened_after):
            raise OSError
        named_after = os.lstat(path)
        _require_directory(named_after)
        if not _same_snapshot(opened_after, named_after):
            raise OSError
    finally:
        os.close(descriptor)
