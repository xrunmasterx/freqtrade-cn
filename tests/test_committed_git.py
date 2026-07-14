from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def git(repository: Path, *arguments: str, input_bytes: bytes | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        input=input_bytes,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("ascii").strip()


class CommittedGitFixture:
    COMPONENTS = {
        "freqtrade": "1" * 40,
        "frequi": "2" * 40,
        "freqtrade-strategies": "3" * 40,
    }

    def __init__(self, parent: Path) -> None:
        self.root = parent / "repository"
        self.root.mkdir()
        git(self.root, "init", "--quiet")
        git(self.root, "config", "user.email", "committed-git@example.invalid")
        git(self.root, "config", "user.name", "Committed Git Tests")
        git(self.root, "config", "core.autocrlf", "false")
        git(self.root, "config", "core.filemode", "false")
        git(self.root, "config", "core.symlinks", "false")
        self.write_bytes("ft_userdata/user_data/config.example.json", b"config\n")
        self.write_bytes(
            "ft_userdata/user_data/strategies/sample_strategy.py",
            b"strategy\n",
        )
        self.write_bytes("ops/config/trading-safety.json", b"safety\n")
        git(self.root, "add", "--all", "--", ".")
        for path, commit in self.COMPONENTS.items():
            git(self.root, "update-index", "--add", "--cacheinfo", "160000", commit, path)
        self.commit = self.create_index_commit("initial tree")

    def write_bytes(self, relative_path: str, contents: bytes) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    def create_index_commit(self, message: str) -> str:
        git(self.root, "commit", "--quiet", "-m", message)
        return git(self.root, "rev-parse", "HEAD")


try:
    from tools.committed_git import CommittedGitStore
except ModuleNotFoundError as error:
    COMMITTED_GIT_IMPORT_ERROR: ModuleNotFoundError | None = error
else:
    COMMITTED_GIT_IMPORT_ERROR = None


class CommittedGitAvailabilityTests(unittest.TestCase):
    def test_committed_git_module_exists(self) -> None:
        self.assertIsNone(COMMITTED_GIT_IMPORT_ERROR)


@unittest.skipIf(COMMITTED_GIT_IMPORT_ERROR is not None, "committed_git is missing")
class CommittedGitStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = CommittedGitFixture(Path(self.temporary_directory.name))

    def test_accepts_only_full_lowercase_commit_identity(self) -> None:
        invalid = (
            "HEAD",
            self.fixture.commit[:12],
            self.fixture.commit.upper(),
            "g" * 40,
        )
        for commit in invalid:
            with self.subTest(commit=commit):
                with self.assertRaisesRegex(ValueError, "full lowercase"):
                    CommittedGitStore(self.fixture.root, commit)

    def test_rejects_non_commit_and_unapproved_commit(self) -> None:
        blob = git(
            self.fixture.root,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"not a commit\n",
        )
        tree = git(self.fixture.root, "write-tree")
        unrelated = git(self.fixture.root, "commit-tree", tree, "-m", "unrelated")
        with self.assertRaisesRegex(ValueError, "commit object"):
            CommittedGitStore(self.fixture.root, blob)
        with self.assertRaisesRegex(ValueError, "ancestor of HEAD"):
            CommittedGitStore(self.fixture.root, unrelated)

    def test_root_is_an_exact_local_git_toplevel(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact Git toplevel"):
            CommittedGitStore(self.fixture.root / "ft_userdata", self.fixture.commit)
        missing = self.fixture.root / "credential-secret-marker"
        with self.assertRaises(ValueError) as caught:
            CommittedGitStore(missing, self.fixture.commit)
        self.assertNotIn(str(missing), str(caught.exception))
        self.assertNotIn(str(missing), repr(caught.exception))

    def test_git_plumbing_is_noninteractive_and_side_effect_hardened(self) -> None:
        with patch("tools.committed_git.subprocess.run", wraps=subprocess.run) as run:
            store = CommittedGitStore(self.fixture.root, self.fixture.commit)
            store.assert_runtime_checkout_clean()
            store.read_runtime_config_blob()

        self.assertGreater(len(run.call_args_list), 0)
        for call in run.call_args_list:
            command = call.args[0]
            self.assertIsInstance(command, list)
            self.assertIn("--no-replace-objects", command)
            self.assertIn(f"core.hooksPath={os.devnull}", command)
            self.assertIn("credential.helper=", command)
            self.assertIn("credential.interactive=never", command)
            self.assertNotIn("fetch", command)
            self.assertNotIn("pull", command)
            self.assertNotIn("push", command)
            environment = call.kwargs["env"]
            self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(environment["GIT_OPTIONAL_LOCKS"], "0")

    def test_ignores_environment_that_redirects_git_state_or_objects(self) -> None:
        redirected = self.fixture.root / "redirected-secret-marker"
        redirected.mkdir()
        hostile_environment = {
            "GIT_DIR": str(redirected),
            "GIT_WORK_TREE": str(redirected),
            "GIT_INDEX_FILE": str(redirected / "index"),
            "GIT_OBJECT_DIRECTORY": str(redirected / "objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(redirected / "alternates"),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "hostile-helper",
        }
        with patch.dict(os.environ, hostile_environment, clear=False):
            try:
                store = CommittedGitStore(self.fixture.root, self.fixture.commit)
            except ValueError:
                self.fail("Git environment redirected the committed object store")
            self.assertEqual(store.read_runtime_config_blob(), b"config\n")

    def test_fixed_runtime_blob_and_component_accessors(self) -> None:
        store = CommittedGitStore(self.fixture.root, self.fixture.commit)
        store.assert_runtime_checkout_clean()
        self.assertEqual(store.read_runtime_config_blob(), b"config\n")
        self.assertEqual(store.read_runtime_strategy_blob(), b"strategy\n")
        self.assertEqual(store.read_runtime_safety_blob(), b"safety\n")
        self.assertEqual(store.backend_commit, self.fixture.COMPONENTS["freqtrade"])
        self.assertEqual(store.frontend_commit, self.fixture.COMPONENTS["frequi"])
        self.assertEqual(
            store.strategies_commit,
            self.fixture.COMPONENTS["freqtrade-strategies"],
        )

    def test_repr_exposes_commit_but_not_absolute_object_store_path(self) -> None:
        store = CommittedGitStore(self.fixture.root, self.fixture.commit)
        rendered = repr(store)
        self.assertIn(self.fixture.commit, rendered)
        self.assertNotIn(str(self.fixture.root), rendered)

    def test_runtime_clean_guard_rejects_index_and_worktree_hiding(self) -> None:
        path = "ft_userdata/user_data/config.example.json"
        mutations = ("unstaged", "staged", "assume-unchanged", "skip-worktree")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = CommittedGitFixture(Path(directory))
                    if mutation == "assume-unchanged":
                        git(fixture.root, "update-index", "--assume-unchanged", "--", path)
                    elif mutation == "skip-worktree":
                        git(fixture.root, "update-index", "--skip-worktree", "--", path)
                    fixture.write_bytes(path, b"replacement\n")
                    if mutation == "staged":
                        git(fixture.root, "add", "--", path)
                    store = CommittedGitStore(fixture.root, fixture.commit)
                    with self.assertRaisesRegex(ValueError, "checkout must be clean"):
                        store.assert_runtime_checkout_clean()


if __name__ == "__main__":
    unittest.main()
