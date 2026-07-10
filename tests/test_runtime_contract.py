from __future__ import annotations

import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tools import runtime_contract


SENTINEL = "__SET_VIA_SECRET_FILE__"
SERVICES = (
    ("freqtrade", "trading", "trading", "config.json", "SampleStrategy"),
    (
        "freqtrade-futures",
        "trading",
        "trading",
        "config.volatility.futures.json",
        "VolatilitySystem",
    ),
    ("freqtrade-research", "research", "research", "config.research.json", None),
)
SECRET_TARGETS = {
    "api_password": "api_password",
    "jwt_secret": "jwt_secret_key",
    "ws_token": "ws_token",
}


def service_entry(
    name: str,
    role: str,
    profile: str,
    config_name: str,
    strategy: str | None,
) -> dict[str, object]:
    database = "trades.sqlite" if role == "trading" else None
    return {
        "name": name,
        "role": role,
        "profile": profile,
        "config_path": f"ft_userdata/user_data/{config_name}",
        "strategy": strategy,
        "state_root": f"ft_userdata/runtime/{name}",
        "database_filename": database,
    }


def secret_source(service_name: str, suffix: str) -> str:
    return f"{service_name.replace('-', '_')}_{suffix}"


def safe_service(entry: dict[str, object], user: str, port: int) -> dict[str, object]:
    name = str(entry["name"])
    role = entry["role"]
    volumes: list[dict[str, object]] = [
        {
            "type": "bind",
            "source": f"/repo/{entry['config_path']}",
            "target": "/freqtrade/config/runtime.json",
            "read_only": True,
            "bind": {"create_host_path": False},
        },
        {
            "type": "bind",
            "source": "/repo/ft_userdata/user_data/strategies",
            "target": "/freqtrade/user_data/strategies",
            "read_only": True,
            "bind": {"create_host_path": False},
        },
        {
            "type": "bind",
            "source": f"/repo/{entry['state_root']}",
            "target": "/freqtrade/state",
            "bind": {"create_host_path": False},
        },
    ]
    command = (
        "trade --logfile /freqtrade/state/logs/runtime.log "
        "--db-url sqlite:////freqtrade/state/trades.sqlite "
        "--config /freqtrade/config/runtime.json "
        "--config /freqtrade/config/trading-safety.json "
        f"--strategy {entry['strategy']}"
    )
    if role == "trading":
        volumes.insert(
            1,
            {
                "type": "bind",
                "source": "/repo/ops/config/trading-safety.json",
                "target": "/freqtrade/config/trading-safety.json",
                "read_only": True,
                "bind": {"create_host_path": False},
            },
        )
    if role == "research":
        volumes.extend(
            [
                {
                    "type": "bind",
                    "source": "/repo/ft_userdata/user_data/research_data",
                    "target": "/freqtrade/user_data/research_data",
                    "read_only": True,
                    "bind": {"create_host_path": False},
                },
                {
                    "type": "bind",
                    "source": f"/repo/{entry['state_root']}/data",
                    "target": "/freqtrade/user_data/data",
                    "bind": {"create_host_path": False},
                },
                {
                    "type": "bind",
                    "source": f"/repo/{entry['state_root']}/backtest_results",
                    "target": "/freqtrade/user_data/backtest_results",
                    "bind": {"create_host_path": False},
                },
            ]
        )
        command = (
            "webserver --logfile /freqtrade/state/logs/runtime.log "
            "--config /freqtrade/config/runtime.json"
        )
    return {
        "user": user,
        "init": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "profiles": [entry["profile"]],
        "volumes": volumes,
        "secrets": [
            {
                "source": secret_source(name, suffix),
                "target": target,
            }
            for suffix, target in SECRET_TARGETS.items()
        ],
        "environment": {
            "FT_API_PASSWORD_FILE": "/run/secrets/api_password",
            "FT_JWT_SECRET_FILE": "/run/secrets/jwt_secret_key",
            "FT_WS_TOKEN_FILE": "/run/secrets/ws_token",
            "HOME": "/freqtrade/state/home",
        },
        "ports": [
            {
                "mode": "ingress",
                "target": 8080,
                "published": str(port),
                "host_ip": "127.0.0.1",
                "protocol": "tcp",
            }
        ],
        "command": command,
    }


def build_safe_contract() -> tuple[dict[str, object], dict[str, object]]:
    entries = [service_entry(*values) for values in SERVICES]
    manifest: dict[str, object] = {"schema_version": 1, "services": entries}
    compose_services = {
        str(entry["name"]): safe_service(entry, "1001:1002", 8081 + index)
        for index, entry in enumerate(entries)
    }
    compose_secrets = {}
    for entry in entries:
        name = str(entry["name"])
        for suffix, filename in SECRET_TARGETS.items():
            source = secret_source(name, suffix)
            compose_secrets[source] = {
                "name": f"freqtrade-cn_{source}",
                "file": f"/repo/ft_userdata/secrets/{name}/{filename}"
            }
    return manifest, {"services": compose_services, "secrets": compose_secrets}


def find_volume(compose: dict[str, object], service_name: str, target: str) -> dict[str, object]:
    service = compose["services"][service_name]
    return next(volume for volume in service["volumes"] if volume.get("target") == target)


class RuntimeComposeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest, self.compose = build_safe_contract()

    def errors(self) -> str:
        return "\n".join(runtime_contract.validate_compose(self.manifest, self.compose))

    def test_accepts_the_minimal_safe_contract(self) -> None:
        self.assertEqual(runtime_contract.validate_compose(self.manifest, self.compose), [])

    def test_rejects_service_not_in_manifest(self) -> None:
        self.compose["services"]["rogue-bot"] = copy.deepcopy(
            self.compose["services"]["freqtrade"]
        )
        self.assertIn("Compose services differ from runtime manifest", self.errors())

    def test_rejects_shared_or_whole_user_data_write_mount(self) -> None:
        service = self.compose["services"]["freqtrade"]
        service["volumes"].append(
            {
                "type": "bind",
                "source": "/repo/ft_userdata/user_data",
                "target": "/freqtrade/user_data",
                "read_only": False,
                "bind": {"create_host_path": False},
            }
        )
        self.assertIn("whole user_data cannot be writable", self.errors())

    def test_rejects_config_strategy_policy_or_research_source_write_mount(self) -> None:
        cases = (
            ("freqtrade", "/freqtrade/config/runtime.json"),
            ("freqtrade", "/freqtrade/config/trading-safety.json"),
            ("freqtrade", "/freqtrade/user_data/strategies"),
            ("freqtrade-research", "/freqtrade/user_data/research_data"),
        )
        for name, target in cases:
            with self.subTest(name=name, target=target):
                _, compose = build_safe_contract()
                find_volume(compose, name, target)["read_only"] = False
                errors = runtime_contract.validate_compose(self.manifest, compose)
                self.assertIn(f"{target} must be read-only", "\n".join(errors))

    def test_rejects_wrong_writable_targets_and_state_sources(self) -> None:
        find_volume(self.compose, "freqtrade", "/freqtrade/state")["read_only"] = True
        self.compose["services"]["freqtrade-futures"]["volumes"].append(
            {
                "type": "bind",
                "source": "/repo/unapproved",
                "target": "/tmp/unapproved",
                "bind": {"create_host_path": False},
            }
        )
        state = find_volume(self.compose, "freqtrade-research", "/freqtrade/state")
        state["source"] = "/repo/ft_userdata/runtime/freqtrade-futures"
        text = self.errors()
        self.assertIn("expected one writable state mount", text)
        self.assertIn("writable mount targets differ from runtime contract", text)
        self.assertIn("state source differs from runtime manifest", text)

    def test_rejects_non_bind_or_auto_created_mount(self) -> None:
        volume = find_volume(self.compose, "freqtrade", "/freqtrade/config/runtime.json")
        volume["type"] = "volume"
        volume["bind"]["create_host_path"] = True
        text = self.errors()
        self.assertIn("all mounts must be bind mounts", text)
        self.assertIn("bind mount must set create_host_path false", text)

    def test_rejects_docker_socket_mount_without_echoing_source(self) -> None:
        secret = "/var/run/docker.sock-secret-value"
        self.compose["services"]["freqtrade"]["volumes"].append(
            {
                "type": "bind",
                "source": secret,
                "target": "/sock",
                "read_only": True,
                "bind": {"create_host_path": False},
            }
        )
        text = self.errors()
        self.assertIn("Docker socket mount is forbidden", text)
        self.assertNotIn(secret, text)

    def test_rejects_reused_or_mismatched_secrets_and_direct_environment(self) -> None:
        futures = self.compose["services"]["freqtrade-futures"]
        futures["secrets"] = copy.deepcopy(self.compose["services"]["freqtrade"]["secrets"])
        self.compose["services"]["freqtrade"]["environment"][
            "FREQTRADE__API_SERVER__PASSWORD"
        ] = "forbidden-value"
        text = self.errors()
        self.assertIn("secret source must be used by one service", text)
        self.assertIn("API secret mapping differs from runtime contract", text)
        self.assertIn("direct secret environment is forbidden", text)
        self.assertNotIn("forbidden-value", text)

    def test_rejects_top_level_secret_set_file_or_extra_environment(self) -> None:
        self.compose["secrets"].pop("freqtrade_ws_token")
        self.compose["secrets"]["rogue"] = {"file": "/private/value"}
        self.compose["secrets"]["freqtrade_api_password"]["file"] = "/wrong/path"
        self.compose["services"]["freqtrade"]["environment"]["EXTRA"] = "private"
        text = self.errors()
        self.assertIn("Compose secrets differ from runtime contract", text)
        self.assertIn("secret file differs from runtime contract", text)
        self.assertIn("environment differs from runtime contract", text)
        self.assertNotIn("/private/value", text)
        self.assertNotIn("private", text)

    def test_rejects_invalid_or_different_runtime_users(self) -> None:
        cases = ("0:1002", "1001:0", "1001", "abc:1002", "-1:1002", "1001:1002:3")
        for user in cases:
            with self.subTest(user=user):
                _, compose = build_safe_contract()
                compose["services"]["freqtrade"]["user"] = user
                self.assertIn(
                    "runtime user must be one non-root uid:gid",
                    "\n".join(runtime_contract.validate_compose(self.manifest, compose)),
                )
        self.compose["services"]["freqtrade-futures"]["user"] = "1003:1004"
        self.assertIn("runtime user must be identical", self.errors())

    def test_rejects_home_or_container_security_baseline_changes(self) -> None:
        service = self.compose["services"]["freqtrade"]
        service["environment"]["HOME"] = "/tmp"
        service["init"] = False
        service["cap_drop"] = ["NET_RAW"]
        service["security_opt"] = []
        text = self.errors()
        self.assertIn("environment differs from runtime contract", text)
        self.assertIn("init must be true", text)
        self.assertIn("cap_drop must be exactly ALL", text)
        self.assertIn("no-new-privileges is required", text)

    def test_rejects_additional_security_options(self) -> None:
        self.compose["services"]["freqtrade"]["security_opt"].append(
            "seccomp=unconfined"
        )
        self.assertIn("security_opt differs from runtime contract", self.errors())

    def test_rejects_non_loopback_duplicate_or_malformed_ports(self) -> None:
        first = self.compose["services"]["freqtrade"]["ports"][0]
        first["host_ip"] = "0.0.0.0"
        second = self.compose["services"]["freqtrade-futures"]["ports"][0]
        second["published"] = "8081"
        second["target"] = 8081
        second["protocol"] = "udp"
        text = self.errors()
        self.assertIn("host port must bind 127.0.0.1", text)
        self.assertIn("published host port must be unique", text)
        self.assertIn("port mapping differs from runtime contract", text)

    def test_rejects_non_numeric_published_port_without_echoing_it(self) -> None:
        secret = "private-host-port-value"
        self.compose["services"]["freqtrade"]["ports"][0]["published"] = secret
        text = self.errors()
        self.assertIn("port mapping differs from runtime contract", text)
        self.assertNotIn(secret, text)

    def test_rejects_safety_config_not_loaded_last_and_bad_database_or_log(self) -> None:
        service = self.compose["services"]["freqtrade"]
        service["command"] = (
            "trade --logfile /tmp/private-log --db-url sqlite:///private.sqlite "
            "--config /freqtrade/config/trading-safety.json "
            "--config /freqtrade/config/runtime.json --strategy SampleStrategy"
        )
        text = self.errors()
        self.assertIn("trading safety config must be last", text)
        self.assertIn("database must live below /freqtrade/state", text)
        self.assertIn("logfile must live below /freqtrade/state/logs", text)
        self.assertNotIn("private-log", text)
        self.assertNotIn("private.sqlite", text)

    def test_rejects_research_database_strategy_or_wrong_writable_mounts(self) -> None:
        service = self.compose["services"]["freqtrade-research"]
        service["command"] += " --db-url sqlite:////freqtrade/state/x --strategy Hidden"
        service["volumes"].pop()
        text = self.errors()
        self.assertIn("research service cannot use a trading database", text)
        self.assertIn("research service cannot select a strategy", text)
        self.assertIn("writable mount targets differ from runtime contract", text)
        self.assertNotIn("Hidden", text)

    def test_rejects_profile_config_source_and_strategy_mismatch(self) -> None:
        service = self.compose["services"]["freqtrade"]
        service["profiles"] = ["research"]
        find_volume(self.compose, "freqtrade", "/freqtrade/config/runtime.json")[
            "source"
        ] = "/repo/private-config.json"
        service["command"] = service["command"].replace("SampleStrategy", "HiddenStrategy")
        text = self.errors()
        self.assertIn("Compose profile differs from runtime manifest", text)
        self.assertIn("config source differs from runtime manifest", text)
        self.assertIn("strategy differs from runtime manifest", text)
        self.assertNotIn("private-config", text)
        self.assertNotIn("HiddenStrategy", text)

    def test_rejects_fullstake_and_additional_profiles(self) -> None:
        entry = service_entry("freqtrade-fullstake", "trading", "trading", "full.json", "Full")
        self.manifest["services"].append(entry)
        self.compose["services"]["freqtrade-fullstake"] = safe_service(entry, "1001:1002", 8084)
        for suffix, filename in SECRET_TARGETS.items():
            source = secret_source("freqtrade-fullstake", suffix)
            self.compose["secrets"][source] = {
                "name": f"freqtrade-cn_{source}",
                "file": f"/repo/ft_userdata/secrets/freqtrade-fullstake/{filename}"
            }
        self.compose["services"]["freqtrade"]["profiles"] = ["trading", "extra"]
        text = self.errors()
        self.assertIn("fullstake service is forbidden", text)
        self.assertIn("additional Compose profiles are forbidden", text)

    def test_malformed_shapes_return_errors_without_exceptions_or_values(self) -> None:
        mutations = (
            ("services", ["private-service-value"]),
            ("secrets", ["private-secret-value"]),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                _, compose = build_safe_contract()
                compose[key] = value
                text = "\n".join(runtime_contract.validate_compose(self.manifest, compose))
                self.assertIn("must be an object", text)
                self.assertNotIn("private", text)

        _, compose = build_safe_contract()
        find_volume(compose, "freqtrade", "/freqtrade/state")["target"] = [
            "private-target-value"
        ]
        text = "\n".join(runtime_contract.validate_compose(self.manifest, compose))
        self.assertIn("volume target must be a string", text)
        self.assertNotIn("private-target-value", text)


class TrackedConfigContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "ft_userdata/user_data").mkdir(parents=True)
        (self.root / "ops/config").mkdir(parents=True)
        self.template = Path("ft_userdata/user_data/config.example.json")
        self.safe_template = {
            "dry_run": True,
            "api_server": {
                "password": SENTINEL,
                "jwt_secret_key": SENTINEL,
                "ws_token": SENTINEL,
            },
            "exchange": {"key": "", "secret": "", "password": None, "uid": ""},
        }
        self.write_json(self.template, self.safe_template)
        self.write_json(
            Path("ops/config/trading-safety.json"),
            {"dry_run": True, "ignore_buying_expired_candle_after": 60},
        )

    def write_json(self, relative: Path, data: object) -> None:
        (self.root / relative).write_text(json.dumps(data), encoding="utf-8")

    def validate(self, tracked: bytes | None = None) -> list[str]:
        output = tracked if tracked is not None else str(self.template).encode() + b"\0"
        completed = subprocess.CompletedProcess([], 0, stdout=output, stderr=b"")
        with mock.patch.object(runtime_contract.subprocess, "run", return_value=completed) as run:
            errors = runtime_contract.validate_tracked_configs(self.root)
        self.assertEqual(
            run.call_args.args[0],
            ["git", "ls-files", "-z", "ft_userdata/user_data/config*.json"],
        )
        self.assertIs(run.call_args.kwargs["check"], True)
        self.assertNotIn("text", run.call_args.kwargs)
        return errors

    def test_accepts_safe_tracked_template_and_exact_policy(self) -> None:
        self.assertEqual(self.validate(), [])

    def test_rejects_tracked_operational_config(self) -> None:
        path = Path("ft_userdata/user_data/config.json")
        self.write_json(path, {"secret": "must-not-leak"})
        text = "\n".join(self.validate(str(path).encode() + b"\0"))
        self.assertIn("tracked operational config is forbidden", text)
        self.assertNotIn("must-not-leak", text)

    def test_rejects_false_or_non_boolean_dry_run(self) -> None:
        for value in (False, 1, "true", None):
            with self.subTest(value=value):
                data = copy.deepcopy(self.safe_template)
                data["dry_run"] = value
                self.write_json(self.template, data)
                self.assertIn("tracked template must be dry-run", "\n".join(self.validate()))

    def test_rejects_api_values_and_nonempty_exchange_secrets_without_leaking(self) -> None:
        data = copy.deepcopy(self.safe_template)
        data["api_server"]["password"] = "api-private-value"
        data["exchange"]["key"] = "exchange-private-value"
        self.write_json(self.template, data)
        text = "\n".join(self.validate())
        self.assertIn("tracked API field must use sentinel", text)
        self.assertIn("tracked exchange field must be empty", text)
        self.assertNotIn("private-value", text)

    def test_rejects_malformed_json_and_wrong_shapes_with_fixed_errors(self) -> None:
        path = self.root / self.template
        path.write_text('{"password":"json-private-value",', encoding="utf-8")
        text = "\n".join(self.validate())
        self.assertIn("tracked template is not valid JSON", text)
        self.assertNotIn("json-private-value", text)
        for data in ([], {"dry_run": True, "api_server": [], "exchange": {}},
                     {"dry_run": True, "api_server": {}, "exchange": []}):
            with self.subTest(data=data):
                self.write_json(self.template, data)
                text = "\n".join(self.validate())
                self.assertIn("must be an object", text)

    def test_rejects_invalid_git_path_bytes_without_decoding_or_leaking(self) -> None:
        text = "\n".join(self.validate(b"ft_userdata/user_data/config.\xff.example.json\0"))
        self.assertEqual(text, "tracked config path encoding is invalid")
        self.assertNotIn("xff", text)

    def test_rejects_policy_malformed_wrong_shape_bool_as_int_or_extra_keys(self) -> None:
        policy_path = self.root / "ops/config/trading-safety.json"
        cases = (
            "not-json-private",
            [],
            {"dry_run": 1, "ignore_buying_expired_candle_after": 60},
            {"dry_run": True, "ignore_buying_expired_candle_after": True},
            {"dry_run": True, "ignore_buying_expired_candle_after": 60, "extra": 1},
        )
        for value in cases:
            with self.subTest(value=value):
                if isinstance(value, str):
                    policy_path.write_text(value, encoding="utf-8")
                else:
                    policy_path.write_text(json.dumps(value), encoding="utf-8")
                text = "\n".join(self.validate())
                self.assertIn("trading safety policy", text)
                self.assertNotIn("not-json-private", text)

    def test_reports_git_and_file_io_failures_with_fixed_errors(self) -> None:
        secret = "private-subprocess-detail"
        with mock.patch.object(
            runtime_contract.subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(2, ["git"], stderr=secret),
        ):
            text = "\n".join(runtime_contract.validate_tracked_configs(self.root))
        self.assertEqual(text, "tracked config inventory failed")
        self.assertNotIn(secret, text)

        (self.root / self.template).unlink()
        text = "\n".join(self.validate())
        self.assertIn("tracked template could not be read", text)


class RuntimeContractCliTests(unittest.TestCase):
    def invoke(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = runtime_contract.main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_configs_only_skips_manifest_and_compose(self) -> None:
        with (
            mock.patch.object(runtime_contract, "validate_tracked_configs", return_value=[]),
            mock.patch.object(runtime_contract, "load_runtime_manifest") as manifest,
            mock.patch.object(runtime_contract.subprocess, "run") as run,
        ):
            result, stdout, stderr = self.invoke(["--check-configs-only"])
        self.assertEqual((result, stdout, stderr), (0, "runtime contract: OK\n", ""))
        manifest.assert_not_called()
        run.assert_not_called()

    def test_default_render_uses_safe_helper_not_direct_docker(self) -> None:
        manifest, compose = build_safe_contract()
        completed = subprocess.CompletedProcess([], 0, json.dumps(compose), "")
        with (
            mock.patch.object(runtime_contract, "validate_tracked_configs", return_value=[]),
            mock.patch.object(runtime_contract, "load_runtime_manifest", return_value=manifest),
            mock.patch.object(runtime_contract.subprocess, "run", return_value=completed) as run,
        ):
            result, stdout, stderr = self.invoke([])
        self.assertEqual((result, stdout, stderr), (0, "runtime contract: OK\n", ""))
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [
                sys.executable,
                str((runtime_contract.REPO_ROOT / "tools/compose_runtime.py").resolve()),
                "--profile",
                "trading",
                "--profile",
                "research",
                "config",
                "--format",
                "json",
            ],
        )
        self.assertNotIn("docker", command)
        self.assertIs(run.call_args.kwargs["check"], True)
        self.assertIs(run.call_args.kwargs["capture_output"], True)
        self.assertIs(run.call_args.kwargs["text"], True)

    def test_compose_json_requires_a_strict_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compose.json"
            for content in ("[]", "null", '"private-value"', "{broken-private"):
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")
                    with mock.patch.object(
                        runtime_contract, "validate_tracked_configs", return_value=[]
                    ):
                        result, stdout, stderr = self.invoke(["--compose-json", str(path)])
                    self.assertEqual(result, 1)
                    self.assertEqual(stdout, "")
                    self.assertEqual(stderr, "error: Compose JSON could not be loaded\n")
                    self.assertNotIn("private", stderr)
                    self.assertNotIn(str(path), stderr)

    def test_deep_json_io_manifest_and_subprocess_failures_are_fixed_and_secret_free(self) -> None:
        secret = "private-failure-detail"
        failures = (
            ("render", subprocess.CalledProcessError(1, ["helper"], stderr=secret)),
            ("render", OSError(secret)),
            ("render", RecursionError(secret)),
            ("manifest", ValueError(secret)),
        )
        for source, failure in failures:
            with self.subTest(source=source, failure=type(failure).__name__):
                patches = [
                    mock.patch.object(
                        runtime_contract, "validate_tracked_configs", return_value=[]
                    ),
                    mock.patch.object(
                        runtime_contract,
                        "load_runtime_manifest",
                        return_value=build_safe_contract()[0],
                    ),
                    mock.patch.object(runtime_contract.subprocess, "run", side_effect=failure),
                ]
                if source == "manifest":
                    patches[1] = mock.patch.object(
                        runtime_contract, "load_runtime_manifest", side_effect=failure
                    )
                    patches[2] = mock.patch.object(runtime_contract.subprocess, "run")
                with patches[0], patches[1], patches[2]:
                    result, stdout, stderr = self.invoke([])
                self.assertEqual(result, 1)
                self.assertEqual(stdout, "")
                expected = (
                    "error: runtime manifest could not be loaded\n"
                    if source == "manifest"
                    else "error: rendered Compose could not be loaded\n"
                )
                self.assertEqual(stderr, expected)
                self.assertNotIn(secret, stderr)

    def test_validation_errors_are_prefixed_and_do_not_echo_values(self) -> None:
        manifest, compose = build_safe_contract()
        compose["services"]["freqtrade"]["environment"][
            "FREQTRADE__API_SERVER__PASSWORD"
        ] = "private-cli-value"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compose.json"
            path.write_text(json.dumps(compose), encoding="utf-8")
            with (
                mock.patch.object(runtime_contract, "validate_tracked_configs", return_value=[]),
                mock.patch.object(runtime_contract, "load_runtime_manifest", return_value=manifest),
            ):
                result, stdout, stderr = self.invoke(["--compose-json", str(path)])
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertTrue(all(line.startswith("error: ") for line in stderr.splitlines()))
        self.assertIn("direct secret environment is forbidden", stderr)
        self.assertNotIn("private-cli-value", stderr)


if __name__ == "__main__":
    unittest.main()
