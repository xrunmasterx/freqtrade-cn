from __future__ import annotations

import argparse
from contextlib import closing
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile


CORE_TABLES = ("trades", "orders")
COUNT_TABLES = ("trades", "orders", "pairlocks", "KeyValueStore")
MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FIELDS = {
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
SERVICE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
UTC_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class StateBundleError(RuntimeError):
    pass


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
        missing = sorted(set(CORE_TABLES) - set(tables))
        if integrity != ["ok"] or foreign_keys or missing:
            raise StateBundleError("SQLite integrity or core-table policy failed")
        counts = {
            table: connection.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]
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


def _validate_manifest(manifest: object) -> dict[str, object]:
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise StateBundleError("invalid state bundle manifest fields")
    if not _is_exact_int(manifest["schema_version"]):
        raise StateBundleError("invalid state bundle manifest types")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise StateBundleError("unsupported state bundle schema")
    string_fields = ("service", "created_at_utc", "sqlite_version", "source_filename")
    if any(type(manifest[field]) is not str for field in string_fields):
        raise StateBundleError("invalid state bundle manifest types")
    if not SERVICE_PATTERN.fullmatch(manifest["service"]):
        raise StateBundleError("invalid state bundle manifest service")
    if not UTC_TIMESTAMP_PATTERN.fullmatch(manifest["created_at_utc"]):
        raise StateBundleError("invalid state bundle manifest timestamp")
    if (
        type(manifest["database_sha256"]) is not str
        or not SHA256_PATTERN.fullmatch(manifest["database_sha256"])
        or not _is_exact_int(manifest["database_size"])
        or manifest["database_size"] < 0
        or not _is_exact_int(manifest["user_version"])
        or type(manifest["tables"]) is not list
        or any(type(table) is not str for table in manifest["tables"])
        or type(manifest["row_counts"]) is not dict
        or any(
            table not in COUNT_TABLES
            or type(table) is not str
            or not _is_exact_int(count)
            or count < 0
            for table, count in manifest["row_counts"].items()
        )
        or manifest["integrity_check"] != "ok"
        or not _is_exact_int(manifest["foreign_key_violations"])
        or manifest["foreign_key_violations"] != 0
    ):
        raise StateBundleError("invalid state bundle manifest types")
    return manifest


def verify_bundle(bundle: Path) -> dict[str, object]:
    manifest_path = bundle / "manifest.json"
    database_path = bundle / "database.sqlite"
    if not manifest_path.is_file() or not database_path.is_file():
        raise StateBundleError("state bundle is incomplete")
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError, OSError) as error:
        raise StateBundleError("invalid state bundle manifest") from error
    manifest = _validate_manifest(manifest_data)
    if sha256_file(database_path) != manifest["database_sha256"]:
        raise StateBundleError("state bundle database hash mismatch")
    if database_path.stat().st_size != manifest["database_size"]:
        raise StateBundleError("state bundle database size mismatch")
    inspected = inspect_database(database_path)
    for key in (
        "user_version",
        "tables",
        "row_counts",
        "integrity_check",
        "foreign_key_violations",
    ):
        if inspected[key] != manifest[key]:
            raise StateBundleError(f"state bundle metadata mismatch: {key}")
    return manifest


def create_backup(
    *,
    service: str,
    source: Path,
    output_root: Path,
    now: datetime,
) -> Path:
    if type(service) is not str or not SERVICE_PATTERN.fullmatch(service):
        raise StateBundleError("invalid service name")
    if not isinstance(now, datetime):
        raise StateBundleError("invalid backup timestamp")
    if not source.is_file():
        raise StateBundleError("backup source is not a file")
    created_at = now.astimezone(UTC).replace(microsecond=0)
    timestamp = created_at.strftime("%Y%m%dT%H%M%SZ")
    if not re.fullmatch(r"\d{8}T\d{6}Z", timestamp):
        raise StateBundleError("invalid backup timestamp")
    output_root.mkdir(parents=True, exist_ok=True)
    final_bundle = output_root / f"{timestamp}-{service}"
    if final_bundle.parent != output_root or final_bundle.exists():
        raise StateBundleError("backup bundle already exists or has an invalid path")
    staging = Path(tempfile.mkdtemp(prefix=f".{service}-", dir=output_root))
    database = staging / "database.sqlite"
    try:
        online_backup(source, database)
        inspected = inspect_database(database)
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "service": service,
            "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
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


def restore_bundle(bundle: Path, destination: Path) -> None:
    verify_bundle(bundle)
    if destination.exists():
        raise StateBundleError(f"restore destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_text = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_text)
    try:
        shutil.copyfile(bundle / "database.sqlite", temporary)
        inspect_database(temporary)
        if sha256_file(temporary) != sha256_file(bundle / "database.sqlite"):
            raise StateBundleError("restored database hash mismatch")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def compare_databases(source: Path, candidate: Path) -> None:
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
        source_count = source_counts.get(table)
        candidate_count = candidate_counts.get(table)
        if source_count != candidate_count:
            raise StateBundleError(
                f"{table} row count mismatch: {source_count} != {candidate_count}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage consistent SQLite state bundles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup")
    backup.add_argument("--service", required=True)
    backup.add_argument("--source", type=Path, required=True)
    backup.add_argument("--output-root", type=Path, required=True)
    backup.add_argument("--print-path", action="store_true")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)

    restore = subparsers.add_parser("restore")
    restore.add_argument("--bundle", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--source", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "backup":
        bundle = create_backup(
            service=args.service,
            source=args.source,
            output_root=args.output_root,
            now=datetime.now(UTC),
        )
        print(bundle if args.print_path else "SQLite backup: OK")
    elif args.command == "verify":
        verify_bundle(args.bundle)
        print("SQLite bundle verification: OK")
    elif args.command == "restore":
        restore_bundle(args.bundle, args.destination)
        print("SQLite restore: OK")
    elif args.command == "compare":
        compare_databases(args.source, args.candidate)
        print("SQLite comparison: OK")
    return 0


def _run_cli() -> int:
    try:
        return main()
    except (StateBundleError, OSError, sqlite3.Error, ValueError):
        print("SQLite state operation failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_run_cli())
