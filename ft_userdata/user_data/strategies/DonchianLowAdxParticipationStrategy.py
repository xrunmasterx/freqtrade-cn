from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy


def wilder_rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder smoothing used by the factor screen that selected this candidate."""
    return series.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


class DonchianLowAdxParticipationStrategy(IStrategy):
    """Trade prior-20 Donchian breakouts emerging from low-ADX, non-spike volume."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "30m"
    process_only_new_candles = True
    startup_candle_count = 40

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
    max_adx = 18.06
    volume_baseline_length = 20
    max_relative_volume = 1.5
    max_hold_hours = 72
    default_leverage = 1.0

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "donchian_high": {"color": "#36B37E"},
            "donchian_low": {"color": "#FF5630"},
        },
        "subplots": {
            "Low-ADX participation": {
                "adx14": {"color": "#FFAB00"},
                "relative_volume": {"color": "#00B8D9"},
            }
        },
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.copy()
        previous_close = dataframe["close"].shift(1)
        true_range = pd.concat(
            [
                dataframe["high"] - dataframe["low"],
                (dataframe["high"] - previous_close).abs(),
                (dataframe["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        up_move = dataframe["high"].diff()
        down_move = -dataframe["low"].diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        smoothed_true_range = wilder_rma(true_range, self.adx_length)
        plus_di = 100 * wilder_rma(plus_dm, self.adx_length) / smoothed_true_range
        minus_di = 100 * wilder_rma(minus_dm, self.adx_length) / smoothed_true_range
        directional_sum = (plus_di + minus_di).replace(0, float("nan"))
        dx = 100 * (plus_di - minus_di).abs() / directional_sum

        dataframe["adx14"] = wilder_rma(dx, self.adx_length)
        dataframe["donchian_high"] = (
            dataframe["high"].rolling(self.channel_length).max().shift(1)
        )
        dataframe["donchian_low"] = (
            dataframe["low"].rolling(self.channel_length).min().shift(1)
        )
        prior_volume_mean = (
            dataframe["volume"]
            .shift(1)
            .rolling(self.volume_baseline_length)
            .mean()
            .replace(0, float("nan"))
        )
        dataframe["relative_volume"] = dataframe["volume"] / prior_volume_mean
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        participation = (dataframe["adx14"] <= self.max_adx) & (
            dataframe["relative_volume"] <= self.max_relative_volume
        )
        long_condition = (
            (dataframe["close"] > dataframe["donchian_high"])
            & (dataframe["close"].shift(1) <= dataframe["donchian_high"].shift(1))
            & participation
        )
        short_condition = (
            (dataframe["close"] < dataframe["donchian_low"])
            & (dataframe["close"].shift(1) >= dataframe["donchian_low"].shift(1))
            & participation
        )
        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            "donchian_low_adx_long",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            "donchian_low_adx_short",
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
            return "max_hold_72h"
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
        return min(self.default_leverage, max_leverage)
