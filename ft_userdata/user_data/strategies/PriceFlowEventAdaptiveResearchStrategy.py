from __future__ import annotations

from typing import ClassVar

import numpy as np
import pandas as pd
from pandas import DataFrame
from PriceFlowCapitalIntentResearchStrategy import PriceFlowCapitalIntentResearchBase


class PriceFlowEventAdaptiveResearchBase(PriceFlowCapitalIntentResearchBase):
    """Offline-only, preregistered event-adaptive descendants of frozen C04."""

    research_id = 4
    event_id = 0

    _fomc_events: ClassVar[tuple[str, ...]] = (
        "2023-09-20T18:00:00Z",
        "2023-11-01T18:00:00Z",
        "2023-12-13T19:00:00Z",
        "2024-01-31T19:00:00Z",
        "2024-03-20T18:00:00Z",
        "2024-05-01T18:00:00Z",
        "2024-06-12T18:00:00Z",
        "2024-07-31T18:00:00Z",
        "2024-09-18T18:00:00Z",
        "2024-11-07T19:00:00Z",
        "2024-12-18T19:00:00Z",
        "2025-01-29T19:00:00Z",
        "2025-03-19T18:00:00Z",
        "2025-05-07T18:00:00Z",
        "2025-06-18T18:00:00Z",
        "2025-07-30T18:00:00Z",
        "2025-09-17T18:00:00Z",
        "2025-10-29T18:00:00Z",
        "2025-12-10T19:00:00Z",
        "2026-01-28T19:00:00Z",
        "2026-03-18T18:00:00Z",
        "2026-04-29T18:00:00Z",
        "2026-06-17T18:00:00Z",
        "2026-07-29T18:00:00Z",
    )
    _policy_available_events: ClassVar[tuple[str, ...]] = (
        "2024-01-11T00:00:00Z",
        "2024-05-24T00:00:00Z",
        "2024-08-01T00:00:00Z",
        "2025-01-24T00:00:00Z",
        "2025-03-07T00:00:00Z",
        "2025-04-03T00:00:00Z",
        "2025-04-10T00:00:00Z",
        "2025-07-19T00:00:00Z",
        "2025-07-31T00:00:00Z",
    )

    @property
    def event_code(self) -> str:
        return f"E{self.event_id:02d}"

    @staticmethod
    def _minutes_from_events(decisions: pd.Series, event_values: tuple[str, ...]) -> pd.Series:
        decision_ns = pd.to_datetime(decisions, utc=True).astype("datetime64[ns, UTC]").array.asi8
        event_ns = np.array([pd.Timestamp(value).value for value in event_values], dtype=np.int64)
        values = np.full(len(decisions), np.nan)
        for position, timestamp in enumerate(decision_ns):
            if timestamp == pd.NaT.value:
                continue
            nearest = event_ns[np.argmin(np.abs(event_ns - timestamp))]
            values[position] = (timestamp - nearest) / (60 * 1_000_000_000)
        return pd.Series(values, index=decisions.index, dtype=float)

    def _derive_event_features(self, dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        decisions = pd.to_datetime(dataframe["decision_time"], utc=True)
        fomc = self._minutes_from_events(decisions, self._fomc_events)
        cpi = self._numeric(dataframe, "minutes_from_cpi")
        policy = self._minutes_from_events(decisions, self._policy_available_events)
        scheduled = fomc.where(fomc.abs().le(cpi.abs()), cpi)

        dataframe["ea_minutes_from_fomc"] = fomc
        dataframe["ea_minutes_from_scheduled"] = scheduled
        dataframe["ea_minutes_from_policy"] = policy
        dataframe["ea_policy_post_24h"] = policy.between(0, 24 * 60)

        expiry_minutes = self._numeric(dataframe, "minutes_from_expiry")
        expiry_time = decisions - pd.to_timedelta(expiry_minutes, unit="m")
        quarterly = expiry_time.dt.month.mod(3).eq(0) & expiry_time.notna()
        dataframe["ea_quarterly_expiry"] = quarterly
        dataframe["ea_quarterly_expiry_minutes"] = expiry_minutes.where(quarterly)

        event = self._boolean(dataframe, "volatility_event")
        dataframe["ea_shock_window_4"] = event.astype(int).rolling(5, min_periods=1).max().gt(0)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        return self._derive_event_features(dataframe)

    def _directional_features(
        self, dataframe: DataFrame
    ) -> tuple[dict[str, pd.Series], dict[str, pd.Series]]:
        relative_volume = self._numeric(dataframe, "relative_volume")
        oi_z = self._numeric(dataframe, "bin_oi_change_15m_z")
        slope = self._numeric(dataframe, "ema50_slope_4h")
        taker = self._numeric(dataframe, "bin_taker_imbalance")
        taker_lag2 = self._numeric(dataframe, "bin_taker_lag2")
        close = self._numeric(dataframe, "close")

        common = {
            "rv08": relative_volume.ge(0.80),
            "rv10": relative_volume.ge(1.00),
            "oi_z0": oi_z.ge(0.0),
            "oi_z05": oi_z.ge(0.5),
            "oi_z1": oi_z.ge(1.0),
            "oi_add": self._boolean(dataframe, "ci_oi_add"),
            "valid": self._boolean(dataframe, "cross_data_valid"),
        }
        long = {
            **common,
            "price": self._boolean(dataframe, "ci_price_accept_long"),
            "trend_strong": slope.ge(0.010),
            "trend_ok": slope.ge(0.008),
            "crowding": self._boolean(dataframe, "ci_crowding_safe_long"),
            "leader": self._boolean(dataframe, "ci_leader_size_long"),
            "top5": self._boolean(dataframe, "ci_top_5m_long"),
            "fresh": taker.ge(taker_lag2),
            "current_taker": taker.gt(0),
            "extension": close.gt(close.shift(1)),
            "option_clear": ~self._boolean(dataframe, "ci_option_opposed_long"),
            "absorption": self._boolean(dataframe, "ci_absorption_reload_long"),
            "score4": self._numeric(dataframe, "ci_capital_score_long").ge(4),
        }
        short = {
            **common,
            "price": self._boolean(dataframe, "ci_price_accept_short"),
            "trend_strong": slope.le(-0.010),
            "trend_ok": slope.le(-0.008),
            "crowding": self._boolean(dataframe, "ci_crowding_safe_short"),
            "leader": self._boolean(dataframe, "ci_leader_size_short"),
            "top5": self._boolean(dataframe, "ci_top_5m_short"),
            "fresh": taker.le(taker_lag2),
            "current_taker": taker.lt(0),
            "extension": close.lt(close.shift(1)),
            "option_clear": ~self._boolean(dataframe, "ci_option_opposed_short"),
            "absorption": self._boolean(dataframe, "ci_absorption_reload_short"),
            "score4": self._numeric(dataframe, "ci_capital_score_short").ge(4),
        }
        return long, short

    @staticmethod
    def _core_extra_masks(
        dataframe: DataFrame, base: pd.Series, side: str
    ) -> tuple[pd.Series, pd.Series]:
        tags = dataframe.get("enter_tag", pd.Series(None, index=dataframe.index)).fillna("")
        direction = tags.str.endswith(f"_{side}")
        return (
            base & direction & tags.str.contains("_core_", regex=False),
            base & direction & tags.str.contains("_extra_", regex=False),
        )

    def _scheduled_masks(self, dataframe: DataFrame) -> tuple[pd.Series, pd.Series]:
        minutes = self._numeric(dataframe, "ea_minutes_from_scheduled")
        return minutes.ge(-360) & minutes.lt(0), minutes.between(0, 360)

    def _candidate_base_mask(
        self,
        dataframe: DataFrame,
        features: dict[str, pd.Series],
        core: pd.Series,
        extra: pd.Series,
    ) -> pd.Series:
        base = core | extra
        candidate = self.event_id
        if candidate == 1:
            return base & features["rv08"]
        if candidate == 2:
            return base & features["rv10"]
        if candidate == 3:
            return base & features["rv08"] & features["crowding"]
        if candidate == 4:
            return base & features["price"]
        if candidate == 5:
            return base & (features["price"] | features["trend_strong"])
        if candidate == 6:
            return base & (features["price"] | features["oi_z1"])
        if candidate == 7:
            return base & (features["price"] | (features["trend_ok"] & features["oi_z0"]))
        if candidate == 8:
            return (core & features["rv08"]) | (extra & features["rv08"] & features["price"])
        if candidate == 9:
            return (
                base
                & features["rv08"]
                & (features["price"] | features["oi_z05"] | features["trend_ok"])
            )
        if candidate == 10:
            return base & features["rv08"] & (features["price"] | features["fresh"])
        if 11 <= candidate <= 16:
            return base & features["rv08"]
        if candidate in {17, 18}:
            pre, post = self._scheduled_masks(dataframe)
            outside = ~(pre | post)
            post_gate = features["price"] & features["oi_z1"]
            if candidate == 18:
                post_gate &= features["option_clear"]
            return base & ((outside & features["rv08"]) | (post & post_gate))
        if candidate == 19:
            shock = self._boolean(dataframe, "ea_shock_window_4")
            strict = (
                features["price"]
                & features["oi_z1"]
                & features["leader"]
                & features["option_clear"]
            )
            return base & ((~shock & features["rv08"]) | (shock & strict))
        if candidate == 20:
            scheduled = self._numeric(dataframe, "ea_minutes_from_scheduled")
            quarterly = self._numeric(dataframe, "ea_quarterly_expiry_minutes")
            pre = (scheduled.ge(-360) & scheduled.lt(0)) | (quarterly.ge(-360) & quarterly.lt(0))
            post = (
                scheduled.between(0, 24 * 60)
                | quarterly.between(0, 24 * 60)
                | self._boolean(dataframe, "ea_policy_post_24h")
            )
            shock = self._boolean(dataframe, "ea_shock_window_4")
            normal = ~(pre | post | shock)
            normal_gate = features["rv08"] & (
                features["price"] | features["oi_z05"] | features["trend_ok"]
            )
            post_gate = (
                features["price"]
                & features["oi_z0"]
                & features["leader"]
                & features["rv10"]
                & features["option_clear"]
            )
            shock_gate = post_gate & features["oi_z1"]
            return (
                base & ~pre & ((normal & normal_gate) | (post & post_gate) | (shock & shock_gate))
            )
        return base

    def _candidate_extra_mask(
        self,
        dataframe: DataFrame,
        features: dict[str, pd.Series],
        context: pd.Series,
    ) -> tuple[pd.Series, str]:
        candidate = self.event_id
        no_extra = self._false(dataframe.index)
        if candidate == 11:
            return (
                features["price"] & features["oi_add"] & features["leader"] & context,
                "acceptance",
            )
        if candidate == 12:
            return features["price"] & features["oi_z1"] & context, "strong_oi_acceptance"
        if candidate == 13:
            return (
                features["price"]
                & features["oi_add"]
                & (features["top5"] | features["leader"])
                & features["rv10"]
                & context,
                "position_acceptance",
            )
        if candidate == 14:
            return (
                features["price"] & features["score4"] & features["rv08"] & context,
                "capital_consensus",
            )
        if candidate == 15:
            return (
                features["absorption"] & features["leader"] & features["rv08"] & context,
                "absorption_reload",
            )
        if candidate == 16:
            return (
                features["price"].shift(1).fillna(False)
                & features["extension"]
                & features["oi_add"]
                & features["current_taker"]
                & features["leader"]
                & features["rv08"]
                & context,
                "second_acceptance",
            )
        if candidate == 18:
            _, post = self._scheduled_masks(dataframe)
            return (
                post
                & features["price"]
                & features["oi_z1"]
                & features["leader"]
                & features["rv10"]
                & features["option_clear"]
                & context,
                "post_macro_acceptance",
            )
        if candidate == 19:
            shock = self._boolean(dataframe, "ea_shock_window_4")
            return (
                shock
                & features["price"]
                & features["oi_z1"]
                & features["leader"]
                & features["option_clear"]
                & context,
                "shock_acceptance",
            )
        if candidate == 20:
            scheduled = self._numeric(dataframe, "ea_minutes_from_scheduled")
            quarterly = self._numeric(dataframe, "ea_quarterly_expiry_minutes")
            pre = (scheduled.ge(-360) & scheduled.lt(0)) | (quarterly.ge(-360) & quarterly.lt(0))
            post = (
                scheduled.between(0, 24 * 60)
                | quarterly.between(0, 24 * 60)
                | self._boolean(dataframe, "ea_policy_post_24h")
            )
            shock = self._boolean(dataframe, "ea_shock_window_4")
            strict = (
                features["price"]
                & features["oi_z0"]
                & features["leader"]
                & features["rv10"]
                & features["option_clear"]
            )
            strict &= ~shock | features["oi_z1"]
            return ~pre & (post | shock) & strict & context, "event_acceptance"
        return no_extra, "none"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        if self.event_id == 0:
            return dataframe
        dataframe = self._derive_event_features(dataframe)
        long_features, short_features = self._directional_features(dataframe)
        base_long = self._signal_series(dataframe, "enter_long")
        base_short = self._signal_series(dataframe, "enter_short")
        core_long, extra_long = self._core_extra_masks(dataframe, base_long, "long")
        core_short, extra_short = self._core_extra_masks(dataframe, base_short, "short")
        keep_long = self._candidate_base_mask(dataframe, long_features, core_long, extra_long)
        keep_short = self._candidate_base_mask(dataframe, short_features, core_short, extra_short)
        long_context, short_context = self._market_context(dataframe)
        add_long, long_label = self._candidate_extra_mask(dataframe, long_features, long_context)
        add_short, short_label = self._candidate_extra_mask(
            dataframe, short_features, short_context
        )
        keep_long &= long_features["valid"]
        keep_short &= short_features["valid"]
        add_long &= long_features["valid"]
        add_short &= short_features["valid"]

        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0
        dataframe.loc[:, "enter_tag"] = None
        code = self.event_code.lower()
        dataframe.loc[keep_long, ["enter_long", "enter_tag"]] = (
            1,
            f"ea_{code}_base_long",
        )
        dataframe.loc[keep_short, ["enter_short", "enter_tag"]] = (
            1,
            f"ea_{code}_base_short",
        )
        new_long = add_long & ~keep_long
        new_short = add_short & ~keep_short
        dataframe.loc[new_long, ["enter_long", "enter_tag"]] = (
            1,
            f"ea_{code}_{long_label}_long",
        )
        dataframe.loc[new_short, ["enter_short", "enter_tag"]] = (
            1,
            f"ea_{code}_{short_label}_short",
        )
        return dataframe


class PriceFlowEventAdaptiveControl(PriceFlowEventAdaptiveResearchBase):
    event_id = 0


# Freqtrade prefilters strategy files using literal ``class <name>(`` markers.
# class PriceFlowEventAdaptive01Strategy(
# class PriceFlowEventAdaptive02Strategy(
# class PriceFlowEventAdaptive03Strategy(
# class PriceFlowEventAdaptive04Strategy(
# class PriceFlowEventAdaptive05Strategy(
# class PriceFlowEventAdaptive06Strategy(
# class PriceFlowEventAdaptive07Strategy(
# class PriceFlowEventAdaptive08Strategy(
# class PriceFlowEventAdaptive09Strategy(
# class PriceFlowEventAdaptive10Strategy(
# class PriceFlowEventAdaptive11Strategy(
# class PriceFlowEventAdaptive12Strategy(
# class PriceFlowEventAdaptive13Strategy(
# class PriceFlowEventAdaptive14Strategy(
# class PriceFlowEventAdaptive15Strategy(
# class PriceFlowEventAdaptive16Strategy(
# class PriceFlowEventAdaptive17Strategy(
# class PriceFlowEventAdaptive18Strategy(
# class PriceFlowEventAdaptive19Strategy(
# class PriceFlowEventAdaptive20Strategy(


def _candidate_class(candidate_id: int) -> type[PriceFlowEventAdaptiveResearchBase]:
    return type(
        f"PriceFlowEventAdaptive{candidate_id:02d}Strategy",
        (PriceFlowEventAdaptiveResearchBase,),
        {"event_id": candidate_id, "__module__": __name__},
    )


for _candidate_id in range(1, 21):
    globals()[f"PriceFlowEventAdaptive{_candidate_id:02d}Strategy"] = _candidate_class(
        _candidate_id
    )
