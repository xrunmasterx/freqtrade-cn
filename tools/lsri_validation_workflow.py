from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


DEFAULT_CONFIG = "/freqtrade/user_data/config.lsri.futures.100u.json"
DEFAULT_TIMERANGE = "20240704-20260704"
DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]
DEFAULT_STRESS_FEES = [0.001, 0.0015]
DEFAULT_STAGES = [
    "download",
    "baseline",
    "detail",
    "stress",
    "walkforward",
    "key-trades",
    "shadow-plan",
]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: list[str]

    def powershell(self) -> str:
        return " ".join(_quote_arg(arg) for arg in self.argv)


@dataclass(frozen=True)
class WorkflowConfig:
    config: str = DEFAULT_CONFIG
    strategy: str = "LSRICoreStrategy"
    timerange: str = DEFAULT_TIMERANGE
    pairs: list[str] = field(default_factory=list)
    timeframes: list[str] = field(default_factory=lambda: DEFAULT_TIMEFRAMES.copy())
    stress_fees: list[float] = field(default_factory=lambda: DEFAULT_STRESS_FEES.copy())
    walkforward_months: int = 1
    shadow_container: str = "freqtrade-lsri-shadow"
    shadow_port: int = 8084


def split_monthly_timeranges(timerange: str, months_per_window: int = 1) -> list[str]:
    start, end = _parse_timerange(timerange)
    if months_per_window < 1:
        raise ValueError("months_per_window must be >= 1")

    ranges: list[str] = []
    cursor = start
    while cursor < end:
        next_cursor = min(_add_months(date(cursor.year, cursor.month, 1), months_per_window), end)
        if next_cursor <= cursor:
            raise ValueError(f"Invalid generated window: {cursor} -> {next_cursor}")
        ranges.append(f"{_format_date(cursor)}-{_format_date(next_cursor)}")
        cursor = next_cursor
    return ranges


def build_workflow_commands(config: WorkflowConfig, stages: Iterable[str]) -> list[CommandSpec]:
    commands: list[CommandSpec] = []
    for stage in stages:
        normalized = stage.strip().lower()
        if normalized == "download":
            commands.append(_download_command(config))
        elif normalized == "baseline":
            commands.append(_backtest_command(config, "baseline_5m", detail=False))
        elif normalized == "detail":
            commands.append(_backtest_command(config, "detail_1m", detail=True))
        elif normalized == "stress":
            for fee in config.stress_fees:
                commands.append(
                    _backtest_command(
                        config,
                        f"stress_fee_{fee:.4f}".replace(".", "_"),
                        detail=True,
                        fee=fee,
                    )
                )
        elif normalized == "walkforward":
            for window in split_monthly_timeranges(config.timerange, config.walkforward_months):
                commands.append(_backtest_command(config, f"walkforward_{window}", detail=True, timerange=window))
        elif normalized == "shadow-plan":
            commands.append(_shadow_start_command(config))
        elif normalized == "key-trades":
            continue
        else:
            raise ValueError(f"Unknown stage: {stage}")
    return commands


def export_key_trade_candidates(
    result_dir: Path,
    output_csv: Path,
    top_n: int = 30,
    *,
    strategy_filter: str | None = None,
    modified_since: float | None = None,
) -> int:
    candidates: list[dict[str, object]] = []
    for zip_path in sorted(result_dir.glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True):
        if modified_since is not None and zip_path.stat().st_mtime < modified_since:
            continue
        payload = _read_backtest_payload(zip_path)
        if payload is None:
            continue
        for strategy_name, strategy_result in payload.get("strategy", {}).items():
            if strategy_filter is not None and strategy_name != strategy_filter:
                continue
            for trade in strategy_result.get("trades", []):
                profit_abs = _safe_float(trade.get("profit_abs"))
                exit_reason = str(trade.get("exit_reason", ""))
                candidates.append(
                    {
                        "result_zip": zip_path.name,
                        "strategy": strategy_name,
                        "pair": trade.get("pair", ""),
                        "open_date": trade.get("open_date", ""),
                        "close_date": trade.get("close_date", ""),
                        "profit_abs": profit_abs,
                        "profit_ratio": _safe_float(trade.get("profit_ratio")),
                        "exit_reason": exit_reason,
                        "reason": _candidate_reason(profit_abs, exit_reason),
                    }
                )

    candidates.sort(key=lambda row: abs(float(row["profit_abs"])), reverse=True)
    selected = candidates[:top_n]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "result_zip",
                "strategy",
                "pair",
                "open_date",
                "close_date",
                "profit_abs",
                "profit_ratio",
                "exit_reason",
                "reason",
            ],
        )
        writer.writeheader()
        writer.writerows(selected)
    return len(selected)


def encode_for_console(text: str, encoding: str | None) -> bytes:
    return text.encode(encoding or "utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_started_at = datetime.now().timestamp()
    root_dir = Path(args.root).resolve()
    stages = _parse_csv_list(args.stages)
    pairs = _resolve_pairs(args.pairs, args.config, root_dir)
    workflow_config = WorkflowConfig(
        config=args.config,
        strategy=args.strategy,
        timerange=args.timerange,
        pairs=pairs,
        timeframes=_parse_csv_list(args.timeframes),
        stress_fees=[float(item) for item in _parse_csv_list(args.stress_fees)],
        walkforward_months=args.walkforward_months,
        shadow_container=args.shadow_container,
        shadow_port=args.shadow_port,
    )

    run_dir = root_dir / args.run_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    commands = build_workflow_commands(workflow_config, stages)
    _write_manifest(run_dir, workflow_config, stages, commands, args.execute)
    _write_shadow_notes(run_dir, workflow_config)

    print(f"Run directory: {run_dir}")
    for command in commands:
        print(f"[{command.name}] {command.powershell()}")

    if args.execute:
        for command in commands:
            exit_code = _run_command(root_dir, run_dir, command)
            if exit_code != 0:
                print(f"Command failed: {command.name} exit={exit_code}", file=sys.stderr)
                return exit_code

    if "key-trades" in stages:
        result_dir = root_dir / args.result_dir
        csv_path = run_dir / "key_trade_candidates.csv"
        modified_since = _parse_optional_since(args.key_trade_since)
        if modified_since is None and args.execute:
            modified_since = run_started_at
        count = export_key_trade_candidates(
            result_dir,
            csv_path,
            top_n=args.key_trade_top_n,
            strategy_filter=args.strategy,
            modified_since=modified_since,
        )
        print(f"Exported {count} key trade candidates to {csv_path}")

    return 0


def _download_command(config: WorkflowConfig) -> CommandSpec:
    argv = _docker_prefix() + [
        "download-data",
        "--config",
        config.config,
        "--trading-mode",
        "futures",
        "--timerange",
        config.timerange,
        "--pairs",
        *config.pairs,
        "--timeframes",
        *config.timeframes,
    ]
    return CommandSpec("download_1m_5m_15m_1h_4h", argv)


def _backtest_command(
    config: WorkflowConfig,
    name: str,
    *,
    detail: bool,
    timerange: str | None = None,
    fee: float | None = None,
) -> CommandSpec:
    argv = _docker_prefix() + [
        "backtesting",
        "--config",
        config.config,
        "--strategy",
        config.strategy,
        "--timerange",
        timerange or config.timerange,
        "--export",
        "signals",
        "--cache",
        "none",
    ]
    if config.pairs:
        argv.extend(["--pairs", *config.pairs])
    if detail:
        argv.extend(["--timeframe-detail", "1m"])
    if fee is not None:
        argv.extend(["--fee", f"{fee:g}"])
    return CommandSpec(name, argv)


def _shadow_start_command(config: WorkflowConfig) -> CommandSpec:
    argv = [
        "docker",
        "compose",
        "run",
        "-d",
        "--name",
        config.shadow_container,
        "-p",
        f"127.0.0.1:{config.shadow_port}:8080",
        "freqtrade-futures",
        "trade",
        "--logfile",
        "/freqtrade/user_data/logs/lsri-shadow.log",
        "--db-url",
        "sqlite:////freqtrade/user_data/tradesv3-lsri-shadow.sqlite",
        "--config",
        config.config,
        "--strategy",
        config.strategy,
    ]
    return CommandSpec("shadow_dry_run_start", argv)


def _docker_prefix() -> list[str]:
    return ["docker", "compose", "run", "--rm", "freqtrade-futures"]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LSRI validation workflow.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--strategy", default="LSRICoreStrategy")
    parser.add_argument("--timerange", default=DEFAULT_TIMERANGE)
    parser.add_argument("--pairs", default="", help="Comma separated pair list. Empty reads config whitelist.")
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--stress-fees", default=",".join(str(fee) for fee in DEFAULT_STRESS_FEES))
    parser.add_argument("--walkforward-months", type=int, default=1)
    parser.add_argument("--stages", default=",".join(DEFAULT_STAGES))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--run-dir", default="ft_userdata/user_data/lsri_validation_runs")
    parser.add_argument("--result-dir", default="ft_userdata/user_data/backtest_results")
    parser.add_argument("--key-trade-top-n", type=int, default=30)
    parser.add_argument(
        "--key-trade-since",
        default="",
        help="Only export result zips modified at or after this local ISO timestamp.",
    )
    parser.add_argument("--shadow-container", default="freqtrade-lsri-shadow")
    parser.add_argument("--shadow-port", type=int, default=8084)
    return parser.parse_args(argv)


def _parse_optional_since(value: str) -> float | None:
    if not value:
        return None
    return datetime.fromisoformat(value).timestamp()


def _parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_pairs(raw_pairs: str, container_config: str, root_dir: Path) -> list[str]:
    pairs = _parse_csv_list(raw_pairs)
    if pairs:
        return pairs

    config_path = _container_config_to_local_path(container_config, root_dir)
    with config_path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    return list(config.get("exchange", {}).get("pair_whitelist", []))


def _container_config_to_local_path(container_config: str, root_dir: Path) -> Path:
    prefix = "/freqtrade/user_data/"
    normalized = container_config.replace("\\", "/")
    if normalized.startswith(prefix):
        return root_dir / "ft_userdata" / "user_data" / normalized[len(prefix) :]
    return root_dir / container_config


def _write_manifest(
    run_dir: Path,
    config: WorkflowConfig,
    stages: list[str],
    commands: list[CommandSpec],
    execute: bool,
) -> None:
    manifest = {
        "config": {
            "freqtrade_config": config.config,
            "strategy": config.strategy,
            "timerange": config.timerange,
            "pairs": config.pairs,
            "timeframes": config.timeframes,
            "stress_fees": config.stress_fees,
            "walkforward_months": config.walkforward_months,
        },
        "stages": stages,
        "execute": execute,
        "commands": [{"name": command.name, "argv": command.argv} for command in commands],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _write_shadow_notes(run_dir: Path, config: WorkflowConfig) -> None:
    notes = (
        "# LSRI shadow validation\n\n"
        "The shadow stage starts Freqtrade in dry-run mode using the selected LSRI config. "
        "Do not switch this config to real trading until baseline, detail, stress, and walk-forward gates pass.\n\n"
        f"- Container: `{config.shadow_container}`\n"
        f"- UI: `http://127.0.0.1:{config.shadow_port}`\n"
        "- Log: `ft_userdata/user_data/logs/lsri-shadow.log`\n"
        "- DB: `ft_userdata/user_data/tradesv3-lsri-shadow.sqlite`\n\n"
        "Stop command:\n\n"
        f"```powershell\ndocker rm -f {config.shadow_container}\n```\n"
    )
    (run_dir / "shadow_notes.md").write_text(notes, encoding="utf-8")


def _run_command(root_dir: Path, run_dir: Path, command: CommandSpec) -> int:
    log_path = run_dir / f"{command.name}.log"
    with log_path.open("w", encoding="utf-8") as log:
        log.write(command.powershell() + "\n\n")
        process = subprocess.Popen(
            command.argv,
            cwd=root_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.buffer.write(encode_for_console(line, sys.stdout.encoding))
            sys.stdout.buffer.flush()
            log.write(line)
        return process.wait()


def _read_backtest_payload(zip_path: Path) -> dict | None:
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.endswith(".json") or "_config" in name or name.endswith(".meta.json"):
                continue
            payload = json.loads(archive.read(name))
            if isinstance(payload, dict) and "strategy" in payload:
                return payload
    return None


def _candidate_reason(profit_abs: float, exit_reason: str) -> str:
    lowered = exit_reason.lower()
    if profit_abs < 0:
        return "large_loss"
    if profit_abs > 0:
        return "large_win"
    if "no_impulse" in lowered:
        return "no_impulse"
    if "stop" in lowered:
        return "stop_window"
    if "tp" in lowered:
        return "take_profit_window"
    return "review"


def _safe_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_timerange(timerange: str) -> tuple[date, date]:
    if "-" not in timerange:
        raise ValueError(f"Timerange must use START-END: {timerange}")
    start_raw, end_raw = timerange.split("-", 1)
    return _parse_date(start_raw), _parse_date(end_raw)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def _format_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _add_months(value: date, months: int) -> date:
    month_index = (value.month - 1) + months
    return date(value.year + month_index // 12, month_index % 12 + 1, 1)


def _quote_arg(arg: str) -> str:
    if not arg or any(char.isspace() for char in arg):
        return "'" + arg.replace("'", "''") + "'"
    return arg


if __name__ == "__main__":
    raise SystemExit(main())
