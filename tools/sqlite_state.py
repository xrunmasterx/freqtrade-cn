from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sqlite3
import sys
import tempfile
from typing import Literal

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
        if type(durability) is not str or durability not in {
            "unknown",
            "atomic-process-crash",
            "power-loss-posix",
        }:
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


def verify_bundle(bundle: Path) -> VerifiedBundle:
    manifest_path = bundle / "manifest.json"
    database_path = bundle / "database.sqlite"
    if not manifest_path.is_file() or not database_path.is_file():
        raise StateBundleError("state bundle is incomplete")
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError, OSError, RecursionError) as error:
        raise StateBundleError("invalid state bundle manifest") from error
    verified = _verified_manifest(manifest_data)
    if sha256_file(database_path) != verified.database_sha256:
        raise StateBundleError("state bundle database hash mismatch")
    if database_path.stat().st_size != verified.database_size:
        raise StateBundleError("state bundle database size mismatch")
    inspected = inspect_database(database_path)
    for key, expected in verified.metadata.items():
        if inspected[key] != expected:
            raise StateBundleError(f"state bundle metadata mismatch: {key}")
    return verified


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


def _cleanup_restore_temporary(
    temporary: Path,
    *,
    cleanup_root: Path,
    destination_parent_identity: _PathIdentity,
) -> None:
    temporary.unlink(missing_ok=True)
    for candidate in cleanup_root.rglob(temporary.name):
        try:
            candidate_parent_identity = _capture_path_identity(
                candidate.parent,
                description="temporary restore parent",
                expected_kind="directory",
            )
        except StateBundleError:
            continue
        if (
            candidate_parent_identity.device == destination_parent_identity.device
            and candidate_parent_identity.inode == destination_parent_identity.inode
        ):
            candidate.unlink(missing_ok=True)


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
    return "windows" if os.name == "nt" else "posix"


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
    if final_bundle.parent != output_root or final_bundle.exists():
        raise StateBundleError("backup bundle already exists or has an invalid path")
    staging = Path(tempfile.mkdtemp(prefix=f".{identity}-", dir=output_root))
    database = staging / "database.sqlite"
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
        manifest = {
            "schema_version": 2,
            "purpose": purpose,
            "service": identity if purpose == "service-state" else None,
            "archive_label": identity if purpose == "archive" else None,
            "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
            "creation_platform": _creation_platform(),
            "durability": "atomic-process-crash",
            "sqlite_version": sqlite3.sqlite_version,
            "source_filename": source.name,
            "database_sha256": sha256_file(database),
            "database_size": database.stat().st_size,
            **inspected,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        verify_bundle(staging)
        os.replace(staging, final_bundle)
        return final_bundle
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
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
    cleanup_root: Path,
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
    os.close(descriptor)
    temporary = Path(temporary_text).resolve(strict=True)
    published = False
    try:
        shutil.copyfile(bundle / "database.sqlite", temporary)
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
        try:
            os.link(temporary, destination)
        except FileExistsError as error:
            raise StateBundleError(
                f"restore destination already exists: {destination}"
            ) from error
        published = True
        try:
            temporary.unlink()
        except OSError as error:
            raise StateBundleError(
                "restore succeeded but temporary cleanup failed"
            ) from error
    except BaseException:
        if not published:
            _cleanup_restore_temporary(
                temporary,
                cleanup_root=cleanup_root,
                destination_parent_identity=destination_parent_identity,
            )
        raise


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
        root,
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
