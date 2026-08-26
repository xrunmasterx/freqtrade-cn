from __future__ import annotations

from typing import ClassVar

import numpy as np
import pandas as pd
import talib.abstract as ta
from DonchianCounterMomentumRegimeStrategy import DonchianCounterMomentumRegimeStrategy
from freqtrade.indicators.supertrend import add_supertrend
from freqtrade.strategy import merge_informative_pair
from pandas import DataFrame, Series


class DonchianMultiTimeframeRegimeStrategy(DonchianCounterMomentumRegimeStrategy):
    """Use 4h and 1d direction agreement to gate 15m breakout entries.

    A disagreement or unavailable higher-timeframe direction is explicitly neutral. The
    neutral state abstains instead of routing a signal to a second, unvalidated strategy.
    """

    regime_timeframe = "4h"
    daily_timeframe = "1d"
    supertrend_period = 10
    supertrend_multiplier = 3.0
    regime_adx_length = 14
    regime_adx_threshold = 15.0

    regime_state_column = "regime_state"
    regime_4h_column = "regime_trend_4h"
    regime_1d_column = "regime_trend_1d"
    regime_adx_column = "regime_adx"

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "donchian_high": {"color": "#36B37E"},
            "donchian_low": {"color": "#FF5630"},
        },
        "subplots": {
            "Multi-timeframe regime": {
                "regime_trend_4h": {"color": "#4C9AFF"},
                "regime_trend_1d": {"color": "#6554C0"},
            }
        },
    }

    @staticmethod
    def _numeric_column(dataframe: DataFrame, column: str) -> Series:
        if column not in dataframe:
            return Series(np.nan, index=dataframe.index, dtype="float64")
        return pd.to_numeric(dataframe[column], errors="coerce")

    @classmethod
    def classify_regime(cls, dataframe: DataFrame) -> Series:
        """Return only aligned trend states; every other state is neutral."""
        trend_4h = cls._numeric_column(dataframe, cls.regime_4h_column)
        trend_1d = cls._numeric_column(dataframe, cls.regime_1d_column)
        state = Series("neutral", index=dataframe.index, dtype="string")
        adx = cls._numeric_column(dataframe, cls.regime_adx_column)
        strength_ok = adx >= cls.regime_adx_threshold
        state.loc[(trend_4h == 1) & (trend_1d == 1) & strength_ok] = "trend_up"
        state.loc[(trend_4h == -1) & (trend_1d == -1) & strength_ok] = "trend_down"
        return state

    @classmethod
    def _populate_regime_frame(cls, dataframe: DataFrame) -> DataFrame:
        result = add_supertrend(
            dataframe,
            period=cls.supertrend_period,
            multiplier=cls.supertrend_multiplier,
            prefix="regime",
        )
        trend = Series(np.nan, index=result.index, dtype="float64")
        trend.loc[result["regime_up"].notna()] = 1.0
        trend.loc[result["regime_down"].notna()] = -1.0
        return DataFrame({"date": result["date"], "regime_trend": trend})

    def informative_pairs(self) -> list[tuple[str, str]]:
        data_provider = getattr(self, "dp", None)
        pairs = (
            data_provider.current_whitelist()
            if data_provider
            else self.config.get("exchange", {}).get("pair_whitelist", [])
        )
        return [
            (pair, timeframe)
            for pair in pairs
            for timeframe in (self.regime_timeframe, self.daily_timeframe)
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        result = dataframe.copy()
        result["donchian_high"] = (
            result["high"].rolling(self.channel_length).max().shift(1)
        )
        result["donchian_low"] = result["low"].rolling(self.channel_length).min().shift(1)
        result["directional_return"] = (
            result["close"] / result["close"].shift(self.momentum_lookback) - 1
        )
        result[self.regime_adx_column] = ta.ADX(result, timeperiod=self.regime_adx_length)

        data_provider = getattr(self, "dp", None)
        if data_provider:
            pair = metadata["pair"]
            for timeframe, column in (
                (self.regime_timeframe, self.regime_4h_column),
                (self.daily_timeframe, self.regime_1d_column),
            ):
                informative = data_provider.get_pair_dataframe(pair=pair, timeframe=timeframe)
                if informative.empty:
                    result[column] = np.nan
                    continue
                regime = self._populate_regime_frame(informative)
                result = merge_informative_pair(
                    result,
                    regime,
                    self.timeframe,
                    timeframe,
                    ffill=True,
                )
        else:
            result[self.regime_4h_column] = np.nan
            result[self.regime_1d_column] = np.nan

        result[self.regime_state_column] = self.classify_regime(result)
        return result

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_breakout = (
            (dataframe["close"] > dataframe["donchian_high"])
            & (dataframe["close"].shift(1) <= dataframe["donchian_high"].shift(1))
        )
        short_breakout = (
            (dataframe["close"] < dataframe["donchian_low"])
            & (dataframe["close"].shift(1) >= dataframe["donchian_low"].shift(1))
        )
        long_condition = (
            long_breakout
            & (dataframe["directional_return"] <= self.max_directional_return_72h)
            & (dataframe[self.regime_state_column] == "trend_up")
        )
        short_condition = (
            short_breakout
            & (-dataframe["directional_return"] <= self.max_directional_return_72h)
            & (dataframe[self.regime_state_column] == "trend_down")
        )
        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            "donchian_mtf_trend_long",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            "donchian_mtf_trend_short",
        )
        return dataframe
