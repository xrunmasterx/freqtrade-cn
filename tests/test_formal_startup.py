from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from tools import formal_startup


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_SAFETY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "root-safety.yml"


def accepted_trading_transcript() -> str:
    timestamp = "2026-07-11 09:30:19,000"
    return "\n".join(
        (
            f"{timestamp} - freqtrade.worker - INFO - Starting worker 2026.7-dev",
            f"{timestamp} - freqtrade.configuration.load_config - INFO - "
            "Using config: /freqtrade/config/runtime.json ...",
            f"{timestamp} - freqtrade.configuration.load_config - INFO - "
            "Using config: /freqtrade/config/trading-safety.json ...",
            f"{timestamp} - freqtrade.configuration.configuration - INFO - "
            "Runmode set to dry_run.",
            f"{timestamp} - freqtrade.configuration.configuration - INFO - "
            "Using additional Strategy lookup path: /freqtrade/user_data/strategies",
            f'{timestamp} - freqtrade.configuration.configuration - INFO - '
            'Using DB: "sqlite:////freqtrade/state/trades.sqlite"',
            f"{timestamp} - freqtrade.configuration.configuration - INFO - "
            "Using user-data directory: /freqtrade/state ...",
            f"{timestamp} - freqtrade.exchange.check_exchange - INFO - Checking exchange...",
            f"{timestamp} - freqtrade.exchange.exchange - INFO - "
            "Instance is running with dry_run enabled",
            f"{timestamp} - freqtrade - ERROR - "
            "Could not load markets, therefore cannot start. Please investigate "
            "the above error for more details.",
        )
    )


def local_image_available() -> bool:
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", "freqtrade-cn:local"],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


class FormalStartupUnitTests(unittest.TestCase):
    def test_root_safety_runs_formal_startup_after_image_build(self) -> None:
        workflow = ROOT_SAFETY_WORKFLOW.read_text(encoding="utf-8")
        step = (
            "      - name: Verify formal dynamic-UID startup\n"
            "        run: python tools/formal_startup.py verify-all --image freqtrade-cn:local"
        )
        self.assertEqual(workflow.count(step), 1)
        self.assertLess(
            workflow.index("      - name: Build integrated image"), workflow.index(step)
        )

    def test_formal_command_reads_rendered_production_argv(self) -> None:
        rendered = {
            "services": {
                "freqtrade": {
                    "command": [
                        "trade",
                        "--config",
                        "/freqtrade/config/runtime.json",
                        "--config",
                        "/freqtrade/config/trading-safety.json",
                    ]
                }
            }
        }

        self.assertEqual(
            formal_startup.formal_command(rendered, "freqtrade"),
            (
                "trade",
                "--config",
                "/freqtrade/config/runtime.json",
                "--config",
                "/freqtrade/config/trading-safety.json",
            ),
        )
        self.assertEqual(formal_startup.STARTUP_EXPECTATIONS["freqtrade"].command, ())

    def test_offline_command_uses_non_1000_uid_network_none_and_ephemeral_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            probe_root = Path(temporary_directory)
            expectation = replace(
                formal_startup.STARTUP_EXPECTATIONS["freqtrade"],
                command=("trade", "--config", "/freqtrade/config/runtime.json"),
            )
            command = formal_startup.build_offline_docker_command(
                image="freqtrade-cn:local",
                expectation=expectation,
                runtime_uid=12345,
                runtime_gid=12345,
                repo_root=REPO_ROOT,
                probe_root=probe_root,
            )

        self.assertEqual(command[:2], ["docker", "run"])
        self.assertNotIn("--rm", command)
        self.assertIn("--detach", command)
        self.assertIn("--network", command)
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertEqual(command[command.index("--user") + 1], "12345:12345")
        self.assertIn("HOME=/freqtrade/state/home", command)
        mounts = [command[index + 1] for index, token in enumerate(command) if token == "--mount"]
        self.assertTrue(
            any(
                "target=/freqtrade/state" in mount and "readonly" not in mount
                for mount in mounts
            )
        )
        for target in (
            "/freqtrade/config/runtime.json",
            "/freqtrade/config/trading-safety.json",
            "/freqtrade/user_data/strategies",
            "/run/secrets/api_password",
            "/run/secrets/jwt_secret_key",
            "/run/secrets/ws_token",
        ):
            self.assertTrue(
                any(f"target={target}" in mount and "readonly" in mount for mount in mounts),
                target,
            )
        self.assertEqual(command[-len(expectation.command) :], list(expectation.command))

    def test_trading_rejects_userdata_strategy_secret_and_database_failures(self) -> None:
        expectation = formal_startup.STARTUP_EXPECTATIONS["freqtrade"]
        failures = (
            "fatal: FT_API_PASSWORD_FILE is required",
            "fatal: secret policy failed\n"
            "Could not load markets, therefore cannot start. Please investigate the above error",
            "Using user-data directory: /freqtrade/user_data ... Permission denied",
            "Impossible to load Strategy 'SampleStrategy'",
            "sqlalchemy.exc.OperationalError: unable to open database file",
        )

        for output in failures:
            with self.subTest(output=output):
                completed = subprocess.CompletedProcess([], 2, output, "")
                with self.assertRaisesRegex(RuntimeError, "formal startup verification failed"):
                    formal_startup.verify_startup_result(expectation, completed)

    def test_trading_accepts_only_the_named_external_network_boundary(self) -> None:
        expectation = formal_startup.STARTUP_EXPECTATIONS["freqtrade"]
        named_boundary = subprocess.CompletedProcess(
            [],
            2,
            accepted_trading_transcript(),
            "",
        )
        formal_startup.verify_startup_result(expectation, named_boundary)

        contaminated = (
            "Traceback (most recent call last):\nRuntimeError: unrelated failure",
            "AssertionError: startup invariant failed",
            "ConfigurationError: malformed unrelated setting",
            "unknown startup failure",
        )
        failures = (
            "unexpected failure",
            "ExchangeNotAvailable",
            "Permission denied",
            *(
                f"{accepted_trading_transcript()}\n{mutation}"
                for mutation in contaminated
            ),
        )
        for output in failures:
            with self.subTest(output=output):
                completed = subprocess.CompletedProcess([], 2, output, "")
                with self.assertRaises(RuntimeError):
                    formal_startup.verify_startup_result(expectation, completed)

        approved_lines = accepted_trading_transcript().splitlines()
        for insertion in range(len(approved_lines) + 1):
            with self.subTest(unapproved_line_position=insertion):
                mutated_lines = approved_lines.copy()
                mutated_lines.insert(insertion, "UNAPPROVED STARTUP OUTPUT")
                completed = subprocess.CompletedProcess(
                    [], 2, "\n".join(mutated_lines), ""
                )
                with self.assertRaises(RuntimeError):
                    formal_startup.verify_startup_result(expectation, completed)

    def test_research_requires_ping_and_bounded_clean_stop(self) -> None:
        expectation = replace(
            formal_startup.STARTUP_EXPECTATIONS["freqtrade-research"],
            command=("webserver", "--config", "/freqtrade/config/runtime.json"),
        )
        self.assertTrue(expectation.requires_healthcheck)
        self.assertEqual(expectation.accepted_network_error_markers, ())
        with tempfile.TemporaryDirectory() as temporary_directory:
            command = formal_startup.build_offline_docker_command(
                image="freqtrade-cn:local",
                expectation=expectation,
                runtime_uid=12345,
                runtime_gid=12345,
                repo_root=REPO_ROOT,
                probe_root=Path(temporary_directory),
            )
        self.assertIn("--detach", command)
        self.assertIn("--cidfile", command)

    def test_cleanup_stop_or_remove_failure_rejects_success_without_leaking(self) -> None:
        secret = "cleanup-secret-that-must-not-leak"
        success = subprocess.CompletedProcess([], 0, "", "")
        failures = (
            (subprocess.CompletedProcess([], 1, "", secret), success),
            (success, subprocess.CompletedProcess([], 1, "", secret)),
            (subprocess.TimeoutExpired(["docker", "stop"], 10), success),
            (OSError(secret), success),
            (success, subprocess.TimeoutExpired(["docker", "rm"], 10)),
            (success, OSError(secret)),
        )
        for stop_result, remove_result in failures:
            with self.subTest(
                stop_result=type(stop_result).__name__,
                remove_result=type(remove_result).__name__,
            ):
                rendered = subprocess.CompletedProcess(
                    [],
                    0,
                    json.dumps(
                        {"services": {"freqtrade": {"command": ["trade"]}}}
                    ),
                    "",
                )
                results = (
                    rendered,
                    stop_result,
                    remove_result,
                )

                def mark_launched(
                    expectation: formal_startup.StartupExpectation,
                    *,
                    command: list[str],
                    cid_path: Path,
                    timeout_seconds: int,
                ) -> None:
                    cid_path.write_text("container-id", encoding="utf-8")

                with mock.patch.object(
                    formal_startup.subprocess, "run", side_effect=results
                ) as run, mock.patch.object(
                    formal_startup, "_prepare_probe"
                ), mock.patch.object(
                    formal_startup, "build_offline_docker_command", return_value=[]
                ), mock.patch.object(
                    formal_startup, "_verify_trading_startup", side_effect=mark_launched
                ):
                    with self.assertRaises(RuntimeError) as caught:
                        formal_startup.verify_formal_startup(
                            "freqtrade", image="freqtrade-cn:local", repo_root=REPO_ROOT
                        )

                self.assertEqual(run.call_count, 3)
                self.assertEqual(
                    run.call_args_list[1].args[0],
                    ["docker", "stop", "--time", "5", "container-id"],
                )
                self.assertEqual(
                    run.call_args_list[2].args[0],
                    ["docker", "rm", "--force", "container-id"],
                )
                self.assertEqual(
                    str(caught.exception), "freqtrade formal startup verification failed"
                )
                self.assertNotIn(secret, str(caught.exception))

    def test_primary_verification_failure_precedes_cleanup_failures(self) -> None:
        rendered = subprocess.CompletedProcess(
            [],
            0,
            json.dumps({"services": {"freqtrade": {"command": ["trade"]}}}),
            "",
        )
        primary = RuntimeError("freqtrade formal startup verification failed")

        def fail_after_launch(
            expectation: formal_startup.StartupExpectation,
            *,
            command: list[str],
            cid_path: Path,
            timeout_seconds: int,
        ) -> None:
            cid_path.write_text("container-id", encoding="utf-8")
            raise primary

        cleanup_secret = "cleanup-output-that-must-not-leak"
        results = (
            rendered,
            subprocess.CompletedProcess([], 1, "", cleanup_secret),
            OSError(cleanup_secret),
        )
        with mock.patch.object(
            formal_startup.subprocess, "run", side_effect=results
        ) as run, mock.patch.object(
            formal_startup, "_prepare_probe"
        ), mock.patch.object(
            formal_startup, "build_offline_docker_command", return_value=[]
        ), mock.patch.object(
            formal_startup, "_verify_trading_startup", side_effect=fail_after_launch
        ):
            with self.assertRaises(RuntimeError) as caught:
                formal_startup.verify_formal_startup(
                    "freqtrade", image="freqtrade-cn:local", repo_root=REPO_ROOT
                )

        self.assertIs(caught.exception, primary)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(
            run.call_args_list[2].args[0],
            ["docker", "rm", "--force", "container-id"],
        )
        self.assertNotIn(cleanup_secret, str(caught.exception))

    def test_failure_output_is_secret_and_row_safe(self) -> None:
        expectation = formal_startup.STARTUP_EXPECTATIONS["freqtrade"]
        secret = "private-jwt-value"
        row = "trade_id=17 pair=BTC/USDT amount=0.125"
        completed = subprocess.CompletedProcess([], 2, f"{secret}\n{row}", "")

        with self.assertRaises(RuntimeError) as caught:
            formal_startup.verify_startup_result(expectation, completed)

        message = str(caught.exception)
        self.assertEqual(message, "freqtrade formal startup verification failed")
        self.assertNotIn(secret, message)
        self.assertNotIn(row, message)


@unittest.skipUnless(local_image_available(), "freqtrade-cn:local is not built")
class FormalStartupDockerTests(unittest.TestCase):
    def test_all_formal_services_pass_dynamic_uid_contract(self) -> None:
        for service in formal_startup.STARTUP_EXPECTATIONS:
            with self.subTest(service=service):
                formal_startup.verify_formal_startup(
                    service,
                    image="freqtrade-cn:local",
                    repo_root=REPO_ROOT,
                )


if __name__ == "__main__":
    unittest.main()
