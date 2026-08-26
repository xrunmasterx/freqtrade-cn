from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import pandas as pd
from pandas import DataFrame, Series

from freqtrade.persistence import Order, Trade
from freqtrade.strategy import (
    IStrategy,
    merge_informative_pair,
    timeframe_to_next_date,
    timeframe_to_prev_date,
)


class TradingViewSupertrendStrategy(IStrategy):
    """TradingView Supertrend entries with causal price-action exits."""

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "15m"
    exit_timeframe = "5m"
    regime_timeframe = "1h"
    process_only_new_candles = True

    atr_period = 10
    atr_multiplier = 3.0
    change_atr = True
    order_offset_multiplier = 0.2

    activation_min_profit = 0.002
    activation_atr_multiplier = 0.5
    bounce_max_candles = 4
    trail_bars = 3
    swing_lookback = 12
    partial_exit_fraction = 0.5
    invalidation_atr_multiplier = 0.25
    regime_structure_lookback = 3
    require_regime_filter = True
    require_regime_structure = False
    price_action_exit_enabled = True

    minimal_roi: ClassVar[dict[str, float]] = {"0": 100.0}
    stoploss = -0.03
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    position_adjustment_enable = True
    max_entry_position_adjustment = 2
    startup_candle_count = 100

    order_types: ClassVar[dict[str, str | bool]] = {
        "entry": "limit",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "supertrend_up": {
                "type": "line",
                "color": "#00c853",
                "fill_to": "supertrend_price",
            },
            "supertrend_down": {
                "type": "line",
                "color": "#ff1744",
                "fill_to": "supertrend_price",
            },
            "supertrend_price": {"type": "line", "hidden": True},
            "supertrend_long_order_1": {"type": "line", "color": "#76ff03"},
            "supertrend_long_order_2": {"type": "line", "color": "#00e676"},
            "supertrend_long_order_3": {"type": "line", "color": "#00bfa5"},
            "supertrend_short_order_1": {"type": "line", "color": "#ff9100"},
            "supertrend_short_order_2": {"type": "line", "color": "#ff5252"},
            "supertrend_short_order_3": {"type": "line", "color": "#d500f9"},
            "supertrend_long_activation_reference": {
                "type": "line",
                "color": "#d4ff00",
            },
            "supertrend_short_activation_reference": {
                "type": "line",
                "color": "#ffb300",
            },
            "supertrend_long_partial_target": {"type": "line", "color": "#64ffda"},
            "supertrend_short_partial_target": {"type": "line", "color": "#ff80ab"},
            "supertrend_long_invalidation": {"type": "line", "color": "#ff6d00"},
            "supertrend_short_invalidation": {"type": "line", "color": "#aa00ff"},
            "regime_supertrend_up": {"type": "line", "color": "#69f0ae"},
            "regime_supertrend_down": {"type": "line", "color": "#ff8a80"},
        },
        "subplots": {
            "1h Price-Action Regime": {
                "supertrend_regime_bias": {"type": "line", "color": "#40c4ff"},
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
        return list(
            dict.fromkeys(
                (pair, informative_timeframe)
                for pair in pairs
                for informative_timeframe in (self.exit_timeframe, self.regime_timeframe)
            )
        )

    @staticmethod
    def _pine_rma(values: Series, period: int) -> Series:
        result = Series(float("nan"), index=values.index, dtype="float64")
        if len(values) < period:
            return result

        result.iloc[period - 1] = values.iloc[:period].mean()
        for index in range(period, len(values)):
            result.iloc[index] = (
                result.iloc[index - 1] * (period - 1) + values.iloc[index]
            ) / period
        return result

    @classmethod
    def _average_true_range(cls, dataframe: DataFrame) -> Series:
        previous_close = dataframe["close"].shift(1)
        true_range = pd.concat(
            [
                dataframe["high"] - dataframe["low"],
                (dataframe["high"] - previous_close).abs(),
                (dataframe["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        if cls.change_atr:
            return cls._pine_rma(true_range, cls.atr_period)
        return true_range.rolling(cls.atr_period, min_periods=cls.atr_period).mean()

    @classmethod
    def _add_supertrend(cls, dataframe: DataFrame) -> DataFrame:
        result = dataframe.copy()
        atr = cls._average_true_range(result)
        source = (result["high"] + result["low"]) / 2.0
        basic_up = source - cls.atr_multiplier * atr
        basic_down = source + cls.atr_multiplier * atr
        up = Series(float("nan"), index=result.index, dtype="float64")
        down = Series(float("nan"), index=result.index, dtype="float64")
        trend = Series(1, index=result.index, dtype="int64")

        for index in range(len(result)):
            if pd.isna(atr.iloc[index]):
                if index > 0:
                    trend.iloc[index] = trend.iloc[index - 1]
                continue

            previous_up = up.iloc[index - 1] if index > 0 else float("nan")
            previous_down = down.iloc[index - 1] if index > 0 else float("nan")
            up_reference = basic_up.iloc[index] if pd.isna(previous_up) else previous_up
            down_reference = basic_down.iloc[index] if pd.isna(previous_down) else previous_down
            previous_close = result["close"].iloc[index - 1] if index > 0 else float("nan")

            up.iloc[index] = (
                max(basic_up.iloc[index], up_reference)
                if previous_close > up_reference
                else basic_up.iloc[index]
            )
            down.iloc[index] = (
                min(basic_down.iloc[index], down_reference)
                if previous_close < down_reference
                else basic_down.iloc[index]
            )

            previous_trend = trend.iloc[index - 1] if index > 0 else 1
            close = result["close"].iloc[index]
            if previous_trend == -1 and close > down_reference:
                trend.iloc[index] = 1
            elif previous_trend == 1 and close < up_reference:
                trend.iloc[index] = -1
            else:
                trend.iloc[index] = previous_trend

        previous_trend = trend.shift(1)
        buy_signal = previous_trend.eq(-1) & trend.eq(1)
        sell_signal = previous_trend.eq(1) & trend.eq(-1)

        result["supertrend_atr"] = atr
        result["supertrend_up"] = up.where(trend.eq(1))
        result["supertrend_down"] = down.where(trend.eq(-1))
        result["supertrend_price"] = (
            result["open"] + result["high"] + result["low"] + result["close"]
        ) / 4.0
        result["supertrend_trend"] = trend
        result["supertrend_buy_signal"] = up.where(buy_signal)
        result["supertrend_sell_signal"] = down.where(sell_signal)
        result["supertrend_change"] = previous_trend.notna() & trend.ne(previous_trend)
        return result

    @staticmethod
    def _resample_closed_hours(dataframe: DataFrame) -> DataFrame:
        indexed = dataframe.set_index("date")
        grouped = indexed.resample("1h", label="left", closed="left")
        result = grouped.agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        counts = grouped["close"].count()
        return result.loc[counts.eq(4)].dropna().reset_index()

    @classmethod
    def _add_regime_structure(cls, dataframe: DataFrame) -> DataFrame:
        result = cls._add_supertrend(dataframe)
        lookback = cls.regime_structure_lookback
        recent_high = result["high"].rolling(lookback, min_periods=lookback).max()
        recent_low = result["low"].rolling(lookback, min_periods=lookback).min()
        previous_high = recent_high.shift(lookback)
        previous_low = recent_low.shift(lookback)
        result["regime_structure_long"] = (recent_high > previous_high) & (
            recent_low > previous_low
        )
        result["regime_structure_short"] = (recent_high < previous_high) & (
            recent_low < previous_low
        )
        result["regime_supertrend_up"] = result["supertrend_up"]
        result["regime_supertrend_down"] = result["supertrend_down"]
        result["regime_trend"] = result["supertrend_trend"]
        return result

    def _add_regime(self, dataframe: DataFrame, pair: str) -> DataFrame:
        data_provider = getattr(self, "dp", None)
        informative = DataFrame()
        if data_provider:
            informative = data_provider.get_pair_dataframe(
                pair=pair,
                timeframe=self.regime_timeframe,
            )
        if informative.empty:
            informative = self._resample_closed_hours(dataframe)
        informative = self._add_regime_structure(informative)
        columns = [
            "date",
            "regime_supertrend_up",
            "regime_supertrend_down",
            "regime_trend",
            "regime_structure_long",
            "regime_structure_short",
        ]
        result = merge_informative_pair(
            dataframe,
            informative.loc[:, columns],
            self.timeframe,
            self.regime_timeframe,
            ffill=True,
        )
        suffix = f"_{self.regime_timeframe}"
        for column in columns[1:]:
            result[column] = result[f"{column}{suffix}"]
        if self.require_regime_structure:
            long_structure = result["regime_structure_long"].fillna(False)
            short_structure = result["regime_structure_short"].fillna(False)
        else:
            long_structure = Series(True, index=result.index)
            short_structure = Series(True, index=result.index)
        if self.require_regime_filter:
            result["supertrend_regime_long_allowed"] = result["regime_trend"].eq(
                1
            ) & long_structure
            result["supertrend_regime_short_allowed"] = result["regime_trend"].eq(
                -1
            ) & short_structure
        else:
            result["supertrend_regime_long_allowed"] = True
            result["supertrend_regime_short_allowed"] = True
        result["supertrend_regime_bias"] = 0
        result.loc[result["supertrend_regime_long_allowed"], "supertrend_regime_bias"] = 1
        result.loc[result["supertrend_regime_short_allowed"], "supertrend_regime_bias"] = -1
        return result

    @classmethod
    def _add_price_action_guides(cls, dataframe: DataFrame) -> DataFrame:
        result = dataframe.copy()
        candle_range = result["high"] - result["low"]
        trend_sequence = result["supertrend_change"].fillna(False).astype(int).cumsum()
        average_range = candle_range.groupby(trend_sequence).expanding().mean()
        average_range = average_range.reset_index(level=0, drop=True).sort_index()

        result["supertrend_average_candle_range"] = average_range
        order_offset = average_range * cls.order_offset_multiplier
        uptrend = result["supertrend_trend"].eq(1)
        downtrend = result["supertrend_trend"].eq(-1)
        result["supertrend_long_order_1"] = (
            result["supertrend_up"] + order_offset
        ).where(uptrend)
        result["supertrend_long_order_2"] = result["supertrend_up"].where(uptrend)
        result["supertrend_long_order_3"] = (
            result["supertrend_up"] - order_offset
        ).where(uptrend)
        result["supertrend_short_order_1"] = (
            result["supertrend_down"] - order_offset
        ).where(downtrend)
        result["supertrend_short_order_2"] = result["supertrend_down"].where(downtrend)
        result["supertrend_short_order_3"] = (
            result["supertrend_down"] + order_offset
        ).where(downtrend)

        activation_distance = pd.concat(
            [
                result["close"] * cls.activation_min_profit,
                result["supertrend_atr"] * cls.activation_atr_multiplier,
            ],
            axis=1,
        ).max(axis=1)
        result["supertrend_long_activation_reference"] = (
            result["supertrend_long_order_2"] + activation_distance
        ).where(uptrend)
        result["supertrend_short_activation_reference"] = (
            result["supertrend_short_order_2"] - activation_distance
        ).where(downtrend)
        result["supertrend_long_partial_target"] = (
            result["high"].shift(1).rolling(cls.swing_lookback).max().where(uptrend)
        )
        result["supertrend_short_partial_target"] = (
            result["low"].shift(1).rolling(cls.swing_lookback).min().where(downtrend)
        )
        result["supertrend_long_invalidation"] = (
            result["supertrend_up"]
            - result["supertrend_atr"] * cls.invalidation_atr_multiplier
        ).where(uptrend)
        result["supertrend_short_invalidation"] = (
            result["supertrend_down"]
            + result["supertrend_atr"] * cls.invalidation_atr_multiplier
        ).where(downtrend)
        return result

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        result = self._add_supertrend(dataframe)
        result = self._add_regime(result, metadata.get("pair", ""))
        return self._add_price_action_guides(result)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        volume_ok = dataframe["volume"] > 0
        buy_signal = (
            dataframe["supertrend_buy_signal"].notna()
            & dataframe["supertrend_long_order_1"].notna()
            & dataframe["supertrend_regime_long_allowed"].fillna(False)
            & volume_ok
        )
        sell_signal = (
            dataframe["supertrend_sell_signal"].notna()
            & dataframe["supertrend_short_order_1"].notna()
            & dataframe["supertrend_regime_short_allowed"].fillna(False)
            & volume_ok
        )

        dataframe.loc[buy_signal, ["enter_long", "enter_tag"]] = (
            1,
            "supertrend_regime_long",
        )
        dataframe.loc[sell_signal, ["enter_short", "enter_tag"]] = (
            1,
            "supertrend_regime_short",
        )
        return dataframe

    def _closed_signal_rows(self, pair: str, at: datetime) -> DataFrame:
        if self.dp is None:
            return DataFrame()
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        current_candle_open = timeframe_to_prev_date(self.timeframe, at)
        return dataframe.loc[dataframe["date"] < current_candle_open]

    def _closed_signal_row(self, pair: str, at: datetime) -> Series | None:
        dataframe = self._closed_signal_rows(pair, at)
        return None if dataframe.empty else dataframe.iloc[-1]

    def _closed_market_rows(self, pair: str, timeframe: str, at: datetime) -> DataFrame:
        if self.dp is None:
            return DataFrame()
        dataframe = self.dp.get_pair_dataframe(pair=pair, timeframe=timeframe)
        current_candle_open = timeframe_to_prev_date(timeframe, at)
        return dataframe.loc[dataframe["date"] < current_candle_open]

    @classmethod
    def _regime_allows_row(cls, row: Series, side: str) -> bool:
        if not cls.require_regime_filter:
            return True
        return bool(row.get(f"supertrend_regime_{side}_allowed", False))

    @classmethod
    def _order_price(cls, row: Series | None, side: str, order_number: int) -> float | None:
        if row is None or not cls._regime_allows_row(row, side):
            return None
        expected_trend = 1 if side == "long" else -1
        if int(row.get("supertrend_trend", 0)) != expected_trend:
            return None
        value = row.get(f"supertrend_{side}_order_{order_number}")
        if value is None or pd.isna(value):
            return None
        return float(value)

    @staticmethod
    def _entry_fill_time(trade: Trade) -> datetime:
        return trade.date_entry_fill_utc or trade.open_date_utc

    def _entry_context_row(self, trade: Trade) -> Series | None:
        return self._closed_signal_row(trade.pair, self._entry_fill_time(trade))

    def _exit_rows_since_entry(self, trade: Trade, current_time: datetime) -> DataFrame:
        rows = self._closed_market_rows(trade.pair, self.exit_timeframe, current_time)
        first_complete = timeframe_to_next_date(
            self.exit_timeframe,
            self._entry_fill_time(trade),
        )
        return rows.loc[rows["date"] >= first_complete]

    def _activation_ratio(self, trade: Trade, context: Series | None) -> float:
        atr = None if context is None else context.get("supertrend_atr")
        atr_ratio = (
            0.0
            if atr is None or pd.isna(atr)
            else float(atr) * self.activation_atr_multiplier / trade.open_rate
        )
        return max(self.activation_min_profit, atr_ratio)

    def _activation_reached(
        self,
        trade: Trade,
        context: Series | None,
        exit_rows: DataFrame,
    ) -> bool:
        if exit_rows.empty:
            return False
        activation_ratio = self._activation_ratio(trade, context)
        if trade.is_short:
            return float(exit_rows["low"].min()) <= trade.open_rate * (1.0 - activation_ratio)
        return float(exit_rows["high"].max()) >= trade.open_rate * (1.0 + activation_ratio)

    def _entry_invalidated(
        self,
        trade: Trade,
        context: Series | None,
        exit_rows: DataFrame,
    ) -> bool:
        if context is None or exit_rows.empty:
            return False
        column = (
            "supertrend_short_invalidation"
            if trade.is_short
            else "supertrend_long_invalidation"
        )
        invalidation = context.get(column)
        if invalidation is None or pd.isna(invalidation):
            return False
        last_close = float(exit_rows["close"].iloc[-1])
        return (
            last_close > float(invalidation)
            if trade.is_short
            else last_close < float(invalidation)
        )

    def _failed_bounce(
        self,
        trade: Trade,
        context: Series | None,
        exit_rows: DataFrame,
        current_time: datetime,
    ) -> bool:
        if self._activation_reached(trade, context, exit_rows):
            return False
        rows = self._closed_market_rows(trade.pair, self.timeframe, current_time)
        first_complete = timeframe_to_next_date(self.timeframe, self._entry_fill_time(trade))
        rows = rows.loc[rows["date"] >= first_complete]
        return len(rows) >= self.bounce_max_candles

    def _structure_exit_reason(
        self,
        trade: Trade,
        exit_rows: DataFrame,
    ) -> str | None:
        if len(exit_rows) < self.trail_bars + 1:
            return None
        last_close = float(exit_rows["close"].iloc[-1])
        previous = exit_rows.iloc[-(self.trail_bars + 1) : -1]
        break_even = float(trade.calc_close_rate_for_roi(0.0))
        if trade.is_short:
            structure_ceiling = float(previous["high"].max())
            protection = min(structure_ceiling, break_even)
            if last_close > protection:
                return (
                    "pa_net_breakeven_5m"
                    if protection == break_even
                    else "pa_structure_trail_5m"
                )
        else:
            structure_floor = float(previous["low"].min())
            protection = max(structure_floor, break_even)
            if last_close < protection:
                return (
                    "pa_net_breakeven_5m"
                    if protection == break_even
                    else "pa_structure_trail_5m"
                )
        return None

    def _partial_target_reached(
        self,
        trade: Trade,
        context: Series | None,
        exit_rows: DataFrame,
    ) -> bool:
        if context is None or exit_rows.empty:
            return False
        column = (
            "supertrend_short_partial_target"
            if trade.is_short
            else "supertrend_long_partial_target"
        )
        target = context.get(column)
        if target is None or pd.isna(target):
            return False
        target = float(target)
        if trade.is_short:
            return target < trade.open_rate and float(exit_rows["low"].min()) <= target
        return target > trade.open_rate and float(exit_rows["high"].max()) >= target

    def _may_add(self, trade: Trade, current_time: datetime) -> bool:
        if not self.price_action_exit_enabled:
            return True
        context = self._entry_context_row(trade)
        exit_rows = self._exit_rows_since_entry(trade, current_time)
        if self._activation_reached(trade, context, exit_rows):
            return False
        if self._entry_invalidated(trade, context, exit_rows):
            return False
        return not self._failed_bounce(trade, context, exit_rows, current_time)

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
        return proposed_stake / 3.0

    def custom_entry_price(
        self,
        pair: str,
        trade: Trade | None,
        current_time: datetime,
        proposed_rate: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        order_number = 1 if trade is None else trade.nr_of_successful_entries + 1
        price = self._order_price(self._closed_signal_row(pair, current_time), side, order_number)
        return proposed_rate if price is None else price

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        row = self._closed_signal_row(pair, current_time)
        return self._order_price(row, side, 1) is not None

    def adjust_entry_price(
        self,
        trade: Trade,
        order: Order | None,
        pair: str,
        current_time: datetime,
        proposed_rate: float,
        current_order_rate: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float | None:
        if trade.nr_of_successful_entries > 0 and not self._may_add(trade, current_time):
            return None
        order_number = trade.nr_of_successful_entries + 1
        return self._order_price(self._closed_signal_row(pair, current_time), side, order_number)

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> float | tuple[float, str] | None:
        if trade.has_open_orders:
            return None
        context = self._entry_context_row(trade)
        exit_rows = self._exit_rows_since_entry(trade, current_time)
        activated = self._activation_reached(trade, context, exit_rows)
        structure_exit = self._structure_exit_reason(trade, exit_rows) if activated else None
        if (
            self.price_action_exit_enabled
            and self.partial_exit_fraction > 0
            and activated
            and not structure_exit
            and not self._entry_invalidated(trade, context, exit_rows)
            and self._partial_target_reached(trade, context, exit_rows)
            and trade.nr_of_successful_exits == 0
        ):
            return (
                -(trade.stake_amount * self.partial_exit_fraction),
                "pa_swing_partial",
            )

        entry_count = trade.nr_of_successful_entries
        if entry_count <= 0 or entry_count >= 3 or not self._may_add(trade, current_time):
            return None
        side = "short" if trade.is_short else "long"
        row = self._closed_signal_row(trade.pair, current_time)
        if self._order_price(row, side, entry_count + 1) is None:
            return None
        stake = trade.stake_amount / entry_count
        return stake, f"supertrend_{side}_order_{entry_count + 1}"

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | bool | None:
        if not self.price_action_exit_enabled:
            return None
        context = self._entry_context_row(trade)
        exit_rows = self._exit_rows_since_entry(trade, current_time)
        if self._entry_invalidated(trade, context, exit_rows):
            return "pa_invalidation_5m"
        if self._failed_bounce(trade, context, exit_rows, current_time):
            return f"pa_failed_bounce_{self.bounce_max_candles}x15m"
        if self._activation_reached(trade, context, exit_rows):
            return self._structure_exit_reason(trade, exit_rows)
        return None

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        volume_ok = dataframe["volume"] > 0
        buy_signal = dataframe["supertrend_buy_signal"].notna() & volume_ok
        sell_signal = dataframe["supertrend_sell_signal"].notna() & volume_ok

        dataframe.loc[sell_signal, ["exit_long", "exit_tag"]] = (
            1,
            "supertrend_long_reversal",
        )
        dataframe.loc[buy_signal, ["exit_short", "exit_tag"]] = (
            1,
            "supertrend_short_reversal",
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
        return 1.0
