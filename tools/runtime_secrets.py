from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tools.bootstrap_runtime import _verify_secret_permissions


DEFAULT_SECRET_ROOT = Path("ft_userdata/secrets/runtime")

_IDENTIFIER_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_MINIMUM_CLASS_LENGTHS: Final = {
    "api_password": 32,
    "jwt_secret": 48,
    "ws_token": 32,
}
_MAXIMUM_MATERIAL_LENGTH: Final = 4096

_IDENTITY_ERROR: Final = "secret identity is invalid"
_PATH_ERROR: Final = "secret path is not a regular file"
_PERMISSIONS_ERROR: Final = "secret permissions are invalid"
_CONTENT_ERROR: Final = "secret content is invalid"
_DISTINCT_ERROR: Final = "required secret values must be distinct"
_CLOSED_ERROR: Final = "secret material handle is closed"


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
        self._closed = True
        self._descriptor = -1
        try:
            os.close(descriptor)
        except OSError:
            raise SecretMaterialError(_CLOSED_ERROR) from None

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
    __slots__ = ("_requirements", "_requirements_by_identity", "_runtime_uid", "_secret_root")

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
        self._secret_root = Path(secret_root)

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


def _open_secret_material(
    secret_root: Path,
    requirement: SecretMaterialRequirement,
    runtime_uid: int,
) -> tuple[int, str]:
    path = secret_root / requirement.reference_id / requirement.version_id / "value"
    before = _capture_path_state(secret_root, path)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, _read_only_flags())
        opened_status = os.fstat(descriptor)
        _require_regular_single_link(opened_status)
        if not _same_file_snapshot(before[-1], opened_status):
            raise SecretMaterialError(_PATH_ERROR)

        try:
            _verify_secret_permissions(path, runtime_uid)
        except (OSError, ValueError):
            raise SecretMaterialError(_PERMISSIONS_ERROR) from None

        value = _read_validated_value(descriptor, opened_status, requirement.secret_class)
        after = _capture_path_state(secret_root, path)
        after_opened_status = os.fstat(descriptor)
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
        return descriptor, value
    except SecretMaterialError:
        if descriptor is not None:
            _close_descriptors([descriptor])
        raise
    except OSError:
        if descriptor is not None:
            _close_descriptors([descriptor])
        raise SecretMaterialError(_PATH_ERROR) from None


def _capture_path_state(secret_root: Path, path: Path) -> tuple[os.stat_result, ...]:
    reference_directory = path.parent.parent
    version_directory = path.parent
    components = (secret_root, reference_directory, version_directory, path)
    statuses: list[os.stat_result] = []
    try:
        for index, component in enumerate(components):
            status = os.lstat(component)
            if _is_link_or_reparse(component, status):
                raise SecretMaterialError(_PATH_ERROR)
            if index < len(components) - 1:
                if not stat.S_ISDIR(status.st_mode):
                    raise SecretMaterialError(_PATH_ERROR)
            else:
                _require_regular_single_link(status)
            statuses.append(status)

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
    if not raw_value or b"\x00" in raw_value or b"\n" in raw_value or b"\r" in raw_value:
        raise SecretMaterialError(_CONTENT_ERROR)
    if len(raw_value) > _MAXIMUM_MATERIAL_LENGTH:
        raise SecretMaterialError(_CONTENT_ERROR)
    try:
        value = raw_value.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise SecretMaterialError(_CONTENT_ERROR) from None
    minimum_length = _MINIMUM_CLASS_LENGTHS[secret_class]
    if not minimum_length <= len(value) <= _MAXIMUM_MATERIAL_LENGTH:
        raise SecretMaterialError(_CONTENT_ERROR)
    return value


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    return all(getattr(left, field, None) == getattr(right, field, None) for field in fields)


def _verify_distinct_values(values: list[str]) -> None:
    for index, value in enumerate(values):
        if any(value == previous for previous in values[:index]):
            raise SecretMaterialError(_DISTINCT_ERROR)


def _close_descriptors(descriptors: list[int | None]) -> None:
    for descriptor in descriptors:
        if descriptor is None:
            continue
        try:
            os.close(descriptor)
        except OSError:
            pass
