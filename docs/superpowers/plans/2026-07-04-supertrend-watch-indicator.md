# Supertrend Watch Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add default ATR(10) x 3 Supertrend to the Trade page watch chart with green/red segmented main-plot rendering and a subtle price-to-trend fill.

**Architecture:** Extend the existing `/chart_candles` watch indicator layer so Supertrend is calculated on the backend from the selected chart timeframe. Reuse the existing FreqUI plot config and ECharts line/fill rendering path, adding only a small `hidden` indicator flag for helper columns.

**Tech Stack:** Python, Pydantic, pandas, TA-Lib, pytest, Vue 3, TypeScript, Pinia, ECharts, Vitest.

---

## File Structure

- Modify `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
  - Add `SupertrendIndicatorRequest`.
  - Add `supertrend` to `ChartIndicatorRequest`.

- Modify `freqtrade/freqtrade/rpc/chart_indicators.py`
  - Add default Supertrend plot config.
  - Add Supertrend calculation and column naming helpers.
  - Add default/custom/empty Supertrend handling to the existing watch indicator flow.

- Modify `freqtrade/tests/rpc/test_chart_indicators.py`
  - Add schema tests.
  - Add Supertrend column, segmentation, custom suffix, empty request, and plot config tests.

- Modify `freqtrade/tests/rpc/test_chart_data.py`
  - Add `/chart_candles` response coverage for default Supertrend columns and plot config.

- Modify `frequi/src/types/candleTypes.ts`
  - Add `ChartSupertrendIndicatorPayload`.
  - Add `supertrend` to `ChartIndicatorPayload`.

- Modify `frequi/src/types/plot.ts`
  - Add `hidden?: boolean` to `IndicatorConfig`.

- Modify `frequi/src/utils/charts/candleChartSeries.ts`
  - Add a small visibility helper for indicator configs.

- Modify `frequi/src/components/charts/CandleChart.vue`
  - Skip normal series and legend generation for `hidden` helper indicators while keeping them usable as `fill_to` targets.

- Create `frequi/tests/unit/plotConfigVisibility.spec.ts`
  - Cover hidden indicator visibility behavior and Supertrend request payload typing.

---

### Task 1: Backend Supertrend Request Schema

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/tests/rpc/test_chart_indicators.py`

- [ ] **Step 1: Write failing schema tests**

In `freqtrade/tests/rpc/test_chart_indicators.py`, change the schema import to include `SupertrendIndicatorRequest`:

```python
from freqtrade.rpc.api_server.api_schemas import (
    ChartIndicatorRequest,
    MacdIndicatorRequest,
    SupertrendIndicatorRequest,
)
```

Add these tests after `test_invalid_macd_period_order_fails_schema`:

```python
def test_chart_indicator_request_includes_default_supertrend():
    indicators = ChartIndicatorRequest()

    assert len(indicators.supertrend) == 1
    assert indicators.supertrend[0].period == 10
    assert indicators.supertrend[0].multiplier == pytest.approx(3.0)


def test_chart_indicator_request_accepts_empty_supertrend():
    indicators = ChartIndicatorRequest(supertrend=[])

    assert indicators.supertrend == []


def test_invalid_supertrend_period_fails_schema():
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        SupertrendIndicatorRequest(period=0, multiplier=3)


def test_invalid_supertrend_multiplier_fails_schema():
    with pytest.raises(ValueError, match="greater than 0"):
        SupertrendIndicatorRequest(period=10, multiplier=0)
```

- [ ] **Step 2: Run schema tests and verify failure**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
python -m pytest tests/rpc/test_chart_indicators.py::test_chart_indicator_request_includes_default_supertrend tests/rpc/test_chart_indicators.py::test_chart_indicator_request_accepts_empty_supertrend tests/rpc/test_chart_indicators.py::test_invalid_supertrend_period_fails_schema tests/rpc/test_chart_indicators.py::test_invalid_supertrend_multiplier_fails_schema -q
```

Expected: FAIL because `SupertrendIndicatorRequest` is not defined.

- [ ] **Step 3: Add backend schema**

In `freqtrade/freqtrade/rpc/api_server/api_schemas.py`, add this class directly after `MacdIndicatorRequest`:

```python
class SupertrendIndicatorRequest(BaseModel):
    period: int = Field(default=10, ge=1, le=500)
    multiplier: float = Field(default=3.0, gt=0, le=100)
```

In the existing `ChartIndicatorRequest`, add the `supertrend` field after `macd`:

```python
class ChartIndicatorRequest(BaseModel):
    ma: list[int] = Field(default_factory=lambda: [20, 60])
    rsi: list[int] = Field(default_factory=lambda: [14])
    macd: list[MacdIndicatorRequest] = Field(default_factory=lambda: [MacdIndicatorRequest()])
    supertrend: list[SupertrendIndicatorRequest] = Field(
        default_factory=lambda: [SupertrendIndicatorRequest()]
    )
```

- [ ] **Step 4: Run schema tests and verify pass**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
python -m pytest tests/rpc/test_chart_indicators.py::test_chart_indicator_request_includes_default_supertrend tests/rpc/test_chart_indicators.py::test_chart_indicator_request_accepts_empty_supertrend tests/rpc/test_chart_indicators.py::test_invalid_supertrend_period_fails_schema tests/rpc/test_chart_indicators.py::test_invalid_supertrend_multiplier_fails_schema -q
```

Expected: PASS.

- [ ] **Step 5: Commit schema task**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
git add freqtrade/rpc/api_server/api_schemas.py tests/rpc/test_chart_indicators.py
git commit -m "feat: add supertrend watch indicator schema"
```

Expected: commit includes only the two listed files.

---

### Task 2: Backend Supertrend Calculation And Plot Config

**Files:**
- Modify: `freqtrade/freqtrade/rpc/chart_indicators.py`
- Modify: `freqtrade/tests/rpc/test_chart_indicators.py`

- [ ] **Step 1: Write failing default column and plot config tests**

In `freqtrade/tests/rpc/test_chart_indicators.py`, update `test_add_watch_indicators_uses_default_columns` with these assertions after the MACD column assertions:

```python
    assert "watch_supertrend_up" in result.columns
    assert "watch_supertrend_down" in result.columns
    assert "watch_supertrend_price" in result.columns
```

Add this assertion after `assert result["watch_macd"].notna().sum() > 0`:

```python
    assert (
        result[["watch_supertrend_up", "watch_supertrend_down"]]
        .notna()
        .any(axis=1)
        .sum()
        > 0
    )
```

Replace `test_build_watch_plot_config_matches_default_columns` with:

```python
def test_build_watch_plot_config_matches_default_columns():
    plot_config = build_watch_plot_config()

    assert set(plot_config["main_plot"]) == {
        "watch_ma20",
        "watch_ma60",
        "watch_supertrend_up",
        "watch_supertrend_down",
        "watch_supertrend_price",
    }
    assert plot_config["main_plot"]["watch_supertrend_up"] == {
        "color": "#22c55e",
        "type": "line",
        "fill_to": "watch_supertrend_price",
    }
    assert plot_config["main_plot"]["watch_supertrend_down"] == {
        "color": "#ef4444",
        "type": "line",
        "fill_to": "watch_supertrend_price",
    }
    assert plot_config["main_plot"]["watch_supertrend_price"] == {
        "type": "line",
        "hidden": True,
    }
    assert set(plot_config["subplots"]["RSI 14"]) == {"watch_rsi14"}
    assert set(plot_config["subplots"]["MACD"]) == {
        "watch_macd",
        "watch_macdsignal",
        "watch_macdhist",
    }
    assert plot_config["subplots"]["MACD"]["watch_macdhist"]["type"] == "bar"
```

Add this test after `test_add_watch_indicators_accepts_custom_periods`:

```python
def test_supertrend_populates_only_one_direction_per_candle():
    dataframe = generate_test_data("15m", 160, "2024-01-01 00:00:00+00:00")

    result = add_watch_indicators(dataframe)

    populated_sides = result[["watch_supertrend_up", "watch_supertrend_down"]].notna().sum(axis=1)
    assert populated_sides.max() <= 1
    assert populated_sides.sum() > 0
```

Update `test_add_watch_indicators_accepts_custom_periods` to include custom Supertrend:

```python
    indicators = ChartIndicatorRequest(
        ma=[10],
        rsi=[7],
        macd=[MacdIndicatorRequest(fast=5, slow=13, signal=4)],
        supertrend=[SupertrendIndicatorRequest(period=7, multiplier=2.5)],
    )
```

Add these assertions to the same test:

```python
    assert "watch_supertrend_up_7_2_5" in result.columns
    assert "watch_supertrend_down_7_2_5" in result.columns
    assert "watch_supertrend_price_7_2_5" in result.columns
```

Update `test_build_watch_plot_config_accepts_custom_periods` to include the same custom Supertrend request:

```python
    indicators = ChartIndicatorRequest(
        ma=[10],
        rsi=[7],
        macd=[MacdIndicatorRequest(fast=5, slow=13, signal=4)],
        supertrend=[SupertrendIndicatorRequest(period=7, multiplier=2.5)],
    )
```

Replace the expected main plot assertion in that test with:

```python
    assert set(plot_config["main_plot"]) == {
        "watch_ma10",
        "watch_supertrend_up_7_2_5",
        "watch_supertrend_down_7_2_5",
        "watch_supertrend_price_7_2_5",
    }
    assert plot_config["main_plot"]["watch_supertrend_up_7_2_5"]["fill_to"] == (
        "watch_supertrend_price_7_2_5"
    )
    assert plot_config["main_plot"]["watch_supertrend_price_7_2_5"]["hidden"] is True
```

Update `test_add_watch_indicators_accepts_empty_request` to disable Supertrend explicitly:

```python
    indicators = ChartIndicatorRequest(ma=[], rsi=[], macd=[], supertrend=[])
```

- [ ] **Step 2: Run indicator tests and verify failure**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
python -m pytest tests/rpc/test_chart_indicators.py -q
```

Expected: FAIL because Supertrend columns and plot config are not implemented.

- [ ] **Step 3: Implement Supertrend defaults and calculation**

In `freqtrade/freqtrade/rpc/chart_indicators.py`, add imports:

```python
import math

import pandas as pd
```

Update the schema import:

```python
from freqtrade.rpc.api_server.api_schemas import (
    ChartIndicatorRequest,
    MacdIndicatorRequest,
    SupertrendIndicatorRequest,
)
```

Add this constant after `DEFAULT_MACD_PERIOD`:

```python
DEFAULT_SUPERTREND_PERIOD = (10, 3.0)
```

Update `DEFAULT_WATCH_PLOT_CONFIG["main_plot"]` to include Supertrend:

```python
    "main_plot": {
        "watch_ma20": {"color": "#3b82f6"},
        "watch_ma60": {"color": "#f59e0b"},
        "watch_supertrend_up": {
            "color": "#22c55e",
            "type": "line",
            "fill_to": "watch_supertrend_price",
        },
        "watch_supertrend_down": {
            "color": "#ef4444",
            "type": "line",
            "fill_to": "watch_supertrend_price",
        },
        "watch_supertrend_price": {"type": "line", "hidden": True},
    },
```

In `add_watch_indicators`, add this loop after the MACD loop:

```python
    for supertrend_config in indicators.supertrend:
        up_column, down_column, price_column = _supertrend_column_names(supertrend_config)
        supertrend, direction = _calculate_supertrend(
            result, supertrend_config.period, supertrend_config.multiplier
        )
        result[up_column] = supertrend.where(direction == 1)
        result[down_column] = supertrend.where(direction == -1)
        result[price_column] = result["close"]
```

In `build_watch_plot_config`, add this loop after the MA loop and before RSI subplots:

```python
    for supertrend_config in indicators.supertrend:
        up_column, down_column, price_column = _supertrend_column_names(supertrend_config)
        plot_config["main_plot"][up_column] = {
            "color": "#22c55e",
            "type": "line",
            "fill_to": price_column,
        }
        plot_config["main_plot"][down_column] = {
            "color": "#ef4444",
            "type": "line",
            "fill_to": price_column,
        }
        plot_config["main_plot"][price_column] = {"type": "line", "hidden": True}
```

Add these helper functions after `_macd_column_names`:

```python
def _supertrend_column_names(
    supertrend_config: SupertrendIndicatorRequest,
) -> tuple[str, str, str]:
    if _supertrend_period(supertrend_config) == DEFAULT_SUPERTREND_PERIOD:
        return "watch_supertrend_up", "watch_supertrend_down", "watch_supertrend_price"

    suffix = (
        f"_{supertrend_config.period}_"
        f"{_supertrend_multiplier_suffix(supertrend_config.multiplier)}"
    )
    return (
        f"watch_supertrend_up{suffix}",
        f"watch_supertrend_down{suffix}",
        f"watch_supertrend_price{suffix}",
    )


def _supertrend_multiplier_suffix(multiplier: float) -> str:
    return f"{multiplier:g}".replace(".", "_")


def _calculate_supertrend(
    dataframe: DataFrame, period: int, multiplier: float
) -> tuple[pd.Series, pd.Series]:
    atr = ta.ATR(dataframe, timeperiod=period)
    hl2 = (dataframe["high"] + dataframe["low"]) / 2
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr
    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    supertrend = pd.Series(float("nan"), index=dataframe.index, dtype="float64")
    direction = pd.Series(0, index=dataframe.index, dtype="int64")

    for index in range(len(dataframe)):
        if pd.isna(atr.iloc[index]):
            continue

        if index == 0 or direction.iloc[index - 1] == 0:
            final_upper.iloc[index] = basic_upper.iloc[index]
            final_lower.iloc[index] = basic_lower.iloc[index]
            if dataframe["close"].iloc[index] <= final_upper.iloc[index]:
                direction.iloc[index] = -1
                supertrend.iloc[index] = final_upper.iloc[index]
            else:
                direction.iloc[index] = 1
                supertrend.iloc[index] = final_lower.iloc[index]
            continue

        prev_final_upper = final_upper.iloc[index - 1]
        prev_final_lower = final_lower.iloc[index - 1]
        prev_close = dataframe["close"].iloc[index - 1]

        if pd.isna(prev_final_upper) or (
            basic_upper.iloc[index] < prev_final_upper or prev_close > prev_final_upper
        ):
            final_upper.iloc[index] = basic_upper.iloc[index]
        else:
            final_upper.iloc[index] = prev_final_upper

        if pd.isna(prev_final_lower) or (
            basic_lower.iloc[index] > prev_final_lower or prev_close < prev_final_lower
        ):
            final_lower.iloc[index] = basic_lower.iloc[index]
        else:
            final_lower.iloc[index] = prev_final_lower

        close = dataframe["close"].iloc[index]
        if direction.iloc[index - 1] == -1:
            if close > final_upper.iloc[index]:
                direction.iloc[index] = 1
                supertrend.iloc[index] = final_lower.iloc[index]
            else:
                direction.iloc[index] = -1
                supertrend.iloc[index] = final_upper.iloc[index]
        else:
            if close < final_lower.iloc[index]:
                direction.iloc[index] = -1
                supertrend.iloc[index] = final_upper.iloc[index]
            else:
                direction.iloc[index] = 1
                supertrend.iloc[index] = final_lower.iloc[index]

    return supertrend, direction
```

Update `_is_default_watch_indicators`:

```python
def _is_default_watch_indicators(indicators: ChartIndicatorRequest) -> bool:
    macd_periods = tuple(_macd_period(macd_config) for macd_config in indicators.macd)
    supertrend_periods = tuple(
        _supertrend_period(supertrend_config) for supertrend_config in indicators.supertrend
    )
    return (
        tuple(indicators.ma) == DEFAULT_MA_PERIODS
        and tuple(indicators.rsi) == DEFAULT_RSI_PERIODS
        and macd_periods == (DEFAULT_MACD_PERIOD,)
        and supertrend_periods == (DEFAULT_SUPERTREND_PERIOD,)
    )
```

Add `_supertrend_period` after `_macd_period`:

```python
def _supertrend_period(supertrend_config: SupertrendIndicatorRequest) -> tuple[int, float]:
    multiplier = float(supertrend_config.multiplier)
    if math.isclose(multiplier, round(multiplier)):
        multiplier = float(round(multiplier))
    return supertrend_config.period, multiplier
```

- [ ] **Step 4: Run indicator tests and verify pass**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
python -m pytest tests/rpc/test_chart_indicators.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit indicator calculation task**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
git add freqtrade/rpc/chart_indicators.py tests/rpc/test_chart_indicators.py
git commit -m "feat: calculate supertrend watch indicators"
```

Expected: commit includes only the two listed files.

---

### Task 3: Backend Chart Response Coverage

**Files:**
- Modify: `freqtrade/tests/rpc/test_chart_data.py`

- [ ] **Step 1: Write chart response tests**

In `freqtrade/tests/rpc/test_chart_data.py`, add this test after `test_build_chart_candles_response_includes_watch_plot_config`:

```python
def test_build_chart_candles_response_includes_supertrend_watch_indicator(mocker):
    chart_df = generate_test_data("15m", 170, "2024-01-01 00:00:00+00:00")
    rpc = MagicMock()
    rpc._freqtrade.exchange.get_historic_ohlcv.return_value = chart_df
    rpc._freqtrade.config = {
        "strategy": "StrategyUnderTest",
        "timeframe": "1h",
        "candle_type_def": CandleType.SPOT,
    }
    request = ChartCandlesRequest(
        pair="BTC/USDT", timeframe="15m", limit=50, include_strategy_overlay=False
    )

    response = build_chart_candles_response(rpc, rpc._freqtrade.config, request)

    assert "watch_supertrend_up" in response["columns"]
    assert "watch_supertrend_down" in response["columns"]
    assert "watch_supertrend_price" in response["columns"]
    assert "watch_supertrend_up" in response["plot_config"]["main_plot"]
    assert "watch_supertrend_down" in response["plot_config"]["main_plot"]
    assert response["plot_config"]["main_plot"]["watch_supertrend_price"]["hidden"] is True
    populated = [
        row
        for row in response["data"]
        if row[response["columns"].index("watch_supertrend_up")] is not None
        or row[response["columns"].index("watch_supertrend_down")] is not None
    ]
    assert len(populated) > 0
```

Update `test_build_chart_candles_response_includes_watch_plot_config` with:

```python
    assert "watch_supertrend_up" in response["plot_config"]["main_plot"]
    assert "watch_supertrend_down" in response["plot_config"]["main_plot"]
    assert response["plot_config"]["main_plot"]["watch_supertrend_price"]["hidden"] is True
```

Update `test_build_chart_candles_response_keeps_warmup_for_watch_indicators` with:

```python
    assert "watch_supertrend_up" in response["columns"]
    assert "watch_supertrend_down" in response["columns"]
    assert any(
        value is not None
        for value in _response_column(response, "watch_supertrend_up")
        + _response_column(response, "watch_supertrend_down")
    )
```

- [ ] **Step 2: Run chart response tests**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
python -m pytest tests/rpc/test_chart_data.py::test_build_chart_candles_response_includes_watch_plot_config tests/rpc/test_chart_data.py::test_build_chart_candles_response_includes_supertrend_watch_indicator tests/rpc/test_chart_data.py::test_build_chart_candles_response_keeps_warmup_for_watch_indicators -q
```

Expected: PASS if Task 2 is complete. If a test fails, fix only `freqtrade/freqtrade/rpc/chart_indicators.py` or the test assertions until the response includes the Supertrend columns and plot config.

- [ ] **Step 3: Run existing chart data regression tests**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
python -m pytest tests/rpc/test_chart_data.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit chart response tests**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
git add tests/rpc/test_chart_data.py
git commit -m "test: cover supertrend chart candle response"
```

Expected: commit includes only `tests/rpc/test_chart_data.py`.

---

### Task 4: Frontend Types And Indicator Visibility Helper

**Files:**
- Modify: `frequi/src/types/candleTypes.ts`
- Modify: `frequi/src/types/plot.ts`
- Modify: `frequi/src/utils/charts/candleChartSeries.ts`
- Create: `frequi/tests/unit/plotConfigVisibility.spec.ts`

- [ ] **Step 1: Write failing frontend unit test**

Create `frequi/tests/unit/plotConfigVisibility.spec.ts`:

```ts
import { describe, expect, it } from 'vitest';

import type { ChartIndicatorPayload, IndicatorConfig } from '@/types';
import { isIndicatorVisible } from '@/utils/charts/candleChartSeries';

describe('indicator plot visibility', () => {
  it('treats hidden helper indicators as non-visible', () => {
    const config: IndicatorConfig = { type: 'line', hidden: true };

    expect(isIndicatorVisible(config)).toBe(false);
  });

  it('keeps normal indicators visible by default', () => {
    const config: IndicatorConfig = { type: 'line' };

    expect(isIndicatorVisible(config)).toBe(true);
  });

  it('accepts supertrend watch indicator request payloads', () => {
    const payload: ChartIndicatorPayload = {
      supertrend: [{ period: 10, multiplier: 3 }],
    };

    expect(payload.supertrend?.[0]?.period).toBe(10);
    expect(payload.supertrend?.[0]?.multiplier).toBe(3);
  });
});
```

- [ ] **Step 2: Run frontend unit test and verify failure**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm test:unit tests/unit/plotConfigVisibility.spec.ts
```

Expected: FAIL because `isIndicatorVisible`, `hidden`, and `supertrend` are not implemented.

- [ ] **Step 3: Add frontend types**

In `frequi/src/types/candleTypes.ts`, add this interface after `ChartMacdIndicatorPayload`:

```ts
export interface ChartSupertrendIndicatorPayload {
  period: number;
  multiplier: number;
}
```

Update `ChartIndicatorPayload`:

```ts
export interface ChartIndicatorPayload {
  ma?: number[];
  rsi?: number[];
  macd?: ChartMacdIndicatorPayload[];
  supertrend?: ChartSupertrendIndicatorPayload[];
}
```

In `frequi/src/types/plot.ts`, update `IndicatorConfig`:

```ts
export interface IndicatorConfig {
  color?: string;
  type?: ChartType | ChartTypeString;
  fill_to?: string;
  scatterSymbolSize?: number;
  hidden?: boolean;
}
```

- [ ] **Step 4: Add visibility helper**

In `frequi/src/utils/charts/candleChartSeries.ts`, add this function after the `SupportedSeriesTypes` type:

```ts
export function isIndicatorVisible(value: IndicatorConfig): boolean {
  return value.hidden !== true;
}
```

- [ ] **Step 5: Run frontend unit test and verify pass**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm test:unit tests/unit/plotConfigVisibility.spec.ts
```

Expected: PASS.

- [ ] **Step 6: Commit frontend type/helper task**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
git add src/types/candleTypes.ts src/types/plot.ts src/utils/charts/candleChartSeries.ts tests/unit/plotConfigVisibility.spec.ts
git commit -m "feat: support hidden supertrend chart config"
```

Expected: commit includes only the four listed files.

---

### Task 5: Frontend Hidden Helper Rendering

**Files:**
- Modify: `frequi/src/components/charts/CandleChart.vue`
- Modify: `frequi/src/utils/charts/candleChartSeries.ts`
- Modify: `frequi/tests/unit/plotConfigVisibility.spec.ts`

- [ ] **Step 1: Extend visibility test for fill target behavior**

In `frequi/tests/unit/plotConfigVisibility.spec.ts`, update the import:

```ts
import { getDiffColumnsFromPlotConfig } from '@/utils/charts/areaPlotDataset';
import { isIndicatorVisible } from '@/utils/charts/candleChartSeries';
```

Add this test inside the existing `describe` block:

```ts
  it('keeps hidden fill targets available for area calculations', () => {
    const diffColumns = getDiffColumnsFromPlotConfig({
      main_plot: {
        watch_supertrend_up: {
          color: '#22c55e',
          type: 'line',
          fill_to: 'watch_supertrend_price',
        },
        watch_supertrend_price: {
          type: 'line',
          hidden: true,
        },
      },
      subplots: {},
    });

    expect(diffColumns).toEqual([['watch_supertrend_up', 'watch_supertrend_price']]);
  });
```

- [ ] **Step 2: Run visibility tests**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm test:unit tests/unit/plotConfigVisibility.spec.ts
```

Expected: PASS because `fill_to` collection should already be independent of visibility.

- [ ] **Step 3: Use visibility helper in CandleChart main plot rendering**

In `frequi/src/components/charts/CandleChart.vue`, update the chart series import:

```ts
import {
  generateAreaCandleSeries,
  generateCandleSeries,
  isIndicatorVisible,
} from '@/utils/charts/candleChartSeries';
```

In the main plot loop, add the visibility guard as the first statement inside `forEach`:

```ts
    Object.entries(props.plotConfig.main_plot).forEach(([key, value]) => {
      if (!isIndicatorVisible(value)) {
        return;
      }
      const col = columns.findIndex((el) => el === key);
```

- [ ] **Step 4: Use visibility helper in CandleChart subplot rendering**

In the subplot indicator loop, add the same visibility guard as the first statement inside `forEach`:

```ts
      Object.entries(value).forEach(([sk, sv]) => {
        if (!isIndicatorVisible(sv)) {
          return;
        }
        const col = columns.findIndex((el) => el === sk);
```

- [ ] **Step 5: Run focused frontend tests**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm test:unit tests/unit/plotConfigVisibility.spec.ts tests/unit/plotConfigKey.spec.ts tests/unit/useLiveChartDataset.spec.ts
```

Expected: PASS.

- [ ] **Step 6: Commit frontend rendering task**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
git add src/components/charts/CandleChart.vue src/utils/charts/candleChartSeries.ts tests/unit/plotConfigVisibility.spec.ts
git commit -m "feat: hide helper chart indicator series"
```

Expected: commit includes only the three listed files.

---

### Task 6: Full Verification And Browser Check

**Files:**
- No planned code changes.
- Use the current app browser at `http://127.0.0.1:8081/trade`.

- [ ] **Step 1: Run backend indicator and chart tests**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
python -m pytest tests/rpc/test_chart_indicators.py tests/rpc/test_chart_data.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend focused unit tests**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm test:unit tests/unit/plotConfigVisibility.spec.ts tests/unit/plotConfigKey.spec.ts tests/unit/useLiveChartDataset.spec.ts
```

Expected: PASS.

- [ ] **Step 3: Run frontend typecheck**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm typecheck
```

Expected: PASS.

- [ ] **Step 4: Run frontend lint on changed source and test files**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm lint-ci src/types/candleTypes.ts src/types/plot.ts src/utils/charts/candleChartSeries.ts src/components/charts/CandleChart.vue tests/unit/plotConfigVisibility.spec.ts
```

Expected: PASS. If `lint-ci` does not accept file arguments in this project, run `pnpm lint-ci` and report the full result.

- [ ] **Step 5: Verify backend response shape manually**

With the local backend running, request chart candles for the Trade chart pair and timeframe:

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8081/api/v1/chart_candles' -ContentType 'application/json' -Body '{"pair":"BTC/USDT:USDT","timeframe":"15m","limit":120,"include_strategy_overlay":true,"candle_mode":"live"}' | ConvertTo-Json -Depth 6
```

Expected: JSON includes `watch_supertrend_up`, `watch_supertrend_down`, `watch_supertrend_price`, and `plot_config.main_plot.watch_supertrend_price.hidden = true`.

- [ ] **Step 6: Verify Trade page visually**

Use the app browser:

```text
http://127.0.0.1:8081/trade
```

Expected visual checks:

- Supertrend appears by default on the main candle chart.
- Bullish segments are green.
- Bearish segments are red.
- A subtle filled band appears between the active Supertrend segment and price.
- `watch_supertrend_price` is not visible as a normal separate indicator line.
- Switching `1m`, `15m`, and `1h` refreshes the Supertrend per chart timeframe.
- Strategy overlay labels and bot strategy timeframe do not change because of Supertrend.

- [ ] **Step 7: Check git status in all touched repositories**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
git status --short
git -C freqtrade status --short
git -C frequi status --short
```

Expected: only intentional Supertrend changes are present in `freqtrade` and `frequi`. Root-level unrelated files remain untouched.

---

## Self-Review

- Spec coverage: Tasks 1-3 cover backend request schema, default Supertrend calculation, timeframe-independent chart response data, custom/empty requests, validation, and plot config. Tasks 4-5 cover frontend payload typing, hidden helper config, and chart rendering changes. Task 6 covers backend, frontend, typecheck, API response, and browser verification.
- Marker scan: This plan contains no unresolved markers and no open-ended handling steps.
- Type consistency: The plan consistently uses `SupertrendIndicatorRequest`, `ChartSupertrendIndicatorPayload`, `supertrend`, `watch_supertrend_up`, `watch_supertrend_down`, and `watch_supertrend_price`.
