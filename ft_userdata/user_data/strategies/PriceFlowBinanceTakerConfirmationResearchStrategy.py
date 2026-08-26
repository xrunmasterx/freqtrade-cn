from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from pandas import DataFrame
from PriceFlowContinuationStrategy import PriceFlowContinuationStrategy


class PriceFlowBinanceTakerConfirmationResearchStrategy(PriceFlowContinuationStrategy):
    """Research-only BTC/OKX PriceFlow signal with lagged Binance taker confirmation."""

    research_only = True
    sidecar_path = (
        Path(__file__).resolve().parents[1]
        / "research_data"
        / "binance-taker-priceflow-confirmation"
        / "derived"
        / "BTCUSDT-15m-taker-confirmation.feather"
    )

    @staticmethod
    def _false(index: pd.Index) -> pd.Series:
        return pd.Series(False, index=index, dtype=bool)

    @classmethod
    def _prepare_binance_sidecar(cls, sidecar: DataFrame) -> DataFrame:
        required = {
            "date",
            "decision_time",
            "bucket_open",
            "source_complete_time",
            "publication_lag_minutes",
            "constituent_5m_count",
            "binance_taker_imbalance_15m",
            "binance_taker_imbalance_first_5m",
            "binance_taker_imbalance_last_5m",
            "binance_taker_improved_long_10m",
            "binance_taker_improved_short_10m",
        }
        missing = required.difference(sidecar.columns)
        if missing:
            raise ValueError(f"Binance taker sidecar is missing columns: {sorted(missing)}")

        evidence = sidecar.copy()
        for column in ("date", "decision_time", "bucket_open", "source_complete_time"):
            evidence[column] = pd.to_datetime(evidence[column], utc=True, errors="coerce")
        timestamp_columns = ["date", "decision_time", "bucket_open", "source_complete_time"]
        if evidence[timestamp_columns].isna().any().any():
            raise ValueError("Binance taker sidecar contains an invalid timestamp")
        if evidence["date"].duplicated().any() or not evidence["date"].is_monotonic_increasing:
            raise ValueError("Binance taker sidecar strategy timestamps are not unique and ordered")
        research_end = pd.Timestamp("2025-01-01T00:00:00Z")
        if evidence["date"].ge(research_end).any() or evidence["decision_time"].ge(
            research_end
        ).any():
            raise ValueError("Binance taker sidecar contains a forbidden 2025+ timestamp")
        if not evidence["date"].equals(evidence["source_complete_time"]):
            raise ValueError("Binance taker sidecar date must equal source completion time")
        if not evidence["decision_time"].equals(evidence["date"] + pd.Timedelta(minutes=15)):
            raise ValueError("Binance taker sidecar decision time must lag date by 15 minutes")
        if not evidence["source_complete_time"].equals(
            evidence["bucket_open"] + pd.Timedelta(minutes=15)
        ):
            raise ValueError("Binance taker sidecar source completion does not match its bucket")
        if not pd.to_numeric(evidence["publication_lag_minutes"], errors="coerce").eq(15).all():
            raise ValueError("Binance taker sidecar publication lag must be 15 minutes")
        if not pd.to_numeric(evidence["constituent_5m_count"], errors="coerce").eq(3).all():
            raise ValueError("Binance taker sidecar requires three complete 5m constituents")

        return evidence[
            [
                "date",
                "decision_time",
                "bucket_open",
                "source_complete_time",
                "publication_lag_minutes",
                "constituent_5m_count",
                "binance_taker_imbalance_15m",
                "binance_taker_imbalance_first_5m",
                "binance_taker_imbalance_last_5m",
                "binance_taker_improved_long_10m",
                "binance_taker_improved_short_10m",
            ]
        ].rename(
            columns={
                "decision_time": "binance_decision_time",
                "bucket_open": "binance_bucket_open",
                "source_complete_time": "binance_source_complete_time",
            }
        )

    @classmethod
    def _signal(cls, dataframe: DataFrame, column: str) -> pd.Series:
        if column not in dataframe:
            return cls._false(dataframe.index)
        return pd.to_numeric(dataframe[column], errors="coerce").fillna(0).eq(1)

    @staticmethod
    def _derive_directional_price_acceptance(dataframe: DataFrame) -> DataFrame:
        dataframe["directional_price_accept_long"] = (
            dataframe["close_location"].ge(0.35)
            & dataframe["body_atr"].ge(0.30)
            & dataframe["close"].gt(dataframe["high"].shift(1))
        )
        dataframe["directional_price_accept_short"] = (
            dataframe["close_location"].le(-0.35)
            & dataframe["body_atr"].ge(0.30)
            & dataframe["close"].lt(dataframe["low"].shift(1))
        )
        return dataframe

    @classmethod
    def _load_binance_sidecar(cls) -> DataFrame:
        return cls._prepare_binance_sidecar(pd.read_feather(cls.sidecar_path))

    @classmethod
    def _merge_binance_sidecar(
        cls, dataframe: DataFrame, sidecar: DataFrame | None = None
    ) -> DataFrame:
        evidence = (
            cls._load_binance_sidecar()
            if sidecar is None
            else cls._prepare_binance_sidecar(sidecar)
        )
        dataframe = dataframe.copy()
        dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True).astype(
            "datetime64[ns, UTC]"
        )
        evidence["date"] = pd.to_datetime(evidence["date"], utc=True).astype(
            "datetime64[ns, UTC]"
        )
        return dataframe.merge(evidence, on="date", how="left", validate="one_to_one")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if metadata.get("pair") != "BTC/USDT:USDT":
            raise ValueError("Research-only Binance taker confirmation is frozen to BTC/USDT:USDT")
        decision_time = pd.to_datetime(dataframe["date"], utc=True, errors="coerce") + pd.Timedelta(
            minutes=15
        )
        if decision_time.isna().any() or decision_time.ge(
            pd.Timestamp("2025-01-01T00:00:00Z")
        ).any():
            raise ValueError("Research-only strategy received a forbidden 2025+ decision candle")
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe = self._derive_directional_price_acceptance(dataframe)
        return self._merge_binance_sidecar(dataframe)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        dataframe = self._derive_directional_price_acceptance(dataframe)
        base_long = self._signal(dataframe, "enter_long")
        base_short = self._signal(dataframe, "enter_short")
        volume_ok = dataframe["relative_volume"].ge(0.80)
        taker_long = dataframe.get(
            "binance_taker_improved_long_10m", self._false(dataframe.index)
        ).fillna(False)
        taker_short = dataframe.get(
            "binance_taker_improved_short_10m", self._false(dataframe.index)
        ).fillna(False)
        source_complete = pd.to_datetime(
            dataframe.get("binance_source_complete_time"), utc=True, errors="coerce"
        )
        decision_time = pd.to_datetime(dataframe["date"], utc=True) + pd.Timedelta(minutes=15)
        taker_valid = (
            source_complete.notna()
            & source_complete.add(pd.Timedelta(minutes=15)).le(decision_time)
            & dataframe.get("constituent_5m_count", pd.Series(0, index=dataframe.index)).eq(3)
        )
        keep_long = base_long & volume_ok & (
            dataframe["directional_price_accept_long"] | (taker_valid & taker_long)
        )
        keep_short = base_short & volume_ok & (
            dataframe["directional_price_accept_short"] | (taker_valid & taker_short)
        )

        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0
        dataframe.loc[:, "enter_tag"] = None
        dataframe.loc[keep_long, ["enter_long", "enter_tag"]] = (
            1,
            "research_binance_taker_confirm_long",
        )
        dataframe.loc[keep_short, ["enter_short", "enter_tag"]] = (
            1,
            "research_binance_taker_confirm_short",
        )
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
        return min(1.0, max_leverage)
