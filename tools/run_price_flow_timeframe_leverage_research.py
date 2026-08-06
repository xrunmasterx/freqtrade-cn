
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
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
    / "price-flow-timeframe-leverage-research"
)
CONFIG = RESULT_ROOT / "research-config.json"
PREREGISTRATION = RESULT_ROOT / "PREREGISTRATION.md"
EXPECTED_PREREGISTRATION_SHA256 = (
    "24eff678a002a946379d7e3b001ef852f1137950f57ffed43614b709c21548f8"
)
USER_DATA = REPO_ROOT / "ft_userdata" / "user_data"
DATA_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data-price-flow-timeframe-leverage"
)
PAIRS = ("BTC/USDT:USDT", "ETH/USDT:USDT")
TIMEFRAMES = ("5m", "15m", "30m", "1h")
LEVERAGES = (1, 2, 3, 5, 10)

DEVELOPMENT_WINDOW = ("20240701", "20250801")
CHALLENGE_WINDOW = ("20250801", "20260801")
FULL_WINDOW = ("20240701", "20260801")
DEVELOPMENT_FOLDS = {
    "D1": ("2024-07-01T00:00:00Z", "2024-11-01T00:00:00Z"),
    "D2": ("2024-11-01T00:00:00Z", "2025-02-01T00:00:00Z"),
    "D3": ("2025-02-01T00:00:00Z", "2025-05-01T00:00:00Z"),
    "D4": ("2025-05-01T00:00:00Z", "2025-08-01T00:00:00Z"),
}
CHALLENGE_FOLDS = {
    "Q1": ("2025-08-01T00:00:00Z", "2025-11-01T00:00:00Z"),
    "Q2": ("2025-11-01T00:00:00Z", "2026-02-01T00:00:00Z"),
    "Q3": ("2026-02-01T00:00:00Z", "2026-05-01T00:00:00Z"),
    "Q4": ("2026-05-01T00:00:00Z", "2026-08-01T00:00:00Z"),
}
FULL_FOLDS = {
    "Y1": ("2024-07-01T00:00:00Z", "2025-07-01T00:00:00Z"),
    "Y2": ("2025-07-01T00:00:00Z", "2026-08-01T00:00:00Z"),
}


@dataclass(frozen=True)
class StrategySpec:
    code: str
    strategy: str
    timeframe: str
    leverage: int
    risk_model: str
    confirmation: str


@dataclass
class Metrics:
    code: str
    strategy: str
    stage: str
    timeframe: str
    leverage: int
    risk_model: str
    confirmation: str = "original"
    status: str = "MEASURED"
    reason: str = ""
    fee: float = 0.0005
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
    liquidations: int = 0
    btc_trades: int = 0
    eth_trades: int = 0
    long_trades: int = 0
    short_trades: int = 0
    independent_weeks: int = 0
    profitable_folds: int = 0
    worst_fold_profit_pct: float = 0.0
    min_asset_profit_factor: float = 0.0
    btc_profit_sum_pct: float = 0.0
    eth_profit_sum_pct: float = 0.0
    btc_profit_factor: float | None = None
    eth_profit_factor: float | None = None
    top3_gross_profit_share: float = 0.0
    best_month_positive_share: float = 0.0
    profitable_months: int = 0
    losing_months: int = 0
    folds: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    months: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    entry_tag_counts: dict[str, int] = field(default_factory=dict)
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    trade_fingerprint: str | None = None
    artifact_sha256: str | None = None
    artifact: str | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen E10 timeframe/leverage research protocol."
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


def _baseline_specs() -> list[StrategySpec]:
    return [
        StrategySpec(
            code=f"T{timeframe}-L{leverage}",
            strategy=f"PriceFlowE10Tf{timeframe}Lev{leverage}Strategy",
            timeframe=timeframe,
            leverage=leverage,
            risk_model="fixed_account",
            confirmation="original",
        )
        for timeframe in TIMEFRAMES
        for leverage in LEVERAGES
    ]


def _confirmation_specs(base: StrategySpec) -> list[StrategySpec]:
    prefix = f"PriceFlowE10Tf{base.timeframe}Lev{base.leverage}"
    return [
        StrategySpec(
            code=f"{base.code}-M1",
            strategy=f"{prefix}SignedFreshStrategy",
            timeframe=base.timeframe,
            leverage=base.leverage,
            risk_model="fixed_account",
            confirmation="signed_fresh",
        ),
        StrategySpec(
            code=f"{base.code}-M2",
            strategy=f"{prefix}SignedFreshOiStrategy",
            timeframe=base.timeframe,
            leverage=base.leverage,
            risk_model="fixed_account",
            confirmation="signed_fresh_oi",
        ),
    ]


def _price_geometry_specs(timeframe: str) -> list[StrategySpec]:
    return [
        StrategySpec(
            code=f"T{timeframe}-L{leverage}-PG",
            strategy=f"PriceFlowE10Tf{timeframe}Lev{leverage}PriceGeometryStrategy",
            timeframe=timeframe,
            leverage=leverage,
            risk_model="price_geometry",
            confirmation="original",
        )
        for leverage in LEVERAGES
    ]


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
    trades: list[dict[str, Any]], timerange: tuple[str, str]
) -> dict[str, dict[str, float | int | None]]:
    start_month = pd.Timestamp(timerange[0]).to_period("M")
    end_month = (pd.Timestamp(timerange[1]) - pd.Timedelta(seconds=1)).to_period("M")
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
    spec: StrategySpec,
    stage: str,
    timerange: tuple[str, str],
    fold_boundaries: dict[str, tuple[str, str]],
    result: dict[str, Any],
    archive: Path,
    fee: float,
) -> Metrics:
    trades = result["trades"]
    profits = [float(trade["profit_ratio"]) for trade in trades]
    winners = [value for value in profits if value > 0]
    draws = [value for value in profits if value == 0]
    losers = [value for value in profits if value < 0]
    payoff = None
    if winners and losers:
        payoff = statistics.mean(winners) / abs(statistics.mean(losers))
    folds = _period_metrics(trades, fold_boundaries)
    fold_profits = [float(item["profit_sum_pct"] or 0) for item in folds.values()]
    months = _monthly_metrics(trades, timerange)
    month_profits = [float(item["profit_sum_pct"] or 0) for item in months.values()]

    pair_values: dict[str, list[float]] = {"BTC": [], "ETH": []}
    for trade, value in zip(trades, profits, strict=True):
        asset = str(trade["pair"]).split("/", maxsplit=1)[0]
        if asset in pair_values:
            pair_values[asset].append(value)
    pair_pf = {asset: _profit_factor(values) for asset, values in pair_values.items()}
    finite_pair_pf = [0.0 if value is None else float(value) for value in pair_pf.values()]
    positive_month_total = sum(value for value in month_profits if value > 0)
    gross_profit = sum(winners)
    total = next(row for row in result["results_per_pair"] if row["key"] == "TOTAL")
    try:
        artifact = str(archive.relative_to(REPO_ROOT))
    except ValueError:
        artifact = str(archive)
    pairs = [str(trade["pair"]) for trade in trades]
    shorts = [bool(trade["is_short"]) for trade in trades]
    exit_reasons = [str(trade.get("exit_reason") or "") for trade in trades]
    return Metrics(
        code=spec.code,
        strategy=spec.strategy,
        stage=stage,
        timeframe=spec.timeframe,
        leverage=spec.leverage,
        risk_model=spec.risk_model,
        confirmation=spec.confirmation,
        fee=fee,
        trades=len(trades),
        wins=len(winners),
        draws=len(draws),
        losses=len(losers),
        winrate=len(winners) / len(trades) if trades else 0.0,
        payoff=payoff,
        profit_factor=float(total["profit_factor"]),
        expectancy=float(total.get("expectancy") or 0),
        profit_pct=float(total["profit_total_pct"]),
        profit_usdt=float(total["profit_total_abs"]),
        starting_balance=float(result["starting_balance"]),
        final_balance=float(result["final_balance"]),
        drawdown_pct=float(result["max_drawdown_account"]) * 100,
        funding_fees_usdt=sum(float(trade.get("funding_fees") or 0) for trade in trades),
        liquidations=sum("liquidation" in reason.lower() for reason in exit_reasons),
        btc_trades=sum(pair.startswith("BTC/") for pair in pairs),
        eth_trades=sum(pair.startswith("ETH/") for pair in pairs),
        long_trades=sum(not is_short for is_short in shorts),
        short_trades=sum(shorts),
        independent_weeks=len(
            {
                pd.Timestamp(str(trade["close_date"])).to_period("W").start_time
                for trade in trades
                if trade.get("close_date")
            }
        ),
        profitable_folds=sum(value > 0 for value in fold_profits),
        worst_fold_profit_pct=min(fold_profits, default=0.0),
        min_asset_profit_factor=min(finite_pair_pf, default=0.0),
        btc_profit_sum_pct=round(sum(pair_values["BTC"]) * 100, 10),
        eth_profit_sum_pct=round(sum(pair_values["ETH"]) * 100, 10),
        btc_profit_factor=pair_pf["BTC"],
        eth_profit_factor=pair_pf["ETH"],
        top3_gross_profit_share=(
            sum(sorted(winners, reverse=True)[:3]) / gross_profit if gross_profit else 0.0
        ),
        best_month_positive_share=(
            max(month_profits, default=0.0) / positive_month_total
            if positive_month_total > 0
            else 0.0
        ),
        profitable_months=sum(value > 0 for value in month_profits),
        losing_months=sum(value < 0 for value in month_profits),
        folds=folds,
        months=months,
        entry_tag_counts=dict(Counter(str(trade.get("enter_tag") or "") for trade in trades)),
        exit_reason_counts=dict(Counter(exit_reasons)),
        trade_fingerprint=_trade_fingerprint(trades),
        artifact_sha256=_sha256(archive),
        artifact=artifact,
    )


def _run_backtest(
    spec: StrategySpec,
    stage: str,
    timerange: tuple[str, str],
    fold_boundaries: dict[str, tuple[str, str]],
    *,
    fee: float,
    resume: bool,
    timeframe_detail: str | None = None,
) -> Metrics:
    directory_name = spec.code.lower().replace("/", "-")
    directory = RESULT_ROOT / stage / directory_name
    if fee != 0.0005:
        directory = directory / f"fee-{fee:.4f}".replace(".", "p")
    if timeframe_detail:
        directory = directory / f"detail-{timeframe_detail}"
    directory.mkdir(parents=True, exist_ok=True)
    archive = _result_zip(directory) if resume else None
    if archive is None:
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
            spec.strategy,
            "--pairs",
            *PAIRS,
            "--timerange",
            f"{timerange[0]}-{timerange[1]}",
            "--fee",
            str(fee),
            "--enable-protections",
            "--cache",
            "none",
            "--backtest-directory",
            str(directory),
            "--export",
            "trades",
        ]
        if timeframe_detail:
            command.extend(["--timeframe-detail", timeframe_detail])
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
                code=spec.code,
                strategy=spec.strategy,
                stage=stage,
                timeframe=spec.timeframe,
                leverage=spec.leverage,
                risk_model=spec.risk_model,
                confirmation=spec.confirmation,
                status="INVALID_IMPLEMENTATION",
                reason=f"Freqtrade exited {completed.returncode}",
                fee=fee,
            )
        archive = _result_zip(directory)
    if archive is None:
        return Metrics(
            code=spec.code,
            strategy=spec.strategy,
            stage=stage,
            timeframe=spec.timeframe,
            leverage=spec.leverage,
            risk_model=spec.risk_model,
            confirmation=spec.confirmation,
            status="INVALID_IMPLEMENTATION",
            reason="Freqtrade did not produce a result ZIP",
            fee=fee,
        )
    try:
        return _summarize(
            spec,
            stage,
            timerange,
            fold_boundaries,
            _read_result(archive, spec.strategy),
            archive,
            fee,
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
            code=spec.code,
            strategy=spec.strategy,
            stage=stage,
            timeframe=spec.timeframe,
            leverage=spec.leverage,
            risk_model=spec.risk_model,
            confirmation=spec.confirmation,
            status="INVALID_IMPLEMENTATION",
            reason=f"result parse failed: {exc}",
            fee=fee,
        )


def _sample_gate(metrics: Metrics) -> tuple[bool, str]:
    checks = (
        (metrics.trades >= 20, "trades<20"),
        (metrics.wins >= 7, "wins<7"),
        (metrics.losses >= 7, "losses<7"),
        (metrics.btc_trades >= 5, "BTC<5"),
        (metrics.eth_trades >= 5, "ETH<5"),
        (metrics.long_trades >= 8, "long<8"),
        (metrics.short_trades >= 4, "short<4"),
        (metrics.independent_weeks >= 10, "weeks<10"),
    )
    failures = [label for passed, label in checks if not passed]
    return not failures, ", ".join(failures)


def _development_gate(metrics: Metrics) -> tuple[str, str]:
    if metrics.status == "INVALID_IMPLEMENTATION":
        return metrics.status, metrics.reason
    sample_ok, reason = _sample_gate(metrics)
    if not sample_ok:
        return "REJECTED_SAMPLE", reason
    failures = []
    checks = (
        (metrics.profit_pct > 0, "profit<=0"),
        (metrics.profit_factor >= 1.50, "PF<1.50"),
        (metrics.winrate >= 0.40, "winrate<40%"),
        ((metrics.payoff or 0.0) >= 2.00, "payoff<2.00"),
        (metrics.drawdown_pct < 20.0, "drawdown>=20%"),
        (metrics.profitable_folds >= 3, "profitable folds<3"),
        (metrics.worst_fold_profit_pct > -10.0, "worst fold<=-10%"),
        (metrics.btc_profit_sum_pct > 0, "BTC profit<=0"),
        (metrics.eth_profit_sum_pct > 0, "ETH profit<=0"),
        ((metrics.btc_profit_factor or 0.0) > 1.0, "BTC PF<=1"),
        ((metrics.eth_profit_factor or 0.0) > 1.0, "ETH PF<=1"),
        (metrics.top3_gross_profit_share < 0.55, "top3 share>=55%"),
        (metrics.best_month_positive_share < 0.45, "best month share>=45%"),
        (metrics.liquidations == 0, "liquidation>0"),
    )
    failures.extend(label for passed, label in checks if not passed)
    if failures:
        return "REJECTED_QUALITY", ", ".join(failures)
    return "DEVELOPMENT_SURVIVOR", "all frozen development gates passed"


def _challenge_gate(metrics: Metrics) -> tuple[str, str]:
    if metrics.status == "INVALID_IMPLEMENTATION":
        return metrics.status, metrics.reason
    checks = (
        (metrics.trades >= 12, "trades<12"),
        (metrics.btc_trades >= 3, "BTC<3"),
        (metrics.eth_trades >= 3, "ETH<3"),
        (metrics.profit_pct > 0, "profit<=0"),
        (metrics.profit_factor >= 1.30, "PF<1.30"),
        (metrics.winrate >= 0.35, "winrate<35%"),
        ((metrics.payoff or 0.0) >= 1.80, "payoff<1.80"),
        (metrics.drawdown_pct < 20.0, "drawdown>=20%"),
        (metrics.profitable_folds >= 3, "profitable quarters<3"),
        (metrics.btc_profit_sum_pct > 0, "BTC profit<=0"),
        (metrics.eth_profit_sum_pct > 0, "ETH profit<=0"),
        (metrics.liquidations == 0, "liquidation>0"),
    )
    failures = [label for passed, label in checks if not passed]
    if failures:
        return "REJECTED_CHALLENGE", ", ".join(failures)
    return "TEMPORAL_CHALLENGE_SURVIVOR", "all frozen challenge gates passed"


def _score(metrics: Metrics) -> tuple[float, ...]:
    return (
        metrics.worst_fold_profit_pct,
        metrics.min_asset_profit_factor,
        metrics.profit_factor,
        metrics.winrate,
        metrics.payoff or 0.0,
        metrics.profit_pct,
        -metrics.drawdown_pct,
    )


def _timeframe_representatives(metrics: list[Metrics]) -> list[Metrics]:
    representatives: dict[str, Metrics] = {}
    for item in metrics:
        sample_ok, _ = _sample_gate(item)
        if item.status == "INVALID_IMPLEMENTATION" or not sample_ok:
            continue
        current = representatives.get(item.timeframe)
        if current is None or _score(item) > _score(current):
            representatives[item.timeframe] = item
    return list(representatives.values())


def _run_parallel(
    specs: list[StrategySpec],
    stage: str,
    timerange: tuple[str, str],
    folds: dict[str, tuple[str, str]],
    *,
    fee: float,
    resume: bool,
    workers: int,
) -> list[Metrics]:
    results: list[Metrics] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _run_backtest,
                spec,
                stage,
                timerange,
                folds,
                fee=fee,
                resume=resume,
            ): spec
            for spec in specs
        }
        for future in as_completed(futures):
            results.append(future.result())
    order = {spec.code: position for position, spec in enumerate(specs)}
    return sorted(results, key=lambda item: order[item.code])


def _metric_spec(metrics: Metrics) -> StrategySpec:
    return StrategySpec(
        code=metrics.code,
        strategy=metrics.strategy,
        timeframe=metrics.timeframe,
        leverage=metrics.leverage,
        risk_model=metrics.risk_model,
        confirmation=metrics.confirmation,
    )


def _write_csv(path: Path, metrics: list[Metrics]) -> None:
    fields = [
        "stage",
        "code",
        "strategy",
        "timeframe",
        "leverage",
        "risk_model",
        "confirmation",
        "status",
        "reason",
        "trades",
        "profit_pct",
        "winrate",
        "payoff",
        "profit_factor",
        "drawdown_pct",
        "btc_profit_sum_pct",
        "eth_profit_sum_pct",
        "profitable_folds",
        "worst_fold_profit_pct",
        "trade_fingerprint",
        "artifact",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in metrics:
            values = asdict(item)
            writer.writerow({field: values[field] for field in fields})


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.workers < 1:
        raise ValueError("--workers must be positive")
    if _sha256(PREREGISTRATION) != EXPECTED_PREREGISTRATION_SHA256:
        raise RuntimeError("Preregistration hash changed; refusing to run")

    frozen = StrategySpec(
        code="FROZEN-E10",
        strategy="PriceFlowParticipationFreshnessStrategy",
        timeframe="15m",
        leverage=2,
        risk_model="frozen_control",
        confirmation="original",
    )
    duplicate = next(
        spec
        for spec in _baseline_specs()
        if spec.timeframe == "15m" and spec.leverage == 2
    )
    parity = _run_parallel(
        [frozen, duplicate],
        "parity-full",
        FULL_WINDOW,
        FULL_FOLDS,
        fee=0.0005,
        resume=args.resume,
        workers=min(args.workers, 2),
    )
    parity_ok = (
        all(item.status == "MEASURED" for item in parity)
        and parity[0].trade_fingerprint == parity[1].trade_fingerprint
    )
    if not parity_ok:
        payload = {"parity_ok": False, "parity": [asdict(item) for item in parity]}
        (RESULT_ROOT / "results.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise RuntimeError("15m/2x duplicate did not reproduce frozen E10")

    baseline_specs = _baseline_specs()
    development = _run_parallel(
        baseline_specs,
        "development",
        DEVELOPMENT_WINDOW,
        DEVELOPMENT_FOLDS,
        fee=0.0005,
        resume=args.resume,
        workers=args.workers,
    )
    for item in development:
        item.status, item.reason = _development_gate(item)

    representatives = _timeframe_representatives(development)
    ranked_representatives = sorted(representatives, key=_score, reverse=True)
    tuning_bases = ranked_representatives[:2]
    confirmation_specs = [
        spec
        for base in tuning_bases
        for spec in _confirmation_specs(_metric_spec(base))
    ]
    confirmation = _run_parallel(
        confirmation_specs,
        "development-confirmation",
        DEVELOPMENT_WINDOW,
        DEVELOPMENT_FOLDS,
        fee=0.0005,
        resume=args.resume,
        workers=args.workers,
    )
    for item in confirmation:
        item.status, item.reason = _development_gate(item)

    geometry_specs = (
        _price_geometry_specs(ranked_representatives[0].timeframe)
        if ranked_representatives
        else []
    )
    geometry = _run_parallel(
        geometry_specs,
        "development-price-geometry",
        DEVELOPMENT_WINDOW,
        DEVELOPMENT_FOLDS,
        fee=0.0005,
        resume=args.resume,
        workers=args.workers,
    )
    for item in geometry:
        item.status, item.reason = _development_gate(item)

    development_pool = [*development, *confirmation, *geometry]
    survivors = [
        item for item in development_pool if item.status == "DEVELOPMENT_SURVIVOR"
    ]
    challenge_seeds = sorted(survivors, key=_score, reverse=True)[:3]
    if len(challenge_seeds) < 3:
        diagnostics = []
        for item in development_pool:
            sample_ok, _ = _sample_gate(item)
            if sample_ok and item not in challenge_seeds:
                diagnostics.append(item)
        for item in sorted(diagnostics, key=_score, reverse=True)[: 3 - len(challenge_seeds)]:
            item.status = "DIAGNOSTIC_ONLY"
            item.reason = "filled challenge slot after frozen development rejection"
            challenge_seeds.append(item)

    challenge_specs = [_metric_spec(item) for item in challenge_seeds]
    challenge = _run_parallel(
        challenge_specs,
        "challenge",
        CHALLENGE_WINDOW,
        CHALLENGE_FOLDS,
        fee=0.0005,
        resume=args.resume,
        workers=args.workers,
    )
    for item in challenge:
        item.status, item.reason = _challenge_gate(item)

    full = _run_parallel(
        challenge_specs,
        "full",
        FULL_WINDOW,
        FULL_FOLDS,
        fee=0.0005,
        resume=args.resume,
        workers=args.workers,
    )
    all_metrics = [*parity, *development, *confirmation, *geometry, *challenge, *full]
    payload = {
        "protocol": {
            "preregistration_sha256": EXPECTED_PREREGISTRATION_SHA256,
            "parity_ok": parity_ok,
            "attempts": {
                "baseline": len(development),
                "confirmation": len(confirmation),
                "price_geometry": len(geometry),
                "challenge": len(challenge),
            },
            "tuning_bases": [item.code for item in tuning_bases],
            "geometry_timeframe": (
                ranked_representatives[0].timeframe if ranked_representatives else None
            ),
            "challenge_seeds": [item.code for item in challenge_seeds],
        },
        "metrics": [asdict(item) for item in all_metrics],
    }
    (RESULT_ROOT / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(RESULT_ROOT / "results.csv", all_metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
