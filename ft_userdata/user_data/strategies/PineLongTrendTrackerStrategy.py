from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    IStrategy,
    stoploss_from_absolute,
    timeframe_to_minutes,
    timeframe_to_prev_date,
)


def pine_rma(series: pd.Series, length: int) -> pd.Series:
    """Pine-compatible RMA seeded with the first simple average."""
    result = pd.Series(float("nan"), index=series.index, dtype="float64")
    if len(series) < length:
        return result

    result.iloc[length - 1] = series.iloc[:length].mean()
    alpha = 1.0 / length
    for index in range(length, len(series)):
        result.iloc[index] = alpha * series.iloc[index] + (1.0 - alpha) * result.iloc[index - 1]
    return result


def pine_atr(dataframe: DataFrame, length: int) -> pd.Series:
    """Pine ta.atr(), including high-low as true range on the first bar."""
    previous_close = dataframe["close"].shift(1)
    true_range = pd.concat(
        [
            dataframe["high"] - dataframe["low"],
            (dataframe["high"] - previous_close).abs(),
            (dataframe["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return pine_rma(true_range, length)


class PineLongTrendTrackerStrategy(IStrategy):
    """Freqtrade conversion of the supplied Pine v6 long-term trend tracker."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "5m"
    startup_candle_count = 21
    process_only_new_candles = True

    max_open_trades = 1
    position_adjustment_enable = False
    minimal_roi = {"0": 100.0}
    stoploss = -1.0
    trailing_stop = False
    use_custom_stoploss = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    channel_length = 20
    atr_length = 14
    trail_multiplier = 2.5
    fallback_tick_size = 0.1

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "high_channel": {"color": "green"},
            "low_channel": {"color": "red"},
        },
        "subplots": {
            "ATR trailing offset": {
                "atr": {"color": "orange"},
                "trail_offset_ticks": {"color": "blue"},
            },
            "Market state": {"market_state": {"color": "purple"}},
        },
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["high_channel"] = (
            dataframe["high"].rolling(self.channel_length).max().shift(1)
        )
        dataframe["low_channel"] = (
            dataframe["low"].rolling(self.channel_length).min().shift(1)
        )
        dataframe["atr"] = pine_atr(dataframe, self.atr_length)
        dataframe["trail_offset_ticks"] = dataframe["atr"] * self.trail_multiplier
        dataframe["market_state"] = np.select(
            [
                dataframe["close"] > dataframe["high_channel"],
                dataframe["close"] < dataframe["low_channel"],
            ],
            [1, -1],
            default=0,
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_condition = (dataframe["close"] > dataframe["high_channel"]) & (
            dataframe["close"].shift(1) <= dataframe["high_channel"].shift(1)
        )
        short_condition = (dataframe["close"] < dataframe["low_channel"]) & (
            dataframe["close"].shift(1) >= dataframe["low_channel"].shift(1)
        )

        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            "confirmed_high_channel_breakout",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            "confirmed_low_channel_breakout",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["enter_short"] == 1, ["exit_long", "exit_tag"]] = (
            1,
            "reverse_to_short",
        )
        dataframe.loc[dataframe["enter_long"] == 1, ["exit_short", "exit_tag"]] = (
            1,
            "reverse_to_long",
        )
        return dataframe

    def _tick_size(self, pair: str) -> float:
        if self.dp is not None:
            market = self.dp.market(pair)
            tick_size = market.get("precision", {}).get("price") if market else None
            if isinstance(tick_size, (int, float)) and tick_size > 0:
                return float(tick_size)
        return self.fallback_tick_size

    def _closed_atr(self, pair: str, current_time: datetime) -> float | None:
        if self.dp is None:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        current_candle_open = timeframe_to_prev_date(self.timeframe, current_time)
        closed = dataframe.loc[dataframe["date"] < current_candle_open, "atr"]
        if closed.empty:
            return None
        atr = closed.iloc[-1]
        return float(atr) if atr > 0 else None

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        atr = self._closed_atr(pair, current_time)
        if atr is None:
            return None

        first_exit_order_time = trade.open_date_utc + timedelta(
            minutes=timeframe_to_minutes(self.timeframe)
        )
        if current_time < first_exit_order_time:
            return None

        activated = bool(trade.get_custom_data("pine_trail_activated", False))
        activation_reached = (
            current_rate <= trade.open_rate if trade.is_short else current_rate >= trade.open_rate
        )
        if not activated:
            if not activation_reached:
                return None
            trade.set_custom_data("pine_trail_activated", True)

        # Pine's trail_offset is measured in syminfo.mintick units, not price units.
        offset_price = atr * self.trail_multiplier * self._tick_size(pair)
        stop_rate = current_rate + offset_price if trade.is_short else current_rate - offset_price
        return stoploss_from_absolute(
            stop_rate,
            current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )
