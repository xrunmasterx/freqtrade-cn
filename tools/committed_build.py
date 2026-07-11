from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator


_SUBMODULES = (("freqtrade", "backend"), ("frequi", "frontend"))
_ALLOWED_MEMBER_TYPES = {
    tarfile.REGTYPE,
    tarfile.AREGTYPE,
    tarfile.DIRTYPE,
    tarfile.SYMTYPE,
    tarfile.LNKTYPE,
}


@dataclass(frozen=True)
class CommitIdentity:
    root: str
    backend: str
    frontend: str

    def short_tag(self, length: int = 12) -> str:
        if length < 1:
            raise ValueError("tag length must be positive")
        return self.root[:length]


def _run_git(repository: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError):
        raise ValueError("Git operation failed") from None
    return result.stdout


def _git_text(repository: Path, *arguments: str) -> str:
    try:
        return _run_git(repository, *arguments).decode("ascii").strip()
    except UnicodeDecodeError:
        raise ValueError("Git returned an invalid object identity") from None


def _validate_object_id(commit: str) -> str:
    is_hexadecimal = all(character in "0123456789abcdef" for character in commit)
    if len(commit) not in (40, 64) or not is_hexadecimal:
        raise ValueError("Git returned an invalid object identity")
    return commit


def _resolve_gitlink(root: Path, name: str) -> str:
    record = _run_git(root, "ls-tree", "-z", "HEAD", "--", name)
    try:
        metadata, entry_name = record.rstrip(b"\0").split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ", 2)
    except ValueError:
        raise ValueError("Required Git link is missing") from None
    if entry_name != name.encode("ascii") or mode != b"160000" or object_type != b"commit":
        raise ValueError("Required Git link is invalid")
    try:
        commit = object_id.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("Required Git link has an invalid identity") from None
    return _validate_object_id(commit)


def resolve_commit_identity(root: Path) -> CommitIdentity:
    return CommitIdentity(
        root=_validate_object_id(_git_text(root, "rev-parse", "--verify", "HEAD")),
        backend=_resolve_gitlink(root, "freqtrade"),
        frontend=_resolve_gitlink(root, "frequi"),
    )


def _require_clean_repository(repository: Path) -> None:
    status = _run_git(
        repository,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=all",
    )
    if status:
        raise ValueError("Committed build checkout is not clean")


def verify_committed_checkout(root: Path, identity: CommitIdentity) -> None:
    if resolve_commit_identity(root) != identity:
        raise ValueError("Committed build identity does not match the checkout")
    for directory, identity_field in _SUBMODULES:
        submodule = root / directory
        checked_out_commit = _git_text(submodule, "rev-parse", "--verify", "HEAD")
        if checked_out_commit != getattr(identity, identity_field):
            raise ValueError("Submodule checkout does not match the committed Git link")
    _require_clean_repository(root)
    for directory, _identity_field in _SUBMODULES:
        _require_clean_repository(root / directory)


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _validated_parts(value: str) -> tuple[str, ...]:
    if (
        not value
        or value.startswith(("/", "\\"))
        or "\\" in value
        or _has_control_characters(value)
    ):
        raise ValueError("Archive contains an unsafe path")
    parts = tuple(part for part in PurePosixPath(value).parts if part not in ("", "."))
    if not parts or ".." in parts or ":" in parts[0]:
        raise ValueError("Archive contains an unsafe path")
    return parts


def _resolved_link_parts(
    member_parts: tuple[str, ...], linkname: str, *, relative_to_parent: bool
) -> tuple[str, ...]:
    if (
        not linkname
        or linkname.startswith(("/", "\\"))
        or "\\" in linkname
        or _has_control_characters(linkname)
    ):
        raise ValueError("Archive contains an unsafe link")
    resolved = list(member_parts[:-1] if relative_to_parent else ())
    link_parts = PurePosixPath(linkname).parts
    normalized_link_parts = tuple(part for part in link_parts if part not in ("", "."))
    if normalized_link_parts and ":" in normalized_link_parts[0]:
        raise ValueError("Archive contains an unsafe link")
    for part in link_parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved:
                raise ValueError("Archive link escapes its destination")
            resolved.pop()
        else:
            resolved.append(part)
    if not resolved:
        raise ValueError("Archive contains an unsafe link")
    return tuple(resolved)


def validate_archive_member(name: str, linkname: str | None = None) -> None:
    member_parts = _validated_parts(name)
    if linkname is not None:
        _resolved_link_parts(member_parts, linkname, relative_to_parent=True)


def _member_kind(member: tarfile.TarInfo) -> str:
    if member.isdir():
        return "directory"
    if member.isreg():
        return "file"
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    raise ValueError("Archive contains a special file")


def _validate_members(members: list[tarfile.TarInfo]) -> dict[tuple[str, ...], str]:
    path_types: dict[tuple[str, ...], str] = {}
    for member in members:
        if member.type not in _ALLOWED_MEMBER_TYPES:
            raise ValueError("Archive contains a special file")
        linkname = member.linkname if (member.issym() or member.islnk()) else None
        validate_archive_member(member.name, linkname)
        parts = _validated_parts(member.name)
        kind = _member_kind(member)
        for index in range(1, len(parts)):
            ancestor_type = path_types.get(parts[:index])
            if ancestor_type is not None and ancestor_type != "directory":
                raise ValueError("Archive contains a path type conflict")
        existing_type = path_types.get(parts)
        if existing_type is not None and not (existing_type == kind == "directory"):
            raise ValueError("Archive contains a path type conflict")
        if kind != "directory" and any(
            len(existing_path) > len(parts) and existing_path[: len(parts)] == parts
            for existing_path in path_types
        ):
            raise ValueError("Archive contains a path type conflict")
        if member.issym():
            _resolved_link_parts(parts, member.linkname, relative_to_parent=True)
        elif member.islnk():
            target = _resolved_link_parts(parts, member.linkname, relative_to_parent=False)
            if path_types.get(target) not in ("file", "hardlink"):
                raise ValueError("Archive hardlink target is invalid")
        path_types[parts] = kind
    return path_types


def _extract_member(
    archive: tarfile.TarFile, member: tarfile.TarInfo, destination: Path
) -> None:
    path = destination.joinpath(*_validated_parts(member.name))
    if member.isdir():
        path.mkdir(parents=True, exist_ok=True)
    elif member.isreg():
        path.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            raise ValueError("Archive file data is missing")
        with source, path.open("xb") as output:
            shutil.copyfileobj(source, output)
    else:
        return
    os.chmod(path, member.mode & 0o777)


def extract_git_archive(stream: BinaryIO, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Archive destination is not empty")
    with tempfile.TemporaryFile() as buffered_archive:
        shutil.copyfileobj(stream, buffered_archive)
        buffered_archive.seek(0)
        try:
            with tarfile.open(fileobj=buffered_archive, mode="r:*") as archive:
                members = archive.getmembers()
                _validate_members(members)
                for member in members:
                    _extract_member(archive, member, destination)
                for member in members:
                    path = destination.joinpath(*_validated_parts(member.name))
                    parts = _validated_parts(member.name)
                    if member.issym():
                        path.parent.mkdir(parents=True, exist_ok=True)
                        os.symlink(member.linkname, path)
                    elif member.islnk():
                        target_parts = _resolved_link_parts(
                            parts, member.linkname, relative_to_parent=False
                        )
                        os.link(destination.joinpath(*target_parts), path)
        except (tarfile.TarError, EOFError):
            raise ValueError("Git archive is invalid") from None


def _extract_commit(repository: Path, commit: str, destination: Path) -> None:
    try:
        process = subprocess.Popen(
            ["git", "-C", str(repository), "archive", "--format=tar", commit],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        raise ValueError("Git archive operation failed") from None
    assert process.stdout is not None
    try:
        extract_git_archive(process.stdout, destination)
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        process.stdout.close()
    if process.wait() != 0:
        raise ValueError("Git archive operation failed")


@contextmanager
def committed_build_context(root: Path, identity: CommitIdentity) -> Iterator[Path]:
    verify_committed_checkout(root, identity)
    with tempfile.TemporaryDirectory(prefix="committed-build-") as temporary_directory:
        context = Path(temporary_directory)
        _extract_commit(root, identity.root, context)
        _extract_commit(root / "freqtrade", identity.backend, context / "freqtrade")
        _extract_commit(root / "frequi", identity.frontend, context / "frequi")
        yield context
