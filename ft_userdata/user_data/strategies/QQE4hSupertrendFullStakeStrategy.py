from __future__ import annotations

from datetime import datetime

import pandas as pd
from pandas import DataFrame

from freqtrade.indicators.qqe_mod import add_qqe_mod
from freqtrade.indicators.supertrend import add_supertrend
from freqtrade.strategy import IStrategy, merge_informative_pair


class QQE4hSupertrendFullStakeStrategy(IStrategy):
    """
    Full-stake QQE Mod + Supertrend futures strategy.

    The 4h Supertrend defines the tradable direction. The strategy only enters on the
    matching local Supertrend direction, and exits immediately when the 4h direction flips.
    """

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "4h"
    informative_timeframe = "4h"
    process_only_new_candles = True

    minimal_roi = {"0": 100}
    stoploss = -1.0
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False
    startup_candle_count = 80

    qqe_up_entry_threshold = 15.0
    qqe_down_entry_threshold = -15.0
    leverage_value = 3.0

    plot_config = {
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

    def informative_pairs(self):
        data_provider = getattr(self, "dp", None)
        pairs = (
            data_provider.current_whitelist()
            if data_provider
            else self.config.get("exchange", {}).get("pair_whitelist", [])
        )
        return [(pair, self.informative_timeframe) for pair in pairs]

    @staticmethod
    def _populate_4h_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = add_supertrend(dataframe, prefix="supertrend")
        return dataframe[
            [
                "date",
                "supertrend_up",
                "supertrend_down",
                "supertrend_trend",
                "supertrend_buy_signal",
                "supertrend_sell_signal",
                "supertrend_change",
            ]
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = add_supertrend(dataframe, prefix="supertrend")
        dataframe = add_qqe_mod(dataframe, prefix="qqe_mod")

        data_provider = getattr(self, "dp", None)
        if data_provider and self.timeframe != self.informative_timeframe:
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
        elif "supertrend_trend_4h" not in dataframe:
            dataframe["supertrend_trend_4h"] = dataframe["supertrend_trend"]

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return self._apply_paired_signals(dataframe)

    def _higher_supertrend_trend(self, dataframe: DataFrame) -> pd.Series:
        if "supertrend_trend_4h" in dataframe:
            return self._numeric_column(dataframe, "supertrend_trend_4h")
        return self._numeric_column(dataframe, "supertrend_trend")

    def _raw_signal_masks(
        self, dataframe: DataFrame
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        volume_ok = self._numeric_column(dataframe, "volume") > 0
        supertrend_trend = self._numeric_column(dataframe, "supertrend_trend")
        higher_supertrend_trend = self._higher_supertrend_trend(dataframe)
        qqe_up = self._numeric_column(dataframe, "qqe_mod_up")
        qqe_down = self._numeric_column(dataframe, "qqe_mod_down")
        qqe_up_state = self._bool_column(dataframe, "qqe_mod_up_state")
        qqe_down_state = self._bool_column(dataframe, "qqe_mod_down_state")

        long_threshold_cross = (qqe_up >= self.qqe_up_entry_threshold) & (
            qqe_up.shift(1).isna() | (qqe_up.shift(1) < self.qqe_up_entry_threshold)
        )
        short_threshold_cross = (qqe_down <= self.qqe_down_entry_threshold) & (
            qqe_down.shift(1).isna() | (qqe_down.shift(1) > self.qqe_down_entry_threshold)
        )

        higher_long_regime = higher_supertrend_trend == 1
        higher_short_regime = higher_supertrend_trend == -1

        long_condition = (
            higher_long_regime
            & (supertrend_trend == 1)
            & long_threshold_cross
            & volume_ok
        )
        short_condition = (
            higher_short_regime
            & (supertrend_trend == -1)
            & short_threshold_cross
            & volume_ok
        )

        previous_supertrend_trend = supertrend_trend.shift(1)
        previous_qqe_up_state = qqe_up_state.shift(1).fillna(False).astype(bool)
        previous_qqe_down_state = qqe_down_state.shift(1).fillna(False).astype(bool)

        long_higher_trend_lost = higher_short_regime
        short_higher_trend_lost = higher_long_regime
        long_trend_lost = (previous_supertrend_trend == 1) & (supertrend_trend != 1)
        long_qqe_lost = previous_qqe_up_state & ~qqe_up_state
        short_trend_lost = (previous_supertrend_trend == -1) & (supertrend_trend != -1)
        short_qqe_lost = previous_qqe_down_state & ~qqe_down_state

        long_exit = (long_higher_trend_lost | long_trend_lost | long_qqe_lost) & volume_ok
        short_exit = (short_higher_trend_lost | short_trend_lost | short_qqe_lost) & volume_ok
        return long_condition, short_condition, long_exit, short_exit

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return self._apply_paired_signals(dataframe)

    def _apply_paired_signals(self, dataframe: DataFrame) -> DataFrame:
        long_entry, short_entry, long_exit, short_exit = self._raw_signal_masks(dataframe)
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        if "enter_tag" not in dataframe:
            dataframe["enter_tag"] = ""
        if "exit_tag" not in dataframe:
            dataframe["exit_tag"] = ""

        position: str | None = None
        for index in dataframe.index:
            if position == "long":
                if bool(long_exit.at[index]):
                    dataframe.at[index, "exit_long"] = 1
                    dataframe.at[index, "exit_tag"] = "4h_qqe_st_full_long_exit"
                    position = None
                continue
            if position == "short":
                if bool(short_exit.at[index]):
                    dataframe.at[index, "exit_short"] = 1
                    dataframe.at[index, "exit_tag"] = "4h_qqe_st_full_short_exit"
                    position = None
                continue
            if bool(long_entry.at[index]):
                dataframe.at[index, "enter_long"] = 1
                dataframe.at[index, "enter_tag"] = "4h_qqe_st_full_long"
                position = "long"
            elif bool(short_entry.at[index]):
                dataframe.at[index, "enter_short"] = 1
                dataframe.at[index, "enter_tag"] = "4h_qqe_st_full_short"
                position = "short"
        return dataframe

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return max_stake

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
