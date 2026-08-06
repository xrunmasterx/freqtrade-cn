from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import zipfile
from dataclasses import asdict, dataclass
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
    / "price-flow-cross-venue-50-rounds"
)
CONFIG = RESULT_ROOT / "research-config.json"
PREREGISTRATION = RESULT_ROOT / "PREREGISTRATION.md"
STRATEGY_SOURCE = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "PriceFlowCrossVenueResearchStrategy.py"
)
USER_DATA = REPO_ROOT / "ft_userdata" / "user_data"
DATA_ROOT = (
    REPO_ROOT / "ft_userdata" / "runtime" / "freqtrade-futures" / "data-price-flow-funded"
)
EXPECTED_PREREGISTRATION_SHA256 = (
    "674be796dbc5272242bd32d6477da2b701259550f6915bed562a350fecde9965"
)
WINDOWS = {
    "d1": ("1722700800", "1754236800"),
    "d2": ("1754236800", "1770220800"),
}
INVALID_DATA = {
    26: "No point-in-time OKX 5m open-interest archive for two-venue OI expansion.",
    27: "No point-in-time OKX 5m open-interest archive for OI migration veto.",
    34: "No archived point-in-time NFP calendar revision snapshots were admitted.",
}


@dataclass
class Metrics:
    code: str
    strategy: str
    window: str
    status: str
    reason: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    winrate: float = 0.0
    payoff: float | None = None
    breakeven_winrate: float | None = None
    profit_factor: float = 0.0
    expectancy: float = 0.0
    profit_pct: float = 0.0
    drawdown_pct: float = 0.0
    btc_trades: int = 0
    eth_trades: int = 0
    long_trades: int = 0
    short_trades: int = 0
    btc_long: int = 0
    btc_short: int = 0
    eth_long: int = 0
    eth_short: int = 0
    independent_weeks: int = 0
    extra_trades: int = 0
    extra_profit_factor: float | None = None
    artifact: str | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frozen cross-venue research funnel.")
    parser.add_argument("--resume", action="store_true")
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_code(candidate_id: int) -> str:
    if candidate_id <= 12:
        return f"B{candidate_id:02d}"
    if candidate_id <= 21:
        return f"D{candidate_id:02d}"
    if candidate_id <= 29:
        return f"X{candidate_id:02d}"
    if candidate_id <= 36:
        return f"P{candidate_id:02d}"
    if candidate_id <= 43:
        return f"A{candidate_id:02d}"
    return f"R{candidate_id:02d}"


def _strategy_name(candidate_id: int) -> str:
    return f"PriceFlowCrossVenue{candidate_id:02d}Strategy"


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


def _summarize(
    code: str,
    strategy: str,
    window: str,
    result: dict[str, Any],
    archive: Path,
) -> Metrics:
    trades = result["trades"]
    profits = [float(trade["profit_ratio"]) for trade in trades]
    winners = [value for value in profits if value > 0]
    losers = [value for value in profits if value < 0]
    payoff = None
    if winners and losers:
        payoff = (sum(winners) / len(winners)) / abs(sum(losers) / len(losers))
    breakeven = 1 / (1 + payoff) if payoff is not None else None
    tags = [str(trade.get("enter_tag") or "") for trade in trades]
    extra_profits = [
        value for value, tag in zip(profits, tags, strict=True) if "_extra_" in tag
    ]
    pairs = [str(trade["pair"]) for trade in trades]
    shorts = [bool(trade["is_short"]) for trade in trades]
    weeks = {
        pd.Timestamp(str(trade["close_date"])).to_period("W").start_time.date().isoformat()
        for trade in trades
        if trade.get("close_date") is not None
    }
    total = next(item for item in result["results_per_pair"] if item["key"] == "TOTAL")
    return Metrics(
        code=code,
        strategy=strategy,
        window=window,
        status="MEASURED",
        reason="",
        trades=len(trades),
        wins=len(winners),
        losses=len(losers),
        winrate=(len(winners) / len(trades)) if trades else 0.0,
        payoff=payoff,
        breakeven_winrate=breakeven,
        profit_factor=float(total["profit_factor"]),
        expectancy=float(total["expectancy"]),
        profit_pct=float(total["profit_total_pct"]),
        drawdown_pct=float(result["max_drawdown_account"]) * 100,
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
        extra_trades=len(extra_profits),
        extra_profit_factor=_profit_factor(extra_profits),
        artifact=str(archive.relative_to(REPO_ROOT)),
    )


def _run_backtest(
    strategy: str, code: str, window: str, *, resume: bool
) -> Metrics:
    directory = RESULT_ROOT / window / code.lower()
    directory.mkdir(parents=True, exist_ok=True)
    existing = _result_zip(directory) if resume else None
    if existing is None:
        start, end = WINDOWS[window]
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
            "--timerange",
            f"{start}-{end}",
            "--fee",
            "0.0005",
            "--cache",
            "none",
            "--backtest-directory",
            str(directory),
            "--export",
            "trades",
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
                window=window,
                status="INVALID_IMPLEMENTATION",
                reason=f"Freqtrade exited {completed.returncode}; see run.log.",
            )
        existing = _result_zip(directory)
    if existing is None:
        return Metrics(
            code=code,
            strategy=strategy,
            window=window,
            status="INVALID_ARTIFACT",
            reason="Freqtrade produced no ZIP artifact.",
        )
    return _summarize(code, strategy, window, _read_result(existing, strategy), existing)


def _d1_gate(metrics: Metrics, baseline: Metrics) -> tuple[str, str]:
    sample_failures = []
    if metrics.trades < 80:
        sample_failures.append("trades<80")
    if metrics.wins < 15 or metrics.losses < 15:
        sample_failures.append("wins_or_losses<15")
    if metrics.btc_trades < 30 or metrics.eth_trades < 30:
        sample_failures.append("asset<30")
    if metrics.long_trades < 25 or metrics.short_trades < 25:
        sample_failures.append("side<25")
    if min(metrics.btc_long, metrics.btc_short, metrics.eth_long, metrics.eth_short) < 10:
        sample_failures.append("asset_side<10")
    if metrics.independent_weeks < 15:
        sample_failures.append("independent_weeks<15")
    if sample_failures:
        return "INSUFFICIENT_D1", ",".join(sample_failures)
    economic_failures = []
    if metrics.profit_pct <= 0 or metrics.profit_pct < baseline.profit_pct:
        economic_failures.append("profit")
    if metrics.payoff is None or metrics.payoff < 1.20:
        economic_failures.append("payoff")
    if (
        metrics.breakeven_winrate is None
        or metrics.winrate < metrics.breakeven_winrate + 0.02
    ):
        economic_failures.append("winrate_vs_breakeven")
    if metrics.profit_factor < 1.10 or metrics.expectancy <= 0:
        economic_failures.append("pf_or_expectancy")
    if metrics.drawdown_pct >= 15 or metrics.drawdown_pct > baseline.drawdown_pct + 2:
        economic_failures.append("drawdown")
    if economic_failures:
        return "REJECTED_D1", ",".join(economic_failures)
    return "D1_SURVIVOR", "all frozen D1 gates passed"


def _d2_gate(metrics: Metrics, baseline: Metrics) -> tuple[str, str]:
    sample_failures = []
    if metrics.trades < 150:
        sample_failures.append("trades<150")
    if metrics.wins < 30 or metrics.losses < 30:
        sample_failures.append("wins_or_losses<30")
    if metrics.btc_trades < 60 or metrics.eth_trades < 60:
        sample_failures.append("asset<60")
    if metrics.long_trades < 50 or metrics.short_trades < 50:
        sample_failures.append("side<50")
    if min(metrics.btc_long, metrics.btc_short, metrics.eth_long, metrics.eth_short) < 25:
        sample_failures.append("asset_side<25")
    if metrics.independent_weeks < 30:
        sample_failures.append("independent_weeks<30")
    if sample_failures:
        return "INSUFFICIENT_D2", ",".join(sample_failures)
    economic_failures = []
    if metrics.profit_pct <= 0 or metrics.profit_pct < baseline.profit_pct + 1:
        economic_failures.append("profit")
    if metrics.payoff is None or metrics.payoff < 1.25:
        economic_failures.append("payoff")
    if (
        metrics.breakeven_winrate is None
        or metrics.winrate < metrics.breakeven_winrate + 0.05
    ):
        economic_failures.append("winrate_vs_breakeven")
    if metrics.profit_factor < max(1.20, baseline.profit_factor):
        economic_failures.append("profit_factor")
    if metrics.expectancy <= 0:
        economic_failures.append("expectancy")
    if metrics.drawdown_pct >= 10 or metrics.drawdown_pct > baseline.drawdown_pct:
        economic_failures.append("drawdown")
    if economic_failures:
        return "REJECTED_D2", ",".join(economic_failures)
    return "D2_POINT_SURVIVOR", "point gates passed; FWER bootstrap still required"


def _write_rows(path: Path, rows: list[Metrics]) -> None:
    data = [asdict(row) for row in rows]
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    with path.with_suffix(".csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    preregistration_hash = _sha256(PREREGISTRATION)
    if preregistration_hash != EXPECTED_PREREGISTRATION_SHA256:
        raise RuntimeError(
            f"Preregistration changed: {preregistration_hash} != "
            f"{EXPECTED_PREREGISTRATION_SHA256}"
        )
    receipt = {
        "preregistration_sha256": preregistration_hash,
        "strategy_sha256": _sha256(STRATEGY_SOURCE),
        "config_sha256": _sha256(CONFIG),
        "runner_sha256": _sha256(Path(__file__)),
        "data_manifest_sha256": _sha256(DATA_ROOT / "cross-venue" / "manifest.json"),
        "windows": WINDOWS,
        "fee": 0.0005,
        "cache": "none",
        "invalid_data_candidates": INVALID_DATA,
    }
    (RESULT_ROOT / "freeze-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"
    )

    baseline_d1 = _run_backtest(
        "PriceFlowCrossVenueControl", "B0", "d1", resume=args.resume
    )
    if baseline_d1.status != "MEASURED":
        raise RuntimeError(f"D1 baseline failed: {baseline_d1.reason}")
    d1_rows: list[Metrics] = [baseline_d1]
    for candidate_id in range(1, 51):
        code = _candidate_code(candidate_id)
        strategy = _strategy_name(candidate_id)
        if candidate_id in INVALID_DATA:
            d1_rows.append(
                Metrics(
                    code=code,
                    strategy=strategy,
                    window="d1",
                    status="INVALID_DATA",
                    reason=INVALID_DATA[candidate_id],
                )
            )
            continue
        measured = _run_backtest(strategy, code, "d1", resume=args.resume)
        if measured.status == "MEASURED":
            measured.status, measured.reason = _d1_gate(measured, baseline_d1)
        d1_rows.append(measured)
        print(
            f"{code}: {measured.status} trades={measured.trades} "
            f"profit={measured.profit_pct:.2f}% pf={measured.profit_factor:.2f}",
            flush=True,
        )
    _write_rows(RESULT_ROOT / "d1-results.json", d1_rows)

    survivors = [row for row in d1_rows if row.status == "D1_SURVIVOR"]
    survivors.sort(
        key=lambda row: (
            -(row.profit_pct - baseline_d1.profit_pct),
            row.drawdown_pct,
            row.code,
        )
    )
    shortlist = survivors[:10]
    baseline_d2 = _run_backtest(
        "PriceFlowCrossVenueControl", "B0", "d2", resume=args.resume
    )
    if baseline_d2.status != "MEASURED":
        raise RuntimeError(f"D2 baseline failed: {baseline_d2.reason}")
    d2_rows = [baseline_d2]
    for d1_row in shortlist:
        measured = _run_backtest(d1_row.strategy, d1_row.code, "d2", resume=args.resume)
        if measured.status == "MEASURED":
            measured.status, measured.reason = _d2_gate(measured, baseline_d2)
        d2_rows.append(measured)
    _write_rows(RESULT_ROOT / "d2-results.json", d2_rows)
    summary = {
        "family_size": 50,
        "d1_survivors": [row.code for row in shortlist],
        "d2_point_survivors": [
            row.code for row in d2_rows if row.status == "D2_POINT_SURVIVOR"
        ],
        "v_opened": False,
        "highest_possible_status": "DEVELOPMENT_SURVIVOR",
    }
    (RESULT_ROOT / "funnel-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
