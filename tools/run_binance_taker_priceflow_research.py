from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_ROOT = REPO_ROOT / "freqtrade"
PYTHON = FREQTRADE_ROOT / ".venv" / "Scripts" / "python.exe"
USER_DATA = REPO_ROOT / "ft_userdata" / "user_data"
RESEARCH_ROOT = USER_DATA / "research_data" / "binance-taker-priceflow-confirmation"
DATA_ROOT = RESEARCH_ROOT / "okx-market-data"
CONFIG = RESEARCH_ROOT / "research-config.json"
PREREGISTRATION = RESEARCH_ROOT / "PREREGISTRATION.md"
OUTPUT_ROOT = RESEARCH_ROOT / "results"
STRATEGY = "PriceFlowBinanceTakerConfirmationResearchStrategy"
PAIR = "BTC/USDT:USDT"
FEE_PER_SIDE = 0.0006
EXPECTED_TIER_UPDATED = "2026-08-12 10:33:49.153543+00:00"
EXPECTED_FIRST_TIER = {
    "tier": 1,
    "symbol": PAIR,
    "currency": "USDT",
    "minNotional": 0.0,
    "maxNotional": 1000.0,
    "maintenanceMarginRate": 0.004,
    "maxLeverage": 100.0,
    "info": {
        "baseMaxLoan": "",
        "imr": "0.01",
        "instFamily": "BTC-USDT",
        "instId": "",
        "maxLever": "100",
        "maxSz": "1000",
        "minSz": "0",
        "mmr": "0.004",
        "optMgnFactor": "0",
        "quoteMaxLoan": "",
        "tier": "1",
        "uly": "BTC-USDT",
    },
}
DEVELOPMENT = ("1646092800", "1704066300")
DEVELOPMENT_LOGICAL = ("2022-03-01T00:00:00Z", "2024-01-01T00:00:00Z")
HOLDOUT_2024 = ("1704067200", "1735687800")
HOLDOUT_2024_LOGICAL = ("2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z")
END_EXCLUSIVE = pd.Timestamp("2025-01-01T00:00:00Z")
PARENT_SOURCE = "ft_userdata/user_data/strategies/PriceFlowContinuationStrategy.py"
STRATEGY_SOURCE = (
    "ft_userdata/user_data/strategies/"
    "PriceFlowBinanceTakerConfirmationResearchStrategy.py"
)
TEST_SOURCE = (
    "ft_userdata/user_data/tests/"
    "test_price_flow_binance_taker_confirmation_research_strategy.py"
)
RESEARCH_RELATIVE = Path(
    "ft_userdata/user_data/research_data/binance-taker-priceflow-confirmation"
)
FUTURES_RELATIVE = RESEARCH_RELATIVE / "okx-market-data" / "futures"
EXPECTED_HASHES = {
    PARENT_SOURCE: (
        "ed1bcbb8cb342826b71fc4ea456b6905e5bd9f91341e6da2029f4d3511ef2f8d"
    ),
    STRATEGY_SOURCE: (
        "fd9a29132bca1e9157b37acfa0fd3950eb87aeb4e6ca3250c6e9889f94b1bad9"
    ),
    TEST_SOURCE: (
        "9f37a54532f9bdd6d88039a6c75f89ccd58a062a3d481ff8bb5c1bb119e31e21"
    ),
    (RESEARCH_RELATIVE / "research-config.json").as_posix(): (
        "8d6b2c4f64dd0c51a77c3a38b181a7f7819a449f0df5c376780491d002a49a74"
    ),
    (RESEARCH_RELATIVE / "binance-data-manifest.json").as_posix(): (
        "4f2ba86b00e35a151d4c40795ed4140032f33c96df971b21fe91252319ebdb34"
    ),
    (RESEARCH_RELATIVE / "derived" / "BTCUSDT-5m-kline-taker.feather").as_posix(): (
        "93caab0c79d2720ff6211e2f8909bbf66c307cc23eb6f85d4e3ac3c0543ca385"
    ),
    (
        RESEARCH_RELATIVE / "derived" / "BTCUSDT-15m-taker-confirmation.feather"
    ).as_posix(): (
        "c34af1b33798369e747c2349d17258a285632f17e6baef14626a323c19f8873f"
    ),
    (RESEARCH_RELATIVE / "okx-data-manifest.json").as_posix(): (
        "d28f954814ed616caea319e7e93ba67833586cd95d566818d91923142f4970c2"
    ),
    (FUTURES_RELATIVE / "BTC_USDT_USDT-5m-futures.feather").as_posix(): (
        "20a5167ff276c28226bc6e85a5ffea91f7dab67ad191626967cc6c6254f77da9"
    ),
    (FUTURES_RELATIVE / "BTC_USDT_USDT-15m-futures.feather").as_posix(): (
        "a8b065b6070c5e59cd021645ec1eb3256dabd2eb546acc276741a3b205235708"
    ),
    (FUTURES_RELATIVE / "BTC_USDT_USDT-1h-futures.feather").as_posix(): (
        "dce2eb3cfe136680413398f4ef39be483d5a8cd3d49b2ed96cd0344c2080dca0"
    ),
    (FUTURES_RELATIVE / "BTC_USDT_USDT-4h-futures.feather").as_posix(): (
        "12a264aa4fcce6ab86b69d021e1c4126c962b401a5fe2445e2bdc75b1951a5da"
    ),
    (FUTURES_RELATIVE / "BTC_USDT_USDT-1h-mark.feather").as_posix(): (
        "2a8a9ba530b17cd8292855772f948fb7d43940cfd312b82c17330e7992e1316b"
    ),
    (FUTURES_RELATIVE / "BTC_USDT_USDT-1h-funding_rate.feather").as_posix(): (
        "98fa273cb29c92a75a0fe09b7f36485b1a810986f4254569aad177f1ca42227d"
    ),
    (FUTURES_RELATIVE / "leverage_tiers_USDT.json").as_posix(): (
        "abc2d7352f237a6ce5a99da7ebc2b320b9584ce13f0d5296943e7713bf4f9825"
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def verify_tier_cache(path: Path) -> None:
    tier_cache = json.loads(path.read_text(encoding="utf-8"))
    if tier_cache.get("updated") != EXPECTED_TIER_UPDATED:
        raise RuntimeError("Leverage-tier cache timestamp differs from the frozen snapshot")
    btc_tiers = tier_cache.get("data", {}).get(PAIR)
    if not isinstance(btc_tiers, list) or len(btc_tiers) != 99:
        raise RuntimeError("Leverage-tier cache does not contain the frozen 99 BTC tiers")
    if btc_tiers[0] != EXPECTED_FIRST_TIER:
        raise RuntimeError("First BTC leverage tier differs from the frozen snapshot")


def verify_frozen_inputs(preregistration_sha256: str) -> None:
    if len(preregistration_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in preregistration_sha256
    ):
        raise ValueError("--prereg-sha256 must be a lowercase SHA-256 digest")
    if sha256(PREREGISTRATION) != preregistration_sha256:
        raise RuntimeError("Preregistration hash mismatch; refusing performance execution")
    for name, expected in EXPECTED_HASHES.items():
        path = REPO_ROOT / name
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"Frozen input hash mismatch for {name}: {actual} != {expected}")

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if config["futures_funding_rate"] != 0.0000042304172276700455:
        raise RuntimeError("Funding fallback differs from the frozen hourly value")
    if config["exchange"]["pair_whitelist"] != [PAIR]:
        raise RuntimeError("Pair whitelist differs from the frozen BTC-only scope")

    futures = DATA_ROOT / "futures"
    verify_tier_cache(futures / "leverage_tiers_USDT.json")
    for path in sorted(futures.glob("*.feather")):
        dates = pd.to_datetime(pd.read_feather(path, columns=["date"])["date"], utc=True)
        if dates.empty or dates.ge(END_EXCLUSIVE).any():
            raise RuntimeError(f"Final input is empty or contains 2025+ rows: {relative(path)}")
    sidecar = pd.read_feather(
        RESEARCH_ROOT / "derived" / "BTCUSDT-15m-taker-confirmation.feather",
        columns=["date", "decision_time"],
    )
    if pd.to_datetime(sidecar["date"], utc=True).ge(END_EXCLUSIVE).any() or pd.to_datetime(
        sidecar["decision_time"], utc=True
    ).ge(END_EXCLUSIVE).any():
        raise RuntimeError("Final Binance sidecar contains a 2025+ timestamp")


def result_archive(directory: Path) -> Path:
    archives = list(directory.glob("*.zip"))
    if len(archives) != 1:
        raise RuntimeError(f"Expected one result archive in {directory}, found {len(archives)}")
    return archives[0]


def read_strategy_result(archive: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as bundle:
        candidates = [
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        if len(candidates) != 1:
            raise RuntimeError(f"Expected one main result JSON, found {len(candidates)}")
        payload = json.loads(bundle.read(candidates[0]))
    return payload["strategy"][STRATEGY]


def timerange_boundary(value: str) -> pd.Timestamp:
    if len(value) == 10 and value.isdigit():
        return pd.Timestamp(int(value), unit="s", tz="UTC")
    return pd.Timestamp(value, tz="UTC")


def summarize(result: dict[str, Any], archive: Path, timerange: tuple[str, str]) -> dict[str, Any]:
    trades = result["trades"]
    profits = [float(trade["profit_ratio"]) for trade in trades]
    profits_abs = [float(trade["profit_abs"]) for trade in trades]
    winners = [value for value in profits if value > 0]
    losers = [value for value in profits if value < 0]
    payoff = (
        statistics.mean(winners) / abs(statistics.mean(losers))
        if winners and losers
        else None
    )
    gross_profit = sum(value for value in profits_abs if value > 0)
    gross_loss = -sum(value for value in profits_abs if value < 0)
    profit_factor = gross_profit / gross_loss if gross_profit > 0 and gross_loss > 0 else None
    open_dates = [pd.Timestamp(str(trade["open_date"])) for trade in trades]
    start = timerange_boundary(timerange[0])
    end = timerange_boundary(timerange[1])
    if any(not (start <= opened < end) for opened in open_dates):
        raise RuntimeError("Backtest emitted a trade outside its frozen stage window")
    leverages = [float(trade.get("leverage", 1.0)) for trade in trades]
    if any(not math.isclose(value, 1.0, rel_tol=0, abs_tol=1e-12) for value in leverages):
        raise RuntimeError("Backtest emitted non-1x trades")

    liquidation_count = sum(
        "liquidation" in str(trade.get("exit_reason") or "").lower()
        for trade in trades
    )
    return {
        "artifact": relative(archive),
        "artifact_sha256": sha256(archive),
        "trades": len(trades),
        "wins": len(winners),
        "losses": len(losers),
        "win_rate": len(winners) / len(trades) if trades else 0.0,
        "strict_payoff": payoff,
        "profit_factor": profit_factor,
        "profit_total_abs": float(result["profit_total_abs"]),
        "profit_total_ratio": float(result["profit_total"]),
        "profit_total_pct": float(result["profit_total_pct"]),
        "max_drawdown_account": float(result["max_drawdown_account"]),
        "max_drawdown_pct": float(result["max_drawdown_account"]) * 100,
        "funding_fees_abs": sum(float(trade.get("funding_fees") or 0) for trade in trades),
        "liquidation_count": liquidation_count,
        "leverage_values": sorted(set(leverages)),
    }


def development_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    payoff = metrics["strict_payoff"]
    profit_factor = metrics["profit_factor"]
    checks = {
        "trades_gte_30": metrics["trades"] >= 30,
        "win_rate_gte_40pct": metrics["win_rate"] >= 0.40,
        "strict_payoff_gte_2": payoff is not None and payoff >= 2.0,
        "profit_factor_gt_1_2": profit_factor is not None and profit_factor > 1.2,
        "profit_gt_0": metrics["profit_total_abs"] > 0,
        "drawdown_lt_25pct": metrics["max_drawdown_account"] < 0.25,
        "liquidation_count_eq_0": metrics["liquidation_count"] == 0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run_stage(
    stage: str,
    timerange: tuple[str, str],
    logical_trade_window: tuple[str, str],
    preregistration_sha256: str,
) -> tuple[dict[str, Any], list[str]]:
    directory = OUTPUT_ROOT / stage
    if directory.exists():
        raise FileExistsError(f"Refusing to reuse or overwrite stage: {directory}")
    directory.mkdir(parents=True)
    command = [
        str(PYTHON),
        "-m",
        "freqtrade",
        "backtesting",
        "--config",
        str(CONFIG),
        "--user-data-dir",
        str(USER_DATA),
        "--datadir",
        str(DATA_ROOT),
        "--strategy",
        STRATEGY,
        "--pairs",
        PAIR,
        "--timeframe",
        "15m",
        "--timeframe-detail",
        "5m",
        "--timerange",
        f"{timerange[0]}-{timerange[1]}",
        "--fee",
        str(FEE_PER_SIDE),
        "--enable-protections",
        "--cache",
        "none",
        "--backtest-directory",
        str(directory),
        "--export",
        "trades",
    ]
    completed = subprocess.run(
        command,
        cwd=FREQTRADE_ROOT,
        env={
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("FREQTRADE__")
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    (directory / "run.log").write_text(
        completed.stdout + "\n" + completed.stderr, encoding="utf-8"
    )
    verify_frozen_inputs(preregistration_sha256)
    if completed.returncode != 0:
        raise RuntimeError(f"Freqtrade {stage} execution exited {completed.returncode}")
    archive = result_archive(directory)
    return summarize(read_strategy_result(archive), archive, logical_trade_window), command


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the single frozen research-only protocol.")
    parser.add_argument("--prereg-sha256", required=True)
    args = parser.parse_args()
    preregistration_sha256 = args.prereg_sha256.lower()

    verify_frozen_inputs(preregistration_sha256)
    if OUTPUT_ROOT.exists():
        raise FileExistsError(f"Refusing to reuse research output root: {OUTPUT_ROOT}")
    OUTPUT_ROOT.mkdir()

    development, development_command = run_stage(
        "development", DEVELOPMENT, DEVELOPMENT_LOGICAL, preregistration_sha256
    )
    gate = development_gate(development)
    development_receipt = {
        "research_only": True,
        "stage": "development",
        "window": {"start_inclusive": "2022-03-01", "end_exclusive": "2024-01-01"},
        "raw_main_timeframe_candle_timerange": {
            "value": "1646092800-1704066300",
            "stop_semantics": "inclusive",
            "first_open": "2022-03-01T00:00:00Z",
            "last_open": "2023-12-31T23:45:00Z",
        },
        "preregistration_sha256": preregistration_sha256,
        "fee_per_side": FEE_PER_SIDE,
        "timeframe": "15m",
        "timeframe_detail": "5m",
        "runtime_exchange_metadata_dependency": (
            "OKX public API markets/precision; all FREQTRADE__* environment overrides removed"
        ),
        "metrics": development,
        "gate": gate,
        "command": development_command,
    }
    write_json(OUTPUT_ROOT / "development-receipt.json", development_receipt)
    if not gate["passed"]:
        write_json(
            OUTPUT_ROOT / "terminal-receipt.json",
            {
                "status": "DEVELOPMENT_REJECTED",
                "holdout_2024_opened": False,
                "preregistration_sha256": preregistration_sha256,
                "development_receipt_sha256": sha256(
                    OUTPUT_ROOT / "development-receipt.json"
                ),
            },
        )
        print(json.dumps(development_receipt, indent=2, sort_keys=True))
        return 2

    freeze = {
        "status": "FROZEN_AFTER_DEVELOPMENT_GATE_PASS",
        "preregistration_sha256": preregistration_sha256,
        "development_receipt_sha256": sha256(OUTPUT_ROOT / "development-receipt.json"),
        "strategy_sha256": EXPECTED_HASHES[STRATEGY_SOURCE],
        "validation_main_timeframe_open_window": {
            "start_inclusive": "2024-01-01T00:00:00Z",
            "raw_stop_inclusive": "2024-12-31T23:30:00Z",
            "last_allowed_open": "2024-12-31T23:30:00Z",
        },
        "validation_raw_timerange": "1704067200-1735687800",
        "validation_decision_boundary": "decision_time < 2025-01-01T00:00:00Z",
        "holdout_runs_authorized": 1,
    }
    write_json(OUTPUT_ROOT / "freeze-before-2024.json", freeze)
    holdout, holdout_command = run_stage(
        "holdout-2024", HOLDOUT_2024, HOLDOUT_2024_LOGICAL, preregistration_sha256
    )
    holdout_gate = development_gate(holdout)
    holdout_receipt = {
        "research_only": True,
        "stage": "holdout-2024",
        "main_timeframe_open_window": {
            "start_inclusive": "2024-01-01T00:00:00Z",
            "raw_stop_inclusive": "2024-12-31T23:30:00Z",
            "last_allowed_open": "2024-12-31T23:30:00Z",
        },
        "raw_main_timeframe_candle_timerange": "1704067200-1735687800",
        "decision_boundary": "decision_time < 2025-01-01T00:00:00Z",
        "preregistration_sha256": preregistration_sha256,
        "freeze_sha256": sha256(OUTPUT_ROOT / "freeze-before-2024.json"),
        "runs_executed": 1,
        "fee_per_side": FEE_PER_SIDE,
        "timeframe": "15m",
        "timeframe_detail": "5m",
        "runtime_exchange_metadata_dependency": (
            "OKX public API markets/precision; all FREQTRADE__* environment overrides removed"
        ),
        "metrics": holdout,
        "gate": holdout_gate,
        "command": holdout_command,
    }
    write_json(OUTPUT_ROOT / "holdout-2024-receipt.json", holdout_receipt)
    write_json(
        OUTPUT_ROOT / "terminal-receipt.json",
        {
            "status": (
                "VALIDATION_PASSED" if holdout_gate["passed"] else "VALIDATION_REJECTED"
            ),
            "research_only": True,
            "paper_or_live_authorized": False,
            "validation_is_retrospective_not_fresh_holdout": True,
            "holdout_2024_opened": True,
            "holdout_2024_runs": 1,
            "preregistration_sha256": preregistration_sha256,
            "holdout_receipt_sha256": sha256(OUTPUT_ROOT / "holdout-2024-receipt.json"),
        },
    )
    print(json.dumps({"development": development_receipt, "holdout": holdout_receipt}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
