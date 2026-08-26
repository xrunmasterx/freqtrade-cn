from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

import MultiTimeframeRegimeResearchStrategy as strategy_module
from MultiTimeframeRegimeResearchStrategy import (
    MtfRegimeR1E1P1Strategy,
    MultiTimeframeRegimeResearchStrategy,
)


class FakeDataProvider:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def current_whitelist(self) -> list[str]:
        return ["BTC/USDT:USDT"]

    def get_pair_dataframe(
        self, pair: str, timeframe: str, candle_type: str = ""
    ) -> pd.DataFrame:
        assert pair == "BTC/USDT:USDT"
        key = "funding" if candle_type == "funding_rate" else timeframe
        return self.frames.get(key, pd.DataFrame()).copy()


def ohlcv_frame(start: str, periods: int, frequency: str) -> pd.DataFrame:
    index = np.arange(periods, dtype=float)
    close = 100.0 + index * 0.5
    return pd.DataFrame(
        {
            "date": pd.date_range(start, periods=periods, freq=frequency, tz="UTC"),
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(periods),
        }
    )


def test_variant_matrix_is_static_and_exactly_50_unique_classes() -> None:
    specs = list(strategy_module.VARIANT_SPECS)
    names = [str(spec["name"]) for spec in specs]
    classes = [getattr(strategy_module, name) for name in names]

    assert len(specs) == 50
    assert len({str(spec["code"]) for spec in specs}) == 50
    assert len(set(names)) == 50
    assert all(issubclass(candidate, MultiTimeframeRegimeResearchStrategy) for candidate in classes)
    assert [candidate.variant_code for candidate in classes] == [str(spec["code"]) for spec in specs]


def test_informative_pairs_include_closed_regime_and_observed_funding_frames() -> None:
    strategy = MultiTimeframeRegimeResearchStrategy(
        config={"exchange": {"pair_whitelist": ["BTC/USDT:USDT"]}}
    )

    assert strategy.informative_pairs() == [
        ("BTC/USDT:USDT", "4h"),
        ("BTC/USDT:USDT", "1d"),
        ("BTC/USDT:USDT", "1h", "funding_rate"),
    ]


def test_future_higher_timeframe_rows_do_not_change_prior_merged_regime() -> None:
    base = ohlcv_frame("2025-01-01", 240, "15min")
    four_hour = ohlcv_frame("2024-12-01", 500, "4h")
    daily = ohlcv_frame("2024-01-01", 500, "1D")
    provider = FakeDataProvider({"4h": four_hour, "1d": daily})

    strategy = MultiTimeframeRegimeResearchStrategy(config={})
    strategy.dp = provider
    original = strategy.populate_indicators(base.copy(), {"pair": "BTC/USDT:USDT"})

    changed_four_hour = four_hour.copy()
    changed_four_hour.loc[
        changed_four_hour["date"] == pd.Timestamp("2025-01-02 00:00:00Z"),
        ["open", "high", "low", "close"],
    ] *= -10
    provider.frames["4h"] = changed_four_hour
    changed = strategy.populate_indicators(base.copy(), {"pair": "BTC/USDT:USDT"})

    # Freqtrade shifts a 4h candle by 4h minus one 15m decision candle;
    # the signal at 03:45 executes on the 04:00 open.
    before_closed = changed["date"] < pd.Timestamp("2025-01-02 03:45:00Z")
    pd.testing.assert_series_equal(
        original.loc[before_closed, "regime_dir_4h"].reset_index(drop=True),
        changed.loc[before_closed, "regime_dir_4h"].reset_index(drop=True),
    )


def test_missing_higher_timeframe_evidence_is_neutral_not_range() -> None:
    strategy = MultiTimeframeRegimeResearchStrategy(config={})
    base = ohlcv_frame("2024-01-01", 32, "15min")

    result = strategy.populate_indicators(base, {"pair": "BTC/USDT:USDT"})

    assert result["regime_state"].eq("neutral").all()


def test_funding_merge_keeps_only_the_observed_row_without_forward_fill() -> None:
    base = ohlcv_frame("2024-01-01", 32, "15min")
    funding = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2024-01-01 00:00:00Z", "2024-01-01 08:00:00Z"], utc=True
            ),
            "open": [0.001, -0.001],
            "high": [0.0, 0.0],
            "low": [0.0, 0.0],
            "close": [0.0, 0.0],
            "volume": [0.0, 0.0],
        }
    )
    strategy = MultiTimeframeRegimeResearchStrategy(config={})
    strategy.dp = FakeDataProvider({"funding": funding})

    result = strategy.populate_indicators(base, {"pair": "BTC/USDT:USDT"})
    observed = result["funding_rate_fr_1h"].dropna()

    assert observed.tolist() == [0.001]
    assert result.loc[result["date"] == pd.Timestamp("2024-01-01 00:45:00Z"), "funding_rate_fr_1h"].iloc[0] == 0.001
    assert result.loc[result["date"] == pd.Timestamp("2024-01-01 01:00:00Z"), "funding_rate_fr_1h"].isna().all()


def _entry_frame(*, side: str, funding: float) -> pd.DataFrame:
    if side == "long":
        return pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC"),
                "open": [98.5, 100.0],
                "high": [100.0, 102.0],
                "low": [98.0, 99.0],
                "close": [99.0, 101.5],
                "volume": [2.0, 2.0],
                "donchian_high": [100.0, 100.0],
                "donchian_low": [90.0, 90.0],
                "close_location": [0.0, 0.6666667],
                "relative_volume": [2.0, 2.0],
                "atrp": [0.01, 0.01],
                "regime_state": ["trend_up", "trend_up"],
                "funding_rate_fr_1h": [np.nan, funding],
                "enter_long": [0, 0],
                "enter_short": [0, 0],
                "enter_tag": ["", ""],
            }
        )
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC"),
            "open": [101.5, 99.5],
            "high": [102.0, 100.0],
            "low": [100.0, 98.0],
            "close": [101.0, 98.2],
            "volume": [2.0, 2.0],
            "donchian_high": [110.0, 110.0],
            "donchian_low": [100.0, 100.0],
            "close_location": [0.0, -0.8],
            "relative_volume": [2.0, 2.0],
            "atrp": [0.01, 0.01],
            "regime_state": ["trend_down", "trend_down"],
            "funding_rate_fr_1h": [np.nan, funding],
            "enter_long": [0, 0],
            "enter_short": [0, 0],
            "enter_tag": ["", ""],
        }
    )


def test_funding_filter_requires_observed_favourable_rate() -> None:
    strategy = MtfRegimeR1E1P1Strategy(config={})

    long_allowed = strategy.populate_entry_trend(
        _entry_frame(side="long", funding=-0.001), {"pair": "BTC/USDT:USDT"}
    )
    long_rejected = strategy.populate_entry_trend(
        _entry_frame(side="long", funding=0.001), {"pair": "BTC/USDT:USDT"}
    )
    short_allowed = strategy.populate_entry_trend(
        _entry_frame(side="short", funding=0.001), {"pair": "BTC/USDT:USDT"}
    )
    short_rejected = strategy.populate_entry_trend(
        _entry_frame(side="short", funding=-0.001), {"pair": "BTC/USDT:USDT"}
    )

    assert int(long_allowed.loc[1, "enter_long"]) == 1
    assert int(long_rejected.get("enter_long", pd.Series(0)).fillna(0).sum()) == 0
    assert int(short_allowed.loc[1, "enter_short"]) == 1
    assert int(short_rejected.get("enter_short", pd.Series(0)).fillna(0).sum()) == 0


def test_custom_exit_and_leverage_are_fixed() -> None:
    strategy = MultiTimeframeRegimeResearchStrategy(config={})

    class FakeTrade:
        open_date_utc = datetime(2024, 1, 1, tzinfo=UTC)

    trade = FakeTrade()
    assert strategy.custom_exit(
        "BTC/USDT:USDT",
        trade,
        trade.open_date_utc + timedelta(hours=71),
        100.0,
        0.0,
    ) is None
    assert strategy.custom_exit(
        "BTC/USDT:USDT",
        trade,
        trade.open_date_utc + timedelta(hours=72),
        100.0,
        0.0,
    ) == "time_exit_72h"
    assert strategy.leverage(
        "BTC/USDT:USDT",
        trade.open_date_utc,
        100.0,
        5.0,
        100.0,
        None,
        "long",
    ) == 1.0


def test_aggregation_is_left_closed_and_does_not_use_next_bucket() -> None:
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from prepare_mtf_regime_research_data import _ohlcv

    source = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=6, freq="5min", tz="UTC"),
            "open": [100, 101, 102, 103, 104, 105],
            "high": [100, 101, 102, 103, 104, 105],
            "low": [100, 101, 102, 103, 104, 105],
            "close": [100, 101, 102, 103, 104, 105],
            "volume": [1, 1, 1, 1, 1, 1],
        }
    )

    result = _ohlcv(source, "15min")

    assert result["date"].tolist() == [
        pd.Timestamp("2024-01-01 00:00:00Z"),
        pd.Timestamp("2024-01-01 00:15:00Z"),
    ]
    assert result.loc[0, "close"] == 102
    assert result.loc[1, "close"] == 105
    assert result.loc[0, "volume"] == 3
    assert result.loc[1, "volume"] == 3
