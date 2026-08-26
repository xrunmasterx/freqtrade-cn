from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREREGISTRATION = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "donchian-logistic-meta-label"
    / "PROSPECTIVE_CANDIDATE_PREREGISTRATION.md"
)


class ProjectionNotReady(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ProjectionNotReady(f"required file is unreadable: {path}") from error
    return digest.hexdigest()


def _lower_sha256(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise argparse.ArgumentTypeError("value must be a lowercase SHA-256")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan the frozen V7/V8 prospective signal projection."
    )
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--prereg-sha256", type=_lower_sha256, required=True)
    parser.add_argument("--v7-journal", type=Path, required=True)
    parser.add_argument("--publication-journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    actual_preregistration_sha256 = sha256_file(args.preregistration)
    if actual_preregistration_sha256 != args.prereg_sha256:
        raise ProjectionNotReady("prospective candidate preregistration SHA-256 mismatch")

    plan: dict[str, object] = {
        "action": "build" if args.build else "plan",
        "output": str(args.output),
        "preregistration": str(args.preregistration),
        "preregistration_sha256": actual_preregistration_sha256,
        "publication_journal": str(args.publication_journal),
        "status": "NOT_READY_FROZEN_INPUT_CHAIN",
        "unresolved": [
            "V8 freeze manifest and runtime schema identity",
            "prospective OKX BTC 99-tier snapshot and exact hash",
            "final materialization receipt schema and external expected hashes",
            "canonical V7 5m path proof with no synthetic candle fill",
            "exact V7 funding-observation to V8 raw-settlement cross-check",
        ],
        "v7_journal": str(args.v7_journal),
        "writes": False,
    }
    if args.build:
        raise ProjectionNotReady(
            "V8 freeze and prospective leverage-tier snapshot are not available"
        )
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(json.dumps(run(args), allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
