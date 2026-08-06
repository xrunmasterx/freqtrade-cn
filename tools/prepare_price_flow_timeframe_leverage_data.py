from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from tools import prepare_price_flow_cross_venue as cross_venue
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import prepare_price_flow_cross_venue as cross_venue


REPO_ROOT = Path(__file__).resolve().parents[1]
DEEP_DATA_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data-price-flow-deep-5y"
)
FIVE_MINUTE_SOURCE = (
    REPO_ROOT / "ft_userdata" / "runtime" / "freqtrade-futures" / "data" / "futures"
)
OUTPUT_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data-price-flow-timeframe-leverage"
)
ASSETS = ("BTC", "ETH")

FLOW_COLUMNS = [
    "bin_taker_imbalance",
    "bin_taker_lag1",
    "bin_taker_lag2",
    "bin_oi_change_5m",
    "bin_oi_change_15m",
    "bin_oi_delta_lag1",
    "bin_oi_delta_lag2",
    "bin_top_position_ratio",
    "bin_top_account_ratio",
    "bin_top_position_change_5m",
    "bin_top_account_change_5m",
    "bin_top_position_change_2h",
    "bin_top_account_change_2h",
    "bin_top_position_delta_lag1",
    "bin_global_account_log_z",
    "bin_breakout_long_recent",
    "bin_breakout_short_recent",
    "bin_breakout_long_current_15m",
    "bin_breakout_short_current_15m",
    "bin_price_return_15m",
    "bin_oi_change_15m_z",
    "bin_taker_imbalance_z",
    "bin_three_5m_valid",
]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare immutable OHLCV and causal 5m flow data for the E10 study."
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resample_ohlcv(
    dataframe: pd.DataFrame,
    target_frequency: str,
    *,
    source_minutes: int,
) -> pd.DataFrame:
    frame = dataframe.copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    frame = frame.sort_values("date").reset_index(drop=True)
    target_delta = pd.Timedelta(target_frequency)
    source_delta = pd.Timedelta(minutes=source_minutes)
    if target_delta % source_delta:
        raise ValueError("Target timeframe must be an integer multiple of the source")
    expected_rows = int(target_delta / source_delta)
    frame["bucket"] = frame["date"].dt.floor(target_frequency)

    complete = frame.groupby("bucket", sort=True)["date"].transform("count").eq(
        expected_rows
    )
    expected_offset = frame.groupby("bucket", sort=True).cumcount() * source_delta
    complete &= frame["date"].eq(frame["bucket"] + expected_offset)
    complete_buckets = frame.loc[complete].groupby("bucket")["date"].count()
    complete_buckets = complete_buckets.loc[complete_buckets.eq(expected_rows)].index
    frame = frame.loc[frame["bucket"].isin(complete_buckets)].copy()

    result = (
        frame.groupby("bucket", sort=True, as_index=False)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .rename(columns={"bucket": "date"})
    )
    return result[["date", "open", "high", "low", "close", "volume"]]


def _augment_five_minute_flow(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.sort_index().copy()
    result["bin_taker_lag1"] = result["bin_taker_imbalance"].shift(1)
    result["bin_taker_lag2"] = result["bin_taker_imbalance"].shift(2)
    result["bin_oi_delta_lag1"] = result["bin_oi_change_5m"].shift(1)
    result["bin_oi_delta_lag2"] = result["bin_oi_change_5m"].shift(2)
    result["bin_top_position_delta_lag1"] = result[
        "bin_top_position_change_5m"
    ].shift(1)
    result["bin_breakout_long_recent"] = (
        result["bin_breakout_long_5m"].shift(1).rolling(24).max().fillna(0) > 0
    )
    result["bin_breakout_short_recent"] = (
        result["bin_breakout_short_5m"].shift(1).rolling(24).max().fillna(0) > 0
    )
    result["bin_breakout_long_current_15m"] = (
        result["bin_breakout_long_5m"].rolling(3).max().fillna(0) > 0
    )
    result["bin_breakout_short_current_15m"] = (
        result["bin_breakout_short_5m"].rolling(3).max().fillna(0) > 0
    )
    result["bin_cusum_long_current_15m"] = (
        result["bin_taker_cusum_cross"].eq(1).rolling(3).max().fillna(0) > 0
    )
    result["bin_cusum_short_current_15m"] = (
        result["bin_taker_cusum_cross"].eq(-1).rolling(3).max().fillna(0) > 0
    )
    return result


def _validate_15m_parity(
    generated: pd.DataFrame,
    frozen: pd.DataFrame,
    *,
    columns: list[str],
) -> dict[str, int]:
    generated_15m = generated.loc[
        pd.to_datetime(generated["decision_time"], utc=True).dt.minute.isin([0, 15, 30, 45])
    ]
    joined = generated_15m[["decision_time", *columns]].merge(
        frozen[["decision_time", *columns]],
        on="decision_time",
        how="inner",
        suffixes=("_generated", "_frozen"),
        validate="one_to_one",
    )
    if joined.empty:
        raise ValueError("15m parity check has no overlapping rows")
    mismatches = 0
    mismatch_details: list[str] = []
    for column in columns:
        left = joined[f"{column}_generated"]
        right = joined[f"{column}_frozen"]
        if pd.api.types.is_bool_dtype(left) or pd.api.types.is_bool_dtype(right):
            equal = left.fillna(False).eq(right.fillna(False))
        else:
            equal = pd.Series(
                np.isclose(
                    pd.to_numeric(left, errors="coerce"),
                    pd.to_numeric(right, errors="coerce"),
                    rtol=1e-12,
                    atol=1e-12,
                    equal_nan=True,
                ),
                index=joined.index,
            )
        count = int((~equal).sum())
        mismatches += count
        if count:
            examples = joined.loc[~equal, "decision_time"].head(3)
            mismatch_details.append(
                f"{column}={count} at {', '.join(value.isoformat() for value in examples)}"
            )
    if mismatches:
        detail = "; ".join(mismatch_details)
        raise ValueError(f"15m parity failed with {mismatches} field mismatches: {detail}")
    return {"overlap_rows": len(joined), "field_mismatches": 0}


def _copy_market_data(output_root: Path) -> list[dict[str, Any]]:
    futures_output = output_root / "futures"
    futures_output.mkdir(parents=True, exist_ok=True)
    outputs: list[dict[str, Any]] = []
    for asset in ASSETS:
        five_minute = FIVE_MINUTE_SOURCE / f"{asset}_USDT_USDT-5m-futures.feather"
        sources = [
            five_minute,
            *sorted((DEEP_DATA_ROOT / "futures").glob(f"{asset}_USDT_USDT-*")),
        ]
        for source in sources:
            target = futures_output / source.name
            shutil.copy2(source, target)
            outputs.append(
                {"path": str(target.relative_to(REPO_ROOT)), "sha256": _sha256(target)}
            )

        fifteen_path = futures_output / f"{asset}_USDT_USDT-15m-futures.feather"
        thirty_path = futures_output / f"{asset}_USDT_USDT-30m-futures.feather"
        fifteen = pd.read_feather(fifteen_path)
        thirty = _resample_ohlcv(fifteen, "30min", source_minutes=15)
        thirty.to_feather(thirty_path)
        outputs.append(
            {"path": str(thirty_path.relative_to(REPO_ROOT)), "sha256": _sha256(thirty_path)}
        )

    tiers_source = DEEP_DATA_ROOT / "futures" / "leverage_tiers_USDT.json"
    tiers_target = futures_output / tiers_source.name
    shutil.copy2(tiers_source, tiers_target)
    outputs.append(
        {"path": str(tiers_target.relative_to(REPO_ROOT)), "sha256": _sha256(tiers_target)}
    )
    return outputs


def _prepare_five_minute_flow(output_root: Path, asset: str) -> dict[str, Any]:
    raw_root = DEEP_DATA_ROOT / "cross-venue" / "raw"
    metric_paths = sorted((raw_root / "metrics" / asset).glob("*.zip"))
    kline_paths = sorted((raw_root / "klines" / asset).glob("*.zip"))
    if not metric_paths or not kline_paths:
        raise RuntimeError(f"Missing raw Binance flow inputs for {asset}")

    metrics, metric_conflicts = cross_venue._load_binance_metrics(metric_paths)
    klines, kline_conflicts = cross_venue._load_binance_klines(kline_paths)
    engineered = cross_venue._engineer_binance_5m(metrics.join(klines, how="outer"))
    engineered = _augment_five_minute_flow(engineered)
    required_finite = [column for column in FLOW_COLUMNS if column != "bin_three_5m_valid"]
    engineered["bin_three_5m_valid"] &= np.isfinite(
        engineered[required_finite].select_dtypes(include=[np.number])
    ).all(axis=1)
    output = engineered.reset_index().rename(columns={"period_end": "decision_time"})
    output = output[["decision_time", *FLOW_COLUMNS]]

    frozen_path = (
        DEEP_DATA_ROOT / "cross-venue" / f"{asset}_USDT_USDT-15m-cross-venue.feather"
    )
    parity_columns = list(FLOW_COLUMNS)
    frozen = pd.read_feather(
        frozen_path,
        columns=["decision_time", "cross_data_valid", *parity_columns],
    )
    frozen = frozen.loc[frozen["cross_data_valid"].fillna(False)].drop(
        columns="cross_data_valid"
    )
    parity = _validate_15m_parity(output, frozen, columns=parity_columns)

    flow_root = output_root / "cross-venue-flow5m"
    flow_root.mkdir(parents=True, exist_ok=True)
    output_path = flow_root / f"{asset}_USDT_USDT-5m-binance-flow.feather"
    output.to_feather(output_path)
    return {
        "asset": asset,
        "path": str(output_path.relative_to(REPO_ROOT)),
        "sha256": _sha256(output_path),
        "rows": len(output),
        "decision_start": output["decision_time"].min().isoformat(),
        "decision_end": output["decision_time"].max().isoformat(),
        "valid_rows": int(output["bin_three_5m_valid"].sum()),
        "metric_conflicts": metric_conflicts,
        "kline_conflicts": kline_conflicts,
        "parity": parity,
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    output_root = args.output_root.expanduser().resolve()
    outputs = _copy_market_data(output_root)
    flow = [_prepare_five_minute_flow(output_root, asset) for asset in ASSETS]
    manifest = {
        "purpose": "E10 timeframe/leverage research; no Paper/Live mutation",
        "source_data_root": str(DEEP_DATA_ROOT.relative_to(REPO_ROOT)),
        "five_minute_source": str(FIVE_MINUTE_SOURCE.relative_to(REPO_ROOT)),
        "market_files": outputs,
        "flow_files": flow,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
