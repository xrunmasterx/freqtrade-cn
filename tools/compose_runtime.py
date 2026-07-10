from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

if __package__:
    from tools.bootstrap_runtime import (
        COMPOSE_IDENTITY_RELATIVE_PATH,
        RUNTIME_IDENTITY_KEYS,
        verify_runtime,
    )
    from tools.runtime_manifest import load_runtime_manifest
else:
    from bootstrap_runtime import (  # type: ignore[no-redef]
        COMPOSE_IDENTITY_RELATIVE_PATH,
        RUNTIME_IDENTITY_KEYS,
        verify_runtime,
    )
    from runtime_manifest import load_runtime_manifest  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_compose(
    arguments: Sequence[str],
    *,
    root: Path = REPO_ROOT,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    resolved_root = root.resolve()
    manifest = load_runtime_manifest(resolved_root / "ops/runtime-services.json")
    verify_runtime(resolved_root, manifest)
    override = resolved_root / COMPOSE_IDENTITY_RELATIVE_PATH
    command = [
        "docker",
        "compose",
        "-f",
        str(resolved_root / "docker-compose.yml"),
        "-f",
        str(override),
        *arguments,
    ]
    environment = os.environ.copy()
    for key in RUNTIME_IDENTITY_KEYS:
        environment.pop(key, None)
    return subprocess.run(
        command,
        cwd=resolved_root,
        env=environment,
        text=True,
        capture_output=capture_output,
        check=False,
    )


def render_compose(*, root: Path = REPO_ROOT) -> dict[str, Any]:
    completed = run_compose(
        [
            "--profile",
            "trading",
            "--profile",
            "research",
            "config",
            "--format",
            "json",
        ],
        root=root,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("compose runtime command failed")
    return json.loads(completed.stdout)


def main(arguments: Sequence[str] | None = None) -> int:
    try:
        completed = run_compose(list(arguments if arguments is not None else sys.argv[1:]))
    except (OSError, ValueError):
        sys.stderr.write("compose runtime: verification failed\n")
        return 78
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
