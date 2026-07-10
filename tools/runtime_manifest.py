from __future__ import annotations

import json
from pathlib import Path
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


def load_runtime_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or DEFAULT_MANIFEST
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("runtime manifest schema_version must be 1")
    services = data.get("services")
    if not isinstance(services, list) or not services:
        raise ValueError("runtime manifest services must be a non-empty list")

    names: set[str] = set()
    for service in services:
        if not isinstance(service, dict):
            raise ValueError("runtime service entries must be objects")
        missing = REQUIRED_SERVICE_KEYS - service.keys()
        if missing:
            raise ValueError(
                f"runtime service is missing keys: {', '.join(sorted(missing))}"
            )
        name = service["name"]
        if not isinstance(name, str) or not name:
            raise ValueError("runtime service name must be a non-empty string")
        if name in names:
            raise ValueError(f"duplicate runtime service: {name}")
        names.add(name)
        if service["role"] not in {"trading", "research"}:
            raise ValueError(f"unsupported runtime role for {name}")
    return data
