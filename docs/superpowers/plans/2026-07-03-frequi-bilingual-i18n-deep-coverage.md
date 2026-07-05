# FreqUI Bilingual i18n Deep Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing FreqUI bilingual display system from navigation/settings/login into the Plot Configurator, chart controls, trading panel, dashboard, and their high-visibility child components.

**Architecture:** Reuse the current lightweight app-owned i18n layer: `src/locales/en.ts`, `src/locales/zh-CN.ts`, `src/locales/keys.ts`, and `useAppI18n().t(key)`. Keep all exchange data, market symbols, strategy names, dataframe column names, indicator names, pair names, trade tags, and API payload values unchanged; only FreqUI-owned labels, headings, tooltips, modal text, table headers, button labels, placeholders, and toast/confirm copy are localized. Avoid introducing vue-i18n, DOM rewriting, browser translation, backend changes, or a second translation path.

**Tech Stack:** Vue 3, Vite, TypeScript, Pinia, Nuxt UI, ECharts, Vitest, Playwright, Docker Compose.

---

## Scope Notes

- Current first-stage i18n foundation already exists in `G:\AI_Trading\freqtrade-cn\frequi`.
- Continue work inside the existing FreqUI branch unless the user requests a new branch.
- Do not modify `G:\AI_Trading\freqtrade-cn\freqtrade`.
- Do not edit `G:\AI_Trading\freqtrade-cn\frequi\dist`.
- Do not translate:
  - `BTC/USDT`, `ETH/USDT`, exchange names, strategy names, bot names.
  - Plot config names such as `default`, subplot names such as `main_plot`, and indicator/dataframe names such as `VOL`, `MACD`, `RSI`, `ma20`, `tema`, `sar`.
  - API enum values or payload fields such as `long`, `short`, `market`, `limit`, `spot`, `futures`.
- Do translate the human text around those values, for example `Plot Configurator / 图表绘制配置`, `Remove indicator / 移除指标`, `Current Exchange / 当前交易所`.
- When text is used in a reactive computed structure, make that structure `computed(...)`; do not build translated arrays once at module setup if the text must react to Settings language changes.

## File Structure

Modify locale foundation:

- `G:\AI_Trading\freqtrade-cn\frequi\src\locales\en.ts`  
  Add `common`, `plot`, `chart`, `trade`, `dashboard`, and `bot` namespaces.
- `G:\AI_Trading\freqtrade-cn\frequi\src\locales\zh-CN.ts`  
  Add matching Simplified Chinese messages.
- `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`  
  Add resolver assertions for the new namespaces.

Modify chart and Plot Configurator surface:

- `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\CandleChartContainer.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\SingleCandleChartContainer.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\CandleChart.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\PlotConfigurator.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\PlotFromTemplate.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\PlotIndicator.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\PlotIndicatorSelect.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\PlotConfigSelect.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TimeRangeSelect.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TimeframeSelect.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\ExchangeSelect.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\views\ChartsView.vue`

Modify trading surface:

- `G:\AI_Trading\freqtrade-cn\frequi\src\views\TradingView.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotControls.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TradeList.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TradeActions.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TradeActionsPopover.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\ForceEntryForm.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\ForceExitForm.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TradeDetail.vue`

Modify trading/dashboard shared widgets:

- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotStatus.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotPerformance.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotBalance.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotProfit.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\PairSummary.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\PairListLive.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\PairLockList.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\PeriodBreakdown.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotComparisonList.vue`
- `G:\AI_Trading\freqtrade-cn\frequi\src\views\DashboardView.vue`

Modify focused E2E tests:

- `G:\AI_Trading\freqtrade-cn\frequi\e2e\i18n.spec.ts`
- `G:\AI_Trading\freqtrade-cn\frequi\e2e\chart.spec.ts`
- `G:\AI_Trading\freqtrade-cn\frequi\e2e\trade.spec.ts`
- `G:\AI_Trading\freqtrade-cn\frequi\e2e\dashboard.spec.ts`

---

### Task 0: Confirm Current State and Generate a Targeted String Audit

**Files:**
- Inspect only: `G:\AI_Trading\freqtrade-cn`
- Inspect only: `G:\AI_Trading\freqtrade-cn\frequi`

- [ ] **Step 1: Confirm repository state**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn status --short --branch
git -C G:\AI_Trading\freqtrade-cn\frequi status --short --branch
git -C G:\AI_Trading\freqtrade-cn\frequi log --oneline --max-count=5
```

Expected:

```text
Top-level may show existing untracked Docker/runtime files.
frequi should be on cn/i18n and clean before implementation starts.
```

- [ ] **Step 2: Audit hardcoded user-facing strings in the requested surfaces**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
rg -n --glob '*.vue' --glob '*.ts' "('[A-Z][^']{2,}'|\"[A-Z][^\"]{2,}\")" src/views/TradingView.vue src/views/DashboardView.vue src/views/ChartsView.vue src/components/charts src/components/ftbot
```

Expected:

```text
The command lists candidate strings. Use it as an audit checklist only.
Do not translate API values, runtime data, indicator names, pair names, or enum values.
```

- [ ] **Step 3: Record the implementation rule in the commit notes**

Use this rule for every later task:

```text
Translate only FreqUI-owned copy. Preserve data-owned values and payload values.
```

---

### Task 1: Add Locale Keys for the Deep Coverage Slice

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\locales\en.ts`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\locales\zh-CN.ts`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`

- [ ] **Step 1: Add failing assertions for the new namespaces**

Append this block to `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`:

```ts
describe('deep coverage locale labels', () => {
  it('resolves plot and chart labels', () => {
    expect(resolveLocaleText('plot.configuratorTitle', 'bilingual')).toBe(
      'Plot Configurator / 图表绘制配置',
    );
    expect(resolveLocaleText('plot.addIndicator', 'bilingual')).toBe(
      'Add indicator / 添加指标',
    );
    expect(resolveLocaleText('chart.refreshChart', 'bilingual')).toBe(
      'Refresh chart / 刷新图表',
    );
    expect(resolveLocaleText('chart.noDataAvailable', 'bilingual')).toBe(
      'No data available / 暂无数据',
    );
  });

  it('resolves trade panel labels', () => {
    expect(resolveLocaleText('trade.openTrades', 'bilingual')).toBe('Open Trades / 未平仓交易');
    expect(resolveLocaleText('trade.reloadConfig', 'bilingual')).toBe('Reload Config / 重新加载配置');
    expect(resolveLocaleText('trade.forceExitTrade', 'bilingual')).toBe(
      'Force exit trade / 强制退出交易',
    );
    expect(resolveLocaleText('trade.table.profitPercent', 'bilingual')).toBe('Profit % / 收益率 %');
  });

  it('resolves dashboard and bot labels', () => {
    expect(resolveLocaleText('dashboard.botComparison', 'bilingual')).toBe(
      'Bot comparison / 机器人对比',
    );
    expect(resolveLocaleText('dashboard.cumulativeProfit', 'bilingual')).toBe(
      'Cumulative Profit / 累计收益',
    );
    expect(resolveLocaleText('bot.performance', 'bilingual')).toBe('Performance / 表现');
    expect(resolveLocaleText('bot.balance', 'bilingual')).toBe('Balance / 余额');
  });
});
```

- [ ] **Step 2: Run the failing locale test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit -- tests/unit/appI18n.spec.ts
```

Expected:

```text
FAIL tests/unit/appI18n.spec.ts
TypeScript reports that new locale keys do not exist yet.
```

- [ ] **Step 3: Add English messages**

In `G:\AI_Trading\freqtrade-cn\frequi\src\locales\en.ts`, add these namespaces after the existing `confirm` namespace. Keep the existing namespaces unchanged.

```ts
  common: {
    abort: 'Abort',
    actions: 'Actions',
    add: 'Add',
    all: 'All',
    apply: 'Apply',
    cancel: 'Cancel',
    close: 'Close',
    confirm: 'Confirm',
    count: 'Count',
    delete: 'Delete',
    disabled: 'disabled',
    enabled: 'enabled',
    filter: 'Filter',
    hide: 'Hide',
    live: 'Live',
    loading: 'Loading...',
    long: 'Long',
    market: 'Market',
    metric: 'Metric',
    offline: 'Offline',
    ok: 'Ok',
    pair: 'Pair',
    refresh: 'Refresh',
    reset: 'Reset',
    save: 'Save',
    short: 'Short',
    show: 'Show',
    summary: 'Summary',
    total: 'Total',
    unknown: 'Unknown',
    value: 'Value',
  },
  plot: {
    configuratorTitle: 'Plot Configurator',
    configuratorDescription: 'Configure chart plot indicators and subplots',
    configName: 'Plot config name',
    showTagsInTooltips: 'Show Tags in Tooltips',
    markAreaZIndex: 'Mark Area Z-Index',
    markAreaZIndexHint: '(defaults to 1 - Candlechart is at Z=2)',
    targetPlot: 'Target Plot',
    indicatorsInThisPlot: 'Indicators in this plot',
    removeIndicator: 'Remove indicator',
    removeIndicatorTitle: 'Remove indicator from plot',
    fromTemplate: 'From template',
    fromTemplateTitle: 'Load indicator config from template',
    addIndicator: 'Add indicator',
    addIndicatorTitle: 'Add indicator to plot',
    selectIndicatorToAdd: 'Select indicator to add',
    resetToLastSavedTitle: 'Reset to last saved configuration',
    fromStrategy: 'From strategy',
    showConfigurationTitle: 'Show configuration for easy transfer to a strategy',
    saveConfigurationTitle: 'Save configuration',
    loadFromStringBelow: 'Load from string below',
    loadFromStringTitle: 'Load configuration from text box below',
    hideConfig: 'Hide',
    showConfig: 'Show',
    noStrategySelected: "No strategy selected, can't load plot config.",
    loadFromStrategyFailed: 'Failed to load Plot configuration from Strategy.',
    notAvailableInChart: 'not available in this chart',
    editName: 'plot configuration',
    selectTemplate: 'Select Template',
    remapIndicators: 'Re-map indicators',
    useTemplate: 'Use Template',
    applyTemplate: 'Apply Template',
    type: 'Type',
    color: 'Color',
    fillTo: 'Area chart - Fill to (leave empty for line chart)',
    scatterSymbolSize: 'Scatter symbol size',
  },
  chart: {
    settings: 'Settings',
    settingsHint:
      "These settings only apply to the chart view and do not affect the bot's actual configuration or behavior.",
    customExchange: 'Custom Exchange',
    currentExchange: 'Current Exchange',
    strategy: 'Strategy',
    timeframe: 'Timeframe',
    useLiveData: 'Use Live Data',
    useLiveDataTitle:
      "Use live data from the exchange. Only use if you don't have data downloaded locally.",
    startDate: 'Start Date',
    endDate: 'End Date',
    clearStartDate: 'Clear start date',
    clearEndDate: 'Clear end date',
    timerange: 'Timerange',
    useStrategyDefault: 'Use strategy default',
    selectPairsToPlot: 'Select pairs to plot',
    refreshChart: 'Refresh chart',
    multiPair: 'Multi pair',
    showChartAreas: 'Show Chart Areas',
    heikinAshi: 'Heikin Ashi',
    noPairSelected: 'No pair selected',
    notLoadedYet: 'Not loaded yet.',
    noDataAvailable: 'No data available',
    failedToLoadData: 'Failed to load data',
    historyTakesLonger: 'This is taking longer than expected ... Hold on ...',
    longEntries: 'Long entries',
    longExit: 'Long exit',
    shortEntries: 'Short entries',
    shortExits: 'Short exits',
    pairFallback: 'Pair',
    legendCandles: 'Candles',
    legendVolume: 'Volume',
    legendEntry: 'Entry',
    legendExit: 'Exit',
    legendTrades: 'Trades',
  },
  trade: {
    multiPane: 'Multi Pane',
    pairsCombined: 'Pairs combined',
    general: 'General',
    performance: 'Performance',
    balance: 'Balance',
    timeBreakdown: 'Time Breakdown',
    pairlist: 'Pairlist',
    pairLocks: 'Pair Locks',
    openTrades: 'Open Trades',
    openTradesTitle: 'Open trades',
    openTradesEmpty: 'Currently no open trades.',
    closedTrades: 'Closed Trades',
    tradeHistory: 'Trade history',
    tradeHistoryEmpty: 'No closed trades so far.',
    tradeDetail: 'Trade Detail',
    chart: 'Chart',
    startTrading: 'Start Trading',
    stopTrading: 'Stop Trading - Also stops handling open trades.',
    pauseTrading:
      'Pause (StopBuy) - Freqtrade will continue to handle open trades, but will not enter new trades or increase position sizes.',
    reloadConfigTitle:
      'Reload Config - reloads configuration including strategy, resetting all settings changed on the fly.',
    forceExitAllTitle: 'Force exit all',
    forceEnterTitle:
      'Force enter - Immediately enter a trade at an optional price. Exits are then handled according to strategy rules.',
    startTradingMode: 'Start Trading mode',
    stopBot: 'Stop Bot',
    stopBotMessage: 'Stop the bot loop from running?',
    pauseStopEntering: 'Pause - Stop Entering',
    pauseStopEnteringMessage:
      'Freqtrade will continue to handle open trades, but will not enter new trades or increase position sizes. Really stop entering?',
    reloadConfig: 'Reload Config',
    reloadConfigMessage: 'Reload configuration (including strategy)?',
    forceExitAll: 'ForceExit all',
    forceExitAllMessage: 'Really forceexit ALL trades?',
    configReloaded: 'Config reloaded successfully.',
    table: {
      id: 'ID',
      bot: 'Bot',
      pair: 'Pair',
      amount: 'Amount',
      stakeAmount: 'Stake amount',
      totalStakeAmount: 'Total stake amount',
      openRate: 'Open rate',
      currentRate: 'Current rate',
      closeRate: 'Close rate',
      currentProfitPercent: 'Current profit %',
      profitPercent: 'Profit %',
      openDate: 'Open date',
      closeDate: 'Close date',
      closeReason: 'Close Reason',
    },
    forceExitTrade: 'Force exit trade',
    deleteTrade: 'Delete trade',
    cancelOpenOrder: 'Cancel open order',
    actionCannotBeUndone: 'This action cannot be undone.',
    reallyExitTrade: 'Really exit trade',
    usingOrder: 'using a {orderType} order',
    reallyDeleteTrade: 'Really delete trade',
    reallyCancelOpenOrder: 'Really cancel open order for trade',
    actionsFor: 'Actions for',
    closeActionsMenu: 'Close Actions menu',
    forceexit: 'Forceexit',
    forceexitLimit: 'Forceexit limit',
    forceexitMarket: 'Forceexit market',
    forceexitPartial: 'Forceexit partial',
    cancelOpenOrders: 'Cancel open orders',
    increasePosition: 'Increase position',
    reload: 'Reload',
    forceEntryModalTitle: 'Force entering a trade',
    forceEntryModalDescription: 'Manually enter a new trade',
    increasePositionFor: 'Increasing position for',
    increasePositionDescription: 'Increase an existing position',
    orderDirection: 'Order direction (Long or Short)',
    priceOptional: 'Price [optional]',
    stakeAmountOptional: 'Stake-amount in {currency} [optional]',
    leverageOptional: 'Leverage to apply [optional]',
    orderType: 'OrderType',
    customEntryTagOptional: '* Custom entry tag [optional]',
    enterPosition: 'Enter Position',
    forceExitModalTitle: 'Force exiting a trade',
    forceExitModalDescription: 'Configure and confirm a forced trade exit',
    exitingTrade: 'Exiting Trade',
    currentlyOwning: 'Currently owning',
    amountOptional: 'Amount in {currency} [optional]',
    estimatedValue: 'Estimated value',
    priceOnlyLimit: 'Only available with limit orders',
    exitPosition: 'Exit Position',
    showCustomData: 'Show custom data',
    details: 'Details',
    stoploss: 'Stoploss',
    atRisk: 'At risk',
    atRiskHelp:
      'The amount at risk based on the stake amount. This is how much you would lose if the stoploss is hit.',
    currentStoplossDist: 'Current stoploss dist',
    initialStoploss: 'Initial Stoploss',
    stoplossLastUpdated: 'Stoploss last updated',
    futuresMargin: 'Futures/Margin',
    direction: 'Direction',
    fundingFees: 'Funding fees',
    interestRate: 'Interest rate',
    liquidationPrice: 'Liquidation Price',
    orders: 'Orders',
  },
  bot: {
    runningFreqtrade: 'Running Freqtrade',
    runningWith: 'Running with',
    on: 'on',
    in: 'in',
    marketsWithStrategy: 'markets, with Strategy',
    stoplossOnExchangeIs: 'Stoploss on exchange is',
    currently: 'Currently',
    forceEntry: 'force entry',
    dryRun: 'Dry-Run',
    avgProfit: 'Avg Profit',
    trades: 'Trades',
    averageDuration: 'average duration',
    bestPair: 'Best pair',
    botStartDate: 'Bot start date',
    firstTradeOpened: 'First trade opened',
    lastTradeOpened: 'Last trade opened',
    profitFactor: 'Profit factor',
    tradingVolume: 'Trading volume',
    strategyParameters: 'Strategy parameters',
    performance: 'Performance',
    entries: 'Entries',
    exits: 'Exits',
    mixTag: 'Mix Tag',
    enterTag: 'Enter tag',
    exitReason: 'Exit Reason',
    profit: 'Profit',
    profitPercent: 'Profit %',
    profitCurrency: 'Profit {currency}',
    count: 'Count',
    currency: 'Currency',
    available: 'Available',
    accountBalance: 'Account Balance',
    botBalance: 'Bot Balance',
    showingAccountBalance: 'Showing Account balance',
    showingBotBalance: 'Showing Bot balance',
    hideSmallBalances: 'Hide small balances',
    showAllBalances: 'Show all balances',
    whitelistMethods: 'Whitelist Methods',
    whitelist: 'Whitelist',
    blacklist: 'Blacklist',
    blacklistTitle: "Blacklist - Select (followed by a click on '-') to remove pairs",
    addPairToBlacklist: 'Add Pair to Blacklist',
    pairLocks: 'Pair Locks',
    until: 'Until',
    reason: 'Reason',
    deleteLock: 'Delete Lock',
    deleteLockUnsupported: 'This Freqtrade version does not support deleting locks.',
    profitsFor: 'Profits for',
    roiClosedTrades: 'ROI closed trades',
    roiAllTrades: 'ROI all trades',
    totalTradeCount: 'Total Trade count',
    botStarted: 'Bot started',
    latestTradeOpened: 'Latest Trade opened',
    winLoss: 'Win / Loss',
    winrate: 'Winrate',
    expectancyRatio: 'Expectancy (ratio)',
    avgDuration: 'Avg. Duration',
    bestPerforming: 'Best performing',
    maxDrawdown: 'Max Drawdown',
    currentDrawdown: 'Current Drawdown',
  },
  dashboard: {
    profitOverTime: 'Profit over time',
    profitOverTimeCombined: 'Profit over time combined',
    botComparison: 'Bot comparison',
    openTradesInfo:
      'Open trades of all selected bots. Click on a trade to go to the trade page for that trade/bot.',
    closedTradesInfo:
      'Closed trades for all selected bots. Click on a trade to go to the trade page for that trade/bot.',
    cumulativeProfit: 'Cumulative Profit',
    walletHistory: 'Wallet History',
    profitDistribution: 'Profit Distribution',
    tradesLog: 'Trades Log',
    openProfit: 'Open Profit',
    closedProfit: 'Closed Profit',
    winLossShort: 'W/L',
    botName: 'Bot Name',
    clickSelectAllBots: 'Click to select all bots',
    showThisBotInDashboard: 'Show this bot in Dashboard',
    toggleAllBots: 'Toggle all bots',
    clickSelectAllDryRunBots: 'Click to select all dry run bots',
    clickSelectAllLiveBots: 'Click to select all live bots',
    dry: 'Dry',
  },
```

- [ ] **Step 4: Add Simplified Chinese messages**

In `G:\AI_Trading\freqtrade-cn\frequi\src\locales\zh-CN.ts`, add the matching namespaces after the existing `confirm` namespace.

```ts
  common: {
    abort: '中止',
    actions: '操作',
    add: '添加',
    all: '全部',
    apply: '应用',
    cancel: '取消',
    close: '关闭',
    confirm: '确认',
    count: '数量',
    delete: '删除',
    disabled: '已禁用',
    enabled: '已启用',
    filter: '筛选',
    hide: '隐藏',
    live: '实盘',
    loading: '加载中...',
    long: '做多',
    market: '市价',
    metric: '指标',
    offline: '离线',
    ok: '确定',
    pair: '交易对',
    refresh: '刷新',
    reset: '重置',
    save: '保存',
    short: '做空',
    show: '显示',
    summary: '汇总',
    total: '合计',
    unknown: '未知',
    value: '值',
  },
  plot: {
    configuratorTitle: '图表绘制配置',
    configuratorDescription: '配置图表指标和子图',
    configName: '绘图配置名称',
    showTagsInTooltips: '在提示中显示标签',
    markAreaZIndex: '标记区域 Z 轴层级',
    markAreaZIndexHint: '（默认 1，K 线图位于 Z=2）',
    targetPlot: '目标图层',
    indicatorsInThisPlot: '当前图层中的指标',
    removeIndicator: '移除指标',
    removeIndicatorTitle: '从图层移除指标',
    fromTemplate: '来自模板',
    fromTemplateTitle: '从模板加载指标配置',
    addIndicator: '添加指标',
    addIndicatorTitle: '向图层添加指标',
    selectIndicatorToAdd: '选择要添加的指标',
    resetToLastSavedTitle: '重置为上次保存的配置',
    fromStrategy: '来自策略',
    showConfigurationTitle: '显示配置，便于复制到策略',
    saveConfigurationTitle: '保存配置',
    loadFromStringBelow: '从下方文本加载',
    loadFromStringTitle: '从下方文本框加载配置',
    hideConfig: '隐藏',
    showConfig: '显示',
    noStrategySelected: '未选择策略，无法加载绘图配置。',
    loadFromStrategyFailed: '从策略加载绘图配置失败。',
    notAvailableInChart: '当前图表不可用',
    editName: '绘图配置',
    selectTemplate: '选择模板',
    remapIndicators: '重新映射指标',
    useTemplate: '使用模板',
    applyTemplate: '应用模板',
    type: '类型',
    color: '颜色',
    fillTo: '面积图填充到（留空表示折线图）',
    scatterSymbolSize: '散点标记大小',
  },
  chart: {
    settings: '设置',
    settingsHint: '这些设置只作用于图表视图，不会影响机器人的实际配置或行为。',
    customExchange: '自定义交易所',
    currentExchange: '当前交易所',
    strategy: '策略',
    timeframe: '周期',
    useLiveData: '使用实时数据',
    useLiveDataTitle: '使用交易所实时数据。只有在本地没有下载数据时才建议启用。',
    startDate: '开始日期',
    endDate: '结束日期',
    clearStartDate: '清除开始日期',
    clearEndDate: '清除结束日期',
    timerange: '时间范围',
    useStrategyDefault: '使用策略默认值',
    selectPairsToPlot: '选择要绘制的交易对',
    refreshChart: '刷新图表',
    multiPair: '多交易对',
    showChartAreas: '显示图表区域',
    heikinAshi: '平均 K 线',
    noPairSelected: '未选择交易对',
    notLoadedYet: '尚未加载。',
    noDataAvailable: '暂无数据',
    failedToLoadData: '数据加载失败',
    historyTakesLonger: '加载时间比预期更长，请稍等...',
    longEntries: '做多入场',
    longExit: '做多出场',
    shortEntries: '做空入场',
    shortExits: '做空出场',
    pairFallback: '交易对',
    legendCandles: 'K 线',
    legendVolume: '成交量',
    legendEntry: '入场',
    legendExit: '出场',
    legendTrades: '交易',
  },
  trade: {
    multiPane: '多面板',
    pairsCombined: '交易对汇总',
    general: '概览',
    performance: '表现',
    balance: '余额',
    timeBreakdown: '时间拆分',
    pairlist: '交易对列表',
    pairLocks: '交易对锁定',
    openTrades: '未平仓交易',
    openTradesTitle: '未平仓交易',
    openTradesEmpty: '当前没有未平仓交易。',
    closedTrades: '已平仓交易',
    tradeHistory: '交易历史',
    tradeHistoryEmpty: '目前还没有已平仓交易。',
    tradeDetail: '交易详情',
    chart: '图表',
    startTrading: '开始交易',
    stopTrading: '停止交易，也会停止处理未平仓交易。',
    pauseTrading: '暂停入场，Freqtrade 会继续处理未平仓交易，但不会新开仓或加仓。',
    reloadConfigTitle: '重新加载配置，包括策略，并重置所有运行时修改。',
    forceExitAllTitle: '强制退出全部交易',
    forceEnterTitle: '强制入场，以可选价格立即进入交易，之后按策略规则出场。',
    startTradingMode: '启动交易模式',
    stopBot: '停止机器人',
    stopBotMessage: '停止机器人循环运行？',
    pauseStopEntering: '暂停入场',
    pauseStopEnteringMessage: 'Freqtrade 会继续处理未平仓交易，但不会新开仓或加仓。确定暂停入场？',
    reloadConfig: '重新加载配置',
    reloadConfigMessage: '重新加载配置（包括策略）？',
    forceExitAll: '强制退出全部',
    forceExitAllMessage: '确定强制退出所有交易？',
    configReloaded: '配置已成功重新加载。',
    table: {
      id: 'ID',
      bot: '机器人',
      pair: '交易对',
      amount: '数量',
      stakeAmount: '投入金额',
      totalStakeAmount: '总投入金额',
      openRate: '开仓价',
      currentRate: '当前价',
      closeRate: '平仓价',
      currentProfitPercent: '当前收益率 %',
      profitPercent: '收益率 %',
      openDate: '开仓时间',
      closeDate: '平仓时间',
      closeReason: '平仓原因',
    },
    forceExitTrade: '强制退出交易',
    deleteTrade: '删除交易',
    cancelOpenOrder: '取消未完成订单',
    actionCannotBeUndone: '此操作无法撤销。',
    reallyExitTrade: '确定退出交易',
    usingOrder: '使用 {orderType} 订单',
    reallyDeleteTrade: '确定删除交易',
    reallyCancelOpenOrder: '确定取消该交易的未完成订单',
    actionsFor: '操作对象',
    closeActionsMenu: '关闭操作菜单',
    forceexit: '强制退出',
    forceexitLimit: '限价强制退出',
    forceexitMarket: '市价强制退出',
    forceexitPartial: '部分强制退出',
    cancelOpenOrders: '取消未完成订单',
    increasePosition: '加仓',
    reload: '重新加载',
    forceEntryModalTitle: '强制进入交易',
    forceEntryModalDescription: '手动进入一笔新交易',
    increasePositionFor: '为交易加仓',
    increasePositionDescription: '增加已有仓位',
    orderDirection: '订单方向（做多或做空）',
    priceOptional: '价格 [可选]',
    stakeAmountOptional: '{currency} 投入金额 [可选]',
    leverageOptional: '应用杠杆 [可选]',
    orderType: '订单类型',
    customEntryTagOptional: '* 自定义入场标签 [可选]',
    enterPosition: '进入仓位',
    forceExitModalTitle: '强制退出交易',
    forceExitModalDescription: '配置并确认强制退出交易',
    exitingTrade: '正在退出交易',
    currentlyOwning: '当前持有',
    amountOptional: '{currency} 数量 [可选]',
    estimatedValue: '预估价值',
    priceOnlyLimit: '仅限限价单可用',
    exitPosition: '退出仓位',
    showCustomData: '显示自定义数据',
    details: '详情',
    stoploss: '止损',
    atRisk: '风险金额',
    atRiskHelp: '基于投入金额计算的风险金额，即触发止损时可能损失的金额。',
    currentStoplossDist: '当前止损距离',
    initialStoploss: '初始止损',
    stoplossLastUpdated: '止损最后更新时间',
    futuresMargin: '合约/保证金',
    direction: '方向',
    fundingFees: '资金费用',
    interestRate: '利率',
    liquidationPrice: '强平价格',
    orders: '订单',
  },
  bot: {
    runningFreqtrade: '正在运行 Freqtrade',
    runningWith: '运行参数',
    on: '在',
    in: '以',
    marketsWithStrategy: '市场，策略为',
    stoplossOnExchangeIs: '交易所止损状态',
    currently: '当前状态',
    forceEntry: '强制入场',
    dryRun: '模拟交易',
    avgProfit: '平均收益',
    trades: '交易',
    averageDuration: '平均持续时间',
    bestPair: '最佳交易对',
    botStartDate: '机器人启动时间',
    firstTradeOpened: '第一笔交易开仓',
    lastTradeOpened: '最近一笔交易开仓',
    profitFactor: '收益因子',
    tradingVolume: '交易量',
    strategyParameters: '策略参数',
    performance: '表现',
    entries: '入场',
    exits: '出场',
    mixTag: '混合标签',
    enterTag: '入场标签',
    exitReason: '出场原因',
    profit: '收益',
    profitPercent: '收益率 %',
    profitCurrency: '收益 {currency}',
    count: '数量',
    currency: '币种',
    available: '可用',
    accountBalance: '账户余额',
    botBalance: '机器人余额',
    showingAccountBalance: '正在显示账户余额',
    showingBotBalance: '正在显示机器人余额',
    hideSmallBalances: '隐藏小额余额',
    showAllBalances: '显示全部余额',
    whitelistMethods: '白名单方法',
    whitelist: '白名单',
    blacklist: '黑名单',
    blacklistTitle: "黑名单 - 选择交易对后点击 '-' 可移除",
    addPairToBlacklist: '添加交易对到黑名单',
    pairLocks: '交易对锁定',
    until: '直到',
    reason: '原因',
    deleteLock: '删除锁定',
    deleteLockUnsupported: '当前 Freqtrade 版本不支持删除锁定。',
    profitsFor: '收益范围',
    roiClosedTrades: '已平仓交易 ROI',
    roiAllTrades: '全部交易 ROI',
    totalTradeCount: '总交易数',
    botStarted: '机器人启动',
    latestTradeOpened: '最近交易开仓',
    winLoss: '胜 / 负',
    winrate: '胜率',
    expectancyRatio: '期望值（比率）',
    avgDuration: '平均持续时间',
    bestPerforming: '最佳表现',
    maxDrawdown: '最大回撤',
    currentDrawdown: '当前回撤',
  },
  dashboard: {
    profitOverTime: '收益时间走势',
    profitOverTimeCombined: '汇总收益时间走势',
    botComparison: '机器人对比',
    openTradesInfo: '所有选中机器人的未平仓交易。点击交易可跳转到对应机器人/交易页面。',
    closedTradesInfo: '所有选中机器人的已平仓交易。点击交易可跳转到对应机器人/交易页面。',
    cumulativeProfit: '累计收益',
    walletHistory: '钱包历史',
    profitDistribution: '收益分布',
    tradesLog: '交易日志',
    openProfit: '未平仓收益',
    closedProfit: '已平仓收益',
    winLossShort: '胜/负',
    botName: '机器人名称',
    clickSelectAllBots: '点击选择全部机器人',
    showThisBotInDashboard: '在仪表盘显示此机器人',
    toggleAllBots: '切换全部机器人',
    clickSelectAllDryRunBots: '点击选择全部模拟交易机器人',
    clickSelectAllLiveBots: '点击选择全部实盘机器人',
    dry: '模拟',
  },
```

- [ ] **Step 5: Run locale unit tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit -- tests/unit/appI18n.spec.ts
```

Expected:

```text
PASS tests/unit/appI18n.spec.ts
```

- [ ] **Step 6: Commit locale key expansion**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add src/locales/en.ts src/locales/zh-CN.ts tests/unit/appI18n.spec.ts
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "feat: add deep bilingual locale keys"
```

Expected:

```text
[cn/i18n <sha>] feat: add deep bilingual locale keys
```

---

### Task 2: Localize Plot Configurator and Chart Controls

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\CandleChartContainer.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\SingleCandleChartContainer.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\CandleChart.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\PlotConfigurator.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\PlotFromTemplate.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\PlotIndicator.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\PlotIndicatorSelect.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\charts\PlotConfigSelect.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TimeRangeSelect.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TimeframeSelect.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\ExchangeSelect.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\views\ChartsView.vue`

- [ ] **Step 1: Add `useAppI18n` to chart containers**

In `CandleChartContainer.vue`, add near the existing stores:

```ts
const { t } = useAppI18n();
```

Replace the toolbar labels and modal text with:

```vue
placeholder="Select pairs to plot"
```

becomes:

```vue
:placeholder="t('chart.selectPairsToPlot')"
```

Replace:

```vue
title="Refresh chart"
```

with:

```vue
:title="t('chart.refreshChart')"
```

Replace checkbox body text:

```vue
<span class="text-nowrap">Multi pair</span>
<span class="text-nowrap">Show Chart Areas</span>
<span class="text-nowrap">Heikin Ashi</span>
```

with:

```vue
<span class="text-nowrap">{{ t('chart.multiPair') }}</span>
<span class="text-nowrap">{{ t('chart.showChartAreas') }}</span>
<span class="text-nowrap">{{ t('chart.heikinAshi') }}</span>
```

Replace the configurator button and modal props:

```vue
:title="t('plot.configuratorTitle')"
:title="t('plot.configuratorTitle')"
:description="t('plot.configuratorDescription')"
```

The modal block should become:

```vue
<DraggableModal
  v-model:open="showPlotConfigModal"
  :title="t('plot.configuratorTitle')"
  class="max-w-xl"
  :description="t('plot.configuratorDescription')"
  :overlay="false"
  :modal="false"
  :dismissible="false"
>
```

- [ ] **Step 2: Localize dataset state text in `SingleCandleChartContainer.vue`**

Add:

```ts
const { t } = useAppI18n();
```

Replace `noDatasetText` with:

```ts
const noDatasetText = computed((): string => {
  const status = props.historicView
    ? botStore.activeBot.historyStatus
    : botStore.activeBot.candleDataStatus;

  switch (status) {
    case LoadingStatus.not_loaded:
      return t('chart.notLoadedYet');
    case LoadingStatus.loading:
      return t('common.loading');
    case LoadingStatus.success:
      return t('chart.noDataAvailable');
    case LoadingStatus.error:
      return t('chart.failedToLoadData');
    default:
      return t('common.unknown');
  }
});
```

Replace visible status labels:

```vue
:title="t('chart.longEntries')"
>{{ t('chart.longEntries') }}: {{ dataset.enter_long_signals || dataset.buy_signals }}</small>

:title="t('chart.longExit')"
>{{ t('chart.longExit') }}: {{ dataset.exit_long_signals || dataset.sell_signals }}</small>

>{{ t('chart.shortEntries') }}: {{ dataset.enter_short_signals }}</small>
>{{ t('chart.shortExits') }}: {{ dataset.exit_short_signals }}</small>

{{ pair || t('chart.pairFallback') }}

{{ t('chart.historyTakesLonger') }}
```

- [ ] **Step 3: Localize ECharts fixed legend labels in `CandleChart.vue`**

Add after props:

```ts
const settingsStore = useSettingsStore();
const { t } = useAppI18n();
```

Replace fixed series and legend names:

```ts
const candlesName = t('chart.legendCandles');
const volumeName = t('chart.legendVolume');
const entryName = t('chart.legendEntry');
const exitName = t('chart.legendExit');
const tradesName = t('chart.legendTrades');
```

Use those values in `updateChart()`:

```ts
name: candlesName,
name: volumeName,
name: entryName,
name: exitName,
const nameTrades = tradesName;
```

Use translated tooltip prefixes:

```ts
tooltipPrefix: t('chart.longEntries'),
tooltipPrefix: t('chart.longExit'),
tooltipPrefix: t('chart.shortEntries'),
tooltipPrefix: t('chart.shortExits'),
```

Replace initial legend data with:

```ts
data: [candlesName, volumeName, entryName, exitName],
```

Update the watcher so chart labels refresh when language mode changes:

```ts
watch([() => props.useUTC, () => props.theme, () => props.plotConfig, () => settingsStore.localeMode], () =>
  initializeChartOptions(),
);
```

- [ ] **Step 4: Localize `PlotConfigurator.vue`**

Add:

```ts
const { t } = useAppI18n();
```

Replace `usedColumns` label construction:

```ts
label: !props.columns.includes(col) ? `${col} <-- ${t('plot.notAvailableInChart')}` : col,
```

Replace alert strings:

```ts
showAlert(t('plot.noStrategySelected'));
showAlert(t('plot.loadFromStrategyFailed'));
```

Replace template labels and titles:

```vue
<UFormField :label="t('plot.configName')" class="text-md">
<BaseCheckbox v-model="showTagsInTooltips" class="mb-1">
  {{ t('plot.showTagsInTooltips') }}
</BaseCheckbox>
<label>{{ t('plot.markAreaZIndex') }} <br /><small>{{ t('plot.markAreaZIndexHint') }}</small></label>
<UFormField :label="t('plot.targetPlot')" class="text-md">
:editable-name="t('plot.editName')"
<UFormField :label="t('plot.indicatorsInThisPlot')" class="text-md">
:title="t('plot.removeIndicatorTitle')"
:label="t('plot.removeIndicator')"
:title="t('plot.fromTemplateTitle')"
:label="t('plot.fromTemplate')"
:title="t('plot.addIndicatorTitle')"
:label="t('plot.addIndicator')"
:label="t('plot.selectIndicatorToAdd')"
:title="t('plot.resetToLastSavedTitle')"
:label="t('common.reset')"
:label="t('plot.fromStrategy')"
:title="t('plot.showConfigurationTitle')"
:label="showConfig ? t('plot.hideConfig') : t('plot.showConfig')"
:title="t('plot.saveConfigurationTitle')"
:label="t('common.save')"
:title="t('plot.loadFromStringTitle')"
{{ t('plot.loadFromStringBelow') }}
```

- [ ] **Step 5: Localize plot child components**

In `PlotFromTemplate.vue`, add:

```ts
const { t } = useAppI18n();
```

Replace:

```vue
<UFormField v-if="!showIndicatorMapping" :label="t('plot.selectTemplate')" class="text-md">
<h5 class="mt-1 text-center text-md mb-1">{{ t('plot.remapIndicators') }}</h5>
<UButton :title="t('common.abort')" ... />
:title="t('plot.useTemplate')"
:label="t('plot.useTemplate')"
:title="t('plot.applyTemplate')"
:label="t('plot.applyTemplate')"
```

In `PlotIndicator.vue`, add:

```ts
const { t } = useAppI18n();
```

Replace:

```vue
<UFormField :label="t('plot.type')" class="w-full">
<UFormField :label="t('plot.color')" class="w-full">
:label="t('plot.fillTo')"
<UFormField :label="t('plot.scatterSymbolSize')" class="w-full" v-if="graphType === ChartType.scatter">
```

In `PlotIndicatorSelect.vue`, keep the `label` prop for caller-specific labels, but localize abort:

```ts
const { t } = useAppI18n();
```

```vue
<UButton :title="t('common.abort')" class="ms-1 mt-auto" color="neutral" icon="mdi:close" @click="abort" />
```

In `PlotConfigSelect.vue`, replace both hardcoded editable-name props:

```vue
:editable-name="editableName || t('plot.editName')"
```

Add `const { t } = useAppI18n();` in script setup.

- [ ] **Step 6: Localize chart settings view and selectors**

In `ChartsView.vue`, add:

```ts
const { t } = useAppI18n();
```

Replace visible chart settings text:

```vue
<span class="text-xl font-bold">{{ t('chart.settings') }}</span>
<InfoBox :hint="t('chart.settingsHint')" />
<BaseCheckbox v-model="exchange.customExchange">{{ t('chart.customExchange') }}</BaseCheckbox>
{{ t('chart.currentExchange') }}:
<span>{{ t('chart.strategy') }}</span>
:title="t('chart.useLiveDataTitle')"
{{ t('chart.useLiveData') }}
<span>{{ t('chart.timeframe') }}</span>
```

In `TimeRangeSelect.vue`, add `const { t } = useAppI18n();` and replace:

```vue
<UFormField :label="t('chart.startDate')">
:title="t('chart.clearStartDate')"
<UFormField :label="t('chart.endDate')">
:title="t('chart.clearEndDate')"
{{ t('chart.timerange') }}: <b>{{ timeRange }}</b>
```

In `TimeframeSelect.vue`, add `const { t } = useAppI18n();` and replace the placeholder-only option with a computed list:

```ts
const availableTimeframesBase = computed(() => [
  { value: null, label: t('chart.useStrategyDefault') },
  { value: '1m', label: '1m' },
  { value: '3m', label: '3m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '30m', label: '30m' },
  { value: '1h', label: '1h' },
  { value: '2h', label: '2h' },
  { value: '4h', label: '4h' },
  { value: '6h', label: '6h' },
  { value: '8h', label: '8h' },
  { value: '12h', label: '12h' },
  { value: '1d', label: '1d' },
  { value: '3d', label: '3d' },
  { value: '1w', label: '1w' },
  { value: '2w', label: '2w' },
  { value: '1M', label: '1M' },
  { value: '1y', label: '1y' },
]);
```

Update `availableTimeframes` to use `.value`:

```ts
const availableTimeframes = computed(() => {
  if (!props.belowTimeframe) {
    return availableTimeframesBase.value;
  }
  const idx = availableTimeframesBase.value.findIndex((v) => v.value === props.belowTimeframe);
  return [...availableTimeframesBase.value].splice(0, idx);
});
```

And:

```vue
:placeholder="t('chart.useStrategyDefault')"
```

In `ExchangeSelect.vue`, add `const { t } = useAppI18n();` and replace group labels:

```ts
{ label: t('common.enabled'), type: 'label' },
{ label: t('common.disabled'), type: 'label' },
```

Use `enabled/disabled` here because these groups represent supported/unsupported exchange modes in a user-facing selector. If this wording is considered less precise during review, add explicit keys `chart.supported` and `chart.unsupported`.

- [ ] **Step 7: Run focused tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit -- tests/unit/appI18n.spec.ts
pnpm run typecheck
```

Expected:

```text
PASS tests/unit/appI18n.spec.ts
vue-tsc --build --noEmit
```

- [ ] **Step 8: Commit chart and Plot Configurator migration**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add src/components/charts src/components/ftbot/TimeRangeSelect.vue src/components/ftbot/TimeframeSelect.vue src/components/ftbot/ExchangeSelect.vue src/views/ChartsView.vue
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "feat: localize chart and plot configurator"
```

Expected:

```text
[cn/i18n <sha>] feat: localize chart and plot configurator
```

---

### Task 3: Localize Trading Panel Shell, Controls, Lists, and Trade Action Modals

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\views\TradingView.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotControls.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TradeList.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TradeActions.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TradeActionsPopover.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\ForceEntryForm.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\ForceExitForm.vue`

- [ ] **Step 1: Localize trading page panel headers and tabs**

In `TradingView.vue`, add:

```ts
const { t } = useAppI18n();
```

Replace `tradingTabItems` labels:

```ts
label: showText ? t('trade.pairsCombined') : undefined,
label: showText ? t('trade.general') : undefined,
label: showText ? t('trade.performance') : undefined,
label: showText ? t('trade.balance') : undefined,
label: showText ? t('trade.timeBreakdown') : undefined,
label: showText ? t('trade.pairlist') : undefined,
label: showText ? t('trade.pairLocks') : undefined,
```

Replace `DraggableContainer` headers and `TradeList` props:

```vue
<DraggableContainer :header="t('trade.multiPane')">
<DraggableContainer :header="t('trade.openTrades')">
  <TradeList
    class="open-trades"
    :trades="botStore.activeBot.openTrades"
    :title="t('trade.openTradesTitle')"
    :active-trades="true"
    :empty-text="t('trade.openTradesEmpty')"
  />
</DraggableContainer>
<DraggableContainer :header="t('trade.closedTrades')">
  <TradeList
    class="trade-history"
    :trades="botStore.activeBot.closedTrades"
    :title="t('trade.tradeHistory')"
    :show-filter="true"
    :empty-text="t('trade.tradeHistoryEmpty')"
  />
</DraggableContainer>
<DraggableContainer :header="t('trade.tradeDetail')">
<DraggableContainer :header="t('trade.chart')">
```

- [ ] **Step 2: Localize bot control confirms and button titles**

In `BotControls.vue`, add:

```ts
const { t } = useAppI18n();
```

Replace confirm copy:

```ts
title: t('trade.stopBot'),
message: t('trade.stopBotMessage'),
title: t('trade.pauseStopEntering'),
message: t('trade.pauseStopEnteringMessage'),
title: t('trade.reloadConfig'),
message: t('trade.reloadConfigMessage'),
title: t('trade.forceExitAll'),
message: t('trade.forceExitAllMessage'),
```

Replace button titles:

```vue
:title="t('trade.startTrading')"
:title="t('trade.stopTrading')"
:title="t('trade.pauseTrading')"
:title="t('trade.reloadConfigTitle')"
:title="t('trade.forceExitAllTitle')"
:title="t('trade.forceEnterTitle')"
:title="t('trade.startTradingMode')"
```

- [ ] **Step 3: Localize trade list table and confirmations**

In `TradeList.vue`, add:

```ts
const { t } = useAppI18n();
```

Replace `tableFields` with a computed so headers react to language changes:

```ts
const tableFields = computed(() => {
  const fields = [
    { field: 'trade_id', header: t('trade.table.id') },
    { field: 'pair', header: t('trade.table.pair') },
    { field: 'amount', header: t('trade.table.amount') },
    props.activeTrades
      ? { field: 'stake_amount', header: t('trade.table.stakeAmount') }
      : { field: 'max_stake_amount', header: t('trade.table.totalStakeAmount') },
    { field: 'open_rate', header: t('trade.table.openRate') },
    {
      field: props.activeTrades ? 'current_rate' : 'close_rate',
      header: props.activeTrades ? t('trade.table.currentRate') : t('trade.table.closeRate'),
    },
    {
      field: 'profit',
      header: props.activeTrades
        ? t('trade.table.currentProfitPercent')
        : t('trade.table.profitPercent'),
    },
    { field: 'open_timestamp', header: t('trade.table.openDate') },
    ...(props.activeTrades
      ? [{ field: 'actions', header: '' }]
      : [
          { field: 'close_timestamp', header: t('trade.table.closeDate') },
          { field: 'exit_reason', header: t('trade.table.closeReason') },
        ]),
  ];

  if (props.multiBotView) {
    fields.unshift({ field: 'botName', header: t('trade.table.bot') });
  }

  return fields;
});
```

Update `tableColumns` to use `tableFields.value`.

Replace confirmation copy:

```ts
const message = ordertype
  ? `${t('trade.reallyExitTrade')} ${item.trade_id} (${t('common.pair')} ${item.pair}) ${t('trade.usingOrder').replace('{orderType}', ordertype)}?`
  : `${t('trade.reallyExitTrade')} ${item.trade_id} (${t('common.pair')} ${item.pair})?`;

title: t('trade.forceExitTrade'),
description: t('trade.actionCannotBeUndone'),
confirmText: t('common.confirm'),

title: t('trade.deleteTrade'),
message: `${t('trade.reallyDeleteTrade')} ${item.trade_id} (${t('common.pair')} ${item.pair})?`,

title: t('trade.cancelOpenOrder'),
message: `${t('trade.reallyCancelOpenOrder')} ${item.trade_id} (${t('common.pair')} ${item.pair})?`,
```

Replace filter placeholder:

```vue
<UInput v-model="filterText" :placeholder="t('common.filter')" class="w-64" />
```

- [ ] **Step 4: Localize trade actions and popover**

In `TradeActions.vue`, add:

```ts
const { t } = useAppI18n();
```

Replace every action label/title pair:

```vue
:title="t('trade.forceexit')"
:label="t('trade.forceexit')"
:title="t('trade.forceexitLimit')"
:label="t('trade.forceexitLimit')"
:title="t('trade.forceexitMarket')"
:label="t('trade.forceexitMarket')"
:title="t('trade.forceexitPartial')"
:label="t('trade.forceexitPartial')"
:title="t('trade.cancelOpenOrders')"
:label="t('trade.cancelOpenOrders')"
:title="t('trade.increasePosition')"
:label="t('trade.increasePosition')"
:title="t('trade.reload')"
:label="t('trade.reload')"
:title="t('trade.deleteTrade')"
:label="t('trade.deleteTrade')"
```

In `TradeActionsPopover.vue`, add:

```ts
const { t } = useAppI18n();
```

Replace:

```vue
:title="`${t('trade.actionsFor')} ${trade.pair}`"
:title="t('common.actions')"
:label="t('trade.closeActionsMenu')"
```

- [ ] **Step 5: Localize force entry and force exit forms**

In `ForceEntryForm.vue`, add:

```ts
const { t } = useAppI18n();
```

Make option lists computed:

```ts
const orderTypeOptions = computed(() => [
  { value: 'market', text: t('common.market') },
  { value: 'limit', text: 'Limit' },
]);

const orderSideOptions = computed(() => [
  { value: 'long', text: t('common.long') },
  { value: 'short', text: t('common.short') },
]);
```

Replace modal props and labels:

```vue
:title="positionIncrease ? `${t('trade.increasePositionFor')} ${pair}` : t('trade.forceEntryModalTitle')"
:description="positionIncrease ? t('trade.increasePositionDescription') : t('trade.forceEntryModalDescription')"
<UFormField :label="t('trade.orderDirection')">
<UFormField :label="t('common.pair')" required>
<UFormField :label="t('trade.priceOptional')">
<UFormField :label="t('trade.stakeAmountOptional').replace('{currency}', botStore.activeBot.stakeCurrency)">
<UFormField :label="t('trade.leverageOptional')">
<UFormField :label="t('trade.orderType')">
<UFormField :label="t('trade.customEntryTagOptional')">
{{ t('common.cancel') }}
{{ t('trade.enterPosition') }}
```

In `ForceExitForm.vue`, add:

```ts
const { t } = useAppI18n();
```

Update `amountInBase`:

```ts
const amountInBase = computed<string>(() => {
  return amountDebounced.value && props.trade.current_rate
    ? `~${formatPriceCurrency(amountDebounced.value * props.trade.current_rate, props.trade.quote_currency || '', props.stakeCurrencyDecimals)} (${t('trade.estimatedValue')}) `
    : '';
});
```

Make options computed:

```ts
const orderTypeOptions = computed(() => [
  { value: 'market', text: t('common.market') },
  { value: 'limit', text: 'Limit' },
]);
```

Replace template text:

```vue
<UModal :title="t('trade.forceExitModalTitle')" :description="t('trade.forceExitModalDescription')">
{{ t('trade.exitingTrade') }} #{{ trade.trade_id }} {{ trade.pair }}.
{{ t('trade.currentlyOwning') }} {{ trade.amount }} {{ trade.base_currency }}
:label="t('trade.amountOptional').replace('{currency}', trade.base_currency)"
:description="amountInBase"
<UFormField :label="t('trade.priceOptional')" v-if="..." :description="t('trade.priceOnlyLimit')">
<UFormField :label="t('trade.orderType')" required>
{{ t('common.cancel') }}
{{ t('trade.exitPosition') }}
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run typecheck
pnpm run test:e2e-chromium -- e2e/trade.spec.ts
```

Expected:

```text
vue-tsc --build --noEmit
trade.spec.ts passes after selector updates in Task 6.
```

If `trade.spec.ts` still uses exact English selectors, continue to Task 6 before treating this as a failure.

- [ ] **Step 7: Commit trading controls migration**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add src/views/TradingView.vue src/components/ftbot/BotControls.vue src/components/ftbot/TradeList.vue src/components/ftbot/TradeActions.vue src/components/ftbot/TradeActionsPopover.vue src/components/ftbot/ForceEntryForm.vue src/components/ftbot/ForceExitForm.vue
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "feat: localize trading controls"
```

Expected:

```text
[cn/i18n <sha>] feat: localize trading controls
```

---

### Task 4: Localize Trading Information Widgets

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotStatus.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotPerformance.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotBalance.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotProfit.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\PairSummary.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\PairListLive.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\PairLockList.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\PeriodBreakdown.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\TradeDetail.vue`

- [ ] **Step 1: Localize `BotStatus.vue` high-visibility paragraphs**

Add:

```ts
const { t } = useAppI18n();
```

Replace headings and labels in template using text interpolation:

```vue
{{ t('bot.runningFreqtrade') }} <strong>{{ botStore.activeBot.version }}</strong>
{{ t('bot.runningWith') }}
{{ t('bot.on') }}
{{ t('bot.in') }}
{{ t('bot.marketsWithStrategy') }} <strong>{{ botStore.activeBot.botState.strategy }}</strong>.
{{ t('bot.stoplossOnExchangeIs') }}
<strong>{{ botStore.activeBot.botState.stoploss_on_exchange ? t('common.enabled') : t('common.disabled') }}</strong>.
{{ t('bot.currently') }} <strong>{{ botStore.activeBot.botState.state }}</strong>,
<strong>{{ t('bot.forceEntry') }}: {{ botStore.activeBot.botState.force_entry_enable }}</strong>
<strong>{{ botStore.activeBot.botState.dry_run ? t('bot.dryRun') : t('common.live') }}</strong>
{{ t('bot.avgProfit') }}
{{ botStore.activeBot.profit.trade_count }} {{ t('bot.trades') }}
{{ t('bot.averageDuration') }}
{{ t('bot.bestPair') }}:
{{ t('bot.botStartDate') }}:
{{ t('bot.firstTradeOpened') }}:
{{ t('bot.lastTradeOpened') }}:
{{ t('bot.profitFactor') }}:
{{ t('bot.tradingVolume') }}:
<BaseCollapsible v-if="botStore.activeBot.strategy?.params" :title="t('bot.strategyParameters')">
```

- [ ] **Step 2: Localize `BotPerformance.vue`**

Add:

```ts
const { t } = useAppI18n();
```

Replace `performanceTable` with translated computed headers:

```ts
const initialCol = {
  [PerformanceOptions.performance]: { key: 'pair', label: t('common.pair') },
  [PerformanceOptions.entryStats]: {
    key: 'enter_tag',
    label: t('bot.enterTag'),
    formatter: (v: unknown) => formatTextLen(v as string, textLength),
  },
  [PerformanceOptions.exitStats]: {
    key: 'exit_reason',
    label: t('bot.exitReason'),
    formatter: (v: unknown) => formatTextLen(v as string, textLength),
  },
  [PerformanceOptions.mixTagStats]: {
    key: 'mix_tag',
    label: t('bot.mixTag'),
    formatter: (v: unknown) => formatTextLen(v as string, textLength),
  },
};
```

Replace table columns:

```ts
{ key: 'profit', label: t('bot.profitPercent') },
{
  key: 'profit_abs',
  label: t('bot.profitCurrency').replace('{currency}', botStore.activeBot.botState?.stake_currency ?? ''),
  formatter: (v: unknown) => formatPrice(v as number, 5),
},
{ key: 'count', label: t('common.count') },
```

Make `options` computed:

```ts
const options = computed(() => [
  { value: PerformanceOptions.performance, text: t('bot.performance') },
  { value: PerformanceOptions.entryStats, text: t('bot.entries') },
  { value: PerformanceOptions.exitStats, text: t('bot.exits') },
  { value: PerformanceOptions.mixTagStats, text: t('bot.mixTag') },
]);
```

Replace heading:

```vue
<h3 class="me-auto text-2xl inline">{{ t('bot.performance') }}</h3>
```

- [ ] **Step 3: Localize `BotBalance.vue`**

Add:

```ts
const { t } = useAppI18n();
```

Replace table headers:

```ts
{ field: 'currency', header: t('bot.currency') },
{
  field: showBotOnly.value && canUseBotBalance.value ? 'bot_owned' : 'free',
  header: t('bot.available'),
  asCurrency: true,
},
{
  field: showBotOnly.value && canUseBotBalance.value ? 'est_stake_bot' : 'est_stake',
  header: `${t('bot.in')} ${botStore.activeBot.balance.stake}`,
  asCurrency: true,
},
```

Replace footer and template text:

```ts
footer: index === 0 ? t('common.total') : ...
title: `${t('bot.currently')} ${formatCurrency(botStore.activeBot.balance.starting_capital)} ${botStore.activeBot.balance.stake}`
```

```vue
<label class="text-xl ms-1 me-auto mb-0">
  {{ showBotOnly ? t('bot.botBalance') : t('bot.accountBalance') }}
</label>
:tooltip="!showBotOnly ? t('bot.showingAccountBalance') : t('bot.showingBotBalance')"
:tooltip="!hideSmallBalances ? t('bot.hideSmallBalances') : t('bot.showAllBalances')"
```

- [ ] **Step 4: Localize pair lists, locks, breakdown, and profit table**

In `PairSummary.vue`, add:

```ts
const { t } = useAppI18n();
```

Replace:

```ts
profitString = `${t('trade.table.currentProfitPercent')}: ${formatPercent(profit)}`;
profitString += `\n${t('trade.table.openDate')}: ${timestampms(trade.open_timestamp)}`;
```

Replace filter placeholder:

```vue
:placeholder="t('common.filter')"
```

In `PairListLive.vue`, add `const { t } = useAppI18n();` and replace headings/labels:

```vue
<h3 class="text-xl">{{ t('bot.whitelistMethods') }}</h3>
:title="`${botStore.activeBot.whitelist.length} pairs`"
{{ t('bot.whitelist') }}
<p v-else>{{ t('chart.noDataAvailable') }}</p>
:title="t('bot.blacklistTitle')"
{{ t('bot.blacklist') }}
<h4 class="font-bold mb-2">{{ t('bot.addPairToBlacklist') }}</h4>
<UFormField :label="t('common.pair')" class="space-x-2" required>
<UButton id="blacklist-submit" class="ms-auto mb-2" type="submit">{{ t('common.add') }}</UButton>
:title="t('common.delete')"
```

In `PairLockList.vue`, add `const { t } = useAppI18n();`, make columns computed, and replace:

```ts
const columns = computed<TableColumn<Lock>[]>(() => [
  { accessorKey: 'pair', header: t('common.pair') },
  { accessorKey: 'lock_end_timestamp', header: t('bot.until') },
  { accessorKey: 'reason', header: t('bot.reason') },
  { id: 'actions', header: t('common.actions') },
]);
showAlert(t('bot.deleteLockUnsupported'));
```

```vue
<label class="me-auto text-xl">{{ t('bot.pairLocks') }}</label>
:title="t('bot.deleteLock')"
```

In `PeriodBreakdown.vue`, add `const { t } = useAppI18n();`, convert option arrays to computed values, and replace headings/table headers:

```ts
const periodicBreakdownSelections = computed(() => {
  const vals = [{ value: TimeSummaryOptions.daily, text: 'Days' }];
  if (hasWeekly.value) {
    vals.push({ value: TimeSummaryOptions.weekly, text: 'Weeks' });
    vals.push({ value: TimeSummaryOptions.monthly, text: 'Months' });
  }
  return vals;
});
```

If Chinese display for `Days/Weeks/Months` is required in this pass, add explicit keys `bot.days`, `bot.weeks`, `bot.months` in Task 1 and use them here. Otherwise keep period enum labels as-is for this task and localize headings:

```vue
<h3 class="me-auto inline text-xl">{{ hasWeekly ? 'Period' : 'Daily' }} {{ t('trade.timeBreakdown') }}</h3>
```

In `BotProfit.vue`, add `const { t } = useAppI18n();` and replace `metric` strings:

```ts
metric: t('bot.roiClosedTrades')
metric: t('bot.roiAllTrades')
metric: t('bot.totalTradeCount')
metric: t('bot.botStarted')
metric: t('bot.firstTradeOpened')
metric: t('bot.latestTradeOpened')
metric: t('bot.winLoss')
metric: t('bot.winrate')
metric: t('bot.expectancyRatio')
metric: 'CAGR'
metric: 'Calmar'
metric: 'Sharpe'
metric: 'Sortino'
metric: 'SQN'
metric: t('bot.avgDuration')
metric: t('bot.bestPerforming')
metric: t('bot.tradingVolume')
metric: t('bot.profitFactor')
metric: t('bot.maxDrawdown')
metric: t('bot.currentDrawdown')
```

Keep financial metric acronyms such as `CAGR`, `SQN`, `Sharpe`, and `Sortino` unchanged.

- [ ] **Step 5: Localize `TradeDetail.vue` labels**

Add:

```ts
const { t } = useAppI18n();
```

Replace FreqUI-owned section headings, button labels, and `ValuePair` descriptions:

```vue
<h5 class="text-xl font-semibold w-full block mb-1">{{ t('trade.general') }}</h5>
:label="t('trade.showCustomData')"
<ValuePair :description="t('trade.table.id')">
<ValuePair :description="t('common.pair')">
<ValuePair :description="t('trade.table.openDate')">
<ValuePair v-if="trade.enter_tag" :description="t('bot.enterTag')">
<ValuePair v-if="trade.is_open" description="Stake">
<ValuePair v-if="!trade.is_open" description="Total Stake">
<ValuePair :description="t('trade.table.amount')">
<ValuePair :description="t('trade.table.openRate')">
<ValuePair v-if="trade.is_open && trade.current_rate" :description="t('trade.table.currentRate')">
<ValuePair v-if="!trade.is_open && trade.close_rate" :description="t('trade.table.closeRate')">
<ValuePair v-if="trade.close_timestamp" :description="t('trade.table.closeDate')">
<ValuePair v-if="trade.is_open && trade.total_profit_abs" description="Total Profit">
<BaseCollapsible :title="t('trade.details')" class="px-2 pb-2">
<h5 class="text-xl font-semibold border-b pb-1 w-full block mb-1">{{ t('trade.stoploss') }}</h5>
<ValuePair :description="t('trade.atRisk')" :help="t('trade.atRiskHelp')">
<ValuePair :description="t('trade.currentStoplossDist')">
<ValuePair :description="t('trade.initialStoploss')">
<ValuePair :description="t('trade.stoplossLastUpdated')">
<h5 class="text-xl font-semibold border-b pb-1 w-full block mb-1">{{ t('trade.futuresMargin') }}</h5>
<ValuePair :description="t('trade.direction')">
<ValuePair :description="t('trade.fundingFees')">
<ValuePair :description="t('trade.interestRate')">
<ValuePair :description="t('trade.liquidationPrice')">
:title="`${t('trade.orders')} ${trade.orders.length > 1 ? `[${trade.orders.length}]` : ''}`"
```

Keep actual order side values from the API (`buy`, `sell`, `long`, `short`) unchanged inside order details unless a separate data-normalization decision is made later.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run typecheck
pnpm run test:unit -- tests/unit/appI18n.spec.ts
```

Expected:

```text
vue-tsc --build --noEmit
PASS tests/unit/appI18n.spec.ts
```

- [ ] **Step 7: Commit information widget migration**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add src/components/ftbot/BotStatus.vue src/components/ftbot/BotPerformance.vue src/components/ftbot/BotBalance.vue src/components/ftbot/BotProfit.vue src/components/ftbot/PairSummary.vue src/components/ftbot/PairListLive.vue src/components/ftbot/PairLockList.vue src/components/ftbot/PeriodBreakdown.vue src/components/ftbot/TradeDetail.vue
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "feat: localize trading information widgets"
```

Expected:

```text
[cn/i18n <sha>] feat: localize trading information widgets
```

---

### Task 5: Localize Dashboard View and Bot Comparison Table

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\views\DashboardView.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\ftbot\BotComparisonList.vue`

- [ ] **Step 1: Localize dashboard container headers**

In `DashboardView.vue`, add:

```ts
const { t } = useAppI18n();
```

Replace headers and info text:

```vue
<DraggableContainer
  :header="botStore.botCount > 1 ? t('dashboard.profitOverTimeCombined') : t('dashboard.profitOverTime')"
>
<DraggableContainer :header="t('dashboard.botComparison')">
<DraggableContainer :header="t('trade.openTrades')" :info-text="t('dashboard.openTradesInfo')">
<DraggableContainer :header="t('dashboard.cumulativeProfit')">
<DraggableContainer :header="t('dashboard.walletHistory')">
<DraggableContainer :header="t('trade.closedTrades')" :info-text="t('dashboard.closedTradesInfo')">
<DraggableContainer :header="t('dashboard.profitDistribution')">
<DraggableContainer :header="t('dashboard.tradesLog')">
```

- [ ] **Step 2: Localize bot comparison table headers and badges**

In `BotComparisonList.vue`, add:

```ts
const { t } = useAppI18n();
```

Update summary value:

```ts
botName: t('common.summary'),
```

Convert columns to computed:

```ts
const columns = computed<TableColumn<ComparisonTableItems>[]>(() => [
  { accessorKey: 'botName' },
  { accessorKey: 'trades', header: t('bot.trades') },
  { id: 'profitOpen', header: t('dashboard.openProfit') },
  { id: 'profitClosed', header: t('dashboard.closedProfit') },
  { accessorKey: 'balance', header: t('bot.balance') },
  { id: 'winVsLoss', header: t('dashboard.winLossShort') },
]);
```

Replace template labels/titles:

```vue
<b>{{ t('dashboard.botName') }}</b>
:title="t('dashboard.clickSelectAllBots')"
{{ t('common.all') }}
:title="t('dashboard.showThisBotInDashboard')"
:title="t('dashboard.toggleAllBots')"
:title="t('dashboard.clickSelectAllDryRunBots')"
{{ t('dashboard.dry') }}
:title="t('dashboard.clickSelectAllLiveBots')"
{{ t('common.live') }}
{{ t('common.offline') }}
```

- [ ] **Step 3: Run dashboard test locally**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run typecheck
pnpm run test:e2e-chromium -- e2e/dashboard.spec.ts
```

Expected:

```text
vue-tsc --build --noEmit
dashboard.spec.ts passes after selector updates in Task 6.
```

- [ ] **Step 4: Commit dashboard migration**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add src/views/DashboardView.vue src/components/ftbot/BotComparisonList.vue
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "feat: localize dashboard panels"
```

Expected:

```text
[cn/i18n <sha>] feat: localize dashboard panels
```

---

### Task 6: Update E2E Tests for Bilingual Deep Coverage

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\e2e\i18n.spec.ts`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\e2e\chart.spec.ts`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\e2e\trade.spec.ts`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\e2e\dashboard.spec.ts`

- [ ] **Step 1: Add a deep coverage E2E test to `i18n.spec.ts`**

Append:

```ts
test('shows bilingual text in chart, plot configurator, trade, and dashboard surfaces', async ({
  page,
}) => {
  await setLoginInfo(page);
  await defaultMocks(page);

  await page.goto('/graph');
  await page.waitForResponse('**/pair_candles');
  await page.getByRole('button', { name: /Plot Configurator|图表绘制配置/ }).click();
  await expect(page.getByText(/Plot Configurator \/ 图表绘制配置/)).toBeVisible();
  await expect(page.getByText(/Plot config name \/ 绘图配置名称/)).toBeVisible();
  await expect(page.getByRole('button', { name: /Add indicator \/ 添加指标/ })).toBeVisible();

  await page.goto('/trade');
  await page.waitForResponse('**/status');
  await expect(page.locator('.drag-header', { hasText: /Multi Pane \/ 多面板/ })).toBeVisible();
  await expect(page.locator('.drag-header', { hasText: /Open Trades \/ 未平仓交易/ })).toBeVisible();

  await page.goto('/dashboard');
  await page.waitForResponse('**/status');
  await expect(page.locator('.drag-header', { hasText: /Bot comparison \/ 机器人对比/ })).toBeVisible();
  await expect(page.locator('.drag-header', { hasText: /Cumulative Profit \/ 累计收益/ })).toBeVisible();
});
```

- [ ] **Step 2: Make existing chart selectors bilingual-safe**

In `chart.spec.ts`, replace exact button selectors:

```ts
await page.getByRole('button', { name: 'Refresh chart' }).click();
await page.getByRole('button', { name: 'Plot configurator' }).click();
await page.getByRole('button', { name: 'From template' }).click();
await page.getByRole('button', { name: 'Use Template' }).click();
await page.getByRole('button', { name: 'Apply Template' }).click();
await page.getByRole('button', { name: 'Save' }).click();
```

with:

```ts
await page.getByRole('button', { name: /Refresh chart/ }).click();
await page.getByRole('button', { name: /Plot Configurator|图表绘制配置/ }).click();
await page.getByRole('button', { name: /From template/ }).click();
await page.getByRole('button', { name: /Use Template/ }).click();
await page.getByRole('button', { name: /Apply Template/ }).click();
await page.getByRole('button', { name: /Save/ }).click();
```

Replace:

```ts
const indicatorPanel = page.getByText('Indicators in this plotb');
```

with:

```ts
const indicatorPanel = page.getByText(/Indicators in this plot/);
```

- [ ] **Step 3: Make existing trade selectors bilingual-safe**

In `trade.spec.ts`, replace key exact text selectors:

```ts
await expect(page.locator('.drag-header', { hasText: 'Multi Pane' })).toBeInViewport();
await expect(page.locator('.drag-header', { hasText: 'Chart' })).toBeInViewport();
await expect(page.locator('th:has-text("Profit USDT")')).toBeInViewport();
await page.getByRole('button', { name: 'Stop Trading - Also stops' }).click();
const modalCancelButton = dialogModal.getByRole('button', { name: 'Cancel' });
const modalOkButton = dialogModal.getByRole('button', { name: 'Ok' });
await page.getByRole('button', { name: 'Reload Config' }).click();
```

with:

```ts
await expect(page.locator('.drag-header', { hasText: /Multi Pane/ })).toBeInViewport();
await expect(page.locator('.drag-header', { hasText: /Chart|图表/ })).toBeInViewport();
await expect(page.locator('th').filter({ hasText: /Profit/ })).toBeInViewport();
await page.getByRole('button', { name: /Stop Trading/ }).click();
const modalCancelButton = dialogModal.getByRole('button', { name: /Cancel|取消/ });
const modalOkButton = dialogModal.getByRole('button', { name: /Ok|确定/ });
await page.getByRole('button', { name: /Reload Config/ }).click();
```

Replace header locators:

```ts
page.locator('.drag-header:has-text("Open Trades")')
page.locator('.drag-header:has-text("Closed Trades")')
```

with:

```ts
page.locator('.drag-header').filter({ hasText: /Open Trades/ })
page.locator('.drag-header').filter({ hasText: /Closed Trades/ })
```

- [ ] **Step 4: Make existing dashboard selectors bilingual-safe**

In `dashboard.spec.ts`, replace:

```ts
await expect(page.locator('.drag-header', { hasText: 'Bot comparison' })).toBeVisible();
await expect(page.locator('.drag-header', { hasText: 'Profit over time' })).toBeVisible();
await expect(page.locator('.drag-header', { hasText: 'Open trades' })).toBeVisible();
await expect(page.locator('.drag-header', { hasText: 'Cumulative Profit' })).toBeVisible();
await expect(page.locator('span', { hasText: 'Summary' })).toBeVisible();
await page.locator('.drag-header', { hasText: 'Trades Log' }).scrollIntoViewIfNeeded();
await expect(page.locator('.drag-header', { hasText: 'Closed Trades' })).toBeInViewport();
await expect(page.locator('.drag-header', { hasText: 'Profit Distribution' })).toBeInViewport();
await expect(page.locator('.drag-header', { hasText: 'Trades Log' })).toBeInViewport();
```

with:

```ts
await expect(page.locator('.drag-header', { hasText: /Bot comparison/ })).toBeVisible();
await expect(page.locator('.drag-header', { hasText: /Profit over time/ })).toBeVisible();
await expect(page.locator('.drag-header', { hasText: /Open Trades|Open trades/ })).toBeVisible();
await expect(page.locator('.drag-header', { hasText: /Cumulative Profit/ })).toBeVisible();
await expect(page.locator('span', { hasText: /Summary/ })).toBeVisible();
await page.locator('.drag-header', { hasText: /Trades Log/ }).scrollIntoViewIfNeeded();
await expect(page.locator('.drag-header', { hasText: /Closed Trades/ })).toBeInViewport();
await expect(page.locator('.drag-header', { hasText: /Profit Distribution/ })).toBeInViewport();
await expect(page.locator('.drag-header', { hasText: /Trades Log/ })).toBeInViewport();
```

- [ ] **Step 5: Run focused E2E tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:e2e-chromium -- e2e/i18n.spec.ts e2e/chart.spec.ts e2e/trade.spec.ts e2e/dashboard.spec.ts
```

Expected:

```text
All focused Chromium E2E tests pass.
```

- [ ] **Step 6: Commit E2E updates**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add e2e/i18n.spec.ts e2e/chart.spec.ts e2e/trade.spec.ts e2e/dashboard.spec.ts
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "test: cover deep bilingual ui surfaces"
```

Expected:

```text
[cn/i18n <sha>] test: cover deep bilingual ui surfaces
```

---

### Task 7: Full Verification and Docker Rebuild

**Files:**
- Verify only: `G:\AI_Trading\freqtrade-cn\frequi`
- Verify only: `G:\AI_Trading\freqtrade-cn\Dockerfile`
- Verify only: `G:\AI_Trading\freqtrade-cn\docker-compose.yml`

- [ ] **Step 1: Run frontend verification**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit
pnpm run typecheck
pnpm run lint-ci
pnpm run build
```

Expected:

```text
All commands exit with code 0.
Do not commit dist output unless it is already tracked and intentionally updated.
```

- [ ] **Step 2: Run focused E2E verification**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:e2e-chromium -- e2e/i18n.spec.ts e2e/chart.spec.ts e2e/trade.spec.ts e2e/dashboard.spec.ts
```

Expected:

```text
All focused E2E tests pass.
```

- [ ] **Step 3: Rebuild Docker image and restart container**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose build
docker compose up -d
docker compose ps
```

Expected:

```text
freqtrade-cn container is Up.
FreqUI is reachable at http://127.0.0.1:8081 unless FT_UI_PORT overrides it.
```

- [ ] **Step 4: Browser verification in bilingual mode**

Open:

```text
http://127.0.0.1:8081/graph
```

Expected visible text:

```text
Plot Configurator / 图表绘制配置
Plot config name / 绘图配置名称
Target Plot / 目标图层
Indicators in this plot / 当前图层中的指标
Add indicator / 添加指标
```

Open:

```text
http://127.0.0.1:8081/trade
```

Expected visible text:

```text
Multi Pane / 多面板
Open Trades / 未平仓交易
Closed Trades / 已平仓交易
Chart / 图表
```

Open:

```text
http://127.0.0.1:8081/dashboard
```

Expected visible text:

```text
Bot comparison / 机器人对比
Cumulative Profit / 累计收益
Profit Distribution / 收益分布
Trades Log / 交易日志
```

- [ ] **Step 5: Browser verification in English-only mode**

Open:

```text
http://127.0.0.1:8081/settings
```

Change `Language display / 语言显示` to English.

Expected:

```text
Navigation and migrated labels show English only.
Market symbols, indicators, strategy names, and plot names remain unchanged.
```

- [ ] **Step 6: Final repository status**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi status --short --branch
git -C G:\AI_Trading\freqtrade-cn status --short --branch
```

Expected:

```text
frequi is clean after commits.
Top-level may show the frequi submodule pointer changed and existing unrelated Docker/runtime files.
```

## Plan Self-Review Checklist

- Spec coverage:
  - Plot Configurator panel: Tasks 1, 2, 6, 7.
  - Trading panel: Tasks 1, 3, 4, 6, 7.
  - Dashboard: Tasks 1, 5, 6, 7.
  - Chart view: Tasks 1, 2, 6, 7.
  - Existing Settings language mode remains the single switch: all migration tasks use `useAppI18n().t(key)`.
  - Non-invasive approach: no backend changes, no DOM rewriting, no new i18n library.
- Placeholder scan:
  - No unresolved placeholder markers or undefined task references.
  - Dynamic replacements use existing `String.replace` with explicit placeholders like `{currency}` and `{orderType}`.
- Type consistency:
  - All keys are added to `en.ts`; `LocaleKey` continues deriving from English keys.
  - `zh-CN.ts` uses `PartialLocaleMessages`, so missing Chinese text falls back to English.
  - Computed option arrays are used where labels must update after changing Settings language mode.
- Residual risk:
  - Some deep child components outside the named surfaces may still contain English-only text. Task 0's `rg` audit is the checklist for deciding whether to include them in this pass or leave them for a later narrower pass.
  - ECharts visual snapshots may shift because legend labels become longer in bilingual mode. Task 6 keeps screenshot assertions but allows the existing tolerance unless a real layout issue appears.
