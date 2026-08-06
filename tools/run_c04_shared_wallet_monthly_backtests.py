from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
import zipfile
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

from tools import run_c04_monthly_backtests as base

REPO_ROOT = base.REPO_ROOT
USER_DATA = base.USER_DATA
DATA_ROOT = base.DATA_ROOT
RESULT_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "c04-btc-eth-shared-wallet-monthly-3y"
)
SOURCE_CONFIG = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "price-flow-capital-intent-20-rounds"
    / "research-config.json"
)
CONFIG = RESULT_ROOT / "backtest-config.json"
STRATEGY = base.STRATEGY
STRATEGY_SOURCES = base.STRATEGY_SOURCES
PAIRS = ("BTC/USDT:USDT", "ETH/USDT:USDT")
MONTHS = base.MONTHS
CONTINUOUS_WINDOW = base.CONTINUOUS_WINDOW
MAX_WORKERS = 2


@dataclass
class SharedMetric:
    mode: str
    window: str
    start: str
    end: str
    status: str
    reason: str
    trades: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    winrate_pct: float = 0.0
    profit_pct: float = 0.0
    profit_usdt: float = 0.0
    funding_fees_usdt: float = 0.0
    starting_balance: float = 20.0
    final_balance: float = 20.0
    profit_factor: float | None = None
    payoff: float | None = None
    expectancy: float = 0.0
    max_drawdown_pct: float = 0.0
    btc_trades: int = 0
    eth_trades: int = 0
    btc_profit_usdt: float = 0.0
    eth_profit_usdt: float = 0.0
    long_trades: int = 0
    short_trades: int = 0
    force_exit_trades: int = 0
    left_open_trades: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    average_duration_minutes: float = 0.0
    best_trade_pct: float | None = None
    worst_trade_pct: float | None = None
    actual_start_utc: str = ""
    actual_end_utc: str = ""
    entry_tag_counts: dict[str, int] = field(default_factory=dict)
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    trade_fingerprint: str | None = None
    artifact_sha256: str | None = None
    artifact: str | None = None


@dataclass
class SharedMonth:
    month: str
    start: str
    end: str
    trades: int
    wins: int
    draws: int
    losses: int
    winrate_pct: float
    profit_pct: float
    profit_usdt: float
    funding_fees_usdt: float
    opening_balance: float
    closing_balance: float
    profit_factor: float | None
    payoff: float | None
    realized_drawdown_pct: float
    btc_trades: int
    eth_trades: int
    btc_profit_usdt: float
    eth_profit_usdt: float
    long_trades: int
    short_trades: int
    cross_month_trades: int
    force_exit_trades: int
    entry_tag_counts: dict[str, int]
    exit_reason_counts: dict[str, int]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run C04 BTC+ETH shared-wallet calendar-month backtests."
    )
    parser.add_argument("--resume", action="store_true")
    return parser


def _backtest_command(window: base.MonthWindow, directory: Path) -> list[str]:
    return [
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
        STRATEGY,
        "--pairs",
        *PAIRS,
        "--timerange",
        f"{window.start}-{window.end}",
        "--fee",
        "0.0005",
        "--cache",
        "none",
        "--backtest-directory",
        str(directory),
        "--export",
        "trades",
    ]


def _read_result(archive: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as bundle:
        result_name = next(
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        )
        payload = json.loads(bundle.read(result_name))
    return payload["strategy"][STRATEGY]


def _pair_total(result: dict[str, Any], pair: str) -> dict[str, Any]:
    return next(
        (
            row
            for row in result["results_per_pair"]
            if row["key"] == pair
        ),
        {"trades": 0, "profit_total_abs": 0.0, "profit_total_pct": 0.0},
    )


def _summarize(
    mode: str,
    window: base.MonthWindow,
    result: dict[str, Any],
    archive: Path,
) -> SharedMetric:
    trades = result["trades"]
    ratios = [float(trade["profit_ratio"]) for trade in trades]
    winners = [value for value in ratios if value > 0]
    draws = [value for value in ratios if value == 0]
    losers = [value for value in ratios if value < 0]
    payoff = None
    if winners and losers:
        payoff = statistics.mean(winners) / abs(statistics.mean(losers))
    total = next(row for row in result["results_per_pair"] if row["key"] == "TOTAL")
    btc = _pair_total(result, PAIRS[0])
    eth = _pair_total(result, PAIRS[1])
    exit_reasons = Counter(str(trade.get("exit_reason") or "") for trade in trades)
    durations = [float(trade.get("trade_duration") or 0) for trade in trades]
    backtest_start = str(result.get("backtest_start") or "")
    backtest_end = str(result.get("backtest_end") or "")
    return SharedMetric(
        mode=mode,
        window=window.label,
        start=window.start,
        end=window.end,
        status="MEASURED",
        reason="",
        trades=len(trades),
        wins=len(winners),
        draws=len(draws),
        losses=len(losers),
        winrate_pct=(len(winners) / len(trades) * 100) if trades else 0.0,
        profit_pct=float(total["profit_total_pct"]),
        profit_usdt=float(total["profit_total_abs"]),
        funding_fees_usdt=sum(
            float(trade.get("funding_fees") or 0) for trade in trades
        ),
        starting_balance=float(result["starting_balance"]),
        final_balance=float(result["final_balance"]),
        profit_factor=float(total["profit_factor"]) if losers else None,
        payoff=payoff,
        expectancy=float(total.get("expectancy") or 0),
        max_drawdown_pct=float(result["max_drawdown_account"]) * 100,
        btc_trades=int(btc["trades"]),
        eth_trades=int(eth["trades"]),
        btc_profit_usdt=float(btc["profit_total_abs"]),
        eth_profit_usdt=float(eth["profit_total_abs"]),
        long_trades=sum(not bool(trade["is_short"]) for trade in trades),
        short_trades=sum(bool(trade["is_short"]) for trade in trades),
        force_exit_trades=exit_reasons.get("force_exit", 0),
        left_open_trades=base._left_open_count(result),
        max_consecutive_wins=int(result.get("max_consecutive_wins") or 0),
        max_consecutive_losses=int(result.get("max_consecutive_losses") or 0),
        average_duration_minutes=statistics.mean(durations) if durations else 0.0,
        best_trade_pct=max(ratios) * 100 if ratios else None,
        worst_trade_pct=min(ratios) * 100 if ratios else None,
        actual_start_utc=f"{backtest_start}Z" if backtest_start else "",
        actual_end_utc=f"{backtest_end}Z" if backtest_end else "",
        entry_tag_counts=dict(
            Counter(str(trade.get("enter_tag") or "") for trade in trades)
        ),
        exit_reason_counts=dict(exit_reasons),
        trade_fingerprint=base._trade_fingerprint(trades),
        artifact_sha256=base._sha256(archive),
        artifact=base._display_path(archive),
    )


def _failed_metric(
    mode: str, window: base.MonthWindow, status: str, reason: str
) -> SharedMetric:
    return SharedMetric(
        mode=mode,
        window=window.label,
        start=window.start,
        end=window.end,
        status=status,
        reason=reason,
    )


def _run_backtest(
    mode: str,
    window: base.MonthWindow,
    directory: Path,
    *,
    resume: bool,
) -> SharedMetric:
    directory.mkdir(parents=True, exist_ok=True)
    archive = base._result_zip(directory) if resume else None
    if archive is None:
        completed = subprocess.run(
            _backtest_command(window, directory),
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
            return _failed_metric(
                mode,
                window,
                "BACKTEST_FAILED",
                f"Freqtrade exited {completed.returncode}; see run.log.",
            )
        archive = base._result_zip(directory)
    if archive is None:
        return _failed_metric(
            mode, window, "MISSING_ARTIFACT", "Freqtrade produced no ZIP artifact."
        )
    try:
        result = _read_result(archive)
    except (KeyError, StopIteration, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        return _failed_metric(
            mode, window, "INVALID_ARTIFACT", f"Cannot read artifact: {exc}"
        )
    return _summarize(mode, window, result, archive)


def _compound_returns(values: Iterable[float]) -> float:
    return base._compound_returns(values)


def _attribute_continuous_months(result: dict[str, Any]) -> list[SharedMonth]:
    balance = float(result["starting_balance"])
    all_trades = result["trades"]
    rows: list[SharedMonth] = []
    for window in MONTHS:
        start = base._parse_utc(
            f"{window.start[:4]}-{window.start[4:6]}-{window.start[6:]}T00:00:00Z"
        )
        end = base._parse_utc(
            f"{window.end[:4]}-{window.end[4:6]}-{window.end[6:]}T00:00:00Z"
        )
        trades = [
            trade
            for trade in all_trades
            if start <= base._parse_utc(str(trade["close_date"])) < end
        ]
        ratios = [float(trade["profit_ratio"]) for trade in trades]
        absolute = [float(trade["profit_abs"]) for trade in trades]
        winners = [value for value in ratios if value > 0]
        draws = [value for value in ratios if value == 0]
        losers = [value for value in ratios if value < 0]
        gross_profit = sum(value for value in absolute if value > 0)
        gross_loss = abs(sum(value for value in absolute if value < 0))
        profit_factor = gross_profit / gross_loss if gross_loss else None
        payoff = None
        if winners and losers:
            payoff = statistics.mean(winners) / abs(statistics.mean(losers))
        profit_usdt = sum(absolute)
        closing_balance = balance + profit_usdt
        btc_trades = [trade for trade in trades if trade["pair"] == PAIRS[0]]
        eth_trades = [trade for trade in trades if trade["pair"] == PAIRS[1]]
        exit_reasons = Counter(str(trade.get("exit_reason") or "") for trade in trades)
        rows.append(
            SharedMonth(
                month=window.label,
                start=window.start,
                end=window.end,
                trades=len(trades),
                wins=len(winners),
                draws=len(draws),
                losses=len(losers),
                winrate_pct=(len(winners) / len(trades) * 100) if trades else 0.0,
                profit_pct=(profit_usdt / balance * 100) if balance else 0.0,
                profit_usdt=profit_usdt,
                funding_fees_usdt=sum(
                    float(trade.get("funding_fees") or 0) for trade in trades
                ),
                opening_balance=balance,
                closing_balance=closing_balance,
                profit_factor=profit_factor,
                payoff=payoff,
                realized_drawdown_pct=base._realized_drawdown(balance, trades),
                btc_trades=len(btc_trades),
                eth_trades=len(eth_trades),
                btc_profit_usdt=sum(float(t["profit_abs"]) for t in btc_trades),
                eth_profit_usdt=sum(float(t["profit_abs"]) for t in eth_trades),
                long_trades=sum(not bool(trade["is_short"]) for trade in trades),
                short_trades=sum(bool(trade["is_short"]) for trade in trades),
                cross_month_trades=sum(
                    base._parse_utc(str(trade["open_date"])) < start for trade in trades
                ),
                force_exit_trades=exit_reasons.get("force_exit", 0),
                entry_tag_counts=dict(
                    Counter(str(trade.get("enter_tag") or "") for trade in trades)
                ),
                exit_reason_counts=dict(exit_reasons),
            )
        )
        balance = closing_balance
    return rows


def _csv_value(value: Any) -> Any:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _write_records(stem: str, rows: list[Any]) -> None:
    data = [asdict(row) for row in rows]
    (RESULT_ROOT / f"{stem}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not data:
        return
    with (RESULT_ROOT / f"{stem}.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(
            {key: _csv_value(value) for key, value in row.items()} for row in data
        )


def _write_config() -> None:
    config = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    config["bot_name"] = "c04-btc-eth-shared-wallet-monthly-3y"
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def _fmt_ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _summary(
    monthly: list[SharedMetric],
    continuous: SharedMetric,
    attributed: list[SharedMonth],
) -> dict[str, Any]:
    returns = [row.profit_pct for row in monthly]
    attributed_returns = [row.profit_pct for row in attributed]
    best = max(monthly, key=lambda row: row.profit_pct)
    worst = min(monthly, key=lambda row: row.profit_pct)
    return {
        "isolated_months": len(monthly),
        "isolated_total_trades": sum(row.trades for row in monthly),
        "isolated_wins": sum(row.wins for row in monthly),
        "isolated_losses": sum(row.losses for row in monthly),
        "isolated_winrate_pct": sum(row.wins for row in monthly)
        / sum(row.trades for row in monthly)
        * 100,
        "isolated_profitable_months": sum(value > 0 for value in returns),
        "isolated_losing_months": sum(value < 0 for value in returns),
        "isolated_flat_months": sum(value == 0 for value in returns),
        "isolated_average_monthly_return_pct": statistics.mean(returns),
        "isolated_median_monthly_return_pct": statistics.median(returns),
        "isolated_chained_return_pct": _compound_returns(returns),
        "isolated_force_exit_trades": sum(row.force_exit_trades for row in monthly),
        "isolated_best_month": best.window,
        "isolated_best_month_return_pct": best.profit_pct,
        "isolated_worst_month": worst.window,
        "isolated_worst_month_return_pct": worst.profit_pct,
        "continuous_trades": continuous.trades,
        "continuous_winrate_pct": continuous.winrate_pct,
        "continuous_profit_pct": continuous.profit_pct,
        "continuous_profit_usdt": continuous.profit_usdt,
        "continuous_final_balance": continuous.final_balance,
        "continuous_profit_factor": continuous.profit_factor,
        "continuous_payoff": continuous.payoff,
        "continuous_max_drawdown_pct": continuous.max_drawdown_pct,
        "continuous_btc_trades": continuous.btc_trades,
        "continuous_eth_trades": continuous.eth_trades,
        "continuous_btc_profit_usdt": continuous.btc_profit_usdt,
        "continuous_eth_profit_usdt": continuous.eth_profit_usdt,
        "continuous_cross_month_trades": sum(
            row.cross_month_trades for row in attributed
        ),
        "continuous_attributed_compound_return_pct": _compound_returns(
            attributed_returns
        ),
        "continuous_funding_fees_usdt": continuous.funding_fees_usdt,
    }


def _year_rows(
    monthly: list[SharedMetric], attributed: list[SharedMonth]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in (2023, 2024, 2025, 2026):
        isolated = [row for row in monthly if int(row.window[:4]) == year]
        continuous = [row for row in attributed if int(row.month[:4]) == year]
        rows.append(
            {
                "year": year,
                "months": len(isolated),
                "isolated_return_pct": _compound_returns(
                    row.profit_pct for row in isolated
                ),
                "isolated_trades": sum(row.trades for row in isolated),
                "continuous_return_pct": _compound_returns(
                    row.profit_pct for row in continuous
                ),
                "continuous_trades": sum(row.trades for row in continuous),
            }
        )
    return rows


def _write_report(
    monthly: list[SharedMetric],
    continuous: SharedMetric,
    attributed: list[SharedMonth],
    summary: dict[str, Any],
    audit: dict[str, Any],
) -> None:
    lines = [
        "# C04 BTC+ETH 共享钱包三年逐月回测",
        "",
        "覆盖 `[2023-08-01 00:00 UTC, 2026-08-01 00:00 UTC)` 的 36 个完整自然月。",
        "BTC 与 ETH 共用一个 20 USDT 钱包，最多一仓，90% 余额使用率，2 倍杠杆，",
        "0.05% 单边手续费。Funding 有数据时由引擎计入，缺失时回退为 0。",
        "",
        "## 总览",
        "",
        "| 口径 | 交易 | 收益 | 胜率 | Payoff | PF | 最大回撤 | 期末余额 | 月末强平/跨月 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| 36 次独立月串联* | {summary['isolated_total_trades']} | "
            f"{_fmt_pct(summary['isolated_chained_return_pct'])} | "
            f"{summary['isolated_winrate_pct']:.2f}% | — | — | — | — | "
            f"{summary['isolated_force_exit_trades']} |"
        ),
        (
            f"| 连续三年共享钱包 | {continuous.trades} | "
            f"{_fmt_pct(continuous.profit_pct)} | {continuous.winrate_pct:.2f}% | "
            f"{_fmt_ratio(continuous.payoff)} | {_fmt_ratio(continuous.profit_factor)} | "
            f"{continuous.max_drawdown_pct:.2f}% | {continuous.final_balance:.8f} | "
            f"{summary['continuous_cross_month_trades']} |"
        ),
        "",
        "*独立月串联只是数学相乘；每个月都会重置钱包并切断跨月持仓。",
        "",
        "## 每月明细",
        "",
        "| 月份 | 独立月收益 | 交易 | BTC/ETH | 胜率 | PF | Payoff | 回撤 | 强平 | 连续归因收益 | 连续余额 | 连续BTC/ETH |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    isolated_by_month = {row.window: row for row in monthly}
    attributed_by_month = {row.month: row for row in attributed}
    for window in MONTHS:
        isolated = isolated_by_month[window.label]
        continuous_month = attributed_by_month[window.label]
        winrate = f"{isolated.winrate_pct:.2f}%" if isolated.trades else "—"
        lines.append(
            f"| {window.label} | {_fmt_pct(isolated.profit_pct)} | {isolated.trades} | "
            f"{isolated.btc_trades}/{isolated.eth_trades} | {winrate} | "
            f"{_fmt_ratio(isolated.profit_factor)} | {_fmt_ratio(isolated.payoff)} | "
            f"{isolated.max_drawdown_pct:.2f}% | {isolated.force_exit_trades} | "
            f"{_fmt_pct(continuous_month.profit_pct)} | "
            f"{continuous_month.closing_balance:.8f} | "
            f"{continuous_month.btc_trades}/{continuous_month.eth_trades} |"
        )
    lines.extend(
        [
            "",
            "## 分年对照",
            "",
            "2023 只有 8–12 月，2026 只有 1–7 月。",
            "",
            "| 年份 | 月数 | 独立月串联 | 独立交易 | 连续归因收益 | 连续交易 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in _year_rows(monthly, attributed):
        lines.append(
            f"| {row['year']} | {row['months']} | "
            f"{_fmt_pct(row['isolated_return_pct'])} | {row['isolated_trades']} | "
            f"{_fmt_pct(row['continuous_return_pct'])} | {row['continuous_trades']} |"
        )
    lines.extend(
        [
            "",
            "## 数据与解释限制",
            "",
            (
                f"- BTC/ETH 15m 数据各 {audit['BTC']['15m']['rows']} 行，价格缺口、重复和"
                "零成交量均为 0。"
            ),
            (
                f"- 资金侧有效率：BTC {audit['BTC']['cross_venue_15m']['cross_valid_pct']:.4f}%"
                f"，ETH {audit['ETH']['cross_venue_15m']['cross_valid_pct']:.4f}%。"
            ),
            "- 连续月收益按交易平仓月归因，不是严格的月末盯市收益。",
            "- 本回测未模拟额外滑点、冲击成本、交易所中断或实时侧车延迟。",
            "- C04 是后选择策略，本结果是历史刻画，不是新的独立样本外验证。",
        ]
    )
    (RESULT_ROOT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_monthly(*, resume: bool) -> list[SharedMetric]:
    rows: list[SharedMetric] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(
                _run_backtest,
                "isolated_month",
                window,
                RESULT_ROOT / "isolated" / window.label,
                resume=resume,
            ): window
            for window in MONTHS
        }
        for future in as_completed(futures):
            window = futures[future]
            metric = future.result()
            rows.append(metric)
            rows.sort(key=lambda row: row.window)
            _write_records("isolated-monthly-results", rows)
            print(
                f"isolated {window.label} {metric.status:<16} trades={metric.trades:<3} "
                f"btc/eth={metric.btc_trades}/{metric.eth_trades} "
                f"return={metric.profit_pct:>8.2f}% win={metric.winrate_pct:>6.2f}% "
                f"force={metric.force_exit_trades}",
                flush=True,
            )
    return sorted(rows, key=lambda row: row.window)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _write_config()
    for source_file in STRATEGY_SOURCES:
        source = USER_DATA / "strategies" / source_file
        if not source.is_file():
            raise FileNotFoundError(source)
    manifest = DATA_ROOT / "cross-venue" / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(manifest)

    audit, _ = base._data_audit()
    (RESULT_ROOT / "data-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    monthly = _run_monthly(resume=args.resume)
    if any(row.status != "MEASURED" for row in monthly):
        return 1

    continuous = _run_backtest(
        "continuous_3y",
        CONTINUOUS_WINDOW,
        RESULT_ROOT / "continuous",
        resume=args.resume,
    )
    print(
        f"continuous {continuous.status:<16} trades={continuous.trades:<3} "
        f"btc/eth={continuous.btc_trades}/{continuous.eth_trades} "
        f"return={continuous.profit_pct:>8.2f}% win={continuous.winrate_pct:>6.2f}%",
        flush=True,
    )
    _write_records("continuous-result", [continuous])
    if continuous.status != "MEASURED" or continuous.artifact is None:
        return 1

    artifact = Path(continuous.artifact)
    if not artifact.is_absolute():
        artifact = REPO_ROOT / artifact
    attributed = _attribute_continuous_months(_read_result(artifact))
    _write_records("continuous-monthly-attribution", attributed)
    summary = _summary(monthly, continuous, attributed)
    (RESULT_ROOT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_report(monthly, continuous, attributed, summary, audit)

    receipt = {
        "strategy": STRATEGY,
        "research_code": "C04",
        "pair_execution": "BTC and ETH share one wallet with max_open_trades=1",
        "requested_window_utc_half_open": {
            "start": "2023-08-01T00:00:00Z",
            "end_exclusive": "2026-08-01T00:00:00Z",
        },
        "calendar_months": [asdict(window) for window in MONTHS],
        "isolated_monthly_backtests": len(monthly),
        "continuous_backtests": 1,
        "wallet_usdt": 20,
        "tradable_balance_ratio": 0.9,
        "leverage": 2,
        "fee_one_way": 0.0005,
        "funding_rate_config_fallback_when_data_missing": 0.0,
        "max_open_trades": 1,
        "config_sha256": base._sha256(CONFIG),
        "strategy_source_sha256": {
            name: base._sha256(USER_DATA / "strategies" / name)
            for name in STRATEGY_SOURCES
        },
        "runner_sha256": base._sha256(Path(__file__)),
        "data_manifest_sha256": base._sha256(manifest),
        "freqtrade_version": version("freqtrade"),
        "python_version": sys.version,
        "all_backtests_measured": all(
            row.status == "MEASURED" for row in [*monthly, continuous]
        ),
    }
    (RESULT_ROOT / "run-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
