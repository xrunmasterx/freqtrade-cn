from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_NETWORK_BOUNDARY = (
    "Could not load markets, therefore cannot start. Please investigate the above error"
)


@dataclass(frozen=True)
class StartupExpectation:
    service: str
    command: tuple[str, ...]
    requires_healthcheck: bool
    accepted_network_error_markers: tuple[str, ...]


STARTUP_EXPECTATIONS = {
    "freqtrade": StartupExpectation(
        service="freqtrade",
        command=(),
        requires_healthcheck=False,
        accepted_network_error_markers=(EXTERNAL_NETWORK_BOUNDARY,),
    ),
    "freqtrade-futures": StartupExpectation(
        service="freqtrade-futures",
        command=(),
        requires_healthcheck=False,
        accepted_network_error_markers=(EXTERNAL_NETWORK_BOUNDARY,),
    ),
    "freqtrade-research": StartupExpectation(
        service="freqtrade-research",
        command=(),
        requires_healthcheck=True,
        accepted_network_error_markers=(),
    ),
}

CONFIG_TEMPLATES = {
    "freqtrade": "ft_userdata/user_data/config.example.json",
    "freqtrade-futures": "ft_userdata/user_data/config.volatility.futures.example.json",
    "freqtrade-research": "ft_userdata/user_data/config.research.example.json",
}
SECRET_NAMES = ("api_password", "jwt_secret_key", "ws_token")
SECRET_ENVIRONMENT = {
    "api_password": "FT_API_PASSWORD_FILE",
    "jwt_secret_key": "FT_JWT_SECRET_FILE",
    "ws_token": "FT_WS_TOKEN_FILE",
}
FORBIDDEN_FAILURE_MARKERS = (
    "fatal:",
    "secret file is unavailable",
    "secret does not meet runtime policy",
    "permission denied",
    "impossible to load strategy",
    "unable to open database file",
    "operationalerror",
)


def formal_command(compose: Mapping[str, Any], service: str) -> tuple[str, ...]:
    try:
        command = compose["services"][service]["command"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{service} formal command is unavailable") from exc
    if not isinstance(command, list) or not command or not all(
        isinstance(argument, str) and argument for argument in command
    ):
        raise ValueError(f"{service} formal command is invalid")
    return tuple(command)


def _mount(source: Path, target: str, *, read_only: bool) -> str:
    option = f"type=bind,source={source.resolve()},target={target}"
    return f"{option},readonly" if read_only else option


def build_offline_docker_command(
    *,
    image: str,
    expectation: StartupExpectation,
    runtime_uid: int,
    runtime_gid: int,
    repo_root: Path,
    probe_root: Path,
) -> list[str]:
    if runtime_uid <= 0 or runtime_gid <= 0 or runtime_uid == 1000 or runtime_gid == 1000:
        raise ValueError("formal startup requires a dynamic non-root identity")

    command = ["docker", "run"]
    if expectation.requires_healthcheck:
        command.extend(["--detach", "--cidfile", str((probe_root / "container.cid").resolve())])
    else:
        command.extend(
            [
                "--detach",
                "--cidfile",
                str((probe_root / "container.cid").resolve()),
            ]
        )
    command.extend(
        [
            "--network",
            "none",
            "--user",
            f"{runtime_uid}:{runtime_gid}",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev",
            "--env",
            "HOME=/freqtrade/state/home",
        ]
    )
    for secret_name in SECRET_NAMES:
        target = f"/run/secrets/{secret_name}"
        command.extend(["--env", f"{SECRET_ENVIRONMENT[secret_name]}={target}"])
    command.extend(
        [
            "--mount",
            _mount(probe_root / "state", "/freqtrade/state", read_only=False),
            "--mount",
            _mount(
                probe_root / "config" / "runtime.json",
                "/freqtrade/config/runtime.json",
                read_only=True,
            ),
            "--mount",
            _mount(
                repo_root / "ops" / "config" / "trading-safety.json",
                "/freqtrade/config/trading-safety.json",
                read_only=True,
            ),
            "--mount",
            _mount(
                repo_root / "ft_userdata" / "user_data" / "strategies",
                "/freqtrade/user_data/strategies",
                read_only=True,
            ),
        ]
    )
    if expectation.service == "freqtrade-research":
        command.extend(
            [
                "--mount",
                _mount(
                    repo_root / "ft_userdata" / "user_data" / "research_data",
                    "/freqtrade/user_data/research_data",
                    read_only=True,
                ),
            ]
        )
    for secret_name in SECRET_NAMES:
        command.extend(
            [
                "--mount",
                _mount(
                    probe_root / "secrets" / secret_name,
                    f"/run/secrets/{secret_name}",
                    read_only=True,
                ),
            ]
        )
    command.extend([image, *expectation.command])
    return command


def verify_startup_result(
    expectation: StartupExpectation,
    completed: subprocess.CompletedProcess[str],
) -> None:
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    normalized = output.casefold()
    if any(marker in normalized for marker in FORBIDDEN_FAILURE_MARKERS):
        raise RuntimeError(f"{expectation.service} formal startup verification failed")
    if expectation.requires_healthcheck:
        if completed.returncode == 0:
            return
    elif completed.returncode != 0 and any(
        marker in output for marker in expectation.accepted_network_error_markers
    ):
        return
    raise RuntimeError(f"{expectation.service} formal startup verification failed")


def verify_formal_startup(
    service: str,
    *,
    image: str,
    repo_root: Path,
    runtime_uid: int = 12345,
    runtime_gid: int = 12345,
    timeout_seconds: int = 45,
) -> None:
    if service not in STARTUP_EXPECTATIONS:
        raise ValueError("unsupported formal service")
    rendered = subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "trading",
            "--profile",
            "research",
            "config",
            "--format",
            "json",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if rendered.returncode != 0:
        raise RuntimeError(f"{service} formal startup verification failed")
    try:
        compose = json.loads(rendered.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{service} formal startup verification failed") from exc
    expectation = replace(
        STARTUP_EXPECTATIONS[service], command=formal_command(compose, service)
    )

    with tempfile.TemporaryDirectory(prefix=f"formal-startup-{service}-") as temporary:
        probe_root = Path(temporary)
        _prepare_probe(expectation, repo_root=repo_root, probe_root=probe_root)
        command = build_offline_docker_command(
            image=image,
            expectation=expectation,
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
            repo_root=repo_root,
            probe_root=probe_root,
        )
        cid_path = probe_root / "container.cid"
        verification_succeeded = False
        try:
            if expectation.requires_healthcheck:
                _verify_research_startup(
                    expectation,
                    command=command,
                    cid_path=cid_path,
                    timeout_seconds=timeout_seconds,
                )
            else:
                _verify_trading_startup(
                    expectation,
                    command=command,
                    cid_path=cid_path,
                    timeout_seconds=timeout_seconds,
                )
            verification_succeeded = True
        finally:
            if cid_path.is_file():
                container_id = cid_path.read_text(encoding="utf-8").strip()
                if container_id:
                    stopped = subprocess.run(
                        ["docker", "stop", "--time", "5", container_id],
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=10,
                    )
                    subprocess.run(
                        ["docker", "rm", "--force", container_id],
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=10,
                    )
                    if verification_succeeded and stopped.returncode != 0:
                        raise RuntimeError(
                            f"{expectation.service} formal startup verification failed"
                        )


def _prepare_probe(
    expectation: StartupExpectation, *, repo_root: Path, probe_root: Path
) -> None:
    config_directory = probe_root / "config"
    secret_directory = probe_root / "secrets"
    state_root = probe_root / "state"
    config_directory.mkdir()
    secret_directory.mkdir()
    for relative in ("", "home", "logs", "data", "backtest_results"):
        directory = state_root / relative
        directory.mkdir(exist_ok=True)
        os.chmod(directory, 0o707)

    template = repo_root / CONFIG_TEMPLATES[expectation.service]
    runtime_config = config_directory / "runtime.json"
    shutil.copyfile(template, runtime_config)
    config = json.loads(runtime_config.read_text(encoding="utf-8"))
    safety = json.loads(
        (repo_root / "ops" / "config" / "trading-safety.json").read_text(
            encoding="utf-8"
        )
    )
    if config.get("dry_run") is not True or safety.get("dry_run") is not True:
        raise RuntimeError(f"{expectation.service} formal startup verification failed")

    for secret_name in SECRET_NAMES:
        secret_path = secret_directory / secret_name
        secret_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        os.chmod(secret_path, 0o604)


def _verify_research_startup(
    expectation: StartupExpectation,
    *,
    command: list[str],
    cid_path: Path,
    timeout_seconds: int,
) -> None:
    launched = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    verify_startup_result(expectation, launched)
    if not cid_path.is_file():
        raise RuntimeError(f"{expectation.service} formal startup verification failed")
    container_id = cid_path.read_text(encoding="utf-8").strip()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        ping = subprocess.run(
            [
                "docker",
                "exec",
                container_id,
                "curl",
                "-fsS",
                "http://127.0.0.1:8080/api/v1/ping",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        if ping.returncode == 0:
            break
        time.sleep(0.5)
    else:
        raise RuntimeError(f"{expectation.service} formal startup verification failed")

def _verify_trading_startup(
    expectation: StartupExpectation,
    *,
    command: list[str],
    cid_path: Path,
    timeout_seconds: int,
) -> None:
    launched = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    if launched.returncode != 0 or not cid_path.is_file():
        raise RuntimeError(f"{expectation.service} formal startup verification failed")
    container_id = cid_path.read_text(encoding="utf-8").strip()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        logs = subprocess.run(
            ["docker", "logs", container_id],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        output = f"{logs.stdout or ''}\n{logs.stderr or ''}"
        if any(marker in output.casefold() for marker in FORBIDDEN_FAILURE_MARKERS):
            raise RuntimeError(f"{expectation.service} formal startup verification failed")
        if any(marker in output for marker in expectation.accepted_network_error_markers):
            verify_startup_result(
                expectation, subprocess.CompletedProcess([], 2, output, "")
            )
            break
        running = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container_id],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        if running.returncode != 0 or running.stdout.strip() != "true":
            raise RuntimeError(f"{expectation.service} formal startup verification failed")
        time.sleep(0.5)
    else:
        raise RuntimeError(f"{expectation.service} formal startup verification failed")

def main(arguments: Sequence[str] | None = None) -> int:
    supplied = list(arguments if arguments is not None else sys.argv[1:])
    if len(supplied) != 3 or supplied[:2] != ["verify-all", "--image"]:
        sys.stderr.write("formal startup: unsupported arguments\n")
        return 64
    image = supplied[2]
    try:
        for service in STARTUP_EXPECTATIONS:
            verify_formal_startup(service, image=image, repo_root=REPO_ROOT)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        sys.stderr.write("formal startup: verification failed\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
