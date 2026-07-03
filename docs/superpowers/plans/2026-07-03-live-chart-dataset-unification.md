# Live Chart Dataset Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Graph page live chart use the same `/chart_candles` data model as the current Trade page chart, while preserving historical Graph behavior.

**Architecture:** Extract the existing Trade page live chart state, refresh, and dataset derivation into a small `useLiveChartDataset()` composable. Both `TradingView.vue` and `ChartsView.vue` consume that composable in live trading mode and pass the resulting dataset props into the existing shared chart components.

**Tech Stack:** Vue 3 Composition API, Pinia, Vitest, Vue Test Utils, TypeScript, FreqUI `/chart_candles` API.

---

## File Structure

- Create: `frequi/src/composables/useLiveChartDataset.ts`
  - Owns live chart timeframe, dataset derivation, refresh payload construction, refresh timer, visibility handling, status text, warning text, and plot config.
- Create: `frequi/tests/unit/useLiveChartDataset.spec.ts`
  - Unit tests for the composable behavior.
- Modify: `frequi/src/views/TradingView.vue`
  - Remove duplicated live chart logic and consume `useLiveChartDataset()`.
- Create: `frequi/tests/component/TradingViewLiveChart.spec.ts`
  - Regression test that Trade still passes live chart props and timeframe selector.
- Modify: `frequi/src/views/ChartsView.vue`
  - Use `useLiveChartDataset()` in trading live chart mode, keep historical/webserver path unchanged.
- Create: `frequi/tests/component/ChartsViewLiveChart.spec.ts`
  - Tests Graph live mode and webserver fallback mode.
- Modify: `frequi/src/components/charts/CandleChartContainer.vue`
  - Pass `props.historicView` to `SingleCandleChartContainer`.
- Create: `frequi/tests/component/CandleChartContainerHistoricView.spec.ts`
  - Test that the parent prop is forwarded instead of global bot webserver state.

## Task 1: Add Failing Tests For `useLiveChartDataset()`

**Files:**
- Create: `frequi/tests/unit/useLiveChartDataset.spec.ts`

- [ ] **Step 1: Write the failing tests**

Create `frequi/tests/unit/useLiveChartDataset.spec.ts` with:

```ts
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { computed, defineComponent, nextTick, ref } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useLiveChartDataset } from '@/composables/useLiveChartDataset';
import { useBotStore } from '@/stores/ftbotwrapper';
import { useTradeChartStore } from '@/stores/tradeChart';
import { LoadingStatus } from '@/types';

function installBotStore() {
  const pinia = createPinia();
  setActivePinia(pinia);

  const getChartCandles = vi.fn();
  const botStore = useBotStore();
  botStore.selectedBot = 'test-bot';
  botStore.botStores = {
    'test-bot': {
      botFeatures: { chartCandles: true },
      botState: { strategy: 'VolatilitySystem' },
      timeframe: '1h',
      plotMultiPairs: ['BTC/USDT:USDT'],
      chartCandleData: {
        'BTC/USDT:USDT__1h': {
          pair: 'BTC/USDT:USDT',
          timeframe: '1h',
          data: {
            strategy: 'VolatilitySystem',
            pair: 'BTC/USDT:USDT',
            timeframe: '1h',
            timeframe_ms: 3600000,
            chart_timeframe: '1h',
            strategy_timeframe: '1h',
            candle_mode: 'live',
            columns: ['date', 'open', 'high', 'low', 'close', 'volume'],
            all_columns: ['date', 'open', 'high', 'low', 'close', 'volume'],
            data: [],
            length: 0,
            buy_signals: 0,
            sell_signals: 0,
            enter_long_signals: 0,
            exit_long_signals: 0,
            enter_short_signals: 0,
            exit_short_signals: 0,
            plot_config: {
              main_plot: { watch_ma20: {} },
              subplots: { MACD: { watch_macd: {} } },
            },
            warnings: ['Strategy overlay unavailable'],
            overlay: { strategy_timeframe: '1h', alignment: 'direct', columns: [] },
            last_candle_complete: false,
          },
        },
      },
      chartCandleDataStatus: LoadingStatus.success,
      allTrades: [],
      getChartCandles,
    },
  } as never;

  return { botStore, getChartCandles };
}

function mountLiveChart(defaultTimeframe = '1h', active = true) {
  let liveChart: ReturnType<typeof useLiveChartDataset> | undefined;
  const wrapper = mount(
    defineComponent({
      setup() {
        liveChart = useLiveChartDataset({
          active: ref(active),
          defaultTimeframe: computed(() => defaultTimeframe),
        });
        return {};
      },
      template: '<div />',
    }),
  );

  if (!liveChart) {
    throw new Error('Live chart composable did not initialize');
  }

  return { wrapper, liveChart };
}

describe('useLiveChartDataset', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('uses the bot timeframe when no live chart timeframe is selected', () => {
    installBotStore();
    const tradeChartStore = useTradeChartStore();
    tradeChartStore.selectedTimeframe = '';

    const { liveChart } = mountLiveChart('1h');

    expect(liveChart.timeframe.value).toBe('1h');
  });

  it('writes timeframe changes into the trade chart store', () => {
    installBotStore();
    const tradeChartStore = useTradeChartStore();

    const { liveChart } = mountLiveChart('1h');

    liveChart.timeframe.value = '15m';

    expect(tradeChartStore.selectedTimeframe).toBe('15m');
    expect(liveChart.timeframe.value).toBe('15m');
  });

  it('derives dataset props from chartCandleData', () => {
    installBotStore();

    const { liveChart } = mountLiveChart('1h');

    expect(liveChart.chartDataSource.value['BTC/USDT:USDT__1h']).toBeDefined();
    expect(liveChart.chartDataStatus.value).toBe(LoadingStatus.success);
    expect(liveChart.plotConfig.value?.main_plot).toHaveProperty('watch_ma20');
    expect(liveChart.warningText.value).toBe('Strategy overlay unavailable');
    expect(liveChart.statusText.value).toContain('1h');
    expect(liveChart.statusText.value).toContain('VolatilitySystem');
  });

  it('refreshes chart candles with live mode and strategy overlay', () => {
    const { getChartCandles } = installBotStore();
    const tradeChartStore = useTradeChartStore();
    tradeChartStore.useStrategyOverlay = true;

    const { liveChart } = mountLiveChart('1h');

    liveChart.refresh('BTC/USDT:USDT');

    expect(getChartCandles).toHaveBeenCalledWith({
      pair: 'BTC/USDT:USDT',
      timeframe: '1h',
      include_strategy_overlay: true,
      candle_mode: 'live',
    });
  });

  it('does not call chart candles when the feature is unavailable', () => {
    const { botStore, getChartCandles } = installBotStore();
    botStore.botStores['test-bot']!.botFeatures = { chartCandles: false } as never;

    const { liveChart } = mountLiveChart('1h');

    liveChart.refresh('BTC/USDT:USDT');

    expect(getChartCandles).not.toHaveBeenCalled();
  });

  it('schedules automatic refresh by timeframe while active', async () => {
    const { getChartCandles } = installBotStore();

    mountLiveChart('1m');
    await nextTick();

    vi.advanceTimersByTime(10_000);

    expect(getChartCandles).toHaveBeenCalledWith({
      pair: 'BTC/USDT:USDT',
      timeframe: '1m',
      include_strategy_overlay: true,
      candle_mode: 'live',
    });
  });

  it('does not schedule refresh while inactive', async () => {
    const { getChartCandles } = installBotStore();

    mountLiveChart('1m', false);
    await nextTick();

    vi.advanceTimersByTime(10_000);

    expect(getChartCandles).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the failing tests**

Run:

```powershell
pnpm test:unit -- tests/unit/useLiveChartDataset.spec.ts --run
```

Expected result:

```text
FAIL  tests/unit/useLiveChartDataset.spec.ts
Error: Failed to resolve import "@/composables/useLiveChartDataset"
```

- [ ] **Step 3: Commit the failing tests**

```powershell
git add frequi/tests/unit/useLiveChartDataset.spec.ts
git commit -m "test: cover live chart dataset composable"
```

## Task 2: Implement `useLiveChartDataset()`

**Files:**
- Create: `frequi/src/composables/useLiveChartDataset.ts`
- Test: `frequi/tests/unit/useLiveChartDataset.spec.ts`

- [ ] **Step 1: Create the composable**

Create `frequi/src/composables/useLiveChartDataset.ts` with:

```ts
import type { ComputedRef, Ref } from 'vue';
import type { PlotConfig } from '@/types';
import { getTradeChartRefreshIntervalMs } from '@/utils/tradeChartRefresh';

const LIVE_CHART_TIMEFRAME_BASE_OPTIONS = [
  '1m',
  '3m',
  '5m',
  '15m',
  '30m',
  '1h',
  '2h',
  '4h',
  '6h',
  '8h',
  '12h',
  '1d',
  '3d',
  '1w',
  '2w',
  '1M',
  '1y',
];

interface UseLiveChartDatasetOptions {
  active: Ref<boolean> | ComputedRef<boolean>;
  defaultTimeframe: Ref<string> | ComputedRef<string>;
}

export function useLiveChartDataset(options: UseLiveChartDatasetOptions) {
  const botStore = useBotStore();
  const tradeChartStore = useTradeChartStore();
  const { t } = useAppI18n();
  let refreshTimer: number | undefined;

  const useChartCandles = computed(() => !!botStore.activeBot?.botFeatures?.chartCandles);

  const timeframe = computed({
    get() {
      return tradeChartStore.selectedTimeframe || options.defaultTimeframe.value;
    },
    set(value: string) {
      tradeChartStore.selectedTimeframe = value;
    },
  });

  const timeframeOptions = computed(() => {
    const nonCanonicalTimeframes = [timeframe.value, options.defaultTimeframe.value].filter(
      (tf): tf is string => !!tf && !LIVE_CHART_TIMEFRAME_BASE_OPTIONS.includes(tf),
    );

    return [...new Set([...nonCanonicalTimeframes, ...LIVE_CHART_TIMEFRAME_BASE_OPTIONS])];
  });

  const dataset = computed(() => {
    const [pair] = botStore.activeBot?.plotMultiPairs ?? [];
    if (!pair || !timeframe.value) {
      return undefined;
    }

    return botStore.activeBot.chartCandleData[`${pair}__${timeframe.value}`]?.data;
  });

  const chartDataSource = computed(() => botStore.activeBot?.chartCandleData ?? {});
  const chartDataStatus = computed(() => botStore.activeBot?.chartCandleDataStatus);
  const plotConfig = computed<PlotConfig | undefined>(() => dataset.value?.plot_config);
  const warningText = computed(() => dataset.value?.warnings?.join(' ') ?? '');

  const statusText = computed(() => {
    const currentDataset = dataset.value;
    const chartTimeframe = currentDataset?.chart_timeframe || timeframe.value;
    const strategyName = currentDataset?.strategy || botStore.activeBot?.botState?.strategy || '';
    const strategyTimeframe =
      currentDataset?.strategy_timeframe || currentDataset?.overlay?.strategy_timeframe || '';
    const strategyOverlay = [strategyName, strategyTimeframe].filter(Boolean).join(' ');

    if (!strategyOverlay) {
      return chartTimeframe;
    }

    return formatLocaleText(t('trade.chartStatus'), {
      chartTimeframe,
      strategy: strategyOverlay,
      strategyTimeframe: '',
    }).trim();
  });

  function refresh(pair: string) {
    if (!useChartCandles.value || !pair || !timeframe.value) {
      return;
    }

    botStore.activeBot.getChartCandles({
      pair,
      timeframe: timeframe.value,
      include_strategy_overlay: tradeChartStore.useStrategyOverlay,
      candle_mode: 'live',
    });
  }

  function refreshAll() {
    if (!useChartCandles.value) {
      return;
    }

    for (const pair of botStore.activeBot.plotMultiPairs) {
      refresh(pair);
    }
  }

  function clearRefreshTimer() {
    if (refreshTimer) {
      window.clearTimeout(refreshTimer);
      refreshTimer = undefined;
    }
  }

  function scheduleRefresh() {
    clearRefreshTimer();

    if (
      !options.active.value ||
      !useChartCandles.value ||
      !timeframe.value ||
      botStore.activeBot.plotMultiPairs.length === 0
    ) {
      return;
    }

    refreshTimer = window.setTimeout(() => {
      if (document.visibilityState !== 'hidden') {
        refreshAll();
      }
      scheduleRefresh();
    }, getTradeChartRefreshIntervalMs(timeframe.value));
  }

  function handleVisibilityChange() {
    if (document.visibilityState === 'hidden') {
      clearRefreshTimer();
      return;
    }

    if (options.active.value) {
      refreshAll();
      scheduleRefresh();
    }
  }

  watch(
    () => botStore.selectedBot,
    () => {
      tradeChartStore.resetForBot(options.defaultTimeframe.value);
      tradeChartStore.activeBotId = botStore.selectedBot;
      tradeChartStore.isTradeChartActive = options.active.value;
    },
    { immediate: true },
  );

  watch(
    () => timeframe.value,
    () => {
      if (options.active.value) {
        refreshAll();
      }
    },
  );

  watch(
    () => [
      options.active.value,
      botStore.selectedBot,
      timeframe.value,
      botStore.activeBot?.plotMultiPairs?.join('|') ?? '',
      useChartCandles.value,
      tradeChartStore.useStrategyOverlay,
    ],
    () => {
      tradeChartStore.isTradeChartActive = options.active.value;
      scheduleRefresh();
    },
  );

  onMounted(() => {
    document.addEventListener('visibilitychange', handleVisibilityChange);
    scheduleRefresh();
  });

  onUnmounted(() => {
    clearRefreshTimer();
    document.removeEventListener('visibilitychange', handleVisibilityChange);
    if (tradeChartStore.activeBotId === botStore.selectedBot) {
      tradeChartStore.activeBotId = '';
      tradeChartStore.isTradeChartActive = false;
    }
  });

  return {
    timeframe,
    timeframeOptions,
    chartDataSource,
    chartDataStatus,
    plotConfig,
    warningText,
    statusText,
    refresh,
    refreshAll,
  };
}
```

- [ ] **Step 2: Run the composable test**

Run:

```powershell
pnpm test:unit -- tests/unit/useLiveChartDataset.spec.ts --run
```

Expected result:

```text
PASS  tests/unit/useLiveChartDataset.spec.ts
```

- [ ] **Step 3: Run existing refresh helper tests**

Run:

```powershell
pnpm test:unit -- tests/unit/tradeChartRefresh.spec.ts --run
```

Expected result:

```text
PASS  tests/unit/tradeChartRefresh.spec.ts
```

- [ ] **Step 4: Commit the composable**

```powershell
git add frequi/src/composables/useLiveChartDataset.ts frequi/tests/unit/useLiveChartDataset.spec.ts
git commit -m "feat: add shared live chart dataset composable"
```

## Task 3: Refactor Trade Page To Use The Composable

**Files:**
- Modify: `frequi/src/views/TradingView.vue`
- Create: `frequi/tests/component/TradingViewLiveChart.spec.ts`

- [ ] **Step 1: Write the failing Trade page regression test**

Create `frequi/tests/component/TradingViewLiveChart.spec.ts` with:

```ts
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { computed, ref } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import TradingView from '@/views/TradingView.vue';
import { useBotStore } from '@/stores/ftbotwrapper';
import { LoadingStatus } from '@/types';

const refresh = vi.fn();
const liveChart = {
  timeframe: ref('1h'),
  timeframeOptions: computed(() => ['1m', '15m', '1h']),
  chartDataSource: computed(() => ({ 'BTC/USDT:USDT__1h': { data: { plot_config: {} } } })),
  chartDataStatus: computed(() => LoadingStatus.success),
  plotConfig: computed(() => ({ main_plot: { watch_ma20: {} }, subplots: {} })),
  warningText: computed(() => 'warning text'),
  statusText: computed(() => '1h VolatilitySystem'),
  refresh,
  refreshAll: vi.fn(),
};

vi.mock('@/composables/useLiveChartDataset', () => ({
  useLiveChartDataset: () => liveChart,
}));

function installTradingBot() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const botStore = useBotStore();
  botStore.selectedBot = 'test-bot';
  botStore.botStores = {
    'test-bot': {
      botFeatures: { chartCandles: true },
      timeframe: '1h',
      whitelist: ['BTC/USDT:USDT'],
      plotMultiPairs: ['BTC/USDT:USDT'],
      allTrades: [],
      openTrades: [],
      closedTrades: [],
      activeLocks: [],
      detailTradeId: null,
      tradeDetail: undefined,
      stakeCurrency: 'USDT',
      botState: { strategy: 'VolatilitySystem' },
    },
  } as never;

  return pinia;
}

describe('TradingView live chart', () => {
  beforeEach(() => {
    refresh.mockClear();
  });

  it('passes shared live chart props to CandleChartContainer', () => {
    const pinia = installTradingBot();

    const wrapper = mount(TradingView, {
      global: {
        plugins: [pinia],
        stubs: {
          GridLayout: { template: '<div><slot :gridItemProps=\"{}\" /></div>' },
          GridItem: { template: '<div><slot /></div>' },
          DraggableContainer: { template: '<section><slot /></section>' },
          UTabs: true,
          PairSummary: true,
          BotControls: true,
          BotStatus: true,
          BotPerformance: true,
          BotBalance: true,
          PeriodBreakdown: true,
          PairListLive: true,
          PairLockList: true,
          TradeList: true,
          TradeDetail: true,
          USelect: true,
          CandleChartContainer: {
            props: [
              'chartDataSource',
              'chartDataStatus',
              'plotConfigOverride',
              'chartStatusText',
              'chartWarningText',
              'timeframe',
            ],
            template: '<div data-test=\"chart\">{{ chartStatusText }} {{ chartWarningText }}</div>',
          },
        },
      },
    });

    const chart = wrapper.findComponent({ name: 'CandleChartContainer' });

    expect(chart.props('timeframe')).toBe('1h');
    expect(chart.props('chartDataSource')).toEqual(liveChart.chartDataSource.value);
    expect(chart.props('chartDataStatus')).toBe(LoadingStatus.success);
    expect(chart.props('plotConfigOverride')).toEqual(liveChart.plotConfig.value);
    expect(chart.props('chartStatusText')).toBe('1h VolatilitySystem');
    expect(chart.props('chartWarningText')).toBe('warning text');
  });
});
```

- [ ] **Step 2: Run the failing Trade page test**

Run:

```powershell
pnpm test:unit -- tests/component/TradingViewLiveChart.spec.ts --run
```

Expected result:

```text
FAIL  tests/component/TradingViewLiveChart.spec.ts
```

The failure should show that `TradingView.vue` still computes and passes its own live chart props instead of using the mocked composable.

- [ ] **Step 3: Update `TradingView.vue` script**

In `frequi/src/views/TradingView.vue`, remove the Trade-chart-only import and declarations that are superseded by `useLiveChartDataset()`:

- Remove `import { getTradeChartRefreshIntervalMs } from '@/utils/tradeChartRefresh';`.
- Remove `let tradeChartRefreshTimer: number | undefined;`.
- Remove the `tradeChartTimeframeBaseOptions` array declaration.
- Remove the `tradeChartTimeframe` computed getter/setter.
- Remove the local `useChartCandles` computed declaration.
- Remove the `tradeChartTimeframeOptions` computed declaration.
- Remove the `tradeChartDataset` computed declaration.
- Remove the `tradeChartPlotConfig` computed declaration.
- Remove the `tradeChartWarningText` computed declaration.
- Remove the `tradeChartStatusText` computed declaration.
- Remove `refreshOHLCV()`.
- Remove `refreshTradeChartPairs()`.
- Remove `clearTradeChartRefreshTimer()`.
- Remove `scheduleTradeChartRefresh()`.
- Remove `handleTradeChartVisibilityChange()`.
- Remove the `watch()` block that resets `tradeChartStore` for `botStore.selectedBot`.
- Remove the `watch()` block that refreshes pairs on `tradeChartTimeframe` changes.
- Remove the `watch()` block that schedules refreshes from bot, timeframe, pair, feature, and overlay changes.
- Remove the `onMounted()` block that adds `visibilitychange` and schedules refresh.
- Remove the `onUnmounted()` block that clears the timer and removes `visibilitychange`.

Add the shared composable state near the existing stores:

```ts
const useChartCandles = computed(() => botStore.activeBot.botFeatures.chartCandles);
const liveChart = useLiveChartDataset({
  active: computed(() => true),
  defaultTimeframe: computed(() => botStore.activeBot.timeframe),
});
```

- [ ] **Step 4: Update `TradingView.vue` template**

Replace the chart container props in `frequi/src/views/TradingView.vue` with:

```vue
<CandleChartContainer
  :available-pairs="botStore.activeBot.whitelist"
  :historic-view="!!false"
  :timeframe="liveChart.timeframe.value"
  :trades="botStore.activeBot.allTrades"
  :chart-data-source="useChartCandles ? liveChart.chartDataSource.value : undefined"
  :chart-data-status="useChartCandles ? liveChart.chartDataStatus.value : undefined"
  :plot-config-override="useChartCandles ? liveChart.plotConfig.value : undefined"
  :chart-status-text="useChartCandles ? liveChart.statusText.value : undefined"
  :chart-warning-text="useChartCandles ? liveChart.warningText.value : undefined"
  @refresh-data="liveChart.refresh"
>
  <template #timeframe-select>
    <div v-if="useChartCandles" class="flex items-center gap-1">
      <span class="text-sm text-nowrap">{{ t('trade.chartTimeframe') }}</span>
      <USelect
        v-model="liveChart.timeframe.value"
        :title="t('trade.chartTimeframe')"
        :items="liveChart.timeframeOptions.value"
        size="sm"
        class="w-24"
      />
    </div>
  </template>
</CandleChartContainer>
```

- [ ] **Step 5: Run the Trade page test**

Run:

```powershell
pnpm test:unit -- tests/component/TradingViewLiveChart.spec.ts --run
```

Expected result:

```text
PASS  tests/component/TradingViewLiveChart.spec.ts
```

- [ ] **Step 6: Run the composable tests again**

Run:

```powershell
pnpm test:unit -- tests/unit/useLiveChartDataset.spec.ts --run
```

Expected result:

```text
PASS  tests/unit/useLiveChartDataset.spec.ts
```

- [ ] **Step 7: Commit the Trade page refactor**

```powershell
git add frequi/src/views/TradingView.vue frequi/tests/component/TradingViewLiveChart.spec.ts
git commit -m "refactor: use shared live chart dataset on trade page"
```

## Task 4: Migrate Graph Trading Mode To The Live Chart Dataset

**Files:**
- Modify: `frequi/src/views/ChartsView.vue`
- Create: `frequi/tests/component/ChartsViewLiveChart.spec.ts`

- [ ] **Step 1: Write the failing Graph page tests**

Create `frequi/tests/component/ChartsViewLiveChart.spec.ts` with:

```ts
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { computed, ref } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ChartsView from '@/views/ChartsView.vue';
import { useBotStore } from '@/stores/ftbotwrapper';
import { LoadingStatus, RunModes } from '@/types';

const refresh = vi.fn();
const liveChart = {
  timeframe: ref('1h'),
  timeframeOptions: computed(() => ['1m', '15m', '1h']),
  chartDataSource: computed(() => ({ 'BTC/USDT:USDT__1h': { data: { plot_config: {} } } })),
  chartDataStatus: computed(() => LoadingStatus.success),
  plotConfig: computed(() => ({ main_plot: { watch_ma20: {} }, subplots: {} })),
  warningText: computed(() => 'live warning'),
  statusText: computed(() => '1h VolatilitySystem'),
  refresh,
  refreshAll: vi.fn(),
};

vi.mock('@/composables/useLiveChartDataset', () => ({
  useLiveChartDataset: () => liveChart,
}));

function installBot({ webserverMode = false, chartCandles = true } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const botStore = useBotStore();
  const getPairHistory = vi.fn();
  const getPairCandles = vi.fn();

  botStore.selectedBot = 'test-bot';
  botStore.botStores = {
    'test-bot': {
      isWebserverMode: webserverMode,
      botFeatures: { chartCandles, chartLiveData: true },
      botState: {
        exchange: 'okx',
        trading_mode: webserverMode ? 'spot' : 'futures',
        runmode: webserverMode ? RunModes.WEBSERVER : RunModes.DRY_RUN,
      },
      timeframe: '1h',
      whitelist: ['BTC/USDT:USDT'],
      pairlist: ['BTC/USDT:USDT'],
      pairlistWithTimeframe: [['BTC/USDT:USDT', '1h']],
      plotMultiPairs: ['BTC/USDT:USDT'],
      allTrades: [],
      history: {},
      candleData: {},
      getAvailablePairs: vi.fn(),
      getWhitelist: vi.fn(),
      getMarkets: vi.fn().mockResolvedValue({ markets: {} }),
      getPairHistory,
      getPairCandles,
    },
  } as never;

  return { pinia, botStore, getPairHistory, getPairCandles };
}

describe('ChartsView live chart mode', () => {
  beforeEach(() => {
    refresh.mockClear();
  });

  it('uses shared live chart props in trading mode', () => {
    const { pinia } = installBot({ webserverMode: false, chartCandles: true });

    const wrapper = mount(ChartsView, {
      global: {
        plugins: [pinia],
        stubs: {
          UCard: { template: '<div><slot /></div>' },
          UCollapsible: true,
          BaseCheckbox: true,
          StrategySelect: true,
          TimeframeSelect: true,
          TimeRangeSelect: true,
          ExchangeSelect: true,
          InfoBox: true,
          USelect: true,
          CandleChartContainer: {
            props: [
              'chartDataSource',
              'chartDataStatus',
              'plotConfigOverride',
              'chartStatusText',
              'chartWarningText',
              'timeframe',
              'historicView',
            ],
            template: '<div data-test=\"chart\">{{ chartStatusText }} {{ chartWarningText }}</div>',
          },
        },
      },
    });

    const chart = wrapper.findComponent({ name: 'CandleChartContainer' });

    expect(chart.props('historicView')).toBe(false);
    expect(chart.props('timeframe')).toBe('1h');
    expect(chart.props('chartDataSource')).toEqual(liveChart.chartDataSource.value);
    expect(chart.props('chartDataStatus')).toBe(LoadingStatus.success);
    expect(chart.props('plotConfigOverride')).toEqual(liveChart.plotConfig.value);
    expect(chart.props('chartStatusText')).toBe('1h VolatilitySystem');
    expect(chart.props('chartWarningText')).toBe('live warning');
  });

  it('keeps the historical path in webserver mode', async () => {
    const { pinia, getPairHistory } = installBot({ webserverMode: true, chartCandles: true });

    const wrapper = mount(ChartsView, {
      global: {
        plugins: [pinia],
        stubs: {
          UCard: { template: '<div><slot /></div>' },
          UCollapsible: true,
          BaseCheckbox: true,
          StrategySelect: true,
          TimeframeSelect: true,
          TimeRangeSelect: true,
          ExchangeSelect: true,
          InfoBox: true,
          CandleChartContainer: {
            emits: ['refreshData'],
            template: '<button data-test=\"refresh\" @click=\"$emit(\\'refreshData\\', \\'BTC/USDT:USDT\\', [])\" />',
          },
        },
      },
    });

    await wrapper.find('[data-test=\"refresh\"]').trigger('click');

    expect(getPairHistory).toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the failing Graph page test**

Run:

```powershell
pnpm test:unit -- tests/component/ChartsViewLiveChart.spec.ts --run
```

Expected result:

```text
FAIL  tests/component/ChartsViewLiveChart.spec.ts
```

The live-mode test should fail because `ChartsView.vue` still passes old chart props.

- [ ] **Step 3: Update `ChartsView.vue` script**

In `frequi/src/views/ChartsView.vue`, add live mode state:

```ts
const useLiveChart = computed(
  () => !botStore.activeBot.isWebserverMode && botStore.activeBot.botFeatures.chartCandles,
);

const liveChart = useLiveChartDataset({
  active: useLiveChart,
  defaultTimeframe: computed(() => botStore.activeBot.timeframe),
});
```

Update `finalTimeframe` to:

```ts
const finalTimeframe = computed<string>(() => {
  if (useLiveChart.value) {
    return liveChart.timeframe.value;
  }

  return botStore.activeBot.isWebserverMode
    ? chartStore.selectedTimeframe || botStore.activeBot.strategy?.timeframe || ''
    : botStore.activeBot.timeframe;
});
```

Update `refreshOHLCV()` to:

```ts
function refreshOHLCV(pair: string, columns: string[]) {
  if (useLiveChart.value) {
    liveChart.refresh(pair);
    return;
  }

  console.log('Refreshing OHLCV for pair:', pair, finalTimeframe.value, 'with columns:', columns);
  if (botStore.activeBot.isWebserverMode && finalTimeframe.value) {
    const payload: PairHistoryPayload = {
      pair: pair,
      timeframe: finalTimeframe.value,
      timerange: chartStore.timerange,
      strategy: chartStore.strategy,
      columns: columns,
      live_mode: chartStore.useLiveData,
    };
    if (exchange.value.customExchange) {
      payload.exchange = exchange.value.selectedExchange.exchange;
      payload.trading_mode = exchange.value.selectedExchange.trade_mode.trading_mode;
      payload.margin_mode = exchange.value.selectedExchange.trade_mode.margin_mode;
    }
    botStore.activeBot.getPairHistory(payload);
  } else {
    botStore.activeBot.getPairCandles({
      pair: pair,
      timeframe: finalTimeframe.value,
      columns: columns,
    });
  }
}
```

- [ ] **Step 4: Update `ChartsView.vue` template**

Update the `CandleChartContainer` block to:

```vue
<CandleChartContainer
  :available-pairs="availablePairs"
  :historic-view="botStore.activeBot.isWebserverMode"
  :timeframe="finalTimeframe"
  :trades="botStore.activeBot.allTrades"
  :timerange="botStore.activeBot.isWebserverMode ? chartStore.timerange : undefined"
  :strategy="botStore.activeBot.isWebserverMode ? chartStore.strategy : undefined"
  :chart-data-source="useLiveChart ? liveChart.chartDataSource.value : undefined"
  :chart-data-status="useLiveChart ? liveChart.chartDataStatus.value : undefined"
  :plot-config-override="useLiveChart ? liveChart.plotConfig.value : undefined"
  :chart-status-text="useLiveChart ? liveChart.statusText.value : undefined"
  :chart-warning-text="useLiveChart ? liveChart.warningText.value : undefined"
  @refresh-data="refreshOHLCV"
>
  <template #timeframe-select>
    <div v-if="useLiveChart" class="flex items-center gap-1">
      <span class="text-sm text-nowrap">{{ t('trade.chartTimeframe') }}</span>
      <USelect
        v-model="liveChart.timeframe.value"
        :title="t('trade.chartTimeframe')"
        :items="liveChart.timeframeOptions.value"
        size="sm"
        class="w-24"
      />
    </div>
  </template>
</CandleChartContainer>
```

- [ ] **Step 5: Run the Graph page tests**

Run:

```powershell
pnpm test:unit -- tests/component/ChartsViewLiveChart.spec.ts --run
```

Expected result:

```text
PASS  tests/component/ChartsViewLiveChart.spec.ts
```

- [ ] **Step 6: Run Trade and composable tests**

Run:

```powershell
pnpm test:unit -- tests/component/TradingViewLiveChart.spec.ts tests/unit/useLiveChartDataset.spec.ts --run
```

Expected result:

```text
PASS  tests/component/TradingViewLiveChart.spec.ts
PASS  tests/unit/useLiveChartDataset.spec.ts
```

- [ ] **Step 7: Commit the Graph page migration**

```powershell
git add frequi/src/views/ChartsView.vue frequi/tests/component/ChartsViewLiveChart.spec.ts
git commit -m "feat: use live chart dataset on graph page"
```

## Task 5: Fix `CandleChartContainer` Historic View Boundary

**Files:**
- Modify: `frequi/src/components/charts/CandleChartContainer.vue`
- Create: `frequi/tests/component/CandleChartContainerHistoricView.spec.ts`

- [ ] **Step 1: Write the failing component boundary test**

Create `frequi/tests/component/CandleChartContainerHistoricView.spec.ts` with:

```ts
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';

import CandleChartContainer from '@/components/charts/CandleChartContainer.vue';
import { useBotStore } from '@/stores/ftbotwrapper';

describe('CandleChartContainer historicView boundary', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('forwards the historicView prop to SingleCandleChartContainer', () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const botStore = useBotStore();
    botStore.selectedBot = 'test-bot';
    botStore.botStores = {
      'test-bot': {
        isWebserverMode: true,
        selectedPair: 'BTC/USDT',
        plotMultiPairs: ['BTC/USDT'],
      },
    } as never;

    const wrapper = mount(CandleChartContainer, {
      props: {
        availablePairs: ['BTC/USDT'],
        timeframe: '1h',
        historicView: false,
      },
      global: {
        plugins: [pinia],
        stubs: {
          BaseStringMultiSelectMenu: true,
          USelectMenu: true,
          UButton: true,
          BaseCheckbox: true,
          PlotConfigSelect: true,
          DraggableModal: true,
          PlotConfigurator: true,
          SingleCandleChartContainer: {
            props: ['historicView'],
            template: '<div data-test=\"single\">{{ String(historicView) }}</div>',
          },
        },
      },
    });

    expect(wrapper.find('[data-test=\"single\"]').text()).toBe('false');
  });
});
```

- [ ] **Step 2: Run the failing boundary test**

Run:

```powershell
pnpm test:unit -- tests/component/CandleChartContainerHistoricView.spec.ts --run
```

Expected result:

```text
FAIL  tests/component/CandleChartContainerHistoricView.spec.ts
```

The test should fail because the component currently forwards `botStore.activeBot.isWebserverMode`.

- [ ] **Step 3: Implement the boundary fix**

In `frequi/src/components/charts/CandleChartContainer.vue`, replace:

```vue
:historic-view="botStore.activeBot.isWebserverMode"
```

with:

```vue
:historic-view="props.historicView"
```

- [ ] **Step 4: Run the boundary test**

Run:

```powershell
pnpm test:unit -- tests/component/CandleChartContainerHistoricView.spec.ts --run
```

Expected result:

```text
PASS  tests/component/CandleChartContainerHistoricView.spec.ts
```

- [ ] **Step 5: Commit the boundary fix**

```powershell
git add frequi/src/components/charts/CandleChartContainer.vue frequi/tests/component/CandleChartContainerHistoricView.spec.ts
git commit -m "fix: forward chart container historic view prop"
```

## Task 6: Run Full Frontend Verification

**Files:**
- No source changes expected.

- [ ] **Step 1: Run targeted live chart tests**

Run:

```powershell
pnpm test:unit -- tests/unit/useLiveChartDataset.spec.ts tests/component/TradingViewLiveChart.spec.ts tests/component/ChartsViewLiveChart.spec.ts tests/component/CandleChartContainerHistoricView.spec.ts --run
```

Expected result:

```text
PASS  tests/unit/useLiveChartDataset.spec.ts
PASS  tests/component/TradingViewLiveChart.spec.ts
PASS  tests/component/ChartsViewLiveChart.spec.ts
PASS  tests/component/CandleChartContainerHistoricView.spec.ts
```

- [ ] **Step 2: Run existing chart-related tests**

Run:

```powershell
pnpm test:unit -- tests/unit/tradeChartRefresh.spec.ts tests/unit/chartZoom.spec.ts tests/unit/plotConfigKey.spec.ts tests/unit/signalTooltip.spec.ts tests/component/SingleCandleChartContainer.spec.ts --run
```

Expected result:

```text
PASS  tests/unit/tradeChartRefresh.spec.ts
PASS  tests/unit/chartZoom.spec.ts
PASS  tests/unit/plotConfigKey.spec.ts
PASS  tests/unit/signalTooltip.spec.ts
PASS  tests/component/SingleCandleChartContainer.spec.ts
```

- [ ] **Step 3: Run typecheck**

Run:

```powershell
pnpm typecheck
```

Expected result:

```text
vue-tsc --build --noEmit
```

The command exits with code 0.

- [ ] **Step 4: Run frontend build**

Run:

```powershell
pnpm build
```

Expected result:

```text
build completed successfully
```

The existing third-party Rolldown warning from `@vueuse/core` can appear if the command still exits with code 0.

- [ ] **Step 5: Commit verification-only generated changes if any**

If type generation or formatting changes files, inspect them first:

```powershell
git status --short
```

Only commit files produced by this implementation:

```powershell
git add <implementation-owned-files>
git commit -m "test: verify live chart dataset unification"
```

Skip this commit if no files changed.

## Task 7: Rebuild, Restart, And Browser Verify

**Files:**
- No source changes expected.

- [ ] **Step 1: Rebuild and restart Docker services**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
docker compose up -d --build --force-recreate
```

Expected result:

```text
Container freqtrade-cn Started
Container freqtrade-cn-futures Started
```

- [ ] **Step 2: Verify both APIs respond**

Run:

```powershell
$cfg = Get-Content -Raw 'G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\config.json' | ConvertFrom-Json
$auth = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes("$($cfg.api_server.username):$($cfg.api_server.password)"))
Invoke-RestMethod -Uri 'http://127.0.0.1:8081/api/v1/ping' -Headers @{Authorization="Basic $auth"}

$cfg2 = Get-Content -Raw 'G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\config.volatility.futures.json' | ConvertFrom-Json
$auth2 = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes("$($cfg2.api_server.username):$($cfg2.api_server.password)"))
Invoke-RestMethod -Uri 'http://127.0.0.1:8082/api/v1/ping' -Headers @{Authorization="Basic $auth2"}
```

Expected result for both:

```text
status
------
pong
```

- [ ] **Step 3: Browser verify spot bot**

Use the in-app browser:

1. Open `http://127.0.0.1:8081/trade?livechartverify=<timestamp>`.
2. Select `BTC/USDT` and `1m`.
3. Record signal counts and visible legend.
4. Open `http://127.0.0.1:8081/graph?livechartverify=<timestamp>`.
5. Select the same pair and `1m`.
6. Confirm latest candle timestamp, signal counts, watch indicators, and legend match the Trade page.
7. Repeat with `15m` and `1h`.

- [ ] **Step 4: Browser verify futures bot**

Use the in-app browser:

1. Open `http://127.0.0.1:8082/trade?livechartverify=<timestamp>`.
2. Select `BTC/USDT:USDT` and `1h`.
3. Record signal counts and visible legend.
4. Open `http://127.0.0.1:8082/graph?livechartverify=<timestamp>`.
5. Select `BTC/USDT:USDT` and `1h`.
6. Confirm latest candle timestamp, signal counts, watch indicators, and strategy overlay match the Trade page.

- [ ] **Step 5: Verify zoom preservation on Graph page**

Use the in-app browser:

1. Open `http://127.0.0.1:8081/graph?livechartzoom=<timestamp>`.
2. Select `BTC/USDT` and `1m`.
3. Zoom into the chart.
4. Wait at least 12 seconds.
5. Confirm the chart refreshes and the zoom range remains stable.

- [ ] **Step 6: Final status check**

Run:

```powershell
git status --short
```

Expected result:

Only implementation-owned files should be modified or committed. Existing unrelated dirty files may remain; do not revert them.
