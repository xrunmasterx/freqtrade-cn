from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "data"
    / "okx-btc-usdt-swap-full-20260813"
    / "market-data"
    / "futures"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data-mtf-regime-research"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ohlcv(frame: pd.DataFrame, frequency: str) -> pd.DataFrame:
    source = frame.copy()
    source["date"] = pd.to_datetime(source["date"], utc=True)
    source = source.sort_values("date").drop_duplicates("date")
    source = source.set_index("date")
    result = source.resample(
        frequency,
        origin="epoch",
        label="left",
        closed="left",
    ).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    result = result.dropna(subset=["open", "high", "low", "close"]).reset_index()
    result["date"] = pd.to_datetime(result["date"], utc=True)
    return result[["date", "open", "high", "low", "close", "volume"]]


def prepare(source_root: Path, output_root: Path) -> dict[str, object]:
    source_path = source_root / "BTC_USDT_USDT-5m-futures.feather"
    funding_path = source_root / "BTC_USDT_USDT-1h-funding_rate.feather"
    tiers_path = source_root / "leverage_tiers_USDT.json"
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if not funding_path.is_file():
        raise FileNotFoundError(funding_path)

    source = pd.read_feather(source_path)
    source["date"] = pd.to_datetime(source["date"], utc=True)
    if source["date"].duplicated().any() or not source["date"].is_monotonic_increasing:
        raise ValueError("source 5m candles are not unique and ordered")

    futures_root = output_root / "okx" / "futures"
    futures_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, futures_root / source_path.name)
    shutil.copy2(funding_path, futures_root / funding_path.name)
    if tiers_path.is_file():
        shutil.copy2(tiers_path, futures_root / tiers_path.name)

    derived: dict[str, dict[str, object]] = {}
    for timeframe, frequency in (("15m", "15min"), ("1h", "1h"), ("4h", "4h"), ("1d", "1D")):
        output_path = futures_root / f"BTC_USDT_USDT-{timeframe}-futures.feather"
        result = _ohlcv(source, frequency)
        result.to_feather(output_path)
        derived[timeframe] = {
            "path": str(output_path.relative_to(REPO_ROOT)),
            "sha256": _sha256(output_path),
            "rows": len(result),
            "first": result["date"].iloc[0].isoformat(),
            "last": result["date"].iloc[-1].isoformat(),
        }

    funding = pd.read_feather(funding_path)
    funding["date"] = pd.to_datetime(funding["date"], utc=True)
    manifest = {
        "schema_version": 1,
        "purpose": "multi-timeframe-regime-research",
        "source": {
            "path": str(source_path.relative_to(REPO_ROOT)),
            "sha256": _sha256(source_path),
            "rows": len(source),
            "first": source["date"].iloc[0].isoformat(),
            "last": source["date"].iloc[-1].isoformat(),
        },
        "funding": {
            "path": str(funding_path.relative_to(REPO_ROOT)),
            "sha256": _sha256(funding_path),
            "rows": len(funding),
            "first": funding["date"].iloc[0].isoformat(),
            "last": funding["date"].iloc[-1].isoformat(),
            "semantics": "observed OKX settlement rows; no synthetic rows inserted",
        },
        "derived": derived,
        "aggregation": {
            "source_timeframe": "5m",
            "timezone": "UTC",
            "label": "left",
            "closed": "left",
            "origin": "epoch",
            "lookahead": "each derived candle contains only source rows in its closed interval",
        },
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare immutable derived candles for MTF research.")
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    manifest = prepare(args.source_root.resolve(), args.output_root.resolve())
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
