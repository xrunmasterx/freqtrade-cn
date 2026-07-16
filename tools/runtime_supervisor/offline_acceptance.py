from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Sequence

from tools.runtime_artifacts import (
    CommittedPaperProbeArtifacts,
    CommittedPaperProbeMaterialProvider,
    read_committed_paper_probe_artifacts,
)
from tools.runtime_driver import DriverIdentity
from tools.runtime_launch_policy import load_resolved_launch_policy_bundle
from tools.runtime_secrets import LocalFileSecretProvider, SecretMaterialRequirement
from tools.runtime_snapshot import (
    LaunchCompilationAuthority,
    ResolvedAttemptAuthority,
    ResolvedSecretVersionAuthority,
    RuntimeSpecLaunchAuthority,
    compile_launch_snapshot,
    render_container_policy,
    validate_launch_snapshot,
    validate_rendered_snapshot,
)
from tools.runtime_state import VerifiedStateMount
from tools.runtime_templates import read_committed_template


PAPER_PROBE_TEMPLATE_ID = "freqtrade-paper-probe-v1"
PAPER_PROBE_INSTANCE_ID = "phase2-spot-paper-probe"
PAPER_PROBE_ATTEMPT_ID = "phase2-offline-attempt"
PAPER_PROBE_STATE_ALLOCATION_ID = "state-phase2-spot-paper-probe-v1"
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SECRET_REQUIREMENTS = (
    SecretMaterialRequirement(
        "secret-phase2-spot-paper-probe-api-password-v1",
        "version-1",
        "api_password",
    ),
    SecretMaterialRequirement(
        "secret-phase2-spot-paper-probe-jwt-secret-v1",
        "version-1",
        "jwt_secret",
    ),
    SecretMaterialRequirement(
        "secret-phase2-spot-paper-probe-ws-token-v1",
        "version-1",
        "ws_token",
    ),
)


@dataclass(frozen=True, slots=True)
class OfflinePaperProbeReceipt:
    root_commit: str
    image_id: str
    launch_authority_digest: str
    template_digest: str
    policy_digest: str
    dry_run: bool
    exchange: str
    product: str
    strategy: str
    runtime_action_executed: bool
    published_ports: int
    writable_mounts: int
    secret_mounts: int
    secret_runtime_readability_verified: bool

    def to_json(self) -> str:
        return json.dumps(
            {
                "dry_run": self.dry_run,
                "exchange": self.exchange,
                "image_id": self.image_id,
                "launch_authority_digest": self.launch_authority_digest,
                "policy_digest": self.policy_digest,
                "product": self.product,
                "published_ports": self.published_ports,
                "root_commit": self.root_commit,
                "runtime_action_executed": self.runtime_action_executed,
                "secret_mounts": self.secret_mounts,
                "secret_runtime_readability_verified": (
                    self.secret_runtime_readability_verified
                ),
                "strategy": self.strategy,
                "template_digest": self.template_digest,
                "writable_mounts": self.writable_mounts,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


def _write_secret(root: Path, requirement: SecretMaterialRequirement, value: str) -> None:
    path = root / requirement.reference_id / requirement.version_id / "value"
    path.parent.mkdir(parents=True)
    path.write_text(value + "\n", encoding="utf-8", newline="\n")
    os.chmod(path, 0o600)


def _network_names(instance_id: str) -> tuple[str, ...]:
    digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()[:24]
    return (f"runtime-{digest}-access",)


def _spec(
    artifacts: CommittedPaperProbeArtifacts,
    template_digest: str,
) -> RuntimeSpecLaunchAuthority:
    payload_digest = hashlib.sha256(
        f"offline-paper-probe\0{template_digest}".encode("ascii")
    ).hexdigest()
    return RuntimeSpecLaunchAuthority(
        runtime_spec_revision_id=f"runtime-spec-{payload_digest}",
        payload_digest=payload_digest,
        owner_kind="paper_probe",
        instance_kind="freqtrade",
        environment="paper",
        adapter_template_revision_id=f"template-{template_digest}",
        template_digest=template_digest,
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
        state_allocation_id=PAPER_PROBE_STATE_ALLOCATION_ID,
        secret_reference_ids=tuple(
            requirement.reference_id for requirement in _SECRET_REQUIREMENTS
        ),
        config_blob_commit=artifacts.root_commit,
        strategy_commit=artifacts.root_commit,
        strategy_class_name=artifacts.strategy_class_name,
        safety_policy_commit=artifacts.root_commit,
        root_commit=artifacts.root_commit,
        backend_commit=artifacts.backend_commit,
        frontend_commit=artifacts.frontend_commit,
        strategies_commit=artifacts.strategies_commit,
        config_blob_digest=artifacts.config_sha256,
        strategy_digest=artifacts.strategy_sha256,
        safety_policy_digest=artifacts.safety_sha256,
    )


def verify_offline_paper_probe(
    repository_root: Path,
    root_commit: str,
    image_id: str,
) -> OfflinePaperProbeReceipt:
    if (
        type(repository_root) is not type(Path())
        or not repository_root.is_absolute()
        or type(root_commit) is not str
        or _COMMIT.fullmatch(root_commit) is None
        or type(image_id) is not str
        or _IMAGE_ID.fullmatch(image_id) is None
    ):
        raise ValueError("offline paper probe input invalid")
    committed = read_committed_paper_probe_artifacts(repository_root, root_commit)
    template = read_committed_template(
        repository_root,
        PAPER_PROBE_TEMPLATE_ID,
        root_commit,
    )
    policies = load_resolved_launch_policy_bundle(
        repository_root,
        PAPER_PROBE_TEMPLATE_ID,
        root_commit,
    )
    spec = _spec(committed, template.digest)
    with (
        CommittedPaperProbeMaterialProvider(repository_root, root_commit) as materials,
        tempfile.TemporaryDirectory(prefix="runtime-supervisor-offline-") as directory,
    ):
        temporary = Path(directory).resolve()
        state_source = temporary / "state"
        for child in (
            state_source,
            state_source / "home",
            state_source / "logs",
            state_source / "data",
        ):
            child.mkdir(exist_ok=True)
        secret_root = temporary / "secrets"
        for requirement, value in zip(
            _SECRET_REQUIREMENTS,
            ("a" * 32, "b" * 48, "c" * 32),
            strict=True,
        ):
            _write_secret(secret_root, requirement, value)
        runtime_uid = getattr(os, "getuid", lambda: 12345)()
        secret_provider = LocalFileSecretProvider(
            _SECRET_REQUIREMENTS,
            runtime_uid=runtime_uid,
            secret_root=secret_root,
        )
        state = VerifiedStateMount(
            attempt_id=PAPER_PROBE_ATTEMPT_ID,
            state_allocation_id=PAPER_PROBE_STATE_ALLOCATION_ID,
            instance_id=PAPER_PROBE_INSTANCE_ID,
            layout_id="freqtrade-state-v1",
            provider_id="managed-local-v1",
            generation=1,
            relative_path=(
                "ft_userdata/runtime/instances/phase2-spot-paper-probe"
            ),
            source=state_source,
            runtime_uid=12345,
            durability=(
                "atomic-process-crash" if os.name == "nt" else "power-loss-posix"
            ),
        )
        attempt = ResolvedAttemptAuthority(
            attempt_id=PAPER_PROBE_ATTEMPT_ID,
            instance_id=PAPER_PROBE_INSTANCE_ID,
            runtime_spec_revision_id=spec.runtime_spec_revision_id,
            runtime_spec_payload_digest=spec.payload_digest,
            adapter_template_revision_id=spec.adapter_template_revision_id,
            state_allocation_id=spec.state_allocation_id,
            resolved_secret_versions=tuple(
                ResolvedSecretVersionAuthority(
                    requirement.reference_id,
                    requirement.version_id,
                )
                for requirement in _SECRET_REQUIREMENTS
            ),
            image_id=image_id,
            root_commit=committed.root_commit,
            backend_commit=committed.backend_commit,
            frontend_commit=committed.frontend_commit,
            strategies_commit=committed.strategies_commit,
            project_identity="runtime-phase2-spot-paper-probe",
            container_identity="runtime-phase2-spot-paper-probe-worker",
        )
        identity = DriverIdentity(
            project_name=attempt.project_identity,
            container_name=attempt.container_identity,
            instance_id=attempt.instance_id,
            attempt_id=attempt.attempt_id,
            runtime_spec_digest=attempt.runtime_spec_payload_digest,
            state_allocation_id=attempt.state_allocation_id,
            image_id=attempt.image_id,
            network_names=_network_names(attempt.instance_id),
        )
        with (
            materials.mint_lease(PAPER_PROBE_ATTEMPT_ID) as material_lease,
            secret_provider.resolve_mounts(PAPER_PROBE_ATTEMPT_ID) as secret_lease,
        ):
            authority = LaunchCompilationAuthority(
                spec=spec,
                attempt=attempt,
                template=template,
                policies=policies,
                state=state,
                secrets=secret_lease.mounts,
                materials=material_lease.materials,
                identity=identity,
            )
            snapshot = compile_launch_snapshot(authority)
            validate_launch_snapshot(snapshot, authority)
            rendered = render_container_policy(snapshot, authority)
            validate_rendered_snapshot(rendered, snapshot, authority)
            if any(not mount.source.exists() for mount in rendered.mounts):
                raise ValueError("offline paper probe material unavailable")

    writable_mounts = tuple(
        mount for mount in rendered.mounts if not mount.read_only
    )
    secret_mounts = tuple(
        mount for mount in rendered.mounts if mount.kind.value == "secret"
    )
    if (
        snapshot.runtime_user.uid != 12345
        or snapshot.runtime_user.gid != 12345
        or snapshot.internal_ports != (8080,)
        or len(snapshot.read_only_mounts) != 3
        or len(snapshot.secret_mounts) != 3
        or len(rendered.mounts) != 7
        or len(writable_mounts) != 1
        or len(secret_mounts) != 3
        or rendered.privileged
        or rendered.devices
        or rendered.cap_add
        or rendered.cap_drop != ("ALL",)
        or rendered.security_options != ("no-new-privileges:true",)
        or not rendered.read_only_root_filesystem
        or rendered.published_ports
    ):
        raise ValueError("offline paper probe policy invalid")
    return OfflinePaperProbeReceipt(
        root_commit=root_commit,
        image_id=image_id,
        launch_authority_digest=snapshot.launch_authority_digest,
        template_digest=template.digest,
        policy_digest=policies.policy_digest,
        dry_run=True,
        exchange="bitget",
        product="spot",
        strategy="SampleStrategy",
        runtime_action_executed=False,
        published_ports=0,
        writable_mounts=1,
        secret_mounts=3,
        secret_runtime_readability_verified=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--root-commit", required=True)
    parser.add_argument("--image-id", required=True)
    arguments = parser.parse_args(argv)
    try:
        receipt = verify_offline_paper_probe(
            Path(__file__).resolve().parents[2],
            arguments.root_commit,
            arguments.image_id,
        )
    except Exception:
        sys.stderr.write("offline_paper_probe_failed\n")
        return 1
    sys.stdout.write(receipt.to_json() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
