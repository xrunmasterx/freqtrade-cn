from __future__ import annotations

from typing import ClassVar

import pandas as pd
from pandas import DataFrame
from PriceFlowCrossVenueResearchStrategy import PriceFlowCrossVenueResearchBase


class PriceFlowCapitalIntentResearchBase(PriceFlowCrossVenueResearchBase):
    """Offline-only preregistered capital-intent candidates.

    Public futures and option fields are observable behavior proxies.  They do
    not identify an actor, opening versus closing intent, or institutional flow.
    """

    candidate_id = 0
    research_id = 0

    _sidecar_columns: ClassVar[list[str]] = list(
        dict.fromkeys(
            [
                *PriceFlowCrossVenueResearchBase._sidecar_columns,
                "bin_top_position_change_5m",
                "bin_top_account_change_5m",
                "bin_oi_change_15m_z",
                "bin_taker_imbalance_z",
                "venue_spread_z",
                "opt_dte_1_7_flow_1h",
            ]
        )
    )

    @property
    def research_code(self) -> str:
        return f"C{self.research_id:02d}"

    @staticmethod
    def _false(index: pd.Index) -> pd.Series:
        return pd.Series(False, index=index, dtype=bool)

    @staticmethod
    def _numeric(dataframe: DataFrame, column: str) -> pd.Series:
        if column not in dataframe:
            return pd.Series(float("nan"), index=dataframe.index, dtype=float)
        return pd.to_numeric(dataframe[column], errors="coerce")

    @staticmethod
    def _boolean(dataframe: DataFrame, column: str) -> pd.Series:
        if column not in dataframe:
            return pd.Series(False, index=dataframe.index, dtype=bool)
        return dataframe[column].fillna(False).astype(bool)

    def _derive_capital_features(self, dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        taker = self._numeric(dataframe, "bin_taker_imbalance")
        taker_lag1 = self._numeric(dataframe, "bin_taker_lag1")
        taker_lag2 = self._numeric(dataframe, "bin_taker_lag2")
        oi_change = self._numeric(dataframe, "bin_oi_change_15m")
        oi_z = self._numeric(dataframe, "bin_oi_change_15m_z")
        top_5m = self._numeric(dataframe, "bin_top_position_change_5m")
        leader_size = self._numeric(
            dataframe, "bin_top_position_change_2h"
        ) - self._numeric(dataframe, "bin_top_account_change_2h")

        long_taker_votes = sum(
            value.gt(0).astype(int) for value in (taker, taker_lag1, taker_lag2)
        )
        short_taker_votes = sum(
            value.lt(0).astype(int) for value in (taker, taker_lag1, taker_lag2)
        )
        dataframe["ci_oi_add"] = oi_change.gt(0)
        dataframe["ci_taker_persist_long"] = long_taker_votes.ge(2)
        dataframe["ci_taker_persist_short"] = short_taker_votes.ge(2)
        dataframe["ci_top_5m_long"] = top_5m.gt(0)
        dataframe["ci_top_5m_short"] = top_5m.lt(0)
        dataframe["ci_leader_size_delta"] = leader_size
        dataframe["ci_leader_size_long"] = leader_size.gt(0)
        dataframe["ci_leader_size_short"] = leader_size.lt(0)
        dataframe["ci_material_oi_unwind"] = oi_change.lt(0) & oi_z.le(-1)

        close_location = self._numeric(dataframe, "close_location")
        body_atr = self._numeric(dataframe, "body_atr")
        close = self._numeric(dataframe, "close")
        high = self._numeric(dataframe, "high")
        low = self._numeric(dataframe, "low")
        open_ = self._numeric(dataframe, "open")
        dataframe["ci_price_accept_long"] = (
            close_location.ge(0.35)
            & body_atr.ge(0.30)
            & close.gt(high.shift(1))
        )
        dataframe["ci_price_accept_short"] = (
            close_location.le(-0.35)
            & body_atr.ge(0.30)
            & close.lt(low.shift(1))
        )

        funding_valid = self._boolean(dataframe, "funding_valid")
        funding_z = self._numeric(dataframe, "funding_dispersion_z")
        global_account_z = self._numeric(dataframe, "bin_global_account_log_z")
        spread_shock = self._boolean(dataframe, "venue_spread_shock")
        dataframe["ci_crowding_safe_long"] = (
            global_account_z.lt(2)
            & (~funding_valid | funding_z.lt(2))
            & ~spread_shock
        )
        dataframe["ci_crowding_safe_short"] = (
            global_account_z.gt(-2)
            & (~funding_valid | funding_z.gt(-2))
            & ~spread_shock
        )

        option_count = self._numeric(dataframe, "opt_dte_1_7_count_1h")
        option_urgency = self._numeric(dataframe, "opt_dte_1_7_urgency_1h")
        option_evidence = option_count.ge(3)
        dataframe["ci_option_opposed_long"] = option_evidence & option_urgency.lt(0)
        dataframe["ci_option_opposed_short"] = option_evidence & option_urgency.gt(0)
        dataframe["ci_option_same_long"] = option_evidence & option_urgency.gt(0)
        dataframe["ci_option_same_short"] = option_evidence & option_urgency.lt(0)

        long_absorption_seed = (
            dataframe["ci_taker_persist_short"]
            & close.gt(open_)
            & close_location.ge(0.20)
        )
        short_absorption_seed = (
            dataframe["ci_taker_persist_long"]
            & close.lt(open_)
            & close_location.le(-0.20)
        )
        dataframe["ci_absorption_reload_long"] = (
            long_absorption_seed.shift(1).fillna(False)
            & taker.gt(0)
            & dataframe["ci_oi_add"]
            & close.gt(high.shift(1))
        )
        dataframe["ci_absorption_reload_short"] = (
            short_absorption_seed.shift(1).fillna(False)
            & taker.lt(0)
            & dataframe["ci_oi_add"]
            & close.lt(low.shift(1))
        )

        spread_z = self._numeric(dataframe, "venue_spread_z")
        spread = self._numeric(dataframe, "venue_spread")
        bin_return = self._numeric(dataframe, "bin_price_return_15m")
        cusum_long = self._boolean(dataframe, "taker_cusum_long_follow")
        cusum_short = self._boolean(dataframe, "taker_cusum_short_follow")
        dataframe["ci_venue_relay_long"] = (
            cusum_long
            & bin_return.gt(0)
            & spread_z.ge(1)
            & dataframe["ci_oi_add"]
            & close.gt(open_)
        )
        dataframe["ci_venue_relay_short"] = (
            cusum_short
            & bin_return.lt(0)
            & spread_z.le(-1)
            & dataframe["ci_oi_add"]
            & close.lt(open_)
        )
        spread_shrinking = spread.abs().lt(spread.shift(1).abs())
        dataframe["ci_venue_catchup_long"] = (
            spread_z.shift(1).ge(1)
            & spread_shrinking
            & dataframe["ci_oi_add"]
            & close.gt(close.shift(1))
        )
        dataframe["ci_venue_catchup_short"] = (
            spread_z.shift(1).le(-1)
            & spread_shrinking
            & dataframe["ci_oi_add"]
            & close.lt(close.shift(1))
        )

        dataframe["ci_capital_score_long"] = sum(
            dataframe[column].astype(int)
            for column in (
                "ci_oi_add",
                "ci_taker_persist_long",
                "ci_top_5m_long",
                "ci_leader_size_long",
                "ci_price_accept_long",
            )
        )
        dataframe["ci_capital_score_short"] = sum(
            dataframe[column].astype(int)
            for column in (
                "ci_oi_add",
                "ci_taker_persist_short",
                "ci_top_5m_short",
                "ci_leader_size_short",
                "ci_price_accept_short",
            )
        )
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        return self._derive_capital_features(dataframe)

    def _base_extra_entries(self, dataframe: DataFrame) -> tuple[pd.Series, pd.Series]:
        long_context, short_context = self._market_context(dataframe)
        valid = self._boolean(dataframe, "cross_data_valid")
        return (
            self._boolean(dataframe, "taker_cusum_long_follow")
            & long_context
            & valid,
            self._boolean(dataframe, "taker_cusum_short_follow")
            & short_context
            & valid,
        )

    def _candidate_masks(
        self,
        dataframe: DataFrame,
        core_long: pd.Series,
        core_short: pd.Series,
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        valid = self._boolean(dataframe, "cross_data_valid")
        core_long = core_long & valid
        core_short = core_short & valid
        extra_long, extra_short = self._base_extra_entries(dataframe)
        candidate = self.research_id

        if candidate == 1:
            extra_long &= dataframe["ci_oi_add"]
            extra_short &= dataframe["ci_oi_add"]
        elif candidate == 2:
            extra_long &= dataframe["ci_oi_add"] & dataframe["ci_taker_persist_long"]
            extra_short &= dataframe["ci_oi_add"] & dataframe["ci_taker_persist_short"]
        elif candidate == 3:
            extra_long &= dataframe["ci_oi_add"] & dataframe["ci_top_5m_long"]
            extra_short &= dataframe["ci_oi_add"] & dataframe["ci_top_5m_short"]
        elif candidate == 4:
            extra_long &= dataframe["ci_oi_add"] & dataframe["ci_leader_size_long"]
            extra_short &= dataframe["ci_oi_add"] & dataframe["ci_leader_size_short"]
        elif candidate == 5:
            extra_long &= dataframe["ci_oi_add"] & dataframe["ci_price_accept_long"]
            extra_short &= dataframe["ci_oi_add"] & dataframe["ci_price_accept_short"]
        elif candidate == 6:
            taker = self._numeric(dataframe, "bin_taker_imbalance")
            core_long &= dataframe["ci_oi_add"] & taker.gt(0) & dataframe["ci_top_5m_long"]
            core_short &= dataframe["ci_oi_add"] & taker.lt(0) & dataframe["ci_top_5m_short"]
        elif candidate == 7:
            allowed = ~dataframe["ci_material_oi_unwind"]
            core_long &= allowed
            core_short &= allowed
            extra_long &= allowed
            extra_short &= allowed
        elif candidate == 8:
            core_long &= dataframe["ci_crowding_safe_long"]
            core_short &= dataframe["ci_crowding_safe_short"]
            extra_long &= dataframe["ci_crowding_safe_long"]
            extra_short &= dataframe["ci_crowding_safe_short"]
        elif candidate == 9:
            delta = dataframe["ci_leader_size_delta"]
            long_allowed = ~delta.lt(0)
            short_allowed = ~delta.gt(0)
            core_long &= long_allowed
            core_short &= short_allowed
            extra_long &= long_allowed
            extra_short &= short_allowed
        elif candidate == 10:
            long_allowed = ~dataframe["ci_option_opposed_long"]
            short_allowed = ~dataframe["ci_option_opposed_short"]
            core_long &= long_allowed
            core_short &= short_allowed
            extra_long &= long_allowed
            extra_short &= short_allowed
        elif candidate == 11:
            long_context, short_context = self._market_context(dataframe)
            extra_long |= dataframe["ci_absorption_reload_long"] & long_context & valid
            extra_short |= dataframe["ci_absorption_reload_short"] & short_context & valid
        elif candidate == 12:
            long_context, short_context = self._market_context(dataframe)
            extra_long |= (
                dataframe["ci_absorption_reload_long"]
                & dataframe["ci_top_5m_long"]
                & dataframe["ci_leader_size_long"]
                & long_context
                & valid
            )
            extra_short |= (
                dataframe["ci_absorption_reload_short"]
                & dataframe["ci_top_5m_short"]
                & dataframe["ci_leader_size_short"]
                & short_context
                & valid
            )
        elif candidate == 13:
            long_context, short_context = self._market_context(dataframe)
            extra_long |= dataframe["ci_venue_relay_long"] & long_context & valid
            extra_short |= dataframe["ci_venue_relay_short"] & short_context & valid
        elif candidate == 14:
            long_context, short_context = self._market_context(dataframe)
            extra_long |= dataframe["ci_venue_catchup_long"] & long_context & valid
            extra_short |= dataframe["ci_venue_catchup_short"] & short_context & valid
        elif candidate == 15:
            extra_long &= dataframe["ci_option_same_long"]
            extra_short &= dataframe["ci_option_same_short"]
        elif candidate == 16:
            extra_long &= dataframe["ci_capital_score_long"].ge(3)
            extra_short &= dataframe["ci_capital_score_short"].ge(3)
        elif candidate in {17, 18, 19, 20}:
            long_allowed = (
                dataframe["ci_crowding_safe_long"]
                & ~dataframe["ci_option_opposed_long"]
            )
            short_allowed = (
                dataframe["ci_crowding_safe_short"]
                & ~dataframe["ci_option_opposed_short"]
            )
            core_long &= long_allowed
            core_short &= short_allowed
            extra_long &= dataframe["ci_capital_score_long"].ge(3) & long_allowed
            extra_short &= dataframe["ci_capital_score_short"].ge(3) & short_allowed
            if candidate in {18, 19, 20}:
                long_context, short_context = self._market_context(dataframe)
                extra_long |= (
                    dataframe["ci_absorption_reload_long"]
                    & long_context
                    & valid
                    & long_allowed
                )
                extra_short |= (
                    dataframe["ci_absorption_reload_short"]
                    & short_context
                    & valid
                    & short_allowed
                )

        return core_long, core_short, extra_long, extra_short

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self._derive_capital_features(dataframe)
        dataframe = super().populate_entry_trend(dataframe, metadata)
        core_long = self._signal_series(dataframe, "enter_long")
        core_short = self._signal_series(dataframe, "enter_short")
        core_long, core_short, extra_long, extra_short = self._candidate_masks(
            dataframe, core_long, core_short
        )

        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0
        dataframe.loc[:, "enter_tag"] = None
        code = self.research_code.lower()

        if self.research_id == 19:
            raw_long = core_long | extra_long
            raw_short = core_short | extra_short
            event = self._boolean(dataframe, "volatility_event")
            long_context, short_context = self._market_context(dataframe)
            valid = self._boolean(dataframe, "cross_data_valid")
            delayed_long = (
                raw_long.shift(1).fillna(False)
                & event.shift(1).fillna(False)
                & dataframe["ci_price_accept_long"]
                & long_context
                & valid
            )
            delayed_short = (
                raw_short.shift(1).fillna(False)
                & event.shift(1).fillna(False)
                & dataframe["ci_price_accept_short"]
                & short_context
                & valid
            )
            immediate = ~event & ~event.shift(1).fillna(False)
            core_long &= immediate
            core_short &= immediate
            extra_long &= immediate
            extra_short &= immediate
        else:
            delayed_long = self._false(dataframe.index)
            delayed_short = self._false(dataframe.index)

        dataframe.loc[core_long, ["enter_long", "enter_tag"]] = (
            1,
            f"ci_{code}_core_long",
        )
        dataframe.loc[core_short, ["enter_short", "enter_tag"]] = (
            1,
            f"ci_{code}_core_short",
        )
        extra_only_long = extra_long & ~core_long
        extra_only_short = extra_short & ~core_short
        absorption_long = self._boolean(dataframe, "ci_absorption_reload_long")
        absorption_short = self._boolean(dataframe, "ci_absorption_reload_short")
        dataframe.loc[extra_only_long, ["enter_long", "enter_tag"]] = (
            1,
            f"ci_{code}_extra_long",
        )
        dataframe.loc[extra_only_short, ["enter_short", "enter_tag"]] = (
            1,
            f"ci_{code}_extra_short",
        )
        dataframe.loc[
            extra_only_long & absorption_long, "enter_tag"
        ] = f"ci_{code}_absorption_long"
        dataframe.loc[
            extra_only_short & absorption_short, "enter_tag"
        ] = f"ci_{code}_absorption_short"
        dataframe.loc[delayed_long, ["enter_long", "enter_tag"]] = (
            1,
            f"ci_{code}_event_delay_long",
        )
        dataframe.loc[delayed_short, ["enter_short", "enter_tag"]] = (
            1,
            f"ci_{code}_event_delay_short",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_exit_trend(dataframe, metadata)
        if self.research_id != 20:
            return dataframe

        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0
        dataframe.loc[:, "exit_tag"] = None
        taker = self._numeric(dataframe, "bin_taker_imbalance")
        oi_change = self._numeric(dataframe, "bin_oi_change_15m")
        long_price_failed = (
            self._numeric(dataframe, "close")
            < self._numeric(dataframe, "rolling_vwap_24h")
        ) & self._numeric(dataframe, "flow_imbalance_8").lt(0)
        short_price_failed = (
            self._numeric(dataframe, "close")
            > self._numeric(dataframe, "rolling_vwap_24h")
        ) & self._numeric(dataframe, "flow_imbalance_8").gt(0)
        long_exit = (long_price_failed & taker.lt(0) & oi_change.lt(0)) | (
            self._boolean(dataframe, "short_displacement") & taker.lt(0)
        )
        short_exit = (short_price_failed & taker.gt(0) & oi_change.lt(0)) | (
            self._boolean(dataframe, "long_displacement") & taker.gt(0)
        )
        dataframe.loc[long_exit, ["exit_long", "exit_tag"]] = (
            1,
            "ci_c20_capital_failure_long",
        )
        dataframe.loc[short_exit, ["exit_short", "exit_tag"]] = (
            1,
            "ci_c20_capital_failure_short",
        )
        return dataframe


class PriceFlowCapitalIntentControl(PriceFlowCapitalIntentResearchBase):
    research_id = 0


# Freqtrade prefilters files using literal ``class <name>(`` source markers.
# class PriceFlowCapitalIntent01Strategy(
# class PriceFlowCapitalIntent02Strategy(
# class PriceFlowCapitalIntent03Strategy(
# class PriceFlowCapitalIntent04Strategy(
# class PriceFlowCapitalIntent05Strategy(
# class PriceFlowCapitalIntent06Strategy(
# class PriceFlowCapitalIntent07Strategy(
# class PriceFlowCapitalIntent08Strategy(
# class PriceFlowCapitalIntent09Strategy(
# class PriceFlowCapitalIntent10Strategy(
# class PriceFlowCapitalIntent11Strategy(
# class PriceFlowCapitalIntent12Strategy(
# class PriceFlowCapitalIntent13Strategy(
# class PriceFlowCapitalIntent14Strategy(
# class PriceFlowCapitalIntent15Strategy(
# class PriceFlowCapitalIntent16Strategy(
# class PriceFlowCapitalIntent17Strategy(
# class PriceFlowCapitalIntent18Strategy(
# class PriceFlowCapitalIntent19Strategy(
# class PriceFlowCapitalIntent20Strategy(


def _candidate_class(candidate_id: int) -> type[PriceFlowCapitalIntentResearchBase]:
    return type(
        f"PriceFlowCapitalIntent{candidate_id:02d}Strategy",
        (PriceFlowCapitalIntentResearchBase,),
        {"research_id": candidate_id, "__module__": __name__},
    )


for _candidate_id in range(1, 21):
    globals()[f"PriceFlowCapitalIntent{_candidate_id:02d}Strategy"] = _candidate_class(
        _candidate_id
    )
