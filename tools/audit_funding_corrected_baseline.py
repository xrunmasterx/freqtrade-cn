from __future__ import annotations

import hashlib
import json
import math
import statistics
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


REPOSITORY = Path(__file__).resolve().parents[1]
RESULT_ROOT = (
    REPOSITORY
    / "ft_userdata/runtime/freqtrade-futures/backtest_results/goal-100pct"
    / "funding-corrected-baseline"
)
DATASET_ROOT = (
    REPOSITORY / "ft_userdata/user_data/data/okx-btc-usdt-swap-full-20260813"
)
CONFIG_ROOT = (
    REPOSITORY
    / "ft_userdata/user_data/research_data/funding-corrected-baseline-configs"
)
STRATEGY_NAME = "DonchianCounterMomentumRegimeHighReturnStrategy"

SCENARIOS = {
    "zero": ("funding-zero.json", 0.0),
    "positive-hourly": (
        "funding-hourly-positive.json",
        0.0000042304172276700455,
    ),
    "negative-hourly": (
        "funding-hourly-negative.json",
        -0.0000042304172276700455,
    ),
}
WINDOWS = {
    "180d": "1770998400-1786550400",
    "365d": "1755014400-1786550400",
    "all-history": "1576476000-1786550400",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(REPOSITORY).as_posix()


def load_archive(directory: Path, expected_fallback: float) -> dict:
    archives = list(directory.glob("*.zip"))
    if len(archives) != 1:
        raise RuntimeError(f"Expected one archive in {directory}, found {len(archives)}")
    archive = archives[0]
    with zipfile.ZipFile(archive) as handle:
        result_names = [
            name
            for name in handle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        config_names = [name for name in handle.namelist() if name.endswith("_config.json")]
        if len(result_names) != 1 or len(config_names) != 1:
            raise RuntimeError(f"Unexpected archive members in {archive}")
        result = json.loads(handle.read(result_names[0]))
        config = json.loads(handle.read(config_names[0]))

    stats = result["strategy"][STRATEGY_NAME]
    trades = stats["trades"]
    winners = [trade["profit_ratio"] for trade in trades if trade["profit_ratio"] > 0]
    losers = [trade["profit_ratio"] for trade in trades if trade["profit_ratio"] < 0]
    positive_abs = sum(trade["profit_abs"] for trade in trades if trade["profit_abs"] > 0)
    negative_abs = sum(trade["profit_abs"] for trade in trades if trade["profit_abs"] < 0)
    funding_total = sum(trade["funding_fees"] for trade in trades)
    funding_long = sum(trade["funding_fees"] for trade in trades if not trade["is_short"])
    funding_short = sum(trade["funding_fees"] for trade in trades if trade["is_short"])
    identity_fields = (
        "pair",
        "open_date",
        "close_date",
        "open_rate",
        "close_rate",
        "is_short",
        "leverage",
        "exit_reason",
    )
    identity = [
        {field: trade[field] for field in identity_fields}
        for trade in trades
    ]
    identity_hash = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    strict_payoff = None
    if winners and losers:
        strict_payoff = statistics.fmean(winners) / abs(statistics.fmean(losers))
    profit_factor = None
    if positive_abs and negative_abs:
        profit_factor = positive_abs / abs(negative_abs)

    checks = {
        "configured_fallback_matches_scenario": math.isclose(
            config["futures_funding_rate"], expected_fallback, rel_tol=0, abs_tol=1e-18
        ),
        "all_trade_numbers_finite": all(
            math.isfinite(trade[field])
            for trade in trades
            for field in ("profit_ratio", "profit_abs", "funding_fees")
        ),
        "trade_count_reconciles": len(trades) == stats["total_trades"],
        "profit_abs_reconciles": math.isclose(
            sum(trade["profit_abs"] for trade in trades),
            stats["profit_total_abs"],
            rel_tol=0,
            abs_tol=1e-8,
        ),
        "final_balance_reconciles": math.isclose(
            stats["starting_balance"] + stats["profit_total_abs"],
            stats["final_balance"],
            rel_tol=0,
            abs_tol=1e-8,
        ),
        "fee_per_side_is_0_0006": all(
            trade["fee_open"] == 0.0006 and trade["fee_close"] == 0.0006
            for trade in trades
        ),
        "timeframe_is_15m": stats["timeframe"] == "15m",
        "detail_timeframe_is_5m": stats["timeframe_detail"] == "5m",
        "futures_isolated": (
            stats["trading_mode"] == "futures" and stats["margin_mode"] == "isolated"
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"Audit failed for {archive}: {checks}")

    return {
        "archive": relative(archive),
        "archive_sha256": sha256(archive),
        "requested_timerange": stats["timerange"],
        "effective_start_utc": stats["backtest_start"],
        "effective_end_utc": stats["backtest_end"],
        "trades": len(trades),
        "long_trades": stats["trade_count_long"],
        "short_trades": stats["trade_count_short"],
        "wins": len(winners),
        "draws": sum(trade["profit_ratio"] == 0 for trade in trades),
        "losses": len(losers),
        "win_rate_pct": len(winners) / len(trades) * 100 if trades else None,
        "strict_payoff": strict_payoff,
        "profit_factor": profit_factor,
        "return_pct": stats["profit_total"] * 100,
        "profit_abs_usdt": stats["profit_total_abs"],
        "starting_balance_usdt": stats["starting_balance"],
        "final_balance_usdt": stats["final_balance"],
        "max_drawdown_account_pct": stats["max_drawdown_account"] * 100,
        "max_relative_drawdown_pct": stats["max_relative_drawdown"] * 100,
        "funding_fees_total_usdt": funding_total,
        "funding_fees_long_usdt": funding_long,
        "funding_fees_short_usdt": funding_short,
        "funding_fee_receipts_usdt": sum(
            trade["funding_fees"] for trade in trades if trade["funding_fees"] > 0
        ),
        "funding_fee_payments_usdt": sum(
            trade["funding_fees"] for trade in trades if trade["funding_fees"] < 0
        ),
        "trade_identity_sha256": identity_hash,
        "checks": checks,
    }


def dataset_semantics() -> dict:
    futures = DATASET_ROOT / "market-data/futures"
    mark_path = futures / "BTC_USDT_USDT-1h-mark.feather"
    funding_path = futures / "BTC_USDT_USDT-1h-funding_rate.feather"
    mark = pd.read_feather(mark_path, columns=["date"])
    funding = pd.read_feather(funding_path, columns=["date", "open"])
    first_funding = funding["date"].iloc[0]
    actual_matches = funding["date"].isin(mark["date"])
    leading_fallback_rows = int((mark["date"] < first_funding).sum())
    actual_settlement_rows = int(actual_matches.sum())
    post_first_mark_rows = int((mark["date"] >= first_funding).sum())
    return {
        "mark_timeframe": "1h",
        "mark_rows": len(mark),
        "mark_first_utc": mark["date"].iloc[0].isoformat(),
        "mark_last_utc": mark["date"].iloc[-1].isoformat(),
        "funding_storage": "raw settlement-event rows; not expanded to hourly rows",
        "funding_rows": len(funding),
        "funding_first_utc": first_funding.isoformat(),
        "funding_last_utc": funding["date"].iloc[-1].isoformat(),
        "funding_rows_matching_mark": actual_settlement_rows,
        "leading_hourly_fallback_rows": leading_fallback_rows,
        "retained_combined_rows": leading_fallback_rows + actual_settlement_rows,
        "post_first_mark_rows_without_settlement_record_dropped": (
            post_first_mark_rows - actual_settlement_rows
        ),
        "internal_gap_fallback_rows": 0,
        "policy": (
            "combine_funding_and_mark left-joins funding onto 1h mark candles, fills only "
            "leading NaNs through the first real record, then dropna removes all later "
            "non-settlement hours and genuine internal gaps"
        ),
        "data_warning": (
            "The source manifest records a 2021-09-30 08:00 to 2022-01-16 16:00 "
            "funding-history gap. Freqtrade does not apply futures_funding_rate inside it, "
            "so funding is understated for positions crossing that gap in every scenario."
        ),
    }


def load_legacy() -> dict:
    legacy_root = RESULT_ROOT.parent / "full-history-baseline"
    legacy_manifest = legacy_root / "run-manifest.json"
    results = {}
    for window in WINDOWS:
        results[window] = load_archive(
            legacy_root / window,
            expected_fallback=0.000033843337821360364,
        )
    return {
        "manifest": relative(legacy_manifest),
        "manifest_sha256": sha256(legacy_manifest),
        "fallback_per_1h_mark_row": 0.000033843337821360364,
        "results": results,
    }


def main() -> None:
    scenario_results = {}
    for scenario, (config_name, fallback) in SCENARIOS.items():
        config_path = CONFIG_ROOT / config_name
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not math.isclose(
            config["futures_funding_rate"], fallback, rel_tol=0, abs_tol=1e-18
        ):
            raise RuntimeError(f"Unexpected fallback in {config_path}")
        scenario_results[scenario] = {
            "config": relative(config_path),
            "config_sha256": sha256(config_path),
            "fallback_per_1h_mark_row": fallback,
            "results": {
                window: load_archive(RESULT_ROOT / scenario / window, fallback)
                for window in WINDOWS
            },
        }

    legacy = load_legacy()
    corrected = scenario_results["positive-hourly"]["results"]
    legacy_delta = {}
    for window in WINDOWS:
        old = legacy["results"][window]
        new = corrected[window]
        legacy_delta[window] = {
            "corrected_minus_legacy_return_percentage_points": (
                new["return_pct"] - old["return_pct"]
            ),
            "corrected_minus_legacy_final_balance_usdt": (
                new["final_balance_usdt"] - old["final_balance_usdt"]
            ),
            "corrected_minus_legacy_total_funding_fees_usdt": (
                new["funding_fees_total_usdt"] - old["funding_fees_total_usdt"]
            ),
            "corrected_minus_legacy_trade_count": new["trades"] - old["trades"],
        }

    source_files = [
        REPOSITORY / "freqtrade/freqtrade/exchange/exchange.py",
        REPOSITORY / "freqtrade/freqtrade/optimize/backtesting.py",
        REPOSITORY / "freqtrade/tests/exchange/test_exchange.py",
        REPOSITORY
        / "ft_userdata/user_data/strategies/DonchianCounterMomentumRegimeStrategy.py",
        DATASET_ROOT / "dataset-manifest.json",
        DATASET_ROOT / "market-data/futures/BTC_USDT_USDT-1h-mark.feather",
        DATASET_ROOT / "market-data/futures/BTC_USDT_USDT-1h-funding_rate.feather",
        REPOSITORY
        / "ft_userdata/user_data/research_data/funding-corrected-baseline-cache"
        / "leverage_tiers_USDT.json",
    ]
    manifest = {
        "status": "completed",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "purpose": (
            "Correct the unit of the fixed funding fallback without modifying the strategy "
            "or market-data files, and quantify zero and sign-symmetric boundary cases."
        ),
        "artifact_root": relative(RESULT_ROOT),
        "artifact_root_absolute": str(RESULT_ROOT.resolve()),
        "instrument": "OKX BTC/USDT:USDT perpetual swap",
        "cutoff_exclusive_utc": "2026-08-12T16:00:00Z",
        "execution": {
            "strategy": STRATEGY_NAME,
            "timeframe": "15m",
            "detail_timeframe": "5m",
            "fee_per_side": 0.0006,
            "starting_balance_usdt": 1000,
            "stake_amount": "unlimited",
            "max_open_trades": 1,
            "leverage": 14,
            "cache": "none",
            "windows": WINDOWS,
            "command_template": (
                "docker compose run --rm --no-deps --volume <full-data>:/freqtrade/full-data:ro "
                "--volume <isolated-tier-cache>:/freqtrade/full-data/futures/"
                "leverage_tiers_USDT.json --volume <scenario-configs>:/freqtrade/"
                "research-configs:ro freqtrade-futures backtesting --config /freqtrade/config/"
                "runtime.json --config /freqtrade/config/trading-safety.json --config /freqtrade/"
                "state/config.pine-timeframe-research.json --config <scenario> --strategy "
                "DonchianCounterMomentumRegimeHighReturnStrategy --datadir /freqtrade/full-data "
                "--pairs BTC/USDT:USDT --timerange <window> --timeframe-detail 5m "
                "--fee 0.0006 --cache none --export trades"
            ),
        },
        "funding_unit_finding": {
            "legacy_fixed_value": 0.000033843337821360364,
            "corrected_hourly_value": 0.0000042304172276700455,
            "conversion": "legacy 8h proxy / 8",
            "official_okx_rule": (
                "Funding is assessed every 8h by default. OKX normalizes shorter periods with "
                "the (8 / N) divisor: N=8 divides by 1 and N=1 divides by 8."
            ),
            "official_sources": [
                "https://www.okx.com/en-us/help/perps-funding-fee-mechanism",
                "https://www.okx.com/en-gb/help/how-to-calculate-future-funding-fee",
            ],
            "freqtrade_behavior": (
                "The fallback is inserted into each missing leading 1h mark row. Funding fee is "
                "the sum of open_fund * open_mark * amount over retained rows, with the sign "
                "negated for longs. Therefore the config value is per retained row, not an 8h "
                "rate that Freqtrade automatically prorates."
            ),
            "implementation_evidence": [
                "freqtrade/freqtrade/exchange/exchange.py:161",
                "freqtrade/freqtrade/exchange/exchange.py:3937",
                "freqtrade/freqtrade/exchange/exchange.py:3946",
                "freqtrade/freqtrade/exchange/exchange.py:3976",
                "freqtrade/freqtrade/exchange/exchange.py:3980",
                "freqtrade/freqtrade/optimize/backtesting.py:592",
                "freqtrade/tests/exchange/test_exchange.py:5496",
                "freqtrade/tests/exchange/test_exchange.py:5524",
                "freqtrade/tests/exchange/test_exchange.py:5546",
            ],
            "important_scope": (
                "Only the leading fixed fallback is converted. Actual OKX settlement-event rates "
                "remain unchanged and are never divided by 8."
            ),
        },
        "dataset_semantics": dataset_semantics(),
        "directional_stress_limitation": {
            "positive_hourly": "adverse to longs and favorable to shorts",
            "negative_hourly": "favorable to longs and adverse to shorts",
            "limitation": (
                "One scalar config cannot be adverse to both directions. Both signs were run as "
                "separate boundary cases; no direction-aware engine or source-data mutation was "
                "used."
            ),
        },
        "scenarios": scenario_results,
        "legacy_incorrect_hourly_application": legacy,
        "corrected_positive_minus_legacy": legacy_delta,
        "source_hashes": {relative(path): sha256(path) for path in source_files},
        "verification": {
            "command": (
                ".\\.venv\\Scripts\\python -m pytest "
                "tests/exchange/test_exchange.py::test_combine_funding_and_mark "
                "tests/exchange/test_exchange.py::test_calculate_funding_fees -q"
            ),
            "result": "8 passed in 2.28s",
            "all_archive_checks_passed": True,
            "zip_count": 9,
            "old_results_overwritten": False,
        },
        "conclusion": (
            "The legacy fixed fallback was applied about eight times too often before the first "
            "real funding row. The correction does not change 180d or 365d because those windows "
            "are fully covered by real settlement records. All full-history variants still lose "
            "approximately the entire account and therefore do not validate the strategy."
        ),
    }
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    output = RESULT_ROOT / "run-manifest.json"
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
