from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from unittest import mock

from tools.runtime_artifacts import MaterialSourceIdentity, VerifiedReadOnlyMaterial
from tools.runtime_driver import (
    DriverIdentity,
    DriverPolicyError,
    DriverValidationError,
    EnvironmentEntry,
    HealthProfile,
    LaunchSnapshot,
    ReadOnlyMount,
    ResourceLimits,
    RuntimeNetworkBinding,
    RuntimeUser,
    SecretMount,
    WritableStateMount,
)
from tools.runtime_launch_policy import (
    CommandToken,
    CommandTokenKind,
    EnvironmentBinding,
    EnvironmentBindingKind,
    ExecutionMode,
    ImageIdentitySource,
    MaterialKind,
    MaterialMountPolicy,
    NetworkIdentitySource,
    NetworkNameDerivation,
    NetworkRule,
    ResolvedLaunchPolicyBundle,
    SecretMountPolicy,
    StateMountPolicy,
    StateTarget,
)
from tools.runtime_secrets import (
    SecretSourceIdentity,
    VerifiedSecretMount,
    _SecretPathIdentity,
)
from tools.runtime_state import VerifiedStateMount
from tools.runtime_templates import CommittedTemplate


try:
    from tools.runtime_driver import SecretPathEnvironmentBinding
    from tools.runtime_snapshot import (
        LaunchCompilationAuthority,
        RenderedContainerPolicy,
        RenderedEnvironmentEntry,
        RenderedLabel,
        RenderedMount,
        RenderedMountKind,
        ResolvedAttemptAuthority,
        ResolvedSecretVersionAuthority,
        RuntimeSpecLaunchAuthority,
        compile_launch_snapshot,
        validate_launch_snapshot,
        validate_rendered_snapshot,
    )
except (ImportError, ModuleNotFoundError) as error:
    RUNTIME_SNAPSHOT_IMPORT_ERROR: ImportError | ModuleNotFoundError | None = error
else:
    RUNTIME_SNAPSHOT_IMPORT_ERROR = None


ROOT_COMMIT = "1" * 40
BACKEND_COMMIT = "2" * 40
FRONTEND_COMMIT = "3" * 40
STRATEGIES_COMMIT = "4" * 40
CONFIG_DIGEST = "5" * 64
STRATEGY_DIGEST = "6" * 64
SAFETY_DIGEST = "7" * 64
IMAGE_ID = f"sha256:{'8' * 64}"
INSTANCE_ID = "paper-probe-1"
ATTEMPT_ID = "attempt-1"
STATE_ALLOCATION_ID = "state-paper-probe-1"
TEMPLATE_ID = "freqtrade-paper-probe-v1"
TEMPLATE_REVISION_ID = "adapter-template-revision-1"
POLICY_DIGEST = "1a8fb0cefd2db6cc8a34f8041bd7d9bfcdea90f2622a3f9b356d21f52d0de266"
CATALOG_DIGEST = "afba9a1a05211e9136f6bfd934c5a700e4c0efcb234f9a5cb7479ec1dd2358ea"
CATALOG_BLOB_ID = "b" * 40
SECRET_IDENTITIES = (
    ("api-password-ref", "api-password-v1", "api_password"),
    ("jwt-secret-ref", "jwt-secret-v1", "jwt_secret"),
    ("ws-token-ref", "ws-token-v1", "ws_token"),
)
MATERIAL_IDENTITIES = (
    (
        "runtime_config",
        "ft_userdata/user_data/config.example.json",
        CONFIG_DIGEST,
    ),
    ("safety_policy", "ops/config/trading-safety.json", SAFETY_DIGEST),
    (
        "strategy",
        "ft_userdata/user_data/strategies/sample_strategy.py",
        STRATEGY_DIGEST,
    ),
)
HOST_ROOT = (
    Path("C:/runtime-snapshot-tests")
    if os.name == "nt"
    else Path("/runtime-snapshot-tests")
)


def _template_payload() -> dict[str, object]:
    return {
        "allowed_environments": ["paper"],
        "allowed_instance_kinds": ["freqtrade"],
        "allowed_owner_kinds": ["paper_probe"],
        "command_policy_id": "freqtrade-spot-paper-v1",
        "health_profile_id": "freqtrade-ping-v1",
        "image_policy_id": "freqtrade-reviewed-image-v1",
        "mount_policy_ids": [
            "runtime-config-ro-v1",
            "safety-policy-ro-v1",
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
        "template_id": TEMPLATE_ID,
    }


def _committed_template() -> CommittedTemplate:
    payload = _template_payload()
    canonical_json = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    return CommittedTemplate(
        payload=MappingProxyType(
            {
                key: tuple(value) if isinstance(value, list) else value
                for key, value in payload.items()
            }
        ),
        canonical_json=canonical_json,
        digest=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
        source_path="ops/adapter-templates/freqtrade-paper-probe-v1.json",
        source_commit=ROOT_COMMIT,
    )


def _policies(template: CommittedTemplate) -> ResolvedLaunchPolicyBundle:
    return ResolvedLaunchPolicyBundle(
        template_id=TEMPLATE_ID,
        template_digest=template.digest,
        source_commit=ROOT_COMMIT,
        catalog_source_path="ops/runtime-policies/launch-policy-catalog.json",
        catalog_blob_id=CATALOG_BLOB_ID,
        catalog_digest=CATALOG_DIGEST,
        policy_digest=POLICY_DIGEST,
        image_policy_id="freqtrade-reviewed-image-v1",
        image_identity_source=ImageIdentitySource.RESOLVED_ATTEMPT_SHA256,
        command_policy_id="freqtrade-spot-paper-v1",
        execution_mode=ExecutionMode.IMAGE_ENTRYPOINT_ARGS,
        entrypoint_argv=("python", "/usr/local/bin/freqtrade-entrypoint"),
        command_tokens=(
            CommandToken(CommandTokenKind.LITERAL, "trade"),
            CommandToken(CommandTokenKind.LITERAL, "--logfile"),
            CommandToken(CommandTokenKind.STATE_TARGET, "log_file"),
            CommandToken(CommandTokenKind.LITERAL, "--db-url"),
            CommandToken(CommandTokenKind.STATE_TARGET, "database_url"),
            CommandToken(CommandTokenKind.LITERAL, "--config"),
            CommandToken(CommandTokenKind.MOUNT_TARGET, "runtime_config"),
            CommandToken(CommandTokenKind.LITERAL, "--config"),
            CommandToken(CommandTokenKind.MOUNT_TARGET, "safety_policy"),
            CommandToken(CommandTokenKind.LITERAL, "--user-data-dir"),
            CommandToken(CommandTokenKind.STATE_TARGET, "user_data"),
            CommandToken(CommandTokenKind.LITERAL, "--strategy-path"),
            CommandToken(
                CommandTokenKind.LITERAL,
                "/freqtrade/user_data/strategies",
            ),
            CommandToken(CommandTokenKind.LITERAL, "--strategy"),
            CommandToken(CommandTokenKind.STRATEGY_CLASS_NAME, None),
        ),
        working_directory=PurePosixPath("/freqtrade"),
        environment_bindings=(
            EnvironmentBinding(
                "FT_API_PASSWORD_FILE",
                EnvironmentBindingKind.SECRET_MOUNT_TARGET,
                "api_password",
            ),
            EnvironmentBinding(
                "FT_JWT_SECRET_FILE",
                EnvironmentBindingKind.SECRET_MOUNT_TARGET,
                "jwt_secret",
            ),
            EnvironmentBinding(
                "FT_WS_TOKEN_FILE",
                EnvironmentBindingKind.SECRET_MOUNT_TARGET,
                "ws_token",
            ),
            EnvironmentBinding(
                "HOME",
                EnvironmentBindingKind.STATE_TARGET,
                "home",
            ),
        ),
        material_mounts=(
            MaterialMountPolicy(
                "runtime-config-ro-v1",
                "runtime_config",
                MaterialKind.RUNTIME_CONFIG,
                PurePosixPath("/freqtrade/config/runtime.json"),
            ),
            MaterialMountPolicy(
                "safety-policy-ro-v1",
                "safety_policy",
                MaterialKind.SAFETY_POLICY,
                PurePosixPath("/freqtrade/config/trading-safety.json"),
            ),
            MaterialMountPolicy(
                "strategy-ro-v1",
                "strategy",
                MaterialKind.STRATEGY,
                PurePosixPath("/freqtrade/user_data/strategies/strategy.py"),
            ),
        ),
        state_mount=StateMountPolicy(
            "managed-state-rw-v1",
            "state",
            PurePosixPath("/freqtrade/state"),
        ),
        secret_mounts=(
            SecretMountPolicy(
                "api-secrets-ro-v1",
                "api_password",
                PurePosixPath("/run/secrets/api_password"),
            ),
            SecretMountPolicy(
                "api-secrets-ro-v1",
                "jwt_secret",
                PurePosixPath("/run/secrets/jwt_secret_key"),
            ),
            SecretMountPolicy(
                "api-secrets-ro-v1",
                "ws_token",
                PurePosixPath("/run/secrets/ws_token"),
            ),
        ),
        state_layout_id="freqtrade-state-v1",
        state_targets=(
            StateTarget(
                "database_url",
                "sqlite:////freqtrade/state/data/trades.sqlite",
            ),
            StateTarget("home", "/freqtrade/state/home"),
            StateTarget("log_file", "/freqtrade/state/logs/freqtrade.log"),
            StateTarget("root", "/freqtrade/state"),
            StateTarget("user_data", "/freqtrade/state/data"),
        ),
        runtime_user=RuntimeUser(
            uid=12345,
            gid=12345,
            home=PurePosixPath("/freqtrade/state/home"),
        ),
        internal_ports=(8080,),
        health_profile=HealthProfile(
            profile_id="freqtrade-ping-v1",
            probe_argv=(
                "curl",
                "-fsS",
                "--max-time",
                "5",
                "http://127.0.0.1:8080/api/v1/ping",
            ),
            start_period_seconds=30,
            interval_seconds=30,
            timeout_seconds=5,
            retries=3,
        ),
        resource_profile_id="freqtrade-small-v1",
        resource_limits=ResourceLimits(
            cpu_millis=1000,
            memory_bytes=536870912,
            pids_limit=256,
        ),
        network_policy_id="isolated-public-market-data-v1",
        network_rules=(
            NetworkRule(
                role="access",
                identity_source=NetworkIdentitySource.INSTANCE_ID,
                derivation=NetworkNameDerivation.SHA256_PREFIX_V1,
                prefix="runtime-",
                digest_characters=24,
                suffix="-access",
                internal=False,
                requires_upstream_access=True,
                requires_platform_control=True,
            ),
        ),
    )


def _network_names() -> tuple[str, ...]:
    digest = hashlib.sha256(INSTANCE_ID.encode("utf-8")).hexdigest()[:24]
    return (f"runtime-{digest}-access",)


def _spec(template: CommittedTemplate) -> RuntimeSpecLaunchAuthority:
    payload_digest = "c" * 64
    return RuntimeSpecLaunchAuthority(
        runtime_spec_revision_id=f"runtime-spec-{payload_digest}",
        payload_digest=payload_digest,
        owner_kind="paper_probe",
        instance_kind="freqtrade",
        environment="paper",
        adapter_template_revision_id=f"template-{template.digest}",
        template_digest=template.digest,
        image_policy_id="freqtrade-reviewed-image-v1",
        command_policy_id="freqtrade-spot-paper-v1",
        mount_policy_ids=(
            "runtime-config-ro-v1",
            "safety-policy-ro-v1",
            "strategy-ro-v1",
            "managed-state-rw-v1",
            "api-secrets-ro-v1",
        ),
        network_policy_id="isolated-public-market-data-v1",
        health_profile_id="freqtrade-ping-v1",
        resource_profile_id="freqtrade-small-v1",
        state_layout_id="freqtrade-state-v1",
        state_allocation_id=STATE_ALLOCATION_ID,
        secret_reference_ids=tuple(item[0] for item in SECRET_IDENTITIES),
        config_blob_commit=ROOT_COMMIT,
        strategy_commit=ROOT_COMMIT,
        strategy_class_name="SampleStrategy",
        safety_policy_commit=ROOT_COMMIT,
        root_commit=ROOT_COMMIT,
        backend_commit=BACKEND_COMMIT,
        frontend_commit=FRONTEND_COMMIT,
        strategies_commit=STRATEGIES_COMMIT,
        config_blob_digest=CONFIG_DIGEST,
        strategy_digest=STRATEGY_DIGEST,
        safety_policy_digest=SAFETY_DIGEST,
    )


def _attempt(spec: RuntimeSpecLaunchAuthority) -> ResolvedAttemptAuthority:
    return ResolvedAttemptAuthority(
        attempt_id=ATTEMPT_ID,
        instance_id=INSTANCE_ID,
        runtime_spec_revision_id=spec.runtime_spec_revision_id,
        runtime_spec_payload_digest=spec.payload_digest,
        adapter_template_revision_id=spec.adapter_template_revision_id,
        state_allocation_id=STATE_ALLOCATION_ID,
        resolved_secret_versions=tuple(
            ResolvedSecretVersionAuthority(
                secret_reference_id=reference_id,
                version_id=version_id,
            )
            for reference_id, version_id, _ in SECRET_IDENTITIES
        ),
        image_id=IMAGE_ID,
        root_commit=ROOT_COMMIT,
        backend_commit=BACKEND_COMMIT,
        frontend_commit=FRONTEND_COMMIT,
        strategies_commit=STRATEGIES_COMMIT,
        project_identity="runtime-paper-probe-1",
        container_identity="runtime-paper-probe-1-worker",
    )


def _state() -> VerifiedStateMount:
    source = Path(os.path.abspath(HOST_ROOT / "state"))
    return VerifiedStateMount(
        attempt_id=ATTEMPT_ID,
        state_allocation_id=STATE_ALLOCATION_ID,
        instance_id=INSTANCE_ID,
        layout_id="freqtrade-state-v1",
        provider_id="managed-local-v1",
        generation=1,
        relative_path=f"ft_userdata/runtime/instances/{INSTANCE_ID}",
        source=source,
        runtime_uid=12345,
        durability="atomic-process-crash",
    )


def _material_source_identity() -> MaterialSourceIdentity:
    return MaterialSourceIdentity(
        device=1,
        inode=2,
        mode=0o100400,
        size=64,
        modified_ns=3,
        changed_ns=4,
        link_count=1,
        owner_uid=12345,
        owner_gid=12345,
        file_attributes=None,
        reparse_tag=None,
    )


def _materials() -> tuple[VerifiedReadOnlyMaterial, ...]:
    return tuple(
        VerifiedReadOnlyMaterial(
            role=role,
            attempt_id=ATTEMPT_ID,
            provider_id="committed-paper-probe-material-v1",
            root_commit=ROOT_COMMIT,
            repository_relative_path=relative_path,
            source_path=HOST_ROOT / "materials" / f"{role}.verified",
            blob_sha256=digest,
            source_identity=_material_source_identity(),
            strategy_class_name=("SampleStrategy" if role == "strategy" else None),
        )
        for role, relative_path, digest in MATERIAL_IDENTITIES
    )


def _secret_source_identity() -> SecretSourceIdentity:
    path_identity = _SecretPathIdentity(
        device=1,
        inode=2,
        mode=0o100400,
        link_count=1,
        size=32,
        modified_ns=3,
        changed_ns=4,
        owner_uid=12345,
        owner_gid=12345,
        file_attributes=None,
    )
    return SecretSourceIdentity(
        root=path_identity,
        reference_directory=path_identity,
        version_directory=path_identity,
        value_file=path_identity,
    )


def _secrets() -> tuple[VerifiedSecretMount, ...]:
    return tuple(
        VerifiedSecretMount(
            attempt_id=ATTEMPT_ID,
            provider_id="local-file-secret-v1",
            reference_id=reference_id,
            version_id=version_id,
            secret_class=secret_class,
            source=HOST_ROOT / "secrets" / reference_id / version_id / "value",
            source_identity=_secret_source_identity(),
        )
        for reference_id, version_id, secret_class in SECRET_IDENTITIES
    )


def _identity(spec: RuntimeSpecLaunchAuthority) -> DriverIdentity:
    return DriverIdentity(
        project_name="runtime-paper-probe-1",
        container_name="runtime-paper-probe-1-worker",
        instance_id=INSTANCE_ID,
        attempt_id=ATTEMPT_ID,
        runtime_spec_digest=spec.payload_digest,
        state_allocation_id=STATE_ALLOCATION_ID,
        image_id=IMAGE_ID,
        network_names=_network_names(),
    )


def valid_authority() -> LaunchCompilationAuthority:
    template = _committed_template()
    spec = _spec(template)
    return LaunchCompilationAuthority(
        spec=spec,
        attempt=_attempt(spec),
        template=template,
        policies=_policies(template),
        state=_state(),
        secrets=_secrets(),
        materials=_materials(),
        identity=_identity(spec),
    )


def _rendered_labels(snapshot: LaunchSnapshot) -> tuple[RenderedLabel, ...]:
    values = {
        "io.freqtrade.runtime.attempt-id": snapshot.identity.attempt_id,
        "io.freqtrade.runtime.container-name": snapshot.identity.container_name,
        "io.freqtrade.runtime.image-id": snapshot.identity.image_id,
        "io.freqtrade.runtime.instance-id": snapshot.identity.instance_id,
        "io.freqtrade.runtime.launch-authority-digest": (
            snapshot.launch_authority_digest
        ),
        "io.freqtrade.runtime.project-name": snapshot.identity.project_name,
        "io.freqtrade.runtime.runtime-spec-digest": (
            snapshot.identity.runtime_spec_digest
        ),
        "io.freqtrade.runtime.state-allocation-id": (
            snapshot.identity.state_allocation_id
        ),
    }
    return tuple(RenderedLabel(name, values[name]) for name in sorted(values))


def valid_rendered(
    snapshot: LaunchSnapshot,
    authority: LaunchCompilationAuthority,
) -> RenderedContainerPolicy:
    material_mounts = tuple(
        RenderedMount(
            kind=RenderedMountKind.MATERIAL,
            role=policy.role,
            source=mount.source,
            target=mount.target,
            read_only=True,
        )
        for policy, mount in zip(
            authority.policies.material_mounts,
            snapshot.read_only_mounts,
            strict=True,
        )
    )
    state_mount = RenderedMount(
        kind=RenderedMountKind.STATE,
        role=authority.policies.state_mount.role,
        source=snapshot.state_mount.source,
        target=snapshot.state_mount.target,
        read_only=False,
    )
    secret_mounts = tuple(
        RenderedMount(
            kind=RenderedMountKind.SECRET,
            role=policy.secret_class,
            source=mount.source,
            target=mount.target,
            read_only=True,
        )
        for policy, mount in zip(
            authority.policies.secret_mounts,
            snapshot.secret_mounts,
            strict=True,
        )
    )
    environment = tuple(
        RenderedEnvironmentEntry(entry.name, entry.value)
        for entry in snapshot.non_secret_environment
    ) + tuple(
        RenderedEnvironmentEntry(binding.name, str(binding.target))
        for binding in snapshot.secret_path_environment
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


class RuntimeSnapshotAvailabilityTests(unittest.TestCase):
    def test_runtime_snapshot_module_and_contract_exist(self) -> None:
        self.assertIsNone(RUNTIME_SNAPSHOT_IMPORT_ERROR)

    def test_import_succeeds_under_python_s(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import tools.runtime_snapshot; print('ok')",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "ok\n")


@unittest.skipIf(
    RUNTIME_SNAPSHOT_IMPORT_ERROR is not None,
    "runtime_snapshot contract is missing",
)
class RuntimeSnapshotCompilerTests(unittest.TestCase):
    def test_compiles_exact_deterministic_snapshot_without_model_validate(
        self,
    ) -> None:
        authority = valid_authority()
        with mock.patch.object(
            LaunchSnapshot,
            "model_validate",
            wraps=LaunchSnapshot.model_validate,
        ) as mapping_guard:
            first = compile_launch_snapshot(authority)
            second = compile_launch_snapshot(authority)
        mapping_guard.assert_not_called()

        self.assertEqual(first, second)
        self.assertRegex(first.launch_authority_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(first.identity, authority.identity)
        self.assertEqual(
            first.argv,
            (
                "python",
                "/usr/local/bin/freqtrade-entrypoint",
                "trade",
                "--logfile",
                "/freqtrade/state/logs/freqtrade.log",
                "--db-url",
                "sqlite:////freqtrade/state/data/trades.sqlite",
                "--config",
                "/freqtrade/config/runtime.json",
                "--config",
                "/freqtrade/config/trading-safety.json",
                "--user-data-dir",
                "/freqtrade/state/data",
                "--strategy-path",
                "/freqtrade/user_data/strategies",
                "--strategy",
                "SampleStrategy",
            ),
        )
        self.assertEqual(first.working_directory, "/freqtrade")
        self.assertEqual(
            tuple((entry.name, entry.value) for entry in first.non_secret_environment),
            (("HOME", "/freqtrade/state/home"),),
        )
        self.assertEqual(
            tuple(
                (binding.name, str(binding.target))
                for binding in first.secret_path_environment
            ),
            (
                ("FT_API_PASSWORD_FILE", "/run/secrets/api_password"),
                ("FT_JWT_SECRET_FILE", "/run/secrets/jwt_secret_key"),
                ("FT_WS_TOKEN_FILE", "/run/secrets/ws_token"),
            ),
        )
        self.assertTrue(
            all(
                isinstance(binding, SecretPathEnvironmentBinding)
                for binding in first.secret_path_environment
            )
        )
        self.assertEqual(
            tuple((mount.source, mount.target) for mount in first.read_only_mounts),
            tuple(
                (material.source_path, policy.target)
                for material, policy in zip(
                    authority.materials,
                    authority.policies.material_mounts,
                    strict=True,
                )
            ),
        )
        self.assertEqual(first.state_mount.source, authority.state.source)
        self.assertEqual(
            first.state_mount.target,
            authority.policies.state_mount.target,
        )
        self.assertEqual(
            tuple(
                (
                    mount.source,
                    mount.target,
                    mount.secret_reference_id,
                    mount.version,
                )
                for mount in first.secret_mounts
            ),
            tuple(
                (
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
        )
        self.assertEqual(first.runtime_user, authority.policies.runtime_user)
        self.assertEqual(first.internal_ports, (8080,))
        self.assertEqual(first.health_profile, authority.policies.health_profile)
        self.assertEqual(first.resource_limits, authority.policies.resource_limits)
        self.assertEqual(len(first.network_bindings), 1)
        binding = first.network_bindings[0]
        self.assertIsInstance(binding, RuntimeNetworkBinding)
        self.assertEqual(binding.role, "access")
        self.assertEqual(binding.network_name, first.identity.network_names[0])
        alias_digest = hashlib.sha256(
            f"{INSTANCE_ID}\0{ATTEMPT_ID}".encode("utf-8")
        ).hexdigest()
        self.assertEqual(binding.runtime_alias, f"runtime-{alias_digest[:24]}")
        self.assertRegex(binding.policy_digest, r"^[0-9a-f]{64}$")
        self.assertFalse(binding.internal)
        self.assertTrue(binding.requires_upstream_access)
        self.assertTrue(binding.requires_platform_control)

    def test_network_name_is_instance_stable_and_alias_is_attempt_unique(self) -> None:
        first_authority = valid_authority()
        first = compile_launch_snapshot(first_authority)
        attempt_id = "attempt-2"
        second_authority = dataclasses.replace(
            first_authority,
            attempt=dataclasses.replace(
                first_authority.attempt,
                attempt_id=attempt_id,
                container_identity="runtime-paper-probe-1-worker-attempt-2",
            ),
            state=dataclasses.replace(first_authority.state, attempt_id=attempt_id),
            materials=tuple(
                dataclasses.replace(material, attempt_id=attempt_id)
                for material in first_authority.materials
            ),
            secrets=tuple(
                dataclasses.replace(secret, attempt_id=attempt_id)
                for secret in first_authority.secrets
            ),
            identity=dataclasses.replace(
                first_authority.identity,
                attempt_id=attempt_id,
                container_name="runtime-paper-probe-1-worker-attempt-2",
            ),
        )
        second = compile_launch_snapshot(second_authority)

        self.assertEqual(
            first.network_bindings[0].network_name,
            second.network_bindings[0].network_name,
        )
        self.assertNotEqual(
            first.network_bindings[0].runtime_alias,
            second.network_bindings[0].runtime_alias,
        )
        self.assertEqual(
            first.network_bindings[0].policy_digest,
            second.network_bindings[0].policy_digest,
        )
        self.assertNotEqual(
            first.launch_authority_digest,
            second.launch_authority_digest,
        )

    def test_network_bindings_support_role_and_name_orders_that_differ(self) -> None:
        from tools.runtime_snapshot import (
            _derived_network_bindings,
            _derived_network_names,
        )

        authority = valid_authority()
        access = dataclasses.replace(
            authority.policies.network_rules[0],
            prefix="zzz-",
        )
        private = NetworkRule(
            role="private",
            identity_source=NetworkIdentitySource.INSTANCE_ID,
            derivation=NetworkNameDerivation.SHA256_PREFIX_V1,
            prefix="aaa-",
            digest_characters=24,
            suffix="-private",
            internal=True,
            requires_upstream_access=False,
            requires_platform_control=False,
        )
        digest = hashlib.sha256(INSTANCE_ID.encode("utf-8")).hexdigest()[:24]
        authority = dataclasses.replace(
            authority,
            policies=dataclasses.replace(
                authority.policies,
                network_rules=(access, private),
            ),
            identity=dataclasses.replace(
                authority.identity,
                network_names=(f"aaa-{digest}-private", f"zzz-{digest}-access"),
            ),
        )

        bindings = _derived_network_bindings(authority)

        self.assertEqual(
            tuple(binding.role for binding in bindings),
            ("access", "private"),
        )
        self.assertEqual(
            _derived_network_names(authority),
            (f"aaa-{digest}-private", f"zzz-{digest}-access"),
        )

    def test_launch_authority_digest_binds_compiled_network_alias(self) -> None:
        authority = valid_authority()
        original = compile_launch_snapshot(authority)
        with mock.patch(
            "tools.runtime_snapshot._runtime_alias",
            return_value="runtime-different-alias",
        ):
            changed = compile_launch_snapshot(authority)

        self.assertNotEqual(
            original.network_bindings[0].runtime_alias,
            changed.network_bindings[0].runtime_alias,
        )
        self.assertNotEqual(
            original.launch_authority_digest,
            changed.launch_authority_digest,
        )

    def test_compilation_and_validation_perform_no_io(self) -> None:
        authority = valid_authority()
        snapshot = compile_launch_snapshot(authority)
        rendered = valid_rendered(snapshot, authority)
        forbidden = AssertionError("pure runtime_snapshot operation attempted I/O")
        with (
            mock.patch("builtins.open", side_effect=forbidden),
            mock.patch("os.getenv", side_effect=forbidden),
            mock.patch("os.stat", side_effect=forbidden),
            mock.patch("os.lstat", side_effect=forbidden),
            mock.patch("pathlib.Path.open", side_effect=forbidden),
            mock.patch("pathlib.Path.read_bytes", side_effect=forbidden),
            mock.patch("pathlib.Path.read_text", side_effect=forbidden),
            mock.patch("subprocess.Popen", side_effect=forbidden),
            mock.patch("subprocess.run", side_effect=forbidden),
            mock.patch("socket.socket", side_effect=forbidden),
            mock.patch("socket.create_connection", side_effect=forbidden),
            mock.patch("time.time", side_effect=forbidden),
        ):
            self.assertEqual(compile_launch_snapshot(authority), snapshot)
            validate_launch_snapshot(snapshot, authority)
            validate_rendered_snapshot(rendered, snapshot, authority)

    def test_launch_validator_recompiles_instead_of_trusting_the_digest(self) -> None:
        authority = valid_authority()
        snapshot = compile_launch_snapshot(authority)
        changed = dataclasses.replace(
            snapshot,
            argv=(*snapshot.argv[:-1], "DifferentStrategy"),
        )
        self.assertEqual(
            changed.launch_authority_digest,
            snapshot.launch_authority_digest,
        )

        with self.assertRaisesRegex(
            DriverPolicyError,
            "^driver_policy_error$",
        ):
            validate_launch_snapshot(changed, authority)

        changed_binding = dataclasses.replace(
            snapshot.network_bindings[0],
            runtime_alias="runtime-attacker",
        )
        with self.assertRaisesRegex(
            DriverPolicyError,
            "^driver_policy_error$",
        ):
            validate_launch_snapshot(
                dataclasses.replace(snapshot, network_bindings=(changed_binding,)),
                authority,
            )

    def test_rejects_legacy_spec_without_strategy_class(self) -> None:
        authority = valid_authority()
        authority = dataclasses.replace(
            authority,
            spec=dataclasses.replace(authority.spec, strategy_class_name=None),
        )
        with self.assertRaisesRegex(
            DriverPolicyError,
            "^driver_policy_error$",
        ):
            compile_launch_snapshot(authority)

    def test_rejects_mutated_state_provenance_scalars_without_io(self) -> None:
        for field_name, value in (
            ("generation", True),
            ("runtime_uid", True),
            ("durability", "arbitrary"),
            ("relative_path", "ft_userdata/runtime/instances/caller"),
        ):
            authority = valid_authority()
            object.__setattr__(authority.state, field_name, value)
            with (
                self.subTest(field=field_name),
                mock.patch(
                    "os.path.abspath",
                    side_effect=AssertionError("compiler attempted path resolution"),
                ),
                self.assertRaisesRegex(
                    DriverValidationError,
                    "^driver_validation_error$",
                ),
            ):
                compile_launch_snapshot(authority)

    def test_rejects_resolved_policy_drift_after_loader_validation(self) -> None:
        def replace_policy(
            authority: LaunchCompilationAuthority,
            **changes: object,
        ) -> LaunchCompilationAuthority:
            return dataclasses.replace(
                authority,
                policies=dataclasses.replace(authority.policies, **changes),
            )

        def replace_first_secret(
            authority: LaunchCompilationAuthority,
            **changes: object,
        ) -> LaunchCompilationAuthority:
            mounts = authority.policies.secret_mounts
            return replace_policy(
                authority,
                secret_mounts=(dataclasses.replace(mounts[0], **changes), *mounts[1:]),
            )

        mutations = (
            (
                "unapproved secret environment name",
                lambda a: replace_policy(
                    a,
                    environment_bindings=(
                        dataclasses.replace(
                            a.policies.environment_bindings[0],
                            name="CALLER_FILE",
                        ),
                        *a.policies.environment_bindings[1:],
                    ),
                ),
            ),
            (
                "shell health probe",
                lambda a: replace_policy(
                    a,
                    health_profile=dataclasses.replace(
                        a.policies.health_profile,
                        probe_argv=("sh", "-c", "caller command"),
                    ),
                ),
            ),
            (
                "health start period above platform limit",
                lambda a: replace_policy(
                    a,
                    health_profile=dataclasses.replace(
                        a.policies.health_profile,
                        start_period_seconds=301,
                    ),
                ),
            ),
            (
                "cpu above platform limit",
                lambda a: replace_policy(
                    a,
                    resource_limits=dataclasses.replace(
                        a.policies.resource_limits,
                        cpu_millis=8001,
                    ),
                ),
            ),
            (
                "state layout outside managed root",
                lambda a: replace_policy(
                    a,
                    state_targets=(
                        dataclasses.replace(
                            a.policies.state_targets[0],
                            value="sqlite:////tmp/trades.sqlite",
                        ),
                        *a.policies.state_targets[1:],
                    ),
                ),
            ),
            (
                "secret target outside closed root",
                lambda a: replace_first_secret(
                    a,
                    target=PurePosixPath("/tmp/api_password"),
                ),
            ),
            (
                "material role policy mismatch",
                lambda a: replace_policy(
                    a,
                    material_mounts=(
                        dataclasses.replace(
                            a.policies.material_mounts[0],
                            policy_id="safety-policy-ro-v1",
                        ),
                        *a.policies.material_mounts[1:],
                    ),
                ),
            ),
        )

        for name, mutate in mutations:
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    DriverPolicyError,
                    "^driver_policy_error$",
                ),
            ):
                compile_launch_snapshot(mutate(valid_authority()))

    def test_rejects_string_subclasses_in_compilation_authority(self) -> None:
        class AlwaysEqualStr(str):
            __hash__ = str.__hash__

            def __eq__(self, _other: object) -> bool:
                return True

            def __ne__(self, _other: object) -> bool:
                return False

        authority = valid_authority()
        mutations = (
            lambda: dataclasses.replace(
                authority,
                spec=dataclasses.replace(
                    authority.spec,
                    owner_kind=AlwaysEqualStr("workspace_worker"),
                ),
            ),
            lambda: dataclasses.replace(
                authority,
                policies=dataclasses.replace(
                    authority.policies,
                    source_commit=AlwaysEqualStr("d" * 40),
                ),
            ),
        )

        for mutate in mutations:
            with self.assertRaises((DriverValidationError, ValueError)):
                compile_launch_snapshot(mutate())

    def test_rejects_incomplete_or_drifted_template_schema_with_fixed_error(
        self,
    ) -> None:
        def with_template_payload(payload: dict[str, object]):
            canonical = (
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            authority = valid_authority()
            template = dataclasses.replace(
                authority.template,
                payload=MappingProxyType(
                    {
                        key: tuple(value) if isinstance(value, list) else value
                        for key, value in payload.items()
                    }
                ),
                canonical_json=canonical,
                digest=digest,
            )
            spec = dataclasses.replace(
                authority.spec,
                adapter_template_revision_id=f"template-{digest}",
                template_digest=digest,
            )
            attempt = dataclasses.replace(
                authority.attempt,
                adapter_template_revision_id=spec.adapter_template_revision_id,
            )
            policies = dataclasses.replace(authority.policies, template_digest=digest)
            return dataclasses.replace(
                authority,
                spec=spec,
                attempt=attempt,
                template=template,
                policies=policies,
            )

        missing = _template_payload()
        del missing["image_policy_id"]
        extra = {**_template_payload(), "caller_field": "value"}
        wrong_schema = {**_template_payload(), "schema_version": 2}
        drifted_identity = {**_template_payload(), "semantic_version": "2.0.0"}

        for payload in (missing, extra, wrong_schema, drifted_identity):
            with self.assertRaisesRegex(
                DriverPolicyError,
                "^driver_policy_error$",
            ):
                compile_launch_snapshot(with_template_payload(payload))

    def test_rejects_cross_object_correlation_mutations(self) -> None:
        def replace_spec(authority: LaunchCompilationAuthority, **changes: object):
            return dataclasses.replace(
                authority,
                spec=dataclasses.replace(authority.spec, **changes),
            )

        def replace_attempt(
            authority: LaunchCompilationAuthority,
            **changes: object,
        ):
            return dataclasses.replace(
                authority,
                attempt=dataclasses.replace(authority.attempt, **changes),
            )

        mutations = (
            (
                "identity payload digest",
                lambda a: dataclasses.replace(
                    a,
                    identity=dataclasses.replace(
                        a.identity,
                        runtime_spec_digest="d" * 64,
                    ),
                ),
            ),
            (
                "attempt payload digest",
                lambda a: replace_attempt(a, runtime_spec_payload_digest="d" * 64),
            ),
            (
                "attempt spec revision",
                lambda a: replace_attempt(a, runtime_spec_revision_id="other-spec"),
            ),
            (
                "attempt instance",
                lambda a: replace_attempt(a, instance_id="other-instance"),
            ),
            (
                "attempt template revision",
                lambda a: replace_attempt(
                    a,
                    adapter_template_revision_id="other-template-revision",
                ),
            ),
            (
                "attempt state allocation",
                lambda a: replace_attempt(a, state_allocation_id="other-state"),
            ),
            (
                "attempt image",
                lambda a: replace_attempt(a, image_id=f"sha256:{'d' * 64}"),
            ),
            (
                "attempt project",
                lambda a: replace_attempt(a, project_identity="other-project"),
            ),
            (
                "attempt container",
                lambda a: replace_attempt(a, container_identity="other-container"),
            ),
            (
                "spec template digest",
                lambda a: replace_spec(a, template_digest="d" * 64),
            ),
            (
                "spec image policy",
                lambda a: replace_spec(a, image_policy_id="other-image-policy"),
            ),
            (
                "spec command policy",
                lambda a: replace_spec(a, command_policy_id="other-command-policy"),
            ),
            (
                "spec mount policies",
                lambda a: replace_spec(
                    a,
                    mount_policy_ids=(*a.spec.mount_policy_ids[:-1], "other-mount"),
                ),
            ),
            (
                "spec network policy",
                lambda a: replace_spec(a, network_policy_id="other-network"),
            ),
            (
                "spec health profile",
                lambda a: replace_spec(a, health_profile_id="other-health"),
            ),
            (
                "spec resource profile",
                lambda a: replace_spec(a, resource_profile_id="other-resource"),
            ),
            (
                "spec state layout",
                lambda a: replace_spec(a, state_layout_id="other-layout"),
            ),
            (
                "spec state allocation",
                lambda a: replace_spec(a, state_allocation_id="other-state"),
            ),
            (
                "spec config commit",
                lambda a: replace_spec(a, config_blob_commit="d" * 40),
            ),
            (
                "spec strategy commit",
                lambda a: replace_spec(a, strategy_commit="d" * 40),
            ),
            (
                "spec safety commit",
                lambda a: replace_spec(a, safety_policy_commit="d" * 40),
            ),
            (
                "spec config digest",
                lambda a: replace_spec(a, config_blob_digest="d" * 64),
            ),
            (
                "spec strategy digest",
                lambda a: replace_spec(a, strategy_digest="d" * 64),
            ),
            (
                "spec safety digest",
                lambda a: replace_spec(a, safety_policy_digest="d" * 64),
            ),
            (
                "spec secret references",
                lambda a: replace_spec(
                    a,
                    secret_reference_ids=(
                        *a.spec.secret_reference_ids[:-1],
                        "other-ref",
                    ),
                ),
            ),
            (
                "spec root commit",
                lambda a: replace_spec(a, root_commit="d" * 40),
            ),
            (
                "spec backend commit",
                lambda a: replace_spec(a, backend_commit="d" * 40),
            ),
            (
                "spec frontend commit",
                lambda a: replace_spec(a, frontend_commit="d" * 40),
            ),
            (
                "spec strategies commit",
                lambda a: replace_spec(a, strategies_commit="d" * 40),
            ),
            (
                "template source commit",
                lambda a: dataclasses.replace(
                    a,
                    template=dataclasses.replace(a.template, source_commit="d" * 40),
                ),
            ),
            (
                "template payload owner",
                lambda a: dataclasses.replace(
                    a,
                    template=dataclasses.replace(
                        a.template,
                        payload=MappingProxyType(
                            {
                                **dict(a.template.payload),
                                "allowed_owner_kinds": ["workspace_worker"],
                            }
                        ),
                    ),
                ),
            ),
            (
                "template source path",
                lambda a: dataclasses.replace(
                    a,
                    template=dataclasses.replace(
                        a.template,
                        source_path="ops/adapter-templates/other.json",
                    ),
                ),
            ),
            (
                "policy source commit",
                lambda a: dataclasses.replace(
                    a,
                    policies=dataclasses.replace(a.policies, source_commit="d" * 40),
                ),
            ),
            (
                "state attempt",
                lambda a: dataclasses.replace(
                    a,
                    state=dataclasses.replace(a.state, attempt_id="other-attempt"),
                ),
            ),
            (
                "state instance",
                lambda a: dataclasses.replace(
                    a,
                    state=dataclasses.replace(
                        a.state,
                        instance_id="other-instance",
                        relative_path=("ft_userdata/runtime/instances/other-instance"),
                    ),
                ),
            ),
            (
                "state allocation lease",
                lambda a: dataclasses.replace(
                    a,
                    state=dataclasses.replace(
                        a.state,
                        state_allocation_id="other-state",
                    ),
                ),
            ),
            (
                "state runtime uid",
                lambda a: dataclasses.replace(
                    a,
                    state=dataclasses.replace(a.state, runtime_uid=54321),
                ),
            ),
            (
                "material attempt",
                lambda a: dataclasses.replace(
                    a,
                    materials=(
                        dataclasses.replace(
                            a.materials[0],
                            attempt_id="other-attempt",
                        ),
                        *a.materials[1:],
                    ),
                ),
            ),
            (
                "material root commit",
                lambda a: dataclasses.replace(
                    a,
                    materials=(
                        dataclasses.replace(a.materials[0], root_commit="d" * 40),
                        *a.materials[1:],
                    ),
                ),
            ),
            (
                "material digest",
                lambda a: dataclasses.replace(
                    a,
                    materials=(
                        dataclasses.replace(a.materials[0], blob_sha256="d" * 64),
                        *a.materials[1:],
                    ),
                ),
            ),
            (
                "material role",
                lambda a: dataclasses.replace(
                    a,
                    materials=(
                        dataclasses.replace(a.materials[0], role="other_role"),
                        *a.materials[1:],
                    ),
                ),
            ),
            (
                "material provider",
                lambda a: dataclasses.replace(
                    a,
                    materials=(
                        dataclasses.replace(
                            a.materials[0],
                            provider_id="other-provider",
                        ),
                        *a.materials[1:],
                    ),
                ),
            ),
            (
                "material repository path",
                lambda a: dataclasses.replace(
                    a,
                    materials=(
                        dataclasses.replace(
                            a.materials[0],
                            repository_relative_path="other/config.json",
                        ),
                        *a.materials[1:],
                    ),
                ),
            ),
            (
                "material missing",
                lambda a: dataclasses.replace(a, materials=a.materials[:-1]),
            ),
            (
                "material order",
                lambda a: dataclasses.replace(
                    a,
                    materials=tuple(reversed(a.materials)),
                ),
            ),
            (
                "secret attempt",
                lambda a: dataclasses.replace(
                    a,
                    secrets=(
                        dataclasses.replace(a.secrets[0], attempt_id="other-attempt"),
                        *a.secrets[1:],
                    ),
                ),
            ),
            (
                "secret version",
                lambda a: dataclasses.replace(
                    a,
                    secrets=(
                        dataclasses.replace(a.secrets[0], version_id="other-version"),
                        *a.secrets[1:],
                    ),
                ),
            ),
            (
                "secret reference",
                lambda a: dataclasses.replace(
                    a,
                    secrets=(
                        dataclasses.replace(a.secrets[0], reference_id="other-ref"),
                        *a.secrets[1:],
                    ),
                ),
            ),
            (
                "secret class",
                lambda a: dataclasses.replace(
                    a,
                    secrets=(
                        dataclasses.replace(a.secrets[0], secret_class="other_class"),
                        *a.secrets[1:],
                    ),
                ),
            ),
            (
                "secret missing",
                lambda a: dataclasses.replace(a, secrets=a.secrets[:-1]),
            ),
            (
                "secret order",
                lambda a: dataclasses.replace(a, secrets=tuple(reversed(a.secrets))),
            ),
            (
                "attempt secret versions",
                lambda a: replace_attempt(
                    a,
                    resolved_secret_versions=(
                        dataclasses.replace(
                            a.attempt.resolved_secret_versions[0],
                            version_id="other-version",
                        ),
                        *a.attempt.resolved_secret_versions[1:],
                    ),
                ),
            ),
            (
                "attempt secret order",
                lambda a: replace_attempt(
                    a,
                    resolved_secret_versions=tuple(
                        reversed(a.attempt.resolved_secret_versions)
                    ),
                ),
            ),
            (
                "identity network",
                lambda a: dataclasses.replace(
                    a,
                    identity=dataclasses.replace(
                        a.identity,
                        network_names=("caller-network",),
                    ),
                ),
            ),
        )

        for name, mutate in mutations:
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    DriverPolicyError,
                    "^driver_policy_error$",
                ),
            ):
                compile_launch_snapshot(mutate(valid_authority()))


@unittest.skipIf(
    RUNTIME_SNAPSHOT_IMPORT_ERROR is not None,
    "runtime_snapshot contract is missing",
)
class RuntimeSnapshotIngressBoundaryTests(unittest.TestCase):
    def test_rejects_mapping_ingress_without_snapshot_model_validation(self) -> None:
        authority = valid_authority()
        snapshot = compile_launch_snapshot(authority)
        rendered = valid_rendered(snapshot, authority)
        boundaries = (
            ("compile authority", lambda: compile_launch_snapshot({"spec": {}})),
            (
                "validate snapshot",
                lambda: validate_launch_snapshot({"identity": {}}, authority),
            ),
            (
                "validate launch authority",
                lambda: validate_launch_snapshot(snapshot, {"spec": {}}),
            ),
            (
                "validate rendered",
                lambda: validate_rendered_snapshot({}, snapshot, authority),
            ),
            (
                "validate rendered snapshot",
                lambda: validate_rendered_snapshot(rendered, {}, authority),
            ),
            (
                "validate rendered authority",
                lambda: validate_rendered_snapshot(rendered, snapshot, {}),
            ),
        )
        for name, boundary in boundaries:
            with (
                self.subTest(name=name),
                mock.patch.object(
                    LaunchSnapshot,
                    "model_validate",
                    wraps=LaunchSnapshot.model_validate,
                ) as mapping_guard,
                self.assertRaisesRegex(
                    DriverValidationError,
                    "^driver_validation_error$",
                ),
            ):
                boundary()
            mapping_guard.assert_not_called()

    def test_authority_constructor_rejects_nested_mapping_ingress(self) -> None:
        authority = valid_authority()
        nested_fields = (
            "spec",
            "attempt",
            "template",
            "policies",
            "state",
            "secrets",
            "materials",
            "identity",
        )
        for field_name in nested_fields:
            invalid_value: object = () if field_name in {"secrets", "materials"} else {}
            if field_name in {"secrets", "materials"}:
                invalid_value = ({"source": "caller"},)
            with (
                self.subTest(field=field_name),
                self.assertRaisesRegex(
                    DriverValidationError,
                    "^driver_validation_error$",
                ),
            ):
                dataclasses.replace(authority, **{field_name: invalid_value})

    def test_rejects_mutable_or_custom_committed_template_payload(self) -> None:
        class CallerMapping(dict[str, object]):
            pass

        authority = valid_authority()
        for payload in (
            dict(authority.template.payload),
            CallerMapping(authority.template.payload),
            MappingProxyType(
                {
                    **dict(authority.template.payload),
                    "secret_classes": ["api_password", "jwt_secret", "ws_token"],
                }
            ),
        ):
            with (
                self.subTest(payload_type=type(payload).__name__),
                self.assertRaisesRegex(
                    DriverPolicyError,
                    "^driver_policy_error$",
                ),
            ):
                compile_launch_snapshot(
                    dataclasses.replace(
                        authority,
                        template=dataclasses.replace(
                            authority.template, payload=payload
                        ),
                    )
                )

    def test_rejects_subclasses_at_exact_type_ingress(self) -> None:
        class AuthoritySubclass(LaunchCompilationAuthority):
            pass

        class SnapshotSubclass(LaunchSnapshot):
            pass

        class RenderedSubclass(RenderedContainerPolicy):
            pass

        authority = valid_authority()
        snapshot = compile_launch_snapshot(authority)
        rendered = valid_rendered(snapshot, authority)
        authority_subclass = AuthoritySubclass(
            **{
                field.name: getattr(authority, field.name)
                for field in dataclasses.fields(authority)
            }
        )
        snapshot_subclass = SnapshotSubclass(
            **{
                field.name: getattr(snapshot, field.name)
                for field in dataclasses.fields(snapshot)
            }
        )
        rendered_subclass = RenderedSubclass(
            **{
                field.name: getattr(rendered, field.name)
                for field in dataclasses.fields(rendered)
            }
        )
        boundaries = (
            lambda: compile_launch_snapshot(authority_subclass),
            lambda: validate_launch_snapshot(snapshot_subclass, authority),
            lambda: validate_launch_snapshot(snapshot, authority_subclass),
            lambda: validate_rendered_snapshot(rendered_subclass, snapshot, authority),
        )
        for boundary in boundaries:
            with self.assertRaisesRegex(
                DriverValidationError,
                "^driver_validation_error$",
            ):
                boundary()

    def test_rejects_security_critical_nested_dto_subclasses(self) -> None:
        class AlwaysEqualMixin:
            def __eq__(self, _other: object) -> bool:
                return True

        class IdentitySubclass(AlwaysEqualMixin, DriverIdentity):
            pass

        class EnvironmentSubclass(AlwaysEqualMixin, EnvironmentEntry):
            pass

        class ReadOnlyMountSubclass(AlwaysEqualMixin, ReadOnlyMount):
            pass

        class StateMountSubclass(AlwaysEqualMixin, WritableStateMount):
            pass

        class SecretMountSubclass(AlwaysEqualMixin, SecretMount):
            pass

        class SecretBindingSubclass(AlwaysEqualMixin, SecretPathEnvironmentBinding):
            pass

        class RuntimeUserSubclass(AlwaysEqualMixin, RuntimeUser):
            pass

        class HealthSubclass(AlwaysEqualMixin, HealthProfile):
            pass

        class ResourceSubclass(AlwaysEqualMixin, ResourceLimits):
            pass

        class RenderedMountSubclass(AlwaysEqualMixin, RenderedMount):
            pass

        class RenderedEnvironmentSubclass(AlwaysEqualMixin, RenderedEnvironmentEntry):
            pass

        class RenderedLabelSubclass(AlwaysEqualMixin, RenderedLabel):
            pass

        authority = valid_authority()
        snapshot = compile_launch_snapshot(authority)
        rendered = valid_rendered(snapshot, authority)

        snapshot_mutations = (
            lambda: dataclasses.replace(
                snapshot,
                identity=IdentitySubclass(
                    **{
                        field.name: getattr(snapshot.identity, field.name)
                        for field in dataclasses.fields(snapshot.identity)
                    }
                ),
            ),
            lambda: dataclasses.replace(
                snapshot,
                non_secret_environment=(
                    EnvironmentSubclass(
                        snapshot.non_secret_environment[0].name,
                        snapshot.non_secret_environment[0].value,
                    ),
                ),
            ),
            lambda: dataclasses.replace(
                snapshot,
                read_only_mounts=(
                    ReadOnlyMountSubclass(
                        snapshot.read_only_mounts[0].source,
                        snapshot.read_only_mounts[0].target,
                    ),
                    *snapshot.read_only_mounts[1:],
                ),
            ),
            lambda: dataclasses.replace(
                snapshot,
                state_mount=StateMountSubclass(
                    snapshot.state_mount.source,
                    snapshot.state_mount.target,
                    snapshot.state_mount.allocation_id,
                ),
            ),
            lambda: dataclasses.replace(
                snapshot,
                secret_mounts=(
                    SecretMountSubclass(
                        snapshot.secret_mounts[0].source,
                        snapshot.secret_mounts[0].target,
                        snapshot.secret_mounts[0].secret_reference_id,
                        snapshot.secret_mounts[0].version,
                    ),
                    *snapshot.secret_mounts[1:],
                ),
            ),
            lambda: dataclasses.replace(
                snapshot,
                secret_path_environment_bindings=(
                    SecretBindingSubclass(
                        snapshot.secret_path_environment_bindings[0].name,
                        snapshot.secret_path_environment_bindings[0].target,
                    ),
                    *snapshot.secret_path_environment_bindings[1:],
                ),
            ),
            lambda: dataclasses.replace(
                snapshot,
                runtime_user=RuntimeUserSubclass(
                    snapshot.runtime_user.uid,
                    snapshot.runtime_user.gid,
                    snapshot.runtime_user.home,
                ),
            ),
            lambda: dataclasses.replace(
                snapshot,
                health_profile=HealthSubclass(
                    **{
                        field.name: getattr(snapshot.health_profile, field.name)
                        for field in dataclasses.fields(snapshot.health_profile)
                    }
                ),
            ),
            lambda: dataclasses.replace(
                snapshot,
                resource_limits=ResourceSubclass(
                    **{
                        field.name: getattr(snapshot.resource_limits, field.name)
                        for field in dataclasses.fields(snapshot.resource_limits)
                    }
                ),
            ),
        )
        for mutate in snapshot_mutations:
            with self.assertRaisesRegex(
                DriverValidationError,
                "^driver_validation_error$",
            ):
                validate_launch_snapshot(mutate(), authority)

        rendered_mutations = (
            lambda: dataclasses.replace(
                rendered,
                mounts=(
                    RenderedMountSubclass(
                        **{
                            field.name: getattr(rendered.mounts[0], field.name)
                            for field in dataclasses.fields(rendered.mounts[0])
                        }
                    ),
                    *rendered.mounts[1:],
                ),
            ),
            lambda: dataclasses.replace(
                rendered,
                environment=(
                    RenderedEnvironmentSubclass(
                        rendered.environment[0].name,
                        rendered.environment[0].value,
                    ),
                    *rendered.environment[1:],
                ),
            ),
            lambda: dataclasses.replace(
                rendered,
                labels=(
                    RenderedLabelSubclass(
                        rendered.labels[0].name,
                        rendered.labels[0].value,
                    ),
                    *rendered.labels[1:],
                ),
            ),
        )
        for mutate in rendered_mutations:
            with self.assertRaisesRegex(
                DriverValidationError,
                "^driver_validation_error$",
            ):
                validate_rendered_snapshot(mutate(), snapshot, authority)

    def test_rejects_always_equal_scalar_and_tuple_subclasses(self) -> None:
        class AlwaysEqualStr(str):
            __hash__ = str.__hash__

            def __eq__(self, _other: object) -> bool:
                return True

            def __ne__(self, _other: object) -> bool:
                return False

        class AlwaysEqualTuple(tuple[str, ...]):
            def __eq__(self, _other: object) -> bool:
                return True

            def __ne__(self, _other: object) -> bool:
                return False

        authority = valid_authority()
        snapshot = compile_launch_snapshot(authority)
        evil_argv = tuple(
            AlwaysEqualStr(value)
            for value in (
                "sh",
                "-c",
                "evil",
                *("x" for _ in range(len(snapshot.argv) - 3)),
            )
        )
        with self.assertRaisesRegex(
            DriverValidationError,
            "^driver_validation_error$",
        ):
            validate_launch_snapshot(
                dataclasses.replace(snapshot, argv=evil_argv),
                authority,
            )

        rendered = valid_rendered(snapshot, authority)
        for mutate in (
            lambda: dataclasses.replace(
                rendered,
                argv=AlwaysEqualTuple(("sh", "-c", "evil")),
            ),
            lambda: dataclasses.replace(
                rendered,
                network_names=AlwaysEqualTuple(("caller-network",)),
            ),
        ):
            with self.assertRaisesRegex(
                DriverValidationError,
                "^driver_validation_error$",
            ):
                validate_rendered_snapshot(mutate(), snapshot, authority)

    def test_snapshot_and_rendered_repr_hide_host_sources(self) -> None:
        authority = valid_authority()
        snapshot = compile_launch_snapshot(authority)
        rendered = valid_rendered(snapshot, authority)

        for value in (snapshot, rendered):
            representation = repr(value)
            self.assertNotIn(str(HOST_ROOT), representation)
            for material in authority.materials:
                self.assertNotIn(str(material.source_path), representation)
            for secret in authority.secrets:
                self.assertNotIn(str(secret.source), representation)
            self.assertNotIn(str(authority.state.source), representation)


@unittest.skipIf(
    RUNTIME_SNAPSHOT_IMPORT_ERROR is not None,
    "runtime_snapshot contract is missing",
)
class RenderedSnapshotPolicyTests(unittest.TestCase):
    def test_accepts_exact_typed_hardened_render(self) -> None:
        authority = valid_authority()
        snapshot = compile_launch_snapshot(authority)
        rendered = valid_rendered(snapshot, authority)

        self.assertIsNone(validate_rendered_snapshot(rendered, snapshot, authority))

    def test_rejects_forbidden_capability_and_exactness_mutations(self) -> None:
        authority = valid_authority()
        snapshot = compile_launch_snapshot(authority)
        rendered = valid_rendered(snapshot, authority)
        material_index = 0
        state_index = len(authority.materials)
        secret_index = state_index + 1

        def replace_mount(index: int, **changes: object) -> RenderedContainerPolicy:
            mounts = list(rendered.mounts)
            mounts[index] = dataclasses.replace(mounts[index], **changes)
            return dataclasses.replace(rendered, mounts=tuple(mounts))

        mutations = (
            ("restart", dataclasses.replace(rendered, restart="unless-stopped")),
            ("network mode", dataclasses.replace(rendered, network_mode="host")),
            ("pid mode", dataclasses.replace(rendered, pid_mode="host")),
            ("ipc mode", dataclasses.replace(rendered, ipc_mode="host")),
            ("privileged", dataclasses.replace(rendered, privileged=True)),
            ("device", dataclasses.replace(rendered, devices=("/dev/sda",))),
            ("added capability", dataclasses.replace(rendered, cap_add=("NET_ADMIN",))),
            ("missing cap drop", dataclasses.replace(rendered, cap_drop=())),
            (
                "missing no-new-privileges",
                dataclasses.replace(rendered, security_options=()),
            ),
            (
                "writable root filesystem",
                dataclasses.replace(rendered, read_only_root_filesystem=False),
            ),
            (
                "published port",
                dataclasses.replace(rendered, published_ports=("18080:8080",)),
            ),
            (
                "second writable mount",
                replace_mount(material_index, read_only=False),
            ),
            (
                "writable secret",
                replace_mount(secret_index, read_only=False),
            ),
            (
                "state made read only",
                replace_mount(state_index, read_only=True),
            ),
            (
                "docker socket",
                replace_mount(
                    material_index,
                    source=HOST_ROOT / "docker.sock",
                ),
            ),
            (
                "material role",
                replace_mount(material_index, role="secret-as-config"),
            ),
            (
                "material source",
                replace_mount(material_index, source=HOST_ROOT / "other-config"),
            ),
            (
                "material target",
                replace_mount(
                    material_index,
                    target=PurePosixPath("/freqtrade/config/other.json"),
                ),
            ),
            (
                "mount kind",
                replace_mount(material_index, kind=RenderedMountKind.SECRET),
            ),
            (
                "shell argv",
                dataclasses.replace(rendered, argv=("sh", "-c", "caller command")),
            ),
            (
                "raw credential argv",
                dataclasses.replace(
                    rendered,
                    argv=("freqtrade", "--password", "private"),
                ),
            ),
            (
                "non-allowlisted environment",
                dataclasses.replace(
                    rendered,
                    environment=rendered.environment
                    + (RenderedEnvironmentEntry("CALLER_VALUE", "raw-secret"),),
                ),
            ),
            (
                "environment value",
                dataclasses.replace(
                    rendered,
                    environment=(
                        dataclasses.replace(
                            rendered.environment[0],
                            value="/caller/home",
                        ),
                        *rendered.environment[1:],
                    ),
                ),
            ),
            (
                "image",
                dataclasses.replace(rendered, image_id=f"sha256:{'d' * 64}"),
            ),
            (
                "identity",
                dataclasses.replace(
                    rendered,
                    identity=dataclasses.replace(
                        rendered.identity,
                        attempt_id="other-attempt",
                    ),
                ),
            ),
            (
                "network",
                dataclasses.replace(rendered, network_names=("caller-network",)),
            ),
            (
                "working directory",
                dataclasses.replace(
                    rendered,
                    working_directory=PurePosixPath("/tmp"),
                ),
            ),
            (
                "missing label",
                dataclasses.replace(rendered, labels=rendered.labels[:-1]),
            ),
            (
                "extra caller label",
                dataclasses.replace(
                    rendered,
                    labels=rendered.labels + (RenderedLabel("caller.label", "value"),),
                ),
            ),
            (
                "changed label",
                dataclasses.replace(
                    rendered,
                    labels=(
                        dataclasses.replace(rendered.labels[0], value="caller-value"),
                        *rendered.labels[1:],
                    ),
                ),
            ),
            (
                "health profile",
                dataclasses.replace(
                    rendered,
                    health_profile=dataclasses.replace(
                        rendered.health_profile,
                        retries=4,
                    ),
                ),
            ),
            (
                "resource limits",
                dataclasses.replace(
                    rendered,
                    resource_limits=dataclasses.replace(
                        rendered.resource_limits,
                        cpu_millis=2000,
                    ),
                ),
            ),
        )

        for name, changed in mutations:
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    DriverPolicyError,
                    "^driver_policy_error$",
                ),
            ):
                validate_rendered_snapshot(changed, snapshot, authority)


if __name__ == "__main__":
    unittest.main()
