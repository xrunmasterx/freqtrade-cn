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
    stoploss = -0.99
    use_custom_stoploss = True
    trailing_stop = False
    position_adjustment_enable = False
    startup_candle_count = 240

    pullback_window = 12
    pullback_tolerance = 0.0015
    funding_limit = 0.0003
    adx_threshold = 18.0
    volume_z_threshold = 1.0
    take_profit_r = 2.2
    time_stop_minutes = 90
    time_stop_r = 0.5
    fee_buffer_pct = 0.0015

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
    def _pair_stake_cap(pair: str) -> float:
        return 18.0 if pair.startswith(("BTC/", "ETH/")) else 0.0

    @staticmethod
    def _pair_leverage(pair: str) -> float:
        if pair.startswith("BTC/"):
            return 20.0
        if pair.startswith("ETH/"):
            return 15.0
        return 1.0

    @staticmethod
    def _populate_15m_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["atr14"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["adx14"] = ta.ADX(dataframe, timeperiod=14)
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

        dataframe["long_recent_breakout"] = (
            dataframe["long_structure_breakout_15m"]
            .fillna(False)
            .astype(int)
            .rolling(self.pullback_window)
            .max()
            > 0
        )
        dataframe["short_recent_breakdown"] = (
            dataframe["short_structure_breakdown_15m"]
            .fillna(False)
            .astype(int)
            .rolling(self.pullback_window)
            .max()
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
        dataframe.loc[
            (
                (dataframe["volume"] > 0)
                & dataframe["funding_rate_fr_1h"].notna()
                & dataframe["long_recent_breakout"]
                & dataframe["long_stop_valid"]
                & (dataframe["long_score"] >= 80)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "lsri_long_pullback_s80")

        dataframe.loc[
            (
                (dataframe["volume"] > 0)
                & dataframe["funding_rate_fr_1h"].notna()
                & dataframe["short_recent_breakdown"]
                & dataframe["short_stop_valid"]
                & (dataframe["short_score"] >= 80)
            ),
            ["enter_short", "enter_tag"],
        ] = (1, "lsri_short_pullback_s80")

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
        stake_cap = self._pair_stake_cap(pair)
        if stake_cap <= 0:
            return 0
        return min(proposed_stake, max_stake, stake_cap)

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

    def _entry_candle_for_trade(self, trade: Trade) -> Optional[pd.Series]:
        if not self.dp:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        if dataframe.empty:
            return None
        entry_rows = dataframe.loc[dataframe["date"] <= trade.open_date_utc]
        if entry_rows.empty:
            return dataframe.iloc[-1].squeeze()
        return entry_rows.iloc[-1].squeeze()

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

        fee_buffer = self.fee_buffer_pct * entry_rate

        if trade.is_short:
            if current_rate <= entry_rate - (1.6 * risk_rate):
                stop_rate = min(stop_rate, entry_rate - (0.8 * risk_rate))
            elif current_rate <= entry_rate - risk_rate:
                stop_rate = min(stop_rate, entry_rate - fee_buffer)
        else:
            if current_rate >= entry_rate + (1.6 * risk_rate):
                stop_rate = max(stop_rate, entry_rate + (0.8 * risk_rate))
            elif current_rate >= entry_rate + risk_rate:
                stop_rate = max(stop_rate, entry_rate + fee_buffer)

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
        if take_profit_rate is None or half_r_rate is None:
            return None

        if trade.is_short:
            if current_rate <= take_profit_rate:
                return "short_tp_2_2r"
        else:
            if current_rate >= take_profit_rate:
                return "long_tp_2_2r"

        trade_duration_minutes = (current_time - trade.open_date_utc).total_seconds() / 60
        if trade_duration_minutes >= self.time_stop_minutes:
            if trade.is_short and current_rate > half_r_rate:
                return "time_stop_no_impulse"
            if not trade.is_short and current_rate < half_r_rate:
                return "time_stop_no_impulse"

        return None
