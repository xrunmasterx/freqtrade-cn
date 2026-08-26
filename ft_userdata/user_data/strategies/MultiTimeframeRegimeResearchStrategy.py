from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame


class MultiTimeframeRegimeResearchStrategy(IStrategy):
    """Fixed, no-leverage candidates for the multi-timeframe research screen.

    The execution frame is 15m.  The 4h and 1d frames are merged with
    ``merge_informative_pair`` so an informative candle is only available after
    it has closed.  A candidate either trades an aligned trend or trades a
    weak/conflicted (range) regime; it never routes a conflicted trend signal
    into the trend leg.
    """

    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "15m"
    process_only_new_candles = True
    # Informative loading applies this count in the informative timeframe too.
    startup_candle_count = 1_200

    max_open_trades = 1
    position_adjustment_enable = False
    minimal_roi: ClassVar[dict[str, float]] = {"0": 0.04}
    stoploss = -0.015
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

    # These are overwritten by each preregistered generated subclass.
    variant_code: ClassVar[str] = "BASE"
    regime_code: ClassVar[str] = "R1"
    regime_fast: ClassVar[int] = 20
    regime_slow: ClassVar[int] = 50
    regime_adx_threshold: ClassVar[float] = 15.0
    regime_slope_threshold: ClassVar[float] = 0.0
    entry_code: ClassVar[str] = "E1"
    entry_style: ClassVar[str] = "trend_breakout"
    channel_length: ClassVar[int] = 20
    close_location_min: ClassVar[float] = 0.55
    atrp_min: ClassVar[float] = 0.0
    retest_bars: ClassVar[int] = 0
    range_rsi_low: ClassVar[float] = 30.0
    range_rsi_high: ClassVar[float] = 70.0
    range_band_std: ClassVar[float] = 2.0
    participation_code: ClassVar[str] = "P0"
    relative_volume_min: ClassVar[float] = 1.0
    funding_filter: ClassVar[bool] = False
    funding_long_max: ClassVar[float] = 0.0
    funding_short_min: ClassVar[float] = 0.0
    max_hold_hours: ClassVar[int] = 72

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
            "Participation": {
                "relative_volume": {"color": "#FFAB00"},
                "funding_rate_fr_1h": {"color": "#00A3BF"},
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
                    (pair, "1h", "funding_rate"),
                ]
            )
        return result

    @classmethod
    def _regime_frame(cls, dataframe: DataFrame) -> DataFrame:
        frame = dataframe.copy()
        fast = ta.EMA(frame, timeperiod=cls.regime_fast)
        slow = ta.EMA(frame, timeperiod=cls.regime_slow)
        adx = ta.ADX(frame, timeperiod=14)
        slope = fast / fast.shift(6) - 1.0
        direction = pd.Series(0.0, index=frame.index, dtype="float64")
        direction.loc[
            (frame["close"] > slow)
            & (fast > slow)
            & (slope >= cls.regime_slope_threshold)
        ] = 1.0
        direction.loc[
            (frame["close"] < slow)
            & (fast < slow)
            & (slope <= -cls.regime_slope_threshold)
        ] = -1.0
        return DataFrame(
            {
                "date": frame["date"],
                "regime_dir": direction,
                "regime_adx": adx,
                "regime_ema_fast": fast,
                "regime_ema_slow": slow,
            },
            index=frame.index,
        )

    @staticmethod
    def _funding_frame(dataframe: DataFrame) -> DataFrame:
        frame = dataframe.copy()
        source = next(
            (name for name in ("funding_rate", "fundingRate", "rate", "open", "close") if name in frame),
            None,
        )
        values = pd.to_numeric(frame[source], errors="coerce") if source else np.nan
        return DataFrame({"date": frame["date"], "funding_rate": values}, index=frame.index)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        result = dataframe.copy()
        result["donchian_high"] = result["high"].rolling(self.channel_length).max().shift(1)
        result["donchian_low"] = result["low"].rolling(self.channel_length).min().shift(1)
        result["atr14"] = ta.ATR(result, timeperiod=14)
        result["atrp"] = result["atr14"] / result["close"]
        result["rsi14"] = ta.RSI(result, timeperiod=14)
        result["bb_mid"] = result["close"].rolling(self.channel_length).mean().shift(1)
        result["bb_std"] = result["close"].rolling(self.channel_length).std(ddof=0).shift(1)
        result["bb_upper"] = result["bb_mid"] + self.range_band_std * result["bb_std"]
        result["bb_lower"] = result["bb_mid"] - self.range_band_std * result["bb_std"]
        volume_reference = result["volume"].rolling(96).median().shift(1)
        result["relative_volume"] = result["volume"] / volume_reference.replace(0, np.nan)
        candle_range = (result["high"] - result["low"]).replace(0, np.nan)
        result["close_location"] = (
            (2.0 * result["close"] - result["high"] - result["low"]) / candle_range
        ).clip(-1.0, 1.0)

        data_provider = getattr(self, "dp", None)
        if data_provider:
            pair = metadata["pair"]
            for timeframe in ("4h", "1d"):
                informative = data_provider.get_pair_dataframe(pair=pair, timeframe=timeframe)
                if informative.empty:
                    result[f"regime_dir_{timeframe}"] = np.nan
                    result[f"regime_adx_{timeframe}"] = np.nan
                    result[f"regime_ema_fast_{timeframe}"] = np.nan
                    result[f"regime_ema_slow_{timeframe}"] = np.nan
                    continue
                regime = self._regime_frame(informative)
                result = merge_informative_pair(
                    result, regime, self.timeframe, timeframe, ffill=True
                )

            funding = data_provider.get_pair_dataframe(
                pair=pair, timeframe="1h", candle_type="funding_rate"
            )
            if funding.empty:
                result["funding_rate_fr_1h"] = np.nan
            else:
                result = merge_informative_pair(
                    result,
                    self._funding_frame(funding),
                    self.timeframe,
                    "1h",
                    ffill=False,
                    append_timeframe=False,
                    suffix="fr_1h",
                )
        else:
            for timeframe in ("4h", "1d"):
                for column in ("regime_dir", "regime_adx", "regime_ema_fast", "regime_ema_slow"):
                    result[f"{column}_{timeframe}"] = np.nan
            result["funding_rate_fr_1h"] = np.nan

        strong_up = (
            (result["regime_dir_4h"] == 1)
            & (result["regime_dir_1d"] == 1)
            & (result["regime_adx_4h"] >= self.regime_adx_threshold)
            & (result["regime_adx_1d"] >= self.regime_adx_threshold)
        )
        strong_down = (
            (result["regime_dir_4h"] == -1)
            & (result["regime_dir_1d"] == -1)
            & (result["regime_adx_4h"] >= self.regime_adx_threshold)
            & (result["regime_adx_1d"] >= self.regime_adx_threshold)
        )
        regime_available = result[
            [
                "regime_dir_4h",
                "regime_adx_4h",
                "regime_dir_1d",
                "regime_adx_1d",
            ]
        ].notna().all(axis=1)
        result["regime_state"] = "neutral"
        result.loc[strong_up, "regime_state"] = "trend_up"
        result.loc[strong_down, "regime_state"] = "trend_down"
        result.loc[regime_available & ~(strong_up | strong_down), "regime_state"] = "range"
        return result

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        candle_range = (dataframe["high"] - dataframe["low"]).replace(0, np.nan)
        body = (dataframe["close"] - dataframe["open"]).abs() / candle_range
        bullish_quality = (
            (dataframe["close_location"] >= self.close_location_min)
            & (body >= 0.30)
            & (dataframe["close"] > dataframe["open"])
        )
        bearish_quality = (
            (dataframe["close_location"] <= -self.close_location_min)
            & (body >= 0.30)
            & (dataframe["close"] < dataframe["open"])
        )
        volume_ok = dataframe["relative_volume"] >= self.relative_volume_min
        funding = dataframe["funding_rate_fr_1h"]
        if self.funding_filter:
            long_funding_ok = funding.notna() & (funding <= self.funding_long_max)
            short_funding_ok = funding.notna() & (funding >= self.funding_short_min)
        else:
            long_funding_ok = pd.Series(True, index=dataframe.index)
            short_funding_ok = pd.Series(True, index=dataframe.index)

        long_breakout = (
            (dataframe["close"] > dataframe["donchian_high"])
            & (dataframe["close"].shift(1) <= dataframe["donchian_high"].shift(1))
        )
        short_breakout = (
            (dataframe["close"] < dataframe["donchian_low"])
            & (dataframe["close"].shift(1) >= dataframe["donchian_low"].shift(1))
        )
        if self.entry_style == "trend_retest":
            prior_long = (dataframe["close"] > dataframe["donchian_high"]).astype(int)
            prior_short = (dataframe["close"] < dataframe["donchian_low"]).astype(int)
            long_recent = prior_long.shift(1).rolling(self.retest_bars).max().fillna(0) > 0
            short_recent = prior_short.shift(1).rolling(self.retest_bars).max().fillna(0) > 0
            long_breakout = (
                long_recent
                & (dataframe["low"] <= dataframe["donchian_high"])
                & (dataframe["close"] > dataframe["donchian_high"])
            )
            short_breakout = (
                short_recent
                & (dataframe["high"] >= dataframe["donchian_low"])
                & (dataframe["close"] < dataframe["donchian_low"])
            )

        if self.entry_style == "range_reversion":
            long_signal = (
                (dataframe["regime_state"] == "range")
                & (dataframe["close"] <= dataframe["bb_lower"])
                & (dataframe["rsi14"] <= self.range_rsi_low)
                & bullish_quality
            )
            short_signal = (
                (dataframe["regime_state"] == "range")
                & (dataframe["close"] >= dataframe["bb_upper"])
                & (dataframe["rsi14"] >= self.range_rsi_high)
                & bearish_quality
            )
        else:
            long_signal = (
                (dataframe["regime_state"] == "trend_up")
                & long_breakout
                & bullish_quality
                & (dataframe["atrp"] >= self.atrp_min)
            )
            short_signal = (
                (dataframe["regime_state"] == "trend_down")
                & short_breakout
                & bearish_quality
                & (dataframe["atrp"] >= self.atrp_min)
            )

        long_signal &= volume_ok & long_funding_ok
        short_signal &= volume_ok & short_funding_ok
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
        if current_time >= trade.open_date_utc + timedelta(hours=self.max_hold_hours):
            return "time_exit_72h"
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
        return 1.0


REGIME_PROFILES: tuple[dict[str, object], ...] = (
    {"code": "R1", "fast": 20, "slow": 50, "adx": 15.0, "slope": 0.0},
    {"code": "R2", "fast": 30, "slow": 90, "adx": 18.0, "slope": 0.0},
    {"code": "R3", "fast": 20, "slow": 80, "adx": 20.0, "slope": 0.0005},
    {"code": "R4", "fast": 10, "slow": 40, "adx": 22.0, "slope": 0.0},
    {"code": "R5", "fast": 50, "slow": 200, "adx": 12.0, "slope": 0.0},
)
ENTRY_PROFILES: tuple[dict[str, object], ...] = (
    {"code": "E1", "style": "trend_breakout", "channel": 20, "clv": 0.55, "atrp": 0.0, "retest": 0},
    {"code": "E2", "style": "trend_breakout", "channel": 40, "clv": 0.60, "atrp": 0.002, "retest": 0},
    {"code": "E3", "style": "trend_breakout", "channel": 64, "clv": 0.65, "atrp": 0.003, "retest": 0},
    {"code": "E4", "style": "trend_retest", "channel": 40, "clv": 0.45, "atrp": 0.001, "retest": 4},
    {"code": "E5", "style": "range_reversion", "channel": 30, "clv": 0.20, "atrp": 0.0, "retest": 0, "rsi_low": 30.0, "rsi_high": 70.0, "band_std": 2.0},
)
PARTICIPATION_PROFILES: tuple[dict[str, object], ...] = (
    {"code": "P0", "volume": 1.0, "funding": False, "funding_long": 0.0, "funding_short": 0.0},
    {"code": "P1", "volume": 1.0, "funding": True, "funding_long": 0.0, "funding_short": 0.0},
)

VARIANT_SPECS: tuple[dict[str, object], ...] = tuple(
    {
        **regime,
        **entry,
        **participation,
        "code": f"{regime['code']}-{entry['code']}-{participation['code']}",
        "name": f"MtfRegime{regime['code']}{entry['code']}{participation['code']}Strategy",
        "regime": regime["code"],
        "entry": entry["code"],
        "participation": participation["code"],
    }
    for regime in REGIME_PROFILES
    for entry in ENTRY_PROFILES
    for participation in PARTICIPATION_PROFILES
)


class MtfRegimeR1E1P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR1E1P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR1E2P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR1E2P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR1E3P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR1E3P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR1E4P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR1E4P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR1E5P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR1E5P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR2E1P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR2E1P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR2E2P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR2E2P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR2E3P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR2E3P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR2E4P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR2E4P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR2E5P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR2E5P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR3E1P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR3E1P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR3E2P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR3E2P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR3E3P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR3E3P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR3E4P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR3E4P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR3E5P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR3E5P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR4E1P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR4E1P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR4E2P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR4E2P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR4E3P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR4E3P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR4E4P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR4E4P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR4E5P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR4E5P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR5E1P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR5E1P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR5E2P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR5E2P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR5E3P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR5E3P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR5E4P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR5E4P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR5E5P0Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


class MtfRegimeR5E5P1Strategy(MultiTimeframeRegimeResearchStrategy):
    pass


def _apply_variant(
    strategy_class: type[MultiTimeframeRegimeResearchStrategy], spec: dict[str, object]
) -> None:
    attributes = {
        "variant_code": spec["code"],
        "regime_code": spec["regime"],
        "regime_fast": spec["fast"],
        "regime_slow": spec["slow"],
        "regime_adx_threshold": spec["adx"],
        "regime_slope_threshold": spec["slope"],
        "entry_code": spec["entry"],
        "entry_style": spec["style"],
        "channel_length": spec["channel"],
        "close_location_min": spec["clv"],
        "atrp_min": spec["atrp"],
        "retest_bars": spec["retest"],
        "range_rsi_low": spec.get("rsi_low", 30.0),
        "range_rsi_high": spec.get("rsi_high", 70.0),
        "range_band_std": spec.get("band_std", 2.0),
        "participation_code": spec["participation"],
        "relative_volume_min": spec["volume"],
        "funding_filter": spec["funding"],
        "funding_long_max": spec["funding_long"],
        "funding_short_min": spec["funding_short"],
    }
    for name, value in attributes.items():
        setattr(strategy_class, name, value)


for _spec in VARIANT_SPECS:
    _apply_variant(globals()[str(_spec["name"])], _spec)
