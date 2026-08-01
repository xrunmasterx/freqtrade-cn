# Phase 1 Backtest Effective Window Binding

**Status:** Implemented; acceptance receipt pending

**Scope:** FreqUI selected-result Backtest chart timerange ownership, an explicit actual-window
label, exact English and Chinese locale copy, focused component/locale tests, and lifecycle
documentation only; no backend, API, result artifact, market-data, strategy, Runtime, Paper,
Live, or AI change

**Standing contract:** [Chart Data Source Rules](../../chart-data-source-rules.md)

## User problem

The accepted Backtest chart correctly states that its Trades come from the selected result while
its candles, indicators, Signals, and annotations are current recomputation. However, that current
reference chart still requests `backtestResult.timerange`, which is the original requested range.
It may be open-ended or wider than the interval Freqtrade actually scored after startup trimming
and data admission.

As local history grows, an old result with an open-ended request can therefore reopen on candles
that occurred after the Backtest ended. The result-owned Trade markers remain historical and may
all be outside the visible data. The header also calls the requested range the chart timerange even
though the result already contains the concrete effective bounds in `backtest_start_ts` and
`backtest_end_ts`.

This is a review correctness defect, not a missing replay platform. The permanent mixed-source
warning remains true and is not weakened by narrowing the current reference data to the actual
scored window.

## First-principles invariant

> When a selected Backtest result provides an unambiguous effective scored window, that one window
> must own both the reference-chart request and its visible label. When the window is ambiguous,
> the UI must preserve the legacy request and must not call it the actual Backtest window.

## Verified protocol facts

- Strategy result `backtest_start_ts` and `backtest_end_ts` are emitted as Unix milliseconds.
- Freqtrade `TimeRange` accepts a pair of 13-digit timestamp values and converts each to seconds.
- Pair-History trimming includes both the start and stop candle, matching the result's first and
  last scored candle timestamps. No extra candle is added to either end.
- The parser's millisecond conversion discards sub-second remainder. Exact mapping therefore
  requires second-aligned input; guessing or rounding would create a different window.
- The existing timezone-bearing formatter renders the configured display timezone while the
  request remains timezone-independent numeric identity.

## Minimal product contract

`BacktestResultChart` derives one local effective-window value from the selected result.

The actual result window is usable only when both bounds atomically satisfy every condition:

1. each value is a JavaScript number and a safe integer;
2. each value is a positive 13-digit Unix-millisecond value;
3. each value is exactly second-aligned (`value % 1000 === 0`);
4. each value produces a valid JavaScript `Date`; and
5. `backtest_start_ts < backtest_end_ts`.

When valid:

- `PairHistoryRequestContext.timerange` is exactly
  `<backtest_start_ts>-<backtest_end_ts>`;
- that same computed value therefore owns the existing Pair-History request key and refresh;
- the header says `Actual Backtest window` and renders both endpoints with the existing
  timezone-bearing formatter, reacting to configured timezone changes without changing the
  numeric request; and
- the strategy name remains visible beside the window.

When either endpoint fails any condition, the whole actual-window interpretation fails closed:

- the request continues to use `backtestResult.timerange` unchanged;
- the header continues to use the existing `Timerange` label and value; and
- no endpoint is rounded, unit-guessed, combined with the other source, or labelled actual.

The existing permanent mixed-source warning, selected-result Trades, strategy, timeframe, FreqAI
presence semantics, trading mode, margin mode, forced POST behavior, explicit-no-FreqAI capability
guard, Plot Config columns, user-selected pair, and exchange ownership remain unchanged.

## Rejected alternatives

- **Exact historical chart snapshot:** retained Backtest data currently preserves OHLCV, not the
  analyzed indicator, Signal, or annotation output. Expanding the artifact schema, versioning,
  size limits, and replay capability is disproportionate to this defect and would still need the
  source disclosure.
- **Use the original request forever:** an open-ended range changes meaning as local history grows
  and can put all historical Trades outside the reviewed data.
- **Convert the bounds to `yyyyMMdd`:** date-only serialization can widen an intraday scored
  interval and loses exact candle identity.
- **Guess seconds versus milliseconds or round fractional seconds:** either can silently request a
  different interval. Ambiguous values use the legacy fallback instead.
- **Fix stale result-pair selection at the same time:** that is a separate P2 state-ownership issue
  and is not required to restore time-window truth.

## Test-first acceptance criteria

1. A focused component test first fails because a valid result still sends its original requested
   timerange. It then proves one valid, second-aligned 13-digit result window owns the chart request,
   request refresh, and actual-window header.
2. The header uses the configured non-UTC timezone and visibly includes its timezone. Changing
   that setting while the component remains mounted updates the label while the numeric request
   stays unchanged.
3. A focused fallback matrix covers missing/null or non-number input, unsafe or non-finite input,
   non-13-digit input, sub-second input, equal endpoints, reversed endpoints, and preserves the
   original request and legacy label for each case.
4. Existing tests continue to prove the permanent mixed-source warning, selected-result Trades,
   all other result-owned request fields, forced POST behavior, and old-backend no-FreqAI guard.
5. Exact English, Chinese, and bilingual locale resolution for the new label is covered.
6. Frontend typecheck, changed-file lint, and production build pass.

## Explicit non-scope

- no backend, API version, schema, route, database, or artifact change;
- no exact historical indicators, Signals, annotations, strategy-code execution, or replay claim;
- no new market-data request beyond narrowing the existing user-triggered reference request;
- no pair-selection repair, generalized timerange utility, store, or platform abstraction;
- no strategy candidate, market-data run, Backtest run, holdout use, promotion, Paper, Live,
  Runtime, autonomous worker, or AI model call; and
- no claim of profitability, reproducibility, promotion eligibility, or exact historical replay.

## Verification commands

Run from `frequi/`:

```powershell
pnpm vitest run tests/component/BacktestResultChartContext.spec.ts tests/unit/appI18n.spec.ts
pnpm eslint src/components/ftbot/BacktestResultChart.vue src/locales/en.ts src/locales/zh-CN.ts tests/component/BacktestResultChartContext.spec.ts tests/unit/appI18n.spec.ts
pnpm typecheck
pnpm build
```

No exchange, user market data, strategy candidate, retired holdout, Backtest workload, Paper,
Live, or Runtime execution is authorized by this plan.
