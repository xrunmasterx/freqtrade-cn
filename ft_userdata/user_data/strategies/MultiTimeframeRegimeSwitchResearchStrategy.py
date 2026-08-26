from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np
import pandas as pd
from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_absolute
from pandas import DataFrame

from MultiTimeframeCapitalRegimeResearchStrategy import (
    MultiTimeframeCapitalRegimeResearchStrategy,
)


class MultiTimeframeRegimeSwitchResearchStrategy(
    MultiTimeframeCapitalRegimeResearchStrategy
):
    """Causal regime switch study with a range reversal and trend continuation leg."""

    minimal_roi: ClassVar[dict[str, float]] = {"0": 100.0}
    stoploss = -0.99
    use_custom_stoploss = True
    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    mode: ClassVar[str] = "range"
    range_adx_max: ClassVar[float] = 22.0
    range_deviation_atr: ClassVar[float] = 1.0
    range_long_rsi: ClassVar[float] = 35.0
    range_short_rsi: ClassVar[float] = 65.0
    range_long_enabled: ClassVar[bool] = True
    range_short_enabled: ClassVar[bool] = True
    trend_enabled: ClassVar[bool] = False
    trend_channel_length: ClassVar[int] = 20

    initial_stop: ClassVar[float] = 0.006
    target: ClassVar[float] = 0.024
    trail_activation: ClassVar[float] = 0.008
    profit_lock: ClassVar[float] = 0.001
    trail_distance: ClassVar[float] = 0.010
    max_hold_hours: ClassVar[int] = 72

    require_funding: ClassVar[bool] = False
    funding_long_max: ClassVar[float] = 0.0
    funding_short_min: ClassVar[float] = 0.0
    basis_abs_max: ClassVar[float] = 0.004
    basis_long_min: ClassVar[float] = -0.004
    basis_short_max: ClassVar[float] = 0.004

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        result = super().populate_indicators(dataframe, metadata)
        result["range_ema"] = result["close"].ewm(
            span=20, adjust=False, min_periods=20
        ).mean()
        true_range = pd.concat(
            [
                result["high"] - result["low"],
                (result["high"] - result["close"].shift()).abs(),
                (result["low"] - result["close"].shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        result["range_atr"] = true_range.ewm(
            alpha=1 / 14, adjust=False, min_periods=14
        ).mean()
        change = result["close"].diff()
        gains = change.clip(lower=0.0)
        losses = -change.clip(upper=0.0)
        rs = gains.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / losses.ewm(
            alpha=1 / 14, adjust=False, min_periods=14
        ).mean()
        result["range_rsi"] = 100.0 - 100.0 / (1.0 + rs)
        result["switch_channel_high"] = (
            result["high"].rolling(self.trend_channel_length).max().shift(1)
        )
        result["switch_channel_low"] = (
            result["low"].rolling(self.trend_channel_length).min().shift(1)
        )
        return result

    def _capital_gate(self, dataframe: DataFrame) -> tuple[pd.Series, pd.Series]:
        basis = pd.to_numeric(dataframe["basis_1h"], errors="coerce")
        basis_ok = dataframe["basis_observed"] & basis.abs().le(self.basis_abs_max)
        long_ok = basis_ok & basis.ge(self.basis_long_min)
        short_ok = basis_ok & basis.le(self.basis_short_max)
        if self.require_funding:
            funding = pd.to_numeric(dataframe["funding_rate_1h"], errors="coerce")
            observed = dataframe["funding_observed"]
            long_ok &= observed & funding.le(self.funding_long_max)
            short_ok &= observed & funding.ge(self.funding_short_min)
        return long_ok.fillna(False), short_ok.fillna(False)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = None

        long_capital, short_capital = self._capital_gate(dataframe)
        range_regime = (
            (dataframe["regime_state"] == "range")
            & dataframe["regime_adx_4h"].le(self.range_adx_max)
            & dataframe["regime_adx_1d"].le(self.range_adx_max)
        )
        trend_up = dataframe["regime_state"] == "trend_up"
        trend_down = dataframe["regime_state"] == "trend_down"
        range_long = (
            range_regime
            & self.range_long_enabled
            & (dataframe["close"] <= dataframe["range_ema"] - self.range_deviation_atr * dataframe["range_atr"])
            & (dataframe["range_rsi"] <= self.range_long_rsi)
            & long_capital
        )
        range_short = (
            range_regime
            & self.range_short_enabled
            & (dataframe["close"] >= dataframe["range_ema"] + self.range_deviation_atr * dataframe["range_atr"])
            & (dataframe["range_rsi"] >= self.range_short_rsi)
            & short_capital
        )
        long_breakout = (
            trend_up
            & (dataframe["close"] > dataframe["switch_channel_high"])
            & (dataframe["close"].shift(1) <= dataframe["switch_channel_high"].shift(1))
            & long_capital
        )
        short_breakout = (
            trend_down
            & (dataframe["close"] < dataframe["switch_channel_low"])
            & (dataframe["close"].shift(1) >= dataframe["switch_channel_low"].shift(1))
            & short_capital
        )
        if self.mode == "trend":
            long_signal = self.trend_enabled & long_breakout
            short_signal = self.trend_enabled & short_breakout
        elif self.mode == "switch":
            long_signal = range_long | (self.trend_enabled & long_breakout)
            short_signal = range_short | (self.trend_enabled & short_breakout)
        else:
            long_signal = range_long
            short_signal = range_short

        dataframe.loc[long_signal.fillna(False), ["enter_long", "enter_tag"]] = (
            1,
            f"{self.variant_code}_long",
        )
        dataframe.loc[short_signal.fillna(False), ["enter_short", "enter_tag"]] = (
            1,
            f"{self.variant_code}_short",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
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
        del pair, current_rate, kwargs
        if current_profit >= self.target:
            return f"target_{self.target:g}"
        if current_time >= trade.open_date_utc + timedelta(hours=self.max_hold_hours):
            return f"max_hold_{self.max_hold_hours}h"
        return None

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
        del pair, current_time, current_profit, after_fill, kwargs
        entry = float(trade.open_rate)
        if not np.isfinite(entry) or entry <= 0:
            return None
        if trade.is_short:
            stop_rate = entry * (1.0 + self.initial_stop)
            favorable = trade.min_rate if trade.min_rate is not None else entry
            favorable = float(favorable)
            favorable_gain = entry / favorable - 1.0 if favorable > 0 else 0.0
            if favorable_gain >= self.trail_activation:
                stop_rate = min(stop_rate, entry * (1.0 - self.profit_lock))
                if self.trail_distance > 0:
                    stop_rate = min(stop_rate, favorable * (1.0 + self.trail_distance))
            previous = trade.get_custom_data("switch_stop_rate")
            if previous is not None:
                stop_rate = min(stop_rate, float(previous))
        else:
            stop_rate = entry * (1.0 - self.initial_stop)
            favorable = trade.max_rate if trade.max_rate is not None else entry
            favorable = float(favorable)
            favorable_gain = favorable / entry - 1.0 if entry > 0 else 0.0
            if favorable_gain >= self.trail_activation:
                stop_rate = max(stop_rate, entry * (1.0 + self.profit_lock))
                if self.trail_distance > 0:
                    stop_rate = max(stop_rate, favorable * (1.0 - self.trail_distance))
            previous = trade.get_custom_data("switch_stop_rate")
            if previous is not None:
                stop_rate = max(stop_rate, float(previous))
        trade.set_custom_data("switch_stop_rate", stop_rate)
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
        del pair, current_time, current_rate, proposed_leverage, max_leverage, entry_tag, side, kwargs
        return 1.0


REGIME_PROFILES: tuple[dict[str, object], ...] = (
    {"code": "R1", "fast_4h": 20, "slow_4h": 50, "fast_1d": 20, "slow_1d": 50, "adx": 18.0, "mode": "range"},
    {"code": "R2", "fast_4h": 20, "slow_4h": 50, "fast_1d": 20, "slow_1d": 50, "adx": 22.0, "mode": "range"},
    {"code": "R3", "fast_4h": 20, "slow_4h": 50, "fast_1d": 20, "slow_1d": 50, "adx": 25.0, "mode": "range"},
    {"code": "R4", "fast_4h": 20, "slow_4h": 50, "fast_1d": 20, "slow_1d": 50, "adx": 18.0, "mode": "trend"},
    {"code": "R5", "fast_4h": 20, "slow_4h": 50, "fast_1d": 20, "slow_1d": 50, "adx": 22.0, "mode": "switch"},
)

SIGNAL_PROFILES: tuple[dict[str, object], ...] = (
    {"code": "S1", "deviation": 1.0, "long_rsi": 35.0, "short_rsi": 65.0, "long": True, "short": True, "trend": False, "stop": 0.006, "target": 0.024, "activation": 0.008, "lock": 0.001, "trail": 0.010, "hold": 72},
    {"code": "S2", "deviation": 1.5, "long_rsi": 35.0, "short_rsi": 65.0, "long": False, "short": True, "trend": False, "stop": 0.006, "target": 0.030, "activation": 0.008, "lock": 0.001, "trail": 0.010, "hold": 72},
    {"code": "S3", "deviation": 1.0, "long_rsi": 40.0, "short_rsi": 60.0, "long": False, "short": True, "trend": False, "stop": 0.006, "target": 0.024, "activation": 0.010, "lock": 0.002, "trail": 0.000, "hold": 48},
    {"code": "S4", "deviation": 0.0, "long_rsi": 50.0, "short_rsi": 50.0, "long": True, "short": True, "trend": True, "stop": 0.012, "target": 0.030, "activation": 0.010, "lock": 0.002, "trail": 0.008, "hold": 96},
    {"code": "S5", "deviation": 1.0, "long_rsi": 35.0, "short_rsi": 65.0, "long": True, "short": True, "trend": True, "stop": 0.006, "target": 0.024, "activation": 0.008, "lock": 0.001, "trail": 0.010, "hold": 72},
)

PARTICIPATION_PROFILES: tuple[dict[str, object], ...] = (
    {"code": "P0", "funding": False, "basis_abs": 0.004, "basis_long": -0.004, "basis_short": 0.004},
    {"code": "P1", "funding": True, "basis_abs": 0.002, "basis_long": 0.001, "basis_short": -0.001},
)

VARIANT_SPECS: tuple[dict[str, object], ...] = tuple(
    {
        **regime,
        **signal,
        **participation,
        "code": f"{regime['code']}-{signal['code']}-{participation['code']}",
        "name": f"MtfSwitch{regime['code']}{signal['code']}{participation['code']}Strategy",
    }
    for regime in REGIME_PROFILES
    for signal in SIGNAL_PROFILES
    for participation in PARTICIPATION_PROFILES
)


def _apply_variant(strategy_class: type[MultiTimeframeRegimeSwitchResearchStrategy], spec: dict[str, object]) -> None:
    attributes = {
        "variant_code": spec["code"],
        "regime_fast_4h": spec["fast_4h"],
        "regime_slow_4h": spec["slow_4h"],
        "regime_fast_1d": spec["fast_1d"],
        "regime_slow_1d": spec["slow_1d"],
        "regime_adx_threshold_4h": 15.0,
        "regime_adx_threshold_1d": 15.0,
        "mode": spec["mode"],
        "range_adx_max": spec["adx"],
        "range_deviation_atr": spec["deviation"],
        "range_long_rsi": spec["long_rsi"],
        "range_short_rsi": spec["short_rsi"],
        "range_long_enabled": spec["long"],
        "range_short_enabled": spec["short"],
        "trend_enabled": spec["trend"],
        "initial_stop": spec["stop"],
        "target": spec["target"],
        "trail_activation": spec["activation"],
        "profit_lock": spec["lock"],
        "trail_distance": spec["trail"],
        "max_hold_hours": spec["hold"],
        "require_funding": spec["funding"],
        "basis_abs_max": spec["basis_abs"],
        "basis_long_min": spec["basis_long"],
        "basis_short_max": spec["basis_short"],
        "funding_long_max": 0.0,
        "funding_short_min": 0.0,
    }
    for name, value in attributes.items():
        setattr(strategy_class, name, value)


for _spec in VARIANT_SPECS:
    _name = str(_spec["name"])
    globals()[_name] = type(_name, (MultiTimeframeRegimeSwitchResearchStrategy,), {})
    _apply_variant(globals()[_name], _spec)
