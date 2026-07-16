from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import stat
import threading
from dataclasses import dataclass
from pathlib import Path

from tools.bootstrap_runtime import (
    _is_windows,
    _verify_windows_trusted_paths_permissions,
)
from tools.committed_git import CommittedGitStore


_EXCHANGE_SENSITIVE_ALIASES = frozenset(
    {
        "key",
        "api_key",
        "apiKey",
        "secret",
        "password",
        "uid",
        "account_id",
        "accountId",
        "wallet_address",
        "walletAddress",
        "private_key",
        "privateKey",
    }
)
_CCXT_CONFIG_BAGS = ("ccxt_config", "ccxt_sync_config", "ccxt_async_config")
_CCXT_PRODUCT_KEYS = frozenset({"defaultType", "default_type"})
_ATTEMPT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}")
_STRATEGY_CLASS_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_MATERIAL_PROVIDER_ID = "committed-paper-probe-material-v1"
_MATERIAL_PATHS = (
    ("runtime_config", "ft_userdata/user_data/config.example.json"),
    ("safety_policy", "ops/config/trading-safety.json"),
    ("strategy", "ft_userdata/user_data/strategies/sample_strategy.py"),
)


@dataclass(frozen=True, slots=True)
class CommittedPaperProbeArtifacts:
    root_commit: str
    backend_commit: str
    frontend_commit: str
    strategies_commit: str
    config_sha256: str
    strategy_sha256: str
    safety_sha256: str
    strategy_class_name: str


@dataclass(frozen=True, slots=True)
class MaterialSourceIdentity:
    device: int | None
    inode: int | None
    mode: int | None
    size: int | None
    modified_ns: int | None
    changed_ns: int | None
    link_count: int | None
    owner_uid: int | None
    owner_gid: int | None
    file_attributes: int | None
    reparse_tag: int | None


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedReadOnlyMaterial:
    role: str
    attempt_id: str
    provider_id: str
    root_commit: str
    repository_relative_path: str
    source_path: Path
    blob_sha256: str
    source_identity: MaterialSourceIdentity
    strategy_class_name: str | None

    def __post_init__(self) -> None:
        if self.role == "strategy":
            if (
                not isinstance(self.strategy_class_name, str)
                or _STRATEGY_CLASS_NAME.fullmatch(self.strategy_class_name) is None
            ):
                raise ValueError("material_lease_invalid")
        elif self.strategy_class_name is not None:
            raise ValueError("material_lease_invalid")

    def __repr__(self) -> str:
        return (
            "VerifiedReadOnlyMaterial("
            f"role={self.role!r}, attempt_id={self.attempt_id!r}, "
            f"provider_id={self.provider_id!r}, root_commit={self.root_commit!r}, "
            f"repository_relative_path={self.repository_relative_path!r}, "
            f"blob_sha256={self.blob_sha256!r}, "
            f"strategy_class_name={self.strategy_class_name!r}, "
            f"source_identity={self.source_identity!r})"
        )


@dataclass(frozen=True, slots=True)
class _PathComponentIdentity:
    relative_path: str
    identity: MaterialSourceIdentity


@dataclass(slots=True)
class _OpenMaterial:
    descriptor: int
    role: str
    repository_relative_path: str
    source_path: Path
    expected_sha256: str
    strategy_class_name: str | None
    source_identity: MaterialSourceIdentity
    component_identities: tuple[_PathComponentIdentity, ...]


@dataclass(slots=True)
class _LeaseRecord:
    lease: VerifiedReadOnlyMaterialLease
    attempt_id: str
    provider_id: str
    materials: tuple[VerifiedReadOnlyMaterial, ...]
    open_materials: tuple[_OpenMaterial, ...]


class VerifiedReadOnlyMaterialLease:
    __slots__ = ("_closed", "_provider", "_token")

    def __init__(
        self,
        *,
        provider: CommittedPaperProbeMaterialProvider,
        token: object,
    ) -> None:
        self._provider = provider
        self._token = token
        self._closed = False

    @property
    def attempt_id(self) -> str:
        try:
            provider = self._provider
        except AttributeError:
            raise ValueError("material_lease_invalid") from None
        return provider._lease_attempt_id(self)

    @property
    def provider_id(self) -> str:
        try:
            provider = self._provider
        except AttributeError:
            raise ValueError("material_lease_invalid") from None
        return provider._lease_provider_id(self)

    @property
    def materials(self) -> tuple[VerifiedReadOnlyMaterial, ...]:
        try:
            provider = self._provider
        except AttributeError:
            raise ValueError("material_lease_invalid") from None
        return provider._lease_materials(self)

    def revalidate_sources(self) -> None:
        try:
            provider = self._provider
        except AttributeError:
            raise ValueError("material_lease_invalid") from None
        provider._revalidate_lease(self)

    def close(self) -> None:
        try:
            closed = self._closed
            provider = self._provider
        except AttributeError:
            raise ValueError("material_lease_invalid") from None
        if closed:
            return
        provider._close_lease(self)

    def __enter__(self) -> VerifiedReadOnlyMaterialLease:
        try:
            provider = self._provider
        except AttributeError:
            raise ValueError("material_lease_invalid") from None
        provider._lease_materials(self)
        return self

    def __exit__(self, *_exception: object) -> None:
        self.close()

    def __repr__(self) -> str:
        try:
            state = "closed" if self._closed else "open"
        except AttributeError:
            state = "invalid"
        return f"<VerifiedReadOnlyMaterialLease {state}>"


class CommittedPaperProbeMaterialProvider:
    __slots__ = (
        "_closed",
        "_expected_blobs",
        "_leases",
        "_lock",
        "_provider_id",
        "_root",
        "_store",
    )

    def __init__(self, root: Path, commit: str) -> None:
        artifacts = read_committed_paper_probe_artifacts(root, commit)
        store = CommittedGitStore(root, commit)
        expected_blobs = {
            "runtime_config": (
                store.read_runtime_config_blob(),
                artifacts.config_sha256,
                None,
            ),
            "safety_policy": (
                store.read_runtime_safety_blob(),
                artifacts.safety_sha256,
                None,
            ),
            "strategy": (
                store.read_runtime_strategy_blob(),
                artifacts.strategy_sha256,
                artifacts.strategy_class_name,
            ),
        }
        self._root = Path(root).resolve(strict=True)
        self._store = store
        self._expected_blobs = expected_blobs
        self._provider_id = _MATERIAL_PROVIDER_ID
        self._lock = threading.RLock()
        self._leases: dict[object, _LeaseRecord] = {}
        self._closed = False

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def root_commit(self) -> str:
        return self._store.root_commit

    def mint_lease(self, attempt_id: str) -> VerifiedReadOnlyMaterialLease:
        if not isinstance(attempt_id, str) or _ATTEMPT_ID.fullmatch(attempt_id) is None:
            raise ValueError("material_lease_invalid")
        with self._lock:
            if self._closed:
                raise ValueError("material_lease_invalid")
            open_materials: list[_OpenMaterial] = []
            try:
                self._store.assert_runtime_checkout_clean()
                for role, relative_path in _MATERIAL_PATHS:
                    expected_blob, expected_sha256, strategy_class_name = (
                        self._expected_blobs[role]
                    )
                    if hashlib.sha256(expected_blob).hexdigest() != expected_sha256:
                        raise ValueError("material source mismatch")
                    path, component_identities = _capture_source_path(
                        self._root,
                        relative_path,
                    )
                    descriptor = _open_nofollow_read(path)
                    try:
                        descriptor_identity = _source_identity(os.fstat(descriptor))
                        if descriptor_identity != component_identities[-1].identity:
                            raise ValueError("material source identity changed")
                        if _descriptor_sha256(descriptor) != expected_sha256:
                            raise ValueError("material source content changed")
                    except BaseException:
                        try:
                            os.close(descriptor)
                        except OSError:
                            pass
                        raise
                    open_materials.append(
                        _OpenMaterial(
                            descriptor=descriptor,
                            role=role,
                            repository_relative_path=relative_path,
                            source_path=path,
                            expected_sha256=expected_sha256,
                            strategy_class_name=strategy_class_name,
                            source_identity=descriptor_identity,
                            component_identities=component_identities,
                        )
                    )
                self._verify_open_materials(tuple(open_materials))
                self._store.assert_runtime_checkout_clean()
            except BaseException as error:
                _close_descriptors(open_materials, suppress_errors=True)
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                raise ValueError("material_source_verification_failed") from None

            token = object()
            materials = tuple(
                self._material_from_opened(attempt_id, opened)
                for opened in open_materials
            )
            lease = VerifiedReadOnlyMaterialLease(
                provider=self,
                token=token,
            )
            self._leases[token] = _LeaseRecord(
                lease=lease,
                attempt_id=attempt_id,
                provider_id=self._provider_id,
                materials=materials,
                open_materials=tuple(open_materials),
            )
            return lease

    def _revalidate_lease(
        self,
        lease: VerifiedReadOnlyMaterialLease,
    ) -> None:
        with self._lock:
            record = self._require_intact_record(lease)
            try:
                self._store.assert_runtime_checkout_clean()
                self._verify_open_materials(record.open_materials)
                self._store.assert_runtime_checkout_clean()
            except BaseException as error:
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                raise ValueError("material_source_verification_failed") from None

    def _lease_materials(
        self,
        lease: VerifiedReadOnlyMaterialLease,
    ) -> tuple[VerifiedReadOnlyMaterial, ...]:
        with self._lock:
            return self._require_intact_record(lease).materials

    def _lease_attempt_id(self, lease: VerifiedReadOnlyMaterialLease) -> str:
        with self._lock:
            return self._require_intact_record(lease).attempt_id

    def _lease_provider_id(self, lease: VerifiedReadOnlyMaterialLease) -> str:
        with self._lock:
            return self._require_intact_record(lease).provider_id

    def _material_from_opened(
        self,
        attempt_id: str,
        opened: _OpenMaterial,
    ) -> VerifiedReadOnlyMaterial:
        return VerifiedReadOnlyMaterial(
            role=opened.role,
            attempt_id=attempt_id,
            provider_id=self._provider_id,
            root_commit=self._store.root_commit,
            repository_relative_path=opened.repository_relative_path,
            source_path=opened.source_path,
            blob_sha256=opened.expected_sha256,
            source_identity=opened.source_identity,
            strategy_class_name=opened.strategy_class_name,
        )

    def _verify_open_materials(
        self,
        open_materials: tuple[_OpenMaterial, ...],
    ) -> None:
        for opened in open_materials:
            path, identities = _capture_source_path(
                self._root,
                opened.repository_relative_path,
            )
            if path != opened.source_path:
                raise ValueError("material source path changed")
            if identities != opened.component_identities:
                raise ValueError("material source ancestry changed")
            if _source_identity(os.fstat(opened.descriptor)) != opened.source_identity:
                raise ValueError("material descriptor identity changed")
            if _descriptor_sha256(opened.descriptor) != opened.expected_sha256:
                raise ValueError("material descriptor content changed")
            _, identities_after_read = _capture_source_path(
                self._root,
                opened.repository_relative_path,
            )
            if identities_after_read != opened.component_identities:
                raise ValueError("material source changed during verification")
            if _source_identity(os.fstat(opened.descriptor)) != opened.source_identity:
                raise ValueError("material descriptor changed during verification")

    def _active_record(
        self,
        lease: VerifiedReadOnlyMaterialLease,
    ) -> _LeaseRecord:
        if self._closed or type(lease) is not VerifiedReadOnlyMaterialLease:
            raise ValueError("material_lease_invalid")
        try:
            closed = lease._closed
            provider = lease._provider
            token = lease._token
        except AttributeError:
            raise ValueError("material_lease_invalid") from None
        if closed or provider is not self:
            raise ValueError("material_lease_invalid")
        record = self._leases.get(token)
        if record is None or record.lease is not lease:
            raise ValueError("material_lease_invalid")
        return record

    def _require_intact_record(
        self,
        lease: VerifiedReadOnlyMaterialLease,
    ) -> _LeaseRecord:
        record = self._active_record(lease)
        expected_materials = tuple(
            self._material_from_opened(record.attempt_id, opened)
            for opened in record.open_materials
        )
        if (
            record.provider_id != self._provider_id
            or not record.open_materials
            or len(record.materials) != len(record.open_materials)
            or any(
                type(material) is not VerifiedReadOnlyMaterial
                for material in record.materials
            )
            or record.materials != expected_materials
        ):
            raise ValueError("material_lease_invalid")
        return record

    def _close_lease(self, lease: VerifiedReadOnlyMaterialLease) -> None:
        with self._lock:
            record = self._active_record(lease)
            try:
                _close_descriptors(record.open_materials)
            except OSError:
                raise ValueError("material_source_verification_failed") from None
            del self._leases[lease._token]
            lease._closed = True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            records = tuple(self._leases.values())
            _close_descriptors(
                tuple(opened for record in records for opened in record.open_materials),
                suppress_errors=True,
            )
            self._closed = True
            self._leases.clear()
            for record in records:
                record.lease._closed = True

    def __enter__(self) -> CommittedPaperProbeMaterialProvider:
        if self._closed:
            raise ValueError("material_lease_invalid")
        return self

    def __exit__(self, *_exception: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            "CommittedPaperProbeMaterialProvider("
            f"provider_id={self._provider_id!r}, root_commit={self._store.root_commit!r}, "
            f"closed={self._closed!r})"
        )


class _DuplicateJsonKey(ValueError):
    pass


class _NonFiniteJsonNumber(ValueError):
    pass


def _close_descriptors(
    open_materials: list[_OpenMaterial] | tuple[_OpenMaterial, ...],
    *,
    suppress_errors: bool = False,
) -> None:
    first_error: BaseException | None = None
    for opened in open_materials:
        if not _descriptor_matches_material(opened):
            continue
        try:
            os.close(opened.descriptor)
        except BaseException as error:
            if first_error is None and (
                not suppress_errors or not isinstance(error, OSError)
            ):
                first_error = error
            if not isinstance(error, OSError) and _descriptor_matches_material(opened):
                try:
                    os.close(opened.descriptor)
                except BaseException as retry_error:
                    if first_error is None and (
                        not suppress_errors or not isinstance(retry_error, OSError)
                    ):
                        first_error = retry_error
    if first_error is not None:
        raise first_error


def _descriptor_matches_material(opened: _OpenMaterial) -> bool:
    try:
        current = _source_identity(os.fstat(opened.descriptor))
    except OSError:
        return False
    return (
        current.device,
        current.inode,
        stat.S_IFMT(current.mode or 0),
    ) == (
        opened.source_identity.device,
        opened.source_identity.inode,
        stat.S_IFMT(opened.source_identity.mode or 0),
    )


def _source_identity(metadata: os.stat_result) -> MaterialSourceIdentity:
    return MaterialSourceIdentity(
        device=getattr(metadata, "st_dev", None),
        inode=getattr(metadata, "st_ino", None),
        mode=getattr(metadata, "st_mode", None),
        size=getattr(metadata, "st_size", None),
        modified_ns=getattr(metadata, "st_mtime_ns", None),
        changed_ns=getattr(metadata, "st_ctime_ns", None),
        link_count=getattr(metadata, "st_nlink", None),
        owner_uid=getattr(metadata, "st_uid", None),
        owner_gid=getattr(metadata, "st_gid", None),
        file_attributes=getattr(metadata, "st_file_attributes", None),
        reparse_tag=getattr(metadata, "st_reparse_tag", None),
    )


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def _verify_material_source_permissions(
    path: Path,
    metadata: os.stat_result,
) -> None:
    if (
        getattr(metadata, "st_uid", None) != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise ValueError("material source permissions are invalid")


def _verify_material_source_chain_permissions(
    components: tuple[tuple[Path, os.stat_result], ...],
) -> None:
    if not components:
        raise ValueError("material source permissions are invalid")
    if _is_windows():
        _verify_windows_trusted_paths_permissions(tuple(path for path, _ in components))
        return
    for path, metadata in components:
        _verify_material_source_permissions(path, metadata)


def _capture_source_path(
    root: Path,
    relative_path: str,
) -> tuple[Path, tuple[_PathComponentIdentity, ...]]:
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or relative_path.startswith("/")
        or "\\" in relative_path
    ):
        raise ValueError("material path is invalid")
    parts = relative_path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("material path is invalid")

    root_status = os.lstat(root)
    if _is_link_or_reparse(root_status) or not stat.S_ISDIR(root_status.st_mode):
        raise ValueError("material root is invalid")
    permission_components = [(root, root_status)]
    identities = [
        _PathComponentIdentity(
            relative_path=".",
            identity=_source_identity(root_status),
        )
    ]
    current = root
    for index, part in enumerate(parts):
        current = current / part
        status = os.lstat(current)
        if _is_link_or_reparse(status):
            raise ValueError("material source link is invalid")
        leaf = index == len(parts) - 1
        if leaf:
            if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
                raise ValueError("material source must be a single-link regular file")
        elif not stat.S_ISDIR(status.st_mode):
            raise ValueError("material source ancestor must be a directory")
        permission_components.append((current, status))
        identities.append(
            _PathComponentIdentity(
                relative_path="/".join(parts[: index + 1]),
                identity=_source_identity(status),
            )
        )
    _verify_material_source_chain_permissions(tuple(permission_components))
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("material source escapes root") from None
    if resolved != current:
        raise ValueError("material source path is not exact")
    return resolved, tuple(identities)


def _open_nofollow_read(path: Path) -> int:
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(path),
            0x80000000,
            0x00000001,
            None,
            3,
            0x00000080 | 0x00200000,
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "material source open failed")
        try:
            descriptor = msvcrt.open_osfhandle(
                int(handle),
                os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT,
            )
        except BaseException:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)
            raise
        try:
            os.set_inheritable(descriptor, False)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("nofollow file open is unavailable")
    descriptor = os.open(
        path,
        os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.set_inheritable(descriptor, False)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _descriptor_sha256(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_nonfinite_number(_value: str) -> None:
    raise _NonFiniteJsonNumber


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _NonFiniteJsonNumber
    return parsed


def _strict_json(document: bytes, identity: str) -> object:
    try:
        text = document.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{identity} JSON must be UTF-8") from None
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_number,
            parse_float=_parse_finite_float,
        )
    except _DuplicateJsonKey:
        raise ValueError(f"{identity} JSON contains a duplicate key") from None
    except _NonFiniteJsonNumber:
        raise ValueError(f"{identity} JSON contains a non-finite number") from None
    except json.JSONDecodeError:
        raise ValueError(f"{identity} JSON is invalid") from None


def _validate_config(document: bytes) -> None:
    payload = _strict_json(document, "config")
    if not isinstance(payload, dict):
        raise ValueError("config root must be a JSON object")
    if payload.get("dry_run") is not True:
        raise ValueError("config dry_run must be exact boolean true")
    if payload.get("trading_mode") != "spot":
        raise ValueError("config trading_mode must be spot")
    exchange = payload.get("exchange")
    if not isinstance(exchange, dict) or exchange.get("name") != "bitget":
        raise ValueError("config exchange must be bitget")
    if any(
        exchange[field] not in (None, "")
        for field in _EXCHANGE_SENSITIVE_ALIASES
        if field in exchange
    ):
        raise ValueError("exchange write credential must be empty")
    for field in _CCXT_CONFIG_BAGS:
        if field not in exchange:
            continue
        bag = exchange[field]
        if not isinstance(bag, dict):
            raise ValueError("CCXT configuration bag must be a JSON object")
        _validate_ccxt_node(bag)


def _validate_ccxt_node(value: object) -> None:
    if isinstance(value, list):
        for item in value:
            _validate_ccxt_node(item)
        return
    if not isinstance(value, dict):
        return
    for field, nested in value.items():
        if field in _EXCHANGE_SENSITIVE_ALIASES and nested not in (None, ""):
            raise ValueError("exchange write credential must be empty")
        if field in _CCXT_PRODUCT_KEYS and nested != "spot":
            raise ValueError("CCXT product override must remain spot")
        if field == "fetchMarkets":
            if not isinstance(nested, dict):
                raise ValueError("CCXT product override must remain spot")
            if "types" in nested and nested["types"] != ["spot"]:
                raise ValueError("CCXT product override must remain spot")
        _validate_ccxt_node(nested)


def _validate_safety(document: bytes) -> None:
    payload = _strict_json(document, "safety")
    if not isinstance(payload, dict):
        raise ValueError("safety root must be a JSON object")
    if payload.get("dry_run") is not True:
        raise ValueError("safety dry_run must be exact boolean true")


def _strategy_class_name(document: bytes) -> str:
    try:
        source = document.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("strategy source must be UTF-8") from None
    try:
        module = ast.parse(source, filename="<committed-strategy>")
    except (SyntaxError, ValueError):
        raise ValueError("strategy syntax is invalid") from None
    classes = [node for node in ast.walk(module) if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        raise ValueError("strategy must declare exactly one SampleStrategy class")
    if classes[0].name != "SampleStrategy" or classes[0] not in module.body:
        raise ValueError("strategy class must be the top-level SampleStrategy")
    return "SampleStrategy"


def read_committed_paper_probe_artifacts(
    root: Path,
    commit: str,
) -> CommittedPaperProbeArtifacts:
    store = CommittedGitStore(root, commit)
    store.assert_runtime_checkout_clean()
    config = store.read_runtime_config_blob()
    strategy = store.read_runtime_strategy_blob()
    safety = store.read_runtime_safety_blob()

    _validate_config(config)
    strategy_class_name = _strategy_class_name(strategy)
    _validate_safety(safety)

    return CommittedPaperProbeArtifacts(
        root_commit=store.root_commit,
        backend_commit=store.backend_commit,
        frontend_commit=store.frontend_commit,
        strategies_commit=store.strategies_commit,
        config_sha256=hashlib.sha256(config).hexdigest(),
        strategy_sha256=hashlib.sha256(strategy).hexdigest(),
        safety_sha256=hashlib.sha256(safety).hexdigest(),
        strategy_class_name=strategy_class_name,
    )
