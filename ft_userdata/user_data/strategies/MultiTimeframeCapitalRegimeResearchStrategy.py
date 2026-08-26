from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame


class MultiTimeframeCapitalRegimeResearchStrategy(IStrategy):
    """Fixed 1x candidates using closed higher-timeframe direction and side data.

    The strategy deliberately abstains when 4h and 1d direction disagree or when the
    mark/basis observation is stale.  It has no range leg: a range state is flat.
    """

    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 1_200

    max_open_trades = 1
    position_adjustment_enable = False
    minimal_roi: ClassVar[dict[str, float]] = {"0": 0.03}
    stoploss = -0.012
    trailing_stop = False
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

    variant_code: ClassVar[str] = "R1-S1-P0"
    regime_fast_4h: ClassVar[int] = 20
    regime_slow_4h: ClassVar[int] = 50
    regime_fast_1d: ClassVar[int] = 20
    regime_slow_1d: ClassVar[int] = 50
    regime_adx_threshold_4h: ClassVar[float] = 15.0
    regime_adx_threshold_1d: ClassVar[float] = 15.0
    regime_slope_threshold_4h: ClassVar[float] = 0.0
    regime_slope_threshold_1d: ClassVar[float] = 0.0

    signal_code: ClassVar[str] = "S1"
    entry_style: ClassVar[str] = "breakout"
    channel_length: ClassVar[int] = 20
    long_close_location_min: ClassVar[float] = 0.55
    short_close_location_min: ClassVar[float] = 0.65
    long_body_min: ClassVar[float] = 0.30
    short_body_min: ClassVar[float] = 0.30
    atrp_min: ClassVar[float] = 0.0015
    atrp_max: ClassVar[float] = 0.08
    expansion_multiple: ClassVar[float] = 1.0
    retest_bars: ClassVar[int] = 0
    relative_volume_min: ClassVar[float] = 0.8
    long_momentum_min: ClassVar[float] = -0.005
    short_momentum_max: ClassVar[float] = 0.005
    stale_loss_hours: ClassVar[int] = 48
    max_hold_hours: ClassVar[int] = 96

    participation_code: ClassVar[str] = "P0"
    long_enabled: ClassVar[bool] = True
    short_enabled: ClassVar[bool] = True
    require_funding: ClassVar[bool] = False
    funding_age_cap_hours: ClassVar[float] = 8.0
    mark_age_cap_hours: ClassVar[float] = 2.0
    funding_long_max: ClassVar[float] = 0.0002
    funding_short_min: ClassVar[float] = -0.0002
    basis_abs_max: ClassVar[float] = 0.004
    basis_long_min: ClassVar[float] = -0.004
    basis_short_max: ClassVar[float] = 0.004

    plot_config: ClassVar[dict] = {
        "main_plot": {
            "donchian_high": {"color": "#36B37E"},
            "donchian_low": {"color": "#FF5630"},
            "regime_ema_fast_4h": {"color": "#4C9AFF"},
            "regime_ema_slow_1d": {"color": "#6554C0"},
        },
        "subplots": {
            "Regime": {
                "regime_dir_4h": {"color": "#4C9AFF"},
                "regime_dir_1d": {"color": "#6554C0"},
            },
            "Capital context": {
                "basis_1h": {"color": "#00A3BF"},
                "funding_rate_1h": {"color": "#FFAB00"},
                "relative_volume": {"color": "#6554C0"},
            },
        },
    }

    def informative_pairs(self) -> list[tuple[str, str] | tuple[str, str, str]]:
        data_provider = getattr(self, "dp", None)
        pairs = (
            data_provider.current_whitelist()
            if data_provider
            else self.config.get("exchange", {}).get("pair_whitelist", [])
        )
        result: list[tuple[str, str] | tuple[str, str, str]] = []
        for pair in pairs:
            result.extend(
                [
                    (pair, "4h"),
                    (pair, "1d"),
                    (pair, "1h", "mark"),
                    (pair, "1h", "funding_rate"),
                ]
            )
        return result

    @staticmethod
    def _regime_frame(dataframe: DataFrame, fast: int, slow: int, slope_floor: float) -> DataFrame:
        frame = dataframe.copy()
        ema_fast = ta.EMA(frame, timeperiod=fast)
        ema_slow = ta.EMA(frame, timeperiod=slow)
        adx = ta.ADX(frame, timeperiod=14)
        slope = ema_fast / ema_fast.shift(6) - 1.0
        direction = pd.Series(0.0, index=frame.index, dtype="float64")
        direction.loc[
            (frame["close"] > ema_slow)
            & (ema_fast > ema_slow)
            & (slope >= slope_floor)
        ] = 1.0
        direction.loc[
            (frame["close"] < ema_slow)
            & (ema_fast < ema_slow)
            & (slope <= -slope_floor)
        ] = -1.0
        return DataFrame(
            {
                "date": frame["date"],
                "regime_dir": direction,
                "regime_adx": adx,
                "regime_ema_fast": ema_fast,
                "regime_ema_slow": ema_slow,
                "regime_slope": slope,
            },
            index=frame.index,
        )

    @staticmethod
    def _mark_frame(dataframe: DataFrame) -> DataFrame:
        frame = dataframe.copy()
        return DataFrame({"date": frame["date"], "mark_close": pd.to_numeric(frame["close"], errors="coerce")})

    @staticmethod
    def _funding_frame(dataframe: DataFrame) -> DataFrame:
        frame = dataframe.copy()
        source = next(
            (
                name
                for name in ("funding_rate", "fundingRate", "rate", "open", "close")
                if name in frame
            ),
            None,
        )
        values = pd.to_numeric(frame[source], errors="coerce") if source else np.nan
        return DataFrame({"date": frame["date"], "funding_rate": values})

    @staticmethod
    def _futures_frame(dataframe: DataFrame) -> DataFrame:
        frame = dataframe.copy()
        return DataFrame({"date": frame["date"], "futures_close": pd.to_numeric(frame["close"], errors="coerce")})

    @staticmethod
    def _rename_side_columns(dataframe: DataFrame, suffix: str, source_label: str, value_label: str) -> DataFrame:
        return dataframe.rename(
            columns={
                f"date_{suffix}": f"{source_label}_source_date_1h",
                f"{value_label}_{suffix}": f"{value_label}_1h",
            }
        )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        result = dataframe.copy()
        result["donchian_high"] = result["high"].rolling(self.channel_length).max().shift(1)
        result["donchian_low"] = result["low"].rolling(self.channel_length).min().shift(1)
        result["atr14"] = ta.ATR(result, timeperiod=14)
        result["atrp"] = result["atr14"] / result["close"]
        result["rsi14"] = ta.RSI(result, timeperiod=14)
        result["momentum_24h"] = result["close"] / result["close"].shift(96) - 1.0
        volume_reference = result["volume"].rolling(96).median().shift(1)
        result["relative_volume"] = result["volume"] / volume_reference.replace(0, np.nan)
        candle_range = (result["high"] - result["low"]).replace(0, np.nan)
        result["close_location"] = (
            (2.0 * result["close"] - result["high"] - result["low"]) / candle_range
        ).clip(-1.0, 1.0)
        result["body_fraction"] = (result["close"] - result["open"]).abs() / candle_range
        result["atrp_reference"] = result["atrp"].rolling(96).median().shift(1)

        data_provider = getattr(self, "dp", None)
        if data_provider:
            pair = metadata["pair"]
            for timeframe, fast, slow, slope_floor in (
                ("4h", self.regime_fast_4h, self.regime_slow_4h, self.regime_slope_threshold_4h),
                ("1d", self.regime_fast_1d, self.regime_slow_1d, self.regime_slope_threshold_1d),
            ):
                informative = data_provider.get_pair_dataframe(pair=pair, timeframe=timeframe)
                if informative.empty:
                    for column in (
                        "regime_dir",
                        "regime_adx",
                        "regime_ema_fast",
                        "regime_ema_slow",
                        "regime_slope",
                    ):
                        result[f"{column}_{timeframe}"] = np.nan
                    continue
                result = merge_informative_pair(
                    result,
                    self._regime_frame(informative, fast, slow, slope_floor),
                    self.timeframe,
                    timeframe,
                    ffill=True,
                )

            mark = data_provider.get_pair_dataframe(pair=pair, timeframe="1h", candle_type="mark")
            futures = data_provider.get_pair_dataframe(pair=pair, timeframe="1h")
            funding = data_provider.get_pair_dataframe(
                pair=pair, timeframe="1h", candle_type="funding_rate"
            )
            if mark.empty or futures.empty:
                result["mark_source_date_1h"] = pd.NaT
                result["mark_close_1h"] = np.nan
                result["futures_source_date_1h"] = pd.NaT
                result["futures_close_1h"] = np.nan
            else:
                result = merge_informative_pair(
                    result,
                    self._mark_frame(mark),
                    self.timeframe,
                    "1h",
                    ffill=True,
                    append_timeframe=False,
                    suffix="mark_1h",
                )
                result = self._rename_side_columns(result, "mark_1h", "mark", "mark_close")
                result = merge_informative_pair(
                    result,
                    self._futures_frame(futures),
                    self.timeframe,
                    "1h",
                    ffill=True,
                    append_timeframe=False,
                    suffix="futures_1h",
                )
                result = self._rename_side_columns(
                    result, "futures_1h", "futures", "futures_close"
                )
            if funding.empty:
                result["funding_source_date_1h"] = pd.NaT
                result["funding_rate_1h"] = np.nan
            else:
                result = merge_informative_pair(
                    result,
                    self._funding_frame(funding),
                    self.timeframe,
                    "1h",
                    ffill=True,
                    append_timeframe=False,
                    suffix="funding_1h",
                )
                result = self._rename_side_columns(
                    result, "funding_1h", "funding", "funding_rate"
                )
        else:
            for timeframe in ("4h", "1d"):
                for column in (
                    "regime_dir",
                    "regime_adx",
                    "regime_ema_fast",
                    "regime_ema_slow",
                    "regime_slope",
                ):
                    result[f"{column}_{timeframe}"] = np.nan
            for column in (
                "mark_source_date_1h",
                "futures_source_date_1h",
                "funding_source_date_1h",
            ):
                result[column] = pd.NaT
            result["mark_close_1h"] = np.nan
            result["futures_close_1h"] = np.nan
            result["funding_rate_1h"] = np.nan

        result["mark_age_hours"] = (
            pd.to_datetime(result["date"], utc=True) - pd.to_datetime(result["mark_source_date_1h"], utc=True)
        ).dt.total_seconds() / 3600.0
        result["funding_age_hours"] = (
            pd.to_datetime(result["date"], utc=True)
            - pd.to_datetime(result["funding_source_date_1h"], utc=True)
        ).dt.total_seconds() / 3600.0
        result["mark_observed"] = (
            result["mark_close_1h"].notna()
            & result["futures_close_1h"].notna()
            & result["mark_age_hours"].between(0, self.mark_age_cap_hours, inclusive="both")
        )
        result["funding_observed"] = (
            result["funding_rate_1h"].notna()
            & result["funding_age_hours"].between(0, self.funding_age_cap_hours, inclusive="both")
        )
        result["basis_1h"] = result["mark_close_1h"] / result["futures_close_1h"] - 1.0
        result["basis_observed"] = result["mark_observed"] & result["basis_1h"].notna()

        regime_available = result[
            ["regime_dir_4h", "regime_adx_4h", "regime_dir_1d", "regime_adx_1d"]
        ].notna().all(axis=1)
        strong_up = (
            (result["regime_dir_4h"] == 1)
            & (result["regime_dir_1d"] == 1)
            & (result["regime_adx_4h"] >= self.regime_adx_threshold_4h)
            & (result["regime_adx_1d"] >= self.regime_adx_threshold_1d)
        )
        strong_down = (
            (result["regime_dir_4h"] == -1)
            & (result["regime_dir_1d"] == -1)
            & (result["regime_adx_4h"] >= self.regime_adx_threshold_4h)
            & (result["regime_adx_1d"] >= self.regime_adx_threshold_1d)
        )
        result["regime_state"] = "neutral"
        result.loc[strong_up, "regime_state"] = "trend_up"
        result.loc[strong_down, "regime_state"] = "trend_down"
        result.loc[regime_available & ~(strong_up | strong_down), "regime_state"] = "range"
        return result

    def _entry_shapes(self, dataframe: DataFrame) -> tuple[pd.Series, pd.Series]:
        long_breakout = (
            (dataframe["close"] > dataframe["donchian_high"])
            & (dataframe["close"].shift(1) <= dataframe["donchian_high"].shift(1))
        )
        short_breakout = (
            (dataframe["close"] < dataframe["donchian_low"])
            & (dataframe["close"].shift(1) >= dataframe["donchian_low"].shift(1))
        )
        if self.entry_style == "retest":
            prior_long = (dataframe["close"] > dataframe["donchian_high"]).astype(int)
            prior_short = (dataframe["close"] < dataframe["donchian_low"]).astype(int)
            long_recent = prior_long.shift(1).rolling(self.retest_bars, min_periods=1).max().fillna(0) > 0
            short_recent = prior_short.shift(1).rolling(self.retest_bars, min_periods=1).max().fillna(0) > 0
            long_breakout = long_recent & (dataframe["low"] <= dataframe["donchian_high"])
            long_breakout &= dataframe["close"] > dataframe["donchian_high"]
            short_breakout = short_recent & (dataframe["high"] >= dataframe["donchian_low"])
            short_breakout &= dataframe["close"] < dataframe["donchian_low"]
        elif self.entry_style == "expansion":
            expansion = dataframe["atrp"] >= dataframe["atrp_reference"] * self.expansion_multiple
            long_breakout &= expansion
            short_breakout &= expansion
        elif self.entry_style == "acceptance":
            long_breakout &= dataframe["close"] > dataframe["open"]
            short_breakout &= dataframe["close"] < dataframe["open"]
        return long_breakout.fillna(False), short_breakout.fillna(False)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = None
        long_shape, short_shape = self._entry_shapes(dataframe)
        candle_range = (dataframe["high"] - dataframe["low"]).replace(0, np.nan)
        bullish_quality = (
            (dataframe["close_location"] >= self.long_close_location_min)
            & (dataframe["body_fraction"] >= self.long_body_min)
            & (dataframe["close"] > dataframe["open"])
        )
        bearish_quality = (
            (dataframe["close_location"] <= -self.short_close_location_min)
            & (dataframe["body_fraction"] >= self.short_body_min)
            & (dataframe["close"] < dataframe["open"])
        )
        del candle_range
        volatility_ok = dataframe["atrp"].between(self.atrp_min, self.atrp_max, inclusive="both")
        participation_ok = dataframe["relative_volume"] >= self.relative_volume_min
        basis = dataframe["basis_1h"]
        basis_ok = (
            dataframe["basis_observed"]
            & basis.abs().le(self.basis_abs_max)
        )
        long_basis_ok = basis_ok & basis.ge(self.basis_long_min)
        short_basis_ok = basis_ok & basis.le(self.basis_short_max)
        if self.require_funding:
            funding = dataframe["funding_rate_1h"]
            funding_available = dataframe["funding_observed"]
            long_funding_ok = funding_available & funding.le(self.funding_long_max)
            short_funding_ok = funding_available & funding.ge(self.funding_short_min)
        else:
            long_funding_ok = pd.Series(True, index=dataframe.index)
            short_funding_ok = pd.Series(True, index=dataframe.index)
        long_momentum_ok = dataframe["momentum_24h"] >= self.long_momentum_min
        short_momentum_ok = dataframe["momentum_24h"] <= self.short_momentum_max
        long_signal = (
            self.long_enabled
            & (dataframe["regime_state"] == "trend_up")
            & long_shape
            & bullish_quality
            & long_momentum_ok
            & volatility_ok
            & participation_ok
            & long_basis_ok
            & long_funding_ok
        )
        short_signal = (
            self.short_enabled
            & (dataframe["regime_state"] == "trend_down")
            & short_shape
            & bearish_quality
            & short_momentum_ok
            & volatility_ok
            & participation_ok
            & short_basis_ok
            & short_funding_ok
        )
        dataframe.loc[long_signal, ["enter_long", "enter_tag"]] = (
            1,
            f"{self.variant_code}_long",
        )
        dataframe.loc[short_signal, ["enter_short", "enter_tag"]] = (
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
        age = current_time - trade.open_date_utc
        if age >= timedelta(hours=self.stale_loss_hours) and current_profit <= 0:
            return f"stale_loss_{self.stale_loss_hours}h"
        if age >= timedelta(hours=self.max_hold_hours):
            return f"max_hold_{self.max_hold_hours}h"
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
        del pair, current_time, current_rate, proposed_leverage, max_leverage, entry_tag, side, kwargs
        return 1.0


REGIME_PROFILES: tuple[dict[str, object], ...] = (
    {
        "code": "R1",
        "fast_4h": 20,
        "slow_4h": 50,
        "fast_1d": 20,
        "slow_1d": 50,
        "adx_4h": 15.0,
        "adx_1d": 15.0,
        "slope_4h": 0.0,
        "slope_1d": 0.0,
    },
    {
        "code": "R2",
        "fast_4h": 30,
        "slow_4h": 90,
        "fast_1d": 20,
        "slow_1d": 50,
        "adx_4h": 18.0,
        "adx_1d": 18.0,
        "slope_4h": 0.0,
        "slope_1d": 0.0,
    },
    {
        "code": "R3",
        "fast_4h": 20,
        "slow_4h": 80,
        "fast_1d": 50,
        "slow_1d": 200,
        "adx_4h": 20.0,
        "adx_1d": 20.0,
        "slope_4h": 0.0005,
        "slope_1d": 0.0005,
    },
    {
        "code": "R4",
        "fast_4h": 10,
        "slow_4h": 40,
        "fast_1d": 10,
        "slow_1d": 30,
        "adx_4h": 22.0,
        "adx_1d": 22.0,
        "slope_4h": 0.0,
        "slope_1d": 0.0,
    },
    {
        "code": "R5",
        "fast_4h": 50,
        "slow_4h": 200,
        "fast_1d": 20,
        "slow_1d": 50,
        "adx_4h": 12.0,
        "adx_1d": 12.0,
        "slope_4h": 0.0,
        "slope_1d": 0.0,
    },
)

SIGNAL_PROFILES: tuple[dict[str, object], ...] = (
    {
        "code": "S1",
        "style": "breakout",
        "channel": 20,
        "long_clv": 0.55,
        "short_clv": 0.65,
        "long_body": 0.30,
        "short_body": 0.30,
        "atrp": 0.0015,
        "rv": 0.80,
        "long_momentum": -0.005,
        "short_momentum": 0.005,
        "stale": 48,
        "hold": 96,
        "expansion": 1.0,
        "retest": 0,
    },
    {
        "code": "S2",
        "style": "breakout",
        "channel": 40,
        "long_clv": 0.60,
        "short_clv": 0.60,
        "long_body": 0.35,
        "short_body": 0.30,
        "atrp": 0.0020,
        "rv": 1.00,
        "long_momentum": 0.0,
        "short_momentum": 0.0,
        "stale": 48,
        "hold": 96,
        "expansion": 1.0,
        "retest": 0,
    },
    {
        "code": "S3",
        "style": "breakout",
        "channel": 64,
        "long_clv": 0.55,
        "short_clv": 0.55,
        "long_body": 0.30,
        "short_body": 0.30,
        "atrp": 0.0025,
        "rv": 1.00,
        "long_momentum": 0.005,
        "short_momentum": -0.005,
        "stale": 72,
        "hold": 120,
        "expansion": 1.0,
        "retest": 0,
    },
    {
        "code": "S4",
        "style": "retest",
        "channel": 40,
        "long_clv": 0.70,
        "short_clv": 0.55,
        "long_body": 0.40,
        "short_body": 0.30,
        "atrp": 0.0030,
        "rv": 1.20,
        "long_momentum": 0.0,
        "short_momentum": 0.0,
        "stale": 36,
        "hold": 72,
        "expansion": 1.0,
        "retest": 4,
    },
    {
        "code": "S5",
        "style": "expansion",
        "channel": 20,
        "long_clv": 0.65,
        "short_clv": 0.45,
        "long_body": 0.35,
        "short_body": 0.25,
        "atrp": 0.0010,
        "rv": 0.80,
        "long_momentum": 0.010,
        "short_momentum": -0.010,
        "stale": 24,
        "hold": 72,
        "expansion": 1.20,
        "retest": 0,
    },
)

PARTICIPATION_PROFILES: tuple[dict[str, object], ...] = (
    {
        "code": "P0",
        "funding": False,
        "funding_long": 0.0002,
        "funding_short": -0.0002,
        "basis_abs": 0.004,
        "basis_long": -0.004,
        "basis_short": 0.004,
    },
    {
        "code": "P1",
        "funding": True,
        "funding_long": 0.0002,
        "funding_short": -0.0002,
        "basis_abs": 0.002,
        "basis_long": -0.001,
        "basis_short": 0.001,
    },
)

VARIANT_SPECS: tuple[dict[str, object], ...] = tuple(
    {
        **regime,
        **signal,
        **participation,
        "code": f"{regime['code']}-{signal['code']}-{participation['code']}",
        "name": f"MtfCapital{regime['code']}{signal['code']}{participation['code']}Strategy",
        "regime": regime["code"],
        "signal": signal["code"],
        "participation": participation["code"],
    }
    for regime in REGIME_PROFILES
    for signal in SIGNAL_PROFILES
    for participation in PARTICIPATION_PROFILES
)


class MtfCapitalR1S1P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR1S1P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR1S2P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR1S2P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR1S3P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR1S3P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR1S4P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR1S4P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR1S5P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR1S5P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR2S1P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR2S1P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR2S2P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR2S2P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR2S3P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR2S3P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR2S4P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR2S4P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR2S5P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR2S5P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR3S1P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR3S1P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR3S2P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR3S2P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR3S3P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR3S3P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR3S4P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR3S4P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR3S5P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR3S5P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR4S1P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR4S1P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR4S2P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR4S2P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR4S3P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR4S3P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR4S4P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR4S4P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR4S5P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR4S5P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR5S1P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR5S1P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR5S2P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR5S2P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR5S3P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR5S3P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR5S4P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR5S4P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR5S5P0Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


class MtfCapitalR5S5P1Strategy(MultiTimeframeCapitalRegimeResearchStrategy):
    pass


def _apply_variant(
    strategy_class: type[MultiTimeframeCapitalRegimeResearchStrategy], spec: dict[str, object]
) -> None:
    attributes = {
        "variant_code": spec["code"],
        "regime_fast_4h": spec["fast_4h"],
        "regime_slow_4h": spec["slow_4h"],
        "regime_fast_1d": spec["fast_1d"],
        "regime_slow_1d": spec["slow_1d"],
        "regime_adx_threshold_4h": spec["adx_4h"],
        "regime_adx_threshold_1d": spec["adx_1d"],
        "regime_slope_threshold_4h": spec["slope_4h"],
        "regime_slope_threshold_1d": spec["slope_1d"],
        "signal_code": spec["signal"],
        "entry_style": spec["style"],
        "channel_length": spec["channel"],
        "long_close_location_min": spec["long_clv"],
        "short_close_location_min": spec["short_clv"],
        "long_body_min": spec["long_body"],
        "short_body_min": spec["short_body"],
        "atrp_min": spec["atrp"],
        "relative_volume_min": spec["rv"],
        "long_momentum_min": spec["long_momentum"],
        "short_momentum_max": spec["short_momentum"],
        "stale_loss_hours": spec["stale"],
        "max_hold_hours": spec["hold"],
        "expansion_multiple": spec["expansion"],
        "retest_bars": spec["retest"],
        "participation_code": spec["participation"],
        "require_funding": spec["funding"],
        "funding_long_max": spec["funding_long"],
        "funding_short_min": spec["funding_short"],
        "basis_abs_max": spec["basis_abs"],
        "basis_long_min": spec["basis_long"],
        "basis_short_max": spec["basis_short"],
    }
    for name, value in attributes.items():
        setattr(strategy_class, name, value)


for _spec in VARIANT_SPECS:
    _apply_variant(globals()[str(_spec["name"])], _spec)
