from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd
from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_absolute
from pandas import DataFrame
from PriceFlowContinuationStrategy import PriceFlowContinuationStrategy


class PriceFlowCrossVenueResearchBase(PriceFlowContinuationStrategy):
    """Offline-only frozen candidates using causal cross-venue sidecars."""

    candidate_id = 0
    use_custom_stoploss = True

    _sidecar_columns: ClassVar[list[str]] = [
        "date",
        "decision_time",
        "bin_taker_imbalance",
        "bin_taker_lag1",
        "bin_taker_lag2",
        "bin_oi_change_5m",
        "bin_oi_change_15m",
        "bin_oi_delta_lag1",
        "bin_oi_delta_lag2",
        "bin_top_position_ratio",
        "bin_top_account_ratio",
        "bin_top_position_change_2h",
        "bin_top_account_change_2h",
        "bin_top_position_delta_lag1",
        "bin_global_account_log_z",
        "bin_breakout_long_recent",
        "bin_breakout_short_recent",
        "bin_breakout_long_current_15m",
        "bin_breakout_short_current_15m",
        "bin_price_return_15m",
        "bin_three_5m_valid",
        "opt_core_count_1h",
        "opt_core_urgency_1h",
        "opt_otm_count_1h",
        "opt_otm_flow_1h",
        "opt_otm_urgency_1h",
        "opt_dte_1_7_count_1h",
        "opt_dte_1_7_urgency_1h",
        "opt_dte_8_30_count_1h",
        "opt_dte_8_30_urgency_1h",
        "opt_dte_gt30_count_1h",
        "opt_dte_gt30_flow_1h",
        "opt_wing_urgency_1h",
        "opt_atm_count_1h",
        "opt_atm_buy_urgency_z",
        "opt_atm_direction_1h",
        "opt_block_count_1h",
        "opt_block_urgency_1h",
        "funding_dispersion_z",
        "funding_valid",
        "venue_spread",
        "venue_spread_shock",
        "venue_spread_cross_zero",
        "position_adding_long_follow",
        "position_adding_short_follow",
        "liquidation_long_shock",
        "liquidation_short_shock",
        "liquidation_long_reversal",
        "liquidation_short_reversal",
        "volatility_event",
        "taker_cusum_long_follow",
        "taker_cusum_short_follow",
        "option_iv_long_follow",
        "option_iv_short_follow",
        "cross_data_valid",
        "minutes_from_fomc",
        "minutes_from_cpi",
        "minutes_from_expiry",
        "nfp_calendar_valid",
    ]

    @property
    def candidate_code(self) -> str:
        if self.candidate_id == 0:
            return "B0"
        prefixes = ((1, 12, "B"), (13, 21, "D"), (22, 29, "X"), (30, 36, "P"), (37, 43, "A"))
        for start, end, prefix in prefixes:
            if start <= self.candidate_id <= end:
                return f"{prefix}{self.candidate_id:02d}"
        return f"R{self.candidate_id:02d}"

    def _sidecar_path(self, pair: str) -> Path:
        configured = self.config.get("cross_venue_sidecar_dir")
        if configured:
            root = Path(str(configured))
        else:
            user_data_dir = Path(str(self.config.get("user_data_dir", "/freqtrade/state")))
            root = user_data_dir / "cross-venue"
        asset = pair.split("/", maxsplit=1)[0]
        return root / f"{asset}_USDT_USDT-15m-cross-venue.feather"

    def _load_sidecar(self, pair: str) -> DataFrame:
        cache = getattr(self, "_cross_venue_sidecars", None)
        if cache is None:
            cache = {}
            self._cross_venue_sidecars = cache
        if pair not in cache:
            path = self._sidecar_path(pair)
            if not path.is_file():
                raise FileNotFoundError(f"Cross-venue sidecar is required: {path}")
            sidecar = pd.read_feather(path, columns=self._sidecar_columns)
            sidecar["date"] = pd.to_datetime(sidecar["date"], utc=True).astype(
                "datetime64[ns, UTC]"
            )
            sidecar["decision_time"] = pd.to_datetime(
                sidecar["decision_time"], utc=True
            ).astype("datetime64[ns, UTC]")
            if not (sidecar["decision_time"] == sidecar["date"] + pd.Timedelta(minutes=15)).all():
                raise ValueError(f"Invalid sidecar decision boundary: {path}")
            cache[pair] = sidecar.sort_values("date").reset_index(drop=True)
        return cache[pair].copy()

    def _merge_sidecar(self, dataframe: DataFrame, pair: str) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True).astype(
            "datetime64[ns, UTC]"
        )
        sidecar = self._load_sidecar(pair)
        return dataframe.merge(
            sidecar,
            on="date",
            how="left",
            validate="one_to_one",
            suffixes=("", "_sidecar"),
        )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe = self._merge_sidecar(dataframe, metadata["pair"])
        dataframe["research_long_structure"] = dataframe["donchian_high_48"].where(
            dataframe["long_displacement"]
        ).ffill()
        dataframe["research_short_structure"] = dataframe["donchian_low_48"].where(
            dataframe["short_displacement"]
        ).ffill()
        dataframe["bin_long_displacement_oi_change"] = dataframe[
            "bin_oi_change_15m"
        ].where(dataframe["long_displacement"]).ffill(limit=self.retest_window)
        dataframe["bin_short_displacement_oi_change"] = dataframe[
            "bin_oi_change_15m"
        ].where(dataframe["short_displacement"]).ffill(limit=self.retest_window)
        for side in ("long", "short"):
            displacement = dataframe[f"{side}_displacement"]
            for kind in ("position", "account"):
                ratio = dataframe[f"bin_top_{kind}_ratio"]
                displacement_ratio = ratio.where(displacement).ffill(
                    limit=self.retest_window
                )
                dataframe[f"bin_{side}_{kind}_change_from_displacement"] = np.log(
                    ratio / displacement_ratio
                )
        fomc_event = dataframe["minutes_from_fomc"].between(-15, 0)
        cpi_event = dataframe["minutes_from_cpi"].between(-15, 0)
        dataframe["fomc_event_high"] = dataframe["high"].where(fomc_event).ffill(limit=6)
        dataframe["fomc_event_low"] = dataframe["low"].where(fomc_event).ffill(limit=6)
        dataframe["cpi_event_high"] = dataframe["high"].where(cpi_event).ffill(limit=4)
        dataframe["cpi_event_low"] = dataframe["low"].where(cpi_event).ffill(limit=4)
        return dataframe

    @staticmethod
    def _market_context(dataframe: DataFrame) -> tuple[pd.Series, pd.Series]:
        long_context = (
            dataframe["long_trend_1h"].fillna(False)
            & dataframe["long_regime_4h"].fillna(False)
            & (dataframe["close"] > dataframe["rolling_vwap_24h"])
            & (dataframe["close"] > dataframe["ema20"])
            & (dataframe["return_24h_1h"] <= 0.08).fillna(False)
            & (dataframe["volume"] > 0)
        )
        short_context = (
            dataframe["short_trend_1h"].fillna(False)
            & dataframe["short_regime_4h"].fillna(False)
            & (dataframe["close"] < dataframe["rolling_vwap_24h"])
            & (dataframe["close"] < dataframe["ema20"])
            & (dataframe["return_24h_1h"] >= -0.08).fillna(False)
            & (dataframe["volume"] > 0)
        )
        return long_context, short_context

    @staticmethod
    def _at_least_two(values: list[pd.Series], positive: bool) -> pd.Series:
        comparisons = [(value > 0) if positive else (value < 0) for value in values]
        return sum(item.astype(int) for item in comparisons) >= 2

    @staticmethod
    def _signal_series(dataframe: DataFrame, column: str) -> pd.Series:
        if column not in dataframe:
            return pd.Series(False, index=dataframe.index)
        return pd.to_numeric(dataframe[column], errors="coerce").fillna(0).eq(1)

    def _core_gate(self, dataframe: DataFrame) -> tuple[pd.Series, pd.Series]:
        valid = dataframe["cross_data_valid"].fillna(False)
        candidate = self.candidate_id
        requires_cross_data = candidate in {
            *range(1, 22),
            22,
            24,
            25,
            28,
            29,
            38,
            41,
            42,
        }
        initial = valid if requires_cross_data else pd.Series(True, index=dataframe.index)
        long_gate = initial.copy()
        short_gate = initial.copy()
        taker = dataframe["bin_taker_imbalance"]
        if candidate == 1:
            long_gate &= taker > 0
            short_gate &= taker < 0
        elif candidate == 2:
            values = [taker, dataframe["bin_taker_lag1"], dataframe["bin_taker_lag2"]]
            long_gate &= self._at_least_two(values, True)
            short_gate &= self._at_least_two(values, False)
        elif candidate == 3:
            long_gate &= (dataframe["bin_taker_lag2"] <= 0) & (
                dataframe["bin_taker_lag1"] <= 0
            ) & (taker > 0)
            short_gate &= (dataframe["bin_taker_lag2"] >= 0) & (
                dataframe["bin_taker_lag1"] >= 0
            ) & (taker < 0)
        elif candidate == 4:
            long_gate &= dataframe["bin_long_displacement_oi_change"] > 0
            short_gate &= dataframe["bin_short_displacement_oi_change"] > 0
        elif candidate == 5:
            contraction = (dataframe["bin_oi_delta_lag2"] < 0) | (
                dataframe["bin_oi_delta_lag1"] < 0
            )
            recovery = dataframe["bin_oi_change_5m"] >= 0
            long_gate &= contraction & recovery
            short_gate &= contraction & recovery
        elif candidate == 6:
            expansion = dataframe["bin_oi_change_5m"] > 0
            long_gate &= expansion & (taker > 0)
            short_gate &= expansion & (taker < 0)
        elif candidate == 7:
            long_gate &= dataframe["bin_long_position_change_from_displacement"] > 0
            short_gate &= dataframe["bin_short_position_change_from_displacement"] < 0
        elif candidate == 8:
            long_gate &= dataframe["bin_long_account_change_from_displacement"] > 0
            short_gate &= dataframe["bin_short_account_change_from_displacement"] < 0
        elif candidate == 9:
            long_gate &= (dataframe["bin_long_position_change_from_displacement"] > 0) & (
                dataframe["bin_long_account_change_from_displacement"] <= 0
            )
            short_gate &= (dataframe["bin_short_position_change_from_displacement"] < 0) & (
                dataframe["bin_short_account_change_from_displacement"] >= 0
            )
        elif candidate == 10:
            long_gate &= dataframe["bin_global_account_log_z"] < 4
            short_gate &= dataframe["bin_global_account_log_z"] > -4
        elif candidate == 11:
            long_gate &= (dataframe["bin_top_position_delta_lag1"] > 0) & (taker > 0)
            short_gate &= (dataframe["bin_top_position_delta_lag1"] < 0) & (taker < 0)
        elif candidate == 12:
            previous_contraction = (dataframe["bin_oi_delta_lag2"] < 0) | (
                dataframe["bin_oi_delta_lag1"] < 0
            )
            long_gate &= previous_contraction & (dataframe["bin_oi_change_5m"] > 0)
            short_gate &= previous_contraction & (dataframe["bin_oi_change_5m"] > 0)
        elif candidate == 13:
            evidence = dataframe["opt_otm_count_1h"] >= 3
            long_gate &= ~(evidence & (dataframe["opt_otm_flow_1h"] <= -0.10))
            short_gate &= ~(evidence & (dataframe["opt_otm_flow_1h"] >= 0.10))
        elif candidate in {14, 20}:
            evidence = dataframe["opt_core_count_1h"] >= 3
            long_gate &= evidence & (dataframe["opt_core_urgency_1h"] > 0)
            short_gate &= evidence & (dataframe["opt_core_urgency_1h"] < 0)
        elif candidate == 15:
            evidence = dataframe["opt_dte_1_7_count_1h"] >= 3
            long_gate &= evidence & (dataframe["opt_dte_1_7_urgency_1h"] > 0)
            short_gate &= evidence & (dataframe["opt_dte_1_7_urgency_1h"] < 0)
        elif candidate == 16:
            evidence = dataframe["opt_dte_8_30_count_1h"] >= 3
            long_gate &= evidence & (dataframe["opt_dte_8_30_urgency_1h"] > 0)
            short_gate &= evidence & (dataframe["opt_dte_8_30_urgency_1h"] < 0)
        elif candidate == 17:
            evidence = dataframe["opt_dte_gt30_count_1h"] >= 3
            long_gate &= ~(evidence & (dataframe["opt_dte_gt30_flow_1h"] <= -0.10))
            short_gate &= ~(evidence & (dataframe["opt_dte_gt30_flow_1h"] >= 0.10))
        elif candidate == 18:
            evidence = dataframe["opt_otm_count_1h"] >= 3
            long_gate &= evidence & (dataframe["opt_wing_urgency_1h"] > 0)
            short_gate &= evidence & (dataframe["opt_wing_urgency_1h"] < 0)
        elif candidate == 19:
            dangerous = (
                (dataframe["opt_atm_count_1h"] >= 3)
                & (dataframe["opt_atm_buy_urgency_z"] >= 4)
                & (dataframe["opt_atm_direction_1h"].abs() < 0.10)
            )
            long_gate &= ~dangerous
            short_gate &= ~dangerous
        elif candidate == 21:
            evidence = dataframe["opt_block_count_1h"] >= 3
            long_gate &= evidence & (dataframe["opt_block_urgency_1h"] > 0)
            short_gate &= evidence & (dataframe["opt_block_urgency_1h"] < 0)
        elif candidate == 22:
            long_gate &= dataframe["bin_breakout_long_recent"].fillna(False)
            short_gate &= dataframe["bin_breakout_short_recent"].fillna(False)
        elif candidate == 24:
            long_gate &= dataframe["bin_price_return_15m"] > 0
            short_gate &= dataframe["bin_price_return_15m"] < 0
        elif candidate in {25, 41}:
            long_gate &= ~dataframe["venue_spread_shock"].fillna(True)
            short_gate &= ~dataframe["venue_spread_shock"].fillna(True)
        elif candidate == 28:
            evidence = dataframe["funding_valid"].fillna(False)
            long_gate &= ~(evidence & (dataframe["funding_dispersion_z"] >= 4))
            short_gate &= ~(evidence & (dataframe["funding_dispersion_z"] <= -4))
        elif candidate == 29:
            evidence = dataframe["opt_otm_count_1h"] >= 3
            long_gate &= evidence & (dataframe["opt_otm_urgency_1h"] > 0) & (taker > 0)
            short_gate &= evidence & (dataframe["opt_otm_urgency_1h"] < 0) & (taker < 0)
        elif candidate == 30:
            banned = dataframe["minutes_from_fomc"].between(-90, 15)
            long_gate &= ~banned
            short_gate &= ~banned
        elif candidate == 32:
            banned = dataframe["minutes_from_cpi"].between(-60, 15)
            long_gate &= ~banned
            short_gate &= ~banned
        elif candidate == 35:
            banned = dataframe["minutes_from_expiry"].between(-240, 0)
            long_gate &= ~banned
            short_gate &= ~banned
        elif candidate == 38:
            long_gate &= ~dataframe["liquidation_long_shock"].fillna(True)
            short_gate &= ~dataframe["liquidation_short_shock"].fillna(True)
        elif candidate == 42:
            long_gate &= ~dataframe["volatility_event"].fillna(True)
            short_gate &= ~dataframe["volatility_event"].fillna(True)
        return long_gate.fillna(False), short_gate.fillna(False)

    def _extra_entries(self, dataframe: DataFrame) -> tuple[pd.Series, pd.Series]:
        long_context, short_context = self._market_context(dataframe)
        candidate = self.candidate_id
        long_setup = pd.Series(False, index=dataframe.index)
        short_setup = long_setup.copy()
        if candidate == 23:
            long_setup = dataframe["bin_breakout_long_current_15m"].fillna(False) & (
                dataframe["close"] > dataframe["high"].shift(1)
            )
            short_setup = dataframe["bin_breakout_short_current_15m"].fillna(False) & (
                dataframe["close"] < dataframe["low"].shift(1)
            )
        elif candidate == 31:
            window = dataframe["minutes_from_fomc"].between(15, 90)
            long_setup = window & (dataframe["close"] > dataframe["fomc_event_high"])
            short_setup = window & (dataframe["close"] < dataframe["fomc_event_low"])
        elif candidate == 33:
            window = dataframe["minutes_from_cpi"].between(30, 60)
            long_setup = (
                window
                & (dataframe["close"] > dataframe["open"])
                & (dataframe["close"].shift(1) > dataframe["open"].shift(1))
                & (dataframe["close"] > dataframe["cpi_event_high"])
            )
            short_setup = (
                window
                & (dataframe["close"] < dataframe["open"])
                & (dataframe["close"].shift(1) < dataframe["open"].shift(1))
                & (dataframe["close"] < dataframe["cpi_event_low"])
            )
        elif candidate == 36:
            window = dataframe["minutes_from_expiry"].between(0, 360)
            raw_long = window & (
                dataframe["close"] > dataframe["high"].rolling(12).max().shift(1)
            )
            raw_short = window & (
                dataframe["close"] < dataframe["low"].rolling(12).min().shift(1)
            )
            event_group = dataframe["minutes_from_expiry"].eq(0).cumsum()
            long_setup = raw_long & raw_long.groupby(event_group).cumsum().eq(1)
            short_setup = raw_short & raw_short.groupby(event_group).cumsum().eq(1)
        elif candidate == 37:
            long_setup = dataframe["position_adding_long_follow"].fillna(False)
            short_setup = dataframe["position_adding_short_follow"].fillna(False)
        elif candidate == 39:
            long_setup = dataframe["liquidation_short_reversal"].fillna(False)
            short_setup = dataframe["liquidation_long_reversal"].fillna(False)
        elif candidate == 40:
            long_setup = dataframe["taker_cusum_long_follow"].fillna(False)
            short_setup = dataframe["taker_cusum_short_follow"].fillna(False)
        elif candidate == 42:
            base_long = dataframe["cv_core_long_signal"].fillna(False)
            base_short = dataframe["cv_core_short_signal"].fillna(False)
            long_setup = (
                base_long.shift(1).fillna(False)
                & dataframe["volatility_event"].shift(1).fillna(False)
                & (dataframe["close"] > dataframe["long_breakout_level"])
            )
            short_setup = (
                base_short.shift(1).fillna(False)
                & dataframe["volatility_event"].shift(1).fillna(False)
                & (dataframe["close"] < dataframe["short_breakout_level"])
            )
        elif candidate == 43:
            long_setup = dataframe["option_iv_long_follow"].fillna(False)
            short_setup = dataframe["option_iv_short_follow"].fillna(False)
        valid = dataframe["cross_data_valid"].fillna(False)
        return (
            long_setup & long_context & valid,
            short_setup & short_context & valid,
        )

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        core_long = self._signal_series(dataframe, "enter_long")
        core_short = self._signal_series(dataframe, "enter_short")
        dataframe["cv_core_long_signal"] = core_long
        dataframe["cv_core_short_signal"] = core_short
        long_gate, short_gate = self._core_gate(dataframe)
        selected_long = core_long & long_gate
        selected_short = core_short & short_gate
        dataframe.loc[core_long & ~selected_long, ["enter_long", "enter_tag"]] = (0, None)
        dataframe.loc[core_short & ~selected_short, ["enter_short", "enter_tag"]] = (0, None)
        code = self.candidate_code.lower()
        dataframe.loc[selected_long, "enter_tag"] = f"cv_{code}_long"
        dataframe.loc[selected_short, "enter_tag"] = f"cv_{code}_short"
        extra_long, extra_short = self._extra_entries(dataframe)
        dataframe.loc[extra_long & ~selected_long, ["enter_long", "enter_tag"]] = (
            1,
            f"cv_{code}_extra_long",
        )
        dataframe.loc[extra_short & ~selected_short, ["enter_short", "enter_tag"]] = (
            1,
            f"cv_{code}_extra_short",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_exit_trend(dataframe, metadata)
        candidate = self.candidate_id
        if candidate == 48:
            contraction = dataframe["bin_oi_change_5m"] < 0
            long_exit = contraction & (dataframe["bin_taker_imbalance"] < 0)
            short_exit = contraction & (dataframe["bin_taker_imbalance"] > 0)
        elif candidate == 49:
            crossed = dataframe["venue_spread_cross_zero"].fillna(False)
            long_exit = crossed & (dataframe["venue_spread"] < 0)
            short_exit = crossed & (dataframe["venue_spread"] > 0)
        elif candidate == 50:
            long_exit = dataframe["short_trend_1h"].fillna(False)
            short_exit = dataframe["long_trend_1h"].fillna(False)
        else:
            return dataframe
        tag = f"cv_{self.candidate_code.lower()}_exit"
        dataframe.loc[long_exit.fillna(False), ["exit_long", "exit_tag"]] = (1, tag)
        dataframe.loc[short_exit.fillna(False), ["exit_short", "exit_tag"]] = (1, tag)
        return dataframe

    def _latest_candle(self, pair: str, current_time: datetime) -> pd.Series | None:
        data_provider = getattr(self, "dp", None)
        if data_provider is None:
            return None
        dataframe, _ = data_provider.get_analyzed_dataframe(pair, self.timeframe)
        eligible = dataframe.loc[dataframe["date"] < current_time]
        return eligible.iloc[-1] if not eligible.empty else None

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
        candidate = self.candidate_id
        if candidate == 44:
            stop_rate = trade.get_custom_data("cv_structural_stop")
            if stop_rate is None:
                candle = self._latest_candle(pair, current_time)
                if candle is None:
                    return None
                level_name = (
                    "research_short_structure" if trade.is_short else "research_long_structure"
                )
                level = float(candle[level_name])
                atr = float(candle["atr14"])
                if not np.isfinite(level) or not np.isfinite(atr):
                    return None
                stop_rate = level + 0.5 * atr if trade.is_short else level - 0.5 * atr
                trade.set_custom_data("cv_structural_stop", stop_rate)
            return stoploss_from_absolute(
                float(stop_rate),
                current_rate,
                is_short=trade.is_short,
                leverage=trade.leverage,
            )
        if candidate == 46 and current_profit >= 0.03:
            fee_buffer = 0.001
            stop_rate = trade.open_rate * (
                (1 - fee_buffer) if trade.is_short else (1 + fee_buffer)
            )
            return stoploss_from_absolute(
                stop_rate,
                current_rate,
                is_short=trade.is_short,
                leverage=trade.leverage,
            )
        if candidate == 47 and current_profit >= 0.06:
            candle = self._latest_candle(pair, current_time)
            if candle is None or not np.isfinite(candle["atr14"]):
                return None
            atr = float(candle["atr14"])
            stop_rate = (
                trade.min_rate + 2 * atr if trade.is_short else trade.max_rate - 2 * atr
            )
            return stoploss_from_absolute(
                stop_rate,
                current_rate,
                is_short=trade.is_short,
                leverage=trade.leverage,
            )
        return None

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        if self.candidate_id == 45:
            duration = (current_time - trade.open_date_utc).total_seconds() / 60
            if duration >= 120:
                return "cv_r45_time_stop"
        return None


class PriceFlowCrossVenueControl(PriceFlowCrossVenueResearchBase):
    candidate_id = 0


# Freqtrade prefilters strategy files using literal ``class <name>(`` source markers
# before importing them.  The candidates are generated below, so keep one marker per
# frozen candidate here for StrategyResolver discovery.
# class PriceFlowCrossVenue01Strategy(
# class PriceFlowCrossVenue02Strategy(
# class PriceFlowCrossVenue03Strategy(
# class PriceFlowCrossVenue04Strategy(
# class PriceFlowCrossVenue05Strategy(
# class PriceFlowCrossVenue06Strategy(
# class PriceFlowCrossVenue07Strategy(
# class PriceFlowCrossVenue08Strategy(
# class PriceFlowCrossVenue09Strategy(
# class PriceFlowCrossVenue10Strategy(
# class PriceFlowCrossVenue11Strategy(
# class PriceFlowCrossVenue12Strategy(
# class PriceFlowCrossVenue13Strategy(
# class PriceFlowCrossVenue14Strategy(
# class PriceFlowCrossVenue15Strategy(
# class PriceFlowCrossVenue16Strategy(
# class PriceFlowCrossVenue17Strategy(
# class PriceFlowCrossVenue18Strategy(
# class PriceFlowCrossVenue19Strategy(
# class PriceFlowCrossVenue20Strategy(
# class PriceFlowCrossVenue21Strategy(
# class PriceFlowCrossVenue22Strategy(
# class PriceFlowCrossVenue23Strategy(
# class PriceFlowCrossVenue24Strategy(
# class PriceFlowCrossVenue25Strategy(
# class PriceFlowCrossVenue26Strategy(
# class PriceFlowCrossVenue27Strategy(
# class PriceFlowCrossVenue28Strategy(
# class PriceFlowCrossVenue29Strategy(
# class PriceFlowCrossVenue30Strategy(
# class PriceFlowCrossVenue31Strategy(
# class PriceFlowCrossVenue32Strategy(
# class PriceFlowCrossVenue33Strategy(
# class PriceFlowCrossVenue34Strategy(
# class PriceFlowCrossVenue35Strategy(
# class PriceFlowCrossVenue36Strategy(
# class PriceFlowCrossVenue37Strategy(
# class PriceFlowCrossVenue38Strategy(
# class PriceFlowCrossVenue39Strategy(
# class PriceFlowCrossVenue40Strategy(
# class PriceFlowCrossVenue41Strategy(
# class PriceFlowCrossVenue42Strategy(
# class PriceFlowCrossVenue43Strategy(
# class PriceFlowCrossVenue44Strategy(
# class PriceFlowCrossVenue45Strategy(
# class PriceFlowCrossVenue46Strategy(
# class PriceFlowCrossVenue47Strategy(
# class PriceFlowCrossVenue48Strategy(
# class PriceFlowCrossVenue49Strategy(
# class PriceFlowCrossVenue50Strategy(


def _candidate_class(candidate_id: int) -> type[PriceFlowCrossVenueResearchBase]:
    return type(
        f"PriceFlowCrossVenue{candidate_id:02d}Strategy",
        (PriceFlowCrossVenueResearchBase,),
        {"candidate_id": candidate_id, "__module__": __name__},
    )


for _candidate_id in range(1, 51):
    globals()[f"PriceFlowCrossVenue{_candidate_id:02d}Strategy"] = _candidate_class(
        _candidate_id
    )
