# ruff: noqa: E402, S101

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

from TradingViewSupertrendStrategy import TradingViewSupertrendStrategy


class FastTradingViewSupertrendStrategy(TradingViewSupertrendStrategy):
    atr_period = 2
    atr_multiplier = 1.0


class SmaTradingViewSupertrendStrategy(FastTradingViewSupertrendStrategy):
    change_atr = False


def make_reversal_data() -> pd.DataFrame:
    close = pd.Series([10.0, 10.0, 10.0, 20.0, 20.0, 5.0, 5.0, 22.0])
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=len(close), freq="15min", tz="UTC"),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 100.0,
        }
    )


def make_trade(*, is_short: bool = False, entries: int = 1, exits: int = 0):
    filled_at = datetime(2026, 1, 1, 1, 2, tzinfo=UTC)
    return SimpleNamespace(
        pair="BTC/USDT:USDT",
        is_short=is_short,
        open_rate=100.0,
        stake_amount=100.0 / 3.0 * entries,
        nr_of_successful_entries=entries,
        nr_of_successful_exits=exits,
        has_open_orders=False,
        date_entry_fill_utc=filled_at,
        open_date_utc=filled_at,
        calc_close_rate_for_roi=lambda roi: 99.88 if is_short else 100.12,
    )


def test_defaults_match_requested_strategy_and_execution_rules() -> None:
    assert TradingViewSupertrendStrategy.timeframe == "15m"
    assert TradingViewSupertrendStrategy.exit_timeframe == "5m"
    assert TradingViewSupertrendStrategy.regime_timeframe == "1h"
    assert TradingViewSupertrendStrategy.atr_period == 10
    assert TradingViewSupertrendStrategy.atr_multiplier == 3.0
    assert TradingViewSupertrendStrategy.change_atr is True
    assert TradingViewSupertrendStrategy.order_offset_multiplier == pytest.approx(0.2)
    assert TradingViewSupertrendStrategy.can_short is True
    assert TradingViewSupertrendStrategy.position_adjustment_enable is True
    assert TradingViewSupertrendStrategy.max_entry_position_adjustment == 2
    assert TradingViewSupertrendStrategy.order_types["entry"] == "limit"
    assert TradingViewSupertrendStrategy.order_types["exit"] == "market"
    assert TradingViewSupertrendStrategy.stoploss == pytest.approx(-0.03)
    assert TradingViewSupertrendStrategy.require_regime_filter is True
    assert TradingViewSupertrendStrategy.require_regime_structure is False


def test_plot_config_exposes_strategy_guides_but_not_synthetic_executions() -> None:
    main_plot = TradingViewSupertrendStrategy.plot_config["main_plot"]

    assert main_plot["supertrend_up"]["fill_to"] == "supertrend_price"
    assert main_plot["supertrend_down"]["fill_to"] == "supertrend_price"
    assert main_plot["supertrend_price"]["hidden"] is True
    for side in ("long", "short"):
        for order_number in (1, 2, 3):
            assert main_plot[f"supertrend_{side}_order_{order_number}"]["type"] == "line"
    assert "supertrend_long_activation_reference" in main_plot
    assert "supertrend_short_activation_reference" in main_plot
    assert "supertrend_long_partial_target" in main_plot
    assert "supertrend_short_partial_target" in main_plot
    assert not any("trigger" in name or "exit_marker" in name for name in main_plot)


def test_indicator_matches_pine_wilder_atr_and_reversal_bands() -> None:
    result = FastTradingViewSupertrendStrategy(config={}).populate_indicators(
        make_reversal_data(), {}
    )

    assert np.isnan(result.loc[0, "supertrend_atr"])
    assert result["supertrend_atr"].iloc[1:].tolist() == pytest.approx(
        [2.0, 2.0, 6.5, 4.25, 10.125, 6.0625, 12.03125]
    )
    assert result["supertrend_trend"].tolist() == [1, 1, 1, 1, 1, -1, -1, 1]
    assert result.loc[4, "supertrend_up"] == pytest.approx(15.75)
    assert result.loc[5, "supertrend_down"] == pytest.approx(15.125)
    assert result.loc[6, "supertrend_down"] == pytest.approx(11.0625)
    assert result.loc[7, "supertrend_up"] == pytest.approx(9.96875)
    assert result.loc[5, "supertrend_sell_signal"] == pytest.approx(15.125)
    assert result.loc[7, "supertrend_buy_signal"] == pytest.approx(9.96875)


def test_change_atr_false_uses_pine_sma_true_range_branch() -> None:
    result = SmaTradingViewSupertrendStrategy(config={}).populate_indicators(
        make_reversal_data(), {}
    )

    assert result["supertrend_atr"].iloc[1:].tolist() == pytest.approx(
        [2.0, 2.0, 6.5, 6.5, 9.0, 9.0, 10.0]
    )


def test_order_levels_use_current_trend_average_range_and_point_two_offset() -> None:
    result = FastTradingViewSupertrendStrategy(config={}).populate_indicators(
        make_reversal_data(), {}
    )

    assert result.loc[4, "supertrend_average_candle_range"] == pytest.approx(2.0)
    assert result.loc[4, "supertrend_long_order_1"] == pytest.approx(16.15)
    assert result.loc[4, "supertrend_long_order_2"] == pytest.approx(15.75)
    assert result.loc[4, "supertrend_long_order_3"] == pytest.approx(15.35)
    assert result.loc[6, "supertrend_short_order_1"] == pytest.approx(10.6625)
    assert result.loc[6, "supertrend_short_order_2"] == pytest.approx(11.0625)
    assert result.loc[6, "supertrend_short_order_3"] == pytest.approx(11.4625)


def test_entry_requires_reversal_and_matching_closed_hour_regime() -> None:
    strategy = TradingViewSupertrendStrategy(config={})
    dataframe = pd.DataFrame(
        {
            "volume": [100.0, 100.0, 100.0],
            "supertrend_long_order_1": [95.0, 95.0, np.nan],
            "supertrend_short_order_1": [np.nan, np.nan, 105.0],
            "supertrend_buy_signal": [95.0, 95.0, np.nan],
            "supertrend_sell_signal": [np.nan, np.nan, 105.0],
            "supertrend_regime_long_allowed": [True, False, False],
            "supertrend_regime_short_allowed": [False, False, True],
        }
    )

    result = strategy.populate_entry_trend(dataframe, {})

    assert result.loc[0, "enter_long"] == 1
    assert pd.isna(result.loc[1, "enter_long"])
    assert result.loc[2, "enter_short"] == 1
    assert result.loc[0, "enter_tag"] == "supertrend_regime_long"
    assert result.loc[2, "enter_tag"] == "supertrend_regime_short"


def test_order_price_rejects_reversed_or_disallowed_context() -> None:
    allowed = pd.Series(
        {
            "supertrend_trend": 1,
            "supertrend_regime_long_allowed": True,
            "supertrend_long_order_1": 101.0,
        }
    )

    assert TradingViewSupertrendStrategy._order_price(allowed, "long", 1) == 101.0
    assert TradingViewSupertrendStrategy._order_price(allowed, "short", 1) is None
    allowed["supertrend_regime_long_allowed"] = False
    assert TradingViewSupertrendStrategy._order_price(allowed, "long", 1) is None


def test_exit_rows_begin_after_first_complete_five_minute_candle() -> None:
    strategy = TradingViewSupertrendStrategy(config={})
    trade = make_trade()
    rows = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01 01:00", periods=5, freq="5min", tz="UTC"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
        }
    )
    strategy._closed_market_rows = lambda pair, timeframe, at: rows

    result = strategy._exit_rows_since_entry(
        trade, datetime(2026, 1, 1, 1, 30, tzinfo=UTC)
    )

    assert len(result) == 4
    assert result["date"].iloc[0] == pd.Timestamp("2026-01-01 01:05", tz="UTC")


def test_activation_uses_entry_atr_and_completed_five_minute_extreme() -> None:
    strategy = TradingViewSupertrendStrategy(config={})
    trade = make_trade()
    context = pd.Series({"supertrend_atr": 1.0})
    not_reached = pd.DataFrame({"high": [100.49], "low": [99.8]})
    reached = pd.DataFrame({"high": [100.5], "low": [99.8]})

    assert strategy._activation_ratio(trade, context) == pytest.approx(0.005)
    assert strategy._activation_reached(trade, context, not_reached) is False
    assert strategy._activation_reached(trade, context, reached) is True


def test_failed_bounce_waits_for_four_completed_fifteen_minute_candles() -> None:
    strategy = TradingViewSupertrendStrategy(config={})
    trade = make_trade()
    context = pd.Series({"supertrend_atr": 1.0})
    exit_rows = pd.DataFrame({"high": [100.2], "low": [99.8]})
    first_complete = datetime(2026, 1, 1, 1, 15, tzinfo=UTC)
    main_rows = pd.DataFrame(
        {
            "date": [first_complete + timedelta(minutes=15 * index) for index in range(4)]
        }
    )
    now = datetime(2026, 1, 1, 2, 15, tzinfo=UTC)
    strategy._closed_market_rows = lambda pair, timeframe, at: main_rows.iloc[:3]
    assert strategy._failed_bounce(trade, context, exit_rows, now) is False

    strategy._closed_market_rows = lambda pair, timeframe, at: main_rows
    assert strategy._failed_bounce(trade, context, exit_rows, now) is True


def test_activated_trade_uses_net_breakeven_then_structure_trail() -> None:
    strategy = TradingViewSupertrendStrategy(config={})
    trade = make_trade()
    break_even_rows = pd.DataFrame(
        {
            "high": [101.0, 101.2, 101.1, 100.4],
            "low": [99.5, 99.6, 99.7, 99.9],
            "close": [100.5, 100.7, 100.8, 100.0],
        }
    )
    structure_rows = break_even_rows.copy()
    structure_rows.loc[:2, "low"] = [100.4, 100.5, 100.6]
    structure_rows.loc[3, "close"] = 100.3

    assert strategy._structure_exit_reason(trade, break_even_rows) == "pa_net_breakeven_5m"
    assert strategy._structure_exit_reason(trade, structure_rows) == "pa_structure_trail_5m"


def test_activation_cancels_remaining_dca_order() -> None:
    strategy = TradingViewSupertrendStrategy(config={})
    trade = make_trade(entries=1)
    strategy._entry_context_row = lambda current_trade: pd.Series({"supertrend_atr": 1.0})
    strategy._exit_rows_since_entry = lambda current_trade, at: pd.DataFrame(
        {"high": [100.6], "low": [99.8], "close": [100.4]}
    )
    strategy._closed_market_rows = lambda pair, timeframe, at: pd.DataFrame()

    assert strategy._may_add(trade, datetime(2026, 1, 1, 2, tzinfo=UTC)) is False


def test_partial_exit_occurs_once_after_activation_and_prior_swing_touch() -> None:
    strategy = TradingViewSupertrendStrategy(config={})
    trade = make_trade(entries=3)
    context = pd.Series(
        {"supertrend_atr": 0.2, "supertrend_long_partial_target": 100.3}
    )
    rows = pd.DataFrame(
        {
            "high": [100.4, 100.5, 100.6, 100.7],
            "low": [100.0, 100.1, 100.2, 100.3],
            "close": [100.2, 100.3, 100.4, 100.5],
        }
    )
    strategy._entry_context_row = lambda current_trade: context
    strategy._exit_rows_since_entry = lambda current_trade, at: rows

    adjustment = strategy.adjust_trade_position(
        trade,
        datetime(2026, 1, 1, 2, tzinfo=UTC),
        100.5,
        0.005,
        1.0,
        1000.0,
        100.0,
        100.5,
        0.0,
        0.0,
    )

    assert adjustment is not None
    assert adjustment[0] == pytest.approx(-trade.stake_amount * 0.5)
    assert adjustment[1] == "pa_swing_partial"
    trade.nr_of_successful_exits = 1
    assert strategy.adjust_trade_position(
        trade,
        datetime(2026, 1, 1, 2, tzinfo=UTC),
        100.5,
        0.005,
        1.0,
        1000.0,
        100.0,
        100.5,
        0.0,
        0.0,
    ) is None


def test_initial_entry_is_rejected_when_dynamic_target_is_unavailable() -> None:
    strategy = TradingViewSupertrendStrategy(config={})
    strategy._closed_signal_row = lambda pair, at: None
    now = datetime.now(UTC)

    assert strategy.custom_entry_price(
        "BTC/USDT:USDT", None, now, 110.0, None, "long"
    ) == pytest.approx(110.0)
    assert strategy.confirm_trade_entry(
        "BTC/USDT:USDT", "limit", 1.0, 110.0, "GTC", now, None, "long"
    ) is False


def test_future_rows_do_not_change_existing_indicator_values() -> None:
    strategy = FastTradingViewSupertrendStrategy(config={})
    dataframe = make_reversal_data()
    columns = [
        "supertrend_atr",
        "supertrend_up",
        "supertrend_down",
        "supertrend_trend",
        "supertrend_buy_signal",
        "supertrend_sell_signal",
        "supertrend_change",
        "supertrend_average_candle_range",
        "supertrend_long_order_1",
        "supertrend_long_order_2",
        "supertrend_long_order_3",
        "supertrend_short_order_1",
        "supertrend_short_order_2",
        "supertrend_short_order_3",
        "supertrend_long_activation_reference",
        "supertrend_short_activation_reference",
        "supertrend_long_partial_target",
        "supertrend_short_partial_target",
        "supertrend_long_invalidation",
        "supertrend_short_invalidation",
    ]

    prefix = strategy.populate_indicators(dataframe.iloc[:7].copy(), {})[columns]
    full = strategy.populate_indicators(dataframe.copy(), {})[columns].iloc[:7]

    assert_frame_equal(prefix, full)
