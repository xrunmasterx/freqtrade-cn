from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from tools.committed_git import CommittedGitStore


_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_SEMANTIC_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)

_POLICY_PATHS = {
    "image_policy_ids": "ops/runtime-policies/image-policies.json",
    "command_policy_ids": "ops/runtime-policies/command-policies.json",
    "mount_policy_ids": "ops/runtime-policies/mount-policies.json",
    "network_policy_ids": "ops/runtime-policies/network-policies.json",
    "health_profile_ids": "ops/runtime-policies/health-profiles.json",
    "resource_profile_ids": "ops/runtime-policies/resource-profiles.json",
    "state_layout_ids": "ops/runtime-policies/state-layouts.json",
}
_TEMPLATE_FIELDS = frozenset(
    {
        "schema_version",
        "template_id",
        "semantic_version",
        "allowed_instance_kinds",
        "allowed_owner_kinds",
        "allowed_environments",
        "image_policy_id",
        "command_policy_id",
        "mount_policy_ids",
        "network_policy_id",
        "health_profile_id",
        "resource_profile_id",
        "secret_classes",
        "state_layout_id",
    }
)
_ARRAY_FIELDS = (
    "allowed_instance_kinds",
    "allowed_owner_kinds",
    "allowed_environments",
    "mount_policy_ids",
    "secret_classes",
)
_IDENTIFIER_FIELDS = (
    "template_id",
    "image_policy_id",
    "command_policy_id",
    "network_policy_id",
    "health_profile_id",
    "resource_profile_id",
    "state_layout_id",
)
_OWNER_KINDS = frozenset({"migration_bot", "paper_probe", "workspace_worker"})
_ENVIRONMENTS = frozenset({"paper", "live"})
_RAW_POWER_KEYS = frozenset(
    {
        "image",
        "command",
        "host_path",
        "mount",
        "mount_source",
        "port",
        "network",
        "device",
        "capability",
        "privileged",
        "compose",
        "project",
        "service",
        "container",
        "environment",
        "env",
        "env_file",
        "environment_passthrough",
        "secret",
        "secret_value",
        "secret_path",
        "credential",
    }
)
_PAPER_PROBE_IDENTITY = {
    "allowed_environments": ["paper"],
    "allowed_instance_kinds": ["freqtrade"],
    "allowed_owner_kinds": ["paper_probe"],
    "command_policy_id": "freqtrade-spot-paper-v1",
    "health_profile_id": "freqtrade-ping-v1",
    "image_policy_id": "freqtrade-reviewed-image-v1",
    "mount_policy_ids": [
        "runtime-config-ro-v1",
        "strategy-ro-v1",
        "managed-state-rw-v1",
        "api-secrets-ro-v1",
    ],
    "network_policy_id": "isolated-public-market-data-v1",
    "resource_profile_id": "freqtrade-small-v1",
    "schema_version": 1,
    "secret_classes": ["api_password", "jwt_secret", "ws_token"],
    "semantic_version": "1.0.0",
    "state_layout_id": "freqtrade-state-v1",
    "template_id": "freqtrade-paper-probe-v1",
}


@dataclass(frozen=True, slots=True)
class ClosedPolicyRegistry:
    image_policy_ids: frozenset[str]
    command_policy_ids: frozenset[str]
    mount_policy_ids: frozenset[str]
    network_policy_ids: frozenset[str]
    health_profile_ids: frozenset[str]
    resource_profile_ids: frozenset[str]
    state_layout_ids: frozenset[str]
    source_commit: str


@dataclass(frozen=True, slots=True)
class CommittedTemplate:
    payload: Mapping[str, object]
    canonical_json: str
    digest: str
    source_path: str
    source_commit: str


class _DuplicateJsonKey(ValueError):
    pass


def _is_artifact_path(path: str) -> bool:
    if path in _POLICY_PATHS.values():
        return True
    prefix = "ops/adapter-templates/"
    suffix = ".json"
    if not path.startswith(prefix) or not path.endswith(suffix):
        return False
    template_id = path[len(prefix) : -len(suffix)]
    return _IDENTIFIER.fullmatch(template_id) is not None


def git_blob(root: Path, commit: str, path: str) -> bytes:
    if not isinstance(path, str) or not _is_artifact_path(path):
        raise ValueError("artifact path is not permitted")
    store = CommittedGitStore(root, commit)
    store.assert_template_checkout_clean()
    for field, policy_path in _POLICY_PATHS.items():
        if path == policy_path:
            return store.read_policy_blob(field)
    template_id = path[len("ops/adapter-templates/") : -len(".json")]
    return store.read_template_blob(template_id)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("invalid JSON constant")


def _canonical_payload(document: bytes) -> object:
    if document.startswith(b"\xef\xbb\xbf"):
        raise ValueError("artifact JSON must not contain a BOM")
    try:
        text = document.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("artifact JSON must be valid UTF-8") from None
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateJsonKey:
        raise ValueError("duplicate JSON key") from None
    except (json.JSONDecodeError, ValueError):
        raise ValueError("artifact contains invalid JSON") from None
    canonical = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    if document != canonical:
        raise ValueError("artifact must use canonical JSON with one trailing newline")
    return payload


def _policy_ids(document: bytes) -> frozenset[str]:
    payload = _canonical_payload(document)
    if not isinstance(payload, dict):
        raise ValueError("policy registry root must be a JSON object")
    expected_keys = {"policy_ids", "schema_version"}
    unknown_keys = set(payload) - expected_keys
    missing_keys = expected_keys - set(payload)
    if unknown_keys:
        raise ValueError("policy registry contains unknown keys")
    if missing_keys:
        raise ValueError("policy registry is missing keys")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("policy registry schema_version must be integer 1")
    policy_ids = payload["policy_ids"]
    if not isinstance(policy_ids, list) or any(type(value) is not str for value in policy_ids):
        raise ValueError("policy_ids must be an array of strings")
    if not policy_ids:
        raise ValueError("policy_ids must be non-empty")
    if len(set(policy_ids)) != len(policy_ids):
        raise ValueError("policy_ids must be unique")
    if any(_IDENTIFIER.fullmatch(value) is None for value in policy_ids):
        raise ValueError("policy_ids must contain valid platform identifiers")
    if policy_ids != sorted(policy_ids):
        raise ValueError("policy_ids must be sorted")
    return frozenset(policy_ids)


def _load_registry(store: CommittedGitStore) -> ClosedPolicyRegistry:
    values = {
        field: _policy_ids(store.read_policy_blob(field)) for field in _POLICY_PATHS
    }
    return ClosedPolicyRegistry(**values, source_commit=store.root_commit)


def load_closed_policy_registry(root: Path, commit: str) -> ClosedPolicyRegistry:
    store = CommittedGitStore(root, commit)
    store.assert_template_checkout_clean()
    return _load_registry(store)


def _require_string(payload: dict[str, object], field: str) -> str:
    value = payload[field]
    if type(value) is not str:
        raise ValueError(f"{field} must be a string")
    return value


def _require_identifier(value: str, field: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must be a valid platform identifier")


def _validated_arrays(payload: dict[str, object]) -> dict[str, list[str]]:
    arrays: dict[str, list[str]] = {}
    for field in _ARRAY_FIELDS:
        value = payload[field]
        if not isinstance(value, list) or any(type(item) is not str for item in value):
            raise ValueError(f"{field} must be a non-empty array of strings")
        if not value:
            raise ValueError(f"{field} must be a non-empty array of strings")
        if len(set(value)) != len(value):
            raise ValueError(f"{field} contains duplicate values")
        arrays[field] = value
    return arrays


def validate_template(
    payload: object, registry: ClosedPolicyRegistry
) -> Mapping[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("template root must be a JSON object")
    raw_power_keys = set(payload) & _RAW_POWER_KEYS
    if raw_power_keys:
        raise ValueError("template contains forbidden raw power")
    unknown_keys = set(payload) - _TEMPLATE_FIELDS
    missing_keys = _TEMPLATE_FIELDS - set(payload)
    if unknown_keys:
        raise ValueError("template contains unknown keys")
    if missing_keys:
        raise ValueError("template is missing keys")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("template schema_version must be integer 1")
    if not isinstance(registry, ClosedPolicyRegistry):
        raise ValueError("template policy registry is invalid")

    strings = {field: _require_string(payload, field) for field in _IDENTIFIER_FIELDS}
    semantic_version = _require_string(payload, "semantic_version")
    if _SEMANTIC_VERSION.fullmatch(semantic_version) is None:
        raise ValueError("semantic_version must use strict MAJOR.MINOR.PATCH")
    for field, value in strings.items():
        _require_identifier(value, field)

    arrays = _validated_arrays(payload)
    for value in arrays["allowed_instance_kinds"]:
        _require_identifier(value, "allowed_instance_kinds")
    for value in arrays["mount_policy_ids"]:
        _require_identifier(value, "mount_policy_ids")
    for value in arrays["secret_classes"]:
        _require_identifier(value, "secret_classes")
    if any(value not in _OWNER_KINDS for value in arrays["allowed_owner_kinds"]):
        raise ValueError("template contains an unknown owner kind")
    if any(value not in _ENVIRONMENTS for value in arrays["allowed_environments"]):
        raise ValueError("template contains an unknown environment")

    if strings["image_policy_id"] not in registry.image_policy_ids:
        raise ValueError("unknown image policy")
    if strings["command_policy_id"] not in registry.command_policy_ids:
        raise ValueError("unknown command policy")
    if any(value not in registry.mount_policy_ids for value in arrays["mount_policy_ids"]):
        raise ValueError("unknown mount policy")
    if strings["network_policy_id"] not in registry.network_policy_ids:
        raise ValueError("unknown network policy")
    if strings["health_profile_id"] not in registry.health_profile_ids:
        raise ValueError("unknown health profile")
    if strings["resource_profile_id"] not in registry.resource_profile_ids:
        raise ValueError("unknown resource profile")
    if strings["state_layout_id"] not in registry.state_layout_ids:
        raise ValueError("unknown state layout")

    if payload["template_id"] == "freqtrade-paper-probe-v1" and payload != _PAPER_PROBE_IDENTITY:
        raise ValueError("freqtrade paper probe identity must match the approved fixed payload")

    immutable_payload = {
        key: tuple(value) if isinstance(value, list) else value
        for key, value in payload.items()
    }
    return MappingProxyType(immutable_payload)


def read_committed_template(
    root: Path, template_id: str, commit: str
) -> CommittedTemplate:
    if not isinstance(template_id, str) or _IDENTIFIER.fullmatch(template_id) is None:
        raise ValueError("template_id must be a valid platform identifier")
    store = CommittedGitStore(root, commit)
    store.assert_template_checkout_clean()
    source_path = f"ops/adapter-templates/{template_id}.json"
    document = store.read_template_blob(template_id)
    payload = _canonical_payload(document)
    registry = _load_registry(store)
    validated_payload = validate_template(payload, registry)
    if validated_payload["template_id"] != template_id:
        raise ValueError("template id does not match its source path")
    return CommittedTemplate(
        payload=validated_payload,
        canonical_json=document.decode("utf-8"),
        digest=hashlib.sha256(document).hexdigest(),
        source_path=source_path,
        source_commit=store.root_commit,
    )
