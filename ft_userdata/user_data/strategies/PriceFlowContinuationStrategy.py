from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame


class PriceFlowContinuationStrategy(IStrategy):
    """Trade confirmed continuation after a high-volume structural displacement.

    ``flow_imbalance`` is a candle/volume pressure proxy.  It is deliberately not
    presented as true aggressor order flow or as evidence of a particular actor.
    """

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 960

    minimal_roi: ClassVar[dict[str, float]] = {
        "0": 0.06,
        "720": 0.04,
        "1440": 0.02,
    }
    stoploss = -0.03
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False

    displacement_volume_min = 1.5
    displacement_body_atr_min = 0.7
    displacement_close_location_min = 0.6
    retest_window = 8
    retest_tolerance = 0.002
    retest_volume_max = 1.5
    flow_fast_threshold = 0.10
    flow_slow_threshold = 0.03
    max_directional_return_24h = 0.08

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "ema20": {"color": "#4C9AFF"},
            "rolling_vwap_24h": {"color": "#FFAB00"},
            "donchian_high_48": {"color": "#36B37E"},
            "donchian_low_48": {"color": "#FF5630"},
        },
        "subplots": {
            "Flow pressure proxy": {
                "flow_imbalance_8": {"color": "#6554C0"},
                "flow_imbalance_24": {"color": "#00B8D9"},
            },
            "Volume structure": {
                "relative_volume": {"color": "#FF8B00"},
            },
        },
    }

    @property
    def protections(self):
        return [{"method": "CooldownPeriod", "stop_duration_candles": 4}]

    def informative_pairs(self):
        data_provider = getattr(self, "dp", None)
        pairs = (
            data_provider.current_whitelist()
            if data_provider
            else self.config.get("exchange", {}).get("pair_whitelist", [])
        )
        return [(pair, timeframe) for pair in pairs for timeframe in ("1h", "4h")]

    @staticmethod
    def _populate_1h_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["return_24h"] = dataframe["close"] / dataframe["close"].shift(24) - 1
        dataframe["long_trend"] = (
            (dataframe["close"] > dataframe["ema50"])
            & (dataframe["ema20"] > dataframe["ema50"])
        )
        dataframe["short_trend"] = (
            (dataframe["close"] < dataframe["ema50"])
            & (dataframe["ema20"] < dataframe["ema50"])
        )
        return dataframe[
            ["date", "close", "ema20", "ema50", "return_24h", "long_trend", "short_trend"]
        ]

    @staticmethod
    def _populate_4h_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["ema50_slope"] = dataframe["ema50"] / dataframe["ema50"].shift(6) - 1
        dataframe["long_regime"] = (
            (dataframe["close"] > dataframe["ema200"])
            & (dataframe["ema50"] > dataframe["ema200"])
            & (dataframe["ema50_slope"] > 0)
        )
        dataframe["short_regime"] = (
            (dataframe["close"] < dataframe["ema200"])
            & (dataframe["ema50"] < dataframe["ema200"])
            & (dataframe["ema50_slope"] < 0)
        )
        return dataframe[
            ["date", "close", "ema50", "ema200", "ema50_slope", "long_regime", "short_regime"]
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        previous_close = dataframe["close"].shift(1)
        candle_range = (dataframe["high"] - dataframe["low"]).replace(0, np.nan)
        true_range = pd.concat(
            [
                dataframe["high"] - dataframe["low"],
                (dataframe["high"] - previous_close).abs(),
                (dataframe["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        dataframe["atr14"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["donchian_high_48"] = dataframe["high"].rolling(48).max().shift(1)
        dataframe["donchian_low_48"] = dataframe["low"].rolling(48).min().shift(1)
        dataframe["close_location"] = (
            (2 * dataframe["close"] - dataframe["high"] - dataframe["low"]) / candle_range
        ).clip(-1, 1)
        dataframe["body_atr"] = (
            (dataframe["close"] - dataframe["open"]).abs() / dataframe["atr14"]
        )
        rolling_volume_median = dataframe["volume"].rolling(96).median().replace(0, np.nan)
        dataframe["relative_volume"] = dataframe["volume"] / rolling_volume_median

        typical_price = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3
        rolling_volume = dataframe["volume"].rolling(96).sum().replace(0, np.nan)
        dataframe["rolling_vwap_24h"] = (
            (typical_price * dataframe["volume"]).rolling(96).sum() / rolling_volume
        )
        signed_volume = dataframe["volume"] * dataframe["close_location"]
        dataframe["flow_imbalance_8"] = (
            signed_volume.rolling(8).sum()
            / dataframe["volume"].rolling(8).sum().replace(0, np.nan)
        )
        dataframe["flow_imbalance_24"] = (
            signed_volume.rolling(24).sum()
            / dataframe["volume"].rolling(24).sum().replace(0, np.nan)
        )

        close_location_min = self.displacement_close_location_min
        dataframe["long_displacement"] = (
            (dataframe["close"] > dataframe["donchian_high_48"])
            & (dataframe["body_atr"] >= self.displacement_body_atr_min)
            & (dataframe["relative_volume"] >= self.displacement_volume_min)
            & (dataframe["close_location"] >= close_location_min)
        )
        dataframe["short_displacement"] = (
            (dataframe["close"] < dataframe["donchian_low_48"])
            & (dataframe["body_atr"] >= self.displacement_body_atr_min)
            & (dataframe["relative_volume"] >= self.displacement_volume_min)
            & (dataframe["close_location"] <= -close_location_min)
        )

        dataframe["long_breakout_level"] = dataframe["donchian_high_48"].where(
            dataframe["long_displacement"]
        ).ffill(limit=self.retest_window)
        dataframe["short_breakout_level"] = dataframe["donchian_low_48"].where(
            dataframe["short_displacement"]
        ).ffill(limit=self.retest_window)
        dataframe["recent_long_displacement"] = (
            dataframe["long_displacement"]
            .shift(1)
            .rolling(self.retest_window)
            .max()
            .fillna(0)
            > 0
        )
        dataframe["recent_short_displacement"] = (
            dataframe["short_displacement"]
            .shift(1)
            .rolling(self.retest_window)
            .max()
            .fillna(0)
            > 0
        )
        dataframe["long_retest"] = (
            dataframe["recent_long_displacement"]
            & (
                dataframe["low"]
                <= dataframe["long_breakout_level"] * (1 + self.retest_tolerance)
            )
            & (dataframe["close"] > dataframe["long_breakout_level"])
            & (dataframe["close"] > dataframe["open"])
            & (dataframe["close_location"] >= 0.35)
            & (dataframe["relative_volume"] <= self.retest_volume_max)
        )
        dataframe["short_retest"] = (
            dataframe["recent_short_displacement"]
            & (
                dataframe["high"]
                >= dataframe["short_breakout_level"] * (1 - self.retest_tolerance)
            )
            & (dataframe["close"] < dataframe["short_breakout_level"])
            & (dataframe["close"] < dataframe["open"])
            & (dataframe["close_location"] <= -0.35)
            & (dataframe["relative_volume"] <= self.retest_volume_max)
        )

        data_provider = getattr(self, "dp", None)
        if data_provider:
            informative_1h = self._populate_1h_indicators(
                data_provider.get_pair_dataframe(pair=metadata["pair"], timeframe="1h")
            )
            dataframe = merge_informative_pair(
                dataframe, informative_1h, self.timeframe, "1h", ffill=True
            )
            informative_4h = self._populate_4h_indicators(
                data_provider.get_pair_dataframe(pair=metadata["pair"], timeframe="4h")
            )
            dataframe = merge_informative_pair(
                dataframe, informative_4h, self.timeframe, "4h", ffill=True
            )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        volume_ok = dataframe["volume"] > 0
        long_condition = (
            dataframe["long_retest"].fillna(False)
            & dataframe["long_trend_1h"].fillna(False)
            & dataframe["long_regime_4h"].fillna(False)
            & (dataframe["close"] > dataframe["rolling_vwap_24h"])
            & (dataframe["close"] > dataframe["ema20"])
            & (dataframe["flow_imbalance_8"] >= self.flow_fast_threshold)
            & (dataframe["flow_imbalance_24"] >= self.flow_slow_threshold)
            & (dataframe["return_24h_1h"] <= self.max_directional_return_24h)
            & volume_ok
        )
        short_condition = (
            dataframe["short_retest"].fillna(False)
            & dataframe["short_trend_1h"].fillna(False)
            & dataframe["short_regime_4h"].fillna(False)
            & (dataframe["close"] < dataframe["rolling_vwap_24h"])
            & (dataframe["close"] < dataframe["ema20"])
            & (dataframe["flow_imbalance_8"] <= -self.flow_fast_threshold)
            & (dataframe["flow_imbalance_24"] <= -self.flow_slow_threshold)
            & (dataframe["return_24h_1h"] >= -self.max_directional_return_24h)
            & volume_ok
        )

        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            "price_flow_retest_long",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            "price_flow_retest_short",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        volume_ok = dataframe["volume"] > 0
        long_exit = (
            (
                (dataframe["close"] < dataframe["rolling_vwap_24h"])
                & (dataframe["flow_imbalance_8"] < 0)
            )
            | dataframe["short_displacement"].fillna(False)
        ) & volume_ok
        short_exit = (
            (
                (dataframe["close"] > dataframe["rolling_vwap_24h"])
                & (dataframe["flow_imbalance_8"] > 0)
            )
            | dataframe["long_displacement"].fillna(False)
        ) & volume_ok
        dataframe.loc[long_exit, ["exit_long", "exit_tag"]] = (1, "flow_invalidated_long")
        dataframe.loc[short_exit, ["exit_short", "exit_tag"]] = (1, "flow_invalidated_short")
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
