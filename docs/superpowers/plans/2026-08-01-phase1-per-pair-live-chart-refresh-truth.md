# Phase 1 Per-Pair Live Chart Refresh Truth

**Status:** Implemented; acceptance Gate pending

**Design Gate:** PASS; P0 = 0, P1 = 0, P2 = 0

**Implementation Gate:** PASS; P0 = 0, P1 = 0, P2 = 0

**Scope:** FreqUI only; no backend API, market-data, strategy, Backtest, Runtime,
Paper, Live, deployment, or AI-worker changes

**Standing contract:** [Chart Data Source Rules](../../chart-data-source-rules.md)

## User problem

The accepted 8081 chart refreshes one-minute data approximately every ten seconds and
keeps the last successful response visible. That retention is useful during a transient
failure, but the current presentation is not truthful:

- every pair shares one `chartCandleDataStatus`;
- a failed refresh leaves the previous dataset visible without saying that refresh
  failed;
- whichever concurrent pair request finishes last determines the shared status; and
- every panel receives the first selected pair's `plot_config` and warnings.

As a result, an old chart can look current, and one pair's failure or presentation
metadata can be attributed to another pair. This is a source-boundary defect in the
existing Phase 1 watch journey, not a request for a new chart platform.

## Assumptions and decisions

1. The chart may retain the last successfully loaded dataset after a refresh failure.
   Removing it would make transient failures harder to inspect.
2. Retained data must be accompanied by a visible, pair-local warning that the latest
   refresh failed and the last successful data is being shown.
3. Display identity for this slice is the existing `${pair}__${timeframe}` dataset key.
   Candle mode and overlay options shape the request, but the store intentionally exposes
   one current dataset per pair and timeframe.
4. Different request shapes for the same display key may be in flight concurrently. A
   private, monotonically increasing generation per display key makes the latest started
   request authoritative. A superseded success or failure cannot modify data or status.
5. Loading, success, and error are tracked independently for each dataset key. A request
   for one key cannot change another key's state. When live keyed status is enabled but a
   key has not yet been requested, that panel resolves explicitly to `not_loaded`; it
   cannot fall back to the legacy bot-wide candle status.
6. Each panel consumes `plot_config` and backend warnings from its own response. The
   first selected pair may still provide the shared chart header and plot-configurator
   context; that shared control is not evidence about another panel's refresh result.
7. A successful later refresh clears that key's refresh-failure warning naturally by
   changing only that key's status to success.
8. This slice does not calculate an exact staleness duration. The plotted candle
   timestamps plus an explicit failure warning are sufficient for this defect; adding a
   clock or persistence contract would be speculative.

## Minimal implementation

1. Replace the bot-wide scalar live-chart status with a record keyed by
   `${pair}__${timeframe}`. Each non-deduplicated request receives the next private
   generation for that key; only the current generation may replace that key's data or
   status with `success` or `error`.
2. Expose that keyed status record from `useLiveChartDataset` without deriving a
   first-pair status, plot configuration, or warning string.
3. Make `CandleChartContainer` select status, `plot_config`, and warnings independently
   for each `SingleCandleChartContainer`. Resolve a missing key to `not_loaded` whenever
   the live status record was supplied.
4. When a key is `error` and still has a dataset, append a localized
   "refresh failed; showing last successful data" warning. When no dataset exists, keep
   the existing failed-to-load empty state.
5. Preserve the current ten-second one-minute schedule, request deduplication, forming
   candle semantics, strategy overlay source, and Signal/Trade separation.

## Acceptance criteria

1. After one successful response, a failed refresh of the same key leaves the old chart
   visible and shows a refresh-failure/retained-data warning on that panel.
2. For concurrent pair A and pair B requests, A success and B failure produce A success
   and B error regardless of completion order.
3. For the same pair/timeframe, a superseded request that completes after a newer
   differently shaped request cannot overwrite the newer data or status. Tests cover old
   success/new success, old failure/new success, and old success/new failure orderings.
4. A later successful B refresh clears only B's failure state and warning.
5. A newly selected live pair with no status entry is `not_loaded`, independent of the
   legacy bot-wide candle status.
6. Two pair responses with different `plot_config` and warnings render those values only
   in their respective panels.
7. A key with no successful dataset and an error continues to show the existing load
   failure empty state rather than a retained-data warning.
8. Existing one-minute refresh, hidden-tab pause/resume, forming-candle status,
   strategy-signal, tooltip, and execution-context tests remain green.
9. Focused Vitest, relevant chart suites, `pnpm typecheck`, `pnpm build`, changed-file
   ESLint, and `git diff --check` pass.
10. Backend and strategy submodules remain unchanged. No market, strategy, holdout,
   Backtest, Paper, or Live workload is run for acceptance.

## Explicit non-goals

- no backend schema or endpoint change;
- no raw ticks, faster polling, new WebSocket market stream, or HFT behavior;
- no exact age/freshness clock, persistence, alert daemon, or notification system;
- no coverage UI in this slice;
- no Decision Snapshot writer or identity expansion;
- no chart permalink, Observation Capsule, AI scheduler, Runtime, Paper, or Live work;
- no redesign of the shared plot configurator.

## Planned verification

```powershell
Set-Location frequi
pnpm vitest run tests/unit/ftbotChartCandles.spec.ts tests/unit/useLiveChartDataset.spec.ts tests/component/CandleChartContainerLiveData.spec.ts tests/component/SingleCandleChartContainer.spec.ts tests/component/ChartsViewLiveChart.spec.ts tests/component/TradingViewLiveChart.spec.ts tests/unit/appI18n.spec.ts
pnpm typecheck
pnpm build
```

Run the complete frontend chart-related Vitest set selected from changed ownership after
the focused tests. Acceptance uses mocks only; it does not start Docker or request market
data.
