from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import time
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "freqtrade" / ".venv" / "Scripts" / "python.exe"
OFFLINE_RUNNER = ROOT / "tools" / "run_freqtrade_offline_backtest.py"
USER_DATA = ROOT / "ft_userdata" / "user_data"
CONFIG = USER_DATA / "config.supertrend-exit-research.json"
STRATEGY = USER_DATA / "strategies" / "TradingViewSupertrendStrategy.py"
RESEARCH_STRATEGY = (
    USER_DATA / "strategies" / "TradingViewSupertrendExitResearchStrategy.py"
)
LONG_DATA = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data-mtf-capital-regime-research"
)
RECENT_DATA = (
    ROOT / "ft_userdata" / "runtime" / "freqtrade-futures" / "data"
)
RESULT_ROOT = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "supertrend-exit-20-rounds"
)
PREREGISTRATION = RESULT_ROOT / "preregistration.json"
DETAIL_CACHE: dict[tuple[str, str], pd.DataFrame] = {}

CONTROL = "TradingViewSupertrendExitControl"
CANDIDATES = {
    "TradingViewSupertrendExitR01": "六点方案基准",
    "TradingViewSupertrendExitR02": "激活阈值下限 0.15%",
    "TradingViewSupertrendExitR03": "激活阈值下限 0.25%",
    "TradingViewSupertrendExitR04": "激活阈值下限 0.30%",
    "TradingViewSupertrendExitR05": "激活距离 0.35 ATR",
    "TradingViewSupertrendExitR06": "激活距离 0.65 ATR",
    "TradingViewSupertrendExitR07": "5m 两根结构跟踪",
    "TradingViewSupertrendExitR08": "5m 四根结构跟踪",
    "TradingViewSupertrendExitR09": "5m 五根结构跟踪",
    "TradingViewSupertrendExitR10": "三根 15m 未反弹即退出",
    "TradingViewSupertrendExitR11": "六根 15m 未反弹即退出",
    "TradingViewSupertrendExitR12": "前高/前低减仓 33%",
    "TradingViewSupertrendExitR13": "前高/前低减仓 67%",
    "TradingViewSupertrendExitR14": "前高/前低回看 8 根",
    "TradingViewSupertrendExitR15": "前高/前低回看 20 根",
    "TradingViewSupertrendExitR16": "失效线无 ATR 缓冲",
    "TradingViewSupertrendExitR17": "失效线 0.5 ATR 缓冲",
    "TradingViewSupertrendExitR18": "1h 超级趋势过滤 / 不附加结构过滤",
    "TradingViewSupertrendExitR19": "1h 两段结构过滤",
    "TradingViewSupertrendExitR20": "不做前高/前低部分止盈",
}

SELECTION_STAGES = {
    "development": {
        "timerange": "20210901-20240101",
        "data": LONG_DATA / "okx",
        "detail": "5m",
        "pairs": ["BTC/USDT:USDT"],
        "fee": 0.0005,
    },
    "validation": {
        "timerange": "20240101-20250701",
        "data": LONG_DATA / "okx",
        "detail": "5m",
        "pairs": ["BTC/USDT:USDT"],
        "fee": 0.0005,
    },
}
DIAGNOSTIC_STAGES = {
    "short_window": {
        "timerange": "20260101-20260812",
        "data": LONG_DATA / "okx",
        "detail": "5m",
        "pairs": ["BTC/USDT:USDT"],
        "fee": 0.0005,
    },
}
POST_SELECTION_STAGES = {
    "long_stress": {
        "timerange": "20250701-20260812",
        "data": LONG_DATA / "okx",
        "detail": "5m",
        "pairs": ["BTC/USDT:USDT"],
        "fee": 0.0005,
    },
    "cost_stress": {
        "timerange": "20250701-20260812",
        "data": LONG_DATA / "okx",
        "detail": "5m",
        "pairs": ["BTC/USDT:USDT"],
        "fee": 0.0007,
    },
    "recent_cross_asset": {
        "timerange": "20260724-20260824",
        "data": RECENT_DATA / "okx",
        "detail": "1m",
        "pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
        "fee": 0.0005,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    def json_safe(value: Any) -> Any:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {str(key): json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(item) for item in value]
        return value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def preregistration_payload() -> dict[str, Any]:
    return {
        "created_before_multi_year_result_read": True,
        "candidate_count": len(CANDIDATES),
        "control": CONTROL,
        "candidates": CANDIDATES,
        "selection_stages": {
            name: {
                **spec,
                "data": str(spec["data"].relative_to(ROOT)),
            }
            for name, spec in SELECTION_STAGES.items()
        },
        "diagnostic_stages_not_used_for_selection": {
            name: {
                **spec,
                "data": str(spec["data"].relative_to(ROOT)),
            }
            for name, spec in DIAGNOSTIC_STAGES.items()
        },
        "post_selection_stages": {
            name: {
                **spec,
                "data": str(spec["data"].relative_to(ROOT)),
            }
            for name, spec in POST_SELECTION_STAGES.items()
        },
        "known_exposure": (
            "The 2025-07-01 onward interval is a stress interval, not a fresh holdout."
        ),
        "execution": {
            "closed_candles_only": True,
            "entry": "dynamic limit order; fill only when detail candle actually touches",
            "exit": "market on the first available detail candle after a closed-candle decision",
            "leverage": 1.0,
            "position_entries": 3,
            "funding": "actual OKX funding and mark rows where available",
            "fee_each_filled_order_side": 0.0005,
            "cost_stress": "0.0007 per side, adding a 2 bp slippage proxy",
        },
        "six_price_action_rules": [
            "four completed 15m candles must prove follow-through, otherwise market exit",
            "activation is max(0.20%, 0.5 ATR at fill); then cancel remaining entries",
            "one partial exit at the prior closed-candle swing high or low",
            "after activation, trail the prior three completed 5m candle structure",
            "15m Supertrend reversal remains the fallback market exit",
            "entries align with the last completed 1h Supertrend and price structure",
        ],
        "anti_overfit": {
            "matrix": "one-factor changes around a preregistered base; no combinatorial search",
            "selection_uses_only": list(SELECTION_STAGES),
            "post_selection_is_not_retuned": True,
            "losing_trades_are_never_deleted_after_the_fact": True,
        },
        "eligibility_gates": {
            "minimum_trades": {"development": 50, "validation": 30},
            "net_profit_abs_each_stage": "> 0 after fees and funding",
            "profit_factor_each_stage": "> 1",
            "winrate_each_stage": ">= 30%",
            "strict_payoff_each_stage": ">= 1.2",
            "force_exit_count": 0,
        },
        "selection_order": [
            "most profitable calendar years across development and validation",
            "largest minimum profit factor across both stages",
            "largest minimum strict payoff across both stages",
            "largest minimum win rate across both stages",
            "smallest maximum drawdown across both stages",
            "candidate code ascending",
        ],
        "hashes": {
            "strategy": sha256(STRATEGY),
            "research_strategy": sha256(RESEARCH_STRATEGY),
            "config": sha256(CONFIG),
            "data_manifest": sha256(LONG_DATA / "manifest.json"),
        },
    }


def ensure_preregistration() -> None:
    expected = preregistration_payload()
    if PREREGISTRATION.exists():
        actual = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
        if actual != expected:
            raise RuntimeError(
                "Research inputs changed after preregistration; refusing to mix runs"
            )
        return
    write_json(PREREGISTRATION, expected)


def latest_archive(directory: Path) -> Path:
    marker = directory / ".last_result.json"
    if marker.is_file():
        filename = json.loads(marker.read_text(encoding="utf-8"))["latest_backtest"]
        archive = directory / filename
        if archive.is_file():
            return archive
    archives = sorted(directory.glob("*.zip"), key=lambda path: path.stat().st_mtime)
    if not archives:
        raise RuntimeError(f"No backtest archive in {directory}")
    return archives[-1]


def read_strategy_payloads(archive: Path) -> dict[str, dict[str, Any]]:
    with zipfile.ZipFile(archive) as bundle:
        for filename in bundle.namelist():
            if filename.endswith(".json") and not filename.endswith("_config.json"):
                payload = json.loads(bundle.read(filename))
                strategies = payload.get("strategy")
                if isinstance(strategies, dict):
                    return strategies
    raise RuntimeError(f"Strategy payload missing from {archive}")


def run_backtest(
    stage: str,
    spec: dict[str, Any],
    strategies: list[str],
) -> tuple[Path, dict[str, dict[str, Any]]]:
    output = RESULT_ROOT / "artifacts" / stage
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / "run.json"
    if receipt.is_file():
        old = json.loads(receipt.read_text(encoding="utf-8"))
        archive = Path(old["archive"])
        if old.get("strategies") == strategies and archive.is_file():
            print(f"[{stage}] reuse {archive.name}", flush=True)
            return archive, read_strategy_payloads(archive)

    command = [
        str(PYTHON),
        str(OFFLINE_RUNNER),
        "backtesting",
        "--config",
        str(CONFIG),
        "--user-data-dir",
        str(USER_DATA),
        "--datadir",
        str(spec["data"]),
        "--timerange",
        str(spec["timerange"]),
        "--timeframe-detail",
        str(spec["detail"]),
        "--fee",
        str(spec["fee"]),
        "--pairs",
        *spec["pairs"],
        "--strategy-list",
        *strategies,
        "--cache",
        "none",
        "--export",
        "trades",
        "--backtest-directory",
        str(output),
    ]
    print(f"[{stage}] running {len(strategies)} strategy backtests", flush=True)
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    (output / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (output / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"{stage} failed with exit {completed.returncode}; see {output / 'stderr.log'}"
        )
    archive = latest_archive(output)
    write_json(
        receipt,
        {
            "stage": stage,
            "strategies": strategies,
            "command": command,
            "archive": str(archive),
            "archive_sha256": sha256(archive),
            "elapsed_seconds": time.monotonic() - started,
            "finished_at": datetime.now(UTC).isoformat(),
        },
    )
    print(f"[{stage}] complete in {time.monotonic() - started:.1f}s", flush=True)
    return archive, read_strategy_payloads(archive)


def profit_factor(values: list[float]) -> float | None:
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    if gross_loss == 0:
        return math.inf if gross_profit > 0 else None
    return gross_profit / gross_loss


def payoff(values: list[float]) -> float | None:
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    if not winners or not losers:
        return None
    return (sum(winners) / len(winners)) / abs(sum(losers) / len(losers))


def yearly_metrics(trades: list[dict[str, Any]]) -> dict[str, dict[str, float | int | None]]:
    years = sorted({str(trade["open_date"])[:4] for trade in trades})
    result: dict[str, dict[str, float | int | None]] = {}
    for year in years:
        year_trades = [trade for trade in trades if str(trade["open_date"]).startswith(year)]
        values = [float(trade.get("profit_abs") or 0.0) for trade in year_trades]
        result[year] = {
            "trades": len(values),
            "profit_abs": sum(values),
            "profit_factor": profit_factor(values),
        }
    return result


def detail_frame(stage: str, pair: str) -> tuple[pd.DataFrame, str]:
    stage_spec = {
        **DIAGNOSTIC_STAGES,
        **SELECTION_STAGES,
        **POST_SELECTION_STAGES,
    }[stage]
    timeframe = str(stage_spec["detail"])
    cache_key = (stage, pair)
    if cache_key not in DETAIL_CACHE:
        pair_name = pair.replace("/", "_").replace(":", "_")
        path = stage_spec["data"] / "futures" / f"{pair_name}-{timeframe}-futures.feather"
        frame = pd.read_feather(path).loc[:, ["date", "high", "low"]].sort_values("date")
        frame["date_ms"] = (
            frame["date"] - pd.Timestamp("1970-01-01", tz="UTC")
        ) // pd.Timedelta(milliseconds=1)
        DETAIL_CACHE[cache_key] = frame
    return DETAIL_CACHE[cache_key], timeframe


def trade_diagnosis(
    trade: dict[str, Any],
    detail: pd.DataFrame,
    detail_timeframe: str,
) -> dict[str, Any]:
    open_rate = float(trade["open_rate"])
    is_short = bool(trade["is_short"])
    net_ratio = float(trade.get("profit_ratio") or 0.0)
    orders = list(trade.get("orders") or [])
    entry_orders = [order for order in orders if order.get("ft_is_entry")]
    entry_times = [
        int(order["order_filled_timestamp"])
        for order in entry_orders
        if order.get("order_filled_timestamp") is not None
    ]
    entry_span_minutes = (
        (max(entry_times) - min(entry_times)) / 60_000 if len(entry_times) > 1 else 0.0
    )
    detail_minutes = {"1m": 1, "5m": 5}[detail_timeframe]
    first_fill = min(entry_times)
    close_time = int(trade["close_timestamp"])
    excursion_rows = detail.loc[
        (detail["date_ms"] >= first_fill + detail_minutes * 60_000)
        & (detail["date_ms"] < close_time)
    ]
    if excursion_rows.empty:
        mfe = 0.0
        mae = 0.0
    elif is_short:
        mfe = max(0.0, (open_rate - float(excursion_rows["low"].min())) / open_rate)
        mae = max(0.0, (float(excursion_rows["high"].max()) - open_rate) / open_rate)
    else:
        mfe = max(0.0, (float(excursion_rows["high"].max()) - open_rate) / open_rate)
        mae = max(0.0, (open_rate - float(excursion_rows["low"].min())) / open_rate)
    if mfe < 0.002:
        diagnosis = "no_follow_through"
    elif net_ratio <= 0 and mfe >= 0.005:
        diagnosis = "good_entry_profit_given_back"
    elif len(entry_orders) == 3 and entry_span_minutes <= 15:
        diagnosis = "three_entries_filled_too_quickly"
    elif net_ratio > 0 and net_ratio / max(mae, 0.0001) >= 1.5:
        diagnosis = "high_reward_to_adverse_excursion"
    elif net_ratio > 0:
        diagnosis = "profitable_but_low_realized_r"
    else:
        diagnosis = "ordinary_failed_setup"
    return {
        "pair": trade["pair"],
        "open_date": trade["open_date"],
        "close_date": trade.get("close_date"),
        "first_fill_date": pd.to_datetime(first_fill, unit="ms", utc=True).isoformat(),
        "last_fill_date": pd.to_datetime(max(entry_times), unit="ms", utc=True).isoformat(),
        "side": "short" if is_short else "long",
        "entries": len(entry_orders),
        "entry_span_minutes": entry_span_minutes,
        "exit_reason": trade.get("exit_reason"),
        "profit_abs": float(trade.get("profit_abs") or 0.0),
        "profit_ratio": net_ratio,
        "funding_fees": float(trade.get("funding_fees") or 0.0),
        "mfe_ratio": mfe,
        "mae_ratio": mae,
        "giveback_ratio": mfe - net_ratio,
        "excursion_timeframe": detail_timeframe,
        "excursion_rows": len(excursion_rows),
        "excursion_starts_after_first_completed_detail_candle": True,
        "diagnosis": diagnosis,
    }


def summarize(
    stage: str,
    strategy: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    trades = list(payload.get("trades") or [])
    values = [float(trade.get("profit_abs") or 0.0) for trade in trades]
    ratio_values = [float(trade.get("profit_ratio") or 0.0) for trade in trades]
    audits = []
    for trade in trades:
        detail, detail_timeframe = detail_frame(stage, str(trade["pair"]))
        audits.append(
            {
                "stage": stage,
                "strategy": strategy,
                **trade_diagnosis(trade, detail, detail_timeframe),
            }
        )
    fees = 0.0
    for trade in trades:
        for order in trade.get("orders") or []:
            fee = trade.get("fee_open") if order.get("ft_is_entry") else trade.get("fee_close")
            fees += float(order.get("cost") or 0.0) * float(fee or 0.0)
    funding = sum(float(trade.get("funding_fees") or 0.0) for trade in trades)
    years = yearly_metrics(trades)
    diagnoses = Counter(audit["diagnosis"] for audit in audits)
    metric = {
        "stage": stage,
        "strategy": strategy,
        "description": CANDIDATES.get(strategy, "原始反转离场对照"),
        "trades": len(trades),
        "wins": sum(value > 0 for value in values),
        "losses": sum(value < 0 for value in values),
        "winrate": sum(value > 0 for value in values) / len(values) if values else 0.0,
        "profit_abs": sum(values),
        "profit_ratio_sum": sum(ratio_values),
        "profit_factor": profit_factor(values),
        "strict_payoff": payoff(values),
        "max_drawdown_ratio": float(payload.get("max_drawdown_account") or 0.0),
        "fees": fees,
        "funding_fees": funding,
        "gross_price_pnl": sum(values) + fees - funding,
        "force_exits": sum(
            str(trade.get("exit_reason") or "").startswith("force_") for trade in trades
        ),
        "positive_years": sum(float(row["profit_abs"] or 0.0) > 0 for row in years.values()),
        "year_count": len(years),
        "years": years,
        "diagnoses": dict(diagnoses),
        "median_mfe_ratio": (
            sorted(audit["mfe_ratio"] for audit in audits)[len(audits) // 2]
            if audits
            else 0.0
        ),
        "median_giveback_ratio": (
            sorted(audit["giveback_ratio"] for audit in audits)[len(audits) // 2]
            if audits
            else 0.0
        ),
    }
    return metric, audits


def eligible(by_stage: dict[str, dict[str, Any]]) -> bool:
    required = {"development": 50, "validation": 30}
    for stage, minimum_trades in required.items():
        metric = by_stage[stage]
        if metric["trades"] < minimum_trades:
            return False
        if metric["profit_abs"] <= 0 or (metric["profit_factor"] or 0.0) <= 1.0:
            return False
        if metric["winrate"] < 0.30 or (metric["strict_payoff"] or 0.0) < 1.2:
            return False
        if metric["force_exits"]:
            return False
    return True


def selection_key(by_stage: dict[str, dict[str, Any]]) -> tuple[Any, ...]:
    metrics = [by_stage[stage] for stage in SELECTION_STAGES]
    profit_factors = [float(metric["profit_factor"] or 0.0) for metric in metrics]
    payoffs = [float(metric["strict_payoff"] or 0.0) for metric in metrics]
    return (
        sum(int(metric["profit_abs"] > 0) for metric in metrics),
        sum(metric["positive_years"] for metric in metrics),
        min(profit_factors),
        min(payoffs),
        min(metric["winrate"] for metric in metrics),
        -max(metric["max_drawdown_ratio"] for metric in metrics),
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ensure_preregistration()
    all_strategies = [CONTROL, *CANDIDATES]
    payloads: dict[str, dict[str, dict[str, Any]]] = {}
    archives: dict[str, str] = {}

    for stage, spec in {**DIAGNOSTIC_STAGES, **SELECTION_STAGES}.items():
        archive, payloads[stage] = run_backtest(stage, spec, all_strategies)
        archives[stage] = str(archive)

    metrics: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for stage, strategies in payloads.items():
        for strategy, payload in strategies.items():
            metric, trade_audits = summarize(stage, strategy, payload)
            metrics.append(metric)
            audits.extend(trade_audits)

    selection_metrics = {
        strategy: {
            stage: next(
                metric
                for metric in metrics
                if metric["stage"] == stage and metric["strategy"] == strategy
            )
            for stage in SELECTION_STAGES
        }
        for strategy in CANDIDATES
    }
    eligible_candidates = [
        strategy for strategy, by_stage in selection_metrics.items() if eligible(by_stage)
    ]
    pool = eligible_candidates or list(CANDIDATES)
    winner = max(pool, key=lambda strategy: (*selection_key(selection_metrics[strategy]), strategy))
    selection_status = "ELIGIBLE_WINNER" if eligible_candidates else "NO_CANDIDATE_PASSED_GATES"

    for stage, spec in POST_SELECTION_STAGES.items():
        archive, post_payload = run_backtest(stage, spec, [winner])
        archives[stage] = str(archive)
        metric, trade_audits = summarize(stage, winner, post_payload[winner])
        metrics.append(metric)
        audits.extend(trade_audits)

    write_json(RESULT_ROOT / "metrics.json", metrics)
    write_json(RESULT_ROOT / "trade-audit.json", audits)
    write_json(
        RESULT_ROOT / "selection.json",
        {
            "status": selection_status,
            "winner": winner,
            "winner_description": CANDIDATES[winner],
            "eligible_candidates": eligible_candidates,
            "selection_key": selection_key(selection_metrics[winner]),
            "selection_metrics": selection_metrics[winner],
            "archives": archives,
            "warning": (
                None
                if eligible_candidates
                else "The measured best candidate failed at least one preregistered gate."
            ),
        },
    )
    flat_metrics = []
    for metric in metrics:
        flat_metrics.append(
            {
                key: value
                for key, value in metric.items()
                if key not in {"years", "diagnoses"}
            }
        )
    write_csv(RESULT_ROOT / "metrics.csv", flat_metrics)
    write_csv(RESULT_ROOT / "trade-audit.csv", audits)
    print(f"selection={selection_status} winner={winner}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
