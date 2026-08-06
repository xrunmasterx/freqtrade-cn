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
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
USER_DATA = REPO_ROOT / "ft_userdata" / "user_data"
DATA_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data-price-flow-deep-5y"
)
RESULT_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "c04-btc-eth-monthly-3y"
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
STRATEGY = "PriceFlowPositionAccountContinuationStrategy"
STRATEGY_SOURCES = (
    "PriceFlowPositionAccountContinuationStrategy.py",
    "PriceFlowCapitalIntentResearchStrategy.py",
    "PriceFlowCrossVenueResearchStrategy.py",
    "PriceFlowContinuationStrategy.py",
)
PAIRS = {
    "BTC": "BTC/USDT:USDT",
    "ETH": "ETH/USDT:USDT",
}
START_DATE = date(2023, 8, 1)
END_DATE = date(2026, 8, 1)
MAX_WORKERS = 2


@dataclass(frozen=True)
class MonthWindow:
    label: str
    start: str
    end: str


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _month_windows(start: date, end: date) -> tuple[MonthWindow, ...]:
    windows: list[MonthWindow] = []
    current = start
    while current < end:
        following = _next_month(current)
        windows.append(
            MonthWindow(
                label=current.strftime("%Y-%m"),
                start=current.strftime("%Y%m%d"),
                end=following.strftime("%Y%m%d"),
            )
        )
        current = following
    return tuple(windows)


MONTHS = _month_windows(START_DATE, END_DATE)
CONTINUOUS_WINDOW = MonthWindow("3y-continuous", "20230801", "20260801")


@dataclass
class Metric:
    mode: str
    asset: str
    pair: str
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
    long_trades: int = 0
    short_trades: int = 0
    force_exit_trades: int = 0
    left_open_trades: int = 0
    rejected_signals: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    average_duration_minutes: float = 0.0
    best_trade_pct: float | None = None
    worst_trade_pct: float | None = None
    gross_profit_usdt: float = 0.0
    gross_loss_usdt: float = 0.0
    cross_valid_pct: float = 0.0
    actual_start_utc: str = ""
    actual_end_utc: str = ""
    entry_tag_counts: dict[str, int] = field(default_factory=dict)
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    trade_fingerprint: str | None = None
    artifact_sha256: str | None = None
    artifact: str | None = None


@dataclass
class ContinuousMonth:
    asset: str
    pair: str
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
    opening_balance: float
    closing_balance: float
    profit_factor: float | None
    payoff: float | None
    realized_drawdown_pct: float
    long_trades: int
    short_trades: int
    cross_month_trades: int
    force_exit_trades: int
    entry_tag_counts: dict[str, int]
    exit_reason_counts: dict[str, int]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run C04 on each BTC/ETH calendar month plus continuous controls."
    )
    parser.add_argument("--resume", action="store_true")
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _trade_fingerprint(trades: list[dict[str, Any]]) -> str:
    keys = (
        "pair",
        "open_date",
        "close_date",
        "open_rate",
        "close_rate",
        "profit_ratio",
        "profit_abs",
        "is_short",
        "enter_tag",
        "exit_reason",
    )
    normalized = [{key: trade.get(key) for key in keys} for trade in trades]
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _result_zip(directory: Path) -> Path | None:
    last_result = directory / ".last_result.json"
    if last_result.is_file():
        latest = json.loads(last_result.read_text(encoding="utf-8")).get(
            "latest_backtest"
        )
        if latest and (directory / latest).is_file():
            return directory / latest
    archives = sorted(directory.glob("*.zip"), key=lambda path: path.stat().st_mtime)
    return archives[-1] if archives else None


def _read_result(archive: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as bundle:
        result_name = next(
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        )
        payload = json.loads(bundle.read(result_name))
    return payload["strategy"][STRATEGY]


def _backtest_command(
    asset: str, window: MonthWindow, directory: Path
) -> list[str]:
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
        PAIRS[asset],
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


def _left_open_count(result: dict[str, Any]) -> int:
    value = result.get("left_open_trades")
    if isinstance(value, list):
        total = next(item for item in value if item["key"] == "TOTAL")
        return int(total["trades"])
    return int(value or 0)


def _summarize(
    mode: str,
    asset: str,
    window: MonthWindow,
    result: dict[str, Any],
    archive: Path,
    *,
    cross_valid_pct: float,
) -> Metric:
    trades = result["trades"]
    ratios = [float(trade["profit_ratio"]) for trade in trades]
    profit_abs = [float(trade["profit_abs"]) for trade in trades]
    winners = [value for value in ratios if value > 0]
    draws = [value for value in ratios if value == 0]
    losers = [value for value in ratios if value < 0]
    payoff = None
    if winners and losers:
        payoff = (sum(winners) / len(winners)) / abs(sum(losers) / len(losers))
    total = next(item for item in result["results_per_pair"] if item["key"] == "TOTAL")
    durations = [float(trade.get("trade_duration") or 0) for trade in trades]
    exit_reasons = Counter(str(trade.get("exit_reason") or "") for trade in trades)
    backtest_start = str(result.get("backtest_start") or "")
    backtest_end = str(result.get("backtest_end") or "")
    return Metric(
        mode=mode,
        asset=asset,
        pair=PAIRS[asset],
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
        long_trades=sum(not bool(trade["is_short"]) for trade in trades),
        short_trades=sum(bool(trade["is_short"]) for trade in trades),
        force_exit_trades=exit_reasons.get("force_exit", 0),
        left_open_trades=_left_open_count(result),
        rejected_signals=int(result.get("rejected_signals") or 0),
        max_consecutive_wins=int(result.get("max_consecutive_wins") or 0),
        max_consecutive_losses=int(result.get("max_consecutive_losses") or 0),
        average_duration_minutes=statistics.mean(durations) if durations else 0.0,
        best_trade_pct=max(ratios) * 100 if ratios else None,
        worst_trade_pct=min(ratios) * 100 if ratios else None,
        gross_profit_usdt=sum(value for value in profit_abs if value > 0),
        gross_loss_usdt=abs(sum(value for value in profit_abs if value < 0)),
        cross_valid_pct=cross_valid_pct,
        actual_start_utc=f"{backtest_start}Z" if backtest_start else "",
        actual_end_utc=f"{backtest_end}Z" if backtest_end else "",
        entry_tag_counts=dict(
            Counter(str(trade.get("enter_tag") or "") for trade in trades)
        ),
        exit_reason_counts=dict(exit_reasons),
        trade_fingerprint=_trade_fingerprint(trades),
        artifact_sha256=_sha256(archive),
        artifact=_display_path(archive),
    )


def _failed_metric(
    mode: str,
    asset: str,
    window: MonthWindow,
    status: str,
    reason: str,
    cross_valid_pct: float,
) -> Metric:
    return Metric(
        mode=mode,
        asset=asset,
        pair=PAIRS[asset],
        window=window.label,
        start=window.start,
        end=window.end,
        status=status,
        reason=reason,
        cross_valid_pct=cross_valid_pct,
    )


def _run_backtest(
    mode: str,
    asset: str,
    window: MonthWindow,
    directory: Path,
    *,
    resume: bool,
    cross_valid_pct: float,
) -> Metric:
    directory.mkdir(parents=True, exist_ok=True)
    archive = _result_zip(directory) if resume else None
    if archive is None:
        completed = subprocess.run(
            _backtest_command(asset, window, directory),
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
                asset,
                window,
                "BACKTEST_FAILED",
                f"Freqtrade exited {completed.returncode}; see run.log.",
                cross_valid_pct,
            )
        archive = _result_zip(directory)
    if archive is None:
        return _failed_metric(
            mode,
            asset,
            window,
            "MISSING_ARTIFACT",
            "Freqtrade produced no ZIP artifact.",
            cross_valid_pct,
        )
    try:
        result = _read_result(archive)
    except (KeyError, StopIteration, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        return _failed_metric(
            mode,
            asset,
            window,
            "INVALID_ARTIFACT",
            f"Cannot read backtest artifact: {exc}",
            cross_valid_pct,
        )
    return _summarize(
        mode,
        asset,
        window,
        result,
        archive,
        cross_valid_pct=cross_valid_pct,
    )


def _compound_returns(returns_pct: Iterable[float]) -> float:
    factor = 1.0
    for value in returns_pct:
        factor *= 1 + float(value) / 100
    return (factor - 1) * 100


def _realized_drawdown(opening_balance: float, trades: list[dict[str, Any]]) -> float:
    equity = opening_balance
    peak = opening_balance
    maximum = 0.0
    for trade in sorted(trades, key=lambda item: _parse_utc(str(item["close_date"]))):
        equity += float(trade["profit_abs"])
        peak = max(peak, equity)
        if peak > 0:
            maximum = max(maximum, (peak - equity) / peak)
    return maximum * 100


def _attribute_continuous_months(
    asset: str, result: dict[str, Any]
) -> list[ContinuousMonth]:
    balance = float(result["starting_balance"])
    all_trades = result["trades"]
    rows: list[ContinuousMonth] = []
    for window in MONTHS:
        start = _parse_utc(f"{window.start[:4]}-{window.start[4:6]}-{window.start[6:]}T00:00:00Z")
        end = _parse_utc(f"{window.end[:4]}-{window.end[4:6]}-{window.end[6:]}T00:00:00Z")
        trades = [
            trade
            for trade in all_trades
            if start <= _parse_utc(str(trade["close_date"])) < end
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
            payoff = (sum(winners) / len(winners)) / abs(sum(losers) / len(losers))
        profit_usdt = sum(absolute)
        closing_balance = balance + profit_usdt
        exit_reasons = Counter(str(trade.get("exit_reason") or "") for trade in trades)
        rows.append(
            ContinuousMonth(
                asset=asset,
                pair=PAIRS[asset],
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
                opening_balance=balance,
                closing_balance=closing_balance,
                profit_factor=profit_factor,
                payoff=payoff,
                realized_drawdown_pct=_realized_drawdown(balance, trades),
                long_trades=sum(not bool(trade["is_short"]) for trade in trades),
                short_trades=sum(bool(trade["is_short"]) for trade in trades),
                cross_month_trades=sum(
                    _parse_utc(str(trade["open_date"])) < start for trade in trades
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


def _timestamp(value: str) -> pd.Timestamp:
    return pd.to_datetime(value, format="%Y%m%d", utc=True)


def _data_audit() -> tuple[dict[str, Any], dict[tuple[str, str], float]]:
    audit: dict[str, Any] = {}
    coverage: dict[tuple[str, str], float] = {}
    start = _timestamp(CONTINUOUS_WINDOW.start)
    end = _timestamp(CONTINUOUS_WINDOW.end)
    for asset in PAIRS:
        asset_audit: dict[str, Any] = {}
        for timeframe, interval in (("15m", "15min"), ("1h", "1h"), ("4h", "4h")):
            path = DATA_ROOT / "futures" / f"{asset}_USDT_USDT-{timeframe}-futures.feather"
            frame = pd.read_feather(path, columns=["date", "volume"])
            dates = pd.to_datetime(frame["date"], utc=True)
            selected = frame.loc[(dates >= start) & (dates < end)].copy()
            selected_dates = pd.to_datetime(selected["date"], utc=True).reset_index(drop=True)
            expected_rows = int((end - start) / pd.Timedelta(interval))
            gaps = int((selected_dates.diff().dropna() != pd.Timedelta(interval)).sum())
            duplicates = int(selected_dates.duplicated().sum())
            zero_volume = int((selected["volume"] <= 0).sum())
            if len(selected) != expected_rows or gaps or duplicates or zero_volume:
                raise ValueError(
                    f"Incomplete {asset} {timeframe} data: rows={len(selected)}/"
                    f"{expected_rows}, gaps={gaps}, duplicates={duplicates}, "
                    f"zero_volume={zero_volume}"
                )
            asset_audit[timeframe] = {
                "rows": len(selected),
                "expected_rows": expected_rows,
                "gaps": gaps,
                "duplicates": duplicates,
                "zero_volume": zero_volume,
                "first_utc": selected_dates.iloc[0].isoformat(),
                "last_utc": selected_dates.iloc[-1].isoformat(),
            }

        mark_path = DATA_ROOT / "futures" / f"{asset}_USDT_USDT-1h-mark.feather"
        mark = pd.read_feather(mark_path, columns=["date", "close"])
        mark_dates = pd.to_datetime(mark["date"], utc=True)
        mark_selected = mark.loc[(mark_dates >= start) & (mark_dates < end)].copy()
        selected_mark_dates = pd.to_datetime(
            mark_selected["date"], utc=True
        ).reset_index(drop=True)
        expected_mark_rows = int((end - start) / pd.Timedelta(hours=1))
        mark_gaps = int(
            (selected_mark_dates.diff().dropna() != pd.Timedelta(hours=1)).sum()
        )
        mark_duplicates = int(selected_mark_dates.duplicated().sum())
        invalid_mark_values = int(
            pd.to_numeric(mark_selected["close"], errors="coerce").isna().sum()
        )
        if (
            len(mark_selected) != expected_mark_rows
            or mark_gaps
            or mark_duplicates
            or invalid_mark_values
        ):
            raise ValueError(
                f"Incomplete {asset} mark data: rows={len(mark_selected)}/"
                f"{expected_mark_rows}, gaps={mark_gaps}, duplicates={mark_duplicates}, "
                f"invalid_values={invalid_mark_values}"
            )
        asset_audit["mark_1h"] = {
            "rows": len(mark_selected),
            "expected_rows": expected_mark_rows,
            "gaps": mark_gaps,
            "duplicates": mark_duplicates,
            "invalid_values": invalid_mark_values,
            "first_utc": selected_mark_dates.iloc[0].isoformat(),
            "last_utc": selected_mark_dates.iloc[-1].isoformat(),
        }

        funding_path = (
            DATA_ROOT / "futures" / f"{asset}_USDT_USDT-1h-funding_rate.feather"
        )
        funding = pd.read_feather(funding_path, columns=["date", "close"])
        funding_dates = pd.to_datetime(funding["date"], utc=True)
        funding_selected = funding.loc[
            (funding_dates >= start) & (funding_dates < end)
        ].copy()
        selected_funding_dates = pd.to_datetime(
            funding_selected["date"], utc=True
        ).reset_index(drop=True)
        expected_funding_rows = int((end - start) / pd.Timedelta(hours=8))
        funding_gaps = int(
            (selected_funding_dates.diff().dropna() != pd.Timedelta(hours=8)).sum()
        )
        funding_duplicates = int(selected_funding_dates.duplicated().sum())
        invalid_funding_values = int(
            pd.to_numeric(funding_selected["close"], errors="coerce").isna().sum()
        )
        if (
            funding_selected.empty
            or funding_gaps
            or funding_duplicates
            or invalid_funding_values
            or selected_funding_dates.iloc[-1] + pd.Timedelta(hours=8) != end
        ):
            raise ValueError(
                f"Invalid {asset} funding data: rows={len(funding_selected)}, "
                f"gaps={funding_gaps}, duplicates={funding_duplicates}, "
                f"invalid_values={invalid_funding_values}"
            )
        missing_initial_rows = int(
            (selected_funding_dates.iloc[0] - start) / pd.Timedelta(hours=8)
        )
        asset_audit["funding_rate_8h"] = {
            "rows": len(funding_selected),
            "full_window_expected_rows": expected_funding_rows,
            "observed_coverage_pct": len(funding_selected)
            / expected_funding_rows
            * 100,
            "missing_initial_rows_using_config_fallback": missing_initial_rows,
            "config_fallback_rate": 0.0,
            "gaps_within_observed_period": funding_gaps,
            "duplicates": funding_duplicates,
            "invalid_values": invalid_funding_values,
            "first_observed_utc": selected_funding_dates.iloc[0].isoformat(),
            "last_observed_utc": selected_funding_dates.iloc[-1].isoformat(),
        }

        sidecar_path = DATA_ROOT / "cross-venue" / f"{asset}_USDT_USDT-15m-cross-venue.feather"
        sidecar = pd.read_feather(
            sidecar_path, columns=["date", "decision_time", "cross_data_valid"]
        )
        dates = pd.to_datetime(sidecar["date"], utc=True)
        decisions = pd.to_datetime(sidecar["decision_time"], utc=True)
        selected_mask = (dates >= start) & (dates < end)
        selected_dates = dates[selected_mask].reset_index(drop=True)
        expected_rows = int((end - start) / pd.Timedelta(minutes=15))
        gaps = int((selected_dates.diff().dropna() != pd.Timedelta(minutes=15)).sum())
        duplicates = int(selected_dates.duplicated().sum())
        bad_decisions = int(
            (decisions[selected_mask] != dates[selected_mask] + pd.Timedelta(minutes=15)).sum()
        )
        if len(selected_dates) != expected_rows or gaps or duplicates or bad_decisions:
            raise ValueError(
                f"Incomplete {asset} sidecar: rows={len(selected_dates)}/{expected_rows}, "
                f"gaps={gaps}, duplicates={duplicates}, bad_decisions={bad_decisions}"
            )
        for window in MONTHS:
            month_mask = (dates >= _timestamp(window.start)) & (dates < _timestamp(window.end))
            expected_month_rows = int(
                (_timestamp(window.end) - _timestamp(window.start))
                / pd.Timedelta(minutes=15)
            )
            if int(month_mask.sum()) != expected_month_rows:
                raise ValueError(f"Incomplete {asset} sidecar month {window.label}")
            coverage[(asset, window.label)] = float(
                sidecar.loc[month_mask, "cross_data_valid"].fillna(False).mean() * 100
            )
        valid_pct = float(
            sidecar.loc[selected_mask, "cross_data_valid"].fillna(False).mean() * 100
        )
        coverage[(asset, CONTINUOUS_WINDOW.label)] = valid_pct
        asset_audit["cross_venue_15m"] = {
            "rows": len(selected_dates),
            "expected_rows": expected_rows,
            "gaps": gaps,
            "duplicates": duplicates,
            "bad_decision_boundaries": bad_decisions,
            "cross_valid_pct": valid_pct,
            "minimum_monthly_cross_valid_pct": min(
                coverage[(asset, window.label)] for window in MONTHS
            ),
        }
        audit[asset] = asset_audit
    return audit, coverage


def _write_config() -> None:
    config = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    config["bot_name"] = "c04-btc-eth-monthly-3y"
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _streak(values: Iterable[float], *, positive: bool) -> int:
    best = 0
    current = 0
    for value in values:
        matches = value > 0 if positive else value < 0
        current = current + 1 if matches else 0
        best = max(best, current)
    return best


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def _fmt_ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _summary_data(
    monthly: list[Metric],
    continuous: list[Metric],
    attributed: list[ContinuousMonth],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for asset in PAIRS:
        isolated_rows = sorted(
            (row for row in monthly if row.asset == asset), key=lambda row: row.window
        )
        continuous_metric = next(row for row in continuous if row.asset == asset)
        continuous_rows = sorted(
            (row for row in attributed if row.asset == asset), key=lambda row: row.month
        )
        returns = [row.profit_pct for row in isolated_rows]
        continuous_returns = [row.profit_pct for row in continuous_rows]
        best = max(isolated_rows, key=lambda row: row.profit_pct)
        worst = min(isolated_rows, key=lambda row: row.profit_pct)
        result[asset] = {
            "isolated_months": len(isolated_rows),
            "isolated_total_trades": sum(row.trades for row in isolated_rows),
            "isolated_wins": sum(row.wins for row in isolated_rows),
            "isolated_losses": sum(row.losses for row in isolated_rows),
            "isolated_trade_winrate_pct": (
                sum(row.wins for row in isolated_rows)
                / sum(row.trades for row in isolated_rows)
                * 100
                if sum(row.trades for row in isolated_rows)
                else 0.0
            ),
            "isolated_profitable_months": sum(value > 0 for value in returns),
            "isolated_losing_months": sum(value < 0 for value in returns),
            "isolated_flat_months": sum(value == 0 for value in returns),
            "isolated_no_trade_months": sum(row.trades == 0 for row in isolated_rows),
            "isolated_average_monthly_return_pct": statistics.mean(returns),
            "isolated_median_monthly_return_pct": statistics.median(returns),
            "isolated_chained_return_pct": _compound_returns(returns),
            "isolated_force_exit_trades": sum(
                row.force_exit_trades for row in isolated_rows
            ),
            "isolated_best_month": best.window,
            "isolated_best_month_return_pct": best.profit_pct,
            "isolated_worst_month": worst.window,
            "isolated_worst_month_return_pct": worst.profit_pct,
            "isolated_longest_positive_streak_months": _streak(returns, positive=True),
            "isolated_longest_negative_streak_months": _streak(returns, positive=False),
            "continuous_trades": continuous_metric.trades,
            "continuous_winrate_pct": continuous_metric.winrate_pct,
            "continuous_profit_pct": continuous_metric.profit_pct,
            "continuous_profit_usdt": continuous_metric.profit_usdt,
            "continuous_funding_fees_usdt": continuous_metric.funding_fees_usdt,
            "continuous_final_balance": continuous_metric.final_balance,
            "continuous_profit_factor": continuous_metric.profit_factor,
            "continuous_payoff": continuous_metric.payoff,
            "continuous_max_drawdown_pct": continuous_metric.max_drawdown_pct,
            "continuous_profitable_months": sum(
                value > 0 for value in continuous_returns
            ),
            "continuous_losing_months": sum(value < 0 for value in continuous_returns),
            "continuous_flat_months": sum(value == 0 for value in continuous_returns),
            "continuous_cross_month_trades": sum(
                row.cross_month_trades for row in continuous_rows
            ),
            "continuous_attributed_compound_return_pct": _compound_returns(
                continuous_returns
            ),
        }
    btc = [row.profit_pct for row in monthly if row.asset == "BTC"]
    eth = [row.profit_pct for row in monthly if row.asset == "ETH"]
    result["isolated_btc_eth_monthly_return_correlation"] = float(
        pd.Series(btc).corr(pd.Series(eth))
    )
    return result


def _year_rows(
    monthly: list[Metric], attributed: list[ContinuousMonth]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in PAIRS:
        for year in (2023, 2024, 2025, 2026):
            isolated = [
                row
                for row in monthly
                if row.asset == asset and int(row.window[:4]) == year
            ]
            continuous = [
                row
                for row in attributed
                if row.asset == asset and int(row.month[:4]) == year
            ]
            rows.append(
                {
                    "asset": asset,
                    "year": year,
                    "months": len(isolated),
                    "isolated_chained_return_pct": _compound_returns(
                        row.profit_pct for row in isolated
                    ),
                    "isolated_trades": sum(row.trades for row in isolated),
                    "isolated_winrate_pct": (
                        sum(row.wins for row in isolated)
                        / sum(row.trades for row in isolated)
                        * 100
                        if sum(row.trades for row in isolated)
                        else 0.0
                    ),
                    "continuous_compound_return_pct": _compound_returns(
                        row.profit_pct for row in continuous
                    ),
                    "continuous_trades": sum(row.trades for row in continuous),
                    "continuous_winrate_pct": (
                        sum(row.wins for row in continuous)
                        / sum(row.trades for row in continuous)
                        * 100
                        if sum(row.trades for row in continuous)
                        else 0.0
                    ),
                }
            )
    return rows


def _seasonality_rows(monthly: list[Metric]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in PAIRS:
        for month_number in range(1, 13):
            selected = [
                row.profit_pct
                for row in monthly
                if row.asset == asset and int(row.window[5:]) == month_number
            ]
            rows.append(
                {
                    "asset": asset,
                    "calendar_month": month_number,
                    "observations": len(selected),
                    "average_isolated_return_pct": statistics.mean(selected),
                    "median_isolated_return_pct": statistics.median(selected),
                    "profitable_observations": sum(value > 0 for value in selected),
                }
            )
    return rows


def _write_report(
    monthly: list[Metric],
    continuous: list[Metric],
    attributed: list[ContinuousMonth],
    summary: dict[str, Any],
    audit: dict[str, Any],
) -> None:
    lines = [
        "# C04 BTC/ETH 三年逐月深度回测",
        "",
        "## 结论口径",
        "",
        "本报告覆盖 `[2023-08-01 00:00 UTC, 2026-08-01 00:00 UTC)` 的 36 个完整自然月。",
        "策略为冻结的 `PriceFlowPositionAccountContinuationStrategy`（C04），BTC 与 ETH 独立运行。",
        "每次回测使用 20 USDT、2 倍杠杆、0.05% 单边手续费、最多一个持仓；本地可用的",
        "资金费率由引擎计入，缺失区间使用配置回退值 0。",
        "",
        "逐月独立结果每月重置钱包，并可能在月底产生 `force_exit`；连续三年结果不在月界重启，",
        "其月收益按交易平仓月归因。后者把跨月交易的全部盈亏放进平仓月，不是月末盯市收益。",
        "",
        "## 三年总览",
        "",
        "| 资产 | 独立月交易 | 盈利月/36 | 独立月总胜率 | 独立月串联收益* | 月末强平 | 连续交易 | 连续收益 | 连续胜率 | PF | 盈亏比 | 最大回撤 | Funding净值 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for asset in PAIRS:
        values = summary[asset]
        lines.append(
            f"| {asset} | {values['isolated_total_trades']} | "
            f"{values['isolated_profitable_months']}/36 | "
            f"{values['isolated_trade_winrate_pct']:.2f}% | "
            f"{_fmt_pct(values['isolated_chained_return_pct'])} | "
            f"{values['isolated_force_exit_trades']} | {values['continuous_trades']} | "
            f"{_fmt_pct(values['continuous_profit_pct'])} | "
            f"{values['continuous_winrate_pct']:.2f}% | "
            f"{_fmt_ratio(values['continuous_profit_factor'])} | "
            f"{_fmt_ratio(values['continuous_payoff'])} | "
            f"{values['continuous_max_drawdown_pct']:.2f}% | "
            f"{values['continuous_funding_fees_usdt']:+.6f} USDT |"
        )
    lines.extend(
        [
            "",
            "*“独立月串联收益”只是把 36 次重置实验的收益率数学相乘，用于诊断稳定性；",
            "它不是可执行的连续资金曲线。可执行性更接近右侧的连续三年结果。",
            "",
            (
                f"BTC/ETH 独立月收益相关系数："
                f"`{summary['isolated_btc_eth_monthly_return_correlation']:.3f}`"
                "（36 个样本）。"
            ),
            "",
            "## 数据完整性",
            "",
            "| 资产 | 15m/1h/4h 行数 | 价格缺口 | 零成交量 | Mark 1h | Funding 8h覆盖 | 资金侧行数 | 资金侧有效率 | 最低单月有效率 | 决策边界错误 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for asset in PAIRS:
        values = audit[asset]
        cross = values["cross_venue_15m"]
        funding = values["funding_rate_8h"]
        lines.append(
            f"| {asset} | {values['15m']['rows']}/{values['1h']['rows']}/"
            f"{values['4h']['rows']} | "
            f"{values['15m']['gaps'] + values['1h']['gaps'] + values['4h']['gaps']} | "
            f"{values['15m']['zero_volume'] + values['1h']['zero_volume'] + values['4h']['zero_volume']} | "
            f"{values['mark_1h']['rows']}/{values['mark_1h']['expected_rows']} | "
            f"{funding['rows']}/{funding['full_window_expected_rows']} "
            f"({funding['observed_coverage_pct']:.2f}%) | "
            f"{cross['rows']} | {cross['cross_valid_pct']:.4f}% | "
            f"{cross['minimum_monthly_cross_valid_pct']:.4f}% | "
            f"{cross['bad_decision_boundaries']} |"
        )

    lines.extend(
        [
            "",
            "## 分年对照",
            "",
            "2023 仅含 8–12 月，2026 仅含 1–7 月；2024 和 2025 各含 12 个月。",
            "",
            "| 资产 | 年份 | 月数 | 独立月串联收益 | 独立交易/胜率 | 连续归因收益 | 连续交易/胜率 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in _year_rows(monthly, attributed):
        lines.append(
            f"| {row['asset']} | {row['year']} | {row['months']} | "
            f"{_fmt_pct(row['isolated_chained_return_pct'])} | "
            f"{row['isolated_trades']}/{row['isolated_winrate_pct']:.2f}% | "
            f"{_fmt_pct(row['continuous_compound_return_pct'])} | "
            f"{row['continuous_trades']}/{row['continuous_winrate_pct']:.2f}% |"
        )

    for asset in PAIRS:
        lines.extend(
            [
                "",
                f"## {asset} 每月明细",
                "",
                "| 月份 | 独立收益 | 交易 | 胜率 | PF | 回撤 | 月末强平 | 连续归因收益 | 交易 | 胜率 | PF | 跨月交易 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        isolated_by_month = {
            row.window: row for row in monthly if row.asset == asset
        }
        continuous_by_month = {
            row.month: row for row in attributed if row.asset == asset
        }
        for window in MONTHS:
            isolated = isolated_by_month[window.label]
            continuous_row = continuous_by_month[window.label]
            isolated_win = (
                f"{isolated.winrate_pct:.2f}%" if isolated.trades else "—"
            )
            continuous_win = (
                f"{continuous_row.winrate_pct:.2f}%" if continuous_row.trades else "—"
            )
            lines.append(
                f"| {window.label} | {_fmt_pct(isolated.profit_pct)} | "
                f"{isolated.trades} | {isolated_win} | "
                f"{_fmt_ratio(isolated.profit_factor)} | "
                f"{isolated.max_drawdown_pct:.2f}% | {isolated.force_exit_trades} | "
                f"{_fmt_pct(continuous_row.profit_pct)} | {continuous_row.trades} | "
                f"{continuous_win} | {_fmt_ratio(continuous_row.profit_factor)} | "
                f"{continuous_row.cross_month_trades} |"
            )
        values = summary[asset]
        lines.extend(
            [
                "",
                (
                    f"- 独立月最好：`{values['isolated_best_month']}` "
                    f"({_fmt_pct(values['isolated_best_month_return_pct'])})；最差："
                    f"`{values['isolated_worst_month']}` "
                    f"({_fmt_pct(values['isolated_worst_month_return_pct'])})。"
                ),
                (
                    f"- 最长连续盈利月："
                    f"{values['isolated_longest_positive_streak_months']}；最长连续亏损月："
                    f"{values['isolated_longest_negative_streak_months']}。"
                ),
                (
                    f"- 连续三年期末余额：{values['continuous_final_balance']:.8f} "
                    f"USDT；跨月平仓交易：{values['continuous_cross_month_trades']}。"
                ),
            ]
        )

    lines.extend(
        [
            "",
            "## 自然月季节性（探索性）",
            "",
            "每个自然月只有 3 个观测，不能据此声明稳定季节性。",
            "",
            "| 资产 | 自然月 | 样本 | 平均独立收益 | 中位数 | 盈利次数 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in _seasonality_rows(monthly):
        lines.append(
            f"| {row['asset']} | {row['calendar_month']:02d} | "
            f"{row['observations']} | {_fmt_pct(row['average_isolated_return_pct'])} | "
            f"{_fmt_pct(row['median_isolated_return_pct'])} | "
            f"{row['profitable_observations']}/{row['observations']} |"
        )

    lines.extend(
        [
            "",
            "## 解释限制",
            "",
            (
                "- 逐月独立回测会切断跨月持仓，并在每个月重新获得 960 根启动 K 线；"
                "连续对照用于量化这种边界效应。"
            ),
            "- 连续月归因按平仓时间确认全部盈亏；跨月未实现盈亏不会在月末盯市。",
            (
                "- 手续费为每边 0.05%。Funding 文件从 2024-05-31 16:00 UTC 起按 8 小时完整"
                "覆盖至结束；此前缺失段使用配置回退值 0。未模拟额外滑点、冲击成本、交易所"
                "中断或实时侧车延迟。"
            ),
            (
                "- C04 使用的是公开聚合资金代理变量；它们不能识别具体交易者、开仓/平仓意图"
                "或所谓“大资金”身份。"
            ),
            (
                "- C04 是历史研究后选出的策略，本结果仍受后选择偏差影响，不构成未来收益保证或"
                "实盘启用依据。"
            ),
            "",
            "## 机器可读证据",
            "",
            "- `isolated-monthly-results.csv/json`：72 次逐月独立回测。",
            "- `continuous-results.csv/json`：BTC、ETH 各一次连续三年回测。",
            "- `continuous-monthly-attribution.csv/json`：连续结果的 72 条月度归因。",
            "- `summary.json`、`data-audit.json`、`run-receipt.json`：汇总、数据门禁与哈希。",
        ]
    )
    (RESULT_ROOT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_jobs(
    jobs: list[tuple[str, MonthWindow, Path]],
    mode: str,
    *,
    resume: bool,
    coverage: dict[tuple[str, str], float],
) -> list[Metric]:
    rows: list[Metric] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(
                _run_backtest,
                mode,
                asset,
                window,
                directory,
                resume=resume,
                cross_valid_pct=coverage[(asset, window.label)],
            ): (asset, window)
            for asset, window, directory in jobs
        }
        for future in as_completed(futures):
            asset, window = futures[future]
            metric = future.result()
            rows.append(metric)
            rows.sort(key=lambda row: (row.window, row.asset))
            if mode == "isolated_month":
                _write_records("isolated-monthly-results", rows)
            print(
                f"{mode:<16} {window.label} {asset} {metric.status:<16} "
                f"trades={metric.trades:<3} return={metric.profit_pct:>8.2f}% "
                f"win={metric.winrate_pct:>6.2f}% force={metric.force_exit_trades}",
                flush=True,
            )
    return sorted(rows, key=lambda row: (row.window, row.asset))


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if len(MONTHS) != 36:
        raise ValueError(f"Expected 36 calendar months, found {len(MONTHS)}")
    _write_config()
    for source_file in STRATEGY_SOURCES:
        source = USER_DATA / "strategies" / source_file
        if not source.is_file():
            raise FileNotFoundError(source)
    manifest = DATA_ROOT / "cross-venue" / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(manifest)

    audit, coverage = _data_audit()
    (RESULT_ROOT / "data-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    monthly_jobs = [
        (
            asset,
            window,
            RESULT_ROOT / "isolated" / asset.lower() / window.label,
        )
        for window in MONTHS
        for asset in PAIRS
    ]
    monthly_rows = _run_jobs(
        monthly_jobs,
        "isolated_month",
        resume=args.resume,
        coverage=coverage,
    )
    monthly_failures = [row for row in monthly_rows if row.status != "MEASURED"]
    if monthly_failures:
        return 1

    continuous_jobs = [
        (
            asset,
            CONTINUOUS_WINDOW,
            RESULT_ROOT / "continuous" / asset.lower(),
        )
        for asset in PAIRS
    ]
    continuous_rows = _run_jobs(
        continuous_jobs,
        "continuous_3y",
        resume=args.resume,
        coverage=coverage,
    )
    _write_records("continuous-results", continuous_rows)
    continuous_failures = [row for row in continuous_rows if row.status != "MEASURED"]
    if continuous_failures:
        return 1

    attributed: list[ContinuousMonth] = []
    for metric in continuous_rows:
        if metric.artifact is None:
            raise ValueError(f"Missing continuous artifact for {metric.asset}")
        artifact = Path(metric.artifact)
        if not artifact.is_absolute():
            artifact = REPO_ROOT / artifact
        attributed.extend(_attribute_continuous_months(metric.asset, _read_result(artifact)))
    attributed.sort(key=lambda row: (row.month, row.asset))
    _write_records("continuous-monthly-attribution", attributed)

    summary = _summary_data(monthly_rows, continuous_rows, attributed)
    (RESULT_ROOT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_report(monthly_rows, continuous_rows, attributed, summary, audit)

    receipt = {
        "strategy": STRATEGY,
        "research_code": "C04",
        "requested_window_utc_half_open": {
            "start": "2023-08-01T00:00:00Z",
            "end_exclusive": "2026-08-01T00:00:00Z",
        },
        "calendar_months": [asdict(window) for window in MONTHS],
        "isolated_backtests": len(monthly_rows),
        "continuous_backtests": len(continuous_rows),
        "wallet_usdt_per_backtest": 20,
        "leverage": 2,
        "fee_one_way": 0.0005,
        "funding_rate_config_fallback_when_data_missing": 0.0,
        "funding_rate_observed_data_is_applied": True,
        "max_open_trades": 1,
        "pair_execution": "separate single-asset backtests",
        "config": _display_path(CONFIG),
        "config_sha256": _sha256(CONFIG),
        "strategy_source_sha256": {
            name: _sha256(USER_DATA / "strategies" / name)
            for name in STRATEGY_SOURCES
        },
        "runner_sha256": _sha256(Path(__file__)),
        "data_manifest_sha256": _sha256(manifest),
        "freqtrade_version": version("freqtrade"),
        "python_version": sys.version,
        "all_backtests_measured": all(
            row.status == "MEASURED" for row in monthly_rows + continuous_rows
        ),
    }
    (RESULT_ROOT / "run-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
