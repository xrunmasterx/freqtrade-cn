from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

from DonchianCounterMomentumRegimeStrategy import (
    DonchianCounterMomentumRegimeStrategy,
)
from freqtrade.persistence import Trade
from pandas import DataFrame


class DonchianRobustBaselineResearchStrategy(DonchianCounterMomentumRegimeStrategy):
    """One-leverage reference used only for the historical robustness study."""


class DonchianRobustNoRegimeResearchStrategy(DonchianRobustBaselineResearchStrategy):
    """Ablation of the 1h EMA regime; all other entry conditions stay unchanged."""

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_condition = (
            (dataframe["close"] > dataframe["donchian_high"])
            & (dataframe["close"].shift(1) <= dataframe["donchian_high"].shift(1))
            & (dataframe["return_72h"] <= self.max_directional_return_72h)
        )
        short_condition = (
            (dataframe["close"] < dataframe["donchian_low"])
            & (dataframe["close"].shift(1) >= dataframe["donchian_low"].shift(1))
            & (-dataframe["return_72h"] <= self.max_directional_return_72h)
        )
        dataframe.loc[long_condition, ["enter_long", "enter_tag"]] = (
            1,
            "donchian_counter_momentum_long",
        )
        dataframe.loc[short_condition, ["enter_short", "enter_tag"]] = (
            1,
            "donchian_counter_momentum_short",
        )
        return dataframe


class DonchianRobustEma240ResearchStrategy(DonchianRobustBaselineResearchStrategy):
    """Ten-day 1h EMA neighborhood check for the existing twenty-day regime."""

    regime_ema_length = 240


class DonchianRobustEma720ResearchStrategy(DonchianRobustBaselineResearchStrategy):
    """Thirty-day 1h EMA neighborhood check for the existing twenty-day regime."""

    regime_ema_length = 720


class DonchianRobustAsymmetricTimeExitResearchStrategy(
    DonchianRobustBaselineResearchStrategy
):
    """Cut stale losers after 24h while allowing profitable trades up to 72h."""

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        age = current_time - trade.open_date_utc
        if age >= timedelta(hours=24) and current_profit <= 0:
            return "stale_loss_24h"
        if age >= timedelta(hours=72):
            return "max_hold_72h"
        return None


class DonchianRobustHold72ResearchStrategy(DonchianRobustBaselineResearchStrategy):
    """Single-parameter exit candidate: extend the fixed maximum hold to 72h."""

    max_hold_hours = 72

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
            return "max_hold_72h"
        return None


class DonchianRobustCloseLocationResearchStrategy(
    DonchianRobustBaselineResearchStrategy
):
    """Require a breakout candle to close in its directional outer quartile."""

    close_location_min = 0.5

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        candle_range = (dataframe["high"] - dataframe["low"]).replace(0, float("nan"))
        dataframe["price_acceptance"] = (
            (2 * dataframe["close"] - dataframe["high"] - dataframe["low"])
            / candle_range
        ).clip(-1, 1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        invalid_long = (dataframe["enter_long"] == 1) & (
            dataframe["price_acceptance"] < self.close_location_min
        )
        invalid_short = (dataframe["enter_short"] == 1) & (
            dataframe["price_acceptance"] > -self.close_location_min
        )
        dataframe.loc[invalid_long, ["enter_long", "enter_tag"]] = (0, None)
        dataframe.loc[invalid_short, ["enter_short", "enter_tag"]] = (0, None)
        return dataframe


class DonchianRobustPriceExitResearchStrategy(
    DonchianRobustCloseLocationResearchStrategy
):
    """The price-acceptance entry filter plus the asymmetric time exit."""

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        age = current_time - trade.open_date_utc
        if age >= timedelta(hours=24) and current_profit <= 0:
            return "stale_loss_24h"
        if age >= timedelta(hours=72):
            return "max_hold_72h"
        return None


class DonchianRobustRrResearchStrategy(DonchianRobustBaselineResearchStrategy):
    """Lower-volatility fixed exit with roughly 2.3:1 reward/risk after 0.06% fees."""

    minimal_roi: ClassVar[dict[str, float]] = {"0": 0.03}
    stoploss = -0.012
