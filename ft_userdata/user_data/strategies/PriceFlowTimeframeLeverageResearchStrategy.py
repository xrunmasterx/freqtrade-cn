from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame
from PriceFlowParticipationFreshnessStrategy import (
    PriceFlowParticipationFreshnessStrategy,
)


class PriceFlowTimeframeLeverageResearchBase(PriceFlowParticipationFreshnessStrategy):
    """E10 duplicate with real-clock price windows and causal 5m flow alignment."""

    target_leverage = 2.0
    confirmation_mode = "original"
    startup_candle_count = 960

    _timeframe_minutes: ClassVar[dict[str, int]] = {
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
    }
    _flow_columns: ClassVar[list[str]] = [
        "bin_taker_imbalance",
        "bin_taker_lag1",
        "bin_taker_lag2",
        "bin_oi_change_5m",
        "bin_oi_change_15m",
        "bin_oi_delta_lag1",
        "bin_oi_delta_lag2",
        "bin_top_position_ratio",
        "bin_top_account_ratio",
        "bin_top_position_change_5m",
        "bin_top_account_change_5m",
        "bin_top_position_change_2h",
        "bin_top_account_change_2h",
        "bin_top_position_delta_lag1",
        "bin_global_account_log_z",
        "bin_breakout_long_recent",
        "bin_breakout_short_recent",
        "bin_breakout_long_current_15m",
        "bin_breakout_short_current_15m",
        "bin_price_return_15m",
        "bin_oi_change_15m_z",
        "bin_taker_imbalance_z",
        "bin_three_5m_valid",
    ]

    @property
    def primary_minutes(self) -> int:
        try:
            return self._timeframe_minutes[self.timeframe]
        except KeyError as exc:
            raise ValueError(f"Unsupported E10 research timeframe: {self.timeframe}") from exc

    @staticmethod
    def _bars(duration_minutes: int, timeframe_minutes: int, minimum: int = 1) -> int:
        return max(minimum, math.ceil(duration_minutes / timeframe_minutes))

    @property
    def adaptive_windows(self) -> dict[str, int]:
        minutes = self.primary_minutes
        return {
            "atr": self._bars(210, minutes, 2),
            "ema": self._bars(300, minutes, 2),
            "donchian": self._bars(720, minutes, 2),
            "relative_volume": self._bars(1440, minutes, 2),
            "vwap": self._bars(1440, minutes, 2),
            "flow_fast": self._bars(120, minutes, 2),
            "flow_slow": self._bars(360, minutes, 2),
            "retest": self._bars(120, minutes),
            "cooldown": self._bars(60, minutes),
        }

    @property
    def retest_window(self) -> int:
        return self.adaptive_windows["retest"]

    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": self.adaptive_windows["cooldown"],
            }
        ]

    def informative_pairs(self):
        data_provider = getattr(self, "dp", None)
        pairs = (
            data_provider.current_whitelist()
            if data_provider
            else self.config.get("exchange", {}).get("pair_whitelist", [])
        )
        return [
            (pair, timeframe)
            for pair in pairs
            for timeframe in ("1h", "4h")
            if timeframe != self.timeframe
        ]

    def _merge_closed_informative(
        self,
        dataframe: DataFrame,
        informative: DataFrame,
        *,
        informative_timeframe: str,
    ) -> DataFrame:
        informative_minutes = {"1h": 60, "4h": 240}[informative_timeframe]
        left = dataframe.copy()
        left["date"] = pd.to_datetime(left["date"], utc=True).astype(
            "datetime64[ns, UTC]"
        )
        left["__row_order"] = np.arange(len(left))
        left["__primary_decision"] = left["date"] + pd.Timedelta(
            minutes=self.primary_minutes
        )

        right = informative.copy()
        right["date"] = pd.to_datetime(right["date"], utc=True).astype(
            "datetime64[ns, UTC]"
        )
        right["__informative_decision"] = right["date"] + pd.Timedelta(
            minutes=informative_minutes
        )
        right = right.rename(
            columns={
                column: f"{column}_{informative_timeframe}"
                for column in right.columns
                if column != "__informative_decision"
            }
        )
        merged = pd.merge_asof(
            left.sort_values("__primary_decision"),
            right.sort_values("__informative_decision"),
            left_on="__primary_decision",
            right_on="__informative_decision",
            direction="backward",
            allow_exact_matches=True,
        )
        return (
            merged.sort_values("__row_order")
            .drop(columns=["__row_order", "__primary_decision", "__informative_decision"])
            .reset_index(drop=True)
        )

    def _load_five_minute_flow(self, pair: str) -> DataFrame:
        cache = getattr(self, "_five_minute_flow_sidecars", None)
        if cache is None:
            cache = {}
            self._five_minute_flow_sidecars = cache
        if pair not in cache:
            configured = self.config.get("cross_venue_5m_flow_dir")
            if not configured:
                raise ValueError("cross_venue_5m_flow_dir is required for E10 timeframe research")
            asset = pair.split("/", maxsplit=1)[0]
            path = Path(str(configured)) / f"{asset}_USDT_USDT-5m-binance-flow.feather"
            if not path.is_file():
                raise FileNotFoundError(f"Causal 5m flow sidecar is required: {path}")
            flow = pd.read_feather(path, columns=["decision_time", *self._flow_columns])
            flow["decision_time"] = pd.to_datetime(flow["decision_time"], utc=True).astype(
                "datetime64[ns, UTC]"
            )
            if flow["decision_time"].duplicated().any():
                raise ValueError(f"Duplicate 5m flow decisions: {path}")
            cache[pair] = flow.sort_values("decision_time").reset_index(drop=True)
        return cache[pair].copy()

    def _merge_causal_cross_venue(self, dataframe: DataFrame, pair: str) -> DataFrame:
        left = dataframe.copy()
        left["date"] = pd.to_datetime(left["date"], utc=True).astype(
            "datetime64[ns, UTC]"
        )
        left["decision_time"] = left["date"] + pd.Timedelta(minutes=self.primary_minutes)
        left["__row_order"] = np.arange(len(left))

        sidecar = self._load_sidecar(pair).rename(
            columns={
                "date": "cross_venue_date",
                "decision_time": "cross_venue_decision_time",
            }
        )
        sidecar["cross_venue_decision_time"] = pd.to_datetime(
            sidecar["cross_venue_decision_time"], utc=True
        ).astype("datetime64[ns, UTC]")
        merged = pd.merge_asof(
            left.sort_values("decision_time"),
            sidecar.sort_values("cross_venue_decision_time"),
            left_on="decision_time",
            right_on="cross_venue_decision_time",
            direction="backward",
            allow_exact_matches=True,
        )

        flow = self._load_five_minute_flow(pair).rename(
            columns={
                "decision_time": "flow_5m_decision_time",
                **{column: f"{column}__flow5m" for column in self._flow_columns},
            }
        )
        flow["flow_5m_decision_time"] = pd.to_datetime(
            flow["flow_5m_decision_time"], utc=True
        ).astype("datetime64[ns, UTC]")
        merged = pd.merge_asof(
            merged.sort_values("decision_time"),
            flow.sort_values("flow_5m_decision_time"),
            left_on="decision_time",
            right_on="flow_5m_decision_time",
            direction="backward",
            allow_exact_matches=True,
        )
        for column in self._flow_columns:
            flow_column = f"{column}__flow5m"
            if flow_column in merged:
                merged[column] = merged[flow_column]

        exact_flow = merged["flow_5m_decision_time"].eq(merged["decision_time"])
        flow_valid = merged.get(
            "bin_three_5m_valid", pd.Series(False, index=merged.index)
        ).fillna(False)
        cross_valid = merged.get(
            "cross_data_valid", pd.Series(False, index=merged.index)
        ).fillna(False)
        merged["cross_data_valid"] = cross_valid & flow_valid & exact_flow
        helper_columns = [
            "__row_order",
            *[f"{column}__flow5m" for column in self._flow_columns],
        ]
        return (
            merged.sort_values("__row_order")
            .drop(columns=[column for column in helper_columns if column in merged])
            .reset_index(drop=True)
        )

    def _populate_adaptive_price_indicators(
        self, dataframe: DataFrame, metadata: dict
    ) -> DataFrame:
        windows = self.adaptive_windows
        dataframe = dataframe.copy()
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

        dataframe["atr14"] = true_range.ewm(
            alpha=1 / windows["atr"], adjust=False
        ).mean()
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=windows["ema"])
        dataframe["donchian_high_48"] = (
            dataframe["high"].rolling(windows["donchian"]).max().shift(1)
        )
        dataframe["donchian_low_48"] = (
            dataframe["low"].rolling(windows["donchian"]).min().shift(1)
        )
        dataframe["close_location"] = (
            (2 * dataframe["close"] - dataframe["high"] - dataframe["low"])
            / candle_range
        ).clip(-1, 1)
        dataframe["body_atr"] = (
            (dataframe["close"] - dataframe["open"]).abs() / dataframe["atr14"]
        )
        volume_median = (
            dataframe["volume"].rolling(windows["relative_volume"]).median().replace(0, np.nan)
        )
        dataframe["relative_volume"] = dataframe["volume"] / volume_median

        typical_price = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3
        rolling_volume = (
            dataframe["volume"].rolling(windows["vwap"]).sum().replace(0, np.nan)
        )
        dataframe["rolling_vwap_24h"] = (
            (typical_price * dataframe["volume"]).rolling(windows["vwap"]).sum()
            / rolling_volume
        )
        signed_volume = dataframe["volume"] * dataframe["close_location"]
        dataframe["flow_imbalance_8"] = (
            signed_volume.rolling(windows["flow_fast"]).sum()
            / dataframe["volume"].rolling(windows["flow_fast"]).sum().replace(0, np.nan)
        )
        dataframe["flow_imbalance_24"] = (
            signed_volume.rolling(windows["flow_slow"]).sum()
            / dataframe["volume"].rolling(windows["flow_slow"]).sum().replace(0, np.nan)
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
            if self.timeframe == "1h":
                one_hour_source = dataframe
            else:
                one_hour_source = data_provider.get_pair_dataframe(
                    pair=metadata["pair"], timeframe="1h"
                )
            one_hour = self._populate_1h_indicators(one_hour_source)
            dataframe = self._merge_closed_informative(
                dataframe, one_hour, informative_timeframe="1h"
            )
            four_hour = self._populate_4h_indicators(
                data_provider.get_pair_dataframe(pair=metadata["pair"], timeframe="4h")
            )
            dataframe = self._merge_closed_informative(
                dataframe, four_hour, informative_timeframe="4h"
            )
        return dataframe

    def _populate_cross_features(self, dataframe: DataFrame) -> DataFrame:
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
        dataframe["fomc_event_high"] = dataframe["high"].where(fomc_event).ffill(
            limit=self._bars(90, self.primary_minutes)
        )
        dataframe["fomc_event_low"] = dataframe["low"].where(fomc_event).ffill(
            limit=self._bars(90, self.primary_minutes)
        )
        dataframe["cpi_event_high"] = dataframe["high"].where(cpi_event).ffill(
            limit=self._bars(60, self.primary_minutes)
        )
        dataframe["cpi_event_low"] = dataframe["low"].where(cpi_event).ffill(
            limit=self._bars(60, self.primary_minutes)
        )
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self._populate_adaptive_price_indicators(dataframe, metadata)
        dataframe = self._merge_causal_cross_venue(dataframe, metadata["pair"])
        dataframe = self._populate_cross_features(dataframe)
        dataframe = self._derive_capital_features(dataframe)
        return self._derive_event_features(dataframe)

    def _directional_features(
        self, dataframe: DataFrame
    ) -> tuple[dict[str, pd.Series], dict[str, pd.Series]]:
        long, short = super()._directional_features(dataframe)
        if self.confirmation_mode in {"signed_fresh", "signed_fresh_oi"}:
            long["fresh"] = long["fresh"] & long["current_taker"]
            short["fresh"] = short["fresh"] & short["current_taker"]
        if self.confirmation_mode == "signed_fresh_oi":
            long["fresh"] = long["fresh"] & long["oi_add"]
            short["fresh"] = short["fresh"] & short["oi_add"]
        return long, short

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
        return min(self.target_leverage, max_leverage)


class PriceFlowE10Tf5mLev1Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "5m"
    target_leverage = 1.0


class PriceFlowE10Tf5mLev2Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "5m"
    target_leverage = 2.0


class PriceFlowE10Tf5mLev3Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "5m"
    target_leverage = 3.0


class PriceFlowE10Tf5mLev5Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "5m"
    target_leverage = 5.0


class PriceFlowE10Tf5mLev10Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "5m"
    target_leverage = 10.0


class PriceFlowE10Tf15mLev1Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "15m"
    target_leverage = 1.0


class PriceFlowE10Tf15mLev2Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "15m"
    target_leverage = 2.0


class PriceFlowE10Tf15mLev3Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "15m"
    target_leverage = 3.0


class PriceFlowE10Tf15mLev5Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "15m"
    target_leverage = 5.0


class PriceFlowE10Tf15mLev10Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "15m"
    target_leverage = 10.0


class PriceFlowE10Tf30mLev1Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "30m"
    target_leverage = 1.0


class PriceFlowE10Tf30mLev2Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "30m"
    target_leverage = 2.0


class PriceFlowE10Tf30mLev3Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "30m"
    target_leverage = 3.0


class PriceFlowE10Tf30mLev5Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "30m"
    target_leverage = 5.0


class PriceFlowE10Tf30mLev10Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "30m"
    target_leverage = 10.0


class PriceFlowE10Tf1hLev1Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "1h"
    target_leverage = 1.0


class PriceFlowE10Tf1hLev2Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "1h"
    target_leverage = 2.0


class PriceFlowE10Tf1hLev3Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "1h"
    target_leverage = 3.0


class PriceFlowE10Tf1hLev5Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "1h"
    target_leverage = 5.0


class PriceFlowE10Tf1hLev10Strategy(PriceFlowTimeframeLeverageResearchBase):
    timeframe = "1h"
    target_leverage = 10.0


# Freqtrade prefilters files using literal ``class <name>(`` source markers.
# The preregistered variants are generated below, so their markers remain literal.
# class PriceFlowE10Tf5mLev1SignedFreshStrategy(
# class PriceFlowE10Tf5mLev1SignedFreshOiStrategy(
# class PriceFlowE10Tf5mLev1PriceGeometryStrategy(
# class PriceFlowE10Tf5mLev2SignedFreshStrategy(
# class PriceFlowE10Tf5mLev2SignedFreshOiStrategy(
# class PriceFlowE10Tf5mLev2PriceGeometryStrategy(
# class PriceFlowE10Tf5mLev3SignedFreshStrategy(
# class PriceFlowE10Tf5mLev3SignedFreshOiStrategy(
# class PriceFlowE10Tf5mLev3PriceGeometryStrategy(
# class PriceFlowE10Tf5mLev5SignedFreshStrategy(
# class PriceFlowE10Tf5mLev5SignedFreshOiStrategy(
# class PriceFlowE10Tf5mLev5PriceGeometryStrategy(
# class PriceFlowE10Tf5mLev10SignedFreshStrategy(
# class PriceFlowE10Tf5mLev10SignedFreshOiStrategy(
# class PriceFlowE10Tf5mLev10PriceGeometryStrategy(
# class PriceFlowE10Tf15mLev1SignedFreshStrategy(
# class PriceFlowE10Tf15mLev1SignedFreshOiStrategy(
# class PriceFlowE10Tf15mLev1PriceGeometryStrategy(
# class PriceFlowE10Tf15mLev2SignedFreshStrategy(
# class PriceFlowE10Tf15mLev2SignedFreshOiStrategy(
# class PriceFlowE10Tf15mLev2PriceGeometryStrategy(
# class PriceFlowE10Tf15mLev3SignedFreshStrategy(
# class PriceFlowE10Tf15mLev3SignedFreshOiStrategy(
# class PriceFlowE10Tf15mLev3PriceGeometryStrategy(
# class PriceFlowE10Tf15mLev5SignedFreshStrategy(
# class PriceFlowE10Tf15mLev5SignedFreshOiStrategy(
# class PriceFlowE10Tf15mLev5PriceGeometryStrategy(
# class PriceFlowE10Tf15mLev10SignedFreshStrategy(
# class PriceFlowE10Tf15mLev10SignedFreshOiStrategy(
# class PriceFlowE10Tf15mLev10PriceGeometryStrategy(
# class PriceFlowE10Tf30mLev1SignedFreshStrategy(
# class PriceFlowE10Tf30mLev1SignedFreshOiStrategy(
# class PriceFlowE10Tf30mLev1PriceGeometryStrategy(
# class PriceFlowE10Tf30mLev2SignedFreshStrategy(
# class PriceFlowE10Tf30mLev2SignedFreshOiStrategy(
# class PriceFlowE10Tf30mLev2PriceGeometryStrategy(
# class PriceFlowE10Tf30mLev3SignedFreshStrategy(
# class PriceFlowE10Tf30mLev3SignedFreshOiStrategy(
# class PriceFlowE10Tf30mLev3PriceGeometryStrategy(
# class PriceFlowE10Tf30mLev5SignedFreshStrategy(
# class PriceFlowE10Tf30mLev5SignedFreshOiStrategy(
# class PriceFlowE10Tf30mLev5PriceGeometryStrategy(
# class PriceFlowE10Tf30mLev10SignedFreshStrategy(
# class PriceFlowE10Tf30mLev10SignedFreshOiStrategy(
# class PriceFlowE10Tf30mLev10PriceGeometryStrategy(
# class PriceFlowE10Tf1hLev1SignedFreshStrategy(
# class PriceFlowE10Tf1hLev1SignedFreshOiStrategy(
# class PriceFlowE10Tf1hLev1PriceGeometryStrategy(
# class PriceFlowE10Tf1hLev2SignedFreshStrategy(
# class PriceFlowE10Tf1hLev2SignedFreshOiStrategy(
# class PriceFlowE10Tf1hLev2PriceGeometryStrategy(
# class PriceFlowE10Tf1hLev3SignedFreshStrategy(
# class PriceFlowE10Tf1hLev3SignedFreshOiStrategy(
# class PriceFlowE10Tf1hLev3PriceGeometryStrategy(
# class PriceFlowE10Tf1hLev5SignedFreshStrategy(
# class PriceFlowE10Tf1hLev5SignedFreshOiStrategy(
# class PriceFlowE10Tf1hLev5PriceGeometryStrategy(
# class PriceFlowE10Tf1hLev10SignedFreshStrategy(
# class PriceFlowE10Tf1hLev10SignedFreshOiStrategy(
# class PriceFlowE10Tf1hLev10PriceGeometryStrategy(


def _research_variant_class(
    name: str,
    base: type[PriceFlowTimeframeLeverageResearchBase],
    *,
    confirmation_mode: str = "original",
    preserve_price_geometry: bool = False,
) -> type[PriceFlowTimeframeLeverageResearchBase]:
    attributes: dict = {
        "confirmation_mode": confirmation_mode,
        "__module__": __name__,
    }
    if preserve_price_geometry:
        leverage = float(base.target_leverage)
        attributes["stoploss"] = round(-0.015 * leverage, 10)
        attributes["minimal_roi"] = {
            "0": round(0.03 * leverage, 10),
            "720": round(0.02 * leverage, 10),
            "1440": round(0.01 * leverage, 10),
        }
    return type(name, (base,), attributes)


for _timeframe in ("5m", "15m", "30m", "1h"):
    for _leverage in (1, 2, 3, 5, 10):
        _prefix = f"PriceFlowE10Tf{_timeframe}Lev{_leverage}"
        _base = globals()[f"{_prefix}Strategy"]
        globals()[f"{_prefix}SignedFreshStrategy"] = _research_variant_class(
            f"{_prefix}SignedFreshStrategy",
            _base,
            confirmation_mode="signed_fresh",
        )
        globals()[f"{_prefix}SignedFreshOiStrategy"] = _research_variant_class(
            f"{_prefix}SignedFreshOiStrategy",
            _base,
            confirmation_mode="signed_fresh_oi",
        )
        globals()[f"{_prefix}PriceGeometryStrategy"] = _research_variant_class(
            f"{_prefix}PriceGeometryStrategy",
            _base,
            preserve_price_geometry=True,
        )

del _base, _leverage, _prefix, _timeframe
