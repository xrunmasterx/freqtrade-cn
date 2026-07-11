from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import compose_runtime


SERVICES = ["freqtrade", "freqtrade-futures", "freqtrade-research"]
MANIFEST = {"services": [{"name": name} for name in SERVICES]}
IDENTITY = {"FREQTRADE_RUNTIME_UID": 1001, "FREQTRADE_RUNTIME_GID": 1002}


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

    def test_parser_allows_only_supported_actions_and_safe_options(self) -> None:
        cases = (
            (["--profile", "trading", "config", "--quiet", "--format", "json"],),
            (["--profile", "research", "up", "--detach", "--build", "freqtrade-research"],),
            (["down"],),
            (["create", "--force-recreate", "freqtrade"],),
            (["start", "freqtrade"],),
            (["stop", "freqtrade-futures"],),
            (["restart", "freqtrade-research"],),
            (["ps", "--all"],),
            (["logs", "--follow", "--tail", "50", "freqtrade"],),
        )
        for (arguments,) in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(
                    compose_runtime.parse_compose_arguments(arguments, set(SERVICES)),
                    arguments,
                )

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
                        "--print-json",
                    ],
                )

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

        def verify(root: Path, manifest: object) -> dict[str, int]:
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
            mock.patch.object(compose_runtime, "validate_tracked_configs", return_value=[]),
            mock.patch.object(
                compose_runtime, "validate_compose", return_value=["runtime user drift"]
            ),
            mock.patch.object(
                compose_runtime.subprocess, "run", return_value=rendered
            ) as run,
        ):
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


if __name__ == "__main__":
    unittest.main()
