from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
USER_DATA = REPO_ROOT / "ft_userdata" / "user_data"
STRATEGY_DIR = USER_DATA / "strategies"
STRATEGY_SOURCE = STRATEGY_DIR / "MultiTimeframeCapitalRegimeResearchStrategy.py"
EXAMPLE_CONFIG = USER_DATA / "config.mtf-capital-regime-research.example.json"
DATA_ROOT = REPO_ROOT / "ft_userdata" / "runtime" / "freqtrade-futures" / "data-mtf-capital-regime-research"
DATA_DIR = DATA_ROOT / "okx"
RESEARCH_ROOT = USER_DATA / "research_data" / "mtf-capital-regime-50"
RESULT_ROOT = RESEARCH_ROOT / "results"
CONFIG_PATH = RESEARCH_ROOT / "backtest-config.json"
PREREGISTRATION_PATH = RESEARCH_ROOT / "PREREGISTRATION.md"
AMENDMENT_PATH = RESEARCH_ROOT / "AMENDMENT-2026-08-14.md"
DIAGNOSTIC_PATH = RESEARCH_ROOT / "diagnostics" / "diagnostics.json"
MANIFEST_PATH = DATA_ROOT / "manifest.json"
MARK_PATH = DATA_DIR / "futures" / "BTC_USDT_USDT-1h-mark.feather"
PYTHON = REPO_ROOT / "freqtrade" / ".venv" / "Scripts" / "python.exe"

STAGES: dict[str, tuple[str, str]] = {
    "development": ("20210901", "20250101"),
    "validation": ("20250101", "20260101"),
    "prospective": ("20260101", "20260813"),
}
FEES = {"baseline": 0.0006, "stress": 0.0010}
DEVELOPMENT_BLOCKS = {
    "D1": ("2021-09-01T00:00:00Z", "2022-01-01T00:00:00Z"),
    "D2": ("2022-01-01T00:00:00Z", "2023-01-01T00:00:00Z"),
    "D3": ("2023-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
    "D4": ("2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
}


@dataclass
class RoundResult:
    stage: str
    fee_scenario: str
    fee: float
    code: str
    strategy: str
    status: str
    reason: str = ""
    trades: int = 0
    wins: int = 0
    losses: int = 0
    winrate: float = 0.0
    strict_payoff: float | None = None
    profit_factor: float | None = None
    sharpe: float | None = None
    profit_pct: float = 0.0
    profit_abs: float = 0.0
    drawdown_pct: float = 0.0
    funding_fees: float = 0.0
    funding_observed_trades: int = 0
    mark_audit: bool = False
    force_exits: int = 0
    profitable_blocks: int = 0
    worst_block_profit_pct: float = 0.0
    blocks: dict[str, dict[str, float | int | None]] | None = None
    trade_fingerprint: str | None = None
    command: list[str] | None = None
    artifact: str | None = None
    artifact_sha256: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    strategy_sha256: str | None = None
    config_sha256: str | None = None
    data_manifest_sha256: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: float | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _load_variants() -> list[dict[str, object]]:
    sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
    sys.path.insert(0, str(STRATEGY_DIR))
    from MultiTimeframeCapitalRegimeResearchStrategy import VARIANT_SPECS

    variants = [dict(item) for item in VARIANT_SPECS]
    if len(variants) != 50 or len({item["code"] for item in variants}) != 50:
        raise RuntimeError("the amended variant matrix is not exactly 50 unique rows")
    return variants


def _write_config() -> None:
    config = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    config["bot_name"] = "mtf-capital-regime-50-research"
    RESEARCH_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _latest_zip(directory: Path) -> Path | None:
    marker = directory / ".last_result.json"
    if marker.is_file():
        try:
            name = json.loads(marker.read_text(encoding="utf-8")).get("latest_backtest")
        except (OSError, json.JSONDecodeError):
            name = None
        if name and (directory / str(name)).is_file():
            return directory / str(name)
    archives = sorted(directory.glob("*.zip"), key=lambda item: item.stat().st_mtime)
    return archives[-1] if archives else None


def _read_strategy_result(archive: Path, strategy_name: str) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as bundle:
        candidates = [
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        for name in candidates:
            payload = json.loads(bundle.read(name))
            strategies = payload.get("strategy")
            if isinstance(strategies, dict) and strategy_name in strategies:
                return strategies[strategy_name]
    raise ValueError(f"strategy result {strategy_name} not found in {archive}")


def _profit_factor(values: list[float]) -> float | None:
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    if gross_loss == 0:
        return None if gross_profit == 0 else float("inf")
    return gross_profit / gross_loss


def _trade_fingerprint(trades: list[dict[str, Any]]) -> str:
    selected = [
        {
            "open_timestamp": trade.get("open_timestamp"),
            "close_timestamp": trade.get("close_timestamp"),
            "profit_ratio": trade.get("profit_ratio"),
            "funding_fees": trade.get("funding_fees"),
            "is_short": trade.get("is_short"),
            "exit_reason": trade.get("exit_reason"),
        }
        for trade in trades
    ]
    encoded = json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _block_metrics(trades: list[dict[str, Any]]) -> dict[str, dict[str, float | int | None]]:
    result: dict[str, dict[str, float | int | None]] = {}
    for label, (start_value, end_value) in DEVELOPMENT_BLOCKS.items():
        start = pd.Timestamp(start_value)
        end = pd.Timestamp(end_value)
        values = [
            float(trade.get("profit_ratio", 0.0))
            for trade in trades
            if start <= pd.Timestamp(str(trade.get("open_date"))) < end
        ]
        result[label] = {
            "trades": len(values),
            "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values),
            "profit_pct": sum(values) * 100.0,
            "profit_factor": _profit_factor(values),
        }
    return result


def _mark_bounds() -> tuple[pd.Timestamp, pd.Timestamp]:
    if not MARK_PATH.is_file():
        raise FileNotFoundError(MARK_PATH)
    frame = pd.read_feather(MARK_PATH)
    dates = pd.to_datetime(frame["date"], utc=True)
    return dates.min(), dates.max()


def _audit_cost_rows(trades: list[dict[str, Any]]) -> tuple[bool, int]:
    mark_start, mark_end = _mark_bounds()
    observed = 0
    for trade in trades:
        if "funding_fees" not in trade:
            return False, observed
        open_date = pd.Timestamp(str(trade.get("open_date")))
        close_date = pd.Timestamp(str(trade.get("close_date")))
        if open_date < mark_start or close_date > mark_end:
            return False, observed
        if float(trade.get("funding_fees") or 0.0) != 0.0:
            observed += 1
    return True, observed


def _summarize(
    stage: str,
    fee_scenario: str,
    fee: float,
    code: str,
    strategy: str,
    payload: dict[str, Any],
) -> RoundResult:
    trades = list(payload.get("trades") or [])
    values = [float(trade.get("profit_ratio", 0.0)) for trade in trades]
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    payoff = None
    if winners and losers:
        payoff = (sum(winners) / len(winners)) / abs(sum(losers) / len(losers))
    blocks = _block_metrics(trades) if stage == "development" else None
    block_profits = [float(item["profit_pct"] or 0.0) for item in (blocks or {}).values()]
    mark_audit, observed_count = _audit_cost_rows(trades)
    return RoundResult(
        stage=stage,
        fee_scenario=fee_scenario,
        fee=fee,
        code=code,
        strategy=strategy,
        status="MEASURED",
        trades=len(trades),
        wins=len(winners),
        losses=len(losers),
        winrate=(len(winners) / len(trades) if trades else 0.0),
        strict_payoff=payoff,
        profit_factor=(float(payload["profit_factor"]) if payload.get("profit_factor") is not None else None),
        sharpe=(float(payload["sharpe"]) if payload.get("sharpe") is not None else None),
        profit_pct=float(payload.get("profit_total", 0.0)) * 100.0,
        profit_abs=float(payload.get("profit_total_abs", 0.0)),
        drawdown_pct=float(payload.get("max_drawdown_account", 0.0) or 0.0) * 100.0,
        funding_fees=sum(float(trade.get("funding_fees") or 0.0) for trade in trades),
        funding_observed_trades=observed_count,
        mark_audit=mark_audit,
        force_exits=sum(str(trade.get("exit_reason") or "").startswith("force_") for trade in trades),
        profitable_blocks=sum(value > 0 for value in block_profits),
        worst_block_profit_pct=min(block_profits) if block_profits else 0.0,
        blocks=blocks,
        trade_fingerprint=_trade_fingerprint(trades),
    )


def _run_one(
    variant: dict[str, object],
    stage: str,
    fee_scenario: str,
    *,
    timeout_seconds: int,
    resume: bool,
) -> RoundResult:
    fee = FEES[fee_scenario]
    code = str(variant["code"])
    strategy = str(variant["name"])
    directory = RESULT_ROOT / "artifacts" / stage / fee_scenario / code
    directory.mkdir(parents=True, exist_ok=True)
    receipt_path = directory / "round.json"
    if resume and receipt_path.is_file():
        try:
            old = json.loads(receipt_path.read_text(encoding="utf-8"))
            if old.get("status") == "MEASURED" and old.get("artifact") and Path(old["artifact"]).is_file():
                return RoundResult(**old)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass

    start_date, end_date = STAGES[stage]
    command = [
        str(PYTHON),
        str(REPO_ROOT / "tools" / "run_freqtrade_offline_backtest.py"),
        "backtesting",
        "--config",
        str(CONFIG_PATH),
        "--user-data-dir",
        str(USER_DATA),
        "--datadir",
        str(DATA_DIR),
        "--strategy",
        strategy,
        "--timerange",
        f"{start_date}-{end_date}",
        "--fee",
        str(fee),
        "--cache",
        "none",
        "--backtest-directory",
        str(directory),
        "--export",
        "trades",
    ]
    stdout_path = directory / "stdout.log"
    stderr_path = directory / "stderr.log"
    started = datetime.now(timezone.utc)
    begin = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
    except subprocess.TimeoutExpired as error:
        stdout_path.write_text(str(error.stdout or ""), encoding="utf-8")
        stderr_path.write_text(str(error.stderr or ""), encoding="utf-8")
        result = RoundResult(
            stage=stage,
            fee_scenario=fee_scenario,
            fee=fee,
            code=code,
            strategy=strategy,
            status="FAILED",
            reason=f"timeout after {timeout_seconds}s",
            command=command,
            stdout=str(stdout_path),
            stderr=str(stderr_path),
        )
        receipt_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    archive = _latest_zip(directory)
    if completed.returncode != 0 or archive is None:
        result = RoundResult(
            stage=stage,
            fee_scenario=fee_scenario,
            fee=fee,
            code=code,
            strategy=strategy,
            status="FAILED",
            reason=f"freqtrade exit={completed.returncode}; archive={archive}",
            command=command,
            stdout=str(stdout_path),
            stderr=str(stderr_path),
        )
    else:
        try:
            payload = _read_strategy_result(archive, strategy)
            result = _summarize(stage, fee_scenario, fee, code, strategy, payload)
            result.artifact = str(archive)
            result.artifact_sha256 = _sha256(archive)
            result.stdout = str(stdout_path)
            result.stderr = str(stderr_path)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            result = RoundResult(
                stage=stage,
                fee_scenario=fee_scenario,
                fee=fee,
                code=code,
                strategy=strategy,
                status="FAILED",
                reason=f"result parse or cost audit failed: {error}",
                command=command,
                artifact=str(archive),
                artifact_sha256=_sha256(archive),
                stdout=str(stdout_path),
                stderr=str(stderr_path),
            )

    result.command = command
    result.strategy_sha256 = _sha256(STRATEGY_SOURCE)
    result.config_sha256 = _sha256(CONFIG_PATH)
    result.data_manifest_sha256 = _sha256(MANIFEST_PATH)
    result.started_at = started.isoformat()
    result.finished_at = datetime.now(timezone.utc).isoformat()
    result.elapsed_seconds = time.monotonic() - begin
    receipt_path.write_text(
        json.dumps(_json_safe(asdict(result)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def _run_many(
    variants: list[dict[str, object]],
    stage: str,
    fee_scenario: str,
    *,
    workers: int,
    timeout_seconds: int,
    resume: bool,
) -> list[RoundResult]:
    results: list[RoundResult] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _run_one,
                variant,
                stage,
                fee_scenario,
                timeout_seconds=timeout_seconds,
                resume=resume,
            ): variant
            for variant in variants
        }
        for future in as_completed(futures):
            results.append(future.result())
    order = {str(item["code"]): index for index, item in enumerate(variants)}
    return sorted(results, key=lambda item: order[item.code])


def _screen(result: RoundResult, *, minimum_trades: int) -> tuple[bool, str]:
    failures: list[str] = []
    if result.status != "MEASURED":
        return False, result.reason or result.status
    if result.trades < minimum_trades:
        failures.append(f"trades<{minimum_trades}")
    if result.winrate <= 0.50:
        failures.append("winrate<=50%")
    if result.strict_payoff is None or result.strict_payoff <= 2.0:
        failures.append("payoff<=2")
    if result.sharpe is None or result.sharpe < 1.5:
        failures.append("sharpe<1.5")
    if result.profit_factor is None or result.profit_factor <= 1.0:
        failures.append("PF<=1")
    if result.profit_pct <= 0:
        failures.append("profit<=0")
    if result.drawdown_pct >= 20.0:
        failures.append("drawdown>=20%")
    if result.force_exits:
        failures.append("force_exit")
    if not result.mark_audit:
        failures.append("mark_audit_failed")
    if result.stage == "development" and result.profitable_blocks < 3:
        failures.append("profitable_blocks<3")
    return not failures, ",".join(failures)


def _score(result: RoundResult) -> tuple[float, ...]:
    return (
        result.worst_block_profit_pct,
        result.sharpe if result.sharpe is not None else float("-inf"),
        result.strict_payoff if result.strict_payoff is not None else float("-inf"),
        result.profit_factor if result.profit_factor is not None else float("-inf"),
        result.winrate,
        -result.drawdown_pct,
    )


def _write_csv(path: Path, results: list[RoundResult]) -> None:
    fields = [
        "stage",
        "fee_scenario",
        "fee",
        "code",
        "strategy",
        "status",
        "reason",
        "trades",
        "wins",
        "losses",
        "winrate",
        "strict_payoff",
        "profit_factor",
        "sharpe",
        "profit_pct",
        "profit_abs",
        "drawdown_pct",
        "funding_fees",
        "funding_observed_trades",
        "mark_audit",
        "force_exits",
        "profitable_blocks",
        "worst_block_profit_pct",
        "trade_fingerprint",
        "artifact",
        "artifact_sha256",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in results:
            values = asdict(item)
            writer.writerow({field: values[field] for field in fields})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed 50-candidate capital-regime research screen.")
    parser.add_argument("--phase", choices=("development", "all"), default="development")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be positive")
    for path in (PYTHON, STRATEGY_SOURCE, EXAMPLE_CONFIG, MANIFEST_PATH, MARK_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not PREREGISTRATION_PATH.is_file() or not AMENDMENT_PATH.is_file():
        raise FileNotFoundError("the preregistration and dated amendment are required")
    _write_config()
    variants = _load_variants()
    RESEARCH_ROOT.mkdir(parents=True, exist_ok=True)
    protocol = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategy_source": str(STRATEGY_SOURCE),
        "strategy_sha256": _sha256(STRATEGY_SOURCE),
        "config": str(CONFIG_PATH),
        "config_sha256": _sha256(CONFIG_PATH),
        "preregistration": str(PREREGISTRATION_PATH),
        "preregistration_sha256": _sha256(PREREGISTRATION_PATH),
        "amendment": str(AMENDMENT_PATH),
        "amendment_sha256": _sha256(AMENDMENT_PATH),
        "data_manifest": str(MANIFEST_PATH),
        "data_manifest_sha256": _sha256(MANIFEST_PATH),
        "diagnostic": str(DIAGNOSTIC_PATH),
        "diagnostic_sha256": _sha256(DIAGNOSTIC_PATH) if DIAGNOSTIC_PATH.is_file() else None,
        "mark_path": str(MARK_PATH),
        "mark_sha256": _sha256(MARK_PATH),
        "variants": variants,
        "stages": STAGES,
        "fees": FEES,
        "commands": "one local Freqtrade backtesting process per round; no leverage above 1x",
        "selection_rule": "only complete development survivors; no diagnostic fallback",
    }
    (RESEARCH_ROOT / "run-manifest.json").write_text(
        json.dumps(_json_safe(protocol), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    development = _run_many(
        variants,
        "development",
        "baseline",
        workers=args.workers,
        timeout_seconds=args.timeout_seconds,
        resume=args.resume,
    )
    results: list[RoundResult] = list(development)
    eligible = [item for item in development if _screen(item, minimum_trades=30)[0]]
    ranked = sorted(eligible, key=_score, reverse=True)
    selected_codes = [item.code for item in ranked[:3]]
    selection: dict[str, object] = {
        "eligible_development": [item.code for item in eligible],
        "ranked_development": [item.code for item in ranked],
        "selected_codes": selected_codes,
        "selected_rule": "top three complete development survivors; no fallback when empty",
        "status": "DEVELOPMENT_COMPLETE" if args.phase == "development" else "PENDING_VALIDATION",
    }
    print(
        f"development rounds={len(development)} measured={sum(item.status == 'MEASURED' for item in development)} "
        f"eligible={len(eligible)}"
    )
    if args.phase == "all" and selected_codes:
        selected = [variant for variant in variants if str(variant["code"]) in selected_codes]
        for stage in ("validation", "prospective"):
            for fee_scenario in ("baseline", "stress"):
                stage_results = _run_many(
                    selected,
                    stage,
                    fee_scenario,
                    workers=args.workers,
                    timeout_seconds=args.timeout_seconds,
                    resume=args.resume,
                )
                results.extend(stage_results)
                print(
                    f"{stage}/{fee_scenario} rounds={len(stage_results)} "
                    f"measured={sum(item.status == 'MEASURED' for item in stage_results)}"
                )
        selection["status"] = "VALIDATION_COMPLETE"
    elif args.phase == "all" and not selected_codes:
        selection["status"] = "NO_DEVELOPMENT_SURVIVOR"
        print("validation/prospective not opened: no complete development survivor")

    payload = {
        "protocol": protocol,
        "selection": selection,
        "results": [_json_safe(asdict(item)) for item in results],
    }
    (RESEARCH_ROOT / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(RESEARCH_ROOT / "results.csv", results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
