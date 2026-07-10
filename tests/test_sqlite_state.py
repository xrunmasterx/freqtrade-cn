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
        self.source = self.root / "tradesv3.sqlite"
        self.output_root = self.root / "backups"
        self.destination = self.root / "restored.sqlite"
        self.fixed_now = datetime(2026, 7, 11, tzinfo=UTC)
        self.create_database(self.source)

    def create_database(
        self,
        path: Path,
        *,
        tables: tuple[str, ...] = sqlite_state.COUNT_TABLES,
    ) -> None:
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

    def open_wal_source(self) -> sqlite3.Connection:
        writer = sqlite3.connect(self.source)
        writer.execute("PRAGMA journal_mode=WAL")
        return writer

    def create_valid_bundle(self) -> Path:
        return sqlite_state.create_backup(
            service="freqtrade",
            source=self.source,
            output_root=self.output_root,
            now=self.fixed_now,
        )

    def copy_source(self) -> Path:
        candidate = self.root / "candidate.sqlite"
        sqlite_state.online_backup(self.source, candidate)
        return candidate

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(Path(sqlite_state.__file__)), *arguments],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_backup_contains_committed_wal_rows_while_writer_stays_open(self) -> None:
        writer = self.open_wal_source()
        self.addCleanup(writer.close)
        writer.execute("INSERT INTO trades(pair) VALUES ('BTC/USDT')")
        writer.commit()

        bundle = self.create_valid_bundle()

        with closing(sqlite3.connect(bundle / "database.sqlite")) as restored:
            self.assertEqual(restored.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 1)

    def test_backup_excludes_uncommitted_rows(self) -> None:
        writer = self.open_wal_source()
        self.addCleanup(writer.close)
        writer.execute("INSERT INTO trades(pair) VALUES ('ETH/USDT')")

        bundle = self.create_valid_bundle()

        with closing(sqlite3.connect(bundle / "database.sqlite")) as backup:
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)
        writer.rollback()

    def test_manifest_hash_size_and_integrity_match_database(self) -> None:
        bundle = self.create_valid_bundle()
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        database = bundle / "database.sqlite"
        self.assertEqual(manifest["database_sha256"], sqlite_state.sha256_file(database))
        self.assertEqual(manifest["database_size"], database.stat().st_size)
        self.assertEqual(manifest["integrity_check"], "ok")
        self.assertEqual(manifest["foreign_key_violations"], 0)

    def test_manifest_has_exact_schema(self) -> None:
        manifest = sqlite_state.verify_bundle(self.create_valid_bundle())
        self.assertEqual(
            set(manifest),
            {
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
            },
        )
        self.assertEqual(manifest["created_at_utc"], "2026-07-11T00:00:00Z")

    def test_verify_rejects_database_tampering(self) -> None:
        bundle = self.create_valid_bundle()
        (bundle / "database.sqlite").write_bytes(b"corrupt")
        with self.assertRaises(sqlite_state.StateBundleError):
            sqlite_state.verify_bundle(bundle)

    def test_verify_rejects_manifest_tampering(self) -> None:
        bundle = self.create_valid_bundle()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["row_counts"]["orders"] = 99
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "metadata mismatch"):
            sqlite_state.verify_bundle(bundle)

    def test_verify_wraps_malformed_manifest_json(self) -> None:
        bundle = self.create_valid_bundle()
        (bundle / "manifest.json").write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "manifest"):
            sqlite_state.verify_bundle(bundle)

    def test_verify_rejects_wrong_manifest_field_type(self) -> None:
        bundle = self.create_valid_bundle()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["database_size"] = str(manifest["database_size"])
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "manifest"):
            sqlite_state.verify_bundle(bundle)

    def test_verify_rejects_missing_or_extra_manifest_field(self) -> None:
        for mutation in ("missing", "extra"):
            with self.subTest(mutation=mutation):
                bundle = self.create_valid_bundle()
                manifest_path = bundle / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if mutation == "missing":
                    del manifest["service"]
                else:
                    manifest["unexpected"] = True
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(sqlite_state.StateBundleError, "manifest"):
                    sqlite_state.verify_bundle(bundle)
                shutil.rmtree(bundle)

    def test_verify_rejects_missing_core_table(self) -> None:
        candidate = self.root / "only-orders.sqlite"
        self.create_database(candidate, tables=("orders",))
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "core-table policy"):
            sqlite_state.inspect_database(candidate)

    def test_backup_does_not_modify_source_hash_or_mtime(self) -> None:
        before_hash = sqlite_state.sha256_file(self.source)
        before_mtime = self.source.stat().st_mtime_ns
        self.create_valid_bundle()
        self.assertEqual(sqlite_state.sha256_file(self.source), before_hash)
        self.assertEqual(self.source.stat().st_mtime_ns, before_mtime)

    def test_backup_rejects_path_traversal_service(self) -> None:
        for service in ("../freqtrade", "..", "freqtrade/escape", "freqtrade\\escape"):
            with self.subTest(service=service):
                with self.assertRaisesRegex(sqlite_state.StateBundleError, "service"):
                    sqlite_state.create_backup(
                        service=service,
                        source=self.source,
                        output_root=self.output_root,
                        now=self.fixed_now,
                    )
        self.assertFalse(self.output_root.exists())

    def test_failed_backup_does_not_publish_bundle_or_leave_staging(self) -> None:
        with mock.patch.object(
            sqlite_state, "inspect_database", side_effect=ValueError("bad")
        ):
            with self.assertRaisesRegex(ValueError, "bad"):
                self.create_valid_bundle()
        self.assertEqual(list(self.output_root.iterdir()), [])

    def test_failed_atomic_publish_does_not_leave_staging(self) -> None:
        with mock.patch.object(os, "replace", side_effect=OSError("publish failed")):
            with self.assertRaisesRegex(OSError, "publish failed"):
                self.create_valid_bundle()
        self.assertEqual(list(self.output_root.iterdir()), [])

    def test_restore_refuses_existing_destination(self) -> None:
        bundle = self.create_valid_bundle()
        self.destination.write_bytes(b"keep")
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "already exists"):
            sqlite_state.restore_bundle(bundle, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"keep")

    def test_restore_verifies_before_creating_destination_parent(self) -> None:
        bundle = self.create_valid_bundle()
        (bundle / "manifest.json").write_text("not-json", encoding="utf-8")
        destination = self.root / "new-parent" / "restored.sqlite"
        with self.assertRaises(sqlite_state.StateBundleError):
            sqlite_state.restore_bundle(bundle, destination)
        self.assertFalse(destination.parent.exists())

    def test_failed_restore_removes_destination_and_temporary_file(self) -> None:
        bundle = self.create_valid_bundle()
        original_inspect = sqlite_state.inspect_database

        def reject_temporary(path: Path) -> dict[str, object]:
            if path.suffix == ".tmp":
                raise sqlite_state.StateBundleError("copied database rejected")
            return original_inspect(path)

        with mock.patch.object(sqlite_state, "inspect_database", side_effect=reject_temporary):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "copied"):
                sqlite_state.restore_bundle(bundle, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob(".restored.sqlite.*.tmp")), [])

    def test_restore_rejects_bundle_database_swapped_after_verification(self) -> None:
        bundle = self.create_valid_bundle()
        swapped = self.root / "swapped.sqlite"
        self.create_database(swapped)
        with closing(sqlite3.connect(swapped)) as connection:
            connection.execute("INSERT INTO orders(id) VALUES (99)")
            connection.commit()
        original_verify = sqlite_state.verify_bundle

        def verify_then_swap(path: Path) -> dict[str, object]:
            manifest = original_verify(path)
            os.replace(swapped, path / "database.sqlite")
            return manifest

        with mock.patch.object(
            sqlite_state, "verify_bundle", side_effect=verify_then_swap
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "metadata mismatch"):
                sqlite_state.restore_bundle(bundle, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob(".restored.sqlite.*.tmp")), [])

    def test_restore_does_not_clobber_destination_created_during_copy(self) -> None:
        bundle = self.create_valid_bundle()
        original_copyfile = shutil.copyfile

        def copy_then_create_destination(source: Path, target: Path) -> str:
            result = original_copyfile(source, target)
            self.destination.write_bytes(b"KEEP-ME")
            return result

        with mock.patch.object(
            shutil, "copyfile", side_effect=copy_then_create_destination
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "already exists"):
                sqlite_state.restore_bundle(bundle, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"KEEP-ME")
        self.assertEqual(list(self.root.glob(".restored.sqlite.*.tmp")), [])

    def test_restore_does_not_clobber_dangling_symlink_created_during_copy(self) -> None:
        bundle = self.create_valid_bundle()
        missing_target = self.root / "missing-target.sqlite"
        original_copyfile = shutil.copyfile

        def copy_then_create_symlink(source: Path, target: Path) -> str:
            result = original_copyfile(source, target)
            self.destination.symlink_to(missing_target)
            return result

        with mock.patch.object(
            shutil, "copyfile", side_effect=copy_then_create_symlink
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "already exists"):
                sqlite_state.restore_bundle(bundle, self.destination)
        self.assertTrue(self.destination.is_symlink())
        link_target = str(Path(os.readlink(self.destination))).removeprefix("\\\\?\\")
        self.assertEqual(Path(link_target), missing_target)
        self.assertFalse(missing_target.exists())
        self.assertEqual(list(self.root.glob(".restored.sqlite.*.tmp")), [])

    def test_restore_reports_cleanup_failure_after_successful_link(self) -> None:
        bundle = self.create_valid_bundle()
        original_unlink = Path.unlink

        def reject_temporary_unlink(
            path: Path, missing_ok: bool = False
        ) -> None:
            if path.name.startswith(".restored.sqlite.") and path.suffix == ".tmp":
                raise PermissionError("temporary unlink blocked")
            original_unlink(path, missing_ok=missing_ok)

        with mock.patch.object(
            Path, "unlink", autospec=True, side_effect=reject_temporary_unlink
        ):
            with self.assertRaisesRegex(
                sqlite_state.StateBundleError, "succeeded but temporary cleanup failed"
            ):
                sqlite_state.restore_bundle(bundle, self.destination)
        self.assertTrue(self.destination.is_file())
        sqlite_state.compare_databases(bundle / "database.sqlite", self.destination)
        self.assertEqual(len(list(self.root.glob(".restored.sqlite.*.tmp"))), 1)

    def test_restore_closes_connections_before_atomic_publish(self) -> None:
        sqlite_state.restore_bundle(self.create_valid_bundle(), self.destination)
        self.assertEqual(list(self.root.glob(".restored.sqlite.*.tmp")), [])
        renamed = self.destination.with_name("renamed.sqlite")
        os.replace(self.destination, renamed)
        self.assertTrue(renamed.is_file())

    def test_compare_detects_core_table_count_mismatch(self) -> None:
        candidate = self.copy_source()
        with closing(sqlite3.connect(candidate)) as connection:
            connection.execute("INSERT INTO orders(id) VALUES (99)")
            connection.commit()
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "orders row count"):
            sqlite_state.compare_databases(self.source, candidate)

    def test_compare_accepts_matching_databases(self) -> None:
        sqlite_state.compare_databases(self.source, self.copy_source())

    def test_cli_four_commands_report_status_without_trade_rows(self) -> None:
        with closing(sqlite3.connect(self.source)) as connection:
            connection.execute("INSERT INTO trades(pair) VALUES ('BTC/USDT')")
            connection.commit()
        backup = self.run_cli(
            "backup",
            "--service",
            "freqtrade-cli",
            "--source",
            str(self.source),
            "--output-root",
            str(self.output_root),
            "--print-path",
        )
        self.assertEqual(backup.returncode, 0, backup.stderr)
        bundle = Path(backup.stdout.strip())
        verify = self.run_cli("verify", "--bundle", str(bundle))
        restore = self.run_cli(
            "restore", "--bundle", str(bundle), "--destination", str(self.destination)
        )
        compare = self.run_cli(
            "compare", "--source", str(self.source), "--candidate", str(self.destination)
        )
        for completed in (backup, verify, restore, compare):
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn("BTC/USDT", completed.stdout)
            self.assertNotIn("BTC/USDT", completed.stderr)
        self.assertIn("verification: OK", verify.stdout)
        self.assertIn("restore: OK", restore.stdout)
        self.assertIn("comparison: OK", compare.stdout)

    def test_cli_error_is_nonzero_and_does_not_print_secret_or_trade_rows(self) -> None:
        secret = "SUPER-SECRET-BTC/USDT"
        bundle = self.create_valid_bundle()
        (bundle / "manifest.json").write_text(secret, encoding="utf-8")
        completed = self.run_cli("verify", "--bundle", str(bundle))
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(secret, completed.stdout + completed.stderr)
        self.assertNotIn("BTC/USDT", completed.stdout + completed.stderr)

    def test_cli_deeply_nested_manifest_has_fixed_safe_error(self) -> None:
        bundle = self.create_valid_bundle()
        secret = "DO-NOT-ECHO-THIS"
        deeply_nested = "[" * 2000 + json.dumps(secret) + "]" * 2000
        (bundle / "manifest.json").write_text(deeply_nested, encoding="utf-8")

        completed = self.run_cli("verify", "--bundle", str(bundle))

        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "SQLite state operation failed\n")
        self.assertNotIn("Traceback", output)
        self.assertNotIn(str(self.root), output)
        self.assertNotIn(secret, output)

if __name__ == "__main__":
    unittest.main()
