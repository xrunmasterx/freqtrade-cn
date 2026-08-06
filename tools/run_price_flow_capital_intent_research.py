from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
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
    / "price-flow-capital-intent-20-rounds"
)
CONFIG = RESULT_ROOT / "research-config.json"
PREREGISTRATION = RESULT_ROOT / "PREREGISTRATION.md"
STRATEGY_SOURCE = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "PriceFlowCapitalIntentResearchStrategy.py"
)
STRATEGY_DEPENDENCIES = [
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "PriceFlowCrossVenueResearchStrategy.py",
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / "PriceFlowContinuationStrategy.py",
]
USER_DATA = REPO_ROOT / "ft_userdata" / "user_data"
DATA_ROOT = (
    REPO_ROOT / "ft_userdata" / "runtime" / "freqtrade-futures" / "data-price-flow-deep-5y"
)
EXPECTED_PREREGISTRATION_SHA256 = (
    "8f7d65d1a7446078c6e2f698915263cdd7d0aab657450075a349973e2428cd59"
)
DEVELOPMENT_WINDOW = ("1690848000", "1754006400")
CHALLENGE_WINDOW = ("1754006400", "1785542400")
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


@dataclass
class Metrics:
    code: str
    strategy: str
    window: str
    status: str = "MEASURED"
    reason: str = ""
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
    profitable_folds: int = 0
    worst_fold_profit_pct: float = 0.0
    min_asset_profit_factor: float = 0.0
    top3_gross_profit_share: float = 0.0
    best_month_positive_share: float = 0.0
    folds: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    pair_profit_sum_pct: dict[str, float] = field(default_factory=dict)
    pair_profit_factor: dict[str, float | None] = field(default_factory=dict)
    entry_tag_counts: dict[str, int] = field(default_factory=dict)
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    trade_fingerprint: str | None = None
    artifact: str | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen 20-round PriceFlow capital-intent study."
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
    return f"PriceFlowCapitalIntent{candidate_id:02d}Strategy"


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


def _fold_metrics(
    trades: list[dict[str, Any]],
    fold_boundaries: dict[str, tuple[str, str]],
) -> dict[str, dict[str, float | int | None]]:
    result: dict[str, dict[str, float | int | None]] = {}
    for label, (start_value, end_value) in fold_boundaries.items():
        start = pd.Timestamp(start_value)
        end = pd.Timestamp(end_value)
        selected = []
        for trade in trades:
            opened = pd.Timestamp(str(trade["open_date"]))
            if opened.tzinfo is None:
                opened = opened.tz_localize("UTC")
            else:
                opened = opened.tz_convert("UTC")
            if start <= opened < end:
                selected.append(float(trade["profit_ratio"]))
        result[label] = {
            "trades": len(selected),
            "wins": sum(value > 0 for value in selected),
            "losses": sum(value < 0 for value in selected),
            "profit_sum_pct": round(sum(selected) * 100, 10),
            "profit_factor": _profit_factor(selected),
        }
    return result


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


def _summarize(
    code: str,
    strategy: str,
    window: str,
    fold_boundaries: dict[str, tuple[str, str]],
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
    pairs = [str(trade["pair"]) for trade in trades]
    shorts = [bool(trade["is_short"]) for trade in trades]
    weeks = {
        pd.Timestamp(str(trade["close_date"])).to_period("W").start_time.date().isoformat()
        for trade in trades
        if trade.get("close_date") is not None
    }
    folds = _fold_metrics(trades, fold_boundaries)
    fold_profits = [float(values["profit_sum_pct"] or 0) for values in folds.values()]

    pair_values: dict[str, list[float]] = {"BTC": [], "ETH": []}
    for pair, value in zip(pairs, profits, strict=True):
        asset = pair.split("/", maxsplit=1)[0]
        if asset in pair_values:
            pair_values[asset].append(value)
    pair_profit_sum = {
        asset: round(sum(values) * 100, 10) for asset, values in pair_values.items()
    }
    pair_profit_factor = {
        asset: _profit_factor(values) for asset, values in pair_values.items()
    }
    finite_pair_pf = [
        0.0 if value is None else float(value) for value in pair_profit_factor.values()
    ]

    gross_profit = sum(winners)
    top3_share = sum(sorted(winners, reverse=True)[:3]) / gross_profit if gross_profit else 0
    month_profit: dict[str, float] = {}
    for trade, value in zip(trades, profits, strict=True):
        month = pd.Timestamp(str(trade["open_date"])).strftime("%Y-%m")
        month_profit[month] = month_profit.get(month, 0.0) + value
    positive_month_total = sum(value for value in month_profit.values() if value > 0)
    best_month_share = (
        max(month_profit.values(), default=0.0) / positive_month_total
        if positive_month_total > 0
        else 0.0
    )

    total = next(item for item in result["results_per_pair"] if item["key"] == "TOTAL")
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
        profitable_folds=sum(value > 0 for value in fold_profits),
        worst_fold_profit_pct=min(fold_profits, default=0.0),
        min_asset_profit_factor=min(finite_pair_pf, default=0.0),
        top3_gross_profit_share=top3_share,
        best_month_positive_share=best_month_share,
        folds=folds,
        pair_profit_sum_pct=pair_profit_sum,
        pair_profit_factor=pair_profit_factor,
        entry_tag_counts=dict(Counter(str(trade.get("enter_tag") or "") for trade in trades)),
        exit_reason_counts=dict(
            Counter(str(trade.get("exit_reason") or "") for trade in trades)
        ),
        trade_fingerprint=_trade_fingerprint(trades),
        artifact=artifact,
    )


def _run_backtest(
    strategy: str,
    code: str,
    window_name: str,
    timerange: tuple[str, str],
    fold_boundaries: dict[str, tuple[str, str]],
    *,
    resume: bool,
) -> Metrics:
    directory = RESULT_ROOT / window_name / code.lower()
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
                window=window_name,
                status="INVALID_IMPLEMENTATION",
                reason=f"Freqtrade exited {completed.returncode}; see run.log.",
            )
        existing = _result_zip(directory)
    if existing is None:
        return Metrics(
            code=code,
            strategy=strategy,
            window=window_name,
            status="INVALID_ARTIFACT",
            reason="Freqtrade produced no ZIP artifact.",
        )
    return _summarize(
        code,
        strategy,
        window_name,
        fold_boundaries,
        _read_result(existing, strategy),
        existing,
    )


def _development_gate(metrics: Metrics, baseline: Metrics) -> tuple[str, str]:
    sample_failures = []
    if metrics.trades < 70:
        sample_failures.append("trades<70")
    if metrics.wins < 20 or metrics.losses < 20:
        sample_failures.append("wins_or_losses<20")
    if metrics.btc_trades < 20 or metrics.eth_trades < 20:
        sample_failures.append("asset<20")
    if metrics.long_trades < 35 or metrics.short_trades < 15:
        sample_failures.append("side")
    if min(metrics.btc_long, metrics.btc_short, metrics.eth_long, metrics.eth_short) < 5:
        sample_failures.append("asset_side<5")
    if metrics.independent_weeks < 30:
        sample_failures.append("independent_weeks<30")
    if sample_failures:
        return "INSUFFICIENT_DEVELOPMENT", ",".join(sample_failures)

    economic_failures = []
    if metrics.profit_pct <= 0 or metrics.profit_pct < baseline.profit_pct + 3:
        economic_failures.append("profit_increment")
    if metrics.profit_factor < max(1.35, baseline.profit_factor + 0.10):
        economic_failures.append("profit_factor")
    if metrics.payoff is None or metrics.payoff < 2.0:
        economic_failures.append("payoff")
    if (
        metrics.breakeven_winrate is None
        or metrics.winrate < metrics.breakeven_winrate + 0.05
    ):
        economic_failures.append("winrate_vs_breakeven")
    if metrics.expectancy <= 0:
        economic_failures.append("expectancy")
    if metrics.drawdown_pct >= 15 or metrics.drawdown_pct > baseline.drawdown_pct + 2:
        economic_failures.append("drawdown")
    if metrics.profitable_folds < 3 or metrics.worst_fold_profit_pct <= -10:
        economic_failures.append("fold_stability")
    if metrics.top3_gross_profit_share > 0.65:
        economic_failures.append("top3_concentration")
    if metrics.best_month_positive_share > 0.60:
        economic_failures.append("month_concentration")
    if economic_failures:
        return "REJECTED_DEVELOPMENT", ",".join(economic_failures)
    return "DEVELOPMENT_POINT_SURVIVOR", "all frozen development gates passed"


def _challenge_gate(
    metrics: Metrics,
    baseline: Metrics,
    *,
    development_survivor: bool,
) -> tuple[str, str]:
    failures = []
    if metrics.profit_pct <= 0 or metrics.profit_pct < baseline.profit_pct:
        failures.append("profit")
    if metrics.profit_factor < max(1.25, baseline.profit_factor):
        failures.append("profit_factor")
    if metrics.payoff is None or metrics.payoff < 1.8:
        failures.append("payoff")
    if (
        metrics.breakeven_winrate is None
        or metrics.winrate < metrics.breakeven_winrate + 0.02
    ):
        failures.append("winrate_vs_breakeven")
    if metrics.drawdown_pct >= 15:
        failures.append("drawdown")
    if metrics.profitable_folds < 3:
        failures.append("quarter_stability")
    if any(metrics.pair_profit_sum_pct.get(asset, 0) <= 0 for asset in ("BTC", "ETH")):
        failures.append("asset_profit")
    if not development_survivor:
        outcome = "pass" if not failures else "fail:" + ",".join(failures)
        return "DIAGNOSTIC_CHALLENGE_ONLY", outcome
    if failures:
        return "REJECTED_TEMPORAL_CHALLENGE", ",".join(failures)
    return (
        "TEMPORAL_CHALLENGE_POINT_SURVIVOR",
        "all frozen temporal challenge point gates passed",
    )


def _formal_rank(metrics: Metrics) -> tuple[float, float, float, float, float, str]:
    return (
        -metrics.worst_fold_profit_pct,
        -metrics.min_asset_profit_factor,
        -metrics.profit_factor,
        -metrics.profit_pct,
        metrics.drawdown_pct,
        metrics.code,
    )


def _diagnostic_rank(metrics: Metrics) -> tuple[int, float, float, float, float, str]:
    return (
        -metrics.profitable_folds,
        -metrics.worst_fold_profit_pct,
        -metrics.profit_factor,
        -metrics.profit_pct,
        metrics.drawdown_pct,
        metrics.code,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and (pd.isna(value) or value in {float("inf"), -float("inf")}):
        return None if pd.isna(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _write_rows(path: Path, rows: list[Metrics]) -> None:
    data = [_json_safe(asdict(row)) for row in rows]
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    csv_rows = []
    for row in data:
        csv_rows.append(
            {
                key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list))
                else value
                for key, value in row.items()
            }
        )
    with path.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)


def _run_development_candidates(*, resume: bool, workers: int) -> list[Metrics]:
    jobs = [
        (_strategy_name(candidate_id), f"C{candidate_id:02d}")
        for candidate_id in range(1, 21)
    ]
    rows: list[Metrics] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _run_backtest,
                strategy,
                code,
                "development",
                DEVELOPMENT_WINDOW,
                DEVELOPMENT_FOLDS,
                resume=resume,
            ): code
            for strategy, code in jobs
        }
        for future in as_completed(futures):
            metrics = future.result()
            rows.append(metrics)
            print(
                f"{metrics.code}: {metrics.status} n={metrics.trades} "
                f"return={metrics.profit_pct:.2f}% PF={metrics.profit_factor:.2f}",
                flush=True,
            )
    return sorted(rows, key=lambda item: item.code)


def _render_report(
    development: list[Metrics],
    challenge: list[Metrics],
    selected: list[dict[str, str]],
    determinism: dict[str, Any],
) -> str:
    lines = [
        "# PriceFlow Capital Intent 20-Round Results",
        "",
        "本报告由冻结 runner 生成。时间挑战窗不是严格 untouched holdout；任何通过者仍不能解释为可实盘策略。",
        "",
        "## Development",
        "",
        "| code | status | n | return | win | payoff | PF | DD | folds+ | worst fold | BTC/ETH | long/short | reason |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in development:
        payoff = "n/a" if row.payoff is None else f"{row.payoff:.2f}"
        lines.append(
            f"| {row.code} | {row.status} | {row.trades} | {row.profit_pct:+.2f}% | "
            f"{row.winrate:.2%} | {payoff} | {row.profit_factor:.2f} | "
            f"{row.drawdown_pct:.2f}% | {row.profitable_folds}/4 | "
            f"{row.worst_fold_profit_pct:+.2f}% | {row.btc_trades}/{row.eth_trades} | "
            f"{row.long_trades}/{row.short_trades} | {row.reason} |"
        )
    lines.extend(
        [
            "",
            "## Frozen challenge selection",
            "",
        ]
    )
    if selected:
        for item in selected:
            lines.append(f"- {item['code']}: {item['selection_status']}")
    else:
        lines.append("- No candidate met even the diagnostic sample floor.")
    lines.extend(
        [
            "",
            "## Temporal challenge",
            "",
            "| code | status | n | return | win | payoff | PF | DD | quarters+ | BTC PnL | ETH PnL | reason |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in challenge:
        payoff = "n/a" if row.payoff is None else f"{row.payoff:.2f}"
        lines.append(
            f"| {row.code} | {row.status} | {row.trades} | {row.profit_pct:+.2f}% | "
            f"{row.winrate:.2%} | {payoff} | {row.profit_factor:.2f} | "
            f"{row.drawdown_pct:.2f}% | {row.profitable_folds}/4 | "
            f"{row.pair_profit_sum_pct.get('BTC', 0):+.2f}% | "
            f"{row.pair_profit_sum_pct.get('ETH', 0):+.2f}% | {row.reason} |"
        )
    lines.extend(
        [
            "",
            "## Determinism",
            "",
            f"```json\n{json.dumps(determinism, indent=2, ensure_ascii=False)}\n```",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    preregistration_hash = _sha256(PREREGISTRATION)
    if preregistration_hash != EXPECTED_PREREGISTRATION_SHA256:
        raise RuntimeError(
            f"Preregistration changed: {preregistration_hash} != "
            f"{EXPECTED_PREREGISTRATION_SHA256}"
        )
    manifest = DATA_ROOT / "cross-venue" / "manifest.json"
    receipt = {
        "preregistration_sha256": preregistration_hash,
        "config_sha256": _sha256(CONFIG),
        "strategy_sha256": _sha256(STRATEGY_SOURCE),
        "strategy_dependency_sha256": {
            str(path.relative_to(REPO_ROOT)): _sha256(path)
            for path in STRATEGY_DEPENDENCIES
        },
        "runner_sha256": _sha256(Path(__file__)),
        "data_manifest_sha256": _sha256(manifest),
        "development_window": DEVELOPMENT_WINDOW,
        "challenge_window": CHALLENGE_WINDOW,
        "fee": 0.0005,
        "cache": "none",
        "workers": args.workers,
    }
    (RESULT_ROOT / "freeze-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"
    )

    baseline_development = _run_backtest(
        "PriceFlowCapitalIntentControl",
        "C00",
        "development",
        DEVELOPMENT_WINDOW,
        DEVELOPMENT_FOLDS,
        resume=args.resume,
    )
    if baseline_development.status != "MEASURED":
        raise RuntimeError(f"Development baseline failed: {baseline_development.reason}")
    candidate_rows = _run_development_candidates(
        resume=args.resume, workers=args.workers
    )
    for row in candidate_rows:
        if row.status == "MEASURED":
            row.status, row.reason = _development_gate(row, baseline_development)
    development_rows = [baseline_development, *candidate_rows]
    _write_rows(RESULT_ROOT / "development-results.json", development_rows)

    formal = sorted(
        [row for row in candidate_rows if row.status == "DEVELOPMENT_POINT_SURVIVOR"],
        key=_formal_rank,
    )[:3]
    selected_rows = list(formal)
    selection_status = {row.code: "DEVELOPMENT_POINT_SURVIVOR" for row in formal}
    if len(selected_rows) < 3:
        diagnostics = sorted(
            [
                row
                for row in candidate_rows
                if row not in selected_rows
                and row.trades >= 40
                and row.wins >= 10
                and row.losses >= 10
            ],
            key=_diagnostic_rank,
        )
        for row in diagnostics:
            if len(selected_rows) >= 3:
                break
            selected_rows.append(row)
            selection_status[row.code] = "DIAGNOSTIC_ONLY"
    selected = [
        {"code": row.code, "selection_status": selection_status[row.code]}
        for row in selected_rows
    ]

    baseline_challenge = _run_backtest(
        "PriceFlowCapitalIntentControl",
        "C00",
        "challenge",
        CHALLENGE_WINDOW,
        CHALLENGE_FOLDS,
        resume=args.resume,
    )
    if baseline_challenge.status != "MEASURED":
        raise RuntimeError(f"Challenge baseline failed: {baseline_challenge.reason}")
    challenge_rows = [baseline_challenge]
    for development_row in selected_rows:
        measured = _run_backtest(
            development_row.strategy,
            development_row.code,
            "challenge",
            CHALLENGE_WINDOW,
            CHALLENGE_FOLDS,
            resume=args.resume,
        )
        if measured.status == "MEASURED":
            measured.status, measured.reason = _challenge_gate(
                measured,
                baseline_challenge,
                development_survivor=(
                    development_row.status == "DEVELOPMENT_POINT_SURVIVOR"
                ),
            )
        challenge_rows.append(measured)
    _write_rows(RESULT_ROOT / "challenge-results.json", challenge_rows)

    determinism: dict[str, Any] = {"performed": False}
    if selected_rows:
        first = selected_rows[0]
        rerun = _run_backtest(
            first.strategy,
            f"{first.code}-RERUN",
            "determinism",
            DEVELOPMENT_WINDOW,
            DEVELOPMENT_FOLDS,
            resume=args.resume,
        )
        determinism = {
            "performed": True,
            "strategy": first.strategy,
            "original_fingerprint": first.trade_fingerprint,
            "rerun_fingerprint": rerun.trade_fingerprint,
            "identical": first.trade_fingerprint == rerun.trade_fingerprint,
            "rerun_status": rerun.status,
            "rerun_artifact": rerun.artifact,
        }
        (RESULT_ROOT / "determinism.json").write_text(
            json.dumps(determinism, indent=2, sort_keys=True), encoding="utf-8"
        )

    summary = {
        "family_size": 20,
        "development_point_survivors": [row.code for row in formal],
        "challenge_selection": selected,
        "temporal_challenge_point_survivors": [
            row.code
            for row in challenge_rows
            if row.status == "TEMPORAL_CHALLENGE_POINT_SURVIVOR"
        ],
        "highest_possible_status": "REQUIRES_NEW_FORWARD_OR_PAPER_VALIDATION",
        "determinism": determinism,
    }
    (RESULT_ROOT / "funnel-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (RESULT_ROOT / "REPORT.md").write_text(
        _render_report(development_rows, challenge_rows, selected, determinism),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
