# ruff: noqa: S101

import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from pandas.testing import assert_series_equal


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from DonchianCounterMomentumRegimeStrategy import (  # noqa: E402
    DonchianCounterMomentumRegimeHighReturnStrategy,
    DonchianCounterMomentumRegimeStrategy,
)
from DonchianLowAdxParticipationStrategy import (  # noqa: E402
    DonchianLowAdxParticipationStrategy,
)


def candle_frame(rows: int, minutes: int) -> pd.DataFrame:
    index = np.arange(rows, dtype=float)
    close = 100.0 + 0.01 * index + 0.2 * np.sin(index / 7)
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=rows, freq=f"{minutes}min", tz="UTC"),
            "open": close - 0.02,
            "high": close + 0.08,
            "low": close - 0.08,
            "close": close,
            "volume": np.full(rows, 100.0),
        }
    )


def signal_value(dataframe: pd.DataFrame, column: str, index: int) -> int:
    value = dataframe.get(column, pd.Series(0, index=dataframe.index)).fillna(0).loc[index]
    return int(value)


def test_low_adx_candidate_parameters_are_frozen():
    strategy = DonchianLowAdxParticipationStrategy(config={})

    assert strategy.timeframe == "30m"
    assert strategy.channel_length == 20
    assert strategy.adx_length == 14
    assert strategy.max_adx == 18.06
    assert strategy.volume_baseline_length == 20
    assert strategy.max_relative_volume == 1.5
    assert strategy.minimal_roi == {"0": 0.03}
    assert strategy.stoploss == -0.015
    assert strategy.max_hold_hours == 72
    assert strategy.order_types["entry"] == "market"
    assert strategy.can_short is True


def test_low_adx_indicators_use_only_current_and_prior_rows():
    strategy = DonchianLowAdxParticipationStrategy(config={})
    dataframe = candle_frame(100, 30)
    dataframe.loc[50, "volume"] = 1000.0
    original = strategy.populate_indicators(dataframe.copy(), {})
    mutated = dataframe.copy()
    mutated.loc[80:, ["open", "high", "low", "close", "volume"]] *= 10
    changed = strategy.populate_indicators(mutated, {})

    assert original.loc[20, "donchian_high"] == dataframe.loc[:19, "high"].max()
    assert original.loc[50, "relative_volume"] == 10.0
    for column in ("donchian_high", "donchian_low", "adx14", "relative_volume"):
        assert_series_equal(original.loc[:79, column], changed.loc[:79, column])


def test_low_adx_candidate_emits_both_breakout_directions():
    strategy = DonchianLowAdxParticipationStrategy(config={})
    dataframe = pd.DataFrame(
        {
            "close": [100.0, 101.0, 100.0, 100.0, 98.0],
            "donchian_high": [101.0, 100.5, 102.0, 102.0, 102.0],
            "donchian_low": [99.0, 99.0, 99.0, 99.5, 98.5],
            "adx14": [10.0] * 5,
            "relative_volume": [1.0] * 5,
        }
    )

    result = strategy.populate_entry_trend(dataframe, {})

    assert signal_value(result, "enter_long", 1) == 1
    assert signal_value(result, "enter_short", 4) == 1


def test_counter_momentum_candidate_parameters_are_frozen():
    strategy = DonchianCounterMomentumRegimeStrategy(config={})

    assert strategy.timeframe == "15m"
    assert strategy.channel_length == 20
    assert strategy.momentum_lookback == 288
    assert strategy.max_directional_return_72h == -0.0175
    assert strategy.regime_timeframe == "1h"
    assert strategy.regime_ema_length == 480
    assert strategy.regime_history_length == 1499
    assert strategy.minimal_roi == {"0": 0.04}
    assert strategy.stoploss == -0.015
    assert strategy.max_hold_hours == 48
    assert strategy.order_types["entry"] == "market"
    assert strategy.can_short is True


def test_counter_momentum_indicators_do_not_change_when_future_rows_change():
    strategy = DonchianCounterMomentumRegimeStrategy(config={})
    dataframe = candle_frame(2100, 15)
    original = strategy.populate_indicators(dataframe.copy(), {})
    mutated = dataframe.copy()
    mutated.loc[2050:, ["open", "high", "low", "close", "volume"]] *= 10
    changed = strategy.populate_indicators(mutated, {})

    assert original.loc[20, "donchian_high"] == dataframe.loc[:19, "high"].max()
    expected_return = dataframe.loc[2000, "close"] / dataframe.loc[1712, "close"] - 1
    assert original.loc[2000, "return_72h"] == expected_return
    for column in ("donchian_high", "donchian_low", "return_72h"):
        assert_series_equal(original.loc[:2049, column], changed.loc[:2049, column])


def test_counter_momentum_regime_ema_uses_only_current_and_prior_1h_rows():
    strategy = DonchianCounterMomentumRegimeStrategy(config={})
    dataframe = candle_frame(1700, 60)
    original = strategy.populate_regime_indicators(dataframe.copy())
    mutated = dataframe.copy()
    mutated.loc[1650:, ["open", "high", "low", "close", "volume"]] *= 10
    changed = strategy.populate_regime_indicators(mutated)

    assert original["ema_20d"].iloc[:1498].isna().all()
    assert original["ema_20d"].iloc[1498:].notna().all()
    assert_series_equal(original.loc[:1649, "ema_20d"], changed.loc[:1649, "ema_20d"])


def test_counter_momentum_regime_ema_is_independent_of_older_prefix():
    strategy = DonchianCounterMomentumRegimeStrategy(config={})
    dataframe = candle_frame(1800, 60)
    full = strategy.populate_regime_indicators(dataframe.copy())
    tail = strategy.populate_regime_indicators(dataframe.iloc[-1499:].copy())

    assert full["ema_20d"].iloc[-1] == tail["ema_20d"].iloc[-1]


def test_counter_momentum_candidate_emits_both_regime_aligned_directions():
    strategy = DonchianCounterMomentumRegimeStrategy(config={})
    dataframe = pd.DataFrame(
        {
            "close": [100.0, 101.0, 100.0, 100.0, 98.0],
            "donchian_high": [101.0, 100.5, 102.0, 102.0, 102.0],
            "donchian_low": [99.0, 99.0, 99.0, 99.5, 98.5],
            "return_72h": [0.0, -0.02, 0.0, 0.0, 0.02],
            "ema_20d": [100.0, 100.0, 99.0, 99.0, 99.0],
        }
    )

    result = strategy.populate_entry_trend(dataframe, {})

    assert signal_value(result, "enter_long", 1) == 1
    assert signal_value(result, "enter_short", 4) == 1


def test_candidates_exit_at_frozen_maximum_holding_time_and_use_one_x():
    opened = datetime(2026, 8, 1, tzinfo=UTC)
    trade = SimpleNamespace(open_date_utc=opened)
    cases = (
        (DonchianLowAdxParticipationStrategy(config={}), 72, "max_hold_72h"),
        (DonchianCounterMomentumRegimeStrategy(config={}), 48, "max_hold_48h"),
    )

    for strategy, hours, tag in cases:
        before = strategy.custom_exit(
            pair="BTC/USDT:USDT",
            trade=trade,
            current_time=opened + timedelta(hours=hours) - timedelta(seconds=1),
            current_rate=100.0,
            current_profit=0.0,
        )
        at_boundary = strategy.custom_exit(
            pair="BTC/USDT:USDT",
            trade=trade,
            current_time=opened + timedelta(hours=hours),
            current_rate=100.0,
            current_profit=0.0,
        )
        leverage = strategy.leverage(
            pair="BTC/USDT:USDT",
            current_time=opened,
            current_rate=100.0,
            proposed_leverage=10.0,
            max_leverage=100.0,
            entry_tag=None,
            side="long",
        )

        assert before is None
        assert at_boundary == tag
        assert leverage == 1.0


def test_counter_momentum_high_return_parameters_are_frozen():
    strategy = DonchianCounterMomentumRegimeHighReturnStrategy(config={})

    assert strategy.startup_candle_count == 1499
    assert strategy.default_leverage == 14.0
    assert strategy.minimal_roi == {"0": 0.52}
    assert strategy.stoploss == -0.21
    assert math.isclose(strategy.stoploss / strategy.default_leverage, -0.015)
