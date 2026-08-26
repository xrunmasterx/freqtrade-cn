from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_ROOT = ROOT / "freqtrade"
sys.path.insert(0, str(FREQTRADE_ROOT))

from freqtrade.exchange.exchange import Exchange
from freqtrade.main import main as freqtrade_main

CONFIG_FILE = (
    ROOT
    / "ft_userdata"
    / "user_data"
    / "config.robust-candidate-research.corrected.json"
)
DATA_ROOT = (
    ROOT
    / "ft_userdata"
    / "user_data"
    / "data"
    / "okx-btc-usdt-swap-full-20260813"
    / "market-data"
)
STAGE_TIMERANGES = {
    "development": "1754006400-1775001599",
    "development-block-1": "1754006400-1759276799",
    "development-block-2": "1759276800-1764547199",
    "development-block-3": "1764547200-1769903999",
    "development-block-4": "1769904000-1775001599",
    "validation": "1775001600-1782863999",
    "pseudo-oos": "1782864000-1786579199",
}
FROZEN_STRATEGIES = (
    "DonchianRobustBaselineResearchStrategy",
    "DonchianRobustHold72ResearchStrategy",
)
FROZEN_FEE = 0.0006
OFFLINE_MARKET = {
    "id": "BTC-USDT-SWAP",
    "symbol": "BTC/USDT:USDT",
    "base": "BTC",
    "quote": "USDT",
    "settle": "USDT",
    "baseId": "BTC",
    "quoteId": "USDT",
    "settleId": "USDT",
    "type": "swap",
    "spot": False,
    "margin": False,
    "swap": True,
    "future": False,
    "option": False,
    "active": True,
    "contract": True,
    "linear": True,
    "inverse": False,
    "contractSize": 0.0001,
    "taker": FROZEN_FEE,
    "maker": 0.0002,
    "percentage": True,
    "tierBased": True,
    "precision": {"amount": 1.0, "price": 0.1, "base": None, "quote": None},
    "limits": {
        "leverage": {"min": 1.0, "max": 100.0},
        "amount": {"min": 1.0, "max": None},
        "price": {"min": None, "max": None},
        "cost": {"min": None, "max": None},
    },
    "info": {},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=tuple(STAGE_TIMERANGES), required=True)
    parser.add_argument("--strategy", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def validate_run(stage: str, strategies: list[str]) -> None:
    if tuple(strategies) != FROZEN_STRATEGIES:
        raise ValueError(
            f"{stage} must run the frozen strategies in order: {FROZEN_STRATEGIES}"
        )


def offline_reload_markets(
    exchange: Exchange,
    force: bool = False,
    *,
    load_leverage_tiers: bool = True,
) -> None:
    exchange._api_async.set_markets([OFFLINE_MARKET])
    exchange._api.set_markets_from_exchange(exchange._api_async)
    exchange._markets = dict(exchange._api_async.markets)
    exchange._last_markets_refresh = 1


def main() -> int:
    args = parse_args()
    validate_run(args.stage, args.strategy)
    args.output.mkdir(parents=True, exist_ok=False)
    command = [
        "backtesting",
        "--strategy-list",
        *args.strategy,
        "-c",
        str(CONFIG_FILE),
        "--userdir",
        str(ROOT / "ft_userdata" / "user_data"),
        "--strategy-path",
        str(ROOT / "ft_userdata" / "user_data" / "strategies"),
        "-d",
        str(DATA_ROOT),
        "--timerange",
        STAGE_TIMERANGES[args.stage],
        "--timeframe-detail",
        "5m",
        "--timeframe",
        "15m",
        "--pairs",
        "BTC/USDT:USDT",
        "--fee",
        str(FROZEN_FEE),
        "--export",
        "trades",
        "--backtest-directory",
        str(args.output),
        "--cache",
        "none",
    ]
    with patch.object(Exchange, "reload_markets", offline_reload_markets):
        try:
            freqtrade_main(command)
        except SystemExit as error:
            return int(error.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
