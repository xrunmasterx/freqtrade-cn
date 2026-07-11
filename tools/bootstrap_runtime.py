from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

if __package__:
    from tools.runtime_manifest import DEFAULT_MANIFEST, load_runtime_manifest
else:
    from runtime_manifest import DEFAULT_MANIFEST, load_runtime_manifest


SENTINEL = "__SET_VIA_SECRET_FILE__"
SECRET_SPECS = {
    "api_password": 32,
    "jwt_secret_key": 48,
    "ws_token": 32,
}
RESEARCH_PATH_MIGRATIONS = (
    (
        "data_source",
        "root",
        "research_data/a_share",
        "/freqtrade/user_data/research_data/a_share",
    ),
    (
        "market_data",
        "meta_root",
        "research_data/a_share_meta",
        "/freqtrade/user_data/research_data/a_share_meta",
    ),
    (
        "side_data",
        "root",
        "research_data/a_share_meta",
        "/freqtrade/user_data/research_data/a_share_meta",
    ),
)
RUNTIME_IDENTITY_KEYS = (
    "FREQTRADE_RUNTIME_UID",
    "FREQTRADE_RUNTIME_GID",
)
RUNTIME_IDENTITY_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(FREQTRADE_RUNTIME_(?:UID|GID))\s*=\s*(.*?)\s*$"
)
NON_NEGATIVE_INTEGER_PATTERN = re.compile(r"[0-9]+")
COMPOSE_IDENTITY_RELATIVE_PATH = Path("ft_userdata/runtime/compose.identity.yml")
WINDOWS_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$secretPath = $env:FREQTRADE_RUNTIME_SECRET_PATH
$action = $env:FREQTRADE_RUNTIME_ACL_ACTION
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$fullControl = [System.Security.AccessControl.FileSystemRights]::FullControl
$allow = [System.Security.AccessControl.AccessControlType]::Allow

if ($action -eq 'harden') {
    $acl = Get-Acl -LiteralPath $secretPath
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) {
        $null = $acl.RemoveAccessRuleSpecific($rule)
    }
    $acl.SetOwner($identity.User)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $identity.User,
        $fullControl,
        $allow
    )
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $secretPath -AclObject $acl
} elseif ($action -ne 'verify') {
    throw 'unsupported runtime ACL action'
}

$acl = Get-Acl -LiteralPath $secretPath
$owner = $acl.GetOwner([System.Security.Principal.SecurityIdentifier])
$rules = @(
    $acl.GetAccessRules(
        $true,
        $true,
        [System.Security.Principal.SecurityIdentifier]
    )
)
$valid = $acl.AreAccessRulesProtected `
    -and $owner.Value -eq $identity.User.Value `
    -and $rules.Count -eq 1 `
    -and $rules[0].IdentityReference.Value -eq $identity.User.Value `
    -and $rules[0].AccessControlType -eq $allow `
    -and -not $rules[0].IsInherited `
    -and [int]$rules[0].FileSystemRights -eq [int]$fullControl
if (-not $valid) {
    throw 'runtime secret ACL verification failed'
}
Write-Output "runtime secret ACL: $action`: OK"
"""


def _is_windows() -> bool:
    return os.name == "nt"


def _run_windows_acl(action: str, path: Path) -> None:
    if action not in {"harden", "verify"}:
        raise ValueError("unsupported Windows runtime secret ACL action")
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise ValueError("unable to prove Windows runtime secret ACL")
    encoded_script = base64.b64encode(WINDOWS_ACL_SCRIPT.encode("utf-16-le")).decode("ascii")
    environment = os.environ.copy()
    environment["FREQTRADE_RUNTIME_SECRET_PATH"] = str(path)
    environment["FREQTRADE_RUNTIME_ACL_ACTION"] = action
    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded_script,
            ],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"failed to {action} Windows runtime secret ACL") from error
    if completed.returncode != 0:
        raise ValueError(f"failed to {action} Windows runtime secret ACL")


def _harden_secret_permissions(path: Path) -> None:
    if _is_windows():
        _run_windows_acl("harden", path)
    else:
        os.chmod(path, 0o600)


def _verify_secret_permissions(path: Path, runtime_uid: int) -> None:
    if _is_windows():
        _run_windows_acl("verify", path)
    else:
        status = path.stat()
        if stat.S_IMODE(status.st_mode) != 0o600:
            raise ValueError("runtime secret permissions must be 0600")
        if status.st_uid != runtime_uid:
            raise ValueError("runtime secret must be owned by runtime uid")


def _expected_runtime_identity() -> dict[str, int]:
    if _is_windows():
        return {
            "FREQTRADE_RUNTIME_UID": 1000,
            "FREQTRADE_RUNTIME_GID": 1000,
        }
    identity = {
        "FREQTRADE_RUNTIME_UID": os.getuid(),
        "FREQTRADE_RUNTIME_GID": os.getgid(),
    }
    if any(value <= 0 for value in identity.values()):
        raise ValueError("POSIX bootstrap requires a non-root runtime identity")
    return identity


def _parse_runtime_identity(content: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in content.splitlines():
        match = RUNTIME_IDENTITY_PATTERN.fullmatch(line)
        if match is None:
            continue
        key, value = match.groups()
        if key in values:
            raise ValueError(f"duplicate runtime identity key: {key}")
        if NON_NEGATIVE_INTEGER_PATTERN.fullmatch(value) is None:
            raise ValueError(f"runtime identity must be a non-negative integer: {key}")
        values[key] = int(value)
    return values


def _read_runtime_identity(path: Path) -> dict[str, int]:
    if not path.is_file():
        raise ValueError("missing runtime identity environment")
    values = _parse_runtime_identity(path.read_text(encoding="utf-8"))
    missing = [key for key in RUNTIME_IDENTITY_KEYS if key not in values]
    if missing:
        raise ValueError(f"missing runtime identity key: {missing[0]}")
    expected = _expected_runtime_identity()
    for key in RUNTIME_IDENTITY_KEYS:
        if values[key] != expected[key]:
            raise ValueError(f"runtime identity does not match current host: {key}")
    return values


def _verify_ambient_runtime_identity(identity: dict[str, int]) -> None:
    ambient = {key: os.environ.get(key) for key in RUNTIME_IDENTITY_KEYS}
    present = [key for key, value in ambient.items() if value is not None]
    if not present:
        return
    if len(present) != len(RUNTIME_IDENTITY_KEYS):
        raise ValueError("ambient runtime identity must contain both uid and gid")
    for key in RUNTIME_IDENTITY_KEYS:
        value = ambient[key]
        if value is None or NON_NEGATIVE_INTEGER_PATTERN.fullmatch(value) is None:
            raise ValueError("ambient runtime identity must be a positive integer pair")
        if int(value) <= 0 or int(value) != identity[key]:
            raise ValueError("ambient runtime identity does not match verified identity")


def build_compose_identity(
    manifest: dict[str, Any], identity: dict[str, int]
) -> dict[str, object]:
    user = (
        f"{identity['FREQTRADE_RUNTIME_UID']}:"
        f"{identity['FREQTRADE_RUNTIME_GID']}"
    )
    return {
        "services": {
            service["name"]: {"user": user} for service in manifest["services"]
        }
    }


def _read_compose_identity(
    path: Path,
    manifest: dict[str, Any],
    identity: dict[str, int],
) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid compose identity override") from error
    if document != build_compose_identity(manifest, identity):
        raise ValueError("invalid or conflicting compose identity override")
    return document


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _require_regular_runtime_control_file(path: Path) -> os.stat_result:
    if path.is_symlink():
        raise ValueError("runtime control file must be a regular file")
    try:
        status = os.lstat(path)
    except OSError as error:
        raise ValueError("runtime control file must be a regular file") from error
    if not stat.S_ISREG(status.st_mode):
        raise ValueError("runtime control file must be a regular file")
    return status


def _harden_runtime_control_file(path: Path, runtime_uid: int) -> None:
    status = _require_regular_runtime_control_file(path)
    if _is_windows():
        _run_windows_acl("harden", path)
    else:
        if status.st_uid != runtime_uid:
            raise ValueError("runtime control file must be owned by runtime uid")
        os.chmod(path, 0o600)


def _verify_runtime_control_file(path: Path, runtime_uid: int) -> None:
    status = _require_regular_runtime_control_file(path)
    if _is_windows():
        _run_windows_acl("verify", path)
    elif status.st_uid != runtime_uid or stat.S_IMODE(status.st_mode) != 0o600:
        raise ValueError("runtime control file must be owned by runtime uid with mode 0600")


def _merge_runtime_identity(path: Path) -> None:
    expected = _expected_runtime_identity()
    if path.exists() and not path.is_file():
        raise ValueError("invalid runtime identity environment")
    content = path.read_bytes().decode("utf-8") if path.is_file() else ""
    existing = _parse_runtime_identity(content)
    for key, value in existing.items():
        if value != expected[key]:
            raise ValueError(f"runtime identity conflicts with current host: {key}")

    missing = [key for key in RUNTIME_IDENTITY_KEYS if key not in existing]
    if not missing:
        return
    newline = "\r\n" if "\r\n" in content else "\n"
    merged = content
    if merged and not merged.endswith(("\r", "\n")):
        merged += newline
    merged += "".join(f"{key}={expected[key]}{newline}" for key in missing)

    _atomic_write_text(path, merged)


def _merge_compose_identity(
    path: Path,
    manifest: dict[str, Any],
    identity: dict[str, int],
) -> None:
    if path.exists():
        if not path.is_file():
            raise ValueError("invalid compose identity override")
        _read_compose_identity(path, manifest, identity)
        return
    content = json.dumps(
        build_compose_identity(manifest, identity),
        indent=2,
        ensure_ascii=True,
    )
    _atomic_write_text(path, content + "\n")


def _service_writable_directories(state_root: Path) -> tuple[Path, ...]:
    return (
        state_root,
        state_root / "home",
        state_root / "logs",
        state_root / "data",
        state_root / "backtest_results",
    )


def _verify_posix_writable_directory(
    path: Path,
    runtime_uid: int,
    runtime_gid: int,
) -> None:
    status = path.stat()
    mode = stat.S_IMODE(status.st_mode)
    if mode & stat.S_IWOTH:
        raise ValueError("runtime writable directory must not be other-writable")
    if status.st_uid == runtime_uid:
        effective = (mode >> 6) & 0o7
    elif status.st_gid == runtime_gid:
        effective = (mode >> 3) & 0o7
    else:
        effective = mode & 0o7
    if effective != 0o7:
        raise ValueError("runtime writable directory permissions do not grant rwx")


def _verify_writable_directories(
    root: Path,
    service: dict[str, Any],
    runtime_uid: int,
    runtime_gid: int,
) -> Path:
    directories = _service_writable_directories(root / service["state_root"])
    state_root = directories[0]
    if state_root.is_symlink() or not state_root.is_dir():
        raise ValueError(f"invalid runtime writable directory for {service['name']}")
    resolved_root = state_root.resolve()
    for path in directories:
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"invalid runtime writable directory for {service['name']}")
        resolved = path.resolve()
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise ValueError(f"runtime writable directory escapes state root: {service['name']}")
        if _is_windows():
            if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
                raise ValueError(
                    f"runtime writable directory is not accessible: {service['name']}"
                )
        else:
            _verify_posix_writable_directory(path, runtime_uid, runtime_gid)
    return resolved_root


def write_new_secret(path: Path, entropy_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(secrets.token_urlsafe(entropy_bytes))
            handle.write("\n")
        _harden_secret_permissions(path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def init_runtime(root: Path, manifest: dict[str, Any]) -> None:
    identity = _expected_runtime_identity()
    runtime_uid = identity["FREQTRADE_RUNTIME_UID"]
    environment_path = root / ".env"
    if os.path.lexists(environment_path):
        _require_regular_runtime_control_file(environment_path)
    override_path = root / COMPOSE_IDENTITY_RELATIVE_PATH
    if override_path.is_symlink() or override_path.exists():
        _read_compose_identity(override_path, manifest, identity)
    _merge_runtime_identity(environment_path)
    _harden_runtime_control_file(environment_path, runtime_uid)
    _merge_compose_identity(override_path, manifest, identity)
    _harden_runtime_control_file(override_path, runtime_uid)
    for service in manifest["services"]:
        template = root / service["config_template"]
        config = root / service["config_path"]
        if not template.is_file():
            raise ValueError(f"missing config template for {service['name']}")
        if not config.exists():
            config.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(template, config)

        state_root = root / service["state_root"]
        for directory in _service_writable_directories(state_root):
            directory.mkdir(parents=True, exist_ok=True)

        secret_root = root / "ft_userdata" / "secrets" / service["name"]
        for filename, entropy_bytes in SECRET_SPECS.items():
            path = secret_root / filename
            if not path.exists():
                write_new_secret(path, entropy_bytes)
            elif path.is_file():
                _harden_secret_permissions(path)
            else:
                raise ValueError(f"invalid runtime secret file for {service['name']}")


def sanitize_api_configs(root: Path, manifest: dict[str, Any]) -> None:
    for service in manifest["services"]:
        config_path = root / service["config_path"]
        config = json.loads(config_path.read_text(encoding="utf-8"))
        api_server = config.setdefault("api_server", {})
        for key in ("password", "jwt_secret_key", "ws_token"):
            api_server[key] = SENTINEL
        temporary = config_path.with_suffix(config_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, config_path)


def migrate_research_paths(root: Path, manifest: dict[str, Any]) -> None:
    research_services = [
        service for service in manifest["services"] if service["role"] == "research"
    ]
    if len(research_services) != 1:
        raise ValueError("research path migration requires one research service")
    config_path = root / research_services[0]["config_path"]
    document = json.loads(config_path.read_text(encoding="utf-8"))
    profiles = document.get("research_bots") if type(document) is dict else None
    if type(profiles) is not list or not profiles:
        raise ValueError("research path migration requires research profiles")

    values: list[tuple[dict[str, Any], str, str, str]] = []
    for profile in profiles:
        if type(profile) is not dict:
            raise ValueError("research path migration requires research profiles")
        for section, key, legacy, approved in RESEARCH_PATH_MIGRATIONS:
            container = profile.get(section)
            value = container.get(key) if type(container) is dict else None
            if value not in (legacy, approved):
                raise ValueError("research path migration rejected unknown value")
            values.append((container, key, legacy, approved))

    changed = False
    for container, key, legacy, approved in values:
        if container[key] == legacy:
            container[key] = approved
            changed = True
    if changed:
        _atomic_write_text(
            config_path,
            json.dumps(document, indent=4, ensure_ascii=False) + "\n",
        )


def rotate_secrets(
    root: Path,
    manifest: dict[str, Any],
    service_names: set[str],
) -> None:
    known = {service["name"] for service in manifest["services"]}
    unknown = service_names - known
    if unknown:
        raise ValueError(f"unknown runtime service: {', '.join(sorted(unknown))}")
    for service_name in sorted(service_names):
        secret_root = root / "ft_userdata" / "secrets" / service_name
        for filename, entropy_bytes in SECRET_SPECS.items():
            destination = secret_root / filename
            temporary = secret_root / f".{filename}.{secrets.token_hex(8)}.tmp"
            write_new_secret(temporary, entropy_bytes)
            os.replace(temporary, destination)
            _harden_secret_permissions(destination)


def verify_runtime(root: Path, manifest: dict[str, Any]) -> dict[str, int]:
    expected_identity = _expected_runtime_identity()
    environment_path = root / ".env"
    _verify_runtime_control_file(
        environment_path,
        expected_identity["FREQTRADE_RUNTIME_UID"],
    )
    identity = _read_runtime_identity(environment_path)
    _verify_ambient_runtime_identity(identity)
    override_path = root / COMPOSE_IDENTITY_RELATIVE_PATH
    _verify_runtime_control_file(override_path, identity["FREQTRADE_RUNTIME_UID"])
    _read_compose_identity(
        override_path,
        manifest,
        identity,
    )
    runtime_uid = identity["FREQTRADE_RUNTIME_UID"]
    runtime_gid = identity["FREQTRADE_RUNTIME_GID"]
    all_values: list[str] = []
    state_roots: set[Path] = set()
    for service in manifest["services"]:
        config = root / service["config_path"]
        state_root = _verify_writable_directories(
            root,
            service,
            runtime_uid,
            runtime_gid,
        )
        if not config.is_file():
            raise ValueError(f"missing operational config for {service['name']}")
        if state_root in state_roots:
            raise ValueError(f"invalid or duplicate state root for {service['name']}")
        state_roots.add(state_root)

        config_data = json.loads(config.read_text(encoding="utf-8"))
        api_server = config_data.get("api_server", {})
        for key in ("password", "jwt_secret_key", "ws_token"):
            if api_server.get(key) != SENTINEL:
                raise ValueError(
                    f"operational API field must use sentinel: {service['name']}:{key}"
                )

        for filename in SECRET_SPECS:
            path = root / "ft_userdata" / "secrets" / service["name"] / filename
            if not path.is_file():
                raise ValueError(f"missing runtime secret file for {service['name']}")
            _verify_secret_permissions(path, runtime_uid)
            value = path.read_text(encoding="utf-8").rstrip("\r\n")
            if "\n" in value or "\r" in value or len(value) < 32 or value == SENTINEL:
                raise ValueError(f"runtime secret policy failed for {service['name']}")
            all_values.append(value)
    if len(all_values) != len(set(all_values)):
        raise ValueError("runtime secrets must be unique")
    return identity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap isolated Freqtrade runtime state")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    subparsers.add_parser("verify")
    subparsers.add_parser("sanitize-api-configs")
    subparsers.add_parser("migrate-research-paths")
    rotate = subparsers.add_parser("rotate-secrets")
    rotate.add_argument("--service", action="append", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = load_runtime_manifest(args.manifest)
    root = args.root.resolve()
    if args.command == "init":
        init_runtime(root, manifest)
    elif args.command == "verify":
        verify_runtime(root, manifest)
    elif args.command == "sanitize-api-configs":
        sanitize_api_configs(root, manifest)
    elif args.command == "migrate-research-paths":
        migrate_research_paths(root, manifest)
    elif args.command == "rotate-secrets":
        rotate_secrets(root, manifest, set(args.service))
    print(f"runtime bootstrap: {args.command}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
