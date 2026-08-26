from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_absolute, timeframe_to_prev_date


def wilder_atr(dataframe: DataFrame, length: int = 14) -> pd.Series:
    """Wilder ATR seeded by the first complete simple average."""
    previous_close = dataframe["close"].shift(1)
    true_range = pd.concat(
        [
            dataframe["high"] - dataframe["low"],
            (dataframe["high"] - previous_close).abs(),
            (dataframe["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    result = pd.Series(np.nan, index=dataframe.index, dtype="float64")
    if len(result) < length:
        return result

    result.iloc[length - 1] = true_range.iloc[:length].mean()
    alpha = 1.0 / length
    for index in range(length, len(result)):
        result.iloc[index] = (
            alpha * true_range.iloc[index]
            + (1.0 - alpha) * result.iloc[index - 1]
        )
    return result


class TrendFollowingFullHistoryBaseStrategy(IStrategy):
    """Closed-candle Donchian breakout with price-denominated ATR risk."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "2h"
    process_only_new_candles = True
    startup_candle_count = 100

    max_open_trades = 1
    position_adjustment_enable = False
    minimal_roi: ClassVar[dict[str, float]] = {"0": 100.0}
    stoploss = -0.99
    trailing_stop = False
    use_custom_stoploss = True
    use_exit_signal = False

    channel_length = 20
    atr_length = 14
    initial_stop_atr = 1.5
    trailing_stop_atr = 2.5
    default_leverage = 1.0

    order_types: ClassVar[dict[str, str | bool]] = {
        "entry": "market",
        "exit": "market",
        "emergency_exit": "market",
        "force_entry": "market",
        "force_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["donchian_high"] = (
            dataframe["high"].rolling(self.channel_length).max().shift(1)
        )
        dataframe["donchian_low"] = (
            dataframe["low"].rolling(self.channel_length).min().shift(1)
        )
        dataframe["atr"] = wilder_atr(dataframe, self.atr_length)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_breakout = (
            (dataframe["close"] > dataframe["donchian_high"])
            & (dataframe["close"].shift(1) <= dataframe["donchian_high"].shift(1))
            & (dataframe["volume"] > 0)
        )
        short_breakout = (
            (dataframe["close"] < dataframe["donchian_low"])
            & (dataframe["close"].shift(1) >= dataframe["donchian_low"].shift(1))
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[long_breakout, ["enter_long", "enter_tag"]] = (
            1,
            f"prior_{self.channel_length}_high_breakout",
        )
        dataframe.loc[short_breakout, ["enter_short", "enter_tag"]] = (
            1,
            f"prior_{self.channel_length}_low_breakout",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def _last_closed_atr(self, pair: str, current_time: datetime) -> float | None:
        if self.dp is None:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        current_candle_open = timeframe_to_prev_date(self.timeframe, current_time)
        closed = dataframe.loc[dataframe["date"] < current_candle_open, "atr"]
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
        entry_atr = trade.get_custom_data("trend_entry_atr", None)
        if entry_atr is None:
            entry_atr = self._last_closed_atr(pair, trade.open_date_utc)
            if entry_atr is None:
                return None
            trade.set_custom_data("trend_entry_atr", entry_atr)

        distance = float(entry_atr) * self.initial_stop_atr
        initial_stop = (
            trade.open_rate + distance if trade.is_short else trade.open_rate - distance
        )

        closed_atr = self._last_closed_atr(pair, current_time)
        if closed_atr is None:
            stop_rate = initial_stop
        else:
            trailing_distance = closed_atr * self.trailing_stop_atr
            favorable_rate = trade.min_rate if trade.is_short else trade.max_rate
            if favorable_rate is None:
                favorable_rate = trade.open_rate
            trailing_candidate = (
                favorable_rate + trailing_distance
                if trade.is_short
                else favorable_rate - trailing_distance
            )
            previous = trade.get_custom_data("trend_stop_rate", None)
            if trade.is_short:
                stop_rate = min(initial_stop, trailing_candidate)
                if previous is not None:
                    stop_rate = min(stop_rate, float(previous))
            else:
                stop_rate = max(initial_stop, trailing_candidate)
                if previous is not None:
                    stop_rate = max(stop_rate, float(previous))
            trade.set_custom_data("trend_stop_rate", stop_rate)

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


class TrendFollowing2hN20Stop15Trail25Strategy(TrendFollowingFullHistoryBaseStrategy):
    pass


class TrendFollowing2hN20Stop15Trail35Strategy(TrendFollowingFullHistoryBaseStrategy):
    trailing_stop_atr = 3.5


class TrendFollowing2hN20Stop20Trail25Strategy(TrendFollowingFullHistoryBaseStrategy):
    initial_stop_atr = 2.0


class TrendFollowing2hN20Stop20Trail35Strategy(TrendFollowing2hN20Stop20Trail25Strategy):
    trailing_stop_atr = 3.5


class TrendFollowing2hN20Stop30Trail25Strategy(TrendFollowingFullHistoryBaseStrategy):
    initial_stop_atr = 3.0


class TrendFollowing2hN20Stop30Trail35Strategy(TrendFollowing2hN20Stop30Trail25Strategy):
    trailing_stop_atr = 3.5


class TrendFollowing2hN55Stop15Trail25Strategy(TrendFollowingFullHistoryBaseStrategy):
    channel_length = 55


class TrendFollowing2hN55Stop15Trail35Strategy(TrendFollowing2hN55Stop15Trail25Strategy):
    trailing_stop_atr = 3.5


class TrendFollowing2hN55Stop20Trail25Strategy(TrendFollowing2hN55Stop15Trail25Strategy):
    initial_stop_atr = 2.0


class TrendFollowing2hN55Stop20Trail35Strategy(TrendFollowing2hN55Stop20Trail25Strategy):
    trailing_stop_atr = 3.5


class TrendFollowing2hN55Stop30Trail25Strategy(TrendFollowing2hN55Stop15Trail25Strategy):
    initial_stop_atr = 3.0


class TrendFollowing2hN55Stop30Trail35Strategy(TrendFollowing2hN55Stop30Trail25Strategy):
    trailing_stop_atr = 3.5


class TrendFollowing4hN20Stop15Trail25Strategy(TrendFollowing2hN20Stop15Trail25Strategy):
    timeframe = "4h"


class TrendFollowing4hN20Stop15Trail35Strategy(TrendFollowing2hN20Stop15Trail35Strategy):
    timeframe = "4h"


class TrendFollowing4hN20Stop20Trail25Strategy(TrendFollowing2hN20Stop20Trail25Strategy):
    timeframe = "4h"


class TrendFollowing4hN20Stop20Trail35Strategy(TrendFollowing2hN20Stop20Trail35Strategy):
    timeframe = "4h"


class TrendFollowing4hN20Stop30Trail25Strategy(TrendFollowing2hN20Stop30Trail25Strategy):
    timeframe = "4h"


class TrendFollowing4hN20Stop30Trail35Strategy(TrendFollowing2hN20Stop30Trail35Strategy):
    timeframe = "4h"


class TrendFollowing4hN55Stop15Trail25Strategy(TrendFollowing2hN55Stop15Trail25Strategy):
    timeframe = "4h"


class TrendFollowing4hN55Stop15Trail35Strategy(TrendFollowing2hN55Stop15Trail35Strategy):
    timeframe = "4h"


class TrendFollowing4hN55Stop20Trail25Strategy(TrendFollowing2hN55Stop20Trail25Strategy):
    timeframe = "4h"


class TrendFollowing4hN55Stop20Trail35Strategy(TrendFollowing2hN55Stop20Trail35Strategy):
    timeframe = "4h"


class TrendFollowing4hN55Stop30Trail25Strategy(TrendFollowing2hN55Stop30Trail25Strategy):
    timeframe = "4h"


class TrendFollowing4hN55Stop30Trail35Strategy(TrendFollowing2hN55Stop30Trail35Strategy):
    timeframe = "4h"
