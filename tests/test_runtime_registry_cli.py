from __future__ import annotations

import builtins
import hashlib
import importlib.util
import io
import json
import stat
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest import mock

from tools import runtime_registry_cli
from tools.runtime_artifacts import CommittedPaperProbeArtifacts
from tools.runtime_templates import ClosedPolicyRegistry, CommittedTemplate


ROOT_COMMIT = "1" * 40
BACKEND_COMMIT = "2" * 40
FRONTEND_COMMIT = "3" * 40
STRATEGIES_COMMIT = "4" * 40
TEMPLATE_ID = "freqtrade-paper-probe-v1"
INSTANCE_ID = "phase2-spot-paper-probe"
LAUNCH_POLICY_CATALOG_DIGEST = "d" * 64
LAUNCH_POLICY_DIGEST = "e" * 64


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
            "safety-policy-ro-v1",
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
    canonical = (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
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
                "safety-policy-ro-v1",
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


def _launch_policy() -> SimpleNamespace:
    return SimpleNamespace(
        source_commit=ROOT_COMMIT,
        template_digest=_committed_template().digest,
        catalog_digest=LAUNCH_POLICY_CATALOG_DIGEST,
        policy_digest=LAUNCH_POLICY_DIGEST,
    )


def _status_payload() -> dict[str, object]:
    return {
        "instance_id": INSTANCE_ID,
        "runtime_spec_revision_id": "runtime-spec-" + "d" * 64,
        "adapter_template_revision_id": "template-" + _committed_template().digest,
        "catalog_revision_id": "catalog-v2",
        "state_allocation_id": "state-phase2-spot-paper-probe-v1",
        "secret_reference_ids": [
            "secret-phase2-spot-paper-probe-api-password-v1",
            "secret-phase2-spot-paper-probe-jwt-secret-v1",
            "secret-phase2-spot-paper-probe-ws-token-v1",
        ],
        "desired_state": "stopped",
        "lifecycle_status": "registered",
    }


class _FakeStatus:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict[str, object]:
        if mode not in {"python", "json"}:
            raise AssertionError("unexpected model dump mode")
        return self.payload


class _FakeStatusType:
    @classmethod
    def model_validate(cls, value: object) -> _FakeStatus:
        if isinstance(value, _FakeStatus):
            return value
        if not isinstance(value, dict):
            raise AssertionError("status must be validated from public data")
        return _FakeStatus(value)


class _FakeAdapterTemplate:
    @classmethod
    def model_validate(cls, value: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(**value)


def _fake_publication(**values: object) -> SimpleNamespace:
    return SimpleNamespace(**values)


def _fake_request(**values: object) -> SimpleNamespace:
    values["component_commits"] = SimpleNamespace(**values["component_commits"])
    values["closed_policy_snapshot"] = SimpleNamespace(
        **values["closed_policy_snapshot"]
    )
    return SimpleNamespace(**values)


def _fake_bindings(**overrides: object) -> SimpleNamespace:
    values = {
        "platform_database_settings": mock.Mock(),
        "create_platform_engine": mock.Mock(),
        "sql_template_repository": mock.Mock(),
        "sql_registration_repository": mock.Mock(),
        "runtime_application_service": mock.Mock(),
        "adapter_template": _FakeAdapterTemplate,
        "committed_template_publication": _fake_publication,
        "ensure_registration_request": _fake_request,
        "registration_status": _FakeStatusType,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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
            mock.patch.object(
                runtime_registry_cli,
                "load_resolved_launch_policy_bundle",
                return_value=_launch_policy(),
            ) as launch_policy_reader,
        ):
            yield (
                commit_reader,
                template_reader,
                artifact_reader,
                policy_reader,
                launch_policy_reader,
            )

    @contextmanager
    def backend_imports_blocked(self):
        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object):
            if name == "sqlalchemy" or name.startswith(("sqlalchemy.", "freqtrade.")):
                raise AssertionError(f"backend import crossed parse boundary: {name}")
            return original_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", side_effect=guarded_import):
            yield

    def test_invalid_raw_arguments_exit_before_any_backend_import(self) -> None:
        with self.backend_imports_blocked():
            code, stdout, stderr = self.run_cli(
                "runtime-registry",
                "compile",
                "--secret",
                "must-not-echo",
            )
        self.assertEqual((code, stdout, stderr), (2, "", "invalid_arguments\n"))

    def test_lifecycle_mutations_fail_closed_without_loading_backend(self) -> None:
        for command in ("start", "stop", "retry", "retire"):
            with (
                self.subTest(command=command),
                mock.patch.object(
                    runtime_registry_cli,
                    "_load_backend_bindings",
                ) as load_bindings,
            ):
                code, stdout, stderr = self.run_cli(
                    "runtime-registry",
                    command,
                    "--actor",
                    "platform-operator",
                    "--instance-id",
                    INSTANCE_ID,
                    "--expected-version",
                    "0",
                    "--idempotency-key",
                    f"paper-{command}-1",
                )
            self.assertEqual(
                (code, stdout, stderr),
                (78, "", "runtime_supervisor_not_enabled\n"),
            )
            load_bindings.assert_not_called()

    def test_every_lifecycle_mutation_requires_closed_typed_arguments(self) -> None:
        invalid_invocations = (
            ("runtime-registry", "start", "--instance-id", INSTANCE_ID),
            (
                "runtime-registry",
                "stop",
                "--actor",
                "platform-operator",
                "--instance-id",
                INSTANCE_ID,
                "--expected-version",
                "-1",
                "--idempotency-key",
                "paper-stop-1",
            ),
            (
                "runtime-registry",
                "retry",
                "--actor",
                "platform-operator",
                "--instance-id",
                INSTANCE_ID,
                "--expected-version",
                "0",
                "--idempotency-key",
                "INVALID",
            ),
            (
                "runtime-registry",
                "retire",
                "--actor",
                "root",
                "--instance-id",
                INSTANCE_ID,
                "--expected-version",
                "0",
                "--idempotency-key",
                "paper-retire-1",
            ),
        )
        for invocation in invalid_invocations:
            with (
                self.subTest(invocation=invocation),
                mock.patch.object(
                    runtime_registry_cli,
                    "_load_backend_bindings",
                ) as load_bindings,
            ):
                code, stdout, stderr = self.run_cli(*invocation)
            self.assertEqual((code, stdout, stderr), (2, "", "invalid_arguments\n"))
            load_bindings.assert_not_called()

    def test_validate_remains_offline_when_backend_imports_are_unavailable(
        self,
    ) -> None:
        with self.patched_evidence(), self.backend_imports_blocked():
            code, stdout, stderr = self.run_cli("runtime-template", "validate")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["status"], "valid")

    def test_option_abbreviations_fail_before_backend_loading(self) -> None:
        invocations = (
            ("runtime-template", "publish", "--a", "platform-operator"),
            ("runtime-registry", "compile", "--a", "platform-operator"),
            ("runtime-registry", "status", "--i", INSTANCE_ID),
        )
        for invocation in invocations:
            with (
                self.subTest(invocation=invocation),
                mock.patch.object(
                    runtime_registry_cli,
                    "_load_backend_bindings",
                ) as load_bindings,
            ):
                code, stdout, stderr = self.run_cli(*invocation)
            self.assertEqual((code, stdout, stderr), (2, "", "invalid_arguments\n"))
            load_bindings.assert_not_called()

    def test_root_commit_file_accepts_only_one_full_lowercase_identity_line(
        self,
    ) -> None:
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
                    self.assertRaisesRegex(
                        ValueError, "^root_commit_identity_invalid$"
                    ),
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

    def test_validate_loads_fixed_evidence_without_loading_backend(self) -> None:
        with (
            self.patched_evidence() as readers,
            mock.patch.object(
                runtime_registry_cli,
                "_load_backend_bindings",
            ) as load_bindings,
        ):
            code, stdout, stderr = self.run_cli("runtime-template", "validate")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(
            stdout,
            json.dumps(json.loads(stdout), separators=(",", ":"), sort_keys=True)
            + "\n",
        )
        self.assertEqual(
            json.loads(stdout),
            {
                "backend_commit": BACKEND_COMMIT,
                "config_blob_digest": "a" * 64,
                "frontend_commit": FRONTEND_COMMIT,
                "launch_policy_catalog_digest": LAUNCH_POLICY_CATALOG_DIGEST,
                "launch_policy_digest": LAUNCH_POLICY_DIGEST,
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
        load_bindings.assert_not_called()
        readers[1].assert_called_once_with(
            runtime_registry_cli.REPOSITORY_ROOT,
            TEMPLATE_ID,
            ROOT_COMMIT,
        )
        readers[4].assert_called_once_with(
            runtime_registry_cli.REPOSITORY_ROOT,
            TEMPLATE_ID,
            ROOT_COMMIT,
        )

    def test_publish_uses_lazy_backend_repository_and_service(self) -> None:
        template = _committed_template()
        engine = mock.Mock()
        repository = object()
        service = mock.Mock()
        service.publish_template.return_value = SimpleNamespace(
            revision_id="template-" + template.digest,
            template=SimpleNamespace(template_id=TEMPLATE_ID),
            payload_digest=template.digest,
            root_commit=ROOT_COMMIT,
            backend_commit=BACKEND_COMMIT,
            frontend_commit=FRONTEND_COMMIT,
            strategies_commit=STRATEGIES_COMMIT,
            status=SimpleNamespace(value="active"),
        )
        bindings = _fake_bindings(
            sql_template_repository=mock.Mock(return_value=repository),
            runtime_application_service=mock.Mock(return_value=service),
        )
        with (
            self.patched_evidence(),
            mock.patch.object(
                runtime_registry_cli,
                "_load_backend_bindings",
                return_value=bindings,
            ),
            mock.patch.object(
                runtime_registry_cli,
                "_create_engine",
                return_value=engine,
            ) as create_engine,
        ):
            code, stdout, stderr = self.run_cli(
                "runtime-template",
                "publish",
                "--actor",
                "platform-operator",
            )
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["status"], "active")
        create_engine.assert_called_once_with(bindings)
        bindings.sql_template_repository.assert_called_once_with(engine)
        bindings.runtime_application_service.assert_called_once_with(
            template_repository=repository
        )
        publication, actor, occurred_at = service.publish_template.call_args.args
        self.assertEqual(actor, "platform-operator")
        self.assertIsNotNone(occurred_at.utcoffset())
        self.assertEqual(publication.template.template_id, TEMPLATE_ID)
        self.assertEqual(publication.backend_commit, BACKEND_COMMIT)
        engine.dispose.assert_called_once_with()

    def test_register_and_compile_use_same_lazy_atomic_service_method(self) -> None:
        for command in ("register-paper-probe", "compile"):
            with self.subTest(command=command):
                engine = mock.Mock()
                repository = object()
                service = mock.Mock()
                service.ensure_paper_probe_registration.return_value = _FakeStatus(
                    _status_payload()
                )
                bindings = _fake_bindings(
                    sql_registration_repository=mock.Mock(return_value=repository),
                    runtime_application_service=mock.Mock(return_value=service),
                )
                with (
                    self.patched_evidence(),
                    mock.patch.object(
                        runtime_registry_cli,
                        "_load_backend_bindings",
                        return_value=bindings,
                    ),
                    mock.patch.object(
                        runtime_registry_cli,
                        "_create_engine",
                        return_value=engine,
                    ),
                ):
                    code, stdout, stderr = self.run_cli(
                        "runtime-registry",
                        command,
                        "--actor",
                        "platform-operator",
                    )
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(json.loads(stdout), _status_payload())
                request, actor, occurred_at = (
                    service.ensure_paper_probe_registration.call_args.args
                )
                self.assertEqual(actor, "platform-operator")
                self.assertIsNotNone(occurred_at.utcoffset())
                self.assertEqual(
                    request.adapter_template_revision_id,
                    "template-" + _committed_template().digest,
                )
                self.assertEqual(request.component_commits.root_commit, ROOT_COMMIT)
                engine.dispose.assert_called_once_with()

    def test_status_uses_lazy_backend_and_fixed_instance(self) -> None:
        engine = mock.Mock()
        repository = object()
        service = mock.Mock()
        service.registration_status.return_value = _FakeStatus(_status_payload())
        bindings = _fake_bindings(
            sql_registration_repository=mock.Mock(return_value=repository),
            runtime_application_service=mock.Mock(return_value=service),
        )
        with (
            mock.patch.object(
                runtime_registry_cli,
                "_load_backend_bindings",
                return_value=bindings,
            ),
            mock.patch.object(
                runtime_registry_cli,
                "_create_engine",
                return_value=engine,
            ),
        ):
            code, stdout, stderr = self.run_cli(
                "runtime-registry",
                "status",
                "--instance-id",
                INSTANCE_ID,
            )
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout), _status_payload())
        service.registration_status.assert_called_once_with(INSTANCE_ID)
        engine.dispose.assert_called_once_with()

    def test_fixed_selectors_and_raw_power_fail_before_backend_loading(self) -> None:
        invocations = (
            ("runtime-template", "publish", "--actor", "other-operator"),
            ("runtime-registry", "compile", "--actor", "other-operator"),
            ("runtime-registry", "status", "--instance-id", "other-instance"),
            ("runtime-template", "validate", "--path", "must-not-echo"),
            ("runtime-registry", "start"),
            ("runtime-registry", "status", "--image", "must-not-echo"),
        )
        for invocation in invocations:
            with (
                self.subTest(invocation=invocation),
                mock.patch.object(
                    runtime_registry_cli,
                    "_load_backend_bindings",
                ) as load_bindings,
            ):
                code, stdout, stderr = self.run_cli(*invocation)
            self.assertEqual((code, stdout, stderr), (2, "", "invalid_arguments\n"))
            load_bindings.assert_not_called()

    def test_application_failure_is_secret_safe_and_disposes_engine(self) -> None:
        secret = "database-secret-that-must-not-leak"
        engine = mock.Mock()
        bindings = _fake_bindings(
            sql_registration_repository=mock.Mock(side_effect=RuntimeError(secret))
        )
        with (
            mock.patch.object(
                runtime_registry_cli,
                "_load_backend_bindings",
                return_value=bindings,
            ),
            mock.patch.object(
                runtime_registry_cli,
                "_create_engine",
                return_value=engine,
            ),
        ):
            code, stdout, stderr = self.run_cli(
                "runtime-registry",
                "status",
                "--instance-id",
                INSTANCE_ID,
            )
        self.assertEqual(
            (code, stdout, stderr),
            (1, "", "runtime_registry_operation_failed\n"),
        )
        self.assertNotIn(secret, stderr)
        engine.dispose.assert_called_once_with()

    def test_database_settings_are_fixed_in_lazy_bindings(self) -> None:
        settings = mock.Mock()
        engine = object()
        bindings = _fake_bindings(
            platform_database_settings=mock.Mock(return_value=settings),
            create_platform_engine=mock.Mock(return_value=engine),
        )
        self.assertIs(runtime_registry_cli._create_engine(bindings), engine)
        bindings.platform_database_settings.assert_called_once_with(
            host="platform-postgres",
            port=5432,
            database="platform",
            username="platform_operator",
            password_file=Path("/run/secrets/database_password"),
        )
        bindings.create_platform_engine.assert_called_once_with(settings)

    @unittest.skipUnless(
        importlib.util.find_spec("pydantic") is not None,
        "backend dependencies unavailable under python -S",
    )
    def test_lazy_bindings_build_real_backend_public_models(self) -> None:
        bindings = runtime_registry_cli._load_backend_bindings()
        evidence = runtime_registry_cli._CommittedEvidence(
            template=_committed_template(),
            artifacts=_artifacts(),
            policies=_policies(),
            launch_policy=_launch_policy(),
        )
        publication = runtime_registry_cli._publication(evidence, bindings)
        request = runtime_registry_cli._registration_request(evidence, bindings)
        self.assertEqual(type(publication).__name__, "CommittedTemplatePublication")
        self.assertEqual(type(request).__name__, "EnsurePaperProbeRegistrationRequest")
        self.assertEqual(publication.template.template_id, TEMPLATE_ID)
        self.assertEqual(request.component_commits.backend_commit, BACKEND_COMMIT)


if __name__ == "__main__":
    unittest.main()
