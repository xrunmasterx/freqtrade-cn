# ruff: noqa: S101

import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from freqtrade.strategy import stoploss_from_absolute


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from MeanReversionFullHistoryStrategy import (  # noqa: E402
    MeanReversionD15V01Strategy,
    MeanReversionD15V02Strategy,
    MeanReversionD25V16Strategy,
)


class FakeDataProvider:
    def __init__(self, dataframe: pd.DataFrame):
        self.dataframe = dataframe

    def get_analyzed_dataframe(self, pair: str, timeframe: str):
        return self.dataframe.copy(), None


class FakeTrade:
    def __init__(self, *, is_short: bool = False):
        self.pair = "BTC/USDT:USDT"
        self.is_short = is_short
        self.leverage = 1.0
        self.open_date_utc = datetime(2026, 8, 1, 10, tzinfo=UTC)
        self.open_rate = 100.0
        self.custom_data: dict[str, object] = {}

    def get_custom_data(self, key: str, default=None):
        return self.custom_data.get(key, default)

    def set_custom_data(self, key: str, value) -> None:
        self.custom_data[key] = value

    def calc_profit_ratio(self, rate: float) -> float:
        direction = -1.0 if self.is_short else 1.0
        return direction * (rate / self.open_rate - 1.0)


def signal_value(dataframe: pd.DataFrame, column: str, index: int) -> int:
    value = dataframe.get(column, pd.Series(0, index=dataframe.index)).fillna(0).loc[index]
    return int(value)


def test_strict_rsi_boundaries_and_symmetric_entries():
    strategy = MeanReversionD15V01Strategy(config={})
    dataframe = pd.DataFrame(
        {
            "date": pd.date_range("2026-08-01", periods=4, freq="1h", tz="UTC"),
            "close": [96.9, 96.9, 103.1, 103.1],
            "mean": [100.0] * 4,
            "atr": [2.0] * 4,
            "rsi": [25.0, 24.9, 75.0, 75.1],
            "long_threshold": [97.0] * 4,
            "short_threshold": [103.0] * 4,
            "volume": [1.0] * 4,
        }
    )

    result = strategy.populate_entry_trend(dataframe, {})

    assert signal_value(result, "enter_long", 0) == 0
    assert signal_value(result, "enter_long", 1) == 1
    assert signal_value(result, "enter_short", 2) == 0
    assert signal_value(result, "enter_short", 3) == 1


def test_mean_and_fixed_target_exit_modes_are_mutually_exclusive():
    dataframe = pd.DataFrame({"close": [99.0, 101.0], "mean": [100.0, 100.0]})
    mean_result = MeanReversionD15V01Strategy(config={}).populate_exit_trend(
        dataframe.copy(), {}
    )
    tp_result = MeanReversionD15V02Strategy(config={}).populate_exit_trend(
        dataframe.copy(), {}
    )

    assert signal_value(mean_result, "exit_short", 0) == 1
    assert signal_value(mean_result, "exit_long", 1) == 1
    assert tp_result[["exit_long", "exit_short"]].to_numpy().sum() == 0


def test_entry_atr_is_frozen_for_stop_and_fixed_target():
    strategy = MeanReversionD15V02Strategy(config={})
    strategy.dp = FakeDataProvider(
        pd.DataFrame(
            {
                "date": [
                    datetime(2026, 8, 1, 9, tzinfo=UTC),
                    datetime(2026, 8, 1, 10, tzinfo=UTC),
                ],
                "atr": [2.0, 20.0],
            }
        )
    )
    trade = FakeTrade()

    stop = strategy.custom_stoploss(
        pair=trade.pair,
        trade=trade,
        current_time=datetime(2026, 8, 1, 10, 5, tzinfo=UTC),
        current_rate=100.0,
        current_profit=0.0,
        after_fill=False,
    )
    target_roi = strategy.custom_roi(
        pair=trade.pair,
        trade=trade,
        current_time=datetime(2026, 8, 1, 10, 5, tzinfo=UTC),
        trade_duration=5,
        entry_tag="mean_reversion_long",
        side="long",
    )

    assert trade.get_custom_data("mr_entry_atr") == 2.0
    assert trade.get_custom_data("mr_stop_rate") == 97.0
    assert trade.get_custom_data("mr_target_rate") == 104.0
    assert math.isclose(stop, stoploss_from_absolute(97.0, 100.0))
    assert math.isclose(target_roi, 0.04)


def test_max_hold_and_one_x_are_frozen_in_clock_hours():
    strategy = MeanReversionD25V16Strategy(config={})
    trade = FakeTrade()

    before = strategy.custom_exit(
        pair=trade.pair,
        trade=trade,
        current_time=trade.open_date_utc + timedelta(hours=48) - timedelta(seconds=1),
        current_rate=100.0,
        current_profit=0.0,
    )
    at_boundary = strategy.custom_exit(
        pair=trade.pair,
        trade=trade,
        current_time=trade.open_date_utc + timedelta(hours=48),
        current_rate=100.0,
        current_profit=0.0,
    )
    leverage = strategy.leverage(
        pair=trade.pair,
        current_time=trade.open_date_utc,
        current_rate=100.0,
        proposed_leverage=10.0,
        max_leverage=100.0,
        entry_tag=None,
        side="long",
    )

    assert before is None
    assert at_boundary == "max_hold_48h"
    assert leverage == 1.0
