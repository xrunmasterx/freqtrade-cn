from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair


class DonchianCounterMomentumRegimeStrategy(IStrategy):
    """Trade prior-20 breakouts that reverse 72h momentum inside the 20-day regime."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 1499

    max_open_trades = 1
    position_adjustment_enable = False
    minimal_roi: ClassVar[dict[str, float]] = {"0": 0.04}
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
    momentum_lookback = 288
    max_directional_return_72h = -0.0175
    regime_timeframe = "1h"
    regime_ema_length = 480
    regime_history_length = 1499
    max_hold_hours = 48
    default_leverage = 1.0

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "donchian_high": {"color": "#36B37E"},
            "donchian_low": {"color": "#FF5630"},
            "ema_20d": {"color": "#4C9AFF"},
        },
        "subplots": {
            "Counter-momentum regime": {
                "return_72h": {"color": "#6554C0"},
            }
        },
    }

    def informative_pairs(self) -> list[tuple[str, str]]:
        data_provider = getattr(self, "dp", None)
        pairs = (
            data_provider.current_whitelist()
            if data_provider
            else self.config.get("exchange", {}).get("pair_whitelist", [])
        )
        return [(pair, self.regime_timeframe) for pair in pairs]

    @classmethod
    def populate_regime_indicators(cls, dataframe: DataFrame) -> DataFrame:
        result = dataframe.copy()
        ema = np.full(len(result), np.nan, dtype=float)
        if len(result) >= cls.regime_history_length:
            alpha = 2.0 / (cls.regime_ema_length + 1.0)
            weights = (1.0 - alpha) ** np.arange(
                cls.regime_history_length - 1, -1, -1, dtype=float
            )
            weights /= weights.sum()
            ema[cls.regime_history_length - 1 :] = np.correlate(
                result["close"].to_numpy(dtype=float), weights, mode="valid"
            )
        result["ema_20d"] = ema
        return result

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["donchian_high"] = (
            dataframe["high"].rolling(self.channel_length).max().shift(1)
        )
        dataframe["donchian_low"] = (
            dataframe["low"].rolling(self.channel_length).min().shift(1)
        )
        dataframe["return_72h"] = (
            dataframe["close"] / dataframe["close"].shift(self.momentum_lookback) - 1
        )
        data_provider = getattr(self, "dp", None)
        if data_provider:
            informative = self.populate_regime_indicators(
                data_provider.get_pair_dataframe(
                    pair=metadata["pair"], timeframe=self.regime_timeframe
                )
            )
            dataframe = merge_informative_pair(
                dataframe,
                informative,
                self.timeframe,
                self.regime_timeframe,
                ffill=True,
            )
            dataframe["ema_20d"] = dataframe["ema_20d_1h"]
        else:
            dataframe["ema_20d"] = float("nan")
        return dataframe

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
            & (dataframe["return_72h"] <= self.max_directional_return_72h)
            & (dataframe["close"] > dataframe["ema_20d"])
        )
        short_condition = (
            short_breakout
            & (-dataframe["return_72h"] <= self.max_directional_return_72h)
            & (dataframe["close"] < dataframe["ema_20d"])
        )
        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            "donchian_counter_momentum_long",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            "donchian_counter_momentum_short",
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
            return "max_hold_48h"
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


class DonchianCounterMomentumRegimeHighReturnStrategy(
    DonchianCounterMomentumRegimeStrategy
):
    """High-risk frozen candidate that crossed 100% in the latest 30-day study."""

    minimal_roi: ClassVar[dict[str, float]] = {"0": 0.52}
    stoploss = -0.21
    default_leverage = 14.0
