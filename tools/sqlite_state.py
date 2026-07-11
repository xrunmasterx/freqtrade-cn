from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import errno
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import shutil
import sqlite3
import stat
import sys
import tempfile
from typing import Iterator, Literal

if __package__:
    from tools.runtime_manifest import REPO_ROOT, load_runtime_manifest
else:
    from runtime_manifest import REPO_ROOT, load_runtime_manifest


BundlePurpose = Literal["service-state", "archive"]
CreationPlatform = Literal["posix", "windows"]
DurabilityLevel = Literal["unknown", "atomic-process-crash", "power-loss-posix"]

CORE_TABLES = ("trades", "orders")
COUNT_TABLES = ("trades", "orders", "pairlocks", "KeyValueStore")
SCHEMA1_FIELDS = {
    "schema_version",
    "service",
    "created_at_utc",
    "sqlite_version",
    "source_filename",
    "database_sha256",
    "database_size",
    "user_version",
    "tables",
    "row_counts",
    "integrity_check",
    "foreign_key_violations",
}
SCHEMA2_FIELDS = SCHEMA1_FIELDS | {
    "purpose",
    "archive_label",
    "creation_platform",
    "durability",
}
IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
UTC_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
COMPLETION_FILENAME = "durability-complete.json"
COMPLETION_FIELDS = {
    "schema_version",
    "durability",
    "manifest_sha256",
    "creation_platform",
    "transaction_nonce",
    "bundle_name",
}
FAILURE_FILENAME = "creation-failed.json"
FAILURE_FIELDS = {
    "schema_version",
    "state",
    "manifest_sha256",
    "creation_platform",
    "bundle_name",
}
RECEIPT_FIELDS = {
    "schema_version",
    "state",
    "transaction_nonce",
    "bundle_name",
    "manifest_sha256",
    "creation_platform",
}
TRANSACTION_NONCE_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
FINAL_BUNDLE_PATTERN = re.compile(
    r"\d{8}T\d{6}Z-[A-Za-z0-9][A-Za-z0-9._-]*\Z"
)
QUARANTINE_BUNDLE_PATTERN = re.compile(
    r"\.(?P<bundle>\d{8}T\d{6}Z-[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"\.quarantine-[0-9a-f]{16}\Z"
)
MAX_RECEIPT_BYTES = 4096


class StateBundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceLane:
    service: str
    legacy_source: Path
    destination: Path


@dataclass(frozen=True)
class VerifiedBundle:
    schema_version: int
    purpose: BundlePurpose
    service: str | None
    archive_label: str | None
    source_filename: str
    creation_platform: CreationPlatform | None
    durability: DurabilityLevel
    database_sha256: str
    database_size: int
    metadata: dict[str, object]


@dataclass(frozen=True)
class _PathIdentity:
    resolved: Path
    device: int
    inode: int


def open_read_only(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def online_backup(source_path: Path, target_path: Path) -> None:
    with closing(open_read_only(source_path)) as source:
        with closing(sqlite3.connect(target_path)) as target:
            source.backup(target)
            target.commit()


def inspect_database(path: Path) -> dict[str, object]:
    with closing(open_read_only(path)) as connection:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        tables = sorted(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        if integrity != ["ok"] or foreign_keys or set(CORE_TABLES) - set(tables):
            raise StateBundleError("SQLite integrity or core-table policy failed")
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in COUNT_TABLES
            if table in tables
        }
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    return {
        "user_version": user_version,
        "tables": tables,
        "row_counts": counts,
        "integrity_check": "ok",
        "foreign_key_violations": 0,
    }


def _is_exact_int(value: object) -> bool:
    return type(value) is int


def _is_portable_basename(value: object) -> bool:
    if type(value) is not str or not value or value in {".", ".."}:
        return False
    if "/" in value or "\\" in value or ":" in value or "\0" in value:
        return False
    windows_path = PureWindowsPath(value)
    return not windows_path.drive and not windows_path.root


def _validate_common_manifest(manifest: dict[str, object]) -> None:
    if (
        type(manifest["created_at_utc"]) is not str
        or not UTC_TIMESTAMP_PATTERN.fullmatch(manifest["created_at_utc"])
        or type(manifest["sqlite_version"]) is not str
        or not _is_portable_basename(manifest["source_filename"])
        or type(manifest["database_sha256"]) is not str
        or not SHA256_PATTERN.fullmatch(manifest["database_sha256"])
        or not _is_exact_int(manifest["database_size"])
        or manifest["database_size"] < 0
        or not _is_exact_int(manifest["user_version"])
        or type(manifest["tables"]) is not list
        or any(type(table) is not str for table in manifest["tables"])
        or type(manifest["row_counts"]) is not dict
        or any(
            type(table) is not str
            or table not in COUNT_TABLES
            or not _is_exact_int(count)
            or count < 0
            for table, count in manifest["row_counts"].items()
        )
        or manifest["integrity_check"] != "ok"
        or not _is_exact_int(manifest["foreign_key_violations"])
        or manifest["foreign_key_violations"] != 0
    ):
        raise StateBundleError("invalid state bundle manifest types")


def _verified_manifest(manifest: object) -> VerifiedBundle:
    if type(manifest) is not dict or not _is_exact_int(manifest.get("schema_version")):
        raise StateBundleError("invalid state bundle manifest fields")
    schema_version = manifest["schema_version"]
    expected_fields = SCHEMA1_FIELDS if schema_version == 1 else SCHEMA2_FIELDS
    if schema_version not in {1, 2} or set(manifest) != expected_fields:
        raise StateBundleError("unsupported state bundle schema or fields")
    _validate_common_manifest(manifest)

    service = manifest["service"]
    if service is not None and (
        type(service) is not str or not IDENTITY_PATTERN.fullmatch(service)
    ):
        raise StateBundleError("invalid state bundle service")
    if schema_version == 1:
        if service is None:
            raise StateBundleError("invalid state bundle service")
        purpose: BundlePurpose = "service-state"
        archive_label = None
        creation_platform = None
        durability: DurabilityLevel = "unknown"
    else:
        purpose = manifest["purpose"]
        archive_label = manifest["archive_label"]
        creation_platform = manifest["creation_platform"]
        durability = manifest["durability"]
        if type(purpose) is not str or purpose not in {"service-state", "archive"}:
            raise StateBundleError("invalid state bundle purpose")
        if type(creation_platform) is not str or creation_platform not in {
            "posix",
            "windows",
        }:
            raise StateBundleError("invalid state bundle creation platform")
        if type(durability) is not str or durability != "atomic-process-crash":
            raise StateBundleError("invalid state bundle durability")
        service_identity_valid = (
            purpose == "service-state" and service is not None and archive_label is None
        )
        archive_identity_valid = (
            purpose == "archive"
            and service is None
            and type(archive_label) is str
            and IDENTITY_PATTERN.fullmatch(archive_label) is not None
        )
        if not service_identity_valid and not archive_identity_valid:
            raise StateBundleError("invalid state bundle identity")

    metadata = {key: manifest[key] for key in (
        "user_version",
        "tables",
        "row_counts",
        "integrity_check",
        "foreign_key_violations",
    )}
    return VerifiedBundle(
        schema_version=schema_version,
        purpose=purpose,
        service=service,
        archive_label=archive_label,
        source_filename=manifest["source_filename"],
        creation_platform=creation_platform,
        durability=durability,
        database_sha256=manifest["database_sha256"],
        database_size=manifest["database_size"],
        metadata=metadata,
    )


def _verify_bundle_contents(
    bundle: Path,
    *,
    receipt: dict[str, object] | None = None,
    original_bundle_name: str | None = None,
) -> VerifiedBundle:
    failure_path = bundle / FAILURE_FILENAME
    if failure_path.exists():
        _load_failure(failure_path)
        raise StateBundleError("quarantined or failed state bundle is not promotable")
    manifest_path = bundle / "manifest.json"
    database_path = bundle / "database.sqlite"
    if not manifest_path.is_file() or not database_path.is_file():
        raise StateBundleError("state bundle is incomplete")
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError, OSError, RecursionError) as error:
        raise StateBundleError("invalid state bundle manifest") from error
    verified = _verified_manifest(manifest_data)
    manifest_sha256 = sha256_file(manifest_path)
    if receipt is not None and (
        receipt["manifest_sha256"] != manifest_sha256
        or (
            verified.schema_version == 2
            and receipt["creation_platform"] != verified.creation_platform
        )
        or receipt["bundle_name"] != original_bundle_name
    ):
        raise StateBundleError("invalid state bundle transaction receipt")
    if sha256_file(database_path) != verified.database_sha256:
        raise StateBundleError("state bundle database hash mismatch")
    if database_path.stat().st_size != verified.database_size:
        raise StateBundleError("state bundle database size mismatch")
    inspected = inspect_database(database_path)
    for key, expected in verified.metadata.items():
        if inspected[key] != expected:
            raise StateBundleError(f"state bundle metadata mismatch: {key}")
    completion_path = bundle / COMPLETION_FILENAME
    if not completion_path.exists():
        return verified
    completion = _load_completion(completion_path)
    if (
        verified.schema_version != 2
        or verified.creation_platform != "posix"
        or verified.durability != "atomic-process-crash"
        or receipt is None
        or original_bundle_name is None
        or bundle.name != original_bundle_name
        or completion["manifest_sha256"] != manifest_sha256
        or completion["creation_platform"] != verified.creation_platform
        or completion["transaction_nonce"] != receipt["transaction_nonce"]
        or completion["bundle_name"] != original_bundle_name
    ):
        raise StateBundleError("invalid state bundle durability completion")
    return replace(verified, durability="power-loss-posix")


def verify_bundle(bundle: Path) -> VerifiedBundle:
    original_bundle_name = _original_bundle_name(bundle.name)
    lock_path = bundle.parent / f".{original_bundle_name}.creation.lock"
    with _bundle_lock(
        lock_path, exclusive=False, blocking=False, create=False
    ) as descriptor:
        return _verify_locked_bundle(bundle, descriptor)


def _verify_locked_bundle(bundle: Path, descriptor: int) -> VerifiedBundle:
    receipt = _read_receipt(descriptor)
    original_bundle_name = _original_bundle_name(bundle.name)
    if receipt["state"] != "success" or receipt["bundle_name"] != original_bundle_name:
        raise StateBundleError("state bundle transaction is not complete")
    return _verify_bundle_contents(
        bundle,
        receipt=receipt,
        original_bundle_name=original_bundle_name,
    )


def _load_completion(path: Path) -> dict[str, object]:
    try:
        completion = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError, OSError, RecursionError) as error:
        raise StateBundleError("invalid state bundle durability completion") from error
    if (
        type(completion) is not dict
        or set(completion) != COMPLETION_FIELDS
        or not _is_exact_int(completion["schema_version"])
        or completion["schema_version"] != 1
        or completion["durability"] != "power-loss-posix"
        or type(completion["durability"]) is not str
        or type(completion["manifest_sha256"]) is not str
        or not SHA256_PATTERN.fullmatch(completion["manifest_sha256"])
        or type(completion["creation_platform"]) is not str
        or completion["creation_platform"] != "posix"
        or type(completion["transaction_nonce"]) is not str
        or not TRANSACTION_NONCE_PATTERN.fullmatch(completion["transaction_nonce"])
        or not _is_portable_basename(completion["bundle_name"])
    ):
        raise StateBundleError("invalid state bundle durability completion")
    return completion


def _validated_receipt(receipt: object) -> dict[str, object]:
    if (
        type(receipt) is not dict
        or set(receipt) != RECEIPT_FIELDS
        or not _is_exact_int(receipt["schema_version"])
        or receipt["schema_version"] != 1
        or type(receipt["state"]) is not str
        or receipt["state"] not in {"pending", "success", "failed"}
        or type(receipt["transaction_nonce"]) is not str
        or not TRANSACTION_NONCE_PATTERN.fullmatch(receipt["transaction_nonce"])
        or not _is_portable_basename(receipt["bundle_name"])
        or not FINAL_BUNDLE_PATTERN.fullmatch(receipt["bundle_name"])
        or type(receipt["creation_platform"]) is not str
        or receipt["creation_platform"] not in {"posix", "windows"}
    ):
        raise StateBundleError("invalid state bundle transaction receipt")
    manifest_sha256 = receipt["manifest_sha256"]
    if receipt["state"] == "success":
        if type(manifest_sha256) is not str or not SHA256_PATTERN.fullmatch(
            manifest_sha256
        ):
            raise StateBundleError("invalid state bundle transaction receipt")
    elif manifest_sha256 is not None:
        raise StateBundleError("invalid state bundle transaction receipt")
    return receipt


def _read_receipt(descriptor: int) -> dict[str, object]:
    size = os.fstat(descriptor).st_size
    if size < 1 or size > MAX_RECEIPT_BYTES:
        raise StateBundleError("invalid state bundle transaction receipt")
    os.lseek(descriptor, 0, os.SEEK_SET)
    contents = bytearray()
    while len(contents) < size:
        chunk = os.read(descriptor, size - len(contents))
        if not chunk:
            raise StateBundleError("invalid state bundle transaction receipt")
        contents.extend(chunk)
    try:
        receipt = json.loads(contents.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError, RecursionError) as error:
        raise StateBundleError("invalid state bundle transaction receipt") from error
    return _validated_receipt(receipt)


def _write_receipt(descriptor: int, receipt: dict[str, object]) -> None:
    _validated_receipt(receipt)
    encoded = (
        json.dumps(receipt, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise StateBundleError("invalid state bundle transaction receipt")
    os.lseek(descriptor, 0, os.SEEK_SET)
    written = 0
    while written < len(encoded):
        count = os.write(descriptor, encoded[written:])
        if count <= 0:
            raise StateBundleError("state bundle transaction receipt write failed")
        written += count
    os.ftruncate(descriptor, len(encoded))
    os.fsync(descriptor)


def _receipt(
    *,
    state: Literal["pending", "success", "failed"],
    transaction_nonce: str,
    bundle_name: str,
    creation_platform: CreationPlatform,
    manifest_sha256: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "state": state,
        "transaction_nonce": transaction_nonce,
        "bundle_name": bundle_name,
        "manifest_sha256": manifest_sha256,
        "creation_platform": creation_platform,
    }


def _original_bundle_name(name: str) -> str:
    if FINAL_BUNDLE_PATTERN.fullmatch(name):
        return name
    quarantine = QUARANTINE_BUNDLE_PATTERN.fullmatch(name)
    if quarantine is not None:
        return quarantine.group("bundle")
    raise StateBundleError("invalid state bundle name")


def _load_failure(path: Path) -> dict[str, object]:
    try:
        failure = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError, OSError, RecursionError) as error:
        raise StateBundleError("invalid state bundle failure record") from error
    if (
        type(failure) is not dict
        or set(failure) != FAILURE_FIELDS
        or not _is_exact_int(failure["schema_version"])
        or failure["schema_version"] != 1
        or type(failure["state"]) is not str
        or failure["state"] != "failed"
        or type(failure["manifest_sha256"]) is not str
        or not SHA256_PATTERN.fullmatch(failure["manifest_sha256"])
        or type(failure["creation_platform"]) is not str
        or failure["creation_platform"] not in {"posix", "windows"}
        or not _is_portable_basename(failure["bundle_name"])
    ):
        raise StateBundleError("invalid state bundle failure record")
    return failure


def _contained_path(root: Path, relative: str, description: str) -> Path:
    resolved_root = root.resolve()
    candidate = root / relative
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as error:
        raise StateBundleError(f"runtime {description} path escapes repository root") from error
    return candidate


def _capture_path_identity(
    path: Path, *, description: str, expected_kind: Literal["file", "directory"]
) -> _PathIdentity:
    try:
        resolved = path.resolve(strict=True)
        status = resolved.stat()
    except OSError as error:
        raise StateBundleError(f"formal {description} is unavailable") from error
    kind_matches = resolved.is_file() if expected_kind == "file" else resolved.is_dir()
    if not kind_matches:
        raise StateBundleError(f"formal {description} is not a {expected_kind}")
    return _PathIdentity(resolved, status.st_dev, status.st_ino)


def _revalidate_path_identity(
    path: Path,
    expected: _PathIdentity,
    *,
    description: str,
    expected_kind: Literal["file", "directory"],
) -> None:
    current = _capture_path_identity(
        path, description=description, expected_kind=expected_kind
    )
    if current != expected:
        raise StateBundleError(f"formal {description} changed during operation")


def _capture_open_file_identity(path: Path, descriptor: int) -> _PathIdentity:
    status = os.fstat(descriptor)
    return _PathIdentity(path.resolve(strict=True), status.st_dev, status.st_ino)


def _resolve_service_lane(
    *, service: str, root: Path, manifest_path: Path
) -> ServiceLane:
    try:
        manifest = load_runtime_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise StateBundleError("invalid runtime service manifest") from error
    selected = next(
        (entry for entry in manifest["services"] if entry["name"] == service), None
    )
    if selected is None or selected["role"] != "trading":
        raise StateBundleError("unsupported formal SQLite service lane")
    legacy_database = selected["legacy_database"]
    database_filename = selected["database_filename"]
    state_root = selected["state_root"]
    if not all(type(value) is str for value in (legacy_database, database_filename, state_root)):
        raise StateBundleError("formal service has no SQLite lane")
    legacy_source = _contained_path(root, legacy_database, "legacy source")
    destination_root = _contained_path(root, state_root, "destination")
    destination = _contained_path(
        root, f"{state_root}/{database_filename}", "destination"
    )
    if destination.parent != destination_root:
        raise StateBundleError("runtime destination path escapes service state root")
    return ServiceLane(service, legacy_source, destination)


def resolve_service_lane(*, service: str) -> ServiceLane:
    return _resolve_service_lane(
        service=service,
        root=REPO_ROOT,
        manifest_path=REPO_ROOT / "ops/runtime-services.json",
    )


def _creation_platform() -> CreationPlatform:
    return "posix" if _is_posix() else "windows"


def _is_posix() -> bool:
    return os.name == "posix"


def _sync_file(path: Path) -> None:
    flags = os.O_RDONLY if _is_posix() else os.O_RDWR | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _new_bundle_durability() -> DurabilityLevel:
    return "atomic-process-crash"


def _acquire_posix_lock(
    module: object, descriptor: int, *, exclusive: bool, blocking: bool
) -> None:
    operation = module.LOCK_EX if exclusive else module.LOCK_SH
    if not blocking:
        operation |= module.LOCK_NB
    module.flock(descriptor, operation)


def _release_posix_lock(module: object, descriptor: int) -> None:
    module.flock(descriptor, module.LOCK_UN)


def _acquire_windows_lock(
    module: object, descriptor: int, *, exclusive: bool, blocking: bool
) -> None:
    if blocking:
        operation = module.LK_LOCK
    else:
        operation = module.LK_NBLCK if exclusive else module.LK_NBRLCK
    os.lseek(descriptor, 0, os.SEEK_SET)
    module.locking(descriptor, operation, 1)


def _release_windows_lock(module: object, descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    module.locking(descriptor, module.LK_UNLCK, 1)


def _acquire_lock(descriptor: int, *, exclusive: bool, blocking: bool) -> object:
    try:
        if os.name == "posix":
            import fcntl

            _acquire_posix_lock(
                fcntl, descriptor, exclusive=exclusive, blocking=blocking
            )
            return fcntl
        if os.name == "nt":
            import msvcrt

            _acquire_windows_lock(
                msvcrt, descriptor, exclusive=exclusive, blocking=blocking
            )
            return msvcrt
    except ImportError as error:
        raise StateBundleError("state bundle locking unavailable") from error
    raise StateBundleError("state bundle locking unavailable")


def _release_lock(module: object, descriptor: int) -> None:
    if os.name == "posix":
        _release_posix_lock(module, descriptor)
    elif os.name == "nt":
        _release_windows_lock(module, descriptor)
    else:
        raise StateBundleError("state bundle locking unavailable")


def _is_lock_contention(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EAGAIN} or getattr(
        error, "winerror", None
    ) in {33, 36}


def _release_and_close_lock(
    module: object,
    descriptor: int,
    *,
    invalidate_success_on_close_failure: bool = False,
) -> None:
    unlock_failed = False
    try:
        _release_lock(module, descriptor)
    except (AttributeError, OSError):
        unlock_failed = True
    try:
        os.close(descriptor)
        return
    except OSError as close_error:
        if invalidate_success_on_close_failure:
            try:
                if not unlock_failed:
                    _acquire_lock(descriptor, exclusive=True, blocking=True)
                receipt = _read_receipt(descriptor)
                if receipt["state"] == "success":
                    _write_receipt(
                        descriptor,
                        {
                            **receipt,
                            "state": "failed",
                            "manifest_sha256": None,
                        },
                    )
            except (OSError, StateBundleError):
                pass
        try:
            _release_lock(module, descriptor)
        except (AttributeError, OSError):
            pass
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise StateBundleError("state bundle lock close failed") from close_error


@contextmanager
def _bundle_lock(
    path: Path, *, exclusive: bool, blocking: bool, create: bool = True
) -> Iterator[int]:
    flags = (
        os.O_RDWR
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if create:
        flags |= os.O_CREAT
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise StateBundleError("state bundle locking unavailable") from error
    module: object | None = None
    try:
        descriptor_status = os.fstat(descriptor)
        path_status = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(descriptor_status.st_mode)
            or not stat.S_ISREG(path_status.st_mode)
            or descriptor_status.st_dev != path_status.st_dev
            or descriptor_status.st_ino != path_status.st_ino
        ):
            raise StateBundleError("state bundle locking unavailable")
        try:
            module = _acquire_lock(
                descriptor, exclusive=exclusive, blocking=blocking
            )
        except OSError as error:
            if not blocking and _is_lock_contention(error):
                raise StateBundleError("state bundle creation in progress") from error
            raise StateBundleError("state bundle locking unavailable") from error
        yield descriptor
    finally:
        if module is not None:
            _release_and_close_lock(
                module,
                descriptor,
                invalidate_success_on_close_failure=exclusive,
            )
        else:
            os.close(descriptor)


def _acquire_creation_lock(path: Path) -> object:
    return _bundle_lock(path, exclusive=True, blocking=True)


def _write_failure_record(bundle: Path, bundle_name: str) -> None:
    manifest_path = bundle / "manifest.json"
    failure_path = bundle / FAILURE_FILENAME
    failure_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state": "failed",
                "manifest_sha256": sha256_file(manifest_path),
                "creation_platform": _creation_platform(),
                "bundle_name": bundle_name,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _sync_file(failure_path)
    if _is_posix():
        _sync_directory(bundle)


def _create_bundle(
    *,
    purpose: BundlePurpose,
    identity: str,
    source: Path,
    output_root: Path,
    now: datetime,
    source_identity: _PathIdentity | None = None,
    source_parent_identity: _PathIdentity | None = None,
) -> Path:
    if type(identity) is not str or not IDENTITY_PATTERN.fullmatch(identity):
        raise StateBundleError("invalid bundle identity")
    if not isinstance(now, datetime):
        raise StateBundleError("invalid backup timestamp")
    if not source.is_file():
        raise StateBundleError("backup source is not a file")
    created_at = now.astimezone(UTC).replace(microsecond=0)
    timestamp = created_at.strftime("%Y%m%dT%H%M%SZ")
    output_root.mkdir(parents=True, exist_ok=True)
    final_bundle = output_root / f"{timestamp}-{identity}"
    if final_bundle.parent != output_root:
        raise StateBundleError("backup bundle already exists or has an invalid path")
    lock_path = output_root / f".{final_bundle.name}.creation.lock"
    with _acquire_creation_lock(lock_path) as lock_descriptor:
        if final_bundle.exists():
            raise StateBundleError("backup bundle already exists or has an invalid path")
        transaction_nonce = secrets.token_hex(16)
        creation_platform = _creation_platform()
        pending_receipt = _receipt(
            state="pending",
            transaction_nonce=transaction_nonce,
            bundle_name=final_bundle.name,
            creation_platform=creation_platform,
        )
        try:
            _write_receipt(lock_descriptor, pending_receipt)
        except BaseException:
            try:
                _write_receipt(
                    lock_descriptor,
                    {**pending_receipt, "state": "failed"},
                )
            except BaseException:
                pass
            raise
        return _create_bundle_under_lock(
            purpose=purpose,
            identity=identity,
            source=source,
            output_root=output_root,
            created_at=created_at,
            final_bundle=final_bundle,
            lock_descriptor=lock_descriptor,
            transaction_nonce=transaction_nonce,
            creation_platform=creation_platform,
            source_identity=source_identity,
            source_parent_identity=source_parent_identity,
        )


def _create_bundle_under_lock(
    *,
    purpose: BundlePurpose,
    identity: str,
    source: Path,
    output_root: Path,
    created_at: datetime,
    final_bundle: Path,
    lock_descriptor: int,
    transaction_nonce: str,
    creation_platform: CreationPlatform,
    source_identity: _PathIdentity | None,
    source_parent_identity: _PathIdentity | None,
) -> Path:
    staging = Path(tempfile.mkdtemp(prefix=f".{identity}-", dir=output_root))
    database = staging / "database.sqlite"
    published_final = False
    try:
        if source_parent_identity is not None:
            _revalidate_path_identity(
                source.parent,
                source_parent_identity,
                description="source parent",
                expected_kind="directory",
            )
        if source_identity is not None:
            _revalidate_path_identity(
                source,
                source_identity,
                description="backup source",
                expected_kind="file",
            )
        online_backup(source, database)
        inspected = inspect_database(database)
        _sync_file(database)
        manifest = {
            "schema_version": 2,
            "purpose": purpose,
            "service": identity if purpose == "service-state" else None,
            "archive_label": identity if purpose == "archive" else None,
            "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
            "creation_platform": creation_platform,
            "durability": _new_bundle_durability(),
            "sqlite_version": sqlite3.sqlite_version,
            "source_filename": source.name,
            "database_sha256": sha256_file(database),
            "database_size": database.stat().st_size,
            **inspected,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _sync_file(manifest_path)
        _verify_bundle_contents(staging)
        if _is_posix():
            _sync_directory(staging)
        os.replace(staging, final_bundle)
        published_final = True
        if _is_posix():
            _sync_directory(output_root)
            manifest_path = final_bundle / "manifest.json"
            pending_completion = final_bundle / (
                f".{COMPLETION_FILENAME}.pending-{secrets.token_hex(8)}"
            )
            pending_completion.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "durability": "power-loss-posix",
                        "manifest_sha256": sha256_file(manifest_path),
                        "creation_platform": "posix",
                        "transaction_nonce": transaction_nonce,
                        "bundle_name": final_bundle.name,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            _sync_file(pending_completion)
            completion_path = final_bundle / COMPLETION_FILENAME
            os.replace(pending_completion, completion_path)
            _sync_directory(final_bundle)
            completion = _load_completion(completion_path)
            if (
                completion["manifest_sha256"] != sha256_file(manifest_path)
                or completion["creation_platform"] != "posix"
                or completion["transaction_nonce"] != transaction_nonce
                or completion["bundle_name"] != final_bundle.name
            ):
                raise StateBundleError("invalid state bundle durability completion")
        manifest_sha256 = sha256_file(final_bundle / "manifest.json")
        success_receipt = _receipt(
            state="success",
            transaction_nonce=transaction_nonce,
            bundle_name=final_bundle.name,
            creation_platform=creation_platform,
            manifest_sha256=manifest_sha256,
        )
        if _is_posix() and _verify_bundle_contents(
            final_bundle,
            receipt=success_receipt,
            original_bundle_name=final_bundle.name,
        ).durability != "power-loss-posix":
            raise StateBundleError("state bundle durability completion failed")
        _write_receipt(
            lock_descriptor,
            success_receipt,
        )
        return final_bundle
    except BaseException:
        receipt_error: BaseException | None = None
        try:
            _write_receipt(
                lock_descriptor,
                _receipt(
                    state="failed",
                    transaction_nonce=transaction_nonce,
                    bundle_name=final_bundle.name,
                    creation_platform=creation_platform,
                ),
            )
        except BaseException as error:
            receipt_error = error
        if published_final:
            quarantine = output_root / (
                f".{final_bundle.name}.quarantine-{secrets.token_hex(8)}"
            )
            failure_error: BaseException | None = None
            try:
                _write_failure_record(final_bundle, final_bundle.name)
            except BaseException as error:
                failure_error = error
            try:
                os.replace(final_bundle, quarantine)
                if _is_posix():
                    _sync_directory(output_root)
            except BaseException as quarantine_error:
                raise StateBundleError("state bundle quarantine failed") from quarantine_error
            if failure_error is not None:
                raise StateBundleError(
                    "state bundle failure recording failed"
                ) from failure_error
        if receipt_error is not None:
            raise StateBundleError(
                "state bundle transaction recording failed"
            ) from receipt_error
        raise


def _create_service_backup(
    *,
    service: str,
    output_root: Path,
    now: datetime,
    root: Path,
    manifest_path: Path,
) -> Path:
    lane = _resolve_service_lane(
        service=service, root=root, manifest_path=manifest_path
    )
    source_parent_identity = _capture_path_identity(
        lane.legacy_source.parent,
        description="source parent",
        expected_kind="directory",
    )
    source_identity = _capture_path_identity(
        lane.legacy_source, description="backup source", expected_kind="file"
    )
    return _create_bundle(
        purpose="service-state",
        identity=lane.service,
        source=lane.legacy_source,
        output_root=output_root,
        now=now,
        source_identity=source_identity,
        source_parent_identity=source_parent_identity,
    )


def create_service_backup(
    *, service: str, output_root: Path, now: datetime
) -> Path:
    return _create_service_backup(
        service=service,
        output_root=output_root,
        now=now,
        root=REPO_ROOT,
        manifest_path=REPO_ROOT / "ops/runtime-services.json",
    )


def create_archive(*, label: str, source: Path, output_root: Path, now: datetime) -> Path:
    return _create_bundle(
        purpose="archive",
        identity=label,
        source=source,
        output_root=output_root,
        now=now,
    )


def _restore_verified_bundle(
    bundle: Path,
    destination: Path,
    verified: VerifiedBundle,
    destination_parent_identity: _PathIdentity,
) -> None:
    _revalidate_path_identity(
        destination.parent,
        destination_parent_identity,
        description="destination parent",
        expected_kind="directory",
    )
    if os.path.lexists(destination):
        raise StateBundleError(f"restore destination already exists: {destination}")
    if not destination.parent.is_dir():
        raise StateBundleError("restore destination parent does not exist")
    _revalidate_path_identity(
        destination.parent,
        destination_parent_identity,
        description="destination parent",
        expected_kind="directory",
    )
    descriptor, temporary_text = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        temporary_identity = _capture_open_file_identity(
            Path(temporary_text), descriptor
        )
    finally:
        os.close(descriptor)
    temporary = temporary_identity.resolved
    _revalidate_path_identity(
        temporary,
        temporary_identity,
        description="restore temporary",
        expected_kind="file",
    )
    shutil.copyfile(bundle / "database.sqlite", temporary)
    _sync_file(temporary)
    if sha256_file(temporary) != verified.database_sha256:
        raise StateBundleError("restored database metadata mismatch: hash")
    if temporary.stat().st_size != verified.database_size:
        raise StateBundleError("restored database metadata mismatch: size")
    inspected = inspect_database(temporary)
    for key, expected in verified.metadata.items():
        if inspected[key] != expected:
            raise StateBundleError(f"restored database metadata mismatch: {key}")
    _revalidate_path_identity(
        destination.parent,
        destination_parent_identity,
        description="destination parent",
        expected_kind="directory",
    )
    _revalidate_path_identity(
        temporary,
        temporary_identity,
        description="restore temporary",
        expected_kind="file",
    )
    try:
        os.link(temporary, destination)
    except FileExistsError as error:
        raise StateBundleError(
            f"restore destination already exists: {destination}"
        ) from error
    if _is_posix():
        _sync_directory(destination.parent)
        # Scheme A intentionally retains the temporary hard link as quarantine.
        _sync_directory(destination.parent)


def _restore_service(
    *,
    service: str,
    bundle: Path,
    root: Path,
    manifest_path: Path,
    allow_legacy_schema1: bool = False,
) -> Path:
    lane = _resolve_service_lane(
        service=service, root=root, manifest_path=manifest_path
    )
    destination_parent_identity = _capture_path_identity(
        lane.destination.parent,
        description="destination parent",
        expected_kind="directory",
    )
    verified = verify_bundle(bundle)
    if verified.purpose == "archive":
        raise StateBundleError("archive bundles cannot restore to formal services")
    if verified.schema_version == 1 and not allow_legacy_schema1:
        raise StateBundleError("legacy schema 1 restore requires explicit authorization")
    if verified.service != lane.service:
        raise StateBundleError("state bundle service does not match destination service")
    if verified.source_filename != lane.legacy_source.name:
        raise StateBundleError("state bundle source filename does not match service lane")
    _restore_verified_bundle(
        bundle,
        lane.destination,
        verified,
        destination_parent_identity,
    )
    return lane.destination


def restore_service(
    *, service: str, bundle: Path, allow_legacy_schema1: bool = False
) -> Path:
    return _restore_service(
        service=service,
        bundle=bundle,
        root=REPO_ROOT,
        manifest_path=REPO_ROOT / "ops/runtime-services.json",
        allow_legacy_schema1=allow_legacy_schema1,
    )


def compare_structure(source: Path, candidate: Path) -> None:
    source_info = inspect_database(source)
    candidate_info = inspect_database(candidate)
    if source_info["user_version"] != candidate_info["user_version"]:
        raise StateBundleError("user_version mismatch")
    if set(source_info["tables"]) != set(candidate_info["tables"]):
        raise StateBundleError("table set mismatch")
    source_counts = source_info["row_counts"]
    candidate_counts = candidate_info["row_counts"]
    assert isinstance(source_counts, dict)
    assert isinstance(candidate_counts, dict)
    for table in COUNT_TABLES:
        if source_counts.get(table) != candidate_counts.get(table):
            raise StateBundleError(
                f"{table} row count mismatch: "
                f"{source_counts.get(table)} != {candidate_counts.get(table)}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage consistent SQLite state bundles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup-service")
    backup.add_argument("--service", required=True)
    backup.add_argument("--output-root", type=Path, required=True)
    backup.add_argument("--print-path", action="store_true")

    restore = subparsers.add_parser("restore-service")
    restore.add_argument("--service", required=True)
    restore.add_argument("--bundle", type=Path, required=True)
    restore.add_argument("--allow-legacy-schema1", action="store_true")

    archive = subparsers.add_parser("archive")
    archive.add_argument("--label", required=True)
    archive.add_argument("--source", type=Path, required=True)
    archive.add_argument("--output-root", type=Path, required=True)
    archive.add_argument("--print-path", action="store_true")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)

    compare = subparsers.add_parser("compare-structure")
    compare.add_argument("--source", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "backup-service":
        bundle = create_service_backup(
            service=args.service,
            output_root=args.output_root,
            now=datetime.now(UTC),
        )
        print(bundle if args.print_path else "SQLite service backup: OK")
    elif args.command == "restore-service":
        restore_service(
            service=args.service,
            bundle=args.bundle,
            allow_legacy_schema1=args.allow_legacy_schema1,
        )
        print("SQLite service restore: OK")
    elif args.command == "archive":
        bundle = create_archive(
            label=args.label,
            source=args.source,
            output_root=args.output_root,
            now=datetime.now(UTC),
        )
        print(bundle if args.print_path else "SQLite archive: OK")
    elif args.command == "verify":
        verify_bundle(args.bundle)
        print("SQLite bundle verification: OK")
    elif args.command == "compare-structure":
        compare_structure(args.source, args.candidate)
        print("SQLite structure comparison: OK")
    return 0


def _run_cli() -> int:
    try:
        return main()
    except (StateBundleError, OSError, sqlite3.Error, ValueError):
        print("SQLite state operation failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_run_cli())
