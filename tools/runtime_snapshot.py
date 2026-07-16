from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from tools.runtime_artifacts import VerifiedReadOnlyMaterial
from tools.runtime_driver import (
    DriverIdentity,
    DriverPolicyError,
    DriverValidationError,
    EnvironmentEntry,
    HealthProfile,
    LaunchSnapshot,
    ReadOnlyMount,
    ResourceLimits,
    RuntimeUser,
    SecretMount,
    SecretPathEnvironmentBinding,
    WritableStateMount,
)
from tools.runtime_launch_policy import (
    CommandTokenKind,
    EnvironmentBindingKind,
    ExecutionMode,
    ImageIdentitySource,
    NetworkIdentitySource,
    NetworkNameDerivation,
    ResolvedLaunchPolicyBundle,
    validate_resolved_launch_policy_bundle,
)
from tools.runtime_secrets import VerifiedSecretMount
from tools.runtime_state import VerifiedStateMount
from tools.runtime_templates import CommittedTemplate


_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_STRATEGY_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_ENVIRONMENT_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
_LABEL_NAME = re.compile(r"[a-z0-9][a-z0-9.-]{0,127}")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_MATERIAL_PROVIDER_ID = "committed-paper-probe-material-v1"
_STATE_PROVIDER_ID = "managed-local-v1"
_SECRET_PROVIDER_ID = "local-file-secret-v1"
_MATERIAL_PATHS = {
    "runtime_config": "ft_userdata/user_data/config.example.json",
    "safety_policy": "ops/config/trading-safety.json",
    "strategy": "ft_userdata/user_data/strategies/sample_strategy.py",
}
_PAPER_PROBE_TEMPLATE_PAYLOAD = {
    "allowed_environments": ("paper",),
    "allowed_instance_kinds": ("freqtrade",),
    "allowed_owner_kinds": ("paper_probe",),
    "command_policy_id": "freqtrade-spot-paper-v1",
    "health_profile_id": "freqtrade-ping-v1",
    "image_policy_id": "freqtrade-reviewed-image-v1",
    "mount_policy_ids": (
        "runtime-config-ro-v1",
        "safety-policy-ro-v1",
        "strategy-ro-v1",
        "managed-state-rw-v1",
        "api-secrets-ro-v1",
    ),
    "network_policy_id": "isolated-public-market-data-v1",
    "resource_profile_id": "freqtrade-small-v1",
    "schema_version": 1,
    "secret_classes": ("api_password", "jwt_secret", "ws_token"),
    "semantic_version": "1.0.0",
    "state_layout_id": "freqtrade-state-v1",
    "template_id": "freqtrade-paper-probe-v1",
}


def _require_identifier(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise DriverValidationError()
    return value


def _require_digest(value: object) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise DriverValidationError()
    return value


def _require_git_object_id(value: object) -> str:
    if type(value) is not str or _GIT_OBJECT_ID.fullmatch(value) is None:
        raise DriverValidationError()
    return value


def _require_string_tuple(
    value: object, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or (not allow_empty and not value)
        or any(type(item) is not str or not item for item in value)
    ):
        raise DriverValidationError()
    return value


@dataclass(frozen=True, slots=True)
class RuntimeSpecLaunchAuthority:
    runtime_spec_revision_id: str
    payload_digest: str
    owner_kind: str
    instance_kind: str
    environment: str
    adapter_template_revision_id: str
    template_digest: str
    image_policy_id: str
    command_policy_id: str
    mount_policy_ids: tuple[str, ...]
    network_policy_id: str
    health_profile_id: str
    resource_profile_id: str
    state_layout_id: str
    state_allocation_id: str
    secret_reference_ids: tuple[str, ...]
    config_blob_commit: str
    strategy_commit: str
    strategy_class_name: str | None
    safety_policy_commit: str
    root_commit: str
    backend_commit: str
    frontend_commit: str
    strategies_commit: str
    config_blob_digest: str
    strategy_digest: str
    safety_policy_digest: str

    def __post_init__(self) -> None:
        identifiers = (
            self.runtime_spec_revision_id,
            self.owner_kind,
            self.instance_kind,
            self.environment,
            self.adapter_template_revision_id,
            self.image_policy_id,
            self.command_policy_id,
            self.network_policy_id,
            self.health_profile_id,
            self.resource_profile_id,
            self.state_layout_id,
            self.state_allocation_id,
        )
        for value in identifiers:
            _require_identifier(value)
        for value in (
            self.payload_digest,
            self.template_digest,
            self.config_blob_digest,
            self.strategy_digest,
            self.safety_policy_digest,
        ):
            _require_digest(value)
        for value in (
            self.config_blob_commit,
            self.strategy_commit,
            self.safety_policy_commit,
            self.root_commit,
            self.backend_commit,
            self.frontend_commit,
            self.strategies_commit,
        ):
            _require_git_object_id(value)
        for values in (self.mount_policy_ids, self.secret_reference_ids):
            for value in _require_string_tuple(values):
                _require_identifier(value)
            if len(values) != len(set(values)):
                raise DriverValidationError()
        if self.strategy_class_name is not None and (
            type(self.strategy_class_name) is not str
            or _STRATEGY_CLASS.fullmatch(self.strategy_class_name) is None
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class ResolvedSecretVersionAuthority:
    secret_reference_id: str
    version_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.secret_reference_id)
        _require_identifier(self.version_id)


@dataclass(frozen=True, slots=True)
class ResolvedAttemptAuthority:
    attempt_id: str
    instance_id: str
    runtime_spec_revision_id: str
    runtime_spec_payload_digest: str
    adapter_template_revision_id: str
    state_allocation_id: str
    resolved_secret_versions: tuple[ResolvedSecretVersionAuthority, ...]
    image_id: str
    root_commit: str
    backend_commit: str
    frontend_commit: str
    strategies_commit: str
    project_identity: str
    container_identity: str

    def __post_init__(self) -> None:
        for value in (
            self.attempt_id,
            self.instance_id,
            self.runtime_spec_revision_id,
            self.adapter_template_revision_id,
            self.state_allocation_id,
            self.project_identity,
            self.container_identity,
        ):
            _require_identifier(value)
        _require_digest(self.runtime_spec_payload_digest)
        if type(self.image_id) is not str or _IMAGE_ID.fullmatch(self.image_id) is None:
            raise DriverValidationError()
        for value in (
            self.root_commit,
            self.backend_commit,
            self.frontend_commit,
            self.strategies_commit,
        ):
            _require_git_object_id(value)
        if type(self.resolved_secret_versions) is not tuple or any(
            type(value) is not ResolvedSecretVersionAuthority
            for value in self.resolved_secret_versions
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class LaunchCompilationAuthority:
    spec: RuntimeSpecLaunchAuthority
    attempt: ResolvedAttemptAuthority
    template: CommittedTemplate
    policies: ResolvedLaunchPolicyBundle
    state: VerifiedStateMount
    secrets: tuple[VerifiedSecretMount, ...]
    materials: tuple[VerifiedReadOnlyMaterial, ...]
    identity: DriverIdentity

    def __post_init__(self) -> None:
        if (
            type(self.spec) is not RuntimeSpecLaunchAuthority
            or type(self.attempt) is not ResolvedAttemptAuthority
            or type(self.template) is not CommittedTemplate
            or type(self.policies) is not ResolvedLaunchPolicyBundle
            or type(self.state) is not VerifiedStateMount
            or type(self.identity) is not DriverIdentity
            or type(self.secrets) is not tuple
            or any(type(value) is not VerifiedSecretMount for value in self.secrets)
            or type(self.materials) is not tuple
            or any(
                type(value) is not VerifiedReadOnlyMaterial for value in self.materials
            )
        ):
            raise DriverValidationError()
        self.spec.__post_init__()
        self.attempt.__post_init__()
        self.identity.__post_init__()
        for material in self.materials:
            string_values = (
                material.role,
                material.attempt_id,
                material.provider_id,
                material.root_commit,
                material.repository_relative_path,
                material.blob_sha256,
            )
            if (
                any(type(value) is not str for value in string_values)
                or type(material.source_path) is not type(Path())
                or (
                    material.strategy_class_name is not None
                    and type(material.strategy_class_name) is not str
                )
            ):
                raise DriverValidationError()
        state_strings = (
            self.state.attempt_id,
            self.state.state_allocation_id,
            self.state.instance_id,
            self.state.layout_id,
            self.state.provider_id,
            self.state.relative_path,
            self.state.durability,
        )
        if any(type(value) is not str for value in state_strings) or type(
            self.state.source
        ) is not type(Path()):
            raise DriverValidationError()
        if (
            type(self.state.generation) is not int
            or self.state.generation < 1
            or type(self.state.runtime_uid) is not int
            or self.state.runtime_uid < 0
            or self.state.durability not in ("atomic-process-crash", "power-loss-posix")
            or self.state.relative_path
            != f"ft_userdata/runtime/instances/{self.state.instance_id}"
        ):
            raise DriverValidationError()
        for secret in self.secrets:
            if any(
                type(value) is not str
                for value in (
                    secret.attempt_id,
                    secret.provider_id,
                    secret.reference_id,
                    secret.version_id,
                    secret.secret_class,
                )
            ) or type(secret.source) is not type(Path()):
                raise DriverValidationError()


class RenderedMountKind(StrEnum):
    MATERIAL = "material"
    STATE = "state"
    SECRET = "secret"


@dataclass(frozen=True, slots=True)
class RenderedMount:
    kind: RenderedMountKind
    role: str
    source: Path = field(repr=False)
    target: PurePosixPath
    read_only: bool

    def __post_init__(self) -> None:
        if (
            type(self.kind) is not RenderedMountKind
            or type(self.role) is not str
            or not self.role
            or type(self.source) is not type(Path())
            or not self.source.is_absolute()
            or type(self.target) is not PurePosixPath
            or not self.target.is_absolute()
            or type(self.read_only) is not bool
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class RenderedEnvironmentEntry:
    name: str
    value: str

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or _ENVIRONMENT_NAME.fullmatch(self.name) is None
            or type(self.value) is not str
            or not self.value
            or _CONTROL_CHARACTER.search(self.value) is not None
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class RenderedLabel:
    name: str
    value: str

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or _LABEL_NAME.fullmatch(self.name) is None
            or type(self.value) is not str
            or not self.value
            or _CONTROL_CHARACTER.search(self.value) is not None
        ):
            raise DriverValidationError()


@dataclass(frozen=True, slots=True)
class RenderedContainerPolicy:
    identity: DriverIdentity
    image_id: str
    argv: tuple[str, ...]
    working_directory: PurePosixPath
    environment: tuple[RenderedEnvironmentEntry, ...]
    mounts: tuple[RenderedMount, ...]
    runtime_user: RuntimeUser
    internal_ports: tuple[int, ...]
    health_profile: HealthProfile
    resource_limits: ResourceLimits
    network_names: tuple[str, ...]
    restart: str
    network_mode: str | None
    pid_mode: str | None
    ipc_mode: str | None
    privileged: bool
    devices: tuple[str, ...]
    cap_add: tuple[str, ...]
    cap_drop: tuple[str, ...]
    security_options: tuple[str, ...]
    read_only_root_filesystem: bool
    published_ports: tuple[str, ...]
    labels: tuple[RenderedLabel, ...]

    def __post_init__(self) -> None:
        typed_values = (
            (self.identity, DriverIdentity),
            (self.runtime_user, RuntimeUser),
            (self.health_profile, HealthProfile),
            (self.resource_limits, ResourceLimits),
        )
        if any(type(value) is not expected for value, expected in typed_values):
            raise DriverValidationError()
        if type(self.image_id) is not str or _IMAGE_ID.fullmatch(self.image_id) is None:
            raise DriverValidationError()
        if (
            type(self.working_directory) is not PurePosixPath
            or not self.working_directory.is_absolute()
        ):
            raise DriverValidationError()
        tuple_types = (
            (self.environment, RenderedEnvironmentEntry),
            (self.mounts, RenderedMount),
            (self.labels, RenderedLabel),
        )
        if any(
            type(values) is not tuple
            or any(type(value) is not expected for value in values)
            for values, expected in tuple_types
        ):
            raise DriverValidationError()
        for values in (
            self.argv,
            self.network_names,
            self.devices,
            self.cap_add,
            self.cap_drop,
            self.security_options,
            self.published_ports,
        ):
            _require_string_tuple(values, allow_empty=True)
        if type(self.internal_ports) is not tuple or any(
            type(port) is not int for port in self.internal_ports
        ):
            raise DriverValidationError()
        if any(
            value is not None and type(value) is not str
            for value in (self.network_mode, self.pid_mode, self.ipc_mode)
        ) or any(
            type(value) is not bool
            for value in (self.privileged, self.read_only_root_filesystem)
        ):
            raise DriverValidationError()
        if type(self.restart) is not str or not self.restart:
            raise DriverValidationError()


def _policy(condition: bool) -> None:
    if not condition:
        raise DriverPolicyError()


def _validate_template(template: CommittedTemplate) -> None:
    _policy(
        all(
            type(value) is str
            for value in (
                template.canonical_json,
                template.digest,
                template.source_path,
                template.source_commit,
            )
        )
    )
    _policy(type(template.payload) is MappingProxyType)
    payload = template.payload
    _policy(all(type(key) is str for key in payload))
    _policy(
        all(
            type(value) in {int, str}
            or (type(value) is tuple and all(type(item) is str for item in value))
            for value in payload.values()
        )
    )
    _policy(dict(payload) == _PAPER_PROBE_TEMPLATE_PAYLOAD)
    try:
        decoded = json.loads(template.canonical_json)
        canonical = (
            json.dumps(
                decoded, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            + "\n"
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        raise DriverPolicyError() from None
    _policy(canonical == template.canonical_json)
    _policy(hashlib.sha256(canonical.encode("utf-8")).hexdigest() == template.digest)
    _policy(
        decoded
        == {
            key: list(value) if type(value) is tuple else value
            for key, value in payload.items()
        }
    )
    template_id = payload.get("template_id")
    _policy(type(template_id) is str)
    _policy(template.source_path == f"ops/adapter-templates/{template_id}.json")


def _validate_authority(authority: LaunchCompilationAuthority) -> None:
    spec = authority.spec
    attempt = authority.attempt
    template = authority.template
    policies = authority.policies
    state = authority.state
    identity = authority.identity

    _validate_template(template)
    try:
        validate_resolved_launch_policy_bundle(policies, template)
    except ValueError:
        raise DriverPolicyError() from None
    _policy(spec.runtime_spec_revision_id == f"runtime-spec-{spec.payload_digest}")
    _policy(spec.runtime_spec_revision_id == attempt.runtime_spec_revision_id)
    _policy(spec.payload_digest == attempt.runtime_spec_payload_digest)
    _policy(spec.payload_digest == identity.runtime_spec_digest)
    _policy(spec.strategy_class_name is not None)
    _policy(attempt.instance_id == identity.instance_id)
    _policy(attempt.attempt_id == identity.attempt_id)
    _policy(attempt.project_identity == identity.project_name)
    _policy(attempt.container_identity == identity.container_name)
    _policy(attempt.image_id == identity.image_id)
    _policy(attempt.state_allocation_id == identity.state_allocation_id)

    payload = template.payload
    _policy(spec.adapter_template_revision_id == attempt.adapter_template_revision_id)
    _policy(spec.adapter_template_revision_id == f"template-{template.digest}")
    _policy(spec.template_digest == template.digest == policies.template_digest)
    _policy(template.source_commit == spec.root_commit == policies.source_commit)
    _policy(payload.get("template_id") == policies.template_id)
    _policy(spec.instance_kind in tuple(payload.get("allowed_instance_kinds", ())))
    _policy(spec.owner_kind in tuple(payload.get("allowed_owner_kinds", ())))
    _policy(spec.environment in tuple(payload.get("allowed_environments", ())))

    policy_mount_ids = (
        *(mount.policy_id for mount in policies.material_mounts),
        policies.state_mount.policy_id,
        *(mount.policy_id for mount in policies.secret_mounts),
    )
    expected_policy_values = (
        (
            spec.image_policy_id,
            payload.get("image_policy_id"),
            policies.image_policy_id,
        ),
        (
            spec.command_policy_id,
            payload.get("command_policy_id"),
            policies.command_policy_id,
        ),
        (
            spec.network_policy_id,
            payload.get("network_policy_id"),
            policies.network_policy_id,
        ),
        (
            spec.health_profile_id,
            payload.get("health_profile_id"),
            policies.health_profile.profile_id,
        ),
        (
            spec.resource_profile_id,
            payload.get("resource_profile_id"),
            policies.resource_profile_id,
        ),
        (
            spec.state_layout_id,
            payload.get("state_layout_id"),
            policies.state_layout_id,
        ),
    )
    _policy(
        all(left == middle == right for left, middle, right in expected_policy_values)
    )
    _policy(spec.mount_policy_ids == tuple(payload.get("mount_policy_ids", ())))
    _policy(set(spec.mount_policy_ids) == set(policy_mount_ids))
    _policy(
        tuple(payload.get("secret_classes", ()))
        == tuple(mount.secret_class for mount in policies.secret_mounts)
    )
    _policy(
        policies.image_identity_source is ImageIdentitySource.RESOLVED_ATTEMPT_SHA256
    )
    _policy(policies.execution_mode is ExecutionMode.IMAGE_ENTRYPOINT_ARGS)
    _policy(
        policies.entrypoint_argv == ("python", "/usr/local/bin/freqtrade-entrypoint")
    )

    for spec_commit, attempt_commit in (
        (spec.root_commit, attempt.root_commit),
        (spec.backend_commit, attempt.backend_commit),
        (spec.frontend_commit, attempt.frontend_commit),
        (spec.strategies_commit, attempt.strategies_commit),
    ):
        _policy(spec_commit == attempt_commit)

    material_roles = tuple(material.role for material in authority.materials)
    policy_roles = tuple(mount.role for mount in policies.material_mounts)
    _policy(material_roles == policy_roles == tuple(sorted(_MATERIAL_PATHS)))
    material_digests = {
        "runtime_config": spec.config_blob_digest,
        "safety_policy": spec.safety_policy_digest,
        "strategy": spec.strategy_digest,
    }
    material_commits = {
        "runtime_config": spec.config_blob_commit,
        "safety_policy": spec.safety_policy_commit,
        "strategy": spec.strategy_commit,
    }
    for material in authority.materials:
        _policy(material.attempt_id == attempt.attempt_id)
        _policy(material.provider_id == _MATERIAL_PROVIDER_ID)
        _policy(material.repository_relative_path == _MATERIAL_PATHS[material.role])
        _policy(material.root_commit == material_commits[material.role])
        _policy(material.blob_sha256 == material_digests[material.role])
        if material.role == "strategy":
            _policy(material.strategy_class_name == spec.strategy_class_name)

    _policy(state.attempt_id == attempt.attempt_id)
    _policy(state.instance_id == attempt.instance_id == identity.instance_id)
    _policy(state.state_allocation_id == spec.state_allocation_id)
    _policy(state.state_allocation_id == attempt.state_allocation_id)
    _policy(state.state_allocation_id == identity.state_allocation_id)
    _policy(state.layout_id == spec.state_layout_id == policies.state_layout_id)
    _policy(state.provider_id == _STATE_PROVIDER_ID)
    _policy(state.runtime_uid == policies.runtime_user.uid)
    _policy(
        state.relative_path == f"ft_userdata/runtime/instances/{identity.instance_id}"
    )

    secret_order = tuple(
        (secret.secret_class, secret.reference_id, secret.version_id)
        for secret in authority.secrets
    )
    _policy(secret_order == tuple(sorted(secret_order)))
    _policy(len(secret_order) == len(set(secret_order)))
    _policy(
        tuple(secret.secret_class for secret in authority.secrets)
        == tuple(mount.secret_class for mount in policies.secret_mounts)
    )
    _policy(
        tuple(secret.reference_id for secret in authority.secrets)
        == spec.secret_reference_ids
    )
    resolved_versions = tuple(
        (version.secret_reference_id, version.version_id)
        for version in attempt.resolved_secret_versions
    )
    _policy(resolved_versions == tuple(sorted(resolved_versions)))
    _policy(len(resolved_versions) == len(set(resolved_versions)))
    _policy(
        tuple((secret.reference_id, secret.version_id) for secret in authority.secrets)
        == resolved_versions
    )
    for secret in authority.secrets:
        _policy(secret.attempt_id == attempt.attempt_id)
        _policy(secret.provider_id == _SECRET_PROVIDER_ID)

    _policy(policies.state_mount.role == "state")
    _policy(policies.runtime_user.uid > 0 and policies.runtime_user.gid > 0)
    _policy(policies.internal_ports == tuple(sorted(set(policies.internal_ports))))
    targets = (
        *(mount.target for mount in policies.material_mounts),
        policies.state_mount.target,
        *(mount.target for mount in policies.secret_mounts),
    )
    _policy(len(targets) == len(set(targets)))
    for index, target in enumerate(targets):
        _policy(
            not any(
                target in other.parents or other in target.parents
                for other in targets[index + 1 :]
            )
        )

    networks = _derived_network_names(authority)
    _policy(networks == identity.network_names)


def _derived_network_names(authority: LaunchCompilationAuthority) -> tuple[str, ...]:
    names: list[str] = []
    for rule in authority.policies.network_rules:
        _policy(rule.identity_source is NetworkIdentitySource.INSTANCE_ID)
        _policy(rule.derivation is NetworkNameDerivation.SHA256_PREFIX_V1)
        digest = hashlib.sha256(
            authority.identity.instance_id.encode("utf-8")
        ).hexdigest()
        names.append(f"{rule.prefix}{digest[: rule.digest_characters]}{rule.suffix}")
    return tuple(sorted(set(names)))


def _expanded_command(authority: LaunchCompilationAuthority) -> tuple[str, ...]:
    policies = authority.policies
    material_targets = {
        mount.role: str(mount.target) for mount in policies.material_mounts
    }
    state_targets = {target.name: target.value for target in policies.state_targets}
    command: list[str] = list(policies.entrypoint_argv)
    strategy_tokens = 0
    for token in policies.command_tokens:
        if token.kind is CommandTokenKind.LITERAL:
            _policy(token.value is not None)
            command.append(token.value)
        elif token.kind is CommandTokenKind.STRATEGY_CLASS_NAME:
            strategy_tokens += 1
            _policy(authority.spec.strategy_class_name is not None)
            command.append(authority.spec.strategy_class_name)
        elif token.kind is CommandTokenKind.MOUNT_TARGET:
            _policy(token.value in material_targets)
            command.append(material_targets[token.value])
        elif token.kind is CommandTokenKind.STATE_TARGET:
            _policy(token.value in state_targets)
            command.append(state_targets[token.value])
        else:
            raise DriverPolicyError()
    _policy(strategy_tokens == 1)
    return tuple(command)


def _compiled_environment(
    authority: LaunchCompilationAuthority,
) -> tuple[tuple[EnvironmentEntry, ...], tuple[SecretPathEnvironmentBinding, ...]]:
    state_targets = {
        target.name: target.value for target in authority.policies.state_targets
    }
    secret_targets = {
        mount.secret_class: mount.target for mount in authority.policies.secret_mounts
    }
    environment: list[EnvironmentEntry] = []
    secret_environment: list[SecretPathEnvironmentBinding] = []
    for binding in authority.policies.environment_bindings:
        if binding.kind is EnvironmentBindingKind.STATE_TARGET:
            _policy(binding.value in state_targets)
            environment.append(
                EnvironmentEntry(binding.name, state_targets[binding.value])
            )
        elif binding.kind is EnvironmentBindingKind.SECRET_MOUNT_TARGET:
            _policy(binding.value in secret_targets)
            secret_environment.append(
                SecretPathEnvironmentBinding(
                    binding.name, secret_targets[binding.value]
                )
            )
        else:
            raise DriverPolicyError()
    environment.sort(key=lambda entry: entry.name)
    secret_environment.sort(key=lambda entry: entry.name)
    return tuple(environment), tuple(secret_environment)


def _authority_projection(
    authority: LaunchCompilationAuthority,
    secret_environment: tuple[SecretPathEnvironmentBinding, ...],
) -> dict[str, object]:
    spec = authority.spec
    attempt = authority.attempt
    policies = authority.policies
    identity = authority.identity
    return {
        "schema_version": 1,
        "runtime_spec": {
            "runtime_spec_revision_id": spec.runtime_spec_revision_id,
            "payload_digest": spec.payload_digest,
            "owner_kind": spec.owner_kind,
            "instance_kind": spec.instance_kind,
            "environment": spec.environment,
            "adapter_template_revision_id": spec.adapter_template_revision_id,
            "template_digest": spec.template_digest,
            "image_policy_id": spec.image_policy_id,
            "command_policy_id": spec.command_policy_id,
            "mount_policy_ids": list(spec.mount_policy_ids),
            "network_policy_id": spec.network_policy_id,
            "health_profile_id": spec.health_profile_id,
            "resource_profile_id": spec.resource_profile_id,
            "state_layout_id": spec.state_layout_id,
            "state_allocation_id": spec.state_allocation_id,
            "secret_reference_ids": list(spec.secret_reference_ids),
            "config_blob_commit": spec.config_blob_commit,
            "strategy_commit": spec.strategy_commit,
            "strategy_class_name": spec.strategy_class_name,
            "safety_policy_commit": spec.safety_policy_commit,
            "root_commit": spec.root_commit,
            "backend_commit": spec.backend_commit,
            "frontend_commit": spec.frontend_commit,
            "strategies_commit": spec.strategies_commit,
            "config_blob_digest": spec.config_blob_digest,
            "strategy_digest": spec.strategy_digest,
            "safety_policy_digest": spec.safety_policy_digest,
        },
        "attempt": {
            "attempt_id": attempt.attempt_id,
            "instance_id": attempt.instance_id,
            "runtime_spec_revision_id": attempt.runtime_spec_revision_id,
            "runtime_spec_payload_digest": attempt.runtime_spec_payload_digest,
            "adapter_template_revision_id": attempt.adapter_template_revision_id,
            "state_allocation_id": attempt.state_allocation_id,
            "resolved_secret_versions": [
                {
                    "secret_reference_id": value.secret_reference_id,
                    "version_id": value.version_id,
                }
                for value in attempt.resolved_secret_versions
            ],
            "image_id": attempt.image_id,
            "root_commit": attempt.root_commit,
            "backend_commit": attempt.backend_commit,
            "frontend_commit": attempt.frontend_commit,
            "strategies_commit": attempt.strategies_commit,
            "project_identity": attempt.project_identity,
            "container_identity": attempt.container_identity,
        },
        "template": {
            "digest": authority.template.digest,
            "source_path": authority.template.source_path,
            "source_commit": authority.template.source_commit,
            "canonical_json": authority.template.canonical_json,
        },
        "policy": {
            "template_id": policies.template_id,
            "template_digest": policies.template_digest,
            "source_commit": policies.source_commit,
            "catalog_source_path": policies.catalog_source_path,
            "catalog_blob_id": policies.catalog_blob_id,
            "catalog_digest": policies.catalog_digest,
            "policy_digest": policies.policy_digest,
            "image_policy_id": policies.image_policy_id,
            "image_identity_source": policies.image_identity_source.value,
            "command_policy_id": policies.command_policy_id,
            "execution_mode": policies.execution_mode.value,
            "entrypoint_argv": list(policies.entrypoint_argv),
            "command_tokens": [
                {"kind": token.kind.value, "value": token.value}
                for token in policies.command_tokens
            ],
            "working_directory": str(policies.working_directory),
            "environment_bindings": [
                {"name": value.name, "kind": value.kind.value, "value": value.value}
                for value in policies.environment_bindings
            ],
            "material_mounts": [
                {
                    "policy_id": value.policy_id,
                    "role": value.role,
                    "material_kind": value.material_kind.value,
                    "target": str(value.target),
                }
                for value in policies.material_mounts
            ],
            "state_mount": {
                "policy_id": policies.state_mount.policy_id,
                "role": policies.state_mount.role,
                "target": str(policies.state_mount.target),
            },
            "secret_mounts": [
                {
                    "policy_id": value.policy_id,
                    "secret_class": value.secret_class,
                    "target": str(value.target),
                }
                for value in policies.secret_mounts
            ],
            "state_layout_id": policies.state_layout_id,
            "state_targets": [
                {"name": value.name, "value": value.value}
                for value in policies.state_targets
            ],
            "runtime_user": {
                "uid": policies.runtime_user.uid,
                "gid": policies.runtime_user.gid,
                "home": str(policies.runtime_user.home),
            },
            "internal_ports": list(policies.internal_ports),
            "health_profile": {
                "profile_id": policies.health_profile.profile_id,
                "probe_argv": list(policies.health_profile.probe_argv),
                "start_period_seconds": policies.health_profile.start_period_seconds,
                "interval_seconds": policies.health_profile.interval_seconds,
                "timeout_seconds": policies.health_profile.timeout_seconds,
                "retries": policies.health_profile.retries,
            },
            "resource_profile_id": policies.resource_profile_id,
            "resource_limits": {
                "cpu_millis": policies.resource_limits.cpu_millis,
                "memory_bytes": policies.resource_limits.memory_bytes,
                "pids_limit": policies.resource_limits.pids_limit,
            },
            "network_policy_id": policies.network_policy_id,
            "network_rules": [
                {
                    "role": value.role,
                    "identity_source": value.identity_source.value,
                    "derivation": value.derivation.value,
                    "prefix": value.prefix,
                    "digest_characters": value.digest_characters,
                    "suffix": value.suffix,
                    "internal": value.internal,
                    "requires_upstream_access": value.requires_upstream_access,
                    "requires_platform_control": value.requires_platform_control,
                }
                for value in policies.network_rules
            ],
        },
        "materials": [
            {
                "role": value.role,
                "attempt_id": value.attempt_id,
                "provider_id": value.provider_id,
                "root_commit": value.root_commit,
                "repository_relative_path": value.repository_relative_path,
                "blob_sha256": value.blob_sha256,
                "strategy_class_name": value.strategy_class_name,
            }
            for value in authority.materials
        ],
        "state": {
            "attempt_id": authority.state.attempt_id,
            "state_allocation_id": authority.state.state_allocation_id,
            "instance_id": authority.state.instance_id,
            "layout_id": authority.state.layout_id,
            "provider_id": authority.state.provider_id,
            "generation": authority.state.generation,
            "relative_path": authority.state.relative_path,
            "runtime_uid": authority.state.runtime_uid,
            "durability": authority.state.durability,
        },
        "secrets": [
            {
                "attempt_id": value.attempt_id,
                "provider_id": value.provider_id,
                "reference_id": value.reference_id,
                "version_id": value.version_id,
                "secret_class": value.secret_class,
            }
            for value in authority.secrets
        ],
        "identity": {
            "project_name": identity.project_name,
            "container_name": identity.container_name,
            "instance_id": identity.instance_id,
            "attempt_id": identity.attempt_id,
            "runtime_spec_digest": identity.runtime_spec_digest,
            "state_allocation_id": identity.state_allocation_id,
            "image_id": identity.image_id,
            "network_names": list(identity.network_names),
        },
        "secret_path_environment_bindings": [
            {"name": value.name, "target": str(value.target)}
            for value in secret_environment
        ],
    }


def _authority_digest(
    authority: LaunchCompilationAuthority,
    secret_environment: tuple[SecretPathEnvironmentBinding, ...],
) -> str:
    canonical = json.dumps(
        _authority_projection(authority, secret_environment),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def compile_launch_snapshot(authority: LaunchCompilationAuthority) -> LaunchSnapshot:
    if type(authority) is not LaunchCompilationAuthority:
        raise DriverValidationError()
    authority.__post_init__()
    _validate_authority(authority)
    environment, secret_environment = _compiled_environment(authority)
    snapshot = LaunchSnapshot(
        identity=authority.identity,
        launch_authority_digest=_authority_digest(authority, secret_environment),
        argv=_expanded_command(authority),
        working_directory=str(authority.policies.working_directory),
        non_secret_environment=environment,
        read_only_mounts=tuple(
            ReadOnlyMount(material.source_path, policy.target)
            for material, policy in zip(
                authority.materials,
                authority.policies.material_mounts,
                strict=True,
            )
        ),
        state_mount=WritableStateMount(
            authority.state.source,
            authority.policies.state_mount.target,
            authority.state.state_allocation_id,
        ),
        secret_mounts=tuple(
            SecretMount(
                secret.source,
                policy.target,
                secret.reference_id,
                secret.version_id,
            )
            for secret, policy in zip(
                authority.secrets,
                authority.policies.secret_mounts,
                strict=True,
            )
        ),
        secret_path_environment_bindings=secret_environment,
        runtime_user=authority.policies.runtime_user,
        internal_ports=authority.policies.internal_ports,
        health_profile=authority.policies.health_profile,
        resource_limits=authority.policies.resource_limits,
    )
    return snapshot


def validate_launch_snapshot(
    snapshot: LaunchSnapshot,
    expected_authority: LaunchCompilationAuthority,
) -> None:
    if (
        type(snapshot) is not LaunchSnapshot
        or type(expected_authority) is not LaunchCompilationAuthority
    ):
        raise DriverValidationError()
    snapshot.__post_init__()
    expected = compile_launch_snapshot(expected_authority)
    if (
        snapshot.launch_authority_digest != expected.launch_authority_digest
        or snapshot != expected
    ):
        raise DriverPolicyError()


def _rendered_labels(snapshot: LaunchSnapshot) -> tuple[RenderedLabel, ...]:
    values = {
        "io.freqtrade.runtime.attempt-id": snapshot.identity.attempt_id,
        "io.freqtrade.runtime.container-name": snapshot.identity.container_name,
        "io.freqtrade.runtime.image-id": snapshot.identity.image_id,
        "io.freqtrade.runtime.instance-id": snapshot.identity.instance_id,
        "io.freqtrade.runtime.launch-authority-digest": snapshot.launch_authority_digest,
        "io.freqtrade.runtime.project-name": snapshot.identity.project_name,
        "io.freqtrade.runtime.runtime-spec-digest": snapshot.identity.runtime_spec_digest,
        "io.freqtrade.runtime.state-allocation-id": snapshot.identity.state_allocation_id,
    }
    return tuple(RenderedLabel(name, values[name]) for name in sorted(values))


def _expected_rendered(
    snapshot: LaunchSnapshot,
    authority: LaunchCompilationAuthority,
) -> RenderedContainerPolicy:
    material_mounts = tuple(
        RenderedMount(
            RenderedMountKind.MATERIAL,
            policy.role,
            mount.source,
            mount.target,
            True,
        )
        for policy, mount in zip(
            authority.policies.material_mounts,
            snapshot.read_only_mounts,
            strict=True,
        )
    )
    state_mount = RenderedMount(
        RenderedMountKind.STATE,
        authority.policies.state_mount.role,
        snapshot.state_mount.source,
        snapshot.state_mount.target,
        False,
    )
    secret_mounts = tuple(
        RenderedMount(
            RenderedMountKind.SECRET,
            policy.secret_class,
            mount.source,
            mount.target,
            True,
        )
        for policy, mount in zip(
            authority.policies.secret_mounts,
            snapshot.secret_mounts,
            strict=True,
        )
    )
    environment = tuple(
        RenderedEnvironmentEntry(value.name, value.value)
        for value in snapshot.non_secret_environment
    ) + tuple(
        RenderedEnvironmentEntry(value.name, str(value.target))
        for value in snapshot.secret_path_environment_bindings
    )
    return RenderedContainerPolicy(
        identity=snapshot.identity,
        image_id=snapshot.identity.image_id,
        argv=snapshot.argv,
        working_directory=PurePosixPath(snapshot.working_directory),
        environment=environment,
        mounts=(*material_mounts, state_mount, *secret_mounts),
        runtime_user=snapshot.runtime_user,
        internal_ports=snapshot.internal_ports,
        health_profile=snapshot.health_profile,
        resource_limits=snapshot.resource_limits,
        network_names=snapshot.identity.network_names,
        restart="no",
        network_mode=None,
        pid_mode=None,
        ipc_mode=None,
        privileged=False,
        devices=(),
        cap_add=(),
        cap_drop=("ALL",),
        security_options=("no-new-privileges:true",),
        read_only_root_filesystem=True,
        published_ports=(),
        labels=_rendered_labels(snapshot),
    )


def validate_rendered_snapshot(
    rendered: RenderedContainerPolicy,
    snapshot: LaunchSnapshot,
    expected_authority: LaunchCompilationAuthority,
) -> None:
    if (
        type(rendered) is not RenderedContainerPolicy
        or type(snapshot) is not LaunchSnapshot
        or type(expected_authority) is not LaunchCompilationAuthority
    ):
        raise DriverValidationError()
    rendered.__post_init__()
    validate_launch_snapshot(snapshot, expected_authority)
    if rendered != _expected_rendered(snapshot, expected_authority):
        raise DriverPolicyError()
