# A-share Trading Session Chart Axis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compress non-trading time in A-share research candlestick charts while preserving real timestamps for data, tooltip evidence, side layers, and backtesting.

**Architecture:** Keep OHLCV and backtest data on real timestamps. Add an optional chart axis metadata contract from the research API, then let the frontend adapt display coordinates by appending a synthetic sequential x value for session-aware markets. Crypto/contract charts keep the existing continuous time axis unless metadata explicitly requests `trading_session`.

**Tech Stack:** Python/FastAPI/Pydantic research API, Vue 3, TypeScript, ECharts 6, Vitest, Vue Test Utils.

## Global Constraints

- Do not rewrite raw OHLCV timestamps.
- Do not generate fake closed-market candles.
- Keep default contract/spot chart behavior unchanged.
- A-share research charts should use trading-session compression for `1m`, `5m`, `15m`, `30m`, `60m`, and `1d`.
- Tooltip, crosshair, event/document/decision point matching, and backtest execution must keep real millisecond timestamps.
- Implement the smallest semantic surface: optional chart metadata plus frontend axis adapter.

---

## File Structure

- Modify `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
  - Add optional chart axis metadata to `ChartResponseMeta`.
- Modify `freqtrade/freqtrade/research/chart.py`
  - Set `meta.axis.mode = "trading_session"` for A-share research chart responses.
- Modify `freqtrade/tests/rpc/test_api_research.py`
  - Assert A-share research chart responses expose the trading-session axis contract.
- Modify `frequi/src/types/candleTypes.ts`
  - Add TypeScript axis metadata types matching the API.
- Create `frequi/src/utils/charts/candleChartTradingAxis.ts`
  - Build display x columns and timestamp lookup for compressed charts.
- Modify `frequi/src/utils/charts/candleChartAxis.ts`
  - Add value-axis helpers for compressed axes while preserving existing time-axis helpers.
- Modify `frequi/src/utils/charts/chartZoom.ts`
  - Add generic initial zoom by arbitrary x column; keep existing time helper as wrapper.
- Modify `frequi/src/utils/charts/candleChartCrosshair.ts`
  - Rename-neutral support: existing nearest-row logic works for timestamps and display x values.
- Modify `frequi/src/composables/useCandleChartTooltip.ts`
  - Prefer the row's real timestamp when axis value is a synthetic display index.
- Modify `frequi/src/components/charts/CandleChart.vue`
  - Use `__display_x` for ECharts x encoding only when `meta.axis.mode === "trading_session"`.
- Add `frequi/tests/unit/candleChartTradingAxis.spec.ts`
  - Unit-test display axis construction and label lookup.
- Modify `frequi/tests/unit/candleChartAxis.spec.ts`
  - Cover linked value-axis mapping.
- Modify `frequi/tests/unit/chartZoom.spec.ts`
  - Cover generic zoom range by display x column.
- Modify `frequi/tests/unit/candleChartTooltip.spec.ts`
  - Cover tooltip timestamp rendering when axis value is synthetic.
- Modify `frequi/tests/component/CandleChart.spec.ts`
  - Cover chart option generation for trading-session axis.

---

### Task 1: Research API Axis Metadata Contract

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/freqtrade/research/chart.py`
- Test: `freqtrade/tests/rpc/test_api_research.py`

**Interfaces:**
- Produces: `ChartAxisMeta(mode, source_column, display_column, timezone)`
- Produces: `ChartResponseMeta.axis: ChartAxisMeta | None`
- Consumes later: frontend `ChartResponseMeta.axis.mode`

- [ ] **Step 1: Write the failing API schema test**

Add this test to `freqtrade/tests/rpc/test_api_research.py` near the existing research chart tests:

```python
def test_research_chart_exposes_a_share_trading_session_axis(research_client) -> None:
    response = client_post(
        research_client,
        f"{BASE_URI}/research/chart_candles",
        data={
            "bot_id": "a-share-local",
            "instrument": "600519.SH",
            "timeframe": "1d",
            "adjustment": "raw",
            "limit": 20,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["axis"] == {
        "mode": "trading_session",
        "source_column": "__date_ts",
        "display_column": "__display_x",
        "timezone": "Asia/Shanghai",
    }
```

- [ ] **Step 2: Run the failing API test**

Run:

```powershell
G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe -m pytest freqtrade/tests/rpc/test_api_research.py::test_research_chart_exposes_a_share_trading_session_axis -q
```

Expected: FAIL because `meta.axis` is missing.

- [ ] **Step 3: Add the API schema**

In `freqtrade/freqtrade/rpc/api_server/api_schemas.py`, add this model near `ChartWindowMeta`:

```python
class ChartAxisMeta(BaseModel):
    mode: Literal["time", "trading_session"] = "time"
    source_column: str = "__date_ts"
    display_column: str | None = None
    timezone: str | None = None
```

Then update `ChartResponseMeta`:

```python
class ChartResponseMeta(BaseModel):
    schema_version: int = 1
    window: ChartWindowMeta
    axis: ChartAxisMeta | None = None
    layers: list[ChartLayerMeta] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    data_provenance: dict[str, Any] | None = None
```

- [ ] **Step 4: Set A-share research axis metadata**

In `freqtrade/freqtrade/research/chart.py`, import `ChartAxisMeta`:

```python
from freqtrade.rpc.api_server.api_schemas import (
    ChartAxisMeta,
    ChartLayerMeta,
    ChartResponseMeta,
    ChartSeriesCoverage,
    ChartSeriesMeta,
    ChartWindowMeta,
    ResearchChartCandlesRequest,
)
```

Pass `profile` into `_build_research_chart_response_meta`:

```python
meta = _build_research_chart_response_meta(
    dataframe,
    profile,
    payload,
    plot_config,
    provenance,
    side_layers=side_layers,
)
```

Update the function signature and set the axis:

```python
def _build_research_chart_response_meta(
    dataframe: DataFrame,
    profile: ResearchBotProfile,
    payload: ResearchChartCandlesRequest,
    plot_config: dict[str, Any],
    provenance: Any,
    side_layers: list[ChartLayerMeta] | None = None,
) -> ChartResponseMeta:
    layers = [
        _build_market_layer_meta(dataframe, payload.timeframe),
        _build_watch_layer_meta(dataframe, plot_config, payload.timeframe),
        *(side_layers or []),
    ]
    warnings = []
    for layer in layers:
        warnings.extend(layer.warnings)

    return ChartResponseMeta(
        window=ChartWindowMeta(
            requested_count=payload.limit,
            returned_count=len(dataframe),
            warmup_count=0,
            data_start=_date_string(dataframe.iloc[0]["date"]) if not dataframe.empty else None,
            data_stop=_date_string(dataframe.iloc[-1]["date"]) if not dataframe.empty else None,
            last_candle_complete=True,
        ),
        axis=_chart_axis_meta(profile),
        layers=layers,
        warnings=list(dict.fromkeys(warnings)),
        data_provenance=provenance.model_dump(),
    )
```

Add this helper in the same file:

```python
def _chart_axis_meta(profile: ResearchBotProfile) -> ChartAxisMeta:
    if profile.market.value == "a_share":
        return ChartAxisMeta(
            mode="trading_session",
            source_column="__date_ts",
            display_column="__display_x",
            timezone="Asia/Shanghai",
        )
    return ChartAxisMeta(mode="time", source_column="__date_ts")
```

- [ ] **Step 5: Run the API test**

Run:

```powershell
G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe -m pytest freqtrade/tests/rpc/test_api_research.py::test_research_chart_exposes_a_share_trading_session_axis -q
```

Expected: PASS.

- [ ] **Step 6: Run focused API regression**

Run:

```powershell
G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe -m pytest freqtrade/tests/rpc/test_api_research.py -q
```

Expected: PASS.

---

### Task 2: Frontend Trading-Session Axis Utilities

**Files:**
- Modify: `frequi/src/types/candleTypes.ts`
- Create: `frequi/src/utils/charts/candleChartTradingAxis.ts`
- Test: `frequi/tests/unit/candleChartTradingAxis.spec.ts`

**Interfaces:**
- Consumes: `ChartResponseMeta.axis`
- Produces: `buildTradingSessionAxisDataset(columns, rows, timestampColumn, displayColumnName)`
- Produces: `getChartAxisMode(meta)`
- Produces: `getTimestampForDisplayValue(axis, value)`

- [ ] **Step 1: Write the failing utility test**

Create `frequi/tests/unit/candleChartTradingAxis.spec.ts`:

```ts
import { describe, expect, it } from 'vitest';

import {
  TRADING_SESSION_DISPLAY_COLUMN,
  buildTradingSessionAxisDataset,
  getChartAxisMode,
  getTimestampForDisplayValue,
} from '@/utils/charts/candleChartTradingAxis';
import type { ChartResponseMeta } from '@/types';

describe('candle chart trading-session axis utilities', () => {
  it('defaults to the native time axis when metadata is absent', () => {
    expect(getChartAxisMode(null)).toBe('time');
    expect(getChartAxisMode(undefined)).toBe('time');
  });

  it('enables trading-session axis only when metadata requests it', () => {
    expect(
      getChartAxisMode({
        schema_version: 1,
        window: {
          requested_count: 3,
          returned_count: 3,
          warmup_count: 0,
          last_candle_complete: true,
        },
        axis: {
          mode: 'trading_session',
          source_column: '__date_ts',
          display_column: TRADING_SESSION_DISPLAY_COLUMN,
          timezone: 'Asia/Shanghai',
        },
        layers: [],
        warnings: [],
      } satisfies ChartResponseMeta),
    ).toBe('trading_session');
  });

  it('appends a sequential display column without changing real timestamps', () => {
    const columns = ['__date_ts', 'open', 'high', 'low', 'close', 'volume'];
    const rows = [
      [Date.UTC(2026, 6, 8, 2, 29), 400, 401, 399, 400.5, 1000],
      [Date.UTC(2026, 6, 8, 3, 16), 401, 402, 400, 401.5, 1100],
      [Date.UTC(2026, 6, 8, 5, 0), 402, 403, 401, 402.5, 1200],
    ];

    const result = buildTradingSessionAxisDataset(columns, rows, 0);

    expect(result.columns).toEqual([
      '__date_ts',
      'open',
      'high',
      'low',
      'close',
      'volume',
      TRADING_SESSION_DISPLAY_COLUMN,
    ]);
    expect(result.timestampColumn).toBe(0);
    expect(result.displayColumn).toBe(6);
    expect(result.rows.map((row) => row[0])).toEqual(rows.map((row) => row[0]));
    expect(result.rows.map((row) => row[6])).toEqual([0, 1, 2]);
    expect(getTimestampForDisplayValue(result, 1)).toBe(rows[1]![0]);
  });

  it('returns undefined for display values that belong to scroll padding rows', () => {
    const result = buildTradingSessionAxisDataset(['__date_ts', 'open'], [[1000, 10]], 0);

    expect(getTimestampForDisplayValue(result, 99)).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run the failing utility test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm test:unit tests/unit/candleChartTradingAxis.spec.ts --run
```

Expected: FAIL because the utility file does not exist.

- [ ] **Step 3: Add frontend axis metadata types**

In `frequi/src/types/candleTypes.ts`, add:

```ts
export interface ChartAxisMeta {
  mode: 'time' | 'trading_session';
  source_column: string;
  display_column?: string | null;
  timezone?: string | null;
}
```

Update `ChartResponseMeta`:

```ts
export interface ChartResponseMeta {
  schema_version: number;
  window: ChartWindowMeta;
  axis?: ChartAxisMeta | null;
  layers: ChartLayerMeta[];
  warnings: string[];
}
```

- [ ] **Step 4: Implement the trading-session utility**

Create `frequi/src/utils/charts/candleChartTradingAxis.ts`:

```ts
import type { ChartResponseMeta } from '@/types';

export const TRADING_SESSION_DISPLAY_COLUMN = '__display_x';

export type CandleChartAxisMode = 'time' | 'trading_session';

export type TradingSessionAxisDataset = {
  columns: string[];
  rows: number[][];
  timestampColumn: number;
  displayColumn: number;
  timestampByDisplayValue: Map<number, number>;
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function getChartAxisMode(meta: ChartResponseMeta | null | undefined): CandleChartAxisMode {
  return meta?.axis?.mode === 'trading_session' ? 'trading_session' : 'time';
}

export function buildTradingSessionAxisDataset(
  columns: string[],
  rows: number[][],
  timestampColumn: number,
  displayColumnName = TRADING_SESSION_DISPLAY_COLUMN,
): TradingSessionAxisDataset {
  const displayColumn = columns.length;
  const timestampByDisplayValue = new Map<number, number>();
  const displayRows = rows.map((row, index) => {
    const nextRow = row.slice();
    nextRow[displayColumn] = index;
    const timestamp = Number(row[timestampColumn]);
    if (isFiniteNumber(timestamp)) {
      timestampByDisplayValue.set(index, timestamp);
    }
    return nextRow;
  });

  return {
    columns: [...columns, displayColumnName],
    rows: displayRows,
    timestampColumn,
    displayColumn,
    timestampByDisplayValue,
  };
}

export function getTimestampForDisplayValue(
  axisDataset: TradingSessionAxisDataset,
  displayValue: unknown,
): number | undefined {
  const roundedValue = Math.round(Number(displayValue));
  if (!Number.isFinite(roundedValue)) {
    return undefined;
  }
  return axisDataset.timestampByDisplayValue.get(roundedValue);
}
```

- [ ] **Step 5: Run the utility test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm test:unit tests/unit/candleChartTradingAxis.spec.ts --run
```

Expected: PASS.

---

### Task 3: Generic Axis Domain, Zoom, Crosshair, and Tooltip Support

**Files:**
- Modify: `frequi/src/utils/charts/candleChartAxis.ts`
- Modify: `frequi/src/utils/charts/chartZoom.ts`
- Modify: `frequi/src/composables/useCandleChartTooltip.ts`
- Test: `frequi/tests/unit/candleChartAxis.spec.ts`
- Test: `frequi/tests/unit/chartZoom.spec.ts`
- Test: `frequi/tests/unit/candleChartTooltip.spec.ts`

**Interfaces:**
- Produces: `getAxisDomain(rows, xColumn)`
- Produces: `withLinkedValueAxisMapping(axis, domain, formatter?)`
- Produces: `buildInitialDataZoomRange(rows, xColumn, visibleCandleCount)`
- Produces: tooltip timestamp preference for row timestamp over synthetic display x

- [ ] **Step 1: Add failing axis and zoom tests**

Append to `frequi/tests/unit/candleChartAxis.spec.ts`:

```ts
import { getAxisDomain, withLinkedValueAxisMapping } from '@/utils/charts/candleChartAxis';

it('derives a numeric display-axis domain from sequential candle indexes', () => {
  expect(
    getAxisDomain([
      [1_782_000_000_000, 0],
      [1_782_003_600_000, 1],
      [1_782_090_000_000, 2],
    ], 1),
  ).toEqual({ min: 0, max: 2 });
});

it('builds linked value axes for compressed trading-session coordinates', () => {
  const formatter = (value: unknown) => `label:${value}`;

  expect(
    withLinkedValueAxisMapping({ type: 'value', gridIndex: 1 }, { min: 0, max: 2 }, formatter),
  ).toEqual({
    type: 'value',
    gridIndex: 1,
    boundaryGap: [0, 0],
    containShape: false,
    min: 0,
    max: 2,
    minInterval: 1,
    maxInterval: 1,
    axisLabel: {
      formatter,
      hideOverlap: true,
    },
  });
});
```

Append to `frequi/tests/unit/chartZoom.spec.ts`:

```ts
import { buildInitialDataZoomRange } from '@/utils/charts/chartZoom';

it('builds the initial zoom window from a generic display x column', () => {
  const rows = [
    [1_782_000_000_000, 0],
    [1_782_003_600_000, 1],
    [1_782_090_000_000, 2],
    [1_782_093_600_000, 3],
  ];

  expect(buildInitialDataZoomRange(rows, 1, 2)).toEqual({
    startValue: 2,
    endValue: 3,
  });
});
```

- [ ] **Step 2: Add the failing tooltip test**

Append to `frequi/tests/unit/candleChartTooltip.spec.ts`:

```ts
it('renders the real row timestamp when the x axis uses a synthetic display index', () => {
  const realTimestamp = 1_783_482_540_000;
  const chartOptions = shallowRef<EChartsOption>({
    dataset: {
      source: [[realTimestamp, 400, 402, 399, 401, 1000, 1]],
    },
    series: [
      {
        name: 'Candles',
        type: 'candlestick',
        yAxisIndex: 0,
        encode: {
          x: 6,
          y: [1, 4, 3, 2],
        },
      },
    ],
  });

  const html = useCandleChartTooltip(chartOptions).formatCandleTooltip([
    {
      componentType: 'series',
      seriesIndex: 0,
      seriesName: 'Candles',
      seriesType: 'candlestick',
      axisValue: 1,
      axisValueLabel: '1',
      marker: '<span></span>',
      encode: {
        x: [6],
        y: [1, 4, 3, 2],
      },
      value: [realTimestamp, 400, 402, 399, 401, 1000, 1],
    },
  ] as never);

  expect(html).toContain('2026-07');
  expect(html).not.toContain('1970');
});
```

- [ ] **Step 3: Run the failing frontend utility tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm test:unit tests/unit/candleChartAxis.spec.ts tests/unit/chartZoom.spec.ts tests/unit/candleChartTooltip.spec.ts --run
```

Expected: FAIL on missing helpers and tooltip timestamp behavior.

- [ ] **Step 4: Add generic axis helpers**

In `frequi/src/utils/charts/candleChartAxis.ts`, add:

```ts
export const REAL_TIMESTAMP_LOWER_BOUND_MS = Date.UTC(2000, 0, 1);

export function getAxisDomain(rows: number[][], axisColumn: number): TimeAxisDomain | undefined {
  return getTimeAxisDomain(rows, axisColumn);
}

export function withLinkedValueAxisMapping<const TAxis extends Record<string, unknown>>(
  axis: TAxis,
  domain: TimeAxisDomain | undefined,
  formatter?: (value: unknown) => string,
) {
  const existingAxisLabel =
    axis.axisLabel && typeof axis.axisLabel === 'object' && !Array.isArray(axis.axisLabel)
      ? axis.axisLabel
      : {};
  const valueAxis = withTimeAxisDomain(
    {
      ...axis,
      boundaryGap: [0, 0] as [number, number],
      containShape: false,
      minInterval: 1,
      maxInterval: 1,
      ...(formatter
        ? {
            axisLabel: {
              ...existingAxisLabel,
              formatter,
              hideOverlap: true,
            },
          }
        : {}),
    },
    domain,
  );

  return valueAxis;
}

export function isLikelyMillisecondTimestamp(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isFinite(value) &&
    value >= REAL_TIMESTAMP_LOWER_BOUND_MS
  );
}
```

- [ ] **Step 5: Add generic zoom helper**

In `frequi/src/utils/charts/chartZoom.ts`, replace `buildInitialTimeDataZoomRange` with a generic helper plus wrapper:

```ts
export function buildInitialDataZoomRange(
  rows: number[][],
  axisColumn: number,
  visibleCandleCount: number,
): DataZoomWindow | undefined {
  if (axisColumn < 0 || rows.length === 0) {
    return undefined;
  }

  let endValue: number | undefined;
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const value = rows[index]?.[axisColumn];
    if (isFiniteNumber(value)) {
      endValue = value;
      break;
    }
  }
  const visibleRows = Math.max(1, Math.floor(visibleCandleCount));
  const startIndex = Math.max(0, rows.length - visibleRows);
  const startValue = rows.slice(startIndex).find((row) => isFiniteNumber(row[axisColumn]))?.[
    axisColumn
  ];

  if (!isFiniteNumber(startValue) || !isFiniteNumber(endValue)) {
    return undefined;
  }

  return { startValue, endValue };
}

export function buildInitialTimeDataZoomRange(
  rows: number[][],
  dateColumn: number,
  visibleCandleCount: number,
): DataZoomWindow | undefined {
  return buildInitialDataZoomRange(rows, dateColumn, visibleCandleCount);
}
```

- [ ] **Step 6: Update tooltip timestamp selection**

In `frequi/src/composables/useCandleChartTooltip.ts`, import:

```ts
import { isLikelyMillisecondTimestamp } from '@/utils/charts/candleChartAxis';
```

Replace `formatTooltipTimestamp` with:

```ts
function firstTimestampFromValue(value: unknown): number | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const candidate = Number(value[0]);
  return isLikelyMillisecondTimestamp(candidate) ? candidate : undefined;
}

function formatTooltipTimestamp(param: CandleTooltipParam): string {
  const rowTimestamp = firstTimestampFromValue(param.value);
  if (rowTimestamp !== undefined) {
    return timestampms(rowTimestamp);
  }

  const axisValueTimestamp = Number(param.axisValue);
  if (isLikelyMillisecondTimestamp(axisValueTimestamp)) {
    return timestampms(axisValueTimestamp);
  }

  const axisLabelTimestamp = Number(param.axisValueLabel);
  if (isLikelyMillisecondTimestamp(axisLabelTimestamp)) {
    return timestampms(axisLabelTimestamp);
  }

  return param.axisValueLabel ?? param.axisValue?.toString() ?? '';
}
```

- [ ] **Step 7: Run utility tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm test:unit tests/unit/candleChartAxis.spec.ts tests/unit/chartZoom.spec.ts tests/unit/candleChartTooltip.spec.ts --run
```

Expected: PASS.

---

### Task 4: Wire Trading-Session Axis into CandleChart

**Files:**
- Modify: `frequi/src/components/charts/CandleChart.vue`
- Test: `frequi/tests/component/CandleChart.spec.ts`

**Interfaces:**
- Consumes: `getChartAxisMode(meta)`
- Consumes: `buildTradingSessionAxisDataset(columns, rows, timestampColumn)`
- Consumes: `withLinkedValueAxisMapping(axis, domain, formatter)`
- Produces: compressed x coordinates for A-share research charts only

- [ ] **Step 1: Write the failing component test**

Append to `frequi/tests/component/CandleChart.spec.ts`:

```ts
function aShareTradingSessionDataset(): PairHistory & { meta: ChartResponseMeta } {
  return {
    strategy: '',
    pair: '688017.SH',
    timeframe: '1m',
    timeframe_ms: 60000,
    columns: ['__date_ts', 'open', 'high', 'low', 'close', 'volume'],
    all_columns: ['__date_ts', 'open', 'high', 'low', 'close', 'volume'],
    data: [
      [Date.UTC(2026, 6, 8, 2, 29), 400, 401, 399, 400.5, 1000],
      [Date.UTC(2026, 6, 8, 3, 16), 401, 402, 400, 401.5, 1100],
      [Date.UTC(2026, 6, 8, 5, 0), 402, 403, 401, 402.5, 1200],
    ],
    annotations: [],
    length: 3,
    buy_signals: 0,
    sell_signals: 0,
    last_analyzed: 0,
    data_start_ts: Date.UTC(2026, 6, 8, 2, 29),
    data_start: '2026-07-08 02:29:00+00:00',
    data_stop: '2026-07-08 05:00:00+00:00',
    data_stop_ts: Date.UTC(2026, 6, 8, 5, 0),
    meta: {
      schema_version: 1,
      window: {
        requested_count: 3,
        returned_count: 3,
        warmup_count: 0,
        last_candle_complete: true,
      },
      axis: {
        mode: 'trading_session',
        source_column: '__date_ts',
        display_column: '__display_x',
        timezone: 'Asia/Shanghai',
      },
      layers: [],
      warnings: [],
    },
  };
}

it('uses a sequential display x axis for A-share trading-session chart metadata', async () => {
  mount(CandleChart, {
    props: {
      trades: [],
      dataset: aShareTradingSessionDataset(),
      heikinAshi: false,
      showMarkArea: false,
      useUTC: true,
      plotConfig: { main_plot: {}, subplots: {} },
      theme: 'dark',
      colorUp: '#00ff00',
      colorDown: '#ff0000',
      labelSide: 'right',
      startCandleCount: 250,
    },
  });

  await nextTick();

  const option = setOptionMock.mock.calls.at(-1)?.[0] as {
    dataset?: { source?: number[][] };
    xAxis?: Array<{ type?: string; min?: number; max?: number }>;
    series?: Array<{ encode?: { x?: number } }>;
  };

  expect(option.dataset?.source?.map((row) => row[0]).slice(0, 3)).toEqual(
    aShareTradingSessionDataset().data.map((row) => row[0]),
  );
  expect(option.dataset?.source?.map((row) => row[6]).slice(0, 3)).toEqual([0, 1, 2]);
  expect(option.xAxis?.[0]?.type).toBe('value');
  expect(option.xAxis?.[0]?.min).toBe(0);
  expect(option.xAxis?.[0]?.max).toBe(7);
  expect(option.series?.[0]?.encode?.x).toBe(6);
  expect(option.series?.[1]?.encode?.x).toBe(6);
});
```

- [ ] **Step 2: Run the failing component test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm test:unit tests/component/CandleChart.spec.ts --run
```

Expected: FAIL because `CandleChart.vue` still uses `__date_ts` and `type: 'time'`.

- [ ] **Step 3: Import the new helpers**

In `frequi/src/components/charts/CandleChart.vue`, extend imports:

```ts
import {
  createLinkedTimeAxisPointer,
  createMainPriceAxisPointer,
  getAxisDomain,
  getTimeAxisDomain,
  withLinkedTimeAxisMapping,
  withLinkedValueAxisMapping,
} from '@/utils/charts/candleChartAxis';
import {
  TRADING_SESSION_DISPLAY_COLUMN,
  buildTradingSessionAxisDataset,
  getChartAxisMode,
  getTimestampForDisplayValue,
  type TradingSessionAxisDataset,
} from '@/utils/charts/candleChartTradingAxis';
```

Update chart zoom import:

```ts
import {
  buildInitialDataZoomRange,
  buildLinkedDataZoomOptions,
  captureDataZoomRange,
  createAxisIndexes,
  restoreDataZoomRange,
} from '@/utils/charts/chartZoom';
```

- [ ] **Step 3A: Add persistent crosshair axis refs**

Near the existing `crosshairDateColumn` state, add refs for the active x-axis mapping so `updateCrosshairGraphic()` can use the latest chart axis mode outside `updateChart()`:

```ts
const crosshairDateColumn = ref(-1);
const crosshairXColumn = ref(-1);
const crosshairAxisMode = ref<CandleChartAxisMode>('time');
const crosshairGridCount = ref(0);
```

- [ ] **Step 4: Build the display dataset inside `updateChart`**

Replace the current `colDate` and dataset setup block with this structure:

```ts
const rawDateColumn = columns.findIndex((el) => el === '__date_ts');
const axisMode = getChartAxisMode(chartMeta.value);

let dataset = props.heikinAshi
  ? heikinAshiDataset(columns, props.dataset.data)
  : props.dataset.data.slice();

let xColumn = rawDateColumn;
let timestampColumn = rawDateColumn;
let tradingAxisDataset: TradingSessionAxisDataset | undefined;

if (axisMode === 'trading_session' && rawDateColumn >= 0) {
  tradingAxisDataset = buildTradingSessionAxisDataset(
    columns,
    dataset,
    rawDateColumn,
    chartMeta.value?.axis?.display_column ?? TRADING_SESSION_DISPLAY_COLUMN,
  );
  columns.splice(0, columns.length, ...tradingAxisDataset.columns);
  dataset = tradingAxisDataset.rows;
  xColumn = tradingAxisDataset.displayColumn;
  timestampColumn = tradingAxisDataset.timestampColumn;
}
```

Keep the existing diff-column block after this dataset construction. When calling `calculateDiff`, continue passing the current `columns` and `dataset`.

- [ ] **Step 5: Update scroll padding and axis domain**

Replace `crosshairDateColumn`, scroll padding, and time-axis domain setup with:

```ts
crosshairRows.value = dataset.slice();
crosshairDateColumn.value = timestampColumn;
crosshairXColumn.value = xColumn;
crosshairAxisMode.value = axisMode;
const lastXValue = dataset[dataset.length - 1]?.[xColumn];
if (lastXValue !== undefined) {
  const newArray = Array(columns.length);
  newArray[xColumn] =
    axisMode === 'trading_session'
      ? Number(lastXValue) + scrollPastLength
      : Number(lastXValue) + props.dataset.timeframe_ms * scrollPastLength;
  dataset.push(newArray);
}
const xAxisDomain =
  axisMode === 'trading_session'
    ? getAxisDomain(dataset, xColumn)
    : getTimeAxisDomain(dataset, xColumn);
```

- [ ] **Step 6: Use `xColumn` for all x encodings**

In `CandleChart.vue`, replace all `encode: { x: colDate, ... }` with:

```ts
encode: {
  x: xColumn,
  y: [colOpen, colClose, colLow, colHigh],
}
```

For volume, scatter signals, indicator lines, and subplot series, use:

```ts
encode: {
  x: xColumn,
  y: colVolume,
}
```

or the matching existing y column for that series.

- [ ] **Step 7: Build x axes by mode**

Inside `updateChart`, add:

```ts
const formatTradingAxisLabel = (value: unknown): string => {
  if (!tradingAxisDataset) {
    return '';
  }
  const timestamp = getTimestampForDisplayValue(tradingAxisDataset, value);
  return timestamp ? timestampms(timestamp) : '';
};

const buildXAxis = (gridIndex?: number) =>
  axisMode === 'trading_session'
    ? withLinkedValueAxisMapping(
        {
          type: 'value',
          ...(gridIndex !== undefined ? { gridIndex } : {}),
          axisLine: { onZero: false },
          axisTick: { show: gridIndex === undefined },
          axisLabel: { show: gridIndex === undefined },
          axisPointer: createLinkedTimeAxisPointer(),
          position: gridIndex === undefined ? 'top' : undefined,
          splitLine: { show: false },
          splitNumber: 20,
        },
        xAxisDomain,
        formatTradingAxisLabel,
      )
    : withLinkedTimeAxisMapping(
        {
          type: 'time',
          ...(gridIndex !== undefined ? { gridIndex } : {}),
          axisLine: { onZero: false },
          axisTick: { show: gridIndex === undefined },
          axisLabel: { show: gridIndex === undefined },
          axisPointer: createLinkedTimeAxisPointer(),
          position: gridIndex === undefined ? 'top' : undefined,
          splitLine: { show: false },
          splitNumber: 20,
        },
        xAxisDomain,
      );
```

Then replace the initial `xAxis` array with:

```ts
xAxis: [buildXAxis(), buildXAxis(1)],
```

When adding subplot x axes later in the file, call `buildXAxis(plotIndex)` instead of constructing a hard-coded `type: 'time'` axis.

- [ ] **Step 8: Update crosshair display-to-real timestamp mapping**

In `updateCrosshairGraphic`, rename the pointer value and use `xColumn` for nearest-row lookup:

```ts
const pointerXValue = getTimeValueAtPixel(chart, hitGridIndex, x);
if (pointerXValue === undefined) {
  hideCrosshair();
  return;
}

const dataIndex = findNearestCandleIndex(
  crosshairRows.value,
  crosshairAxisMode.value === 'trading_session' ? crosshairXColumn.value : crosshairDateColumn.value,
  pointerXValue,
);
```

Keep `crosshairSelection.value` using the real timestamp:

```ts
crosshairSelection.value = { dataIndex, timestamp };
```

For projection, use the display x value in compressed mode:

```ts
const projectionValue =
  crosshairAxisMode.value === 'trading_session' && selectedRow
    ? Number(selectedRow[crosshairXColumn.value])
    : timestamp;
const projections = getTimeAxisGridProjections(chart, crosshairGridCount.value, projectionValue);
```

- [ ] **Step 9: Update dataZoom initialization**

Replace:

```ts
const initialZoomRange =
  currentZoomRange ??
  (colDate >= 0
    ? buildInitialTimeDataZoomRange(props.dataset.data, colDate, props.startCandleCount + 2)
    : undefined);
```

with:

```ts
const initialZoomRange =
  currentZoomRange ??
  (xColumn >= 0
    ? buildInitialDataZoomRange(dataset, xColumn, props.startCandleCount + 2)
    : undefined);
```

- [ ] **Step 10: Keep slider positions on real time only**

Leave `updateSliderPosition()` unchanged for this task. It is driven by external timestamp ranges and is not used by the A-share research chart path in Phase 1C. Add this guard at the top to avoid wrong synthetic-axis zoom when a caller sends timestamp slider positions into a compressed chart:

```ts
if (getChartAxisMode(chartMeta.value) === 'trading_session') {
  return;
}
```

- [ ] **Step 11: Run component test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm test:unit tests/component/CandleChart.spec.ts --run
```

Expected: PASS.

---

### Task 5: Regression, Browser Validation, and Documentation

**Files:**
- Modify: `docs/a-share-research-data.md`
- Validate: browser at `http://127.0.0.1:8082/research`

**Interfaces:**
- Consumes: Task 1 API metadata
- Consumes: Task 4 chart rendering behavior
- Produces: documented user-facing behavior for compressed A-share charts

- [ ] **Step 1: Document the display invariant**

Add this section to `docs/a-share-research-data.md`:

```markdown
## A-share chart axis behavior

A-share OHLCV files keep real timestamps. Research charts compress non-trading time in the display axis when API metadata returns `meta.axis.mode = "trading_session"`.

This means:

- 09:30-11:30 and 13:00-15:00 candles are drawn as adjacent trading bars.
- Lunch break, overnight gaps, weekends, and holidays do not consume horizontal chart space.
- Tooltip and crosshair labels still show the original candle timestamp.
- Backtests and market rules continue to use real timestamps, trading calendars, T+1, limit-up/down, and suspension state.
- Missing candles inside an open trading session remain data-quality issues and must not be hidden as closed-market compression.
```

- [ ] **Step 2: Run focused backend tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe -m pytest tests/rpc/test_api_research.py tests/research/test_a_share_sessions.py tests/research/test_data_source.py -q
```

Expected: PASS.

- [ ] **Step 3: Run focused frontend tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm test:unit tests/unit/candleChartTradingAxis.spec.ts tests/unit/candleChartAxis.spec.ts tests/unit/chartZoom.spec.ts tests/unit/candleChartTooltip.spec.ts tests/component/CandleChart.spec.ts --run
```

Expected: PASS.

- [ ] **Step 4: Run frontend typecheck**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm typecheck
```

Expected: PASS.

- [ ] **Step 5: Run lint on touched frontend files**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm lint-ci src/types/candleTypes.ts src/utils/charts/candleChartTradingAxis.ts src/utils/charts/candleChartAxis.ts src/utils/charts/chartZoom.ts src/composables/useCandleChartTooltip.ts src/components/charts/CandleChart.vue tests/unit/candleChartTradingAxis.spec.ts tests/unit/candleChartAxis.spec.ts tests/unit/chartZoom.spec.ts tests/unit/candleChartTooltip.spec.ts tests/component/CandleChart.spec.ts
```

Expected: PASS.

- [ ] **Step 6: Browser validation with real A-share data**

Use the in-app browser and verify these actions:

1. Open `http://127.0.0.1:8082/research`.
2. Select bot `A Share Local`.
3. Select instrument `688017`.
4. Select timeframe `1m`.
5. Click `Refresh chart / 刷新图表`.
6. Confirm the chart still shows `688017.SH` and the real data range.
7. Confirm visible candles are adjacent across lunch/overnight gaps rather than separated by large blank regions.
8. Hover/crosshair a candle and confirm tooltip timestamp is a real 2026 A-share candle time, not `1970` and not a small display index.
9. Click `Run backtest / 运行回测` and confirm backtest result still renders.

Expected: chart readability improves without changing backtest output.

---

## Self-Review

- Spec coverage: This plan covers closed-market blank-space compression, raw timestamp preservation, A-share first delivery, future market extensibility, chart/crosshair/tooltip behavior, and validation.
- Placeholder scan: No step relies on unspecified behavior. Each code-changing step includes concrete code.
- Type consistency: Backend `ChartAxisMeta` maps to frontend `ChartAxisMeta`; `axis.mode` uses the same `"time" | "trading_session"` values; display column uses `__display_x` consistently.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-08-a-share-trading-session-chart-axis.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.
