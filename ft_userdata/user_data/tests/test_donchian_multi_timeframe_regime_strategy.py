from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

from DonchianMultiTimeframeRegimeStrategy import (
    DonchianMultiTimeframeRegimeStrategy,
)


class FakeDataProvider:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def current_whitelist(self) -> list[str]:
        return ["BTC/USDT:USDT"]

    def get_pair_dataframe(self, pair: str, timeframe: str) -> pd.DataFrame:
        assert pair == "BTC/USDT:USDT"
        return self.frames[timeframe].copy()


def ohlcv_frame(start: str, periods: int, frequency: str) -> pd.DataFrame:
    index = np.arange(periods, dtype=float)
    close = 100.0 + index * 0.25 + np.sin(index / 4.0)
    return pd.DataFrame(
        {
            "date": pd.date_range(start, periods=periods, freq=frequency, tz="UTC"),
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": np.ones(periods),
        }
    )


def test_informative_pairs_request_closed_4h_and_daily_context() -> None:
    strategy = DonchianMultiTimeframeRegimeStrategy(
        config={"exchange": {"pair_whitelist": ["BTC/USDT:USDT"]}}
    )

    assert strategy.informative_pairs() == [
        ("BTC/USDT:USDT", "4h"),
        ("BTC/USDT:USDT", "1d"),
    ]


def test_regime_requires_both_higher_timeframes_to_agree() -> None:
    dataframe = pd.DataFrame(
        {
            "regime_trend_4h": [1, 1, -1, -1, 1],
            "regime_trend_1d": [1, -1, -1, 1, np.nan],
            "regime_adx": [20.0, 20.0, 20.0, 20.0, 20.0],
        }
    )

    result = DonchianMultiTimeframeRegimeStrategy.classify_regime(dataframe)

    assert result.tolist() == ["trend_up", "neutral", "trend_down", "neutral", "neutral"]


def test_entry_routes_only_aligned_trend_states_and_abstains_on_neutral() -> None:
    strategy = DonchianMultiTimeframeRegimeStrategy(config={})
    dataframe = pd.DataFrame(
        {
            "close": [100.0, 101.0, 100.0, 98.0, 99.0],
            "donchian_high": [101.0, 100.5, 102.0, 102.0, 98.5],
            "donchian_low": [99.0, 99.0, 99.0, 98.5, 99.5],
            "directional_return": [-0.01, -0.02, 0.0, 0.02, 0.02],
            "regime_state": ["neutral", "trend_up", "neutral", "trend_down", "trend_up"],
            "regime_adx": [20.0] * 5,
        }
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert int(result.get("enter_long", pd.Series(0)).fillna(0).loc[1]) == 1
    assert int(result.get("enter_short", pd.Series(0)).fillna(0).loc[3]) == 1
    assert int(result.get("enter_long", pd.Series(0)).fillna(0).loc[0]) == 0
    assert int(result.get("enter_long", pd.Series(0)).fillna(0).loc[4]) == 0


def test_low_adx_is_neutral_even_when_higher_timeframes_agree() -> None:
    dataframe = pd.DataFrame(
        {
            "regime_trend_4h": [1],
            "regime_trend_1d": [1],
            "regime_adx": [14.99],
        }
    )

    result = DonchianMultiTimeframeRegimeStrategy.classify_regime(dataframe)

    assert result.tolist() == ["neutral"]


def test_without_data_provider_higher_timeframes_fail_closed() -> None:
    strategy = DonchianMultiTimeframeRegimeStrategy(config={})
    dataframe = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=40, freq="15min", tz="UTC"),
            "open": np.arange(40, dtype=float) + 100,
            "high": np.arange(40, dtype=float) + 101,
            "low": np.arange(40, dtype=float) + 99,
            "close": np.arange(40, dtype=float) + 100,
            "volume": np.ones(40),
        }
    )

    result = strategy.populate_indicators(dataframe, {"pair": "BTC/USDT:USDT"})

    assert result["regime_trend_4h"].isna().all()
    assert result["regime_trend_1d"].isna().all()
    assert result["regime_state"].eq("neutral").all()


def test_populate_indicators_merges_both_higher_timeframe_states() -> None:
    strategy = DonchianMultiTimeframeRegimeStrategy(config={})
    strategy.dp = FakeDataProvider(
        {
            "4h": ohlcv_frame("2025-12-01", 300, "4h"),
            "1d": ohlcv_frame("2025-11-01", 100, "1D"),
        }
    )

    result = strategy.populate_indicators(
        ohlcv_frame("2026-01-01", 400, "15min"),
        {"pair": "BTC/USDT:USDT"},
    )

    assert {
        "regime_trend_4h",
        "regime_trend_1d",
        "regime_adx",
        "regime_state",
    }.issubset(result)
    assert result["regime_state"].eq("trend_up").any()


def test_supertrend_regime_prefix_does_not_depend_on_future_rows() -> None:
    index = np.arange(80, dtype=float)
    close = 100.0 + index * 0.25 + np.sin(index / 4.0)
    dataframe = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=80, freq="4h", tz="UTC"),
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": np.ones(80),
        }
    )
    original = DonchianMultiTimeframeRegimeStrategy._populate_regime_frame(dataframe)
    mutated = dataframe.copy()
    mutated.loc[50:, ["open", "high", "low", "close"]] *= 10
    changed = DonchianMultiTimeframeRegimeStrategy._populate_regime_frame(mutated)

    pd.testing.assert_series_equal(
        original.loc[:49, "regime_trend"],
        changed.loc[:49, "regime_trend"],
    )
