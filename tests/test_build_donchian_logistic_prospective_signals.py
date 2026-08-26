import hashlib
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "build_donchian_logistic_prospective_signals.py"
)
SPEC = importlib.util.spec_from_file_location(
    "build_donchian_logistic_prospective_signals", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def arguments(tmp_path: Path, preregistration: Path, digest: str, *extra: str) -> list[str]:
    return [
        "--preregistration",
        str(preregistration),
        "--prereg-sha256",
        digest,
        "--v7-journal",
        str(tmp_path / "v7.jsonl"),
        "--publication-journal",
        str(tmp_path / "v8-publication.jsonl"),
        "--output",
        str(tmp_path / "signals.feather"),
        *extra,
    ]


def test_default_is_a_deterministic_no_write_not_ready_plan(tmp_path, capsys):
    preregistration = tmp_path / "prereg.md"
    preregistration.write_bytes(b"frozen synthetic preregistration\n")
    digest = hashlib.sha256(preregistration.read_bytes()).hexdigest()
    output = tmp_path / "signals.feather"

    assert builder.main(arguments(tmp_path, preregistration, digest)) == 0

    stdout = capsys.readouterr().out
    assert '"status": "NOT_READY_FROZEN_INPUT_CHAIN"' in stdout
    assert "prospective OKX BTC 99-tier snapshot" in stdout
    assert "final materialization receipt schema" in stdout
    assert "no synthetic candle fill" in stdout
    assert "V7 funding-observation to V8 raw-settlement cross-check" in stdout
    assert '"writes": false' in stdout
    assert "performance" not in stdout.lower()
    assert not output.exists()


def test_preregistration_hash_mismatch_fails_closed(tmp_path):
    preregistration = tmp_path / "prereg.md"
    preregistration.write_bytes(b"frozen synthetic preregistration\n")

    args = builder.build_parser().parse_args(arguments(tmp_path, preregistration, "0" * 64))
    with pytest.raises(builder.ProjectionNotReady, match="SHA-256 mismatch"):
        builder.run(args)


def test_explicit_build_remains_not_ready_without_frozen_v8_schema(tmp_path):
    preregistration = tmp_path / "prereg.md"
    preregistration.write_bytes(b"frozen synthetic preregistration\n")
    digest = hashlib.sha256(preregistration.read_bytes()).hexdigest()
    output = tmp_path / "signals.feather"
    args = builder.build_parser().parse_args(
        arguments(tmp_path, preregistration, digest, "--build")
    )

    with pytest.raises(builder.ProjectionNotReady, match=r"V8 freeze.*leverage-tier snapshot"):
        builder.run(args)
    assert not output.exists()
