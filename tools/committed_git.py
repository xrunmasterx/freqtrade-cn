from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path


_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_TEMPLATE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}")
_TEMPLATE_PREFIX = "ops/adapter-templates/"
_POLICY_PATHS = {
    "image_policy_ids": "ops/runtime-policies/image-policies.json",
    "command_policy_ids": "ops/runtime-policies/command-policies.json",
    "mount_policy_ids": "ops/runtime-policies/mount-policies.json",
    "network_policy_ids": "ops/runtime-policies/network-policies.json",
    "health_profile_ids": "ops/runtime-policies/health-profiles.json",
    "resource_profile_ids": "ops/runtime-policies/resource-profiles.json",
    "state_layout_ids": "ops/runtime-policies/state-layouts.json",
}
_RUNTIME_CONFIG_PATH = "ft_userdata/user_data/config.example.json"
_RUNTIME_STRATEGY_PATH = "ft_userdata/user_data/strategies/sample_strategy.py"
_RUNTIME_SAFETY_PATH = "ops/config/trading-safety.json"
_RUNTIME_PATHS = (
    _RUNTIME_CONFIG_PATH,
    _RUNTIME_STRATEGY_PATH,
    _RUNTIME_SAFETY_PATH,
)
_COMPONENT_PATHS = {
    "backend": "freqtrade",
    "frontend": "frequi",
    "strategies": "freqtrade-strategies",
}


@dataclass(frozen=True, slots=True)
class _TreeEntry:
    mode: bytes
    object_type: bytes
    object_id: str


class CommittedGitStore:
    __slots__ = ("_commit", "_root")

    def __init__(self, root: Path, commit: str) -> None:
        exact_root = self._exact_git_root(root)
        self._root = exact_root
        self._commit = self._resolve_commit(commit)

    @property
    def root_commit(self) -> str:
        return self._commit

    @property
    def backend_commit(self) -> str:
        return self._component_commit("backend")

    @property
    def frontend_commit(self) -> str:
        return self._component_commit("frontend")

    @property
    def strategies_commit(self) -> str:
        return self._component_commit("strategies")

    def __repr__(self) -> str:
        return f"CommittedGitStore(commit={self._commit!r})"

    @staticmethod
    def _command(root: Path, *arguments: str) -> list[str]:
        return [
            "git",
            "--no-replace-objects",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "credential.helper=",
            "-c",
            "credential.interactive=never",
            "-c",
            "core.askPass=",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "protocol.allow=never",
            "-C",
            str(root),
            *arguments,
        ]

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = os.environ.copy()
        for key in tuple(environment):
            normalized = key.upper()
            if normalized.startswith(("GIT_", "GCM_")) or normalized == "SSH_ASKPASS":
                environment.pop(key)
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
            }
        )
        return environment

    @classmethod
    def _run_at(
        cls,
        root: Path,
        *arguments: str,
        error: str = "Git operation failed",
    ) -> bytes:
        try:
            result = subprocess.run(
                cls._command(root, *arguments),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=cls._environment(),
            )
        except OSError:
            raise ValueError(error) from None
        if result.returncode != 0:
            raise ValueError(error)
        return result.stdout

    def _run(self, *arguments: str, error: str = "Git operation failed") -> bytes:
        return self._run_at(self._root, *arguments, error=error)

    def _returncode(self, *arguments: str) -> int:
        try:
            result = subprocess.run(
                self._command(self._root, *arguments),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self._environment(),
            )
        except OSError:
            raise ValueError("Git operation failed") from None
        return result.returncode

    @classmethod
    def _exact_git_root(cls, root: Path) -> Path:
        requested = Path(root)
        try:
            requested_resolved = requested.resolve(strict=True)
        except OSError:
            raise ValueError("root must be the exact Git toplevel") from None
        output = cls._run_at(
            requested_resolved,
            "rev-parse",
            "--show-toplevel",
            error="root must be the exact Git toplevel",
        )
        try:
            toplevel = Path(output.decode("utf-8").strip()).resolve(strict=True)
        except (OSError, UnicodeDecodeError):
            raise ValueError("root must be the exact Git toplevel") from None
        if requested_resolved != toplevel:
            raise ValueError("root must be the exact Git toplevel")
        return toplevel

    def _resolve_commit(self, commit: str) -> str:
        if not isinstance(commit, str) or _OBJECT_ID.fullmatch(commit) is None:
            raise ValueError("commit must be a full lowercase Git identity")
        object_type = self._run(
            "cat-file",
            "-t",
            commit,
            error="commit identity must name a commit object",
        )
        if object_type != b"commit\n":
            raise ValueError("commit identity must name a commit object")
        resolved_bytes = self._run(
            "rev-parse",
            "--verify",
            commit,
            error="commit identity must name a commit object",
        )
        try:
            resolved = resolved_bytes.decode("ascii").strip()
        except UnicodeDecodeError:
            raise ValueError("commit identity must name a commit object") from None
        if resolved != commit or _OBJECT_ID.fullmatch(resolved) is None:
            raise ValueError("commit identity must name a commit object")
        if self._returncode("merge-base", "--is-ancestor", resolved, "HEAD") != 0:
            raise ValueError("commit must be an ancestor of HEAD")
        return resolved

    def assert_template_checkout_clean(self) -> None:
        self._assert_clean(
            ("ops/adapter-templates", "ops/runtime-policies"),
            "template checkout must be clean",
            required_paths=tuple(_POLICY_PATHS.values()),
            exact_index=False,
        )

    def assert_runtime_checkout_clean(self) -> None:
        self._assert_clean(
            _RUNTIME_PATHS,
            "runtime artifact checkout must be clean",
            required_paths=_RUNTIME_PATHS,
            exact_index=True,
        )

    def _assert_clean(
        self,
        paths: tuple[str, ...],
        error: str,
        *,
        required_paths: tuple[str, ...],
        exact_index: bool,
    ) -> None:
        status = self._run(
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=matching",
            "--ignore-submodules=all",
            "--",
            *paths,
            error=error,
        )
        if status:
            raise ValueError(error)
        index_entries = self._run(
            "ls-files",
            "-v",
            "-z",
            "--",
            *paths,
            error=error,
        )
        indexed_paths = self._parse_index_entries(index_entries, error)
        if any(
            not any(path == scope or path.startswith(f"{scope}/") for scope in paths)
            for path in indexed_paths
        ):
            raise ValueError(error)
        required = set(required_paths)
        if not required.issubset(indexed_paths):
            raise ValueError(error)
        if exact_index and indexed_paths != required:
            raise ValueError(error)
        for path in required_paths:
            self._assert_regular_worktree_file(path, error)

    @staticmethod
    def _parse_index_entries(output: bytes, error: str) -> set[str]:
        if output and not output.endswith(b"\0"):
            raise ValueError(error)
        records = output.split(b"\0")[:-1] if output else []
        paths: set[str] = set()
        for record in records:
            if len(record) < 3 or record[:2] != b"H ":
                raise ValueError(error)
            try:
                path = record[2:].decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(error) from None
            if not path or path in paths:
                raise ValueError(error)
            paths.add(path)
        return paths

    def _assert_regular_worktree_file(self, path: str, error: str) -> None:
        try:
            metadata = os.lstat(self._root / path)
        except OSError:
            raise ValueError(error) from None
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(error)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if getattr(metadata, "st_file_attributes", 0) & reparse_flag:
            raise ValueError(error)

    def _assert_current_paths(self, paths: tuple[str, ...], error: str) -> None:
        index_entries = self._run(
            "ls-files",
            "-v",
            "-z",
            "--",
            *paths,
            error=error,
        )
        if self._parse_index_entries(index_entries, error) != set(paths):
            raise ValueError(error)
        for path in paths:
            self._assert_regular_worktree_file(path, error)

    def read_template_blob(self, template_id: str) -> bytes:
        if not isinstance(template_id, str) or _TEMPLATE_ID.fullmatch(template_id) is None:
            raise ValueError("template_id must be a valid platform identifier")
        path = f"{_TEMPLATE_PREFIX}{template_id}.json"
        self._assert_current_paths(
            (path, *_POLICY_PATHS.values()),
            "template checkout must be clean",
        )
        return self._blob(path)

    def read_policy_blob(self, policy_field: str) -> bytes:
        try:
            path = _POLICY_PATHS[policy_field]
        except (KeyError, TypeError):
            raise ValueError("artifact path is not permitted") from None
        return self._blob(path)

    def read_runtime_config_blob(self) -> bytes:
        return self._blob(_RUNTIME_CONFIG_PATH, runtime=True)

    def read_runtime_strategy_blob(self) -> bytes:
        return self._blob(_RUNTIME_STRATEGY_PATH, runtime=True)

    def read_runtime_safety_blob(self) -> bytes:
        return self._blob(_RUNTIME_SAFETY_PATH, runtime=True)

    def _tree_entry(self, path: str, *, runtime: bool = False) -> _TreeEntry:
        unavailable = (
            "runtime artifact metadata is unavailable"
            if runtime
            else "required artifact metadata is unavailable"
        )
        missing = "runtime artifact is missing" if runtime else "required artifact is missing"
        invalid = (
            "runtime artifact metadata is invalid"
            if runtime
            else "required artifact metadata is invalid"
        )
        output = self._run(
            "ls-tree",
            "-z",
            self._commit,
            "--",
            path,
            error=unavailable,
        )
        records = [record for record in output.split(b"\0") if record]
        if len(records) != 1:
            raise ValueError(missing)
        try:
            metadata, encoded_path = records[0].split(b"\t", 1)
            mode, object_type, encoded_object_id = metadata.split(b" ", 2)
            actual_path = encoded_path.decode("utf-8")
            object_id = encoded_object_id.decode("ascii")
        except (ValueError, UnicodeDecodeError):
            raise ValueError(invalid) from None
        if actual_path != path:
            raise ValueError(missing)
        if _OBJECT_ID.fullmatch(object_id) is None:
            raise ValueError(invalid)
        return _TreeEntry(mode=mode, object_type=object_type, object_id=object_id)

    def _blob(self, path: str, *, runtime: bool = False) -> bytes:
        entry = self._tree_entry(path, runtime=runtime)
        if entry.mode != b"100644" or entry.object_type != b"blob":
            if runtime:
                raise ValueError("runtime artifact must be a regular 100644 blob")
            raise ValueError("artifact must be a regular 100644 blob")
        return self._run(
            "cat-file",
            "blob",
            entry.object_id,
            error=(
                "runtime artifact blob is unavailable"
                if runtime
                else "required artifact blob is unavailable"
            ),
        )

    def _component_commit(self, component: str) -> str:
        entry = self._tree_entry(_COMPONENT_PATHS[component], runtime=True)
        if entry.mode != b"160000" or entry.object_type != b"commit":
            raise ValueError("component must be a 160000 commit gitlink")
        return entry.object_id
