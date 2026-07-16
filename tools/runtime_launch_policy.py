from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from tools.committed_git import CommittedGitStore
from tools.runtime_driver import HealthProfile, ResourceLimits, RuntimeUser
from tools.runtime_templates import (
    CommittedTemplate,
    parse_canonical_json_document,
    read_committed_template,
)


_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_ENVIRONMENT_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_CATALOG_PATH = "ops/runtime-policies/launch-policy-catalog.json"
_PAPER_PROBE_TEMPLATE_ID = "freqtrade-paper-probe-v1"
_TEMPLATE_FIELDS = frozenset(
    {
        "allowed_environments",
        "allowed_instance_kinds",
        "allowed_owner_kinds",
        "command_policy_id",
        "health_profile_id",
        "image_policy_id",
        "mount_policy_ids",
        "network_policy_id",
        "resource_profile_id",
        "schema_version",
        "secret_classes",
        "semantic_version",
        "state_layout_id",
        "template_id",
    }
)
_MAX_CPU_MILLIS = 8_000
_MAX_HEALTH_INTERVAL_SECONDS = 300
_MAX_HEALTH_RETRIES = 20
_MAX_HEALTH_START_PERIOD_SECONDS = 300
_MAX_HEALTH_TIMEOUT_SECONDS = 60
_MAX_MEMORY_BYTES = 8 * 1024 * 1024 * 1024
_MAX_NETWORK_NAME_LENGTH = 63
_MAX_PIDS = 1_024
_PAPER_PROBE_POLICY_DIGEST = (
    "1a8fb0cefd2db6cc8a34f8041bd7d9bfcdea90f2622a3f9b356d21f52d0de266"
)


class CommandTokenKind(StrEnum):
    LITERAL = "literal"
    MOUNT_TARGET = "mount_target"
    STATE_TARGET = "state_target"
    STRATEGY_CLASS_NAME = "strategy_class_name"


class EnvironmentBindingKind(StrEnum):
    SECRET_MOUNT_TARGET = "secret_mount_target"
    STATE_TARGET = "state_target"


class MaterialKind(StrEnum):
    RUNTIME_CONFIG = "runtime_config"
    SAFETY_POLICY = "safety_policy"
    STRATEGY = "strategy"


class ExecutionMode(StrEnum):
    IMAGE_ENTRYPOINT_ARGS = "image-entrypoint-args"


class ImageIdentitySource(StrEnum):
    RESOLVED_ATTEMPT_SHA256 = "resolved-attempt-sha256"


class NetworkIdentitySource(StrEnum):
    INSTANCE_ID = "instance_id"


class NetworkNameDerivation(StrEnum):
    SHA256_PREFIX_V1 = "sha256-prefix-v1"


def _require_identifier(value: object, field: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must be a valid platform identifier")
    return value


def _require_text(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or _CONTROL_CHARACTER.search(value) is not None
    ):
        raise ValueError(f"{field} must be non-empty text without control characters")
    return value


def _require_digest(value: object, field: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_posix_path(value: object, field: str) -> PurePosixPath:
    text = _require_text(value, field)
    path = PurePosixPath(text)
    if (
        not path.is_absolute()
        or text.startswith("//")
        or str(path) != text
        or ".." in path.parts
        or "docker.sock" in text.casefold()
    ):
        raise ValueError(f"{field} must be a canonical absolute POSIX path")
    return path


def _require_object(
    value: object,
    fields: frozenset[str],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown:
        raise ValueError(f"{label} contains unknown keys")
    if missing:
        raise ValueError(f"{label} is missing keys")
    return value


def _require_array(
    value: object, field: str, *, allow_empty: bool = False
) -> list[object]:
    if type(value) is not list or (not allow_empty and not value):
        raise ValueError(f"{field} must be a JSON array")
    return value


def _require_sorted_unique(values: tuple[str, ...], field: str) -> None:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{field} must be sorted and unique")


@dataclass(frozen=True, slots=True)
class CommandToken:
    kind: CommandTokenKind
    value: str | None

    def __post_init__(self) -> None:
        if type(self.kind) is not CommandTokenKind:
            raise ValueError("command token kind is invalid")
        if self.kind is CommandTokenKind.STRATEGY_CLASS_NAME:
            if self.value is not None:
                raise ValueError("strategy token must not carry a value")
            return
        if self.kind is CommandTokenKind.LITERAL:
            text = _require_text(self.value, "command literal")
            if any(character in text for character in ("$", "`", "{", "}")):
                raise ValueError("command literal contains interpolation syntax")
            normalized = re.sub(r"[^A-Z0-9]+", "_", text.upper())
            if any(
                marker in normalized
                for marker in (
                    "ACCESS_KEY",
                    "API_KEY",
                    "APIKEY",
                    "CREDENTIAL",
                    "PASSWORD",
                    "PRIVATE_KEY",
                    "SECRET",
                    "TOKEN",
                )
            ):
                raise ValueError("command literal contains a credential-bearing token")
            return
        _require_identifier(self.value, "command token reference")


@dataclass(frozen=True, slots=True)
class MaterialMountPolicy:
    policy_id: str
    role: str
    material_kind: MaterialKind
    target: PurePosixPath

    def __post_init__(self) -> None:
        _require_identifier(self.policy_id, "material mount policy_id")
        _require_identifier(self.role, "material mount role")
        if type(self.material_kind) is not MaterialKind:
            raise ValueError("material mount kind is invalid")
        _require_posix_path(str(self.target), "material mount target")


@dataclass(frozen=True, slots=True)
class SecretMountPolicy:
    policy_id: str
    secret_class: str
    target: PurePosixPath

    def __post_init__(self) -> None:
        _require_identifier(self.policy_id, "secret mount policy_id")
        _require_identifier(self.secret_class, "secret mount class")
        _require_posix_path(str(self.target), "secret mount target")


@dataclass(frozen=True, slots=True)
class StateMountPolicy:
    policy_id: str
    role: str
    target: PurePosixPath

    def __post_init__(self) -> None:
        _require_identifier(self.policy_id, "state mount policy_id")
        _require_identifier(self.role, "state mount role")
        _require_posix_path(str(self.target), "state mount target")


@dataclass(frozen=True, slots=True)
class StateTarget:
    name: str
    value: str

    def __post_init__(self) -> None:
        _require_identifier(self.name, "state target name")
        _require_text(self.value, "state target value")


@dataclass(frozen=True, slots=True)
class EnvironmentBinding:
    name: str
    kind: EnvironmentBindingKind
    value: str

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or _ENVIRONMENT_NAME.fullmatch(self.name) is None
            or type(self.kind) is not EnvironmentBindingKind
        ):
            raise ValueError("environment binding is invalid")
        _require_identifier(self.value, "environment binding reference")


@dataclass(frozen=True, slots=True)
class NetworkRule:
    role: str
    identity_source: NetworkIdentitySource
    derivation: NetworkNameDerivation
    prefix: str
    digest_characters: int
    suffix: str
    internal: bool
    requires_upstream_access: bool
    requires_platform_control: bool

    def __post_init__(self) -> None:
        _require_identifier(self.role, "network role")
        if type(self.identity_source) is not NetworkIdentitySource:
            raise ValueError("network identity source is invalid")
        if type(self.derivation) is not NetworkNameDerivation:
            raise ValueError("network derivation is invalid")
        for field, value in (
            ("network prefix", self.prefix),
            ("network suffix", self.suffix),
        ):
            if (
                type(value) is not str
                or not value
                or len(value) > 32
                or re.fullmatch(r"[a-z0-9-]+", value) is None
            ):
                raise ValueError(f"{field} is invalid")
        if not self.prefix[0].isalnum() or not self.suffix[-1].isalnum():
            raise ValueError("derived network name must have alphanumeric boundaries")
        if (
            type(self.digest_characters) is not int
            or self.digest_characters < 16
            or self.digest_characters > 64
        ):
            raise ValueError("network digest_characters is invalid")
        if (
            len(self.prefix) + self.digest_characters + len(self.suffix)
            > _MAX_NETWORK_NAME_LENGTH
        ):
            raise ValueError("derived network name exceeds the platform limit")
        if any(
            type(value) is not bool
            for value in (
                self.internal,
                self.requires_upstream_access,
                self.requires_platform_control,
            )
        ):
            raise ValueError("network flags must be booleans")
        if self.internal is self.requires_upstream_access:
            raise ValueError(
                "network isolation must match its upstream access requirement"
            )
        if self.role == "access" and not self.requires_platform_control:
            raise ValueError("the access network must include platform control")


@dataclass(frozen=True, slots=True)
class ResolvedLaunchPolicyBundle:
    template_id: str
    template_digest: str
    source_commit: str
    catalog_source_path: str
    catalog_blob_id: str
    catalog_digest: str
    policy_digest: str
    image_policy_id: str
    image_identity_source: ImageIdentitySource
    command_policy_id: str
    execution_mode: ExecutionMode
    entrypoint_argv: tuple[str, ...]
    command_tokens: tuple[CommandToken, ...]
    working_directory: PurePosixPath
    environment_bindings: tuple[EnvironmentBinding, ...]
    material_mounts: tuple[MaterialMountPolicy, ...]
    state_mount: StateMountPolicy
    secret_mounts: tuple[SecretMountPolicy, ...]
    state_layout_id: str
    state_targets: tuple[StateTarget, ...]
    runtime_user: RuntimeUser
    internal_ports: tuple[int, ...]
    health_profile: HealthProfile
    resource_profile_id: str
    resource_limits: ResourceLimits
    network_policy_id: str
    network_rules: tuple[NetworkRule, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.template_id, "template_id")
        for field, value in (
            ("template_digest", self.template_digest),
            ("catalog_digest", self.catalog_digest),
            ("policy_digest", self.policy_digest),
        ):
            _require_digest(value, field)
        if (
            type(self.source_commit) is not str
            or _OBJECT_ID.fullmatch(self.source_commit) is None
        ):
            raise ValueError("source_commit must be a full lowercase Git identity")
        if (
            type(self.catalog_source_path) is not str
            or self.catalog_source_path != _CATALOG_PATH
        ):
            raise ValueError("catalog_source_path is invalid")
        if (
            type(self.catalog_blob_id) is not str
            or _OBJECT_ID.fullmatch(self.catalog_blob_id) is None
        ):
            raise ValueError("catalog_blob_id must be a full lowercase Git identity")
        for field, value in (
            ("image_policy_id", self.image_policy_id),
            ("command_policy_id", self.command_policy_id),
            ("state_layout_id", self.state_layout_id),
            ("resource_profile_id", self.resource_profile_id),
            ("network_policy_id", self.network_policy_id),
        ):
            _require_identifier(value, field)
        if (
            type(self.image_identity_source) is not ImageIdentitySource
            or type(self.execution_mode) is not ExecutionMode
            or type(self.runtime_user) is not RuntimeUser
            or type(self.health_profile) is not HealthProfile
            or type(self.resource_limits) is not ResourceLimits
            or type(self.state_mount) is not StateMountPolicy
        ):
            raise ValueError("resolved launch policy contains an invalid typed value")
        _require_posix_path(str(self.working_directory), "working_directory")
        if not self.entrypoint_argv or any(
            type(token) is not str
            or not token
            or _CONTROL_CHARACTER.search(token) is not None
            for token in self.entrypoint_argv
        ):
            raise ValueError("entrypoint_argv is invalid")
        typed_tuples = (
            (self.command_tokens, CommandToken),
            (self.environment_bindings, EnvironmentBinding),
            (self.material_mounts, MaterialMountPolicy),
            (self.secret_mounts, SecretMountPolicy),
            (self.state_targets, StateTarget),
            (self.network_rules, NetworkRule),
        )
        if any(
            type(values) is not tuple
            or not values
            or any(type(value) is not item_type for value in values)
            for values, item_type in typed_tuples
        ):
            raise ValueError("resolved launch policy contains invalid tuple values")
        if not self.internal_ports or any(
            type(port) is not int or port < 1024 or port > 65535
            for port in self.internal_ports
        ):
            raise ValueError("internal_ports is invalid")
        if self.internal_ports != tuple(sorted(set(self.internal_ports))):
            raise ValueError("internal_ports must be sorted and unique")
        _require_sorted_unique(
            tuple(rule.role for rule in self.network_rules),
            "network roles",
        )


def _command_token(value: object) -> CommandToken:
    payload = _require_object(
        value,
        frozenset({"kind"})
        if type(value) is dict and value.get("kind") == "strategy_class_name"
        else frozenset({"kind", "value"}),
        "command token",
    )
    try:
        kind = CommandTokenKind(payload["kind"])
    except (TypeError, ValueError):
        raise ValueError("command token kind is invalid") from None
    token_value = payload.get("value")
    return CommandToken(
        kind=kind, value=token_value if type(token_value) is str else None
    )


def _environment_binding(value: object) -> EnvironmentBinding:
    payload = _require_object(
        value,
        frozenset({"kind", "name", "value"}),
        "environment binding",
    )
    try:
        kind = EnvironmentBindingKind(payload["kind"])
    except (TypeError, ValueError):
        raise ValueError("environment binding kind is invalid") from None
    return EnvironmentBinding(
        name=_require_text(payload["name"], "environment binding name"),
        kind=kind,
        value=_require_text(payload["value"], "environment binding value"),
    )


def _material_mount(value: object) -> MaterialMountPolicy:
    payload = _require_object(
        value,
        frozenset({"material_kind", "policy_id", "role", "target"}),
        "material mount",
    )
    try:
        material_kind = MaterialKind(payload["material_kind"])
    except (TypeError, ValueError):
        raise ValueError("material mount kind is invalid") from None
    return MaterialMountPolicy(
        policy_id=_require_identifier(payload["policy_id"], "material mount policy_id"),
        role=_require_identifier(payload["role"], "material mount role"),
        material_kind=material_kind,
        target=_require_posix_path(payload["target"], "material mount target"),
    )


def _secret_mount(value: object) -> SecretMountPolicy:
    payload = _require_object(
        value,
        frozenset({"policy_id", "secret_class", "target"}),
        "secret mount",
    )
    return SecretMountPolicy(
        policy_id=_require_identifier(payload["policy_id"], "secret mount policy_id"),
        secret_class=_require_identifier(payload["secret_class"], "secret mount class"),
        target=_require_posix_path(payload["target"], "secret mount target"),
    )


def _state_mount(value: object) -> StateMountPolicy:
    payload = _require_object(
        value,
        frozenset({"policy_id", "role", "target"}),
        "state mount",
    )
    return StateMountPolicy(
        policy_id=_require_identifier(payload["policy_id"], "state mount policy_id"),
        role=_require_identifier(payload["role"], "state mount role"),
        target=_require_posix_path(payload["target"], "state mount target"),
    )


def _state_target(value: object) -> StateTarget:
    payload = _require_object(
        value,
        frozenset({"name", "value"}),
        "state target",
    )
    return StateTarget(
        name=_require_identifier(payload["name"], "state target name"),
        value=_require_text(payload["value"], "state target value"),
    )


def _network_rule(value: object) -> NetworkRule:
    payload = _require_object(
        value,
        frozenset(
            {
                "derivation",
                "digest_characters",
                "identity_source",
                "internal",
                "prefix",
                "requires_platform_control",
                "requires_upstream_access",
                "role",
                "suffix",
            }
        ),
        "network rule",
    )
    try:
        identity_source = NetworkIdentitySource(payload["identity_source"])
        derivation = NetworkNameDerivation(payload["derivation"])
    except (TypeError, ValueError):
        raise ValueError("network rule contains an unknown closed mode") from None
    return NetworkRule(
        role=_require_identifier(payload["role"], "network role"),
        identity_source=identity_source,
        derivation=derivation,
        prefix=_require_text(payload["prefix"], "network prefix"),
        digest_characters=payload["digest_characters"],
        suffix=_require_text(payload["suffix"], "network suffix"),
        internal=payload["internal"],
        requires_upstream_access=payload["requires_upstream_access"],
        requires_platform_control=payload["requires_platform_control"],
    )


def _parse_health(value: object) -> HealthProfile:
    payload = _require_object(
        value,
        frozenset(
            {
                "interval_seconds",
                "probe_argv",
                "profile_id",
                "retries",
                "start_period_seconds",
                "timeout_seconds",
            }
        ),
        "health profile",
    )
    argv_values = _require_array(payload["probe_argv"], "health probe_argv")
    if any(type(token) is not str for token in argv_values):
        raise ValueError("health probe_argv must contain strings")
    argv = tuple(argv_values)
    if PurePosixPath(argv[0]).name.casefold() in {
        "bash",
        "cmd",
        "powershell",
        "pwsh",
        "sh",
    }:
        raise ValueError("health probe must not invoke a shell")
    profile = HealthProfile(
        profile_id=_require_identifier(payload["profile_id"], "health profile_id"),
        probe_argv=argv,
        start_period_seconds=payload["start_period_seconds"],
        interval_seconds=payload["interval_seconds"],
        timeout_seconds=payload["timeout_seconds"],
        retries=payload["retries"],
    )
    if (
        profile.start_period_seconds > _MAX_HEALTH_START_PERIOD_SECONDS
        or profile.interval_seconds > _MAX_HEALTH_INTERVAL_SECONDS
        or profile.timeout_seconds > _MAX_HEALTH_TIMEOUT_SECONDS
        or profile.retries > _MAX_HEALTH_RETRIES
    ):
        raise ValueError("health profile exceeds platform limits")
    return profile


def _parse_resource(value: object) -> tuple[str, ResourceLimits]:
    payload = _require_object(
        value,
        frozenset({"cpu_millis", "memory_bytes", "pids_limit", "profile_id"}),
        "resource profile",
    )
    profile_id = _require_identifier(payload["profile_id"], "resource profile_id")
    limits = ResourceLimits(
        cpu_millis=payload["cpu_millis"],
        memory_bytes=payload["memory_bytes"],
        pids_limit=payload["pids_limit"],
    )
    if (
        limits.cpu_millis > _MAX_CPU_MILLIS
        or limits.memory_bytes > _MAX_MEMORY_BYTES
        or limits.pids_limit > _MAX_PIDS
    ):
        raise ValueError("resource profile exceeds platform limits")
    return profile_id, limits


def _parse_runtime_user(value: object) -> RuntimeUser:
    payload = _require_object(
        value,
        frozenset({"gid", "home", "uid"}),
        "runtime user",
    )
    runtime_user = RuntimeUser(
        uid=payload["uid"],
        gid=payload["gid"],
        home=_require_posix_path(payload["home"], "runtime user home"),
    )
    if runtime_user.uid == 1000 or runtime_user.gid == 1000:
        raise ValueError("runtime user must not reuse the common host user identity")
    return runtime_user


def _policy_digest(policy: dict[str, object]) -> str:
    canonical = json.dumps(
        policy,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _resolved_policy_payload(bundle: ResolvedLaunchPolicyBundle) -> dict[str, object]:
    return {
        "command_policy": {
            "argument_tokens": [
                (
                    {"kind": token.kind.value}
                    if token.kind is CommandTokenKind.STRATEGY_CLASS_NAME
                    else {"kind": token.kind.value, "value": token.value}
                )
                for token in bundle.command_tokens
            ],
            "entrypoint_argv": list(bundle.entrypoint_argv),
            "execution_mode": bundle.execution_mode.value,
            "policy_id": bundle.command_policy_id,
        },
        "environment_bindings": [
            {
                "kind": binding.kind.value,
                "name": binding.name,
                "value": binding.value,
            }
            for binding in bundle.environment_bindings
        ],
        "health_profile": {
            "interval_seconds": bundle.health_profile.interval_seconds,
            "probe_argv": list(bundle.health_profile.probe_argv),
            "profile_id": bundle.health_profile.profile_id,
            "retries": bundle.health_profile.retries,
            "start_period_seconds": bundle.health_profile.start_period_seconds,
            "timeout_seconds": bundle.health_profile.timeout_seconds,
        },
        "image_policy": {
            "identity_source": bundle.image_identity_source.value,
            "policy_id": bundle.image_policy_id,
        },
        "internal_ports": list(bundle.internal_ports),
        "material_mounts": [
            {
                "material_kind": mount.material_kind.value,
                "policy_id": mount.policy_id,
                "role": mount.role,
                "target": str(mount.target),
            }
            for mount in bundle.material_mounts
        ],
        "network_policy": {
            "networks": [
                {
                    "derivation": rule.derivation.value,
                    "digest_characters": rule.digest_characters,
                    "identity_source": rule.identity_source.value,
                    "internal": rule.internal,
                    "prefix": rule.prefix,
                    "requires_platform_control": rule.requires_platform_control,
                    "requires_upstream_access": rule.requires_upstream_access,
                    "role": rule.role,
                    "suffix": rule.suffix,
                }
                for rule in bundle.network_rules
            ],
            "policy_id": bundle.network_policy_id,
        },
        "resource_profile": {
            "cpu_millis": bundle.resource_limits.cpu_millis,
            "memory_bytes": bundle.resource_limits.memory_bytes,
            "pids_limit": bundle.resource_limits.pids_limit,
            "profile_id": bundle.resource_profile_id,
        },
        "runtime_user": {
            "gid": bundle.runtime_user.gid,
            "home": str(bundle.runtime_user.home),
            "uid": bundle.runtime_user.uid,
        },
        "secret_mounts": [
            {
                "policy_id": mount.policy_id,
                "secret_class": mount.secret_class,
                "target": str(mount.target),
            }
            for mount in bundle.secret_mounts
        ],
        "state_layout": {
            "layout_id": bundle.state_layout_id,
            "targets": [
                {"name": target.name, "value": target.value}
                for target in bundle.state_targets
            ],
        },
        "state_mount": {
            "policy_id": bundle.state_mount.policy_id,
            "role": bundle.state_mount.role,
            "target": str(bundle.state_mount.target),
        },
        "template_id": bundle.template_id,
        "working_directory": str(bundle.working_directory),
    }


def _catalog_digest(policy: dict[str, object]) -> str:
    canonical = (
        json.dumps(
            {"policies": [policy], "schema_version": 1},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_exact_bundle_types(bundle: ResolvedLaunchPolicyBundle) -> None:
    if type(bundle) is not ResolvedLaunchPolicyBundle:
        raise ValueError("resolved launch policy type is invalid")
    exact_values = (
        (bundle.image_identity_source, ImageIdentitySource),
        (bundle.execution_mode, ExecutionMode),
        (bundle.working_directory, PurePosixPath),
        (bundle.state_mount, StateMountPolicy),
        (bundle.runtime_user, RuntimeUser),
        (bundle.health_profile, HealthProfile),
        (bundle.resource_limits, ResourceLimits),
    )
    if any(type(value) is not expected for value, expected in exact_values):
        raise ValueError("resolved launch policy nested type is invalid")
    tuple_types = (
        (bundle.command_tokens, CommandToken),
        (bundle.environment_bindings, EnvironmentBinding),
        (bundle.material_mounts, MaterialMountPolicy),
        (bundle.secret_mounts, SecretMountPolicy),
        (bundle.state_targets, StateTarget),
        (bundle.network_rules, NetworkRule),
    )
    if any(
        type(values) is not tuple
        or any(type(value) is not expected for value in values)
        for values, expected in tuple_types
    ):
        raise ValueError("resolved launch policy tuple type is invalid")
    if type(bundle.entrypoint_argv) is not tuple or any(
        type(value) is not str for value in bundle.entrypoint_argv
    ):
        raise ValueError("resolved launch policy entrypoint type is invalid")
    if type(bundle.internal_ports) is not tuple or any(
        type(value) is not int for value in bundle.internal_ports
    ):
        raise ValueError("resolved launch policy port type is invalid")
    mount_targets = (
        *(mount.target for mount in bundle.material_mounts),
        bundle.state_mount.target,
        *(mount.target for mount in bundle.secret_mounts),
    )
    if any(type(target) is not PurePosixPath for target in mount_targets):
        raise ValueError("resolved launch policy mount target type is invalid")

    ResolvedLaunchPolicyBundle.__post_init__(bundle)
    bundle.state_mount.__post_init__()
    bundle.runtime_user.__post_init__()
    bundle.health_profile.__post_init__()
    bundle.resource_limits.__post_init__()
    for values in (
        bundle.command_tokens,
        bundle.environment_bindings,
        bundle.material_mounts,
        bundle.secret_mounts,
        bundle.state_targets,
        bundle.network_rules,
    ):
        for value in values:
            value.__post_init__()


def validate_resolved_launch_policy_bundle(
    bundle: ResolvedLaunchPolicyBundle,
    template: CommittedTemplate,
) -> None:
    """Revalidate a typed bundle without trusting its constructor or loader history."""

    if type(template) is not CommittedTemplate or any(
        type(value) is not str
        for value in (
            template.canonical_json,
            template.digest,
            template.source_path,
            template.source_commit,
        )
    ):
        raise ValueError("committed template type is invalid")
    _validate_exact_bundle_types(bundle)
    if bundle.template_id != _PAPER_PROBE_TEMPLATE_ID:
        raise ValueError("launch policy is not an approved closed policy")
    if bundle.entrypoint_argv != ("python", "/usr/local/bin/freqtrade-entrypoint"):
        raise ValueError("entrypoint_argv is not an approved executable")
    if bundle.runtime_user.uid == 1000 or bundle.runtime_user.gid == 1000:
        raise ValueError("runtime user must not reuse the common host user identity")
    if PurePosixPath(bundle.health_profile.probe_argv[0]).name.casefold() in {
        "bash",
        "cmd",
        "powershell",
        "pwsh",
        "sh",
    }:
        raise ValueError("health probe must not invoke a shell")
    if (
        bundle.health_profile.start_period_seconds > _MAX_HEALTH_START_PERIOD_SECONDS
        or bundle.health_profile.interval_seconds > _MAX_HEALTH_INTERVAL_SECONDS
        or bundle.health_profile.timeout_seconds > _MAX_HEALTH_TIMEOUT_SECONDS
        or bundle.health_profile.retries > _MAX_HEALTH_RETRIES
    ):
        raise ValueError("health profile exceeds platform limits")
    if (
        bundle.resource_limits.cpu_millis > _MAX_CPU_MILLIS
        or bundle.resource_limits.memory_bytes > _MAX_MEMORY_BYTES
        or bundle.resource_limits.pids_limit > _MAX_PIDS
    ):
        raise ValueError("resource profile exceeds platform limits")

    policy = _resolved_policy_payload(bundle)
    if (
        bundle.policy_digest != _PAPER_PROBE_POLICY_DIGEST
        or _policy_digest(policy) != bundle.policy_digest
    ):
        raise ValueError("resolved launch policy does not match its committed digest")
    if _catalog_digest(policy) != bundle.catalog_digest:
        raise ValueError("resolved launch policy does not match its catalog digest")
    _validate_correlations(bundle, template)


def _validate_state_layout(
    state_mount: StateMountPolicy,
    state_targets: tuple[StateTarget, ...],
    runtime_user: RuntimeUser,
) -> None:
    target_names = tuple(target.name for target in state_targets)
    _require_sorted_unique(target_names, "state target names")
    targets = {target.name: target.value for target in state_targets}
    if set(targets) != {"database_url", "home", "log_file", "root", "user_data"}:
        raise ValueError("state layout targets are incomplete")
    if targets["root"] != str(state_mount.target):
        raise ValueError("state root does not match the writable mount")
    if targets["home"] != str(runtime_user.home):
        raise ValueError("runtime HOME does not match the state layout")
    root = state_mount.target
    data_root = root / "data"
    home_root = root / "home"
    logs_root = root / "logs"
    home = _require_posix_path(targets["home"], "state target home")
    log_file = _require_posix_path(targets["log_file"], "state target log_file")
    user_data = _require_posix_path(targets["user_data"], "state target user_data")
    if home != home_root or user_data != data_root or log_file.parent != logs_root:
        raise ValueError("state targets do not match the managed allocation layout")
    database_prefix = "sqlite:///"
    database_url = targets["database_url"]
    if not database_url.startswith(database_prefix):
        raise ValueError("state database_url must be an absolute sqlite URL")
    database_path = _require_posix_path(
        database_url[len(database_prefix) :],
        "state database path",
    )
    if data_root not in database_path.parents:
        raise ValueError("state database must remain inside managed data")


def _validate_correlations(
    bundle: ResolvedLaunchPolicyBundle,
    template: CommittedTemplate,
) -> None:
    payload = template.payload
    if (
        type(payload) is not MappingProxyType
        or set(payload) != _TEMPLATE_FIELDS
        or payload["schema_version"] != 1
        or payload["template_id"] != _PAPER_PROBE_TEMPLATE_ID
        or payload["semantic_version"] != "1.0.0"
        or payload["allowed_environments"] != ("paper",)
        or payload["allowed_instance_kinds"] != ("freqtrade",)
        or payload["allowed_owner_kinds"] != ("paper_probe",)
    ):
        raise ValueError("committed template is not the approved fixed payload")
    expected = {
        "template_id": bundle.template_id,
        "image_policy_id": bundle.image_policy_id,
        "command_policy_id": bundle.command_policy_id,
        "network_policy_id": bundle.network_policy_id,
        "health_profile_id": bundle.health_profile.profile_id,
        "resource_profile_id": bundle.resource_profile_id,
        "state_layout_id": bundle.state_layout_id,
    }
    if any(payload[field] != value for field, value in expected.items()):
        raise ValueError("launch policy does not match the committed template")

    mount_policy_ids = {
        *(mount.policy_id for mount in bundle.material_mounts),
        bundle.state_mount.policy_id,
        *(mount.policy_id for mount in bundle.secret_mounts),
    }
    if mount_policy_ids != set(payload["mount_policy_ids"]):
        raise ValueError("launch mount policies do not match the committed template")
    secret_classes = tuple(mount.secret_class for mount in bundle.secret_mounts)
    if secret_classes != tuple(payload["secret_classes"]):
        raise ValueError("launch secret classes do not match the committed template")

    material_roles = tuple(mount.role for mount in bundle.material_mounts)
    material_kinds = tuple(
        mount.material_kind.value for mount in bundle.material_mounts
    )
    secret_targets = tuple(str(mount.target) for mount in bundle.secret_mounts)
    _require_sorted_unique(material_roles, "material mount roles")
    _require_sorted_unique(material_kinds, "material mount kinds")
    if material_roles != material_kinds or set(material_kinds) != {
        kind.value for kind in MaterialKind
    }:
        raise ValueError("material mount roles do not match their closed kinds")
    expected_material_policies = {
        "runtime_config": "runtime-config-ro-v1",
        "safety_policy": "safety-policy-ro-v1",
        "strategy": "strategy-ro-v1",
    }
    if any(
        mount.policy_id != expected_material_policies[mount.role]
        for mount in bundle.material_mounts
    ):
        raise ValueError("material mount roles do not match their policy IDs")
    if bundle.state_mount.role != "state":
        raise ValueError("writable mount must use the state role")
    if bundle.state_mount.policy_id != "managed-state-rw-v1":
        raise ValueError("writable state mount uses the wrong policy ID")
    if any(mount.policy_id != "api-secrets-ro-v1" for mount in bundle.secret_mounts):
        raise ValueError("secret mount uses the wrong policy ID")
    _require_sorted_unique(secret_classes, "secret mount classes")
    all_targets = tuple(
        PurePosixPath(target)
        for target in (
            *(str(mount.target) for mount in bundle.material_mounts),
            str(bundle.state_mount.target),
            *secret_targets,
        )
    )
    if len(all_targets) != len(set(all_targets)):
        raise ValueError("launch mount targets must be unique")
    for index, target in enumerate(all_targets):
        if any(
            target in other.parents or other in target.parents
            for other in all_targets[index + 1 :]
        ):
            raise ValueError("launch mount targets must not overlap")
    secret_root = PurePosixPath("/run/secrets")
    if any(mount.target.parent != secret_root for mount in bundle.secret_mounts):
        raise ValueError("secret mount targets must be direct children of /run/secrets")

    state_names = {target.name for target in bundle.state_targets}
    secret_names = {mount.secret_class for mount in bundle.secret_mounts}
    material_names = set(material_roles)
    if (
        sum(
            token.kind is CommandTokenKind.STRATEGY_CLASS_NAME
            for token in bundle.command_tokens
        )
        != 1
    ):
        raise ValueError("command must contain exactly one strategy class token")
    for token in bundle.command_tokens:
        if (
            token.kind is CommandTokenKind.MOUNT_TARGET
            and token.value not in material_names
        ):
            raise ValueError("command references an unknown material mount")
        if (
            token.kind is CommandTokenKind.STATE_TARGET
            and token.value not in state_names
        ):
            raise ValueError("command references an unknown state target")

    environment_names = tuple(binding.name for binding in bundle.environment_bindings)
    _require_sorted_unique(environment_names, "environment binding names")
    for binding in bundle.environment_bindings:
        if (
            binding.kind is EnvironmentBindingKind.SECRET_MOUNT_TARGET
            and binding.value not in secret_names
        ):
            raise ValueError("environment references an unknown secret mount")
        if (
            binding.kind is EnvironmentBindingKind.STATE_TARGET
            and binding.value not in state_names
        ):
            raise ValueError("environment references an unknown state target")
    secret_binding_names = {
        binding.value
        for binding in bundle.environment_bindings
        if binding.kind is EnvironmentBindingKind.SECRET_MOUNT_TARGET
    }
    if secret_binding_names != secret_names:
        raise ValueError("secret mounts require exact path environment bindings")
    secret_environment = {
        binding.value: binding.name
        for binding in bundle.environment_bindings
        if binding.kind is EnvironmentBindingKind.SECRET_MOUNT_TARGET
    }
    if secret_environment != {
        "api_password": "FT_API_PASSWORD_FILE",
        "jwt_secret": "FT_JWT_SECRET_FILE",
        "ws_token": "FT_WS_TOKEN_FILE",
    }:
        raise ValueError("secret path environment bindings do not match the entrypoint")
    state_environment = {
        (binding.name, binding.value)
        for binding in bundle.environment_bindings
        if binding.kind is EnvironmentBindingKind.STATE_TARGET
    }
    if state_environment != {("HOME", "home")}:
        raise ValueError("state environment bindings do not match the entrypoint")
    _validate_state_layout(
        bundle.state_mount, bundle.state_targets, bundle.runtime_user
    )


def _parse_policy(
    policy: dict[str, object],
    *,
    template: CommittedTemplate,
    source_commit: str,
    catalog_blob_id: str,
    catalog_digest: str,
    policy_digest: str,
) -> ResolvedLaunchPolicyBundle:
    fields = frozenset(
        {
            "command_policy",
            "environment_bindings",
            "health_profile",
            "image_policy",
            "internal_ports",
            "material_mounts",
            "network_policy",
            "resource_profile",
            "runtime_user",
            "secret_mounts",
            "state_layout",
            "state_mount",
            "template_id",
            "working_directory",
        }
    )
    payload = _require_object(policy, fields, "launch policy")
    image = _require_object(
        payload["image_policy"],
        frozenset({"identity_source", "policy_id"}),
        "image policy",
    )
    command = _require_object(
        payload["command_policy"],
        frozenset(
            {
                "argument_tokens",
                "entrypoint_argv",
                "execution_mode",
                "policy_id",
            }
        ),
        "command policy",
    )
    network = _require_object(
        payload["network_policy"],
        frozenset({"networks", "policy_id"}),
        "network policy",
    )
    state_layout = _require_object(
        payload["state_layout"],
        frozenset({"layout_id", "targets"}),
        "state layout",
    )

    try:
        image_identity_source = ImageIdentitySource(image["identity_source"])
        execution_mode = ExecutionMode(command["execution_mode"])
    except (TypeError, ValueError):
        raise ValueError("launch policy contains an unknown closed mode") from None

    entrypoint_values = _require_array(command["entrypoint_argv"], "entrypoint_argv")
    if any(type(value) is not str for value in entrypoint_values):
        raise ValueError("entrypoint_argv must contain strings")
    entrypoint_argv = tuple(entrypoint_values)
    if entrypoint_argv != ("python", "/usr/local/bin/freqtrade-entrypoint"):
        raise ValueError("entrypoint_argv is not an approved executable")

    command_tokens = tuple(
        _command_token(value)
        for value in _require_array(command["argument_tokens"], "argument_tokens")
    )
    environment_bindings = tuple(
        _environment_binding(value)
        for value in _require_array(
            payload["environment_bindings"],
            "environment_bindings",
        )
    )
    material_mounts = tuple(
        _material_mount(value)
        for value in _require_array(payload["material_mounts"], "material_mounts")
    )
    secret_mounts = tuple(
        _secret_mount(value)
        for value in _require_array(payload["secret_mounts"], "secret_mounts")
    )
    state_targets = tuple(
        _state_target(value)
        for value in _require_array(state_layout["targets"], "state targets")
    )
    network_rules = tuple(
        _network_rule(value)
        for value in _require_array(network["networks"], "network rules")
    )
    _require_sorted_unique(
        tuple(rule.role for rule in network_rules),
        "network roles",
    )
    internal_port_values = _require_array(payload["internal_ports"], "internal_ports")
    internal_ports = tuple(internal_port_values)
    resource_profile_id, resource_limits = _parse_resource(payload["resource_profile"])

    bundle = ResolvedLaunchPolicyBundle(
        template_id=_require_identifier(payload["template_id"], "template_id"),
        template_digest=template.digest,
        source_commit=source_commit,
        catalog_source_path=_CATALOG_PATH,
        catalog_blob_id=catalog_blob_id,
        catalog_digest=catalog_digest,
        policy_digest=policy_digest,
        image_policy_id=_require_identifier(image["policy_id"], "image policy_id"),
        image_identity_source=image_identity_source,
        command_policy_id=_require_identifier(
            command["policy_id"], "command policy_id"
        ),
        execution_mode=execution_mode,
        entrypoint_argv=entrypoint_argv,
        command_tokens=command_tokens,
        working_directory=_require_posix_path(
            payload["working_directory"],
            "working_directory",
        ),
        environment_bindings=environment_bindings,
        material_mounts=material_mounts,
        state_mount=_state_mount(payload["state_mount"]),
        secret_mounts=secret_mounts,
        state_layout_id=_require_identifier(
            state_layout["layout_id"],
            "state layout_id",
        ),
        state_targets=state_targets,
        runtime_user=_parse_runtime_user(payload["runtime_user"]),
        internal_ports=internal_ports,
        health_profile=_parse_health(payload["health_profile"]),
        resource_profile_id=resource_profile_id,
        resource_limits=resource_limits,
        network_policy_id=_require_identifier(
            network["policy_id"], "network policy_id"
        ),
        network_rules=network_rules,
    )
    validate_resolved_launch_policy_bundle(bundle, template)
    return bundle


def load_resolved_launch_policy_bundle(
    root: Path,
    template_id: str,
    commit: str,
) -> ResolvedLaunchPolicyBundle:
    _require_identifier(template_id, "template_id")
    store = CommittedGitStore(root, commit)
    store.assert_launch_policy_checkout_clean()
    document = store.read_launch_policy_catalog_blob()
    payload = parse_canonical_json_document(document)
    catalog = _require_object(
        payload,
        frozenset({"policies", "schema_version"}),
        "launch policy catalog",
    )
    if type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1:
        raise ValueError("launch policy catalog schema_version must be integer 1")
    policies = _require_array(catalog["policies"], "launch policies")
    if any(not isinstance(policy, dict) for policy in policies):
        raise ValueError("launch policies must contain JSON objects")
    policy_ids = tuple(
        _require_identifier(policy.get("template_id"), "launch policy template_id")
        for policy in policies
    )
    _require_sorted_unique(policy_ids, "launch policy template IDs")
    if policy_ids != (_PAPER_PROBE_TEMPLATE_ID,):
        raise ValueError(
            "launch policy catalog must contain only the approved paper probe"
        )
    if template_id != _PAPER_PROBE_TEMPLATE_ID:
        raise ValueError("launch policy is not approved for the template") from None
    catalog_blob_id = store.launch_policy_catalog_blob_id()
    catalog_digest = hashlib.sha256(document).hexdigest()
    selected = policies[0]
    assert isinstance(selected, dict)
    policy_digest = _policy_digest(selected)
    if policy_digest != _PAPER_PROBE_POLICY_DIGEST:
        raise ValueError(
            "freqtrade paper probe launch policy must match the approved payload"
        )
    template = read_committed_template(root, template_id, store.root_commit)
    return _parse_policy(
        selected,
        template=template,
        source_commit=store.root_commit,
        catalog_blob_id=catalog_blob_id,
        catalog_digest=catalog_digest,
        policy_digest=policy_digest,
    )
