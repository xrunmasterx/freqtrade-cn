from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
import sys
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "price-flow-event-adaptive-20-rounds"
)
CONFIG = RESULT_ROOT / "research-config.json"
PREREGISTRATION = RESULT_ROOT / "PREREGISTRATION.md"
EXPECTED_PREREGISTRATION_SHA256 = "49b2e5d4f4da598b6ef215f3df06055b3e78dbb2e6352302ed7dd99bcfaa2adf"
STRATEGY_SOURCE = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "PriceFlowEventAdaptiveResearchStrategy.py"
)
STRATEGY_DEPENDENCIES = [
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "PriceFlowPositionAccountContinuationStrategy.py",
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "PriceFlowCapitalIntentResearchStrategy.py",
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "PriceFlowCrossVenueResearchStrategy.py",
    REPO_ROOT / "ft_userdata" / "user_data" / "strategies" / "PriceFlowContinuationStrategy.py",
]
USER_DATA = REPO_ROOT / "ft_userdata" / "user_data"
DATA_ROOT = REPO_ROOT / "ft_userdata" / "runtime" / "freqtrade-futures" / "data-price-flow-deep-5y"
DATA_MANIFEST = DATA_ROOT / "cross-venue" / "manifest.json"
RUNNER = Path(__file__).resolve()
PAIRS = ("BTC/USDT:USDT", "ETH/USDT:USDT")
CONTROL_STRATEGY = "PriceFlowEventAdaptiveControl"
DEVELOPMENT_WINDOW = ("20230801", "20250801")
CHALLENGE_WINDOW = ("20250801", "20260801")
FULL_WINDOW = ("20230801", "20260801")
DEVELOPMENT_FOLDS = {
    "F1": ("2023-08-01T00:00:00Z", "2024-02-01T00:00:00Z"),
    "F2": ("2024-02-01T00:00:00Z", "2024-08-01T00:00:00Z"),
    "F3": ("2024-08-01T00:00:00Z", "2025-02-01T00:00:00Z"),
    "F4": ("2025-02-01T00:00:00Z", "2025-08-01T00:00:00Z"),
}
CHALLENGE_FOLDS = {
    "Q1": ("2025-08-01T00:00:00Z", "2025-11-01T00:00:00Z"),
    "Q2": ("2025-11-01T00:00:00Z", "2026-02-01T00:00:00Z"),
    "Q3": ("2026-02-01T00:00:00Z", "2026-05-01T00:00:00Z"),
    "Q4": ("2026-05-01T00:00:00Z", "2026-08-01T00:00:00Z"),
}
FULL_FOLDS = {
    "Y1": ("2023-08-01T00:00:00Z", "2024-08-01T00:00:00Z"),
    "Y2": ("2024-08-01T00:00:00Z", "2025-08-01T00:00:00Z"),
    "Y3": ("2025-08-01T00:00:00Z", "2026-08-01T00:00:00Z"),
}


@dataclass
class Metrics:
    code: str
    strategy: str
    window: str
    status: str = "MEASURED"
    reason: str = ""
    trades: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    winrate: float = 0.0
    payoff: float | None = None
    profit_factor: float = 0.0
    expectancy: float = 0.0
    profit_pct: float = 0.0
    profit_usdt: float = 0.0
    starting_balance: float = 20.0
    final_balance: float = 20.0
    drawdown_pct: float = 0.0
    funding_fees_usdt: float = 0.0
    btc_trades: int = 0
    eth_trades: int = 0
    long_trades: int = 0
    short_trades: int = 0
    btc_long: int = 0
    btc_short: int = 0
    eth_long: int = 0
    eth_short: int = 0
    independent_weeks: int = 0
    profitable_folds: int = 0
    worst_fold_profit_pct: float = 0.0
    min_asset_profit_factor: float = 0.0
    top3_gross_profit_share: float = 0.0
    best_month_positive_share: float = 0.0
    profitable_months: int = 0
    losing_months: int = 0
    folds: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    months: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    pair_profit_sum_pct: dict[str, float] = field(default_factory=dict)
    pair_profit_factor: dict[str, float | None] = field(default_factory=dict)
    entry_tag_counts: dict[str, int] = field(default_factory=dict)
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    trade_fingerprint: str | None = None
    artifact_sha256: str | None = None
    artifact: str | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen 20-round PriceFlow event-adaptive study."
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strategy_name(candidate_id: int) -> str:
    return f"PriceFlowEventAdaptive{candidate_id:02d}Strategy"


def _result_zip(directory: Path) -> Path | None:
    last_result = directory / ".last_result.json"
    if last_result.is_file():
        name = json.loads(last_result.read_text(encoding="utf-8")).get("latest_backtest")
        if name and (directory / name).is_file():
            return directory / name
    archives = sorted(directory.glob("*.zip"), key=lambda path: path.stat().st_mtime)
    return archives[-1] if archives else None


def _read_result(archive: Path, strategy: str) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as bundle:
        result_name = next(
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        )
        payload = json.loads(bundle.read(result_name))
    return payload["strategy"][strategy]


def _profit_factor(values: list[float]) -> float | None:
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    if gross_loss == 0:
        return None if gross_profit == 0 else float("inf")
    return gross_profit / gross_loss


def _trade_fingerprint(trades: list[dict[str, Any]]) -> str:
    keys = (
        "pair",
        "open_date",
        "close_date",
        "open_rate",
        "close_rate",
        "profit_ratio",
        "is_short",
        "enter_tag",
        "exit_reason",
    )
    normalized = [{key: trade.get(key) for key in keys} for trade in trades]
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _period_metrics(
    trades: list[dict[str, Any]], boundaries: dict[str, tuple[str, str]]
) -> dict[str, dict[str, float | int | None]]:
    result: dict[str, dict[str, float | int | None]] = {}
    for label, (start_value, end_value) in boundaries.items():
        start = pd.Timestamp(start_value)
        end = pd.Timestamp(end_value)
        values = [
            float(trade["profit_ratio"])
            for trade in trades
            if start <= pd.Timestamp(str(trade["open_date"])) < end
        ]
        result[label] = {
            "trades": len(values),
            "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values),
            "profit_sum_pct": round(sum(values) * 100, 10),
            "profit_factor": _profit_factor(values),
        }
    return result


def _monthly_metrics(
    trades: list[dict[str, Any]], start: str, end: str
) -> dict[str, dict[str, float | int | None]]:
    start_month = pd.Timestamp(start).to_period("M")
    end_month = (pd.Timestamp(end) - pd.Timedelta(seconds=1)).to_period("M")
    result: dict[str, dict[str, float | int | None]] = {}
    for month in pd.period_range(start_month, end_month, freq="M"):
        label = str(month)
        values = [
            float(trade["profit_ratio"])
            for trade in trades
            if pd.Timestamp(str(trade["open_date"])).strftime("%Y-%m") == label
        ]
        result[label] = {
            "trades": len(values),
            "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values),
            "winrate_pct": (
                sum(value > 0 for value in values) / len(values) * 100 if values else 0.0
            ),
            "profit_sum_pct": round(sum(values) * 100, 10),
            "profit_factor": _profit_factor(values),
        }
    return result


def _summarize(
    code: str,
    strategy: str,
    window: str,
    timerange: tuple[str, str],
    fold_boundaries: dict[str, tuple[str, str]],
    result: dict[str, Any],
    archive: Path,
) -> Metrics:
    trades = result["trades"]
    profits = [float(trade["profit_ratio"]) for trade in trades]
    winners = [value for value in profits if value > 0]
    draws = [value for value in profits if value == 0]
    losers = [value for value in profits if value < 0]
    payoff = None
    if winners and losers:
        payoff = statistics.mean(winners) / abs(statistics.mean(losers))
    pairs = [str(trade["pair"]) for trade in trades]
    shorts = [bool(trade["is_short"]) for trade in trades]
    weeks = {
        pd.Timestamp(str(trade["close_date"])).to_period("W").start_time.date().isoformat()
        for trade in trades
        if trade.get("close_date")
    }
    folds = _period_metrics(trades, fold_boundaries)
    fold_profits = [float(values["profit_sum_pct"] or 0) for values in folds.values()]
    months = _monthly_metrics(trades, timerange[0], timerange[1])
    month_profits = [float(values["profit_sum_pct"] or 0) for values in months.values()]

    pair_values: dict[str, list[float]] = {"BTC": [], "ETH": []}
    for pair, value in zip(pairs, profits, strict=True):
        asset = pair.split("/", maxsplit=1)[0]
        if asset in pair_values:
            pair_values[asset].append(value)
    pair_profit_sum = {asset: round(sum(values) * 100, 10) for asset, values in pair_values.items()}
    pair_profit_factor = {asset: _profit_factor(values) for asset, values in pair_values.items()}
    finite_pair_pf = [
        0.0 if value is None else float(value) for value in pair_profit_factor.values()
    ]
    gross_profit = sum(winners)
    top3_share = sum(sorted(winners, reverse=True)[:3]) / gross_profit if gross_profit else 0
    positive_month_total = sum(value for value in month_profits if value > 0)
    best_month_share = (
        max(month_profits, default=0.0) / positive_month_total if positive_month_total > 0 else 0.0
    )
    total = next(row for row in result["results_per_pair"] if row["key"] == "TOTAL")
    try:
        artifact = str(archive.relative_to(REPO_ROOT))
    except ValueError:
        artifact = str(archive)
    return Metrics(
        code=code,
        strategy=strategy,
        window=window,
        trades=len(trades),
        wins=len(winners),
        draws=len(draws),
        losses=len(losers),
        winrate=(len(winners) / len(trades)) if trades else 0.0,
        payoff=payoff,
        profit_factor=float(total["profit_factor"]),
        expectancy=float(total.get("expectancy") or 0),
        profit_pct=float(total["profit_total_pct"]),
        profit_usdt=float(total["profit_total_abs"]),
        starting_balance=float(result["starting_balance"]),
        final_balance=float(result["final_balance"]),
        drawdown_pct=float(result["max_drawdown_account"]) * 100,
        funding_fees_usdt=sum(float(trade.get("funding_fees") or 0) for trade in trades),
        btc_trades=sum(pair.startswith("BTC/") for pair in pairs),
        eth_trades=sum(pair.startswith("ETH/") for pair in pairs),
        long_trades=sum(not is_short for is_short in shorts),
        short_trades=sum(shorts),
        btc_long=sum(
            pair.startswith("BTC/") and not is_short
            for pair, is_short in zip(pairs, shorts, strict=True)
        ),
        btc_short=sum(
            pair.startswith("BTC/") and is_short
            for pair, is_short in zip(pairs, shorts, strict=True)
        ),
        eth_long=sum(
            pair.startswith("ETH/") and not is_short
            for pair, is_short in zip(pairs, shorts, strict=True)
        ),
        eth_short=sum(
            pair.startswith("ETH/") and is_short
            for pair, is_short in zip(pairs, shorts, strict=True)
        ),
        independent_weeks=len(weeks),
        profitable_folds=sum(value > 0 for value in fold_profits),
        worst_fold_profit_pct=min(fold_profits, default=0.0),
        min_asset_profit_factor=min(finite_pair_pf, default=0.0),
        top3_gross_profit_share=top3_share,
        best_month_positive_share=best_month_share,
        profitable_months=sum(value > 0 for value in month_profits),
        losing_months=sum(value < 0 for value in month_profits),
        folds=folds,
        months=months,
        pair_profit_sum_pct=pair_profit_sum,
        pair_profit_factor=pair_profit_factor,
        entry_tag_counts=dict(Counter(str(trade.get("enter_tag") or "") for trade in trades)),
        exit_reason_counts=dict(Counter(str(trade.get("exit_reason") or "") for trade in trades)),
        trade_fingerprint=_trade_fingerprint(trades),
        artifact_sha256=_sha256(archive),
        artifact=artifact,
    )


def _run_backtest(
    strategy: str,
    code: str,
    window_name: str,
    timerange: tuple[str, str],
    fold_boundaries: dict[str, tuple[str, str]],
    *,
    fee: float,
    resume: bool,
    export: str = "trades",
) -> Metrics:
    fee_code = f"fee-{fee:.4f}".replace(".", "p")
    directory = RESULT_ROOT / window_name / code.lower()
    if fee != 0.0005:
        directory = directory / fee_code
    directory.mkdir(parents=True, exist_ok=True)
    existing = _result_zip(directory) if resume else None
    if existing is None:
        start, end = timerange
        command = [
            str(REPO_ROOT / "freqtrade" / ".venv" / "Scripts" / "python.exe"),
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
            strategy,
            "--pairs",
            *PAIRS,
            "--timerange",
            f"{start}-{end}",
            "--fee",
            str(fee),
            "--cache",
            "none",
            "--backtest-directory",
            str(directory),
            "--export",
            export,
        ]
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT / "freqtrade",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        (directory / "run.log").write_text(
            completed.stdout + "\n" + completed.stderr, encoding="utf-8"
        )
        if completed.returncode != 0:
            return Metrics(
                code=code,
                strategy=strategy,
                window=window_name,
                status="INVALID_IMPLEMENTATION",
                reason=f"Freqtrade exited {completed.returncode}",
            )
        existing = _result_zip(directory)
    if existing is None:
        return Metrics(
            code=code,
            strategy=strategy,
            window=window_name,
            status="INVALID_IMPLEMENTATION",
            reason="Freqtrade did not produce a result ZIP",
        )
    try:
        result = _read_result(existing, strategy)
        return _summarize(
            code,
            strategy,
            window_name,
            timerange,
            fold_boundaries,
            result,
            existing,
        )
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        StopIteration,
        TypeError,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        return Metrics(
            code=code,
            strategy=strategy,
            window=window_name,
            status="INVALID_IMPLEMENTATION",
            reason=f"result parse failed: {exc}",
        )


def _sample_gate(metrics: Metrics) -> tuple[bool, str]:
    failures = []
    checks = (
        (metrics.trades >= 70, "trades<70"),
        (metrics.wins >= 20, "wins<20"),
        (metrics.losses >= 20, "losses<20"),
        (metrics.btc_trades >= 15, "BTC<15"),
        (metrics.eth_trades >= 15, "ETH<15"),
        (metrics.long_trades >= 25, "long<25"),
        (metrics.short_trades >= 12, "short<12"),
        (metrics.btc_long >= 4, "BTC-long<4"),
        (metrics.btc_short >= 4, "BTC-short<4"),
        (metrics.eth_long >= 4, "ETH-long<4"),
        (metrics.eth_short >= 4, "ETH-short<4"),
        (metrics.independent_weeks >= 24, "weeks<24"),
    )
    failures.extend(label for passed, label in checks if not passed)
    return not failures, ", ".join(failures)


def _development_gate(metrics: Metrics, baseline: Metrics) -> tuple[str, str]:
    if metrics.status == "INVALID_IMPLEMENTATION":
        return metrics.status, metrics.reason
    sample_ok, sample_reason = _sample_gate(metrics)
    if not sample_ok:
        return "REJECTED_SAMPLE", sample_reason
    payoff = metrics.payoff or 0.0
    baseline_payoff = baseline.payoff or 0.0
    failures = []
    checks = (
        (metrics.profit_pct > 0, "profit<=0"),
        (
            metrics.profit_factor >= max(1.75, baseline.profit_factor + 0.15),
            "PF gate",
        ),
        (metrics.winrate >= baseline.winrate + 0.02, "winrate gate"),
        (payoff >= max(2.30, baseline_payoff - 0.15), "payoff gate"),
        (
            metrics.drawdown_pct < 15 and metrics.drawdown_pct <= baseline.drawdown_pct + 2,
            "drawdown gate",
        ),
        (metrics.profitable_folds >= 3, "profitable folds<3"),
        (metrics.worst_fold_profit_pct > -10, "worst fold<=-10"),
        (metrics.min_asset_profit_factor > 1, "asset PF<=1"),
        (metrics.top3_gross_profit_share <= 0.45, "top3 concentration>45%"),
        (
            metrics.best_month_positive_share <= 0.35,
            "best-month concentration>35%",
        ),
    )
    failures.extend(label for passed, label in checks if not passed)
    if failures:
        return "REJECTED_ECONOMIC", ", ".join(failures)
    return "DEVELOPMENT_POINT_SURVIVOR", "all frozen development gates passed"


def _is_expansion_diagnostic(metrics: Metrics, baseline: Metrics) -> bool:
    return (
        metrics.status != "INVALID_IMPLEMENTATION"
        and metrics.trades >= baseline.trades * 1.10
        and metrics.profit_factor >= baseline.profit_factor
        and metrics.winrate >= baseline.winrate - 0.01
        and (metrics.payoff or 0) >= (baseline.payoff or 0) - 0.20
        and metrics.drawdown_pct <= baseline.drawdown_pct + 2
    )


def _ranking_key(metrics: Metrics) -> tuple[float, ...]:
    return (
        metrics.worst_fold_profit_pct,
        metrics.min_asset_profit_factor,
        metrics.profit_factor,
        metrics.winrate,
        metrics.payoff or 0.0,
        metrics.profit_pct,
        -metrics.drawdown_pct,
    )


def _challenge_gate(metrics: Metrics, baseline: Metrics) -> tuple[str, str]:
    if metrics.status == "INVALID_IMPLEMENTATION":
        return metrics.status, metrics.reason
    failures = []
    checks = (
        (metrics.profit_pct > 0, "profit<=0"),
        (metrics.profit_factor >= baseline.profit_factor, "PF<control"),
        (metrics.winrate >= baseline.winrate - 0.02, "winrate<control-2pp"),
        ((metrics.payoff or 0) >= 2.0, "payoff<2"),
        (
            metrics.drawdown_pct < 15 and metrics.drawdown_pct <= baseline.drawdown_pct + 2,
            "drawdown gate",
        ),
        (metrics.profitable_folds >= 3, "profitable quarters<3"),
        (metrics.pair_profit_sum_pct.get("BTC", 0) > 0, "BTC profit<=0"),
        (metrics.pair_profit_sum_pct.get("ETH", 0) > 0, "ETH profit<=0"),
    )
    failures.extend(label for passed, label in checks if not passed)
    if failures:
        return "TEMPORAL_CHALLENGE_REJECTED", ", ".join(failures)
    return (
        "TEMPORAL_CHALLENGE_POINT_SURVIVOR",
        "all frozen temporal challenge gates passed",
    )


def _run_many(
    specs: list[tuple[str, str]],
    window_name: str,
    timerange: tuple[str, str],
    folds: dict[str, tuple[str, str]],
    *,
    fee: float,
    resume: bool,
    workers: int,
) -> list[Metrics]:
    rows: list[Metrics] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_backtest,
                strategy,
                code,
                window_name,
                timerange,
                folds,
                fee=fee,
                resume=resume,
            ): code
            for strategy, code in specs
        }
        for future in as_completed(futures):
            rows.append(future.result())
    order = {code: position for position, (_, code) in enumerate(specs)}
    return sorted(rows, key=lambda row: order[row.code])


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_metrics_csv(path: Path, rows: list[Metrics]) -> None:
    scalar_fields = [
        name
        for name in Metrics.__dataclass_fields__
        if name
        not in {
            "folds",
            "months",
            "pair_profit_sum_pct",
            "pair_profit_factor",
            "entry_tag_counts",
            "exit_reason_counts",
        }
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=scalar_fields)
        writer.writeheader()
        for row in rows:
            values = asdict(row)
            writer.writerow({name: values[name] for name in scalar_fields})


def _display_metric(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _report(
    baseline_development: Metrics,
    development: list[Metrics],
    selected_codes: list[str],
    selection_roles: dict[str, str],
    baseline_challenge: Metrics,
    challenge: list[Metrics],
    baseline_full: Metrics,
    full: list[Metrics],
    fee_stress: Metrics | None,
    determinism: dict[str, Any] | None,
) -> str:
    lines = [
        "# PriceFlow 事件自适应 20 轮研究结果",
        "",
        (
            "状态：离线研究；未启用 Paper/Live。挑战窗已被本 session 其他研究"
            "观察过，不能称为 untouched holdout。"
        ),
        "",
        "## 开发窗：20 轮",
        "",
        "| 轮次 | 交易 | 收益 | 胜率 | Payoff | PF | 最大回撤 | 正折 | 状态 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in [baseline_development, *development]:
        lines.append(
            f"| {row.code} | {row.trades} | {row.profit_pct:+.2f}% | "
            f"{row.winrate * 100:.2f}% | {_display_metric(row.payoff)} | "
            f"{row.profit_factor:.2f} | {row.drawdown_pct:.2f}% | "
            f"{row.profitable_folds}/4 | {row.status} |"
        )
    lines.extend(
        [
            "",
            "开发窗入选："
            + (
                ", ".join(
                    f"{code} ({selection_roles.get(code, 'unknown')})" for code in selected_codes
                )
                if selected_codes
                else "无"
            ),
            "",
            "## 时间挑战",
            "",
            "| 轮次 | 交易 | 收益 | 胜率 | Payoff | PF | 最大回撤 | 正季度 | 状态 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in [baseline_challenge, *challenge]:
        lines.append(
            f"| {row.code} | {row.trades} | {row.profit_pct:+.2f}% | "
            f"{row.winrate * 100:.2f}% | {_display_metric(row.payoff)} | "
            f"{row.profit_factor:.2f} | {row.drawdown_pct:.2f}% | "
            f"{row.profitable_folds}/4 | {row.status} |"
        )
    lines.extend(
        [
            "",
            "## 完整三年共享钱包",
            "",
            "| 轮次 | 交易 | 收益 | 最终余额 | 胜率 | Payoff | PF | 最大回撤 | 正月/负月 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in [baseline_full, *full]:
        lines.append(
            f"| {row.code} | {row.trades} | {row.profit_pct:+.2f}% | "
            f"{row.final_balance:.4f} | {row.winrate * 100:.2f}% | "
            f"{_display_metric(row.payoff)} | {row.profit_factor:.2f} | "
            f"{row.drawdown_pct:.2f}% | {row.profitable_months}/{row.losing_months} |"
        )
    lines.extend(["", "## 压力与审计", ""])
    if fee_stress is not None:
        lines.append(
            f"- 双倍手续费（单边 0.10%）：{fee_stress.code}，"
            f"{fee_stress.trades} 笔，收益 {fee_stress.profit_pct:+.2f}%，"
            f"PF {fee_stress.profit_factor:.2f}，回撤 {fee_stress.drawdown_pct:.2f}%。"
        )
    if determinism is not None:
        lines.append(
            f"- 确定性复跑：{'通过' if determinism.get('passed') else '失败'}；"
            f"原指纹 `{determinism.get('original_fingerprint')}`；"
            f"复跑指纹 `{determinism.get('rerun_fingerprint')}`。"
        )
    lines.extend(
        [
            (
                "- funding 数据在 2024-05-31 16:00 UTC 前缺失，按冻结配置"
                "回退为 0；不得把结果解释为完整 funding 仿真。"
            ),
            "- 静态政策事件只在官方日期后的下一日 00:00 UTC 才可用；不编码消息方向。",
            "- Binance/OKX/Deribit 是不同资金池，OI、账户比和期权成交不能识别交易者或开平仓身份。",
            (
                "- 20 个候选共享同一历史，存在多重试验和选择偏差；任何 "
                "survivor 仍需新的 point-in-time forward/Paper 验证。"
            ),
        ]
    )
    survivors = [row for row in challenge if row.status == "TEMPORAL_CHALLENGE_POINT_SURVIVOR"]
    lines.extend(["", "## 冻结结论", ""])
    if survivors:
        lines.append(
            "通过时间挑战点门槛的候选："
            + ", ".join(row.code for row in survivors)
            + "。这只是历史时间挑战 survivor，不是可实盘结论。"
        )
    else:
        lines.append("20 个预注册候选没有产生通过时间挑战点门槛的可晋级策略；不得事后拼装 E21。")
    return "\n".join(lines) + "\n"


def _audit_inputs() -> dict[str, Any]:
    prereg_hash = _sha256(PREREGISTRATION)
    if prereg_hash != EXPECTED_PREREGISTRATION_SHA256:
        raise RuntimeError(
            f"Preregistration hash changed: {prereg_hash} != {EXPECTED_PREREGISTRATION_SHA256}"
        )
    required = [CONFIG, STRATEGY_SOURCE, *STRATEGY_DEPENDENCIES]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing research inputs: {missing}")
    return {
        "preregistration_sha256": prereg_hash,
        "config_sha256": _sha256(CONFIG),
        "strategy_sha256": _sha256(STRATEGY_SOURCE),
        "runner_sha256": _sha256(RUNNER),
        "dependency_sha256": {path.name: _sha256(path) for path in STRATEGY_DEPENDENCIES},
        "data_manifest_sha256": _sha256(DATA_MANIFEST) if DATA_MANIFEST.is_file() else None,
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    input_audit = _audit_inputs()

    baseline_development = _run_backtest(
        CONTROL_STRATEGY,
        "C04",
        "development",
        DEVELOPMENT_WINDOW,
        DEVELOPMENT_FOLDS,
        fee=0.0005,
        resume=args.resume,
    )
    candidate_specs = [
        (_strategy_name(candidate_id), f"E{candidate_id:02d}") for candidate_id in range(1, 21)
    ]
    development = _run_many(
        candidate_specs,
        "development",
        DEVELOPMENT_WINDOW,
        DEVELOPMENT_FOLDS,
        fee=0.0005,
        resume=args.resume,
        workers=args.workers,
    )
    for row in development:
        row.status, row.reason = _development_gate(row, baseline_development)
        if row.status != "DEVELOPMENT_POINT_SURVIVOR" and _is_expansion_diagnostic(
            row, baseline_development
        ):
            row.reason = f"{row.reason}; EXPANSION_DIAGNOSTIC"

    survivors = sorted(
        [row for row in development if row.status == "DEVELOPMENT_POINT_SURVIVOR"],
        key=_ranking_key,
        reverse=True,
    )
    selected = survivors[:3]
    selection_roles = {row.code: "FORMAL_SURVIVOR" for row in selected}
    if len(selected) < 3:
        diagnostics = []
        for row in development:
            sample_ok, _ = _sample_gate(row)
            if sample_ok and row.code not in selection_roles:
                diagnostics.append(row)
        diagnostics.sort(key=_ranking_key, reverse=True)
        for row in diagnostics[: 3 - len(selected)]:
            selected.append(row)
            selection_roles[row.code] = "DIAGNOSTIC_ONLY"

    baseline_challenge = _run_backtest(
        CONTROL_STRATEGY,
        "C04",
        "challenge",
        CHALLENGE_WINDOW,
        CHALLENGE_FOLDS,
        fee=0.0005,
        resume=args.resume,
    )
    selected_specs = [(row.strategy, row.code) for row in selected]
    challenge = (
        _run_many(
            selected_specs,
            "challenge",
            CHALLENGE_WINDOW,
            CHALLENGE_FOLDS,
            fee=0.0005,
            resume=args.resume,
            workers=min(args.workers, max(1, len(selected_specs))),
        )
        if selected_specs
        else []
    )
    for row in challenge:
        row.status, row.reason = _challenge_gate(row, baseline_challenge)

    baseline_full = _run_backtest(
        CONTROL_STRATEGY,
        "C04",
        "full-3y",
        FULL_WINDOW,
        FULL_FOLDS,
        fee=0.0005,
        resume=args.resume,
        export="signals",
    )
    full = (
        _run_many(
            selected_specs,
            "full-3y",
            FULL_WINDOW,
            FULL_FOLDS,
            fee=0.0005,
            resume=args.resume,
            workers=min(args.workers, max(1, len(selected_specs))),
        )
        if selected_specs
        else []
    )

    fee_stress = None
    determinism = None
    if selected:
        leader = selected[0]
        fee_stress = _run_backtest(
            leader.strategy,
            leader.code,
            "verification-fee",
            FULL_WINDOW,
            FULL_FOLDS,
            fee=0.001,
            resume=args.resume,
        )
        original = next((row for row in full if row.code == leader.code), None)
        rerun = _run_backtest(
            leader.strategy,
            leader.code,
            "verification-determinism",
            FULL_WINDOW,
            FULL_FOLDS,
            fee=0.0005,
            resume=args.resume,
        )
        determinism = {
            "code": leader.code,
            "passed": bool(
                original
                and original.trade_fingerprint
                and original.trade_fingerprint == rerun.trade_fingerprint
            ),
            "original_fingerprint": original.trade_fingerprint if original else None,
            "rerun_fingerprint": rerun.trade_fingerprint,
            "original_artifact": original.artifact if original else None,
            "rerun_artifact": rerun.artifact,
        }

    all_rows = [
        baseline_development,
        *development,
        baseline_challenge,
        *challenge,
        baseline_full,
        *full,
    ]
    if fee_stress is not None:
        all_rows.append(fee_stress)
    _write_json(
        RESULT_ROOT / "development-results.json",
        [asdict(row) for row in [baseline_development, *development]],
    )
    _write_metrics_csv(
        RESULT_ROOT / "development-results.csv", [baseline_development, *development]
    )
    _write_json(
        RESULT_ROOT / "challenge-results.json",
        [asdict(row) for row in [baseline_challenge, *challenge]],
    )
    _write_json(RESULT_ROOT / "full-results.json", [asdict(row) for row in [baseline_full, *full]])
    _write_metrics_csv(RESULT_ROOT / "all-results.csv", all_rows)
    selection = {
        "selected_codes": [row.code for row in selected],
        "selection_roles": selection_roles,
        "challenge_survivors": [
            row.code for row in challenge if row.status == "TEMPORAL_CHALLENGE_POINT_SURVIVOR"
        ],
    }
    _write_json(RESULT_ROOT / "selection.json", selection)
    if determinism is not None:
        _write_json(RESULT_ROOT / "determinism.json", determinism)
    receipt = {
        **input_audit,
        "candidate_count": 20,
        "development_backtests": 21,
        "challenge_backtests": 1 + len(challenge),
        "full_backtests": 1 + len(full),
        "selected": selection,
        "wallet_usdt": 20,
        "tradable_balance_ratio": 0.9,
        "max_open_trades": 1,
        "leverage": 2,
        "fee_one_way": 0.0005,
        "pairs": list(PAIRS),
        "freqtrade_version": version("freqtrade"),
        "python_version": sys.version,
        "all_development_candidates_measured": all(
            row.status != "INVALID_IMPLEMENTATION" for row in development
        ),
    }
    _write_json(RESULT_ROOT / "run-receipt.json", receipt)
    (RESULT_ROOT / "REPORT.md").write_text(
        _report(
            baseline_development,
            development,
            [row.code for row in selected],
            selection_roles,
            baseline_challenge,
            challenge,
            baseline_full,
            full,
            fee_stress,
            determinism,
        ),
        encoding="utf-8",
    )
    print(RESULT_ROOT / "REPORT.md")
    return 0 if receipt["all_development_candidates_measured"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
