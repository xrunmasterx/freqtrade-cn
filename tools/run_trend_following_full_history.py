from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_ROOT = ROOT / "freqtrade"
sys.path.insert(0, str(FREQTRADE_ROOT))

from freqtrade.exchange.exchange import Exchange  # noqa: E402
from freqtrade.main import main as freqtrade_main  # noqa: E402


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
    / "trend-following-full-history"
)
DERIVED_DATA = RESULT_ROOT / "derived-market-data"
DERIVED_FUTURES = DERIVED_DATA / "futures"
GENERATED_CONFIGS = RESULT_ROOT / "generated-configs"
STRATEGY_FILE = (
    ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "TrendFollowingFullHistoryStrategy.py"
)
CONFIG_FILE = (
    ROOT
    / "ft_userdata"
    / "user_data"
    / "config.trend-following-full-history.json"
)
LEVERAGE_TIER_SOURCE = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data"
    / "okx"
    / "futures"
    / "leverage_tiers_USDT.json"
)
PREREGISTRATION = RESULT_ROOT / "preregistration.json"
FREEZE_RECEIPT = RESULT_ROOT / "freeze-receipt.json"
FINAL_SUMMARY = RESULT_ROOT / "final-summary.json"

DATASET_MANIFEST_SHA256 = "29f2f05d3c56af598084eb48eabec213f56555f7848f9c2b16ccbac3ae8282cf"
SOURCE_HASHES = {
    "BTC_USDT_USDT-5m-futures.feather": (
        "77b4e092736cf2f4484555e6c3c76db30dbe78508aeb1c03d2aceafdaa948851"
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
LEVERAGE_TIER_SOURCE_SHA256 = (
    "abc2d7352f237a6ce5a99da7ebc2b320b9584ce13f0d5296943e7713bf4f9825"
)
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
    "oos": {
        "timerange": "1735689600-1786579199",
        "start": 1735689600,
        "end": 1786579199,
    },
}
COST_SCENARIOS = {
    "fee_plus_slippage_baseline": {"fee_each_side": 0.0006},
    "slippage_stress": {"fee_each_side": 0.0010},
}
CORRECTED_HOURLY_FALLBACK = 0.0000042304172276700455
FUNDING_FALLBACKS = {
    "fallback_zero": 0.0,
    "fallback_positive_hourly": CORRECTED_HOURLY_FALLBACK,
    "fallback_negative_hourly": -CORRECTED_HOURLY_FALLBACK,
}
DEVELOPMENT_GATES = {
    "minimum_trades": 20,
    "minimum_winrate_pct": 40.0,
    "minimum_strict_average_payoff": 2.0,
    "minimum_profit_factor": 1.25,
    "maximum_drawdown_pct": 25.0,
}
VALIDATION_GATES = {
    "minimum_trades": 8,
    "minimum_winrate_pct": 40.0,
    "minimum_strict_average_payoff": 2.0,
    "minimum_profit_factor": 1.10,
    "maximum_drawdown_pct": 25.0,
}
STRESS_GATES = {
    "minimum_profit_factor": 1.0,
    "maximum_drawdown_pct": 30.0,
}


def candidate_name(
    timeframe: str,
    channel: int,
    stop_code: int,
    trail_code: int,
) -> str:
    return (
        f"TrendFollowing{timeframe}N{channel}Stop{stop_code}"
        f"Trail{trail_code}Strategy"
    )


CANDIDATES = [
    candidate_name(timeframe, channel, stop_code, trail_code)
    for timeframe in ("2h", "4h")
    for channel in (20, 55)
    for stop_code in (15, 20, 30)
    for trail_code in (25, 35)
]

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
    "taker": 0.0005,
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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def verify_sources() -> None:
    manifest = SOURCE_ROOT / "dataset-manifest.json"
    if sha256_file(manifest) != DATASET_MANIFEST_SHA256:
        raise RuntimeError("full-history dataset manifest is missing or changed")
    for filename, expected in SOURCE_HASHES.items():
        path = SOURCE_DATA / filename
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"source data is missing or changed: {path}")
    if sha256_file(LEVERAGE_TIER_SOURCE) != LEVERAGE_TIER_SOURCE_SHA256:
        raise RuntimeError("current OKX leverage-tier cache is missing or changed")


def copy_source(filename: str) -> None:
    source = SOURCE_DATA / filename
    target = DERIVED_FUTURES / filename
    if target.exists():
        if sha256_file(target) != SOURCE_HASHES[filename]:
            raise RuntimeError(f"derived source copy changed: {target}")
        return
    shutil.copy2(source, target)


def resample_ohlcv(target_name: str, rule: str, expected_rows: int) -> None:
    target = DERIVED_FUTURES / target_name
    if target.exists():
        return
    source = pd.read_feather(
        SOURCE_DATA / "BTC_USDT_USDT-1h-futures.feather"
    ).sort_values("date")
    grouped = source.set_index("date").resample(
        rule,
        origin="epoch",
        label="left",
        closed="left",
    )
    counts = grouped["close"].count()
    result = grouped.agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    result = result.loc[counts == expected_rows].dropna().reset_index()
    if result.empty or result["date"].duplicated().any():
        raise RuntimeError(f"invalid resample result: {target}")
    result.to_feather(target)


def prepare_derived_data() -> dict[str, str]:
    verify_sources()
    DERIVED_FUTURES.mkdir(parents=True, exist_ok=True)
    for filename in SOURCE_HASHES:
        copy_source(filename)
    leverage_target = DERIVED_FUTURES / "leverage_tiers_USDT.json"
    if (
        leverage_target.exists()
        and sha256_file(leverage_target) != LEVERAGE_TIER_SOURCE_SHA256
    ):
        leverage_target.unlink()
    if not leverage_target.exists():
        shutil.copy2(LEVERAGE_TIER_SOURCE, leverage_target)
    resample_ohlcv("BTC_USDT_USDT-2h-futures.feather", "2h", 2)
    resample_ohlcv("BTC_USDT_USDT-4h-futures.feather", "4h", 4)
    return {
        path.name: sha256_file(path)
        for path in sorted(DERIVED_FUTURES.glob("*.feather"))
    }


def prepare_generated_configs() -> dict[str, str]:
    base = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    GENERATED_CONFIGS.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, fallback in FUNDING_FALLBACKS.items():
        payload = dict(base)
        payload["futures_funding_rate"] = fallback
        path = GENERATED_CONFIGS / f"{name}.json"
        serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != serialized:
            raise RuntimeError(f"generated config changed: {path}")
        path.write_text(serialized, encoding="utf-8")
        hashes[path.name] = sha256_file(path)
    return hashes


def funding_coverage() -> dict[str, Any]:
    frame = pd.read_feather(SOURCE_DATA / "BTC_USDT_USDT-1h-funding_rate.feather")
    coverage = {}
    for stage, bounds in STAGES.items():
        start = pd.Timestamp(bounds["start"], unit="s", tz="UTC")
        end = pd.Timestamp(bounds["end"], unit="s", tz="UTC")
        selected = frame.loc[
            (frame["date"] >= start)
            & (frame["date"] <= end)
        ]
        coverage[stage] = {
            "actual_event_rows": len(selected),
            "first_actual_event": None if selected.empty else selected["date"].iloc[0].isoformat(),
            "last_actual_event": None if selected.empty else selected["date"].iloc[-1].isoformat(),
        }
    return coverage


def preregistration_payload(
    derived_hashes: dict[str, str],
    generated_config_hashes: dict[str, str],
) -> dict[str, Any]:
    return {
        "scope": "bounded classic Donchian full-history trend research",
        "created_before_performance_read": True,
        "pair": "BTC/USDT:USDT",
        "instrument": "OKX BTC-USDT-SWAP",
        "data_root": str(SOURCE_ROOT.relative_to(ROOT)),
        "dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
        "source_hashes": SOURCE_HASHES,
        "derived_hashes": derived_hashes,
        "strategy_sha256": sha256_file(STRATEGY_FILE),
        "config_sha256": sha256_file(CONFIG_FILE),
        "runner_sha256": sha256_file(Path(__file__)),
        "generated_config_hashes": generated_config_hashes,
        "stages": STAGES,
        "candidates": CANDIDATES,
        "candidate_family": {
            "timeframes": ["2h", "4h"],
            "entry": "first close beyond prior 20 or 55-bar Donchian channel",
            "directions": ["long", "short"],
            "atr": "Wilder ATR(14), price denominated",
            "initial_stop_atr": [1.5, 2.0, 3.0],
            "trailing_stop_atr": [2.5, 3.5],
            "trailing_reference": (
                "5m-observed favorable price using the latest closed main-timeframe ATR"
            ),
            "other_filters": "none",
        },
        "execution": {
            "wallet": 1000,
            "stake_amount": "unlimited",
            "max_open_trades": 1,
            "leverage": 1.0,
            "margin_mode": "isolated",
            "timeframe_detail": "5m",
            "entry": "standard Freqtrade next-main-candle market fill",
            "stage_end": "standard Freqtrade force-close for stage accounting",
            "leverage_tier_cache_source": str(LEVERAGE_TIER_SOURCE.relative_to(ROOT)),
            "leverage_tier_cache_sha256": LEVERAGE_TIER_SOURCE_SHA256,
            "leverage_tier_cache_observed_at_utc": "2026-08-12T10:33:49.153543+00:00",
            "liquidation_claim_boundary": (
                "The current verified OKX tier cache supplies Freqtrade liquidation inputs; "
                "this 1x study does not claim historical tier reconstruction."
            ),
        },
        "cost_scenarios": COST_SCENARIOS,
        "funding": {
            "actual_rows": funding_coverage(),
            "fallback_semantics": (
                "Freqtrade hourly leading-gap fill only; internal gaps are not filled"
            ),
            "corrected_hourly_fallback": CORRECTED_HOURLY_FALLBACK,
            "correction": "an 8h funding estimate must be divided by 8 before hourly fallback use",
            "oos_fallback_sensitivity": FUNDING_FALLBACKS,
            "selection_uses_old_8h_value": False,
        },
        "selection": {
            "development_gates": DEVELOPMENT_GATES,
            "validation_gates": VALIDATION_GATES,
            "stress_gates": STRESS_GATES,
            "development": "baseline cost only; failures stop before any stress or validation",
            "validation": "baseline and slippage stress are both required",
            "sort_order": [
                "maximize minimum baseline PF across development and validation",
                "maximize minimum baseline strict average payoff",
                "minimize maximum baseline drawdown",
                "candidate name ascending",
            ],
        },
        "rejection_policy": {
            "development": "only development-pass candidates may enter 2024 validation",
            "if_no_candidate_passes_development": "write rejection receipt and seal OOS",
            "if_no_candidate_passes_validation": "write rejection receipt and seal OOS",
            "no_post_validation_parameter_search": True,
        },
        "oos_policy": (
            "Read 2025-01-01 through 2026-08-12 only after one candidate or the rejection "
            "baseline is frozen; OOS results cannot change the frozen parameters."
        ),
    }


def ensure_preregistration() -> dict[str, Any]:
    expected = preregistration_payload(
        prepare_derived_data(),
        prepare_generated_configs(),
    )
    if PREREGISTRATION.exists():
        actual = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
        if actual != expected:
            raise RuntimeError("preregistration differs from current code/config/data")
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
        return {
            "value": None,
            "status": "infinite" if gross_profit > 0 else "no_profit_or_loss",
        }
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
        "winrate_pct": None if not selected else wins / len(selected) * 100.0,
        "strict_average_payoff": metric_ratio(ratios),
        "profit_factor": profit_factor(absolutes),
        "profit_abs": sum(absolutes),
    }


def load_result_payload(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as archive:
        entries = [
            name
            for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        if len(entries) != 1:
            raise RuntimeError(f"expected one result JSON in {zip_path}: {entries}")
        return json.loads(archive.read(entries[0]))


def extract_metrics(
    result: dict[str, Any],
    *,
    stage: str,
    candidate: str,
    scenario: str,
    fee_each_side: float,
    zip_path: Path,
) -> dict[str, Any]:
    trades = result["trades"]
    start_ms = STAGES[stage]["start"] * 1000
    end_ms = STAGES[stage]["end"] * 1000
    if any(int(trade["open_timestamp"]) < start_ms for trade in trades):
        raise RuntimeError("trade opened before the frozen stage")
    if any(int(trade["close_timestamp"]) > end_ms for trade in trades):
        raise RuntimeError("trade closed after the frozen stage")

    ratios = [float(trade["profit_ratio"]) for trade in trades]
    absolutes = [float(trade["profit_abs"]) for trade in trades]
    starting_balance = float(result["starting_balance"])
    final_balance = float(result["final_balance"])
    if not math.isclose(
        final_balance,
        starting_balance + sum(absolutes),
        rel_tol=1e-8,
        abs_tol=1e-5,
    ):
        raise RuntimeError("trade PnL does not reconcile to final balance")

    execution_cost = 0.0
    for trade in trades:
        for order in trade.get("orders", []):
            fee_rate = float(
                trade["fee_open"] if order["ft_is_entry"] else trade["fee_close"]
            )
            execution_cost += float(order["cost"]) * fee_rate
    funding = [float(trade.get("funding_fees") or 0.0) for trade in trades]
    wins = sum(value > 0 for value in absolutes)
    return {
        "stage": stage,
        "candidate": candidate,
        "scenario": scenario,
        "timeframe": result["timeframe"],
        "timeframe_detail": result["timeframe_detail"],
        "timerange": STAGES[stage]["timerange"],
        "effective_start": result["backtest_start"],
        "effective_end": result["backtest_end"],
        "fee_each_side": fee_each_side,
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
        "liquidation_count": sum(
            trade["exit_reason"] == "liquidation" for trade in trades
        ),
        "force_exit_count": sum(trade["exit_reason"] == "force_exit" for trade in trades),
        "long": direction_metrics(trades, False),
        "short": direction_metrics(trades, True),
        "modeled_execution_cost": execution_cost,
        "funding_net": sum(funding),
        "funding_paid": sum(-value for value in funding if value < 0),
        "funding_received": sum(value for value in funding if value > 0),
        "zip": str(zip_path.relative_to(ROOT)),
        "zip_sha256": sha256_file(zip_path),
        "strategy_sha256": sha256_file(STRATEGY_FILE),
        "config_sha256": sha256_file(CONFIG_FILE),
        "runner_sha256": sha256_file(Path(__file__)),
    }


def receipt_path(stage: str, candidate: str, scenario: str) -> Path:
    return RESULT_ROOT / stage / candidate / f"{scenario}.json"


def validate_validation_prerequisites() -> None:
    for candidate in CANDIDATES:
        if not receipt_path(
            "development",
            candidate,
            "fee_plus_slippage_baseline",
        ).is_file():
            raise RuntimeError("validation is blocked until development is complete")


def run_freqtrade(
    *,
    stage: str,
    candidates: list[str],
    timeframe: str,
    scenario: str,
    fee_each_side: float,
    config_path: Path,
) -> dict[str, dict[str, Any]]:
    output = RESULT_ROOT / stage / "raw" / timeframe / scenario
    output.mkdir(parents=True, exist_ok=True)
    before = set(output.glob("*.zip"))
    command = [
        "backtesting",
        "--strategy-list",
        *candidates,
        "-c",
        str(config_path),
        "--userdir",
        str(ROOT / "ft_userdata" / "user_data"),
        "--strategy-path",
        str(ROOT / "ft_userdata" / "user_data" / "strategies"),
        "-d",
        str(DERIVED_DATA),
        "--timerange",
        STAGES[stage]["timerange"],
        "--timeframe",
        timeframe,
        "--timeframe-detail",
        "5m",
        "--pairs",
        "BTC/USDT:USDT",
        "--fee",
        str(fee_each_side),
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
    payload = load_result_payload(zip_path)
    if set(payload.get("strategy", {})) != set(candidates):
        raise RuntimeError("backtest result strategy set does not match the frozen request")
    return {
        candidate: extract_metrics(
            payload["strategy"][candidate],
            stage=stage,
            candidate=candidate,
            scenario=scenario,
            fee_each_side=fee_each_side,
            zip_path=zip_path,
        )
        for candidate in candidates
    }


def run_matrix_stage(stage: str) -> None:
    ensure_preregistration()
    if stage == "validation":
        validate_validation_prerequisites()
        stage_candidates = development_eligible_candidates()
        if not stage_candidates:
            raise RuntimeError(
                "all candidates failed development; run freeze to write the rejection receipt"
            )
    else:
        stage_candidates = CANDIDATES
    scenarios = (
        ("fee_plus_slippage_baseline",)
        if stage == "development"
        else tuple(COST_SCENARIOS)
    )
    for scenario in scenarios:
        cost = COST_SCENARIOS[scenario]
        for candidate in stage_candidates:
            path = receipt_path(stage, candidate, scenario)
            if path.is_file():
                continue
            timeframe = "2h" if "2h" in candidate else "4h"
            values = run_freqtrade(
                stage=stage,
                candidates=[candidate],
                timeframe=timeframe,
                scenario=scenario,
                fee_each_side=cost["fee_each_side"],
                config_path=CONFIG_FILE,
            )[candidate]
            write_json(path, values)


def load_metrics(stage: str, candidate: str, scenario: str) -> dict[str, Any]:
    path = receipt_path(stage, candidate, scenario)
    if not path.is_file():
        raise RuntimeError(f"missing immutable receipt: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def baseline_passes(metrics: dict[str, Any], stage: str) -> bool:
    gates = DEVELOPMENT_GATES if stage == "development" else VALIDATION_GATES
    payoff = metrics["strict_average_payoff"]
    factor = metrics["profit_factor"]
    return all(
        [
            metrics["trades"] >= gates["minimum_trades"],
            metrics["winrate_pct"] is not None
            and metrics["winrate_pct"] >= gates["minimum_winrate_pct"],
            payoff["status"] == "finite"
            and payoff["value"] >= gates["minimum_strict_average_payoff"],
            factor["status"] == "finite"
            and factor["value"] >= gates["minimum_profit_factor"],
            metrics["compound_return_pct"] > 0,
            metrics["max_drawdown_pct"] <= gates["maximum_drawdown_pct"],
            metrics["liquidation_count"] == 0,
        ]
    )


def stress_passes(metrics: dict[str, Any]) -> bool:
    factor = metrics["profit_factor"]
    return all(
        [
            factor["status"] == "finite"
            and factor["value"] > STRESS_GATES["minimum_profit_factor"],
            metrics["compound_return_pct"] > 0,
            metrics["max_drawdown_pct"] <= STRESS_GATES["maximum_drawdown_pct"],
            metrics["liquidation_count"] == 0,
        ]
    )


def development_eligible_candidates() -> list[str]:
    eligible = []
    for candidate in CANDIDATES:
        baseline = load_metrics(
            "development", candidate, "fee_plus_slippage_baseline"
        )
        if baseline_passes(baseline, "development"):
            eligible.append(candidate)
    return eligible


def freeze() -> dict[str, Any]:
    preregistration = ensure_preregistration()
    if FREEZE_RECEIPT.exists():
        raise RuntimeError("freeze receipt already exists; refusing to replace it")
    eligible = []
    audit = {}
    development_eligible = development_eligible_candidates()
    if not development_eligible:
        receipt = {
            "decision": "REJECTED_AT_DEVELOPMENT",
            "frozen_candidate": None,
            "eligible": [],
            "oos_sealed": True,
            "oos_can_change_parameters": False,
            "preregistration_sha256": sha256_file(PREREGISTRATION),
            "strategy_sha256": preregistration["strategy_sha256"],
            "config_sha256": preregistration["config_sha256"],
            "runner_sha256": preregistration["runner_sha256"],
        }
        write_json(FREEZE_RECEIPT, receipt)
        return receipt

    for candidate in CANDIDATES:
        development_baseline = load_metrics(
            "development", candidate, "fee_plus_slippage_baseline"
        )
        if candidate not in development_eligible:
            audit[candidate] = {
                "development_baseline": baseline_passes(
                    development_baseline, "development"
                ),
                "validation": "not_opened_after_development_rejection",
            }
            continue
        validation_baseline = load_metrics(
            "validation", candidate, "fee_plus_slippage_baseline"
        )
        validation_stress = load_metrics("validation", candidate, "slippage_stress")
        passes = {
            "development_baseline": baseline_passes(development_baseline, "development"),
            "validation_baseline": baseline_passes(validation_baseline, "validation"),
            "validation_stress": stress_passes(validation_stress),
        }
        audit[candidate] = passes
        if all(passes.values()):
            eligible.append(
                {
                    "candidate": candidate,
                    "min_baseline_profit_factor": min(
                        development_baseline["profit_factor"]["value"],
                        validation_baseline["profit_factor"]["value"],
                    ),
                    "min_baseline_payoff": min(
                        development_baseline["strict_average_payoff"]["value"],
                        validation_baseline["strict_average_payoff"]["value"],
                    ),
                    "max_baseline_drawdown_pct": max(
                        development_baseline["max_drawdown_pct"],
                        validation_baseline["max_drawdown_pct"],
                    ),
                }
            )
    if eligible:
        eligible.sort(
            key=lambda item: (
                -item["min_baseline_profit_factor"],
                -item["min_baseline_payoff"],
                item["max_baseline_drawdown_pct"],
                item["candidate"],
            )
        )
        frozen = eligible[0]["candidate"]
        decision = "FROZEN_ELIGIBLE_CANDIDATE"
    else:
        frozen = None
        decision = "REJECTED_AT_VALIDATION"
    receipt = {
        "decision": decision,
        "frozen_candidate": frozen,
        "eligible": eligible,
        "gate_audit": audit,
        "oos_sealed": frozen is None,
        "oos_can_change_parameters": False,
        "preregistration_sha256": sha256_file(PREREGISTRATION),
        "strategy_sha256": preregistration["strategy_sha256"],
        "config_sha256": preregistration["config_sha256"],
        "runner_sha256": preregistration["runner_sha256"],
    }
    write_json(FREEZE_RECEIPT, receipt)
    return receipt


def validate_freeze() -> dict[str, Any]:
    if not FREEZE_RECEIPT.is_file():
        raise RuntimeError("OOS is blocked until a candidate is frozen")
    receipt = json.loads(FREEZE_RECEIPT.read_text(encoding="utf-8"))
    if receipt["decision"] != "FROZEN_ELIGIBLE_CANDIDATE":
        raise RuntimeError("OOS is sealed by the development/validation rejection")
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


def run_oos() -> dict[str, Any]:
    freeze_receipt = validate_freeze()
    if FINAL_SUMMARY.exists():
        raise RuntimeError("final summary already exists; refusing to replace it")
    candidate = freeze_receipt["frozen_candidate"]
    timeframe = "2h" if "2h" in candidate else "4h"
    scenarios = {
        "actual_funding_baseline_cost": {
            "fee": COST_SCENARIOS["fee_plus_slippage_baseline"]["fee_each_side"],
            "config": GENERATED_CONFIGS / "fallback_positive_hourly.json",
        },
        "actual_funding_slippage_stress": {
            "fee": COST_SCENARIOS["slippage_stress"]["fee_each_side"],
            "config": GENERATED_CONFIGS / "fallback_positive_hourly.json",
        },
        "actual_funding_fallback_zero": {
            "fee": COST_SCENARIOS["fee_plus_slippage_baseline"]["fee_each_side"],
            "config": GENERATED_CONFIGS / "fallback_zero.json",
        },
        "actual_funding_fallback_negative": {
            "fee": COST_SCENARIOS["fee_plus_slippage_baseline"]["fee_each_side"],
            "config": GENERATED_CONFIGS / "fallback_negative_hourly.json",
        },
    }
    results = {}
    for scenario, settings in scenarios.items():
        path = receipt_path("oos", candidate, scenario)
        if path.exists():
            raise RuntimeError(f"OOS receipt already exists: {path}")
        metrics = run_freqtrade(
            stage="oos",
            candidates=[candidate],
            timeframe=timeframe,
            scenario=scenario,
            fee_each_side=settings["fee"],
            config_path=settings["config"],
        )[candidate]
        write_json(path, metrics)
        results[scenario] = metrics

    baseline = results["actual_funding_baseline_cost"]
    fallback_equal = all(
        math.isclose(
            results[name]["final_balance"],
            baseline["final_balance"],
            rel_tol=0,
            abs_tol=1e-9,
        )
        for name in (
            "actual_funding_fallback_zero",
            "actual_funding_fallback_negative",
        )
    )
    summary = {
        "decision": freeze_receipt["decision"],
        "frozen_candidate": candidate,
        "oos_role": "one-time frozen-candidate evaluation",
        "oos_results": results,
        "fallback_sensitivity_identical": fallback_equal,
        "fallback_interpretation": (
            "Identical fallback scenarios mean official actual funding rows covered the OOS "
            "calculation; they do not prove robustness to altered actual funding rates."
            if fallback_equal
            else "Fallback affected at least one OOS trade and must be treated as model risk."
        ),
        "freeze_receipt_sha256": sha256_file(FREEZE_RECEIPT),
    }
    write_json(FINAL_SUMMARY, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    stage = subparsers.add_parser("run-stage")
    stage.add_argument("--stage", choices=("development", "validation"), required=True)
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
        run_matrix_stage(args.stage)
        return 0
    if args.command == "freeze":
        print(json.dumps(freeze(), sort_keys=True, allow_nan=False))
        return 0
    if args.command == "run-oos":
        print(json.dumps(run_oos(), sort_keys=True, allow_nan=False))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
