# LSRI Core Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new backtestable OKX futures strategy, `LSRICoreStrategy`, implementing the approved LSRI Core multi-timeframe signal and R-based risk model for a 20 USDT isolated-margin dry-run account.

**Architecture:** Add a standalone user strategy and a standalone 20U futures config without modifying `VolatilitySystem`. The strategy uses `5m` as the execution timeframe, Freqtrade informative pairs for `15m`, `1h`, `4h`, and `1h funding_rate`, and callbacks for technical stoploss, 2.2R take-profit, time-stop, pair-specific leverage, and fixed stake behavior.

**Tech Stack:** Freqtrade strategy interface v3, Python 3.11, pandas, TA-Lib, Freqtrade dataprovider, Freqtrade Docker Compose service `freqtrade-futures`, OKX futures historical data.

---

## Assumptions And Boundaries

- Worktree root is `G:\AI_Trading\freqtrade-cn`.
- Docker Compose service for Freqtrade commands is `freqtrade-futures`.
- User data is mounted in the container at `/freqtrade/user_data`.
- The existing webserver on port `8003` can remain running.
- This plan does not modify or restart the existing `freqtrade-cn-futures-webserver-8003` container unless the user asks for UI validation.
- Existing unrelated dirty files in the worktree must not be reverted or staged with LSRI changes.
- Real trading is out of scope. All commands use backtesting, data listing, dry-run config, or webserver mode.
- The implementation should use `startup_candle_count = 240`. Freqtrade applies startup history separately for each informative timeframe, so the `4h` informative pair receives 240 candles of `4h` history for the EMA200 warmup.

## File Map

- Create `ft_userdata/user_data/strategies/LSRICoreStrategy.py`
  - Owns LSRI indicators, entry scoring, pair-specific leverage, stake cap, custom stoploss, custom exit, and trade plan persistence in `Trade` custom data.
- Create `ft_userdata/user_data/config.lsri.futures.20u.json`
  - Owns the isolated futures dry-run account settings for the LSRI strategy.
- Modify no existing strategy or config file.
- Download or verify data files under `ft_userdata/user_data/data/okx/futures`
  - Required for backtesting, but not intended to be committed unless the repository already tracks this data by policy.

## Task 1: Verify And Download Required Historical Data

**Files:**
- Data: `ft_userdata/user_data/data/okx/futures/BTC_USDT_USDT-15m-futures.feather`
- Data: `ft_userdata/user_data/data/okx/futures/BTC_USDT_USDT-4h-futures.feather`
- Data: `ft_userdata/user_data/data/okx/futures/ETH_USDT_USDT-15m-futures.feather`
- Data: `ft_userdata/user_data/data/okx/futures/ETH_USDT_USDT-4h-futures.feather`

- [ ] **Step 1: Verify currently missing required files**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
$required = @(
  'ft_userdata\user_data\data\okx\futures\BTC_USDT_USDT-15m-futures.feather',
  'ft_userdata\user_data\data\okx\futures\BTC_USDT_USDT-4h-futures.feather',
  'ft_userdata\user_data\data\okx\futures\ETH_USDT_USDT-15m-futures.feather',
  'ft_userdata\user_data\data\okx\futures\ETH_USDT_USDT-4h-futures.feather'
)
$required | ForEach-Object {
  [pscustomobject]@{
    Path = $_
    Exists = Test-Path -LiteralPath $_
  }
} | Format-Table -AutoSize
```

Expected before download:

```text
Exists is False for at least one 15m or 4h futures file.
```

- [ ] **Step 2: Download 15m and 4h OKX futures candles**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose run --rm freqtrade-futures download-data `
  --config /freqtrade/user_data/config.volatility.futures.json `
  --trading-mode futures `
  --pairs BTC/USDT:USDT ETH/USDT:USDT `
  --timeframes 15m 4h `
  --timerange 20240101-20260701 `
  --candle-types futures
```

Expected:

```text
Download completes without "No data found" or exchange authentication errors.
```

- [ ] **Step 3: Verify required files exist after download**

Run the same PowerShell check from Step 1.

Expected:

```text
Exists is True for all four required futures files.
```

- [ ] **Step 4: Confirm existing funding-rate data is present**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
$funding = @(
  'ft_userdata\user_data\data\okx\futures\BTC_USDT_USDT-1h-funding_rate.feather',
  'ft_userdata\user_data\data\okx\futures\ETH_USDT_USDT-1h-funding_rate.feather'
)
$funding | ForEach-Object {
  [pscustomobject]@{
    Path = $_
    Exists = Test-Path -LiteralPath $_
  }
} | Format-Table -AutoSize
```

Expected:

```text
Exists is True for both 1h funding_rate files.
```

- [ ] **Step 5: Commit decision**

Do not commit downloaded market data unless the repository already tracks this data. Confirm with:

```powershell
cd G:\AI_Trading\freqtrade-cn
git status --short -- ft_userdata/user_data/data/okx/futures
```

Expected:

```text
No staged data files for this task.
```

## Task 2: Add The 20U LSRI Futures Config

**Files:**
- Create: `ft_userdata/user_data/config.lsri.futures.20u.json`

- [ ] **Step 1: Verify the config does not exist yet**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
Test-Path -LiteralPath 'ft_userdata\user_data\config.lsri.futures.20u.json'
```

Expected:

```text
False
```

- [ ] **Step 2: Create `config.lsri.futures.20u.json`**

Create `ft_userdata/user_data/config.lsri.futures.20u.json` with this exact JSON:

```json
{
    "$schema": "https://schema.freqtrade.io/schema.json",
    "bot_name": "freqtrade-cn-okx-lsri-core-futures-20u",
    "max_open_trades": 1,
    "stake_currency": "USDT",
    "stake_amount": 18,
    "tradable_balance_ratio": 0.9,
    "fiat_display_currency": "USD",
    "dry_run": true,
    "dry_run_wallet": 20,
    "cancel_open_orders_on_exit": false,
    "trading_mode": "futures",
    "margin_mode": "isolated",
    "unfilledtimeout": {
        "entry": 10,
        "exit": 10,
        "exit_timeout_count": 0,
        "unit": "minutes"
    },
    "entry_pricing": {
        "price_side": "same",
        "use_order_book": true,
        "order_book_top": 1,
        "price_last_balance": 0.0,
        "check_depth_of_market": {
            "enabled": false,
            "bids_to_ask_delta": 1
        }
    },
    "exit_pricing": {
        "price_side": "same",
        "use_order_book": true,
        "order_book_top": 1,
        "price_last_balance": 0.0
    },
    "order_types": {
        "entry": "limit",
        "exit": "limit",
        "emergency_exit": "market",
        "force_entry": "market",
        "force_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": true,
        "stoploss_on_exchange_interval": 60
    },
    "order_time_in_force": {
        "entry": "GTC",
        "exit": "GTC"
    },
    "exchange": {
        "name": "okx",
        "key": "",
        "secret": "",
        "password": "",
        "ccxt_config": {
            "httpsProxy": "http://host.docker.internal:12639",
            "wsProxy": "http://host.docker.internal:12639",
            "options": {
                "defaultType": "swap",
                "fetchMarkets": {
                    "types": [
                        "swap"
                    ]
                }
            }
        },
        "ccxt_async_config": {},
        "pair_whitelist": [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT"
        ],
        "pair_blacklist": []
    },
    "pairlists": [
        {
            "method": "StaticPairList"
        }
    ],
    "telegram": {
        "enabled": false,
        "token": "",
        "chat_id": ""
    },
    "api_server": {
        "enabled": true,
        "listen_ip_address": "0.0.0.0",
        "listen_port": 8080,
        "verbosity": "error",
        "enable_openapi": false,
        "jwt_secret_key": "replace-me-lsri-futures-jwt-secret",
        "ws_token": "replace-me-lsri-futures-ws-token",
        "CORS_origins": [
            "http://127.0.0.1:8003",
            "http://localhost:8003",
            "http://127.0.0.1:8082",
            "http://localhost:8082",
            "http://127.0.0.1:8081",
            "http://localhost:8081"
        ],
        "username": "freqtrader",
        "password": "__SET_VIA_SECRET_FILE__"
    },
    "initial_state": "running",
    "force_entry_enable": false,
    "internals": {
        "process_throttle_secs": 5
    }
}
```

- [ ] **Step 3: Validate JSON syntax**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
python -m json.tool ft_userdata\user_data\config.lsri.futures.20u.json | Out-Null
```

Expected:

```text
Command exits with code 0 and prints no error.
```

- [ ] **Step 4: Commit config**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add ft_userdata/user_data/config.lsri.futures.20u.json
git commit -m "config: add lsri 20u futures config"
```

Expected:

```text
Commit succeeds and includes only config.lsri.futures.20u.json.
```

## Task 3: Add The LSRI Core Strategy

**Files:**
- Create: `ft_userdata/user_data/strategies/LSRICoreStrategy.py`

- [ ] **Step 1: Verify strategy is not currently loadable**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose run --rm freqtrade-futures list-strategies `
  --config /freqtrade/user_data/config.lsri.futures.20u.json `
  --strategy-path /freqtrade/user_data/strategies `
  -1 | Select-String -Pattern 'LSRICoreStrategy'
```

Expected before the file exists:

```text
No output containing LSRICoreStrategy.
```

- [ ] **Step 2: Create `LSRICoreStrategy.py`**

Create `ft_userdata/user_data/strategies/LSRICoreStrategy.py` with this exact code:

```python
# flake8: noqa: F401
# isort: skip_file
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from pandas import DataFrame

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair, stoploss_from_absolute


class LSRICoreStrategy(IStrategy):
    """
    LSRI Core: Liquidity Sweep + Regime Impulse.

    Backtestable core version for OKX BTC/ETH USDT perpetual futures.
    """

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "5m"
    process_only_new_candles = True

    minimal_roi = {"0": 100}
    stoploss = -0.99
    use_custom_stoploss = True
    trailing_stop = False
    position_adjustment_enable = False
    startup_candle_count = 240

    pullback_window = 12
    pullback_tolerance = 0.0015
    funding_limit = 0.0003
    adx_threshold = 18.0
    volume_z_threshold = 1.0
    take_profit_r = 2.2
    time_stop_minutes = 90
    time_stop_r = 0.5
    fee_buffer_pct = 0.0015

    plot_config = {
        "main_plot": {
            "key_long_level": {"color": "green"},
            "key_short_level": {"color": "red"},
            "long_stop_rate": {"color": "orange"},
            "short_stop_rate": {"color": "orange"},
        },
        "subplots": {
            "LSRI Score": {
                "long_score": {"color": "green"},
                "short_score": {"color": "red"},
            },
            "Funding": {
                "funding_rate_fr_1h": {"color": "blue"},
            },
        },
    }

    def informative_pairs(self):
        pairs = (
            self.dp.current_whitelist()
            if self.dp
            else self.config.get("exchange", {}).get("pair_whitelist", [])
        )
        informative = []
        for pair in pairs:
            informative.extend(
                [
                    (pair, "15m"),
                    (pair, "1h"),
                    (pair, "4h"),
                    (pair, "1h", "funding_rate"),
                ]
            )
        return informative

    @staticmethod
    def _points(condition: pd.Series, points: int) -> pd.Series:
        return condition.fillna(False).astype(int) * points

    @staticmethod
    def _safe_float(value, default: Optional[float] = None) -> Optional[float]:
        if value is None:
            return default
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default
        if not np.isfinite(result):
            return default
        return result

    @staticmethod
    def _pair_max_stop_distance(pair: str) -> float:
        if pair.startswith("BTC/"):
            return 0.0068
        if pair.startswith("ETH/"):
            return 0.0096
        return 0.0

    @staticmethod
    def _pair_stake_cap(pair: str) -> float:
        return 18.0 if pair.startswith(("BTC/", "ETH/")) else 0.0

    @staticmethod
    def _pair_leverage(pair: str) -> float:
        if pair.startswith("BTC/"):
            return 20.0
        if pair.startswith("ETH/"):
            return 15.0
        return 1.0

    @staticmethod
    def _populate_15m_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["atr14"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["adx14"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["rsi14"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["donchian_high20"] = dataframe["high"].rolling(20).max().shift(1)
        dataframe["donchian_low20"] = dataframe["low"].rolling(20).min().shift(1)

        volume_mean = dataframe["volume"].rolling(20).mean()
        volume_std = dataframe["volume"].rolling(20).std(ddof=0).replace(0, np.nan)
        dataframe["volume_z20"] = ((dataframe["volume"] - volume_mean) / volume_std).replace(
            [np.inf, -np.inf], np.nan
        )

        typical_price = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3.0
        session = dataframe["date"].dt.floor("D")
        cumulative_volume = dataframe["volume"].groupby(session).cumsum().replace(0, np.nan)
        cumulative_price_volume = (typical_price * dataframe["volume"]).groupby(session).cumsum()
        dataframe["vwap"] = cumulative_price_volume / cumulative_volume

        dataframe["adx_rising"] = (
            (dataframe["adx14"] > dataframe["adx14"].shift(1))
            & (dataframe["adx14"].shift(1) > dataframe["adx14"].shift(2))
        )
        dataframe["long_structure_breakout"] = dataframe["close"] > dataframe["donchian_high20"]
        dataframe["short_structure_breakdown"] = dataframe["close"] < dataframe["donchian_low20"]
        return dataframe

    @staticmethod
    def _populate_1h_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["long_trend"] = (dataframe["close"] > dataframe["ema200"]) & (
            dataframe["ema50"] > dataframe["ema200"]
        )
        dataframe["short_trend"] = (dataframe["close"] < dataframe["ema200"]) & (
            dataframe["ema50"] < dataframe["ema200"]
        )
        return dataframe

    @staticmethod
    def _populate_4h_indicators(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["long_regime"] = dataframe["close"] >= dataframe["ema200"]
        dataframe["short_regime"] = dataframe["close"] <= dataframe["ema200"]
        return dataframe

    @staticmethod
    def _populate_funding_rate(dataframe: DataFrame) -> DataFrame:
        dataframe = dataframe.copy()
        rate_column = None
        for candidate in ("funding_rate", "fundingRate", "rate", "open", "close"):
            if candidate in dataframe.columns:
                rate_column = candidate
                break

        if rate_column is None:
            dataframe["funding_rate"] = np.nan
        else:
            dataframe["funding_rate"] = pd.to_numeric(dataframe[rate_column], errors="coerce")

        return dataframe[["date", "funding_rate"]]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rolling_low_12"] = dataframe["low"].rolling(self.pullback_window).min()
        dataframe["rolling_high_12"] = dataframe["high"].rolling(self.pullback_window).max()
        dataframe["max_stop_distance"] = self._pair_max_stop_distance(metadata["pair"])

        if not self.dp:
            return dataframe

        informative_15m = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="15m")
        informative_15m = self._populate_15m_indicators(informative_15m)
        dataframe = merge_informative_pair(
            dataframe, informative_15m, self.timeframe, "15m", ffill=True
        )

        informative_1h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1h")
        informative_1h = self._populate_1h_indicators(informative_1h)
        dataframe = merge_informative_pair(
            dataframe, informative_1h, self.timeframe, "1h", ffill=True
        )

        informative_4h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="4h")
        informative_4h = self._populate_4h_indicators(informative_4h)
        dataframe = merge_informative_pair(
            dataframe, informative_4h, self.timeframe, "4h", ffill=True
        )

        funding_1h = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe="1h", candle_type="funding_rate"
        )
        funding_1h = self._populate_funding_rate(funding_1h)
        dataframe = merge_informative_pair(
            dataframe,
            funding_1h,
            self.timeframe,
            "1h",
            ffill=True,
            append_timeframe=False,
            suffix="fr_1h",
        )

        dataframe["key_long_level"] = dataframe[
            ["donchian_high20_15m", "ema20_15m", "vwap_15m"]
        ].max(axis=1)
        dataframe["key_short_level"] = dataframe[
            ["donchian_low20_15m", "ema20_15m", "vwap_15m"]
        ].min(axis=1)

        dataframe["long_recent_breakout"] = (
            dataframe["long_structure_breakout_15m"]
            .fillna(False)
            .astype(int)
            .rolling(self.pullback_window)
            .max()
            > 0
        )
        dataframe["short_recent_breakdown"] = (
            dataframe["short_structure_breakdown_15m"]
            .fillna(False)
            .astype(int)
            .rolling(self.pullback_window)
            .max()
            > 0
        )

        dataframe["long_pullback_reclaim"] = (
            (dataframe["low"] <= dataframe["key_long_level"] * (1 + self.pullback_tolerance))
            & (dataframe["close"] > dataframe["key_long_level"])
            & (dataframe["close"] > dataframe["open"])
        )
        dataframe["short_pullback_reject"] = (
            (dataframe["high"] >= dataframe["key_short_level"] * (1 - self.pullback_tolerance))
            & (dataframe["close"] < dataframe["key_short_level"])
            & (dataframe["close"] < dataframe["open"])
        )

        dataframe["long_stop_rate"] = dataframe["rolling_low_12"] - (0.2 * dataframe["atr14_15m"])
        dataframe["short_stop_rate"] = dataframe["rolling_high_12"] + (0.2 * dataframe["atr14_15m"])

        dataframe["long_risk_pct"] = (
            (dataframe["close"] - dataframe["long_stop_rate"]) / dataframe["close"]
        )
        dataframe["short_risk_pct"] = (
            (dataframe["short_stop_rate"] - dataframe["close"]) / dataframe["close"]
        )
        dataframe["long_stop_valid"] = (
            (dataframe["max_stop_distance"] > 0)
            & (dataframe["long_risk_pct"] > 0)
            & (dataframe["long_risk_pct"] <= dataframe["max_stop_distance"])
        )
        dataframe["short_stop_valid"] = (
            (dataframe["max_stop_distance"] > 0)
            & (dataframe["short_risk_pct"] > 0)
            & (dataframe["short_risk_pct"] <= dataframe["max_stop_distance"])
        )

        dataframe["long_funding_ok"] = dataframe["funding_rate_fr_1h"] <= self.funding_limit
        dataframe["short_funding_ok"] = dataframe["funding_rate_fr_1h"] >= -self.funding_limit

        dataframe["long_score"] = (
            self._points(dataframe["long_trend_1h"], 20)
            + self._points(dataframe["long_regime_4h"], 10)
            + self._points(
                (dataframe["adx14_15m"] > self.adx_threshold) & dataframe["adx_rising_15m"], 10
            )
            + self._points(dataframe["long_structure_breakout_15m"], 15)
            + self._points(dataframe["long_pullback_reclaim"], 15)
            + self._points(dataframe["volume_z20_15m"] > self.volume_z_threshold, 10)
            + self._points((dataframe["rsi14_15m"] > 50) & (dataframe["rsi14_15m"] < 72), 10)
            + self._points(dataframe["long_funding_ok"], 10)
            + self._points(dataframe["long_stop_valid"], 10)
        )
        dataframe["short_score"] = (
            self._points(dataframe["short_trend_1h"], 20)
            + self._points(dataframe["short_regime_4h"], 10)
            + self._points(
                (dataframe["adx14_15m"] > self.adx_threshold) & dataframe["adx_rising_15m"], 10
            )
            + self._points(dataframe["short_structure_breakdown_15m"], 15)
            + self._points(dataframe["short_pullback_reject"], 15)
            + self._points(dataframe["volume_z20_15m"] > self.volume_z_threshold, 10)
            + self._points((dataframe["rsi14_15m"] > 28) & (dataframe["rsi14_15m"] < 50), 10)
            + self._points(dataframe["short_funding_ok"], 10)
            + self._points(dataframe["short_stop_valid"], 10)
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["volume"] > 0)
                & dataframe["funding_rate_fr_1h"].notna()
                & dataframe["long_recent_breakout"]
                & dataframe["long_stop_valid"]
                & (dataframe["long_score"] >= 80)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "lsri_long_pullback_s80")

        dataframe.loc[
            (
                (dataframe["volume"] > 0)
                & dataframe["funding_rate_fr_1h"].notna()
                & dataframe["short_recent_breakdown"]
                & dataframe["short_stop_valid"]
                & (dataframe["short_score"] >= 80)
            ),
            ["enter_short", "enter_tag"],
        ] = (1, "lsri_short_pullback_s80")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        stake_cap = self._pair_stake_cap(pair)
        if stake_cap <= 0:
            return 0
        return min(proposed_stake, max_stake, stake_cap)

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        return min(self._pair_leverage(pair), max_leverage)

    def _entry_candle_for_trade(self, trade: Trade) -> Optional[pd.Series]:
        if not self.dp:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        if dataframe.empty:
            return None
        entry_rows = dataframe.loc[dataframe["date"] <= trade.open_date_utc]
        if entry_rows.empty:
            return dataframe.iloc[-1].squeeze()
        return entry_rows.iloc[-1].squeeze()

    def _ensure_trade_plan(self, trade: Trade) -> bool:
        if trade.get_custom_data("initial_stop_rate") is not None:
            return True

        entry_candle = self._entry_candle_for_trade(trade)
        if entry_candle is None:
            return False

        stop_column = "short_stop_rate" if trade.is_short else "long_stop_rate"
        stop_rate = self._safe_float(entry_candle.get(stop_column))
        entry_rate = self._safe_float(trade.open_rate)
        if stop_rate is None or entry_rate is None:
            return False

        risk_rate = abs(entry_rate - stop_rate)
        if risk_rate <= 0:
            return False

        if trade.is_short:
            take_profit_rate = entry_rate - (self.take_profit_r * risk_rate)
            half_r_rate = entry_rate - (self.time_stop_r * risk_rate)
        else:
            take_profit_rate = entry_rate + (self.take_profit_r * risk_rate)
            half_r_rate = entry_rate + (self.time_stop_r * risk_rate)

        trade.set_custom_data("initial_stop_rate", stop_rate)
        trade.set_custom_data("risk_rate", risk_rate)
        trade.set_custom_data("take_profit_rate", take_profit_rate)
        trade.set_custom_data("half_r_rate", half_r_rate)
        return True

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> Optional[float]:
        if not self._ensure_trade_plan(trade):
            return None

        stop_rate = self._safe_float(trade.get_custom_data("initial_stop_rate"))
        risk_rate = self._safe_float(trade.get_custom_data("risk_rate"))
        entry_rate = self._safe_float(trade.open_rate)
        if stop_rate is None or risk_rate is None or entry_rate is None:
            return None

        fee_buffer = self.fee_buffer_pct * entry_rate

        if trade.is_short:
            if current_rate <= entry_rate - (1.6 * risk_rate):
                stop_rate = min(stop_rate, entry_rate - (0.8 * risk_rate))
            elif current_rate <= entry_rate - risk_rate:
                stop_rate = min(stop_rate, entry_rate - fee_buffer)
        else:
            if current_rate >= entry_rate + (1.6 * risk_rate):
                stop_rate = max(stop_rate, entry_rate + (0.8 * risk_rate))
            elif current_rate >= entry_rate + risk_rate:
                stop_rate = max(stop_rate, entry_rate + fee_buffer)

        return stoploss_from_absolute(
            stop_rate,
            current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        if not self._ensure_trade_plan(trade):
            return None

        take_profit_rate = self._safe_float(trade.get_custom_data("take_profit_rate"))
        half_r_rate = self._safe_float(trade.get_custom_data("half_r_rate"))
        if take_profit_rate is None or half_r_rate is None:
            return None

        if trade.is_short:
            if current_rate <= take_profit_rate:
                return "short_tp_2_2r"
        else:
            if current_rate >= take_profit_rate:
                return "long_tp_2_2r"

        trade_duration_minutes = (current_time - trade.open_date_utc).total_seconds() / 60
        if trade_duration_minutes >= self.time_stop_minutes:
            if trade.is_short and current_rate > half_r_rate:
                return "time_stop_no_impulse"
            if not trade.is_short and current_rate < half_r_rate:
                return "time_stop_no_impulse"

        return None
```

- [ ] **Step 3: Verify strategy loads**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose run --rm freqtrade-futures list-strategies `
  --config /freqtrade/user_data/config.lsri.futures.20u.json `
  --strategy-path /freqtrade/user_data/strategies `
  -1 | Select-String -Pattern 'LSRICoreStrategy'
```

Expected:

```text
LSRICoreStrategy
```

- [ ] **Step 4: Commit strategy**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add ft_userdata/user_data/strategies/LSRICoreStrategy.py
git commit -m "feat: add lsri core strategy"
```

Expected:

```text
Commit succeeds and includes only LSRICoreStrategy.py.
```

## Task 4: Run A Short Smoke Backtest

**Files:**
- Read: `ft_userdata/user_data/strategies/LSRICoreStrategy.py`
- Read: `ft_userdata/user_data/config.lsri.futures.20u.json`
- Output: `ft_userdata/user_data/backtest_results/*.zip`

- [ ] **Step 1: Run the smoke backtest**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose run --rm freqtrade-futures backtesting `
  --config /freqtrade/user_data/config.lsri.futures.20u.json `
  --strategy LSRICoreStrategy `
  --timerange 20240101-20240301
```

Expected:

```text
Backtesting completes without strategy loading errors, missing 15m or 4h data errors, or missing funding-rate data errors.
```

- [ ] **Step 2: If the smoke backtest reports missing 5m mark or funding data**

Run this command only when the smoke backtest explicitly reports missing futures auxiliary data:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose run --rm freqtrade-futures download-data `
  --config /freqtrade/user_data/config.lsri.futures.20u.json `
  --trading-mode futures `
  --pairs BTC/USDT:USDT ETH/USDT:USDT `
  --timeframes 5m 1h `
  --timerange 20240101-20260701
```

Expected:

```text
Download completes, then Step 1 succeeds on rerun.
```

- [ ] **Step 3: Confirm a result zip was created**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
Get-ChildItem -LiteralPath 'ft_userdata\user_data\backtest_results' -Filter '*.zip' |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 3 Name,LastWriteTime,Length
```

Expected:

```text
The newest result zip has LastWriteTime after the smoke backtest started.
```

## Task 5: Inspect Smoke Backtest Behavior

**Files:**
- Read: latest `ft_userdata/user_data/backtest_results/*.zip`

- [ ] **Step 1: Print a compact behavior summary**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
@'
import json
import zipfile
from pathlib import Path

result_dir = Path("ft_userdata/user_data/backtest_results")
zip_path = max(result_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime)

with zipfile.ZipFile(zip_path) as archive:
    json_name = [name for name in archive.namelist() if name.endswith(".json") and "_config" not in name][0]
    payload = json.loads(archive.read(json_name))

strategy_name = next(iter(payload["strategy"]))
strategy = payload["strategy"][strategy_name]
trades = strategy.get("trades", [])
exit_reasons = {}
pairs = {}
max_leverage = {}

for trade in trades:
    exit_reasons[trade.get("exit_reason", "unknown")] = exit_reasons.get(trade.get("exit_reason", "unknown"), 0) + 1
    pairs[trade["pair"]] = pairs.get(trade["pair"], 0) + 1
    leverage = trade.get("leverage")
    if leverage is not None:
        max_leverage[trade["pair"]] = max(max_leverage.get(trade["pair"], 0), leverage)

print(f"zip={zip_path.name}")
print(f"strategy={strategy_name}")
print(f"total_trades={len(trades)}")
print(f"pairs={pairs}")
print(f"exit_reasons={exit_reasons}")
print(f"max_leverage={max_leverage}")
print(f"profit_total_abs={strategy.get('profit_total_abs')}")
print(f"max_drawdown_abs={strategy.get('max_drawdown_abs')}")
'@ | docker compose run --rm -T freqtrade-futures python -
```

Expected:

```text
The script prints strategy=LSRICoreStrategy.
pairs contains only BTC/USDT:USDT and ETH/USDT:USDT when trades exist.
max_leverage shows BTC at or below 20 and ETH at or below 15 when trades exist.
```

- [ ] **Step 2: Decide whether low or zero trade count is acceptable for the smoke range**

Acceptable:

```text
0 trades or very few trades in the two-month smoke range.
```

Reason:

```text
The smoke range is for loading and behavior checks, not performance evaluation.
```

Unacceptable:

```text
Strategy loading errors, missing required columns, non-BTC/ETH trades, or leverage above configured pair caps.
```

## Task 6: Run The Full Baseline Backtest

**Files:**
- Read: `ft_userdata/user_data/strategies/LSRICoreStrategy.py`
- Read: `ft_userdata/user_data/config.lsri.futures.20u.json`
- Output: `ft_userdata/user_data/backtest_results/*.zip`

- [ ] **Step 1: Run full timerange backtest**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose run --rm freqtrade-futures backtesting `
  --config /freqtrade/user_data/config.lsri.futures.20u.json `
  --strategy LSRICoreStrategy `
  --timerange 20240101-20260701
```

Expected:

```text
Backtesting completes and creates a new result zip.
```

- [ ] **Step 2: Print full-result behavior and performance summary**

Run the same summary script from Task 5 Step 1.

Expected:

```text
The result prints total trades, pair distribution, exit reasons, leverage summary, total profit, and max drawdown.
Entries before the first available funding-rate candle are blocked by design, so the effective signal window starts when funding-rate data is available.
```

- [ ] **Step 3: Check first-pass behavior acceptance**

Pass criteria:

```text
Only BTC/USDT:USDT and ETH/USDT:USDT appear in trades.
BTC leverage does not exceed 20.
ETH leverage does not exceed 15.
Exit reasons include long_tp_2_2r, short_tp_2_2r, time_stop_no_impulse, stop_loss, or trailing/custom stoploss behavior when trades exist.
force_exit is not the dominant exit reason except when there are too few trades for a meaningful distribution.
```

Failure criteria:

```text
Non-whitelisted pairs appear.
Leverage exceeds caps.
Most trades exit only by force_exit.
Backtest cannot finish because informative columns or funding columns are missing.
```

## Task 7: Optional UI Validation On Port 8003

**Files:**
- Read: `ft_userdata/user_data/backtest_results/*.zip`
- Browser: `http://127.0.0.1:8003/backtest`

- [ ] **Step 1: Confirm current webserver is reachable**

Open:

```text
http://127.0.0.1:8003/backtest
```

Expected:

```text
Backtest page loads.
```

- [ ] **Step 2: Use UI to load the latest LSRI result**

In FreqUI:

```text
Backtest -> Load Results -> choose the latest result containing LSRICoreStrategy -> Load
```

Expected:

```text
Summary charts and result tables render.
```

- [ ] **Step 3: Validate UI behavior**

Expected:

```text
The result list shows the LSRI backtest result.
Pair stats show only BTC/USDT:USDT and ETH/USDT:USDT when trades exist.
Trade rows show LSRI entry tags where trades exist.
Exit reason summary shows R-based TP, time stop, or stoploss exits where trades exist.
No empty-result UI error appears unless the backtest genuinely produced zero trades.
```

## Task 8: Final Commit And Handoff Summary

**Files:**
- Commit: `ft_userdata/user_data/config.lsri.futures.20u.json`
- Commit: `ft_userdata/user_data/strategies/LSRICoreStrategy.py`
- Do not commit: downloaded market data, backtest result zips, screenshots, database files, or unrelated dirty files.

- [ ] **Step 1: Review LSRI-related git status**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git status --short -- ft_userdata/user_data/config.lsri.futures.20u.json ft_userdata/user_data/strategies/LSRICoreStrategy.py
```

Expected after Tasks 2 and 3 commits:

```text
No output.
```

- [ ] **Step 2: Review recent commits**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git log --oneline -3
```

Expected:

```text
One commit for the LSRI config.
One commit for the LSRI strategy.
The earlier docs commit for the LSRI design may appear below them.
```

- [ ] **Step 3: Final response content**

The final implementation response should include:

```text
Files created.
Data downloaded or data still missing.
Smoke backtest result.
Full backtest result.
Behavior checks: pairs, leverage, exit reasons, force_exit ratio.
Any tests or commands that could not be run.
```

Do not claim the strategy is profitable unless the full backtest output supports that statement.

## Plan Self-Review

Spec coverage:

- Independent strategy and config are covered by Tasks 2 and 3.
- Required 15m and 4h data are covered by Task 1.
- `5m` main timeframe and informative `15m`, `1h`, `4h`, `1h funding_rate` are covered by Task 3.
- Entry scoring, funding-rate filter, stop distance checks, pair leverage, fixed stake, no position adjustment, custom stoploss, 2.2R exit, and time stop are covered by Task 3.
- Smoke and full backtests are covered by Tasks 4 through 6.
- UI validation is covered by Task 7.

Implementation clarification:

- The strategy uses `startup_candle_count = 240`. Freqtrade backtesting stores this value in config and the data provider subtracts startup history per requested informative timeframe, so the 4h informative dataframe gets 240 candles of 4h warmup history for EMA200.
- The available Freqtrade OKX funding-rate feather files store actual funding values in `open`; `close` is zero. The strategy parser therefore checks `open` before `close` so the funding crowding filter is not silently disabled.

Placeholder scan:

- This plan intentionally contains no open placeholder markers.

Type consistency:

- Strategy class name, config file name, command paths, and entry/exit tags are consistent across tasks.
