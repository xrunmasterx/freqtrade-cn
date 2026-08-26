# ruff: noqa: S101

import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from freqtrade.strategy import stoploss_from_absolute


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from PineLongTrendTrackerStrategy import PineLongTrendTrackerStrategy  # noqa: E402


class FakeTrade:
    def __init__(
        self,
        *,
        is_short: bool = False,
        open_date: datetime | None = None,
        open_rate: float = 100.0,
    ):
        self.is_short = is_short
        self.leverage = 1.0
        self.open_date_utc = open_date or datetime(2026, 8, 1, 9, 55, tzinfo=UTC)
        self.open_rate = open_rate
        self.custom_data: dict[str, object] = {}

    def get_custom_data(self, key: str, default=None):
        return self.custom_data.get(key, default)

    def set_custom_data(self, key: str, value) -> None:
        self.custom_data[key] = value


class FakeDataProvider:
    def __init__(self, dataframe: pd.DataFrame, tick_size: float = 0.1):
        self.dataframe = dataframe
        self.tick_size = tick_size

    def get_analyzed_dataframe(self, pair: str, timeframe: str):
        return self.dataframe.copy(), None

    def market(self, pair: str):
        return {"precision": {"price": self.tick_size}}


def candle_frame() -> pd.DataFrame:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    rows = [
        {
            "date": start + timedelta(minutes=5 * index),
            "open": 99.0,
            "high": 100.0,
            "low": 98.0,
            "close": 99.0,
            "volume": 1.0,
        }
        for index in range(21)
    ]
    rows.extend(
        [
            {
                "date": start + timedelta(minutes=105),
                "open": 99.0,
                "high": 102.0,
                "low": 98.0,
                "close": 101.0,
                "volume": 1.0,
            },
            {
                "date": start + timedelta(minutes=110),
                "open": 101.0,
                "high": 102.0,
                "low": 96.0,
                "close": 97.0,
                "volume": 1.0,
            },
        ]
    )
    return pd.DataFrame(rows)


def test_defaults_match_supplied_pine_strategy():
    strategy = PineLongTrendTrackerStrategy(config={})

    assert strategy.timeframe == "5m"
    assert strategy.can_short is True
    assert strategy.max_open_trades == 1
    assert strategy.position_adjustment_enable is False
    assert strategy.channel_length == 20
    assert strategy.atr_length == 14
    assert strategy.trail_multiplier == 2.5


def test_channels_and_confirmed_cross_signals_use_only_prior_bars():
    strategy = PineLongTrendTrackerStrategy(config={})
    dataframe = strategy.populate_indicators(candle_frame(), {})
    dataframe = strategy.populate_entry_trend(dataframe, {})
    dataframe = strategy.populate_exit_trend(dataframe, {})

    assert dataframe.loc[21, "high_channel"] == 100.0
    assert dataframe.loc[21, "low_channel"] == 98.0
    assert dataframe.loc[21, "enter_long"] == 1
    assert dataframe.loc[21, "exit_short"] == 1
    assert dataframe.loc[21, "market_state"] == 1
    assert dataframe.loc[22, "enter_short"] == 1
    assert dataframe.loc[22, "exit_long"] == 1
    assert dataframe.loc[22, "market_state"] == -1


def test_atr_matches_pine_rma_seed():
    strategy = PineLongTrendTrackerStrategy(config={})
    dataframe = candle_frame().iloc[:14].copy()
    dataframe["high"] = 101.0
    dataframe["low"] = 99.0
    dataframe["close"] = 100.0

    result = strategy.populate_indicators(dataframe, {})

    assert result["atr"].iloc[:13].isna().all()
    assert result["atr"].iloc[13] == 2.0


def test_long_stop_uses_prior_closed_atr_as_pine_tick_count():
    strategy = PineLongTrendTrackerStrategy(config={})
    current_time = datetime(2026, 8, 1, 10, tzinfo=UTC)
    strategy.dp = FakeDataProvider(
        pd.DataFrame(
            {
                "date": [current_time - timedelta(minutes=5), current_time],
                "atr": [40.0, 100.0],
            }
        )
    )

    result = strategy.custom_stoploss(
        pair="BTC/USDT:USDT",
        trade=FakeTrade(),
        current_time=current_time,
        current_rate=110.0,
        current_profit=0.1,
        after_fill=False,
    )

    expected = stoploss_from_absolute(100.0, 110.0)
    assert math.isclose(result, expected, rel_tol=1e-12, abs_tol=1e-12)


def test_short_stop_uses_prior_closed_atr_as_pine_tick_count():
    strategy = PineLongTrendTrackerStrategy(config={})
    current_time = datetime(2026, 8, 1, 10, tzinfo=UTC)
    strategy.dp = FakeDataProvider(
        pd.DataFrame(
            {
                "date": [current_time - timedelta(minutes=5)],
                "atr": [40.0],
            }
        )
    )

    result = strategy.custom_stoploss(
        pair="BTC/USDT:USDT",
        trade=FakeTrade(is_short=True),
        current_time=current_time,
        current_rate=90.0,
        current_profit=0.1,
        after_fill=False,
    )

    expected = stoploss_from_absolute(100.0, 90.0, is_short=True)
    assert math.isclose(result, expected, rel_tol=1e-12, abs_tol=1e-12)


def test_high_timeframe_stop_does_not_use_unclosed_main_candle_atr():
    strategy = PineLongTrendTrackerStrategy(config={})
    strategy.timeframe = "1h"
    current_time = datetime(2026, 8, 1, 10, 5, tzinfo=UTC)
    strategy.dp = FakeDataProvider(
        pd.DataFrame(
            {
                "date": [
                    datetime(2026, 8, 1, 9, tzinfo=UTC),
                    datetime(2026, 8, 1, 10, tzinfo=UTC),
                ],
                "atr": [40.0, 100.0],
            }
        )
    )

    assert strategy._closed_atr("BTC/USDT:USDT", current_time) == 40.0


def test_stop_is_not_created_during_first_bar_after_fill():
    strategy = PineLongTrendTrackerStrategy(config={})
    current_time = datetime(2026, 8, 1, 10, tzinfo=UTC)
    strategy.dp = FakeDataProvider(
        pd.DataFrame(
            {
                "date": [current_time - timedelta(minutes=5)],
                "atr": [40.0],
            }
        )
    )

    result = strategy.custom_stoploss(
        pair="BTC/USDT:USDT",
        trade=FakeTrade(open_date=current_time, open_rate=100.0),
        current_time=current_time,
        current_rate=110.0,
        current_profit=0.1,
        after_fill=True,
    )

    assert result is None


def test_stop_waits_for_entry_price_activation():
    strategy = PineLongTrendTrackerStrategy(config={})
    current_time = datetime(2026, 8, 1, 10, tzinfo=UTC)
    strategy.dp = FakeDataProvider(
        pd.DataFrame(
            {
                "date": [current_time - timedelta(minutes=5)],
                "atr": [40.0],
            }
        )
    )
    trade = FakeTrade(open_date=current_time - timedelta(minutes=5), open_rate=100.0)

    inactive = strategy.custom_stoploss(
        pair="BTC/USDT:USDT",
        trade=trade,
        current_time=current_time,
        current_rate=99.0,
        current_profit=-0.01,
        after_fill=False,
    )
    active = strategy.custom_stoploss(
        pair="BTC/USDT:USDT",
        trade=trade,
        current_time=current_time,
        current_rate=110.0,
        current_profit=0.1,
        after_fill=False,
    )

    assert inactive is None
    assert trade.get_custom_data("pine_trail_activated") is True
    assert active is not None
