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
    / "price-flow-five-strategy-deep-comparison"
)
SOURCE_CONFIG = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "price-flow-cross-venue-50-rounds"
    / "research-config.json"
)
CONFIG = RESULT_ROOT / "backtest-config.json"
PAIRS = {
    "BTC": "BTC/USDT:USDT",
    "ETH": "ETH/USDT:USDT",
}


@dataclass(frozen=True)
class StrategySpec:
    name: str
    code: str
    source_file: str


@dataclass(frozen=True)
class Window:
    label: str
    start: str
    end: str


STRATEGIES = (
    StrategySpec(
        "PriceFlowTakerCUSUMStrategy",
        "taker_cusum",
        "PriceFlowTakerCUSUMStrategy.py",
    ),
    StrategySpec(
        "PriceFlowCrossVenueControl",
        "cross_venue_control",
        "PriceFlowCrossVenueResearchStrategy.py",
    ),
    StrategySpec(
        "PriceFlowContinuationStrategy",
        "continuation",
        "PriceFlowContinuationStrategy.py",
    ),
    StrategySpec(
        "PriceFlowCPIAbsorptionStrategy",
        "cpi_absorption",
        "PriceFlowCPIAbsorptionStrategy.py",
    ),
    StrategySpec(
        "PriceFlowShortDteOptionPressureStrategy",
        "short_dte_option_pressure",
        "PriceFlowShortDteOptionPressureStrategy.py",
    ),
)
WINDOWS = (
    Window("7d", "20260725", "20260801"),
    Window("15d", "20260717", "20260801"),
    Window("1m", "20260701", "20260801"),
    Window("2m", "20260601", "20260801"),
    Window("4m", "20260401", "20260801"),
    Window("6m", "20260201", "20260801"),
    Window("1y", "20250801", "20260801"),
    Window("2y", "20240801", "20260801"),
    Window("3y", "20230801", "20260801"),
    Window("4y", "20220801", "20260801"),
    Window("5y", "20210801", "20260801"),
)


@dataclass
class Metric:
    strategy: str
    strategy_code: str
    source_file: str
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
    profit_factor: float | None = None
    payoff: float | None = None
    max_drawdown_pct: float = 0.0
    long_trades: int = 0
    short_trades: int = 0
    extra_trades: int = 0
    cross_valid_pct: float = 0.0
    artifact: str | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the fixed BTC/ETH PriceFlow strategy comparison matrix."
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


def _write_config() -> None:
    config = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    config["bot_name"] = "price-flow-five-strategy-deep-comparison"
    config["cross_venue_sidecar_dir"] = (
        "../ft_userdata/runtime/freqtrade-futures/"
        "data-price-flow-deep-5y/cross-venue"
    )
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


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


def _read_result(archive: Path, strategy: str) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as bundle:
        result_name = next(
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        )
        payload = json.loads(bundle.read(result_name))
    return payload["strategy"][strategy]


def _backtest_command(
    strategy: StrategySpec, asset: str, window: Window, directory: Path
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
        strategy.name,
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


def _summarize(
    strategy: StrategySpec,
    asset: str,
    window: Window,
    result: dict[str, Any],
    archive: Path,
    *,
    cross_valid_pct: float,
) -> Metric:
    trades = result["trades"]
    profits = [float(trade["profit_ratio"]) for trade in trades]
    winners = [profit for profit in profits if profit > 0]
    draws = [profit for profit in profits if profit == 0]
    losers = [profit for profit in profits if profit < 0]
    payoff = None
    if winners and losers:
        payoff = (sum(winners) / len(winners)) / abs(sum(losers) / len(losers))
    total = next(item for item in result["results_per_pair"] if item["key"] == "TOTAL")
    tags = [str(trade.get("enter_tag") or "") for trade in trades]
    shorts = [bool(trade["is_short"]) for trade in trades]
    return Metric(
        strategy=strategy.name,
        strategy_code=strategy.code,
        source_file=strategy.source_file,
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
        profit_factor=float(total["profit_factor"]) if losers else None,
        payoff=payoff,
        max_drawdown_pct=float(result["max_drawdown_account"]) * 100,
        long_trades=sum(not is_short for is_short in shorts),
        short_trades=sum(shorts),
        extra_trades=sum("_extra_" in tag for tag in tags),
        cross_valid_pct=cross_valid_pct,
        artifact=_display_path(archive),
    )


def _failed_metric(
    strategy: StrategySpec,
    asset: str,
    window: Window,
    status: str,
    reason: str,
    cross_valid_pct: float,
) -> Metric:
    return Metric(
        strategy=strategy.name,
        strategy_code=strategy.code,
        source_file=strategy.source_file,
        asset=asset,
        pair=PAIRS[asset],
        window=window.label,
        start=window.start,
        end=window.end,
        status=status,
        reason=reason,
        cross_valid_pct=cross_valid_pct,
    )


def _sidecar_coverage(asset: str, window: Window) -> float:
    path = DATA_ROOT / "cross-venue" / f"{asset}_USDT_USDT-15m-cross-venue.feather"
    frame = pd.read_feather(path, columns=["date", "cross_data_valid"])
    dates = pd.to_datetime(frame["date"], utc=True)
    start = pd.Timestamp(window.start, tz="UTC")
    end = pd.Timestamp(window.end, tz="UTC")
    selected = frame.loc[(dates >= start) & (dates < end)]
    expected_rows = int((end - start) / pd.Timedelta(minutes=15))
    if len(selected) != expected_rows:
        raise ValueError(
            f"{asset} {window.label} sidecar rows {len(selected)} != {expected_rows}"
        )
    return float(selected["cross_data_valid"].fillna(False).mean() * 100)


def _run_backtest(
    strategy: StrategySpec,
    asset: str,
    window: Window,
    *,
    resume: bool,
    cross_valid_pct: float,
) -> Metric:
    directory = RESULT_ROOT / strategy.code / asset.lower() / window.label
    directory.mkdir(parents=True, exist_ok=True)
    archive = _result_zip(directory) if resume else None
    if archive is None:
        command = _backtest_command(strategy, asset, window, directory)
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
            return _failed_metric(
                strategy,
                asset,
                window,
                "BACKTEST_FAILED",
                f"Freqtrade exited {completed.returncode}; see run.log.",
                cross_valid_pct,
            )
        archive = _result_zip(directory)
    if archive is None:
        return _failed_metric(
            strategy,
            asset,
            window,
            "MISSING_ARTIFACT",
            "Freqtrade produced no ZIP artifact.",
            cross_valid_pct,
        )
    return _summarize(
        strategy,
        asset,
        window,
        _read_result(archive, strategy.name),
        archive,
        cross_valid_pct=cross_valid_pct,
    )


def _write_rows(rows: list[Metric]) -> None:
    data = [asdict(row) for row in rows]
    (RESULT_ROOT / "results.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (RESULT_ROOT / "results.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _write_config()
    for strategy in STRATEGIES:
        source = USER_DATA / "strategies" / strategy.source_file
        if not source.is_file():
            raise FileNotFoundError(source)
    data_manifest = DATA_ROOT / "cross-venue" / "manifest.json"
    if not data_manifest.is_file():
        raise FileNotFoundError(data_manifest)

    coverage = {
        (asset, window.label): _sidecar_coverage(asset, window)
        for asset in PAIRS
        for window in WINDOWS
    }
    rows: list[Metric] = []
    for window in WINDOWS:
        for strategy in STRATEGIES:
            for asset in PAIRS:
                metric = _run_backtest(
                    strategy,
                    asset,
                    window,
                    resume=args.resume,
                    cross_valid_pct=coverage[(asset, window.label)],
                )
                rows.append(metric)
                _write_rows(rows)
                print(
                    f"{window.label:>3} {asset} {strategy.code:<25} "
                    f"{metric.status:<15} trades={metric.trades:<4} "
                    f"return={metric.profit_pct:>8.2f}% "
                    f"win={metric.winrate_pct:>6.2f}%",
                    flush=True,
                )

    receipt = {
        "evaluation_end_utc_exclusive": "2026-08-01T00:00:00Z",
        "wallet_usdt": 20,
        "leverage": 2,
        "fee_one_way": 0.0005,
        "max_open_trades": 1,
        "pair_execution": "separate single-asset backtests",
        "cross_venue_file_interpretation": "PriceFlowCrossVenueControl",
        "windows": [asdict(window) for window in WINDOWS],
        "config_sha256": _sha256(CONFIG),
        "runner_sha256": _sha256(Path(__file__)),
        "data_manifest_sha256": _sha256(data_manifest),
        "strategy_sha256": {
            strategy.name: _sha256(USER_DATA / "strategies" / strategy.source_file)
            for strategy in STRATEGIES
        },
    }
    (RESULT_ROOT / "run-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failures = [row for row in rows if row.status != "MEASURED"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
