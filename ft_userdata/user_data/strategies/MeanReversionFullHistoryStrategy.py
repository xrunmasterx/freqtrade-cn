from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np
import talib.abstract as ta
from pandas import DataFrame, Series, Timedelta, Timestamp

from freqtrade.persistence import Order, Trade
from freqtrade.strategy import (
    IStrategy,
    stoploss_from_absolute,
    timeframe_to_minutes,
    timeframe_to_prev_date,
)


class MeanReversionFullHistoryBase(IStrategy):
    """Closed-candle BTC perpetual mean-reversion family for a sealed study."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count = 200

    max_open_trades = 1
    position_adjustment_enable = False
    use_exit_signal = True
    use_custom_stoploss = True
    use_custom_roi = True
    minimal_roi: ClassVar[dict[str, float]] = {"0": 100.0}
    stoploss = -0.99
    trailing_stop = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    order_types: ClassVar[dict[str, str | bool]] = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    ema_length = 20
    atr_length = 14
    rsi_length = 14
    entry_atr_mult = 1.5
    long_rsi_threshold = 25.0
    short_rsi_threshold = 75.0
    exit_mode = "mean"
    take_profit_atr = 2.0
    hard_stop_atr = 1.5
    max_hold_hours = 24

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "mean": {"color": "#4C9AFF"},
            "long_threshold": {"color": "#36B37E"},
            "short_threshold": {"color": "#FF5630"},
        },
        "subplots": {
            "Mean-reversion": {
                "rsi": {"color": "#6554C0"},
                "atr": {"color": "#FFAB00"},
            }
        },
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["mean"] = ta.EMA(dataframe, timeperiod=self.ema_length)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_length)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=self.rsi_length)
        dataframe["long_threshold"] = (
            dataframe["mean"] - self.entry_atr_mult * dataframe["atr"]
        )
        dataframe["short_threshold"] = (
            dataframe["mean"] + self.entry_atr_mult * dataframe["atr"]
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        valid = (
            np.isfinite(dataframe["mean"])
            & np.isfinite(dataframe["atr"])
            & np.isfinite(dataframe["rsi"])
            & (dataframe["atr"] > 0)
            & (dataframe["volume"] > 0)
        )
        cutoff = self.config.get("mean_reversion_entry_cutoff")
        if cutoff is not None:
            signal_cutoff = Timestamp(cutoff) - Timedelta(
                minutes=timeframe_to_minutes(self.timeframe)
            )
            valid &= dataframe["date"] < signal_cutoff

        long_condition = (
            valid
            & (dataframe["close"] <= dataframe["long_threshold"])
            & (dataframe["rsi"] < self.long_rsi_threshold)
        )
        short_condition = (
            valid
            & (dataframe["close"] >= dataframe["short_threshold"])
            & (dataframe["rsi"] > self.short_rsi_threshold)
        )
        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            "mean_reversion_long",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            "mean_reversion_short",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0
        if self.exit_mode == "mean":
            dataframe.loc[dataframe["close"] >= dataframe["mean"], "exit_long"] = 1
            dataframe.loc[dataframe["close"] <= dataframe["mean"], "exit_short"] = 1
        return dataframe

    @staticmethod
    def _safe_float(value: object) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if np.isfinite(result) else None

    def _closed_signal_row(self, pair: str, at: datetime) -> Series | None:
        if self.dp is None:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        current_candle_open = timeframe_to_prev_date(self.timeframe, at)
        closed = dataframe.loc[dataframe["date"] < current_candle_open]
        return None if closed.empty else closed.iloc[-1]

    def _ensure_trade_plan(self, trade: Trade) -> bool:
        if trade.get_custom_data("mr_stop_rate", None) is not None:
            return True

        row = self._closed_signal_row(trade.pair, trade.open_date_utc)
        if row is None:
            return False
        atr = self._safe_float(row.get("atr"))
        entry_rate = self._safe_float(trade.open_rate)
        if atr is None or atr <= 0 or entry_rate is None or entry_rate <= 0:
            return False

        stop_rate = (
            entry_rate + self.hard_stop_atr * atr
            if trade.is_short
            else entry_rate - self.hard_stop_atr * atr
        )
        target_rate = (
            entry_rate - self.take_profit_atr * atr
            if trade.is_short
            else entry_rate + self.take_profit_atr * atr
        )
        if stop_rate <= 0 or target_rate <= 0:
            return False

        trade.set_custom_data("mr_entry_atr", atr)
        trade.set_custom_data("mr_stop_rate", stop_rate)
        trade.set_custom_data("mr_target_rate", target_rate)
        return True

    def order_filled(
        self,
        pair: str,
        trade: Trade,
        order: Order,
        current_time: datetime,
        **kwargs,
    ) -> None:
        if order.ft_order_side == trade.entry_side:
            self._ensure_trade_plan(trade)

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
        if not self._ensure_trade_plan(trade):
            return None
        stop_rate = self._safe_float(trade.get_custom_data("mr_stop_rate"))
        if stop_rate is None:
            return None
        return stoploss_from_absolute(
            stop_rate,
            current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

    def custom_roi(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        trade_duration: int,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float | None:
        if self.exit_mode != "tp" or not self._ensure_trade_plan(trade):
            return None
        target_rate = self._safe_float(trade.get_custom_data("mr_target_rate"))
        if target_rate is None:
            return None
        target_roi = trade.calc_profit_ratio(target_rate)
        return target_roi if np.isfinite(target_roi) else None

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        if current_time >= trade.open_date_utc + timedelta(hours=self.max_hold_hours):
            return f"max_hold_{self.max_hold_hours}h"
        return None

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
        return min(1.0, max_leverage)


class _V01:
    timeframe = "1h"
    ema_length = 20
    long_rsi_threshold = 25.0
    short_rsi_threshold = 75.0
    exit_mode = "mean"
    hard_stop_atr = 1.5
    max_hold_hours = 24


class _V02:
    timeframe = "1h"
    ema_length = 20
    long_rsi_threshold = 25.0
    short_rsi_threshold = 75.0
    exit_mode = "tp"
    hard_stop_atr = 1.5
    max_hold_hours = 48


class _V03:
    timeframe = "1h"
    ema_length = 20
    long_rsi_threshold = 30.0
    short_rsi_threshold = 70.0
    exit_mode = "mean"
    hard_stop_atr = 2.0
    max_hold_hours = 24


class _V04:
    timeframe = "1h"
    ema_length = 20
    long_rsi_threshold = 30.0
    short_rsi_threshold = 70.0
    exit_mode = "tp"
    hard_stop_atr = 2.0
    max_hold_hours = 48


class _V05:
    timeframe = "1h"
    ema_length = 50
    long_rsi_threshold = 25.0
    short_rsi_threshold = 75.0
    exit_mode = "mean"
    hard_stop_atr = 2.0
    max_hold_hours = 48


class _V06:
    timeframe = "1h"
    ema_length = 50
    long_rsi_threshold = 25.0
    short_rsi_threshold = 75.0
    exit_mode = "tp"
    hard_stop_atr = 2.0
    max_hold_hours = 24


class _V07:
    timeframe = "1h"
    ema_length = 50
    long_rsi_threshold = 30.0
    short_rsi_threshold = 70.0
    exit_mode = "mean"
    hard_stop_atr = 1.5
    max_hold_hours = 48


class _V08:
    timeframe = "1h"
    ema_length = 50
    long_rsi_threshold = 30.0
    short_rsi_threshold = 70.0
    exit_mode = "tp"
    hard_stop_atr = 1.5
    max_hold_hours = 24


class _V09:
    timeframe = "2h"
    ema_length = 20
    long_rsi_threshold = 25.0
    short_rsi_threshold = 75.0
    exit_mode = "mean"
    hard_stop_atr = 2.0
    max_hold_hours = 48


class _V10:
    timeframe = "2h"
    ema_length = 20
    long_rsi_threshold = 25.0
    short_rsi_threshold = 75.0
    exit_mode = "tp"
    hard_stop_atr = 2.0
    max_hold_hours = 24


class _V11:
    timeframe = "2h"
    ema_length = 20
    long_rsi_threshold = 30.0
    short_rsi_threshold = 70.0
    exit_mode = "mean"
    hard_stop_atr = 1.5
    max_hold_hours = 48


class _V12:
    timeframe = "2h"
    ema_length = 20
    long_rsi_threshold = 30.0
    short_rsi_threshold = 70.0
    exit_mode = "tp"
    hard_stop_atr = 1.5
    max_hold_hours = 24


class _V13:
    timeframe = "2h"
    ema_length = 50
    long_rsi_threshold = 25.0
    short_rsi_threshold = 75.0
    exit_mode = "mean"
    hard_stop_atr = 1.5
    max_hold_hours = 24


class _V14:
    timeframe = "2h"
    ema_length = 50
    long_rsi_threshold = 25.0
    short_rsi_threshold = 75.0
    exit_mode = "tp"
    hard_stop_atr = 1.5
    max_hold_hours = 48


class _V15:
    timeframe = "2h"
    ema_length = 50
    long_rsi_threshold = 30.0
    short_rsi_threshold = 70.0
    exit_mode = "mean"
    hard_stop_atr = 2.0
    max_hold_hours = 24


class _V16:
    timeframe = "2h"
    ema_length = 50
    long_rsi_threshold = 30.0
    short_rsi_threshold = 70.0
    exit_mode = "tp"
    hard_stop_atr = 2.0
    max_hold_hours = 48


class MeanReversionD15V01Strategy(_V01, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V02Strategy(_V02, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V03Strategy(_V03, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V04Strategy(_V04, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V05Strategy(_V05, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V06Strategy(_V06, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V07Strategy(_V07, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V08Strategy(_V08, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V09Strategy(_V09, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V10Strategy(_V10, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V11Strategy(_V11, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V12Strategy(_V12, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V13Strategy(_V13, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V14Strategy(_V14, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V15Strategy(_V15, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD15V16Strategy(_V16, MeanReversionFullHistoryBase):
    entry_atr_mult = 1.5


class MeanReversionD20V01Strategy(_V01, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V02Strategy(_V02, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V03Strategy(_V03, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V04Strategy(_V04, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V05Strategy(_V05, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V06Strategy(_V06, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V07Strategy(_V07, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V08Strategy(_V08, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V09Strategy(_V09, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V10Strategy(_V10, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V11Strategy(_V11, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V12Strategy(_V12, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V13Strategy(_V13, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V14Strategy(_V14, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V15Strategy(_V15, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD20V16Strategy(_V16, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.0


class MeanReversionD25V01Strategy(_V01, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V02Strategy(_V02, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V03Strategy(_V03, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V04Strategy(_V04, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V05Strategy(_V05, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V06Strategy(_V06, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V07Strategy(_V07, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V08Strategy(_V08, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V09Strategy(_V09, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V10Strategy(_V10, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V11Strategy(_V11, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V12Strategy(_V12, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V13Strategy(_V13, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V14Strategy(_V14, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V15Strategy(_V15, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5


class MeanReversionD25V16Strategy(_V16, MeanReversionFullHistoryBase):
    entry_atr_mult = 2.5
