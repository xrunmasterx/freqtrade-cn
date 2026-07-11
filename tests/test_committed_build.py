from __future__ import annotations

import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.committed_build import (
    committed_build_context,
    extract_git_archive,
    resolve_commit_identity,
    verify_committed_checkout,
)


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _write(repository: Path, relative_path: str, contents: str) -> None:
    path = repository / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


class GitFixture:
    def __init__(self, directory: Path) -> None:
        self.root = directory / "root"
        self.backend_source = directory / "backend-source"
        self.frontend_source = directory / "frontend-source"
        self._init_repository(self.backend_source, "backend.txt", "backend committed\n")
        self._init_repository(self.frontend_source, "frontend.txt", "frontend committed\n")

        self.root.mkdir()
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "tests@example.invalid")
        _git(self.root, "config", "user.name", "Committed Build Tests")
        _write(self.root, "root.txt", "root committed\n")
        _write(self.root, ".gitignore", "ignored-output/\n*.sqlite\n.env\n")
        for source, name in (
            (self.backend_source, "freqtrade"),
            (self.frontend_source, "frequi"),
        ):
            _git(
                self.root,
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                "-q",
                str(source),
                name,
            )
            _git(self.root / name, "config", "user.email", "tests@example.invalid")
            _git(self.root / name, "config", "user.name", "Committed Build Tests")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-qm", "fixture")

    @staticmethod
    def _init_repository(repository: Path, filename: str, contents: str) -> None:
        repository.mkdir()
        _git(repository, "init", "-q")
        _git(repository, "config", "user.email", "tests@example.invalid")
        _git(repository, "config", "user.name", "Committed Build Tests")
        _write(repository, filename, contents)
        _write(repository, ".gitignore", "ignored-output/\n")
        _git(repository, "add", filename, ".gitignore")
        _git(repository, "commit", "-qm", "fixture")


def _tar_bytes(entries: list[tuple[tarfile.TarInfo, bytes]]) -> io.BytesIO:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for member, contents in entries:
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents) if contents else None)
    stream.seek(0)
    return stream


class CommittedBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.fixture = GitFixture(Path(self.temporary_directory.name))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_resolves_root_and_exact_gitlink_commits(self) -> None:
        identity = resolve_commit_identity(self.fixture.root)

        self.assertEqual(identity.root, _git(self.fixture.root, "rev-parse", "HEAD"))
        self.assertEqual(identity.backend, _git(self.fixture.root, "rev-parse", "HEAD:freqtrade"))
        self.assertEqual(identity.frontend, _git(self.fixture.root, "rev-parse", "HEAD:frequi"))
        self.assertEqual(identity.short_tag(), identity.root[:12])

    def test_rejects_submodule_head_mismatch(self) -> None:
        identity = resolve_commit_identity(self.fixture.root)
        _write(self.fixture.root / "freqtrade", "later.txt", "later\n")
        _git(self.fixture.root / "freqtrade", "add", "later.txt")
        _git(self.fixture.root / "freqtrade", "commit", "-qm", "later")

        with self.assertRaises(ValueError):
            verify_committed_checkout(self.fixture.root, identity)

    def test_rejects_staged_gitlink_index_change(self) -> None:
        identity = resolve_commit_identity(self.fixture.root)
        _write(self.fixture.backend_source, "later.txt", "later\n")
        _git(self.fixture.backend_source, "add", "later.txt")
        _git(self.fixture.backend_source, "commit", "-qm", "later")
        staged_commit = _git(self.fixture.backend_source, "rev-parse", "HEAD")
        _git(
            self.fixture.root,
            "update-index",
            "--cacheinfo",
            f"160000,{staged_commit},freqtrade",
        )

        self.assertEqual(resolve_commit_identity(self.fixture.root), identity)
        checked_out_backend = _git(self.fixture.root / "freqtrade", "rev-parse", "HEAD")
        self.assertEqual(checked_out_backend, identity.backend)
        with self.assertRaises(ValueError):
            verify_committed_checkout(self.fixture.root, identity)

    def test_rejects_tracked_root_backend_or_frontend_changes(self) -> None:
        for relative_repository, filename in (
            (Path(), "root.txt"),
            (Path("freqtrade"), "backend.txt"),
            (Path("frequi"), "frontend.txt"),
        ):
            with self.subTest(repository=str(relative_repository) or "root"):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = GitFixture(Path(directory))
                    identity = resolve_commit_identity(fixture.root)
                    _write(fixture.root / relative_repository, filename, "dirty\n")
                    with self.assertRaises(ValueError):
                        verify_committed_checkout(fixture.root, identity)

    def test_rejects_nonignored_untracked_root_backend_or_frontend_paths(self) -> None:
        for relative_repository in (Path(), Path("freqtrade"), Path("frequi")):
            with self.subTest(repository=str(relative_repository) or "root"):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = GitFixture(Path(directory))
                    identity = resolve_commit_identity(fixture.root)
                    _write(fixture.root / relative_repository, "untracked.txt", "untracked\n")
                    with self.assertRaises(ValueError):
                        verify_committed_checkout(fixture.root, identity)

    def test_ignored_outputs_do_not_enter_context(self) -> None:
        identity = resolve_commit_identity(self.fixture.root)
        _write(self.fixture.root, "ignored-output/cache.bin", "ignored\n")
        _write(self.fixture.root, ".env", "TOKEN=secret\n")
        _write(self.fixture.root / "freqtrade", "ignored-output/backend.bin", "ignored\n")
        _write(self.fixture.root / "frequi", "ignored-output/frontend.bin", "ignored\n")

        with committed_build_context(self.fixture.root, identity) as context:
            self.assertFalse((context / "ignored-output").exists())
            self.assertFalse((context / ".env").exists())
            self.assertFalse((context / "freqtrade" / "ignored-output").exists())
            self.assertFalse((context / "frequi" / "ignored-output").exists())

    def test_context_contains_root_backend_and_frontend_committed_bytes_only(self) -> None:
        identity = resolve_commit_identity(self.fixture.root)

        with committed_build_context(self.fixture.root, identity) as context:
            self.assertEqual((context / "root.txt").read_text(encoding="utf-8"), "root committed\n")
            self.assertEqual(
                (context / "freqtrade" / "backend.txt").read_text(encoding="utf-8"),
                "backend committed\n",
            )
            self.assertEqual(
                (context / "frequi" / "frontend.txt").read_text(encoding="utf-8"),
                "frontend committed\n",
            )
            self.assertFalse((context / ".git").exists())
            self.assertFalse((context / "freqtrade" / ".git").exists())

    def test_context_excludes_runtime_secrets_configs_databases_and_dirty_strategies(self) -> None:
        identity = resolve_commit_identity(self.fixture.root)
        _write(self.fixture.root, ".env", "EXCHANGE_KEY=secret\n")
        _write(self.fixture.root, "runtime.sqlite", "database\n")
        _write(self.fixture.root, "ignored-output/config.json", '{"secret": true}\n')
        _write(self.fixture.root, "ignored-output/strategies/Dirty.py", "dirty strategy\n")

        with committed_build_context(self.fixture.root, identity) as context:
            self.assertFalse((context / ".env").exists())
            self.assertFalse((context / "runtime.sqlite").exists())
            self.assertFalse((context / "ignored-output").exists())

    def test_rejects_archive_absolute_traversal_control_and_special_entries(self) -> None:
        cases: list[tarfile.TarInfo] = []
        for name in (
            "/absolute",
            "C:/drive",
            "./C:/drive",
            "//server/share",
            "../escape",
            "ok/../../escape",
            "bad\x01name",
            "bad\x85name",
            "directory/file:stream",
        ):
            cases.append(tarfile.TarInfo(name))
        fifo = tarfile.TarInfo("fifo")
        fifo.type = tarfile.FIFOTYPE
        cases.append(fifo)
        conflict_file = tarfile.TarInfo("conflict")
        conflict_file.size = 1
        conflict_child = tarfile.TarInfo("conflict/child")
        conflict_child.size = 1

        for member in cases:
            with self.subTest(name=member.name, type=member.type):
                with tempfile.TemporaryDirectory() as destination:
                    with self.assertRaises(ValueError):
                        extract_git_archive(_tar_bytes([(member, b"")]), Path(destination))
                    self.assertEqual(list(Path(destination).iterdir()), [])
        with tempfile.TemporaryDirectory() as destination:
            with self.assertRaises(ValueError):
                extract_git_archive(
                    _tar_bytes([(conflict_file, b"x"), (conflict_child, b"y")]),
                    Path(destination),
                )
            self.assertEqual(list(Path(destination).iterdir()), [])
        occupied = tarfile.TarInfo("existing")
        with tempfile.TemporaryDirectory() as destination:
            _write(Path(destination), "existing", "existing\n")
            with self.assertRaises(ValueError):
                extract_git_archive(_tar_bytes([(occupied, b"")]), Path(destination))

    def test_rejects_escaping_symlink_and_hardlink_targets(self) -> None:
        symlink = tarfile.TarInfo("directory/link")
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = "../../escape"
        hardlink = tarfile.TarInfo("hardlink")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "../escape"

        for member in (symlink, hardlink):
            with self.subTest(type=member.type):
                with tempfile.TemporaryDirectory() as destination:
                    with self.assertRaises(ValueError):
                        extract_git_archive(_tar_bytes([(member, b"")]), Path(destination))
                    self.assertEqual(list(Path(destination).iterdir()), [])

        ads_symlink = tarfile.TarInfo("link")
        ads_symlink.type = tarfile.SYMTYPE
        ads_symlink.linkname = "directory/target:stream"
        ads_target = tarfile.TarInfo("directory/target:stream")
        ads_target.size = 1
        ads_hardlink = tarfile.TarInfo("nested/hardlink")
        ads_hardlink.type = tarfile.LNKTYPE
        ads_hardlink.linkname = "directory/target:stream"
        regular_target = tarfile.TarInfo("directory/target")
        regular_target.size = 1
        ads_target_only_hardlink = tarfile.TarInfo("nested/hardlink")
        ads_target_only_hardlink.type = tarfile.LNKTYPE
        ads_target_only_hardlink.linkname = "directory/target:stream"
        for entries in (
            [(ads_symlink, b"")],
            [(ads_target, b"x"), (ads_hardlink, b"")],
            [(regular_target, b"x"), (ads_target_only_hardlink, b"")],
        ):
            with self.subTest(entries=[member.name for member, _contents in entries]):
                with tempfile.TemporaryDirectory() as destination:
                    with self.assertRaises(ValueError):
                        extract_git_archive(_tar_bytes(entries), Path(destination))
                    self.assertEqual(list(Path(destination).iterdir()), [])

    def test_extracts_nested_hardlink(self) -> None:
        source = tarfile.TarInfo("source")
        source.size = len(b"committed")
        hardlink = tarfile.TarInfo("nested/path/copy")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "source"

        with tempfile.TemporaryDirectory() as destination:
            root = Path(destination)
            extract_git_archive(_tar_bytes([(source, b"committed"), (hardlink, b"")]), root)

            self.assertEqual((root / "nested/path/copy").read_bytes(), b"committed")
            self.assertTrue((root / "source").samefile(root / "nested/path/copy"))

    def test_extraction_failure_removes_partial_writes(self) -> None:
        for mode in (0o644, 0o444):
            with self.subTest(mode=oct(mode)):
                source = tarfile.TarInfo("source")
                source.mode = mode
                source.size = len(b"committed")
                hardlink = tarfile.TarInfo("nested/copy")
                hardlink.type = tarfile.LNKTYPE
                hardlink.linkname = "source"

                with tempfile.TemporaryDirectory() as destination:
                    root = Path(destination)
                    with patch(
                        "tools.committed_build.os.link", side_effect=OSError("link failure")
                    ) as link_operation:
                        with self.assertRaises(ValueError) as raised:
                            extract_git_archive(
                                _tar_bytes([(source, b"committed"), (hardlink, b"")]), root
                            )

                    link_operation.assert_called_once()
                    self.assertEqual(str(raised.exception), "Git archive extraction failed")
                    self.assertNotIn(str(root), str(raised.exception))
                    self.assertEqual(list(root.iterdir()), [])

    def test_context_is_removed_after_success_and_exception(self) -> None:
        identity = resolve_commit_identity(self.fixture.root)
        with committed_build_context(self.fixture.root, identity) as successful_context:
            self.assertTrue(successful_context.is_dir())
        self.assertFalse(successful_context.exists())

        with self.assertRaisesRegex(RuntimeError, "caller failure"):
            with committed_build_context(self.fixture.root, identity) as failed_context:
                self.assertTrue(failed_context.is_dir())
                raise RuntimeError("caller failure")
        self.assertFalse(failed_context.exists())


if __name__ == "__main__":
    unittest.main()
