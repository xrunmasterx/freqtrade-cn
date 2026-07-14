from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from sqlalchemy import Engine

from freqtrade.platform.database import (
    PlatformDatabaseSettings,
    create_platform_engine,
)
from freqtrade.platform.runtime_registration import (
    PAPER_PROBE_INSTANCE_ID,
    EnsurePaperProbeRegistrationRequest,
    PaperProbeRegistrationStatus,
)
from freqtrade.platform.runtime_registration_repository import (
    SqlPaperProbeRegistrationRepository,
)
from freqtrade.platform.runtime_service import RuntimeApplicationService
from freqtrade.platform.template_domain import AdapterTemplate
from freqtrade.platform.template_repository import (
    CommittedTemplatePublication,
    SqlTemplateRepository,
)
from tools.runtime_artifacts import (
    CommittedPaperProbeArtifacts,
    read_committed_paper_probe_artifacts,
)
from tools.runtime_templates import (
    ClosedPolicyRegistry,
    CommittedTemplate,
    load_closed_policy_registry,
    read_committed_template,
)


REPOSITORY_ROOT = Path("/opt/platform-operator/repository")
ROOT_COMMIT_FILE = Path("/opt/platform-operator/root-commit")
DATABASE_PASSWORD_FILE = Path("/run/secrets/database_password")
PAPER_PROBE_TEMPLATE_ID = "freqtrade-paper-probe-v1"
PLATFORM_OPERATOR_ACTOR = "platform-operator"

_GIT_IDENTITY = re.compile(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})\n")


@dataclass(frozen=True, slots=True)
class _CommittedEvidence:
    template: CommittedTemplate
    artifacts: CommittedPaperProbeArtifacts
    policies: ClosedPolicyRegistry


class _ClosedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.exit(2, "invalid_arguments\n")


def _parser() -> argparse.ArgumentParser:
    parser = _ClosedArgumentParser(prog="runtime-registry-cli")
    domains = parser.add_subparsers(dest="domain", required=True)

    template = domains.add_parser("runtime-template")
    template_commands = template.add_subparsers(dest="command", required=True)
    template_commands.add_parser("validate")
    publish = template_commands.add_parser("publish")
    publish.add_argument(
        "--actor",
        choices=(PLATFORM_OPERATOR_ACTOR,),
        required=True,
    )

    registry = domains.add_parser("runtime-registry")
    registry_commands = registry.add_subparsers(dest="command", required=True)
    for name in ("register-paper-probe", "compile"):
        command = registry_commands.add_parser(name)
        command.add_argument(
            "--actor",
            choices=(PLATFORM_OPERATOR_ACTOR,),
            required=True,
        )
    status = registry_commands.add_parser("status")
    status.add_argument(
        "--instance-id",
        choices=(PAPER_PROBE_INSTANCE_ID,),
        required=True,
    )
    return parser


def _read_root_commit_identity() -> str:
    try:
        metadata = os.lstat(ROOT_COMMIT_FILE)
    except OSError:
        raise ValueError("root_commit_identity_invalid") from None
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)
    ):
        raise ValueError("root_commit_identity_invalid")
    try:
        document = ROOT_COMMIT_FILE.read_bytes()
    except OSError:
        raise ValueError("root_commit_identity_invalid") from None
    if _GIT_IDENTITY.fullmatch(document) is None:
        raise ValueError("root_commit_identity_invalid")
    return document[:-1].decode("ascii")


def _load_committed_evidence() -> _CommittedEvidence:
    root_commit = _read_root_commit_identity()
    template = read_committed_template(
        REPOSITORY_ROOT,
        PAPER_PROBE_TEMPLATE_ID,
        root_commit,
    )
    artifacts = read_committed_paper_probe_artifacts(REPOSITORY_ROOT, root_commit)
    policies = load_closed_policy_registry(REPOSITORY_ROOT, root_commit)
    if (
        template.source_commit != root_commit
        or artifacts.root_commit != root_commit
        or policies.source_commit != root_commit
    ):
        raise ValueError("committed_evidence_identity_mismatch")
    return _CommittedEvidence(
        template=template,
        artifacts=artifacts,
        policies=policies,
    )


def _publication(evidence: _CommittedEvidence) -> CommittedTemplatePublication:
    payload = {
        key: value
        for key, value in evidence.template.payload.items()
        if key != "schema_version"
    }
    artifacts = evidence.artifacts
    return CommittedTemplatePublication(
        template=AdapterTemplate.model_validate(payload),
        canonical_payload=evidence.template.canonical_json,
        payload_digest=evidence.template.digest,
        source_commit=evidence.template.source_commit,
        root_commit=artifacts.root_commit,
        backend_commit=artifacts.backend_commit,
        frontend_commit=artifacts.frontend_commit,
        strategies_commit=artifacts.strategies_commit,
    )


def _registration_request(
    evidence: _CommittedEvidence,
) -> EnsurePaperProbeRegistrationRequest:
    artifacts = evidence.artifacts
    policies = evidence.policies
    return EnsurePaperProbeRegistrationRequest(
        adapter_template_revision_id=f"template-{evidence.template.digest}",
        component_commits={
            "root_commit": artifacts.root_commit,
            "backend_commit": artifacts.backend_commit,
            "frontend_commit": artifacts.frontend_commit,
            "strategies_commit": artifacts.strategies_commit,
        },
        config_blob_digest=artifacts.config_sha256,
        strategy_digest=artifacts.strategy_sha256,
        safety_policy_digest=artifacts.safety_sha256,
        strategy_class_name=artifacts.strategy_class_name,
        closed_policy_snapshot={
            "image_policy_ids": policies.image_policy_ids,
            "command_policy_ids": policies.command_policy_ids,
            "mount_policy_ids": policies.mount_policy_ids,
            "network_policy_ids": policies.network_policy_ids,
            "health_profile_ids": policies.health_profile_ids,
            "resource_profile_ids": policies.resource_profile_ids,
            "state_layout_ids": policies.state_layout_ids,
            "source_commit": policies.source_commit,
        },
    )


def _validation_payload(evidence: _CommittedEvidence) -> dict[str, str]:
    artifacts = evidence.artifacts
    return {
        "backend_commit": artifacts.backend_commit,
        "config_blob_digest": artifacts.config_sha256,
        "frontend_commit": artifacts.frontend_commit,
        "root_commit": artifacts.root_commit,
        "safety_policy_digest": artifacts.safety_sha256,
        "status": "valid",
        "strategies_commit": artifacts.strategies_commit,
        "strategy_class_name": artifacts.strategy_class_name,
        "strategy_digest": artifacts.strategy_sha256,
        "template_id": PAPER_PROBE_TEMPLATE_ID,
        "template_payload_digest": evidence.template.digest,
    }


def _status_payload(status: PaperProbeRegistrationStatus) -> dict[str, object]:
    validated = PaperProbeRegistrationStatus.model_validate(
        status.model_dump(mode="python")
    )
    return validated.model_dump(mode="json")


def _create_engine() -> Engine:
    settings = PlatformDatabaseSettings(
        host="platform-postgres",
        port=5432,
        database="platform",
        username="platform_operator",
        password_file=DATABASE_PASSWORD_FILE,
    )
    return create_platform_engine(settings)


def _publish(actor: str) -> dict[str, str]:
    evidence = _load_committed_evidence()
    engine = _create_engine()
    try:
        repository = SqlTemplateRepository(engine)
        service = RuntimeApplicationService(template_repository=repository)
        view = service.publish_template(_publication(evidence), actor, datetime.now(UTC))
    finally:
        engine.dispose()
    return {
        "adapter_template_revision_id": view.revision_id,
        "backend_commit": view.backend_commit,
        "frontend_commit": view.frontend_commit,
        "root_commit": view.root_commit,
        "status": view.status.value,
        "strategies_commit": view.strategies_commit,
        "template_id": view.template.template_id,
        "template_payload_digest": view.payload_digest,
    }


def _ensure_registration(actor: str) -> dict[str, object]:
    evidence = _load_committed_evidence()
    engine = _create_engine()
    try:
        repository = SqlPaperProbeRegistrationRepository(engine)
        service = RuntimeApplicationService(registration_repository=repository)
        status = service.ensure_paper_probe_registration(
            _registration_request(evidence),
            actor,
            datetime.now(UTC),
        )
    finally:
        engine.dispose()
    return _status_payload(status)


def _registration_status(instance_id: str) -> dict[str, object]:
    engine = _create_engine()
    try:
        repository = SqlPaperProbeRegistrationRepository(engine)
        service = RuntimeApplicationService(registration_repository=repository)
        status = service.registration_status(instance_id)
    finally:
        engine.dispose()
    return _status_payload(status)


def _execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.domain == "runtime-template":
        if arguments.command == "validate":
            return _validation_payload(_load_committed_evidence())
        return _publish(arguments.actor)
    if arguments.command in {"register-paper-probe", "compile"}:
        return _ensure_registration(arguments.actor)
    return _registration_status(arguments.instance_id)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = _execute(arguments)
    except Exception:
        sys.stderr.write("runtime_registry_operation_failed\n")
        return 1
    sys.stdout.write(
        json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
