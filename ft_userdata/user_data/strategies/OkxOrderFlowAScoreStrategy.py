from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair, stoploss_from_absolute
from pandas import DataFrame


class OkxOrderFlowAScoreStrategy(IStrategy):
    """Research-only BTC/ETH A-score strategy backed by real OKX aggressor trades."""

    INTERFACE_VERSION = 3
    research_only = True
    can_short = True
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 192

    minimal_roi: ClassVar[dict[str, float]] = {"0": 100.0}
    stoploss = -0.12
    use_custom_stoploss = True
    trailing_stop = False
    position_adjustment_enable = False

    leverage_value = 3.0
    a_risk_pct = 0.0125
    a_plus_risk_pct = 0.0200
    take_profit_r = 2.0
    key_near_full_atr = 0.15
    key_near_atr = 0.35
    funding_extreme = 0.0003
    minimum_atr_pct = 0.004
    maximum_atr_pct = 0.045

    sidecar_dir = (
        Path(__file__).resolve().parents[1]
        / "research_data"
        / "okx-orderflow-score"
        / "derived"
    )
    sidecar_names: ClassVar[dict[str, str]] = {
        "BTC/USDT:USDT": "BTC-USDT-SWAP-15m-orderflow.feather",
        "ETH/USDT:USDT": "ETH-USDT-SWAP-15m-orderflow.feather",
    }

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "vp_poc": {"color": "#f4d03f"},
            "vp_vah": {"color": "#e67e22"},
            "vp_val": {"color": "#1abc9c"},
            "prior_day_high": {"color": "#c0392b"},
            "prior_day_low": {"color": "#27ae60"},
            "long_stop_rate": {"color": "#7dcea0"},
            "short_stop_rate": {"color": "#f1948a"},
        },
        "subplots": {
            "OKX Order Flow": {
                "imbalance": {"color": "#3498db"},
                "cvd_slope_4": {"color": "#9b59b6"},
            },
            "A Score": {
                "long_total_score": {"color": "#2ecc71"},
                "short_total_score": {"color": "#e74c3c"},
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
                    (pair, "1h"),
                    (pair, "4h"),
                ]
            )
        return informative

    @staticmethod
    def _safe_float(value, default: float | None = None) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default
        return result if np.isfinite(result) else default

    @staticmethod
    def _grade(
        total: pd.Series,
        htf: pd.Series,
        key: pd.Series,
        orderflow: pd.Series,
    ) -> pd.Series:
        a_plus = total.ge(85) & htf.eq(25) & key.eq(20) & orderflow.eq(25)
        grade_a = total.between(70, 84) & htf.ge(18) & key.gt(0) & orderflow.ge(18)
        return pd.Series(
            np.select([a_plus, grade_a], [2, 1], default=0), index=total.index
        )

    @classmethod
    def _prepare_sidecar(cls, sidecar: DataFrame) -> DataFrame:
        required = {
            "date",
            "source_complete_time",
            "decision_time",
            "constituent_5m_count",
            "trade_count",
            "buy_base",
            "sell_base",
            "total_base",
            "delta_base",
            "imbalance",
            "first_5m_imbalance",
            "last_5m_imbalance",
            "last_5m_return",
            "cvd_session",
            "cvd_slope_4",
            "vp_source_day",
            "vp_source_complete_time",
            "vp_poc",
            "vp_vah",
            "vp_val",
            "prior_day_high",
            "prior_day_low",
            "oi_source_time",
            "oi_usd",
            "funding_source_time",
            "funding_rate",
        }
        missing = required.difference(sidecar.columns)
        if missing:
            raise ValueError(
                f"OKX order-flow sidecar is missing columns: {sorted(missing)}"
            )
        evidence = sidecar.copy()
        timestamps = [
            "date",
            "source_complete_time",
            "decision_time",
            "vp_source_day",
            "vp_source_complete_time",
            "oi_source_time",
            "funding_source_time",
        ]
        for column in timestamps:
            evidence[column] = pd.to_datetime(
                evidence[column], utc=True, errors="coerce"
            ).astype("datetime64[ns, UTC]")
        if evidence[timestamps].isna().any().any():
            raise ValueError("OKX order-flow sidecar contains an invalid timestamp")
        if (
            evidence["date"].duplicated().any()
            or not evidence["date"].is_monotonic_increasing
        ):
            raise ValueError("OKX order-flow sidecar dates must be unique and ordered")
        expected_complete = evidence["date"] + pd.Timedelta(minutes=15)
        if not evidence["source_complete_time"].equals(expected_complete):
            raise ValueError("Order-flow source complete time must equal candle close")
        if not evidence["decision_time"].equals(expected_complete):
            raise ValueError("Order-flow decision time must equal candle close")
        if (
            not pd.to_numeric(evidence["constituent_5m_count"], errors="coerce")
            .eq(3)
            .all()
        ):
            raise ValueError(
                "OKX order-flow sidecar requires three complete 5m buckets"
            )
        if evidence["vp_source_complete_time"].gt(evidence["date"]).any():
            raise ValueError("Volume-profile evidence is not complete at candle open")
        if evidence["oi_source_time"].gt(evidence["date"]).any():
            raise ValueError("Open-interest evidence is newer than its candle")
        numeric = list(required.difference(timestamps))
        values = evidence[numeric].apply(pd.to_numeric, errors="coerce")
        if not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(
                "OKX order-flow sidecar contains missing or non-finite evidence"
            )
        return evidence

    @classmethod
    def _load_sidecar(cls, pair: str) -> DataFrame:
        name = cls.sidecar_names.get(pair)
        if name is None:
            raise ValueError(
                f"Strategy is restricted to BTC/ETH OKX swaps, received {pair}"
            )
        path = cls.sidecar_dir / name
        if not path.is_file():
            raise ValueError(f"Missing real OKX order-flow sidecar: {path}")
        return cls._prepare_sidecar(pd.read_feather(path))

    @classmethod
    def _merge_sidecar(
        cls,
        dataframe: DataFrame,
        pair: str,
        sidecar: DataFrame | None = None,
    ) -> DataFrame:
        evidence = (
            cls._load_sidecar(pair)
            if sidecar is None
            else cls._prepare_sidecar(sidecar)
        )
        result = dataframe.copy()
        result["date"] = pd.to_datetime(result["date"], utc=True, errors="raise")
        return result.merge(evidence, on="date", how="left", validate="one_to_one")

    @staticmethod
    def _populate_htf(dataframe: DataFrame) -> DataFrame:
        frame = dataframe.copy()
        frame["ema20"] = ta.EMA(frame, timeperiod=20)
        frame["ema50"] = ta.EMA(frame, timeperiod=50)
        frame["atr14"] = ta.ATR(frame, timeperiod=14)
        change = frame["close"].diff().abs()
        frame["efficiency12"] = (
            frame["close"] - frame["close"].shift(12)
        ).abs() / change.rolling(12).sum().replace(0, np.nan)
        prior_high = frame["high"].rolling(20).max().shift(1)
        prior_low = frame["low"].rolling(20).min().shift(1)
        range12 = frame["high"].rolling(12).max() - frame["low"].rolling(12).min()
        frame["cage"] = frame["efficiency12"].lt(0.20) & range12.div(
            frame["atr14"].replace(0, np.nan)
        ).lt(4.0)
        frame["always_long"] = (
            frame["close"].gt(frame["ema20"])
            & frame["ema20"].gt(frame["ema50"])
            & frame["ema20"].gt(frame["ema20"].shift(3))
        )
        frame["always_short"] = (
            frame["close"].lt(frame["ema20"])
            & frame["ema20"].lt(frame["ema50"])
            & frame["ema20"].lt(frame["ema20"].shift(3))
        )
        frame["breakout_long"] = frame["close"].gt(prior_high)
        frame["breakout_short"] = frame["close"].lt(prior_low)
        frame["narrow_long"] = frame["always_long"] & frame["efficiency12"].ge(0.50)
        frame["narrow_short"] = frame["always_short"] & frame["efficiency12"].ge(0.50)
        return frame

    @staticmethod
    def _distance_to_candle(
        level: pd.Series,
        low: pd.Series,
        high: pd.Series,
    ) -> pd.Series:
        return pd.Series(
            np.where(
                level.lt(low), low - level, np.where(level.gt(high), level - high, 0.0)
            ),
            index=level.index,
        )

    @staticmethod
    def _cvd_leading(
        *,
        cvd_slope: pd.Series,
        last_imbalance: pd.Series,
        close: pd.Series,
        prior_high: pd.Series,
        prior_low: pd.Series,
        upper_threshold: pd.Series,
        lower_threshold: pd.Series,
    ) -> tuple[pd.Series, pd.Series]:
        long = (
            cvd_slope.ge(upper_threshold)
            & last_imbalance.ge(0.08)
            & close.le(prior_high)
        )
        short = (
            cvd_slope.le(lower_threshold)
            & last_imbalance.le(-0.08)
            & close.ge(prior_low)
        )
        return long.fillna(False), short.fillna(False)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        dataframe = self._merge_sidecar(dataframe, pair)
        dataframe["atr14"] = ta.ATR(dataframe, timeperiod=14)
        candle_range = (dataframe["high"] - dataframe["low"]).replace(0, np.nan)
        body = (dataframe["close"] - dataframe["open"]).abs()
        dataframe["body_atr"] = body / dataframe["atr14"].replace(0, np.nan)
        dataframe["close_position"] = (
            dataframe["close"] - dataframe["low"]
        ) / candle_range
        dataframe["lower_wick"] = (
            dataframe[["open", "close"]].min(axis=1) - dataframe["low"]
        )
        dataframe["upper_wick"] = dataframe["high"] - dataframe[["open", "close"]].max(
            axis=1
        )
        dataframe["prior_flow_q75"] = (
            dataframe["total_base"].shift(1).rolling(48).quantile(0.75)
        )

        if not self.dp:
            return dataframe
        one_hour = self._populate_htf(
            self.dp.get_pair_dataframe(pair=pair, timeframe="1h")
        )
        four_hour = self._populate_htf(
            self.dp.get_pair_dataframe(pair=pair, timeframe="4h")
        )
        dataframe = merge_informative_pair(
            dataframe, one_hour, self.timeframe, "1h", ffill=True
        )
        dataframe = merge_informative_pair(
            dataframe, four_hour, self.timeframe, "4h", ffill=True
        )
        return self._populate_scores(dataframe)

    def _populate_scores(self, dataframe: DataFrame) -> DataFrame:
        long_aligned = dataframe["always_long_1h"].fillna(False) & dataframe[
            "always_long_4h"
        ].fillna(False)
        short_aligned = dataframe["always_short_1h"].fillna(False) & dataframe[
            "always_short_4h"
        ].fillna(False)
        long_premium = dataframe["breakout_long_1h"].fillna(False) | dataframe[
            "narrow_long_1h"
        ].fillna(False)
        short_premium = dataframe["breakout_short_1h"].fillna(False) | dataframe[
            "narrow_short_1h"
        ].fillna(False)
        long_usable = long_aligned & ~dataframe["cage_1h"].fillna(True)
        short_usable = short_aligned & ~dataframe["cage_1h"].fillna(True)
        dataframe["long_htf_score"] = np.select(
            [long_usable & long_premium, long_usable], [25, 18], default=0
        )
        dataframe["short_htf_score"] = np.select(
            [short_usable & short_premium, short_usable], [25, 18], default=0
        )

        atr = dataframe["atr14"].replace(0, np.nan)
        dataframe["atr_pct"] = atr.div(dataframe["close"].replace(0, np.nan))
        dataframe["volatility_ok"] = dataframe["atr_pct"].between(
            self.minimum_atr_pct, self.maximum_atr_pct
        )
        long_distances = pd.concat(
            [
                self._distance_to_candle(
                    dataframe[column], dataframe["low"], dataframe["high"]
                )
                for column in ("vp_val", "vp_poc", "prior_day_low")
            ],
            axis=1,
        )
        short_distances = pd.concat(
            [
                self._distance_to_candle(
                    dataframe[column], dataframe["low"], dataframe["high"]
                )
                for column in ("vp_vah", "vp_poc", "prior_day_high")
            ],
            axis=1,
        )
        dataframe["long_key_distance_atr"] = long_distances.min(axis=1) / atr
        dataframe["short_key_distance_atr"] = short_distances.min(axis=1) / atr
        dataframe["long_key_score"] = np.select(
            [
                dataframe["long_key_distance_atr"].le(self.key_near_full_atr),
                dataframe["long_key_distance_atr"].le(self.key_near_atr),
            ],
            [20, 15],
            default=0,
        )
        dataframe["short_key_score"] = np.select(
            [
                dataframe["short_key_distance_atr"].le(self.key_near_full_atr),
                dataframe["short_key_distance_atr"].le(self.key_near_atr),
            ],
            [20, 15],
            default=0,
        )

        high_flow = dataframe["total_base"].ge(dataframe["prior_flow_q75"])
        long_absorption = (
            dataframe["imbalance"].le(-0.12)
            & high_flow
            & dataframe["close_position"].ge(0.55)
            & dataframe["lower_wick"].gt(0)
        )
        short_absorption = (
            dataframe["imbalance"].ge(0.12)
            & high_flow
            & dataframe["close_position"].le(0.45)
            & dataframe["upper_wick"].gt(0)
        )
        prior_low = dataframe["low"].rolling(12).min().shift(1)
        prior_high = dataframe["high"].rolling(12).max().shift(1)
        prior_delta_low = dataframe["delta_base"].rolling(12).min().shift(1)
        prior_delta_high = dataframe["delta_base"].rolling(12).max().shift(1)
        long_divergence = (
            dataframe["low"].lt(prior_low)
            & dataframe["delta_base"].gt(prior_delta_low)
            & dataframe["close_position"].ge(0.50)
        )
        short_divergence = (
            dataframe["high"].gt(prior_high)
            & dataframe["delta_base"].lt(prior_delta_high)
            & dataframe["close_position"].le(0.50)
        )
        prior_cvd_q90 = dataframe["cvd_slope_4"].shift(1).rolling(96).quantile(0.90)
        prior_cvd_q10 = dataframe["cvd_slope_4"].shift(1).rolling(96).quantile(0.10)
        long_cvd_leading, short_cvd_leading = self._cvd_leading(
            cvd_slope=dataframe["cvd_slope_4"],
            last_imbalance=dataframe["last_5m_imbalance"],
            close=dataframe["close"],
            prior_high=prior_high,
            prior_low=prior_low,
            upper_threshold=prior_cvd_q90,
            lower_threshold=prior_cvd_q10,
        )
        long_follow = dataframe["close"].gt(dataframe["high"].shift(1)) & dataframe[
            "delta_base"
        ].gt(0)
        short_follow = dataframe["close"].lt(dataframe["low"].shift(1)) & dataframe[
            "delta_base"
        ].lt(0)
        long_full = (
            long_absorption.shift(1).fillna(False)
            | long_divergence.shift(1).fillna(False)
            | long_cvd_leading.shift(1).fillna(False)
        ) & long_follow
        short_full = (
            short_absorption.shift(1).fillna(False)
            | short_divergence.shift(1).fillna(False)
            | short_cvd_leading.shift(1).fillna(False)
        ) & short_follow
        long_single = long_absorption | long_divergence | long_cvd_leading
        short_single = short_absorption | short_divergence | short_cvd_leading
        dataframe["long_orderflow_score"] = np.select(
            [long_full, long_single], [25, 18], default=0
        )
        dataframe["short_orderflow_score"] = np.select(
            [short_full, short_single], [25, 18], default=0
        )

        long_strong = (
            dataframe["close"].gt(dataframe["open"])
            & dataframe["close_position"].ge(0.70)
            & dataframe["body_atr"].ge(0.50)
        )
        short_strong = (
            dataframe["close"].lt(dataframe["open"])
            & dataframe["close_position"].le(0.30)
            & dataframe["body_atr"].ge(0.50)
        )
        long_acceptable = (
            dataframe["close"].gt(dataframe["open"])
            & dataframe["close_position"].ge(0.55)
            & dataframe["long_key_score"].gt(0)
        )
        short_acceptable = (
            dataframe["close"].lt(dataframe["open"])
            & dataframe["close_position"].le(0.45)
            & dataframe["short_key_score"].gt(0)
        )
        dataframe["long_signal_score"] = np.select(
            [long_strong, long_acceptable], [15, 10], default=0
        )
        dataframe["short_signal_score"] = np.select(
            [short_strong, short_acceptable], [15, 10], default=0
        )

        long_votes = (
            dataframe["last_5m_return"].gt(0).astype(int)
            + dataframe["close"].gt(dataframe["open"]).astype(int)
            + dataframe["always_long_1h"].fillna(False).astype(int)
        )
        short_votes = (
            dataframe["last_5m_return"].lt(0).astype(int)
            + dataframe["close"].lt(dataframe["open"]).astype(int)
            + dataframe["always_short_1h"].fillna(False).astype(int)
        )
        dataframe["long_mtf_score"] = np.select(
            [long_votes.eq(3), long_votes.eq(2)], [10, 6], default=0
        )
        dataframe["short_mtf_score"] = np.select(
            [short_votes.eq(3), short_votes.eq(2)], [10, 6], default=0
        )
        dataframe["long_extra_score"] = np.where(
            dataframe["funding_rate"].le(-self.funding_extreme), 3, 0
        )
        dataframe["short_extra_score"] = np.where(
            dataframe["funding_rate"].ge(self.funding_extreme), 3, 0
        )

        for side in ("long", "short"):
            dataframe[f"{side}_total_score"] = sum(
                dataframe[f"{side}_{component}_score"]
                for component in ("htf", "key", "orderflow", "signal", "mtf", "extra")
            )
            dataframe[f"{side}_grade"] = self._grade(
                dataframe[f"{side}_total_score"],
                dataframe[f"{side}_htf_score"],
                dataframe[f"{side}_key_score"],
                dataframe[f"{side}_orderflow_score"],
            )

        evidence_columns = [
            "source_complete_time",
            "vp_poc",
            "vp_vah",
            "vp_val",
            "oi_usd",
            "funding_rate",
        ]
        dataframe["orderflow_evidence_valid"] = (
            dataframe[evidence_columns].notna().all(axis=1)
        )
        dataframe["oi_ok"] = dataframe["oi_usd"].ge(dataframe["minimum_oi_usd"])
        support = dataframe[["vp_val", "vp_poc", "prior_day_low"]].min(axis=1)
        resistance = dataframe[["vp_vah", "vp_poc", "prior_day_high"]].max(axis=1)
        dataframe["long_stop_rate"] = (
            pd.concat([dataframe["low"], support], axis=1).min(axis=1) - 0.2 * atr
        )
        dataframe["short_stop_rate"] = (
            pd.concat([dataframe["high"], resistance], axis=1).max(axis=1) + 0.2 * atr
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = None
        valid = (
            dataframe["volume"].gt(0)
            & dataframe["orderflow_evidence_valid"].fillna(False)
            & dataframe["oi_ok"].fillna(False)
            & dataframe["volatility_ok"].fillna(False)
        )
        long_grade = self._grade(
            dataframe["long_total_score"],
            dataframe["long_htf_score"],
            dataframe["long_key_score"],
            dataframe["long_orderflow_score"],
        )
        short_grade = self._grade(
            dataframe["short_total_score"],
            dataframe["short_htf_score"],
            dataframe["short_key_score"],
            dataframe["short_orderflow_score"],
        )
        dataframe.loc[valid & long_grade.eq(2), ["enter_long", "enter_tag"]] = (
            1,
            "okx_a_plus_long",
        )
        dataframe.loc[valid & long_grade.eq(1), ["enter_long", "enter_tag"]] = (
            1,
            "okx_a_long",
        )
        dataframe.loc[valid & short_grade.eq(2), ["enter_short", "enter_tag"]] = (
            1,
            "okx_a_plus_short",
        )
        dataframe.loc[valid & short_grade.eq(1), ["enter_short", "enter_tag"]] = (
            1,
            "okx_a_short",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
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
        return min(self.leverage_value, max_leverage)

    def _entry_candle(
        self,
        pair: str,
        current_time: datetime,
        side: str,
    ) -> pd.Series | None:
        if not self.dp:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None
        signal = "enter_short" if side == "short" else "enter_long"
        rows = dataframe.loc[
            dataframe["date"].le(current_time)
            & dataframe[signal].fillna(0).astype(bool)
        ]
        return None if rows.empty else rows.iloc[-1].squeeze()

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
        candle = self._entry_candle(pair, current_time, side)
        if candle is None:
            return 0.0
        stop_column = "short_stop_rate" if side == "short" else "long_stop_rate"
        stop_rate = self._safe_float(candle.get(stop_column))
        if stop_rate is None or current_rate <= 0:
            return 0.0
        stop_distance = abs(current_rate - stop_rate) / current_rate
        if stop_distance <= 0:
            return 0.0
        risk_pct = (
            self.a_plus_risk_pct
            if entry_tag and "a_plus" in entry_tag
            else self.a_risk_pct
        )
        wallet = self.wallets.get_total_stake_amount()
        target = wallet * risk_pct / (stop_distance * max(leverage, 1.0))
        stake = min(target, max_stake)
        if min_stake is not None and stake < min_stake:
            return 0.0
        return stake

    def _ensure_trade_plan(self, trade: Trade) -> bool:
        if trade.get_custom_data("initial_stop_rate") is not None:
            return True
        side = "short" if trade.is_short else "long"
        candle = self._entry_candle(trade.pair, trade.open_date_utc, side)
        if candle is None:
            return False
        stop_column = "short_stop_rate" if trade.is_short else "long_stop_rate"
        stop_rate = self._safe_float(candle.get(stop_column))
        entry_rate = self._safe_float(trade.open_rate)
        if stop_rate is None or entry_rate is None:
            return False
        risk_rate = abs(entry_rate - stop_rate)
        if risk_rate <= 0:
            return False
        target = (
            entry_rate - self.take_profit_r * risk_rate
            if trade.is_short
            else entry_rate + self.take_profit_r * risk_rate
        )
        trade.set_custom_data("initial_stop_rate", stop_rate)
        trade.set_custom_data("take_profit_rate", target)
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
        stop_rate = self._safe_float(trade.get_custom_data("initial_stop_rate"))
        if stop_rate is None:
            return None
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
    ) -> str | None:
        if not self._ensure_trade_plan(trade):
            return None
        target = self._safe_float(trade.get_custom_data("take_profit_rate"))
        if target is not None:
            if trade.is_short and current_rate <= target:
                return "short_target_2r"
            if not trade.is_short and current_rate >= target:
                return "long_target_2r"
        if not self.dp:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        rows = dataframe.loc[dataframe["date"].le(current_time)]
        if rows.empty:
            return None
        current = rows.iloc[-1]
        if trade.is_short and int(current.get("short_htf_score", 0)) == 0:
            return "short_htf_invalidated"
        if not trade.is_short and int(current.get("long_htf_score", 0)) == 0:
            return "long_htf_invalidated"
        return None
