from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data-mtf-capital-regime-research"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "ft_userdata" / "user_data" / "research_data" / "mtf-capital-regime-50" / "diagnostics"
)
PAIR = "BTC_USDT_USDT"
EXECUTION_MINUTES = 15


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], utc=True).dt.as_unit("ns")
    return result.sort_values("date").reset_index(drop=True)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def _adx(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high = frame["high"]
    low = frame["low"]
    close = frame["close"]
    true_range = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1)
    up = high.diff()
    down = -low.diff()
    plus = up.where((up > down) & (up > 0), 0.0)
    minus = down.where((down > up) & (down > 0), 0.0)
    atr = true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100 * minus.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _regime_frame(frame: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.DataFrame:
    result = _normalise(frame)
    ema_fast = _ema(result["close"], fast)
    ema_slow = _ema(result["close"], slow)
    slope = ema_fast / ema_fast.shift(6) - 1.0
    direction = pd.Series(0.0, index=result.index, dtype="float64")
    direction.loc[(result["close"] > ema_slow) & (ema_fast > ema_slow)] = 1.0
    direction.loc[(result["close"] < ema_slow) & (ema_fast < ema_slow)] = -1.0
    return pd.DataFrame(
        {
            "date": result["date"],
            "regime_dir": direction,
            "regime_adx": _adx(result),
            "regime_slope": slope,
        }
    )


def _causal_merge(
    base: pd.DataFrame,
    informative: pd.DataFrame,
    *,
    informative_minutes: int,
    prefix: str,
    ffill: bool = True,
) -> pd.DataFrame:
    """Merge an informative row only after its candle has closed."""
    left = _normalise(base)
    right = _normalise(informative)
    right["available_at"] = right["date"] + pd.Timedelta(
        minutes=informative_minutes - EXECUTION_MINUTES
    )
    feature_columns = [column for column in right.columns if column not in ("date", "available_at")]
    renamed = right[["available_at", "date", *feature_columns]].rename(
        columns={
            "date": f"{prefix}_source_date",
            **{column: f"{prefix}_{column}" for column in feature_columns},
        }
    )
    if ffill:
        merged = pd.merge_asof(
            left.sort_values("date"),
            renamed.sort_values("available_at"),
            left_on="date",
            right_on="available_at",
            direction="backward",
        )
    else:
        merged = left.merge(
            renamed,
            left_on="date",
            right_on="available_at",
            how="left",
        )
    return merged.drop(columns=["available_at"])


def _load_frame(data_root: Path) -> pd.DataFrame:
    futures = data_root / "okx" / "futures"
    primary = _normalise(pd.read_feather(futures / f"{PAIR}-15m-futures.feather"))
    four_hour = _regime_frame(pd.read_feather(futures / f"{PAIR}-4h-futures.feather"))
    daily = _regime_frame(pd.read_feather(futures / f"{PAIR}-1d-futures.feather"))
    hourly = _normalise(pd.read_feather(futures / f"{PAIR}-1h-futures.feather"))[["date", "close"]]
    mark = _normalise(pd.read_feather(futures / f"{PAIR}-1h-mark.feather"))[["date", "close"]]
    funding = _normalise(pd.read_feather(futures / f"{PAIR}-1h-funding_rate.feather"))[["date", "open"]]

    result = _causal_merge(primary, four_hour, informative_minutes=240, prefix="4h")
    result = _causal_merge(result, daily, informative_minutes=1440, prefix="1d")
    result = _causal_merge(
        result,
        hourly.rename(columns={"close": "futures_close"}),
        informative_minutes=60,
        prefix="futures_1h",
    )
    result = _causal_merge(
        result,
        mark.rename(columns={"close": "mark_close"}),
        informative_minutes=60,
        prefix="mark_1h",
    )
    result = _causal_merge(
        result,
        funding.rename(columns={"open": "funding_rate"}),
        informative_minutes=60,
        prefix="funding_1h",
    )

    result["basis"] = result["mark_1h_mark_close"] / result["futures_1h_futures_close"] - 1.0
    result["mark_age_hours"] = (
        result["date"] - result["mark_1h_source_date"]
    ).dt.total_seconds() / 3600.0
    result["funding_age_hours"] = (
        result["date"] - result["funding_1h_source_date"]
    ).dt.total_seconds() / 3600.0
    true_range = pd.concat(
        [result["high"] - result["low"],
         (result["high"] - result["close"].shift()).abs(),
         (result["low"] - result["close"].shift()).abs()],
        axis=1,
    ).max(axis=1)
    result["atrp"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / result["close"]
    result["relative_volume"] = result["volume"] / result["volume"].rolling(96).median().shift(1)
    candle_range = (result["high"] - result["low"]).replace(0, np.nan)
    result["close_location"] = (
        (2.0 * result["close"] - result["high"] - result["low"]) / candle_range
    ).clip(-1.0, 1.0)
    result["body_fraction"] = (result["close"] - result["open"]).abs() / candle_range
    result["donchian_high"] = result["high"].rolling(20).max().shift(1)
    result["donchian_low"] = result["low"].rolling(20).min().shift(1)
    result["breakout_up"] = (result["close"] > result["donchian_high"]) & (
        result["close"].shift(1) <= result["donchian_high"].shift(1)
    )
    result["breakout_down"] = (result["close"] < result["donchian_low"]) & (
        result["close"].shift(1) >= result["donchian_low"].shift(1)
    )
    result["regime_state"] = "neutral"
    up = (
        (result["4h_regime_dir"] == 1)
        & (result["1d_regime_dir"] == 1)
        & (result["4h_regime_adx"] >= 15)
        & (result["1d_regime_adx"] >= 15)
    )
    down = (
        (result["4h_regime_dir"] == -1)
        & (result["1d_regime_dir"] == -1)
        & (result["4h_regime_adx"] >= 15)
        & (result["1d_regime_adx"] >= 15)
    )
    result.loc[up, "regime_state"] = "trend_up"
    result.loc[down, "regime_state"] = "trend_down"
    result["forward_return_16"] = result["close"].shift(-16) / result["close"] - 1.0
    result["forward_return_64"] = result["close"].shift(-64) / result["close"] - 1.0
    result["forward_return_96"] = result["close"].shift(-96) / result["close"] - 1.0
    return result


def _bucket_summary(frame: pd.DataFrame, column: str, value_columns: Iterable[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for value, group in frame.groupby(column, dropna=False, observed=True):
        row: dict[str, object] = {"bucket": "NA" if pd.isna(value) else str(value), "count": int(len(group))}
        for value_column in value_columns:
            values = pd.to_numeric(group[value_column], errors="coerce").dropna()
            row[f"{value_column}_mean"] = float(values.mean()) if len(values) else None
            row[f"{value_column}_median"] = float(values.median()) if len(values) else None
            row[f"{value_column}_winrate"] = float((values > 0).mean()) if len(values) else None
        rows.append(row)
    return rows


def diagnose(
    data_root: Path,
    output_root: Path,
    *,
    start: str = "2021-09-01T00:00:00Z",
    end: str = "2025-01-01T00:00:00Z",
) -> dict[str, object]:
    manifest_path = data_root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    frame = _load_frame(data_root)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    development = frame[(frame["date"] >= start_ts) & (frame["date"] < end_ts)].copy()
    development["funding_bucket"] = pd.cut(
        development["funding_1h_funding_rate"],
        bins=[-np.inf, -0.0002, 0.0, 0.0002, np.inf],
        labels=["negative_strong", "negative_weak", "positive_weak", "positive_strong"],
    )
    development["basis_bucket"] = pd.cut(
        development["basis"],
        bins=[-np.inf, -0.002, 0.0, 0.002, np.inf],
        labels=["discount_strong", "discount_weak", "premium_weak", "premium_strong"],
    )
    development["volatility_bucket"] = pd.cut(
        development["atrp"],
        bins=[-np.inf, 0.002, 0.004, 0.008, np.inf],
        labels=["low", "medium", "high", "extreme"],
    )
    development["breakout_direction"] = np.select(
        [development["breakout_up"], development["breakout_down"]],
        ["up", "down"],
        default="none",
    )
    coverage = {
        "rows": int(len(development)),
        "mark_rows": int(development["mark_1h_mark_close"].notna().sum()),
        "mark_within_2h": int(
            (development["mark_age_hours"].between(0, 2, inclusive="both")).sum()
        ),
        "funding_rows": int(development["funding_1h_funding_rate"].notna().sum()),
        "funding_within_8h": int(
            (development["funding_age_hours"].between(0, 8, inclusive="both")).sum()
        ),
        "future_regime_rows": int(
            (
                (development["4h_source_date"] > development["date"])
                | (development["1d_source_date"] > development["date"])
            ).fillna(False).sum()
        ),
    }
    value_columns = ("forward_return_16", "forward_return_64", "forward_return_96")
    factors = {
        "regime_state": _bucket_summary(development, "regime_state", value_columns),
        "funding_bucket": _bucket_summary(development, "funding_bucket", value_columns),
        "basis_bucket": _bucket_summary(development, "basis_bucket", value_columns),
        "volatility_bucket": _bucket_summary(development, "volatility_bucket", value_columns),
        "breakout_direction": _bucket_summary(development, "breakout_direction", value_columns),
    }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = {
        "schema_version": 1,
        "purpose": "causal-factor-diagnostic-only",
        "data_manifest": str(manifest_path),
        "data_manifest_sha256": _sha256(manifest_path),
        "source_manifest_schema": manifest.get("schema_version"),
        "interval": {"start": start_ts.isoformat(), "end": end_ts.isoformat()},
        "causal_rules": {
            "execution_timeframe": "15m",
            "higher_timeframe_availability": "informative open plus duration minus one execution candle",
            "mark_age_cap_hours": 2,
            "funding_age_cap_hours": 8,
            "forward_returns_are_not_features": True,
        },
        "coverage": coverage,
        "factors": factors,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "diagnostics.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    flat_rows: list[dict[str, object]] = []
    for factor, rows in factors.items():
        for row in rows:
            flat_rows.append({"factor": factor, **row})
    pd.DataFrame(flat_rows).to_csv(output_root / "diagnostics.csv", index=False, encoding="utf-8-sig")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist causal MTF factor diagnostics.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--start", default="2021-09-01T00:00:00Z")
    parser.add_argument("--end", default="2025-01-01T00:00:00Z")
    args = parser.parse_args()
    print(json.dumps(diagnose(args.data_root.resolve(), args.output_root.resolve(), start=args.start, end=args.end), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
