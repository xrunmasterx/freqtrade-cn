from __future__ import annotations

from datetime import datetime

import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.indicators.qqe_mod import add_qqe_mod
from freqtrade.indicators.supertrend import add_supertrend
from freqtrade.strategy import merge_informative_pair

from QQESupertrendStrategy import QQESupertrendStrategy


class QQESupertrendResearchBase(QQESupertrendStrategy):
    timeframe = "1h"
    informative_timeframe = "4h"
    daily_timeframe = "1d"
    startup_candle_count = 240

    adx_threshold = 0.0
    max_distance_atr = 100.0
    max_4h_trend_age = 10000.0
    require_daily_regime = False
    long_enabled = True
    short_enabled = True
    eth_long_enabled = True
    leverage_value = 2.0

    def _higher_column(self, column: str) -> str:
        return f"{column}_{self.informative_timeframe}"

    def _regime_column(self, column: str) -> str:
        return f"{column}_{self.daily_timeframe}"

    @staticmethod
    def _populate_supertrend_context(dataframe: DataFrame) -> DataFrame:
        dataframe = QQESupertrendStrategy._populate_4h_indicators(dataframe)
        trend = pd.to_numeric(dataframe["supertrend_trend"], errors="coerce")
        trend_group = trend.ne(trend.shift()).cumsum()
        dataframe["supertrend_trend_age"] = trend.groupby(trend_group).cumcount()
        return dataframe[
            [
                "date",
                "supertrend_up",
                "supertrend_down",
                "supertrend_trend",
                "supertrend_buy_signal",
                "supertrend_sell_signal",
                "supertrend_change",
                "supertrend_trend_age",
            ]
        ]

    def informative_pairs(self):
        data_provider = getattr(self, "dp", None)
        pairs = (
            data_provider.current_whitelist()
            if data_provider
            else self.config.get("exchange", {}).get("pair_whitelist", [])
        )
        return [
            (pair, timeframe)
            for pair in pairs
            for timeframe in (self.informative_timeframe, self.daily_timeframe)
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = add_supertrend(dataframe, prefix="supertrend")
        dataframe = add_qqe_mod(dataframe, prefix="qqe_mod")
        dataframe["atr_14"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["adx_14"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)
        supertrend_line = dataframe["supertrend_up"].combine_first(dataframe["supertrend_down"])
        dataframe["supertrend_distance_atr"] = (
            (pd.to_numeric(dataframe["close"], errors="coerce") - supertrend_line).abs()
            / dataframe["atr_14"]
        )

        data_provider = getattr(self, "dp", None)
        if data_provider:
            informative_4h = data_provider.get_pair_dataframe(
                pair=metadata["pair"], timeframe=self.informative_timeframe
            )
            informative_4h = self._populate_supertrend_context(informative_4h)
            dataframe = merge_informative_pair(
                dataframe,
                informative_4h,
                self.timeframe,
                self.informative_timeframe,
                ffill=True,
            )

            informative_1d = data_provider.get_pair_dataframe(
                pair=metadata["pair"], timeframe=self.daily_timeframe
            )
            informative_1d = self._populate_supertrend_context(informative_1d)
            dataframe = merge_informative_pair(
                dataframe,
                informative_1d,
                self.timeframe,
                self.daily_timeframe,
                ffill=True,
            )
        else:
            dataframe[self._regime_column("supertrend_trend")] = dataframe["supertrend_trend"]
            dataframe[self._regime_column("supertrend_trend_age")] = 0

        return dataframe

    def _long_regime(self, dataframe: DataFrame) -> pd.Series:
        local_long = self._numeric_column(dataframe, "supertrend_trend") == 1
        higher_long = self._numeric_column(dataframe, self._higher_column("supertrend_trend")) == 1
        daily_long = (
            self._numeric_column(dataframe, self._regime_column("supertrend_trend")) == 1
            if self.require_daily_regime
            else pd.Series(True, index=dataframe.index)
        )
        return local_long & higher_long & daily_long

    def _short_regime(self, dataframe: DataFrame) -> pd.Series:
        local_short = self._numeric_column(dataframe, "supertrend_trend") == -1
        higher_short = (
            self._numeric_column(dataframe, self._higher_column("supertrend_trend")) == -1
        )
        daily_short = (
            self._numeric_column(dataframe, self._regime_column("supertrend_trend")) == -1
            if self.require_daily_regime
            else pd.Series(True, index=dataframe.index)
        )
        return local_short & higher_short & daily_short

    def _quality_filter(self, dataframe: DataFrame) -> pd.Series:
        adx_ok = self._numeric_column(dataframe, "adx_14") >= self.adx_threshold
        distance_ok = (
            self._numeric_column(dataframe, "supertrend_distance_atr") <= self.max_distance_atr
        )
        age_ok = (
            self._numeric_column(dataframe, self._higher_column("supertrend_trend_age"))
            <= self.max_4h_trend_age
        )
        return adx_ok & distance_ok & age_ok

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        volume_ok = self._numeric_column(dataframe, "volume") > 0
        quality_ok = self._quality_filter(dataframe)

        long_condition = (
            self.long_enabled
            & self._long_regime(dataframe)
            & self._bool_column(dataframe, "qqe_mod_up_event")
            & quality_ok
            & volume_ok
        )
        if metadata["pair"].startswith("ETH/"):
            long_condition = long_condition & self.eth_long_enabled

        short_condition = (
            self.short_enabled
            & self._short_regime(dataframe)
            & self._bool_column(dataframe, "qqe_mod_down_event")
            & quality_ok
            & volume_ok
        )

        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            f"{self.__class__.__name__}_long",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            f"{self.__class__.__name__}_short",
        )
        return dataframe

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
        return min(self.leverage_value, max_leverage)


class QQESupertrendDailyRegimeStrategy(QQESupertrendResearchBase):
    """Only trade in the direction of both daily and 4h Supertrend."""

    require_daily_regime = True
    leverage_value = 2.0


class QQESupertrendProfitGuardStrategy(QQESupertrendResearchBase):
    """Baseline entries with tighter loss and trailing profit protection."""

    stoploss = -0.05
    trailing_stop = True
    trailing_stop_positive = 0.015
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True
    leverage_value = 2.0


class QQESupertrendHighWinRateStrategy(QQESupertrendResearchBase):
    """Lower-frequency version requiring daily regime, trend strength and no overextension."""

    require_daily_regime = True
    adx_threshold = 20.0
    max_distance_atr = 2.0
    max_4h_trend_age = 24.0
    eth_long_enabled = False
    stoploss = -0.05
    leverage_value = 1.5


class QQESupertrendShortOnlyDailyDownStrategy(QQESupertrendResearchBase):
    """Bear-market version: short only when daily and 4h Supertrend are both down."""

    require_daily_regime = True
    long_enabled = False
    short_enabled = True
    stoploss = -0.06
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True
    leverage_value = 2.0


class QQESupertrendHighFrequencyLowLeverageStrategy(QQESupertrendResearchBase):
    """Higher-frequency test: use 1h signals only, with lower leverage and faster cooldown."""

    require_daily_regime = False
    stoploss = -0.04
    leverage_value = 1.0

    @property
    def protections(self):
        return [{"method": "CooldownPeriod", "stop_duration_candles": 1}]

    def _long_regime(self, dataframe: DataFrame) -> pd.Series:
        return self._numeric_column(dataframe, "supertrend_trend") == 1

    def _short_regime(self, dataframe: DataFrame) -> pd.Series:
        return self._numeric_column(dataframe, "supertrend_trend") == -1


class QQESupertrendStrictHighLeverageStrategy(QQESupertrendResearchBase):
    """Higher leverage only after daily/4h alignment plus strength and anti-chase filters."""

    require_daily_regime = True
    adx_threshold = 25.0
    max_distance_atr = 1.5
    max_4h_trend_age = 18.0
    eth_long_enabled = False
    stoploss = -0.04
    trailing_stop = True
    trailing_stop_positive = 0.018
    trailing_stop_positive_offset = 0.035
    trailing_only_offset_is_reached = True
    leverage_value = 3.0
