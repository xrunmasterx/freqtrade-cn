from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import pandas as pd
import talib.abstract as ta
from freqtrade.indicators.qqe_mod import add_qqe_mod
from freqtrade.indicators.supertrend import add_supertrend
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame


class QQESupertrendStrategy(IStrategy):
    """
    QQE Mod + Supertrend futures strategy.

    The 4h Supertrend defines trade direction, while 1h QQE Mod events trigger entries.
    """

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "1h"
    informative_timeframe = "4h"
    process_only_new_candles = True

    minimal_roi: ClassVar[dict[str, float]] = {"0": 100}
    stoploss = -0.05
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False
    startup_candle_count = 240

    adx_threshold = 15.0
    max_distance_atr = 5.0
    max_4h_trend_age = 72.0

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "supertrend_up": {"color": "green", "fill_to": "supertrend_price"},
            "supertrend_down": {"color": "red", "fill_to": "supertrend_price"},
            "supertrend_price": {"color": "white"},
        },
        "subplots": {
            "QQE MOD": {
                "qqe_mod_hist": {"type": "bar", "color": "#64748b"},
                "qqe_mod_up": {"type": "bar", "color": "#22c55e"},
                "qqe_mod_down": {"type": "bar", "color": "#ef4444"},
                "qqe_mod_trend": {"type": "line", "color": "#eab308"},
            }
        },
    }

    @property
    def protections(self):
        return [{"method": "CooldownPeriod", "stop_duration_candles": 3}]

    def informative_pairs(self):
        data_provider = getattr(self, "dp", None)
        pairs = (
            data_provider.current_whitelist()
            if data_provider
            else self.config.get("exchange", {}).get("pair_whitelist", [])
        )
        return [(pair, self.informative_timeframe) for pair in pairs]

    @staticmethod
    def _add_strategy_supertrend_columns(dataframe: DataFrame) -> DataFrame:
        trend = pd.Series(float("nan"), index=dataframe.index, dtype="float64")
        trend.loc[dataframe["supertrend_up"].notna()] = 1.0
        trend.loc[dataframe["supertrend_down"].notna()] = -1.0
        previous_trend = trend.shift(1)
        changed = trend.notna() & previous_trend.notna() & trend.ne(previous_trend)

        dataframe["supertrend_trend"] = trend
        dataframe["supertrend_buy_signal"] = dataframe["close"].where(changed & trend.eq(1))
        dataframe["supertrend_sell_signal"] = dataframe["close"].where(changed & trend.eq(-1))
        dataframe["supertrend_change"] = trend.diff().where(changed)
        return dataframe

    @staticmethod
    def _populate_4h_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = add_supertrend(dataframe, prefix="supertrend")
        dataframe = QQESupertrendStrategy._add_strategy_supertrend_columns(dataframe)
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

    @staticmethod
    def _bool_column(dataframe: DataFrame, column: str) -> pd.Series:
        if column not in dataframe:
            return pd.Series(False, index=dataframe.index)
        return dataframe[column].fillna(False).astype(bool)

    @staticmethod
    def _numeric_column(dataframe: DataFrame, column: str) -> pd.Series:
        if column not in dataframe:
            return pd.Series(float("nan"), index=dataframe.index)
        return pd.to_numeric(dataframe[column], errors="coerce")

    def _informative_column(self, column: str) -> str:
        return f"{column}_{self.informative_timeframe}"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = add_supertrend(dataframe, prefix="supertrend")
        dataframe = self._add_strategy_supertrend_columns(dataframe)
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
            informative_4h = self._populate_4h_indicators(informative_4h)
            dataframe = merge_informative_pair(
                dataframe,
                informative_4h,
                self.timeframe,
                self.informative_timeframe,
                ffill=True,
            )
        else:
            dataframe[self._informative_column("supertrend_trend")] = dataframe[
                "supertrend_trend"
            ]
            dataframe[self._informative_column("supertrend_trend_age")] = 0

        return dataframe

    def _quality_filter(self, dataframe: DataFrame) -> pd.Series:
        adx_ok = self._numeric_column(dataframe, "adx_14") >= self.adx_threshold
        distance_ok = (
            self._numeric_column(dataframe, "supertrend_distance_atr") <= self.max_distance_atr
        )
        age_ok = (
            self._numeric_column(
                dataframe, self._informative_column("supertrend_trend_age")
            )
            <= self.max_4h_trend_age
        )
        return adx_ok & distance_ok & age_ok

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        volume_ok = self._numeric_column(dataframe, "volume") > 0
        quality_ok = self._quality_filter(dataframe)

        long_condition = (
            (self._numeric_column(dataframe, self._informative_column("supertrend_trend")) == 1)
            & self._bool_column(dataframe, "qqe_mod_up_event")
            & (self._numeric_column(dataframe, "supertrend_trend") == 1)
            & quality_ok
            & volume_ok
        )
        short_condition = (
            (self._numeric_column(dataframe, self._informative_column("supertrend_trend")) == -1)
            & self._bool_column(dataframe, "qqe_mod_down_event")
            & (self._numeric_column(dataframe, "supertrend_trend") == -1)
            & quality_ok
            & volume_ok
        )

        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (1, "qqe_st_long")
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (1, "qqe_st_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        volume_ok = self._numeric_column(dataframe, "volume") > 0
        close = self._numeric_column(dataframe, "close")

        long_exit = (
            self._numeric_column(dataframe, "supertrend_sell_signal").notna()
            | self._bool_column(dataframe, "qqe_mod_down_event")
            | (close < self._numeric_column(dataframe, "supertrend_up")).fillna(False)
        ) & volume_ok
        short_exit = (
            self._numeric_column(dataframe, "supertrend_buy_signal").notna()
            | self._bool_column(dataframe, "qqe_mod_up_event")
            | (close > self._numeric_column(dataframe, "supertrend_down")).fillna(False)
        ) & volume_ok

        dataframe.loc[long_exit, ["exit_long", "exit_tag"]] = (1, "qqe_st_long_exit")
        dataframe.loc[short_exit, ["exit_short", "exit_tag"]] = (1, "qqe_st_short_exit")
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
        return min(2.0, max_leverage)
