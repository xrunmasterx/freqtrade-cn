from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar

import pandas as pd
from freqtrade.enums import MarginMode, RunMode, TradingMode
from freqtrade.exceptions import OperationalException
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy
from pandas import DataFrame


class DonchianLogisticProspectiveStrategy(IStrategy):
    """Execution-only adapter for the frozen prospective logistic predictions."""

    INTERFACE_VERSION = 3

    pair = "BTC/USDT:USDT"
    timeframe = "5m"
    can_short = True
    max_open_trades = 1
    stake_currency = "USDT"
    stake_amount = "unlimited"

    leverage_value = 14.0
    target_underlying_ratio = 0.04
    max_hold = timedelta(hours=48)

    minimal_roi: ClassVar[dict] = {}
    use_custom_roi = True
    stoploss = -0.21
    trailing_stop = False
    use_custom_stoploss = False
    position_adjustment_enable = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True
    startup_candle_count = 0

    order_types: ClassVar[dict] = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force: ClassVar[dict] = {"entry": "GTC", "exit": "GTC"}

    sidecar_config_key = "donchian_logistic_signal_sidecar"
    sidecar_columns = (
        "date",
        "execution_time",
        "computed_at",
        "projection_durable_at",
        "direction",
        "predicted_positive",
        "event_semantic_sha256",
        "projection_semantic_sha256",
        "publication_receipt_semantic_sha256",
    )
    prospective_boundary = pd.Timestamp("2026-08-14T00:00:00Z")
    _sha256_pattern = re.compile(r"[0-9a-f]{64}\Z")

    def bot_start(self, **kwargs) -> None:
        runmode = RunMode(self.config.get("runmode", RunMode.OTHER))
        if runmode != RunMode.BACKTEST:
            raise OperationalException("prospective candidate is authorized only for backtesting")
        self._validate_frozen_configuration()
        self._prospective_signals = self._read_signal_sidecar()
        self._validate_execution_environment()

    def _validate_frozen_configuration(self) -> None:
        self._validate_market_configuration()
        self._validate_wallet_configuration()
        self._validate_strategy_configuration()
        self._validate_sidecar_configuration()

    def _validate_market_configuration(self) -> None:
        exchange = self.config.get("exchange")
        if not isinstance(exchange, dict) or exchange.get("name", "").lower() != "okx":
            raise OperationalException("prospective candidate requires exchange.name=okx")
        if exchange.get("pair_whitelist") != [self.pair]:
            raise OperationalException("prospective candidate requires an exact BTC-only whitelist")
        if self.config.get("pairlists") != [{"method": "StaticPairList"}]:
            raise OperationalException("prospective candidate requires exactly one StaticPairList")
        if self.config.get("trading_mode") != TradingMode.FUTURES:
            raise OperationalException("prospective candidate requires futures trading mode")
        if self.config.get("margin_mode") != MarginMode.ISOLATED:
            raise OperationalException("prospective candidate requires isolated margin mode")
        if self.config.get("timeframe") != self.timeframe or self.timeframe != "5m":
            raise OperationalException("prospective candidate requires the frozen 5m timeframe")
        fee = self.config.get("fee")
        if isinstance(fee, bool) or fee not in (0.0006, 0.0010, 0.0015):
            raise OperationalException("candidate fee must be a frozen cost scenario")
        if "timeframe_detail" in self.config:
            raise OperationalException("no prospective detail timeframe is frozen")

    def _validate_wallet_configuration(self) -> None:
        if self.config.get("max_open_trades") != 1 or self.max_open_trades != 1:
            raise OperationalException("prospective candidate requires max_open_trades=1")
        if self.config.get("stake_currency") != "USDT" or self.stake_currency != "USDT":
            raise OperationalException("prospective candidate requires USDT stake currency")
        if self.config.get("stake_amount") != "unlimited" or self.stake_amount != "unlimited":
            raise OperationalException("prospective candidate requires unlimited stake")
        balance_ratio = self.config.get("tradable_balance_ratio")
        if isinstance(balance_ratio, bool) or balance_ratio != 1.0:
            raise OperationalException("prospective candidate requires tradable_balance_ratio=1.0")
        if self.config.get("dry_run_wallet") != 1000:
            raise OperationalException("prospective candidate requires a 1000 USDT starting wallet")
        if "available_capital" in self.config:
            raise OperationalException("available_capital would violate full-wallet compounding")
        if "futures_funding_rate" in self.config:
            raise OperationalException("synthetic funding fallback is forbidden")
        if self.config.get("position_stacking", False) is not False:
            raise OperationalException("position stacking is forbidden")

    def _validate_strategy_configuration(self) -> None:
        frozen_strategy_values = (
            self.can_short is True,
            self.leverage_value == 14.0,
            self.target_underlying_ratio == 0.04,
            self.max_hold == timedelta(hours=48),
            self.minimal_roi == {},
            self.use_custom_roi is True,
            self.stoploss == -0.21,
            self.trailing_stop is False,
            self.use_custom_stoploss is False,
            self.position_adjustment_enable is False,
            self.use_exit_signal is True,
            self.exit_profit_only is False,
            self.ignore_roi_if_entry_signal is False,
            self.process_only_new_candles is True,
            self.startup_candle_count == 0,
            self.order_types.get("entry") == "market",
            self.order_types.get("exit") == "market",
            self.order_types.get("stoploss") == "market",
            self.order_types.get("stoploss_on_exchange") is False,
        )
        if not all(frozen_strategy_values):
            raise OperationalException(
                "resolved strategy settings differ from the frozen candidate"
            )

    def _validate_sidecar_configuration(self) -> None:
        sidecar = self.config.get(self.sidecar_config_key)
        if not isinstance(sidecar, str) or not sidecar:
            raise OperationalException(f"explicit {self.sidecar_config_key} is required")
        sidecar_path = Path(sidecar)
        if not sidecar_path.is_absolute() or sidecar_path.suffix != ".feather":
            raise OperationalException("signal sidecar must be an absolute .feather path")

    def _validate_execution_environment(self) -> None:
        if self.wallets is None:
            raise OperationalException(
                "wallets are unavailable for full-wallet leverage validation"
            )
        if not hasattr(self, "dp"):
            raise OperationalException("data provider is unavailable for execution validation")
        if self.dp.current_whitelist() != [self.pair]:
            raise OperationalException(
                "runtime whitelist differs from the frozen BTC-only whitelist"
            )

        full_stake = float(self.wallets.get_total_stake_amount())
        if not math.isfinite(full_stake) or full_stake <= 0:
            raise OperationalException("full-wallet stake must be finite and positive")
        exchange = getattr(self.dp, "_exchange", None)
        if exchange is None:
            raise OperationalException("exchange is unavailable for leverage-tier validation")
        max_leverage = float(exchange.get_max_leverage(self.pair, full_stake))
        if not math.isfinite(max_leverage) or max_leverage < self.leverage_value:
            raise OperationalException(
                f"exchange permits only {max_leverage}x for full-wallet stake {full_stake}"
            )

    @classmethod
    def validate_signal_sidecar(cls, dataframe: DataFrame) -> DataFrame:
        if tuple(dataframe.columns) != cls.sidecar_columns:
            raise OperationalException("signal sidecar schema mismatch")
        result = dataframe.copy()
        cls._validate_signal_times(result)
        cls._validate_signal_values(result)
        return result

    @classmethod
    def _validate_signal_times(cls, result: DataFrame) -> None:
        for column in ("date", "execution_time", "computed_at", "projection_durable_at"):
            dtype = result[column].dtype
            if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
                raise OperationalException(f"signal sidecar {column} must be UTC datetime")
            if result[column].isna().any():
                raise OperationalException(f"signal sidecar {column} contains nulls")

        if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
            raise OperationalException("signal sidecar decisions must be unique and ordered")
        if not (result["date"] > cls.prospective_boundary).all():
            raise OperationalException("signal sidecar decision is not strictly prospective")
        expected_execution = result["date"] + pd.Timedelta(minutes=5)
        if not result["execution_time"].equals(expected_execution):
            raise OperationalException("signal sidecar execution_time must equal date + 5m")
        if not (
            (result["computed_at"] >= result["date"])
            & (result["computed_at"] < result["execution_time"])
        ).all():
            raise OperationalException("signal sidecar computed_at is outside [D,E)")
        if not (
            (result["projection_durable_at"] >= result["computed_at"])
            & (result["projection_durable_at"] < result["execution_time"])
        ).all():
            raise OperationalException(
                "signal sidecar lacks a pre-execution durable publication receipt"
            )

    @classmethod
    def _validate_signal_values(cls, result: DataFrame) -> None:
        if result["predicted_positive"].dtype != bool or not result[
            "predicted_positive"
        ].all():
            raise OperationalException("signal sidecar may contain only predicted_positive=true")
        if not result["direction"].isin(("long", "short")).all():
            raise OperationalException("signal sidecar direction must be long or short")
        for column in (
            "event_semantic_sha256",
            "projection_semantic_sha256",
            "publication_receipt_semantic_sha256",
        ):
            if result[column].duplicated().any() or not result[column].map(
                lambda value: isinstance(value, str)
                and cls._sha256_pattern.fullmatch(value) is not None
            ).all():
                raise OperationalException(f"signal sidecar {column} is invalid or duplicated")

    def _read_signal_sidecar(self) -> DataFrame:
        path = Path(self.config[self.sidecar_config_key])
        try:
            dataframe = pd.read_feather(path)
        except Exception as error:
            raise OperationalException(f"signal sidecar is unreadable: {path}") from error
        return self.validate_signal_sidecar(dataframe)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if metadata.get("pair") != self.pair:
            raise OperationalException("prospective candidate received an unexpected pair")
        if not hasattr(self, "_prospective_signals"):
            raise OperationalException("prospective signal sidecar was not loaded at bot_start")
        self._validate_candle_sequence(dataframe)

        lookup = self._prospective_signals.set_index("date")
        dataframe["prospective_direction"] = dataframe["date"].map(lookup["direction"])
        dataframe["prospective_event_sha256"] = dataframe["date"].map(
            lookup["event_semantic_sha256"]
        )
        return dataframe

    def _validate_candle_sequence(self, dataframe: DataFrame) -> None:
        if "date" not in dataframe or dataframe.empty:
            raise OperationalException("candle dataframe must contain date rows")
        dates = dataframe["date"]
        dtype = dates.dtype
        if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
            raise OperationalException("candle dates must be UTC datetime")
        if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
            raise OperationalException("candle dates must be unique and strictly ordered")
        if not dates.diff().iloc[1:].eq(pd.Timedelta(minutes=5)).all():
            raise OperationalException("candle rows must form a complete continuous 5m sequence")

        physical_dates = set(dates)
        decisions = set(self._prospective_signals["date"])
        executions = set(self._prospective_signals["execution_time"])
        if not decisions <= physical_dates:
            raise OperationalException("signal decision D lacks its physical candle row")
        if not executions <= physical_dates:
            raise OperationalException("signal execution E lacks its physical candle row")

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = (dataframe["prospective_direction"] == "long").astype(int)
        dataframe["enter_short"] = (dataframe["prospective_direction"] == "short").astype(int)
        for direction, signal_column in (("long", "enter_long"), ("short", "enter_short")):
            mask = dataframe[signal_column] == 1
            dataframe.loc[mask, "enter_tag"] = (
                "v8:" + direction + ":" + dataframe.loc[mask, "prospective_event_sha256"]
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
        # Freqtrade clips this value to max_leverage.  custom_stake_amount then sees the
        # clipped value and rejects the order unless it is still exactly 14x.
        return self.leverage_value

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
        if pair != self.pair or not math.isclose(
            leverage, self.leverage_value, rel_tol=0.0, abs_tol=1e-12
        ):
            return 0.0
        if max_stake + 1e-9 < proposed_stake:
            return 0.0
        return proposed_stake

    def custom_roi(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        trade_duration: int,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        target_rate = trade.open_rate * (
            1.0 - self.target_underlying_ratio
            if trade.is_short
            else 1.0 + self.target_underlying_ratio
        )
        return trade.calc_profit_ratio(target_rate)

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        if current_time >= trade.open_date_utc + self.max_hold:
            return "deadline_48h_open"
        return None
