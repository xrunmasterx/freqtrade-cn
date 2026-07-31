# Phase 1 Pair-History Context Truth

**Status:** Implemented; acceptance Gate pending

**Design Gates:** PASS; state model P0/P1 = 0, product P0/P1 = 0, test design
P0/P1 = 0

**Implementation Gates:** PASS; code P0/P1/P2 = 0, product/documentation P0/P1/P2 =
0, test P0/P1 = 0 with one non-blocking pre-existing Happy DOM teardown-noise P2

**Frontend implementation:** `69fa10cae618f7ed6cc8d19b7084ff9696845d64`

**Scope:** FreqUI `/pair_history` request state and historic-chart presentation only;
no backend API, market-data, strategy, Backtest execution, holdout, Runtime, Paper, Live,
or AI-worker change

## User problem

The historic chart display slot is currently keyed only by `pair + timeframe`, while a
`/pair_history` response also depends on strategy, timerange, FreqAI model, live mode,
exchange, trading mode, margin mode, and the requested columns.

Two normal user actions can therefore make the chart lie about its current context:

1. changing strategy or timerange updates the visible controls and title without
   invalidating the previously loaded dataset; and
2. starting two requests for the same pair/timeframe lets the earlier request overwrite
   the later one if it finishes last.

The same store path is used by 8081 `/graph` in webserver/history mode and the 8083
Backtest visualizer. This slice fixes that request/display boundary before the separate
Backtest source-disclosure slice labels historical Trades against current recomputation.

## First-principles invariant

For one visible historic-chart panel:

> The panel may accept only the latest request started for its `pair + timeframe` slot,
> and it may render a retained dataset only when that dataset's complete request context
> equals the context currently selected by the user.

`pair + timeframe` remains the display slot; it is not treated as the response identity.
The request identity covers every field in the current `PairHistoryPayload`:

```text
pair
timeframe
timerange
strategy
freqaimodel
columns
live_mode
exchange
trading_mode
margin_mode
```

This is frontend request identity only. It does not prove Backtest revision,
Strategy Evidence, DataSnapshot, Execution Context, StrategyRelease, or historical
reproducibility.

## Minimal design

1. Add one history-specific pure `getPairHistoryRequestKey(payload)` function. The
   store, chart components, and tests must use this same function instead of assembling
   keys independently. Its fixed field order is the ten fields listed above; it
   preserves the actual `columns` order, distinguishes `false` from missing values, and
   normalizes optional missing values consistently. This is not a generic request
   manager.
2. Keep one generation counter per `pair + timeframe` history slot. Only the latest
   generation may write data, success/error state, slow-request state, or a user alert.
3. Store the accepted request key beside each history dataset and the latest requested
   key beside each display slot.
4. Replace the single presentation status with per-slot history status and slow-request
   maps. Existing compatibility refs may remain, but historic chart panels must read
   their own slot.
5. Let each owning view construct the exact request context it will send and reuse that
   object for the network request and chart prop. The chart adds its panel pair,
   timeframe, and currently requested columns to produce `desiredKey`; it refuses a
   dataset whose accepted request key differs.
6. A settings change immediately hides a dataset from the old context. The 8081
   webserver chart keeps its existing explicit refresh interaction instead of adding an
   expensive automatic request for each timerange edit.
7. A failed refresh may retain and show data only from the same exact request context,
   with the existing visible refresh-failure warning. Data from another context stays
   hidden.
8. The existing reduced-column Plot Config behavior remains available. Raw accepted
   `all_columns`/`columns` metadata may be used only to decide that an explicit plot
   change needs a new request; a dataset still cannot render unless its complete request
   key matches the new desired key.

The panel derives presentation state as follows:

```text
desiredKey = current view context + panel pair + timeframe + current requested columns

visibleDataset =
  acceptedDataset.requestKey == desiredKey ? acceptedDataset : none

effectiveStatus =
  latestRequestedKey[slot] == desiredKey ? statusBySlot[slot] : not_loaded

effectiveSlow =
  latestRequestedKey[slot] == desiredKey ? slowBySlot[slot] : false
```

The owning `CandleChartContainer` computes this per panel and passes the filtered
dataset, effective status, effective slow state, and applicable warning explicitly to
`SingleCandleChartContainer`. Historic panels no longer read the bot-wide
`historyStatus` or `historyTakesLonger` as presentation authority. Those compatibility
refs may remain for non-panel callers only.

The per-slot request state machine is:

```text
start latest generation:
  latestRequestedKey[slot] = requestKey
  statusBySlot[slot] = loading
  slowBySlot[slot] = false

10-second timer, success, failure, and finally:
  mutate that slot only when the generation is still latest

success:
  accept response + requestKey; status = success; slow = false

failure:
  preserve prior accepted response; status = error; slow = false; show alert

stale success/failure/finally:
  do not mutate accepted data, status, slow state, warning, or alert
```

When `effectiveStatus` is `error`, the existing refresh-failure warning is shown with a
retained chart only if its accepted key also equals `desiredKey`. If no matching retained
dataset exists, the panel shows the current-context failure without any old chart. When
the current selection has not been requested, the effective state is `not_loaded`, not
`success/no data`, a previous error, or a previous slow request.

## Test-first acceptance criteria

1. Two deferred same-slot requests with different complete contexts prove
   latest-started-wins when the older request resolves last.
2. An older rejected request cannot replace a newer success state, show a stale alert,
   or control the newer request's slow indicator.
3. Two overlapping requests with the same complete key also prove latest-started-wins;
   an older same-key response cannot overwrite the newer accepted response.
4. Concurrent requests for different pairs keep success/error/slow states isolated.
5. Changing strategy, timerange, FreqAI model, live mode, exchange/modes, or requested
   columns makes the old dataset ineligible for rendering until the matching context is
   loaded; before refresh, effective status is `not_loaded` and no prior error/slow state
   or warning leaks into the panel.
6. Switching away from an in-flight or failed context to an already accepted context
   shows only that accepted context, without the other context's loading/error/slow state
   or warning.
7. A same-context refresh failure may keep the retained chart visible and must show the
   existing refresh-failure warning.
8. Missing pair/timeframe keeps the existing rejected-input behavior.
9. Existing live `/chart_candles`, reduced-column Plot Config refresh, chart metadata,
   indicators, Signals, Trades, and Backtest result data remain unchanged.
10. Focused unit/component tests, related chart tests, full FreqUI Vitest, typecheck,
   build, changed-file ESLint/Prettier, and `git diff --check` pass, subject only to
   explicitly recorded pre-existing baseline warnings outside this diff.
11. Backend and strategy submodules remain unchanged and clean.

The tests must exercise the real ownership boundaries, not only the key helper:

- `ftbotPairHistory.spec.ts` uses deferred POST responses to prove same-slot ordering,
  a real mocked Axios-error branch to prove a stale failure cannot alert, fake timers
  with staggered request starts to prove generation-aware slow state, separate pair
  slots, same-context retained data after failure, and independent invalid pair/timeframe
  rejection without any request or state mutation.
- `CandleChartContainerHistoricView.spec.ts` starts from one matching complete context
  and parameterizes each response-shaping field mismatch. It must prove the old dataset
  does not reach a real single-panel render, including the `undefined` versus `[]`
  columns boundary. It also proves per-panel status/slow isolation and the integrated
  same-context retained-data warning path.
- `ChartsViewLiveChart.spec.ts` proves that the 8081 webserver owner passes the same
  strategy, timerange, live/exchange/mode context to the chart that it sends through
  `getPairHistory`, with columns coming from the actual refresh event.
- `BacktestResultChartContext.spec.ts` proves the same owner invariant for the 8083
  Backtest visualizer, including FreqAI and trading/margin modes.
- `SingleCandleChartContainer.spec.ts` retains its focused presentation regressions,
  but hand-built props alone are not accepted as proof of context filtering.

Every deferred rejection is explicitly awaited. Tests must assert the accepted response
contents, not only call counts or key inequality. The slow-state test staggers the older
and newer request timers so the old 10-second deadline cannot make the slot slow while
the newer request's own deadline still can.

## Explicit non-goals

- no backend `/pair_history` schema or computation change;
- no AbortController platform, global cache rewrite, or generic request framework;
- no automatic request on every strategy/timerange form keystroke;
- no archived strategy execution or historical environment restoration;
- no claim that current `/pair_history` reproduces a selected historical Backtest;
- no result-bound analyzed-data snapshot in this slice;
- no market, strategy, Backtest, Lookahead, Recursive, retired-holdout, Paper, or Live run;
- no Experiment CRUD, RuntimeInstance, promotion, ranking, optimizer, or AI loop.

## Implemented verification

```powershell
cd frequi
pnpm vitest run tests/unit/ftbotPairHistory.spec.ts tests/component/CandleChartContainerHistoricView.spec.ts tests/component/SingleCandleChartContainer.spec.ts
pnpm vitest run tests/component/ChartsViewLiveChart.spec.ts tests/component/BacktestResultChartContext.spec.ts
pnpm vitest run
pnpm typecheck
pnpm build
pnpm eslint <changed TypeScript and Vue files>
pnpm prettier --check <changed TypeScript and Vue files>

cd ..
git diff --check
```

No product workload is required for this deterministic frontend state-boundary slice.

The final pre-commit implementation verification produced:

- five focused owner/store/container files with 43 passing tests;
- the full FreqUI suite with 51 files and 354 passing tests;
- passing `pnpm typecheck`, production build, changed-code ESLint, focused Prettier, and
  Root/FreqUI `git diff --check`;
- an explicit regression proving that an RSI response whose `all_columns` advertises
  MACD triggers the existing reduced-column refresh when the user selects MACD, while
  the RSI dataset remains hidden under the new desired request key.

The successful Vitest process retained the project's existing Happy DOM fetch-abort and
occasional `EPROTO` teardown output. Full-file Prettier inspection of `ftbot.ts` also
reports two pre-existing lines outside this slice's diff. They are recorded as baseline
waivers rather than being reformatted as unrelated cleanup; all other changed files pass
Prettier and no changed line introduces a formatting error.
