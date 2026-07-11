from __future__ import annotations

import copy
import io
import json
import os
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


def safe_service(
    entry: dict[str, object],
    user: str,
    port: int,
    repo_root: Path,
) -> dict[str, object]:
    name = str(entry["name"])
    role = entry["role"]
    container_names = {
        "freqtrade": "freqtrade-cn",
        "freqtrade-futures": "freqtrade-cn-futures",
        "freqtrade-research": "freqtrade-cn-research",
    }
    volumes: list[dict[str, object]] = [
        {
            "type": "bind",
            "source": str((repo_root / str(entry["config_path"])).resolve()),
            "target": "/freqtrade/config/runtime.json",
            "read_only": True,
            "bind": {"create_host_path": False},
        },
        {
            "type": "bind",
            "source": str((repo_root / "ft_userdata/user_data/strategies").resolve()),
            "target": "/freqtrade/user_data/strategies",
            "read_only": True,
            "bind": {"create_host_path": False},
        },
        {
            "type": "bind",
            "source": str((repo_root / str(entry["state_root"])).resolve()),
            "target": "/freqtrade/state",
            "read_only": False,
            "bind": {"create_host_path": False},
        },
    ]
    command = (
        "trade --logfile /freqtrade/state/logs/runtime.log "
        "--db-url sqlite:////freqtrade/state/trades.sqlite "
        "--config /freqtrade/config/runtime.json "
        "--config /freqtrade/config/trading-safety.json "
        "--user-data-dir /freqtrade/state "
        "--strategy-path /freqtrade/user_data/strategies "
        f"--strategy {entry['strategy']}"
    )
    if role == "trading":
        volumes.insert(
            1,
            {
                "type": "bind",
                "source": str((repo_root / "ops/config/trading-safety.json").resolve()),
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
                    "source": str(
                        (repo_root / "ft_userdata/user_data/research_data").resolve()
                    ),
                    "target": "/freqtrade/user_data/research_data",
                    "read_only": True,
                    "bind": {"create_host_path": False},
                },
            ]
        )
        command = (
            "webserver --logfile /freqtrade/state/logs/runtime.log "
            "--config /freqtrade/config/runtime.json "
            "--user-data-dir /freqtrade/state"
        )
    return {
        "build": {"context": str(repo_root.resolve()), "dockerfile": "Dockerfile"},
        "container_name": container_names.get(name, f"freqtrade-cn-{name}"),
        "entrypoint": None,
        "extra_hosts": ["host.docker.internal=host-gateway"],
        "healthcheck": {
            "test": [
                "CMD-SHELL",
                "curl -fsS http://127.0.0.1:8080/api/v1/ping || exit 1",
            ],
            "timeout": "5s",
            "interval": "30s",
            "retries": 3,
            "start_period": "30s",
        },
        "image": "freqtrade-cn:local",
        "user": user,
        "init": True,
        "networks": {"default": None},
        "restart": "unless-stopped",
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


def build_safe_contract(repo_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    entries = [service_entry(*values) for values in SERVICES]
    source_paths = {
        "ops/config/trading-safety.json",
        "ft_userdata/user_data/strategies",
        "ft_userdata/user_data/research_data",
    }
    for entry in entries:
        source_paths.add(str(entry["config_path"]))
        source_paths.add(str(entry["state_root"]))
    for relative in source_paths:
        path = repo_root / relative
        if Path(relative).suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        else:
            path.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"schema_version": 1, "services": entries}
    compose_services = {
        str(entry["name"]): safe_service(entry, "1001:1002", 8081 + index, repo_root)
        for index, entry in enumerate(entries)
    }
    compose_secrets = {}
    for entry in entries:
        name = str(entry["name"])
        for suffix, filename in SECRET_TARGETS.items():
            source = secret_source(name, suffix)
            compose_secrets[source] = {
                "name": f"freqtrade-cn_{source}",
                "file": str(
                    (repo_root / "ft_userdata/secrets" / name / filename).resolve()
                ),
            }
            secret_path = repo_root / "ft_userdata/secrets" / name / filename
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            secret_path.touch()
    return manifest, {
        "name": "freqtrade-cn",
        "networks": {
            "default": {"name": "freqtrade-cn_default", "ipam": {}}
        },
        "secrets": compose_secrets,
        "services": compose_services,
        "x-freqtrade-common": {
            "build": {"context": ".", "dockerfile": "Dockerfile"},
            "cap_drop": ["ALL"],
            "extra_hosts": ["host.docker.internal:host-gateway"],
            "image": "freqtrade-cn:local",
            "init": True,
            "restart": "unless-stopped",
            "security_opt": ["no-new-privileges:true"],
        },
    }


def find_volume(compose: dict[str, object], service_name: str, target: str) -> dict[str, object]:
    service = compose["services"][service_name]
    return next(volume for volume in service["volumes"] if volume.get("target") == target)


class RuntimeComposeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name).resolve()
        self.manifest, self.compose = build_safe_contract(self.root)

    def validate(
        self,
        manifest: dict[str, object] | None = None,
        compose: dict[str, object] | None = None,
    ) -> list[str]:
        return runtime_contract.validate_compose(
            manifest or self.manifest,
            compose or self.compose,
            repo_root=self.root,
        )

    def errors(self) -> str:
        return "\n".join(self.validate())

    def test_accepts_the_minimal_safe_contract(self) -> None:
        self.assertEqual(self.validate(), [])

    def test_requires_state_userdata_and_read_only_strategy_path(self) -> None:
        self.assertEqual(
            getattr(runtime_contract, "EXPECTED_USER_DATA_DIR", None),
            "/freqtrade/state",
        )
        self.assertEqual(
            getattr(runtime_contract, "EXPECTED_STRATEGY_PATH", None),
            "/freqtrade/user_data/strategies",
        )
        for name in ("freqtrade", "freqtrade-futures"):
            with self.subTest(service=name):
                self.assertEqual(
                    runtime_contract.option_values(
                        self.compose["services"][name]["command"].split(),
                        "--user-data-dir",
                    ),
                    ["/freqtrade/state"],
                )
                self.assertEqual(
                    runtime_contract.option_values(
                        self.compose["services"][name]["command"].split(),
                        "--strategy-path",
                    ),
                    ["/freqtrade/user_data/strategies"],
                )
        self.assertEqual(self.validate(), [])

    def test_rejects_duplicate_or_wrong_userdata_and_strategy_paths(self) -> None:
        mutations = (
            (" --user-data-dir /freqtrade/state", "userdata directory"),
            (" --user-data-dir /freqtrade/user_data", "userdata directory"),
            (" --strategy-path /freqtrade/user_data/strategies", "strategy path"),
            (" --strategy-path /freqtrade/state/strategies", "strategy path"),
            (
                " --strategy-path --user-data-dir /freqtrade/state "
                "/freqtrade/user_data/strategies",
                "userdata directory",
            ),
        )
        for suffix, expected_error in mutations:
            with self.subTest(suffix=suffix):
                _, compose = build_safe_contract(self.root)
                compose["services"]["freqtrade"]["command"] += suffix
                self.assertIn(
                    expected_error,
                    "\n".join(self.validate(compose=compose)),
                )

        for option, expected_error in (
            ("--user-data-dir /freqtrade/state", "userdata directory"),
            (
                "--strategy-path /freqtrade/user_data/strategies",
                "strategy path",
            ),
        ):
            with self.subTest(missing=option):
                _, compose = build_safe_contract(self.root)
                command = compose["services"]["freqtrade"]["command"]
                compose["services"]["freqtrade"]["command"] = command.replace(
                    f" {option}", ""
                )
                self.assertIn(
                    expected_error,
                    "\n".join(self.validate(compose=compose)),
                )

    def test_research_uses_state_userdata_without_strategy_path(self) -> None:
        command = self.compose["services"]["freqtrade-research"]["command"].split()
        self.assertEqual(
            runtime_contract.option_values(command, "--user-data-dir"),
            ["/freqtrade/state"],
        )
        self.assertEqual(
            runtime_contract.option_values(command, "--strategy-path"),
            [],
        )
        self.assertEqual(self.validate(), [])

    def test_research_removes_writable_userdata_alias_mounts(self) -> None:
        targets = {
            volume["target"]
            for volume in self.compose["services"]["freqtrade-research"]["volumes"]
        }
        self.assertNotIn("/freqtrade/user_data/data", targets)
        self.assertNotIn("/freqtrade/user_data/backtest_results", targets)
        self.assertEqual(self.validate(), [])

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
                _, compose = build_safe_contract(self.root)
                find_volume(compose, name, target)["read_only"] = False
                errors = self.validate(compose=compose)
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

    def test_rejects_secret_entry_schema_duplicates_and_non_strings(self) -> None:
        cases = (
            {"source": "freqtrade_api_password", "target": "api_password", "uid": "0"},
            {"source": "freqtrade_api_password"},
            {"source": ["private-source"], "target": "api_password"},
        )
        for secret in cases:
            with self.subTest(secret=secret):
                _, compose = build_safe_contract(self.root)
                compose["services"]["freqtrade"]["secrets"][0] = secret
                text = "\n".join(self.validate(compose=compose))
                self.assertIn("secret entry fields differ from runtime contract", text)
                self.assertNotIn("private-source", text)

        secrets = self.compose["services"]["freqtrade"]["secrets"]
        secrets[1] = copy.deepcopy(secrets[0])
        self.assertIn("secret entries must be unique", self.errors())

    def test_rejects_top_level_secret_schema_and_non_string_file(self) -> None:
        definition = self.compose["secrets"]["freqtrade_api_password"]
        definition["external"] = True
        definition["file"] = ["private-file"]
        text = self.errors()
        self.assertIn("secret definition fields differ from runtime contract", text)
        self.assertNotIn("private-file", text)

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
                _, compose = build_safe_contract(self.root)
                compose["services"]["freqtrade"]["user"] = user
                self.assertIn(
                    "runtime user must be one non-root uid:gid",
                    "\n".join(self.validate(compose=compose)),
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

    def test_rejects_privilege_and_namespace_escape_hatches(self) -> None:
        mutations = {
            "privileged": True,
            "cap_add": ["SYS_ADMIN"],
            "devices": ["/dev/private-device"],
            "device_cgroup_rules": ["a *:* rwm"],
            "volumes_from": ["private-container"],
            "network_mode": "bridge",
            "pid": "service:freqtrade-futures",
            "ipc": "shareable",
            "uts": "private-uts",
            "userns_mode": "private-userns",
            "gpus": "all",
            "runtime": "private-runtime",
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                _, compose = build_safe_contract(self.root)
                compose["services"]["freqtrade"][key] = value
                text = "\n".join(self.validate(compose=compose))
                self.assertIn("privilege escalation field is forbidden", text)
                self.assertNotIn("private", text)

    def test_allows_only_explicit_false_privileged_and_empty_cap_add(self) -> None:
        service = self.compose["services"]["freqtrade"]
        service["privileged"] = False
        service["cap_add"] = []
        self.assertEqual(self.validate(), [])
        for value in (None, 0, "false", []):
            with self.subTest(value=value):
                _, compose = build_safe_contract(self.root)
                compose["services"]["freqtrade"]["privileged"] = value
                self.assertIn(
                    "privileged must be false",
                    "\n".join(self.validate(compose=compose)),
                )

    def test_rejects_extra_mounts_and_volume_schema_drift(self) -> None:
        extra = self.root / "extra-read-only"
        extra.mkdir()
        self.compose["services"]["freqtrade"]["volumes"].append(
            {
                "type": "bind",
                "source": str(extra),
                "target": "/tmp/extra",
                "read_only": True,
                "bind": {"create_host_path": False},
            }
        )
        volume = find_volume(
            self.compose, "freqtrade-futures", "/freqtrade/config/runtime.json"
        )
        volume["consistency"] = "cached"
        volume["bind"]["propagation"] = "rshared"
        text = self.errors()
        self.assertIn("volume set differs from runtime contract", text)
        self.assertIn("volume fields differ from runtime contract", text)
        self.assertIn("bind fields differ from runtime contract", text)

    def test_rejects_non_boolean_read_only_and_missing_read_only_mount(self) -> None:
        for value in (None, 0, 1, "false"):
            with self.subTest(value=value):
                _, compose = build_safe_contract(self.root)
                volume = find_volume(
                    compose, "freqtrade", "/freqtrade/config/runtime.json"
                )
                if value is None:
                    volume.pop("read_only")
                else:
                    volume["read_only"] = value
                text = "\n".join(self.validate(compose=compose))
                self.assertIn("read_only must be an exact boolean", text)

    def test_accepts_canonical_missing_read_only_for_writable_mount(self) -> None:
        state = find_volume(self.compose, "freqtrade", "/freqtrade/state")
        state.pop("read_only")
        self.assertEqual(self.validate(), [])

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

    def test_rejects_unknown_service_and_port_fields(self) -> None:
        service = self.compose["services"]["freqtrade"]
        service["private_escape_field"] = "private-service-value"
        service["ports"][0]["name"] = "private-port-value"
        text = self.errors()
        self.assertIn("service fields differ from runtime contract", text)
        self.assertIn("port fields differ from runtime contract", text)
        self.assertNotIn("private-service-value", text)
        self.assertNotIn("private-port-value", text)

    def test_rejects_canonical_service_value_drift(self) -> None:
        cases = (
            ("entrypoint", ["/bin/private-shell"], "entrypoint must be null"),
            ("image", "private-image", "image differs from runtime contract"),
            (
                "build",
                {"context": str(self.root / "private"), "dockerfile": "Dockerfile"},
                "build differs from runtime contract",
            ),
            ("container_name", "private-container", "container name differs"),
            ("restart", "always", "restart policy differs"),
            ("extra_hosts", ["private-host=host-gateway"], "extra_hosts differs"),
            ("networks", {"private": None}, "service networks differ"),
        )
        for field, value, expected_error in cases:
            with self.subTest(field=field):
                _, compose = build_safe_contract(self.root)
                compose["services"]["freqtrade"][field] = value
                text = "\n".join(self.validate(compose=compose))
                self.assertIn(expected_error, text)
                self.assertNotIn("private", text)

        self.compose["services"]["freqtrade"].pop("entrypoint")
        self.assertIn("entrypoint must be null", self.errors())

    def test_rejects_healthcheck_secret_exfiltration_and_schema_drift(self) -> None:
        healthcheck = self.compose["services"]["freqtrade"]["healthcheck"]
        healthcheck["test"] = ["CMD-SHELL", "send CLI_HEALTH_SECRET_MARKER"]
        healthcheck["retries"] = True
        healthcheck["start_interval"] = "1s"
        text = self.errors()
        self.assertIn("healthcheck differs from runtime contract", text)
        self.assertNotIn("CLI_HEALTH_SECRET_MARKER", text)

    def test_rejects_top_level_network_and_schema_drift(self) -> None:
        self.compose["name"] = "private-project"
        self.compose["networks"] = {
            "default": {"name": "private-network", "external": True}
        }
        self.compose["volumes"] = {"private-volume": {"external": True}}
        self.compose["configs"] = {"private-config": {"file": "private"}}
        self.compose["version"] = "3.9"
        self.compose["x-freqtrade-common"]["image"] = "private-image"
        text = self.errors()
        self.assertIn("top-level fields differ from runtime contract", text)
        self.assertIn("Compose project name differs from runtime contract", text)
        self.assertIn("top-level networks differ from runtime contract", text)
        self.assertIn("Compose extension differs from runtime contract", text)
        self.assertNotIn("private", text)

    def test_nested_canonical_schema_types_never_raise(self) -> None:
        mutations = (
            ("build", []),
            ("healthcheck", "private-healthcheck"),
            ("networks", []),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                _, compose = build_safe_contract(self.root)
                compose["services"]["freqtrade"][field] = value
                text = "\n".join(self.validate(compose=compose))
                self.assertIn("runtime contract", text)
                self.assertNotIn("private-healthcheck", text)

        _, compose = build_safe_contract(self.root)
        compose["networks"] = []
        compose["x-freqtrade-common"] = []
        text = "\n".join(self.validate(compose=compose))
        self.assertIn("top-level networks differ from runtime contract", text)
        self.assertIn("Compose extension differs from runtime contract", text)

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

    def test_rejects_wrong_role_executable_and_unsafe_log_paths(self) -> None:
        commands = (
            (
                "freqtrade",
                "webserver --logfile /freqtrade/state/logs/runtime.log "
                "--db-url sqlite:////freqtrade/state/trades.sqlite "
                "--config /freqtrade/config/runtime.json "
                "--config /freqtrade/config/trading-safety.json "
                "--strategy SampleStrategy",
                "trading command must start with trade",
            ),
            (
                "freqtrade-research",
                "trade --logfile /freqtrade/state/logs/runtime.log "
                "--config /freqtrade/config/runtime.json",
                "research command must start with webserver",
            ),
            (
                "freqtrade",
                "trade --logfile /freqtrade/state/logs/../private.log "
                "--db-url sqlite:////freqtrade/state/trades.sqlite "
                "--config /freqtrade/config/runtime.json "
                "--config /freqtrade/config/trading-safety.json "
                "--strategy SampleStrategy",
                "logfile must be a normalized state log path",
            ),
            (
                "freqtrade",
                "trade --logfile /freqtrade/state/logs/ "
                "--db-url sqlite:////freqtrade/state/trades.sqlite "
                "--config /freqtrade/config/runtime.json "
                "--config /freqtrade/config/trading-safety.json "
                "--strategy SampleStrategy",
                "logfile must be a normalized state log path",
            ),
            (
                "freqtrade",
                "trade --logfile /freqtrade/state/logs/private\n.log "
                "--db-url sqlite:////freqtrade/state/trades.sqlite "
                "--config /freqtrade/config/runtime.json "
                "--config /freqtrade/config/trading-safety.json "
                "--strategy SampleStrategy",
                "logfile must be a normalized state log path",
            ),
        )
        for name, command, expected_error in commands:
            with self.subTest(name=name, expected_error=expected_error):
                _, compose = build_safe_contract(self.root)
                compose["services"][name]["command"] = command
                text = "\n".join(self.validate(compose=compose))
                self.assertIn(expected_error, text)
                self.assertNotIn("private.log", text)

    def test_rejects_unsafe_database_path_without_echoing_it(self) -> None:
        service = self.compose["services"]["freqtrade"]
        service["command"] = service["command"].replace(
            "sqlite:////freqtrade/state/trades.sqlite",
            "sqlite:////freqtrade/state/../private.sqlite",
        )
        text = self.errors()
        self.assertIn("database must be a normalized state path", text)
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

    def test_rejects_suffix_traversal_and_wrong_source_types(self) -> None:
        expected = Path(
            find_volume(
                self.compose, "freqtrade", "/freqtrade/config/runtime.json"
            )["source"]
        )
        evil = self.root.parent / "evil-suffix" / expected.relative_to(expected.anchor)
        evil.parent.mkdir(parents=True, exist_ok=True)
        evil.touch()
        find_volume(self.compose, "freqtrade", "/freqtrade/config/runtime.json")[
            "source"
        ] = str(evil)
        self.assertIn("config source differs from runtime manifest", self.errors())

        _, compose = build_safe_contract(self.root)
        volume = find_volume(compose, "freqtrade", "/freqtrade/config/runtime.json")
        source = Path(volume["source"])
        volume["source"] = str(source.parent / "ignored" / ".." / source.name)
        self.assertIn(
            "source path must not contain traversal",
            "\n".join(self.validate(compose=compose)),
        )

        _, compose = build_safe_contract(self.root)
        volume = find_volume(compose, "freqtrade", "/freqtrade/config/runtime.json")
        source = Path(volume["source"])
        source.unlink()
        source.mkdir()
        self.assertIn(
            "source type differs from runtime contract",
            "\n".join(self.validate(compose=compose)),
        )

    def test_rejects_symlinked_source_that_resolves_outside_repo(self) -> None:
        source = Path(
            find_volume(
                self.compose, "freqtrade", "/freqtrade/config/runtime.json"
            )["source"]
        )
        outside = self.root.parent / "outside-private-config.json"
        outside.write_text("private-marker", encoding="utf-8")
        source.unlink()
        try:
            os.symlink(outside, source)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        text = self.errors()
        self.assertIn("symlink source is forbidden", text)
        self.assertNotIn("private-marker", text)

    def test_rejects_fullstake_and_additional_profiles(self) -> None:
        entry = service_entry("freqtrade-fullstake", "trading", "trading", "full.json", "Full")
        self.manifest["services"].append(entry)
        self.compose["services"]["freqtrade-fullstake"] = safe_service(
            entry, "1001:1002", 8084, self.root
        )
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
                _, compose = build_safe_contract(self.root)
                compose[key] = value
                text = "\n".join(self.validate(compose=compose))
                self.assertIn("must be an object", text)
                self.assertNotIn("private", text)

        _, compose = build_safe_contract(self.root)
        find_volume(compose, "freqtrade", "/freqtrade/state")["target"] = [
            "private-target-value"
        ]
        text = "\n".join(self.validate(compose=compose))
        self.assertIn("volume target must be a string", text)
        self.assertNotIn("private-target-value", text)


class TrackedConfigContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        subprocess.run(["git", "init", "--quiet"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "runtime-contract@example.invalid"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Runtime Contract"],
            cwd=self.root,
            check=True,
        )
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

    def run_git(self, *arguments: str, input_bytes: bytes | None = None) -> bytes:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            input=input_bytes,
            capture_output=True,
            check=True,
        ).stdout

    def stage(self, relative: Path) -> None:
        self.run_git("add", "--", relative.as_posix())

    def write_json(self, relative: Path, data: object, *, stage: bool = True) -> None:
        (self.root / relative).write_text(json.dumps(data), encoding="utf-8")
        if stage:
            self.stage(relative)

    def validate(self) -> list[str]:
        return runtime_contract.validate_tracked_configs(self.root)

    def test_accepts_safe_tracked_template_and_exact_policy(self) -> None:
        self.assertEqual(self.validate(), [])

    def test_rejects_tracked_operational_config(self) -> None:
        path = Path("ft_userdata/user_data/config.json")
        self.write_json(path, {"secret": "must-not-leak"})
        text = "\n".join(self.validate())
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
        self.stage(self.template)
        text = "\n".join(self.validate())
        self.assertIn("tracked template is not valid JSON", text)
        self.assertNotIn("json-private-value", text)
        for data in ([], {"dry_run": True, "api_server": [], "exchange": {}},
                     {"dry_run": True, "api_server": {}, "exchange": []}):
            with self.subTest(data=data):
                self.write_json(self.template, data)
                text = "\n".join(self.validate())
                self.assertIn("must be an object", text)

    def test_rejects_malformed_or_invalid_utf8_index_records_without_leaking(self) -> None:
        records = (
            b"malformed-private-record\0",
            b"100644 " + b"0" * 40 + b" 0\tconfig.\xff.example.json\0",
        )
        for record in records:
            with self.subTest(record=record):
                completed = subprocess.CompletedProcess([], 0, stdout=record, stderr=b"")
                with mock.patch.object(
                    runtime_contract.subprocess, "run", return_value=completed
                ):
                    text = "\n".join(runtime_contract.validate_tracked_configs(self.root))
                self.assertIn("tracked config index is malformed", text)
                self.assertNotIn("private-record", text)

    def test_rejects_unicode_control_and_format_characters_in_index_paths(self) -> None:
        markers = ("\n", "\r", "\t", "\x1b", "\x7f", "\u202e", "\ue000", "\u0378")
        for marker in markers:
            with self.subTest(codepoint=f"U+{ord(marker):04X}"):
                path = f"ft_userdata/user_data/config.{marker}.example.json".encode(
                    "utf-8"
                )
                record = b"100644 " + b"0" * 40 + b" 0\t" + path + b"\0"
                completed = subprocess.CompletedProcess(
                    [], 0, stdout=record, stderr=b""
                )
                with mock.patch.object(
                    runtime_contract.subprocess, "run", return_value=completed
                ):
                    errors = runtime_contract.validate_tracked_configs(self.root)
                self.assertEqual(errors, ["tracked config index is malformed"])

    def test_verified_unicode_path_error_is_single_line(self) -> None:
        path = Path("ft_userdata/user_data/config.安全.json")
        self.write_json(path, self.safe_template)
        errors = self.validate()
        matching = [error for error in errors if "tracked operational config" in error]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].splitlines(), [matching[0]])

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
                self.stage(Path("ops/config/trading-safety.json"))
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
        self.assertEqual(self.validate(), [])

    def test_reads_staged_blob_instead_of_safe_worktree_file(self) -> None:
        unsafe = copy.deepcopy(self.safe_template)
        unsafe["api_server"]["password"] = "INDEX_PRIVATE_MARKER"
        self.write_json(self.template, unsafe)
        self.write_json(self.template, self.safe_template, stage=False)
        text = "\n".join(self.validate())
        self.assertIn("tracked API field must use sentinel", text)
        self.assertNotIn("INDEX_PRIVATE_MARKER", text)

        unsafe_policy = {
            "dry_run": False,
            "ignore_buying_expired_candle_after": 60,
            "marker": "POLICY_INDEX_PRIVATE_MARKER",
        }
        policy = Path("ops/config/trading-safety.json")
        self.write_json(policy, unsafe_policy)
        self.write_json(
            policy,
            {"dry_run": True, "ignore_buying_expired_candle_after": 60},
            stage=False,
        )
        text = "\n".join(self.validate())
        self.assertIn("trading safety policy", text)
        self.assertNotIn("POLICY_INDEX_PRIVATE_MARKER", text)

    def test_rejects_config_outside_the_precise_allowed_directory(self) -> None:
        nested = Path("ft_userdata/user_data/nested/config.private.example.json")
        (self.root / nested).parent.mkdir(parents=True)
        self.write_json(nested, self.safe_template)
        text = "\n".join(self.validate())
        self.assertIn("tracked config path is forbidden", text)
        self.assertNotIn("private.example", text)

    def test_rejects_non_regular_mode_and_nonzero_stage(self) -> None:
        oid = self.run_git("hash-object", "-w", "--stdin", input_bytes=b"private-target").strip()
        self.run_git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"120000,{oid.decode('ascii')},{self.template.as_posix()}",
        )
        text = "\n".join(self.validate())
        self.assertIn("tracked config must be a regular stage-0 file", text)
        self.assertNotIn("private-target", text)

        record = (
            b"100644 " + b"0" * 40 + b" 1\t"
            + self.template.as_posix().encode("utf-8") + b"\0"
        )
        completed = subprocess.CompletedProcess([], 0, stdout=record, stderr=b"")
        with mock.patch.object(runtime_contract.subprocess, "run", return_value=completed):
            text = "\n".join(runtime_contract.validate_tracked_configs(self.root))
        self.assertIn("tracked config must be a regular stage-0 file", text)


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
        manifest, compose = build_safe_contract(runtime_contract.REPO_ROOT)
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
                        return_value=build_safe_contract(runtime_contract.REPO_ROOT)[0],
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
        manifest, compose = build_safe_contract(runtime_contract.REPO_ROOT)
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
