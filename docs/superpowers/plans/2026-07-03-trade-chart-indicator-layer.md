# Trade Chart Indicator Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Trade-page chart data path where users can switch chart timeframes, see default watch indicators, and overlay active strategy indicators without changing the running bot strategy or execution settings.

**Architecture:** Add a backend-owned `/api/v1/chart_candles` endpoint that loads live OHLCV for the selected chart timeframe, calculates watch indicators, and overlays the running strategy dataframe at the strategy timeframe. Keep `CandleChart` as the renderer and adapt only the Trade-page data path and container props so Graph, Dashboard, backtesting, `/pair_candles`, and `/pair_history` keep existing behavior.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pandas, TA-Lib, Freqtrade RPC/API server, Vue 3, Pinia, TypeScript, Vitest, Playwright.

---

## Assumptions And Boundaries

- Worktree root is `G:\AI_Trading\freqtrade-cn`.
- The first product surface is only `frequi/src/views/TradingView.vue`.
- `ChartsView`, backtesting charts, Dashboard, Graph, `/pair_candles`, and `/pair_history` are not semantically changed.
- The active bot strategy timeframe remains the source of truth for strategy overlay columns. For `VolatilitySystem`, that is `1h`.
- Watch indicators are calculated from the user-selected chart timeframe and do not affect bot configuration, strategy code, orders, or bot state.
- First-version chart indicators are MA20, MA60, RSI14, MACD12/26/9, and existing volume.
- First-version timeframe choices in Trade are `1m`, `15m`, `30m`, `1h`, `2h`, `4h`, `1d`.
- First-version strategy overlay is enabled by default.
- First-version data loading uses the active bot exchange and does not add a custom cache.

## File Map

### Backend

- Create `freqtrade/freqtrade/rpc/chart_indicators.py`
  - Owns default watch indicator configuration, watch indicator calculation, and watch plot config generation.
- Create `freqtrade/freqtrade/rpc/chart_data.py`
  - Owns live chart OHLCV loading, limit trimming, strategy overlay extraction, timeframe alignment, plot config merge, and response building.
- Create `freqtrade/freqtrade/rpc/api_server/api_chart.py`
  - Owns the FastAPI route for `POST /api/v1/chart_candles`.
- Modify `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
  - Adds request/response models for chart candles and overlay metadata.
- Modify `freqtrade/freqtrade/rpc/api_server/webserver.py`
  - Registers `api_chart` in trading mode.
- Modify `freqtrade/freqtrade/rpc/api_server/api_v1.py`
  - Bumps `API_VERSION` from `2.49` to `2.50` and documents the endpoint.
- Add `freqtrade/tests/rpc/test_chart_indicators.py`
  - Unit tests for watch indicator columns and plot config.
- Add `freqtrade/tests/rpc/test_chart_data.py`
  - Unit tests for loading, trimming, overlay alignment, overlay hiding, and overlay failure warnings.
- Modify `freqtrade/tests/rpc/test_rpc_apiserver.py`
  - API tests for `/chart_candles` routing, validation, feature version, and response shape.

### Frontend

- Modify `frequi/src/types/candleTypes.ts`
  - Adds `ChartCandlesPayload`, `ChartOverlayMeta`, and `ChartCandlesResponse`.
- Modify `frequi/src/types/features.ts`
  - Adds `chartCandles` feature flag at API version `2.50`.
- Modify `frequi/src/stores/ftbot.ts`
  - Adds chart candle state and `getChartCandles`; uses it for Trade-page chart data only.
- Create `frequi/src/stores/tradeChart.ts`
  - Owns Trade-page chart timeframe and strategy overlay toggle.
- Modify `frequi/src/components/charts/CandleChartContainer.vue`
  - Adds optional props for chart data source, plot config override, status text, warning text, and timeframe selector slot.
- Modify `frequi/src/components/charts/SingleCandleChartContainer.vue`
  - Reads the optional chart data source, renders the optional plot config override, and shows non-blocking warnings.
- Modify `frequi/src/views/TradingView.vue`
  - Uses Trade chart store, calls `getChartCandles`, supplies selected chart timeframe, and displays the timeframe selector.
- Modify `frequi/src/locales/en.ts`
  - Adds English labels for chart timeframe and overlay status.
- Modify `frequi/src/locales/zh-CN.ts`
  - Adds Chinese labels for chart timeframe and overlay status.
- Modify `frequi/e2e/helpers.ts`
  - Adds a mock route for `/api/v1/chart_candles` and updates `show_config` fixture feature version.
- Add `frequi/e2e/testData/chart_candles_btc_15m.json`
  - Fixture with watch columns, overlay metadata, plot config, and no warnings.
- Add `frequi/e2e/testData/chart_candles_btc_4h_warning.json`
  - Fixture with watch columns, hidden overlay metadata, plot config, and overlay warning.
- Modify `frequi/e2e/trade.spec.ts`
  - Adds Trade chart assertions for new endpoint, timeframe switch, and overlay warning.
- Add `frequi/tests/unit/tradeChart.spec.ts`
  - Unit tests for default/reset behavior in the Trade chart store.
- Add `frequi/tests/unit/chartCandleTypes.spec.ts`
  - Type-shape utility assertions for effective plot config data, if a utility is introduced in Task 8.

## Task 1: Backend Schemas And API Version

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_v1.py`
- Test: `freqtrade/tests/rpc/test_rpc_apiserver.py`

- [ ] **Step 1: Add failing schema and version tests**

Append these tests near the existing `test_api_pair_candles` and `test_api_pair_history_live_mode` tests in `freqtrade/tests/rpc/test_rpc_apiserver.py`:

```python
def test_chart_candles_schema_validation(botclient):
    _ftbot, client = botclient

    rc = client_post(client, f"{BASE_URI}/chart_candles", data={"timeframe": "15m"})
    assert_response(rc, 422)

    rc = client_post(
        client,
        f"{BASE_URI}/chart_candles",
        data={"pair": "XRP/BTC", "timeframe": "15m", "limit": 2001},
    )
    assert_response(rc, 422)

    rc = client_post(
        client,
        f"{BASE_URI}/chart_candles",
        data={
            "pair": "XRP/BTC",
            "timeframe": "15m",
            "watch_indicators": {"macd": [{"fast": 26, "slow": 12, "signal": 9}]},
        },
    )
    assert_response(rc, 422)


def test_show_config_api_version_has_chart_candles(botclient):
    _ftbot, client = botclient

    rc = client_get(client, f"{BASE_URI}/show_config")
    assert_response(rc)
    assert rc.json()["api_version"] == 2.50
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_rpc_apiserver.py::test_chart_candles_schema_validation tests/rpc/test_rpc_apiserver.py::test_show_config_api_version_has_chart_candles -q
```

Expected:

```text
FAILED tests/rpc/test_rpc_apiserver.py::test_chart_candles_schema_validation
FAILED tests/rpc/test_rpc_apiserver.py::test_show_config_api_version_has_chart_candles
```

The first failure is acceptable as `404` until the route is added in Task 4. The second failure should show `2.49 != 2.5`.

- [ ] **Step 3: Add chart schema models**

In `freqtrade/freqtrade/rpc/api_server/api_schemas.py`, add `model_validator` to the Pydantic import if it is not already imported:

```python
from pydantic import BaseModel, Field, RootModel, SerializeAsAny, model_validator
```

Insert these models immediately after `PairCandlesRequest`:

```python
class MacdIndicatorRequest(BaseModel):
    fast: int = Field(default=12, ge=1, le=200)
    slow: int = Field(default=26, ge=1, le=300)
    signal: int = Field(default=9, ge=1, le=100)

    @model_validator(mode="after")
    def validate_period_order(self):
        if self.slow <= self.fast:
            raise ValueError("MACD slow period must be greater than fast period.")
        return self


class ChartIndicatorRequest(BaseModel):
    ma: list[int] = Field(default_factory=lambda: [20, 60])
    rsi: list[int] = Field(default_factory=lambda: [14])
    macd: list[MacdIndicatorRequest] = Field(default_factory=lambda: [MacdIndicatorRequest()])

    @model_validator(mode="after")
    def validate_indicator_periods(self):
        if any(period < 1 or period > 500 for period in self.ma):
            raise ValueError("MA periods must be between 1 and 500.")
        if any(period < 1 or period > 500 for period in self.rsi):
            raise ValueError("RSI periods must be between 1 and 500.")
        return self


class ChartCandlesRequest(BaseModel):
    pair: str
    timeframe: str
    limit: int = Field(default=500, ge=1, le=2000)
    watch_indicators: ChartIndicatorRequest | None = None
    include_strategy_overlay: bool = True


class ChartOverlayMeta(BaseModel):
    strategy_timeframe: str
    alignment: str
    columns: list[str] = Field(default_factory=list)
    hidden: bool = False
    warning: str | None = None
```

Insert this response model immediately after `PairHistory`:

```python
class ChartCandlesResponse(PairHistory):
    chart_timeframe: str
    strategy_timeframe: str | None = None
    overlay: ChartOverlayMeta | None = None
    plot_config: PlotConfig
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Bump API version**

In `freqtrade/freqtrade/rpc/api_server/api_v1.py`, add a version history line under the `2.49` comment:

```python
# 2.50: Add /chart_candles Trade chart indicator layer endpoint
```

Change:

```python
API_VERSION = 2.49
```

to:

```python
API_VERSION = 2.50
```

- [ ] **Step 5: Run version test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_rpc_apiserver.py::test_show_config_api_version_has_chart_candles -q
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add freqtrade/freqtrade/rpc/api_server/api_schemas.py freqtrade/freqtrade/rpc/api_server/api_v1.py freqtrade/tests/rpc/test_rpc_apiserver.py
git commit -m "feat: add chart candles api schemas"
```

## Task 2: Backend Watch Indicator Engine

**Files:**
- Create: `freqtrade/freqtrade/rpc/chart_indicators.py`
- Test: `freqtrade/tests/rpc/test_chart_indicators.py`

- [ ] **Step 1: Write failing indicator tests**

Create `freqtrade/tests/rpc/test_chart_indicators.py`:

```python
import pytest

from freqtrade.rpc.api_server.api_schemas import ChartIndicatorRequest, MacdIndicatorRequest
from freqtrade.rpc.chart_indicators import add_watch_indicators, build_watch_plot_config
from tests.conftest import generate_test_data


def test_add_watch_indicators_uses_default_columns():
    dataframe = generate_test_data("15m", 120, "2024-01-01 00:00:00+00:00")

    result = add_watch_indicators(dataframe)

    assert list(dataframe.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert "watch_ma20" in result.columns
    assert "watch_ma60" in result.columns
    assert "watch_rsi14" in result.columns
    assert "watch_macd" in result.columns
    assert "watch_macdsignal" in result.columns
    assert "watch_macdhist" in result.columns
    assert result["watch_ma20"].notna().sum() > 0
    assert result["watch_ma60"].notna().sum() > 0
    assert result["watch_rsi14"].notna().sum() > 0
    assert result["watch_macd"].notna().sum() > 0


def test_add_watch_indicators_accepts_custom_periods():
    dataframe = generate_test_data("15m", 80, "2024-01-01 00:00:00+00:00")
    indicators = ChartIndicatorRequest(
        ma=[10],
        rsi=[7],
        macd=[MacdIndicatorRequest(fast=5, slow=13, signal=4)],
    )

    result = add_watch_indicators(dataframe, indicators)

    assert "watch_ma10" in result.columns
    assert "watch_ma20" not in result.columns
    assert "watch_rsi7" in result.columns
    assert "watch_macd_5_13_4" in result.columns
    assert "watch_macdsignal_5_13_4" in result.columns
    assert "watch_macdhist_5_13_4" in result.columns


def test_build_watch_plot_config_matches_default_columns():
    plot_config = build_watch_plot_config()

    assert set(plot_config["main_plot"]) == {"watch_ma20", "watch_ma60"}
    assert set(plot_config["subplots"]["RSI 14"]) == {"watch_rsi14"}
    assert set(plot_config["subplots"]["MACD"]) == {
        "watch_macd",
        "watch_macdsignal",
        "watch_macdhist",
    }
    assert plot_config["subplots"]["MACD"]["watch_macdhist"]["type"] == "bar"


def test_invalid_macd_period_order_fails_schema():
    with pytest.raises(ValueError, match="slow period"):
        MacdIndicatorRequest(fast=26, slow=12, signal=9)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_chart_indicators.py -q
```

Expected:

```text
FAILED tests/rpc/test_chart_indicators.py::test_add_watch_indicators_uses_default_columns
```

The import should fail until `chart_indicators.py` exists.

- [ ] **Step 3: Implement watch indicator engine**

Create `freqtrade/freqtrade/rpc/chart_indicators.py`:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any

from pandas import DataFrame
import talib.abstract as ta

from freqtrade.rpc.api_server.api_schemas import ChartIndicatorRequest


DEFAULT_WATCH_PLOT_CONFIG: dict[str, Any] = {
    "main_plot": {
        "watch_ma20": {"color": "#3b82f6"},
        "watch_ma60": {"color": "#f59e0b"},
    },
    "subplots": {
        "RSI 14": {
            "watch_rsi14": {"color": "#a855f7"},
        },
        "MACD": {
            "watch_macd": {"color": "#2563eb"},
            "watch_macdsignal": {"color": "#f97316"},
            "watch_macdhist": {"type": "bar", "color": "#22c55e"},
        },
    },
}


def get_default_watch_indicators() -> ChartIndicatorRequest:
    return ChartIndicatorRequest()


def _macd_suffix(fast: int, slow: int, signal: int) -> str:
    if (fast, slow, signal) == (12, 26, 9):
        return ""
    return f"_{fast}_{slow}_{signal}"


def add_watch_indicators(
    dataframe: DataFrame,
    indicators: ChartIndicatorRequest | None = None,
) -> DataFrame:
    indicator_request = indicators or get_default_watch_indicators()
    result = dataframe.copy()

    for period in indicator_request.ma:
        result[f"watch_ma{period}"] = ta.SMA(result, timeperiod=period)

    for period in indicator_request.rsi:
        result[f"watch_rsi{period}"] = ta.RSI(result, timeperiod=period)

    for macd_request in indicator_request.macd:
        suffix = _macd_suffix(macd_request.fast, macd_request.slow, macd_request.signal)
        macd_values = ta.MACD(
            result,
            fastperiod=macd_request.fast,
            slowperiod=macd_request.slow,
            signalperiod=macd_request.signal,
        )
        result[f"watch_macd{suffix}"] = macd_values["macd"]
        result[f"watch_macdsignal{suffix}"] = macd_values["macdsignal"]
        result[f"watch_macdhist{suffix}"] = macd_values["macdhist"]

    return result


def build_watch_plot_config(
    indicators: ChartIndicatorRequest | None = None,
) -> dict[str, Any]:
    indicator_request = indicators or get_default_watch_indicators()
    if indicator_request == get_default_watch_indicators():
        return deepcopy(DEFAULT_WATCH_PLOT_CONFIG)

    plot_config: dict[str, Any] = {"main_plot": {}, "subplots": {}}

    for period in indicator_request.ma:
        plot_config["main_plot"][f"watch_ma{period}"] = {}

    for period in indicator_request.rsi:
        plot_config["subplots"][f"RSI {period}"] = {f"watch_rsi{period}": {}}

    for macd_request in indicator_request.macd:
        suffix = _macd_suffix(macd_request.fast, macd_request.slow, macd_request.signal)
        label = f"MACD {macd_request.fast}/{macd_request.slow}/{macd_request.signal}"
        plot_config["subplots"][label] = {
            f"watch_macd{suffix}": {},
            f"watch_macdsignal{suffix}": {},
            f"watch_macdhist{suffix}": {"type": "bar"},
        }

    return plot_config
```

- [ ] **Step 4: Run indicator tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_chart_indicators.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add freqtrade/freqtrade/rpc/chart_indicators.py freqtrade/tests/rpc/test_chart_indicators.py
git commit -m "feat: add trade chart watch indicators"
```

## Task 3: Backend Chart Data Service

**Files:**
- Create: `freqtrade/freqtrade/rpc/chart_data.py`
- Test: `freqtrade/tests/rpc/test_chart_data.py`

- [ ] **Step 1: Write failing chart data tests**

Create `freqtrade/tests/rpc/test_chart_data.py`:

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pandas as pd

from freqtrade.enums import CandleType
from freqtrade.rpc.api_server.api_schemas import ChartCandlesRequest
from freqtrade.rpc.chart_data import (
    build_chart_candles_response,
    load_chart_ohlcv,
    merge_strategy_overlay,
)
from tests.conftest import generate_test_data


def test_load_chart_ohlcv_uses_limit_and_warmup(mocker):
    exchange = MagicMock()
    exchange.get_historic_ohlcv.return_value = generate_test_data(
        "15m", 700, "2024-01-01 00:00:00+00:00"
    )
    config = {"candle_type_def": CandleType.SPOT}

    result = load_chart_ohlcv(exchange, config, "BTC/USDT", "15m", 500)

    assert len(result) == 500
    assert list(result.columns) == ["date", "open", "high", "low", "close", "volume"]
    exchange.get_historic_ohlcv.assert_called_once()
    _, kwargs = exchange.get_historic_ohlcv.call_args
    assert kwargs["pair"] == "BTC/USDT"
    assert kwargs["timeframe"] == "15m"
    assert kwargs["candle_type"] == CandleType.SPOT
    assert kwargs["is_new_pair"] is True


def test_merge_strategy_overlay_forward_fills_lower_chart_timeframe():
    chart_df = generate_test_data("15m", 8, "2024-01-01 10:00:00+00:00")
    strategy_df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2024-01-01 10:00:00+00:00", "2024-01-01 11:00:00+00:00"],
                utc=True,
            ),
            "atr": [120.0, 135.0],
            "abs_close_change": [5.0, 8.0],
            "enter_long": [1, 0],
            "exit_long": [0, 0],
            "enter_short": [0, 1],
            "exit_short": [0, 0],
        }
    )

    result, overlay, warnings = merge_strategy_overlay(
        chart_df,
        strategy_df,
        chart_timeframe="15m",
        strategy_timeframe="1h",
        strategy_plot_config={
            "main_plot": {},
            "subplots": {"Volatility system": {"atr": {}, "abs_close_change": {}}},
        },
    )

    assert warnings == []
    assert overlay.hidden is False
    assert overlay.alignment == "forward_fill"
    assert overlay.columns == ["strategy_1h_atr", "strategy_1h_abs_close_change"]
    assert result.loc[0, "strategy_1h_atr"] == 120.0
    assert result.loc[3, "strategy_1h_atr"] == 120.0
    assert result.loc[4, "strategy_1h_atr"] == 135.0
    assert result.loc[0, "enter_long"] == 1
    assert result.loc[4, "enter_short"] == 1


def test_merge_strategy_overlay_direct_aligns_equal_timeframe():
    chart_df = generate_test_data("1h", 2, "2024-01-01 10:00:00+00:00")
    strategy_df = chart_df[["date"]].copy()
    strategy_df["atr"] = [120.0, 135.0]

    result, overlay, warnings = merge_strategy_overlay(
        chart_df,
        strategy_df,
        chart_timeframe="1h",
        strategy_timeframe="1h",
        strategy_plot_config={"main_plot": {"atr": {}}, "subplots": {}},
    )

    assert warnings == []
    assert overlay.alignment == "direct"
    assert result["strategy_1h_atr"].tolist() == [120.0, 135.0]


def test_merge_strategy_overlay_hides_continuous_overlay_for_higher_chart_timeframe():
    chart_df = generate_test_data("4h", 2, "2024-01-01 00:00:00+00:00")
    strategy_df = generate_test_data("1h", 8, "2024-01-01 00:00:00+00:00")
    strategy_df["atr"] = range(8)

    result, overlay, warnings = merge_strategy_overlay(
        chart_df,
        strategy_df,
        chart_timeframe="4h",
        strategy_timeframe="1h",
        strategy_plot_config={"main_plot": {"atr": {}}, "subplots": {}},
    )

    assert "strategy_1h_atr" not in result.columns
    assert overlay.hidden is True
    assert overlay.alignment == "hidden"
    assert warnings == ["Strategy overlay hidden: chart timeframe is higher than strategy timeframe."]


def test_build_chart_candles_response_returns_watch_data_when_overlay_fails(mocker):
    chart_df = generate_test_data("15m", 150, "2024-01-01 00:00:00+00:00")
    rpc = MagicMock()
    rpc._freqtrade.exchange.get_historic_ohlcv.return_value = chart_df
    rpc._freqtrade.config = {
        "strategy": "StrategyUnderTest",
        "timeframe": "1h",
        "candle_type_def": CandleType.SPOT,
    }
    rpc._freqtrade.strategy.plot_config = {"main_plot": {"atr": {}}, "subplots": {}}
    rpc._freqtrade.dataprovider.get_analyzed_dataframe.side_effect = RuntimeError("overlay down")
    request = ChartCandlesRequest(pair="BTC/USDT", timeframe="15m", limit=50)

    response = build_chart_candles_response(rpc, rpc._freqtrade.config, request)

    assert response["pair"] == "BTC/USDT"
    assert response["chart_timeframe"] == "15m"
    assert response["strategy_timeframe"] == "1h"
    assert response["length"] == 50
    assert "watch_ma20" in response["columns"]
    assert any("Strategy overlay unavailable" in warning for warning in response["warnings"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_chart_data.py -q
```

Expected:

```text
FAILED tests/rpc/test_chart_data.py::test_load_chart_ohlcv_uses_limit_and_warmup
```

The import should fail until `chart_data.py` exists.

- [ ] **Step 3: Implement chart data service**

Create `freqtrade/freqtrade/rpc/chart_data.py`:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any

from pandas import DataFrame, merge_asof

from freqtrade.constants import DEFAULT_DATAFRAME_COLUMNS
from freqtrade.enums import CandleType
from freqtrade.exchange import timeframe_to_msecs
from freqtrade.rpc import RPC
from freqtrade.rpc.api_server.api_schemas import (
    ChartCandlesRequest,
    ChartOverlayMeta,
)
from freqtrade.rpc.chart_indicators import add_watch_indicators, build_watch_plot_config
from freqtrade.util.datetime_helpers import dt_now, dt_ts


CHART_WARMUP_CANDLES = 120
SIGNAL_COLUMNS = ["enter_long", "exit_long", "enter_short", "exit_short"]


def _empty_signals(dataframe: DataFrame) -> DataFrame:
    result = dataframe.copy()
    for column in SIGNAL_COLUMNS:
        if column not in result.columns:
            result[column] = 0
    return result


def _plot_config_columns(plot_config: dict[str, Any]) -> list[str]:
    columns: list[str] = []
    for column in plot_config.get("main_plot", {}):
        columns.append(column)
    for subplot in plot_config.get("subplots", {}).values():
        for column in subplot:
            columns.append(column)
    return columns


def _prefix_strategy_column(strategy_timeframe: str, column: str) -> str:
    return f"strategy_{strategy_timeframe}_{column}"


def _prefix_strategy_plot_config(
    strategy_timeframe: str,
    strategy_plot_config: dict[str, Any],
    overlay_columns: list[str],
) -> dict[str, Any]:
    if not overlay_columns:
        return {"main_plot": {}, "subplots": {}}

    prefixed: dict[str, Any] = {"main_plot": {}, "subplots": {}}
    overlay_set = set(overlay_columns)
    for column, config in strategy_plot_config.get("main_plot", {}).items():
        if column in overlay_set:
            prefixed["main_plot"][_prefix_strategy_column(strategy_timeframe, column)] = config

    for subplot_name, subplot in strategy_plot_config.get("subplots", {}).items():
        prefixed_subplot = {}
        for column, config in subplot.items():
            if column in overlay_set:
                prefixed_subplot[_prefix_strategy_column(strategy_timeframe, column)] = config
        if prefixed_subplot:
            prefixed["subplots"][f"Strategy overlay {strategy_timeframe}: {subplot_name}"] = (
                prefixed_subplot
            )

    return prefixed


def merge_plot_config(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(left)
    result.setdefault("main_plot", {}).update(right.get("main_plot", {}))
    result.setdefault("subplots", {}).update(right.get("subplots", {}))
    return result


def load_chart_ohlcv(
    exchange,
    config: dict[str, Any],
    pair: str,
    timeframe: str,
    limit: int,
) -> DataFrame:
    timeframe_ms = timeframe_to_msecs(timeframe)
    since_ms = dt_ts(dt_now()) - timeframe_ms * (limit + CHART_WARMUP_CANDLES)
    candle_type = config.get("candle_type_def", CandleType.SPOT)
    dataframe = exchange.get_historic_ohlcv(
        pair=pair,
        timeframe=timeframe,
        since_ms=since_ms,
        is_new_pair=True,
        candle_type=candle_type,
    )
    return dataframe.tail(limit).reset_index(drop=True)


def merge_strategy_overlay(
    chart_dataframe: DataFrame,
    strategy_dataframe: DataFrame,
    chart_timeframe: str,
    strategy_timeframe: str,
    strategy_plot_config: dict[str, Any],
) -> tuple[DataFrame, ChartOverlayMeta, list[str]]:
    chart_ms = timeframe_to_msecs(chart_timeframe)
    strategy_ms = timeframe_to_msecs(strategy_timeframe)
    overlay_columns = [
        column
        for column in _plot_config_columns(strategy_plot_config)
        if column in strategy_dataframe.columns and column not in DEFAULT_DATAFRAME_COLUMNS
    ]

    if chart_ms > strategy_ms:
        warning = "Strategy overlay hidden: chart timeframe is higher than strategy timeframe."
        return (
            _empty_signals(chart_dataframe),
            ChartOverlayMeta(
                strategy_timeframe=strategy_timeframe,
                alignment="hidden",
                columns=[],
                hidden=True,
                warning=warning,
            ),
            [warning],
        )

    signal_columns = [column for column in SIGNAL_COLUMNS if column in strategy_dataframe.columns]
    selected_columns = ["date", *overlay_columns, *signal_columns]
    strategy_selected = strategy_dataframe.loc[:, selected_columns].copy()
    rename_map = {
        column: _prefix_strategy_column(strategy_timeframe, column) for column in overlay_columns
    }
    strategy_selected.rename(columns=rename_map, inplace=True)

    chart_sorted = chart_dataframe.sort_values("date").copy()
    strategy_sorted = strategy_selected.sort_values("date")
    alignment = "direct" if chart_ms == strategy_ms else "forward_fill"
    merged = merge_asof(chart_sorted, strategy_sorted, on="date", direction="backward")
    merged = _empty_signals(merged)
    for column in SIGNAL_COLUMNS:
        merged[column] = merged[column].fillna(0).astype(int)

    return (
        merged,
        ChartOverlayMeta(
            strategy_timeframe=strategy_timeframe,
            alignment=alignment,
            columns=list(rename_map.values()),
            hidden=False,
        ),
        [],
    )


def build_chart_candles_response(
    rpc: RPC,
    config: dict[str, Any],
    payload: ChartCandlesRequest,
) -> dict[str, Any]:
    chart_dataframe = load_chart_ohlcv(
        rpc._freqtrade.exchange,
        config,
        payload.pair,
        payload.timeframe,
        payload.limit,
    )
    chart_dataframe = add_watch_indicators(chart_dataframe, payload.watch_indicators)
    chart_dataframe = _empty_signals(chart_dataframe)

    strategy_name = config.get("strategy", "")
    strategy_timeframe = config.get("timeframe")
    watch_plot_config = build_watch_plot_config(payload.watch_indicators)
    plot_config = watch_plot_config
    overlay = None
    warnings: list[str] = []

    if payload.include_strategy_overlay and strategy_timeframe:
        try:
            strategy_dataframe, _last_analyzed = rpc._freqtrade.dataprovider.get_analyzed_dataframe(
                payload.pair, strategy_timeframe
            )
            strategy_plot_config = getattr(rpc._freqtrade.strategy, "plot_config", {}) or {}
            chart_dataframe, overlay, overlay_warnings = merge_strategy_overlay(
                chart_dataframe,
                strategy_dataframe.copy(),
                payload.timeframe,
                strategy_timeframe,
                strategy_plot_config,
            )
            warnings.extend(overlay_warnings)
            overlay_plot_config = _prefix_strategy_plot_config(
                strategy_timeframe,
                strategy_plot_config,
                [column.removeprefix(f"strategy_{strategy_timeframe}_") for column in overlay.columns]
                if overlay
                else [],
            )
            plot_config = merge_plot_config(watch_plot_config, overlay_plot_config)
        except Exception:
            warnings.append(f"Strategy overlay unavailable for {payload.pair} {strategy_timeframe}")
            overlay = ChartOverlayMeta(
                strategy_timeframe=strategy_timeframe,
                alignment="unavailable",
                columns=[],
                hidden=True,
                warning=warnings[-1],
            )

    response = RPC._convert_dataframe_to_dict(
        strategy_name,
        payload.pair,
        payload.timeframe,
        chart_dataframe,
        dt_now(),
        None,
        [],
    )
    response.update(
        {
            "chart_timeframe": payload.timeframe,
            "strategy_timeframe": strategy_timeframe,
            "overlay": overlay.model_dump() if overlay else None,
            "plot_config": plot_config,
            "warnings": warnings,
        }
    )
    return response
```

- [ ] **Step 4: Run chart data tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_chart_data.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add freqtrade/freqtrade/rpc/chart_data.py freqtrade/tests/rpc/test_chart_data.py
git commit -m "feat: build trade chart candle data service"
```

## Task 4: Backend API Route

**Files:**
- Create: `freqtrade/freqtrade/rpc/api_server/api_chart.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/webserver.py`
- Modify: `freqtrade/tests/rpc/test_rpc_apiserver.py`

- [ ] **Step 1: Add failing route success test**

Append this test near `test_chart_candles_schema_validation` in `freqtrade/tests/rpc/test_rpc_apiserver.py`:

```python
def test_api_chart_candles_success(botclient, mocker):
    _ftbot, client = botclient
    build_response = mocker.patch(
        "freqtrade.rpc.api_server.api_chart.build_chart_candles_response",
        return_value={
            "strategy": CURRENT_TEST_STRATEGY,
            "pair": "XRP/BTC",
            "timeframe": "15m",
            "chart_timeframe": "15m",
            "strategy_timeframe": "5m",
            "timeframe_ms": 900000,
            "columns": ["date", "open", "high", "low", "close", "volume", "__date_ts"],
            "all_columns": ["date", "open", "high", "low", "close", "volume"],
            "data": [],
            "annotations": [],
            "length": 0,
            "buy_signals": 0,
            "sell_signals": 0,
            "enter_long_signals": 0,
            "exit_long_signals": 0,
            "enter_short_signals": 0,
            "exit_short_signals": 0,
            "last_analyzed": datetime.now(UTC),
            "last_analyzed_ts": 0,
            "data_start_ts": 0,
            "data_start": "",
            "data_stop": "",
            "data_stop_ts": 0,
            "overlay": None,
            "plot_config": {"main_plot": {}, "subplots": {}},
            "warnings": [],
        },
    )

    rc = client_post(
        client,
        f"{BASE_URI}/chart_candles",
        data={"pair": "XRP/BTC", "timeframe": "15m", "limit": 50},
    )

    assert_response(rc)
    result = rc.json()
    assert result["pair"] == "XRP/BTC"
    assert result["chart_timeframe"] == "15m"
    assert result["plot_config"] == {"main_plot": {}, "subplots": {}}
    build_response.assert_called_once()
```

- [ ] **Step 2: Run route tests to verify they fail**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_rpc_apiserver.py::test_api_chart_candles_success tests/rpc/test_rpc_apiserver.py::test_chart_candles_schema_validation -q
```

Expected:

```text
FAILED tests/rpc/test_rpc_apiserver.py::test_api_chart_candles_success
FAILED tests/rpc/test_rpc_apiserver.py::test_chart_candles_schema_validation
```

- [ ] **Step 3: Add API route module**

Create `freqtrade/freqtrade/rpc/api_server/api_chart.py`:

```python
import logging

from fastapi import APIRouter, Depends, HTTPException

from freqtrade.rpc import RPC
from freqtrade.rpc.api_server.api_schemas import ChartCandlesRequest, ChartCandlesResponse
from freqtrade.rpc.api_server.deps import get_config, get_rpc
from freqtrade.rpc.chart_data import build_chart_candles_response


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chart_candles", response_model=ChartCandlesResponse, tags=["Candle data"])
def chart_candles(
    payload: ChartCandlesRequest,
    rpc: RPC = Depends(get_rpc),
    config=Depends(get_config),
):
    try:
        return build_chart_candles_response(rpc, config, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Error in chart_candles")
        raise HTTPException(status_code=502, detail=str(exc))
```

- [ ] **Step 4: Register the route in trading mode**

In `freqtrade/freqtrade/rpc/api_server/webserver.py`, inside `configure_app`, add this import next to other `api_*` imports:

```python
from freqtrade.rpc.api_server.api_chart import router as api_chart
```

Add this `include_router` block after `api_trading`:

```python
app.include_router(
    api_chart,
    prefix="/api/v1",
    dependencies=[Depends(http_basic_or_jwt_token), Depends(is_trading_mode)],
)
```

- [ ] **Step 5: Run route tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_rpc_apiserver.py::test_api_chart_candles_success tests/rpc/test_rpc_apiserver.py::test_chart_candles_schema_validation -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit Task 4**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add freqtrade/freqtrade/rpc/api_server/api_chart.py freqtrade/freqtrade/rpc/api_server/webserver.py freqtrade/tests/rpc/test_rpc_apiserver.py
git commit -m "feat: expose trade chart candles endpoint"
```

## Task 5: Backend Integration Verification

**Files:**
- Modify: `freqtrade/tests/rpc/test_rpc_apiserver.py`

- [ ] **Step 1: Add endpoint integration test using live OHLCV mock**

Append this test near `test_api_chart_candles_success`:

```python
def test_api_chart_candles_integration(botclient, mocker):
    ftbot, client = botclient
    ftbot.config["timeframe"] = "1h"
    ftbot.strategy.plot_config = {
        "main_plot": {},
        "subplots": {"Volatility system": {"atr": {}, "abs_close_change": {}}},
    }
    strategy_df = generate_test_data("1h", 100, "2024-01-01 00:00:00+00:00")
    strategy_df["atr"] = range(100)
    strategy_df["abs_close_change"] = range(100)
    strategy_df["enter_long"] = 0
    strategy_df["exit_long"] = 0
    strategy_df["enter_short"] = 0
    strategy_df["exit_short"] = 0
    ftbot.dataprovider._set_cached_df("XRP/BTC", "1h", strategy_df, CandleType.SPOT)
    mocker.patch.object(
        ftbot.exchange,
        "get_historic_ohlcv",
        return_value=generate_test_data("15m", 180, "2024-01-01 00:00:00+00:00"),
    )

    rc = client_post(
        client,
        f"{BASE_URI}/chart_candles",
        data={"pair": "XRP/BTC", "timeframe": "15m", "limit": 50},
    )

    assert_response(rc)
    result = rc.json()
    assert result["length"] == 50
    assert result["chart_timeframe"] == "15m"
    assert result["strategy_timeframe"] == "1h"
    assert "watch_ma20" in result["columns"]
    assert "watch_rsi14" in result["columns"]
    assert "watch_macd" in result["columns"]
    assert "strategy_1h_atr" in result["columns"]
    assert result["overlay"]["alignment"] == "forward_fill"
    assert result["warnings"] == []
    assert "Strategy overlay 1h: Volatility system" in result["plot_config"]["subplots"]


def test_api_chart_candles_excludes_strategy_overlay(botclient, mocker):
    ftbot, client = botclient
    mocker.patch.object(
        ftbot.exchange,
        "get_historic_ohlcv",
        return_value=generate_test_data("15m", 180, "2024-01-01 00:00:00+00:00"),
    )

    rc = client_post(
        client,
        f"{BASE_URI}/chart_candles",
        data={
            "pair": "XRP/BTC",
            "timeframe": "15m",
            "limit": 50,
            "include_strategy_overlay": False,
        },
    )

    assert_response(rc)
    result = rc.json()
    assert "watch_ma20" in result["columns"]
    assert all(not column.startswith("strategy_") for column in result["columns"])
    assert result["overlay"] is None
```

- [ ] **Step 2: Run integration tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_chart_indicators.py tests/rpc/test_chart_data.py tests/rpc/test_rpc_apiserver.py::test_api_chart_candles_integration tests/rpc/test_rpc_apiserver.py::test_api_chart_candles_excludes_strategy_overlay -q
```

Expected:

```text
11 passed
```

- [ ] **Step 3: Run focused API regression tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_rpc_apiserver.py::test_api_pair_candles tests/rpc/test_rpc_apiserver.py::test_api_pair_history_live_mode tests/rpc/test_rpc_apiserver.py::test_api_plot_config -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 4: Commit Task 5**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add freqtrade/tests/rpc/test_rpc_apiserver.py
git commit -m "test: cover trade chart candles api integration"
```

## Task 6: Frontend Types, Feature Flag, And Store API

**Files:**
- Modify: `frequi/src/types/candleTypes.ts`
- Modify: `frequi/src/types/features.ts`
- Modify: `frequi/src/stores/ftbot.ts`
- Test: Typecheck in later task

- [ ] **Step 1: Add chart candle TypeScript types**

In `frequi/src/types/candleTypes.ts`, add this import at the top:

```ts
import type { PlotConfig } from './plot';
```

Add these interfaces after `PairCandlePayload`:

```ts
export interface ChartMacdIndicatorPayload {
  fast: number;
  slow: number;
  signal: number;
}

export interface ChartIndicatorPayload {
  ma?: number[];
  rsi?: number[];
  macd?: ChartMacdIndicatorPayload[];
}

export interface ChartCandlesPayload {
  pair: string;
  timeframe: string;
  limit?: number;
  watch_indicators?: ChartIndicatorPayload;
  include_strategy_overlay?: boolean;
}
```

Add these interfaces after `PairHistory`:

```ts
export interface ChartOverlayMeta {
  strategy_timeframe: string;
  alignment: 'direct' | 'forward_fill' | 'hidden' | 'unavailable';
  columns: string[];
  hidden: boolean;
  warning?: string | null;
}

export interface ChartCandlesResponse extends PairHistory {
  chart_timeframe: string;
  strategy_timeframe?: string | null;
  overlay?: ChartOverlayMeta | null;
  plot_config: PlotConfig;
  warnings: string[];
}
```

- [ ] **Step 2: Add frontend feature flag**

In `frequi/src/types/features.ts`, add `'chartCandles'` to `FeatureKey`:

```ts
  | 'chartCandles'
```

Add this entry to `FEATURES` after `backgroundJobDelete`:

```ts
  chartCandles: { minVersion: 2.5, description: 'Trade chart indicator layer endpoint' },
```

- [ ] **Step 3: Add store state and action imports**

In `frequi/src/stores/ftbot.ts`, add `ChartCandlesPayload` and `ChartCandlesResponse` to the type import list:

```ts
  ChartCandlesPayload,
  ChartCandlesResponse,
```

- [ ] **Step 4: Add chart candle state**

In `frequi/src/stores/ftbot.ts`, near existing candle history state:

```ts
const candleData = shallowRef<PairHistoryLocal>({});
const candleDataStatus = shallowRef(LoadingStatus.not_loaded);
```

add:

```ts
const chartCandleData = shallowRef<PairHistoryLocal>({});
const chartCandleDataStatus = shallowRef(LoadingStatus.not_loaded);
```

- [ ] **Step 5: Add `getChartCandles` action**

In `frequi/src/stores/ftbot.ts`, immediately after `getPairCandles`, add:

```ts
async function getChartCandles(payload: ChartCandlesPayload) {
  if (payload.pair && payload.timeframe) {
    chartCandleDataStatus.value = LoadingStatus.loading;
    try {
      const { data } = await api.post<ChartCandlesPayload, AxiosResponse<ChartCandlesResponse>>(
        '/chart_candles',
        payload,
      );
      chartCandleData.value = {
        ...chartCandleData.value,
        [`${payload.pair}__${payload.timeframe}`]: {
          pair: payload.pair,
          timeframe: payload.timeframe,
          data,
        },
      };
      chartCandleDataStatus.value = LoadingStatus.success;
    } catch (err) {
      console.error(err);
      chartCandleDataStatus.value = LoadingStatus.error;
    }
  } else {
    const error = 'pair or timeframe not specified';
    console.error(error);
    return Promise.reject(error);
  }
}
```

- [ ] **Step 6: Return chart candle state and action**

In the returned object of `frequi/src/stores/ftbot.ts`, add:

```ts
      chartCandleData,
      chartCandleDataStatus,
```

near `candleData` and `candleDataStatus`, and add:

```ts
      getChartCandles,
```

near `getPairCandles`.

- [ ] **Step 7: Run typecheck to catch obvious type errors**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm typecheck
```

Expected:

```text
No TypeScript errors from the new types and store action.
```

- [ ] **Step 8: Commit Task 6**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add frequi/src/types/candleTypes.ts frequi/src/types/features.ts frequi/src/stores/ftbot.ts
git commit -m "feat: add frontend chart candles api support"
```

## Task 7: Trade Chart Store

**Files:**
- Create: `frequi/src/stores/tradeChart.ts`
- Test: `frequi/tests/unit/tradeChart.spec.ts`

- [ ] **Step 1: Write failing store tests**

Create `frequi/tests/unit/tradeChart.spec.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

import { useTradeChartStore } from '@/stores/tradeChart';

describe('tradeChart store', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('defaults to empty timeframe and enabled overlay', () => {
    const store = useTradeChartStore();

    expect(store.selectedTimeframe).toBe('');
    expect(store.useStrategyOverlay).toBe(true);
  });

  it('resets timeframe to bot timeframe', () => {
    const store = useTradeChartStore();
    store.selectedTimeframe = '15m';

    store.resetForBot('1h');

    expect(store.selectedTimeframe).toBe('1h');
  });

  it('keeps empty string when bot has no timeframe', () => {
    const store = useTradeChartStore();
    store.selectedTimeframe = '15m';

    store.resetForBot('');

    expect(store.selectedTimeframe).toBe('');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm test:unit -- tradeChart.spec.ts
```

Expected:

```text
FAIL tests/unit/tradeChart.spec.ts
```

The import should fail until the store exists.

- [ ] **Step 3: Implement store**

Create `frequi/src/stores/tradeChart.ts`:

```ts
export const useTradeChartStore = defineStore('tradeChart', () => {
  const selectedTimeframe = ref('');
  const useStrategyOverlay = ref(true);

  function resetForBot(botTimeframe: string) {
    selectedTimeframe.value = botTimeframe || '';
    useStrategyOverlay.value = true;
  }

  return {
    selectedTimeframe,
    useStrategyOverlay,
    resetForBot,
  };
});

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useTradeChartStore, import.meta.hot));
}
```

- [ ] **Step 4: Run store tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm test:unit -- tradeChart.spec.ts
```

Expected:

```text
PASS tests/unit/tradeChart.spec.ts
```

- [ ] **Step 5: Commit Task 7**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add frequi/src/stores/tradeChart.ts frequi/tests/unit/tradeChart.spec.ts
git commit -m "feat: add trade chart state"
```

## Task 8: Chart Container Trade Data Source Props

**Files:**
- Modify: `frequi/src/components/charts/CandleChartContainer.vue`
- Modify: `frequi/src/components/charts/SingleCandleChartContainer.vue`

- [ ] **Step 1: Add props to `CandleChartContainer.vue`**

In `frequi/src/components/charts/CandleChartContainer.vue`, change the type import:

```ts
import type { ChartSliderPosition, PairHistory, PairHistoryLocal, PlotConfig, Trade } from '@/types';
import { LoadingStatus } from '@/types';
```

Add these props to `defineProps`:

```ts
    chartDataSource?: PairHistoryLocal;
    chartDataStatus?: LoadingStatus;
    plotConfigOverride?: PlotConfig;
    chartStatusText?: string;
    chartWarningText?: string;
```

Add defaults:

```ts
    chartDataSource: undefined,
    chartDataStatus: undefined,
    plotConfigOverride: undefined,
    chartStatusText: '',
    chartWarningText: '',
```

- [ ] **Step 2: Use optional data source for configurator columns**

In `CandleChartContainer.vue`, update `dataset` computed:

```ts
const dataset = computed((): PairHistory | undefined => {
  const firstpair = botStore.activeBot.plotMultiPairs[0];
  if (props.chartDataSource) {
    return props.chartDataSource[`${firstpair}__${props.timeframe}`]?.data;
  }
  if (props.historicView) {
    return botStore.activeBot.history[`${firstpair}__${props.timeframe}`]?.data;
  }
  return botStore.activeBot.candleData[`${firstpair}__${props.timeframe}`]?.data;
});
```

- [ ] **Step 3: Add timeframe selector slot and status text**

In the `CandleChartContainer.vue` template, after the pair selector and refresh button block, add:

```vue
          <slot name="timeframe-select" />
          <small v-if="chartStatusText" class="text-muted text-nowrap">
            {{ chartStatusText }}
          </small>
```

- [ ] **Step 4: Pass props to `SingleCandleChartContainer`**

In the `SingleCandleChartContainer` usage in `CandleChartContainer.vue`, add:

```vue
          :chart-data-source="chartDataSource"
          :chart-data-status="chartDataStatus"
          :plot-config-override="plotConfigOverride"
          :chart-warning-text="chartWarningText"
```

- [ ] **Step 5: Add props to `SingleCandleChartContainer.vue`**

In `frequi/src/components/charts/SingleCandleChartContainer.vue`, change the type import:

```ts
import type { ChartSliderPosition, PairHistory, PairHistoryLocal, PlotConfig, Trade } from '@/types';
import { LoadingStatus } from '@/types';
```

Add these props:

```ts
    chartDataSource?: PairHistoryLocal;
    chartDataStatus?: LoadingStatus;
    plotConfigOverride?: PlotConfig;
    chartWarningText?: string;
```

Add defaults:

```ts
    chartDataSource: undefined,
    chartDataStatus: undefined,
    plotConfigOverride: undefined,
    chartWarningText: '',
```

- [ ] **Step 6: Use optional data source in `SingleCandleChartContainer.vue`**

Replace `dataset` computed with:

```ts
const dataset = computed((): PairHistory | undefined => {
  if (props.chartDataSource) {
    return props.chartDataSource[`${props.pair}__${props.timeframe}`]?.data;
  }
  if (props.historicView) {
    return botStore.activeBot.history[`${props.pair}__${props.timeframe}`]?.data;
  }
  return botStore.activeBot.candleData[`${props.pair}__${props.timeframe}`]?.data;
});
```

Replace `isLoadingDataset` computed with:

```ts
const isLoadingDataset = computed((): boolean => {
  if (props.chartDataStatus !== undefined) {
    return props.chartDataStatus === LoadingStatus.loading;
  }
  if (props.historicView) {
    return botStore.activeBot.historyStatus === LoadingStatus.loading;
  }

  return botStore.activeBot.candleDataStatus === LoadingStatus.loading;
});
```

Replace the local `status` inside `noDatasetText` with:

```ts
  const status =
    props.chartDataStatus ??
    (props.historicView ? botStore.activeBot.historyStatus : botStore.activeBot.candleDataStatus);
```

- [ ] **Step 7: Render plot config override and warning**

In `SingleCandleChartContainer.vue`, change the `CandleChart` prop:

```vue
          :plot-config="plotConfigOverride ?? plotStore.plotConfig"
```

Above the chart area, after the row with the pair label and loading progress, add:

```vue
    <div v-if="chartWarningText" class="mx-2 text-xs text-warning text-wrap">
      {{ chartWarningText }}
    </div>
```

- [ ] **Step 8: Typecheck chart containers**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm typecheck
```

Expected:

```text
No TypeScript errors in CandleChartContainer.vue or SingleCandleChartContainer.vue.
```

- [ ] **Step 9: Commit Task 8**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add frequi/src/components/charts/CandleChartContainer.vue frequi/src/components/charts/SingleCandleChartContainer.vue
git commit -m "feat: allow trade chart data source override"
```

## Task 9: Trade Page Wiring

**Files:**
- Modify: `frequi/src/views/TradingView.vue`
- Modify: `frequi/src/locales/en.ts`
- Modify: `frequi/src/locales/zh-CN.ts`

- [ ] **Step 1: Add Trade chart store and state in `TradingView.vue`**

In `frequi/src/views/TradingView.vue`, add:

```ts
const tradeChartStore = useTradeChartStore();
```

Add these computed values after layout computed values:

```ts
const tradeChartTimeframes = ['1m', '15m', '30m', '1h', '2h', '4h', '1d'].map((timeframe) => ({
  value: timeframe,
  label: timeframe,
}));

const tradeChartTimeframe = computed({
  get() {
    return tradeChartStore.selectedTimeframe || botStore.activeBot.timeframe;
  },
  set(value: string) {
    tradeChartStore.selectedTimeframe = value;
  },
});

const tradeChartDataset = computed(() => {
  const pair = botStore.activeBot.plotMultiPairs[0];
  if (!pair || !tradeChartTimeframe.value) return undefined;
  return botStore.activeBot.chartCandleData[`${pair}__${tradeChartTimeframe.value}`]?.data;
});

const tradeChartPlotConfig = computed(() => tradeChartDataset.value?.plot_config);

const tradeChartWarningText = computed(() => tradeChartDataset.value?.warnings?.join(' ') ?? '');

const tradeChartStatusText = computed(() => {
  const chartTimeframe = tradeChartTimeframe.value;
  const strategy = tradeChartDataset.value?.strategy || botStore.activeBot.strategy?.strategy || '';
  const strategyTimeframe = tradeChartDataset.value?.strategy_timeframe || botStore.activeBot.timeframe;
  return formatLocaleText(t('trade.chartStatus'), {
    chartTimeframe,
    strategy,
    strategyTimeframe,
  });
});
```

- [ ] **Step 2: Replace `refreshOHLCV` implementation**

In `TradingView.vue`, replace `refreshOHLCV` with:

```ts
function refreshOHLCV(pair: string) {
  if (botStore.activeBot.botFeatures.chartCandles) {
    botStore.activeBot.getChartCandles({
      pair,
      timeframe: tradeChartTimeframe.value,
      include_strategy_overlay: tradeChartStore.useStrategyOverlay,
    });
    return;
  }

  botStore.activeBot.getPairCandles({
    pair,
    timeframe: botStore.activeBot.timeframe,
  });
}
```

- [ ] **Step 3: Reset timeframe when active bot changes**

Add this watcher in `TradingView.vue`:

```ts
watch(
  () => botStore.selectedBot,
  () => {
    tradeChartStore.resetForBot(botStore.activeBot.timeframe);
  },
  { immediate: true },
);
```

Add this watcher after it:

```ts
watch(
  () => tradeChartTimeframe.value,
  () => {
    for (const pair of botStore.activeBot.plotMultiPairs) {
      refreshOHLCV(pair);
    }
  },
);
```

- [ ] **Step 4: Wire `CandleChartContainer` props and selector slot**

In the `CandleChartContainer` usage in `TradingView.vue`, change:

```vue
            :timeframe="botStore.activeBot.timeframe"
```

to:

```vue
            :timeframe="tradeChartTimeframe"
            :chart-data-source="
              botStore.activeBot.botFeatures.chartCandles
                ? botStore.activeBot.chartCandleData
                : undefined
            "
            :chart-data-status="
              botStore.activeBot.botFeatures.chartCandles
                ? botStore.activeBot.chartCandleDataStatus
                : undefined
            "
            :plot-config-override="tradeChartPlotConfig"
            :chart-status-text="tradeChartStatusText"
            :chart-warning-text="tradeChartWarningText"
```

Inside the component body, add:

```vue
            <template #timeframe-select>
              <USelect
                v-model="tradeChartTimeframe"
                class="w-24"
                size="md"
                :items="tradeChartTimeframes"
                :title="t('trade.chartTimeframe')"
              />
            </template>
```

- [ ] **Step 5: Add locale strings**

In `frequi/src/locales/en.ts`, inside `trade`, add:

```ts
    chartTimeframe: 'Chart timeframe',
    chartStatus:
      'Chart: {chartTimeframe} | Strategy overlay: {strategy} {strategyTimeframe}',
```

In `frequi/src/locales/zh-CN.ts`, inside `trade`, add:

```ts
    chartTimeframe: '看盘周期',
    chartStatus: '图表: {chartTimeframe} | 策略叠加: {strategy} {strategyTimeframe}',
```

- [ ] **Step 6: Typecheck Trade wiring**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm typecheck
```

Expected:

```text
No TypeScript errors in TradingView.vue or locale keys.
```

- [ ] **Step 7: Commit Task 9**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add frequi/src/views/TradingView.vue frequi/src/locales/en.ts frequi/src/locales/zh-CN.ts
git commit -m "feat: wire trade page chart timeframe selector"
```

## Task 10: Websocket Refresh Guard

**Files:**
- Modify: `frequi/src/stores/ftbot.ts`

- [ ] **Step 1: Add new candle branch awareness**

In `frequi/src/stores/ftbot.ts`, locate the `FtWsMessageTypes.newCandle` branch in `_handleWebsocketMessage`.

Replace:

```ts
            const plotStore = usePlotConfigStore();
            getPairCandles({ pair, timeframe: timeframeValue, columns: plotStore.usedColumns });
```

with:

```ts
            const tradeChartStore = useTradeChartStore();
            if (botFeatures.value.chartCandles && tradeChartStore.selectedTimeframe) {
              getChartCandles({
                pair,
                timeframe: tradeChartStore.selectedTimeframe,
                include_strategy_overlay: tradeChartStore.useStrategyOverlay,
              });
            } else {
              const plotStore = usePlotConfigStore();
              getPairCandles({ pair, timeframe: timeframeValue, columns: plotStore.usedColumns });
            }
```

- [ ] **Step 2: Typecheck websocket branch**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm typecheck
```

Expected:

```text
No TypeScript errors in ftbot.ts.
```

- [ ] **Step 3: Commit Task 10**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add frequi/src/stores/ftbot.ts
git commit -m "fix: refresh trade chart data on websocket candles"
```

## Task 11: Frontend E2E Fixtures And Tests

**Files:**
- Modify: `frequi/e2e/helpers.ts`
- Modify: `frequi/e2e/testData/show_config.json`
- Add: `frequi/e2e/testData/chart_candles_btc_15m.json`
- Add: `frequi/e2e/testData/chart_candles_btc_4h_warning.json`
- Modify: `frequi/e2e/trade.spec.ts`

- [ ] **Step 1: Update mock feature version**

In `frequi/e2e/testData/show_config.json`, change:

```json
"api_version": 2.42
```

to:

```json
"api_version": 2.5
```

- [ ] **Step 2: Add default chart candle mock**

Create `frequi/e2e/testData/chart_candles_btc_15m.json` with a compact valid response:

```json
{
  "strategy": "VolatilitySystem",
  "pair": "BTC/USDT",
  "timeframe": "15m",
  "chart_timeframe": "15m",
  "strategy_timeframe": "1h",
  "timeframe_ms": 900000,
  "columns": [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "watch_ma20",
    "watch_ma60",
    "watch_rsi14",
    "watch_macd",
    "watch_macdsignal",
    "watch_macdhist",
    "strategy_1h_atr",
    "strategy_1h_abs_close_change",
    "enter_long",
    "exit_long",
    "enter_short",
    "exit_short",
    "__date_ts"
  ],
  "all_columns": [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "watch_ma20",
    "watch_ma60",
    "watch_rsi14",
    "watch_macd",
    "watch_macdsignal",
    "watch_macdhist",
    "strategy_1h_atr",
    "strategy_1h_abs_close_change",
    "enter_long",
    "exit_long",
    "enter_short",
    "exit_short"
  ],
  "data": [
    [
      "2024-01-01 00:00:00+00:00",
      42000,
      42100,
      41900,
      42050,
      120,
      42020,
      41980,
      55,
      12,
      10,
      2,
      350,
      125,
      0,
      0,
      0,
      0,
      1704067200000
    ]
  ],
  "annotations": [],
  "length": 1,
  "buy_signals": 0,
  "sell_signals": 0,
  "enter_long_signals": 0,
  "exit_long_signals": 0,
  "enter_short_signals": 0,
  "exit_short_signals": 0,
  "last_analyzed": "2024-01-01T00:00:00Z",
  "last_analyzed_ts": 1704067200,
  "data_start_ts": 1704067200000,
  "data_start": "2024-01-01 00:00:00+00:00",
  "data_stop": "2024-01-01 00:00:00+00:00",
  "data_stop_ts": 1704067200000,
  "overlay": {
    "strategy_timeframe": "1h",
    "alignment": "forward_fill",
    "columns": ["strategy_1h_atr", "strategy_1h_abs_close_change"],
    "hidden": false,
    "warning": null
  },
  "plot_config": {
    "main_plot": {
      "watch_ma20": { "color": "#3b82f6" },
      "watch_ma60": { "color": "#f59e0b" }
    },
    "subplots": {
      "RSI 14": {
        "watch_rsi14": { "color": "#a855f7" }
      },
      "MACD": {
        "watch_macd": { "color": "#2563eb" },
        "watch_macdsignal": { "color": "#f97316" },
        "watch_macdhist": { "type": "bar", "color": "#22c55e" }
      },
      "Strategy overlay 1h: Volatility system": {
        "strategy_1h_atr": {},
        "strategy_1h_abs_close_change": {}
      }
    }
  },
  "warnings": []
}
```

- [ ] **Step 3: Add hidden overlay fixture**

Create `frequi/e2e/testData/chart_candles_btc_4h_warning.json` by copying the `15m` fixture and making these exact changes:

```json
{
  "timeframe": "4h",
  "chart_timeframe": "4h",
  "timeframe_ms": 14400000,
  "columns": [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "watch_ma20",
    "watch_ma60",
    "watch_rsi14",
    "watch_macd",
    "watch_macdsignal",
    "watch_macdhist",
    "enter_long",
    "exit_long",
    "enter_short",
    "exit_short",
    "__date_ts"
  ],
  "overlay": {
    "strategy_timeframe": "1h",
    "alignment": "hidden",
    "columns": [],
    "hidden": true,
    "warning": "Strategy overlay hidden: chart timeframe is higher than strategy timeframe."
  },
  "warnings": ["Strategy overlay hidden: chart timeframe is higher than strategy timeframe."]
}
```

The rest of the fixture remains valid JSON with matching `data` column count.

- [ ] **Step 4: Route chart candle mocks**

In `frequi/e2e/helpers.ts`, add a mapping entry in `defaultMocks`:

```ts
    { name: '@ChartCandles', url: '**/api/v1/chart_candles', fixture: 'chart_candles_btc_15m.json' },
```

Add mapping in `getWaitForResponse`:

```ts
    '@ChartCandles': '**/api/v1/chart_candles',
```

- [ ] **Step 5: Add Trade e2e assertions**

In `frequi/e2e/trade.spec.ts`, add this test inside the existing `test.describe('Trade', () => {` block:

```ts
  test('Trade page chart uses chart_candles endpoint and shows overlay warning', async ({ page }) => {
    await page.route('**/api/v1/chart_candles', async (route, request) => {
      const body = request.postDataJSON() as { timeframe?: string };
      const fixture =
        body.timeframe === '4h'
          ? './e2e/testData/chart_candles_btc_4h_warning.json'
          : './e2e/testData/chart_candles_btc_15m.json';
      await route.fulfill({ path: fixture });
    });

    await Promise.all([
      page.goto('/trade'),
      page.waitForResponse('**/api/v1/chart_candles'),
      page.waitForResponse('**/status'),
      page.waitForResponse('**/profit'),
      page.waitForResponse('**/balance'),
      page.waitForResponse('**/whitelist'),
      page.waitForResponse('**/blacklist'),
      page.waitForResponse('**/locks'),
    ]);

    await expect(page.getByText(/Chart: 1m|Chart: 15m|图表:/)).toBeVisible();
    await expect(page.getByText(/Strategy overlay: VolatilitySystem 1h|策略叠加:/)).toBeVisible();

    await page.getByTitle(/Chart timeframe|看盘周期/).click();
    await page.getByRole('option', { name: '4h' }).click();
    await page.waitForResponse('**/api/v1/chart_candles');

    await expect(
      page.getByText('Strategy overlay hidden: chart timeframe is higher than strategy timeframe.'),
    ).toBeVisible();
  });
```

- [ ] **Step 6: Run frontend e2e test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm test:e2e -- trade.spec.ts --project=chromium
```

Expected:

```text
Trade page chart uses chart_candles endpoint and shows overlay warning passes.
Existing Trade page tests still pass.
```

- [ ] **Step 7: Commit Task 11**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add frequi/e2e/helpers.ts frequi/e2e/testData/show_config.json frequi/e2e/testData/chart_candles_btc_15m.json frequi/e2e/testData/chart_candles_btc_4h_warning.json frequi/e2e/trade.spec.ts
git commit -m "test: cover trade chart timeframe overlay flow"
```

## Task 12: Full Verification And Local Runtime Check

**Files:**
- No planned source edits unless verification reveals a bug in this feature.

- [ ] **Step 1: Run backend focused tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_chart_indicators.py tests/rpc/test_chart_data.py tests/rpc/test_rpc_apiserver.py::test_api_chart_candles_success tests/rpc/test_rpc_apiserver.py::test_chart_candles_schema_validation tests/rpc/test_rpc_apiserver.py::test_api_chart_candles_integration tests/rpc/test_rpc_apiserver.py::test_api_chart_candles_excludes_strategy_overlay -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 2: Run backend regression tests for existing chart endpoints**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
python -m pytest tests/rpc/test_rpc_apiserver.py::test_api_pair_candles tests/rpc/test_rpc_apiserver.py::test_api_pair_history_live_mode tests/rpc/test_rpc_apiserver.py::test_api_plot_config -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 3: Run frontend checks**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm typecheck
pnpm test:unit -- tradeChart.spec.ts
pnpm test:e2e -- trade.spec.ts --project=chromium
```

Expected:

```text
Typecheck passes.
tradeChart unit test passes.
Trade e2e tests pass.
```

- [ ] **Step 4: Rebuild or restart local services if the user wants live browser validation**

If the local UI is served from the source dev server, run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm dev --host 127.0.0.1 --port 5173
```

If the current Docker containers serve bundled UI assets, rebuild the image using the repository's existing Docker workflow rather than editing container files directly.

- [ ] **Step 5: Validate with the running futures bot**

Use the current local futures bot setup. Build a Basic Auth header from the futures config:

```powershell
$config = Get-Content G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\config.volatility.futures.json | ConvertFrom-Json
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$($config.api_server.username):$($config.api_server.password)"))
$headers = @{ Authorization = "Basic $basic" }
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8082/api/v1/chart_candles `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"pair":"BTC/USDT:USDT","timeframe":"15m","limit":100,"include_strategy_overlay":true}'
```

Expected response facts:

```text
chart_timeframe is 15m
strategy_timeframe is 1h
columns include watch_ma20, watch_rsi14, watch_macd
columns include strategy_1h_atr when chart timeframe is 15m
warnings is empty or contains only exchange/data availability warnings
```

Then send:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8082/api/v1/chart_candles `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"pair":"BTC/USDT:USDT","timeframe":"4h","limit":100,"include_strategy_overlay":true}'
```

Expected response facts:

```text
chart_timeframe is 4h
strategy_timeframe is 1h
columns do not include strategy_1h_atr
warnings includes "Strategy overlay hidden: chart timeframe is higher than strategy timeframe."
```

- [ ] **Step 6: Validate bot configuration did not change**

Run:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8082/api/v1/show_config -Headers $headers
```

Expected response facts:

```text
strategy remains VolatilitySystem
timeframe remains 1h
runmode remains dry_run
trading_mode remains futures
```

- [ ] **Step 7: Inspect git diff**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
git status --short
git diff --stat
```

Expected:

```text
Only files listed in this plan are modified by this feature.
Pre-existing unrelated dirty files remain untouched.
```

- [ ] **Step 8: Final commit**

If any verification fixes were needed after Task 11, commit them:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add freqtrade/freqtrade/rpc/chart_indicators.py freqtrade/freqtrade/rpc/chart_data.py freqtrade/freqtrade/rpc/api_server/api_chart.py freqtrade/freqtrade/rpc/api_server/api_schemas.py freqtrade/freqtrade/rpc/api_server/api_v1.py freqtrade/freqtrade/rpc/api_server/webserver.py freqtrade/tests/rpc/test_chart_indicators.py freqtrade/tests/rpc/test_chart_data.py freqtrade/tests/rpc/test_rpc_apiserver.py frequi/src/types/candleTypes.ts frequi/src/types/features.ts frequi/src/stores/ftbot.ts frequi/src/stores/tradeChart.ts frequi/src/components/charts/CandleChartContainer.vue frequi/src/components/charts/SingleCandleChartContainer.vue frequi/src/views/TradingView.vue frequi/src/locales/en.ts frequi/src/locales/zh-CN.ts frequi/tests/unit/tradeChart.spec.ts frequi/e2e/helpers.ts frequi/e2e/testData/show_config.json frequi/e2e/testData/chart_candles_btc_15m.json frequi/e2e/testData/chart_candles_btc_4h_warning.json frequi/e2e/trade.spec.ts
git commit -m "fix: finalize trade chart indicator layer"
```

If no verification fixes were needed, skip this commit.

## Self-Review

- Spec coverage:
  - Trade page scope is covered by Tasks 6 through 11.
  - Backend Chart Indicator Layer is covered by Tasks 1 through 5.
  - Default watch indicators are covered by Task 2 and Task 3.
  - Strategy overlay fixed to strategy timeframe is covered by Task 3.
  - Lower/equal/higher timeframe alignment is covered by Task 3 tests.
  - API response structure and validation are covered by Tasks 1, 4, and 5.
  - Error behavior for overlay failure is covered by Task 3.
  - Frontend selector, labels, warnings, and fallback are covered by Tasks 8 through 11.
  - Acceptance criteria verification is covered by Task 12.
- Placeholder scan:
  - This plan contains concrete file paths, code snippets, commands, and expected outcomes for each implementation task.
- Type consistency:
  - Backend request type is `ChartCandlesRequest`.
  - Backend response type is `ChartCandlesResponse`.
  - Frontend payload type is `ChartCandlesPayload`.
  - Frontend response type is `ChartCandlesResponse`.
  - Store action is `getChartCandles`.
  - Endpoint path is `/api/v1/chart_candles`.
