from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_ROOT = ROOT / "freqtrade"
sys.path.insert(0, str(FREQTRADE_ROOT))

from freqtrade.exchange.exchange import Exchange
from freqtrade.main import main as freqtrade_main

SOURCE_ROOT = (
    ROOT
    / "ft_userdata"
    / "user_data"
    / "data"
    / "okx-btc-usdt-swap-full-20260813"
)
SOURCE_DATA = SOURCE_ROOT / "market-data" / "futures"
RESULT_ROOT = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "goal-100pct"
    / "pine-cost-aware-full-history"
)
DERIVED_DATA = RESULT_ROOT / "derived-market-data"
DERIVED_FUTURES = DERIVED_DATA / "futures"
STRATEGY_FILE = (
    ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "PineCostAwareFullHistoryStrategy.py"
)
CONFIG_FILE = (
    ROOT
    / "ft_userdata"
    / "user_data"
    / "config.pine-cost-aware-full-history.json"
)
LEVERAGE_TIER_CACHE = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data"
    / "okx"
    / "futures"
    / "leverage_tiers_USDT.json"
)
LEVERAGE_TIER_CACHE_SHA256 = (
    "abc2d7352f237a6ce5a99da7ebc2b320b9584ce13f0d5296943e7713bf4f9825"
)
PREREGISTRATION = RESULT_ROOT / "preregistration.json"
FREEZE_RECEIPT = RESULT_ROOT / "freeze-receipt.json"
REJECTION_RECEIPT = RESULT_ROOT / "freeze-rejection.json"

DATASET_MANIFEST_SHA256 = "29f2f05d3c56af598084eb48eabec213f56555f7848f9c2b16ccbac3ae8282cf"
SOURCE_HASHES = {
    "BTC_USDT_USDT-5m-futures.feather": (
        "77b4e092736cf2f4484555e6c3c76db30dbe78508aeb1c03d2aceafdaa948851"
    ),
    "BTC_USDT_USDT-15m-futures.feather": (
        "078f646d904a2964f66b5f0eb40f8e055396a5a43ed994cb25c8d52710626407"
    ),
    "BTC_USDT_USDT-1h-futures.feather": (
        "79936e1c0a851ed6d57a74b0ad541d96cfb0f2d3cff78c52c1d687e166f77db1"
    ),
    "BTC_USDT_USDT-1h-mark.feather": (
        "f887657e694c4627cd3b7f4b42b2ad2e24d663c1892013b29e07c7f375d81143"
    ),
    "BTC_USDT_USDT-1h-funding_rate.feather": (
        "aa7d097b60b59b063b6c428d71f9f24983c85d9a1aa8892bc7ee6a28a343d0e4"
    ),
}

STAGES = {
    "development": {
        "timerange": "1646092800-1704067199",
        "start": 1646092800,
        "end": 1704067199,
    },
    "validation": {
        "timerange": "1704067200-1735689599",
        "start": 1704067200,
        "end": 1735689599,
    },
    "pseudo-oos": {
        "timerange": "1735689600-1786492799",
        "start": 1735689600,
        "end": 1786492799,
    },
}
COST_SCENARIOS = {
    "baseline": {
        "fee_each_side": 0.0006,
        "meaning": "OKX taker fee proxy; no extra slippage",
    },
    "stress_2bp": {
        "fee_each_side": 0.0008,
        "meaning": "0.06% taker fee + 0.02% slippage proxy per side",
    },
}
FUNDING_FALLBACK_SCENARIOS = {
    "hourly_8h_mean_div_8": 0.0000042304172276700455,
    "zero": 0.0,
    "adverse_positive": 0.0000042304172276700455,
    "adverse_negative": -0.0000042304172276700455,
}
CANDIDATES = {
    "PineCostAwareFullHistory15mStrategy": {"timeframe": "15m", "filter": "none"},
    "PineCostAwareFullHistory15mAdxStrategy": {"timeframe": "15m", "filter": "adx"},
    "PineCostAwareFullHistory15mRvStrategy": {"timeframe": "15m", "filter": "rv"},
    "PineCostAwareFullHistory30mStrategy": {"timeframe": "30m", "filter": "none"},
    "PineCostAwareFullHistory30mAdxStrategy": {"timeframe": "30m", "filter": "adx"},
    "PineCostAwareFullHistory30mRvStrategy": {"timeframe": "30m", "filter": "rv"},
    "PineCostAwareFullHistory1hStrategy": {"timeframe": "1h", "filter": "none"},
    "PineCostAwareFullHistory1hAdxStrategy": {"timeframe": "1h", "filter": "adx"},
    "PineCostAwareFullHistory1hRvStrategy": {"timeframe": "1h", "filter": "rv"},
    "PineCostAwareFullHistory2hStrategy": {"timeframe": "2h", "filter": "none"},
    "PineCostAwareFullHistory2hAdxStrategy": {"timeframe": "2h", "filter": "adx"},
    "PineCostAwareFullHistory2hRvStrategy": {"timeframe": "2h", "filter": "rv"},
}
MIN_TRADES = {"development": 60, "validation": 30}
MAX_DRAWDOWN_PCT = 30.0

OFFLINE_MARKET = {
    "id": "BTC-USDT-SWAP",
    "symbol": "BTC/USDT:USDT",
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
    "contractSize": 0.0001,
    "taker": 0.0006,
    "maker": 0.0002,
    "percentage": True,
    "tierBased": True,
    "precision": {"amount": 1.0, "price": 0.1, "base": None, "quote": None},
    "limits": {
        "leverage": {"min": 1.0, "max": 100.0},
        "amount": {"min": 1.0, "max": None},
        "price": {"min": None, "max": None},
        "cost": {"min": None, "max": None},
    },
    "info": {},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def verify_sources() -> None:
    manifest = SOURCE_ROOT / "dataset-manifest.json"
    if sha256_file(manifest) != DATASET_MANIFEST_SHA256:
        raise RuntimeError("dataset-manifest.json SHA256 differs from the frozen dataset")
    for filename, expected in SOURCE_HASHES.items():
        path = SOURCE_DATA / filename
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"source data is missing or changed: {path}")
    if sha256_file(LEVERAGE_TIER_CACHE) != LEVERAGE_TIER_CACHE_SHA256:
        raise RuntimeError("OKX leverage-tier cache SHA256 differs from the frozen context")


def resample_ohlcv(source: Path, target: Path, rule: str, expected_rows: int) -> None:
    frame = pd.read_feather(source).sort_values("date")
    indexed = frame.set_index("date")
    grouped = indexed.resample(rule, origin="epoch", label="left", closed="left")
    counts = grouped["close"].count()
    result = grouped.agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    result = result.loc[counts == expected_rows].dropna().reset_index()
    if result.empty or result["date"].duplicated().any():
        raise RuntimeError(f"invalid resample result: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    result.to_feather(target)


def prepare_derived_data() -> dict[str, str]:
    verify_sources()
    DERIVED_FUTURES.mkdir(parents=True, exist_ok=True)
    for filename, expected in SOURCE_HASHES.items():
        source = SOURCE_DATA / filename
        target = DERIVED_FUTURES / filename
        if target.exists():
            if sha256_file(target) != expected:
                raise RuntimeError(f"derived copy changed: {target}")
        else:
            shutil.copy2(source, target)

    derived_specs = (
        (
            "BTC_USDT_USDT-15m-futures.feather",
            "BTC_USDT_USDT-30m-futures.feather",
            "30min",
            2,
        ),
        (
            "BTC_USDT_USDT-1h-futures.feather",
            "BTC_USDT_USDT-2h-futures.feather",
            "2h",
            2,
        ),
    )
    for source_name, target_name, rule, expected_rows in derived_specs:
        target = DERIVED_FUTURES / target_name
        if not target.exists():
            resample_ohlcv(
                DERIVED_FUTURES / source_name,
                target,
                rule,
                expected_rows,
            )
    return {
        path.name: sha256_file(path)
        for path in sorted(DERIVED_FUTURES.glob("*.feather"))
    }


def preregistration_payload(derived_hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "scope": "Pine Cost-Aware Full-History bounded research",
        "created_before_performance_read": True,
        "pair": "BTC/USDT:USDT",
        "data_root": str(SOURCE_ROOT.relative_to(ROOT)),
        "dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
        "source_hashes": SOURCE_HASHES,
        "leverage_tier_cache_sha256": LEVERAGE_TIER_CACHE_SHA256,
        "derived_hashes": derived_hashes,
        "strategy_sha256": sha256_file(STRATEGY_FILE),
        "config_sha256": sha256_file(CONFIG_FILE),
        "runner_sha256": sha256_file(Path(__file__)),
        "stages": STAGES,
        "candidates": CANDIDATES,
        "cost_scenarios": COST_SCENARIOS,
        "funding_fallback_scenarios": FUNDING_FALLBACK_SCENARIOS,
        "funding": {
            "mode": "actual OKX rows with Freqtrade leading-gap fallback",
            "fallback_rate": 0.0000042304172276700455,
            "fallback_derivation": "frozen 8h mean 0.000033843337821360364 divided by 8 because Freqtrade fills 1h mark rows",
            "coverage_note": "All requested stages start after real funding begins, so leading fallback should not be used.",
        },
        "execution": {
            "timeframe_detail": "5m",
            "closed_candle_entry": True,
            "entry_fill": "next main-candle open under standard Freqtrade backtesting",
            "wallet": 1000,
            "stake_amount": "unlimited",
            "max_open_trades": 1,
            "leverage": 1.0,
        },
        "candidate_family": {
            "entry": "prior Donchian 20 first closed-candle breakout, long and short",
            "hard_stop_before_activation": "2.5 * closed ATR(14) anchored to entry",
            "activation": "0.16% underlying move, covering 0.06% fee + 0.02% slippage each side",
            "stop_after_activation": "monotonic 2.5 * latest closed ATR(14) trail",
            "optional_filter": "none, ADX(14)>=20, or RV(20)>=lagged rolling-median(80)",
        },
        "selection_gates": {
            "both_development_and_validation_and_both_cost_scenarios": True,
            "minimum_trades": MIN_TRADES,
            "compound_return_pct": ">0",
            "winrate_pct": ">=40",
            "strict_average_payoff": ">=2 and finite",
            "profit_factor": ">1 and finite",
            "max_drawdown_pct": f"<={MAX_DRAWDOWN_PCT}",
            "liquidations": 0,
            "left_open_trades": 0,
        },
        "selection_order": [
            "maximize minimum PF across development/validation and both costs",
            "maximize minimum compound return across development/validation and both costs",
            "minimize maximum drawdown across development/validation and both costs",
            "candidate name ascending",
        ],
        "risk_layer": "1x isolated; no leverage optimization in this bounded study",
        "pseudo_oos_policy": (
            "May run only the one frozen winner after strategy/config/runner/data hashes are bound; "
            "a failure cannot be tuned on this interval."
        ),
    }


def ensure_preregistration() -> dict[str, Any]:
    derived_hashes = prepare_derived_data()
    expected = preregistration_payload(derived_hashes)
    if PREREGISTRATION.exists():
        actual = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
        if actual != expected:
            raise RuntimeError("preregistration differs from current code/config/data; fail closed")
    else:
        write_json(PREREGISTRATION, expected)
    return expected


def offline_reload_markets(
    exchange: Exchange,
    force: bool = False,
    *,
    load_leverage_tiers: bool = True,
) -> None:
    exchange._api_async.set_markets([OFFLINE_MARKET])
    exchange._api.set_markets_from_exchange(exchange._api_async)
    exchange._markets = dict(exchange._api_async.markets)
    tiers = json.loads(LEVERAGE_TIER_CACHE.read_text(encoding="utf-8"))["data"]
    exchange._leverage_tiers = {
        "BTC/USDT:USDT": [exchange.parse_leverage_tier(tier) for tier in tiers["BTC/USDT:USDT"]]
    }
    exchange._last_markets_refresh = 1


def metric_ratio(values: list[float]) -> dict[str, Any]:
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    if not winners or not losers:
        return {"value": None, "status": "insufficient_winner_or_loser_sample"}
    return {
        "value": (sum(winners) / len(winners)) / abs(sum(losers) / len(losers)),
        "status": "finite",
    }


def profit_factor(values: list[float]) -> dict[str, Any]:
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = abs(sum(value for value in values if value < 0))
    if gross_loss == 0:
        if gross_profit > 0:
            return {"value": None, "status": "infinite"}
        return {"value": None, "status": "no_profit_or_loss"}
    return {"value": gross_profit / gross_loss, "status": "finite"}


def direction_metrics(trades: list[dict[str, Any]], is_short: bool) -> dict[str, Any]:
    selected = [trade for trade in trades if bool(trade["is_short"]) is is_short]
    ratios = [float(trade["profit_ratio"]) for trade in selected]
    absolutes = [float(trade["profit_abs"]) for trade in selected]
    wins = sum(value > 0 for value in absolutes)
    return {
        "trades": len(selected),
        "wins": wins,
        "losses": sum(value < 0 for value in absolutes),
        "draws": sum(value == 0 for value in absolutes),
        "winrate_pct": None if not selected else wins / len(selected) * 100.0,
        "strict_average_payoff": metric_ratio(ratios),
        "profit_factor": profit_factor(absolutes),
        "profit_abs": sum(absolutes),
    }


def load_result(zip_path: Path, strategy: str) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as archive:
        result_entries = [
            name
            for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        if len(result_entries) != 1:
            raise RuntimeError(f"expected one result JSON in {zip_path}: {result_entries}")
        payload = json.loads(archive.read(result_entries[0]))
    if set(payload.get("strategy", {})) != {strategy}:
        raise RuntimeError(f"unexpected strategy payload in {zip_path}")
    return payload["strategy"][strategy]


def extract_metrics(
    result: dict[str, Any],
    *,
    stage: str,
    strategy: str,
    cost_scenario: str,
    zip_path: Path,
) -> dict[str, Any]:
    trades = result["trades"]
    start = STAGES[stage]["start"] * 1000
    end = STAGES[stage]["end"] * 1000
    if any(int(trade["open_timestamp"]) < start for trade in trades):
        raise RuntimeError("trade opened before the frozen stage")
    if any(int(trade["close_timestamp"]) > end for trade in trades):
        raise RuntimeError("trade closed after the frozen stage")

    ratios = [float(trade["profit_ratio"]) for trade in trades]
    absolutes = [float(trade["profit_abs"]) for trade in trades]
    wins = sum(value > 0 for value in absolutes)
    starting_balance = float(result["starting_balance"])
    final_balance = float(result["final_balance"])
    if not math.isclose(
        final_balance,
        starting_balance + sum(absolutes),
        rel_tol=1e-8,
        abs_tol=1e-5,
    ):
        raise RuntimeError("trade PnL does not reconcile to final balance")

    modeled_execution_cost = 0.0
    for trade in trades:
        for order in trade.get("orders", []):
            fee_rate = float(trade["fee_open"] if order["ft_is_entry"] else trade["fee_close"])
            modeled_execution_cost += float(order["cost"]) * fee_rate
    funding = [float(trade.get("funding_fees") or 0.0) for trade in trades]
    left_open_count = len(result.get("left_open_trades", []))
    liquidation_count = sum(trade["exit_reason"] == "liquidation" for trade in trades)
    return {
        "stage": stage,
        "candidate": strategy,
        "timeframe": result["timeframe"],
        "timeframe_detail": result["timeframe_detail"],
        "timerange": STAGES[stage]["timerange"],
        "cost_scenario": cost_scenario,
        "fee_each_side": COST_SCENARIOS[cost_scenario]["fee_each_side"],
        "zip": str(zip_path.relative_to(ROOT)),
        "zip_sha256": sha256_file(zip_path),
        "trades": len(trades),
        "wins": wins,
        "losses": sum(value < 0 for value in absolutes),
        "draws": sum(value == 0 for value in absolutes),
        "winrate_pct": None if not trades else wins / len(trades) * 100.0,
        "strict_average_payoff": metric_ratio(ratios),
        "profit_factor": profit_factor(absolutes),
        "starting_balance": starting_balance,
        "final_balance": final_balance,
        "compound_return_pct": (final_balance / starting_balance - 1.0) * 100.0,
        "max_drawdown_pct": float(result["max_drawdown_account"]) * 100.0,
        "max_drawdown_abs": float(result["max_drawdown_abs"]),
        "liquidation_count": liquidation_count,
        "left_open_count": left_open_count,
        "long": direction_metrics(trades, False),
        "short": direction_metrics(trades, True),
        "modeled_execution_cost": modeled_execution_cost,
        "funding_net": sum(funding),
        "funding_paid": sum(-value for value in funding if value < 0),
        "funding_received": sum(value for value in funding if value > 0),
    }


def stage_receipt_path(stage: str, strategy: str, cost_scenario: str) -> Path:
    return RESULT_ROOT / stage / strategy / cost_scenario / "metrics.json"


def run_one(stage: str, strategy: str, cost_scenario: str) -> dict[str, Any]:
    if stage == "pseudo-oos":
        validate_freeze(strategy)
    elif stage == "validation":
        for candidate in CANDIDATES:
            for cost in COST_SCENARIOS:
                if not stage_receipt_path("development", candidate, cost).is_file():
                    raise RuntimeError("validation is blocked until the complete development matrix exists")

    ensure_preregistration()
    receipt_path = stage_receipt_path(stage, strategy, cost_scenario)
    if receipt_path.exists():
        raise RuntimeError(f"receipt already exists; refusing to overwrite: {receipt_path}")
    output = receipt_path.parent
    output.mkdir(parents=True, exist_ok=True)
    before = set(output.glob("*.zip"))
    command = [
        "backtesting",
        "--strategy",
        strategy,
        "-c",
        str(CONFIG_FILE),
        "--userdir",
        str(ROOT / "ft_userdata" / "user_data"),
        "--strategy-path",
        str(ROOT / "ft_userdata" / "user_data" / "strategies"),
        "-d",
        str(DERIVED_DATA),
        "--timerange",
        STAGES[stage]["timerange"],
        "--timeframe-detail",
        "5m",
        "--pairs",
        "BTC/USDT:USDT",
        "--fee",
        str(COST_SCENARIOS[cost_scenario]["fee_each_side"]),
        "--export",
        "trades",
        "--backtest-directory",
        str(output),
        "--cache",
        "none",
    ]
    with patch.object(Exchange, "reload_markets", offline_reload_markets):
        try:
            freqtrade_main(command)
        except SystemExit as error:
            if int(error.code or 0) != 0:
                raise RuntimeError(f"Freqtrade exited with {error.code}") from error
    created = set(output.glob("*.zip")) - before
    if len(created) != 1:
        raise RuntimeError(f"expected exactly one new result ZIP, found {created}")
    zip_path = created.pop()
    result = load_result(zip_path, strategy)
    metrics = extract_metrics(
        result,
        stage=stage,
        strategy=strategy,
        cost_scenario=cost_scenario,
        zip_path=zip_path,
    )
    metrics["strategy_sha256"] = sha256_file(STRATEGY_FILE)
    metrics["config_sha256"] = sha256_file(CONFIG_FILE)
    metrics["runner_sha256"] = sha256_file(Path(__file__))
    write_json(receipt_path, metrics)
    return metrics


def load_matrix(stage: str) -> dict[str, dict[str, dict[str, Any]]]:
    matrix: dict[str, dict[str, dict[str, Any]]] = {}
    for candidate in CANDIDATES:
        matrix[candidate] = {}
        for cost in COST_SCENARIOS:
            path = stage_receipt_path(stage, candidate, cost)
            if not path.is_file():
                raise RuntimeError(f"missing matrix receipt: {path}")
            matrix[candidate][cost] = json.loads(path.read_text(encoding="utf-8"))
    return matrix


def metrics_pass(metrics: dict[str, Any], stage: str) -> bool:
    payoff = metrics["strict_average_payoff"]
    factor = metrics["profit_factor"]
    return all(
        [
            metrics["trades"] >= MIN_TRADES[stage],
            metrics["compound_return_pct"] > 0,
            metrics["winrate_pct"] is not None and metrics["winrate_pct"] >= 40.0,
            payoff["status"] == "finite" and payoff["value"] >= 2.0,
            factor["status"] == "finite" and factor["value"] > 1.0,
            metrics["max_drawdown_pct"] <= MAX_DRAWDOWN_PCT,
            metrics["liquidation_count"] == 0,
            metrics["left_open_count"] == 0,
        ]
    )


def freeze() -> dict[str, Any]:
    preregistration = ensure_preregistration()
    if FREEZE_RECEIPT.exists() or REJECTION_RECEIPT.exists():
        raise RuntimeError("freeze decision already exists; refusing to replace it")
    development = load_matrix("development")
    validation = load_matrix("validation")
    eligible = []
    for candidate in CANDIDATES:
        observations = [
            development[candidate][cost] for cost in COST_SCENARIOS
        ] + [validation[candidate][cost] for cost in COST_SCENARIOS]
        if all(
            metrics_pass(development[candidate][cost], "development")
            and metrics_pass(validation[candidate][cost], "validation")
            for cost in COST_SCENARIOS
        ):
            eligible.append(
                {
                    "candidate": candidate,
                    "min_profit_factor": min(
                        value["profit_factor"]["value"] for value in observations
                    ),
                    "min_compound_return_pct": min(
                        value["compound_return_pct"] for value in observations
                    ),
                    "max_drawdown_pct": max(value["max_drawdown_pct"] for value in observations),
                }
            )
    if not eligible:
        rejection = {
            "decision": "REJECTED_BEFORE_PSEUDO_OOS",
            "reason": "No preregistered candidate passed every development/validation gate.",
            "preregistration_sha256": sha256_file(PREREGISTRATION),
            "strategy_sha256": preregistration["strategy_sha256"],
            "development": development,
            "validation": validation,
        }
        write_json(REJECTION_RECEIPT, rejection)
        return rejection

    eligible.sort(
        key=lambda item: (
            -item["min_profit_factor"],
            -item["min_compound_return_pct"],
            item["max_drawdown_pct"],
            item["candidate"],
        )
    )
    winner = eligible[0]
    receipt = {
        "decision": "FROZEN_FOR_ONE_PSEUDO_OOS_READ",
        "winner": winner,
        "risk_layer": {"leverage": 1.0, "margin_mode": "isolated"},
        "preregistration_sha256": sha256_file(PREREGISTRATION),
        "strategy_sha256": sha256_file(STRATEGY_FILE),
        "config_sha256": sha256_file(CONFIG_FILE),
        "runner_sha256": sha256_file(Path(__file__)),
        "development": development[winner["candidate"]],
        "validation": validation[winner["candidate"]],
    }
    write_json(FREEZE_RECEIPT, receipt)
    return receipt


def validate_freeze(strategy: str) -> dict[str, Any]:
    if REJECTION_RECEIPT.exists():
        raise RuntimeError("pseudo-OOS is sealed because the bounded study was rejected")
    if not FREEZE_RECEIPT.is_file():
        raise RuntimeError("pseudo-OOS is blocked until a winner is frozen")
    receipt = json.loads(FREEZE_RECEIPT.read_text(encoding="utf-8"))
    if strategy != receipt["winner"]["candidate"]:
        raise RuntimeError("pseudo-OOS may run only the frozen winner")
    expected = {
        "preregistration_sha256": sha256_file(PREREGISTRATION),
        "strategy_sha256": sha256_file(STRATEGY_FILE),
        "config_sha256": sha256_file(CONFIG_FILE),
        "runner_sha256": sha256_file(Path(__file__)),
    }
    for key, value in expected.items():
        if receipt[key] != value:
            raise RuntimeError(f"freeze identity mismatch: {key}")
    ensure_preregistration()
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")

    run_stage = subparsers.add_parser("run-stage")
    run_stage.add_argument("--stage", choices=("development", "validation"), required=True)
    run_stage.add_argument("--candidate", choices=tuple(CANDIDATES))
    run_stage.add_argument("--cost", choices=tuple(COST_SCENARIOS))

    subparsers.add_parser("freeze")
    subparsers.add_parser("run-oos")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        ensure_preregistration()
        print(PREREGISTRATION)
        return 0
    if args.command == "run-stage":
        candidates = [args.candidate] if args.candidate else list(CANDIDATES)
        costs = [args.cost] if args.cost else list(COST_SCENARIOS)
        for candidate in candidates:
            for cost in costs:
                metrics = run_one(args.stage, candidate, cost)
                print(json.dumps(metrics, sort_keys=True, allow_nan=False))
        return 0
    if args.command == "freeze":
        print(json.dumps(freeze(), sort_keys=True, allow_nan=False))
        return 0
    if args.command == "run-oos":
        receipt = json.loads(FREEZE_RECEIPT.read_text(encoding="utf-8"))
        candidate = receipt["winner"]["candidate"]
        for cost in COST_SCENARIOS:
            metrics = run_one("pseudo-oos", candidate, cost)
            print(json.dumps(metrics, sort_keys=True, allow_nan=False))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
