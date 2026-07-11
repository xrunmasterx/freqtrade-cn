from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

if __package__:
    from tools.bootstrap_runtime import build_compose_identity, verify_runtime
    from tools.runtime_manifest import load_runtime_manifest
else:
    from bootstrap_runtime import build_compose_identity, verify_runtime
    from runtime_manifest import load_runtime_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PROFILES = {"trading", "research"}
ALLOWED_ACTIONS = {"config", "up", "down", "create", "start", "stop", "restart", "ps", "logs"}
CI_PROBE_PATHS = {
    "freqtrade": ("/freqtrade/user_data/strategies/.ci-write-probe",),
    "freqtrade-futures": ("/freqtrade/user_data/strategies/.ci-write-probe",),
    "freqtrade-research": (
        "/freqtrade/user_data/strategies/.ci-write-probe",
        "/freqtrade/user_data/research_data/.ci-write-probe",
    ),
}


class UnsupportedArguments(ValueError):
    pass


def _ci_mount_probe(service: str) -> list[str]:
    read_only_paths = CI_PROBE_PATHS.get(service)
    if read_only_paths is None:
        raise UnsupportedArguments
    program = """\
from pathlib import Path

state = Path("/freqtrade/state/.ci-write-probe")
state.write_text("ok", encoding="utf-8")
state.unlink()
for path_text in READ_ONLY_PATHS:
    path = Path(path_text)
    if not path.parent.is_dir():
        raise SystemExit("read-only runtime input is missing")
    try:
        path.write_text("unexpected", encoding="utf-8")
    except OSError:
        continue
    path.unlink(missing_ok=True)
    raise SystemExit("read-only runtime input is writable")
"""
    program = f"READ_ONLY_PATHS = {read_only_paths!r}\n{program}"
    return ["run", "--rm", "--no-deps", "--entrypoint", "python", service, "-c", program]


def parse_compose_arguments(arguments: Sequence[str], services: set[str]) -> list[str]:
    tokens = list(arguments)
    index = 0
    while index < len(tokens) and tokens[index] == "--profile":
        if index + 1 >= len(tokens) or tokens[index + 1] not in ALLOWED_PROFILES:
            raise UnsupportedArguments
        index += 2
    if index < len(tokens) and tokens[index] in {"ci-probe-version", "ci-probe-mounts"}:
        if index != 0 or len(tokens) != 2 or tokens[1] not in services:
            raise UnsupportedArguments
        service = tokens[1]
        if tokens[0] == "ci-probe-version":
            return ["run", "--rm", "--no-deps", service, "--version"]
        return _ci_mount_probe(service)
    if index >= len(tokens) or tokens[index] not in ALLOWED_ACTIONS:
        raise UnsupportedArguments
    action = tokens[index]
    index += 1
    flags = {
        "config": {"--quiet"},
        "up": {"--detach", "--build", "--force-recreate"},
        "down": set(),
        "create": {"--build", "--force-recreate"},
        "start": set(),
        "stop": set(),
        "restart": set(),
        "ps": {"--all"},
        "logs": {"--follow"},
    }[action]
    allow_services = action not in {"config", "down"}
    while index < len(tokens):
        token = tokens[index]
        if token in flags:
            index += 1
            continue
        if action == "config" and token == "--format":
            if index + 1 >= len(tokens) or tokens[index + 1] != "json":
                raise UnsupportedArguments
            index += 2
            continue
        if action == "logs" and token == "--tail":
            if index + 1 >= len(tokens):
                raise UnsupportedArguments
            value = tokens[index + 1]
            if value != "all" and not value.isdecimal():
                raise UnsupportedArguments
            index += 2
            continue
        if allow_services and token in services:
            index += 1
            continue
        raise UnsupportedArguments
    return tokens


def run_compose(
    arguments: Sequence[str],
    *,
    root: Path = REPO_ROOT,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    resolved_root = root.resolve()
    manifest = load_runtime_manifest(resolved_root / "ops/runtime-services.json")
    services = {service["name"] for service in manifest["services"]}
    safe_arguments = parse_compose_arguments(arguments, services)
    identity = verify_runtime(resolved_root, manifest)
    override = json.dumps(build_compose_identity(manifest, identity)) + "\n"
    command = [
        "docker", "compose", "--project-name", "freqtrade-cn",
        "-f", str(resolved_root / "docker-compose.yml"), "-f", "-",
        *safe_arguments,
    ]
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("FREQTRADE_RUNTIME_") and not key.startswith("COMPOSE_")
    }
    return subprocess.run(
        command,
        cwd=resolved_root,
        env=environment,
        input=override,
        text=True,
        capture_output=capture_output,
        check=False,
    )


def render_compose(*, root: Path = REPO_ROOT) -> dict[str, Any]:
    completed = run_compose(
        ["--profile", "trading", "--profile", "research", "config", "--format", "json"],
        root=root,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("compose runtime command failed")
    return json.loads(completed.stdout)


def main(arguments: Sequence[str] | None = None) -> int:
    supplied = list(arguments if arguments is not None else sys.argv[1:])
    try:
        completed = run_compose(supplied)
    except UnsupportedArguments:
        sys.stderr.write("compose runtime: unsupported arguments\n")
        return 64
    except (OSError, ValueError):
        sys.stderr.write("compose runtime: verification failed\n")
        return 78
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
