# Chart Data Source Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate market, watch, strategy, and decision data semantics in the chart pipeline so FreqUI can display one aligned chart with explicit source, coverage, warmup, and trust metadata.

**Architecture:** Preserve the current `/api/v1/chart_candles` flattened data response during P0 and P1, but add metadata that describes layers and coverage. Introduce a backend `ChartComposition` read model in P1 so chart composition is explicit instead of encoded in dataframe column prefixes. Move FreqUI toward metadata-driven labels, tooltips, and layer grouping in P2. Add decision snapshots in P3 as the source of truth for real bot decision explanations.

**Tech Stack:** Python, pandas, Pydantic v2, FastAPI routing, pytest, TypeScript, Vue 3, ECharts, Vitest.

---

## File Structure

### P0: Explicit Metadata on Current Response

- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
  - Add chart metadata DTOs and optional `meta` field to `ChartCandlesResponse`.
- Modify: `freqtrade/freqtrade/rpc/chart_data.py`
  - Build window, layer, series, coverage, source, and warning metadata from the current response dataframe.
- Modify: `freqtrade/tests/rpc/test_chart_data.py`
  - Cover metadata for default watch indicators, partial strategy overlay, hidden overlay, and live candle status.
- Modify: `frequi/src/types/candleTypes.ts`
  - Add TypeScript interfaces matching the new chart metadata.
- Create: `frequi/src/utils/charts/chartSeriesMeta.ts`
  - Provide lookup helpers for series labels, sources, coverage, and tooltip grouping.
- Create: `frequi/tests/unit/chartSeriesMeta.spec.ts`
  - Cover metadata lookup and fallback behavior.
- Modify: `frequi/src/utils/charts/candleChartSeries.ts`
  - Use metadata labels when available while keeping current column-name fallbacks.
- Modify: `frequi/src/composables/useCandleChartTooltip.ts`
  - Group tooltip output by source when metadata exists.
- Modify: `frequi/tests/unit/candleChartTooltip.spec.ts`
  - Cover source-grouped tooltip output.

### P1: Backend ChartComposition Read Model

- Create: `freqtrade/freqtrade/rpc/chart_composition.py`
  - Own internal `ChartFrame`, `ChartLayer`, `ChartSeries`, `LayerCoverage`, and `ChartComposition` structures.
- Create: `freqtrade/tests/rpc/test_chart_composition.py`
  - Cover frame construction, coverage, source separation, and legacy response conversion.
- Modify: `freqtrade/freqtrade/rpc/chart_data.py`
  - Build a `ChartComposition` first, then convert it to the legacy `/chart_candles` response.
- Modify: `freqtrade/tests/rpc/test_chart_data.py`
  - Keep existing response compatibility tests passing and add tests that prove metadata comes from composition.

### P2: Metadata-Driven Frontend Layers and Explicit Windows

- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
  - Add optional explicit window request fields while preserving `limit`.
- Modify: `freqtrade/freqtrade/rpc/chart_data.py`
  - Separate data window, display window hint, warmup window, and strategy coverage in metadata.
- Modify: `freqtrade/tests/rpc/test_chart_data.py`
  - Cover explicit data window and display window metadata.
- Modify: `frequi/src/stores/settings.ts`
  - Add `chartDataCandleCount` for backend data count and keep `chartDefaultCandleCount` as display zoom count.
- Modify: `frequi/src/views/SettingsView.vue`
  - Expose backend data count separately from default visible candle count.
- Modify: `frequi/src/composables/useLiveChartDataset.ts`
  - Send `limit: settingsStore.chartDataCandleCount` when loading live chart candles.
- Modify: `frequi/src/components/charts/SingleCandleChartContainer.vue`
  - Keep `chartDefaultCandleCount` as initial viewport only.
- Modify: `frequi/src/components/charts/CandleChart.vue`
  - Use layer metadata for legend labels, source grouping, and coverage warnings.
- Modify: `frequi/tests/unit/useLiveChartDataset.spec.ts`
  - Verify chart data count is sent as backend limit.
- Modify: `frequi/tests/component/SingleCandleChartContainer.spec.ts`
  - Verify display count remains a viewport concern.
- Modify: `frequi/tests/unit/candleChartSeries.spec.ts`
  - Verify metadata-driven labels and fallback labels.

### P3: Decision Snapshot Evidence

- Create: `freqtrade/freqtrade/persistence/decision_snapshot_model.py`
  - Store decision-time evidence for bot explanations.
- Modify: `freqtrade/freqtrade/persistence/__init__.py`
  - Export `DecisionSnapshot`.
- Modify: `freqtrade/freqtrade/persistence/migrations.py`
  - Add database migration for decision snapshots.
- Create: `freqtrade/freqtrade/rpc/decision_snapshots.py`
  - Read decision snapshots and adapt them to chart layers.
- Modify: `freqtrade/freqtrade/rpc/chart_data.py`
  - Add optional decision snapshot layer metadata when snapshots exist.
- Modify: `freqtrade/tests/persistence/test_decision_snapshot_model.py`
  - Cover persistence, JSON payload, and trade/order links.
- Create: `freqtrade/tests/rpc/test_decision_snapshots.py`
  - Cover snapshot-to-chart-layer conversion.
- Modify: `frequi/src/types/candleTypes.ts`
  - Add decision snapshot layer metadata typing.
- Modify: `frequi/src/composables/useCandleChartTooltip.ts`
  - Show decision snapshot values above strategy output and watch indicators.
- Modify: `frequi/tests/unit/candleChartTooltip.spec.ts`
  - Verify tooltip trust ordering: decision snapshot, strategy output, watch indicators.

---

## P0: Make Current Behavior Explicit

P0 must not change strategy trading behavior or the existing flattened chart data shape.

### Task P0.1: Add Chart Metadata DTOs

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/tests/rpc/test_chart_data.py`

- [ ] **Step 1: Add failing metadata assertions**

Add a test to `freqtrade/tests/rpc/test_chart_data.py` that builds a default chart response and asserts:

```python
assert response["meta"]["schema_version"] == 1
assert response["meta"]["window"]["requested_count"] == 50
assert response["meta"]["window"]["returned_count"] == 50
assert response["meta"]["window"]["warmup_count"] == CHART_WARMUP_CANDLES
assert any(layer["source"] == "watch" for layer in response["meta"]["layers"])
```

Run:

```powershell
pytest tests/rpc/test_chart_data.py::test_build_chart_candles_response_includes_chart_meta -q
```

Expected: FAIL because `meta` is not present.

- [ ] **Step 2: Add Pydantic metadata models**

In `freqtrade/freqtrade/rpc/api_server/api_schemas.py`, add these models near `ChartOverlayMeta`:

```python
class ChartWindowMeta(BaseModel):
    requested_count: int
    returned_count: int
    warmup_count: int
    display_default_count: int | None = None
    data_start: str | None = None
    data_stop: str | None = None
    last_candle_complete: bool = True


class ChartSeriesCoverage(BaseModel):
    first_valid: str | None = None
    last_valid: str | None = None
    valid_points: int = 0
    total_points: int = 0
    warmup_until: str | None = None
    reason: str | None = None


class ChartSeriesMeta(BaseModel):
    column: str
    label: str
    source: Literal["market", "watch", "strategy", "execution", "decision_snapshot", "recomputed"]
    kind: str
    panel: str
    timeframe: str | None = None
    visible: bool = True
    coverage: ChartSeriesCoverage
    provisional: bool = False


class ChartLayerMeta(BaseModel):
    id: str
    source: Literal["market", "watch", "strategy", "execution", "decision_snapshot", "recomputed"]
    status: Literal["ok", "partial", "hidden", "unavailable", "stale", "provisional"]
    label: str
    timeframe: str | None = None
    alignment: str | None = None
    series: list[ChartSeriesMeta] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ChartResponseMeta(BaseModel):
    schema_version: int = 1
    window: ChartWindowMeta
    layers: list[ChartLayerMeta] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

Then extend `ChartCandlesResponse`:

```python
    meta: ChartResponseMeta | None = None
```

- [ ] **Step 3: Run the metadata test and verify it still fails for missing builder**

Run:

```powershell
pytest tests/rpc/test_chart_data.py::test_build_chart_candles_response_includes_chart_meta -q
```

Expected: FAIL because the schema allows `meta`, but `build_chart_candles_response` does not populate it yet.

### Task P0.2: Build Backend Source and Coverage Metadata

**Files:**
- Modify: `freqtrade/freqtrade/rpc/chart_data.py`
- Modify: `freqtrade/tests/rpc/test_chart_data.py`

- [ ] **Step 1: Add focused tests for watch and strategy coverage**

Add `test_chart_meta_separates_watch_and_strategy_sources` in `freqtrade/tests/rpc/test_chart_data.py`. Build a response with `build_chart_candles_response` using the existing local RPC mock pattern in that file, then assert:

```python
layers = response["meta"]["layers"]
watch_layer = next(layer for layer in layers if layer["source"] == "watch")
strategy_layer = next(layer for layer in layers if layer["source"] == "strategy")
assert watch_layer["label"] == "Watch Indicators"
assert strategy_layer["label"] == "Strategy Output"
assert all(series["source"] == "watch" for series in watch_layer["series"])
assert all(series["source"] == "strategy" for series in strategy_layer["series"])
```

Add `test_chart_meta_marks_partial_strategy_coverage` in the same file. Build a chart response where the mocked strategy analyzed dataframe starts later than the market dataframe, then assert:

```python
strategy_layer = next(layer for layer in response["meta"]["layers"] if layer["source"] == "strategy")
assert strategy_layer["status"] == "partial"
assert any(
    series["coverage"]["valid_points"] < series["coverage"]["total_points"]
    for series in strategy_layer["series"]
)
```

Run:

```powershell
pytest tests/rpc/test_chart_data.py::test_chart_meta_separates_watch_and_strategy_sources tests/rpc/test_chart_data.py::test_chart_meta_marks_partial_strategy_coverage -q
```

Expected: FAIL because metadata builder does not exist.

- [ ] **Step 2: Add metadata builder helpers**

In `freqtrade/freqtrade/rpc/chart_data.py`, import new schema classes:

```python
from freqtrade.rpc.api_server.api_schemas import (
    ChartCandlesRequest,
    ChartLayerMeta,
    ChartOverlayMeta,
    ChartResponseMeta,
    ChartSeriesCoverage,
    ChartSeriesMeta,
    ChartWindowMeta,
)
```

Add helper functions:

```python
def _build_chart_response_meta(
    dataframe: DataFrame,
    payload: ChartCandlesRequest,
    plot_config: dict[str, Any],
    strategy_name: str,
    strategy_timeframe: str | None,
    overlay: ChartOverlayMeta | None,
    warnings: list[str],
) -> ChartResponseMeta:
    layers = [
        _build_market_layer_meta(dataframe, payload.timeframe),
        _build_watch_layer_meta(dataframe, plot_config, payload.timeframe),
    ]
    strategy_layer = _build_strategy_layer_meta(
        dataframe,
        plot_config,
        strategy_name,
        strategy_timeframe,
        overlay,
    )
    if strategy_layer:
        layers.append(strategy_layer)

    meta_warnings = list(warnings)
    for layer in layers:
        meta_warnings.extend(layer.warnings)

    return ChartResponseMeta(
        window=ChartWindowMeta(
            requested_count=payload.limit,
            returned_count=len(dataframe),
            warmup_count=CHART_WARMUP_CANDLES,
            data_start=_date_string(dataframe.iloc[0]["date"]) if not dataframe.empty else None,
            data_stop=_date_string(dataframe.iloc[-1]["date"]) if not dataframe.empty else None,
            last_candle_complete=payload.candle_mode == "closed"
            or _last_candle_complete(dataframe, payload.timeframe),
        ),
        layers=layers,
        warnings=list(dict.fromkeys(meta_warnings)),
    )
```

Implement these helpers in the same file:

```python
def _build_market_layer_meta(dataframe: DataFrame, timeframe: str) -> ChartLayerMeta:
    series = [
        _series_meta(dataframe, "open", "Open", "market", "ohlcv", "main", timeframe),
        _series_meta(dataframe, "high", "High", "market", "ohlcv", "main", timeframe),
        _series_meta(dataframe, "low", "Low", "market", "ohlcv", "main", timeframe),
        _series_meta(dataframe, "close", "Close", "market", "ohlcv", "main", timeframe),
        _series_meta(dataframe, "volume", "Volume", "market", "bar", "volume", timeframe),
    ]
    return ChartLayerMeta(
        id="market.ohlcv",
        source="market",
        status="ok",
        label="Market Data",
        timeframe=timeframe,
        alignment="direct",
        series=series,
    )
```

```python
def _build_watch_layer_meta(
    dataframe: DataFrame, plot_config: dict[str, Any], timeframe: str
) -> ChartLayerMeta:
    series = []
    for panel, column, config in _iter_plot_columns(plot_config):
        if column.startswith("watch_") and column in dataframe.columns:
            series.append(
                _series_meta(
                    dataframe,
                    column,
                    _watch_series_label(column),
                    "watch",
                    str(config.get("type", "line")) if isinstance(config, dict) else "line",
                    panel,
                    timeframe,
                    visible=not (isinstance(config, dict) and config.get("hidden") is True),
                )
            )
    status = "partial" if any(s.coverage.valid_points < s.coverage.total_points for s in series) else "ok"
    return ChartLayerMeta(
        id="watch.indicators",
        source="watch",
        status=status,
        label="Watch Indicators",
        timeframe=timeframe,
        alignment="direct",
        series=series,
    )
```

```python
def _build_strategy_layer_meta(
    dataframe: DataFrame,
    plot_config: dict[str, Any],
    strategy_name: str,
    strategy_timeframe: str | None,
    overlay: ChartOverlayMeta | None,
) -> ChartLayerMeta | None:
    if not strategy_timeframe:
        return None
    if overlay and overlay.hidden:
        return ChartLayerMeta(
            id="strategy.overlay",
            source="strategy",
            status="hidden" if overlay.alignment == "hidden" else "unavailable",
            label="Strategy Output",
            timeframe=strategy_timeframe,
            alignment=overlay.alignment,
            warnings=[overlay.warning] if overlay.warning else [],
        )

    series = []
    for panel, column, config in _iter_plot_columns(plot_config):
        if column.startswith(f"strategy_{strategy_timeframe}_") and column in dataframe.columns:
            original = column.removeprefix(f"strategy_{strategy_timeframe}_")
            series.append(
                _series_meta(
                    dataframe,
                    column,
                    f"{original} - Strategy Output - {strategy_name}",
                    "strategy",
                    str(config.get("type", "line")) if isinstance(config, dict) else "line",
                    panel,
                    strategy_timeframe,
                )
            )
    if not series and not overlay:
        return None
    status = "partial" if any(s.coverage.valid_points < s.coverage.total_points for s in series) else "ok"
    return ChartLayerMeta(
        id="strategy.overlay",
        source="strategy",
        status=status,
        label="Strategy Output",
        timeframe=strategy_timeframe,
        alignment=overlay.alignment if overlay else None,
        series=series,
    )
```

Also add:

```python
def _series_meta(
    dataframe: DataFrame,
    column: str,
    label: str,
    source: str,
    kind: str,
    panel: str,
    timeframe: str | None,
    visible: bool = True,
) -> ChartSeriesMeta:
    return ChartSeriesMeta(
        column=column,
        label=label,
        source=source,
        kind=kind,
        panel=panel,
        timeframe=timeframe,
        visible=visible,
        coverage=_series_coverage(dataframe, column),
    )
```

```python
def _series_coverage(dataframe: DataFrame, column: str) -> ChartSeriesCoverage:
    if column not in dataframe.columns or dataframe.empty:
        return ChartSeriesCoverage(total_points=len(dataframe), reason="column unavailable")
    valid_mask = dataframe[column].notna()
    valid_points = int(valid_mask.sum())
    if valid_points == 0:
        return ChartSeriesCoverage(
            valid_points=0,
            total_points=len(dataframe),
            reason="no valid values in returned window",
        )
    valid_rows = dataframe.loc[valid_mask, "date"]
    return ChartSeriesCoverage(
        first_valid=_date_string(valid_rows.iloc[0]),
        last_valid=_date_string(valid_rows.iloc[-1]),
        valid_points=valid_points,
        total_points=len(dataframe),
        reason="partial coverage" if valid_points < len(dataframe) else None,
    )
```

```python
def _iter_plot_columns(plot_config: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    result: list[tuple[str, str, dict[str, Any]]] = []
    for column, config in plot_config.get("main_plot", {}).items():
        result.append(("main", column, config if isinstance(config, dict) else {}))
    for subplot_name, subplot_columns in plot_config.get("subplots", {}).items():
        if not isinstance(subplot_columns, dict):
            continue
        for column, config in subplot_columns.items():
            result.append((str(subplot_name), column, config if isinstance(config, dict) else {}))
    return result
```

```python
def _date_string(value: Any) -> str:
    return str(pd.to_datetime(value, utc=True))
```

```python
def _watch_series_label(column: str) -> str:
    if column.startswith("watch_ma"):
        return f"MA({column.removeprefix('watch_ma')}) - Watch"
    if column.startswith("watch_rsi"):
        return f"RSI({column.removeprefix('watch_rsi')}) - Watch"
    if column.startswith("watch_qqe_mod_"):
        return f"QQE MOD {column.removeprefix('watch_qqe_mod_').replace('_', ' ').title()} - Watch"
    if column.startswith("watch_supertrend_"):
        return f"Supertrend {column.removeprefix('watch_supertrend_').replace('_', ' ').title()} - Watch"
    if column.startswith("watch_macd"):
        return f"{column.removeprefix('watch_').upper()} - Watch"
    return f"{column} - Watch"
```

- [ ] **Step 3: Attach metadata to chart response**

In `build_chart_candles_response`, after the call to `_trim_to_limit` and before `response.update`, build:

```python
    meta = _build_chart_response_meta(
        chart_dataframe,
        payload,
        plot_config,
        config.get("strategy", ""),
        strategy_timeframe,
        overlay,
        warnings,
    )
```

Then include:

```python
            "meta": meta.model_dump(),
```

- [ ] **Step 4: Run backend chart metadata tests**

Run:

```powershell
pytest tests/rpc/test_chart_data.py -q
```

Expected: PASS.

### Task P0.3: Add Frontend Metadata Types and Lookup Helpers

**Files:**
- Modify: `frequi/src/types/candleTypes.ts`
- Create: `frequi/src/utils/charts/chartSeriesMeta.ts`
- Create: `frequi/tests/unit/chartSeriesMeta.spec.ts`

- [ ] **Step 1: Add TypeScript metadata interfaces**

In `frequi/src/types/candleTypes.ts`, add:

```ts
export type ChartLayerSource =
  | 'market'
  | 'watch'
  | 'strategy'
  | 'execution'
  | 'decision_snapshot'
  | 'recomputed';

export interface ChartSeriesCoverage {
  first_valid?: string | null;
  last_valid?: string | null;
  valid_points: number;
  total_points: number;
  warmup_until?: string | null;
  reason?: string | null;
}

export interface ChartSeriesMeta {
  column: string;
  label: string;
  source: ChartLayerSource;
  kind: string;
  panel: string;
  timeframe?: string | null;
  visible: boolean;
  coverage: ChartSeriesCoverage;
  provisional: boolean;
}

export interface ChartLayerMeta {
  id: string;
  source: ChartLayerSource;
  status: 'ok' | 'partial' | 'hidden' | 'unavailable' | 'stale' | 'provisional';
  label: string;
  timeframe?: string | null;
  alignment?: string | null;
  series: ChartSeriesMeta[];
  warnings: string[];
}

export interface ChartWindowMeta {
  requested_count: number;
  returned_count: number;
  warmup_count: number;
  display_default_count?: number | null;
  data_start?: string | null;
  data_stop?: string | null;
  last_candle_complete: boolean;
}

export interface ChartResponseMeta {
  schema_version: number;
  window: ChartWindowMeta;
  layers: ChartLayerMeta[];
  warnings: string[];
}
```

Then extend `ChartCandlesResponse`:

```ts
  meta?: ChartResponseMeta | null;
```

- [ ] **Step 2: Add metadata lookup tests**

Create `frequi/tests/unit/chartSeriesMeta.spec.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
  getSeriesMetaByColumn,
  getSeriesSourceLabel,
  getSeriesTooltipGroup,
} from '@/utils/charts/chartSeriesMeta';
import type { ChartResponseMeta } from '@/types/candleTypes';

const meta: ChartResponseMeta = {
  schema_version: 1,
  window: {
    requested_count: 500,
    returned_count: 500,
    warmup_count: 120,
    last_candle_complete: true,
  },
  warnings: [],
  layers: [
    {
      id: 'watch.indicators',
      source: 'watch',
      status: 'ok',
      label: 'Watch Indicators',
      alignment: 'direct',
      warnings: [],
      series: [
        {
          column: 'watch_rsi14',
          label: 'RSI(14) - Watch',
          source: 'watch',
          kind: 'line',
          panel: 'RSI 14',
          visible: true,
          provisional: false,
          coverage: { valid_points: 486, total_points: 500 },
        },
      ],
    },
  ],
};

describe('chartSeriesMeta', () => {
  it('finds series metadata by column', () => {
    expect(getSeriesMetaByColumn(meta, 'watch_rsi14')?.label).toBe('RSI(14) - Watch');
  });

  it('returns fallback labels when metadata is unavailable', () => {
    expect(getSeriesSourceLabel(undefined, 'watch_rsi14')).toBe('watch_rsi14');
  });

  it('maps sources to tooltip groups', () => {
    expect(getSeriesTooltipGroup(meta, 'watch_rsi14')).toBe('Watch Indicators');
  });
});
```

Run:

```powershell
pnpm vitest run tests/unit/chartSeriesMeta.spec.ts
```

Expected: FAIL because helper module does not exist.

- [ ] **Step 3: Implement metadata lookup helpers**

Create `frequi/src/utils/charts/chartSeriesMeta.ts`:

```ts
import type { ChartResponseMeta, ChartSeriesMeta } from '@/types/candleTypes';

export function getSeriesMetaByColumn(
  meta: ChartResponseMeta | null | undefined,
  column: string,
): ChartSeriesMeta | undefined {
  return meta?.layers.flatMap((layer) => layer.series).find((series) => series.column === column);
}

export function getSeriesSourceLabel(
  meta: ChartResponseMeta | null | undefined,
  column: string,
): string {
  return getSeriesMetaByColumn(meta, column)?.label ?? column;
}

export function getSeriesTooltipGroup(
  meta: ChartResponseMeta | null | undefined,
  column: string,
): string {
  const layer = meta?.layers.find((candidate) =>
    candidate.series.some((series) => series.column === column),
  );
  return layer?.label ?? 'Other';
}

export function getSeriesCoverageReason(
  meta: ChartResponseMeta | null | undefined,
  column: string,
): string | undefined {
  return getSeriesMetaByColumn(meta, column)?.coverage.reason ?? undefined;
}
```

- [ ] **Step 4: Run helper tests**

Run:

```powershell
pnpm vitest run tests/unit/chartSeriesMeta.spec.ts
```

Expected: PASS.

### Task P0.4: Surface Metadata in Labels and Tooltip

**Files:**
- Modify: `frequi/src/utils/charts/candleChartSeries.ts`
- Modify: `frequi/src/composables/useCandleChartTooltip.ts`
- Modify: `frequi/tests/unit/candleChartSeries.spec.ts`
- Modify: `frequi/tests/unit/candleChartTooltip.spec.ts`

- [ ] **Step 1: Add tests for metadata labels and grouped tooltip**

Extend `frequi/tests/unit/candleChartSeries.spec.ts` with a case where `watch_rsi14` receives label `RSI(14) - Watch` from metadata.

Extend `frequi/tests/unit/candleChartTooltip.spec.ts` with a case where tooltip output includes group labels in this order:

```text
Candle
Strategy Output
Watch Indicators
```

Expected: tests fail because current label and tooltip paths do not use metadata.

- [ ] **Step 2: Thread metadata into series label generation**

Update `candleChartSeries.ts` functions that format watch or strategy names so they accept optional `ChartResponseMeta`.

Rule:

```ts
const label = getSeriesSourceLabel(meta, key);
```

Use the existing column-name label as fallback.

- [ ] **Step 3: Thread metadata into tooltip formatting**

Update `useCandleChartTooltip.ts` so formatter code groups tooltip entries by `getSeriesTooltipGroup(meta, column)`.

Keep the existing value formatter behavior. Metadata should only change grouping and labels in P0.

- [ ] **Step 4: Run focused frontend tests**

Run:

```powershell
pnpm vitest run tests/unit/chartSeriesMeta.spec.ts tests/unit/candleChartSeries.spec.ts tests/unit/candleChartTooltip.spec.ts
```

Expected: PASS.

### Task P0.5: P0 Verification

**Files:**
- No new source files beyond P0 tasks.

- [ ] **Step 1: Run backend tests**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
pytest tests/rpc/test_chart_data.py tests/rpc/test_chart_indicators.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend tests**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm vitest run tests/unit/chartSeriesMeta.spec.ts tests/unit/candleChartSeries.spec.ts tests/unit/candleChartTooltip.spec.ts
pnpm typecheck
```

Expected: PASS.

- [ ] **Step 3: Commit P0**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
git -C freqtrade add freqtrade/rpc/api_server/api_schemas.py freqtrade/rpc/chart_data.py tests/rpc/test_chart_data.py
git -C freqtrade commit -m "feat: add chart source metadata"
git -C frequi add src/types/candleTypes.ts src/utils/charts/chartSeriesMeta.ts src/utils/charts/candleChartSeries.ts src/composables/useCandleChartTooltip.ts tests/unit/chartSeriesMeta.spec.ts tests/unit/candleChartSeries.spec.ts tests/unit/candleChartTooltip.spec.ts
git -C frequi commit -m "feat: surface chart source metadata"
```

---

## P1: Introduce Backend ChartComposition

P1 is an internal backend refactor. The response must remain compatible with P0.

### Task P1.1: Add ChartComposition Model

**Files:**
- Create: `freqtrade/freqtrade/rpc/chart_composition.py`
- Create: `freqtrade/tests/rpc/test_chart_composition.py`

- [ ] **Step 1: Add failing composition tests**

Create `freqtrade/tests/rpc/test_chart_composition.py` with these three test functions:

- `test_chart_composition_keeps_frame_and_layers_separate`
- `test_chart_composition_to_legacy_update_contains_meta`
- `test_chart_composition_coverage_counts_valid_values_after_trim`

The tests should assert:

```python
assert composition.frame.timeframe == "1m"
assert composition.layers[0].source == "market"
assert legacy_update["meta"]["schema_version"] == 1
```

Run:

```powershell
pytest tests/rpc/test_chart_composition.py -q
```

Expected: FAIL because `chart_composition.py` does not exist.

- [ ] **Step 2: Implement composition data structures**

Create `freqtrade/freqtrade/rpc/chart_composition.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pandas import DataFrame

from freqtrade.rpc.api_server.api_schemas import ChartLayerMeta, ChartResponseMeta, ChartWindowMeta


@dataclass(frozen=True)
class ChartFrame:
    dataframe: DataFrame
    pair: str
    timeframe: str
    requested_count: int
    warmup_count: int
    last_candle_complete: bool


@dataclass(frozen=True)
class ChartLayer:
    id: str
    source: str
    label: str
    dataframe: DataFrame
    plot_config: dict[str, Any] = field(default_factory=dict)
    meta: ChartLayerMeta | None = None


@dataclass(frozen=True)
class ChartComposition:
    frame: ChartFrame
    layers: list[ChartLayer]
    plot_config: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    meta: ChartResponseMeta | None = None

    def legacy_update(self) -> dict[str, Any]:
        return {
            "plot_config": self.plot_config,
            "warnings": self.warnings,
            "meta": self.meta.model_dump() if self.meta else None,
            "last_candle_complete": self.frame.last_candle_complete,
        }
```

- [ ] **Step 3: Run composition tests**

Run:

```powershell
pytest tests/rpc/test_chart_composition.py -q
```

Expected: PASS after tests are aligned to the implemented constructor values.

### Task P1.2: Build ChartComposition in `chart_data`

**Files:**
- Modify: `freqtrade/freqtrade/rpc/chart_data.py`
- Modify: `freqtrade/tests/rpc/test_chart_data.py`

- [ ] **Step 1: Add compatibility tests**

In `freqtrade/tests/rpc/test_chart_data.py`, add assertions that:

```python
assert "columns" in response
assert "data" in response
assert "plot_config" in response
assert "meta" in response
assert response["meta"]["layers"]
```

Run:

```powershell
pytest tests/rpc/test_chart_data.py -q
```

Expected: PASS before refactor.

- [ ] **Step 2: Refactor `build_chart_candles_response` around composition**

In `chart_data.py`, add a helper:

```python
def build_chart_composition(
    rpc: RPC, config: dict[str, Any], payload: ChartCandlesRequest
) -> tuple[DataFrame, ChartComposition, str | None, ChartOverlayMeta | None]
```

The helper must:

- load market OHLCV;
- add watch indicators;
- merge strategy overlay if requested;
- trim to payload limit;
- build metadata;
- return the final dataframe and composition.

Keep `build_chart_candles_response` responsible for:

- calling `build_chart_composition`;
- calling `RPC._convert_dataframe_to_dict`;
- adding legacy response fields.

- [ ] **Step 3: Run backend compatibility tests**

Run:

```powershell
pytest tests/rpc/test_chart_data.py tests/rpc/test_chart_composition.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit P1**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
git -C freqtrade add freqtrade/rpc/chart_composition.py freqtrade/rpc/chart_data.py tests/rpc/test_chart_composition.py tests/rpc/test_chart_data.py
git -C freqtrade commit -m "refactor: compose chart response through chart composition"
```

---

## P2: Metadata-Driven Frontend Layers and Explicit Windows

P2 makes the frontend rely on metadata instead of column prefixes where metadata is available.

### Task P2.1: Separate Data Count from Display Count

**Files:**
- Modify: `frequi/src/stores/settings.ts`
- Modify: `frequi/src/views/SettingsView.vue`
- Modify: `frequi/src/composables/useLiveChartDataset.ts`
- Modify: `frequi/tests/unit/useLiveChartDataset.spec.ts`
- Modify: `frequi/tests/component/SingleCandleChartContainer.spec.ts`

- [ ] **Step 1: Add failing tests**

Update `useLiveChartDataset.spec.ts` to assert live chart requests include:

```ts
expect(activeBot.getChartCandles).toHaveBeenCalledWith(
  expect.objectContaining({ limit: 1000 }),
);
```

Set `settingsStore.chartDataCandleCount = 1000` in the test setup.

Run:

```powershell
pnpm vitest run tests/unit/useLiveChartDataset.spec.ts
```

Expected: FAIL because `useLiveChartDataset` does not send `limit`.

- [ ] **Step 2: Add setting**

In `frequi/src/stores/settings.ts`, add:

```ts
const chartDataCandleCount = ref(1000);
```

Return it from the store:

```ts
chartDataCandleCount,
```

- [ ] **Step 3: Expose setting in SettingsView**

In `frequi/src/views/SettingsView.vue`, add a second chart-count control labeled as backend chart data count. Keep the existing default visible candle count unchanged.

The two settings must bind to different refs:

```vue
v-model="settingsStore.chartDataCandleCount"
```

and:

```vue
v-model="settingsStore.chartDefaultCandleCount"
```

- [ ] **Step 4: Send backend data count**

In `frequi/src/composables/useLiveChartDataset.ts`, pass:

```ts
limit: settingsStore.chartDataCandleCount,
```

to `activeBot.getChartCandles`.

- [ ] **Step 5: Verify frontend**

Run:

```powershell
pnpm vitest run tests/unit/useLiveChartDataset.spec.ts tests/component/SingleCandleChartContainer.spec.ts
pnpm typecheck
```

Expected: PASS.

### Task P2.2: Render Source Groups from Metadata

**Files:**
- Modify: `frequi/src/components/charts/CandleChart.vue`
- Modify: `frequi/src/utils/charts/candleChartSeries.ts`
- Modify: `frequi/src/composables/useCandleChartTooltip.ts`
- Modify: `frequi/tests/unit/candleChartSeries.spec.ts`
- Modify: `frequi/tests/unit/candleChartTooltip.spec.ts`

- [ ] **Step 1: Add tests for grouped legend/tooltip source order**

Tests should assert this source order when data exists:

```text
Market Data
Strategy Output
Watch Indicators
```

Expected: FAIL until `CandleChart` passes response metadata into series and tooltip helpers.

- [ ] **Step 2: Pass `dataset.meta` through chart option builders**

Where `CandleChart.vue` builds series and tooltip options, pass:

```ts
props.dataset.meta
```

to metadata-aware helpers.

- [ ] **Step 3: Keep prefix fallback**

When `meta` is missing, existing behavior must remain unchanged:

```ts
const label = meta ? getSeriesSourceLabel(meta, column) : legacyLabel(column);
```

- [ ] **Step 4: Verify frontend**

Run:

```powershell
pnpm vitest run tests/unit/candleChartSeries.spec.ts tests/unit/candleChartTooltip.spec.ts
pnpm typecheck
```

Expected: PASS.

### Task P2.3: Add Backend Window Metadata

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/freqtrade/rpc/chart_data.py`
- Modify: `freqtrade/tests/rpc/test_chart_data.py`

- [ ] **Step 1: Add tests for explicit windows**

Add assertions:

```python
assert response["meta"]["window"]["requested_count"] == request.limit
assert response["meta"]["window"]["returned_count"] == len(response["data"])
assert response["meta"]["window"]["warmup_count"] == CHART_WARMUP_CANDLES
```

For live mode:

```python
assert response["meta"]["window"]["last_candle_complete"] == response["last_candle_complete"]
```

- [ ] **Step 2: Keep `limit` as data window**

Do not rename `limit` in P2. Treat it as backend data count and make metadata explicit.

- [ ] **Step 3: Verify backend**

Run:

```powershell
pytest tests/rpc/test_chart_data.py -q
```

Expected: PASS.

### Task P2.4: Commit P2

**Files:**
- All P2 modified files.

- [ ] **Step 1: Run focused backend/frontend verification**

Run:

```powershell
pytest tests/rpc/test_chart_data.py tests/rpc/test_chart_composition.py -q
pnpm vitest run tests/unit/useLiveChartDataset.spec.ts tests/unit/candleChartSeries.spec.ts tests/unit/candleChartTooltip.spec.ts tests/component/SingleCandleChartContainer.spec.ts
pnpm typecheck
```

Expected: PASS.

- [ ] **Step 2: Commit**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
git -C freqtrade add freqtrade/rpc/api_server/api_schemas.py freqtrade/rpc/chart_data.py tests/rpc/test_chart_data.py
git -C freqtrade commit -m "feat: expose chart window semantics"
git -C frequi add src/stores/settings.ts src/views/SettingsView.vue src/composables/useLiveChartDataset.ts src/components/charts/SingleCandleChartContainer.vue src/components/charts/CandleChart.vue src/utils/charts/candleChartSeries.ts src/composables/useCandleChartTooltip.ts tests/unit/useLiveChartDataset.spec.ts tests/component/SingleCandleChartContainer.spec.ts tests/unit/candleChartSeries.spec.ts tests/unit/candleChartTooltip.spec.ts
git -C frequi commit -m "feat: render chart layers from metadata"
```

---

## P3: Decision Snapshot Evidence

P3 touches persistence and bot decision explanation. Execute it only after P0-P2 are merged and verified.

### Task P3.1: Add Decision Snapshot Persistence

**Files:**
- Create: `freqtrade/freqtrade/persistence/decision_snapshot_model.py`
- Modify: `freqtrade/freqtrade/persistence/__init__.py`
- Modify: `freqtrade/freqtrade/persistence/migrations.py`
- Create: `freqtrade/tests/persistence/test_decision_snapshot_model.py`

- [ ] **Step 1: Add failing persistence tests**

Create tests that insert a decision snapshot with:

```python
pair = "BTC/USDT"
timeframe = "1m"
candle_open = datetime(2026, 7, 5, 9, 0, tzinfo=timezone.utc)
strategy = "SampleStrategy"
snapshot_type = "live"
decision = "enter_long"
values = {"rsi": 42.5, "qqe_mod_up_state": True}
```

Assertions:

```python
assert snapshot.pair == "BTC/USDT"
assert snapshot.values["rsi"] == 42.5
assert snapshot.decision == "enter_long"
```

Run:

```powershell
pytest tests/persistence/test_decision_snapshot_model.py -q
```

Expected: FAIL because model does not exist.

- [ ] **Step 2: Implement model**

Create `freqtrade/freqtrade/persistence/decision_snapshot_model.py` with a SQLAlchemy model containing:

```text
id
trade_id
order_id
pair
timeframe
candle_open
decision_time
strategy
strategy_version
config_hash
snapshot_type
decision
values
context
created_at
```

Use JSON-compatible columns following the project's existing persistence conventions.

- [ ] **Step 3: Add migration**

Update `migrations.py` to create `decision_snapshots` with indexes on:

```text
pair
timeframe
candle_open
trade_id
order_id
```

- [ ] **Step 4: Verify persistence**

Run:

```powershell
pytest tests/persistence/test_decision_snapshot_model.py -q
```

Expected: PASS.

### Task P3.2: Expose Decision Snapshots as Chart Layer

**Files:**
- Create: `freqtrade/freqtrade/rpc/decision_snapshots.py`
- Create: `freqtrade/tests/rpc/test_decision_snapshots.py`
- Modify: `freqtrade/freqtrade/rpc/chart_data.py`
- Modify: `freqtrade/tests/rpc/test_chart_data.py`

- [ ] **Step 1: Add failing RPC adapter tests**

Create tests that convert snapshots to a chart layer with:

```python
assert layer.source == "decision_snapshot"
assert layer.status == "ok"
assert layer.series[0].label == "RSI - Decision Snapshot"
```

Run:

```powershell
pytest tests/rpc/test_decision_snapshots.py -q
```

Expected: FAIL because adapter does not exist.

- [ ] **Step 2: Implement adapter**

Create `freqtrade/freqtrade/rpc/decision_snapshots.py` with functions:

```python
def load_decision_snapshots_for_window(
    pair: str,
    timeframe: str,
    start: datetime,
    stop: datetime,
) -> list[DecisionSnapshot]
```

```python
def build_decision_snapshot_layer(
    snapshots: list[DecisionSnapshot],
    chart_dataframe: DataFrame,
) -> ChartLayerMeta
```

The layer must align snapshots by candle open time.

- [ ] **Step 3: Add layer into chart response**

In `chart_data.py`, after strategy layer metadata, add decision snapshot metadata when snapshots exist.

The tooltip source order must be:

```text
decision_snapshot
strategy
watch
```

- [ ] **Step 4: Verify backend**

Run:

```powershell
pytest tests/rpc/test_decision_snapshots.py tests/rpc/test_chart_data.py -q
```

Expected: PASS.

### Task P3.3: Display Decision Evidence in Tooltip

**Files:**
- Modify: `frequi/src/types/candleTypes.ts`
- Modify: `frequi/src/composables/useCandleChartTooltip.ts`
- Modify: `frequi/tests/unit/candleChartTooltip.spec.ts`

- [ ] **Step 1: Add tooltip test**

Add a test where tooltip metadata includes `decision_snapshot`, `strategy`, and `watch` layers for the same candle.

Assert output order:

```text
Bot Decision
Strategy Output
Watch Indicators
```

Expected: FAIL until tooltip ordering is source-aware.

- [ ] **Step 2: Implement source priority**

In `useCandleChartTooltip.ts`, order groups by:

```ts
const SOURCE_PRIORITY = [
  'decision_snapshot',
  'strategy',
  'watch',
  'market',
  'execution',
  'recomputed',
];
```

Map `decision_snapshot` to label:

```text
Bot Decision
```

- [ ] **Step 3: Verify frontend**

Run:

```powershell
pnpm vitest run tests/unit/candleChartTooltip.spec.ts
pnpm typecheck
```

Expected: PASS.

### Task P3.4: Commit P3

**Files:**
- All P3 modified files.

- [ ] **Step 1: Run backend/frontend verification**

Run:

```powershell
pytest tests/persistence/test_decision_snapshot_model.py tests/rpc/test_decision_snapshots.py tests/rpc/test_chart_data.py -q
pnpm vitest run tests/unit/candleChartTooltip.spec.ts
pnpm typecheck
```

Expected: PASS.

- [ ] **Step 2: Commit**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
git -C freqtrade add freqtrade/persistence/decision_snapshot_model.py freqtrade/persistence/__init__.py freqtrade/persistence/migrations.py freqtrade/rpc/decision_snapshots.py freqtrade/rpc/chart_data.py tests/persistence/test_decision_snapshot_model.py tests/rpc/test_decision_snapshots.py tests/rpc/test_chart_data.py
git -C freqtrade commit -m "feat: add chart decision snapshots"
git -C frequi add src/types/candleTypes.ts src/composables/useCandleChartTooltip.ts tests/unit/candleChartTooltip.spec.ts
git -C frequi commit -m "feat: show decision evidence in chart tooltip"
```

---

## Full Verification

After each phase, run focused tests for that phase.

After P0-P2, run:

```powershell
pytest tests/rpc/test_chart_data.py tests/rpc/test_chart_indicators.py tests/rpc/test_chart_composition.py -q
pnpm vitest run tests/unit/chartSeriesMeta.spec.ts tests/unit/candleChartSeries.spec.ts tests/unit/candleChartTooltip.spec.ts tests/unit/useLiveChartDataset.spec.ts tests/component/SingleCandleChartContainer.spec.ts
pnpm typecheck
```

After P3, also run:

```powershell
pytest tests/persistence/test_decision_snapshot_model.py tests/rpc/test_decision_snapshots.py -q
```

For browser verification:

1. Rebuild and restart `freqtrade-cn:local` only after source changes are complete.
2. Open `http://127.0.0.1:8081/graph`.
3. Verify K line, watch indicators, strategy output, and tooltip source groups.
4. Verify missing strategy coverage is visible and not filled from watch data.
5. Verify `chartDefaultCandleCount` changes initial viewport only.
6. Verify `chartDataCandleCount` changes backend returned candle count.
7. Verify live candles show provisional status in metadata.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-05-chart-data-source-boundaries.md`.

Two execution options:

1. Subagent-Driven - dispatch a fresh subagent per phase or task, review between phases.
2. Inline Execution - execute tasks in this session using checkpoints.

Recommended order:

```text
P0 first, then browser verification.
P1 second, with no visible behavior changes expected.
P2 third, because it changes frontend behavior and settings.
P3 last, after separate approval because it adds persistence.
```
