from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "ops" / "runtime-services.json"
REQUIRED_SERVICE_KEYS = {
    "name",
    "role",
    "profile",
    "config_template",
    "config_path",
    "strategy",
    "state_root",
    "legacy_database",
    "database_filename",
}
PATH_KEYS = {
    "config_template",
    "config_path",
    "state_root",
    "legacy_database",
}
EXPECTED_SERVICES: dict[str, dict[str, object]] = {
    "freqtrade": {
        "name": "freqtrade",
        "role": "trading",
        "profile": "trading",
        "config_template": "ft_userdata/user_data/config.example.json",
        "config_path": "ft_userdata/user_data/config.json",
        "strategy": "SampleStrategy",
        "state_root": "ft_userdata/runtime/freqtrade",
        "legacy_database": "ft_userdata/user_data/tradesv3.sqlite",
        "database_filename": "trades.sqlite",
    },
    "freqtrade-futures": {
        "name": "freqtrade-futures",
        "role": "trading",
        "profile": "trading",
        "config_template": "ft_userdata/user_data/config.volatility.futures.example.json",
        "config_path": "ft_userdata/user_data/config.volatility.futures.json",
        "strategy": "VolatilitySystem",
        "state_root": "ft_userdata/runtime/freqtrade-futures",
        "legacy_database": "ft_userdata/user_data/tradesv3-futures.sqlite",
        "database_filename": "trades.sqlite",
    },
    "freqtrade-research": {
        "name": "freqtrade-research",
        "role": "research",
        "profile": "research",
        "config_template": "ft_userdata/user_data/config.research.example.json",
        "config_path": "ft_userdata/user_data/config.research.json",
        "strategy": None,
        "state_root": "ft_userdata/runtime/freqtrade-research",
        "legacy_database": None,
        "database_filename": None,
    },
}


def _validate_repository_relative_path(value: object, service_name: str, key: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"runtime service {service_name}:{key} must be a repository-relative path")
    posix_path = PurePosixPath(value)
    if (
        "\\" in value
        or posix_path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or value != posix_path.as_posix()
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"runtime service {service_name}:{key} must be a repository-relative path")


def _validate_service_shape(service: object, names: set[str]) -> dict[str, object]:
    if type(service) is not dict:
        raise ValueError("runtime service entries must be objects")
    missing = REQUIRED_SERVICE_KEYS - service.keys()
    if missing:
        raise ValueError(f"runtime service is missing keys: {', '.join(sorted(missing))}")
    extra = service.keys() - REQUIRED_SERVICE_KEYS
    if extra:
        raise ValueError(f"runtime service has unexpected keys: {', '.join(sorted(extra))}")

    name = service["name"]
    if type(name) is not str or not name:
        raise ValueError("runtime service name must be a non-empty string")
    if name in names:
        raise ValueError(f"duplicate runtime service: {name}")
    names.add(name)

    role = service["role"]
    if type(role) is not str or role not in {"trading", "research"}:
        raise ValueError(f"unsupported runtime role for {name}")
    for key in PATH_KEYS:
        value = service[key]
        if value is not None:
            _validate_repository_relative_path(value, name, key)
    for key in {"profile", "strategy", "database_filename"}:
        value = service[key]
        if value is not None and type(value) is not str:
            raise ValueError(f"runtime service {name}:{key} must be a string or null")
    return service


def load_runtime_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or DEFAULT_MANIFEST
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if type(data) is not dict:
        raise ValueError("runtime manifest must be an object")
    expected_top_level = {"schema_version", "services"}
    if set(data) != expected_top_level:
        raise ValueError("runtime manifest must contain only schema_version and services")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("runtime manifest schema_version must be integer 1")
    services = data["services"]
    if type(services) is not list or not services:
        raise ValueError("runtime manifest services must be a non-empty list")

    names: set[str] = set()
    validated_services = [_validate_service_shape(service, names) for service in services]
    if names != set(EXPECTED_SERVICES):
        raise ValueError("runtime manifest must contain exactly the supported services")
    for service in validated_services:
        name = service["name"]
        if service != EXPECTED_SERVICES[name]:
            raise ValueError(f"runtime service contract mismatch for {name}")
    return data
