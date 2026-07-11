from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
import inspect
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
        return sqlite_state._create_service_backup(
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

    def replace_directory(self, directory: Path, moved_directory: Path) -> None:
        directory.rename(moved_directory)
        directory.mkdir(parents=True)

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(Path(sqlite_state.__file__)), *arguments],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_resolve_service_lane_derives_spot_and_futures_from_manifest(self) -> None:
        spot = sqlite_state._resolve_service_lane(
            service="freqtrade", root=self.root, manifest_path=self.manifest_path
        )
        futures = sqlite_state._resolve_service_lane(
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
                    sqlite_state._resolve_service_lane(
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
            sqlite_state._resolve_service_lane(
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
        self.assertEqual(manifest["creation_platform"], sqlite_state._creation_platform())
        self.assertEqual(manifest["durability"], sqlite_state._new_bundle_durability())
        verified = sqlite_state.verify_bundle(bundle)
        self.assertIsInstance(verified, sqlite_state.VerifiedBundle)
        self.assertEqual(verified.service, "freqtrade")

    def test_schema2_archive_bundle_has_archive_identity(self) -> None:
        verified = sqlite_state.verify_bundle(self.create_archive_bundle())
        self.assertEqual(verified.schema_version, 2)
        self.assertEqual(verified.purpose, "archive")
        self.assertIsNone(verified.service)
        self.assertEqual(verified.archive_label, "qqe-research")
        expected = "power-loss-posix" if sqlite_state._is_posix() else "atomic-process-crash"
        self.assertEqual(verified.durability, expected)

    def test_schema2_manifest_accepts_only_atomic_process_crash(self) -> None:
        bundle = self.create_service_bundle()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        (bundle / sqlite_state.COMPLETION_FILENAME).unlink(missing_ok=True)

        for durability in ("unknown", "power-loss-posix"):
            with self.subTest(durability=durability):
                manifest["durability"] = durability
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(sqlite_state.StateBundleError, "durability"):
                    sqlite_state.verify_bundle(bundle)

    def test_schema1_verifies_with_unknown_durability_and_requires_legacy_flag(self) -> None:
        bundle = self.create_service_bundle()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field in ("purpose", "archive_label", "creation_platform", "durability"):
            del manifest[field]
        manifest["schema_version"] = 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (bundle / sqlite_state.COMPLETION_FILENAME).unlink(missing_ok=True)

        verified = sqlite_state.verify_bundle(bundle)
        self.assertEqual(verified.durability, "unknown")
        self.assertIsNone(verified.creation_platform)
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "legacy"):
            sqlite_state._restore_service(
                service="freqtrade",
                bundle=bundle,
                root=self.root,
                manifest_path=self.manifest_path,
            )
        sqlite_state._restore_service(
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
                sqlite_state._restore_service(
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
                sqlite_state._restore_service(
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
                sqlite_state._restore_service(
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
        (bundle / sqlite_state.COMPLETION_FILENAME).unlink(missing_ok=True)
        with mock.patch.object(tempfile, "mkstemp") as mkstemp:
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "source filename"):
                sqlite_state._restore_service(
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
            sqlite_state._restore_service(
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
                sqlite_state._restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        self.assertEqual(self.spot_destination.read_bytes(), b"keep")
        self.assertEqual(len(list(self.spot_destination.parent.glob("*.tmp"))), 1)

    def test_restore_service_refuses_missing_destination_parent(self) -> None:
        bundle = self.create_service_bundle()
        shutil.rmtree(self.spot_destination.parent)
        with mock.patch.object(tempfile, "mkstemp") as mkstemp:
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "parent"):
                sqlite_state._restore_service(
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

    def test_schema2_discriminators_reject_non_strings_with_fixed_cli_error(self) -> None:
        bundle = self.create_service_bundle()
        manifest_path = bundle / "manifest.json"
        original = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field in ("purpose", "creation_platform", "durability"):
            for invalid in ([], {}, 7, True, None):
                with self.subTest(field=field, invalid=invalid):
                    manifest = dict(original)
                    manifest[field] = invalid
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    completed = self.run_cli("verify", "--bundle", str(bundle))
                    self.assertEqual(completed.returncode, 1)
                    self.assertEqual(completed.stdout, "")
                    self.assertEqual(
                        completed.stderr, "SQLite state operation failed\n"
                    )

    def test_source_filename_must_be_a_portable_ordinary_basename(self) -> None:
        bundle = self.create_service_bundle()
        manifest_path = bundle / "manifest.json"
        original = json.loads(manifest_path.read_text(encoding="utf-8"))
        invalid_names = (
            "dir/database.sqlite",
            r"dir\database.sqlite",
            r"C:\database.sqlite",
            r"\\server\share\database.sqlite",
            "/database.sqlite",
            ".",
            "..",
        )
        for invalid in invalid_names:
            with self.subTest(invalid=invalid):
                manifest = dict(original)
                manifest["source_filename"] = invalid
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(sqlite_state.StateBundleError, "types"):
                    sqlite_state.verify_bundle(bundle)

    def test_service_backup_rejects_source_parent_swap_before_read(self) -> None:
        original_mkdtemp = tempfile.mkdtemp
        moved_parent = self.root / "original-source-parent"

        def swap_source_parent(**kwargs: object) -> str:
            staging = original_mkdtemp(**kwargs)
            self.replace_directory(self.spot_source.parent, moved_parent)
            self.create_database(self.spot_source)
            return staging

        with (
            mock.patch.object(tempfile, "mkdtemp", side_effect=swap_source_parent),
            mock.patch.object(sqlite_state, "online_backup") as online_backup,
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "changed"):
                self.create_service_bundle()
        online_backup.assert_not_called()
        self.assertEqual(len(list(self.output_root.glob(".freqtrade-*"))), 1)

    def test_restore_rejects_destination_parent_swap_before_temporary_io(self) -> None:
        bundle = self.create_service_bundle()
        moved_parent = self.root / "original-destination-parent"

        def swap_destination_parent(_path: Path) -> bool:
            self.replace_directory(self.spot_destination.parent, moved_parent)
            return False

        with (
            mock.patch.object(os.path, "lexists", side_effect=swap_destination_parent),
            mock.patch.object(tempfile, "mkstemp") as mkstemp,
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "changed"):
                sqlite_state._restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        mkstemp.assert_not_called()
        self.assertFalse(self.spot_destination.exists())

    def test_restore_rejects_destination_parent_swap_before_publication(self) -> None:
        bundle = self.create_service_bundle()
        moved_parent = self.root / "original-destination-parent"
        original_inspect = sqlite_state.inspect_database
        swapped = False

        def inspect_then_swap(path: Path) -> dict[str, object]:
            nonlocal swapped
            inspected = original_inspect(path)
            if path.suffix == ".tmp" and not swapped:
                swapped = True
                self.replace_directory(self.spot_destination.parent, moved_parent)
            return inspected

        with mock.patch.object(
            sqlite_state, "inspect_database", side_effect=inspect_then_swap
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "changed"):
                sqlite_state._restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        self.assertFalse(self.spot_destination.exists())
        self.assertEqual(len(list(moved_parent.glob("*.tmp"))), 1)

    def test_restore_failure_does_not_unlink_substituted_temporary_name(self) -> None:
        bundle = self.create_service_bundle()
        quarantined_database = self.root / "created-restore-temp.sqlite"
        replacement_contents = b"unrelated replacement"
        original_inspect = sqlite_state.inspect_database

        def replace_temporary_then_fail(path: Path) -> dict[str, object]:
            if path.suffix == ".tmp":
                path.rename(quarantined_database)
                path.write_bytes(replacement_contents)
                raise sqlite_state.StateBundleError("copied database rejected")
            return original_inspect(path)

        with mock.patch.object(
            sqlite_state, "inspect_database", side_effect=replace_temporary_then_fail
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "copied"):
                sqlite_state._restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        replacement = next(self.spot_destination.parent.glob("*.tmp"))
        self.assertEqual(replacement.read_bytes(), replacement_contents)
        self.assertTrue(quarantined_database.is_file())
        self.assertFalse(self.spot_destination.exists())

    def test_successful_restore_retains_same_inode_post_publication_quarantine(self) -> None:
        bundle = self.create_service_bundle()
        sqlite_state._restore_service(
            service="freqtrade",
            bundle=bundle,
            root=self.root,
            manifest_path=self.manifest_path,
        )
        quarantined = list(self.spot_destination.parent.glob("*.tmp"))
        self.assertEqual(len(quarantined), 1)
        self.assertTrue(os.path.samefile(quarantined[0], self.spot_destination))

    def test_restore_failure_has_no_validate_then_unlink_fallback(self) -> None:
        bundle = self.create_service_bundle()
        moved_parent = self.root / "original-destination-parent"
        original_inspect = sqlite_state.inspect_database
        original_capture = sqlite_state._capture_path_identity
        fallback_called = False

        def inspect_then_swap(path: Path) -> dict[str, object]:
            inspected = original_inspect(path)
            if path.suffix == ".tmp":
                self.replace_directory(self.spot_destination.parent, moved_parent)
            return inspected

        def detect_fallback(*args: object, **kwargs: object) -> object:
            nonlocal fallback_called
            if kwargs.get("description") == "temporary restore parent":
                fallback_called = True
            return original_capture(*args, **kwargs)

        with (
            mock.patch.object(
                sqlite_state, "inspect_database", side_effect=inspect_then_swap
            ),
            mock.patch.object(
                sqlite_state, "_capture_path_identity", side_effect=detect_fallback
            ),
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "changed"):
                sqlite_state._restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        self.assertFalse(fallback_called)
        self.assertEqual(len(list(moved_parent.glob("*.tmp"))), 1)

    def test_restore_failure_does_not_unlink_through_replaced_cleanup_root(self) -> None:
        bundle = self.create_service_bundle()
        moved_root = self.root.parent / f"{self.root.name}-original"
        self.addCleanup(shutil.rmtree, moved_root, True)
        original_inspect = sqlite_state.inspect_database
        replacement_contents = b"unrelated root replacement"

        def replace_root_then_fail(path: Path) -> dict[str, object]:
            inspected = original_inspect(path)
            if path.suffix == ".tmp":
                self.root.rename(moved_root)
                path.parent.mkdir(parents=True)
                path.write_bytes(replacement_contents)
                raise sqlite_state.StateBundleError("publication control failed")
            return inspected

        with mock.patch.object(
            sqlite_state, "inspect_database", side_effect=replace_root_then_fail
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "publication"):
                sqlite_state._restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        replacement = next(self.spot_destination.parent.glob("*.tmp"))
        self.assertEqual(replacement.read_bytes(), replacement_contents)
        moved_temporary_parent = (
            moved_root / "ft_userdata/runtime/freqtrade"
        )
        self.assertEqual(len(list(moved_temporary_parent.glob("*.tmp"))), 1)

    def test_failed_backup_retains_staging_and_failed_restore_quarantines_temp(self) -> None:
        with mock.patch.object(
            sqlite_state, "inspect_database", side_effect=ValueError("bad")
        ):
            with self.assertRaisesRegex(ValueError, "bad"):
                self.create_service_bundle()
        self.assertEqual(len(list(self.output_root.glob(".freqtrade-*"))), 1)

        bundle = self.create_service_bundle()
        original_inspect = sqlite_state.inspect_database

        def reject_temporary(path: Path) -> dict[str, object]:
            if path.suffix == ".tmp":
                raise sqlite_state.StateBundleError("copied database rejected")
            return original_inspect(path)

        with mock.patch.object(sqlite_state, "inspect_database", side_effect=reject_temporary):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "copied"):
                sqlite_state._restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )
        self.assertFalse(self.spot_destination.exists())
        self.assertEqual(len(list(self.spot_destination.parent.glob("*.tmp"))), 1)

    def test_posix_backup_orders_file_and_directory_sync_before_success(self) -> None:
        events: list[str] = []
        original_verify = sqlite_state._verify_bundle_contents
        original_replace = os.replace

        def record_file_sync(path: Path) -> None:
            if path.name in {"database.sqlite", "manifest.json"}:
                events.append(f"file:{path.name}")
            else:
                events.append("file:completion")

        def record_directory_sync(path: Path) -> None:
            if path.name.startswith(".freqtrade-"):
                point = "directory:staging"
            elif path == self.output_root:
                point = "directory:output"
            else:
                point = "directory:final"
            events.append(point)

        def record_verify(bundle: Path) -> sqlite_state.VerifiedBundle:
            events.append("verify")
            return original_verify(bundle)

        def record_replace(source: Path, destination: Path) -> None:
            if source.name.startswith(f".{sqlite_state.COMPLETION_FILENAME}.pending-"):
                events.append("replace:completion")
            else:
                events.append("replace:bundle")
            original_replace(source, destination)

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file", side_effect=record_file_sync),
            mock.patch.object(
                sqlite_state, "_sync_directory", side_effect=record_directory_sync
            ),
            mock.patch.object(
                sqlite_state, "_verify_bundle_contents", side_effect=record_verify
            ),
            mock.patch.object(os, "replace", side_effect=record_replace),
        ):
            bundle = self.create_service_bundle()

        self.assertEqual(
            events,
            [
                "file:database.sqlite",
                "file:manifest.json",
                "verify",
                "directory:staging",
                "replace:bundle",
                "directory:output",
                "file:completion",
                "replace:completion",
                "directory:final",
                "verify",
            ],
        )
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["durability"], "atomic-process-crash")
        self.assertEqual(sqlite_state.verify_bundle(bundle).durability, "power-loss-posix")

    def test_posix_restore_orders_file_and_directory_sync_before_success(self) -> None:
        bundle = self.create_service_bundle()
        verified = sqlite_state.verify_bundle(bundle)
        parent_identity = sqlite_state._capture_path_identity(
            self.spot_destination.parent,
            description="destination parent",
            expected_kind="directory",
        )
        events: list[str] = []
        original_link = os.link

        def record_file_sync(path: Path) -> None:
            events.append("file:temporary")

        def record_directory_sync(path: Path) -> None:
            self.assertEqual(path, self.spot_destination.parent)
            events.append("directory:parent")

        def record_link(source: Path, destination: Path) -> None:
            events.append("link")
            original_link(source, destination)

        original_inspect = sqlite_state.inspect_database

        def record_inspect(path: Path) -> dict[str, object]:
            events.append("verify")
            return original_inspect(path)

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file", side_effect=record_file_sync),
            mock.patch.object(
                sqlite_state, "_sync_directory", side_effect=record_directory_sync
            ),
            mock.patch.object(sqlite_state, "inspect_database", side_effect=record_inspect),
            mock.patch.object(os, "link", side_effect=record_link),
        ):
            sqlite_state._restore_verified_bundle(
                bundle,
                self.spot_destination,
                verified,
                parent_identity,
            )

        self.assertEqual(
            events,
            [
                "file:temporary",
                "verify",
                "link",
                "directory:parent",
                "directory:parent",
            ],
        )
        quarantined = list(self.spot_destination.parent.glob("*.tmp"))
        self.assertEqual(len(quarantined), 1)
        self.assertTrue(os.path.samefile(quarantined[0], self.spot_destination))

    def test_posix_backup_output_root_sync_failure_raises_and_quarantines_published_bundle(
        self,
    ) -> None:
        directory_sync_count = 0

        def fail_output_root_sync(_path: Path) -> None:
            nonlocal directory_sync_count
            directory_sync_count += 1
            if directory_sync_count == 2:
                raise OSError("injected output root sync failure")

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(
                sqlite_state, "_sync_directory", side_effect=fail_output_root_sync
            ),
        ):
            with self.assertRaisesRegex(OSError, "output root sync"):
                self.create_service_bundle()

        self.assertEqual(list(self.output_root.glob("*-freqtrade")), [])
        quarantines = list(self.output_root.glob("*.quarantine-*"))
        self.assertEqual(len(quarantines), 1)
        self.assertTrue((quarantines[0] / "database.sqlite").is_file())
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "quarantin"):
            sqlite_state.verify_bundle(quarantines[0])

    def test_posix_restore_first_parent_sync_failure_raises_and_quarantines_destination(
        self,
    ) -> None:
        bundle = self.create_service_bundle()

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(
                sqlite_state,
                "_sync_directory",
                side_effect=OSError("injected first parent sync failure"),
            ),
        ):
            with self.assertRaisesRegex(OSError, "first parent sync"):
                sqlite_state._restore_service(
                    service="freqtrade",
                    bundle=bundle,
                    root=self.root,
                    manifest_path=self.manifest_path,
                )

        self.assertTrue(self.spot_destination.is_file())
        quarantined = list(self.spot_destination.parent.glob("*.tmp"))
        self.assertEqual(len(quarantined), 1)
        self.assertTrue(os.path.samefile(quarantined[0], self.spot_destination))

    def test_windows_schema2_reports_atomic_process_crash(self) -> None:
        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=False),
            mock.patch.object(sqlite_state, "_sync_file") as sync_file,
            mock.patch.object(sqlite_state, "_sync_directory") as sync_directory,
        ):
            bundle = self.create_service_bundle()
            manifest = json.loads(
                (bundle / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["durability"], "atomic-process-crash")
            self.assertEqual(
                [call.args[0].name for call in sync_file.call_args_list],
                ["database.sqlite", "manifest.json"],
            )
            sync_directory.assert_not_called()

            sqlite_state._restore_service(
                service="freqtrade",
                bundle=bundle,
                root=self.root,
                manifest_path=self.manifest_path,
            )
            self.assertTrue(sync_file.call_args_list[-1].args[0].name.endswith(".tmp"))
            sync_directory.assert_not_called()

    def test_posix_backup_each_sync_failure_fails_closed(self) -> None:
        sync_points = (
            "database",
            "manifest",
            "staging",
            "output",
            "completion",
            "completion-directory",
        )
        for target in sync_points:
            with self.subTest(target=target):
                shutil.rmtree(self.output_root, ignore_errors=True)
                events: list[str] = []
                directory_sync_count = 0
                injected = False

                def maybe_fail_file(path: Path) -> None:
                    nonlocal injected
                    if path.name == "database.sqlite":
                        point = "database"
                    elif path.name == "manifest.json":
                        point = "manifest"
                    else:
                        point = "completion"
                    events.append(point)
                    if point == target and not injected:
                        injected = True
                        raise OSError(f"injected {target} sync failure")

                def maybe_fail_directory(_path: Path) -> None:
                    nonlocal directory_sync_count, injected
                    directory_sync_count += 1
                    point = {
                        1: "staging",
                        2: "output",
                    }.get(directory_sync_count, "completion-directory")
                    events.append(point)
                    if point == target and not injected:
                        injected = True
                        raise OSError(f"injected {target} sync failure")

                with (
                    mock.patch.object(sqlite_state, "_is_posix", return_value=True),
                    mock.patch.object(
                        sqlite_state, "_sync_file", side_effect=maybe_fail_file
                    ),
                    mock.patch.object(
                        sqlite_state,
                        "_sync_directory",
                        side_effect=maybe_fail_directory,
                    ),
                ):
                    with self.assertRaisesRegex(OSError, f"{target} sync"):
                        self.create_service_bundle()

                self.assertIn(target, events)
                published = list(self.output_root.glob("*-freqtrade"))
                staging = list(self.output_root.glob(".freqtrade-*"))
                quarantines = list(self.output_root.glob("*.quarantine-*"))
                self.assertEqual(published, [])
                prepublication = target in {"database", "manifest", "staging"}
                self.assertEqual(len(staging), 1 if prepublication else 0)
                self.assertEqual(len(quarantines), 0 if prepublication else 1)

    def test_posix_restore_each_sync_failure_fails_closed_with_quarantine(self) -> None:
        bundle = self.create_service_bundle()
        for target_call in (1, 2, 3):
            with self.subTest(target_call=target_call):
                if self.spot_destination.exists():
                    self.spot_destination.unlink()
                for temporary in self.spot_destination.parent.glob("*.tmp"):
                    temporary.unlink()
                sync_call = 0

                def maybe_fail(_path: Path) -> None:
                    nonlocal sync_call
                    sync_call += 1
                    if sync_call == target_call:
                        raise OSError(f"injected restore sync {target_call} failure")

                with (
                    mock.patch.object(sqlite_state, "_is_posix", return_value=True),
                    mock.patch.object(sqlite_state, "_sync_file", side_effect=maybe_fail),
                    mock.patch.object(
                        sqlite_state, "_sync_directory", side_effect=maybe_fail
                    ),
                ):
                    with self.assertRaisesRegex(OSError, f"restore sync {target_call}"):
                        sqlite_state._restore_service(
                            service="freqtrade",
                            bundle=bundle,
                            root=self.root,
                            manifest_path=self.manifest_path,
                        )

                quarantined = list(self.spot_destination.parent.glob("*.tmp"))
                self.assertEqual(len(quarantined), 1)
                self.assertEqual(self.spot_destination.exists(), target_call > 1)
                if target_call > 1:
                    self.assertTrue(
                        os.path.samefile(quarantined[0], self.spot_destination)
                    )

    @unittest.skipUnless(os.name == "posix", "POSIX durability helper smoke")
    def test_posix_real_file_and_directory_sync_helpers_accept_temp_paths(self) -> None:
        sync_root = self.root / "sync-smoke"
        sync_root.mkdir()
        sync_file = sync_root / "file.txt"
        sync_file.write_text("durable", encoding="utf-8")

        sqlite_state._sync_file(sync_file)
        sqlite_state._sync_directory(sync_root)

    def test_sync_helpers_use_exact_platform_flags_and_descriptor_lifecycle(self) -> None:
        path = self.root / "sync-target"
        directory_flag = 0x10000
        binary_flag = 0x8000
        cases = (
            ("posix-file", True, sqlite_state._sync_file, os.O_RDONLY),
            ("windows-file", False, sqlite_state._sync_file, os.O_RDWR | binary_flag),
            (
                "posix-directory",
                True,
                sqlite_state._sync_directory,
                os.O_RDONLY | directory_flag,
            ),
        )
        for name, is_posix, helper, expected_flags in cases:
            with self.subTest(name=name):
                with (
                    mock.patch.object(sqlite_state, "_is_posix", return_value=is_posix),
                    mock.patch.object(os, "O_BINARY", binary_flag, create=True),
                    mock.patch.object(os, "O_DIRECTORY", directory_flag, create=True),
                    mock.patch.object(os, "open", return_value=41) as open_file,
                    mock.patch.object(os, "fsync") as fsync,
                    mock.patch.object(os, "close") as close,
                ):
                    helper(path)

                open_file.assert_called_once_with(path, expected_flags)
                fsync.assert_called_once_with(41)
                close.assert_called_once_with(41)

    def test_sync_helpers_close_on_fsync_failure_and_stop_on_open_failure(self) -> None:
        path = self.root / "sync-target"
        for helper in (sqlite_state._sync_file, sqlite_state._sync_directory):
            with self.subTest(helper=helper.__name__, failure="fsync"):
                with (
                    mock.patch.object(os, "open", return_value=73),
                    mock.patch.object(
                        os, "fsync", side_effect=OSError("injected fsync failure")
                    ) as fsync,
                    mock.patch.object(os, "close") as close,
                ):
                    with self.assertRaisesRegex(OSError, "fsync failure"):
                        helper(path)
                fsync.assert_called_once_with(73)
                close.assert_called_once_with(73)

            with self.subTest(helper=helper.__name__, failure="open"):
                with (
                    mock.patch.object(
                        os, "open", side_effect=OSError("injected open failure")
                    ),
                    mock.patch.object(os, "fsync") as fsync,
                    mock.patch.object(os, "close") as close,
                ):
                    with self.assertRaisesRegex(OSError, "open failure"):
                        helper(path)
                fsync.assert_not_called()
                close.assert_not_called()

    def test_posix_completion_promotes_weak_manifest_only_after_success(self) -> None:
        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(sqlite_state, "_sync_directory"),
        ):
            bundle = self.create_service_bundle()
            manifest = json.loads(
                (bundle / "manifest.json").read_text(encoding="utf-8")
            )
            completion = json.loads(
                (bundle / sqlite_state.COMPLETION_FILENAME).read_text(encoding="utf-8")
            )
            verified = sqlite_state.verify_bundle(bundle)

        self.assertEqual(manifest["durability"], "atomic-process-crash")
        self.assertEqual(completion["durability"], "power-loss-posix")
        self.assertEqual(completion["bundle_name"], bundle.name)
        self.assertEqual(verified.durability, "power-loss-posix")

    def test_posix_failed_output_barrier_quarantines_nonpromotable_completion(
        self,
    ) -> None:
        directory_sync_count = 0

        def fail_final_output_sync(_path: Path) -> None:
            nonlocal directory_sync_count
            directory_sync_count += 1
            if directory_sync_count == 2:
                raise OSError("injected final output sync failure")

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(
                sqlite_state, "_sync_directory", side_effect=fail_final_output_sync
            ),
        ):
            with self.assertRaisesRegex(OSError, "final output sync"):
                self.create_service_bundle()

        self.assertEqual(list(self.output_root.glob("*-freqtrade")), [])
        quarantines = list(self.output_root.glob("*.quarantine-*"))
        self.assertEqual(len(quarantines), 1)
        manifest = json.loads(
            (quarantines[0] / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["durability"], "atomic-process-crash")
        self.assertFalse((quarantines[0] / sqlite_state.COMPLETION_FILENAME).exists())
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "quarantin"):
            sqlite_state.verify_bundle(quarantines[0])

    def test_backup_failure_never_removes_replacement_at_vacated_staging_path(
        self,
    ) -> None:
        original_replace = os.replace
        vacated_staging: Path | None = None
        replacement_contents = b"unrelated replacement"

        def replace_then_substitute(source: Path, destination: Path) -> None:
            nonlocal vacated_staging
            original_replace(source, destination)
            if source.name.startswith(".freqtrade-"):
                vacated_staging = source
                source.mkdir()
                (source / "unrelated.txt").write_bytes(replacement_contents)

        directory_sync_count = 0

        def fail_final_output_sync(_path: Path) -> None:
            nonlocal directory_sync_count
            directory_sync_count += 1
            if directory_sync_count == 2:
                raise OSError("injected final output sync failure")

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(os, "replace", side_effect=replace_then_substitute),
            mock.patch.object(
                sqlite_state, "_sync_directory", side_effect=fail_final_output_sync
            ),
        ):
            with self.assertRaisesRegex(OSError, "final output sync"):
                self.create_service_bundle()

        self.assertIsNotNone(vacated_staging)
        self.assertEqual(
            (vacated_staging / "unrelated.txt").read_bytes(), replacement_contents
        )

    def test_verify_bundle_rejects_completion_bound_to_another_bundle_name(self) -> None:
        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(sqlite_state, "_sync_directory"),
        ):
            bundle = self.create_service_bundle()
        completion_path = bundle / sqlite_state.COMPLETION_FILENAME
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
        completion["bundle_name"] = "another-bundle"
        completion_path.write_text(json.dumps(completion), encoding="utf-8")

        with self.assertRaisesRegex(sqlite_state.StateBundleError, "completion"):
            sqlite_state.verify_bundle(bundle)

    def test_completion_record_rejects_exact_field_type_hash_platform_and_name_mutations(
        self,
    ) -> None:
        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(sqlite_state, "_sync_directory"),
        ):
            bundle = self.create_service_bundle()
        completion_path = bundle / sqlite_state.COMPLETION_FILENAME
        original = json.loads(completion_path.read_text(encoding="utf-8"))
        self.assertEqual(set(original), sqlite_state.COMPLETION_FIELDS)
        self.assertEqual(original["creation_platform"], "posix")
        mutations = {
            "extra-field": {**original, "extra": "value"},
            "schema-type": {**original, "schema_version": True},
            "durability-type": {**original, "durability": True},
            "hash": {**original, "manifest_sha256": "0" * 64},
            "platform": {**original, "creation_platform": "windows"},
            "platform-type": {**original, "creation_platform": True},
            "name": {**original, "bundle_name": "another-bundle"},
            "name-type": {**original, "bundle_name": True},
        }

        for label, completion in mutations.items():
            with self.subTest(label=label):
                completion_path.write_text(json.dumps(completion), encoding="utf-8")
                with self.assertRaisesRegex(sqlite_state.StateBundleError, "completion"):
                    sqlite_state.verify_bundle(bundle)
        completion_path.write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(sqlite_state.verify_bundle(bundle).durability, "power-loss-posix")

    def test_verify_fails_creation_in_progress_while_creator_holds_final_barrier_lock(
        self,
    ) -> None:
        reached_boundaries: list[str] = []
        observed_contention: list[str] = []
        original_replace = os.replace

        def observe_final_barrier(path: Path) -> None:
            if path.name.endswith("-freqtrade"):
                reached_boundaries.append("final-fsync")
                try:
                    sqlite_state.verify_bundle(path)
                except sqlite_state.StateBundleError as error:
                    observed_contention.append(str(error))

        def observe_completion_rename(source: Path, destination: Path) -> None:
            original_replace(source, destination)
            if destination.name == sqlite_state.COMPLETION_FILENAME:
                reached_boundaries.append("completion-rename")
                try:
                    sqlite_state.verify_bundle(destination.parent)
                except sqlite_state.StateBundleError as error:
                    observed_contention.append(str(error))

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(
                sqlite_state, "_sync_directory", side_effect=observe_final_barrier
            ),
            mock.patch.object(os, "replace", side_effect=observe_completion_rename),
        ):
            bundle = self.create_service_bundle()

        self.assertEqual(reached_boundaries, ["completion-rename", "final-fsync"])
        self.assertEqual(
            observed_contention,
            ["state bundle creation in progress", "state bundle creation in progress"],
        )
        self.assertEqual(sqlite_state.verify_bundle(bundle).durability, "power-loss-posix")

    def test_creation_lock_releases_after_success_and_every_exception(self) -> None:
        final_name = "20260711T000000Z-freqtrade"
        lock_path = self.output_root / f".{final_name}.creation.lock"

        bundle = self.create_service_bundle()
        with sqlite_state._bundle_lock(lock_path, exclusive=True, blocking=False):
            self.assertTrue(bundle.is_dir())

        shutil.rmtree(self.output_root)
        with mock.patch.object(
            sqlite_state, "online_backup", side_effect=OSError("injected construction failure")
        ):
            with self.assertRaisesRegex(OSError, "construction failure"):
                self.create_service_bundle()
        with sqlite_state._bundle_lock(lock_path, exclusive=True, blocking=False):
            pass

        shutil.rmtree(self.output_root)
        directory_sync_count = 0

        def fail_after_publication(_path: Path) -> None:
            nonlocal directory_sync_count
            directory_sync_count += 1
            if directory_sync_count == 2:
                raise OSError("injected publication failure")

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(
                sqlite_state, "_sync_directory", side_effect=fail_after_publication
            ),
        ):
            with self.assertRaisesRegex(OSError, "publication failure"):
                self.create_service_bundle()
        with sqlite_state._bundle_lock(lock_path, exclusive=True, blocking=False):
            pass

    def test_unsupported_creation_lock_fails_before_staging(self) -> None:
        with mock.patch.object(sqlite_state.os, "name", "unsupported"):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "locking unavailable"):
                self.create_service_bundle()
        self.assertEqual(list(self.output_root.glob(".freqtrade-*")), [])
        self.assertEqual(list(self.output_root.glob("*-freqtrade")), [])

    def test_intrinsic_failure_record_rejects_quarantine_and_restored_original_name(
        self,
    ) -> None:
        directory_sync_count = 0

        def fail_completion_directory(_path: Path) -> None:
            nonlocal directory_sync_count
            directory_sync_count += 1
            if directory_sync_count == 3:
                raise OSError("injected completion directory failure")

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(
                sqlite_state, "_sync_directory", side_effect=fail_completion_directory
            ),
        ):
            with self.assertRaisesRegex(OSError, "completion directory failure"):
                self.create_service_bundle()

        quarantine = next(self.output_root.glob("*.quarantine-*"))
        failure_path = quarantine / sqlite_state.FAILURE_FILENAME
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        self.assertEqual(failure["state"], "failed")
        self.assertEqual(failure["creation_platform"], "posix")
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "failed"):
            sqlite_state.verify_bundle(quarantine)

        original = self.output_root / failure["bundle_name"]
        quarantine.rename(original)
        with self.assertRaisesRegex(sqlite_state.StateBundleError, "failed"):
            sqlite_state.verify_bundle(original)

    def test_failure_state_file_and_directory_barriers_precede_quarantine(self) -> None:
        events: list[str] = []
        directory_sync_count = 0
        original_replace = os.replace

        def record_file(path: Path) -> None:
            if path.name == sqlite_state.FAILURE_FILENAME:
                events.append("file:failure")

        def fail_then_record_directories(path: Path) -> None:
            nonlocal directory_sync_count
            directory_sync_count += 1
            if directory_sync_count == 3:
                events.append("failure-trigger")
                raise OSError("injected completion barrier failure")
            if path.name.endswith("-freqtrade") and "failure-trigger" in events:
                events.append("directory:failure")
            elif path == self.output_root and "replace:quarantine" in events:
                events.append("directory:quarantine-root")

        def record_replace(source: Path, destination: Path) -> None:
            if ".quarantine-" in destination.name:
                events.append("replace:quarantine")
            original_replace(source, destination)

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file", side_effect=record_file),
            mock.patch.object(
                sqlite_state, "_sync_directory", side_effect=fail_then_record_directories
            ),
            mock.patch.object(os, "replace", side_effect=record_replace),
        ):
            with self.assertRaisesRegex(OSError, "completion barrier failure"):
                self.create_service_bundle()

        self.assertEqual(
            events[-5:],
            [
                "failure-trigger",
                "file:failure",
                "directory:failure",
                "replace:quarantine",
                "directory:quarantine-root",
            ],
        )

    def test_quarantine_root_sync_failure_keeps_intrinsic_failure_and_releases_lock(
        self,
    ) -> None:
        directory_sync_count = 0

        def fail_completion_and_quarantine_root(_path: Path) -> None:
            nonlocal directory_sync_count
            directory_sync_count += 1
            if directory_sync_count == 3:
                raise OSError("injected completion failure")
            if directory_sync_count == 5:
                raise OSError("injected quarantine root failure")

        with (
            mock.patch.object(sqlite_state, "_is_posix", return_value=True),
            mock.patch.object(sqlite_state, "_sync_file"),
            mock.patch.object(
                sqlite_state,
                "_sync_directory",
                side_effect=fail_completion_and_quarantine_root,
            ),
        ):
            with self.assertRaisesRegex(sqlite_state.StateBundleError, "quarantine failed"):
                self.create_service_bundle()

        quarantine = next(self.output_root.glob("*.quarantine-*"))
        self.assertTrue((quarantine / sqlite_state.FAILURE_FILENAME).is_file())
        lock_path = self.output_root / ".20260711T000000Z-freqtrade.creation.lock"
        with sqlite_state._bundle_lock(lock_path, exclusive=True, blocking=False):
            pass

    def test_failure_record_file_and_directory_barrier_failures_remain_nonpromotable(
        self,
    ) -> None:
        for target in ("failure-file", "failure-directory"):
            with self.subTest(target=target):
                shutil.rmtree(self.output_root, ignore_errors=True)
                directory_sync_count = 0
                failure_file_seen = False

                def maybe_fail_file(path: Path) -> None:
                    nonlocal failure_file_seen
                    if path.name == sqlite_state.FAILURE_FILENAME:
                        failure_file_seen = True
                        if target == "failure-file":
                            raise OSError("injected failure record file barrier")

                def maybe_fail_directory(path: Path) -> None:
                    nonlocal directory_sync_count
                    directory_sync_count += 1
                    if directory_sync_count == 3:
                        raise OSError("injected completion directory barrier")
                    if (
                        target == "failure-directory"
                        and failure_file_seen
                        and path.name.endswith("-freqtrade")
                    ):
                        raise OSError("injected failure record directory barrier")

                with (
                    mock.patch.object(sqlite_state, "_is_posix", return_value=True),
                    mock.patch.object(
                        sqlite_state, "_sync_file", side_effect=maybe_fail_file
                    ),
                    mock.patch.object(
                        sqlite_state,
                        "_sync_directory",
                        side_effect=maybe_fail_directory,
                    ),
                ):
                    with self.assertRaisesRegex(
                        sqlite_state.StateBundleError, "failure recording failed"
                    ):
                        self.create_service_bundle()

                quarantine = next(self.output_root.glob("*.quarantine-*"))
                self.assertTrue((quarantine / sqlite_state.FAILURE_FILENAME).is_file())
                with self.assertRaisesRegex(sqlite_state.StateBundleError, "failed"):
                    sqlite_state.verify_bundle(quarantine)
                lock_path = (
                    self.output_root / ".20260711T000000Z-freqtrade.creation.lock"
                )
                with sqlite_state._bundle_lock(
                    lock_path, exclusive=True, blocking=False
                ):
                    pass

    def test_low_level_lock_adapters_use_shared_exclusive_nonblocking_and_release(self) -> None:
        posix = mock.Mock()
        posix.LOCK_EX = 1
        posix.LOCK_SH = 2
        posix.LOCK_NB = 4
        posix.LOCK_UN = 8
        sqlite_state._acquire_posix_lock(posix, 17, exclusive=True, blocking=True)
        sqlite_state._acquire_posix_lock(posix, 17, exclusive=False, blocking=False)
        sqlite_state._release_posix_lock(posix, 17)
        self.assertEqual(
            posix.flock.call_args_list,
            [mock.call(17, 1), mock.call(17, 2 | 4), mock.call(17, posix.LOCK_UN)],
        )

        windows = mock.Mock()
        windows.LK_LOCK = 1
        windows.LK_NBLCK = 2
        windows.LK_NBRLCK = 3
        windows.LK_UNLCK = 4
        with mock.patch.object(os, "lseek") as seek:
            sqlite_state._acquire_windows_lock(
                windows, 23, exclusive=True, blocking=True
            )
            sqlite_state._acquire_windows_lock(
                windows, 23, exclusive=False, blocking=False
            )
            sqlite_state._release_windows_lock(windows, 23)
        self.assertEqual(seek.call_args_list, [mock.call(23, 0, os.SEEK_SET)] * 3)
        self.assertEqual(
            windows.locking.call_args_list,
            [mock.call(23, 1, 1), mock.call(23, 3, 1), mock.call(23, 4, 1)],
        )

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

    def test_public_formal_lane_apis_do_not_accept_root_or_manifest_overrides(self) -> None:
        public_apis = (
            sqlite_state.resolve_service_lane,
            sqlite_state.create_service_backup,
            sqlite_state.restore_service,
        )
        for api in public_apis:
            with self.subTest(api=api.__name__):
                parameters = inspect.signature(api).parameters
                self.assertNotIn("root", parameters)
                self.assertNotIn("manifest_path", parameters)

        with self.assertRaises(TypeError):
            sqlite_state.resolve_service_lane(service="freqtrade", root=self.root)
        with self.assertRaises(TypeError):
            sqlite_state.create_service_backup(
                service="freqtrade",
                output_root=self.output_root,
                now=self.fixed_now,
                manifest_path=self.manifest_path,
            )
        with self.assertRaises(TypeError):
            sqlite_state.restore_service(
                service="freqtrade", bundle=self.root / "bundle", root=self.root
            )

        parser = sqlite_state.build_parser()
        for action in parser._actions:
            self.assertNotIn(action.dest, {"root", "manifest_path"})

        rejected_cli_overrides = (
            (
                "backup-service",
                "--service",
                "freqtrade",
                "--output-root",
                str(self.output_root),
                "--root",
                str(self.root),
            ),
            (
                "backup-service",
                "--service",
                "freqtrade",
                "--output-root",
                str(self.output_root),
                "--manifest-path",
                str(self.manifest_path),
            ),
            (
                "backup-service",
                "--service",
                "freqtrade",
                "--output-root",
                str(self.output_root),
                "--source",
                str(self.spot_source),
            ),
            (
                "restore-service",
                "--service",
                "freqtrade",
                "--bundle",
                str(self.root / "bundle"),
                "--destination",
                str(self.spot_destination),
            ),
        )
        for arguments in rejected_cli_overrides:
            with self.subTest(arguments=arguments):
                self.assertEqual(self.run_cli(*arguments).returncode, 2)

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
