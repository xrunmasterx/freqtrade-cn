from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_ROOT = ROOT / "freqtrade"
sys.path.insert(0, str(FREQTRADE_ROOT))

from freqtrade.exchange.exchange import Exchange
from freqtrade.main import main as freqtrade_main
from freqtrade.optimize.backtesting import Backtesting

STUDY_ROOT = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "goal-100pct"
    / "low-adx-volume-full-history"
)
SOURCE_DATA = STUDY_ROOT / "derived-data" / "market-data" / "futures"
OUTPUT_ROOT = STUDY_ROOT / "funding-stress"
CONFIG = ROOT / "ft_userdata" / "user_data" / "config.low-adx-volume-full-history.json"
STRATEGY_PATH = ROOT / "ft_userdata" / "user_data" / "strategies"
FREEZE_PATH = STUDY_ROOT / "frozen-parameter-manifest.json"
BASELINE_SUMMARY_PATH = STUDY_ROOT / "summary.json"
LEVERAGE_CACHE = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data"
    / "okx"
    / "futures"
    / "leverage_tiers_USDT.json"
)

WINDOWS = {
    "validation": "1704067200-1735689599",
    "pseudo_oos": "1735689600-1786579199",
}
MEAN_8H_RATE = 0.000033843337821360364
SCENARIOS = {
    "zero": 0.0,
    "actual_plus_mean_8h": MEAN_8H_RATE,
    "actual_minus_mean_8h": -MEAN_8H_RATE,
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
RAW_TIERS = json.loads(LEVERAGE_CACHE.read_text(encoding="utf-8"))["data"][
    "BTC/USDT:USDT"
]
PARSED_TIERS = [
    {
        "minNotional": tier["minNotional"],
        "maxNotional": tier["maxNotional"],
        "maintenanceMarginRate": tier["maintenanceMarginRate"],
        "maxLeverage": tier["maxLeverage"],
        "maintAmt": None,
    }
    for tier in RAW_TIERS
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def offline_reload_markets(
    exchange: Exchange,
    force: bool = False,
    *,
    load_leverage_tiers: bool = True,
) -> None:
    exchange._api_async.set_markets([OFFLINE_MARKET])
    exchange._api.set_markets_from_exchange(exchange._api_async)
    exchange._markets = dict(exchange._api_async.markets)
    exchange._leverage_tiers = {"BTC/USDT:USDT": PARSED_TIERS}
    exchange._last_markets_refresh = 1


def offline_load_leverage_tiers(exchange: Exchange) -> dict[str, list[dict]]:
    return {"BTC/USDT:USDT": RAW_TIERS}


def prepare_scenario_data(scenario: str, shift: float) -> tuple[Path, dict]:
    destination = OUTPUT_ROOT / "data" / scenario / "futures"
    destination.mkdir(parents=True)
    for name in (
        "BTC_USDT_USDT-30m-futures.feather",
        "BTC_USDT_USDT-5m-futures.feather",
        "BTC_USDT_USDT-1h-mark.feather",
    ):
        os.link(SOURCE_DATA / name, destination / name)

    source_funding = SOURCE_DATA / "BTC_USDT_USDT-1h-funding_rate.feather"
    funding = pd.read_feather(source_funding)
    if scenario == "zero":
        adjusted = pd.Series(0.0, index=funding.index)
    else:
        adjusted = funding["open"] + shift
    for column in ("open", "high", "low", "close"):
        funding[column] = adjusted
    target_funding = destination / source_funding.name
    funding.to_feather(target_funding)
    return destination.parent, {
        "scenario": scenario,
        "source_funding_sha256": sha256(source_funding),
        "transformation": (
            "preserve actual funding timestamps; set every rate to zero"
            if scenario == "zero"
            else f"preserve actual timestamps; add {shift:+.18f} to every actual 8h event"
        ),
        "rows": len(funding),
        "first": funding["date"].iloc[0].isoformat(),
        "last": funding["date"].iloc[-1].isoformat(),
        "derived_funding_sha256": sha256(target_funding),
    }


def run_backtest(
    strategy: str,
    window: str,
    timerange: str,
    scenario: str,
    datadir: Path,
) -> Path:
    output = OUTPUT_ROOT / "backtests" / f"{window}-{scenario}"
    output.mkdir(parents=True)
    command = [
        "backtesting",
        "--strategy",
        strategy,
        "-c",
        str(CONFIG),
        "--userdir",
        str(ROOT / "ft_userdata" / "user_data"),
        "--strategy-path",
        str(STRATEGY_PATH),
        "-d",
        str(datadir),
        "--timerange",
        timerange,
        "--timeframe-detail",
        "5m",
        "--timeframe",
        "30m",
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
    with (
        patch.object(Exchange, "reload_markets", offline_reload_markets),
        patch.object(Exchange, "load_leverage_tiers", offline_load_leverage_tiers),
    ):
        try:
            freqtrade_main(command)
        except SystemExit as error:
            code = int(error.code or 0)
            if code != 0:
                raise RuntimeError(
                    f"Freqtrade failed for {window}/{scenario} with exit code {code}"
                ) from error
        finally:
            Backtesting.cleanup()
    archives = list(output.glob("*.zip"))
    if len(archives) != 1:
        raise RuntimeError(f"expected one archive for {window}/{scenario}: {archives}")
    return archives[0]


def extract_metrics(path: Path, strategy: str) -> dict:
    with ZipFile(path) as archive:
        result_name = next(
            name
            for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        )
        stats = json.loads(archive.read(result_name))["strategy"][strategy]
    trades = stats["trades"]
    wins = [float(trade["profit_ratio"]) for trade in trades if trade["profit_ratio"] > 0]
    losses = [float(trade["profit_ratio"]) for trade in trades if trade["profit_ratio"] < 0]
    return {
        "trades": len(trades),
        "win_rate_pct": 100.0 * len(wins) / len(trades),
        "strict_average_payoff_ratio": (
            (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
            if wins and losses
            else None
        ),
        "profit_factor": float(stats["profit_factor"]),
        "compounded_return_pct": 100.0
        * (float(stats["final_balance"]) / float(stats["starting_balance"]) - 1.0),
        "max_drawdown_account_pct": 100.0 * float(stats["max_drawdown_account"]),
        "funding_fees_usdt": sum(float(trade.get("funding_fees") or 0.0) for trade in trades),
        "long_profit_pct": 100.0 * float(stats["profit_total_long"]),
        "short_profit_pct": 100.0 * float(stats["profit_total_short"]),
        "archive": str(path),
        "archive_sha256": sha256(path),
    }


def main() -> int:
    if OUTPUT_ROOT.exists():
        raise RuntimeError(f"funding stress output already exists: {OUTPUT_ROOT}")
    OUTPUT_ROOT.mkdir(parents=True)
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    strategy = freeze["selected_strategy"]
    preregistration = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "frozen_strategy": strategy,
        "freeze_manifest_sha256": sha256(FREEZE_PATH),
        "baseline_summary_sha256": sha256(BASELINE_SUMMARY_PATH),
        "fee_each_side": 0.0006,
        "windows": WINDOWS,
        "scenarios": {
            "zero": "same real event timestamps, all rates zero",
            "actual_plus_mean_8h": f"actual rate + {MEAN_8H_RATE} at every actual event",
            "actual_minus_mean_8h": f"actual rate - {MEAN_8H_RATE} at every actual event",
        },
        "selection_boundary": "post-freeze stress only; results cannot change strategy parameters",
        "runner_sha256": sha256(Path(__file__)),
    }
    write_json(OUTPUT_ROOT / "preregistration.json", preregistration)

    scenario_data = {}
    datadirs = {}
    for scenario, shift in SCENARIOS.items():
        datadirs[scenario], scenario_data[scenario] = prepare_scenario_data(scenario, shift)

    results = {}
    for window, timerange in WINDOWS.items():
        results[window] = {}
        for scenario in SCENARIOS:
            archive = run_backtest(strategy, window, timerange, scenario, datadirs[scenario])
            results[window][scenario] = extract_metrics(archive, strategy)

    write_json(
        OUTPUT_ROOT / "summary.json",
        {
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "frozen_strategy": strategy,
            "scenario_data": scenario_data,
            "results": results,
            "interpretation": (
                "Symmetric additive stress around actual event rates; it is not a prediction "
                "of future funding and does not alter event timestamps."
            ),
        },
    )
    files = sorted(
        path
        for path in OUTPUT_ROOT.rglob("*")
        if path.is_file() and path.name != "artifact-manifest.json"
    )
    write_json(
        OUTPUT_ROOT / "artifact-manifest.json",
        {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "files": [
                {
                    "path": str(path.relative_to(OUTPUT_ROOT)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
                for path in files
            ],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
