from __future__ import annotations

import argparse
import base64
import json
import os
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


def _verify_secret_permissions(path: Path) -> None:
    if _is_windows():
        _run_windows_acl("verify", path)
    elif stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("runtime secret permissions must be 0600")


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
    for service in manifest["services"]:
        template = root / service["config_template"]
        config = root / service["config_path"]
        if not template.is_file():
            raise ValueError(f"missing config template for {service['name']}")
        if not config.exists():
            config.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(template, config)

        state_root = root / service["state_root"]
        (state_root / "logs").mkdir(parents=True, exist_ok=True)
        if service["role"] == "research":
            (state_root / "data").mkdir(parents=True, exist_ok=True)
            (state_root / "backtest_results").mkdir(parents=True, exist_ok=True)

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


def verify_runtime(root: Path, manifest: dict[str, Any]) -> None:
    all_values: list[str] = []
    state_roots: set[Path] = set()
    for service in manifest["services"]:
        config = root / service["config_path"]
        state_root = (root / service["state_root"]).resolve()
        if not config.is_file():
            raise ValueError(f"missing operational config for {service['name']}")
        if not state_root.is_dir() or state_root in state_roots:
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
            _verify_secret_permissions(path)
            value = path.read_text(encoding="utf-8").rstrip("\r\n")
            if "\n" in value or "\r" in value or len(value) < 32 or value == SENTINEL:
                raise ValueError(f"runtime secret policy failed for {service['name']}")
            all_values.append(value)
    if len(all_values) != len(set(all_values)):
        raise ValueError("runtime secrets must be unique")


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
    elif args.command == "rotate-secrets":
        rotate_secrets(root, manifest, set(args.service))
    print(f"runtime bootstrap: {args.command}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
