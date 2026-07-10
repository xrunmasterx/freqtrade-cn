from __future__ import annotations

import argparse
import json
import posixpath
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

if __package__:
    from tools.runtime_manifest import load_runtime_manifest
else:
    from runtime_manifest import load_runtime_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "__SET_VIA_SECRET_FILE__"
API_SECRET_KEYS = ("password", "jwt_secret_key", "ws_token")
EXCHANGE_SECRET_KEYS = ("key", "secret", "password", "uid")
EXPECTED_CONFIGS = [
    "/freqtrade/config/runtime.json",
    "/freqtrade/config/trading-safety.json",
]
READ_ONLY_TARGETS = {
    "/freqtrade/config/runtime.json",
    "/freqtrade/config/trading-safety.json",
    "/freqtrade/user_data/strategies",
    "/freqtrade/user_data/research_data",
}
DIRECT_SECRET_ENV = {
    "FREQTRADE__API_SERVER__PASSWORD",
    "FREQTRADE__API_SERVER__JWT_SECRET_KEY",
    "FREQTRADE__API_SERVER__WS_TOKEN",
}
EXPECTED_ENVIRONMENT = {
    "FT_API_PASSWORD_FILE": "/run/secrets/api_password",
    "FT_JWT_SECRET_FILE": "/run/secrets/jwt_secret_key",
    "FT_WS_TOKEN_FILE": "/run/secrets/ws_token",
    "HOME": "/freqtrade/state/home",
}
SECRET_TARGETS = {
    "api_password": "api_password",
    "jwt_secret": "jwt_secret_key",
    "ws_token": "ws_token",
}
ALLOWED_PROFILES = {"trading", "research"}
USER_PATTERN = re.compile(r"[1-9][0-9]*:[1-9][0-9]*\Z")


def _load_json_object(
    path: Path,
    invalid_error: str,
    read_error: str,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return None, read_error
    except (json.JSONDecodeError, RecursionError):
        return None, invalid_error
    if type(data) is not dict:
        return None, invalid_error
    return data, None


def validate_tracked_configs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "ft_userdata/user_data/config*.json"],
            cwd=repo_root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ["tracked config inventory failed"]

    relative_paths: list[Path] = []
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        try:
            relative_paths.append(Path(item.decode("utf-8")))
        except UnicodeDecodeError:
            return ["tracked config path encoding is invalid"]

    for relative in relative_paths:
        if not relative.name.endswith(".example.json"):
            errors.append(f"tracked operational config is forbidden: {relative.as_posix()}")
            continue
        data, load_error = _load_json_object(
            repo_root / relative,
            f"tracked template is not valid JSON or must be an object: {relative.as_posix()}",
            f"tracked template could not be read: {relative.as_posix()}",
        )
        if load_error:
            errors.append(load_error)
            continue
        assert data is not None
        if data.get("dry_run") is not True:
            errors.append(f"tracked template must be dry-run: {relative.as_posix()}")

        api = data.get("api_server")
        if type(api) is not dict:
            errors.append(f"tracked API section must be an object: {relative.as_posix()}")
        else:
            for key in API_SECRET_KEYS:
                if api.get(key) != SENTINEL:
                    errors.append(
                        f"tracked API field must use sentinel: {relative.as_posix()}:{key}"
                    )

        exchange = data.get("exchange")
        if type(exchange) is not dict:
            errors.append(f"tracked exchange section must be an object: {relative.as_posix()}")
        else:
            for key in EXCHANGE_SECRET_KEYS:
                if exchange.get(key) not in (None, ""):
                    errors.append(
                        f"tracked exchange field must be empty: {relative.as_posix()}:{key}"
                    )

    policy_path = repo_root / "ops/config/trading-safety.json"
    policy, policy_error = _load_json_object(
        policy_path,
        "trading safety policy is not a valid JSON object",
        "trading safety policy could not be read",
    )
    if policy_error:
        errors.append(policy_error)
    elif not (
        set(policy) == {"dry_run", "ignore_buying_expired_candle_after"}
        and policy.get("dry_run") is True
        and type(policy.get("ignore_buying_expired_candle_after")) is int
        and policy["ignore_buying_expired_candle_after"] == 60
    ):
        errors.append("trading safety policy must force dry-run and 60-second freshness")
    return errors


def option_values(tokens: list[str], option: str) -> list[str]:
    return [
        tokens[index + 1]
        for index, token in enumerate(tokens[:-1])
        if token == option
    ]


def _command_tokens(command: object) -> list[str] | None:
    if type(command) is str:
        try:
            return shlex.split(command)
        except ValueError:
            return None
    if type(command) is list and all(type(token) is str for token in command):
        return command
    return None


def _source_matches(source: object, expected_relative: object) -> bool:
    if type(source) is not str or type(expected_relative) is not str:
        return False
    normalized_source = posixpath.normpath(source.replace("\\", "/"))
    normalized_expected = posixpath.normpath(expected_relative)
    return normalized_source == normalized_expected or normalized_source.endswith(
        f"/{normalized_expected}"
    )


def _expected_secret_mapping(service_name: str) -> dict[str, str]:
    prefix = service_name.replace("-", "_")
    return {
        f"{prefix}_{suffix}": target for suffix, target in SECRET_TARGETS.items()
    }


def _manifest_services(manifest: object) -> dict[str, dict[str, object]] | None:
    if type(manifest) is not dict or type(manifest.get("services")) is not list:
        return None
    entries: dict[str, dict[str, object]] = {}
    for entry in manifest["services"]:
        if type(entry) is not dict or type(entry.get("name")) is not str:
            return None
        entries[entry["name"]] = entry
    return entries


def validate_compose(manifest: dict[str, object], compose: dict[str, object]) -> list[str]:
    errors: list[str] = []
    manifest_services = _manifest_services(manifest)
    if manifest_services is None:
        return ["runtime manifest services must be objects"]
    if type(compose) is not dict:
        return ["rendered Compose must be an object"]
    compose_services = compose.get("services")
    if type(compose_services) is not dict:
        return ["rendered Compose services must be an object"]
    compose_secrets = compose.get("secrets")
    if type(compose_secrets) is not dict:
        return ["rendered Compose secrets must be an object"]

    if set(manifest_services) != set(compose_services):
        errors.append("Compose services differ from runtime manifest")

    expected_top_level_secrets: dict[str, tuple[str, str]] = {}
    for name in manifest_services:
        for suffix, filename in SECRET_TARGETS.items():
            source = f"{name.replace('-', '_')}_{suffix}"
            expected_top_level_secrets[source] = (name, filename)
    if set(compose_secrets) != set(expected_top_level_secrets):
        errors.append("Compose secrets differ from runtime contract")
    for source in sorted(set(compose_secrets) & set(expected_top_level_secrets)):
        definition = compose_secrets[source]
        if type(definition) is not dict:
            errors.append(f"secret {source}: definition must be an object")
            continue
        name, filename = expected_top_level_secrets[source]
        expected_path = f"ft_userdata/secrets/{name}/{filename}"
        if (
            set(definition) != {"name", "file"}
            or definition.get("name") != f"freqtrade-cn_{source}"
            or not _source_matches(definition.get("file"), expected_path)
        ):
            errors.append(f"secret {source}: secret file differs from runtime contract")

    state_sources: set[str] = set()
    secret_owners: dict[str, str] = {}
    runtime_users: set[str] = set()
    published_ports: set[str] = set()
    saw_additional_profile = False

    for name in sorted(set(manifest_services) & set(compose_services)):
        expected = manifest_services[name]
        service = compose_services[name]
        if type(service) is not dict:
            errors.append(f"{name}: service must be an object")
            continue

        if "fullstake" in name.lower():
            errors.append(f"{name}: fullstake service is forbidden")

        user = service.get("user")
        if type(user) is not str or USER_PATTERN.fullmatch(user) is None:
            errors.append(f"{name}: runtime user must be one non-root uid:gid")
        else:
            runtime_users.add(user)

        if service.get("init") is not True:
            errors.append(f"{name}: init must be true")
        if service.get("cap_drop") != ["ALL"]:
            errors.append(f"{name}: cap_drop must be exactly ALL")
        security_opt = service.get("security_opt")
        if type(security_opt) is not list or "no-new-privileges:true" not in security_opt:
            errors.append(f"{name}: no-new-privileges is required")
        elif security_opt != ["no-new-privileges:true"]:
            errors.append(f"{name}: security_opt differs from runtime contract")

        profiles = service.get("profiles")
        expected_profile = expected.get("profile")
        if profiles != [expected_profile]:
            errors.append(f"{name}: Compose profile differs from runtime manifest")
        if type(profiles) is not list or any(
            type(profile) is not str or profile not in ALLOWED_PROFILES
            for profile in profiles
        ):
            saw_additional_profile = True

        environment = service.get("environment")
        if type(environment) is not dict:
            errors.append(f"{name}: environment must be an object")
        else:
            if DIRECT_SECRET_ENV & set(environment):
                errors.append(f"{name}: direct secret environment is forbidden")
            if environment != EXPECTED_ENVIRONMENT:
                errors.append(f"{name}: environment differs from runtime contract")

        volumes = service.get("volumes")
        if type(volumes) is not list:
            errors.append(f"{name}: volumes must be a list")
            volumes = []
        valid_volumes: list[dict[str, object]] = []
        for volume in volumes:
            if type(volume) is not dict:
                errors.append(f"{name}: volume entries must be objects")
                continue
            valid_volumes.append(volume)
            if volume.get("type") != "bind":
                errors.append(f"{name}: all mounts must be bind mounts")
            bind = volume.get("bind")
            if type(bind) is not dict or bind.get("create_host_path") is not False:
                errors.append(f"{name}: bind mount must set create_host_path false")
            target = volume.get("target")
            if type(target) is not str:
                errors.append(f"{name}: volume target must be a string")
                continue
            if target == "/freqtrade/user_data" and volume.get("read_only") is not True:
                errors.append(f"{name}: whole user_data cannot be writable")
            if target in READ_ONLY_TARGETS and volume.get("read_only") is not True:
                errors.append(f"{name}: {target} must be read-only")
            if "docker.sock" in str(volume.get("source", "")).lower():
                errors.append(f"{name}: Docker socket mount is forbidden")

        state = [
            volume for volume in valid_volumes if volume.get("target") == "/freqtrade/state"
        ]
        if len(state) != 1 or state[0].get("read_only") is True:
            errors.append(f"{name}: expected one writable state mount")
        else:
            state_source = state[0].get("source")
            if not _source_matches(state_source, expected.get("state_root")):
                errors.append(f"{name}: state source differs from runtime manifest")
            if type(state_source) is str:
                normalized_state = posixpath.normpath(state_source.replace("\\", "/"))
                if normalized_state in state_sources:
                    errors.append(f"{name}: state source must be unique")
                state_sources.add(normalized_state)

        role = expected.get("role")
        writable_targets = {
            target
            for volume in valid_volumes
            if volume.get("read_only") is not True
            for target in [volume.get("target")]
            if type(target) is str
        }
        expected_writable = {"/freqtrade/state"}
        if role == "research":
            expected_writable |= {
                "/freqtrade/user_data/data",
                "/freqtrade/user_data/backtest_results",
            }
        if writable_targets != expected_writable:
            errors.append(f"{name}: writable mount targets differ from runtime contract")

        required_sources = {
            "/freqtrade/config/runtime.json": expected.get("config_path"),
            "/freqtrade/user_data/strategies": "ft_userdata/user_data/strategies",
        }
        if role == "trading":
            required_sources["/freqtrade/config/trading-safety.json"] = (
                "ops/config/trading-safety.json"
            )
        else:
            required_sources["/freqtrade/user_data/research_data"] = (
                "ft_userdata/user_data/research_data"
            )
            state_root = expected.get("state_root")
            if type(state_root) is str:
                required_sources["/freqtrade/user_data/data"] = f"{state_root}/data"
                required_sources["/freqtrade/user_data/backtest_results"] = (
                    f"{state_root}/backtest_results"
                )
        for target, expected_source in required_sources.items():
            matches = [volume for volume in valid_volumes if volume.get("target") == target]
            if len(matches) != 1 or not _source_matches(
                matches[0].get("source"), expected_source
            ):
                label = (
                    "config source differs from runtime manifest"
                    if target == "/freqtrade/config/runtime.json"
                    else f"{target} source differs from runtime contract"
                )
                errors.append(f"{name}: {label}")

        mounted_secrets = service.get("secrets")
        actual_secret_mapping: dict[str, str] = {}
        if type(mounted_secrets) is not list:
            errors.append(f"{name}: secrets must be a list")
        else:
            for secret in mounted_secrets:
                if type(secret) is not dict:
                    errors.append(f"{name}: secret entries must be objects")
                    continue
                source = secret.get("source")
                target = secret.get("target")
                if type(source) is str and type(target) is str:
                    actual_secret_mapping[source] = target
                    owner = secret_owners.setdefault(source, name)
                    if owner != name:
                        errors.append(f"{name}: secret source must be used by one service")
        if actual_secret_mapping != _expected_secret_mapping(name):
            errors.append(f"{name}: API secret mapping differs from runtime contract")

        ports = service.get("ports")
        if type(ports) is not list or len(ports) != 1 or type(ports[0]) is not dict:
            errors.append(f"{name}: port mapping differs from runtime contract")
        else:
            port = ports[0]
            if port.get("host_ip") != "127.0.0.1":
                errors.append(f"{name}: host port must bind 127.0.0.1")
            published = port.get("published")
            published_is_valid = (
                type(published) is int and 1 <= published <= 65535
            ) or (
                type(published) is str
                and published.isdecimal()
                and len(published) <= 5
                and str(int(published)) == published
                and 1 <= int(published) <= 65535
            )
            if (
                type(port.get("target")) is not int
                or port.get("target") != 8080
                or port.get("protocol") != "tcp"
                or port.get("mode") != "ingress"
                or not published_is_valid
            ):
                errors.append(f"{name}: port mapping differs from runtime contract")
            if published_is_valid:
                published_text = str(published)
                if published_text in published_ports:
                    errors.append(f"{name}: published host port must be unique")
                published_ports.add(published_text)

        tokens = _command_tokens(service.get("command"))
        if tokens is None:
            errors.append(f"{name}: command must be a valid string or string list")
            continue
        logs = option_values(tokens, "--logfile")
        if len(logs) != 1 or not logs[0].startswith("/freqtrade/state/logs/"):
            errors.append(f"{name}: logfile must live below /freqtrade/state/logs")
        databases = option_values(tokens, "--db-url")
        strategies = option_values(tokens, "--strategy")
        if role == "trading":
            if option_values(tokens, "--config") != EXPECTED_CONFIGS:
                errors.append(f"{name}: trading safety config must be last")
            database_filename = expected.get("database_filename")
            expected_database = f"sqlite:////freqtrade/state/{database_filename}"
            if databases != [expected_database]:
                errors.append(f"{name}: database must live below /freqtrade/state")
            if strategies != [expected.get("strategy")]:
                errors.append(f"{name}: strategy differs from runtime manifest")
        else:
            if databases:
                errors.append(f"{name}: research service cannot use a trading database")
            if strategies:
                errors.append(f"{name}: research service cannot select a strategy")

    if len(runtime_users) > 1:
        errors.append("runtime user must be identical for every service")
    if saw_additional_profile:
        errors.append("additional Compose profiles are forbidden")
    return errors


def _load_compose_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        return None
    return data if type(data) is dict else None


def _render_compose() -> dict[str, Any] | None:
    command = [
        sys.executable,
        str((REPO_ROOT / "tools/compose_runtime.py").resolve()),
        "--profile",
        "trading",
        "--profile",
        "research",
        "config",
        "--format",
        "json",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, RecursionError):
        return None
    return data if type(data) is dict else None


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the root runtime contract")
    parser.add_argument("--compose-json", type=Path)
    parser.add_argument("--check-configs-only", action="store_true")
    args = parser.parse_args(arguments)

    errors = validate_tracked_configs(REPO_ROOT)
    if args.check_configs_only:
        if errors:
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            return 1
        print("runtime contract: OK")
        return 0

    try:
        manifest = load_runtime_manifest()
    except (OSError, UnicodeError, ValueError, RecursionError):
        print("error: runtime manifest could not be loaded", file=sys.stderr)
        return 1

    if args.compose_json is not None:
        compose = _load_compose_file(args.compose_json)
        compose_error = "Compose JSON could not be loaded"
    else:
        compose = _render_compose()
        compose_error = "rendered Compose could not be loaded"
    if compose is None:
        print(f"error: {compose_error}", file=sys.stderr)
        return 1

    errors.extend(validate_compose(manifest, compose))
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("runtime contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
