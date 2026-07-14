from __future__ import annotations

import hashlib
import io
import json
import stat
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from unittest import mock

from freqtrade.platform.runtime_registration import PaperProbeRegistrationStatus
from freqtrade.platform.template_domain import AdapterTemplate, TemplateStatus
from freqtrade.platform.template_repository import AdapterTemplateRevisionView

from tools import runtime_registry_cli
from tools.runtime_artifacts import CommittedPaperProbeArtifacts
from tools.runtime_templates import ClosedPolicyRegistry, CommittedTemplate


ROOT_COMMIT = "1" * 40
BACKEND_COMMIT = "2" * 40
FRONTEND_COMMIT = "3" * 40
STRATEGIES_COMMIT = "4" * 40
TEMPLATE_ID = "freqtrade-paper-probe-v1"


def _template_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "template_id": TEMPLATE_ID,
        "semantic_version": "1.0.0",
        "allowed_instance_kinds": ["freqtrade"],
        "allowed_owner_kinds": ["paper_probe"],
        "allowed_environments": ["paper"],
        "image_policy_id": "freqtrade-reviewed-image-v1",
        "command_policy_id": "freqtrade-spot-paper-v1",
        "mount_policy_ids": [
            "runtime-config-ro-v1",
            "strategy-ro-v1",
            "managed-state-rw-v1",
            "api-secrets-ro-v1",
        ],
        "network_policy_id": "isolated-public-market-data-v1",
        "health_profile_id": "freqtrade-ping-v1",
        "resource_profile_id": "freqtrade-small-v1",
        "secret_classes": ["api_password", "jwt_secret", "ws_token"],
        "state_layout_id": "freqtrade-state-v1",
    }


def _committed_template() -> CommittedTemplate:
    payload = _template_payload()
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"
    return CommittedTemplate(
        payload=MappingProxyType(
            {
                key: tuple(value) if isinstance(value, list) else value
                for key, value in payload.items()
            }
        ),
        canonical_json=canonical,
        digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        source_path=f"ops/adapter-templates/{TEMPLATE_ID}.json",
        source_commit=ROOT_COMMIT,
    )


def _artifacts() -> CommittedPaperProbeArtifacts:
    return CommittedPaperProbeArtifacts(
        root_commit=ROOT_COMMIT,
        backend_commit=BACKEND_COMMIT,
        frontend_commit=FRONTEND_COMMIT,
        strategies_commit=STRATEGIES_COMMIT,
        config_sha256="a" * 64,
        strategy_sha256="b" * 64,
        safety_sha256="c" * 64,
        strategy_class_name="SampleStrategy",
    )


def _policies() -> ClosedPolicyRegistry:
    return ClosedPolicyRegistry(
        image_policy_ids=frozenset({"freqtrade-reviewed-image-v1"}),
        command_policy_ids=frozenset({"freqtrade-spot-paper-v1"}),
        mount_policy_ids=frozenset(
            {
                "runtime-config-ro-v1",
                "strategy-ro-v1",
                "managed-state-rw-v1",
                "api-secrets-ro-v1",
            }
        ),
        network_policy_ids=frozenset({"isolated-public-market-data-v1"}),
        health_profile_ids=frozenset({"freqtrade-ping-v1"}),
        resource_profile_ids=frozenset({"freqtrade-small-v1"}),
        state_layout_ids=frozenset({"freqtrade-state-v1"}),
        source_commit=ROOT_COMMIT,
    )


def _status() -> PaperProbeRegistrationStatus:
    return PaperProbeRegistrationStatus(
        instance_id="phase2-spot-paper-probe",
        runtime_spec_revision_id="runtime-spec-" + "d" * 64,
        adapter_template_revision_id="template-" + _committed_template().digest,
        catalog_revision_id="catalog-v2",
        state_allocation_id="state-phase2-spot-paper-probe-v1",
        secret_reference_ids=(
            "secret-phase2-spot-paper-probe-api-password-v1",
            "secret-phase2-spot-paper-probe-jwt-secret-v1",
            "secret-phase2-spot-paper-probe-ws-token-v1",
        ),
        desired_state="stopped",
        lifecycle_status="registered",
    )


class RuntimeRegistryCliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = runtime_registry_cli.main(list(arguments))
            except SystemExit as error:
                code = int(error.code)
        return code, stdout.getvalue(), stderr.getvalue()

    @contextmanager
    def patched_evidence(self):
        with (
            mock.patch.object(
                runtime_registry_cli,
                "_read_root_commit_identity",
                return_value=ROOT_COMMIT,
            ) as commit_reader,
            mock.patch.object(
                runtime_registry_cli,
                "read_committed_template",
                return_value=_committed_template(),
            ) as template_reader,
            mock.patch.object(
                runtime_registry_cli,
                "read_committed_paper_probe_artifacts",
                return_value=_artifacts(),
            ) as artifact_reader,
            mock.patch.object(
                runtime_registry_cli,
                "load_closed_policy_registry",
                return_value=_policies(),
            ) as policy_reader,
        ):
            yield commit_reader, template_reader, artifact_reader, policy_reader

    def test_root_commit_file_accepts_only_one_full_lowercase_identity_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "root-commit"
            path.write_bytes((ROOT_COMMIT + "\n").encode("ascii"))
            with mock.patch.object(runtime_registry_cli, "ROOT_COMMIT_FILE", path):
                self.assertEqual(
                    runtime_registry_cli._read_root_commit_identity(),
                    ROOT_COMMIT,
                )

            for invalid in (
                ROOT_COMMIT,
                "A" * 40 + "\n",
                ROOT_COMMIT + "\r\n",
                ROOT_COMMIT + "\n\n",
                "1" * 39 + "\n",
                "../HEAD\n",
            ):
                path.write_bytes(invalid.encode("ascii"))
                with (
                    mock.patch.object(runtime_registry_cli, "ROOT_COMMIT_FILE", path),
                    self.assertRaisesRegex(ValueError, "^root_commit_identity_invalid$"),
                ):
                    runtime_registry_cli._read_root_commit_identity()

    def test_root_commit_file_rejects_non_regular_metadata_before_reading(self) -> None:
        metadata = mock.Mock(st_mode=stat.S_IFLNK, st_file_attributes=0)
        with (
            mock.patch.object(runtime_registry_cli.os, "lstat", return_value=metadata),
            mock.patch.object(
                runtime_registry_cli.Path,
                "read_bytes",
                side_effect=AssertionError("must not read a non-regular identity file"),
            ) as read_bytes,
            self.assertRaisesRegex(ValueError, "^root_commit_identity_invalid$"),
        ):
            runtime_registry_cli._read_root_commit_identity()
        read_bytes.assert_not_called()

    def test_validate_loads_only_fixed_committed_evidence_and_never_builds_database(self) -> None:
        with (
            self.patched_evidence() as patches,
            mock.patch.object(runtime_registry_cli, "_create_engine") as create_engine,
        ):
            code, stdout, stderr = self.run_cli("runtime-template", "validate")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, json.dumps(json.loads(stdout), separators=(",", ":"), sort_keys=True) + "\n")
        self.assertEqual(
            json.loads(stdout),
            {
                "backend_commit": BACKEND_COMMIT,
                "config_blob_digest": "a" * 64,
                "frontend_commit": FRONTEND_COMMIT,
                "root_commit": ROOT_COMMIT,
                "safety_policy_digest": "c" * 64,
                "status": "valid",
                "strategies_commit": STRATEGIES_COMMIT,
                "strategy_class_name": "SampleStrategy",
                "strategy_digest": "b" * 64,
                "template_id": TEMPLATE_ID,
                "template_payload_digest": _committed_template().digest,
            },
        )
        create_engine.assert_not_called()
        patches[1].assert_called_once_with(
            runtime_registry_cli.REPOSITORY_ROOT,
            TEMPLATE_ID,
            ROOT_COMMIT,
        )
        patches[2].assert_called_once_with(
            runtime_registry_cli.REPOSITORY_ROOT,
            ROOT_COMMIT,
        )
        patches[3].assert_called_once_with(
            runtime_registry_cli.REPOSITORY_ROOT,
            ROOT_COMMIT,
        )

    def test_publish_uses_template_repository_and_application_service(self) -> None:
        template = _committed_template()
        publication_view = AdapterTemplateRevisionView(
            revision_id="template-" + template.digest,
            template=AdapterTemplate.model_validate(
                {key: value for key, value in template.payload.items() if key != "schema_version"}
            ),
            payload_digest=template.digest,
            source_commit=ROOT_COMMIT,
            root_commit=ROOT_COMMIT,
            backend_commit=BACKEND_COMMIT,
            frontend_commit=FRONTEND_COMMIT,
            strategies_commit=STRATEGIES_COMMIT,
            status=TemplateStatus.ACTIVE,
            published_by="platform-operator",
            published_at=datetime(2026, 7, 14, tzinfo=UTC),
            deprecated_at=None,
            revoked_at=None,
        )
        engine = mock.Mock()
        repository = object()
        service = mock.Mock()
        service.publish_template.return_value = publication_view
        with (
            self.patched_evidence(),
            mock.patch.object(runtime_registry_cli, "_create_engine", return_value=engine),
            mock.patch.object(
                runtime_registry_cli,
                "SqlTemplateRepository",
                return_value=repository,
            ) as repository_type,
            mock.patch.object(
                runtime_registry_cli,
                "RuntimeApplicationService",
                return_value=service,
            ) as service_type,
        ):
            code, stdout, stderr = self.run_cli(
                "runtime-template",
                "publish",
                "--actor",
                "platform-operator",
            )

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(
            json.loads(stdout),
            {
                "adapter_template_revision_id": "template-" + template.digest,
                "backend_commit": BACKEND_COMMIT,
                "frontend_commit": FRONTEND_COMMIT,
                "root_commit": ROOT_COMMIT,
                "status": "active",
                "strategies_commit": STRATEGIES_COMMIT,
                "template_id": TEMPLATE_ID,
                "template_payload_digest": template.digest,
            },
        )
        repository_type.assert_called_once_with(engine)
        service_type.assert_called_once_with(template_repository=repository)
        publication, actor, occurred_at = service.publish_template.call_args.args
        self.assertEqual(actor, "platform-operator")
        self.assertEqual(occurred_at.tzinfo, UTC)
        self.assertEqual(publication.canonical_payload, template.canonical_json)
        self.assertEqual(publication.template.template_id, TEMPLATE_ID)
        self.assertEqual(publication.backend_commit, BACKEND_COMMIT)
        engine.dispose.assert_called_once_with()

    def test_register_and_compile_call_the_same_atomic_ensure_service_method(self) -> None:
        for command in ("register-paper-probe", "compile"):
            with self.subTest(command=command):
                engine = mock.Mock()
                repository = object()
                service = mock.Mock()
                service.ensure_paper_probe_registration.return_value = _status()
                with (
                    self.patched_evidence(),
                    mock.patch.object(
                        runtime_registry_cli,
                        "_create_engine",
                        return_value=engine,
                    ),
                    mock.patch.object(
                        runtime_registry_cli,
                        "SqlPaperProbeRegistrationRepository",
                        return_value=repository,
                    ) as repository_type,
                    mock.patch.object(
                        runtime_registry_cli,
                        "RuntimeApplicationService",
                        return_value=service,
                    ) as service_type,
                ):
                    code, stdout, stderr = self.run_cli(
                        "runtime-registry",
                        command,
                        "--actor",
                        "platform-operator",
                    )

                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(json.loads(stdout), _status().model_dump(mode="json"))
                repository_type.assert_called_once_with(engine)
                service_type.assert_called_once_with(registration_repository=repository)
                request, actor, occurred_at = (
                    service.ensure_paper_probe_registration.call_args.args
                )
                self.assertEqual(actor, "platform-operator")
                self.assertEqual(occurred_at.tzinfo, UTC)
                self.assertEqual(
                    request.adapter_template_revision_id,
                    "template-" + _committed_template().digest,
                )
                self.assertEqual(request.component_commits.root_commit, ROOT_COMMIT)
                self.assertEqual(request.config_blob_digest, "a" * 64)
                self.assertEqual(request.strategy_digest, "b" * 64)
                self.assertEqual(request.safety_policy_digest, "c" * 64)
                self.assertEqual(
                    request.closed_policy_snapshot.source_commit,
                    ROOT_COMMIT,
                )
                engine.dispose.assert_called_once_with()

    def test_status_uses_only_the_fixed_instance_selector(self) -> None:
        engine = mock.Mock()
        repository = object()
        service = mock.Mock()
        service.registration_status.return_value = _status()
        with (
            mock.patch.object(runtime_registry_cli, "_create_engine", return_value=engine),
            mock.patch.object(
                runtime_registry_cli,
                "SqlPaperProbeRegistrationRepository",
                return_value=repository,
            ),
            mock.patch.object(
                runtime_registry_cli,
                "RuntimeApplicationService",
                return_value=service,
            ),
        ):
            code, stdout, stderr = self.run_cli(
                "runtime-registry",
                "status",
                "--instance-id",
                "phase2-spot-paper-probe",
            )

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout), _status().model_dump(mode="json"))
        service.registration_status.assert_called_once_with("phase2-spot-paper-probe")
        engine.dispose.assert_called_once_with()

    def test_fixed_selectors_reject_other_values_before_database_construction(self) -> None:
        invocations = (
            ("runtime-template", "publish", "--actor", "other-operator"),
            ("runtime-registry", "compile", "--actor", "other-operator"),
            (
                "runtime-registry",
                "status",
                "--instance-id",
                "other-instance",
            ),
        )
        for invocation in invocations:
            with (
                self.subTest(invocation=invocation),
                mock.patch.object(runtime_registry_cli, "_create_engine") as create_engine,
            ):
                code, stdout, stderr = self.run_cli(*invocation)
            self.assertEqual((code, stdout, stderr), (2, "", "invalid_arguments\n"))
            create_engine.assert_not_called()

    def test_raw_power_unknown_flags_and_lifecycle_verbs_fail_closed_without_echo(self) -> None:
        invocations = (
            ("runtime-template", "validate", "--path", "must-not-echo"),
            (
                "runtime-registry",
                "compile",
                "--actor",
                "platform-operator",
                "--secret",
                "must-not-echo",
            ),
            ("runtime-registry", "start"),
            ("runtime-registry", "status", "--image", "must-not-echo"),
            ("runtime-registry", "status", "--unknown", "must-not-echo"),
        )
        for invocation in invocations:
            with (
                self.subTest(invocation=invocation),
                mock.patch.object(runtime_registry_cli, "_create_engine") as create_engine,
            ):
                code, stdout, stderr = self.run_cli(*invocation)
            self.assertEqual((code, stdout, stderr), (2, "", "invalid_arguments\n"))
            create_engine.assert_not_called()

    def test_application_failure_prints_only_stable_code_and_disposes_engine(self) -> None:
        secret = "database-secret-that-must-not-leak"
        engine = mock.Mock()
        with (
            mock.patch.object(runtime_registry_cli, "_create_engine", return_value=engine),
            mock.patch.object(
                runtime_registry_cli,
                "SqlPaperProbeRegistrationRepository",
                side_effect=RuntimeError(secret),
            ),
        ):
            code, stdout, stderr = self.run_cli(
                "runtime-registry",
                "status",
                "--instance-id",
                "phase2-spot-paper-probe",
            )

        self.assertEqual((code, stdout, stderr), (1, "", "runtime_registry_operation_failed\n"))
        self.assertNotIn(secret, stderr)
        engine.dispose.assert_called_once_with()

    def test_database_settings_are_fixed_and_read_only_from_the_secret_file(self) -> None:
        settings = mock.Mock()
        engine = object()
        with (
            mock.patch.object(
                runtime_registry_cli,
                "PlatformDatabaseSettings",
                return_value=settings,
            ) as settings_type,
            mock.patch.object(
                runtime_registry_cli,
                "create_platform_engine",
                return_value=engine,
            ) as create_engine,
        ):
            self.assertIs(runtime_registry_cli._create_engine(), engine)

        settings_type.assert_called_once_with(
            host="platform-postgres",
            port=5432,
            database="platform",
            username="platform_operator",
            password_file=Path("/run/secrets/database_password"),
        )
        create_engine.assert_called_once_with(settings)


if __name__ == "__main__":
    unittest.main()
