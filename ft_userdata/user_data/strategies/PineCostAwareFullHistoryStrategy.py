from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_absolute, timeframe_to_prev_date


def pine_rma(series: pd.Series, length: int) -> pd.Series:
    """Pine-compatible RMA seeded by the first full simple average."""
    result = pd.Series(float("nan"), index=series.index, dtype="float64")
    if len(series) < length:
        return result

    result.iloc[length - 1] = series.iloc[:length].mean()
    alpha = 1.0 / length
    for index in range(length, len(series)):
        result.iloc[index] = (
            alpha * series.iloc[index] + (1.0 - alpha) * result.iloc[index - 1]
        )
    return result


def pine_atr(dataframe: DataFrame, length: int) -> pd.Series:
    previous_close = dataframe["close"].shift(1)
    true_range = pd.concat(
        [
            dataframe["high"] - dataframe["low"],
            (dataframe["high"] - previous_close).abs(),
            (dataframe["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return pine_rma(true_range, length)


class PineCostAwareFullHistoryBaseStrategy(IStrategy):
    """Prior-20 closed-candle breakout with a cost gate and two-stage ATR stop."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 100

    max_open_trades = 1
    position_adjustment_enable = False
    minimal_roi: ClassVar[dict[str, float]] = {"0": 100.0}
    stoploss = -0.99
    trailing_stop = False
    use_custom_stoploss = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    order_types: ClassVar[dict[str, str | bool]] = {
        "entry": "market",
        "exit": "market",
        "emergency_exit": "market",
        "force_entry": "market",
        "force_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    channel_length = 20
    atr_length = 14
    hard_stop_atr = 2.5
    trailing_atr = 2.5
    # 2 * (OKX taker 0.06% + the preregistered 0.02%/side slippage stress).
    activation_cost_fraction = 0.0016
    filter_mode = "none"
    adx_threshold = 20.0
    rv_length = 20
    rv_baseline_length = 80
    default_leverage = 1.0

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "donchian_high": {"color": "#36B37E"},
            "donchian_low": {"color": "#FF5630"},
        },
        "subplots": {
            "Cost-aware risk": {
                "atr": {"color": "#FFAB00"},
                "adx": {"color": "#6554C0"},
            },
            "Realized volatility": {
                "realized_volatility": {"color": "#00B8D9"},
                "rv_baseline": {"color": "#8993A4"},
            },
        },
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["donchian_high"] = (
            dataframe["high"].rolling(self.channel_length).max().shift(1)
        )
        dataframe["donchian_low"] = (
            dataframe["low"].rolling(self.channel_length).min().shift(1)
        )
        dataframe["atr"] = pine_atr(dataframe, self.atr_length)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        log_return = np.log(dataframe["close"] / dataframe["close"].shift(1))
        dataframe["realized_volatility"] = log_return.rolling(self.rv_length).std()
        dataframe["rv_baseline"] = (
            dataframe["realized_volatility"]
            .rolling(self.rv_baseline_length)
            .median()
            .shift(1)
        )
        return dataframe

    def _filter_condition(self, dataframe: DataFrame) -> pd.Series:
        if self.filter_mode == "adx":
            return dataframe["adx"] >= self.adx_threshold
        if self.filter_mode == "rv":
            return dataframe["realized_volatility"] >= dataframe["rv_baseline"]
        return pd.Series(True, index=dataframe.index)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        eligible = self._filter_condition(dataframe) & (dataframe["volume"] > 0)
        long_condition = (
            (dataframe["close"] > dataframe["donchian_high"])
            & (dataframe["close"].shift(1) <= dataframe["donchian_high"].shift(1))
            & eligible
        )
        short_condition = (
            (dataframe["close"] < dataframe["donchian_low"])
            & (dataframe["close"].shift(1) >= dataframe["donchian_low"].shift(1))
            & eligible
        )
        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            f"prior20_breakout_long_{self.filter_mode}",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            f"prior20_breakout_short_{self.filter_mode}",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["enter_short"] == 1, ["exit_long", "exit_tag"]] = (
            1,
            "reverse_to_short",
        )
        dataframe.loc[dataframe["enter_long"] == 1, ["exit_short", "exit_tag"]] = (
            1,
            "reverse_to_long",
        )
        return dataframe

    @staticmethod
    def _safe_float(value: object) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if np.isfinite(result) else None

    def _closed_row(self, pair: str, current_time: datetime) -> pd.Series | None:
        data_provider = getattr(self, "dp", None)
        if data_provider is None:
            return None
        dataframe, _ = data_provider.get_analyzed_dataframe(pair, self.timeframe)
        current_candle_open = timeframe_to_prev_date(self.timeframe, current_time)
        closed = dataframe.loc[dataframe["date"] < current_candle_open]
        return None if closed.empty else closed.iloc[-1]

    def _ensure_trade_plan(self, trade: Trade) -> bool:
        if trade.get_custom_data("initial_stop_rate") is not None:
            return True

        row = self._closed_row(trade.pair, trade.open_date_utc)
        if row is None:
            return False
        atr = self._safe_float(row.get("atr"))
        entry_rate = self._safe_float(trade.open_rate)
        if atr is None or atr <= 0 or entry_rate is None or entry_rate <= 0:
            return False

        initial_stop_rate = (
            entry_rate + self.hard_stop_atr * atr
            if trade.is_short
            else entry_rate - self.hard_stop_atr * atr
        )
        activation_rate = (
            entry_rate * (1.0 - self.activation_cost_fraction)
            if trade.is_short
            else entry_rate * (1.0 + self.activation_cost_fraction)
        )
        trade.set_custom_data("initial_stop_rate", initial_stop_rate)
        trade.set_custom_data("activation_rate", activation_rate)
        trade.set_custom_data("trail_activated", False)
        return True

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

        initial_stop_rate = self._safe_float(trade.get_custom_data("initial_stop_rate"))
        activation_rate = self._safe_float(trade.get_custom_data("activation_rate"))
        if initial_stop_rate is None or activation_rate is None:
            return None

        activated = bool(trade.get_custom_data("trail_activated", False))
        activation_reached = (
            current_rate <= activation_rate if trade.is_short else current_rate >= activation_rate
        )
        if not activated and activation_reached:
            trade.set_custom_data("trail_activated", True)
            activated = True

        stop_rate = initial_stop_rate
        if activated:
            row = self._closed_row(pair, current_time)
            atr = self._safe_float(row.get("atr")) if row is not None else None
            if atr is not None and atr > 0:
                candidate = (
                    current_rate + self.trailing_atr * atr
                    if trade.is_short
                    else current_rate - self.trailing_atr * atr
                )
                previous = self._safe_float(trade.get_custom_data("trail_stop_rate"))
                if trade.is_short:
                    stop_rate = min(initial_stop_rate, candidate, previous or candidate)
                else:
                    stop_rate = max(initial_stop_rate, candidate, previous or candidate)
                trade.set_custom_data("trail_stop_rate", stop_rate)

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


class PineCostAwareFullHistory15mStrategy(PineCostAwareFullHistoryBaseStrategy):
    pass


class PineCostAwareFullHistory15mAdxStrategy(PineCostAwareFullHistoryBaseStrategy):
    filter_mode = "adx"


class PineCostAwareFullHistory15mRvStrategy(PineCostAwareFullHistoryBaseStrategy):
    filter_mode = "rv"


class PineCostAwareFullHistory30mStrategy(PineCostAwareFullHistoryBaseStrategy):
    timeframe = "30m"


class PineCostAwareFullHistory30mAdxStrategy(PineCostAwareFullHistory30mStrategy):
    filter_mode = "adx"


class PineCostAwareFullHistory30mRvStrategy(PineCostAwareFullHistory30mStrategy):
    filter_mode = "rv"


class PineCostAwareFullHistory1hStrategy(PineCostAwareFullHistoryBaseStrategy):
    timeframe = "1h"


class PineCostAwareFullHistory1hAdxStrategy(PineCostAwareFullHistory1hStrategy):
    filter_mode = "adx"


class PineCostAwareFullHistory1hRvStrategy(PineCostAwareFullHistory1hStrategy):
    filter_mode = "rv"


class PineCostAwareFullHistory2hStrategy(PineCostAwareFullHistoryBaseStrategy):
    timeframe = "2h"


class PineCostAwareFullHistory2hAdxStrategy(PineCostAwareFullHistory2hStrategy):
    filter_mode = "adx"


class PineCostAwareFullHistory2hRvStrategy(PineCostAwareFullHistory2hStrategy):
    filter_mode = "rv"
