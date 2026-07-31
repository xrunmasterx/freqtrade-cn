# Phase 1 Recursive Analysis Truthfulness Repair

**Status:** Implementation complete; exact-SHA acceptance pending

**Product authority:** [Product Strategy and Delivery Policy](../STRATEGY.md)

**Triggering evidence:**
[VolatilitySystem Breakout-Episode Risk Calibration Rejection](../reports/2026-08-01-volatility-breakout-episode-risk-calibration-rejection.md)

## User problem

The existing Recursive Analysis implementation and FreqUI can overstate what one run
proved in two concrete ways:

1. the backend stops checking later startup-candle profiles when an earlier profile has
   no final-row indicator difference, so a later profile can be silently omitted;
2. when the sparse result map is empty, FreqUI displays a green success alert saying
   that no recursive formula issue was detected, even though the analysis compared only
   indicator values at one final analyzed candle.

The user needs the existing result to answer only the question it actually evaluated:

> Which tested startup-candle profiles reported an indicator difference at this
> Recursive Analysis run's final analyzed candle?

This repair does not attempt to answer whether signals were stable throughout the
timerange. The latest rejected strategy study directly confirmed three specific intraday
mismatch witnesses among 8,760 scored development rows; it did not certify that these
were the only mismatches. A comparison of only the run's final raw-signal row would not
answer that full-window question and would often compare four inactive flags. Adding an
API field, capability, checkbox, and result state for that low-information sample is
therefore rejected for this slice.

## Assumptions and tradeoffs

- Freqtrade remains the analysis authority; no second indicator or signal engine is
  introduced.
- The current indicator percentage calculation, reference frame, selected pair, route,
  background job, request, and response schema remain unchanged.
- Every startup-candle profile already materialized by Recursive Analysis must be checked
  independently. A match at one profile does not logically prove that a later profile
  matches, especially when finite-window and resampling alignment can differ.
- An empty sparse result means only that this run reported no final-row indicator
  differences for the profiles it tested. It is not a strategy-level pass and does not
  cover entry/exit signals.
- The smallest correct fix is one backend control-flow correction plus truthful frontend
  presentation. It does not justify a new API version or a new user option.

## Scope

Backend:

- change the no-difference branch in `RecursiveAnalysis.analyze_indicators()` so it
  continues to every remaining partial profile instead of leaving the loop;
- add a focused regression test where an earlier profile matches the reference and a
  later profile differs;
- retain the current sparse result representation and percentage semantics;
- clarify in the Recursive Analysis documentation that all tested profiles are evaluated
  at the final row and that empty output has only that bounded meaning.

FreqUI:

- keep the existing Recursive Analysis route, form, store, request, result type, and
  table;
- replace the empty-result success alert with a neutral information alert and remove the
  success checkmark;
- state that no final-candle indicator differences were reported for the tested profiles;
- keep a permanently visible explanation that only one final analyzed candle and
  indicators were compared, not historical signals, orders, trades, Paper, Live, or
  profitability;
- show the complete `startup_candles` list in both empty and non-empty result states, and
  explain that `-` means an evaluated profile reported no final-row difference for that
  indicator rather than that the profile was skipped;
- label `strategy_scc` as the strategy-declared startup-candle count, not a recommendation
  made by Recursive Analysis;
- scope the non-empty warning title to final-candle indicator differences as explicitly
  as the empty state;
- correct any result copy that describes the reference as the profile with the most
  startup candles when it is actually the run's materialized reference frame;
- add focused English, Chinese, and component regression coverage.

Root documentation:

- keep the completed Breakout-Episode rejection as the latest strategy-research
  authority and keep the holdout unopened;
- record this repair as the only active implementation entrypoint;
- retain full-window exact signal parity as a separately preregistered research Gate for
  any future candidate intended for a restartable Runtime, Paper, or Live path, unless a
  separately accepted state-restoration contract proves equivalent decision state across
  restart. Omitting restart stability from a candidate document is not an exemption.

## Acceptance

- Given profiles A then B, when A's final indicator row matches the reference and B's
  final indicator row differs, the result contains B's difference.
- Existing single-profile and differing-profile Recursive Analysis behavior remains
  unchanged apart from evaluating all profiles.
- No backend API request/response field, API version, route, job category, or persistence
  model changes.
- Empty indicator results use neutral/info styling and never display a green success
  state or general "no recursive issue" claim.
- English and Chinese text explicitly says "final analyzed candle", "indicators", and
  "tested profiles".
- Empty and non-empty results both show every tested startup-candle count; `-` is defined
  as evaluated with no reported final-row difference, not skipped or unknown.
- The strategy-owned startup count is described as strategy-declared rather than
  recommended, and the non-empty title also says final-candle indicator difference.
- Indicator differences and an empty indicator result continue to render through the
  existing table/alert journey.
- Focused backend pytest and Ruff, focused frontend component/locale tests, frontend
  typecheck/build/changed-file ESLint, the existing mocked Recursive Analysis Playwright
  journey, and `git diff --check` pass.
- One real 8083 Docker Recursive Analysis run completes after the control-flow change;
  acceptance records exact Root/backend/frontend SHAs and the observed bounded UI state.

## Rejected alternatives

### Final-candle raw-signal checkbox

Rejected for this slice. It would add a request flag, API 2.56 capability, checkbox,
submitted-run state, typed response, four UI result states, and a much larger test matrix
while still sampling only one endpoint. The current date-only FreqUI timerange selector
cannot target an arbitrary intraday mismatch such as the known 18:00-20:00 witness, so
the feature would not reliably find the defect that motivated it.

### Generic all-history rolling-prefix comparison

Rejected for this interactive repair. For arbitrary Python strategies, making each of
`N` historical candles the endpoint of every one of `K` finite startup profiles requires
approximately `O(N x K)` real strategy executions and can interact with informative
data, FreqAI, DataProvider state, and user code. It needs its own bounded research design,
resource policy, and evidence semantics if repeated candidate work proves that a generic
implementation is worth its cost.

### Persisted receipt or promotion Gate

Rejected. Existing Recursive Analysis remains an in-memory supporting diagnostic. This
repair does not bind Strategy Evidence, DataSnapshot, Execution Context, or a complete
test domain and therefore cannot authorize performance interpretation, holdout, Paper,
or Live.

## Explicit non-goals

- no signal calculation or comparison;
- no API version, request, response, route, page, feature flag, checkbox, or store state;
- no all-window checker, checkpoint sampler, strategy-specific evaluator, or generic
  restart-stability claim;
- no Backtest integration, artifact, receipt, database, Experiment, StrategyRelease,
  BotRelease, RuntimeInstance, Paper, Live, scheduler, daemon, or AI loop;
- no strategy source edit, parameter search, performance rerun, holdout spend, or claim
  of current or future profit.
