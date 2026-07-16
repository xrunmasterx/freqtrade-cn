from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath
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
EXPECTED_USER_DATA_DIR = "/freqtrade/state"
EXPECTED_STRATEGY_PATH = "/freqtrade/user_data/strategies"
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
ALLOWED_SERVICE_FIELDS = {
    "build",
    "cap_add",
    "cap_drop",
    "command",
    "container_name",
    "entrypoint",
    "environment",
    "extra_hosts",
    "healthcheck",
    "image",
    "init",
    "networks",
    "ports",
    "privileged",
    "profiles",
    "restart",
    "secrets",
    "security_opt",
    "user",
    "volumes",
}
EXPECTED_PORT_FIELDS = {"mode", "target", "published", "host_ip", "protocol"}
EXPECTED_TOP_LEVEL_FIELDS = {
    "name",
    "networks",
    "secrets",
    "services",
    "x-freqtrade-common",
}
EXPECTED_HEALTHCHECK = {
    "test": [
        "CMD-SHELL",
        "curl -fsS http://127.0.0.1:8080/api/v1/ping || exit 1",
    ],
    "timeout": "5s",
    "interval": "30s",
    "retries": 3,
    "start_period": "30s",
}
EXPECTED_EXTENSION = {
    "build": {"context": ".", "dockerfile": "Dockerfile"},
    "cap_drop": ["ALL"],
    "extra_hosts": ["host.docker.internal:host-gateway"],
    "image": "freqtrade-cn:local",
    "init": True,
    "restart": "unless-stopped",
    "security_opt": ["no-new-privileges:true"],
}
PLATFORM_SERVICES = {"platform-postgres", "platform-control", "platform-operator"}
PLATFORM_SECRET_FILES = {
    "platform_postgres_admin_password": "postgres_admin_password",
    "platform_control_db_password": "platform_control_db_password",
    "platform_supervisor_db_password": "platform_supervisor_db_password",
    "platform_operator_db_password": "platform_operator_db_password",
    "platform_control_api_password": "api_password",
    "platform_control_jwt_secret": "jwt_secret_key",
}
PLATFORM_CONTROL_ENVIRONMENT = {
    "PLATFORM_CONTROL_API_PASSWORD_FILE": "/run/secrets/api_password",
    "PLATFORM_CONTROL_BIND_MODE": "container_loopback_publish",
    "PLATFORM_CONTROL_JWT_SECRET_FILE": "/run/secrets/jwt_secret_key",
    "PLATFORM_CONTROL_LISTEN_HOST": "0.0.0.0",
    "PLATFORM_CONTROL_USERNAME": "platform_operator",
    "PLATFORM_DATABASE_HOST": "platform-postgres",
    "PLATFORM_DATABASE_NAME": "platform",
    "PLATFORM_DATABASE_PASSWORD_FILE": "/run/secrets/database_password",
    "PLATFORM_DATABASE_PORT": "5432",
    "PLATFORM_DATABASE_USERNAME": "platform_control",
}
PLATFORM_ROLE_SCRIPT_SHA256 = (
    "f0f8bd73375a3e90f5931b46f77c4ac22075688cf25e9ec39eadf85b2fd7a6d4"
)
EXPECTED_CONTAINER_NAMES = {
    "freqtrade": "freqtrade-cn",
    "freqtrade-futures": "freqtrade-cn-futures",
    "freqtrade-research": "freqtrade-cn-research",
}
USER_PATTERN = re.compile(r"[1-9][0-9]*:[1-9][0-9]*\Z")


def _exact_value(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return set(actual) == set(expected) and all(
            _exact_value(actual[key], expected[key]) for key in expected
        )
    if type(expected) is list:
        return len(actual) == len(expected) and all(
            _exact_value(actual_value, expected_value)
            for actual_value, expected_value in zip(actual, expected)
        )
    return actual == expected


def _load_json_blob(blob: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return None
    return data if type(data) is dict else None


def _parse_index_record(record: bytes) -> tuple[str, str] | None:
    try:
        metadata, encoded_path = record.split(b"\t", 1)
        mode, oid, stage = metadata.split(b" ")
        path = encoded_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return None
    if (
        mode != b"100644"
        or stage != b"0"
        or len(oid) not in {40, 64}
        or re.fullmatch(b"[0-9a-f]+", oid) is None
    ):
        return "", ""
    pure_path = PurePosixPath(path)
    if (
        not path
        or any(
            unicodedata.category(character).startswith("C")
            or unicodedata.category(character) in {"Zl", "Zp"}
            for character in path
        )
        or "\\" in path
        or pure_path.is_absolute()
        or pure_path.as_posix() != path
        or any(part in {"", ".", ".."} for part in pure_path.parts)
    ):
        return None
    return path, oid.decode("ascii")


def _index_blobs(repo_root: Path) -> tuple[dict[str, bytes], list[str]]:
    command = [
        "git",
        "ls-files",
        "--stage",
        "-z",
        "--",
        ":(glob)ft_userdata/user_data/**/config*.json",
        "ops/config/trading-safety.json",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return {}, ["tracked config inventory failed"]

    entries: dict[str, str] = {}
    errors: list[str] = []
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        parsed = _parse_index_record(record)
        if parsed is None:
            return {}, ["tracked config index is malformed"]
        path, oid = parsed
        if not path:
            errors.append("tracked config must be a regular stage-0 file")
            continue
        if path in entries:
            errors.append("tracked config index contains duplicate paths")
            continue
        entries[path] = oid

    blobs: dict[str, bytes] = {}
    for path, oid in entries.items():
        try:
            result = subprocess.run(
                ["git", "cat-file", "blob", oid],
                cwd=repo_root,
                capture_output=True,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            errors.append("tracked config blob could not be read")
            continue
        blobs[path] = result.stdout
    return blobs, errors


def validate_tracked_configs(repo_root: Path) -> list[str]:
    blobs, errors = _index_blobs(repo_root)
    if not blobs and errors:
        return errors
    policy_path = "ops/config/trading-safety.json"
    for path, blob in blobs.items():
        if path == policy_path:
            continue
        relative = PurePosixPath(path)
        if relative.parent.as_posix() != "ft_userdata/user_data":
            errors.append("tracked config path is forbidden")
            continue
        if not relative.name.startswith("config") or not relative.name.endswith(".json"):
            errors.append("tracked config path is forbidden")
            continue
        if not relative.name.endswith(".example.json"):
            errors.append(f"tracked operational config is forbidden: {path}")
            continue
        data = _load_json_blob(blob)
        if data is None:
            errors.append(f"tracked template is not valid JSON or must be an object: {path}")
            continue
        if data.get("dry_run") is not True:
            errors.append(f"tracked template must be dry-run: {path}")

        api = data.get("api_server")
        if type(api) is not dict:
            errors.append(f"tracked API section must be an object: {path}")
        else:
            for key in API_SECRET_KEYS:
                if api.get(key) != SENTINEL:
                    errors.append(f"tracked API field must use sentinel: {path}:{key}")

        exchange = data.get("exchange")
        if type(exchange) is not dict:
            errors.append(f"tracked exchange section must be an object: {path}")
        else:
            for key in EXCHANGE_SECRET_KEYS:
                if exchange.get(key) not in (None, ""):
                    errors.append(f"tracked exchange field must be empty: {path}:{key}")

    policy_blob = blobs.get(policy_path)
    if policy_blob is None:
        errors.append("trading safety policy must be a tracked regular stage-0 file")
        return errors
    policy = _load_json_blob(policy_blob)
    if policy is None:
        errors.append("trading safety policy is not a valid JSON object")
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


def _is_normalized_container_child(value: object, parent: str) -> bool:
    if type(value) is not str or not value or "\\" in value:
        return False
    if any(ord(character) < 32 for character in value):
        return False
    if not value.startswith("/") or posixpath.normpath(value) != value:
        return False
    prefix = parent.rstrip("/") + "/"
    return value.startswith(prefix) and bool(posixpath.basename(value))


def _path_error(
    source: object,
    expected_relative: object,
    repo_root: Path,
    expected_kind: str,
) -> str | None:
    if type(source) is not str or not source or type(expected_relative) is not str:
        return "source path must be absolute"
    actual = Path(source)
    if not actual.is_absolute():
        return "source path must be absolute"
    if ".." in actual.parts or any(ord(character) < 32 for character in source):
        return "source path must not contain traversal"

    root = repo_root.resolve()
    expected = (root / expected_relative).absolute()
    if os.path.normcase(str(actual.absolute())) != os.path.normcase(str(expected)):
        return "source differs from runtime contract"
    if actual.is_symlink():
        return "symlink source is forbidden"
    try:
        resolved = actual.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return "source resolves outside repo"
    if os.path.normcase(str(resolved)) != os.path.normcase(str(expected.resolve())):
        return "source resolves outside repo"
    if expected_kind == "file" and not actual.is_file():
        return "source type differs from runtime contract"
    if expected_kind == "directory" and not actual.is_dir():
        return "source type differs from runtime contract"
    return None


def _expected_volumes(
    service: dict[str, object],
) -> dict[str, tuple[object, bool, str]]:
    expected = {
        "/freqtrade/config/runtime.json": (service.get("config_path"), True, "file"),
        "/freqtrade/user_data/strategies": (
            "ft_userdata/user_data/strategies",
            True,
            "directory",
        ),
        "/freqtrade/state": (service.get("state_root"), False, "directory"),
    }
    if service.get("role") == "trading":
        expected["/freqtrade/config/trading-safety.json"] = (
            "ops/config/trading-safety.json",
            True,
            "file",
        )
    else:
        expected["/freqtrade/user_data/research_data"] = (
            "ft_userdata/user_data/research_data",
            True,
            "directory",
        )
    return expected


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


def validate_compose(
    manifest: dict[str, object],
    compose: dict[str, object],
    *,
    repo_root: Path = REPO_ROOT,
    launch_service: str | None = None,
    launch_image_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    manifest_services = _manifest_services(manifest)
    if manifest_services is None:
        return ["runtime manifest services must be objects"]
    if (launch_service is None) != (launch_image_id is None):
        return ["launch image contract is incomplete"]
    if launch_service is not None and launch_service not in manifest_services:
        return ["launch service differs from runtime manifest"]
    if launch_image_id is not None and re.fullmatch(r"sha256:[0-9a-f]{64}", launch_image_id) is None:
        return ["launch image ID is invalid"]
    if type(compose) is not dict:
        return ["rendered Compose must be an object"]
    if set(compose) != EXPECTED_TOP_LEVEL_FIELDS:
        errors.append("top-level fields differ from runtime contract")
    if compose.get("name") != "freqtrade-cn":
        errors.append("Compose project name differs from runtime contract")
    expected_networks = {
        "default": {"name": "freqtrade-cn_default", "ipam": {}}
    }
    if not _exact_value(compose.get("networks"), expected_networks):
        errors.append("top-level networks differ from runtime contract")
    if not _exact_value(compose.get("x-freqtrade-common"), EXPECTED_EXTENSION):
        errors.append("Compose extension differs from runtime contract")
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
        if set(definition) != {"name", "file"}:
            errors.append(
                f"secret {source}: secret definition fields differ from runtime contract"
            )
        if definition.get("name") != f"freqtrade-cn_{source}":
            errors.append(f"secret {source}: secret file differs from runtime contract")
        secret_path_error = _path_error(
            definition.get("file"), expected_path, repo_root, "file"
        )
        if secret_path_error:
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
        if set(service) - ALLOWED_SERVICE_FIELDS:
            errors.append(f"{name}: service fields differ from runtime contract")

        if "entrypoint" not in service or service.get("entrypoint") is not None:
            errors.append(f"{name}: entrypoint must be null")
        expected_build = {
            "context": str(repo_root.resolve()),
            "dockerfile": "Dockerfile",
        }
        if name == launch_service:
            if "build" in service:
                errors.append(f"{name}: build is forbidden for launch")
            if service.get("image") != launch_image_id:
                errors.append(f"{name}: image differs from inspected image ID")
        else:
            if not _exact_value(service.get("build"), expected_build):
                errors.append(f"{name}: build differs from runtime contract")
            if service.get("image") != "freqtrade-cn:local":
                errors.append(f"{name}: image differs from runtime contract")
        if service.get("container_name") != EXPECTED_CONTAINER_NAMES.get(name):
            errors.append(f"{name}: container name differs from runtime contract")
        if service.get("restart") != "unless-stopped":
            errors.append(f"{name}: restart policy differs from runtime contract")
        if not _exact_value(
            service.get("extra_hosts"), ["host.docker.internal=host-gateway"]
        ):
            errors.append(f"{name}: extra_hosts differs from runtime contract")
        if not _exact_value(service.get("healthcheck"), EXPECTED_HEALTHCHECK):
            errors.append(f"{name}: healthcheck differs from runtime contract")
        if not _exact_value(service.get("networks"), {"default": None}):
            errors.append(f"{name}: service networks differ from runtime contract")

        if "fullstake" in name.lower():
            errors.append(f"{name}: fullstake service is forbidden")

        if "privileged" in service and service.get("privileged") is not False:
            errors.append(f"{name}: privileged must be false")
            errors.append(f"{name}: privilege escalation field is forbidden")
        if "cap_add" in service and service.get("cap_add") != []:
            errors.append(f"{name}: privilege escalation field is forbidden")
        for field in (
            "devices",
            "device_cgroup_rules",
            "volumes_from",
            "gpus",
            "device_requests",
            "runtime",
        ):
            if field in service:
                errors.append(f"{name}: privilege escalation field is forbidden")
        for field in ("network_mode", "pid", "ipc", "uts", "userns_mode"):
            if field in service:
                errors.append(f"{name}: privilege escalation field is forbidden")

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
        expected_volumes = _expected_volumes(expected)
        seen_targets: list[str] = []
        for volume in volumes:
            if type(volume) is not dict:
                errors.append(f"{name}: volume entries must be objects")
                continue
            valid_volumes.append(volume)
            if set(volume) - {"type", "source", "target", "read_only", "bind"}:
                errors.append(f"{name}: volume fields differ from runtime contract")
            if volume.get("type") != "bind":
                errors.append(f"{name}: all mounts must be bind mounts")
            bind = volume.get("bind")
            if type(bind) is not dict:
                errors.append(f"{name}: bind mount must set create_host_path false")
            elif set(bind) != {"create_host_path"}:
                errors.append(f"{name}: bind fields differ from runtime contract")
            if type(bind) is dict and bind.get("create_host_path") is not False:
                errors.append(f"{name}: bind mount must set create_host_path false")
            target = volume.get("target")
            if type(target) is not str:
                errors.append(f"{name}: volume target must be a string")
                continue
            seen_targets.append(target)
            if target == "/freqtrade/user_data" and volume.get("read_only") is not True:
                errors.append(f"{name}: whole user_data cannot be writable")
            if "docker.sock" in str(volume.get("source", "")).lower():
                errors.append(f"{name}: Docker socket mount is forbidden")
            specification = expected_volumes.get(target)
            if specification is None:
                continue
            expected_source, expected_read_only, expected_kind = specification
            read_only = volume.get("read_only")
            if expected_read_only:
                if read_only is not True:
                    errors.append(f"{name}: read_only must be an exact boolean")
                    errors.append(f"{name}: {target} must be read-only")
            elif "read_only" in volume and read_only is not False:
                errors.append(f"{name}: read_only must be an exact boolean")
            source_error = _path_error(
                volume.get("source"),
                expected_source,
                repo_root,
                expected_kind,
            )
            if source_error:
                errors.append(f"{name}: {source_error}")
                if target == "/freqtrade/config/runtime.json":
                    errors.append(f"{name}: config source differs from runtime manifest")
                if target == "/freqtrade/state":
                    errors.append(f"{name}: state source differs from runtime manifest")

        if set(seen_targets) != set(expected_volumes) or len(seen_targets) != len(
            expected_volumes
        ):
            errors.append(f"{name}: volume set differs from runtime contract")
            errors.append(f"{name}: writable mount targets differ from runtime contract")

        state = [
            volume for volume in valid_volumes if volume.get("target") == "/freqtrade/state"
        ]
        if len(state) != 1 or state[0].get("read_only") is True:
            errors.append(f"{name}: expected one writable state mount")
        elif type(state[0].get("source")) is str:
            normalized_state = os.path.normcase(str(Path(state[0]["source"]).absolute()))
            if normalized_state in state_sources:
                errors.append(f"{name}: state source must be unique")
            state_sources.add(normalized_state)

        role = expected.get("role")

        mounted_secrets = service.get("secrets")
        actual_secret_mapping: dict[str, str] = {}
        seen_secret_pairs: set[tuple[str, str]] = set()
        if type(mounted_secrets) is not list:
            errors.append(f"{name}: secrets must be a list")
        else:
            if len(mounted_secrets) != 3:
                errors.append(f"{name}: expected exactly three API secrets")
            for secret in mounted_secrets:
                if type(secret) is not dict:
                    errors.append(f"{name}: secret entries must be objects")
                    continue
                if set(secret) != {"source", "target"}:
                    errors.append(
                        f"{name}: secret entry fields differ from runtime contract"
                    )
                source = secret.get("source")
                target = secret.get("target")
                if type(source) is not str or type(target) is not str:
                    errors.append(
                        f"{name}: secret entry fields differ from runtime contract"
                    )
                    continue
                pair = (source, target)
                if pair in seen_secret_pairs or source in actual_secret_mapping:
                    errors.append(f"{name}: secret entries must be unique")
                seen_secret_pairs.add(pair)
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
            if set(port) != EXPECTED_PORT_FIELDS:
                errors.append(f"{name}: port fields differ from runtime contract")
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

        raw_command = service.get("command")
        if type(raw_command) is str and any(
            ord(character) < 32 for character in raw_command
        ):
            errors.append(f"{name}: logfile must be a normalized state log path")
            continue
        tokens = _command_tokens(raw_command)
        if not tokens:
            errors.append(f"{name}: command must be a valid string or string list")
            continue
        if role == "trading" and tokens[0] != "trade":
            errors.append(f"{name}: trading command must start with trade")
        if role == "research" and tokens[0] != "webserver":
            errors.append(f"{name}: research command must start with webserver")
        logs = option_values(tokens, "--logfile")
        if len(logs) != 1 or not _is_normalized_container_child(
            logs[0], "/freqtrade/state/logs"
        ):
            errors.append(f"{name}: logfile must live below /freqtrade/state/logs")
            errors.append(f"{name}: logfile must be a normalized state log path")
        databases = option_values(tokens, "--db-url")
        strategies = option_values(tokens, "--strategy")
        user_data_directories = option_values(tokens, "--user-data-dir")
        strategy_paths = option_values(tokens, "--strategy-path")
        if user_data_directories != [EXPECTED_USER_DATA_DIR]:
            errors.append(f"{name}: userdata directory differs from runtime contract")
        expected_log = f"/freqtrade/state/logs/{name}.log"
        if role == "trading":
            if option_values(tokens, "--config") != EXPECTED_CONFIGS:
                errors.append(f"{name}: trading safety config must be last")
            database_filename = expected.get("database_filename")
            expected_database = f"sqlite:////freqtrade/state/{database_filename}"
            if databases != [expected_database]:
                errors.append(f"{name}: database must live below /freqtrade/state")
                errors.append(f"{name}: database must be a normalized state path")
            if strategies != [expected.get("strategy")]:
                errors.append(f"{name}: strategy differs from runtime manifest")
            if strategy_paths != [EXPECTED_STRATEGY_PATH]:
                errors.append(f"{name}: strategy path differs from runtime contract")
            expected_tokens = [
                "trade",
                "--logfile",
                expected_log,
                "--db-url",
                expected_database,
                "--config",
                EXPECTED_CONFIGS[0],
                "--config",
                EXPECTED_CONFIGS[1],
                "--user-data-dir",
                EXPECTED_USER_DATA_DIR,
                "--strategy-path",
                EXPECTED_STRATEGY_PATH,
                "--strategy",
                expected.get("strategy"),
            ]
        else:
            if databases:
                errors.append(f"{name}: research service cannot use a trading database")
            if strategies:
                errors.append(f"{name}: research service cannot select a strategy")
            if strategy_paths:
                errors.append(f"{name}: research service cannot use a strategy path")
            expected_tokens = [
                "webserver",
                "--logfile",
                expected_log,
                "--config",
                "/freqtrade/config/runtime.json",
                "--user-data-dir",
                EXPECTED_USER_DATA_DIR,
            ]
        if tokens != expected_tokens:
            errors.append(f"{name}: formal argv differs from runtime contract")

    if len(runtime_users) > 1:
        errors.append("runtime user must be identical for every service")
    if saw_additional_profile:
        errors.append("additional Compose profiles are forbidden")
    return errors


def _platform_path_matches(value: object, expected: Path) -> bool:
    if type(value) is not str:
        return False
    try:
        return Path(value).resolve() == expected.resolve()
    except (OSError, RuntimeError):
        return False


def _normalize_platform_role_script(content: bytes) -> str | None:
    if content.startswith(b"\xef\xbb\xbf") or b"\x00" in content:
        return None
    try:
        script = content.decode("utf-8")
    except UnicodeError:
        return None
    normalized = script.replace("\r\n", "\n")
    if "\r" in normalized:
        return None
    return normalized


def _active_platform_role_script(script: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", script, flags=re.DOTALL)
    active_lines: list[str] = []
    for line in without_blocks.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith("--"):
            continue
        active_lines.append(line.split("--", 1)[0])
    return " ".join(" ".join(active_lines).upper().split())


def _role_table_inventory(active: str, alias: str) -> list[str] | None:
    match = re.search(
        rf"FROM \(VALUES ((?:(?!FROM \(VALUES).)*?)\) AS {alias}\(TABLE_NAME\)",
        active,
    )
    if match is None:
        return None
    return re.findall(r"\('([^']+)'\)", match.group(1))


def _validate_platform_role_script(repo_root: Path) -> list[str]:
    path = repo_root / "docker/postgres/init-platform-roles.sh"
    try:
        script = _normalize_platform_role_script(path.read_bytes())
    except OSError:
        return ["platform role initializer could not be loaded"]
    if script is None:
        return ["platform role initializer could not be loaded"]
    active = _active_platform_role_script(script)
    compact = re.sub(r"\(\s+", "(", active)
    compact = re.sub(r"\s+\)", ")", compact)
    joined_strings = re.sub(r"'\s+'", "", compact)
    errors: list[str] = []

    digest = hashlib.sha256(script.encode("utf-8")).hexdigest()

    secret_fragments = (
        "WHEN RIGHT(SECRET_VALUE, 2) = E'\\R\\N' THEN LEFT(SECRET_VALUE, -2)",
        "WHEN RIGHT(SECRET_VALUE, 1) = E'\\N' THEN LEFT(SECRET_VALUE, -1)",
    )
    secret_paths = (
        "PG_READ_FILE('/RUN/SECRETS/PLATFORM_CONTROL_DB_PASSWORD')",
        "PG_READ_FILE('/RUN/SECRETS/PLATFORM_SUPERVISOR_DB_PASSWORD')",
        "PG_READ_FILE('/RUN/SECRETS/PLATFORM_OPERATOR_DB_PASSWORD')",
    )
    if (
        re.search(r"\b(?:BTRIM|TRIM)\s*\(", active)
        or any(active.count(fragment) != 3 for fragment in secret_fragments)
        or any(active.count(path_fragment) != 1 for path_fragment in secret_paths)
    ):
        errors.append("platform role initializer secret normalization differs")

    role_hardening = (
        "ALTER ROLE PLATFORM_CONTROL WITH LOGIN NOSUPERUSER NOCREATEDB "
        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L",
        "ALTER ROLE PLATFORM_SUPERVISOR WITH LOGIN NOSUPERUSER NOCREATEDB "
        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L",
        "ALTER ROLE PLATFORM_OPERATOR WITH LOGIN NOSUPERUSER NOCREATEDB "
        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L",
    )
    if (
        any(active.count(fragment) != 1 for fragment in role_hardening)
        or active.count("CREATE ROLE PLATFORM_CONTROL") != 1
        or active.count("CREATE ROLE PLATFORM_SUPERVISOR") != 1
        or active.count("CREATE ROLE PLATFORM_OPERATOR") != 1
    ):
        errors.append("platform role initializer role hardening differs")

    membership_fragments = (
        "FORMAT('REVOKE %I FROM PLATFORM_CONTROL GRANTED BY %I CASCADE', "
        "GRANTED_ROLE.ROLNAME, GRANTOR_ROLE.ROLNAME)",
        "FORMAT('REVOKE PLATFORM_CONTROL FROM %I GRANTED BY %I CASCADE', "
        "MEMBER_ROLE.ROLNAME, GRANTOR_ROLE.ROLNAME)",
        "FORMAT('REVOKE %I FROM PLATFORM_SUPERVISOR GRANTED BY %I CASCADE', "
        "GRANTED_ROLE.ROLNAME, GRANTOR_ROLE.ROLNAME)",
        "FORMAT('REVOKE PLATFORM_SUPERVISOR FROM %I GRANTED BY %I CASCADE', "
        "MEMBER_ROLE.ROLNAME, GRANTOR_ROLE.ROLNAME)",
        "MEMBER_ROLE.ROLNAME = 'PLATFORM_CONTROL'",
        "GRANTED_ROLE.ROLNAME = 'PLATFORM_CONTROL'",
        "MEMBER_ROLE.ROLNAME = 'PLATFORM_SUPERVISOR'",
        "GRANTED_ROLE.ROLNAME = 'PLATFORM_SUPERVISOR'",
        "FORMAT('REVOKE %I FROM PLATFORM_OPERATOR GRANTED BY %I CASCADE', "
        "GRANTED_ROLE.ROLNAME, GRANTOR_ROLE.ROLNAME)",
        "FORMAT('REVOKE PLATFORM_OPERATOR FROM %I GRANTED BY %I CASCADE', "
        "MEMBER_ROLE.ROLNAME, GRANTOR_ROLE.ROLNAME)",
        "MEMBER_ROLE.ROLNAME = 'PLATFORM_OPERATOR'",
        "GRANTED_ROLE.ROLNAME = 'PLATFORM_OPERATOR'",
    )
    if (
        any(compact.count(fragment) != 1 for fragment in membership_fragments)
        or active.count("FROM PG_AUTH_MEMBERS AS MEMBERSHIP") != 6
        or active.count(
            "JOIN PG_ROLES AS GRANTED_ROLE ON GRANTED_ROLE.OID = MEMBERSHIP.ROLEID"
        )
        != 6
        or active.count(
            "JOIN PG_ROLES AS MEMBER_ROLE ON MEMBER_ROLE.OID = MEMBERSHIP.MEMBER"
        )
        != 6
        or active.count(
            "JOIN PG_ROLES AS GRANTOR_ROLE ON GRANTOR_ROLE.OID = MEMBERSHIP.GRANTOR"
        )
        != 6
    ):
        errors.append("platform role initializer membership cleanup differs")

    public_cleanup_formats = (
        "FORMAT('REVOKE %S ON DATABASE %I FROM PUBLIC GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, DATABASE.DATNAME, PUBLIC_GRANTOR_ROLE.ROLNAME)",
        "FORMAT('REVOKE %S ON SCHEMA %I FROM PUBLIC GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, NAMESPACE.NSPNAME, PUBLIC_GRANTOR_ROLE.ROLNAME)",
        "FORMAT('REVOKE %S ON TABLE %I.%I FROM PUBLIC GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, NAMESPACE.NSPNAME, RELATION.RELNAME, "
        "PUBLIC_GRANTOR_ROLE.ROLNAME)",
        "FORMAT('REVOKE %S ON SEQUENCE %I.%I FROM PUBLIC GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, NAMESPACE.NSPNAME, RELATION.RELNAME, "
        "PUBLIC_GRANTOR_ROLE.ROLNAME)",
        "FORMAT('REVOKE %S (%I) ON TABLE %I.%I FROM PUBLIC GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, ATTRIBUTE.ATTNAME, NAMESPACE.NSPNAME, "
        "RELATION.RELNAME, PUBLIC_GRANTOR_ROLE.ROLNAME)",
        "FORMAT('REVOKE EXECUTE ON ROUTINE %I.%I(%S) FROM PUBLIC GRANTED BY %I "
        "CASCADE', NAMESPACE.NSPNAME, ROUTINE.PRONAME, "
        "PG_GET_FUNCTION_IDENTITY_ARGUMENTS(ROUTINE.OID), PUBLIC_GRANTOR_ROLE.ROLNAME)",
    )
    public_acl_sources = (
        "ACLEXPLODE(COALESCE(DATABASE.DATACL, "
        "ACLDEFAULT('D', DATABASE.DATDBA))) AS PRIVILEGE",
        "ACLEXPLODE(COALESCE(NAMESPACE.NSPACL, "
        "ACLDEFAULT('N', NAMESPACE.NSPOWNER))) AS PRIVILEGE",
        "ACLEXPLODE(COALESCE(RELATION.RELACL, "
        "ACLDEFAULT('R', RELATION.RELOWNER))) AS PRIVILEGE",
        "ACLEXPLODE(COALESCE(RELATION.RELACL, "
        "ACLDEFAULT('S', RELATION.RELOWNER))) AS PRIVILEGE",
        "ACLEXPLODE(COALESCE(ATTRIBUTE.ATTACL, "
        "ACLDEFAULT('C', RELATION.RELOWNER))) AS PRIVILEGE",
        "ACLEXPLODE(COALESCE(ROUTINE.PROACL, "
        "ACLDEFAULT('F', ROUTINE.PROOWNER))) AS PRIVILEGE",
    )
    if (
        any(compact.count(fragment) != 1 for fragment in public_cleanup_formats)
        or any(compact.count(fragment) != 2 for fragment in public_acl_sources)
        or compact.count(" AS PUBLIC_SET_ROLE") != 6
        or compact.count(" AS PUBLIC_REVOKE_PRIVILEGE") != 6
        or compact.count(" AS PUBLIC_RESET_ROLE") != 6
        or compact.count(
            "JOIN PG_ROLES AS PUBLIC_GRANTOR_ROLE ON "
            "PUBLIC_GRANTOR_ROLE.OID = PRIVILEGE.GRANTOR"
        )
        != 6
        or compact.count("WHERE PRIVILEGE.GRANTEE = 0") != 12
    ):
        errors.append("platform role initializer public authority cleanup differs")

    default_privilege_hardening = (
        "ALTER DEFAULT PRIVILEGES FOR ROLE POSTGRES REVOKE EXECUTE ON ROUTINES "
        "FROM PUBLIC;",
        "ALTER DEFAULT PRIVILEGES FOR ROLE POSTGRES IN SCHEMA PUBLIC REVOKE ALL "
        "PRIVILEGES ON TABLES FROM PUBLIC;",
        "ALTER DEFAULT PRIVILEGES FOR ROLE POSTGRES IN SCHEMA PUBLIC REVOKE ALL "
        "PRIVILEGES ON SEQUENCES FROM PUBLIC;",
        "ALTER DEFAULT PRIVILEGES FOR ROLE POSTGRES IN SCHEMA PUBLIC REVOKE EXECUTE "
        "ON ROUTINES FROM PUBLIC;",
    )
    if any(active.count(fragment) != 1 for fragment in default_privilege_hardening):
        errors.append("platform role initializer default privilege hardening differs")

    ownership_guard_fragments = (
        "FROM PG_SHDEPEND AS SHARED_DEPENDENCY JOIN PG_ROLES AS FIXED_ROLE ON "
        "FIXED_ROLE.OID = SHARED_DEPENDENCY.REFOBJID",
        "SHARED_DEPENDENCY.REFCLASSID = 'PG_AUTHID'::REGCLASS",
        "SHARED_DEPENDENCY.DEPTYPE = 'O'",
        "FIXED_ROLE.ROLNAME IN ('PLATFORM_CONTROL', 'PLATFORM_SUPERVISOR', "
        "'PLATFORM_OPERATOR')",
        "FROM PG_DATABASE AS DATABASE JOIN PG_ROLES AS OWNER_ROLE ON "
        "OWNER_ROLE.OID = DATABASE.DATDBA",
        "FROM PG_NAMESPACE AS NAMESPACE JOIN PG_ROLES AS OWNER_ROLE ON "
        "OWNER_ROLE.OID = NAMESPACE.NSPOWNER",
        "FROM PG_CLASS AS RELATION JOIN PG_ROLES AS OWNER_ROLE ON "
        "OWNER_ROLE.OID = RELATION.RELOWNER",
        "RAISE EXCEPTION 'FIXED_PLATFORM_ROLE_OWNS_OBJECT'",
    )
    fixed_role_inventory = (
        "OWNER_ROLE.ROLNAME IN ('PLATFORM_CONTROL', 'PLATFORM_SUPERVISOR', "
        "'PLATFORM_OPERATOR')"
    )
    if (
        any(compact.count(fragment) != 1 for fragment in ownership_guard_fragments)
        or compact.count(fixed_role_inventory) != 3
    ):
        errors.append("platform role initializer ownership guard differs")

    default_authority_fragments = (
        "FROM PG_DEFAULT_ACL AS DEFAULT_ACL JOIN PG_ROLES AS DEFAULT_OWNER_ROLE ON "
        "DEFAULT_OWNER_ROLE.OID = DEFAULT_ACL.DEFACLROLE WHERE "
        "DEFAULT_OWNER_ROLE.ROLNAME = 'PLATFORM_OPERATOR'",
        "FROM PG_DEFAULT_ACL AS DEFAULT_ACL CROSS JOIN LATERAL "
        "ACLEXPLODE(DEFAULT_ACL.DEFACLACL) AS DEFAULT_PRIVILEGE WHERE "
        "DEFAULT_PRIVILEGE.GRANTEE = 0 OR DEFAULT_PRIVILEGE.GRANTEE = (SELECT OID "
        "FROM PG_ROLES WHERE ROLNAME = 'PLATFORM_OPERATOR')",
        "RAISE EXCEPTION 'UNSUPPORTED_PLATFORM_OPERATOR_DEFAULT_AUTHORITY'",
    )
    if any(compact.count(fragment) != 1 for fragment in default_authority_fragments):
        errors.append("platform role initializer default authority guard differs")

    public_guard_fragments = (
        "FROM PG_DATABASE AS DATABASE CROSS JOIN LATERAL "
        "ACLEXPLODE(COALESCE(DATABASE.DATACL, "
        "ACLDEFAULT('D', DATABASE.DATDBA))) AS PRIVILEGE WHERE "
        "PRIVILEGE.GRANTEE = 0",
        "FROM PG_PROC AS ROUTINE JOIN PG_NAMESPACE AS NAMESPACE ON "
        "NAMESPACE.OID = ROUTINE.PRONAMESPACE CROSS JOIN LATERAL "
        "ACLEXPLODE(COALESCE(ROUTINE.PROACL, "
        "ACLDEFAULT('F', ROUTINE.PROOWNER))) AS PRIVILEGE WHERE "
        "PRIVILEGE.GRANTEE = 0",
        "RAISE EXCEPTION 'UNSUPPORTED_PUBLIC_AUTHORITY'",
    )
    if any(compact.count(fragment) != 1 for fragment in public_guard_fragments):
        errors.append("platform role initializer public authority guard differs")

    fixed_authority_fragments = (
        "FROM PG_PROC AS ROUTINE JOIN PG_NAMESPACE AS NAMESPACE ON "
        "NAMESPACE.OID = ROUTINE.PRONAMESPACE CROSS JOIN LATERAL "
        "ACLEXPLODE(ROUTINE.PROACL) AS PRIVILEGE JOIN PG_ROLES AS "
        "ROUTINE_GRANTEE_ROLE ON ROUTINE_GRANTEE_ROLE.OID = PRIVILEGE.GRANTEE "
        "WHERE ROUTINE_GRANTEE_ROLE.ROLNAME IN ('PLATFORM_CONTROL', "
        "'PLATFORM_SUPERVISOR', 'PLATFORM_OPERATOR') AND (NAMESPACE.NSPNAME = "
        "'INFORMATION_SCHEMA' OR NAMESPACE.NSPNAME ~ "
        "'^PG_' OR PRIVILEGE.PRIVILEGE_TYPE <> 'EXECUTE')",
        "RAISE EXCEPTION 'UNSUPPORTED_PLATFORM_ROLE_AUTHORITY'",
    )
    if any(compact.count(fragment) != 1 for fragment in fixed_authority_fragments):
        errors.append("platform role initializer fixed authority guard differs")

    revocations = (
        "REVOKE ALL PRIVILEGES ON DATABASE PLATFORM FROM PLATFORM_CONTROL, "
        "PLATFORM_SUPERVISOR, PLATFORM_OPERATOR CASCADE;",
        "REVOKE ALL PRIVILEGES ON SCHEMA PUBLIC FROM PLATFORM_CONTROL, "
        "PLATFORM_SUPERVISOR, PLATFORM_OPERATOR CASCADE;",
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA PUBLIC FROM PLATFORM_CONTROL, "
        "PLATFORM_SUPERVISOR, PLATFORM_OPERATOR CASCADE;",
        "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA PUBLIC FROM PLATFORM_CONTROL, "
        "PLATFORM_SUPERVISOR, PLATFORM_OPERATOR CASCADE;",
    )
    if any(active.count(fragment) != 1 for fragment in revocations):
        errors.append("platform role initializer revocation inventory differs")

    object_formats = (
        "FORMAT('REVOKE %S ON DATABASE %I FROM %I GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, DATABASE.DATNAME, OBJECT_GRANTEE_ROLE.ROLNAME, "
        "OBJECT_GRANTOR_ROLE.ROLNAME) AS OBJECT_REVOKE_PRIVILEGE",
        "FORMAT('REVOKE %S ON SCHEMA %I FROM %I GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, NAMESPACE.NSPNAME, OBJECT_GRANTEE_ROLE.ROLNAME, "
        "OBJECT_GRANTOR_ROLE.ROLNAME) AS OBJECT_REVOKE_PRIVILEGE",
        "FORMAT('REVOKE %S ON TABLE %I.%I FROM %I GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, NAMESPACE.NSPNAME, RELATION.RELNAME, "
        "OBJECT_GRANTEE_ROLE.ROLNAME, OBJECT_GRANTOR_ROLE.ROLNAME) "
        "AS OBJECT_REVOKE_PRIVILEGE",
        "FORMAT('REVOKE %S ON SEQUENCE %I.%I FROM %I GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, NAMESPACE.NSPNAME, RELATION.RELNAME, "
        "OBJECT_GRANTEE_ROLE.ROLNAME, OBJECT_GRANTOR_ROLE.ROLNAME) "
        "AS OBJECT_REVOKE_PRIVILEGE",
    )
    object_fragment_counts = {
        "CROSS JOIN LATERAL ACLEXPLODE(DATABASE.DATACL) AS PRIVILEGE": 2,
        "CROSS JOIN LATERAL ACLEXPLODE(NAMESPACE.NSPACL) AS PRIVILEGE": 2,
        "CROSS JOIN LATERAL ACLEXPLODE(RELATION.RELACL) AS PRIVILEGE": 3,
        "DATABASE.DATNAME = 'PLATFORM'": 1,
        "NAMESPACE.NSPNAME <> 'INFORMATION_SCHEMA'": 15,
        "NAMESPACE.NSPNAME !~ '^PG_'": 15,
        "RELATION.RELKIND IN ('R', 'P', 'V', 'M', 'F')": 7,
        "RELATION.RELKIND = 'S'": 4,
        "PRIVILEGE.PRIVILEGE_TYPE IN ('CONNECT', 'CREATE', 'TEMPORARY')": 3,
        "PRIVILEGE.PRIVILEGE_TYPE IN ('USAGE', 'CREATE')": 3,
        "PRIVILEGE.PRIVILEGE_TYPE IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', "
        "'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN')": 3,
        "PRIVILEGE.PRIVILEGE_TYPE IN ('USAGE', 'SELECT', 'UPDATE')": 3,
        "PRIVILEGE.PRIVILEGE_TYPE NOT IN ('CONNECT', 'CREATE', 'TEMPORARY')": 1,
        "PRIVILEGE.PRIVILEGE_TYPE NOT IN ('USAGE', 'CREATE')": 1,
        "PRIVILEGE.PRIVILEGE_TYPE NOT IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', "
        "'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN')": 1,
        "PRIVILEGE.PRIVILEGE_TYPE NOT IN ('USAGE', 'SELECT', 'UPDATE')": 1,
        "OBJECT_GRANTEE_ROLE.ROLNAME IN ('PLATFORM_CONTROL', 'PLATFORM_SUPERVISOR', "
        "'PLATFORM_OPERATOR')": 4,
        "JOIN PG_ROLES AS OBJECT_GRANTOR_ROLE ON "
        "OBJECT_GRANTOR_ROLE.OID = PRIVILEGE.GRANTOR": 4,
        "RAISE EXCEPTION 'FIXED_PLATFORM_ROLE_OWNS_OBJECT'": 1,
        "RAISE EXCEPTION 'UNSUPPORTED_PLATFORM_ROLE_AUTHORITY'": 1,
    }
    object_execution_prefix = (
        "SELECT FORMAT('SET ROLE %I', OBJECT_GRANTOR_ROLE.ROLNAME) "
        "AS OBJECT_SET_ROLE, FORMAT("
    )
    if (
        any(
            compact.count(fragment) != expected_count
            for fragment, expected_count in object_fragment_counts.items()
        )
        or any(compact.count(fragment) != 1 for fragment in object_formats)
        or compact.count(object_execution_prefix) != 4
        or compact.count(" AS OBJECT_SET_ROLE") != 4
        or compact.count(" AS OBJECT_REVOKE_PRIVILEGE") != 4
        or compact.count(" AS OBJECT_RESET_ROLE") != 4
        or compact.count(
            "AS OBJECT_REVOKE_PRIVILEGE, 'RESET ROLE' AS OBJECT_RESET_ROLE"
        )
        != 4
    ):
        errors.append("platform role initializer residual object cleanup differs")

    column_fragments = (
        "FORMAT('REVOKE %S (%I) ON TABLE %I.%I FROM %I GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, ATTRIBUTE.ATTNAME, NAMESPACE.NSPNAME, "
        "RELATION.RELNAME, COLUMN_GRANTEE_ROLE.ROLNAME, COLUMN_GRANTOR_ROLE.ROLNAME) "
        "AS REVOKE_PRIVILEGE",
        "FROM PG_ATTRIBUTE AS ATTRIBUTE",
        "JOIN PG_CLASS AS RELATION ON RELATION.OID = ATTRIBUTE.ATTRELID",
        "JOIN PG_NAMESPACE AS NAMESPACE ON NAMESPACE.OID = RELATION.RELNAMESPACE",
        "CROSS JOIN LATERAL ACLEXPLODE(ATTRIBUTE.ATTACL) AS PRIVILEGE",
        "JOIN PG_ROLES AS COLUMN_GRANTEE_ROLE ON "
        "COLUMN_GRANTEE_ROLE.OID = PRIVILEGE.GRANTEE",
        "JOIN PG_ROLES AS COLUMN_GRANTOR_ROLE ON "
        "COLUMN_GRANTOR_ROLE.OID = PRIVILEGE.GRANTOR",
        "COLUMN_GRANTEE_ROLE.ROLNAME IN ('PLATFORM_CONTROL', 'PLATFORM_SUPERVISOR', "
        "'PLATFORM_OPERATOR')",
        "PRIVILEGE.PRIVILEGE_TYPE IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')",
        "ATTRIBUTE.ATTNUM > 0",
        "NOT ATTRIBUTE.ATTISDROPPED",
        "ORDER BY COLUMN_GRANTEE_ROLE.ROLNAME, NAMESPACE.NSPNAME, RELATION.RELNAME, "
        "ATTRIBUTE.ATTNAME, PRIVILEGE.PRIVILEGE_TYPE, COLUMN_GRANTOR_ROLE.ROLNAME",
    )
    column_execution = (
        "SELECT FORMAT('SET ROLE %I', COLUMN_GRANTOR_ROLE.ROLNAME) AS SET_ROLE, "
        "FORMAT('REVOKE %S (%I) ON TABLE %I.%I FROM %I GRANTED BY %I CASCADE', "
        "PRIVILEGE.PRIVILEGE_TYPE, ATTRIBUTE.ATTNAME, NAMESPACE.NSPNAME, "
        "RELATION.RELNAME, COLUMN_GRANTEE_ROLE.ROLNAME, COLUMN_GRANTOR_ROLE.ROLNAME) "
        "AS REVOKE_PRIVILEGE, 'RESET ROLE' AS RESET_ROLE FROM PG_ATTRIBUTE AS ATTRIBUTE"
    )
    if (
        any(compact.count(fragment) < 1 for fragment in column_fragments)
        or compact.count(column_execution) != 1
        or compact.count(" AS SET_ROLE") != 1
        or compact.count(" AS REVOKE_PRIVILEGE") != 1
        or compact.count(" AS RESET_ROLE") != 1
    ):
        errors.append("platform role initializer residual column cleanup differs")

    routine_fragments = (
        "FORMAT('REVOKE EXECUTE ON ROUTINE %I.%I(%S) FROM %I GRANTED BY %I "
        "CASCADE', NAMESPACE.NSPNAME, ROUTINE.PRONAME, "
        "PG_GET_FUNCTION_IDENTITY_ARGUMENTS(ROUTINE.OID), "
        "ROUTINE_GRANTEE_ROLE.ROLNAME, ROUTINE_GRANTOR_ROLE.ROLNAME) "
        "AS ROUTINE_REVOKE_PRIVILEGE",
        "FROM PG_PROC AS ROUTINE JOIN PG_NAMESPACE AS NAMESPACE ON "
        "NAMESPACE.OID = ROUTINE.PRONAMESPACE CROSS JOIN LATERAL "
        "ACLEXPLODE(ROUTINE.PROACL) AS PRIVILEGE JOIN PG_ROLES AS "
        "ROUTINE_GRANTEE_ROLE ON ROUTINE_GRANTEE_ROLE.OID = PRIVILEGE.GRANTEE "
        "JOIN PG_ROLES AS ROUTINE_GRANTOR_ROLE ON "
        "ROUTINE_GRANTOR_ROLE.OID = PRIVILEGE.GRANTOR",
        "WHERE ROUTINE_GRANTEE_ROLE.ROLNAME IN ('PLATFORM_CONTROL', "
        "'PLATFORM_SUPERVISOR', 'PLATFORM_OPERATOR') AND "
        "PRIVILEGE.PRIVILEGE_TYPE = 'EXECUTE' AND NAMESPACE.NSPNAME <> "
        "'INFORMATION_SCHEMA' AND NAMESPACE.NSPNAME !~ '^PG_'",
        "ORDER BY ROUTINE_GRANTEE_ROLE.ROLNAME, NAMESPACE.NSPNAME, "
        "ROUTINE.PRONAME, PG_GET_FUNCTION_IDENTITY_ARGUMENTS(ROUTINE.OID), "
        "ROUTINE_GRANTOR_ROLE.ROLNAME",
    )
    routine_execution = (
        "SELECT FORMAT('SET ROLE %I', ROUTINE_GRANTOR_ROLE.ROLNAME) "
        "AS ROUTINE_SET_ROLE, FORMAT('REVOKE EXECUTE ON ROUTINE %I.%I(%S) "
        "FROM %I GRANTED BY %I CASCADE', NAMESPACE.NSPNAME, ROUTINE.PRONAME, "
        "PG_GET_FUNCTION_IDENTITY_ARGUMENTS(ROUTINE.OID), "
        "ROUTINE_GRANTEE_ROLE.ROLNAME, ROUTINE_GRANTOR_ROLE.ROLNAME) "
        "AS ROUTINE_REVOKE_PRIVILEGE, 'RESET ROLE' AS ROUTINE_RESET_ROLE "
        "FROM PG_PROC AS ROUTINE"
    )
    if (
        any(compact.count(fragment) != 1 for fragment in routine_fragments)
        or compact.count(routine_execution) != 1
        or compact.count(" AS ROUTINE_SET_ROLE") != 1
        or compact.count(" AS ROUTINE_REVOKE_PRIVILEGE") != 1
        or compact.count(" AS ROUTINE_RESET_ROLE") != 1
        or compact.count("GRANTED BY %I CASCADE") != 18
    ):
        errors.append("platform role initializer residual routine cleanup differs")

    expected_catalog = [
        "PLATFORM_CATALOG_REVISIONS",
        "RUNTIME_INSTANCES",
        "RUNTIME_ATTEMPTS",
        "RUNTIME_LIFECYCLE_JOBS",
        "RUNTIME_ENDPOINTS",
        "RUNTIME_ACCESS_REQUESTS",
        "RUNTIME_AUDIT_EVENTS",
    ]
    expected_control_writes = ["RUNTIME_ACCESS_REQUESTS", "RUNTIME_AUDIT_EVENTS"]
    expected_supervisor_writes = expected_catalog[1:]
    expected_operator_tables = [
        "PLATFORM_CATALOG_REVISIONS",
        "ADAPTER_TEMPLATE_REVISIONS",
        "STATE_ALLOCATIONS",
        "SECRET_REFERENCES",
        "RUNTIME_SPEC_REVISIONS",
        "RUNTIME_INSTANCES",
        "RUNTIME_AUDIT_EVENTS",
    ]
    grant_fragments = (
        "GRANT CONNECT ON DATABASE PLATFORM TO PLATFORM_CONTROL, PLATFORM_SUPERVISOR;",
        "GRANT USAGE ON SCHEMA PUBLIC TO PLATFORM_CONTROL, PLATFORM_SUPERVISOR;",
        "GRANT CONNECT ON DATABASE PLATFORM TO PLATFORM_OPERATOR;",
        "GRANT USAGE ON SCHEMA PUBLIC TO PLATFORM_OPERATOR;",
        "GRANT SELECT, INSERT ON TABLE PUBLIC.%I TO PLATFORM_OPERATOR",
        "GRANT SELECT ON TABLE PUBLIC.%I TO PLATFORM_CONTROL, PLATFORM_SUPERVISOR",
        "GRANT INSERT ON TABLE PUBLIC.%I TO PLATFORM_CONTROL",
        "GRANT UPDATE (STATUS, RESULT_CODE, COMPLETED_AT) ON TABLE "
        "PUBLIC.RUNTIME_ACCESS_REQUESTS TO PLATFORM_CONTROL",
        "GRANT INSERT, UPDATE ON TABLE PUBLIC.%I TO PLATFORM_SUPERVISOR",
    )
    if (
        any(joined_strings.count(fragment) != 1 for fragment in grant_fragments)
        or len(re.findall(r"\bGRANT\b", active)) != len(grant_fragments)
        or _role_table_inventory(compact, "CATALOG") != expected_catalog
        or _role_table_inventory(compact, "CONTROL_WRITES") != expected_control_writes
        or _role_table_inventory(compact, "SUPERVISOR_WRITES")
        != expected_supervisor_writes
        or _role_table_inventory(compact, "OPERATOR_TABLES")
        != expected_operator_tables
    ):
        errors.append("platform role initializer grant inventory differs")

    forbidden_patterns = (
        r"ALTER\s+DEFAULT\s+PRIVILEGES\b(?:(?!;).)*\bGRANT\b",
        r"GRANT\s+[^;]*\bTO\s+PUBLIC\b",
        r"GRANT\s+ALL(?:\s+PRIVILEGES)?",
        r"GRANT\s+(?:DELETE|TRUNCATE|CREATE|TEMPORARY|TEMP)\b",
        r"\b(?:SUPERUSER|CREATEDB|CREATEROLE|REPLICATION|BYPASSRLS)\b",
        r"\b(?:CAT|PRINTF|ECHO)\b.*?/RUN/SECRETS/",
        r"\b(?:REASSIGN|DROP)\s+OWNED\b",
        r"PASSWORD\s*=",
    )
    if any(re.search(pattern, active) for pattern in forbidden_patterns):
        errors.append("platform role initializer broadens database authority")

    membership_position = active.find("FROM PG_AUTH_MEMBERS AS MEMBERSHIP")
    public_position = active.find("AS PUBLIC_SET_ROLE")
    public_last_position = active.rfind("AS PUBLIC_RESET_ROLE")
    default_positions = [active.find(fragment) for fragment in default_privilege_hardening]
    revoke_position = active.find("REVOKE ALL PRIVILEGES ON DATABASE PLATFORM")
    authority_guard_position = active.find("DO $AUTHORITY_GUARD$")
    object_position = active.find("AS OBJECT_SET_ROLE")
    column_position = active.find("AS SET_ROLE")
    routine_position = active.find("AS ROUTINE_SET_ROLE")
    grant_position = active.find("GRANT CONNECT ON DATABASE PLATFORM")
    if (
        min(public_position, public_last_position, *default_positions) < 0
        or not public_position <= public_last_position < default_positions[0]
        < default_positions[1] < default_positions[2] < default_positions[3]
        < revoke_position < authority_guard_position
    ):
        errors.append("platform role initializer public authority order differs")
    if (
        min(
            membership_position,
            public_position,
            revoke_position,
            authority_guard_position,
            object_position,
            column_position,
            routine_position,
            grant_position,
        )
        < 0
        or not membership_position < public_position < revoke_position
        < authority_guard_position < object_position < column_position
        < routine_position < grant_position
    ):
        errors.append("platform role initializer must revoke before granting")
    if digest != PLATFORM_ROLE_SCRIPT_SHA256:
        errors.append("platform role initializer digest differs")
    return errors


def validate_platform_compose(
    compose: object,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    if type(compose) is not dict:
        return ["rendered platform Compose must be an object"]
    errors: list[str] = []
    allowed_top_level = {
        "name",
        "networks",
        "secrets",
        "services",
        "volumes",
        "x-freqtrade-common",
    }
    if set(compose) != allowed_top_level:
        errors.append("platform Compose top-level fields differ")

    services = compose.get("services")
    if type(services) is not dict or set(services) != PLATFORM_SERVICES:
        errors.append("platform Compose services differ")
        return [*errors, *_validate_platform_role_script(repo_root)]

    networks = compose.get("networks")
    expected_networks = {
        "platform-db": {
            "name": "freqtrade-cn_platform-db",
            "ipam": {},
            "internal": True,
        },
        "platform-ingress": {
            "name": "freqtrade-cn_platform-ingress",
            "ipam": {},
        },
    }
    if type(networks) is not dict or networks != expected_networks:
        errors.append("platform Compose networks differ")

    volumes = compose.get("volumes")
    expected_volume = {"name": "freqtrade-cn_platform-postgres-data"}
    if type(volumes) is not dict or volumes != {"platform-postgres-data": expected_volume}:
        errors.append("platform Compose volumes differ")

    compose_secrets = compose.get("secrets")
    if type(compose_secrets) is not dict or set(compose_secrets) != set(
        PLATFORM_SECRET_FILES
    ):
        errors.append("platform Compose secrets differ")
    else:
        for source, filename in PLATFORM_SECRET_FILES.items():
            definition = compose_secrets[source]
            expected_name = f"freqtrade-cn_{source}"
            if (
                type(definition) is not dict
                or set(definition) != {"name", "file"}
                or definition.get("name") != expected_name
                or not _platform_path_matches(
                    definition.get("file"),
                    repo_root / "ft_userdata/secrets/platform" / filename,
                )
            ):
                errors.append("platform Compose secret definition differs")

    postgres = services["platform-postgres"]
    expected_postgres_fields = {
        "profiles",
        "command",
        "container_name",
        "entrypoint",
        "environment",
        "expose",
        "healthcheck",
        "image",
        "networks",
        "restart",
        "secrets",
        "volumes",
    }
    if type(postgres) is not dict or set(postgres) != expected_postgres_fields:
        errors.append("platform-postgres fields differ")
    else:
        expected_postgres_values = {
            "profiles": ["platform"],
            "command": None,
            "container_name": "freqtrade-cn-platform-postgres",
            "entrypoint": None,
            "environment": {
                "POSTGRES_DB": "platform",
                "POSTGRES_PASSWORD_FILE": "/run/secrets/postgres_admin_password",
                "POSTGRES_USER": "postgres",
            },
            "expose": ["5432"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U postgres -d platform"],
                "timeout": "5s",
                "interval": "10s",
                "retries": 5,
                "start_period": "10s",
            },
            "image": "postgres:17.10-alpine",
            "networks": {"platform-db": None},
            "restart": "unless-stopped",
            "secrets": [
                {
                    "source": "platform_postgres_admin_password",
                    "target": "postgres_admin_password",
                },
                {
                    "source": "platform_control_db_password",
                    "target": "platform_control_db_password",
                },
                {
                    "source": "platform_supervisor_db_password",
                    "target": "platform_supervisor_db_password",
                },
                {
                    "source": "platform_operator_db_password",
                    "target": "platform_operator_db_password",
                },
            ],
        }
        for field, expected in expected_postgres_values.items():
            if postgres.get(field) != expected:
                errors.append(f"platform-postgres {field} differs")
        postgres_volumes = postgres.get("volumes")
        expected_data_volume = {
            "type": "volume",
            "source": "platform-postgres-data",
            "target": "/var/lib/postgresql/data",
        }
        if type(postgres_volumes) is not list or len(postgres_volumes) != 2:
            errors.append("platform-postgres volumes differ")
        else:
            init_mount = postgres_volumes[1]
            if postgres_volumes[0] != expected_data_volume or (
                type(init_mount) is not dict
                or set(init_mount) != {"type", "source", "target", "read_only", "bind"}
                or init_mount.get("type") != "bind"
                or init_mount.get("target")
                != "/docker-entrypoint-initdb.d/init-platform-roles.sh"
                or init_mount.get("read_only") is not True
                or init_mount.get("bind") != {"create_host_path": False}
                or not _platform_path_matches(
                    init_mount.get("source"),
                    repo_root / "docker/postgres/init-platform-roles.sh",
                )
            ):
                errors.append("platform-postgres volumes differ")

    control = services["platform-control"]
    expected_control = {
        "profiles": ["platform"],
        "build": {
            "context": str(repo_root.resolve()),
            "dockerfile": "Dockerfile",
        },
        "cap_drop": ["ALL"],
        "command": None,
        "container_name": "freqtrade-cn-platform-control",
        "depends_on": {
            "platform-postgres": {"condition": "service_healthy", "required": True}
        },
        "entrypoint": ["python", "-m", "freqtrade.platform_control"],
        "environment": PLATFORM_CONTROL_ENVIRONMENT,
        "image": "freqtrade-cn:local",
        "init": True,
        "labels": {
            "io.freqtrade.platform.identity-revision": "platform-control-v1",
            "io.freqtrade.platform.role": "platform-control",
        },
        "networks": {"platform-db": None, "platform-ingress": None},
        "ports": [
            {
                "mode": "ingress",
                "host_ip": "127.0.0.1",
                "target": 8090,
                "published": "8090",
                "protocol": "tcp",
            }
        ],
        "read_only": True,
        "restart": "unless-stopped",
        "secrets": [
            {"source": "platform_control_api_password", "target": "api_password"},
            {"source": "platform_control_jwt_secret", "target": "jwt_secret_key"},
            {"source": "platform_control_db_password", "target": "database_password"},
        ],
        "security_opt": ["no-new-privileges:true"],
        "user": "1000:1000",
    }
    if type(control) is not dict or control != expected_control:
        errors.append("platform-control fields differ")
        if type(control) is dict:
            environment = control.get("environment")
            if type(environment) is dict and environment != PLATFORM_CONTROL_ENVIRONMENT:
                errors.append("platform-control direct secret environment is forbidden")
            if control.get("ports") != expected_control["ports"]:
                errors.append("platform-control host loopback publication differs")
            if control.get("volumes") not in (None, []):
                errors.append("platform-control volumes are forbidden")
            if control.get("secrets") != expected_control["secrets"]:
                errors.append("platform-control secret allocation differs")

    operator_mounts = (
        (".git", ".git"),
        ("ops/adapter-templates", "ops/adapter-templates"),
        ("ops/runtime-policies", "ops/runtime-policies"),
        (
            "ft_userdata/user_data/config.example.json",
            "ft_userdata/user_data/config.example.json",
        ),
        (
            "ft_userdata/user_data/strategies/sample_strategy.py",
            "ft_userdata/user_data/strategies/sample_strategy.py",
        ),
        ("ops/config/trading-safety.json", "ops/config/trading-safety.json"),
    )
    expected_operator = {
        "profiles": ["platform-operator"],
        "cap_drop": ["ALL"],
        "command": None,
        "entrypoint": None,
        "image": "freqtrade-cn-operator:local",
        "init": True,
        "networks": {"platform-db": None},
        "pull_policy": "never",
        "read_only": True,
        "restart": "no",
        "secrets": [
            {
                "source": "platform_operator_db_password",
                "target": "database_password",
            }
        ],
        "security_opt": ["no-new-privileges:true"],
        "user": "1000:1000",
        "volumes": [
            {
                "type": "bind",
                "source": str((repo_root / source).resolve()),
                "target": f"/opt/platform-operator/repository/{target}",
                "read_only": True,
                "bind": {"create_host_path": False},
            }
            for source, target in operator_mounts
        ],
    }
    operator = services["platform-operator"]
    if type(operator) is not dict or operator != expected_operator:
        errors.append("platform-operator fields differ")

    errors.extend(_validate_platform_role_script(repo_root))
    return errors


def _load_compose_file(path: Path) -> dict[str, Any] | None:
    try:
        content = path.read_bytes()
        encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        data = json.loads(content.decode(encoding))
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


def _render_platform_compose() -> dict[str, Any] | None:
    command = [
        sys.executable,
        str((REPO_ROOT / "tools/compose_runtime.py").resolve()),
        "--profile",
        "platform",
        "--profile",
        "platform-operator",
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
    parser.add_argument("--platform", action="store_true")
    args = parser.parse_args(arguments)

    if args.platform:
        if args.check_configs_only:
            print("error: unsupported platform validation arguments", file=sys.stderr)
            return 1
        if args.compose_json is not None:
            compose = _load_compose_file(args.compose_json)
            compose_error = "Compose JSON could not be loaded"
        else:
            compose = _render_platform_compose()
            compose_error = "rendered platform Compose could not be loaded"
        if compose is None:
            print(f"error: {compose_error}", file=sys.stderr)
            return 1
        errors = validate_platform_compose(compose)
        if errors:
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            return 1
        print("platform runtime contract: OK")
        return 0

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
