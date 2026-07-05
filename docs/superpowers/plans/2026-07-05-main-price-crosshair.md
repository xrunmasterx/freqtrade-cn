# Main Price Crosshair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a horizontal dashed price pointer and price-axis label to the main candle chart without changing the existing linked vertical time pointer.

**Architecture:** Keep ECharts native axisPointer as the only pointer rendering mechanism. Add one focused helper for the main price y-axis pointer, wire it to `yAxis[0]`, and explicitly disable y-axis pointers on volume and indicator subplots.

**Tech Stack:** Vue 3, TypeScript, ECharts 6, vue-echarts, Vitest, Vue Test Utils, Pinia.

---

## File Structure

- Modify: `frequi/src/utils/charts/candleChartAxis.ts`
  - Owns reusable axis option helpers for the candle chart.
  - Add `createMainPriceAxisPointer(labelFormatter)`.
- Modify: `frequi/tests/unit/candleChartAxis.spec.ts`
  - Owns unit tests for chart axis helper behavior.
  - Add tests for the main price pointer option.
- Create: `frequi/tests/component/CandleChartCrosshair.spec.ts`
  - Mounts `CandleChart.vue` with a stubbed ECharts component and inspects the emitted option.
  - Verifies main y-axis pointer is enabled and non-main y-axis pointers are disabled.
- Modify: `frequi/src/components/charts/CandleChart.vue`
  - Imports the new helper.
  - Adds a small local price-label formatter.
  - Applies the main price pointer to `yAxis[0]`.
  - Applies `axisPointer: { show: false }` to `yAxis[1]` and dynamically-created subplot y axes.

---

### Task 1: Axis Helper Failing Tests

**Files:**
- Modify: `frequi/tests/unit/candleChartAxis.spec.ts`

- [ ] **Step 1: Add the failing helper tests**

Update the import block at the top of `frequi/tests/unit/candleChartAxis.spec.ts` to include the new helper:

```ts
import {
  createLinkedTimeAxisPointer,
  createMainPriceAxisPointer,
  getTimeAxisDomain,
  withLinkedTimeAxisMapping,
} from '@/utils/charts/candleChartAxis';
```

Add this test after `uses one visible linked time-axis pointer style`:

```ts
  it('builds a visible main price axis pointer without driving tooltip lookup', () => {
    const formatter = (params: { value: unknown }) => `price:${params.value}`;
    const axisPointer = createMainPriceAxisPointer(formatter);

    expect(axisPointer).toEqual({
      show: true,
      type: 'line',
      snap: false,
      triggerTooltip: false,
      lineStyle: {
        color: '#cccccc',
        opacity: 1,
        type: 'dashed',
        width: 1,
      },
      label: {
        show: true,
        formatter,
        backgroundColor: '#111827',
        borderColor: '#cccccc',
        borderWidth: 1,
        color: '#ffffff',
        padding: [3, 5],
        margin: 4,
      },
    });
  });
```

- [ ] **Step 2: Run the targeted unit test and verify it fails for the expected reason**

Run:

```bash
cd G:/AI_Trading/freqtrade-cn/frequi
pnpm test:unit tests/unit/candleChartAxis.spec.ts -t "builds a visible main price axis pointer"
```

Expected: FAIL because `createMainPriceAxisPointer` is not exported from `@/utils/charts/candleChartAxis`.

---

### Task 2: Axis Helper Implementation

**Files:**
- Modify: `frequi/src/utils/charts/candleChartAxis.ts`
- Test: `frequi/tests/unit/candleChartAxis.spec.ts`

- [ ] **Step 1: Implement the minimal helper**

Add this type and function immediately after `createLinkedTimeAxisPointer` in `frequi/src/utils/charts/candleChartAxis.ts`:

```ts
export type AxisPointerLabelFormatter = (params: { value: unknown }) => string;

export function createMainPriceAxisPointer(labelFormatter: AxisPointerLabelFormatter) {
  return {
    show: true,
    type: 'line',
    snap: false,
    triggerTooltip: false,
    lineStyle: createLinkedTimeAxisPointer().lineStyle,
    label: {
      show: true,
      formatter: labelFormatter,
      backgroundColor: '#111827',
      borderColor: '#cccccc',
      borderWidth: 1,
      color: '#ffffff',
      padding: [3, 5],
      margin: 4,
    },
  } as const;
}
```

- [ ] **Step 2: Run the helper test and verify it passes**

Run:

```bash
cd G:/AI_Trading/freqtrade-cn/frequi
pnpm test:unit tests/unit/candleChartAxis.spec.ts -t "builds a visible main price axis pointer"
```

Expected: PASS.

- [ ] **Step 3: Commit the helper change**

Run:

```bash
cd G:/AI_Trading/freqtrade-cn
git add -- frequi/src/utils/charts/candleChartAxis.ts frequi/tests/unit/candleChartAxis.spec.ts
git commit -m "feat: add main price axis pointer helper"
```

Expected: commit only these two files. If unrelated files are already modified, leave them unstaged.

---

### Task 3: CandleChart Option Failing Test

**Files:**
- Create: `frequi/tests/component/CandleChartCrosshair.spec.ts`

- [ ] **Step 1: Add the component-level option test**

Create `frequi/tests/component/CandleChartCrosshair.spec.ts` with this full content:

```ts
import { mount } from '@vue/test-utils';
import type { EChartsOption } from 'echarts';
import { createPinia, setActivePinia } from 'pinia';
import { defineComponent, h, nextTick } from 'vue';
import { beforeEach, describe, expect, it } from 'vitest';

import CandleChart from '@/components/charts/CandleChart.vue';
import { ChartType, type PairHistory, type PlotConfig } from '@/types';

const setOptionCalls: EChartsOption[] = [];

const EChartsStub = defineComponent({
  name: 'ECharts',
  setup(_, { expose }) {
    expose({
      setOption(option: EChartsOption) {
        setOptionCalls.push(option);
      },
      dispatchAction() {},
    });

    return () => h('div', { class: 'echarts-stub' });
  },
});

function buildDataset(): PairHistory {
  const start = Date.UTC(2026, 6, 5, 12, 0, 0);

  return {
    strategy: 'TestStrategy',
    pair: 'BTC/USDT',
    timeframe: '1m',
    timeframe_ms: 60_000,
    columns: ['__date_ts', 'open', 'high', 'low', 'close', 'volume', 'rsi'],
    all_columns: ['__date_ts', 'open', 'high', 'low', 'close', 'volume', 'rsi'],
    annotations: [],
    data: [
      [start, 100, 104, 99, 103, 10, 45],
      [start + 60_000, 103, 106, 101, 105, 11, 55],
      [start + 120_000, 105, 107, 102, 104, 12, 52],
    ],
    length: 3,
    buy_signals: 0,
    sell_signals: 0,
    enter_long_signals: 0,
    exit_long_signals: 0,
    enter_short_signals: 0,
    exit_short_signals: 0,
    last_analyzed: start + 120_000,
    data_start_ts: start,
    data_start: '2026-07-05 12:00:00+00:00',
    data_stop: '2026-07-05 12:02:00+00:00',
    data_stop_ts: start + 120_000,
  };
}

function buildPlotConfig(): PlotConfig {
  return {
    main_plot: {},
    subplots: {
      RSI: {
        rsi: {
          type: ChartType.line,
          color: '#a855f7',
        },
      },
    },
  };
}

describe('CandleChart crosshair axis options', () => {
  beforeEach(() => {
    setOptionCalls.length = 0;
    setActivePinia(createPinia());
  });

  it('enables the price pointer only on the main candle y-axis', async () => {
    const pinia = createPinia();
    setActivePinia(pinia);

    mount(CandleChart, {
      props: {
        trades: [],
        dataset: buildDataset(),
        heikinAshi: false,
        showMarkArea: false,
        useUTC: false,
        plotConfig: buildPlotConfig(),
        theme: 'dark',
        colorUp: '#14b8a6',
        colorDown: '#ef4444',
        labelSide: 'right',
        startCandleCount: 40,
      },
      global: {
        plugins: [pinia],
        stubs: {
          ECharts: EChartsStub,
        },
      },
    });

    await nextTick();

    const chartOption = setOptionCalls.find(
      (option) => Array.isArray(option.yAxis) && option.yAxis.length >= 3,
    );
    expect(chartOption).toBeDefined();

    const yAxis = chartOption!.yAxis as Array<Record<string, unknown>>;
    expect(yAxis[0].axisPointer).toMatchObject({
      show: true,
      type: 'line',
      snap: false,
      triggerTooltip: false,
      label: {
        show: true,
      },
    });
    expect(yAxis[1].axisPointer).toEqual({ show: false });
    expect(yAxis[2].axisPointer).toEqual({ show: false });
  });
});
```

- [ ] **Step 2: Run the component test and verify it fails for the expected reason**

Run:

```bash
cd G:/AI_Trading/freqtrade-cn/frequi
pnpm test:unit tests/component/CandleChartCrosshair.spec.ts
```

Expected: FAIL because `yAxis[0].axisPointer` is undefined or does not match `{ show: true, type: 'line', snap: false, triggerTooltip: false }`.

---

### Task 4: CandleChart Integration

**Files:**
- Modify: `frequi/src/components/charts/CandleChart.vue`
- Test: `frequi/tests/component/CandleChartCrosshair.spec.ts`

- [ ] **Step 1: Import the price pointer helper**

Update the `candleChartAxis` import in `frequi/src/components/charts/CandleChart.vue`:

```ts
import {
  createLinkedTimeAxisPointer,
  createMainPriceAxisPointer,
  getTimeAxisDomain,
  withLinkedTimeAxisMapping,
} from '@/utils/charts/candleChartAxis';
```

- [ ] **Step 2: Add the local price label formatter**

Add this function near the existing small helper functions, before `addLegend`:

```ts
function formatPriceAxisPointerLabel(params: { value: unknown }) {
  const value = Number(params.value);

  return Number.isFinite(value) ? formatDecimal(value, 'en-EN') : '';
}
```

- [ ] **Step 3: Apply the main price pointer and disable non-main value pointers**

In the first `yAxis` object, add `axisPointer` after `position: props.labelSide`:

```ts
        position: props.labelSide,
        axisPointer: createMainPriceAxisPointer(formatPriceAxisPointerLabel),
```

In the volume `yAxis` object, add `axisPointer` after `position: props.labelSide`:

```ts
        position: props.labelSide,
        axisPointer: { show: false },
```

In the dynamically-created subplot y-axis object, add `axisPointer` after `position: props.labelSide`:

```ts
          position: props.labelSide,
          axisPointer: { show: false },
```

- [ ] **Step 4: Run the component test and verify it passes**

Run:

```bash
cd G:/AI_Trading/freqtrade-cn/frequi
pnpm test:unit tests/component/CandleChartCrosshair.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Run the full targeted frontend verification**

Run:

```bash
cd G:/AI_Trading/freqtrade-cn/frequi
pnpm test:unit tests/unit/candleChartAxis.spec.ts tests/component/CandleChartCrosshair.spec.ts
pnpm typecheck
pnpm exec eslint src/components/charts/CandleChart.vue src/utils/charts/candleChartAxis.ts tests/unit/candleChartAxis.spec.ts tests/component/CandleChartCrosshair.spec.ts --quiet
```

Expected: all commands pass.

- [ ] **Step 6: Commit the integration change**

Run:

```bash
cd G:/AI_Trading/freqtrade-cn
git add -- frequi/src/components/charts/CandleChart.vue frequi/tests/component/CandleChartCrosshair.spec.ts
git commit -m "feat: show main chart price crosshair"
```

Expected: commit only these two files. If unrelated files are already modified, leave them unstaged.

---

### Task 5: Browser Verification

**Files:**
- No source files.

- [ ] **Step 1: Start or reuse the local frontend/backend app**

If the local app at `http://127.0.0.1:8081/graph` is already serving the current build, use it. If it is not serving the new frontend bundle, rebuild and restart the local container or dev server using the same workflow already used for this repository.

- [ ] **Step 2: Verify the Graph page behavior**

Open:

```text
http://127.0.0.1:8081/graph
```

Manual browser checks:

- move the mouse over the main candle chart;
- confirm the vertical dashed time line remains visible;
- confirm a horizontal dashed price line appears only in the main candle grid;
- confirm the price axis shows a label at the horizontal line;
- move the mouse over volume, RSI, and MACD subplots;
- confirm those subplots do not show their own horizontal line;
- confirm the vertical time line still aligns across all visible grids.

- [ ] **Step 3: Verify the Trade page behavior**

Open:

```text
http://127.0.0.1:8081/trade
```

Repeat the same checks from the Graph page.

- [ ] **Step 4: Record the final verification result**

In the final response, report:

- targeted unit tests passed;
- typecheck passed;
- eslint passed;
- browser verification page or pages checked;
- whether a rebuild/restart was required.
