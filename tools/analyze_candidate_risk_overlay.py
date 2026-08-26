from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_ROOT = ROOT / "freqtrade"
STRATEGY_DIR = ROOT / "ft_userdata" / "user_data" / "strategies"
DEFAULT_TIERS = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data"
    / "okx"
    / "futures"
    / "leverage_tiers_USDT.json"
)
PAIR = "BTC/USDT:USDT"
LEVERAGES = (1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 12.0, 14.0)
RISK_FRACTIONS = (0.005, 0.01, 0.02)
MARKET_TAKER_RATE = 0.0005
LIQUIDATION_BUFFER = 0.05
OKX_CONTRACT_VALUE_BTC = 0.01


@dataclass(frozen=True)
class OverlaySpec:
    name: str
    leverage: float
    stake_fraction_long: float
    stake_fraction_short: float
    target_risk_fraction: float | None
    planned_stop_risk_per_full_stake_long: float
    planned_stop_risk_per_full_stake_short: float
    target_is_capped_long: bool
    target_is_capped_short: bool
    minimal_roi: dict[str, float]
    stoploss: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scaled_ratio(reference_ratio: float, leverage: float, reference_leverage: float) -> float:
    if reference_leverage <= 0 or leverage <= 0:
        raise ValueError("leverage values must be positive")
    return reference_ratio * leverage / reference_leverage


def planned_stop_risk_per_full_stake(
    price_stop_distance: float,
    leverage: float,
    fee_per_side: float,
    *,
    is_short: bool,
) -> float:
    """Planned loss at the price stop, excluding unknowable future funding.

    Freqtrade's static futures stop is an account ratio. The corresponding price move is
    stoploss / leverage. Fees in the backtest are charged on leveraged notional, so both
    entry and exit costs are included here. The caller must report funding separately.
    """
    if price_stop_distance <= 0 or leverage <= 0 or fee_per_side < 0:
        raise ValueError("stop distance/leverage must be positive and fee must be non-negative")
    fee_cross_term = price_stop_distance * fee_per_side
    return leverage * (
        price_stop_distance
        + 2 * fee_per_side
        + (fee_cross_term if is_short else -fee_cross_term)
    )


def fixed_risk_stake_fraction(
    target_risk_fraction: float,
    price_stop_distance: float,
    leverage: float,
    fee_per_side: float,
    *,
    is_short: bool,
) -> tuple[float, bool]:
    if target_risk_fraction <= 0:
        raise ValueError("target risk must be positive")
    planned = planned_stop_risk_per_full_stake(
        price_stop_distance,
        leverage,
        fee_per_side,
        is_short=is_short,
    )
    uncapped = target_risk_fraction / planned
    return min(uncapped, 1.0), uncapped > 1.0


def scaled_roi(
    reference_roi: dict[str, float],
    leverage: float,
    reference_leverage: float,
) -> dict[str, float]:
    return {
        str(minute): scaled_ratio(float(value), leverage, reference_leverage)
        for minute, value in reference_roi.items()
    }


def longest_losing_streak(trades: list[dict[str, Any]]) -> int:
    longest = 0
    current = 0
    for trade in sorted(trades, key=lambda item: int(item["close_timestamp"])):
        if float(trade["profit_ratio"]) < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def profit_factor_abs(trades: list[dict[str, Any]]) -> float | str | None:
    wins = sum(
        float(trade["profit_abs"])
        for trade in trades
        if float(trade["profit_abs"]) > 0
    )
    losses = sum(
        float(trade["profit_abs"])
        for trade in trades
        if float(trade["profit_abs"]) < 0
    )
    if losses:
        return wins / abs(losses)
    return "+Infinity" if wins else None


def rolling_30d_stats(wallet: pd.DataFrame) -> dict[str, float | int | None]:
    """Return realized-wallet 30-day changes from the actual Freqtrade wallet path."""
    if wallet.empty:
        return {
            "observations": 0,
            "min_pct": None,
            "median_pct": None,
            "max_pct": None,
            "latest_pct": None,
            "positive_fraction": None,
        }
    frame = wallet[["date", "total_quote"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
    prior = frame["total_quote"].reindex(frame.index - pd.Timedelta(days=30)).to_numpy()
    current = frame["total_quote"].to_numpy()
    valid = pd.notna(prior) & (prior > 0)
    values = current[valid] / prior[valid] - 1
    if len(values) == 0:
        return {
            "observations": 0,
            "min_pct": None,
            "median_pct": None,
            "max_pct": None,
            "latest_pct": None,
            "positive_fraction": None,
        }
    return {
        "observations": len(values),
        "min_pct": float(values.min() * 100),
        "median_pct": float(pd.Series(values).median() * 100),
        "max_pct": float(values.max() * 100),
        "latest_pct": float(values[-1] * 100),
        "positive_fraction": float((values > 0).mean()),
    }


def _tier_for_engine_stake(
    tiers: list[dict[str, Any]],
    stake_amount: float,
) -> dict[str, Any]:
    for tier in reversed(tiers):
        if stake_amount >= float(tier["minNotional"]):
            return tier
    raise ValueError(f"no leverage tier for stake amount {stake_amount}")


def _tier_for_okx_contracts(
    tiers: list[dict[str, Any]],
    base_amount: float,
) -> tuple[dict[str, Any], float]:
    contracts = base_amount / OKX_CONTRACT_VALUE_BTC
    for tier in reversed(tiers):
        if contracts >= float(tier["minNotional"]):
            return tier, contracts
    raise ValueError(f"no leverage tier for {contracts} OKX contracts")


def liquidation_distances(
    leverage: float,
    maintenance_margin_rate: float,
    taker_rate: float = MARKET_TAKER_RATE,
    liquidation_buffer: float = LIQUIDATION_BUFFER,
) -> tuple[float, float, float, float]:
    """Return raw and Freqtrade-buffered long/short liquidation price distances."""
    maintenance_with_taker = maintenance_margin_rate + taker_rate
    numerator = 1 / leverage - maintenance_with_taker
    long_raw_distance = numerator / (1 - maintenance_with_taker)
    short_raw_distance = numerator / (1 + maintenance_with_taker)
    multiplier = 1 - liquidation_buffer
    return (
        long_raw_distance,
        short_raw_distance,
        long_raw_distance * multiplier,
        short_raw_distance * multiplier,
    )


def _load_result(result_zip: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    with zipfile.ZipFile(result_zip) as archive:
        result_member = next(
            name
            for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        )
        wallet_member = next(name for name in archive.namelist() if name.endswith("_wallet.feather"))
        payload = json.loads(archive.read(result_member))
        result = next(iter(payload["strategy"].values()))
        wallet = pd.read_feather(io.BytesIO(archive.read(wallet_member)))
    return result, wallet


def entry_equities(
    trades: list[dict[str, Any]],
    starting_balance: float,
) -> dict[int, float]:
    """Replay serial single-position equity immediately before each entry."""
    equity = starting_balance
    values = {}
    for index, trade in sorted(
        enumerate(trades),
        key=lambda item: (int(item[1]["open_timestamp"]), item[0]),
    ):
        values[index] = equity
        equity += float(trade["profit_abs"])
    return values


def summarize_result(
    result_zip: Path,
    spec: OverlaySpec,
    tiers: list[dict[str, Any]],
    price_stop_distance: float,
) -> dict[str, Any]:
    result, wallet = _load_result(result_zip)
    trades = list(result["trades"])
    actual_leverages = [float(trade["leverage"]) for trade in trades]
    if actual_leverages and any(
        abs(leverage - spec.leverage) > 1e-12 for leverage in actual_leverages
    ):
        raise RuntimeError(
            f"requested leverage {spec.leverage} was not honored: "
            f"observed {sorted(set(actual_leverages))}"
        )
    equities = entry_equities(trades, float(result["starting_balance"]))
    fee_cost = sum(
        float(trade["amount"])
        * (
            float(trade["open_rate"]) * float(trade["fee_open"])
            + float(trade["close_rate"]) * float(trade["fee_close"])
        )
        for trade in trades
    )
    funding_values = [float(trade.get("funding_fees", 0.0)) for trade in trades]
    trade_losses_equity = [
        float(trade["profit_abs"]) / equities[index]
        for index, trade in enumerate(trades)
        if float(trade["profit_abs"]) < 0
    ]
    actual_stake_fractions = [
        float(trade["stake_amount"]) / equities[index]
        for index, trade in enumerate(trades)
    ]
    actual_planned_risks = [
        actual_stake_fractions[index]
        * (
            spec.planned_stop_risk_per_full_stake_short
            if trade["is_short"]
            else spec.planned_stop_risk_per_full_stake_long
        )
        for index, trade in enumerate(trades)
    ]

    liquidation_rows = []
    for trade in trades:
        engine_tier = _tier_for_engine_stake(tiers, float(trade["stake_amount"]))
        okx_tier, okx_contracts = _tier_for_okx_contracts(tiers, float(trade["amount"]))
        engine_distances = liquidation_distances(
            float(trade["leverage"]),
            float(engine_tier["maintenanceMarginRate"]),
        )
        okx_tier_distances = liquidation_distances(
            float(trade["leverage"]),
            float(okx_tier["maintenanceMarginRate"]),
        )
        raw_index = 1 if trade["is_short"] else 0
        buffered_index = 3 if trade["is_short"] else 2
        engine_raw = engine_distances[raw_index]
        engine_buffered = engine_distances[buffered_index]
        okx_tier_raw = okx_tier_distances[raw_index]
        okx_tier_buffered = okx_tier_distances[buffered_index]
        liquidation_rows.append(
            {
                "engine_tier": int(engine_tier["tier"]),
                "engine_maintenance_margin_rate": float(
                    engine_tier["maintenanceMarginRate"]
                ),
                "engine_raw_price_distance": engine_raw,
                "engine_buffered_price_distance": engine_buffered,
                "stop_to_engine_raw_liquidation_margin": (
                    engine_raw - price_stop_distance
                ),
                "stop_to_engine_buffered_liquidation_margin": (
                    engine_buffered - price_stop_distance
                ),
                "okx_contract_count": okx_contracts,
                "okx_contract_tier": int(okx_tier["tier"]),
                "okx_contract_tier_maintenance_margin_rate": float(
                    okx_tier["maintenanceMarginRate"]
                ),
                "okx_tier_raw_price_distance_estimate": okx_tier_raw,
                "okx_tier_buffered_price_distance_estimate": okx_tier_buffered,
                "stop_to_okx_tier_buffered_liquidation_margin_estimate": (
                    okx_tier_buffered - price_stop_distance
                ),
            }
        )

    returns = [float(trade["profit_ratio"]) for trade in trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    payoff = (
        (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
        if wins and losses
        else None
    )
    return {
        "scenario": spec.name,
        "result_zip": str(result_zip),
        "result_zip_sha256": sha256_file(result_zip),
        "leverage": spec.leverage,
        "actual_leverage_min": min(actual_leverages) if actual_leverages else None,
        "actual_leverage_max": max(actual_leverages) if actual_leverages else None,
        "requested_leverage_honored": True if actual_leverages else None,
        "stake_fraction_requested_long": spec.stake_fraction_long,
        "stake_fraction_requested_short": spec.stake_fraction_short,
        "target_risk_pct": (
            spec.target_risk_fraction * 100
            if spec.target_risk_fraction is not None
            else None
        ),
        "target_is_capped_by_wallet_long": spec.target_is_capped_long,
        "target_is_capped_by_wallet_short": spec.target_is_capped_short,
        "planned_stop_risk_pct_ex_funding_long": (
            spec.stake_fraction_long * spec.planned_stop_risk_per_full_stake_long * 100
        ),
        "planned_stop_risk_pct_ex_funding_short": (
            spec.stake_fraction_short * spec.planned_stop_risk_per_full_stake_short * 100
        ),
        "actual_stake_fraction_of_entry_equity_min_pct": (
            min(actual_stake_fractions) * 100 if actual_stake_fractions else None
        ),
        "actual_stake_fraction_of_entry_equity_max_pct": (
            max(actual_stake_fractions) * 100 if actual_stake_fractions else None
        ),
        "max_actual_planned_stop_risk_pct_ex_funding": (
            max(actual_planned_risks) * 100 if actual_planned_risks else None
        ),
        "max_actual_planned_stop_risk_excess_target_basis_points": (
            max(
                0.0,
                max(
                    risk - spec.target_risk_fraction
                    for risk in actual_planned_risks
                ),
            )
            * 10_000
            if actual_planned_risks and spec.target_risk_fraction is not None
            else None
        ),
        "underlying_price_stop_distance_pct": price_stop_distance * 100,
        "account_stoploss_ratio_pct": abs(spec.stoploss) * 100,
        "minimal_roi_account_ratio_pct": {
            minute: value * 100 for minute, value in spec.minimal_roi.items()
        },
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / len(trades) * 100 if trades else None,
        "average_win_loss_ratio": payoff,
        "profit_factor": profit_factor_abs(trades),
        "account_return_pct": float(result["profit_total"]) * 100,
        "final_balance_usdt": float(result["final_balance"]),
        "max_account_drawdown_pct": float(result["max_drawdown_account"]) * 100,
        "max_relative_drawdown_pct": float(result["max_relative_drawdown"]) * 100,
        "liquidation_exit_count": sum(
            trade.get("exit_reason") == "liquidation" for trade in trades
        ),
        "longest_losing_streak": longest_losing_streak(trades),
        "fees_usdt": fee_cost,
        "funding_net_usdt": sum(funding_values),
        "funding_paid_usdt": abs(sum(value for value in funding_values if value < 0)),
        "funding_received_usdt": sum(value for value in funding_values if value > 0),
        "worst_realized_trade_loss_pct_of_entry_equity": (
            min(trade_losses_equity) * 100 if trade_losses_equity else None
        ),
        "rolling_30d_realized_wallet": rolling_30d_stats(wallet),
        "min_engine_raw_liquidation_price_distance_pct": (
            min(row["engine_raw_price_distance"] for row in liquidation_rows) * 100
            if liquidation_rows
            else None
        ),
        "min_engine_buffered_liquidation_price_distance_pct": (
            min(row["engine_buffered_price_distance"] for row in liquidation_rows) * 100
            if liquidation_rows
            else None
        ),
        "min_stop_to_engine_raw_liquidation_margin_pct_points": (
            min(
                row["stop_to_engine_raw_liquidation_margin"]
                for row in liquidation_rows
            )
            * 100
            if liquidation_rows
            else None
        ),
        "min_stop_to_engine_buffered_liquidation_margin_pct_points": (
            min(
                row["stop_to_engine_buffered_liquidation_margin"]
                for row in liquidation_rows
            )
            * 100
            if liquidation_rows
            else None
        ),
        "max_engine_maintenance_margin_rate_pct": (
            max(row["engine_maintenance_margin_rate"] for row in liquidation_rows) * 100
            if liquidation_rows
            else None
        ),
        "engine_vs_okx_contract_tier_mismatch_trades": sum(
            row["engine_tier"] != row["okx_contract_tier"] for row in liquidation_rows
        ),
        "max_okx_contract_count": (
            max(row["okx_contract_count"] for row in liquidation_rows)
            if liquidation_rows
            else None
        ),
        "min_okx_tier_raw_liquidation_price_distance_estimate_pct": (
            min(row["okx_tier_raw_price_distance_estimate"] for row in liquidation_rows)
            * 100
            if liquidation_rows
            else None
        ),
        "min_okx_tier_buffered_liquidation_price_distance_estimate_pct": (
            min(
                row["okx_tier_buffered_price_distance_estimate"]
                for row in liquidation_rows
            )
            * 100
            if liquidation_rows
            else None
        ),
        "min_stop_to_okx_tier_buffered_liquidation_margin_estimate_pct_points": (
            min(
                row["stop_to_okx_tier_buffered_liquidation_margin_estimate"]
                for row in liquidation_rows
            )
            * 100
            if liquidation_rows
            else None
        ),
    }


def _format_class_number(value: float) -> str:
    return str(value).replace(".", "p")


def build_specs(
    reference_roi: dict[str, float],
    reference_stoploss: float,
    reference_leverage: float,
    fee_per_side: float,
    leverages: list[float],
    risks: list[float],
) -> list[OverlaySpec]:
    price_stop_distance = abs(reference_stoploss) / reference_leverage
    specs: list[OverlaySpec] = []
    for leverage in leverages:
        account_stoploss = -price_stop_distance * leverage
        roi = scaled_roi(reference_roi, leverage, reference_leverage)
        planned_long = planned_stop_risk_per_full_stake(
            price_stop_distance,
            leverage,
            fee_per_side,
            is_short=False,
        )
        planned_short = planned_stop_risk_per_full_stake(
            price_stop_distance,
            leverage,
            fee_per_side,
            is_short=True,
        )
        specs.append(
            OverlaySpec(
                name=f"full_L{_format_class_number(leverage)}",
                leverage=leverage,
                stake_fraction_long=1.0,
                stake_fraction_short=1.0,
                target_risk_fraction=None,
                planned_stop_risk_per_full_stake_long=planned_long,
                planned_stop_risk_per_full_stake_short=planned_short,
                target_is_capped_long=False,
                target_is_capped_short=False,
                minimal_roi=roi,
                stoploss=account_stoploss,
            )
        )
        for risk in risks:
            fraction_long, capped_long = fixed_risk_stake_fraction(
                risk,
                price_stop_distance,
                leverage,
                fee_per_side,
                is_short=False,
            )
            fraction_short, capped_short = fixed_risk_stake_fraction(
                risk,
                price_stop_distance,
                leverage,
                fee_per_side,
                is_short=True,
            )
            specs.append(
                OverlaySpec(
                    name=(
                        f"risk_{_format_class_number(risk * 100)}pct_"
                        f"L{_format_class_number(leverage)}"
                    ),
                    leverage=leverage,
                    stake_fraction_long=fraction_long,
                    stake_fraction_short=fraction_short,
                    target_risk_fraction=risk,
                    planned_stop_risk_per_full_stake_long=planned_long,
                    planned_stop_risk_per_full_stake_short=planned_short,
                    target_is_capped_long=capped_long,
                    target_is_capped_short=capped_short,
                    minimal_roi=roi,
                    stoploss=account_stoploss,
                )
            )
    return specs


def render_overlay(
    module_name: str,
    strategy_class: str,
    overlay_class: str,
    spec: OverlaySpec,
) -> str:
    roi = repr(spec.minimal_roi)
    return f'''from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from {module_name} import {strategy_class}


class {overlay_class}({strategy_class}):
    """Generated risk overlay; alpha indicators and signals are inherited unchanged."""

    minimal_roi: ClassVar[dict[str, float]] = {roi}
    stoploss = {spec.stoploss!r}
    risk_overlay_leverage = {spec.leverage!r}
    risk_overlay_stake_fraction_long = {spec.stake_fraction_long!r}
    risk_overlay_stake_fraction_short = {spec.stake_fraction_short!r}

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
        return min(self.risk_overlay_leverage, max_leverage)

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
        fraction = (
            self.risk_overlay_stake_fraction_short
            if side == "short"
            else self.risk_overlay_stake_fraction_long
        )
        equity = self.wallets.get_total_stake_amount()
        stake = min(equity * fraction, proposed_stake, max_stake)
        if min_stake is not None and stake < min_stake:
            return 0.0
        return stake
'''


def _offline_market() -> dict[str, Any]:
    return {
        "id": "BTC-USDT-SWAP",
        "symbol": PAIR,
        "base": "BTC",
        "quote": "USDT",
        "settle": "USDT",
        "baseId": "BTC",
        "quoteId": "USDT",
        "settleId": "USDT",
        "type": "swap",
        "spot": False,
        "margin": False,
        "swap": True,
        "future": False,
        "option": False,
        "active": True,
        "contract": True,
        "linear": True,
        "inverse": False,
        "contractSize": OKX_CONTRACT_VALUE_BTC,
        "maker": 0.0002,
        "taker": MARKET_TAKER_RATE,
        "percentage": True,
        "tierBased": True,
        "precision": {"amount": 0.01, "price": 0.1, "base": None, "quote": None},
        "limits": {
            "leverage": {"min": 1.0, "max": 100.0},
            "amount": {"min": 0.01, "max": None},
            "price": {"min": None, "max": None},
            "cost": {"min": None, "max": None},
        },
        "info": {},
    }


def worker(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(FREQTRADE_ROOT))
    sys.path.insert(0, str(STRATEGY_DIR))
    from freqtrade.exchange.exchange import Exchange
    from freqtrade.main import main as freqtrade_main

    def offline_reload_markets(
        exchange: Exchange,
        force: bool = False,
        *,
        load_leverage_tiers: bool = True,
    ) -> None:
        exchange._api_async.set_markets([_offline_market()])
        exchange._api.set_markets_from_exchange(exchange._api_async)
        exchange._markets = dict(exchange._api_async.markets)
        exchange._last_markets_refresh = 1

    command = [
        "backtesting",
        "--config",
        str(args.config),
        "--userdir",
        str(ROOT / "ft_userdata" / "user_data"),
        "--strategy-path",
        str(args.overlay_dir),
        "--strategy",
        args.overlay_class,
        "--datadir",
        str(args.datadir),
        "--pairs",
        PAIR,
        "--timeframe",
        args.timeframe,
        "--timeframe-detail",
        args.timeframe_detail,
        "--timerange",
        args.timerange,
        "--fee",
        str(args.fee),
        "--cache",
        "none",
        "--export",
        "trades",
        "--backtest-directory",
        str(args.output),
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    with patch.object(Exchange, "reload_markets", offline_reload_markets):
        try:
            freqtrade_main(command)
        except SystemExit as error:
            return int(error.code or 0)
    return 0


def _write_config(path: Path, funding_fallback: float) -> None:
    payload = {
        "$schema": "https://schema.freqtrade.io/schema.json",
        "max_open_trades": 1,
        "stake_currency": "USDT",
        "stake_amount": "unlimited",
        "tradable_balance_ratio": 1.0,
        "dry_run": True,
        "dry_run_wallet": 1000,
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "liquidation_buffer": LIQUIDATION_BUFFER,
        "futures_funding_rate": funding_fallback,
        "entry_pricing": {"price_side": "other", "use_order_book": False},
        "exit_pricing": {"price_side": "other", "use_order_book": False},
        "exchange": {
            "name": "okx",
            "key": "",
            "secret": "",
            "password": "",
            "ccxt_config": {"options": {"defaultType": "swap"}},
            "ccxt_async_config": {},
            "pair_whitelist": [PAIR],
            "pair_blacklist": [],
        },
        "pairlists": [{"method": "StaticPairList"}],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _copy_data(
    source: Path,
    target: Path,
    tiers: Path,
    timeframe: str,
    timeframe_detail: str,
) -> list[Path]:
    source_futures = source / "futures"
    target_futures = target / "futures"
    target_futures.mkdir(parents=True)
    required = {
        f"BTC_USDT_USDT-{timeframe}-futures.feather",
        f"BTC_USDT_USDT-{timeframe_detail}-futures.feather",
        "BTC_USDT_USDT-1h-mark.feather",
        "BTC_USDT_USDT-1h-funding_rate.feather",
    }
    missing = sorted(name for name in required if not (source_futures / name).is_file())
    if missing:
        raise FileNotFoundError(f"required market data is missing: {', '.join(missing)}")
    copied = []
    for source_file in sorted(source_futures.glob("BTC_USDT_USDT-*.feather")):
        target_file = target_futures / source_file.name
        shutil.copy2(source_file, target_file)
        copied.append(target_file)
    shutil.copy2(tiers, target_futures / tiers.name)
    return copied


def _load_reference(module_name: str, strategy_class: str) -> type:
    sys.path.insert(0, str(FREQTRADE_ROOT))
    sys.path.insert(0, str(STRATEGY_DIR))
    module = importlib.import_module(module_name)
    return getattr(module, strategy_class)


def _validate_static_risk_overlay(strategy: type) -> None:
    unsupported = []
    if bool(getattr(strategy, "use_custom_stoploss", False)):
        unsupported.append("use_custom_stoploss")
    if bool(getattr(strategy, "trailing_stop", False)):
        unsupported.append("trailing_stop")
    if bool(getattr(strategy, "position_adjustment_enable", False)):
        unsupported.append("position_adjustment_enable")
    if unsupported:
        raise ValueError(
            "generic risk overlay supports static one-entry risk only; unsupported: "
            + ", ".join(unsupported)
        )


def controller(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    source_file = STRATEGY_DIR / f"{args.strategy_module}.py"
    if not source_file.is_file():
        raise FileNotFoundError(source_file)
    strategy = _load_reference(
        args.strategy_module,
        args.strategy_class,
    )
    _validate_static_risk_overlay(strategy)
    reference_roi = {
        str(key): float(value) for key, value in strategy.minimal_roi.items()
    }
    reference_stoploss = float(strategy.stoploss)
    reference_leverage = float(getattr(strategy, "default_leverage", 1.0))
    timeframe = args.timeframe or str(strategy.timeframe)
    price_stop_distance = abs(reference_stoploss) / reference_leverage
    specs = build_specs(
        reference_roi,
        reference_stoploss,
        reference_leverage,
        args.fee,
        args.leverages,
        args.risks,
    )
    tiers_payload = json.loads(args.tiers.read_text(encoding="utf-8"))
    tiers = tiers_payload["data"][PAIR]
    overlay_dir = args.output / "overlays"
    overlay_dir.mkdir(exist_ok=True)
    config = args.output / "risk-overlay-config.json"
    _write_config(config, args.funding_fallback)

    summaries = []
    with tempfile.TemporaryDirectory(prefix="freqtrade-risk-overlay-") as temporary:
        staged_data = Path(temporary) / "data"
        copied = _copy_data(
            args.datadir,
            staged_data,
            args.tiers,
            timeframe,
            args.timeframe_detail,
        )
        source_hashes = {
            str(path.relative_to(staged_data)): sha256_file(path) for path in copied
        }
        for index, spec in enumerate(specs, start=1):
            overlay_class = f"RiskOverlay{index:02d}Strategy"
            overlay_file = overlay_dir / f"{overlay_class}.py"
            overlay_file.write_text(
                render_overlay(
                    args.strategy_module,
                    args.strategy_class,
                    overlay_class,
                    spec,
                ),
                encoding="utf-8",
            )
            scenario_output = args.output / "runs" / spec.name
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "_worker",
                "--config",
                str(config),
                "--overlay-dir",
                str(overlay_dir),
                "--overlay-class",
                overlay_class,
                "--datadir",
                str(staged_data),
                "--timerange",
                args.timerange,
                "--timeframe",
                timeframe,
                "--timeframe-detail",
                args.timeframe_detail,
                "--fee",
                str(args.fee),
                "--output",
                str(scenario_output),
            ]
            completed = subprocess.run(command, cwd=ROOT, check=False)
            if completed.returncode != 0:
                raise RuntimeError(f"Freqtrade failed for {spec.name}: {completed.returncode}")
            result_zip = max(scenario_output.glob("*.zip"), key=lambda path: path.stat().st_mtime_ns)
            summary = summarize_result(
                result_zip,
                spec,
                tiers,
                price_stop_distance,
            )
            summary["generated_overlay_sha256"] = sha256_file(overlay_file)
            summaries.append(summary)
        post_run_hashes = {
            str(path.relative_to(staged_data)): sha256_file(path) for path in copied
        }
        if post_run_hashes != source_hashes:
            raise RuntimeError("staged market data changed during risk overlay runs")

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": "completed",
        "runner": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "strategy": {
            "module": args.strategy_module,
            "class": args.strategy_class,
            "source": str(source_file),
            "sha256": sha256_file(source_file),
            "reference_leverage": reference_leverage,
            "reference_stoploss_account_ratio": reference_stoploss,
            "reference_minimal_roi_account_ratio": reference_roi,
            "underlying_price_stop_distance": price_stop_distance,
        },
        "simulation": {
            "pair": PAIR,
            "timerange": args.timerange,
            "timeframe": timeframe,
            "timeframe_detail": args.timeframe_detail,
            "fee_per_side": args.fee,
            "fee_note": "cash cost proxy; configured as Freqtrade fee, not shifted fill prices",
            "funding_fallback_hourly": args.funding_fallback,
            "funding_note": "actual retained funding is used where present; fallback is hourly",
            "starting_wallet_usdt": 1000,
            "stake_amount": "unlimited before risk overlay",
            "margin_mode": "isolated",
            "liquidation_buffer": LIQUIDATION_BUFFER,
            "liquidation_taker_rate": MARKET_TAKER_RATE,
            "okx_contract_value_btc": OKX_CONTRACT_VALUE_BTC,
            "fixed_risk_definition": (
                "side-specific stake_fraction = target_equity_risk / exact planned cash "
                "loss at the static price stop; long denominator is leverage * "
                "(distance + 2*fee - distance*fee), short uses + distance*fee; capped at "
                "100%; future funding and stop gaps are excluded from sizing and reported ex post"
            ),
            "rolling_30d_definition": (
                "realized Freqtrade wallet total_quote change versus the exact timestamp "
                "30 calendar days earlier"
            ),
        },
        "inputs": {
            "data_root": str(args.datadir),
            "data_sha256": source_hashes,
            "tiers": str(args.tiers),
            "tiers_sha256": sha256_file(args.tiers),
            "generated_config_sha256": sha256_file(config),
        },
        "results": summaries,
        "limitations": [
            "This changes only leverage, account-scaled ROI/stop, and stake sizing; alpha signals are inherited.",
            "The generic runner fails closed for custom stoploss, trailing stop, or position adjustment strategies.",
            "Under current Freqtrade semantics the funding fallback fills only leading gaps; post-first-observation gaps are dropped and remain unmodeled.",
            "The fee includes the selected slippage proxy as a cash cost; trigger prices are not shifted.",
            "Fixed-risk sizing excludes unknowable future funding, stop gaps, and slippage beyond the stated cash proxy.",
            "Account and relative drawdown plus rolling 30d use realized wallet balance, not intratrade mark-to-market equity.",
            "Liquidation distances mirror the current Freqtrade engine, which selects OKX maintenance tiers using exported stake_amount.",
            "The OKX-tier estimate converts base amount to contracts using the current 0.01 BTC contract value, but is not a historical tier reconstruction or a live exchange liquidation price.",
            "A historical backtest cannot guarantee future compounding or absence of overfitting.",
        ],
    }
    (args.output / "risk-overlay-summary.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    worker_parser = subparsers.add_parser("_worker")
    worker_parser.add_argument("--config", type=Path, required=True)
    worker_parser.add_argument("--overlay-dir", type=Path, required=True)
    worker_parser.add_argument("--overlay-class", required=True)
    worker_parser.add_argument("--datadir", type=Path, required=True)
    worker_parser.add_argument("--timerange", required=True)
    worker_parser.add_argument("--timeframe", required=True)
    worker_parser.add_argument("--timeframe-detail", required=True)
    worker_parser.add_argument("--fee", type=float, required=True)
    worker_parser.add_argument("--output", type=Path, required=True)

    parser.add_argument("--strategy-module")
    parser.add_argument("--strategy-class")
    parser.add_argument("--datadir", type=Path)
    parser.add_argument("--tiers", type=Path, default=DEFAULT_TIERS)
    parser.add_argument("--timerange")
    parser.add_argument("--timeframe")
    parser.add_argument("--timeframe-detail", default="5m")
    parser.add_argument("--fee", type=float, default=0.0006)
    parser.add_argument("--funding-fallback", type=float)
    parser.add_argument("--leverages", type=float, nargs="+", default=list(LEVERAGES))
    parser.add_argument("--risks", type=float, nargs="*", default=list(RISK_FRACTIONS))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command != "_worker":
        required = (
            "strategy_module",
            "strategy_class",
            "datadir",
            "timerange",
            "funding_fallback",
            "output",
        )
        missing = [name for name in required if getattr(args, name) is None]
        if missing:
            parser.error(f"missing required arguments: {', '.join(missing)}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return worker(args) if args.command == "_worker" else controller(args)


if __name__ == "__main__":
    raise SystemExit(main())
