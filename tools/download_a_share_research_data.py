from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_REPO = REPO_ROOT / "freqtrade"
TIMERANGE_ERROR = "Timerange must use YYYYMMDD-YYYYMMDD format."
CONFIG_READ_ERROR = "Unable to read config file."
COLLECTION_IO_ERROR = "Unable to write A-share OHLCV output."
sys.path.insert(0, str(FREQTRADE_REPO))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config_path = Path(args.config).expanduser().resolve()

    try:
        config = _load_config(config_path)
    except OSError:
        print(CONFIG_READ_ERROR, file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        start_date, end_date = _parse_timerange(args.timerange)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    from freqtrade.research import load_research_profiles
    from freqtrade.research.collectors.a_share_ohlcv import (
        AShareOhlcvCollectionError,
        AShareOhlcvCollector,
        AShareOhlcvRequest,
    )
    from freqtrade.research.data_sources.akshare_ashare import (
        AkshareAshareOhlcvProvider,
    )
    from freqtrade.research.exceptions import ResearchConfigError

    try:
        profiles = {profile.id: profile for profile in load_research_profiles(config)}
    except ResearchConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    profile = profiles.get(args.bot_id)
    if profile is None:
        print(f"Unknown research bot: {args.bot_id}", file=sys.stderr)
        return 2

    collector = AShareOhlcvCollector(
        root=profile.data_root,
        provider=AkshareAshareOhlcvProvider(),
    )
    request = AShareOhlcvRequest(
        instruments=args.instruments,
        timeframes=args.timeframes,
        start_date=start_date,
        end_date=end_date,
        adjustment=args.adjustment,
    )

    try:
        summary = collector.collect(request)
    except AShareOhlcvCollectionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError:
        print(COLLECTION_IO_ERROR, file=sys.stderr)
        return 2

    for file_summary in summary.files:
        error = _public_file_error(file_summary.error)
        print(
            f"{file_summary.status}: {file_summary.path} "
            f"rows={file_summary.rows} error={error}"
        )

    return 1 if summary.failed else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download A-share OHLCV data for a repository-local research bot."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--instruments", nargs="+", required=True)
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=["1d"],
        help="Supported values: 1m 5m 15m 30m 60m 1d.",
    )
    parser.add_argument("--timerange")
    parser.add_argument("--adjustment", choices=["raw", "qfq", "hfq"], default="raw")
    return parser


def _load_config(config_path: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if "user_data_dir" not in config:
        config["user_data_dir"] = str(config_path.parent)
    return config


def _parse_timerange(timerange: str | None) -> tuple[str | None, str | None]:
    if timerange is None:
        return None, None

    if timerange.count("-") != 1:
        raise ValueError(TIMERANGE_ERROR)

    start_date, end_date = timerange.split("-", maxsplit=1)
    if not start_date and not end_date:
        raise ValueError(TIMERANGE_ERROR)

    parsed_start = _parse_timerange_side(start_date)
    parsed_end = _parse_timerange_side(end_date)
    if parsed_start is not None and parsed_end is not None and parsed_start > parsed_end:
        raise ValueError(TIMERANGE_ERROR)

    return start_date or None, end_date or None


def _parse_timerange_side(value: str) -> date | None:
    if not value:
        return None
    if len(value) != 8 or not value.isdigit():
        raise ValueError(TIMERANGE_ERROR)
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError as exc:
        raise ValueError(TIMERANGE_ERROR) from exc


def _public_file_error(error: str | None) -> str:
    if not error:
        return ""
    if _contains_local_path(error):
        return "failed"
    return error


def _contains_local_path(message: str) -> bool:
    repo_root = str(REPO_ROOT)
    if repo_root and repo_root in message:
        return True
    return re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", message) is not None


if __name__ == "__main__":
    raise SystemExit(main())
