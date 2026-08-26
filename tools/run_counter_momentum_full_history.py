from __future__ import annotations

import csv
import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_ROOT = ROOT / "freqtrade"
USERDIR = ROOT / "ft_userdata" / "user_data"
STRATEGY_FILE = USERDIR / "strategies" / "CounterMomentumFullHistoryStrategy.py"
CONFIG_FILE = USERDIR / "config.counter-momentum-full-history.json"
DATA_ROOT = USERDIR / "data" / "okx-btc-usdt-swap-full-20260813" / "market-data"
DATA_FILES = (
    DATA_ROOT / "futures" / "BTC_USDT_USDT-5m-futures.feather",
    DATA_ROOT / "futures" / "BTC_USDT_USDT-15m-futures.feather",
    DATA_ROOT / "futures" / "BTC_USDT_USDT-1h-futures.feather",
    DATA_ROOT / "futures" / "BTC_USDT_USDT-1h-mark.feather",
    DATA_ROOT / "futures" / "BTC_USDT_USDT-1h-funding_rate.feather",
)
DEFAULT_OUTPUT = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "goal-100pct"
    / "counter-momentum-full-history-1x-v5"
)

sys.path.insert(0, str(FREQTRADE_ROOT))

from freqtrade.exchange.exchange import Exchange
from freqtrade.exchange.okx import Okx
from freqtrade.main import main as freqtrade_main

STAGES = {
    "development": {
        "timerange": "1646092800-1704067199",
        "label": "2022-03-01T00:00:00Z/2023-12-31T23:59:59Z",
    },
    "validation": {
        "timerange": "1704067200-1735689599",
        "label": "2024-01-01T00:00:00Z/2024-12-31T23:59:59Z",
    },
    "pre_oos": {
        "timerange": "1646092800-1735689599",
        "label": "2022-03-01T00:00:00Z/2024-12-31T23:59:59Z",
    },
    "oos": {
        "timerange": "1735689600-1786579199",
        "label": "2025-01-01T00:00:00Z/2026-08-12T23:59:59Z",
    },
}
FUNDING_FALLBACK_PER_HOUR = 0.0000042304172276700455
FUNDING_STRESS = {
    "zero": 0.0,
    "positive_2x": FUNDING_FALLBACK_PER_HOUR * 2,
    "negative_2x": -FUNDING_FALLBACK_PER_HOUR * 2,
}

BASELINE = "CounterMomentumFullHistoryBaselineStrategy"
CANDIDATES = (
    BASELINE,
    "CounterMomentumFullHistoryLookback60Strategy",
    "CounterMomentumFullHistoryLookback84Strategy",
    "CounterMomentumFullHistoryThreshold125Strategy",
    "CounterMomentumFullHistoryThreshold225Strategy",
    "CounterMomentumFullHistoryEma384Strategy",
    "CounterMomentumFullHistoryEma576Strategy",
    "CounterMomentumFullHistoryHold72Strategy",
)
CANDIDATE_PARAMETERS = {
    BASELINE: {"lookback_h": 72, "threshold": -0.0175, "ema_h": 480, "hold_h": 48},
    "CounterMomentumFullHistoryLookback60Strategy": {
        "lookback_h": 60,
        "threshold": -0.0175,
        "ema_h": 480,
        "hold_h": 48,
    },
    "CounterMomentumFullHistoryLookback84Strategy": {
        "lookback_h": 84,
        "threshold": -0.0175,
        "ema_h": 480,
        "hold_h": 48,
    },
    "CounterMomentumFullHistoryThreshold125Strategy": {
        "lookback_h": 72,
        "threshold": -0.0125,
        "ema_h": 480,
        "hold_h": 48,
    },
    "CounterMomentumFullHistoryThreshold225Strategy": {
        "lookback_h": 72,
        "threshold": -0.0225,
        "ema_h": 480,
        "hold_h": 48,
    },
    "CounterMomentumFullHistoryEma384Strategy": {
        "lookback_h": 72,
        "threshold": -0.0175,
        "ema_h": 384,
        "hold_h": 48,
    },
    "CounterMomentumFullHistoryEma576Strategy": {
        "lookback_h": 72,
        "threshold": -0.0175,
        "ema_h": 576,
        "hold_h": 48,
    },
    "CounterMomentumFullHistoryHold72Strategy": {
        "lookback_h": 72,
        "threshold": -0.0175,
        "ema_h": 480,
        "hold_h": 72,
    },
}
ELIGIBILITY = {
    "development_min_trades": 20,
    "validation_min_trades": 10,
    "both_splits_min_win_rate_pct": 40.0,
    "both_splits_min_strict_payoff": 2.0,
    "both_splits_min_profit_factor": 1.0,
    "both_splits_min_return_pct_exclusive": 0.0,
    "both_splits_max_account_drawdown_pct": 20.0,
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
OFFLINE_LEVERAGE_TIERS = {
    "BTC/USDT:USDT": [
        {
            "tier": 1,
            "symbol": "BTC/USDT:USDT",
            "currency": "USDT",
            "minNotional": 0.0,
            "maxNotional": 1_000_000_000.0,
            "maintenanceMarginRate": 0.004,
            "maxLeverage": 100.0,
            "info": {},
        }
    ]
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
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
    exchange._last_markets_refresh = 1


def offline_ohlcv_candle_limit(
    exchange: Okx, timeframe: str, candle_type: Any, since_ms: int | None = None
) -> int:
    # The exchange API page limit is irrelevant when backtesting a complete local file.
    # Raising only this runner-local validation ceiling admits the 1,499h EMA warmup.
    return 2000


def offline_load_leverage_tiers(exchange: Exchange) -> dict[str, list[dict[str, Any]]]:
    # A 1x study cannot approach liquidation. This broad local tier only satisfies the
    # futures engine's metadata invariant; it does not alter entry, exit, fee, funding,
    # leverage, or position size.
    return OFFLINE_LEVERAGE_TIERS


def run_backtest(
    stage: str,
    strategies: tuple[str, ...],
    output: Path,
    config_file: Path = CONFIG_FILE,
) -> Path:
    output.mkdir(parents=True, exist_ok=False)
    before = set(output.glob("*.zip"))
    command = [
        "backtesting",
        "--strategy-list",
        *strategies,
        "-c",
        str(config_file),
        "--userdir",
        str(USERDIR),
        "--strategy-path",
        str(STRATEGY_FILE.parent),
        "-d",
        str(DATA_ROOT),
        "--timerange",
        STAGES[stage]["timerange"],
        "--timeframe-detail",
        "5m",
        "--timeframe",
        "15m",
        "--pairs",
        "BTC/USDT:USDT",
        "--fee",
        "0.0006",
        "--export",
        "trades",
        "--breakdown",
        "month",
        "--backtest-directory",
        str(output),
        "--cache",
        "none",
    ]
    with (
        patch.object(Exchange, "reload_markets", offline_reload_markets),
        patch.object(Exchange, "load_leverage_tiers", offline_load_leverage_tiers),
        patch.object(Okx, "ohlcv_candle_limit", offline_ohlcv_candle_limit),
    ):
        try:
            freqtrade_main(command)
        except SystemExit as error:
            if error.code not in (None, 0):
                raise RuntimeError(f"Freqtrade {stage} failed with exit code {error.code}")
    created = sorted(set(output.glob("*.zip")) - before, key=lambda path: path.stat().st_mtime)
    if len(created) != 1:
        raise RuntimeError(f"Expected one new {stage} result ZIP, found {len(created)}")
    return created[0]


def load_strategy_results(path: Path) -> dict[str, dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        entries = [
            name
            for name in archive.namelist()
            if name.endswith(".json")
            and not name.endswith("_config.json")
            and "_strategy" not in name
        ]
        if len(entries) != 1:
            raise RuntimeError(f"Expected one result JSON in {path}, found {entries}")
        payload = json.loads(archive.read(entries[0]))
    return payload["strategy"]


def ratio_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [float(trade["profit_ratio"]) for trade in trades if trade["profit_ratio"] > 0]
    losses = [float(trade["profit_ratio"]) for trade in trades if trade["profit_ratio"] < 0]
    total = len(trades)
    strict_payoff = None
    profit_factor = None
    if wins and losses:
        strict_payoff = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
        profit_factor = sum(wins) / abs(sum(losses))
    elif wins and not losses:
        profit_factor = "infinity"
    long_count = sum(not bool(trade["is_short"]) for trade in trades)
    short_count = total - long_count
    return {
        "trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "draws": total - len(wins) - len(losses),
        "win_rate_pct": len(wins) / total * 100 if total else None,
        "strict_payoff": strict_payoff,
        "profit_factor": profit_factor,
        "long_trades": long_count,
        "short_trades": short_count,
        "dominant_direction": (
            "long" if long_count > short_count else "short" if short_count > long_count else "tie"
        ),
        "direction_concentration_pct": max(long_count, short_count) / total * 100
        if total
        else None,
        "funding_fees_usdt": sum(float(trade.get("funding_fees", 0.0)) for trade in trades),
    }


def stage_metrics(result: dict[str, Any]) -> dict[str, Any]:
    metrics = ratio_metrics(result["trades"])
    metrics.update(
        {
            "return_pct": float(result["profit_total"]) * 100,
            "profit_usdt": float(result["profit_total_abs"]),
            "starting_balance_usdt": float(result["starting_balance"]),
            "ending_balance_usdt": float(result["final_balance"]),
            "max_account_drawdown_pct": float(result["max_drawdown_account"]) * 100,
            "max_relative_drawdown_pct": float(result["max_relative_drawdown"]) * 100,
            "effective_start": result["backtest_start"],
            "effective_end": result["backtest_end"],
        }
    )
    return metrics


def is_eligible(development: dict[str, Any], validation: dict[str, Any]) -> bool:
    if development["trades"] < ELIGIBILITY["development_min_trades"]:
        return False
    if validation["trades"] < ELIGIBILITY["validation_min_trades"]:
        return False
    for metrics in (development, validation):
        if metrics["win_rate_pct"] is None or metrics["win_rate_pct"] < 40.0:
            return False
        if metrics["strict_payoff"] is None or metrics["strict_payoff"] < 2.0:
            return False
        if not isinstance(metrics["profit_factor"], float) or metrics["profit_factor"] <= 1.0:
            return False
        if metrics["return_pct"] <= 0.0:
            return False
        if metrics["max_account_drawdown_pct"] > 20.0:
            return False
    return True


def select_candidate(
    development: dict[str, dict[str, Any]], validation: dict[str, dict[str, Any]]
) -> tuple[str, str, list[str]]:
    eligible = [
        candidate
        for candidate in CANDIDATES
        if is_eligible(development[candidate], validation[candidate])
    ]
    if BASELINE in eligible:
        return BASELINE, "eligible_baseline_preferred_without_parameter_change", eligible
    if not eligible:
        return BASELINE, "no_candidate_eligible_baseline_retained_as_rejected_diagnostic", []

    order = {candidate: index for index, candidate in enumerate(CANDIDATES)}

    def rank(candidate: str) -> tuple[float, float, int]:
        minimum_profit_factor = min(
            float(development[candidate]["profit_factor"]),
            float(validation[candidate]["profit_factor"]),
        )
        maximum_drawdown = max(
            development[candidate]["max_account_drawdown_pct"],
            validation[candidate]["max_account_drawdown_pct"],
        )
        return (-minimum_profit_factor, maximum_drawdown, order[candidate])

    selected = min(eligible, key=rank)
    return selected, "eligible_single_axis_best_worst_split_profit_factor", eligible


def write_candidate_matrix(
    path: Path,
    development: dict[str, dict[str, Any]],
    validation: dict[str, dict[str, Any]],
    eligible: list[str],
) -> None:
    rows = []
    for candidate in CANDIDATES:
        for stage, metrics in (("development", development[candidate]), ("validation", validation[candidate])):
            rows.append(
                {
                    "candidate": candidate,
                    "stage": stage,
                    **CANDIDATE_PARAMETERS[candidate],
                    **metrics,
                    "eligible_on_both_splits": candidate in eligible,
                }
            )
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def month_floor(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def parse_close(trade: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(trade["close_date"])


def stitch_trades(stage_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    balance = 1000.0
    stitched: list[dict[str, Any]] = []
    for stage in ("development", "validation", "oos"):
        result = stage_results[stage]
        scale = balance / float(result["starting_balance"])
        for trade in sorted(result["trades"], key=parse_close):
            row = dict(trade)
            row["research_stage"] = stage
            row["scaled_profit_abs"] = float(trade["profit_abs"]) * scale
            stitched.append(row)
            balance += row["scaled_profit_abs"]
    return stitched


def close_to_close_drawdown(start_balance: float, trades: list[dict[str, Any]]) -> float:
    balance = start_balance
    peak = start_balance
    maximum = 0.0
    for trade in sorted(trades, key=parse_close):
        balance += float(trade["scaled_profit_abs"])
        peak = max(peak, balance)
        if peak > 0:
            maximum = max(maximum, (peak - balance) / peak)
    return maximum * 100


def window_row(
    label: str,
    start: datetime,
    end: datetime,
    start_balance: float,
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = [trade for trade in trades if start <= parse_close(trade) < end]
    profit = sum(float(trade["scaled_profit_abs"]) for trade in selected)
    metrics = ratio_metrics(selected)
    return {
        "window": label,
        "start_utc": start.isoformat(),
        "end_exclusive_utc": end.isoformat(),
        **metrics,
        "return_pct": profit / start_balance * 100 if start_balance else None,
        "profit_usdt": profit,
        "starting_balance_usdt": start_balance,
        "ending_balance_usdt": start_balance + profit,
        "realized_close_to_close_drawdown_pct": close_to_close_drawdown(
            start_balance, selected
        ),
    }


def balance_before(start: datetime, trades: list[dict[str, Any]]) -> float:
    return 1000.0 + sum(
        float(trade["scaled_profit_abs"])
        for trade in trades
        if parse_close(trade) < start
    )


def rolling_rows(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    first = datetime(2022, 3, 1, tzinfo=UTC)
    stop = datetime(2026, 9, 1, tzinfo=UTC)
    calendar_rows: list[dict[str, Any]] = []
    rolling_30d_rows: list[dict[str, Any]] = []
    cursor = first
    while cursor < stop:
        following = next_month(cursor)
        start_balance = balance_before(cursor, trades)
        calendar_rows.append(
            window_row(cursor.strftime("%Y-%m"), cursor, following, start_balance, trades)
        )
        rolling_stop = cursor + timedelta(days=30)
        rolling_30d_rows.append(
            window_row(
                f"{cursor.date().isoformat()}+30d",
                cursor,
                rolling_stop,
                start_balance,
                trades,
            )
        )
        cursor = following
    return calendar_rows, rolling_30d_rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def format_value(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    if value == "infinity":
        return "∞"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def write_report(
    path: Path,
    selected: str,
    selection_reason: str,
    eligible: list[str],
    stage_metrics_by_name: dict[str, dict[str, Any]],
    stress_metrics: dict[str, dict[str, Any]],
    calendar_rows: list[dict[str, Any]],
    rolling_30d_rows: list[dict[str, Any]],
) -> None:
    lines = [
        "# Counter-momentum full-history sealed study",
        "",
        f"Frozen candidate: `{selected}`",
        f"Selection result: `{selection_reason}`",
        f"Eligible candidates before OOS: `{', '.join(eligible) if eligible else 'none'}`",
        "",
        "| Split | Trades | Return | Win rate | Strict payoff | PF | Account DD | Long/Short | Direction concentration |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for stage in ("development", "validation", "oos"):
        metrics = stage_metrics_by_name[stage]
        lines.append(
            "| "
            + " | ".join(
                [
                    stage,
                    str(metrics["trades"]),
                    f"{format_value(metrics['return_pct'])}%",
                    f"{format_value(metrics['win_rate_pct'])}%",
                    format_value(metrics["strict_payoff"]),
                    format_value(metrics["profit_factor"]),
                    f"{format_value(metrics['max_account_drawdown_pct'])}%",
                    f"{metrics['long_trades']}/{metrics['short_trades']}",
                    f"{format_value(metrics['direction_concentration_pct'])}%",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Frozen-candidate pre-OOS funding fallback stress",
            "",
            "| Scenario | Hourly fallback | Trades | Return | Win rate | Strict payoff | PF | Account DD |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for scenario, metrics in stress_metrics.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    scenario,
                    format_value(FUNDING_STRESS[scenario], 8),
                    str(metrics["trades"]),
                    f"{format_value(metrics['return_pct'])}%",
                    f"{format_value(metrics['win_rate_pct'])}%",
                    format_value(metrics["strict_payoff"]),
                    format_value(metrics["profit_factor"]),
                    f"{format_value(metrics['max_account_drawdown_pct'])}%",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            (
                "Execution assumptions: 1x isolated perpetual, one full-wallet position, "
                "market orders, OKX historical funding, 5m detail, and 0.06% each side "
                "(0.05% taker fee + 0.01% cash-equivalent slippage proxy)."
            ),
            "",
            (
                "Strict payoff is mean winning `profit_ratio` divided by the absolute mean "
                "losing `profit_ratio`; it is N/A when either side has no sample. Calendar "
                "and rolling-30d rows are derived from the three sealed continuous split runs "
                "and assign P&L to trade close time. Their drawdown is realized "
                "close-to-close, not intratrade Freqtrade DD."
            ),
            "",
            f"Calendar rows: {len(calendar_rows)}; rolling 30-day rows: {len(rolling_30d_rows)}.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def source_hashes() -> dict[str, str]:
    paths = (STRATEGY_FILE, CONFIG_FILE, Path(__file__).resolve(), *DATA_FILES)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing sealed-study inputs: {missing}")
    return {str(path.relative_to(ROOT)): sha256(path) for path in paths}


def write_funding_scenario_config(path: Path, funding_rate: float) -> None:
    payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if payload["futures_funding_rate"] != FUNDING_FALLBACK_PER_HOUR:
        raise RuntimeError("Base config funding fallback differs from the preregistered hourly rate")
    payload["futures_funding_rate"] = funding_rate
    write_json(path, payload)


def main() -> int:
    output = DEFAULT_OUTPUT
    if output.exists():
        raise FileExistsError(
            f"Refusing to overwrite sealed study directory: {output}. "
            "A repeat must use a new explicitly versioned path."
        )
    output.mkdir(parents=True)
    preregistration = {
        "created_at_utc": utc_now(),
        "purpose": "single-axis audit without using 2025+ data for parameter selection",
        "pair": "BTC/USDT:USDT",
        "timeframe": "15m",
        "detail_timeframe": "5m",
        "leverage": 1.0,
        "fee_each_side": 0.0005,
        "slippage_proxy_each_side": 0.0001,
        "freqtrade_fee_argument_each_side": 0.0006,
        "funding": {
            "actual_series": "OKX historical funding-rate feather",
            "gap_fallback_per_hour": FUNDING_FALLBACK_PER_HOUR,
            "conversion": "8h fallback mean divided by 8 before Freqtrade hourly mark filling",
            "pre_oos_stress": FUNDING_STRESS,
            "stress_use": "frozen candidate only; never used to change its identity",
        },
        "stages": STAGES,
        "candidate_order": CANDIDATES,
        "candidate_parameters": CANDIDATE_PARAMETERS,
        "eligibility": ELIGIBILITY,
        "selection_rule": [
            "Prefer the unchanged baseline if it is eligible on development and validation.",
            "Otherwise choose an eligible single-axis neighbor with the highest minimum profit factor across the two splits.",
            "Break ties by lower worst split account drawdown, then fixed candidate order.",
            "If none is eligible, retain the unchanged baseline only as a rejected OOS diagnostic.",
            "Seal candidate identity before fixed zero and +/-2x pre-OOS funding stresses.",
            "Write and hash the freeze manifest before opening OOS exactly once.",
        ],
        "source_hashes": source_hashes(),
    }
    prereg_path = output / "preregistration.json"
    write_json(prereg_path, preregistration)

    development_zip = run_backtest(
        "development", CANDIDATES, output / "development"
    )
    validation_zip = run_backtest("validation", CANDIDATES, output / "validation")
    development_results = load_strategy_results(development_zip)
    validation_results = load_strategy_results(validation_zip)
    if tuple(development_results) != CANDIDATES or tuple(validation_results) != CANDIDATES:
        raise RuntimeError("Backtest result strategy order/content differs from preregistration")
    development_metrics = {
        candidate: stage_metrics(development_results[candidate]) for candidate in CANDIDATES
    }
    validation_metrics = {
        candidate: stage_metrics(validation_results[candidate]) for candidate in CANDIDATES
    }
    selected, selection_reason, eligible = select_candidate(
        development_metrics, validation_metrics
    )
    write_candidate_matrix(
        output / "candidate-matrix.csv",
        development_metrics,
        validation_metrics,
        eligible,
    )

    current_hashes = source_hashes()
    if current_hashes != preregistration["source_hashes"]:
        raise RuntimeError("A sealed input changed during development/validation screening")
    selection_manifest = {
        "selected_at_utc": utc_now(),
        "selected_strategy": selected,
        "selection_reason": selection_reason,
        "eligible_candidates": eligible,
        "development_metrics": development_metrics,
        "validation_metrics": validation_metrics,
        "preregistration_sha256": sha256(prereg_path),
        "development_result_sha256": sha256(development_zip),
        "validation_result_sha256": sha256(validation_zip),
        "source_hashes": current_hashes,
        "candidate_identity_status": "sealed_before_funding_stress_and_oos",
    }
    selection_path = output / "selection-manifest.json"
    write_json(selection_path, selection_manifest)
    selection_hash = sha256(selection_path)

    stress_root = output / "funding-stress-configs"
    stress_root.mkdir()
    stress_metrics: dict[str, dict[str, Any]] = {}
    stress_result_hashes: dict[str, str] = {}
    stress_config_hashes: dict[str, str] = {}
    for scenario, fallback in FUNDING_STRESS.items():
        scenario_config = stress_root / f"{scenario}.json"
        write_funding_scenario_config(scenario_config, fallback)
        stress_config_hashes[scenario] = sha256(scenario_config)
        stress_zip = run_backtest(
            "pre_oos",
            (selected,),
            output / "funding-stress" / scenario,
            scenario_config,
        )
        result = load_strategy_results(stress_zip)
        if tuple(result) != (selected,):
            raise RuntimeError(f"Funding stress {scenario} did not run only the frozen strategy")
        stress_metrics[scenario] = stage_metrics(result[selected])
        stress_result_hashes[scenario] = sha256(stress_zip)
        if sha256(selection_path) != selection_hash:
            raise RuntimeError("Candidate identity changed during pre-OOS funding stress")

    if source_hashes() != current_hashes:
        raise RuntimeError("A sealed input changed during pre-OOS funding stress")
    freeze_manifest = {
        "frozen_at_utc": utc_now(),
        "selected_strategy": selected,
        "selection_reason": selection_reason,
        "eligible_candidates": eligible,
        "selection_manifest_sha256": selection_hash,
        "funding_fallback_per_hour": FUNDING_FALLBACK_PER_HOUR,
        "funding_stress_values_per_hour": FUNDING_STRESS,
        "funding_stress_metrics_pre_oos": stress_metrics,
        "funding_stress_config_sha256": stress_config_hashes,
        "funding_stress_result_sha256": stress_result_hashes,
        "source_hashes": current_hashes,
        "oos_status": "sealed_not_opened",
    }
    freeze_path = output / "freeze-manifest.json"
    write_json(freeze_path, freeze_manifest)
    freeze_hash_before_oos = sha256(freeze_path)

    oos_started_at = utc_now()
    oos_zip = run_backtest("oos", (selected,), output / "oos")
    oos_results = load_strategy_results(oos_zip)
    if tuple(oos_results) != (selected,):
        raise RuntimeError("OOS result does not contain only the frozen strategy")
    if source_hashes() != current_hashes or sha256(freeze_path) != freeze_hash_before_oos:
        raise RuntimeError("A sealed input or freeze manifest changed while OOS was running")
    oos_metrics = stage_metrics(oos_results[selected])
    oos_receipt = {
        "opened_once_at_utc": oos_started_at,
        "completed_at_utc": utc_now(),
        "strategy": selected,
        "timerange": STAGES["oos"],
        "freeze_manifest_sha256_before_oos": freeze_hash_before_oos,
        "result_zip": str(oos_zip.relative_to(ROOT)),
        "result_zip_sha256": sha256(oos_zip),
        "metrics": oos_metrics,
    }
    write_json(output / "oos-open-receipt.json", oos_receipt)

    selected_stage_results = {
        "development": development_results[selected],
        "validation": validation_results[selected],
        "oos": oos_results[selected],
    }
    stage_metrics_by_name = {
        "development": development_metrics[selected],
        "validation": validation_metrics[selected],
        "oos": oos_metrics,
    }
    stitched = stitch_trades(selected_stage_results)
    calendar_rows, rolling_30d_rows = rolling_rows(stitched)
    write_csv(output / "calendar-month-metrics.csv", calendar_rows)
    write_csv(output / "rolling-30d-monthly-step-metrics.csv", rolling_30d_rows)
    summary = {
        "completed_at_utc": utc_now(),
        "selected_strategy": selected,
        "selection_reason": selection_reason,
        "eligible_candidates": eligible,
        "stage_metrics": stage_metrics_by_name,
        "funding_stress_metrics_pre_oos": stress_metrics,
        "calendar_month_count": len(calendar_rows),
        "rolling_30d_monthly_step_count": len(rolling_30d_rows),
        "artifact_hashes": {
            "preregistration": sha256(prereg_path),
            "selection_manifest": sha256(selection_path),
            "freeze_manifest": sha256(freeze_path),
            "candidate_matrix": sha256(output / "candidate-matrix.csv"),
            "oos_receipt": sha256(output / "oos-open-receipt.json"),
            "calendar_month_metrics": sha256(output / "calendar-month-metrics.csv"),
            "rolling_30d_metrics": sha256(
                output / "rolling-30d-monthly-step-metrics.csv"
            ),
        },
    }
    write_json(output / "summary.json", summary)
    write_report(
        output / "report.md",
        selected,
        selection_reason,
        eligible,
        stage_metrics_by_name,
        stress_metrics,
        calendar_rows,
        rolling_30d_rows,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
