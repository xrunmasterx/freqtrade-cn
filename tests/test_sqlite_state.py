from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import sqlite_state


class SQLiteStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        manifest_source = Path(__file__).resolve().parents[1] / "ops" / "runtime-services.json"
        self.manifest_path = self.root / "ops" / "runtime-services.json"
        self.manifest_path.parent.mkdir(parents=True)
        shutil.copyfile(manifest_source, self.manifest_path)
        self.spot_source = self.root / "ft_userdata/user_data/tradesv3.sqlite"
        self.futures_source = self.root / "ft_userdata/user_data/tradesv3-futures.sqlite"
        self.spot_destination = self.root / "ft_userdata/runtime/freqtrade/trades.sqlite"
        self.futures_destination = (
            self.root / "ft_userdata/runtime/freqtrade-futures/trades.sqlite"
        )
        self.spot_source.parent.mkdir(parents=True)
        self.spot_destination.parent.mkdir(parents=True)
        self.futures_destination.parent.mkdir(parents=True)
        self.create_database(self.spot_source)
        self.create_database(self.futures_source)
        self.output_root = self.root / "backups"
        self.fixed_now = datetime(2026, 7, 11, tzinfo=UTC)

    def create_database(
        self, path: Path, *, tables: tuple[str, ...] = sqlite_state.COUNT_TABLES
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            definitions = {
                "trades": "CREATE TABLE trades (id INTEGER PRIMARY KEY, pair TEXT)",
                "orders": "CREATE TABLE orders (id INTEGER PRIMARY KEY)",
                "pairlocks": "CREATE TABLE pairlocks (id INTEGER PRIMARY KEY)",
                "KeyValueStore": (
                    'CREATE TABLE "KeyValueStore" (id INTEGER PRIMARY KEY, value TEXT)'
                ),
            }
            for table in tables:
                connection.execute(definitions[table])
            connection.commit()

    def create_service_bundle(self, service: str = "freqtrade") -> Path:
        return sqlite_state.create_service_backup(
            service=service,
            output_root=self.output_root,
            now=self.fixed_now,
            root=self.root,
            manifest_path=self.manifest_path,
        )

    def create_archive_bundle(self) -> Path:
        return sqlite_state.create_archive(
            label="qqe-research",
            source=self.spot_source,
            output_root=self.output_root,
            now=self.fixed_now,
        )

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(Path(sqlite_state.__file__)), *arguments],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_resolve_service_lane_derives_spot_and_futures_from_manifest(self) -> None:
        spot = sqlite_state.resolve_service_lane(
            service="freqtrade", root=self.root, manifest_path=self.manifest_path
        )
        futures = sqlite_state.resolve_service_lane(
            service="freqtrade-futures", root=self.root, manifest_path=self.manifest_path
        )
        self.assertEqual(
            spot,
            sqlite_state.ServiceLane(
                "freqtrade", self.spot_source, self.spot_destination
            ),
        )
        self.assertEqual(
            futures,
            sqlite_state.ServiceLane(
                "freqtrade-futures", self.futures_source, self.futures_destination
            ),
        )

    def test_resolve_service_lane_rejects_research_and_unknown_services(self) -> None:
        for service in ("freqtrade-research", "unknown", "../freqtrade"):
            with self.subTest(service=service):
                with self.assertRaises(sqlite_state.StateBundleError):
                    sqlite_state.resolve_service_lane(
                        service=service, root=self.root, manifest_path=self.manifest_path
                    )

    def test_resolve_service_lane_rejects_path_escape(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        self.addCleanup(shutil.rmtree, outside, True)
        shutil.rmtree(self.spot_destination.parent)
        try:
            self.spot_destination.parent.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlinks are unavailable")
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "escape"):
            sqlite_state.resolve_service_lane(
                service="freqtrade", root=self.root, manifest_path=self.manifest_path
            )

    def test_schema2_service_bundle_has_exact_fields_and_identity(self) -> None:
        bundle = self.create_service_bundle()
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(manifest),
            {
                "schema_version",
                "purpose",
                "service",
                "archive_label",
                "created_at_utc",
                "creation_platform",
                "durability",
                "sqlite_version",
                "source_filename",
                "database_sha256",
                "database_size",
                "user_version",
                "tables",
                "row_counts",
                "integrity_check",
                "foreign_key_violations",
            },
        )
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["purpose"], "service-state")
        self.assertEqual(manifest["service"], "freqtrade")
        self.assertIsNone(manifest["archive_label"])
        self.assertEqual(manifest["source_filename"], "tradesv3.sqlite")
        self.assertIn(manifest["creation_platform"], {"posix", "windows"})
        self.assertEqual(manifest["durability"], "atomic-process-crash")
        verified = sqlite_state.verify_bundle(bundle)
        self.assertIsInstance(verified, sqlite_state.VerifiedBundle)
        self.assertEqual(verified.service, "freqtrade")

    def test_schema2_archive_bundle_has_archive_identity(self) -> None:
        verified = sqlite_state.verify_bundle(self.create_archive_bundle())
        self.assertEqual(verified.schema_version, 2)
        self.assertEqual(verified.purpose, "archive")
        self.assertIsNone(verified.service)
        self.assertEqual(verified.archive_label, "qqe-research")
        self.assertEqual(verified.durability, "atomic-process-crash")

    def test_schema1_verifies_with_unknown_durability_and_requires_legacy_flag(self) -> None:
        bundle = self.create_service_bundle()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field in ("purpose", "archive_label", "creation_platform", "durability"):
            del manifest[field]
        manifest["schema_version"] = 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        verified = sqlite_state.verify_bundle(bundle)
        self.assertEqual(verified.durability, "unknown")
        self.assertIsNone(verified.creation_platform)
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "legacy"):
            sqlite_state.restore_service(
                service="freqtrade",
                bundle=bundle,
                root=self.root,
                manifest_path=self.manifest_path,
            )
        sqlite_state.restore_service(
            service="freqtrade",
            bundle=bundle,
            root=self.root,
            manifest_path=self.manifest_path,
            allow_legacy_schema1=True,
        )
        self.assertTrue(self.spot_destination.is_file())

    def test_restore_service_rejects_futures_bundle_for_spot_before_any_write(self) -> None:
        bundle = self.create_service_bundle("freqtrade-futures")
        with (
            mock.patch.object(tempfile, "mkstemp") as mkstemp,
            mock.patch.object(shutil, "copyfile") as copyfile,
            mock.patch.object(os, "link") as link,
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "service"):
                sqlite_state.restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        mkstemp.assert_not_called()
        copyfile.assert_not_called()
        link.assert_not_called()

    def test_restore_service_rejects_spot_bundle_for_futures_before_any_write(self) -> None:
        bundle = self.create_service_bundle("freqtrade")
        with (
            mock.patch.object(tempfile, "mkstemp") as mkstemp,
            mock.patch.object(shutil, "copyfile") as copyfile,
            mock.patch.object(os, "link") as link,
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "service"):
                sqlite_state.restore_service(
                    service="freqtrade-futures",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        mkstemp.assert_not_called()
        copyfile.assert_not_called()
        link.assert_not_called()

    def test_archive_bundle_cannot_restore_to_formal_service(self) -> None:
        bundle = self.create_archive_bundle()
        with mock.patch.object(tempfile, "mkstemp") as mkstemp:
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "archive"):
                sqlite_state.restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        mkstemp.assert_not_called()

    def test_restore_service_rejects_source_filename_mismatch_before_write(self) -> None:
        bundle = self.create_service_bundle()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_filename"] = "other.sqlite"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with mock.patch.object(tempfile, "mkstemp") as mkstemp:
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "source filename"):
                sqlite_state.restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        mkstemp.assert_not_called()

    def test_restore_service_refuses_existing_destination(self) -> None:
        bundle = self.create_service_bundle()
        self.spot_destination.write_bytes(b"keep")
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "already exists"):
            sqlite_state.restore_service(
                service="freqtrade",
                bundle=bundle,
                root=self.root,
                manifest_path=self.manifest_path,
            )
        self.assertEqual(self.spot_destination.read_bytes(), b"keep")

    def test_restore_service_does_not_clobber_destination_created_during_copy(self) -> None:
        bundle = self.create_service_bundle()
        original_copyfile = shutil.copyfile

        def copy_then_create_destination(source: Path, target: Path) -> str:
            result = original_copyfile(source, target)
            self.spot_destination.write_bytes(b"keep")
            return result

        with mock.patch.object(
            shutil, "copyfile", side_effect=copy_then_create_destination
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "already exists"):
                sqlite_state.restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        self.assertEqual(self.spot_destination.read_bytes(), b"keep")
        self.assertEqual(list(self.spot_destination.parent.glob("*.tmp")), [])

    def test_restore_service_refuses_missing_destination_parent(self) -> None:
        bundle = self.create_service_bundle()
        shutil.rmtree(self.spot_destination.parent)
        with mock.patch.object(tempfile, "mkstemp") as mkstemp:
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "parent"):
                sqlite_state.restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        mkstemp.assert_not_called()
        self.assertFalse(self.spot_destination.parent.exists())

    def test_backup_contains_committed_wal_rows_and_excludes_uncommitted_rows(self) -> None:
        writer = sqlite3.connect(self.spot_source)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO trades(pair) VALUES ('BTC/USDT')")
        writer.commit()
        writer.execute("INSERT INTO trades(pair) VALUES ('ETH/USDT')")
        bundle = self.create_service_bundle()
        with closing(sqlite3.connect(bundle / "database.sqlite")) as backup:
            rows = backup.execute("SELECT pair FROM trades").fetchall()
        self.assertEqual(rows, [("BTC/USDT",)])
        writer.rollback()

    def test_verify_rejects_database_and_manifest_tampering(self) -> None:
        bundle = self.create_service_bundle()
        (bundle / "database.sqlite").write_bytes(b"corrupt")
        with self.assertRaises(sqlite_state.StateBundleError):
            sqlite_state.verify_bundle(bundle)

        shutil.rmtree(bundle)
        bundle = self.create_service_bundle()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["row_counts"]["orders"] = 99
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "metadata mismatch"):
            sqlite_state.verify_bundle(bundle)

    def test_failed_backup_and_restore_leave_no_staging_files(self) -> None:
        with mock.patch.object(
            sqlite_state, "inspect_database", side_effect=ValueError("bad")
        ):
            with self.assertRaisesRegex(ValueError, "bad"):
                self.create_service_bundle()
        self.assertEqual(list(self.output_root.iterdir()), [])

        bundle = self.create_service_bundle()
        original_inspect = sqlite_state.inspect_database

        def reject_temporary(path: Path) -> dict[str, object]:
            if path.suffix == ".tmp":
                raise sqlite_state.StateBundleError("copied database rejected")
            return original_inspect(path)

        with mock.patch.object(sqlite_state, "inspect_database", side_effect=reject_temporary):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "copied"):
                sqlite_state.restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        self.assertFalse(self.spot_destination.exists())
        self.assertEqual(list(self.spot_destination.parent.glob("*.tmp")), [])

    def test_compare_structure_detects_count_mismatch_and_accepts_match(self) -> None:
        matching = self.root / "matching.sqlite"
        sqlite_state.online_backup(self.spot_source, matching)
        sqlite_state.compare_structure(self.spot_source, matching)
        with closing(sqlite3.connect(matching)) as connection:
            connection.execute("INSERT INTO orders(id) VALUES (99)")
            connection.commit()
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "orders row count"):
            sqlite_state.compare_structure(self.spot_source, matching)

    def test_public_generic_escape_hatches_are_removed(self) -> None:
        for name in ("create_backup", "restore_bundle", "compare_databases"):
            self.assertFalse(hasattr(sqlite_state, name), name)
        parser = sqlite_state.build_parser()
        help_text = parser.format_help()
        for command in (
            "backup-service",
            "restore-service",
            "archive",
            "verify",
            "compare-structure",
        ):
            self.assertIn(command, help_text)

    def test_cli_archive_print_path_is_exactly_one_path_line(self) -> None:
        completed = self.run_cli(
            "archive",
            "--label",
            "qqe-research",
            "--source",
            str(self.spot_source),
            "--output-root",
            str(self.output_root),
            "--print-path",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(completed.stdout.splitlines()), 1)
        self.assertTrue(Path(completed.stdout.strip()).is_dir())

    def test_cli_error_is_fixed_and_does_not_print_secret_or_paths(self) -> None:
        bundle = self.create_service_bundle()
        secret = "SUPER-SECRET-BTC/USDT"
        (bundle / "manifest.json").write_text(secret, encoding="utf-8")
        completed = self.run_cli("verify", "--bundle", str(bundle))
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "SQLite state operation failed\n")
        self.assertNotIn(secret, completed.stdout + completed.stderr)
        self.assertNotIn(str(self.root), completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
