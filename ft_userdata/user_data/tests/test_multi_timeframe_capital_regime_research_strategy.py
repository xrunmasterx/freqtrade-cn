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

import MultiTimeframeCapitalRegimeResearchStrategy as strategy_module
from MultiTimeframeCapitalRegimeResearchStrategy import (
    MtfCapitalR1S1P1Strategy,
    MultiTimeframeCapitalRegimeResearchStrategy,
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
        key = candle_type or timeframe
        return self.frames.get(key, pd.DataFrame()).copy()


def ohlcv_frame(start: str, periods: int, frequency: str, slope: float = 0.5) -> pd.DataFrame:
    index = np.arange(periods, dtype=float)
    close = 100.0 + index * slope
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
    assert all(issubclass(candidate, MultiTimeframeCapitalRegimeResearchStrategy) for candidate in classes)
    assert [candidate.variant_code for candidate in classes] == [str(spec["code"]) for spec in specs]


def test_informative_pairs_include_mark_and_observed_funding() -> None:
    strategy = MultiTimeframeCapitalRegimeResearchStrategy(
        config={"exchange": {"pair_whitelist": ["BTC/USDT:USDT"]}}
    )
    assert strategy.informative_pairs() == [
        ("BTC/USDT:USDT", "4h"),
        ("BTC/USDT:USDT", "1d"),
        ("BTC/USDT:USDT", "1h", "mark"),
        ("BTC/USDT:USDT", "1h", "funding_rate"),
    ]


def test_missing_higher_timeframe_or_mark_evidence_abstains() -> None:
    strategy = MultiTimeframeCapitalRegimeResearchStrategy(config={})
    base = ohlcv_frame("2024-01-01", 64, "15min")
    result = strategy.populate_indicators(base, {"pair": "BTC/USDT:USDT"})
    result = strategy.populate_entry_trend(result, {"pair": "BTC/USDT:USDT"})
    assert result["regime_state"].eq("neutral").all()
    assert int(result["enter_long"].sum()) == 0
    assert int(result["enter_short"].sum()) == 0


def test_causal_informative_rows_are_available_only_after_close() -> None:
    base = ohlcv_frame("2024-01-01", 32, "15min")
    four_hour = ohlcv_frame("2023-12-01", 100, "4h")
    daily = ohlcv_frame("2023-01-01", 100, "1D")
    mark = ohlcv_frame("2023-12-01", 100, "1h")
    funding = mark[["date", "open"]].copy()
    funding["open"] = 0.0001
    strategy = MultiTimeframeCapitalRegimeResearchStrategy(config={})
    strategy.dp = FakeDataProvider(
        {"4h": four_hour, "1d": daily, "mark": mark, "funding_rate": funding, "1h": mark}
    )
    original = strategy.populate_indicators(base.copy(), {"pair": "BTC/USDT:USDT"})
    changed = four_hour.copy()
    changed.loc[changed["date"] == pd.Timestamp("2024-01-02 00:00:00Z"), "close"] *= -10
    strategy.dp.frames["4h"] = changed
    revised = strategy.populate_indicators(base.copy(), {"pair": "BTC/USDT:USDT"})
    before_closed = original["date"] < pd.Timestamp("2024-01-02 03:45:00Z")
    pd.testing.assert_series_equal(
        original.loc[before_closed, "regime_dir_4h"].reset_index(drop=True),
        revised.loc[before_closed, "regime_dir_4h"].reset_index(drop=True),
    )
    observed = original["mark_source_date_1h"].dropna()
    assert (observed <= original.loc[observed.index, "date"]).all()


def _entry_frame(*, funding: float, basis: float, funding_age: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC"),
            "open": [100.0, 100.0],
            "high": [100.5, 103.0],
            "low": [99.5, 99.0],
            "close": [100.0, 102.0],
            "donchian_high": [101.0, 101.0],
            "donchian_low": [90.0, 90.0],
            "close_location": [0.0, 0.8],
            "body_fraction": [0.0, 0.8],
            "relative_volume": [2.0, 2.0],
            "atrp": [0.01, 0.01],
            "atrp_reference": [0.01, 0.01],
            "momentum_24h": [0.0, 0.01],
            "regime_state": ["trend_up", "trend_up"],
            "basis_1h": [basis, basis],
            "basis_observed": [True, True],
            "funding_rate_1h": [funding, funding],
            "funding_observed": [funding_age <= 8.0, funding_age <= 8.0],
            "funding_age_hours": [funding_age, funding_age],
            "enter_long": [0, 0],
            "enter_short": [0, 0],
            "enter_tag": [None, None],
        }
    )


def test_funding_and_basis_gates_are_side_specific_and_age_bounded() -> None:
    strategy = MtfCapitalR1S1P1Strategy(config={})
    allowed = strategy.populate_entry_trend(
        _entry_frame(funding=-0.0001, basis=-0.0005), {"pair": "BTC/USDT:USDT"}
    )
    rejected_funding = strategy.populate_entry_trend(
        _entry_frame(funding=0.001, basis=-0.0005), {"pair": "BTC/USDT:USDT"}
    )
    rejected_age = strategy.populate_entry_trend(
        _entry_frame(funding=-0.0001, basis=-0.0005, funding_age=9.0),
        {"pair": "BTC/USDT:USDT"},
    )
    assert int(allowed.loc[1, "enter_long"]) == 1
    assert int(rejected_funding["enter_long"].sum()) == 0
    assert int(rejected_age["enter_long"].sum()) == 0


def test_custom_exit_is_stale_loss_then_hard_hold_and_leverage_is_one() -> None:
    strategy = MultiTimeframeCapitalRegimeResearchStrategy(config={})

    class FakeTrade:
        open_date_utc = datetime(2024, 1, 1, tzinfo=UTC)

    trade = FakeTrade()
    assert strategy.custom_exit(
        "BTC/USDT:USDT", trade, trade.open_date_utc + timedelta(hours=47), 100.0, -0.001
    ) is None
    assert strategy.custom_exit(
        "BTC/USDT:USDT", trade, trade.open_date_utc + timedelta(hours=48), 100.0, -0.001
    ) == "stale_loss_48h"
    assert strategy.custom_exit(
        "BTC/USDT:USDT", trade, trade.open_date_utc + timedelta(hours=96), 100.0, 0.001
    ) == "max_hold_96h"
    assert strategy.leverage(
        "BTC/USDT:USDT",
        trade.open_date_utc,
        100.0,
        5.0,
        100.0,
        None,
        "long",
    ) == 1.0
