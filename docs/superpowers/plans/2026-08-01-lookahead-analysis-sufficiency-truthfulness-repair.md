# Phase 1 Lookahead Analysis Sufficiency Truthfulness Repair

**Status:** Design approved; implementation not started

**Product authority:** [Product Strategy and Delivery Policy](../STRATEGY.md)

**Triggering evidence:**
[Phase 1 Baseline Capability Gate Acceptance](../reports/2026-07-30-phase1-baseline-capability-gate-acceptance.md)

## User problem

The existing 8083 Lookahead Analysis result collapses two different questions into the
single `has_bias` boolean:

1. did the run analyze enough signals to reach its configured minimum; and
2. after reaching that minimum, did the run detect lookahead bias?

This is not only a theoretical ambiguity. The accepted baseline recorded a completed API
job with `has_bias=false` and `total_signals=0`, while its evidence report had to add a
manual caveat that the run did not provide meaningful strategy coverage. The normal
FreqUI result has no equivalent caveat: it renders any `has_bias=false` result as a green
success with a checkmark and a green "No" badge. Freqtrade's command-line presentation,
by contrast, reports a result below `minimum_trade_amount` as too few trades and says the
test failed.

The user needs the existing result to answer the questions in their logical order:

> Did this run analyze at least its effective minimum number of signals? If it did, did
> it find a lookahead-bias witness among the analyzed signals?

This is a supporting strategy-safety diagnostic. Even a sufficiently sampled clean
result does not prove strategy quality, representativeness, robustness, Paper or Live
eligibility, or current or future profitability.

## Assumptions and tradeoffs

- Freqtrade remains the sole Lookahead Analysis authority. The analysis algorithm,
  signal selection, configured threshold values, route, background-job lifecycle, and
  request shape/defaults remain unchanged.
- The CLI already accepts only positive integers for both thresholds, and the existing
  form declares `min=1`, but the public API schema currently accepts zero and negative
  integers. The API must enforce the same positive-integer invariant authoritatively. A
  zero minimum would otherwise allow zero analyzed signals to satisfy the new completion
  comparison and recreate the false-green defect.
- `minimum_trade_amount` is the validity threshold already enforced by Freqtrade.
  `targeted_trade_amount` is a work target/cap, not a second validity threshold. A run
  that analyzes at least the minimum but fewer than the target is complete.
- The API must report the effective thresholds owned by the completed backend instance,
  after Freqtrade applies its configuration overrides. FreqUI must not reconstruct them
  from form state, defaults, or a prior request.
- The smallest machine-readable result state has exactly two successful response values:
  `completed` and `insufficient_signals`. An unexpected backend condition where the
  minimum was reached but Freqtrade still marks the check failed uses the existing
  background-job error channel; it is not disguised as a third successful result state.
- Existing result fields remain additive-compatible. `has_bias` remains present, but a
  clean verdict is meaningful only when `analysis_state=completed`.
- New FreqUI types keep the additive fields optional so that a rolling deployment can
  still load an older response. A response without the state and effective thresholds
  is presented neutrally as legacy/unknown; FreqUI never infers completion from
  `has_bias=false`.
- Rolling compatibility is one-directional: new FreqUI with an old backend is safe and
  neutral, but old FreqUI cannot understand a new backend's additive state and would
  retain the false-green behavior. API 2.56 must therefore be deployed frontend-first or
  atomically with the matching FreqUI. Backend-first deployment to an old UI is
  unsupported. The local packaged stack uses an exact combined image for acceptance.
- A positive witness and a completed clean result remain visually asymmetric, but this
  slice does not design a general diagnostic evidence hierarchy or persisted receipt.

## Result contract

For new backend responses:

| Condition | `analysis_state` | Meaning of `has_bias` | FreqUI state |
|---|---|---|---|
| `total_signals < minimum_trade_amount` | `insufficient_signals` | not a clean verdict | neutral, no conclusion |
| `total_signals >= minimum_trade_amount` and the engine check completed | `completed` | bounded detected/not-detected result | red witness or bounded green result |
| minimum reached but the engine still reports a failed check | no successful result | none | existing job error |

Every new result also reports positive integer `minimum_trade_amount` and
`targeted_trade_amount`. FreqUI always shows analyzed, minimum, and target counts for a
new-state result. It uses `analysis_state` before reading `has_bias`.

For a legacy response missing any required discriminator/threshold field, FreqUI shows a
neutral compatibility message and an unknown/not-evaluated bias verdict. It does not
reconstruct the missing evidence from the submitted form or current defaults.

## Scope

Backend:

- require `minimum_trade_amount >= 1` and `targeted_trade_amount >= 1` in the API request
  schema, matching the established CLI invariant without changing defaults;
- extend `LookaheadAnalysisResultEntry` with required `analysis_state`, effective
  `minimum_trade_amount`, and effective `targeted_trade_amount` fields;
- derive those fields from the initialized `LookaheadAnalysis` instance after the
  existing configuration overrides run;
- return `insufficient_signals` below the effective minimum and `completed` only when the
  minimum is reached and `failed_bias_check` is false;
- route a minimum-reached but still-failed invariant through the existing background-job
  error path;
- increment the public API version for the additive response contract;
- add focused API tests for zero/negative request rejection, instance-owned effective
  thresholds, insufficient, exact-minimum complete, completed biased, and inconsistent
  failed-check behavior;
- document the two result states and the target-versus-minimum distinction in the
  existing Freqtrade Lookahead Analysis documentation.

FreqUI:

- extend the existing result type with optional additive fields for rolling compatibility;
- keep the route, form, store, polling lifecycle, table, and request unchanged;
- branch first on the explicit backend result state;
- show a neutral insufficient-signal alert without a success checkmark or green "No"
  badge, including analyzed/minimum/target counts and a no-conclusion statement;
- show green only for `completed` plus `has_bias=false`, and scope the copy to the number
  of signals actually analyzed;
- retain the red completed-bias result while giving it the same sample context;
- show legacy/missing-contract responses neutrally as unknown rather than inferring a
  verdict;
- keep a permanently visible boundary that this diagnostic does not establish strategy
  quality, representative coverage, robustness, Paper/Live eligibility, or profit;
- add focused component, English/Chinese locale, and fully mocked browser coverage while
  retaining the existing completed-clean journey.
- prove the safe rolling direction with a legacy-response component case; package and
  accept API 2.56 only in a matching exact FreqUI/backend image (or deploy FreqUI first).

Root documentation:

- make this bounded truthfulness repair the active implementation entrypoint;
- retain Recursive Analysis Truthfulness Repair as the latest completed implementation
  until this slice is exact-SHA accepted;
- do not create or evaluate a strategy candidate, assign a replacement holdout, inspect
  the retired holdout, or activate Runtime, Paper, Live, AI, or optimization scope.

## Acceptance

- A result below the effective minimum returns
  `analysis_state=insufficient_signals` with the backend-owned effective minimum and
  target.
- Zero or negative minimum/target API inputs fail request validation; zero analyzed
  signals can never satisfy a valid minimum.
- A result at exactly the effective minimum with `failed_bias_check=false` returns
  `analysis_state=completed`; the target is not treated as a validity Gate.
- A biased completed result retains its current counts and indicator evidence while
  carrying the new state and thresholds.
- A minimum-reached result that remains failed does not return a successful analysis
  result and instead exposes the existing background-job error state.
- Existing request fields, analysis calculations, routes, job category, and persistence
  remain unchanged; only the CLI's established positive threshold invariant is added to
  API validation.
- FreqUI never displays a green alert, checkmark, or green "No" bias badge for
  `insufficient_signals` or a legacy response missing the new contract.
- Completed clean, completed biased, insufficient, and legacy responses each render a
  distinct truthful state through the existing result component.
- English and Chinese text distinguish analyzed, minimum, and target signal counts and
  keep the permanent supporting-diagnostic boundary visible.
- The API version assertion is exactly 2.56, effective thresholds are proven to come
  from the initialized backend instance rather than submitted/default form state, and a
  new frontend renders a legacy response neutrally.
- Focused backend API pytest and Ruff, focused frontend component/locale tests, frontend
  typecheck/build/changed-file ESLint, completed and insufficient fully mocked Playwright
  journeys, and `git diff --check` pass.
- An exact combined API 2.56/FreqUI image is accepted after independent implementation
  review; backend-first publication to an old FreqUI is explicitly excluded. Exact
  Root/backend/frontend/strategy SHAs and the unchanged no-market-data boundary are
  recorded.

## Rejected alternatives

### Frontend-only inference

Rejected. `has_bias=false` cannot distinguish a complete clean result from an analysis
that returned before reaching the minimum. Submitted form values and UI defaults also
cannot prove the effective thresholds after backend overrides. The authority must expose
its state explicitly.

### Backend-only rollout or compatibility encoding in `has_bias`

Rejected. An old FreqUI ignores additive result state and would still render
`has_bias=false` green, while setting `has_bias=true` for insufficient evidence would
falsely claim that bias was detected. The smallest truthful compatibility policy is a
new-frontend-first or atomic rollout, with legacy responses neutral in the new UI and an
exact combined image used for acceptance.

### Treating the target as a second Gate

Rejected. Freqtrade intentionally allows analysis of all available signals when the
minimum is reached but the target is not. Turning the target into a validity threshold
would silently change established analysis semantics rather than repair their
presentation.

### Persisted diagnostic receipt or cross-route evidence ledger

Rejected for this slice. A durable ledger needs identity, lifecycle, retention, and
cross-route ownership rules and would still leave today's false-green result unfixed.
The current defect is repaired at the existing in-memory API/UI boundary.

### Exact-candle Recursive witness or AI evidence brief

Deferred. Both may improve later investigation, but neither prevents the active
Lookahead result from claiming success with zero analyzed signals. This repair is
smaller, directly user-visible, and logically prior to summarizing or extending the
diagnostic evidence.

## Explicit non-goals

- no Lookahead Analysis algorithm, signal-selection, threshold-default, request shape,
  form, polling, route, page, store, or job-lifecycle redesign; API positivity validation
  is the only request-behavior change;
- no second analysis engine, signal sampler, exact-candle selector, all-window checker,
  model call, generated advice, or autonomous action;
- no database, artifact, receipt, evidence ledger, scheduler, daemon, service, or new UI
  route;
- no Backtest, chart, trade, exchange, strategy, strategy-parameter, Experiment,
  StrategyRelease, BotRelease, RuntimeInstance, Paper, or Live change;
- no market-data download, analysis run on historical market data, performance metric,
  holdout use, promotion decision, or claim of stable or future profit.
