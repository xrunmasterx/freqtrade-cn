from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "binance-taker-priceflow-confirmation"
    / "okx-market-data"
    / "futures"
)
OUTPUT_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "donchian-funding-rv"
    / "development-data"
)
CUTOFF = pd.Timestamp("2024-01-01T00:00:00Z")
INPUTS = {
    "5m": (
        "BTC_USDT_USDT-5m-futures.feather",
        "20a5167ff276c28226bc6e85a5ffea91f7dab67ad191626967cc6c6254f77da9",
    ),
    "15m": (
        "BTC_USDT_USDT-15m-futures.feather",
        "a8b065b6070c5e59cd021645ec1eb3256dabd2eb546acc276741a3b205235708",
    ),
    "funding": (
        "BTC_USDT_USDT-1h-funding_rate.feather",
        "98fa273cb29c92a75a0fe09b7f36485b1a810986f4254569aad177f1ca42227d",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def frame_identity(path: Path, frame: pd.DataFrame) -> dict[str, object]:
    dates = pd.to_datetime(frame["date"], utc=True)
    if frame.empty or dates.isna().any():
        raise RuntimeError(f"empty or invalid dated input: {relative(path)}")
    if dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise RuntimeError(f"unordered or duplicate input dates: {relative(path)}")
    return {
        "path": relative(path),
        "sha256": sha256(path),
        "rows": len(frame),
        "first": dates.iloc[0].isoformat(),
        "last": dates.iloc[-1].isoformat(),
    }


def prepare(output_root: Path = OUTPUT_ROOT) -> Path:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite development snapshot: {output_root}")

    sources: dict[str, tuple[Path, pd.DataFrame]] = {}
    source_manifest: dict[str, object] = {}
    for role, (name, expected_sha256) in INPUTS.items():
        path = SOURCE_ROOT / name
        if sha256(path) != expected_sha256:
            raise RuntimeError(f"bound pre-2025 source hash mismatch for {role}")
        frame = pd.read_feather(path)
        source_manifest[role] = frame_identity(path, frame)
        sources[role] = (path, frame)

    output_root.mkdir(parents=True)
    derived_manifest: dict[str, object] = {}
    for role, (source_path, source) in sources.items():
        dates = pd.to_datetime(source["date"], utc=True)
        derived = source.loc[dates < CUTOFF].reset_index(drop=True)
        if derived.empty or pd.to_datetime(derived["date"], utc=True).max() >= CUTOFF:
            raise RuntimeError(f"derived {role} does not satisfy the physical cutoff")
        output_path = output_root / source_path.name
        derived.to_feather(output_path)
        derived_manifest[role] = frame_identity(output_path, derived)

    manifest = {
        "schema_version": 1,
        "purpose": "physical-development-snapshot-only",
        "cutoff_exclusive": CUTOFF.isoformat(),
        "source_snapshot": source_manifest,
        "derived_snapshot": derived_manifest,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mechanically derive the bound pre-2024 F3 development snapshot."
    )
    parser.parse_args()
    manifest = prepare()
    print(json.dumps({"manifest": relative(manifest), "sha256": sha256(manifest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
