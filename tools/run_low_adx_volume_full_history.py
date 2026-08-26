from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from unittest.mock import patch
from zipfile import ZipFile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_ROOT = ROOT / "freqtrade"
sys.path.insert(0, str(FREQTRADE_ROOT))

from freqtrade.exchange.exchange import Exchange
from freqtrade.main import main as freqtrade_main
from freqtrade.optimize.backtesting import Backtesting

SOURCE_SNAPSHOT = (
    ROOT
    / "ft_userdata"
    / "user_data"
    / "data"
    / "okx-btc-usdt-swap-full-20260813"
)
SOURCE_DATA = SOURCE_SNAPSHOT / "market-data" / "futures"
RESULT_ROOT = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "goal-100pct"
    / "low-adx-volume-full-history"
)
DERIVED_DATA = RESULT_ROOT / "derived-data" / "market-data"
CONFIG = ROOT / "ft_userdata" / "user_data" / "config.low-adx-volume-full-history.json"
STRATEGY_FILE = (
    ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "LowAdxVolumeFullHistoryStrategy.py"
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
BTC_LEVERAGE_TIERS_RAW = json.loads(LEVERAGE_TIER_CACHE.read_text(encoding="utf-8"))[
    "data"
]["BTC/USDT:USDT"]
BTC_LEVERAGE_TIERS = [
    {
        "minNotional": tier["minNotional"],
        "maxNotional": tier["maxNotional"],
        "maintenanceMarginRate": tier["maintenanceMarginRate"],
        "maxLeverage": tier["maxLeverage"],
        "maintAmt": None,
    }
    for tier in BTC_LEVERAGE_TIERS_RAW
]

STAGES = {
    "development": "1646092800-1704067199",
    "validation": "1704067200-1735689599",
    "pseudo_oos": "1735689600-1786579199",
}
COSTS = {
    "baseline_0.0006": 0.0006,
    "stress_0.0008": 0.0008,
    "stress_0.0010": 0.0010,
    "stress_0.0015": 0.0015,
}
ADX_VALUES = (15, 18, 21, 24)
VOLUME_VALUES = (1.25, 1.5, 2.0)
HOLD_VALUES = (48, 72)

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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def strategy_name(adx: int, volume: float, hold: int) -> str:
    volume_code = {1.25: "125", 1.5: "150", 2.0: "200"}[volume]
    return f"LowAdxVolumeA{adx}V{volume_code}H{hold}Strategy"


def parameter_matrix() -> list[dict]:
    return [
        {
            "strategy": strategy_name(adx, volume, hold),
            "adx_max": adx,
            "volume_ratio_max": volume,
            "max_hold_hours": hold,
        }
        for adx in ADX_VALUES
        for volume in VOLUME_VALUES
        for hold in HOLD_VALUES
    ]


def prepare_derived_data() -> dict:
    source_manifest_path = SOURCE_SNAPSHOT / "dataset-manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    expected_hashes = {Path(item["path"]).name: item["sha256"] for item in source_manifest["files"]}

    required = (
        "BTC_USDT_USDT-15m-futures.feather",
        "BTC_USDT_USDT-5m-futures.feather",
        "BTC_USDT_USDT-1h-mark.feather",
        "BTC_USDT_USDT-1h-funding_rate.feather",
    )
    actual_source_hashes = {}
    for name in required:
        source = SOURCE_DATA / name
        actual = sha256(source)
        if actual != expected_hashes[name]:
            raise RuntimeError(f"source snapshot hash mismatch: {name}")
        actual_source_hashes[name] = actual

    target_dir = DERIVED_DATA / "futures"
    target_dir.mkdir(parents=True)
    for name in required[1:]:
        os.link(SOURCE_DATA / name, target_dir / name)

    source_15m = pd.read_feather(SOURCE_DATA / required[0])
    source_15m["bucket"] = source_15m["date"].dt.floor("30min")
    group_sizes = source_15m.groupby("bucket", sort=True).size()
    if not bool((group_sizes == 2).all()):
        raise RuntimeError("15m source cannot be losslessly paired into complete 30m candles")
    derived_30m = (
        source_15m.groupby("bucket", sort=True, as_index=False)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .rename(columns={"bucket": "date"})
    )
    derived_path = target_dir / "BTC_USDT_USDT-30m-futures.feather"
    derived_30m.to_feather(derived_path)

    return {
        "source_snapshot_manifest": str(source_manifest_path),
        "source_snapshot_manifest_sha256": sha256(source_manifest_path),
        "source_file_sha256": actual_source_hashes,
        "derivation": "UTC-aligned pairs of complete 15m candles; OHLC first/max/min/last, volume sum",
        "derived_30m": {
            "path": str(derived_path),
            "sha256": sha256(derived_path),
            "rows": len(derived_30m),
            "first": derived_30m["date"].iloc[0].isoformat(),
            "last": derived_30m["date"].iloc[-1].isoformat(),
        },
        "hardlinked_support_files": {
            name: sha256(target_dir / name) for name in required[1:]
        },
    }


def offline_reload_markets(
    exchange: Exchange,
    force: bool = False,
    *,
    load_leverage_tiers: bool = True,
) -> None:
    exchange._api_async.set_markets([OFFLINE_MARKET])
    exchange._api.set_markets_from_exchange(exchange._api_async)
    exchange._markets = dict(exchange._api_async.markets)
    exchange._leverage_tiers = {"BTC/USDT:USDT": BTC_LEVERAGE_TIERS}
    exchange._last_markets_refresh = 1


def run_backtest(
    label: str,
    strategies: list[str],
    timerange: str,
    fee: float,
) -> Path:
    output = RESULT_ROOT / "backtests" / label
    output.mkdir(parents=True)
    command = [
        "backtesting",
        "-c",
        str(CONFIG),
        "--userdir",
        str(ROOT / "ft_userdata" / "user_data"),
        "--strategy-path",
        str(ROOT / "ft_userdata" / "user_data" / "strategies"),
        "-d",
        str(DERIVED_DATA),
        "--timerange",
        timerange,
        "--timeframe-detail",
        "5m",
        "--timeframe",
        "30m",
        "--pairs",
        "BTC/USDT:USDT",
        "--fee",
        str(fee),
        "--export",
        "trades",
        "--backtest-directory",
        str(output),
        "--cache",
        "none",
    ]
    if len(strategies) == 1:
        command[1:1] = ["--strategy", strategies[0]]
    else:
        command[1:1] = ["--strategy-list", *strategies]

    with patch.object(Exchange, "reload_markets", offline_reload_markets):
        try:
            freqtrade_main(command)
        except SystemExit as error:
            code = int(error.code or 0)
            if code != 0:
                raise RuntimeError(f"Freqtrade failed for {label} with exit code {code}") from error
        finally:
            Backtesting.cleanup()

    archives = list(output.glob("*.zip"))
    if len(archives) != 1:
        raise RuntimeError(f"expected exactly one backtest archive for {label}: {archives}")
    return archives[0]


def load_archive(path: Path) -> dict[str, dict]:
    with ZipFile(path) as archive:
        result_names = [
            name
            for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        if len(result_names) != 1:
            raise RuntimeError(f"unexpected result payload in {path}: {result_names}")
        payload = json.loads(archive.read(result_names[0]))
    return payload["strategy"]


def strict_trade_metrics(trades: list[dict]) -> dict:
    ratios = [float(trade["profit_ratio"]) for trade in trades]
    wins = [value for value in ratios if value > 0]
    losses = [value for value in ratios if value < 0]
    payoff = mean(wins) / abs(mean(losses)) if wins and losses else None
    ratio_pf = sum(wins) / abs(sum(losses)) if losses else None
    return {
        "trades": len(ratios),
        "wins": len(wins),
        "losses": len(losses),
        "draws": len(ratios) - len(wins) - len(losses),
        "win_rate_pct": 100.0 * len(wins) / len(ratios) if ratios else 0.0,
        "average_win_pct": 100.0 * mean(wins) if wins else None,
        "average_loss_abs_pct": 100.0 * abs(mean(losses)) if losses else None,
        "strict_average_payoff_ratio": payoff,
        "profit_factor_trade_ratio": ratio_pf,
    }


def summarize_strategy(stats: dict, archive: Path) -> dict:
    trades = stats["trades"]
    strict = strict_trade_metrics(trades)
    direction = {}
    for name, is_short in (("long", False), ("short", True)):
        direction_trades = [trade for trade in trades if bool(trade["is_short"]) is is_short]
        direction[name] = {
            **strict_trade_metrics(direction_trades),
            "profit_abs_usdt": sum(float(trade["profit_abs"]) for trade in direction_trades),
            "funding_fees_usdt": sum(
                float(trade.get("funding_fees") or 0.0) for trade in direction_trades
            ),
        }
    return {
        **strict,
        "freqtrade_profit_factor": float(stats["profit_factor"]),
        "compounded_return_pct": 100.0
        * (float(stats["final_balance"]) / float(stats["starting_balance"]) - 1.0),
        "starting_balance_usdt": float(stats["starting_balance"]),
        "final_balance_usdt": float(stats["final_balance"]),
        "max_drawdown_account_pct": 100.0 * float(stats["max_drawdown_account"]),
        "max_relative_drawdown_pct": 100.0 * float(stats["max_relative_drawdown"]),
        "funding_fees_usdt": sum(float(trade.get("funding_fees") or 0.0) for trade in trades),
        "direction": direction,
        "archive": str(archive),
        "archive_sha256": sha256(archive),
        "effective_backtest_start": stats["backtest_start"],
        "effective_backtest_end": stats["backtest_end"],
    }


def development_gate(metric: dict) -> bool:
    payoff = metric["strict_average_payoff_ratio"]
    return bool(
        metric["trades"] >= 50
        and metric["win_rate_pct"] >= 40.0
        and payoff is not None
        and payoff >= 2.0
        and metric["freqtrade_profit_factor"] >= 1.2
        and metric["compounded_return_pct"] > 0.0
    )


def select_candidate(metrics: dict[str, dict]) -> tuple[str, bool]:
    eligible = [name for name, metric in metrics.items() if development_gate(metric)]
    pool = eligible or [name for name, metric in metrics.items() if metric["trades"] >= 50]
    if not pool:
        pool = list(metrics)
    selected = max(
        pool,
        key=lambda name: (
            metrics[name]["freqtrade_profit_factor"],
            -metrics[name]["max_drawdown_account_pct"],
            metrics[name]["trades"],
            name,
        ),
    )
    return selected, bool(eligible)


def candidate_parameters(name: str) -> dict:
    return next(item for item in parameter_matrix() if item["strategy"] == name)


def development_neighbors(selected: str, metrics: dict[str, dict]) -> list[dict]:
    params = candidate_parameters(selected)
    neighbors = []
    for dimension, values in (
        ("adx_max", ADX_VALUES),
        ("volume_ratio_max", VOLUME_VALUES),
        ("max_hold_hours", HOLD_VALUES),
    ):
        position = values.index(params[dimension])
        for neighbor_position in (position - 1, position + 1):
            if 0 <= neighbor_position < len(values):
                neighbor_params = dict(params)
                neighbor_params[dimension] = values[neighbor_position]
                name = strategy_name(
                    neighbor_params["adx_max"],
                    neighbor_params["volume_ratio_max"],
                    neighbor_params["max_hold_hours"],
                )
                neighbors.append(
                    {
                        "changed_dimension": dimension,
                        "parameters": candidate_parameters(name),
                        "metrics": metrics[name],
                        "passes_development_gate": development_gate(metrics[name]),
                    }
                )
    return neighbors


def write_summary_csv(rows: list[dict]) -> None:
    fields = [
        "stage",
        "cost_case",
        "fee_each_side",
        "strategy",
        "trades",
        "win_rate_pct",
        "strict_average_payoff_ratio",
        "freqtrade_profit_factor",
        "compounded_return_pct",
        "max_drawdown_account_pct",
        "long_trades",
        "long_win_rate_pct",
        "long_payoff",
        "long_pf_ratio",
        "short_trades",
        "short_win_rate_pct",
        "short_payoff",
        "short_pf_ratio",
        "funding_fees_usdt",
    ]
    with (RESULT_ROOT / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if RESULT_ROOT.exists():
        raise RuntimeError(f"one-shot result directory already exists: {RESULT_ROOT}")
    RESULT_ROOT.mkdir(parents=True)

    data_manifest = prepare_derived_data()
    preregistration = {
        "created_at_utc": utc_now(),
        "protocol": "one-shot chronological low-ADX/non-extreme-volume Donchian study",
        "pair": "BTC/USDT:USDT",
        "contract": "OKX BTC-USDT-SWAP",
        "timeframe": "30m",
        "detail_timeframe": "5m",
        "leverage": 1.0,
        "initial_wallet_usdt": 1000,
        "stake": "unlimited; at most one isolated position; compounds the simulated wallet",
        "signal": {
            "channel": "prior 20 completed 30m highs/lows; first close outside channel",
            "adx": "TA-Lib ADX(14) <= candidate cap",
            "volume_ratio": "current volume / mean of prior 20 completed volumes <= candidate cap",
        },
        "exits": {
            "freqtrade_minimal_roi": 0.03,
            "freqtrade_stoploss": -0.015,
            "maximum_hold_hours": [48, 72],
        },
        "parameter_matrix": parameter_matrix(),
        "stages_utc_epoch_seconds": STAGES,
        "cost_cases_each_side": COSTS,
        "cost_interpretation": (
            "0.0006 baseline is 0.0005 OKX taker plus 0.0001 cash-equivalent slippage; "
            "higher cases are predeclared fee/slippage cash-equivalent pressure, not order-book fills"
        ),
        "selection_policy": {
            "minimum_development_trades": 50,
            "gates": {
                "win_rate_pct_min": 40.0,
                "strict_average_payoff_ratio_min": 2.0,
                "freqtrade_profit_factor_min": 1.2,
                "compounded_return_positive": True,
            },
            "ranking": "highest Freqtrade PF, then lower account DD, then more trades, then name",
            "fallback": "same ranking among >=50 trades (or all if none), marked gate failure",
            "validation_and_pseudo_oos": "frozen candidate only; no parameter callback",
        },
        "funding": {
            "source": "OKX official archive plus exact-overlap REST merge",
            "configured_leading_gap_fallback_per_1h_mark_row": 0.0000042304172276700455,
            "fallback_derivation": "8h mean 0.000033843337821360364 divided by 8",
            "expected_use_in_stages": "none; all stages begin after the archived series is continuous",
        },
        "data": data_manifest,
        "source_hashes": {
            "strategy": sha256(STRATEGY_FILE),
            "config": sha256(CONFIG),
            "runner": sha256(Path(__file__)),
            "okx_leverage_tier_cache": sha256(LEVERAGE_TIER_CACHE),
        },
    }
    write_json(RESULT_ROOT / "preregistration.json", preregistration)

    matrix = parameter_matrix()
    development_archive = run_backtest(
        "development-baseline",
        [item["strategy"] for item in matrix],
        STAGES["development"],
        COSTS["baseline_0.0006"],
    )
    development_payload = load_archive(development_archive)
    development_metrics = {
        name: summarize_strategy(stats, development_archive)
        for name, stats in development_payload.items()
    }
    selected, any_gate_pass = select_candidate(development_metrics)
    neighbors = development_neighbors(selected, development_metrics)

    freeze_manifest = {
        "frozen_at_utc_before_validation": utc_now(),
        "selected_strategy": selected,
        "selected_parameters": candidate_parameters(selected),
        "selected_development_metrics": development_metrics[selected],
        "selected_passes_development_gate": development_gate(development_metrics[selected]),
        "any_candidate_passed_development_gate": any_gate_pass,
        "eligible_candidates": [
            name for name, metric in development_metrics.items() if development_gate(metric)
        ],
        "development_neighbors": neighbors,
        "development_archive": str(development_archive),
        "development_archive_sha256": sha256(development_archive),
    }
    write_json(RESULT_ROOT / "frozen-parameter-manifest.json", freeze_manifest)

    stage_results: dict[str, dict[str, dict]] = {"development": development_metrics}
    summary_rows = []
    for stage in ("validation", "pseudo_oos"):
        stage_results[stage] = {}
        for cost_name, fee in COSTS.items():
            archive = run_backtest(
                f"{stage}-{cost_name}",
                [selected],
                STAGES[stage],
                fee,
            )
            payload = load_archive(archive)
            metric = summarize_strategy(payload[selected], archive)
            stage_results[stage][cost_name] = metric
            summary_rows.append(
                {
                    "stage": stage,
                    "cost_case": cost_name,
                    "fee_each_side": fee,
                    "strategy": selected,
                    "trades": metric["trades"],
                    "win_rate_pct": metric["win_rate_pct"],
                    "strict_average_payoff_ratio": metric["strict_average_payoff_ratio"],
                    "freqtrade_profit_factor": metric["freqtrade_profit_factor"],
                    "compounded_return_pct": metric["compounded_return_pct"],
                    "max_drawdown_account_pct": metric["max_drawdown_account_pct"],
                    "long_trades": metric["direction"]["long"]["trades"],
                    "long_win_rate_pct": metric["direction"]["long"]["win_rate_pct"],
                    "long_payoff": metric["direction"]["long"][
                        "strict_average_payoff_ratio"
                    ],
                    "long_pf_ratio": metric["direction"]["long"][
                        "profit_factor_trade_ratio"
                    ],
                    "short_trades": metric["direction"]["short"]["trades"],
                    "short_win_rate_pct": metric["direction"]["short"]["win_rate_pct"],
                    "short_payoff": metric["direction"]["short"][
                        "strict_average_payoff_ratio"
                    ],
                    "short_pf_ratio": metric["direction"]["short"][
                        "profit_factor_trade_ratio"
                    ],
                    "funding_fees_usdt": metric["funding_fees_usdt"],
                }
            )

    summary = {
        "completed_at_utc": utc_now(),
        "selected_strategy": selected,
        "selected_parameters": candidate_parameters(selected),
        "development_gate_pass": development_gate(development_metrics[selected]),
        "development": development_metrics,
        "development_neighbors": neighbors,
        "validation": stage_results["validation"],
        "pseudo_oos": stage_results["pseudo_oos"],
        "interpretation_boundary": (
            "2025-2026 is retrospective pseudo-OOS, not a prospective blind test; "
            "cash-equivalent slippage stress does not simulate order-book queue or gaps"
        ),
    }
    write_json(RESULT_ROOT / "summary.json", summary)
    write_summary_csv(summary_rows)

    artifact_paths = sorted(
        path
        for path in RESULT_ROOT.rglob("*")
        if path.is_file() and path.name != "artifact-manifest.json"
    )
    write_json(
        RESULT_ROOT / "artifact-manifest.json",
        {
            "generated_at_utc": utc_now(),
            "files": [
                {
                    "path": str(path.relative_to(RESULT_ROOT)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
                for path in artifact_paths
            ],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
