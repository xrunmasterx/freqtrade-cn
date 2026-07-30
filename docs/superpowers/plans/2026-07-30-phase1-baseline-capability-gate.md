# Phase 1 Baseline Capability Gate

**Status:** Active; working-tree compatibility journeys passed, exact-SHA receipt pending

**Decision date:** 2026-07-30

**Working branch:** `phase1-baseline-capability-gate`

**Starting identities:**

| Repository | Starting commit |
|---|---|
| Root | `f69c69edf023e435c50103fd5dbcb4c987309ec2` |
| Backend `freqtrade/` | `b9345c4a65e57c9bcb62635d13be2c2190e0876f` |
| Frontend `frequi/` | `09b235d863471871d54558e1d31cd7091ae2b79e` |
| Strategies | `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4` |

**Product authority:** [../STRATEGY.md](../STRATEGY.md)

**Chart authority:** [../../chart-data-source-rules.md](../../chart-data-source-rules.md)

## Goal

Prove that the repository still provides its minimum useful strategy-validation loop
before any new Experiment, dynamic Runtime, Paper Observation, Runtime Access, or cutover
work resumes.

This is one product Gate across two existing compatibility services:

~~~mermaid
flowchart LR
    U[Local strategy researcher]
    U --> G[8081 /graph]
    U --> T[8081 /trade]
    U --> B[8083 /backtest]
    U --> A[8083 Lookahead and Recursive]
    G --> E[Exact-SHA baseline receipt]
    T --> E
    B --> E
    A --> E
    E --> D{Explicit one-journey decision}
~~~

8081 is the existing preconfigured dry-run Spot compatibility service. It is not a fixed
Bot domain model, a Registry RuntimeInstance, or formal dynamic Paper acceptance. 8083 is
the existing webserver-mode compatibility service used for standard Freqtrade offline
validation; its `/research` SMA calculation is not the accepted backtest engine.

## Required user outcomes

| Outcome | P0 acceptance |
|---|---|
| Minute-candle watch | 1m is selectable; live requests retain the Forming Candle and use the normal approximately 10-second cadence while active and visible |
| Strategy indicators | Strategy `plot_config` series render from analyzed strategy output; missing strategy data is never replaced with Watch Indicator data |
| Strategy signals | Entry/exit points render only from closed-candle strategy evidence and are not forward-filled |
| Execution evidence | Paper/backtest execution markers use recorded/simulated time and price, remain separate from signals, and are hidden when strategy context does not match |
| Authoritative backtest | 8083 runs the standard Freqtrade backtest and presents an inspectable result summary, trades, and chart; retained history/load and multi-result comparison must not regress but are not P0 reasons to manufacture extra runs |
| Supporting analysis | Lookahead and Recursive Analysis start, complete, and render their result contracts on the webserver-mode compatibility service |
| Safety | No Live environment, real order, exchange write, credential disclosure, listener removal, or destructive state action occurs |

A trade does not need to occur during the live observation window. Deterministic tests
may prove the execution-marker presentation.

## Source and candle semantics

1. The live Market layer may update the final Forming Candle.
2. Watch Indicators may calculate on that row but are provisional observation.
3. Strategy Indicators and Strategy Signals originate from the strategy analyzed-data
   contract and use closed source candles only.
4. An alignment carry-forward may display the last closed strategy-indicator value on a
   finer chart timeframe; it must not create a new forming-candle strategy evaluation.
5. Strategy Signals align by exact candle open and are never forward-filled.
6. Execution Markers originate from persisted Paper evidence or simulated backtest
   evidence; they are never synthesized from signal columns.
7. A mismatched strategy/revision/release context suppresses execution evidence rather
   than displaying a plausible but false comparison.

## Current evidence and gaps

### Verified automatically on 2026-07-30

- Backend chart composition/indicator suites: 62 passed.
- Forming Market and Watch series are marked `provisional=true`; closed observation and
  Strategy series remain non-provisional.
- Backend chart/backtest/analysis API selection: 17 passed, 92 deselected; one existing
  Starlette TestClient deprecation warning.
- Backend Ruff check for `freqtrade/rpc` and `tests/rpc`: passed.
- Frontend focused chart and locale suites: 13 files, 98 tests passed. Happy DOM emitted
  teardown `AbortError`/`EPROTO` noise after an earlier successful run; the final run
  completed without that teardown output.
- Frontend `pnpm typecheck`: passed.
- Changed-file frontend ESLint with `--quiet`: passed.
- Frontend production build: passed; third-party pure-annotation warnings did not fail
  the build.
- Local fully mocked Chromium journeys: four passed, covering a completed standard
  backtest result becoming visible plus Lookahead and Recursive Analysis. The existing
  background-job mock emitted non-failing `data is not iterable` console noise.

These checks prove the scoped code paths and local mocked browser contracts. Real
compatibility-service evidence is recorded below, but it still requires a committed
image rerun before it becomes the exact-SHA runtime receipt.

### Verified on real compatibility services on 2026-07-30

- Only `freqtrade` on 8081 and `freqtrade-research` on 8083 were built and started; both
  became healthy and authenticated. 8081 reported `dry_run=true`, Spot, OKX,
  `SampleStrategy`, and 1m. 8083 reported the Research webserver identity with no
  preselected strategy.
- 8081 `/graph` issued three live 1m chart requests at approximately ten-second
  intervals. Consecutive API observations advanced the Forming Candle; its Market and
  Watch series were provisional, while official strategy output remained closed-candle
  evidence. The chart rendered strategy indicators and entry/exit points with the
  observation-only status visible.
- 8081 `/trade` retained the preconfigured Spot compatibility-service journey. Runtime
  Trade markers remained a separate source from Strategy Signals; deterministic tests
  cover mismatch suppression because no live Paper trade was required or manufactured.
- 8083 loaded `SampleStrategy` through the fixed read-only strategy mount and completed a
  standard Freqtrade 5m backtest over local fixture data for
  `20251124-20251204`. The UI rendered the summary, one simulated trade, result chart,
  trade navigation, and retained history/load entry.
- Lookahead Analysis completed with no reported bias after explicitly allowing the
  strategy's configured limit orders. Recursive Analysis completed for startup candle
  counts 50, 100, and 200 and returned 15 indicators.
- Non-secret screenshots and runtime result artifacts were retained in the ignored local
  acceptance directory. No Live service, real order, exchange write, listener change,
  state migration, or second backtest engine entered the acceptance.

### Remaining Gate gaps and compatibility limits

1. The compatibility-service browser journeys passed from the reviewed working tree, but
   its image was built before the final commits. Rebuild and recheck the committed image,
   then record the exact Root/backend/frontend/strategy SHAs and image ID. Exact
   provenance—not Docker availability or journey behavior—is the remaining Gate blocker.
2. Gate A trade filtering uses the strongest compatibility fields currently exposed by
   both sides: strategy name and, when available, timeframe. It suppresses explicit
   mismatches and retains Trades missing either field for backward compatibility. A
   match or legacy fallback does not prove an exact revision/release match or formal
   Paper acceptance.
3. The real 8083 journey proved the full result summary, trade navigation, chart
   visualization, and retained history/load entry. Only one result was needed, so
   multi-result comparison was intentionally not manufactured; its existing automated
   compatibility coverage remains the scoped evidence.
4. Happy DOM, third-party annotation, line-ending, and incomplete background-job mock
   warnings are retained as test-harness noise; none failed a command. They are not
   silently promoted to product defects or fixed outside this Gate.

### Corrected topology fact

8081 runs Freqtrade `trade` mode. The backend intentionally rejects standard backtest,
Lookahead, and Recursive APIs there with HTTP 503. Those capabilities belong to the
existing 8083 `webserver` mode for Gate A. A same-origin or single-port redesign is
outside this Gate.

## Execution plan

### Task 0: Establish authority and terminology

- [x] Record the product purpose, page responsibilities, and two-gate Phase 1 strategy.
- [x] Record shared domain terms and signal-versus-execution semantics.
- [x] Pause Phase 2D Tasks 5-8, Phase 2E, Experiment, dynamic Runtime, and Paper
  Observation without deleting completed assets or historical plans.
- [x] Verify every active-status document and link after the documentation diff.

### Task 1: Close only the automated P0 gaps

Focused tests were written before behavior changes:

1. [x] backend live composition: final Forming Candle cannot produce a new Strategy
   Signal or consume a forming strategy-indicator row as official output;
2. [x] backend trust metadata: forming Market and Watch series are provisional while
   closed observation and Strategy output are not;
3. [x] frontend trust state: the visible live status labels a Forming Candle as
   observation/watch-only and removes the label after close;
4. [x] frontend chart: runtime Trades and Strategy Signals remain separate series;
5. [x] frontend context: an explicit strategy-name or available-timeframe mismatch is
   not passed to the chart and produces a visible hidden-marker count, while legacy
   Trades missing context retain compatibility;
6. [x] frontend backtest: a completed standard Freqtrade result enters a visible result
   view in the existing mocked browser journey.

Implement only the smallest changes required by those tests. Do not add a new API,
runtime abstraction, page, backtest engine, or generalized evidence framework.

Task 1 is complete. The implementation added no new API, domain model, page, runtime
abstraction, or backtest engine.

### Task 2: Run the offline automated gate

From `freqtrade/`:

~~~powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_chart_data.py tests/rpc/test_chart_composition.py tests/rpc/test_chart_indicators.py -q -p no:cacheprovider
.\.venv\Scripts\python -m pytest tests/rpc/test_rpc_apiserver.py -k "chart_candles or backtesting or backtest_history or lookahead_analysis or recursive_analysis" -q -p no:cacheprovider
.\.venv\Scripts\python -m ruff check freqtrade/rpc tests/rpc
~~~

From `frequi/`:

~~~powershell
pnpm vitest run tests/unit/tradeChartRefresh.spec.ts tests/unit/useLiveChartDataset.spec.ts tests/unit/ftbotChartCandles.spec.ts tests/unit/candleChartSeries.spec.ts tests/unit/chartSeriesMeta.spec.ts tests/unit/candleChartTooltip.spec.ts tests/component/ChartsViewLiveChart.spec.ts tests/component/TradingViewLiveChart.spec.ts tests/component/CandleChart.spec.ts tests/component/CandleChartCrosshair.spec.ts tests/component/SingleCandleChartContainer.spec.ts tests/component/CandleChartContainerHistoricView.spec.ts
pnpm typecheck
pnpm build
~~~

Run focused browser tests only against mocked/local fixtures. Compatibility-service
startup and external reads belong to Task 3 and its prerequisites:

~~~powershell
pnpm exec playwright test e2e/backtest.spec.ts e2e/analysis.spec.ts --project=chromium
~~~

Task 2 completed on 2026-07-30 with the results recorded above. Service-backed evidence
remains intentionally separate in Task 3.

### Task 3: Run the compatibility-service browser gate

Prerequisites:

- Docker CLI/runtime is available.
- Runtime secrets pass the existing operations runbook.
- Any public exchange read is explicitly authorized.
- Exact component SHAs and dry-run/Spot configuration are recorded without secret values.

Then:

1. [x] build and start only `freqtrade` and `freqtrade-research`;
2. [x] verify bounded health and authenticated login;
3. [x] on 8081 `/graph`, select 1m and observe at least two scheduled refreshes;
4. [x] verify Forming Candle behavior, strategy indicators, and closed-candle signal
   points on the real service; verify separately styled and context-filtered execution
   markers deterministically because no live Paper trade is required;
5. [x] on 8081 `/trade`, verify the service identity is dry-run Spot and observation/control
   behavior is unchanged;
6. [x] on 8083 `/backtest`, run one local-data standard Freqtrade backtest and inspect its
   result summary, trades, and chart; confirm the retained history/load entrypoint, and
   inspect comparison only if two results already exist;
7. [x] run Lookahead and Recursive Analysis against the same strategy/data context;
8. [ ] stop the two services using the existing non-destructive runbook and retain a
   non-secret receipt.

Do not require a live Paper trade, use `/research` as backtest evidence, call a real
order path, remove a listener, or migrate state.

Steps 1-7 passed on the reviewed working tree. Repeat the bounded smoke checks against
the committed image before completing step 8; do not substitute the earlier dirty-image
run for exact-SHA evidence.

### Task 4: Record the Gate receipt and choose one next journey

The receipt records:

- exact Root/backend/frontend/strategy SHAs;
- configuration identity and `dry_run=true`/Spot facts without secrets;
- automated commands and results;
- the two compatibility origins and observed routes;
- screenshots for strategy indicators, signals, execution markers, and backtest results;
- all warnings, skipped online steps, and unresolved defects.

After a pass, stop. Update the current-status index and make one explicit roadmap
decision. Do not automatically resume an old plan.

## Stop conditions

Stop scope expansion and fix only the root baseline defect if:

- market/watch/strategy/execution sources are substituted or visually conflated;
- a Strategy Signal appears on a Forming Candle;
- unrelated strategy trades are overlaid;
- the standard Freqtrade backtest cannot complete or its result cannot be inspected;
- dry-run/Spot identity, authentication, health, or exact provenance cannot be proven.

Request a new roadmap decision if a proposed fix requires 8090, Runtime Registry,
Supervisor production assembly, Experiment UI, dynamic Runtime, Paper Observation,
Research expansion, listener removal, or a second backtest engine.

## Definition of done

- every Required user outcome has deterministic automated evidence and an exact-SHA
  compatibility-service receipt;
- the Gate has no unresolved P0 defect;
- 8081 evidence is labelled compatibility watch/runtime evidence, not formal Paper;
- 8083 standard Freqtrade backtest evidence is not confused with the simplified Research
  SMA calculation;
- no new platform feature or Live authority entered the diff;
- one explicit next-journey decision is recorded.
