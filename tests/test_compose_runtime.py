from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import compose_runtime
from tools.committed_build import CommitIdentity
from tools.image_provenance import InspectedImage


SERVICES = ["freqtrade", "freqtrade-futures", "freqtrade-research"]
MANIFEST = {"services": [{"name": name} for name in SERVICES]}
IDENTITY = {"FREQTRADE_RUNTIME_UID": 1001, "FREQTRADE_RUNTIME_GID": 1002}
COMMIT_IDENTITY = CommitIdentity("a" * 40, "b" * 40, "c" * 40)
CHANGED_COMMIT_IDENTITY = CommitIdentity("e" * 40, "b" * 40, "c" * 40)
INSPECTED_IMAGE = InspectedImage(
    "sha256:" + "d" * 64,
    "freqtrade-cn:p0-aaaaaaaaaaaa-bbbbbbbbbbbb-cccccccccccc",
    {},
)


class ComposeRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    def commit_runtime_controls(self) -> None:
        controls = {
            "Dockerfile": "FROM scratch\n",
            "docker/freqtrade_entrypoint.py": "raise SystemExit\n",
            "ops/config/trading-safety.json": json.dumps(
                {"dry_run": True, "ignore_buying_expired_candle_after": 60}
            ),
        }
        for relative, content in controls.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "tests@example.invalid"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Compose Runtime Tests"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.root, check=True)

    def test_parser_exposes_only_approved_public_actions(self) -> None:
        self.assertEqual(
            compose_runtime.ALLOWED_ACTIONS,
            {"config", "up", "down", "stop", "ps", "logs"},
        )
        cases = (
            (["--profile", "trading", "config", "--quiet", "--format", "json"],),
            (["up", "freqtrade-research"],),
            (["down"],),
            (["stop", "freqtrade-futures"],),
            (["ps", "--all"],),
            (["logs", "--follow", "--tail", "50", "freqtrade"],),
        )
        for (arguments,) in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(
                    compose_runtime.parse_compose_arguments(arguments, set(SERVICES)),
                    arguments,
                )

    def test_parser_requires_up_with_exactly_one_approved_service_and_no_flags(self) -> None:
        for service in SERVICES:
            with self.subTest(service=service):
                self.assertEqual(
                    compose_runtime.parse_compose_arguments(["up", service], set(SERVICES)),
                    ["up", service],
                )

        forbidden = (
            ["up"],
            ["up", "unknown-service"],
            ["up", "freqtrade", "freqtrade-futures"],
            ["up", "--detach", "freqtrade"],
            ["up", "--build", "freqtrade"],
            ["up", "--force-recreate", "freqtrade"],
            ["--profile", "trading", "up", "freqtrade"],
        )
        for arguments in forbidden:
            with self.subTest(arguments=arguments):
                with self.assertRaises(compose_runtime.UnsupportedArguments):
                    compose_runtime.parse_compose_arguments(arguments, set(SERVICES))

    def test_parser_rejects_create_start_and_restart_before_docker(self) -> None:
        for action in ("create", "start", "restart"):
            arguments = [action, "freqtrade"]
            with self.subTest(action=action):
                with self.assertRaises(compose_runtime.UnsupportedArguments):
                    compose_runtime.parse_compose_arguments(arguments, set(SERVICES))
                with (
                    mock.patch.object(compose_runtime.subprocess, "run") as run,
                    mock.patch("sys.stderr"),
                ):
                    self.assertEqual(compose_runtime.main(arguments), 64)
                run.assert_not_called()

    def test_up_delegates_to_internal_launcher_with_frozen_service(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        launcher = mock.Mock(return_value=completed)
        with mock.patch.object(
            compose_runtime, "load_runtime_manifest", return_value=MANIFEST
        ):
            result = compose_runtime.run_compose(
                ["up", "freqtrade-futures"],
                root=self.root,
                launch_service=launcher,
            )

        self.assertIs(result, completed)
        launcher.assert_called_once_with("freqtrade-futures", self.root.resolve())

    def test_up_builds_context_inspects_labels_and_launches_exact_image_id(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        context = self.root / "committed"
        with (
            mock.patch.object(
                compose_runtime, "load_runtime_manifest", return_value=MANIFEST
            ),
            mock.patch.object(
                compose_runtime,
                "resolve_commit_identity",
                side_effect=[COMMIT_IDENTITY, COMMIT_IDENTITY],
            ) as resolve,
            mock.patch.object(compose_runtime, "verify_committed_checkout") as verify,
            mock.patch.object(
                compose_runtime, "committed_build_context"
            ) as committed_context,
            mock.patch.object(
                compose_runtime, "build_and_inspect_image", return_value=INSPECTED_IMAGE
            ) as build,
            mock.patch.object(
                compose_runtime, "_launch_inspected_image", return_value=completed
            ) as launch,
        ):
            committed_context.return_value.__enter__.return_value = context
            result = compose_runtime.launch_reviewed_service("freqtrade", self.root)

        self.assertIs(result, completed)
        committed_context.assert_called_once_with(self.root.resolve(), COMMIT_IDENTITY)
        build.assert_called_once_with(context, COMMIT_IDENTITY)
        self.assertEqual(resolve.call_count, 2)
        verify.assert_called_once_with(self.root.resolve(), COMMIT_IDENTITY)
        launch.assert_called_once_with(
            "freqtrade",
            self.root.resolve(),
            MANIFEST,
            INSPECTED_IMAGE.image_id,
            COMMIT_IDENTITY,
        )

    def test_legacy_launch_delegates_to_extracted_snapshot_kernel(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        with (
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(
                compose_runtime,
                "_run_validated_snapshot_launch",
                return_value=completed,
            ) as kernel,
        ):
            result = compose_runtime._launch_inspected_image(
                "freqtrade",
                self.root,
                MANIFEST,
                INSPECTED_IMAGE.image_id,
                COMMIT_IDENTITY,
            )

        self.assertIs(result, completed)
        arguments = kernel.call_args.kwargs
        self.assertEqual(arguments["service"], "freqtrade")
        self.assertEqual(arguments["root"], self.root)
        self.assertEqual(arguments["manifest"], MANIFEST)
        self.assertEqual(arguments["image_id"], INSPECTED_IMAGE.image_id)
        self.assertEqual(arguments["commit_identity"], COMMIT_IDENTITY)
        self.assertIn("services:", arguments["override"])

    def test_extracted_kernel_validates_before_fixed_action_and_cleans_snapshot(
        self,
    ) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        events: list[str] = []
        snapshot_path: Path | None = None

        def validate(
            root,
            manifest,
            command_prefix,
            override,
            environment,
            service,
            image_id,
            snapshot,
            commit_identity,
        ) -> None:
            nonlocal snapshot_path
            snapshot_path = snapshot
            events.append("validate")
            snapshot_path.write_text('{"services":{}}\n', encoding="utf-8")

        def run(command, **kwargs):
            events.append("action")
            self.assertIn("--no-build", command)
            self.assertIn("--no-deps", command)
            self.assertEqual(command[-1], "freqtrade")
            return completed

        with (
            mock.patch.object(compose_runtime, "_validate_launch", side_effect=validate),
            mock.patch.object(compose_runtime.subprocess, "run", side_effect=run),
        ):
            result = compose_runtime._run_validated_snapshot_launch(
                service="freqtrade",
                root=self.root,
                manifest=MANIFEST,
                image_id=INSPECTED_IMAGE.image_id,
                commit_identity=COMMIT_IDENTITY,
                override="services: {}\n",
            )

        self.assertIs(result, completed)
        self.assertEqual(events, ["validate", "action"])
        self.assertIsNotNone(snapshot_path)
        self.assertFalse(snapshot_path.exists())

    def test_up_rejects_identity_change_during_build_before_preflight(self) -> None:
        with (
            mock.patch.object(
                compose_runtime, "load_runtime_manifest", return_value=MANIFEST
            ),
            mock.patch.object(
                compose_runtime,
                "resolve_commit_identity",
                side_effect=[COMMIT_IDENTITY, CHANGED_COMMIT_IDENTITY],
            ),
            mock.patch.object(compose_runtime, "committed_build_context") as context,
            mock.patch.object(
                compose_runtime, "build_and_inspect_image", return_value=INSPECTED_IMAGE
            ),
            mock.patch.object(compose_runtime, "_launch_inspected_image") as launch,
        ):
            context.return_value.__enter__.return_value = self.root / "committed"
            with self.assertRaises(ValueError):
                compose_runtime.launch_reviewed_service("freqtrade", self.root)
        launch.assert_not_called()

    def test_up_uses_fixed_recreate_no_build_no_deps_flags(self) -> None:
        rendered_text = '{"services":{"freqtrade":{"image":"sha256:' + "d" * 64 + '"}}}'
        completed = subprocess.CompletedProcess([], 0, "", "")
        final_snapshot: Path | None = None

        def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            nonlocal final_snapshot
            if command[0] == "git":
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[-3:] == ["config", "--format", "json"]:
                return subprocess.CompletedProcess(command, 0, rendered_text, "")
            final_snapshot = Path(command[command.index("-f") + 1])
            self.assertTrue(final_snapshot.is_file())
            self.assertEqual(final_snapshot.read_text(encoding="utf-8"), rendered_text)
            self.assertNotIn(str(self.root / "docker-compose.yml"), command)
            self.assertIsNone(kwargs["input"])
            return completed

        with (
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(compose_runtime, "validate_tracked_configs", return_value=[]),
            mock.patch.object(compose_runtime, "validate_compose", return_value=[]),
            mock.patch.object(
                compose_runtime, "resolve_commit_identity", return_value=COMMIT_IDENTITY
            ),
            mock.patch.object(compose_runtime, "verify_committed_checkout"),
            mock.patch.object(compose_runtime.subprocess, "run", side_effect=run) as run_mock,
        ):
            result = compose_runtime._launch_inspected_image(
                "freqtrade",
                self.root,
                MANIFEST,
                INSPECTED_IMAGE.image_id,
                COMMIT_IDENTITY,
            )
        self.assertIs(result, completed)
        self.assertIsNotNone(final_snapshot)
        self.assertFalse(final_snapshot.exists())
        self.assertEqual(
            run_mock.call_args.args[0][-9:],
            [
                "up",
                "--detach",
                "--wait",
                "--wait-timeout",
                "180",
                "--force-recreate",
                "--no-build",
                "--no-deps",
                "freqtrade",
            ],
        )

    def test_up_returns_unhealthy_and_timeout_results_unchanged(self) -> None:
        rendered_text = '{"services":{"freqtrade":{}}}'
        for returncode in (1, 124):
            with self.subTest(returncode=returncode):
                completed = subprocess.CompletedProcess([], returncode, "", "failed")

                def run(
                    command: list[str], **_kwargs: object
                ) -> subprocess.CompletedProcess[str]:
                    if command[0] == "git":
                        return subprocess.CompletedProcess(command, 0, "", "")
                    if command[-3:] == ["config", "--format", "json"]:
                        return subprocess.CompletedProcess(command, 0, rendered_text, "")
                    self.assertEqual(
                        command[-9:],
                        [
                            "up",
                            "--detach",
                            "--wait",
                            "--wait-timeout",
                            "180",
                            "--force-recreate",
                            "--no-build",
                            "--no-deps",
                            "freqtrade",
                        ],
                    )
                    return completed

                with (
                    mock.patch.object(
                        compose_runtime, "verify_runtime", return_value=IDENTITY
                    ),
                    mock.patch.object(
                        compose_runtime, "validate_tracked_configs", return_value=[]
                    ),
                    mock.patch.object(compose_runtime, "validate_compose", return_value=[]),
                    mock.patch.object(
                        compose_runtime,
                        "resolve_commit_identity",
                        return_value=COMMIT_IDENTITY,
                    ),
                    mock.patch.object(compose_runtime, "verify_committed_checkout"),
                    mock.patch.object(compose_runtime.subprocess, "run", side_effect=run),
                ):
                    result = compose_runtime._launch_inspected_image(
                        "freqtrade",
                        self.root,
                        MANIFEST,
                        INSPECTED_IMAGE.image_id,
                        COMMIT_IDENTITY,
                    )

                self.assertIs(result, completed)
                launcher = mock.Mock(return_value=completed)
                with mock.patch.object(
                    compose_runtime, "load_runtime_manifest", return_value=MANIFEST
                ):
                    result = compose_runtime.run_compose(
                        ["up", "freqtrade"],
                        root=self.root,
                        launch_service=launcher,
                    )
                self.assertIs(result, completed)
                with mock.patch.object(
                    compose_runtime, "run_compose", return_value=completed
                ):
                    self.assertEqual(
                        compose_runtime.main(["up", "freqtrade"]), returncode
                    )

    def test_launch_uses_validated_snapshot_when_live_compose_changes(self) -> None:
        rendered_text = '{"name":"validated-snapshot"}'
        final_bytes: list[str] = []

        def verify(root: Path, identity: CommitIdentity) -> None:
            (root / "docker-compose.yml").write_text("mutated live source", encoding="utf-8")

        def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if command[0] == "git":
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[-3:] == ["config", "--format", "json"]:
                return subprocess.CompletedProcess(command, 0, rendered_text, "")
            snapshot = Path(command[command.index("-f") + 1])
            final_bytes.append(snapshot.read_text(encoding="utf-8"))
            self.assertNotIn(str(self.root / "docker-compose.yml"), command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with (
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(compose_runtime, "validate_tracked_configs", return_value=[]),
            mock.patch.object(compose_runtime, "validate_compose", return_value=[]),
            mock.patch.object(
                compose_runtime, "resolve_commit_identity", return_value=COMMIT_IDENTITY
            ),
            mock.patch.object(
                compose_runtime, "verify_committed_checkout", side_effect=verify
            ),
            mock.patch.object(compose_runtime.subprocess, "run", side_effect=run),
        ):
            compose_runtime._launch_inspected_image(
                "freqtrade", self.root, MANIFEST, INSPECTED_IMAGE.image_id, COMMIT_IDENTITY
            )
        self.assertEqual(final_bytes, [rendered_text])

    def test_launch_rejects_identity_drift_after_snapshot_validation(self) -> None:
        rendered = subprocess.CompletedProcess([], 0, '{"services":{}}', "")
        with (
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(compose_runtime, "validate_tracked_configs", return_value=[]),
            mock.patch.object(compose_runtime, "validate_compose", return_value=[]),
            mock.patch.object(
                compose_runtime, "resolve_commit_identity", return_value=CHANGED_COMMIT_IDENTITY
            ),
            mock.patch.object(compose_runtime.subprocess, "run", return_value=rendered) as run,
        ):
            with self.assertRaises(ValueError):
                compose_runtime._launch_inspected_image(
                    "freqtrade",
                    self.root,
                    MANIFEST,
                    INSPECTED_IMAGE.image_id,
                    COMMIT_IDENTITY,
                )
        self.assertFalse(any(call.args[0][-1] == "freqtrade" for call in run.call_args_list))

    def test_launch_rejects_control_drift_after_snapshot_validation(self) -> None:
        rendered = subprocess.CompletedProcess([], 0, '{"services":{}}', "")
        controls = [
            subprocess.CompletedProcess([], 0, "", ""),
            rendered,
            subprocess.CompletedProcess([], 1, "", ""),
        ]
        with (
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(compose_runtime, "validate_tracked_configs", return_value=[]),
            mock.patch.object(compose_runtime, "validate_compose", return_value=[]),
            mock.patch.object(
                compose_runtime, "resolve_commit_identity", return_value=COMMIT_IDENTITY
            ),
            mock.patch.object(compose_runtime, "verify_committed_checkout"),
            mock.patch.object(
                compose_runtime.subprocess, "run", side_effect=controls
            ) as run,
        ):
            with self.assertRaises(ValueError):
                compose_runtime._launch_inspected_image(
                    "freqtrade",
                    self.root,
                    MANIFEST,
                    INSPECTED_IMAGE.image_id,
                    COMMIT_IDENTITY,
                )
        self.assertEqual(run.call_count, 3)

    def test_launch_snapshot_is_cleaned_when_final_compose_fails(self) -> None:
        rendered = subprocess.CompletedProcess([], 0, '{"services":{}}', "")
        snapshot: Path | None = None

        def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            nonlocal snapshot
            if command[0] == "git":
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[-3:] == ["config", "--format", "json"]:
                return rendered
            snapshot = Path(command[command.index("-f") + 1])
            raise OSError("final compose failed")

        with (
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(compose_runtime, "validate_tracked_configs", return_value=[]),
            mock.patch.object(compose_runtime, "validate_compose", return_value=[]),
            mock.patch.object(
                compose_runtime, "resolve_commit_identity", return_value=COMMIT_IDENTITY
            ),
            mock.patch.object(compose_runtime, "verify_committed_checkout"),
            mock.patch.object(compose_runtime.subprocess, "run", side_effect=run),
        ):
            with self.assertRaises(OSError):
                compose_runtime._launch_inspected_image(
                    "freqtrade",
                    self.root,
                    MANIFEST,
                    INSPECTED_IMAGE.image_id,
                    COMMIT_IDENTITY,
                )
        self.assertIsNotNone(snapshot)
        self.assertFalse(snapshot.exists())

    def test_up_never_launches_when_build_inspect_or_label_validation_fails(self) -> None:
        for failure in (OSError("build"), ValueError("inspect"), ValueError("labels")):
            with self.subTest(failure=type(failure).__name__):
                with (
                    mock.patch.object(
                        compose_runtime, "resolve_commit_identity", return_value=COMMIT_IDENTITY
                    ),
                    mock.patch.object(compose_runtime, "committed_build_context") as context,
                    mock.patch.object(
                        compose_runtime, "build_and_inspect_image", side_effect=failure
                    ),
                    mock.patch.object(compose_runtime, "_launch_inspected_image") as launch,
                ):
                    context.return_value.__enter__.return_value = self.root / "committed"
                    with self.assertRaises((OSError, ValueError)):
                        compose_runtime.launch_reviewed_service("freqtrade", self.root)
                launch.assert_not_called()

    def test_up_cleans_context_after_every_failure(self) -> None:
        events: list[str] = []

        class Context:
            def __enter__(self) -> Path:
                events.append("enter")
                return self.root / "committed"

            def __init__(self, root: Path) -> None:
                self.root = root

            def __exit__(self, *args: object) -> None:
                events.append("exit")

        with (
            mock.patch.object(
                compose_runtime, "load_runtime_manifest", return_value=MANIFEST
            ),
            mock.patch.object(
                compose_runtime, "resolve_commit_identity", return_value=COMMIT_IDENTITY
            ),
            mock.patch.object(
                compose_runtime, "committed_build_context", return_value=Context(self.root)
            ),
            mock.patch.object(
                compose_runtime, "build_and_inspect_image", side_effect=ValueError("failed")
            ),
        ):
            with self.assertRaises(ValueError):
                compose_runtime.launch_reviewed_service("freqtrade", self.root)
        self.assertEqual(events, ["enter", "exit"])

    def test_emergency_actions_do_not_require_image_provenance(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        with (
            mock.patch.object(compose_runtime, "load_runtime_manifest", return_value=MANIFEST),
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(compose_runtime, "resolve_commit_identity") as resolve,
            mock.patch.object(compose_runtime, "build_and_inspect_image") as build,
            mock.patch.object(compose_runtime.subprocess, "run", return_value=completed),
        ):
            for action in (["down"], ["stop", "freqtrade"], ["ps", "freqtrade"], ["logs", "freqtrade"]):
                compose_runtime.run_compose(action, root=self.root)
        resolve.assert_not_called()
        build.assert_not_called()

    def test_emergency_actions_run_exact_fixed_command_when_manifest_loading_fails(
        self,
    ) -> None:
        cases = (
            (["down"], False),
            (["stop", "freqtrade-futures"], True),
            (["ps", "--all", "freqtrade-research"], False),
            (["logs", "--follow", "--tail", "50", "freqtrade"], True),
        )
        for arguments, capture_output in cases:
            with self.subTest(arguments=arguments):
                completed = subprocess.CompletedProcess([], 17, "output", "error")
                with (
                    mock.patch.object(
                        compose_runtime,
                        "load_runtime_manifest",
                        side_effect=ValueError("missing manifest"),
                    ) as load_manifest,
                    mock.patch.object(
                        compose_runtime,
                        "verify_runtime",
                        side_effect=ValueError("runtime unavailable"),
                    ) as verify_runtime,
                    mock.patch.object(
                        compose_runtime.subprocess, "run", return_value=completed
                    ) as run,
                    mock.patch.dict(
                        os.environ,
                        {
                            "KEEP_ME": "yes",
                            "FREQTRADE_RUNTIME_UID": "1001",
                            "COMPOSE_FILE": "outside.yml",
                        },
                        clear=True,
                    ),
                ):
                    result = compose_runtime.run_compose(
                        arguments,
                        root=self.root,
                        capture_output=capture_output,
                    )

                self.assertIs(result, completed)
                load_manifest.assert_not_called()
                verify_runtime.assert_not_called()
                run.assert_called_once_with(
                    [
                        "docker",
                        "compose",
                        "--project-name",
                        "freqtrade-cn",
                        "-f",
                        str(self.root / "docker-compose.yml"),
                        *arguments,
                    ],
                    cwd=self.root.resolve(),
                    env={"KEEP_ME": "yes"},
                    text=True,
                    capture_output=capture_output,
                    check=False,
                )

    def test_emergency_actions_do_not_call_manifest_or_runtime_verification(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        for arguments in (
            ["down"],
            ["stop", "freqtrade"],
            ["ps", "freqtrade"],
            ["logs", "freqtrade"],
        ):
            with self.subTest(arguments=arguments):
                with (
                    mock.patch.object(
                        compose_runtime,
                        "load_runtime_manifest",
                        side_effect=AssertionError("manifest must not load"),
                    ) as load_manifest,
                    mock.patch.object(
                        compose_runtime,
                        "verify_runtime",
                        side_effect=ValueError("runtime verification failed"),
                    ) as verify_runtime,
                    mock.patch.object(
                        compose_runtime.subprocess, "run", return_value=completed
                    ) as run,
                ):
                    result = compose_runtime.run_compose(arguments, root=self.root)

                self.assertIs(result, completed)
                load_manifest.assert_not_called()
                verify_runtime.assert_not_called()
                run.assert_called_once()

    def test_forbidden_emergency_services_and_flags_fail_before_dependencies_or_docker(
        self,
    ) -> None:
        for arguments in (
            ["stop", "unknown-service"],
            ["stop", "--timeout", "1", "freqtrade"],
            ["down", "freqtrade"],
            ["ps", "--format", "json"],
            ["logs", "--tail", "secret", "freqtrade"],
        ):
            with self.subTest(arguments=arguments):
                with (
                    mock.patch.object(
                        compose_runtime,
                        "load_runtime_manifest",
                        side_effect=ValueError("missing manifest"),
                    ) as load_manifest,
                    mock.patch.object(compose_runtime, "verify_runtime") as verify_runtime,
                    mock.patch.object(compose_runtime.subprocess, "run") as run,
                ):
                    with self.assertRaises(compose_runtime.UnsupportedArguments):
                        compose_runtime.run_compose(arguments, root=self.root)

                load_manifest.assert_not_called()
                verify_runtime.assert_not_called()
                run.assert_not_called()

    def test_non_launch_actions_never_call_internal_launcher(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        launcher = mock.Mock(side_effect=AssertionError("launcher must not run"))
        cases = (
            ["config"],
            ["down"],
            ["stop", "freqtrade"],
            ["ps", "freqtrade"],
            ["logs", "freqtrade"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with (
                    mock.patch.object(
                        compose_runtime, "load_runtime_manifest", return_value=MANIFEST
                    ),
                    mock.patch.object(
                        compose_runtime, "verify_runtime", return_value=IDENTITY
                    ),
                    mock.patch.object(
                        compose_runtime.subprocess, "run", return_value=completed
                    ),
                ):
                    result = compose_runtime.run_compose(
                        arguments,
                        root=self.root,
                        launch_service=launcher,
                    )
                self.assertIs(result, completed)
        launcher.assert_not_called()

    def test_stop_down_ps_and_logs_remain_available_when_launch_validation_fails(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        for arguments in (
            ["stop", "freqtrade"],
            ["down"],
            ["ps", "freqtrade"],
            ["logs", "freqtrade"],
        ):
            with self.subTest(arguments=arguments):
                with (
                    mock.patch.object(
                        compose_runtime, "load_runtime_manifest", return_value=MANIFEST
                    ),
                    mock.patch.object(
                        compose_runtime, "verify_runtime", return_value=IDENTITY
                    ),
                    mock.patch.object(
                        compose_runtime,
                        "_validate_launch",
                        side_effect=ValueError("launch validation failed"),
                    ),
                    mock.patch.object(
                        compose_runtime.subprocess, "run", return_value=completed
                    ),
                ):
                    result = compose_runtime.run_compose(arguments, root=self.root)
                self.assertIs(result, completed)

    def test_parser_rejects_escape_hatches_before_docker(self) -> None:
        forbidden = (
            ["-f", "-"],
            ["--file", "-"],
            ["--project-directory", "outside"],
            ["--env-file", "outside"],
            ["run", "--user", "0", "freqtrade"],
            ["exec", "freqtrade", "sh"],
            ["up", "--privileged"],
            ["up", "--volume", "host:/container"],
            ["up", "--entrypoint", "sh"],
            ["up", "--env", "X=Y"],
            ["--profile", "unsafe-experiments", "config"],
            ["up", "unknown-service"],
        )
        for arguments in forbidden:
            with self.subTest(arguments=arguments):
                with self.assertRaises(compose_runtime.UnsupportedArguments):
                    compose_runtime.parse_compose_arguments(arguments, set(SERVICES))
                with (
                    mock.patch.object(compose_runtime.subprocess, "run") as run,
                    mock.patch("sys.stderr") as stderr,
                ):
                    result = compose_runtime.main(arguments)
                self.assertEqual(result, 64)
                run.assert_not_called()
                self.assertEqual(
                    "".join(call.args[0] for call in stderr.write.call_args_list),
                    "compose runtime: unsupported arguments\n",
                )

    def test_ci_version_probe_expands_to_fixed_compose_run(self) -> None:
        self.assertEqual(
            compose_runtime.parse_compose_arguments(
                ["ci-probe-version", "freqtrade-futures"], set(SERVICES)
            ),
            ["run", "--rm", "--no-deps", "freqtrade-futures", "--version"],
        )

    def test_ci_mount_probe_expands_to_fixed_python_program(self) -> None:
        arguments = compose_runtime.parse_compose_arguments(
            ["ci-probe-mounts", "freqtrade-research"], set(SERVICES)
        )

        self.assertEqual(
            arguments[:7],
            [
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "python",
                "freqtrade-research",
                "-c",
            ],
        )
        program = arguments[7]
        self.assertIn("/freqtrade/state/.ci-write-probe", program)
        self.assertIn("/freqtrade/user_data/strategies/.ci-write-probe", program)
        self.assertIn("/freqtrade/user_data/research_data/.ci-write-probe", program)
        self.assertIn("if not path.parent.is_dir()", program)

    def test_ci_probes_reject_unknown_services_and_all_extra_arguments(self) -> None:
        forbidden = (
            ["ci-probe-version"],
            ["ci-probe-version", "unknown-service"],
            ["ci-probe-version", "freqtrade", "--user", "0"],
            ["ci-probe-mounts"],
            ["ci-probe-mounts", "unknown-service"],
            ["ci-probe-mounts", "freqtrade", "--entrypoint", "sh"],
            ["ci-probe-mounts", "freqtrade", "--volume", "host:/container"],
            ["ci-probe-mounts", "freqtrade", "--env", "X=Y"],
            ["ci-probe-mounts", "freqtrade", "--cap-add", "ALL"],
        )
        for arguments in forbidden:
            with self.subTest(arguments=arguments):
                with self.assertRaises(compose_runtime.UnsupportedArguments):
                    compose_runtime.parse_compose_arguments(arguments, set(SERVICES))

    def test_state_check_expands_to_fixed_freqtrade_command(self) -> None:
        for service in ("freqtrade", "freqtrade-futures"):
            with self.subTest(service=service):
                self.assertEqual(
                    compose_runtime.parse_compose_arguments(
                        ["check-state", service], set(SERVICES)
                    ),
                    [
                        "run",
                        "--rm",
                        "--no-deps",
                        service,
                        "show-trades",
                        "--db-url",
                        "sqlite:////freqtrade/state/trades.sqlite",
                        "--config",
                        "/freqtrade/config/runtime.json",
                        "--config",
                        "/freqtrade/config/trading-safety.json",
                        "--user-data-dir",
                        "/freqtrade/state",
                        "--print-json",
                    ],
                )

    def test_state_check_reuses_formal_userdata_contract(self) -> None:
        with mock.patch.object(
            compose_runtime,
            "EXPECTED_USER_DATA_DIR",
            "/contract-userdata",
            create=True,
        ):
            arguments = compose_runtime.parse_compose_arguments(
                ["check-state", "freqtrade"], set(SERVICES)
            )

        index = arguments.index("--user-data-dir")
        self.assertEqual(arguments[index + 1], "/contract-userdata")

    def test_state_check_rejects_research_unknown_and_extra_arguments(self) -> None:
        forbidden = (
            ["check-state"],
            ["check-state", "freqtrade-research"],
            ["check-state", "unknown-service"],
            ["check-state", "freqtrade", "--user", "0"],
            ["check-state", "freqtrade", "--db-url", "sqlite:///outside"],
            ["check-state", "freqtrade", "--entrypoint", "sh"],
            ["check-state", "freqtrade", "--volume", "host:/container"],
            ["check-state", "freqtrade", "--env", "X=Y"],
            ["check-state", "freqtrade", "--cap-add", "ALL"],
        )
        for arguments in forbidden:
            with self.subTest(arguments=arguments):
                with self.assertRaises(compose_runtime.UnsupportedArguments):
                    compose_runtime.parse_compose_arguments(arguments, set(SERVICES))

    def test_run_uses_verified_in_memory_override_and_clean_environment(self) -> None:
        completed = subprocess.CompletedProcess([], 17, "", "")
        with (
            mock.patch.object(compose_runtime, "load_runtime_manifest", return_value=MANIFEST),
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(compose_runtime.subprocess, "run", return_value=completed) as run,
            mock.patch.dict(
                os.environ,
                {
                    "KEEP_ME": "yes",
                    "FREQTRADE_RUNTIME_UID": "1001",
                    "FREQTRADE_RUNTIME_EXTRA": "bad",
                    "COMPOSE_FILE": "bad.yml",
                    "COMPOSE_PROFILES": "bad",
                    "COMPOSE_PROJECT_NAME": "bad",
                },
                clear=True,
            ),
        ):
            result = compose_runtime.run_compose(
                ["--profile", "trading", "config"],
                root=self.root,
            )

        self.assertIs(result, completed)
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [
                "docker",
                "compose",
                "--project-name",
                "freqtrade-cn",
                "-f",
                str(self.root / "docker-compose.yml"),
                "-f",
                "-",
                "--profile",
                "trading",
                "config",
            ],
        )
        options = run.call_args.kwargs
        self.assertNotIn("shell", options)
        self.assertEqual(options["cwd"], self.root.resolve())
        self.assertEqual(options["env"], {"KEEP_ME": "yes"})
        self.assertEqual(
            json.loads(options["input"]),
            {
                "services": {
                    name: {"user": "1001:1002"} for name in SERVICES
                }
            },
        )

    def test_verified_identity_is_not_reread_from_replaced_override(self) -> None:
        override = self.root / "ft_userdata/runtime/compose.identity.yml"
        override.parent.mkdir(parents=True)
        override.write_text("verified artifact", encoding="utf-8")

        def verify(
            root: Path,
            manifest: object,
            *,
            verify_platform_secrets: bool = True,
        ) -> dict[str, int]:
            self.assertFalse(verify_platform_secrets)
            override.write_text('{"services":{"freqtrade":{"user":"0:0"}}}', encoding="utf-8")
            return IDENTITY

        completed = subprocess.CompletedProcess([], 0, "", "")
        with (
            mock.patch.object(compose_runtime, "load_runtime_manifest", return_value=MANIFEST),
            mock.patch.object(compose_runtime, "verify_runtime", side_effect=verify),
            mock.patch.object(compose_runtime.subprocess, "run", return_value=completed) as run,
        ):
            compose_runtime.run_compose(["config"], root=self.root)
        users = json.loads(run.call_args.kwargs["input"])["services"]
        self.assertTrue(all(service["user"] == "1001:1002" for service in users.values()))

    def test_launch_rejects_worktree_safety_policy_drift_before_docker(self) -> None:
        self.commit_runtime_controls()
        (self.root / "ops/config/trading-safety.json").write_text(
            json.dumps({"dry_run": False, "ignore_buying_expired_candle_after": 60}),
            encoding="utf-8",
        )
        original_run = subprocess.run

        def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if command[0] == "git":
                return original_run(command, **kwargs)
            raise AssertionError("Docker must not run after runtime control drift")

        with (
            mock.patch.object(compose_runtime, "load_runtime_manifest", return_value=MANIFEST),
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(compose_runtime.subprocess, "run", side_effect=run),
        ):
            with self.assertRaises(ValueError):
                compose_runtime.run_compose(["up", "freqtrade"], root=self.root)

    def test_launch_rejects_rendered_compose_drift_before_action(self) -> None:
        self.commit_runtime_controls()
        rendered = subprocess.CompletedProcess(
            [], 0, '{"services":{"freqtrade":{"user":"0:0"}}}', ""
        )
        with (
            mock.patch.object(compose_runtime, "load_runtime_manifest", return_value=MANIFEST),
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(
                compose_runtime, "resolve_commit_identity", return_value=COMMIT_IDENTITY
            ),
            mock.patch.object(compose_runtime, "verify_committed_checkout"),
            mock.patch.object(compose_runtime, "committed_build_context") as context,
            mock.patch.object(
                compose_runtime, "build_and_inspect_image", return_value=INSPECTED_IMAGE
            ),
            mock.patch.object(compose_runtime, "validate_tracked_configs", return_value=[]),
            mock.patch.object(
                compose_runtime, "validate_compose", return_value=["runtime user drift"]
            ),
            mock.patch.object(
                compose_runtime.subprocess, "run", return_value=rendered
            ) as run,
        ):
            context.return_value.__enter__.return_value = self.root / "committed"
            with self.assertRaises(ValueError):
                compose_runtime.run_compose(["up", "freqtrade"], root=self.root)

        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[1].args[0][-3:], ["config", "--format", "json"]
        )

    def test_emergency_stop_remains_available_with_control_drift(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        with (
            mock.patch.object(compose_runtime, "load_runtime_manifest", return_value=MANIFEST),
            mock.patch.object(compose_runtime, "verify_runtime", return_value=IDENTITY),
            mock.patch.object(
                compose_runtime.subprocess, "run", return_value=completed
            ) as run,
        ):
            result = compose_runtime.run_compose(["stop", "freqtrade"], root=self.root)

        self.assertIs(result, completed)
        run.assert_called_once()

    def test_main_rejects_unsupported_arguments_with_fixed_error(self) -> None:
        with (
            mock.patch.object(compose_runtime.subprocess, "run") as run,
            mock.patch("sys.stderr") as stderr,
        ):
            result = compose_runtime.main(["run", "--user", "0", "secret-input"])
        self.assertEqual(result, 64)
        run.assert_not_called()
        message = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertEqual(message, "compose runtime: unsupported arguments\n")
        self.assertNotIn("secret-input", message)

    def test_main_returns_fixed_verification_error_without_leaking_details(self) -> None:
        secret = "detail-that-must-not-leak"
        with (
            mock.patch.object(compose_runtime, "run_compose", side_effect=ValueError(secret)),
            mock.patch("sys.stderr") as stderr,
        ):
            result = compose_runtime.main(["config"])
        self.assertEqual(result, 78)
        message = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertEqual(message, "compose runtime: verification failed\n")
        self.assertNotIn(secret, message)

    def test_platform_parser_allows_only_exact_config_commands(self) -> None:
        accepted = (
            ["--profile", "platform", "config"],
            ["--profile", "platform", "config", "--quiet"],
            ["--profile", "platform", "config", "--format", "json"],
            [
                "--profile",
                "platform",
                "config",
                "--quiet",
                "--format",
                "json",
            ],
            [
                "--profile",
                "platform",
                "config",
                "--format",
                "json",
                "--quiet",
            ],
            [
                "--profile",
                "platform",
                "--profile",
                "platform-operator",
                "config",
                "--format",
                "json",
            ],
        )
        for arguments in accepted:
            with self.subTest(arguments=arguments):
                self.assertEqual(compose_runtime.parse_platform_arguments(arguments), arguments)

        forbidden = (
            ["--profile", "platform", "up", "platform-control"],
            ["--profile", "platform", "config", "platform-control"],
            ["--profile", "platform", "config", "--format", "yaml"],
            ["--profile", "platform", "--profile", "trading", "config"],
            ["--profile", "platform-operator", "--profile", "platform", "config"],
            ["--profile", "trading", "--profile", "platform", "config"],
            ["--profile", "platform", "config", "--quiet", "--quiet"],
            ["config"],
        )
        for arguments in forbidden:
            with self.subTest(arguments=arguments):
                with self.assertRaises(compose_runtime.UnsupportedArguments):
                    compose_runtime.parse_platform_arguments(arguments)

    def test_platform_config_bypasses_legacy_bootstrap_and_manifest(self) -> None:
        completed = subprocess.CompletedProcess([], 0, '{"services":{}}', "")
        with (
            mock.patch.object(
                compose_runtime, "_run_platform_compose", return_value=completed
            ) as run_platform,
            mock.patch.object(compose_runtime, "verify_runtime") as verify_runtime,
            mock.patch.object(compose_runtime, "load_runtime_manifest") as load_manifest,
        ):
            result = compose_runtime.run_compose(
                ["--profile", "platform", "config", "--format", "json"],
                root=self.root,
                capture_output=True,
            )
        self.assertIs(result, completed)
        run_platform.assert_called_once()
        verify_runtime.assert_not_called()
        load_manifest.assert_not_called()

    def test_render_platform_compose_parses_strict_json_object(self) -> None:
        completed = subprocess.CompletedProcess([], 0, '{"services":{}}', "")
        with mock.patch.object(
            compose_runtime, "run_compose", return_value=completed
        ) as run:
            self.assertEqual(compose_runtime.render_platform_compose(root=self.root), {"services": {}})
        self.assertEqual(
            run.call_args.args[0],
            [
                "--profile",
                "platform",
                "--profile",
                "platform-operator",
                "config",
                "--format",
                "json",
            ],
        )

        for output in ("[]", "null", "{broken"):
            with self.subTest(output=output), mock.patch.object(
                compose_runtime,
                "run_compose",
                return_value=subprocess.CompletedProcess([], 0, output, ""),
            ):
                with self.assertRaises(RuntimeError):
                    compose_runtime.render_platform_compose(root=self.root)


if __name__ == "__main__":
    unittest.main()
