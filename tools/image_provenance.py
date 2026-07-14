from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

if __package__:
    from tools.committed_build import (
        CommitIdentity,
        committed_build_context,
        resolve_commit_identity,
    )
else:
    from committed_build import (
        CommitIdentity,
        committed_build_context,
        resolve_commit_identity,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
LABEL_PREFIX = "org.freqtrade-cn.revision."
IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class InspectedImage:
    image_id: str
    tag: str
    labels: Mapping[str, str]


def provenance_tag(identity: CommitIdentity) -> str:
    return (
        f"freqtrade-cn:p0-{identity.root[:12]}-{identity.backend[:12]}-"
        f"{identity.frontend[:12]}"
    )


def operator_provenance_tag(identity: CommitIdentity) -> str:
    return (
        f"freqtrade-cn-operator:p0-{identity.root[:12]}-{identity.backend[:12]}-"
        f"{identity.frontend[:12]}"
    )


def expected_labels(identity: CommitIdentity) -> dict[str, str]:
    return {
        f"{LABEL_PREFIX}root": identity.root,
        f"{LABEL_PREFIX}backend": identity.backend,
        f"{LABEL_PREFIX}frontend": identity.frontend,
    }


def build_committed_image(
    context: Path, identity: CommitIdentity, *, timeout_seconds: int = 1800
) -> str:
    tag = provenance_tag(identity)
    command = ["docker", "build", "--tag", tag]
    for name, value in expected_labels(identity).items():
        command.extend(["--label", f"{name}={value}"])
    command.append(str(context))
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("Docker image build failed") from None
    return tag


def build_committed_operator_image(
    context: Path, identity: CommitIdentity, *, timeout_seconds: int = 1800
) -> str:
    tag = operator_provenance_tag(identity)
    command = [
        "docker",
        "build",
        "--tag",
        tag,
        "--target",
        "platform-operator-image",
        "--build-arg",
        f"PLATFORM_OPERATOR_ROOT_COMMIT={identity.root}",
    ]
    for name, value in expected_labels(identity).items():
        command.extend(["--label", f"{name}={value}"])
    command.append(str(context))
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("Docker operator image build failed") from None
    return tag


def inspect_image(reference: str) -> InspectedImage:
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", reference],
            check=True,
            capture_output=True,
            text=True,
        )
        records = json.loads(completed.stdout)
    except (
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        RecursionError,
    ):
        raise ValueError("Docker image inspection failed") from None
    if type(records) is not list or len(records) != 1 or type(records[0]) is not dict:
        raise ValueError("Docker image inspection returned an invalid result")
    record = records[0]
    image_id = record.get("Id")
    config = record.get("Config")
    labels = config.get("Labels") if type(config) is dict else None
    if not isinstance(image_id, str) or IMAGE_ID_PATTERN.fullmatch(image_id) is None:
        raise ValueError("Docker image inspection returned an invalid image ID")
    if type(labels) is not dict or not all(
        isinstance(name, str) and isinstance(value, str) for name, value in labels.items()
    ):
        raise ValueError("Docker image inspection returned invalid labels")
    return InspectedImage(image_id=image_id, tag=reference, labels=dict(labels))


def verify_image_provenance(image: InspectedImage, identity: CommitIdentity) -> None:
    if image.tag != provenance_tag(identity):
        raise ValueError("Docker image tag does not match committed revisions")
    identity_labels = {
        name: value for name, value in image.labels.items() if name.startswith(LABEL_PREFIX)
    }
    if identity_labels != expected_labels(identity):
        raise ValueError("Docker image labels do not match committed revisions")


def verify_operator_image_provenance(
    image: InspectedImage, identity: CommitIdentity
) -> None:
    if image.tag != operator_provenance_tag(identity):
        raise ValueError("Docker operator image tag is invalid")
    identity_labels = {
        name: value for name, value in image.labels.items() if name.startswith(LABEL_PREFIX)
    }
    if identity_labels != expected_labels(identity):
        raise ValueError("Docker image labels do not match committed revisions")


def build_and_inspect_image(context: Path, identity: CommitIdentity) -> InspectedImage:
    tag = build_committed_image(context, identity)
    image = inspect_image(tag)
    verify_image_provenance(image, identity)
    return image


def build_and_inspect_operator_image(
    context: Path, identity: CommitIdentity
) -> InspectedImage:
    tag = build_committed_operator_image(context, identity)
    image = inspect_image(tag)
    verify_operator_image_provenance(image, identity)
    return image


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "build-operator"))
    parser.add_argument("--print-image-id", action="store_true")
    options = parser.parse_args(arguments)
    try:
        identity = resolve_commit_identity(REPO_ROOT)
        with committed_build_context(REPO_ROOT, identity) as context:
            if options.command == "build-operator":
                image = build_and_inspect_operator_image(context, identity)
            else:
                image = build_and_inspect_image(context, identity)
    except (OSError, ValueError):
        sys.stderr.write("image provenance: verification failed\n")
        return 78
    if options.print_image_id:
        sys.stdout.write(f"{image.image_id}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
