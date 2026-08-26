from __future__ import annotations

from typing import Any
from unittest.mock import patch

from run_offline_robust_candidate_backtest_corrected import Exchange, main

OFFLINE_LEVERAGE_TIERS = {
    "BTC/USDT:USDT": [
        {
            "tier": 1,
            "symbol": "BTC/USDT:USDT",
            "currency": "USDT",
            "minNotional": 0.0,
            "maxNotional": 1_000_000_000.0,
            "maintenanceMarginRate": 0.004,
            "maxLeverage": 100.0,
            "info": {},
        }
    ]
}


def offline_load_leverage_tiers(
    exchange: Exchange,
) -> dict[str, list[dict[str, Any]]]:
    return OFFLINE_LEVERAGE_TIERS


if __name__ == "__main__":
    with patch.object(Exchange, "load_leverage_tiers", offline_load_leverage_tiers):
        raise SystemExit(main())
