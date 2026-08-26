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
    / "data-mtf-capital-regime-research"
)
PAIR = "BTC_USDT_USDT"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_dates(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], utc=True).dt.as_unit("ns")
    return result.sort_values("date").reset_index(drop=True)


def _ohlcv(frame: pd.DataFrame, frequency: str) -> pd.DataFrame:
    source = _normalise_dates(frame).drop_duplicates("date", keep="last")
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
    result["date"] = pd.to_datetime(result["date"], utc=True).dt.as_unit("ns")
    return result[["date", "open", "high", "low", "close", "volume"]]


def _file_record(path: Path, *, relative_to: Path, frame: pd.DataFrame | None = None) -> dict[str, object]:
    try:
        display_path = str(path.relative_to(relative_to))
    except ValueError:
        display_path = str(path)
    record: dict[str, object] = {
        "path": display_path,
        "sha256": _sha256(path),
    }
    if frame is not None:
        dates = _normalise_dates(frame)["date"]
        record.update(
            {
                "rows": len(frame),
                "first": dates.iloc[0].isoformat(),
                "last": dates.iloc[-1].isoformat(),
            }
        )
    return record


def prepare(source_root: Path, output_root: Path) -> dict[str, object]:
    source_path = source_root / f"{PAIR}-5m-futures.feather"
    funding_path = source_root / f"{PAIR}-1h-funding_rate.feather"
    mark_path = source_root / f"{PAIR}-1h-mark.feather"
    tiers_path = source_root / "leverage_tiers_USDT.json"
    for path in (source_path, funding_path, mark_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    source = _normalise_dates(pd.read_feather(source_path))
    funding = _normalise_dates(pd.read_feather(funding_path))
    mark = _normalise_dates(pd.read_feather(mark_path))
    if source["date"].duplicated().any() or not source["date"].is_monotonic_increasing:
        raise ValueError("source 5m candles are not unique and ordered")
    for label, frame in (("funding", funding), ("mark", mark)):
        if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
            raise ValueError(f"{label} rows are not unique and ordered")
    if mark["date"].max() < source["date"].max() - pd.Timedelta(days=2):
        raise ValueError("mark data does not cover the end of the primary snapshot")
    if funding["date"].max() < source["date"].max() - pd.Timedelta(days=2):
        raise ValueError("funding data does not cover the end of the primary snapshot")

    futures_root = output_root / "okx" / "futures"
    futures_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, futures_root / source_path.name)
    shutil.copy2(funding_path, futures_root / funding_path.name)
    shutil.copy2(mark_path, futures_root / mark_path.name)
    if tiers_path.is_file():
        shutil.copy2(tiers_path, futures_root / tiers_path.name)

    derived: dict[str, dict[str, object]] = {}
    for timeframe, frequency in (("15m", "15min"), ("1h", "1h"), ("4h", "4h"), ("1d", "1D")):
        output_path = futures_root / f"{PAIR}-{timeframe}-futures.feather"
        result = _ohlcv(source, frequency)
        result.to_feather(output_path)
        derived[timeframe] = _file_record(output_path, relative_to=REPO_ROOT, frame=result)

    manifest = {
        "schema_version": 2,
        "purpose": "multi-timeframe-capital-regime-research",
        "pair": "BTC/USDT:USDT",
        "source": _file_record(source_path, relative_to=REPO_ROOT, frame=source),
        "funding": {
            **_file_record(funding_path, relative_to=REPO_ROOT, frame=funding),
            "semantics": "observed OKX settlement rows; no synthetic rows inserted",
        },
        "mark": {
            **_file_record(mark_path, relative_to=REPO_ROOT, frame=mark),
            "semantics": "authoritative OKX 1h mark-price candles used by funding accounting and basis",
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
        "causal_side_data": {
            "execution_timeframe": "15m",
            "mark_observation_age_cap_hours": 2,
            "funding_observation_age_cap_hours": 8,
            "informative_availability": "informative open timestamp plus informative duration minus one execution candle",
        },
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare causal MTF candles with authoritative mark and funding data."
    )
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    manifest = prepare(args.source_root.resolve(), args.output_root.resolve())
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
