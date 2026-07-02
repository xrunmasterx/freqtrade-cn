# FreqUI Bilingual i18n Design

## Status

Approved for design by the user on 2026-07-03.

## Goal

Add a long-term, interactive bilingual Chinese/English display mode to FreqUI, with bilingual mode enabled by default, while keeping Freqtrade backend code unchanged and preserving a Docker-first workflow that works on Windows and macOS.

## Assumptions

- The product target is `G:\AI_Trading\freqtrade-cn`.
- The UI implementation target is the `frequi` submodule.
- The default user experience should show both English and Simplified Chinese, for example `Trade / 交易`.
- Users should also be able to switch to English-only or Simplified-Chinese-only display from the settings page.
- Docker remains the primary reproducible runtime path.
- Freqtrade backend logs, API raw errors, exchange names, trading pairs, strategy names, and indicator names should not be translated.

## Non-Goals

- Do not modify `G:\AI_Trading\freqtrade-cn\freqtrade` for ordinary UI localization.
- Do not modify generated `frequi/dist` assets directly.
- Do not rely on browser translation, DOM injection, extensions, reverse proxy rewriting, or runtime static-file patching as the product solution.
- Do not localize URLs. Existing routes such as `/trade`, `/graph`, and `/settings` remain unchanged.
- Do not translate backend logs, raw API error payloads, market symbols, strategy names, exchange names, or technical indicator identifiers.

## Recommended Architecture

Use a lightweight app-owned i18n layer inside `frequi`.

The i18n layer exposes a typed `t(key)` API that returns text according to a persisted display mode:

```ts
type LocaleMode = 'bilingual' | 'zh-CN' | 'en';
```

Expected behavior:

```ts
t('nav.trade') // bilingual: "Trade / 交易"
t('nav.trade') // zh-CN: "交易"
t('nav.trade') // en: "Trade"
```

This keeps bilingual display as a first-class behavior instead of bolting it onto a single-language i18n library. The structure remains compatible with a later migration to `vue-i18n` if upstream contribution becomes a priority.

## File Boundaries

### Locale Data

Create:

```text
G:\AI_Trading\freqtrade-cn\frequi\src\locales\en.ts
G:\AI_Trading\freqtrade-cn\frequi\src\locales\zh-CN.ts
G:\AI_Trading\freqtrade-cn\frequi\src\locales\keys.ts
```

Responsibilities:

- `en.ts` contains the canonical English UI strings.
- `zh-CN.ts` contains Simplified Chinese translations.
- `keys.ts` defines typed translation keys derived from the English source object so components do not use arbitrary untracked strings.

Example locale shape:

```ts
export const en = {
  nav: {
    trade: 'Trade',
    dashboard: 'Dashboard',
    chart: 'Chart',
    logs: 'Logs',
    settings: 'Settings',
  },
  settings: {
    title: 'FreqUI Settings',
    uiSettings: 'UI settings',
  },
} as const;
```

### Translation API

Create:

```text
G:\AI_Trading\freqtrade-cn\frequi\src\composables\useAppI18n.ts
```

Responsibilities:

- Read `settingsStore.localeMode`.
- Return English, Simplified Chinese, or bilingual display strings.
- Fall back to English when the Chinese translation is missing.
- Avoid rendering empty strings, raw keys, or `undefined`.
- Emit development-only warnings for missing Chinese translations when helpful.

### Settings Store

Modify:

```text
G:\AI_Trading\freqtrade-cn\frequi\src\stores\settings.ts
```

Add:

```ts
export type LocaleMode = 'bilingual' | 'zh-CN' | 'en';
const localeMode = ref<LocaleMode>('bilingual');
```

The existing Pinia persisted-state setup already persists UI settings, so language mode can be stored with the same mechanism.

### Nuxt UI Locale Bridge

Modify:

```text
G:\AI_Trading\freqtrade-cn\frequi\src\App.vue
```

Responsibilities:

- Continue to render FreqUI business strings through `t(key)`.
- Pass the matching Nuxt UI locale to `<UApp>`.
- Use Nuxt UI `zh_cn` for `bilingual` and `zh-CN`.
- Use Nuxt UI `en` for `en`.

This separates app-owned business copy from component-library internal copy.

### Settings UI

Modify:

```text
G:\AI_Trading\freqtrade-cn\frequi\src\views\SettingsView.vue
```

Add a language display setting:

```text
Language display / 语言显示
- English
- 简体中文
- English / 中文
```

Default selection is `English / 中文`, backed by `localeMode = 'bilingual'`.

## First Migration Slice

Migrate high-frequency UI first:

```text
G:\AI_Trading\freqtrade-cn\frequi\src\components\layout\NavBar.vue
G:\AI_Trading\freqtrade-cn\frequi\src\components\layout\NavFooter.vue
G:\AI_Trading\freqtrade-cn\frequi\src\views\SettingsView.vue
G:\AI_Trading\freqtrade-cn\frequi\src\components\BotLogin.vue
G:\AI_Trading\freqtrade-cn\frequi\src\components\general\ConfirmDialogBox.vue
```

This covers first-load navigation, login, settings, and confirmation dialogs without touching the whole UI at once.

Later migration slices should cover:

1. Trade page tables, force entry/exit controls, pairlist UI, and common toast messages.
2. Backtesting, download data, pairlist configuration, recursive analysis, and lookahead analysis.
3. Chart titles, legends, tooltips, and metric labels where the text is clearly UI-owned.

## Runtime Data Flow

1. The app starts.
2. `settingsStore.localeMode` loads from persisted Pinia state.
3. If no persisted value exists, `localeMode` defaults to `bilingual`.
4. Components call `useAppI18n()` and render labels through `t(key)`.
5. `t(key)` reads English and Chinese locale values.
6. `t(key)` returns English, Chinese, or `English / 中文` depending on `localeMode`.
7. Settings UI changes update `localeMode` immediately.
8. Vue reactivity updates migrated labels without a page refresh.
9. `App.vue` updates Nuxt UI locale according to the same mode.

## Missing Translation Behavior

English is the canonical complete language. Simplified Chinese can be incomplete during migration.

Rules:

- `en` mode always returns the English string.
- `zh-CN` mode returns Chinese when available and falls back to English when missing.
- `bilingual` mode returns `English / 中文` when both are available.
- `bilingual` mode returns only English when Chinese is missing.
- Production UI must not display translation keys, `undefined`, or empty fallback text.

## Publishing Strategy

Long-term source ownership:

```text
freqtrade-cn top-level repository:
  Dockerfile, docker-compose.yml, README, config examples, submodule pinning

frequi submodule:
  i18n infrastructure, locale files, migrated UI text

freqtrade submodule:
  unchanged for ordinary UI localization
```

Recommended `frequi` fork workflow:

```text
official freqtrade/frequi main
  -> merge into xrunmasterx/frequi cn/i18n
  -> run tests and build
  -> update freqtrade-cn frequi submodule SHA
```

Patch files may be exported for review or emergency use, but should not be the source of truth for ongoing i18n development.

## Docker Strategy

Keep the current Docker build direction:

1. Build `frequi` from source in the Node builder stage.
2. Generate `dist`.
3. Copy `dist` into `/freqtrade/freqtrade/rpc/api_server/ui/installed`.
4. Serve the UI through Freqtrade's existing API server static route.

This means Windows and macOS users only need Docker and initialized submodules. They do not need host Node.js, pnpm, browser extensions, or manual UI asset copying.

## Testing Strategy

### Unit Tests

Test `useAppI18n` behavior:

- `bilingual` returns `English / 中文`.
- `zh-CN` returns Simplified Chinese.
- `en` returns English.
- missing Chinese falls back to English.
- missing values never render `undefined`.

Test settings behavior:

- default `localeMode` is `bilingual`.
- changing `localeMode` updates computed translations.

### E2E Smoke Tests

Add a small Playwright smoke path:

1. Open `/trade`.
2. Verify default navigation displays bilingual labels such as `Trade / 交易`.
3. Open `/settings`.
4. Switch to `English`.
5. Verify navigation displays English-only labels.
6. Switch back to `English / 中文`.
7. Verify bilingual labels return without page refresh.

### Manual Browser QA

Verify desktop and mobile-width layouts for:

- nav bar
- mobile nav footer
- login form
- settings page
- confirmation dialog

The highest visual risk is text expansion in navigation, narrow buttons, and table headers.

## Acceptance Criteria

- Docker build succeeds.
- Docker container starts and serves FreqUI at the configured local port.
- A fresh browser session shows bilingual UI by default.
- Settings page can switch between `English`, `简体中文`, and `English / 中文`.
- Switching mode updates migrated UI text without a page refresh.
- Refreshing the browser preserves the selected display mode.
- Login, navigation, settings, and confirmation dialog core text are migrated in the first slice.
- Unmigrated pages remain functional and show English.
- Trading pairs, strategy names, indicator names, logs, and backend raw errors remain unmodified.
- Freqtrade backend source is not changed for this feature.
- Generated `dist` files are not edited directly.

## Risk Controls

- Migrate the UI in slices to avoid a broad, hard-to-review diff.
- Keep all translated text in locale files instead of writing bilingual strings directly in components.
- Keep URLs, backend API contracts, and backend runtime behavior unchanged.
- Use English fallback so partial migration cannot break screens.
- Use browser screenshots or Playwright checks for narrow layouts before expanding the migration to table-heavy screens.

## Implementation Sequence

1. Add locale files and typed key support.
2. Add `localeMode` to settings store.
3. Add `useAppI18n`.
4. Bridge Nuxt UI locale in `App.vue`.
5. Add language display control in Settings.
6. Migrate NavBar and NavFooter.
7. Migrate BotLogin and ConfirmDialogBox.
8. Add focused unit tests and E2E smoke coverage.
9. Build FreqUI.
10. Build and run Docker image.
11. Verify the UI in the browser.

## Confirmed Design Choices

- Use `cn/i18n` as the recommended `frequi` fork branch name.
- Keep bilingual separator as ` / ` for the first implementation.
- Keep English first in bilingual mode, for example `Trade / 交易`, to preserve terminology alignment with upstream documentation.
