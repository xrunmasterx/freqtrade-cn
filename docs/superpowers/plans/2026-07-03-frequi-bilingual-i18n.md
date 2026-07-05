# FreqUI Bilingual i18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a long-term FreqUI bilingual display foundation where the default UI shows English and Simplified Chinese together, with settings to switch to English-only or Chinese-only.

**Architecture:** Implement a lightweight app-owned i18n layer in the `frequi` submodule. English and Chinese strings live in locale files, components render text through a typed `t(key)` API, and `settingsStore.localeMode` persists the selected display mode. The Freqtrade backend remains unchanged; Docker continues building FreqUI from source and copying the built `dist` into the API server image.

**Tech Stack:** Vue 3, Vite, TypeScript, Pinia, pinia-plugin-persistedstate, Nuxt UI, Vitest, Playwright, Docker Compose.

---

## Scope Notes

- Implementation target: `G:\AI_Trading\freqtrade-cn\frequi`.
- Top-level repository: `G:\AI_Trading\freqtrade-cn`.
- Keep `G:\AI_Trading\freqtrade-cn\freqtrade` unchanged for this feature.
- Do not edit `G:\AI_Trading\freqtrade-cn\frequi\dist`.
- Do not add a browser translation layer, DOM mutation layer, reverse proxy text rewrite, or runtime static asset patch.
- Existing top-level untracked Docker/runtime files must not be staged accidentally.

## File Structure

Create in `frequi`:

- `G:\AI_Trading\freqtrade-cn\frequi\src\locales\en.ts`  
  Canonical English UI strings for the first migration slice.
- `G:\AI_Trading\freqtrade-cn\frequi\src\locales\zh-CN.ts`  
  Simplified Chinese translations for the first migration slice.
- `G:\AI_Trading\freqtrade-cn\frequi\src\locales\keys.ts`  
  Locale types, key-path type generation, and `LocaleMode`.
- `G:\AI_Trading\freqtrade-cn\frequi\src\composables\useAppI18n.ts`  
  Pure resolver plus Vue composable that reads `settingsStore.localeMode`.
- `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`  
  Unit tests for resolver and settings-backed composable.
- `G:\AI_Trading\freqtrade-cn\frequi\e2e\i18n.spec.ts`  
  Playwright smoke test for default bilingual mode and Settings switching.

Modify in `frequi`:

- `G:\AI_Trading\freqtrade-cn\frequi\src\stores\settings.ts`  
  Add persisted `localeMode`.
- `G:\AI_Trading\freqtrade-cn\frequi\src\App.vue`  
  Bridge `localeMode` to Nuxt UI `UApp` locale.
- `G:\AI_Trading\freqtrade-cn\frequi\src\views\SettingsView.vue`  
  Add language display selector and migrate core settings copy.
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\layout\NavBar.vue`  
  Migrate navigation and dropdown labels.
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\layout\NavFooter.vue`  
  Migrate mobile footer labels.
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\BotLogin.vue`  
  Migrate login form labels, buttons, and front-end-owned error wrappers.
- `G:\AI_Trading\freqtrade-cn\frequi\src\components\general\ConfirmDialogBox.vue`  
  Migrate default confirmation/cancel labels without changing caller-provided messages.

Top-level repository finalization:

- `G:\AI_Trading\freqtrade-cn\frequi` submodule SHA should be updated in the top-level repository after the `frequi` branch commit exists and has been pushed.

---

### Task 0: Prepare the `frequi` i18n Branch

**Files:**
- Inspect only: `G:\AI_Trading\freqtrade-cn`
- Inspect only: `G:\AI_Trading\freqtrade-cn\frequi`

- [ ] **Step 1: Confirm current repository state**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn status --short
git -C G:\AI_Trading\freqtrade-cn\frequi status --short
git -C G:\AI_Trading\freqtrade-cn\frequi rev-parse --abbrev-ref HEAD
git -C G:\AI_Trading\freqtrade-cn\frequi rev-parse --short HEAD
```

Expected:

```text
Top-level may show existing untracked Docker/runtime files.
frequi should be clean before implementation starts.
frequi may report HEAD because submodules are often checked out detached.
```

- [ ] **Step 2: Create the implementation branch in `frequi`**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi switch -c cn/i18n
```

Expected:

```text
Switched to a new branch 'cn/i18n'
```

If the branch already exists, stop this task and run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi switch cn/i18n
git -C G:\AI_Trading\freqtrade-cn\frequi status --short
```

Expected:

```text
Switched to branch 'cn/i18n'
Working tree clean before implementation starts.
```

---

### Task 1: Locale Dictionaries and Pure Resolver

**Files:**
- Create: `G:\AI_Trading\freqtrade-cn\frequi\src\locales\en.ts`
- Create: `G:\AI_Trading\freqtrade-cn\frequi\src\locales\zh-CN.ts`
- Create: `G:\AI_Trading\freqtrade-cn\frequi\src\locales\keys.ts`
- Create: `G:\AI_Trading\freqtrade-cn\frequi\src\composables\useAppI18n.ts`
- Test: `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`

- [ ] **Step 1: Write failing resolver tests**

Create `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts` with:

```ts
import { describe, expect, it } from 'vitest';
import { resolveLocaleText } from '@/composables/useAppI18n';

describe('resolveLocaleText', () => {
  it('returns bilingual text by default mode', () => {
    expect(resolveLocaleText('nav.trade', 'bilingual')).toBe('Trade / 交易');
  });

  it('returns English text in English mode', () => {
    expect(resolveLocaleText('nav.trade', 'en')).toBe('Trade');
  });

  it('returns Chinese text in zh-CN mode', () => {
    expect(resolveLocaleText('nav.trade', 'zh-CN')).toBe('交易');
  });

  it('falls back to English when Chinese text is missing', () => {
    expect(
      resolveLocaleText('nav.trade', 'bilingual', {
        zhMessages: {
          nav: {},
        },
      }),
    ).toBe('Trade');
    expect(
      resolveLocaleText('nav.trade', 'zh-CN', {
        zhMessages: {
          nav: {},
        },
      }),
    ).toBe('Trade');
  });
});
```

- [ ] **Step 2: Run the failing resolver test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit -- tests/unit/appI18n.spec.ts
```

Expected:

```text
FAIL tests/unit/appI18n.spec.ts
Cannot find module '@/composables/useAppI18n'
```

- [ ] **Step 3: Create English locale messages**

Create `G:\AI_Trading\freqtrade-cn\frequi\src\locales\en.ts` with:

```ts
export const en = {
  nav: {
    trade: 'Trade',
    dashboard: 'Dashboard',
    chart: 'Chart',
    logs: 'Logs',
    settings: 'Settings',
    backtest: 'Backtest',
    analysis: 'Analysis',
    recursiveAnalysis: 'Recursive Analysis',
    lookaheadAnalysis: 'Lookahead Analysis',
    downloadData: 'Download Data',
    pairlistConfig: 'Pairlist Config',
    lockLayout: 'Lock Layout',
    unlockLayout: 'Unlock Layout',
    resetLayout: 'Reset Layout',
    logout: 'Logout',
    botNotFound: 'Bot not found',
    trades: 'Trades',
    history: 'History',
    pairlist: 'Pairlist',
    balance: 'Balance',
  },
  settings: {
    title: 'FreqUI Settings',
    uiVersion: 'UI Version',
    uiSettings: 'UI settings',
    languageDisplay: 'Language display',
    languageDisplayHint: 'Choose how FreqUI labels are displayed.',
    languageEnglish: 'English',
    languageChinese: 'Simplified Chinese',
    languageBilingual: 'English / Chinese',
    lockDynamicLayouts: 'Lock dynamic layouts',
    lockDynamicLayoutsHint:
      'Lock dynamic layouts, so they cannot move anymore. Can also be set from the navbar at the top.',
    resetLayout: 'Reset layout',
    resetLayoutHint: 'Reset dynamic layouts to how they were.',
    layoutsReset: 'Layouts have been reset.',
    showOpenTradesInHeader: 'Show open trades in header',
    showOpenTradesInHeaderHint: 'Decide if open trades should be visualized',
    showPillInIcon: 'Show pill in icon',
    showInTitle: 'Show in title',
    doNotShowOpenTrades: "Don't show open trades in header",
    utcTimezone: 'UTC Timezone',
    utcTimezoneHint: 'Select timezone (UTC is recommended as exchanges usually work in UTC)',
    backgroundSync: 'Background sync',
    backgroundSyncHint: 'Keep background sync running while other bots are selected.',
    confirmDialog: 'Show Confirm Dialog for Trade Exits',
    confirmDialogHint: 'Use confirmation dialogs when force-exiting a trade.',
    multiPaneButtonsShowText: 'Show Text on Multi Pane Buttons',
    multiPaneButtonsShowTextHint: 'Show text on multi pane buttons. If disabled, only shows images.',
    chartSettings: 'Chart settings',
    chartScaleSide: 'Chart scale Side',
    chartScaleSideHint: 'Should the scale be displayed on the right or left?',
    left: 'Left',
    right: 'Right',
    useHeikinAshiCandles: 'Use Heikin Ashi candles',
    useHeikinAshiCandlesHint: 'Use Heikin Ashi candles in your charts',
    onlyRequestNecessaryColumns: 'Only request necessary columns',
    onlyRequestNecessaryColumnsHint:
      'Can reduce the transfer size for large dataframes. May require additional calls if the plot config changes.',
    defaultCandles: 'Default number of candles to display (defaults to 250)',
    candleColorPreference: 'Candle Color Preference',
    greenUpRedDown: 'Green Up/Red Down',
    redUpGreenDown: 'Red Up/Green Down',
    notificationSettings: 'Notification Settings',
    entryNotifications: 'Entry notifications',
    exitNotifications: 'Exit notifications',
    entryCancelNotifications: 'Entry Cancel notifications',
    exitCancelNotifications: 'Exit Cancel notifications',
    backtestingSettings: 'Backtesting settings',
    backtestingMetrics: 'Backtesting metrics',
    backtestingMetricsHint: 'Select which metrics should be shown on a per pair / tag basis.',
  },
  login: {
    botName: 'Bot Name',
    apiUrl: 'API Url',
    apiUrlRequired: 'API URL is required.',
    duplicateUrl: 'This URL is already in use by another bot.',
    username: 'Username',
    namePasswordRequired: 'Name and Password are required.',
    password: 'Password',
    invalidPassword: 'Invalid Password',
    loginFailed: 'Login failed',
    authFailed: 'Connected to bot, however Login failed, Username or Password wrong.',
    apiUnreachable:
      'Please verify that the bot is running, the Bot API is enabled and the URL is reachable.',
    apiPingHint: 'You can verify this by navigating to this ping URL:',
    corsCheck: "Please also check your bot's CORS configuration:",
    corsDocs: 'Freqtrade CORS documentation',
    reset: 'Reset',
    cancel: 'Cancel',
    submit: 'Submit',
  },
  confirm: {
    description: 'Confirmation',
    cancel: 'Cancel',
    ok: 'Ok',
  },
} as const;
```

- [ ] **Step 4: Create locale key types**

Create `G:\AI_Trading\freqtrade-cn\frequi\src\locales\keys.ts` with:

```ts
import type { en } from './en';

export type LocaleMode = 'bilingual' | 'zh-CN' | 'en';
export type LocaleMessages = typeof en;

export type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends object ? DeepPartial<T[K]> : T[K];
};

type LeafPaths<T> = {
  [K in keyof T & string]: T[K] extends string ? K : `${K}.${LeafPaths<T[K]>}`;
}[keyof T & string];

export type LocaleKey = LeafPaths<LocaleMessages>;
export type PartialLocaleMessages = DeepPartial<LocaleMessages>;
```

- [ ] **Step 5: Create Simplified Chinese messages**

Create `G:\AI_Trading\freqtrade-cn\frequi\src\locales\zh-CN.ts` with:

```ts
import type { PartialLocaleMessages } from './keys';

export const zhCN = {
  nav: {
    trade: '交易',
    dashboard: '仪表盘',
    chart: '图表',
    logs: '日志',
    settings: '设置',
    backtest: '回测',
    analysis: '分析',
    recursiveAnalysis: '递归分析',
    lookaheadAnalysis: '前瞻分析',
    downloadData: '下载数据',
    pairlistConfig: '交易对列表配置',
    lockLayout: '锁定布局',
    unlockLayout: '解锁布局',
    resetLayout: '重置布局',
    logout: '退出登录',
    botNotFound: '未找到机器人',
    trades: '交易',
    history: '历史',
    pairlist: '交易对列表',
    balance: '余额',
  },
  settings: {
    title: 'FreqUI 设置',
    uiVersion: 'UI 版本',
    uiSettings: 'UI 设置',
    languageDisplay: '语言显示',
    languageDisplayHint: '选择 FreqUI 标签的显示方式。',
    languageEnglish: '英文',
    languageChinese: '简体中文',
    languageBilingual: '英文 / 中文',
    lockDynamicLayouts: '锁定动态布局',
    lockDynamicLayoutsHint: '锁定动态布局，使其不能再移动。也可以从顶部导航栏设置。',
    resetLayout: '重置布局',
    resetLayoutHint: '将动态布局恢复为初始状态。',
    layoutsReset: '布局已重置。',
    showOpenTradesInHeader: '在页头显示未平仓交易',
    showOpenTradesInHeaderHint: '决定是否可视化未平仓交易',
    showPillInIcon: '在图标中显示标记',
    showInTitle: '在标题中显示',
    doNotShowOpenTrades: '不在页头显示未平仓交易',
    utcTimezone: 'UTC 时区',
    utcTimezoneHint: '选择时区（推荐 UTC，因为交易所通常使用 UTC）',
    backgroundSync: '后台同步',
    backgroundSyncHint: '选择其他机器人时仍保持后台同步。',
    confirmDialog: '交易退出时显示确认对话框',
    confirmDialogHint: '强制退出交易时使用确认对话框。',
    multiPaneButtonsShowText: '多面板按钮显示文字',
    multiPaneButtonsShowTextHint: '在多面板按钮上显示文字。关闭后只显示图标。',
    chartSettings: '图表设置',
    chartScaleSide: '图表刻度位置',
    chartScaleSideHint: '刻度应该显示在右侧还是左侧？',
    left: '左侧',
    right: '右侧',
    useHeikinAshiCandles: '使用平均 K 线',
    useHeikinAshiCandlesHint: '在图表中使用平均 K 线',
    onlyRequestNecessaryColumns: '只请求必要列',
    onlyRequestNecessaryColumnsHint: '可减少大型 dataframe 的传输量。图表配置变化时可能需要额外请求。',
    defaultCandles: '默认显示的 K 线数量（默认 250）',
    candleColorPreference: 'K 线颜色偏好',
    greenUpRedDown: '上涨绿 / 下跌红',
    redUpGreenDown: '上涨红 / 下跌绿',
    notificationSettings: '通知设置',
    entryNotifications: '入场通知',
    exitNotifications: '出场通知',
    entryCancelNotifications: '入场取消通知',
    exitCancelNotifications: '出场取消通知',
    backtestingSettings: '回测设置',
    backtestingMetrics: '回测指标',
    backtestingMetricsHint: '选择按交易对 / 标签显示哪些指标。',
  },
  login: {
    botName: '机器人名称',
    apiUrl: 'API 地址',
    apiUrlRequired: '必须填写 API 地址。',
    duplicateUrl: '该地址已被另一个机器人使用。',
    username: '用户名',
    namePasswordRequired: '必须填写用户名和密码。',
    password: '密码',
    invalidPassword: '密码无效',
    loginFailed: '登录失败',
    authFailed: '已连接到机器人，但登录失败，用户名或密码错误。',
    apiUnreachable: '请确认机器人正在运行、Bot API 已启用，并且地址可以访问。',
    apiPingHint: '你可以访问下面的 ping 地址确认 Bot API 可用：',
    corsCheck: '也请检查机器人的 CORS 配置：',
    corsDocs: 'Freqtrade CORS 文档',
    reset: '重置',
    cancel: '取消',
    submit: '提交',
  },
  confirm: {
    description: '确认',
    cancel: '取消',
    ok: '确定',
  },
} satisfies PartialLocaleMessages;
```

- [ ] **Step 6: Create the pure resolver**

Create `G:\AI_Trading\freqtrade-cn\frequi\src\composables\useAppI18n.ts` with:

```ts
import { en } from '@/locales/en';
import { zhCN } from '@/locales/zh-CN';
import type { LocaleKey, LocaleMessages, LocaleMode, PartialLocaleMessages } from '@/locales/keys';

interface ResolveLocaleTextOptions {
  enMessages?: LocaleMessages;
  zhMessages?: PartialLocaleMessages;
}

function readPath(messages: PartialLocaleMessages, key: LocaleKey): string | undefined {
  const value = key
    .split('.')
    .reduce<unknown>(
      (current, segment) =>
        current && typeof current === 'object'
          ? (current as Record<string, unknown>)[segment]
          : undefined,
      messages,
    );

  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

export function resolveLocaleText(
  key: LocaleKey,
  mode: LocaleMode,
  options: ResolveLocaleTextOptions = {},
): string {
  const enMessages = options.enMessages ?? en;
  const zhMessages = options.zhMessages ?? zhCN;
  const enText = readPath(enMessages, key);
  const zhText = readPath(zhMessages, key);

  if (!enText) {
    return '';
  }

  if (mode === 'en') {
    return enText;
  }

  if (mode === 'zh-CN') {
    return zhText ?? enText;
  }

  return zhText ? `${enText} / ${zhText}` : enText;
}
```

- [ ] **Step 7: Run resolver tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit -- tests/unit/appI18n.spec.ts
```

Expected:

```text
PASS tests/unit/appI18n.spec.ts
```

- [ ] **Step 8: Commit locale foundation in `frequi`**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add src/locales src/composables/useAppI18n.ts tests/unit/appI18n.spec.ts
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "feat: add bilingual locale resolver"
```

Expected:

```text
[cn/i18n <sha>] feat: add bilingual locale resolver
```

---

### Task 2: Persisted Locale Mode and Settings-Backed Composable

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\stores\settings.ts`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\composables\useAppI18n.ts`
- Test: `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`

- [ ] **Step 1: Add failing settings-backed composable tests**

Append these imports at the top of `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia';
import { useAppI18n } from '@/composables/useAppI18n';
import { useSettingsStore } from '@/stores/settings';
```

Append this test block to the same file:

```ts
describe('useAppI18n', () => {
  it('uses the persisted settings locale mode', () => {
    setActivePinia(createPinia());
    const settingsStore = useSettingsStore();
    const { t } = useAppI18n();

    expect(settingsStore.localeMode).toBe('bilingual');
    expect(t('nav.trade')).toBe('Trade / 交易');

    settingsStore.localeMode = 'en';
    expect(t('nav.trade')).toBe('Trade');

    settingsStore.localeMode = 'zh-CN';
    expect(t('nav.trade')).toBe('交易');
  });
});
```

- [ ] **Step 2: Run failing settings-backed composable tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit -- tests/unit/appI18n.spec.ts
```

Expected:

```text
FAIL tests/unit/appI18n.spec.ts
Property 'localeMode' does not exist
```

- [ ] **Step 3: Add `localeMode` to settings store**

Modify `G:\AI_Trading\freqtrade-cn\frequi\src\stores\settings.ts`.

Add this import after the existing imports:

```ts
import type { LocaleMode } from '@/locales/keys';
```

Add this ref after `const currentTheme = ref('dark' as ThemeName);`:

```ts
const localeMode = ref<LocaleMode>('bilingual');
```

Add `localeMode` to the returned object after `currentTheme`:

```ts
localeMode,
```

- [ ] **Step 4: Add the settings-backed composable**

Append this function to `G:\AI_Trading\freqtrade-cn\frequi\src\composables\useAppI18n.ts` after `resolveLocaleText`:

```ts
export function useAppI18n() {
  const settingsStore = useSettingsStore();

  function t(key: LocaleKey): string {
    return resolveLocaleText(key, settingsStore.localeMode);
  }

  return {
    t,
  };
}
```

- [ ] **Step 5: Run focused unit tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit -- tests/unit/appI18n.spec.ts
```

Expected:

```text
PASS tests/unit/appI18n.spec.ts
```

- [ ] **Step 6: Run typecheck**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run typecheck
```

Expected:

```text
vue-tsc --build --noEmit
```

Exit code must be `0`.

- [ ] **Step 7: Commit persisted locale mode**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add src/stores/settings.ts src/composables/useAppI18n.ts tests/unit/appI18n.spec.ts
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "feat: persist FreqUI locale mode"
```

Expected:

```text
[cn/i18n <sha>] feat: persist FreqUI locale mode
```

---

### Task 3: Nuxt UI Locale Bridge and Settings Selector

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\App.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\views\SettingsView.vue`
- Test: `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`

- [ ] **Step 1: Add a unit test for locale mode option text**

Append this test to `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`:

```ts
describe('settings locale labels', () => {
  it('resolves the three locale display option labels', () => {
    expect(resolveLocaleText('settings.languageBilingual', 'bilingual')).toBe(
      'English / Chinese / 英文 / 中文',
    );
    expect(resolveLocaleText('settings.languageChinese', 'zh-CN')).toBe('简体中文');
    expect(resolveLocaleText('settings.languageEnglish', 'en')).toBe('English');
  });
});
```

- [ ] **Step 2: Run the current focused unit tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit -- tests/unit/appI18n.spec.ts
```

Expected:

```text
PASS tests/unit/appI18n.spec.ts
```

- [ ] **Step 3: Bridge Nuxt UI locale in `App.vue`**

Modify `G:\AI_Trading\freqtrade-cn\frequi\src\App.vue`.

Replace the script block with:

```vue
<script setup lang="ts">
import { en, zh_cn } from '@nuxt/ui/locale';

const settingsStore = useSettingsStore();
const colorStore = useColorStore();

const uiLocale = computed(() => (settingsStore.localeMode === 'en' ? en : zh_cn));

onMounted(() => {
  setTimezone(settingsStore.timezone);
  colorStore.updateProfitLossColor();
});
watch(
  () => settingsStore.timezone,
  (tz) => {
    console.log('timezone changed', tz);
    setTimezone(tz);
  },
);
</script>
```

Replace `<UApp>` with:

```vue
<UApp :locale="uiLocale">
```

- [ ] **Step 4: Convert Settings options to computed localized labels**

Modify the script block in `G:\AI_Trading\freqtrade-cn\frequi\src\views\SettingsView.vue`.

Add after the store declarations:

```ts
const { t } = useAppI18n();
```

Replace `openTradesOptions` and `colorPreferenceOptions` with:

```ts
const openTradesOptions = computed(() => [
  { value: OpenTradeVizOptions.showPill, text: t('settings.showPillInIcon') },
  { value: OpenTradeVizOptions.asTitle, text: t('settings.showInTitle') },
  { value: OpenTradeVizOptions.noOpenTrades, text: t('settings.doNotShowOpenTrades') },
]);

const colorPreferenceOptions = computed(() => [
  { value: ColorPreferences.GREEN_UP, text: t('settings.greenUpRedDown') },
  { value: ColorPreferences.RED_UP, text: t('settings.redUpGreenDown') },
]);

const chartScaleSideOptions = computed(() => [
  { label: t('settings.left'), value: 'left' },
  { label: t('settings.right'), value: 'right' },
]);

const localeModeOptions = computed(() => [
  { label: t('settings.languageBilingual'), value: 'bilingual' },
  { label: t('settings.languageChinese'), value: 'zh-CN' },
  { label: t('settings.languageEnglish'), value: 'en' },
]);
```

Replace the body of `resetDynamicLayout` with:

```ts
layoutStore.resetTradingLayout();
layoutStore.resetDashboardLayout();
showAlert(t('settings.layoutsReset'));
```

- [ ] **Step 5: Add language selector and migrate Settings text**

In `G:\AI_Trading\freqtrade-cn\frequi\src\views\SettingsView.vue`, replace the header and top settings labels with localized calls.

Use these replacements in the template:

```vue
<template #header><span class="text-2xl font-bold">{{ t('settings.title') }}</span></template>
<p class="text-left">{{ t('settings.uiVersion') }}: {{ settingsStore.uiVersion }}</p>
<h4 class="text-xl font-semibold">{{ t('settings.uiSettings') }}</h4>
```

Insert this block immediately after the `<h4 class="text-xl font-semibold">` line in the UI settings section:

```vue
<div class="space-y-1">
  <label class="block text-sm">{{ t('settings.languageDisplay') }}</label>
  <USelect
    v-model="settingsStore.localeMode"
    :items="localeModeOptions"
    label-key="label"
    value-key="value"
    data-testid="locale-mode-select"
    class="w-full"
  />
  <small class="text-sm text-neutral-600 dark:text-neutral-400">
    {{ t('settings.languageDisplayHint') }}
  </small>
</div>

<USeparator />
```

Replace the first settings section text with:

```vue
<BaseCheckbox v-model="layoutStore.layoutLocked" class="space-y-1">
  {{ t('settings.lockDynamicLayouts') }}
  <template #hint>
    {{ t('settings.lockDynamicLayoutsHint') }}
  </template>
</BaseCheckbox>

<div class="flex flex-row items-center gap-2 space-y-2">
  <UButton color="neutral" size="md" class="mb-0" @click="resetDynamicLayout">
    {{ t('settings.resetLayout') }}
  </UButton>
  <small class="text-sm block text-neutral-600 dark:text-neutral-400">
    {{ t('settings.resetLayoutHint') }}
  </small>
</div>

<USeparator />

<div class="space-y-1">
  <label class="block text-sm">{{ t('settings.showOpenTradesInHeader') }}</label>
  <USelect
    v-model="settingsStore.openTradesInTitle"
    :items="openTradesOptions"
    label-key="text"
    value-key="value"
    class="w-full"
  />
  <small class="text-sm text-neutral-600 dark:text-neutral-400">
    {{ t('settings.showOpenTradesInHeaderHint') }}
  </small>
</div>

<div class="space-y-1">
  <label class="block text-sm">{{ t('settings.utcTimezone') }}</label>
  <USelect v-model="settingsStore.timezone" :items="timezoneOptions" class="w-full" />
  <small class="text-sm text-neutral-600 dark:text-neutral-400">
    {{ t('settings.utcTimezoneHint') }}
  </small>
</div>

<BaseCheckbox v-model="settingsStore.backgroundSync" class="space-y-1">
  {{ t('settings.backgroundSync') }}
  <template #hint>{{ t('settings.backgroundSyncHint') }}</template>
</BaseCheckbox>

<BaseCheckbox v-model="settingsStore.confirmDialog" class="space-y-1">
  {{ t('settings.confirmDialog') }}
  <template #hint>
    {{ t('settings.confirmDialogHint') }}<br />
    This will also show <i-mdi-run-fast class="text-yellow-300 inline" />
    <i-mdi-alert class="text-yellow-300 inline" />
    in the title bar.
  </template>
</BaseCheckbox>

<BaseCheckbox v-model="settingsStore.multiPaneButtonsShowText" class="space-y-1">
  {{ t('settings.multiPaneButtonsShowText') }}
  <template #hint>{{ t('settings.multiPaneButtonsShowTextHint') }}</template>
</BaseCheckbox>
```

Replace chart, notification, and backtesting headings and short labels with:

```vue
<h4 class="text-lg font-semibold">{{ t('settings.chartSettings') }}</h4>
<label class="block text-sm">{{ t('settings.chartScaleSide') }}</label>
<URadioGroup
  v-model="settingsStore.chartLabelSide"
  :items="chartScaleSideOptions"
  orientation="horizontal"
/>
<small class="text-sm text-neutral-600 dark:text-neutral-400">
  {{ t('settings.chartScaleSideHint') }}
</small>

<BaseCheckbox v-model="settingsStore.useHeikinAshiCandles" class="space-y-1">
  {{ t('settings.useHeikinAshiCandles') }}
  <template #hint>{{ t('settings.useHeikinAshiCandlesHint') }}</template>
</BaseCheckbox>

<BaseCheckbox v-model="settingsStore.useReducedPairCalls" class="space-y-1">
  {{ t('settings.onlyRequestNecessaryColumns') }}
  <template #hint>{{ t('settings.onlyRequestNecessaryColumnsHint') }}</template>
</BaseCheckbox>

<p>{{ t('settings.defaultCandles') }}</p>
<label class="block">{{ t('settings.candleColorPreference') }}</label>
<h4 class="text-lg font-semibold">{{ t('settings.notificationSettings') }}</h4>
<h4 class="text-lg font-semibold">{{ t('settings.backtestingSettings') }}</h4>
<label for="backtestMetrics" class="block">{{ t('settings.backtestingMetrics') }}</label>
<small class="text-sm text-neutral-600 dark:text-neutral-400">
  {{ t('settings.backtestingMetricsHint') }}
</small>
```

Replace notification checkbox text with:

```vue
{{ t('settings.entryNotifications') }}
{{ t('settings.exitNotifications') }}
{{ t('settings.entryCancelNotifications') }}
{{ t('settings.exitCancelNotifications') }}
```

- [ ] **Step 6: Run focused tests and typecheck**

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

Both commands must exit with code `0`.

- [ ] **Step 7: Commit App and Settings UI**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add src/App.vue src/views/SettingsView.vue tests/unit/appI18n.spec.ts
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "feat: add bilingual display setting"
```

Expected:

```text
[cn/i18n <sha>] feat: add bilingual display setting
```

---

### Task 4: Migrate Navigation Labels

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\layout\NavBar.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\layout\NavFooter.vue`
- Test: `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`

- [ ] **Step 1: Add unit assertions for navigation keys**

Append to the existing `resolveLocaleText` describe block in `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`:

```ts
it('resolves first-slice navigation labels', () => {
  expect(resolveLocaleText('nav.dashboard', 'bilingual')).toBe('Dashboard / 仪表盘');
  expect(resolveLocaleText('nav.chart', 'bilingual')).toBe('Chart / 图表');
  expect(resolveLocaleText('nav.logs', 'bilingual')).toBe('Logs / 日志');
  expect(resolveLocaleText('nav.settings', 'bilingual')).toBe('Settings / 设置');
  expect(resolveLocaleText('nav.trades', 'bilingual')).toBe('Trades / 交易');
});
```

- [ ] **Step 2: Run focused unit test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit -- tests/unit/appI18n.spec.ts
```

Expected:

```text
PASS tests/unit/appI18n.spec.ts
```

- [ ] **Step 3: Migrate desktop navigation**

Modify `G:\AI_Trading\freqtrade-cn\frequi\src\components\layout\NavBar.vue`.

Add after `const loginDialog = useLoginDialog();`:

```ts
const { t } = useAppI18n();
```

Replace navigation labels:

```ts
label: t('nav.trade'),
label: t('nav.dashboard'),
label: t('nav.chart'),
label: t('nav.logs'),
label: t('nav.settings'),
label: t('nav.backtest'),
label: t('nav.analysis'),
label: t('nav.recursiveAnalysis'),
label: t('nav.lookaheadAnalysis'),
label: t('nav.downloadData'),
label: t('nav.pairlistConfig'),
```

Replace dropdown labels:

```ts
label: t('nav.settings'),
label: layoutStore.layoutLocked ? t('nav.unlockLayout') : t('nav.lockLayout'),
label: t('nav.resetLayout'),
label: t('nav.logout'),
```

Replace:

```ts
showAlert('Bot not found', 'warning');
```

with:

```ts
showAlert(t('nav.botNotFound'), 'warning');
```

- [ ] **Step 4: Migrate mobile footer labels**

Modify `G:\AI_Trading\freqtrade-cn\frequi\src\components\layout\NavFooter.vue`.

Replace the script block with:

```vue
<script setup lang="ts">
const botStore = useBotStore();
const { t } = useAppI18n();
</script>
```

Replace static `label` attributes with dynamic labels:

```vue
:label="t('nav.trades')"
:label="t('nav.history')"
:label="t('nav.pairlist')"
:label="t('nav.balance')"
:label="t('nav.dashboard')"
```

- [ ] **Step 5: Run typecheck**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run typecheck
```

Expected:

```text
vue-tsc --build --noEmit
```

Exit code must be `0`.

- [ ] **Step 6: Commit navigation migration**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add src/components/layout/NavBar.vue src/components/layout/NavFooter.vue tests/unit/appI18n.spec.ts
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "feat: localize primary navigation"
```

Expected:

```text
[cn/i18n <sha>] feat: localize primary navigation
```

---

### Task 5: Migrate Login and Confirmation Defaults

**Files:**
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\BotLogin.vue`
- Modify: `G:\AI_Trading\freqtrade-cn\frequi\src\components\general\ConfirmDialogBox.vue`
- Test: `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`

- [ ] **Step 1: Add unit assertions for login and confirmation keys**

Append to the existing `resolveLocaleText` describe block in `G:\AI_Trading\freqtrade-cn\frequi\tests\unit\appI18n.spec.ts`:

```ts
it('resolves login and confirmation labels', () => {
  expect(resolveLocaleText('login.botName', 'bilingual')).toBe('Bot Name / 机器人名称');
  expect(resolveLocaleText('login.submit', 'bilingual')).toBe('Submit / 提交');
  expect(resolveLocaleText('confirm.cancel', 'bilingual')).toBe('Cancel / 取消');
  expect(resolveLocaleText('confirm.ok', 'bilingual')).toBe('Ok / 确定');
});
```

- [ ] **Step 2: Run focused unit test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit -- tests/unit/appI18n.spec.ts
```

Expected:

```text
PASS tests/unit/appI18n.spec.ts
```

- [ ] **Step 3: Migrate login script text**

Modify `G:\AI_Trading\freqtrade-cn\frequi\src\components\BotLogin.vue`.

Add after `const botStore = useBotStore();`:

```ts
const { t } = useAppI18n();
```

Replace:

```ts
errorMessage.value = 'Connected to bot, however Login failed, Username or Password wrong.';
```

with:

```ts
errorMessage.value = t('login.authFailed');
```

Replace:

```ts
errorMessage.value = `Please verify that the bot is running, the Bot API is enabled and the URL is reachable.
You can verify this by navigating to ${auth.value.url}/api/v1/ping to make sure the bot API is reachable`;
```

with:

```ts
errorMessage.value = `${t('login.apiUnreachable')}
${t('login.apiPingHint')} ${auth.value.url}/api/v1/ping`;
```

- [ ] **Step 4: Migrate login template text**

In `G:\AI_Trading\freqtrade-cn\frequi\src\components\BotLogin.vue`, use these template replacements:

```vue
<UFormField class="mb-4" :label="t('login.botName')">
<UInput
  v-model="auth.botName"
  class="mt-1 block w-full"
  @keydown.enter="handleOk"
/>

<UFormField
  class="mb-4"
  :label="t('login.apiUrl')"
  :error="urlState === false ? t('login.apiUrlRequired') : undefined"
>

<UAlert
  v-if="urlDuplicate"
  class="mt-2"
  color="warning"
  :title="t('login.duplicateUrl')"
>
</UAlert>

<UFormField
  class="mb-4"
  :label="t('login.username')"
  :error="nameState === false ? t('login.namePasswordRequired') : undefined"
>

<UFormField
  class="mb-4"
  :label="t('login.password')"
  :error="pwdState === false ? t('login.invalidPassword') : undefined"
>

<UAlert
  v-if="errorMessage"
  class="mt-2 whitespace-pre-line"
  color="warning"
  :title="t('login.loginFailed')"
>

{{ t('login.corsCheck') }}
<a
  href="https://www.freqtrade.io/en/latest/rest-api/#cors"
  class="text-blue-500 underline"
>
  {{ t('login.corsDocs') }}
</a>

<UButton :label="t('login.reset')" color="error" type="reset" />
<UButton
  v-if="inModal"
  :label="t('login.cancel')"
  color="neutral"
  type="button"
  @click="emitLoginResult(true)"
/>
<UButton :label="t('login.submit')" color="primary" type="submit" icon="mdi:login" />
```

- [ ] **Step 5: Migrate confirmation defaults**

Modify `G:\AI_Trading\freqtrade-cn\frequi\src\components\general\ConfirmDialogBox.vue`.

Replace the script block with:

```vue
<script setup lang="ts">
export interface ConfirmDialogBoxProps {
  title: string;
  description?: string;
  message: string;
  cancelText?: string;
  confirmText?: string;
}

const props = defineProps<ConfirmDialogBoxProps>();
const { t } = useAppI18n();

const modalDescription = computed(() => props.description ?? t('confirm.description'));
const cancelLabel = computed(() => props.cancelText ?? t('confirm.cancel'));
const confirmLabel = computed(() => props.confirmText ?? t('confirm.ok'));

defineEmits<{
  close: [value: boolean];
}>();
</script>
```

Replace the template labels:

```vue
<UModal :title="title" :ui="{ footer: 'justify-end' }" :description="modalDescription">
...
:label="cancelLabel"
...
:label="confirmLabel"
```

- [ ] **Step 6: Run focused tests and typecheck**

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

Both commands must exit with code `0`.

- [ ] **Step 7: Commit login and confirmation migration**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add src/components/BotLogin.vue src/components/general/ConfirmDialogBox.vue tests/unit/appI18n.spec.ts
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "feat: localize login and confirmation text"
```

Expected:

```text
[cn/i18n <sha>] feat: localize login and confirmation text
```

---

### Task 6: Add Playwright i18n Smoke Coverage

**Files:**
- Create: `G:\AI_Trading\freqtrade-cn\frequi\e2e\i18n.spec.ts`
- Modify if failing selectors require it: `G:\AI_Trading\freqtrade-cn\frequi\src\views\SettingsView.vue`

- [ ] **Step 1: Write the Playwright smoke test**

Create `G:\AI_Trading\freqtrade-cn\frequi\e2e\i18n.spec.ts` with:

```ts
import { test, expect } from '@playwright/test';
import { defaultMocks, setLoginInfo } from './helpers';

test.describe('Bilingual i18n', () => {
  test('defaults to bilingual labels and switches modes from settings', async ({ page }) => {
    await setLoginInfo(page);
    await defaultMocks(page);

    await page.goto('/trade');
    await expect(page.getByRole('link', { name: /Trade \/ 交易/ })).toBeVisible();

    await page.getByRole('button', { name: 'FT' }).click();
    await page.getByRole('menuitem', { name: /Settings/ }).click();
    await expect(page.getByText('FreqUI Settings / FreqUI 设置')).toBeVisible();

    await page.getByTestId('locale-mode-select').click();
    await page.getByRole('option', { name: /^English$/ }).click();
    await expect(page.getByRole('link', { name: /^Trade$/ })).toBeVisible();

    await page.getByTestId('locale-mode-select').click();
    await page.getByRole('option', { name: /English \/ Chinese/ }).click();
    await expect(page.getByRole('link', { name: /Trade \/ 交易/ })).toBeVisible();

    const settings = await page.evaluate(() =>
      JSON.parse(window.localStorage.getItem('ftUISettings') || '{}'),
    );
    expect(settings.localeMode).toBe('bilingual');
  });
});
```

- [ ] **Step 2: Run the i18n Playwright test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:e2e-chromium -- e2e/i18n.spec.ts
```

Expected:

```text
1 passed
```

If the test cannot find `data-testid="locale-mode-select"`, inspect `SettingsView.vue` and confirm the `USelect` for `settingsStore.localeMode` includes this exact attribute:

```vue
data-testid="locale-mode-select"
```

- [ ] **Step 3: Run existing settings smoke test**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:e2e-chromium -- e2e/settings.spec.ts
```

Expected:

```text
1 passed
```

If the settings test fails because it expects exact English text, replace exact selectors with regex selectors that still assert the English part. Example replacement:

```ts
await page.getByRole('menuitem', { name: /Settings/ }).click();
await expect(page.getByText(/FreqUI Settings/)).toBeVisible();
```

- [ ] **Step 4: Commit e2e coverage**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi add e2e/i18n.spec.ts e2e/settings.spec.ts src/views/SettingsView.vue
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "test: cover bilingual locale switching"
```

Expected:

```text
[cn/i18n <sha>] test: cover bilingual locale switching
```

---

### Task 7: Full Frontend Verification

**Files:**
- Verify only: `G:\AI_Trading\freqtrade-cn\frequi`

- [ ] **Step 1: Run unit tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run test:unit
```

Expected:

```text
All Vitest tests pass.
```

- [ ] **Step 2: Run typecheck**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run typecheck
```

Expected:

```text
vue-tsc --build --noEmit
```

Exit code must be `0`.

- [ ] **Step 3: Run lint**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run lint-ci
```

Expected:

```text
eslint --no-fix src tests e2e
```

Exit code must be `0`.

- [ ] **Step 4: Build FreqUI**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm run build
```

Expected:

```text
vite build
```

Exit code must be `0`, and `G:\AI_Trading\freqtrade-cn\frequi\dist` should be generated locally. Do not commit `dist`.

- [ ] **Step 5: Commit verification-only metadata if lint changed generated declarations**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi status --short
```

Expected preferred output:

```text
No modified tracked files from verification commands.
```

If `src/auto-imports.d.ts` or `src/components.d.ts` changed because the tooling regenerated imports, inspect the diff and commit only those generated declaration files:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi diff -- src/auto-imports.d.ts src/components.d.ts
git -C G:\AI_Trading\freqtrade-cn\frequi add src/auto-imports.d.ts src/components.d.ts
git -C G:\AI_Trading\freqtrade-cn\frequi commit -m "chore: update generated UI declarations"
```

Expected:

```text
[cn/i18n <sha>] chore: update generated UI declarations
```

---

### Task 8: Docker and Browser Verification

**Files:**
- Verify only: `G:\AI_Trading\freqtrade-cn\Dockerfile`
- Verify only: `G:\AI_Trading\freqtrade-cn\docker-compose.yml`
- Verify only: `G:\AI_Trading\freqtrade-cn\frequi`

- [ ] **Step 1: Build Docker image from top-level repository**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose build
```

Expected:

```text
freqtrade-cn image builds successfully.
The FreqUI build stage completes with the bilingual i18n changes.
```

- [ ] **Step 2: Start Docker container**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose up -d
docker compose ps
```

Expected:

```text
freqtrade-cn service is Up.
Host port maps to 127.0.0.1:8081 unless FT_UI_PORT overrides it.
```

- [ ] **Step 3: Verify UI manually in the browser**

Open:

```text
http://127.0.0.1:8081/trade
```

Expected visible labels:

```text
Trade / 交易
Dashboard / 仪表盘
Chart / 图表
Logs / 日志
```

Open Settings and verify:

```text
FreqUI Settings / FreqUI 设置
Language display / 语言显示
English / Chinese / 英文 / 中文
```

Switch to English and verify navigation shows:

```text
Trade
Dashboard
Chart
Logs
```

Switch back to bilingual and verify:

```text
Trade / 交易
```

- [ ] **Step 4: Verify raw trading data labels are not altered**

In the browser, confirm these values remain unlocalized if visible:

```text
BTC/USDT
ETH/USDT
SampleStrategy
RSI
MACD
```

Expected:

```text
Market symbols, strategy names, and indicator names remain unchanged.
```

- [ ] **Step 5: Stop follow logs after verification**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose logs --tail=80 freqtrade
```

Expected:

```text
No frontend asset 404 errors.
No server crash.
```

Leave the container running if the user wants to inspect the UI. Otherwise run:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose down
```

---

### Task 9: Publish Submodule Branch and Update Top-Level Pointer

**Files:**
- Commit in submodule: `G:\AI_Trading\freqtrade-cn\frequi`
- Modify in top-level repository: `G:\AI_Trading\freqtrade-cn\frequi` submodule pointer

- [ ] **Step 1: Confirm `frequi` branch is clean**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi status --short
git -C G:\AI_Trading\freqtrade-cn\frequi log --oneline --max-count=6
```

Expected:

```text
frequi working tree is clean.
Recent commits include the bilingual i18n implementation commits.
```

- [ ] **Step 2: Push the `frequi` implementation branch**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn\frequi push -u origin cn/i18n
```

Expected:

```text
Branch cn/i18n is available on origin.
```

If authentication fails, stop here and configure GitHub credentials before continuing. Do not commit the top-level pointer to an unpublished submodule commit.

- [ ] **Step 3: Commit the top-level submodule pointer**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn status --short
git -C G:\AI_Trading\freqtrade-cn add frequi
git -C G:\AI_Trading\freqtrade-cn commit -m "chore: pin bilingual FreqUI submodule"
```

Expected:

```text
[main <sha>] chore: pin bilingual FreqUI submodule
```

The existing untracked top-level Docker/runtime files should remain unstaged unless the user separately asks to commit them.

- [ ] **Step 4: Final status check**

Run:

```powershell
git -C G:\AI_Trading\freqtrade-cn status --short
git -C G:\AI_Trading\freqtrade-cn\frequi status --short
```

Expected:

```text
frequi is clean.
Top-level may still list only unrelated untracked Docker/runtime files from earlier work.
```

## Plan Self-Review Checklist

- Spec coverage:
  - Default bilingual display: Tasks 1, 2, 4, 6, 8.
  - English and Chinese modes: Tasks 2, 3, 6.
  - Settings persistence: Task 2.
  - Nuxt UI locale bridge: Task 3.
  - First migration slice: Tasks 3, 4, 5.
  - No backend localization: Scope notes and Docker verification tasks.
  - Docker reproducibility: Task 8.
  - Submodule publishing: Task 9.
- Type consistency:
  - `LocaleMode` is defined once in `src/locales/keys.ts`.
  - `settingsStore.localeMode` uses the same `LocaleMode` type.
  - `useAppI18n().t` accepts `LocaleKey`.
  - `resolveLocaleText` accepts `LocaleKey` and `LocaleMode`.
- Verification:
  - Unit tests cover resolver and settings-backed composable.
  - Playwright covers mode switching.
  - Typecheck, lint, build, Docker build, Docker runtime verification are included.
