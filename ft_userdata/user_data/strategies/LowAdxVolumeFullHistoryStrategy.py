from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy
from pandas import DataFrame


class LowAdxVolumeFullHistoryStrategy(IStrategy):
    """Prior-20 Donchian breakout screened by low ADX and non-extreme volume."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "30m"
    process_only_new_candles = True
    startup_candle_count = 50

    max_open_trades = 1
    position_adjustment_enable = False
    minimal_roi: ClassVar[dict[str, float]] = {"0": 0.03}
    stoploss = -0.015
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    order_types: ClassVar[dict[str, str | bool]] = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    channel_length = 20
    adx_length = 14
    volume_length = 20
    adx_max = 21.0
    volume_ratio_max = 1.5
    max_hold_hours = 48

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["donchian_high"] = (
            dataframe["high"].rolling(self.channel_length).max().shift(1)
        )
        dataframe["donchian_low"] = (
            dataframe["low"].rolling(self.channel_length).min().shift(1)
        )
        dataframe["adx_14"] = ta.ADX(dataframe, timeperiod=self.adx_length)
        dataframe["volume_mean_20_prior"] = (
            dataframe["volume"].shift(1).rolling(self.volume_length).mean()
        )
        dataframe["volume_ratio"] = (
            dataframe["volume"] / dataframe["volume_mean_20_prior"]
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        common = (
            (dataframe["adx_14"] <= self.adx_max)
            & (dataframe["volume"] > 0)
            & (dataframe["volume_mean_20_prior"] > 0)
            & (dataframe["volume_ratio"] <= self.volume_ratio_max)
        )
        long_condition = (
            common
            & (dataframe["close"] > dataframe["donchian_high"])
            & (dataframe["close"].shift(1) <= dataframe["donchian_high"].shift(1))
        )
        short_condition = (
            common
            & (dataframe["close"] < dataframe["donchian_low"])
            & (dataframe["close"].shift(1) >= dataframe["donchian_low"].shift(1))
        )
        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            "low_adx_volume_donchian_long",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            "low_adx_volume_donchian_short",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0
        return dataframe

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


class LowAdxVolumeA15V125H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 15.0
    volume_ratio_max = 1.25
    max_hold_hours = 48


class LowAdxVolumeA15V125H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 15.0
    volume_ratio_max = 1.25
    max_hold_hours = 72


class LowAdxVolumeA15V150H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 15.0
    volume_ratio_max = 1.5
    max_hold_hours = 48


class LowAdxVolumeA15V150H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 15.0
    volume_ratio_max = 1.5
    max_hold_hours = 72


class LowAdxVolumeA15V200H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 15.0
    volume_ratio_max = 2.0
    max_hold_hours = 48


class LowAdxVolumeA15V200H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 15.0
    volume_ratio_max = 2.0
    max_hold_hours = 72


class LowAdxVolumeA18V125H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 18.0
    volume_ratio_max = 1.25
    max_hold_hours = 48


class LowAdxVolumeA18V125H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 18.0
    volume_ratio_max = 1.25
    max_hold_hours = 72


class LowAdxVolumeA18V150H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 18.0
    volume_ratio_max = 1.5
    max_hold_hours = 48


class LowAdxVolumeA18V150H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 18.0
    volume_ratio_max = 1.5
    max_hold_hours = 72


class LowAdxVolumeA18V200H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 18.0
    volume_ratio_max = 2.0
    max_hold_hours = 48


class LowAdxVolumeA18V200H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 18.0
    volume_ratio_max = 2.0
    max_hold_hours = 72


class LowAdxVolumeA21V125H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 21.0
    volume_ratio_max = 1.25
    max_hold_hours = 48


class LowAdxVolumeA21V125H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 21.0
    volume_ratio_max = 1.25
    max_hold_hours = 72


class LowAdxVolumeA21V150H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 21.0
    volume_ratio_max = 1.5
    max_hold_hours = 48


class LowAdxVolumeA21V150H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 21.0
    volume_ratio_max = 1.5
    max_hold_hours = 72


class LowAdxVolumeA21V200H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 21.0
    volume_ratio_max = 2.0
    max_hold_hours = 48


class LowAdxVolumeA21V200H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 21.0
    volume_ratio_max = 2.0
    max_hold_hours = 72


class LowAdxVolumeA24V125H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 24.0
    volume_ratio_max = 1.25
    max_hold_hours = 48


class LowAdxVolumeA24V125H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 24.0
    volume_ratio_max = 1.25
    max_hold_hours = 72


class LowAdxVolumeA24V150H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 24.0
    volume_ratio_max = 1.5
    max_hold_hours = 48


class LowAdxVolumeA24V150H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 24.0
    volume_ratio_max = 1.5
    max_hold_hours = 72


class LowAdxVolumeA24V200H48Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 24.0
    volume_ratio_max = 2.0
    max_hold_hours = 48


class LowAdxVolumeA24V200H72Strategy(LowAdxVolumeFullHistoryStrategy):
    adx_max = 24.0
    volume_ratio_max = 2.0
    max_hold_hours = 72
