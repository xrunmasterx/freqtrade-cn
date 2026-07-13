# Research Chart Auto Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add default-on automatic refresh to the A-share research chart using the same timeframe cadence as contract and spot charts.

**Architecture:** Keep the behavior frontend-only. Add a tiny timeframe alias in the shared chart refresh utility, then add a focused `useResearchChartAutoRefresh` composable that owns timers, visibility, and loading guards. `ResearchView` stays responsible for selection state and request payload construction.

**Tech Stack:** Vue 3 Composition API, Pinia, Vitest, Vue Test Utils, happy-dom, existing Nuxt UI auto-import configuration.

## Global Constraints

- Default auto-refresh is enabled.
- Do not add a user-facing auto-refresh toggle in this phase.
- Do not change `/research/chart_candles` request or response contracts.
- Do not change backend data sources, collectors, or OHLCV storage.
- Do not implement A-share websocket, SSE, collector scheduling, or market-session status APIs.
- Do not auto-run research backtests.
- Do not modify global bot auto-refresh behavior.
- Reuse `getTradeChartRefreshIntervalMs()` cadence for research chart refresh.
- Normalize research `60m` to the shared `1h` refresh cadence.
- Stop polling when `document.visibilityState === 'hidden'`.
- Never overlap chart requests when `chartRequestState.loading` is true.

---

## Assumptions

- The active frontend package is `frequi`.
- Existing auto-import config covers `src/composables` and `src/utils/**`, but tests should import new functions explicitly.
- `ResearchView.vue` may display the refresh status as compact English text from the composable: `Auto 10s`, `Auto 180s`, `Paused`, `Refreshing`.
- The chart request context can be represented by a single computed `refreshKey` string. This keeps timer reset logic in the composable without moving request payload construction out of `ResearchView`.

## File Structure

- `frequi/src/utils/tradeChartRefresh.ts`
  - Owns shared chart refresh cadence and in-flight dedupe helper.
  - Add one alias helper for `60m -> 1h`.
- `frequi/tests/unit/tradeChartRefresh.spec.ts`
  - Verifies cadence mapping and duplicate refresh guard.
  - Add coverage for `60m`.
- `frequi/src/composables/useResearchChartAutoRefresh.ts`
  - Owns research chart timer lifecycle, page visibility handling, loading guard, and compact status label.
  - Does not build chart request payloads.
  - Does not call backtest functions.
- `frequi/tests/unit/useResearchChartAutoRefresh.spec.ts`
  - Verifies timer cadence, visibility pause/resume, loading skip, unmount cleanup, and `refreshKey` reset.
- `frequi/src/views/ResearchView.vue`
  - Wires the new composable to current chart selections and `refreshChart()`.
  - Renders a compact status label near the manual refresh button.
- `frequi/tests/component/ResearchView.spec.ts`
  - Verifies default wiring, status labels, manual refresh, automatic refresh, and no automatic backtest.

---

### Task 1: Shared Refresh Cadence Alias

**Files:**
- Modify: `frequi/src/utils/tradeChartRefresh.ts`
- Modify: `frequi/tests/unit/tradeChartRefresh.spec.ts`

**Interfaces:**
- Consumes: existing `getTradeChartRefreshIntervalMs(timeframe: string): number`
- Produces: `normalizeTradeChartRefreshTimeframe(timeframe: string): string`
- Produces: `getTradeChartRefreshIntervalMs('60m') === 180_000`

- [ ] **Step 1: Write the failing cadence test**

Edit `frequi/tests/unit/tradeChartRefresh.spec.ts` so the import includes the new helper:

```ts
import {
  getTradeChartRefreshIntervalMs,
  normalizeTradeChartRefreshTimeframe,
  runDedupedChartRefresh,
} from '@/utils/tradeChartRefresh';
```

Add `['60m', 180_000]` to the existing `it.each` table:

```ts
    ['1h', 180_000],
    ['60m', 180_000],
    ['2h', 300_000],
```

Add this test after the mapping test:

```ts
  it('normalizes minute-style one hour timeframe to the shared 1h cadence key', () => {
    expect(normalizeTradeChartRefreshTimeframe('60m')).toBe('1h');
    expect(normalizeTradeChartRefreshTimeframe('1m')).toBe('1m');
    expect(normalizeTradeChartRefreshTimeframe('unknown')).toBe('unknown');
  });
```

- [ ] **Step 2: Run the focused test and verify failure**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm vitest run tests/unit/tradeChartRefresh.spec.ts
```

Expected: FAIL because `normalizeTradeChartRefreshTimeframe` is not exported, or because `60m` maps to `60_000`.

- [ ] **Step 3: Implement the minimal helper**

Edit `frequi/src/utils/tradeChartRefresh.ts`:

```ts
const TRADE_CHART_REFRESH_INTERVAL_MS: Record<string, number> = {
  '1m': 10_000,
  '3m': 30_000,
  '5m': 60_000,
  '15m': 60_000,
  '30m': 60_000,
  '1h': 180_000,
  '2h': 300_000,
  '4h': 300_000,
  '6h': 600_000,
  '8h': 600_000,
  '12h': 600_000,
  '1d': 900_000,
  '3d': 900_000,
  '1w': 900_000,
  '2w': 900_000,
  '1M': 900_000,
  '1y': 900_000,
};

const TRADE_CHART_REFRESH_TIMEFRAME_ALIASES: Record<string, string> = {
  '60m': '1h',
};

const DEFAULT_TRADE_CHART_REFRESH_INTERVAL_MS = 60_000;

export function normalizeTradeChartRefreshTimeframe(timeframe: string): string {
  return TRADE_CHART_REFRESH_TIMEFRAME_ALIASES[timeframe] ?? timeframe;
}

export function getTradeChartRefreshIntervalMs(timeframe: string): number {
  return (
    TRADE_CHART_REFRESH_INTERVAL_MS[normalizeTradeChartRefreshTimeframe(timeframe)] ??
    DEFAULT_TRADE_CHART_REFRESH_INTERVAL_MS
  );
}
```

Keep the existing `runDedupedChartRefresh()` implementation unchanged.

- [ ] **Step 4: Run the focused test and verify pass**

Run:

```powershell
pnpm vitest run tests/unit/tradeChartRefresh.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add frequi/src/utils/tradeChartRefresh.ts frequi/tests/unit/tradeChartRefresh.spec.ts
git commit -m "feat: normalize research chart refresh timeframe"
```

Expected: commit succeeds with only the two listed files staged.

---

### Task 2: Research Chart Auto Refresh Composable

**Files:**
- Create: `frequi/src/composables/useResearchChartAutoRefresh.ts`
- Create: `frequi/tests/unit/useResearchChartAutoRefresh.spec.ts`

**Interfaces:**
- Consumes: `getTradeChartRefreshIntervalMs(timeframe: string): number`
- Consumes: `Ref<T> | ComputedRef<T>` values from `ResearchView`
- Produces:

```ts
export type ResearchChartAutoRefreshStatus = 'active' | 'paused' | 'refreshing';

export interface UseResearchChartAutoRefreshOptions {
  active: Ref<boolean> | ComputedRef<boolean>;
  timeframe: Ref<string> | ComputedRef<string>;
  canRefresh: Ref<boolean> | ComputedRef<boolean>;
  isLoading: Ref<boolean> | ComputedRef<boolean>;
  refreshChart: () => Promise<void> | void;
  refreshKey?: Ref<string> | ComputedRef<string>;
}

export interface UseResearchChartAutoRefreshResult {
  autoRefreshEnabled: ComputedRef<boolean>;
  refreshIntervalMs: ComputedRef<number>;
  refreshStatus: ComputedRef<ResearchChartAutoRefreshStatus>;
  refreshLabel: ComputedRef<string>;
}
```

- [ ] **Step 1: Write the failing composable tests**

Create `frequi/tests/unit/useResearchChartAutoRefresh.spec.ts`:

```ts
import { mount } from '@vue/test-utils';
import type { VueWrapper } from '@vue/test-utils';
import { computed, defineComponent, nextTick, ref } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useResearchChartAutoRefresh } from '@/composables/useResearchChartAutoRefresh';

type VisibilityValue = DocumentVisibilityState;

function setDocumentVisibility(value: VisibilityValue) {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => value,
  });
}

function dispatchVisibility(value: VisibilityValue) {
  setDocumentVisibility(value);
  document.dispatchEvent(new Event('visibilitychange'));
}

function mountAutoRefresh(options: {
  active?: ReturnType<typeof ref<boolean>>;
  timeframe?: ReturnType<typeof ref<string>>;
  canRefresh?: ReturnType<typeof ref<boolean>>;
  isLoading?: ReturnType<typeof ref<boolean>>;
  refreshKey?: ReturnType<typeof ref<string>>;
  refreshChart?: ReturnType<typeof vi.fn>;
} = {}) {
  const active = options.active ?? ref(true);
  const timeframe = options.timeframe ?? ref('1m');
  const canRefresh = options.canRefresh ?? ref(true);
  const isLoading = options.isLoading ?? ref(false);
  const refreshKey = options.refreshKey ?? ref('initial');
  const refreshChart = options.refreshChart ?? vi.fn(async () => undefined);
  let autoRefresh: ReturnType<typeof useResearchChartAutoRefresh> | undefined;

  const wrapper = mount(
    defineComponent({
      setup() {
        autoRefresh = useResearchChartAutoRefresh({
          active: computed(() => active.value),
          timeframe: computed(() => timeframe.value),
          canRefresh: computed(() => canRefresh.value),
          isLoading: computed(() => isLoading.value),
          refreshKey: computed(() => refreshKey.value),
          refreshChart,
        });
        return {};
      },
      template: '<div />',
    }),
  );

  if (!autoRefresh) {
    throw new Error('Research auto-refresh composable did not initialize');
  }

  return {
    active,
    timeframe,
    canRefresh,
    isLoading,
    refreshKey,
    refreshChart,
    autoRefresh,
    wrapper,
  };
}

describe('useResearchChartAutoRefresh', () => {
  const wrappers: VueWrapper[] = [];

  beforeEach(() => {
    vi.useFakeTimers();
    setDocumentVisibility('visible');
  });

  afterEach(() => {
    for (const wrapper of wrappers.splice(0)) {
      wrapper.unmount();
    }
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    setDocumentVisibility('visible');
  });

  function track(wrapper: VueWrapper) {
    wrappers.push(wrapper);
  }

  it('exposes active status and interval label from the selected timeframe', () => {
    const { autoRefresh, wrapper } = mountAutoRefresh({ timeframe: ref('1m') });
    track(wrapper);

    expect(autoRefresh.autoRefreshEnabled.value).toBe(true);
    expect(autoRefresh.refreshIntervalMs.value).toBe(10_000);
    expect(autoRefresh.refreshStatus.value).toBe('active');
    expect(autoRefresh.refreshLabel.value).toBe('Auto 10s');
  });

  it('uses the 1h cadence for research 60m timeframe', () => {
    const { autoRefresh, wrapper } = mountAutoRefresh({ timeframe: ref('60m') });
    track(wrapper);

    expect(autoRefresh.refreshIntervalMs.value).toBe(180_000);
    expect(autoRefresh.refreshLabel.value).toBe('Auto 180s');
  });

  it('calls refreshChart after the selected timeframe interval', async () => {
    const { refreshChart, wrapper } = mountAutoRefresh({ timeframe: ref('1m') });
    track(wrapper);
    await nextTick();

    vi.advanceTimersByTime(9_999);
    expect(refreshChart).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    await Promise.resolve();

    expect(refreshChart).toHaveBeenCalledTimes(1);
  });

  it('skips a scheduled tick while a chart request is loading', async () => {
    const isLoading = ref(true);
    const { refreshChart, autoRefresh, wrapper } = mountAutoRefresh({ isLoading });
    track(wrapper);
    await nextTick();

    expect(autoRefresh.refreshStatus.value).toBe('refreshing');

    vi.advanceTimersByTime(10_000);
    await Promise.resolve();

    expect(refreshChart).not.toHaveBeenCalled();
  });

  it('does not schedule while canRefresh is false', async () => {
    const canRefresh = ref(false);
    const { refreshChart, autoRefresh, wrapper } = mountAutoRefresh({ canRefresh });
    track(wrapper);
    await nextTick();

    expect(autoRefresh.autoRefreshEnabled.value).toBe(false);
    expect(autoRefresh.refreshStatus.value).toBe('paused');

    vi.advanceTimersByTime(10_000);

    expect(refreshChart).not.toHaveBeenCalled();
  });

  it('stops while hidden and refreshes immediately when visible again', async () => {
    const { refreshChart, autoRefresh, wrapper } = mountAutoRefresh();
    track(wrapper);
    await nextTick();

    dispatchVisibility('hidden');
    expect(autoRefresh.refreshStatus.value).toBe('paused');

    vi.advanceTimersByTime(10_000);
    expect(refreshChart).not.toHaveBeenCalled();

    dispatchVisibility('visible');
    await Promise.resolve();

    expect(refreshChart).toHaveBeenCalledTimes(1);
    expect(autoRefresh.refreshStatus.value).toBe('active');
  });

  it('resets the next scheduled tick when the refresh key changes', async () => {
    const refreshKey = ref('600519.SH|1m|raw|5|20');
    const { refreshChart, wrapper } = mountAutoRefresh({ refreshKey });
    track(wrapper);
    await nextTick();

    vi.advanceTimersByTime(9_000);
    refreshKey.value = '600519.SH|1m|qfq|5|20';
    await nextTick();
    vi.advanceTimersByTime(9_000);

    expect(refreshChart).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1_000);
    await Promise.resolve();

    expect(refreshChart).toHaveBeenCalledTimes(1);
  });

  it('clears the scheduled timer on unmount', async () => {
    const { refreshChart, wrapper } = mountAutoRefresh();
    await nextTick();

    wrapper.unmount();
    vi.advanceTimersByTime(10_000);

    expect(refreshChart).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the focused test and verify failure**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm vitest run tests/unit/useResearchChartAutoRefresh.spec.ts
```

Expected: FAIL because `@/composables/useResearchChartAutoRefresh` does not exist.

- [ ] **Step 3: Implement the composable**

Create `frequi/src/composables/useResearchChartAutoRefresh.ts`:

```ts
import type { ComputedRef, Ref } from 'vue';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';

import { getTradeChartRefreshIntervalMs } from '@/utils/tradeChartRefresh';

export type ResearchChartAutoRefreshStatus = 'active' | 'paused' | 'refreshing';

export interface UseResearchChartAutoRefreshOptions {
  active: Ref<boolean> | ComputedRef<boolean>;
  timeframe: Ref<string> | ComputedRef<string>;
  canRefresh: Ref<boolean> | ComputedRef<boolean>;
  isLoading: Ref<boolean> | ComputedRef<boolean>;
  refreshChart: () => Promise<void> | void;
  refreshKey?: Ref<string> | ComputedRef<string>;
}

export interface UseResearchChartAutoRefreshResult {
  autoRefreshEnabled: ComputedRef<boolean>;
  refreshIntervalMs: ComputedRef<number>;
  refreshStatus: ComputedRef<ResearchChartAutoRefreshStatus>;
  refreshLabel: ComputedRef<string>;
}

function formatRefreshIntervalMs(intervalMs: number): string {
  return `${Math.round(intervalMs / 1000)}s`;
}

export function useResearchChartAutoRefresh(
  options: UseResearchChartAutoRefreshOptions,
): UseResearchChartAutoRefreshResult {
  const isVisible = ref(document.visibilityState !== 'hidden');
  let refreshTimer: number | undefined;

  const autoRefreshEnabled = computed(() => options.active.value && options.canRefresh.value);
  const refreshIntervalMs = computed(() => getTradeChartRefreshIntervalMs(options.timeframe.value));
  const refreshKey = computed(() => options.refreshKey?.value ?? '');
  const refreshStatus = computed<ResearchChartAutoRefreshStatus>(() => {
    if (!autoRefreshEnabled.value || !isVisible.value) {
      return 'paused';
    }

    if (options.isLoading.value) {
      return 'refreshing';
    }

    return 'active';
  });
  const refreshLabel = computed(() => {
    if (refreshStatus.value === 'paused') {
      return 'Paused';
    }

    if (refreshStatus.value === 'refreshing') {
      return 'Refreshing';
    }

    return `Auto ${formatRefreshIntervalMs(refreshIntervalMs.value)}`;
  });

  function clearRefreshTimer() {
    if (refreshTimer !== undefined) {
      window.clearTimeout(refreshTimer);
      refreshTimer = undefined;
    }
  }

  async function runRefreshNow() {
    if (!autoRefreshEnabled.value || !isVisible.value || options.isLoading.value) {
      return;
    }

    try {
      await options.refreshChart();
    } catch {
      // Research store owns user-visible chart request errors.
    }
  }

  function scheduleRefresh() {
    clearRefreshTimer();

    if (!autoRefreshEnabled.value || !isVisible.value) {
      return;
    }

    refreshTimer = window.setTimeout(() => {
      void runRefreshNow().finally(scheduleRefresh);
    }, refreshIntervalMs.value);
  }

  function handleVisibilityChange() {
    isVisible.value = document.visibilityState !== 'hidden';

    if (!isVisible.value) {
      clearRefreshTimer();
      return;
    }

    void runRefreshNow().finally(scheduleRefresh);
  }

  watch(
    () => [options.active.value, options.canRefresh.value, options.timeframe.value, refreshKey.value],
    scheduleRefresh,
  );

  onMounted(() => {
    document.addEventListener('visibilitychange', handleVisibilityChange);
    scheduleRefresh();
  });

  onUnmounted(() => {
    clearRefreshTimer();
    document.removeEventListener('visibilitychange', handleVisibilityChange);
  });

  return {
    autoRefreshEnabled,
    refreshIntervalMs,
    refreshStatus,
    refreshLabel,
  };
}
```

- [ ] **Step 4: Run the focused test and verify pass**

Run:

```powershell
pnpm vitest run tests/unit/useResearchChartAutoRefresh.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add frequi/src/composables/useResearchChartAutoRefresh.ts frequi/tests/unit/useResearchChartAutoRefresh.spec.ts
git commit -m "feat: add research chart auto refresh composable"
```

Expected: commit succeeds with only the two listed files staged.

---

### Task 3: ResearchView Integration

**Files:**
- Modify: `frequi/src/views/ResearchView.vue`
- Modify: `frequi/tests/component/ResearchView.spec.ts`

**Interfaces:**
- Consumes: `useResearchChartAutoRefresh(options)`
- Consumes: `refreshChart(): Promise<void>`
- Produces: `data-test="research-auto-refresh-status"` status label in `ResearchView`
- Produces: automatic chart refresh calls through `researchStore.loadChart(...)`

- [ ] **Step 1: Write failing ResearchView component tests**

Edit `frequi/tests/component/ResearchView.spec.ts`.

Update the Vitest import:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
```

Add a wrapper registry near the mount helper:

```ts
const mountedWrappers: ReturnType<typeof mountResearchView>[] = [];
```

Update `mountResearchView()` so it registers wrappers:

```ts
function mountResearchView(pinia: ReturnType<typeof createPinia>) {
  const wrapper = mount(ResearchView, {
    global: {
      plugins: [pinia],
      stubs: {
        Button: {
          props: ['disabled', 'icon'],
          emits: ['click'],
          template:
            '<button :disabled="disabled" type="button" @click="$emit(\'click\', $event)"><slot /></button>',
        },
        CandleChart: {
          name: 'CandleChart',
          props: ['dataset', 'trades', 'plotConfig'],
          template: '<div data-test="candle-chart" />',
        },
        Input: {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template:
            '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
        },
        Select: {
          props: ['modelValue', 'items'],
          emits: ['update:modelValue'],
          template:
            '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option v-for="item in items" :key="item.value" :value="item.value">{{ item.label }}</option></select>',
        },
        UButton: {
          props: ['disabled', 'icon', 'loading'],
          emits: ['click'],
          template:
            '<button :disabled="disabled" type="button" @click="$emit(\'click\', $event)"><slot /></button>',
        },
        UInput: {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template:
            '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
        },
        USelect: {
          props: ['modelValue', 'items'],
          emits: ['update:modelValue'],
          template:
            '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option v-for="item in items" :key="item.value" :value="item.value">{{ item.label }}</option></select>',
        },
      },
    },
  });
  mountedWrappers.push(wrapper);
  return wrapper;
}
```

Update `beforeEach` and add `afterEach`:

```ts
describe('ResearchView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    for (const wrapper of mountedWrappers.splice(0)) {
      wrapper.unmount();
    }
    vi.clearAllTimers();
    vi.useRealTimers();
  });
```

In the first render test, add:

```ts
    expect(wrapper.find('[data-test="research-auto-refresh-status"]').exists()).toBe(true);
```

Add this test near the existing chart refresh tests:

```ts
  it('auto-refreshes the chart by the selected research timeframe', async () => {
    vi.useFakeTimers();
    const { pinia, store } = installResearchStore();
    store.loadInstruments = vi.fn(async () => {
      store.instruments = [
        instrument('688017.SH', '688017', 'Green Harmonics', ['1m', '60m']),
      ];
      store.selectedInstrument = '688017.SH';
      return store.instruments;
    });

    const wrapper = mountResearchView(pinia);
    await flushPromises();

    expect(wrapper.find<HTMLSelectElement>('[data-test="timeframe-select"]').element.value).toBe(
      '1m',
    );
    expect(wrapper.find('[data-test="research-auto-refresh-status"]').text()).toBe('Auto 10s');

    store.loadChart.mockClear();
    store.runBacktest.mockClear();

    vi.advanceTimersByTime(9_999);
    await flushPromises();
    expect(store.loadChart).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    await flushPromises();

    expect(store.loadChart).toHaveBeenCalledWith({
      bot_id: 'a-share-research',
      instrument: '688017.SH',
      timeframe: '1m',
      limit: 1000,
      timerange: null,
      adjustment: 'raw',
      watch_indicators: { ma: [5, 20] },
      side_layers: null,
    });
    expect(store.runBacktest).not.toHaveBeenCalled();
  });
```

Add this test after it:

```ts
  it('shows the 1h cadence label when research timeframe is 60m', async () => {
    const { pinia, store } = installResearchStore();
    store.loadInstruments = vi.fn(async () => {
      store.instruments = [
        instrument('688017.SH', '688017', 'Green Harmonics', ['1m', '60m']),
      ];
      store.selectedInstrument = '688017.SH';
      return store.instruments;
    });
    const wrapper = mountResearchView(pinia);
    await flushPromises();

    await wrapper.find('[data-test="timeframe-select"]').setValue('60m');
    await flushPromises();

    expect(wrapper.find('[data-test="research-auto-refresh-status"]').text()).toBe('Auto 180s');
  });
```

Extend the existing loading-state test:

```ts
    expect(wrapper.find('[data-test="research-auto-refresh-status"]').text()).toBe('Refreshing');
```

- [ ] **Step 2: Run the component test and verify failure**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm vitest run tests/component/ResearchView.spec.ts
```

Expected: FAIL because `data-test="research-auto-refresh-status"` is not rendered and auto-refresh is not wired.

- [ ] **Step 3: Wire the composable into ResearchView**

Edit `frequi/src/views/ResearchView.vue`.

Add this computed value after `hasSelection`:

```ts
const chartRefreshKey = computed(() =>
  [
    researchStore.selectedBotId,
    researchStore.selectedInstrument,
    timeframe.value,
    adjustment.value,
    selectedFeatureDataset.value,
    selectedEventDataset.value,
    selectedDocumentDataset.value,
    Number(smaFast.value),
    Number(smaSlow.value),
  ].join('|'),
);
```

Add this composable call after `refreshChart()` is declared:

```ts
const researchAutoRefresh = useResearchChartAutoRefresh({
  active: computed(() => true),
  timeframe,
  canRefresh: hasSelection,
  isLoading: computed(() => researchStore.chartRequestState.loading),
  refreshKey: chartRefreshKey,
  refreshChart,
});
```

Update the refresh button cell in the template from a single button to a button plus compact status:

```vue
        <div class="flex flex-col justify-end gap-1">
          <UButton
            icon="i-mdi-refresh"
            :disabled="!hasSelection || researchStore.chartRequestState.loading"
            :loading="researchStore.chartRequestState.loading"
            class="w-full justify-center"
            data-test="refresh-chart"
            @click="refreshChart"
          >
            {{ t('research.refreshChart') }}
          </UButton>
          <span
            class="min-h-4 text-center text-xs text-neutral-500 dark:text-neutral-400"
            data-test="research-auto-refresh-status"
          >
            {{ researchAutoRefresh.refreshLabel }}
          </span>
        </div>
```

- [ ] **Step 4: Run the component test and verify pass**

Run:

```powershell
pnpm vitest run tests/component/ResearchView.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add frequi/src/views/ResearchView.vue frequi/tests/component/ResearchView.spec.ts
git commit -m "feat: auto refresh research chart view"
```

Expected: commit succeeds with only the two listed files staged.

---

### Task 4: Full Frontend Verification

**Files:**
- No source files are created in this task.
- Verify modified files from Tasks 1 through 3.

**Interfaces:**
- Consumes: all interfaces produced by Tasks 1 through 3.
- Produces: verified frontend behavior and browser validation notes.

- [ ] **Step 1: Run focused unit and component tests**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm vitest run tests/unit/tradeChartRefresh.spec.ts tests/unit/useResearchChartAutoRefresh.spec.ts tests/component/ResearchView.spec.ts
```

Expected: PASS for all three files.

- [ ] **Step 2: Run typecheck**

Run:

```powershell
pnpm typecheck
```

Expected: PASS with no TypeScript or Vue template errors.

- [ ] **Step 3: Browser validation on the research surface**

Use the active research UI:

```text
http://127.0.0.1:8083/research
```

Validate this sequence:

```text
1. Select A Share Local.
2. Select 688017.
3. Select 1m.
4. Confirm the chart renders.
5. Confirm the status label shows Auto 10s.
6. Wait 10 seconds and confirm a chart request occurs without clicking refresh.
7. Change timeframe to 60m.
8. Confirm the status label shows Auto 180s.
9. Click Refresh chart manually and confirm it still sends a chart request.
10. Confirm Run backtest is not triggered by automatic refresh.
```

- [ ] **Step 4: Inspect the final diff**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
git diff -- frequi/src/utils/tradeChartRefresh.ts frequi/tests/unit/tradeChartRefresh.spec.ts frequi/src/composables/useResearchChartAutoRefresh.ts frequi/tests/unit/useResearchChartAutoRefresh.spec.ts frequi/src/views/ResearchView.vue frequi/tests/component/ResearchView.spec.ts
```

Expected:

```text
Only the shared cadence helper, new research auto-refresh composable, ResearchView wiring, and focused tests changed.
No backend files changed.
No backtest request path changed.
No global bot auto-refresh path changed.
```

- [ ] **Step 5: Confirm no verification-only commit is needed**

If Task 4 only ran commands and browser validation, do not create an empty commit.

```powershell
git status --short
```

Expected: no new uncommitted files appear from Task 4. If a code or test fix was required during verification, return to Task 1, Task 2, or Task 3, apply the fix in the owning task, rerun that task's focused test, and use that task's commit command.

---

## Acceptance Mapping

- Default-on auto-refresh: Task 2 creates default enabled behavior, Task 3 wires it without a toggle.
- Shared cadence: Task 1 keeps the cadence in `tradeChartRefresh.ts`.
- `60m -> 1h` cadence: Task 1 adds `60m` coverage and helper.
- Hidden-page pause: Task 2 visibility tests and implementation.
- Visible-page immediate refresh: Task 2 visibility resume test and implementation.
- No overlapping requests: Task 2 loading skip and Task 3 loading status.
- Manual refresh remains: Task 3 keeps the existing button and tests.
- Auto-refresh never runs backtest: Task 3 asserts `store.runBacktest` is not called.
- Existing store errors remain inline: Task 3 does not change `refreshChart()` catch or error template.
- Focused tests pass: Task 4 runs the selected Vitest files.
- Browser validates `688017 / 1m`: Task 4 browser sequence.

## Execution Notes

- Execute tasks in order. Task 2 depends on Task 1 for `60m` cadence.
- Use `apply_patch` for manual edits.
- Before each commit, run `git diff --cached` to confirm unrelated files are not staged.
- If the working tree contains unrelated user changes, do not revert them and do not stage them.
