from __future__ import annotations

import argparse
import hashlib
import importlib
import itertools
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_ROOT = ROOT / "freqtrade"
USERDIR = ROOT / "ft_userdata" / "user_data"
STRATEGY_DIR = USERDIR / "strategies"
STRATEGY_FILE = STRATEGY_DIR / "MeanReversionFullHistoryStrategy.py"
CONFIG_FILE = USERDIR / "config.mean-reversion-full-history.json"
TEST_FILE = USERDIR / "tests" / "test_mean_reversion_full_history_strategy.py"
SOURCE_ROOT = USERDIR / "data" / "okx-btc-usdt-swap-full-20260813"
SOURCE_DATA = SOURCE_ROOT / "market-data" / "futures"
SOURCE_TIER_CACHE = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data"
    / "okx"
    / "futures"
    / "leverage_tiers_USDT.json"
)
RESULT_ROOT = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "goal-100pct"
    / "mean-reversion-full-history-riv48-v1"
)
DERIVED_DATA = RESULT_ROOT / "derived-market-data"
DERIVED_FUTURES = DERIVED_DATA / "futures"
PREREGISTRATION = RESULT_ROOT / "preregistration.json"
PREREGISTRATION_SHA = RESULT_ROOT / "preregistration.sha256"
DEVELOPMENT_CONFIG = RESULT_ROOT / "development-config.json"

sys.path.insert(0, str(FREQTRADE_ROOT))
sys.path.insert(0, str(STRATEGY_DIR))

from freqtrade.exchange.exchange import Exchange  # noqa: E402
from freqtrade.main import main as freqtrade_main  # noqa: E402


DATASET_MANIFEST_SHA256 = "29f2f05d3c56af598084eb48eabec213f56555f7848f9c2b16ccbac3ae8282cf"
SOURCE_TIER_CACHE_SHA256 = "abc2d7352f237a6ce5a99da7ebc2b320b9584ce13f0d5296943e7713bf4f9825"
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
DEVELOPMENT = {
    "start": "2022-03-01T00:00:00Z",
    "end_exclusive": "2024-01-01T00:00:00Z",
    "entry_end_exclusive": "2023-12-30T00:00:00Z",
    "timerange": "1646092800-1704067200",
}
GATES = {
    "profit_factor_strictly_greater_than": 1.2,
    "win_rate_at_least": 0.40,
    "strict_average_payoff_at_least": 2.0,
    "account_drawdown_strictly_less_than": 0.20,
    "trade_count_at_least": 30,
}
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
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def variants() -> list[dict[str, Any]]:
    timeframes = {-1: "1h", 1: "2h"}
    ema_lengths = {-1: 20, 1: 50}
    rsi_thresholds = {-1: (25.0, 75.0), 1: (30.0, 70.0)}
    exit_modes = {-1: "mean", 1: "tp"}
    stop_multipliers = {-1: 1.5, 1: 2.0}
    hold_hours = {-1: 24, 1: 48}
    result = []
    for deviation_tenths in (15, 20, 25):
        for index, (timeframe, ema, rsi, exit_mode) in enumerate(
            itertools.product((-1, 1), repeat=4), start=1
        ):
            stop = timeframe * ema * rsi
            hold = timeframe * ema * exit_mode
            result.append(
                {
                    "strategy": (
                        f"MeanReversionD{deviation_tenths}V{index:02d}Strategy"
                    ),
                    "coded": {
                        "T": timeframe,
                        "A": ema,
                        "R": rsi,
                        "X": exit_mode,
                        "S": stop,
                        "H": hold,
                    },
                    "parameters": {
                        "timeframe": timeframes[timeframe],
                        "ema_length": ema_lengths[ema],
                        "entry_atr_mult": deviation_tenths / 10,
                        "long_rsi_strictly_less_than": rsi_thresholds[rsi][0],
                        "short_rsi_strictly_greater_than": rsi_thresholds[rsi][1],
                        "exit_mode": exit_modes[exit_mode],
                        "take_profit_atr": 2.0,
                        "hard_stop_atr": stop_multipliers[stop],
                        "max_hold_hours": hold_hours[hold],
                    },
                }
            )
    return result


def verify_design(candidate_rows: list[dict[str, Any]]) -> None:
    if len(candidate_rows) != 48 or len({row["strategy"] for row in candidate_rows}) != 48:
        raise RuntimeError("mean-reversion design must contain exactly 48 unique candidates")
    module = importlib.import_module("MeanReversionFullHistoryStrategy")
    for row in candidate_rows:
        strategy = getattr(module, row["strategy"])(config={})
        params = row["parameters"]
        actual = {
            "timeframe": strategy.timeframe,
            "ema_length": strategy.ema_length,
            "entry_atr_mult": strategy.entry_atr_mult,
            "long_rsi_strictly_less_than": strategy.long_rsi_threshold,
            "short_rsi_strictly_greater_than": strategy.short_rsi_threshold,
            "exit_mode": strategy.exit_mode,
            "take_profit_atr": strategy.take_profit_atr,
            "hard_stop_atr": strategy.hard_stop_atr,
            "max_hold_hours": strategy.max_hold_hours,
        }
        if actual != params:
            raise RuntimeError(f"strategy class does not match frozen design: {row['strategy']}")
    for deviation in (1.5, 2.0, 2.5):
        subset = [
            row["coded"]
            for row in candidate_rows
            if row["parameters"]["entry_atr_mult"] == deviation
        ]
        if len(subset) != 16:
            raise RuntimeError("each deviation layer must have 16 candidates")
        for factor in "TARXSH":
            if sum(row[factor] for row in subset) != 0:
                raise RuntimeError(f"unbalanced design factor: {factor}")
        for left, right in itertools.combinations("TARXSH", 2):
            if sum(row[left] * row[right] for row in subset) != 0:
                raise RuntimeError(f"non-orthogonal design factors: {left}/{right}")


def prepare_data() -> dict[str, str]:
    manifest = SOURCE_ROOT / "dataset-manifest.json"
    if sha256_file(manifest) != DATASET_MANIFEST_SHA256:
        raise RuntimeError("full-history dataset manifest changed")
    if sha256_file(SOURCE_TIER_CACHE) != SOURCE_TIER_CACHE_SHA256:
        raise RuntimeError("OKX leverage tiers changed")

    DERIVED_FUTURES.mkdir(parents=True, exist_ok=True)
    for filename, expected_hash in SOURCE_HASHES.items():
        source = SOURCE_DATA / filename
        target = DERIVED_FUTURES / filename
        if sha256_file(source) != expected_hash:
            raise RuntimeError(f"source data changed: {source}")
        if not target.exists():
            shutil.copy2(source, target)
        if sha256_file(target) != expected_hash:
            raise RuntimeError(f"derived copy changed: {target}")

    target_2h = DERIVED_FUTURES / "BTC_USDT_USDT-2h-futures.feather"
    if not target_2h.exists():
        source_frame = pd.read_feather(
            SOURCE_DATA / "BTC_USDT_USDT-1h-futures.feather"
        ).sort_values("date")
        grouped = source_frame.set_index("date").resample(
            "2h", origin="epoch", label="left", closed="left"
        )
        counts = grouped["close"].count()
        result = grouped.agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        result = result.loc[counts == 2].dropna().reset_index()
        result.to_feather(target_2h)

    source_tiers = json.loads(SOURCE_TIER_CACHE.read_text(encoding="utf-8"))
    btc_tiers = source_tiers["data"]["BTC/USDT:USDT"]
    tier_target = DERIVED_FUTURES / "leverage_tiers_USDT.json"
    tier_target.write_text(
        json.dumps(
            {
                "updated": source_tiers["updated"],
                "data": {"BTC/USDT:USDT": btc_tiers},
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return {
        path.name: sha256_file(path)
        for path in sorted(DERIVED_FUTURES.iterdir())
        if path.is_file()
    }


def prepare() -> dict[str, Any]:
    candidate_rows = variants()
    verify_design(candidate_rows)
    derived_hashes = prepare_data()

    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    config["mean_reversion_entry_cutoff"] = DEVELOPMENT["entry_end_exclusive"]
    write_json(DEVELOPMENT_CONFIG, config)
    payload = {
        "design_id": "mr_riv48_v1",
        "created_before_any_performance_read": True,
        "pair": "BTC/USDT:USDT",
        "development": DEVELOPMENT,
        "validation": {
            "start": "2024-01-01T00:00:00Z",
            "end_exclusive": "2025-01-01T00:00:00Z",
            "policy": "run only development-gate survivors",
        },
        "pseudo_oos": {
            "start": "2025-01-01T00:00:00Z",
            "end_exclusive": "2026-08-13T00:00:00Z",
            "policy": "open once only after a development+validation winner is frozen",
            "truth_boundary": "retrospective pseudo-OOS, not prospectively blind",
        },
        "execution": {
            "leverage": 1.0,
            "margin_mode": "isolated",
            "wallet_usdt": 1000,
            "stake_amount": "unlimited",
            "max_open_trades": 1,
            "entry_and_exit_orders": "market",
            "signal_fill": "next main-timeframe open",
            "timeframe_detail": "5m",
            "fee_argument_each_side": 0.0006,
            "fee_meaning": "0.0005 OKX taker fee + 0.0001 cash-equivalent slippage proxy",
            "funding": "actual OKX funding events from 2022-03; zero leading fallback",
            "same_5m_stop_and_target": "stoploss first (Freqtrade conservative ordering)",
            "entry_blackout": "no entry during final 48 clock-hours of each split",
        },
        "signal_semantics": {
            "entry": "closed close at/beyond EMA deviation; RSI uses strict inequalities",
            "mean_exit": "closed main-timeframe close back at/beyond EMA, next-open fill",
            "tp_exit": "actual entry price +/- 2 * frozen signal ATR",
            "hard_stop": "actual entry price +/- frozen signal ATR multiplier",
            "level_not_cross": True,
        },
        "design": {
            "type": "48-run Resolution-IV fractional factorial",
            "generators": {"S": "T*A*R", "H": "T*A*X"},
            "defining_relation": "I=TARS=TAXH=RSXH",
            "candidates": candidate_rows,
        },
        "gates_applied_independently_to_development_and_validation": GATES,
        "sequence": [
            "run all 48 candidates on development baseline cost only",
            "stop immediately if development has no survivors",
            "run 2024 validation only for development survivors",
            "freeze at most one winner before opening pseudo-OOS",
        ],
        "selection": {
            "primary": "maximize minimum normalized gate margin across development and validation",
            "no_eligible": "reject without relaxing gates or expanding parameters",
        },
        "data": {
            "dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
            "source_hashes": SOURCE_HASHES,
            "derived_hashes": derived_hashes,
            "source_tier_cache_sha256": SOURCE_TIER_CACHE_SHA256,
        },
        "identity": {
            "strategy_sha256": sha256_file(STRATEGY_FILE),
            "base_config_sha256": sha256_file(CONFIG_FILE),
            "development_config_sha256": sha256_file(DEVELOPMENT_CONFIG),
            "mechanics_test_sha256": sha256_file(TEST_FILE),
            "runner_sha256": sha256_file(Path(__file__)),
        },
    }
    if PREREGISTRATION.exists():
        existing = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
        if existing != payload:
            raise RuntimeError("preregistration differs from current frozen inputs")
    else:
        write_json(PREREGISTRATION, payload)
    prereg_hash = sha256_file(PREREGISTRATION)
    PREREGISTRATION_SHA.write_text(f"{prereg_hash}  preregistration.json\n", encoding="utf-8")
    return {"preregistration_sha256": prereg_hash, "candidate_count": 48}


def offline_reload_markets(
    exchange: Exchange,
    force: bool = False,
    *,
    load_leverage_tiers: bool = True,
) -> None:
    exchange._api_async.set_markets([OFFLINE_MARKET])
    exchange._api.set_markets_from_exchange(exchange._api_async)
    exchange._markets = dict(exchange._api_async.markets)
    tiers = json.loads(SOURCE_TIER_CACHE.read_text(encoding="utf-8"))["data"]
    exchange._leverage_tiers = {
        "BTC/USDT:USDT": [
            exchange.parse_leverage_tier(tier) for tier in tiers["BTC/USDT:USDT"]
        ]
    }
    exchange._last_markets_refresh = 1


def ensure_frozen_inputs() -> dict[str, Any]:
    if not PREREGISTRATION.is_file():
        raise RuntimeError("run prepare before any performance run")
    payload = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    expected = {
        "strategy_sha256": sha256_file(STRATEGY_FILE),
        "base_config_sha256": sha256_file(CONFIG_FILE),
        "development_config_sha256": sha256_file(DEVELOPMENT_CONFIG),
        "mechanics_test_sha256": sha256_file(TEST_FILE),
        "runner_sha256": sha256_file(Path(__file__)),
    }
    if payload["identity"] != expected:
        raise RuntimeError("a frozen source changed after preregistration")
    if PREREGISTRATION_SHA.read_text(encoding="utf-8").split()[0] != sha256_file(
        PREREGISTRATION
    ):
        raise RuntimeError("preregistration hash receipt mismatch")
    return payload


def ratio_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    ratios = [float(trade["profit_ratio"]) for trade in trades]
    absolutes = [float(trade["profit_abs"]) for trade in trades]
    winners = [value for value in ratios if value > 0]
    losers = [value for value in ratios if value < 0]
    gross_profit = sum(value for value in absolutes if value > 0)
    gross_loss = abs(sum(value for value in absolutes if value < 0))
    return {
        "trades": len(trades),
        "wins": sum(value > 0 for value in absolutes),
        "losses": sum(value < 0 for value in absolutes),
        "draws": sum(value == 0 for value in absolutes),
        "win_rate": None if not trades else sum(value > 0 for value in absolutes) / len(trades),
        "strict_average_payoff": (
            None
            if not winners or not losers
            else (sum(winners) / len(winners)) / abs(sum(losers) / len(losers))
        ),
        "profit_factor": None if gross_loss == 0 else gross_profit / gross_loss,
    }


def run_group(timeframe: str) -> dict[str, Any]:
    preregistration = ensure_frozen_inputs()
    candidate_rows = [
        row
        for row in preregistration["design"]["candidates"]
        if row["parameters"]["timeframe"] == timeframe
    ]
    output = RESULT_ROOT / "development" / timeframe
    if output.exists():
        raise RuntimeError(f"refusing to overwrite development group: {output}")
    output.mkdir(parents=True)
    command = [
        "backtesting",
        "--strategy-list",
        *(row["strategy"] for row in candidate_rows),
        "-c",
        str(DEVELOPMENT_CONFIG),
        "--userdir",
        str(USERDIR),
        "--strategy-path",
        str(STRATEGY_DIR),
        "-d",
        str(DERIVED_DATA),
        "--timerange",
        DEVELOPMENT["timerange"],
        "--timeframe",
        timeframe,
        "--timeframe-detail",
        "5m",
        "--pairs",
        "BTC/USDT:USDT",
        "--fee",
        "0.0006",
        "--export",
        "trades",
        "--backtest-directory",
        str(output),
        "--cache",
        "none",
    ]
    before = set(output.glob("*.zip"))
    with patch.object(Exchange, "reload_markets", offline_reload_markets):
        try:
            freqtrade_main(command)
        except SystemExit as error:
            if int(error.code or 0) != 0:
                raise RuntimeError(f"Freqtrade exited with {error.code}") from error
    created = set(output.glob("*.zip")) - before
    if len(created) != 1:
        raise RuntimeError(f"expected one result ZIP, found {created}")
    zip_path = created.pop()
    with zipfile.ZipFile(zip_path) as archive:
        entries = [
            name
            for name in archive.namelist()
            if name.endswith(".json")
            and not name.endswith("_config.json")
            and "_strategy" not in name
        ]
        if len(entries) != 1:
            raise RuntimeError(f"unexpected result entries: {entries}")
        results = json.loads(archive.read(entries[0]))["strategy"]
    expected_names = [row["strategy"] for row in candidate_rows]
    if set(results) != set(expected_names):
        raise RuntimeError("result strategies differ from the frozen group")

    metrics = {}
    cutoff_ms = int(datetime.fromisoformat(DEVELOPMENT["entry_end_exclusive"]).timestamp() * 1000)
    for name in expected_names:
        result = results[name]
        trades = result["trades"]
        if any(int(trade["open_timestamp"]) >= cutoff_ms for trade in trades):
            raise RuntimeError(f"entry blackout failed for {name}")
        values = ratio_metrics(trades)
        values.update(
            {
                "return": float(result["profit_total"]),
                "profit_usdt": float(result["profit_total_abs"]),
                "max_account_drawdown": float(result["max_drawdown_account"]),
                "funding_usdt": sum(float(trade.get("funding_fees") or 0.0) for trade in trades),
                "force_exit_count": sum(trade["exit_reason"] == "force_exit" for trade in trades),
            }
        )
        metrics[name] = values
    receipt = {
        "stage": "development",
        "timeframe": timeframe,
        "preregistration_sha256": sha256_file(PREREGISTRATION),
        "result_zip": str(zip_path.relative_to(ROOT)),
        "result_zip_sha256": sha256_file(zip_path),
        "metrics": metrics,
    }
    write_json(output / "metrics.json", receipt)
    return receipt


def passes_development(metrics: dict[str, Any]) -> bool:
    return all(
        (
            metrics["profit_factor"] is not None
            and metrics["profit_factor"] > GATES["profit_factor_strictly_greater_than"],
            metrics["win_rate"] is not None
            and metrics["win_rate"] >= GATES["win_rate_at_least"],
            metrics["strict_average_payoff"] is not None
            and metrics["strict_average_payoff"]
            >= GATES["strict_average_payoff_at_least"],
            metrics["max_account_drawdown"]
            < GATES["account_drawdown_strictly_less_than"],
            metrics["trades"] >= GATES["trade_count_at_least"],
            metrics["force_exit_count"] == 0,
        )
    )


def finalize_development() -> dict[str, Any]:
    preregistration = ensure_frozen_inputs()
    metrics = {}
    group_hashes = {}
    for timeframe in ("1h", "2h"):
        path = RESULT_ROOT / "development" / timeframe / "metrics.json"
        if not path.is_file():
            raise RuntimeError(f"development group is incomplete: {path}")
        group = json.loads(path.read_text(encoding="utf-8"))
        if group["preregistration_sha256"] != sha256_file(PREREGISTRATION):
            raise RuntimeError("development group used a different preregistration")
        metrics.update(group["metrics"])
        group_hashes[timeframe] = sha256_file(path)
    expected = {row["strategy"] for row in preregistration["design"]["candidates"]}
    if set(metrics) != expected:
        raise RuntimeError("development metrics do not cover all 48 candidates")
    survivors = sorted(name for name, values in metrics.items() if passes_development(values))
    decision = {
        "decision": (
            "ADVANCE_DEVELOPMENT_SURVIVORS_TO_2024"
            if survivors
            else "REJECTED_AT_DEVELOPMENT_STOP_BEFORE_2024_AND_PSEUDO_OOS"
        ),
        "preregistration_sha256": sha256_file(PREREGISTRATION),
        "group_metric_sha256": group_hashes,
        "survivors": survivors,
        "metrics": metrics,
    }
    write_json(RESULT_ROOT / "development-screen.json", decision)
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    run_group_parser = subparsers.add_parser("run-group")
    run_group_parser.add_argument("--timeframe", choices=("1h", "2h"), required=True)
    subparsers.add_parser("finalize-development")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare(), sort_keys=True))
        return 0
    if args.command == "run-group":
        print(json.dumps(run_group(args.timeframe), sort_keys=True))
        return 0
    if args.command == "finalize-development":
        print(json.dumps(finalize_development(), sort_keys=True))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
