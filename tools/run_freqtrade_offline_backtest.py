from __future__ import annotations

# ruff: noqa: E402, I001

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))

from freqtrade.data import dataprovider as dataprovider_module
from freqtrade.enums import CandleType
from freqtrade.exchange.exchange import Exchange
from freqtrade.main import main as freqtrade_main


def offline_market(base: str, contract_size: float, price_precision: float) -> dict:
    return {
        "id": f"{base}-USDT-SWAP",
        "symbol": f"{base}/USDT:USDT",
        "base": base,
        "quote": "USDT",
        "settle": "USDT",
        "baseId": base,
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
        "contractSize": contract_size,
        "taker": 0.0005,
        "maker": 0.0002,
        "percentage": True,
        "tierBased": True,
        "precision": {
            "amount": 1.0,
            "price": price_precision,
            "base": None,
            "quote": None,
        },
        "limits": {
            "leverage": {"min": 1.0, "max": 100.0},
            "amount": {"min": 1.0, "max": None},
            "price": {"min": None, "max": None},
            "cost": {"min": None, "max": None},
        },
        "info": {},
    }


OFFLINE_MARKETS = (
    offline_market("BTC", 0.0001, 0.1),
    offline_market("ETH", 0.01, 0.01),
)
OFFLINE_LEVERAGE_TIERS = {
    pair: [
        {
            "tier": 1,
            "symbol": pair,
            "currency": "USDT",
            "minNotional": 0.0,
            "maxNotional": None,
            "maintenanceMarginRate": 0.004,
            "maxLeverage": 100.0,
            "info": {},
        }
    ]
    for pair in ("BTC/USDT:USDT", "ETH/USDT:USDT")
}


def offline_reload_markets(
    exchange: Exchange,
    force: bool = False,
    *,
    load_leverage_tiers: bool = True,
) -> None:
    del force, load_leverage_tiers
    exchange._api_async.set_markets(list(OFFLINE_MARKETS))
    exchange._api.set_markets_from_exchange(exchange._api_async)
    exchange._markets = dict(exchange._api_async.markets)
    exchange._last_markets_refresh = 1


def offline_load_leverage_tiers(exchange: Exchange) -> dict[str, list[dict]]:
    del exchange
    return OFFLINE_LEVERAGE_TIERS


_load_pair_history = dataprovider_module.load_pair_history


def offline_load_pair_history(*args, **kwargs):
    if kwargs.get("candle_type") == CandleType.FUNDING_RATE:
        kwargs["fill_up_missing"] = False
    return _load_pair_history(*args, **kwargs)


def main() -> int:
    with (
        patch.object(Exchange, "reload_markets", offline_reload_markets),
        patch.object(Exchange, "load_leverage_tiers", offline_load_leverage_tiers),
        patch.object(dataprovider_module, "load_pair_history", offline_load_pair_history),
    ):
        try:
            freqtrade_main(sys.argv[1:])
        except SystemExit as error:
            return int(error.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
