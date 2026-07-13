from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_REPO = REPO_ROOT / "freqtrade"
TIMERANGE_ERROR = "Timerange must use YYYYMMDD-YYYYMMDD format."
CONFIG_READ_ERROR = "Unable to read config file."
CALENDAR_REQUIRED_ERROR = (
    "A-share event/document side-data live collection requires market_data.calendar."
)
sys.path.insert(0, str(FREQTRADE_REPO))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

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
    from freqtrade.research.exceptions import ResearchConfigError
    from freqtrade.research.market_context import create_research_market_context
    from freqtrade.research.side_data.collectors.a_share_side_data import (
        AShareSideDataCollectionError,
        AShareSideDataCollector,
        AShareSideDataRequest,
    )

    try:
        profiles = {profile.id: profile for profile in load_research_profiles(config)}
    except ResearchConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    profile = profiles.get(args.bot_id)
    if profile is None:
        print(f"Unknown research bot: {args.bot_id}", file=sys.stderr)
        return 2
    if profile.side_data_root is None:
        print(f"Research bot has no side_data root: {args.bot_id}", file=sys.stderr)
        return 2

    try:
        market_context = create_research_market_context(profile)
    except (ResearchConfigError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    calendar = market_context.calendar if market_context is not None else None
    if _requires_calendar(args.datasets) and calendar is None:
        print(CALENDAR_REQUIRED_ERROR, file=sys.stderr)
        return 2

    try:
        provider = _create_provider(args.provider, calendar)
        collector = AShareSideDataCollector(
            profile.side_data_root,
            provider,
            calendar=calendar,
        )
        summary = collector.collect(
            AShareSideDataRequest(
                instruments=args.instruments,
                datasets=args.datasets,
                start_date=start_date,
                end_date=end_date,
            )
        )
    except (AShareSideDataCollectionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if summary.failed:
        _print_failed_summary(summary)

    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    return 1 if summary.failed else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download A-share side-data artifacts.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--provider", default="akshare", choices=["akshare"])
    parser.add_argument(
        "--datasets",
        nargs="+",
        required=True,
        choices=["fund_flow_daily", "limit_pool", "announcements"],
    )
    parser.add_argument("--instruments", nargs="+", required=True)
    parser.add_argument("--timerange")
    return parser


def _create_provider(provider_name: str, calendar: Any) -> Any:
    if provider_name == "akshare":
        from freqtrade.research.side_data.providers.akshare_side_data import (
            AkshareAshareSideDataProvider,
        )

        return AkshareAshareSideDataProvider(calendar)
    raise ValueError(f"Unsupported A-share side-data provider: {provider_name}")


def _requires_calendar(datasets: list[str]) -> bool:
    return any(dataset in {"limit_pool", "announcements"} for dataset in datasets)


def _print_failed_summary(summary: Any) -> None:
    print(
        f"A-share side-data collection failed for {summary.failed} artifact(s).",
        file=sys.stderr,
    )
    for file_summary in summary.files:
        if file_summary.status == "error":
            print(f"{file_summary.path}: {file_summary.error or 'failed'}", file=sys.stderr)


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


if __name__ == "__main__":
    raise SystemExit(main())
