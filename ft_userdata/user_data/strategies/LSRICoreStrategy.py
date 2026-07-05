# flake8: noqa: F401
# isort: skip_file
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from pandas import DataFrame

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair, stoploss_from_absolute


class LSRICoreStrategy(IStrategy):
    """
    LSRI Core: Liquidity Sweep + Regime Impulse.

    Backtestable core version for OKX BTC/ETH USDT perpetual futures.
    """

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "5m"
    process_only_new_candles = True

    minimal_roi = {"0": 100}
    stoploss = -0.16
    use_custom_stoploss = True
    trailing_stop = False
    position_adjustment_enable = False
    startup_candle_count = 240

    pullback_window = 12
    pullback_tolerance = 0.0015
    funding_limit = 0.0003
    adx_threshold = 18.0
    volume_z_threshold = 1.0
    max_account_risk_pct = 0.08
    entry_min_risk_pct = 0.0035
    entry_max_risk_pct = 0.0068
    entry_volume_z_min = 1.0
    entry_volume_z_max = 2.8
    long_adx_hard_threshold = 22.0
    short_adx_hard_threshold = 24.0
    di_direction_ratio = 1.15
    long_funding_edge = 0.0001
    short_funding_edge = -0.0001
    crowded_funding_limit = 0.0003
    crowded_ret24_limit = 0.035
    trend_min_ema_spread = 0.004
    trend_min_atrp = 0.0025
    chop_max_adx = 18.0
    chop_max_atrp = 0.002
    take_profit_r = 2.2
    early_time_stop_minutes = 45
    early_time_stop_r = 0.35
    time_stop_minutes = 90
    time_stop_r = 0.5

    plot_config = {
        "main_plot": {
            "key_long_level": {"color": "green"},
            "key_short_level": {"color": "red"},
            "long_stop_rate": {"color": "orange"},
            "short_stop_rate": {"color": "orange"},
        },
        "subplots": {
            "LSRI Score": {
                "long_score": {"color": "green"},
                "short_score": {"color": "red"},
            },
            "Funding": {
                "funding_rate_fr_1h": {"color": "blue"},
            },
        },
    }

    def informative_pairs(self):
        pairs = (
            self.dp.current_whitelist()
            if self.dp
            else self.config.get("exchange", {}).get("pair_whitelist", [])
        )
        informative = []
        for pair in pairs:
            informative.extend(
                [
                    (pair, "15m"),
                    (pair, "1h"),
                    (pair, "4h"),
                    (pair, "1h", "funding_rate"),
                ]
            )
        return informative

    @staticmethod
    def _points(condition: pd.Series, points: int) -> pd.Series:
        return condition.fillna(False).astype(int) * points

    @staticmethod
    def _safe_float(value, default: Optional[float] = None) -> Optional[float]:
        if value is None:
            return default
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default
        if not np.isfinite(result):
            return default
        return result

    @staticmethod
    def _pair_max_stop_distance(pair: str) -> float:
        if pair.startswith("BTC/"):
            return 0.0068
        if pair.startswith("ETH/"):
            return 0.0096
        return 0.0

    @staticmethod
    def _pair_leverage(pair: str) -> float:
        if pair.startswith("BTC/"):
            return 12.0
        if pair.startswith("ETH/"):
            return 8.0
        return 1.0

    @staticmethod
    def _populate_15m_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["atr14"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["adx14"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di14"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di14"] = ta.MINUS_DI(dataframe, timeperiod=14)
        dataframe["rsi14"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["donchian_high20"] = dataframe["high"].rolling(20).max().shift(1)
        dataframe["donchian_low20"] = dataframe["low"].rolling(20).min().shift(1)

        volume_mean = dataframe["volume"].rolling(20).mean()
        volume_std = dataframe["volume"].rolling(20).std(ddof=0).replace(0, np.nan)
        dataframe["volume_z20"] = ((dataframe["volume"] - volume_mean) / volume_std).replace(
            [np.inf, -np.inf], np.nan
        )

        typical_price = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3.0
        session = dataframe["date"].dt.floor("D")
        cumulative_volume = dataframe["volume"].groupby(session).cumsum().replace(0, np.nan)
        cumulative_price_volume = (typical_price * dataframe["volume"]).groupby(session).cumsum()
        dataframe["vwap"] = cumulative_price_volume / cumulative_volume

        dataframe["adx_rising"] = (
            (dataframe["adx14"] > dataframe["adx14"].shift(1))
            & (dataframe["adx14"].shift(1) > dataframe["adx14"].shift(2))
        )
        dataframe["long_structure_breakout"] = dataframe["close"] > dataframe["donchian_high20"]
        dataframe["short_structure_breakdown"] = dataframe["close"] < dataframe["donchian_low20"]
        return dataframe

    @staticmethod
    def _populate_1h_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["ret24"] = dataframe["close"] / dataframe["close"].shift(24) - 1
        dataframe["ema50_slope24"] = dataframe["ema50"] / dataframe["ema50"].shift(24) - 1
        dataframe["long_trend"] = (dataframe["close"] > dataframe["ema200"]) & (
            dataframe["ema50"] > dataframe["ema200"]
        )
        dataframe["short_trend"] = (dataframe["close"] < dataframe["ema200"]) & (
            dataframe["ema50"] < dataframe["ema200"]
        )
        return dataframe

    @staticmethod
    def _populate_4h_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["dist_ema200"] = dataframe["close"] / dataframe["ema200"] - 1
        dataframe["long_regime"] = dataframe["close"] >= dataframe["ema200"]
        dataframe["short_regime"] = dataframe["close"] <= dataframe["ema200"]
        return dataframe

    @staticmethod
    def _populate_funding_rate(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        rate_column = None
        for candidate in ("funding_rate", "fundingRate", "rate", "open", "close"):
            if candidate in dataframe.columns:
                rate_column = candidate
                break

        if rate_column is None:
            dataframe["funding_rate"] = np.nan
        else:
            dataframe["funding_rate"] = pd.to_numeric(dataframe[rate_column], errors="coerce")

        return dataframe[["date", "funding_rate"]]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rolling_low_12"] = dataframe["low"].rolling(self.pullback_window).min()
        dataframe["rolling_high_12"] = dataframe["high"].rolling(self.pullback_window).max()
        dataframe["max_stop_distance"] = self._pair_max_stop_distance(metadata["pair"])

        if not self.dp:
            return dataframe

        informative_15m = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="15m")
        informative_15m = self._populate_15m_indicators(informative_15m)
        dataframe = merge_informative_pair(
            dataframe, informative_15m, self.timeframe, "15m", ffill=True
        )

        informative_1h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1h")
        informative_1h = self._populate_1h_indicators(informative_1h)
        dataframe = merge_informative_pair(
            dataframe, informative_1h, self.timeframe, "1h", ffill=True
        )

        informative_4h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="4h")
        informative_4h = self._populate_4h_indicators(informative_4h)
        dataframe = merge_informative_pair(
            dataframe, informative_4h, self.timeframe, "4h", ffill=True
        )

        funding_1h = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe="1h", candle_type="funding_rate"
        )
        funding_1h = self._populate_funding_rate(funding_1h)
        dataframe = merge_informative_pair(
            dataframe,
            funding_1h,
            self.timeframe,
            "1h",
            ffill=True,
            append_timeframe=False,
            suffix="fr_1h",
        )

        dataframe["key_long_level"] = dataframe[
            ["donchian_high20_15m", "ema20_15m", "vwap_15m"]
        ].max(axis=1)
        dataframe["key_short_level"] = dataframe[
            ["donchian_low20_15m", "ema20_15m", "vwap_15m"]
        ].min(axis=1)
        dataframe["dist_ema20_15m"] = dataframe["close"] / dataframe["ema20_15m"] - 1
        dataframe["dist_vwap_15m"] = dataframe["close"] / dataframe["vwap_15m"] - 1
        dataframe["atrp_15m"] = dataframe["atr14_15m"] / dataframe["close"]
        dataframe["ema_spread_1h"] = (
            (dataframe["ema50_1h"] - dataframe["ema200_1h"]).abs() / dataframe["close"]
        )

        dataframe["long_recent_breakout"] = (
            dataframe["long_structure_breakout_15m"]
            .fillna(False)
            .astype(int)
            .rolling(self.pullback_window)
            .max()
            .shift(1)
            > 0
        )
        dataframe["short_recent_breakdown"] = (
            dataframe["short_structure_breakdown_15m"]
            .fillna(False)
            .astype(int)
            .rolling(self.pullback_window)
            .max()
            .shift(1)
            > 0
        )

        dataframe["long_pullback_reclaim"] = (
            (dataframe["low"] <= dataframe["key_long_level"] * (1 + self.pullback_tolerance))
            & (dataframe["close"] > dataframe["key_long_level"])
            & (dataframe["close"] > dataframe["open"])
        )
        dataframe["short_pullback_reject"] = (
            (dataframe["high"] >= dataframe["key_short_level"] * (1 - self.pullback_tolerance))
            & (dataframe["close"] < dataframe["key_short_level"])
            & (dataframe["close"] < dataframe["open"])
        )

        dataframe["long_stop_rate"] = dataframe["rolling_low_12"] - (0.2 * dataframe["atr14_15m"])
        dataframe["short_stop_rate"] = dataframe["rolling_high_12"] + (0.2 * dataframe["atr14_15m"])

        dataframe["long_risk_pct"] = (
            (dataframe["close"] - dataframe["long_stop_rate"]) / dataframe["close"]
        )
        dataframe["short_risk_pct"] = (
            (dataframe["short_stop_rate"] - dataframe["close"]) / dataframe["close"]
        )
        dataframe["long_stop_valid"] = (
            (dataframe["max_stop_distance"] > 0)
            & (dataframe["long_risk_pct"] > 0)
            & (dataframe["long_risk_pct"] <= dataframe["max_stop_distance"])
        )
        dataframe["short_stop_valid"] = (
            (dataframe["max_stop_distance"] > 0)
            & (dataframe["short_risk_pct"] > 0)
            & (dataframe["short_risk_pct"] <= dataframe["max_stop_distance"])
        )

        dataframe["long_funding_ok"] = dataframe["funding_rate_fr_1h"] <= self.funding_limit
        dataframe["short_funding_ok"] = dataframe["funding_rate_fr_1h"] >= -self.funding_limit

        dataframe["long_score"] = (
            self._points(dataframe["long_trend_1h"], 20)
            + self._points(dataframe["long_regime_4h"], 10)
            + self._points(
                (dataframe["adx14_15m"] > self.adx_threshold) & dataframe["adx_rising_15m"], 10
            )
            + self._points(dataframe["long_structure_breakout_15m"], 15)
            + self._points(dataframe["long_pullback_reclaim"], 15)
            + self._points(dataframe["volume_z20_15m"] > self.volume_z_threshold, 10)
            + self._points((dataframe["rsi14_15m"] > 50) & (dataframe["rsi14_15m"] < 72), 10)
            + self._points(dataframe["long_funding_ok"], 10)
            + self._points(dataframe["long_stop_valid"], 10)
        )
        dataframe["short_score"] = (
            self._points(dataframe["short_trend_1h"], 20)
            + self._points(dataframe["short_regime_4h"], 10)
            + self._points(
                (dataframe["adx14_15m"] > self.adx_threshold) & dataframe["adx_rising_15m"], 10
            )
            + self._points(dataframe["short_structure_breakdown_15m"], 15)
            + self._points(dataframe["short_pullback_reject"], 15)
            + self._points(dataframe["volume_z20_15m"] > self.volume_z_threshold, 10)
            + self._points((dataframe["rsi14_15m"] > 28) & (dataframe["rsi14_15m"] < 50), 10)
            + self._points(dataframe["short_funding_ok"], 10)
            + self._points(dataframe["short_stop_valid"], 10)
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        candle_range = (dataframe["high"] - dataframe["low"]).replace(0, np.nan)
        body_pct = (dataframe["close"] - dataframe["open"]).abs() / candle_range
        close_pos = (dataframe["close"] - dataframe["low"]) / candle_range
        upper_wick_pct = (
            dataframe["high"] - dataframe[["open", "close"]].max(axis=1)
        ) / candle_range
        lower_wick_pct = (
            dataframe[["open", "close"]].min(axis=1) - dataframe["low"]
        ) / candle_range

        long_adx_hard = (
            (dataframe["adx14_15m"] >= self.long_adx_hard_threshold)
            & dataframe["adx_rising_15m"].fillna(False)
        )
        short_adx_hard = (
            (dataframe["adx14_15m"] >= self.short_adx_hard_threshold)
            & dataframe["adx_rising_15m"].fillna(False)
        )
        long_di_ok = (
            dataframe["plus_di14_15m"] > dataframe["minus_di14_15m"] * self.di_direction_ratio
        )
        short_di_ok = (
            dataframe["minus_di14_15m"] > dataframe["plus_di14_15m"] * self.di_direction_ratio
        )
        long_rsi_hard = (dataframe["rsi14_15m"] >= 52) & (dataframe["rsi14_15m"] <= 68)
        short_rsi_hard = (dataframe["rsi14_15m"] >= 32) & (dataframe["rsi14_15m"] <= 48)
        long_volume_ok = (
            (dataframe["volume_z20_15m"] >= self.entry_volume_z_min)
            & (dataframe["volume_z20_15m"] <= self.entry_volume_z_max)
        )
        short_volume_ok = (
            (dataframe["volume_z20_15m"] >= self.entry_volume_z_min)
            & (dataframe["volume_z20_15m"] <= self.entry_volume_z_max)
        )
        long_candle_quality = (
            (close_pos >= 0.65)
            & (body_pct >= 0.35)
            & (upper_wick_pct <= 0.30)
        )
        short_candle_quality = (
            (close_pos <= 0.35)
            & (body_pct >= 0.35)
            & (lower_wick_pct <= 0.30)
        )
        long_not_extended = (
            (dataframe["dist_ema20_15m"] <= 0.006)
            & (dataframe["dist_vwap_15m"] <= 0.008)
            & (dataframe["ret24_1h"] <= self.crowded_ret24_limit)
            & (dataframe["dist_ema200_4h"] <= 0.08)
        )
        short_not_extended = (
            (dataframe["dist_ema20_15m"] >= -0.006)
            & (dataframe["dist_vwap_15m"] >= -0.008)
            & (dataframe["ret24_1h"] >= -self.crowded_ret24_limit)
            & (dataframe["dist_ema200_4h"] >= -0.08)
        )
        long_funding_edge = dataframe["funding_rate_fr_1h"] <= self.long_funding_edge
        short_funding_edge = dataframe["funding_rate_fr_1h"] >= self.short_funding_edge
        long_crowded_skip = (
            (dataframe["funding_rate_fr_1h"] > self.crowded_funding_limit)
            & (dataframe["ret24_1h"] > self.crowded_ret24_limit)
        )
        short_crowded_skip = (
            (dataframe["funding_rate_fr_1h"] < -self.crowded_funding_limit)
            & (dataframe["ret24_1h"] < -self.crowded_ret24_limit)
        )
        trend_regime = (
            (dataframe["ema_spread_1h"] >= self.trend_min_ema_spread)
            & (dataframe["adx14_15m"] >= self.long_adx_hard_threshold)
            & (dataframe["atrp_15m"] >= self.trend_min_atrp)
        )
        chop_regime = (
            (dataframe["adx14_15m"] < self.chop_max_adx)
            | (dataframe["atrp_15m"] < self.chop_max_atrp)
        )
        long_risk_ok = (
            (dataframe["long_risk_pct"] >= self.entry_min_risk_pct)
            & (dataframe["long_risk_pct"] <= self.entry_max_risk_pct)
        )
        short_risk_ok = (
            (dataframe["short_risk_pct"] >= self.entry_min_risk_pct)
            & (dataframe["short_risk_pct"] <= self.entry_max_risk_pct)
        )

        long_a_plus = (
            (dataframe["volume"] > 0)
            & dataframe["funding_rate_fr_1h"].notna()
            & dataframe["long_trend_1h"].fillna(False)
            & dataframe["long_regime_4h"].fillna(False)
            & dataframe["long_recent_breakout"].fillna(False)
            & dataframe["long_pullback_reclaim"].fillna(False)
            & long_adx_hard.fillna(False)
            & long_di_ok.fillna(False)
            & long_rsi_hard.fillna(False)
            & long_candle_quality.fillna(False)
            & long_volume_ok.fillna(False)
            & long_not_extended.fillna(False)
            & long_funding_edge.fillna(False)
            & ~long_crowded_skip.fillna(False)
            & dataframe["long_stop_valid"].fillna(False)
            & long_risk_ok.fillna(False)
            & trend_regime.fillna(False)
            & ~chop_regime.fillna(False)
        )
        dataframe.loc[
            long_a_plus,
            ["enter_long", "enter_tag"],
        ] = (1, "lsri_v2_long_trend")

        short_a_plus = (
            (dataframe["volume"] > 0)
            & dataframe["funding_rate_fr_1h"].notna()
            & dataframe["short_trend_1h"].fillna(False)
            & dataframe["short_regime_4h"].fillna(False)
            & dataframe["short_recent_breakdown"].fillna(False)
            & dataframe["short_pullback_reject"].fillna(False)
            & short_adx_hard.fillna(False)
            & short_di_ok.fillna(False)
            & short_rsi_hard.fillna(False)
            & short_candle_quality.fillna(False)
            & short_volume_ok.fillna(False)
            & short_not_extended.fillna(False)
            & short_funding_edge.fillna(False)
            & ~short_crowded_skip.fillna(False)
            & dataframe["short_stop_valid"].fillna(False)
            & short_risk_ok.fillna(False)
            & trend_regime.fillna(False)
            & ~chop_regime.fillna(False)
        )
        dataframe.loc[
            short_a_plus,
            ["enter_short", "enter_tag"],
        ] = (1, "lsri_v2_short_trend")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        base_stake = min(proposed_stake, max_stake)
        if base_stake <= 0:
            return 0

        entry_candle = self._entry_candle_for_time(pair, current_time, side)
        if entry_candle is None:
            return base_stake

        risk_column = "short_risk_pct" if side == "short" else "long_risk_pct"
        risk_pct = self._safe_float(entry_candle.get(risk_column))
        effective_leverage = self._pair_leverage(pair)
        if risk_pct is None or risk_pct <= 0 or effective_leverage <= 0:
            return base_stake

        risk_budget = max_stake * self.max_account_risk_pct
        risk_limited_stake = risk_budget / (risk_pct * effective_leverage)
        stake_amount = min(base_stake, risk_limited_stake)
        if min_stake is not None and stake_amount < min_stake:
            return 0
        return stake_amount

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        return min(self._pair_leverage(pair), max_leverage)

    def _entry_candle_for_time(
        self,
        pair: str,
        current_time: datetime,
        side: Optional[str] = None,
    ) -> Optional[pd.Series]:
        data_provider = getattr(self, "dp", None)
        if not data_provider:
            return None
        dataframe, _ = data_provider.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None
        entry_rows = dataframe.loc[dataframe["date"] <= current_time]
        if entry_rows.empty:
            return dataframe.iloc[-1].squeeze()
        if side is not None:
            signal_column = "enter_short" if side == "short" else "enter_long"
            if signal_column in entry_rows:
                signal_rows = entry_rows.loc[
                    entry_rows[signal_column].fillna(0).astype(int) == 1
                ]
                if not signal_rows.empty:
                    return signal_rows.iloc[-1].squeeze()
        return entry_rows.iloc[-1].squeeze()

    def _entry_candle_for_trade(self, trade: Trade) -> Optional[pd.Series]:
        side = "short" if trade.is_short else "long"
        return self._entry_candle_for_time(trade.pair, trade.open_date_utc, side)

    def _ensure_trade_plan(self, trade: Trade) -> bool:
        if trade.get_custom_data("initial_stop_rate") is not None:
            return True

        entry_candle = self._entry_candle_for_trade(trade)
        if entry_candle is None:
            return False

        stop_column = "short_stop_rate" if trade.is_short else "long_stop_rate"
        stop_rate = self._safe_float(entry_candle.get(stop_column))
        entry_rate = self._safe_float(trade.open_rate)
        if stop_rate is None or entry_rate is None:
            return False

        risk_rate = abs(entry_rate - stop_rate)
        if risk_rate <= 0:
            return False

        if trade.is_short:
            take_profit_rate = entry_rate - (self.take_profit_r * risk_rate)
            half_r_rate = entry_rate - (self.time_stop_r * risk_rate)
        else:
            take_profit_rate = entry_rate + (self.take_profit_r * risk_rate)
            half_r_rate = entry_rate + (self.time_stop_r * risk_rate)

        trade.set_custom_data("initial_stop_rate", stop_rate)
        trade.set_custom_data("risk_rate", risk_rate)
        trade.set_custom_data("take_profit_rate", take_profit_rate)
        trade.set_custom_data("half_r_rate", half_r_rate)
        return True

    def _update_max_favorable_r(
        self,
        trade: Trade,
        current_rate: float,
        entry_rate: float,
        risk_rate: float,
    ) -> float:
        if trade.is_short:
            current_favorable_r = (entry_rate - current_rate) / risk_rate
        else:
            current_favorable_r = (current_rate - entry_rate) / risk_rate

        previous_max = self._safe_float(trade.get_custom_data("max_favorable_r"), 0.0)
        max_favorable_r = max(previous_max or 0.0, current_favorable_r)
        trade.set_custom_data("max_favorable_r", max_favorable_r)
        return max_favorable_r

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> Optional[float]:
        if not self._ensure_trade_plan(trade):
            return None

        stop_rate = self._safe_float(trade.get_custom_data("initial_stop_rate"))
        risk_rate = self._safe_float(trade.get_custom_data("risk_rate"))
        entry_rate = self._safe_float(trade.open_rate)
        if stop_rate is None or risk_rate is None or entry_rate is None:
            return None

        if trade.is_short:
            if current_rate <= entry_rate - (1.6 * risk_rate):
                stop_rate = min(stop_rate, entry_rate - (0.8 * risk_rate))
        else:
            if current_rate >= entry_rate + (1.6 * risk_rate):
                stop_rate = max(stop_rate, entry_rate + (0.8 * risk_rate))

        return stoploss_from_absolute(
            stop_rate,
            current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        if not self._ensure_trade_plan(trade):
            return None

        take_profit_rate = self._safe_float(trade.get_custom_data("take_profit_rate"))
        half_r_rate = self._safe_float(trade.get_custom_data("half_r_rate"))
        risk_rate = self._safe_float(trade.get_custom_data("risk_rate"))
        entry_rate = self._safe_float(trade.open_rate)
        if take_profit_rate is None or half_r_rate is None or risk_rate is None or entry_rate is None:
            return None

        max_favorable_r = self._update_max_favorable_r(
            trade,
            current_rate,
            entry_rate,
            risk_rate,
        )

        if trade.is_short:
            if current_rate <= take_profit_rate:
                return "short_tp_2_2r"
        else:
            if current_rate >= take_profit_rate:
                return "long_tp_2_2r"

        trade_duration_minutes = (current_time - trade.open_date_utc).total_seconds() / 60
        if (
            trade_duration_minutes >= self.early_time_stop_minutes
            and max_favorable_r < self.early_time_stop_r
        ):
            return "early_time_stop_no_impulse"

        if trade_duration_minutes >= self.time_stop_minutes:
            if trade.is_short and current_rate > half_r_rate:
                return "time_stop_no_impulse"
            if not trade.is_short and current_rate < half_r_rate:
                return "time_stop_no_impulse"

        return None
