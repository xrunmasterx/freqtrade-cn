from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np
import pandas as pd
from freqtrade.persistence import Trade
from freqtrade.strategy import (
    IStrategy,
    stoploss_from_absolute,
    timeframe_to_minutes,
    timeframe_to_prev_date,
)
from pandas import DataFrame


def pine_rma(series: pd.Series, length: int) -> pd.Series:
    """Pine-compatible RMA, seeded with the first simple average."""
    result = pd.Series(np.nan, index=series.index, dtype="float64")
    if len(series) < length:
        return result

    result.iloc[length - 1] = series.iloc[:length].mean()
    alpha = 1.0 / length
    for index in range(length, len(series)):
        value = series.iloc[index]
        previous = result.iloc[index - 1]
        if np.isfinite(value) and np.isfinite(previous):
            result.iloc[index] = alpha * value + (1.0 - alpha) * previous
    return result


def pine_atr(dataframe: DataFrame, length: int = 14) -> pd.Series:
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


def prepare_breakout_frame(
    dataframe: DataFrame,
    *,
    channel_length: int = 20,
    atr_length: int = 14,
) -> DataFrame:
    """Calculate the supplied Pine strategy's closed-bar signal fields."""
    result = dataframe.copy()
    result["high_channel"] = result["high"].rolling(channel_length).max().shift(1)
    result["low_channel"] = result["low"].rolling(channel_length).min().shift(1)
    result["atr"] = pine_atr(result, atr_length)
    result["long_cond"] = (result["close"] > result["high_channel"]) & (
        result["close"].shift(1) <= result["high_channel"].shift(1)
    )
    result["short_cond"] = (result["close"] < result["low_channel"]) & (
        result["close"].shift(1) >= result["low_channel"].shift(1)
    )
    return result


class TimeframeBreakoutFullHistoryStrategy(IStrategy):
    """Research surface for the prior-20 Pine breakout and its minimal risk variant.

    The companion full-history runner is the execution authority for this study because
    it models same-close reversals, lower-timeframe paths, fees, slippage, and funding.
    Freqtrade cannot reproduce Pine's same-close reversal with ordinary exit signals.
    """

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "5m"
    startup_candle_count = 21
    process_only_new_candles = True

    max_open_trades = 1
    position_adjustment_enable = False
    minimal_roi: ClassVar[dict[str, float]] = {"0": 100.0}
    stoploss = -0.99
    trailing_stop = False
    use_custom_stoploss = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    channel_length = 20
    atr_length = 14
    trail_multiplier = 2.5
    hard_stop_atr = 1.5
    trail_mode = "tick"
    fallback_tick_size = 0.1
    default_leverage = 1.0

    order_types: ClassVar[dict[str, str | bool]] = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "high_channel": {"color": "green"},
            "low_channel": {"color": "red"},
        },
        "subplots": {"ATR": {"atr": {"color": "orange"}}},
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return prepare_breakout_frame(
            dataframe,
            channel_length=self.channel_length,
            atr_length=self.atr_length,
        )

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["long_cond"], ["enter_long", "enter_tag"]] = (
            1,
            "prior_20_high_breakout",
        )
        dataframe.loc[dataframe["short_cond"], ["enter_short", "enter_tag"]] = (
            1,
            "prior_20_low_breakout",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["short_cond"], ["exit_long", "exit_tag"]] = (
            1,
            "reverse_to_short",
        )
        dataframe.loc[dataframe["long_cond"], ["exit_short", "exit_tag"]] = (
            1,
            "reverse_to_long",
        )
        return dataframe

    def _tick_size(self, pair: str) -> float:
        if self.dp is not None:
            market = self.dp.market(pair)
            precision = market.get("precision", {}).get("price") if market else None
            if isinstance(precision, (int, float)) and precision > 0:
                return float(precision)
        return self.fallback_tick_size

    def _closed_atr(self, pair: str, current_time: datetime) -> float | None:
        if self.dp is None:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        current_open = timeframe_to_prev_date(self.timeframe, current_time)
        closed = dataframe.loc[dataframe["date"] < current_open, "atr"]
        if closed.empty or not np.isfinite(closed.iloc[-1]):
            return None
        return float(closed.iloc[-1])

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
        entry_atr = trade.get_custom_data("breakout_entry_atr", None)
        if entry_atr is None:
            entry_atr = self._closed_atr(pair, trade.open_date_utc)
            if entry_atr is None:
                return None
            trade.set_custom_data("breakout_entry_atr", entry_atr)

        first_trail_time = trade.open_date_utc + timedelta(
            minutes=timeframe_to_minutes(self.timeframe)
        )
        activated = bool(trade.get_custom_data("breakout_trail_activated", False))
        favorable_rate = trade.min_rate if trade.is_short else trade.max_rate
        if not activated and current_time >= first_trail_time:
            reached = favorable_rate <= trade.open_rate if trade.is_short else (
                favorable_rate >= trade.open_rate
            )
            if reached:
                activated = True
                trade.set_custom_data("breakout_trail_activated", True)

        if not activated:
            distance = float(entry_atr) * self.hard_stop_atr
            stop_rate = trade.open_rate + distance if trade.is_short else (
                trade.open_rate - distance
            )
        else:
            current_atr = self._closed_atr(pair, current_time)
            if current_atr is None:
                return None
            distance = current_atr * self.trail_multiplier
            if self.trail_mode == "tick":
                distance *= self._tick_size(pair)
            stop_rate = favorable_rate + distance if trade.is_short else (
                favorable_rate - distance
            )

        return stoploss_from_absolute(
            stop_rate,
            current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return min(self.default_leverage, max_leverage)
