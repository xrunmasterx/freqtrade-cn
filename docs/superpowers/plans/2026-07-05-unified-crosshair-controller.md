# Unified Crosshair Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace visible per-axis vertical pointer lines with one chart-level crosshair selection and one visible vertical guide.

**Architecture:** CandleChart owns a single crosshair selection `{ dataIndex, timestamp }`. A small chart utility computes nearest rows and graphic elements. The tooltip formatter normalizes incoming ECharts params to that same selection before rendering values.

**Tech Stack:** Vue 3, TypeScript, ECharts 6, vue-echarts, Vitest.

---

### Task 1: Lock Native Pointer Invariants With Tests

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\candleChartAxis.spec.ts`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\tests\component\CandleChartCrosshair.spec.ts`

- [ ] Update the time-axis pointer unit test so `createLinkedTimeAxisPointer()` is expected to be visually hidden.
- [ ] Add a CandleChart component assertion that every xAxis has `axisPointer.show === false`.
- [ ] Add a CandleChart component assertion that tooltip axisPointer has transparent/zero-width line style.
- [ ] Run `pnpm test:unit tests/unit/candleChartAxis.spec.ts tests/component/CandleChartCrosshair.spec.ts` and verify the new assertions fail before implementation.

### Task 2: Lock Tooltip Selection Invariant With Tests

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\candleChartTooltip.spec.ts`

- [ ] Add a test with an active selected row where ECharts params contain stale row values.
- [ ] Assert the rendered tooltip uses the selected row values, not the stale param values.
- [ ] Run `pnpm test:unit tests/unit/candleChartTooltip.spec.ts` and verify the new assertion fails before implementation.

### Task 3: Add Crosshair Utilities

**Files:**
- Create: `G:\AI_Trading\freqtrade-cn\frequi\src\utils\charts\candleChartCrosshair.ts`
- Create: `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\candleChartCrosshair.spec.ts`

- [ ] Add `findNearestCandleIndex(rows, dateColumn, timestamp)` with deterministic binary-search snapping.
- [ ] Add small helpers for ECharts grid rectangle extraction and graphic option construction.
- [ ] Run `pnpm test:unit tests/unit/candleChartCrosshair.spec.ts` and verify it passes after implementation.

### Task 4: Wire Unified Selection Into CandleChart

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\CandleChart.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\utils\charts\candleChartAxis.ts`

- [ ] Register `GraphicComponent`.
- [ ] Store rendered real rows, date column, and grid count for crosshair selection.
- [ ] Handle `zr:mousemove` by computing the nearest selected row, updating the single graphic crosshair, and dispatching `showTip` at the selected x pixel.
- [ ] Handle `zr:globalout` by removing only the crosshair graphic ids and dispatching `hideTip`.
- [ ] Change native time-axis pointer options to be visually hidden.

### Task 5: Normalize Tooltip Rows

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\composables\useCandleChartTooltip.ts`

- [ ] Accept an optional selected crosshair ref.
- [ ] When present, replace each tooltip param's `dataIndex`, `value`, `axisValue`, and `axisValueLabel` with the selected row before rendering.
- [ ] Keep the existing grouping and value formatting behavior.

### Task 6: Verify

**Commands:**
- `pnpm test:unit tests/unit/candleChartAxis.spec.ts tests/unit/candleChartCrosshair.spec.ts tests/unit/candleChartTooltip.spec.ts tests/component/CandleChartCrosshair.spec.ts`
- `pnpm typecheck`
- `pnpm lint-ci src/components/charts/CandleChart.vue src/composables/useCandleChartTooltip.ts src/utils/charts/candleChartAxis.ts src/utils/charts/candleChartCrosshair.ts tests/unit/candleChartAxis.spec.ts tests/unit/candleChartCrosshair.spec.ts tests/unit/candleChartTooltip.spec.ts tests/component/CandleChartCrosshair.spec.ts`

Expected result: all commands exit 0. Then verify in the browser that hover shows one vertical guide across the candle and indicator grids.
