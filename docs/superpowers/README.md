# Superpowers Documentation Index

**Current status date:** 2026-08-01

Read this file before selecting an implementation plan. Dated plans and specifications
are retained as design and acceptance history; unchecked boxes in a completed plan are
not an active backlog.

## Current development state

- Runtime Registry v2 Phases 2A, 2B, and 2C are merged into local Root `main`.
- Phase 2C is accepted at its offline, fail-closed boundary. Production Supervisor
  assembly, online runtime acceptance, exchange writes, and live trading remain disabled.
- Product Phase 1 now means the strategy-validation program in
  [STRATEGY.md](STRATEGY.md), not the completed historical "Phase 1 Market Catalog."
- The [Phase 1 Baseline Capability Gate](plans/2026-07-30-phase1-baseline-capability-gate.md)
  passed on branch `phase1-baseline-capability-gate` at accepted implementation Root
  `ec1026a`, backend `455455980`, frontend `ce0df358`, and strategies `dbd5b0b`. Its
  [exact-SHA acceptance report](reports/2026-07-30-phase1-baseline-capability-gate-acceptance.md)
  is the evidence authority.
- The bounded
  [Phase 1 Experiment Revision Backtest](plans/2026-07-31-phase1-experiment-revision-backtest.md)
  is accepted on branch `xrunmasterx/phase1-experiment-revision-backtest` at implementation
  Root `f7f294c`, backend `73a7431f2`, frontend `3c0f0dbc`, and strategies `dbd5b0b`.
  Its [exact-SHA acceptance report](reports/2026-07-31-phase1-backtest-revision-receipt-acceptance.md)
  is the evidence authority.
- The bounded [Phase 1 DataSnapshot Binding](plans/2026-07-31-phase1-data-snapshot-binding.md)
  is accepted on branch `xrunmasterx/phase1-data-snapshot-binding` at implementation
  Root `a933df5b`, backend `05f3d5845`, frontend `a71cf5b1`, and strategies `dbd5b0b`.
  Its [exact-SHA acceptance report](reports/2026-07-31-phase1-data-snapshot-binding-acceptance.md)
  is the evidence authority. It binds API-2.52 standard Backtests to exact logical
  market-data identity without adding data archival, a snapshot picker, Experiment CRUD,
  Runtime, Paper, or Live scope.
- The bounded
  [Backtest Artifact Secret Redaction](plans/2026-07-31-backtest-artifact-secret-redaction.md)
  is accepted on branch `xrunmasterx/phase1-complete-development` at implementation Root
  `014c0f677` and backend `c8fb9af73`. It closes newly written Backtest ZIP credential
  leakage before further automated strategy iteration. Its
  [acceptance report](reports/2026-07-31-backtest-artifact-secret-redaction-acceptance.md)
  records the separately authorized historical-artifact remediation boundary.
- The bounded
  [Phase 1 Backtest Strategy Evidence Binding](plans/2026-07-31-phase1-backtest-strategy-evidence-binding.md)
  is accepted on branch `xrunmasterx/phase1-complete-development` at implementation Root
  `091a797a3`, backend `d254eed96`, frontend `29097e95b`, and unchanged strategies
  `dbd5b0b`. Its
  [exact-SHA acceptance report](reports/2026-07-31-phase1-backtest-strategy-evidence-binding-acceptance.md)
  binds the executed primary-module source and supported resolved Freqtrade parameters
  without adding StrategyRelease, Environment Identity, Runtime, Paper, or Live scope.
- The bounded
  [Phase 1 Retained DataSnapshot Replay](plans/2026-07-31-phase1-retained-data-snapshot-replay.md)
  is accepted on branch `xrunmasterx/phase1-complete-development` at implementation
  Root `02563c1d`, backend `9baff126f`, frontend `e2b5e36c`, and unchanged strategies
  `dbd5b0b`. Its
  [exact-SHA acceptance report](reports/2026-07-31-phase1-retained-data-snapshot-replay-acceptance.md)
  is the evidence authority. It stores canonical rows and admission routes inside each
  opted-in Backtest ZIP, adds one verified history-row replay action, and explicitly
  leaves the current exchange/software context unbound.
- The bounded
  [Phase 1 Backtest Execution Context Evidence](plans/2026-07-31-phase1-backtest-execution-context-evidence.md)
  is accepted at implementation Root `290fecbe8`, backend `3209d4374`, frontend
  `17e88f2d6`, and unchanged strategies `dbd5b0b21`. Its
  [exact-SHA acceptance report](reports/2026-07-31-phase1-backtest-execution-context-evidence-acceptance.md)
  is the evidence authority. The slice keeps the existing 8083 Backtest journey and adds
  a bounded third comparison axis for core-runtime versions, effective simulation
  configuration, and admitted-pair exchange simulation facts. It is correlation evidence
  for detecting confounded comparisons, not Environment Identity, complete
  reproducibility, or environment restoration.
- The frontend-only
  [Phase 1 Evidence-Guided Backtest Pair](plans/2026-07-31-phase1-evidence-guided-backtest-pair.md)
  is accepted at implementation Root `bb769e459aa62d653ddc1f40ed4a29d42d024a54`
  and frontend `515b00cccb882c3f304bab18d0eb5520f934901e`. Its
  [exact-SHA acceptance report](reports/2026-07-31-phase1-evidence-guided-backtest-pair-acceptance.md)
  is the evidence authority. It adds a fail-closed interpretation for exactly two loaded
  results without adding a backend, split ledger, roles, score, ranking, optimizer,
  Paper, or Runtime scope.
- The bounded
  [Phase 1 Futures validation dogfood](reports/2026-07-31-phase1-futures-validation-dogfood-acceptance.md)
  is accepted at implementation Root `e1553633d`, unchanged backend `3209d4374`,
  unchanged frontend `515b00ccc`, and strategies `dec5adb77`. It repaired
  `VolatilitySystem` startup warmup at 499 candles, verified the existing Backtest,
  Lookahead, Recursive, retained-data, and fail-closed pair-interpretation journeys on
  OKX `BTC/USDT:USDT`, and required no new API or platform surface. The controlled
  candidate lost 2.021% versus the baseline's 1.751%, so the validation workflow is
  accepted but the candidate is not eligible for Paper promotion.
- The preregistered
  [VolatilitySystem Static-Stop Calibration](plans/2026-07-31-volatility-static-stop-calibration.md)
  is completed and rejected at calibration. The candidate changed total profit from
  `+2.7856%` to `-0.6799%`, increased drawdown from `3.7498%` to `6.2781%`, and failed
  six preregistered performance/risk Gates. Its
  [rejection report](reports/2026-07-31-volatility-static-stop-calibration-rejection.md)
  is the evidence authority. Safety analysis, the sealed holdout, strategy edits,
  Paper, and Live were not opened by that study; the follow-up below is now completed.
- The
  [VolatilitySystem Breakout-Episode Risk Calibration](plans/2026-07-31-volatility-breakout-episode-risk-calibration.md)
  is completed and rejected at its pre-performance signal-parity Gate. The finite-edge
  candidate matched the actual 599-candle cold/warm frames and the 600/799 profiles, but
  three development rows produced five signal-field differences at the frozen 499-candle
  minimum. Its
  [rejection report](reports/2026-08-01-volatility-breakout-episode-risk-calibration-rejection.md)
  is the evidence authority. B/S/C performance, safety analysis, holdout, tracked
  strategy edits, Paper, and Live were not opened during that study; no strategy
  candidate is active.
- The preceding completed product slice is
  [Recursive Analysis Truthfulness Repair](plans/2026-08-01-recursive-analysis-truthfulness-repair.md).
  It makes the existing 8083 Recursive Analysis evaluate every materialized startup
  profile and narrows the empty-result UI to neutral, final-candle indicator evidence.
  It adds no API, signal comparison, page, service, persistence, Runtime, Paper, or Live
  scope. Root `bc51d415`, backend `53fb46d0`, and frontend `8a26426f` passed
  independent re-Gate and isolated Docker/API/UI acceptance. Its
  [acceptance report](reports/2026-08-01-recursive-analysis-truthfulness-repair-acceptance.md)
  is the evidence authority. A preparatory API run and the later exact-image acceptance
  accidentally crossed into the reserved `20250702-20260702` holdout and exposed
  final-row indicators. That window is retired and cannot support future fresh-holdout
  claims; formal acceptance was rerun on `20250101-20250701`. No signal, trade,
  performance, Paper, or Live evidence was opened.
- The preceding completed product slice is
  [Phase 1 Lookahead Analysis Sufficiency Truthfulness Repair](plans/2026-08-01-lookahead-analysis-sufficiency-truthfulness-repair.md).
  It separates minimum-signal completion from the detected/not-detected bias verdict in
  the existing 8083 API and FreqUI result. The additive contract reports backend-owned
  effective minimum and target counts; insufficient and legacy responses remain neutral
  instead of rendering a false-green success. API thresholds become positive integers,
  matching the existing CLI invariant. API 2.56 must ship frontend-first or atomically
  with its matching FreqUI because an old UI cannot interpret the additive state.
  Root `c79df336`, backend `8b1ec827`, frontend `a0a4502a`, and unchanged strategies
  `dec5adb77` passed independent implementation Gates and exact combined-image API/UI
  acceptance. Its
  [acceptance report](reports/2026-08-01-lookahead-analysis-sufficiency-truthfulness-repair-acceptance.md)
  is the functional evidence authority. That frozen report records an embedded
  UI-identity P2; the subsequent packaging slice closes it without changing the
  historical report. Its local acceptance combined the Root submodule tree,
  Buildx-recorded metadata, immutable-image identity, and actual behavior. The Buildx
  metadata remains corroborating audit data, not an independently trusted source
  binding. It adds no analysis algorithm, data run,
  strategy candidate, receipt, persistence, Runtime, Paper, Live, or AI scope.
- The preceding completed bounded implementation is
  [Phase 1 Reviewed Image UI Self-Identity](plans/2026-08-01-reviewed-image-ui-self-identity.md).
  Root `39177df0` and frontend `212c9121` pass the full frontend identity through the
  existing committed-image wrapper, preserve the exact Root/backend/frontend labels,
  verify the embedded marker from the immutable image ID, and display the same complete
  frontend identity once in the packaged UI. Ad-hoc builds remain usable and
  non-reviewed. Its
  [acceptance report](reports/2026-08-01-reviewed-image-ui-self-identity-acceptance.md)
  is the exact-SHA and image evidence authority. It adds no strategy, market-data,
  Backtest, Runtime, Paper, Live, deployment, or AI scope.
- The latest completed bounded implementation is
  [Phase 1 Per-Pair Live Chart Refresh Truth](plans/2026-08-01-phase1-per-pair-live-chart-refresh-truth.md).
  Static review found that failed live-chart refreshes retain old data without a visible
  failure warning, while one bot-wide status and first-pair presentation metadata can
  cross-contaminate multiple pair panels. Root `064908fc` and frontend `c74ad28d` make
  refresh state, `plot_config`, and warnings pair/timeframe-local. It adds no backend,
  market-data request, strategy, Backtest, Runtime, Paper, Live, or AI-worker scope.
  Its
  [acceptance report](reports/2026-08-01-phase1-per-pair-live-chart-refresh-truth-acceptance.md)
  is the exact-SHA, frontend-test evidence authority.
- The baseline is one product Gate across existing compatibility services: 8081
  `/graph` and `/trade` own live watch/runtime observation; 8083 `/backtest`,
  `/lookahead_analysis`, and `/recursive_analysis` own standard Freqtrade offline
  validation. The simplified 8083 `/research` SMA calculation is frozen and is not the
  authoritative backtest.
- The offline automated Gate is green: 62 backend chart tests, 17 selected backend
  chart/backtest/analysis API tests, backend Ruff, 98 focused frontend chart/locale
  tests, frontend typecheck/build and changed-file ESLint, and four local fully mocked
  Chromium journeys covering backtest-result visibility, Lookahead Analysis, and
  Recursive Analysis.
- The working branch now guards official strategy output at the closed-candle boundary,
  marks forming Market/Watch metadata as provisional, presents the Forming Candle as
  observation-only, keeps Strategy Signals separate from runtime Trades, and suppresses
  and reports Trades whose available strategy name or timeframe mismatches the chart.
  These compatibility fields are not formal revision/release identity.
- Docker 29.6.2, Compose 5.3.1, and the `desktop-linux` daemon were used for exact-SHA
  acceptance. The committed-image 8081 and 8083 journeys passed: 1m watch refreshed at
  approximately ten-second cadence, strategy overlays and signals rendered with
  forming-candle trust state, the standard Freqtrade backtest completed and rendered,
  and Lookahead/Recursive Analysis completed. Both services were stopped after the
  receipt; Docker is installed but is not on the coordinator PowerShell `PATH`.
- The Futures dogfood additionally used immutable image
  `sha256:749e372bfee2bc5d263608f37d7e7ceb2ae4f9ff93dc271d6637e6e6311bc30a`
  on isolated host port 18084. A native-warmup pair correctly failed closed because its
  admitted DataSnapshots differed; a common 499-candle warmup then produced the same
  exact DataSnapshot and captured execution context, different strategy evidence, and a
  UI-classified same-window strategy-change review.
- Phase 2D Tasks 1-4 remain complete locally as reusable, unpublished backend assets. Its
  last implementation Root commit is `2128646`; the accepted Phase 1 Gate implementation
  Root is `ec1026a`.
- Phase 2D Tasks 5-8, Phase 2E, new Experiment UI, dynamic Runtime, Paper Observation,
  Runtime Access, and 8090 chart work are paused. Passing the baseline does not
  automatically resume any of them.

## Current authority and resume entrypoints

| Role | Document | Status |
|---|---|---|
| Product purpose and sequencing | `STRATEGY.md` | Governing |
| Shared domain language | `../../CONTEXT.md` | Governing glossary |
| Previous baseline implementation | `plans/2026-07-30-phase1-baseline-capability-gate.md` | Completed; exact-SHA accepted |
| Previous baseline evidence | `reports/2026-07-30-phase1-baseline-capability-gate-acceptance.md` | Accepted implementation receipt |
| Previous completed implementation | `plans/2026-07-31-phase1-experiment-revision-backtest.md` | Completed; exact-SHA accepted |
| Previous acceptance evidence | `reports/2026-07-31-phase1-backtest-revision-receipt-acceptance.md` | Accepted contract-slice receipt |
| Preceding completed implementation | `plans/2026-07-31-phase1-data-snapshot-binding.md` | Completed; exact-SHA accepted |
| Preceding acceptance evidence | `reports/2026-07-31-phase1-data-snapshot-binding-acceptance.md` | Accepted contract-slice receipt |
| Security prerequisite implementation | `plans/2026-07-31-backtest-artifact-secret-redaction.md` | Completed; exact-SHA accepted |
| Security prerequisite evidence | `reports/2026-07-31-backtest-artifact-secret-redaction-acceptance.md` | Accepted forward-write security receipt |
| Preceding completed implementation | `plans/2026-07-31-phase1-backtest-strategy-evidence-binding.md` | Completed; exact-SHA accepted |
| Preceding acceptance evidence | `reports/2026-07-31-phase1-backtest-strategy-evidence-binding-acceptance.md` | Accepted strategy-evidence receipt |
| Preceding completed implementation | `plans/2026-07-31-phase1-retained-data-snapshot-replay.md` | Completed; exact-SHA accepted |
| Preceding acceptance evidence | `reports/2026-07-31-phase1-retained-data-snapshot-replay-acceptance.md` | Accepted retained-data replay receipt |
| Preceding completed implementation | `plans/2026-07-31-phase1-evidence-guided-backtest-pair.md` | Completed; exact-SHA accepted |
| Preceding acceptance evidence | `reports/2026-07-31-phase1-evidence-guided-backtest-pair-acceptance.md` | Accepted pair-interpretation receipt |
| Latest Futures dogfood evidence | `reports/2026-07-31-phase1-futures-validation-dogfood-acceptance.md` | Accepted workflow receipt; candidate rejected |
| Preceding strategy research | `plans/2026-07-31-volatility-static-stop-calibration.md` | Completed; candidate rejected at calibration |
| Preceding strategy-research evidence | `reports/2026-07-31-volatility-static-stop-calibration-rejection.md` | Rejection authority; holdout unopened then, later retired |
| Latest strategy research | `plans/2026-07-31-volatility-breakout-episode-risk-calibration.md` | Completed; candidate rejected before performance |
| Latest strategy-research evidence | `reports/2026-08-01-volatility-breakout-episode-risk-calibration-rejection.md` | Rejection authority; holdout unopened then, later retired |
| Preceding completed implementation | `plans/2026-08-01-recursive-analysis-truthfulness-repair.md` | Completed; exact-SHA accepted |
| Preceding acceptance evidence | `reports/2026-08-01-recursive-analysis-truthfulness-repair-acceptance.md` | Accepted bounded-diagnostic receipt |
| Preceding completed implementation | `plans/2026-08-01-lookahead-analysis-sufficiency-truthfulness-repair.md` | Completed; exact-SHA accepted |
| Preceding acceptance evidence | `reports/2026-08-01-lookahead-analysis-sufficiency-truthfulness-repair-acceptance.md` | Accepted bounded-diagnostic receipt |
| Preceding completed implementation | `plans/2026-08-01-reviewed-image-ui-self-identity.md` | Completed; exact-image accepted |
| Preceding acceptance evidence | `reports/2026-08-01-reviewed-image-ui-self-identity-acceptance.md` | Accepted packaging-provenance receipt |
| Latest completed implementation | `plans/2026-08-01-phase1-per-pair-live-chart-refresh-truth.md` | Completed; exact-SHA accepted |
| Latest acceptance evidence | `reports/2026-08-01-phase1-per-pair-live-chart-refresh-truth-acceptance.md` | Accepted frontend state-isolation receipt |
| Active implementation | None | No bounded implementation is active |
| Data identity decision | `decisions/2026-07-31-logical-data-snapshot-identity.md` | Accepted |
| Replay boundary decision | `decisions/2026-07-31-retained-data-snapshot-replay-boundary.md` | Accepted |
| Strategy evidence decision | `decisions/2026-07-31-backtest-strategy-evidence-boundary.md` | Accepted |
| Execution-context evidence decision | `decisions/2026-07-31-backtest-execution-context-evidence-boundary.md` | Accepted and implemented |
| Backtest pair interpretation decision | `decisions/2026-07-31-backtest-pair-interpretation-boundary.md` | Accepted and implemented |
| Chart source semantics | `../chart-data-source-rules.md` | Standing contract |
| Runtime Registry coordination | `plans/2026-07-12-runtime-registry-v2-master.md` | Paused target sequence |
| Runtime Access decision | `specs/2026-07-30-runtime-access-rebaseline-design.md` | Approved resume design; execution paused |
| Phase 2D continuation | `plans/2026-07-12-runtime-registry-v2-phase2d-market-data-ui.md` | Tasks 1-4 retained; Tasks 5-8 paused |
| Phase 2E cutover | `plans/2026-07-12-runtime-registry-v2-phase2e-cutover.md` | Provisional and paused |

## Governing specifications

- `specs/2026-07-12-multi-market-research-trading-platform-design.md`
- `specs/2026-07-12-runtime-registry-v2-design.md`
- `specs/2026-07-30-runtime-access-rebaseline-design.md`
- `specs/2026-07-15-phase2c-runtime-driver-contract-design.md`
- `specs/2026-07-17-phase2c-task7b-persisted-launch-authority-design.md`
- `../chart-data-source-rules.md` for chart indicators, overlays, decision evidence,
  crosshair, and tooltip work

Later amendments override only the sections they explicitly supersede. They do not
silently replace global safety constraints or previously reviewed domain contracts.
The 2026-07-30 baseline-first decision supersedes the current execution ordering and
forming-candle signal semantics only: official strategy indicators/signals are
closed-candle evidence, and Strategy Signals never prove execution. The long-term
architecture and safety constraints remain target authority.

## Completed historical plans

Treat the following as implementation history, not executable work queues:

- P0 current-system and Draft PR safety closure plans
- Market Catalog and Runtime Registry v2 Phase 2A plans
- Runtime Registry v2 Phase 2B and its Task 7 completion plan
- Runtime Registry v2 Phase 2C and its Task 1, Task 3, Task 4, and Task 7 repair or
  continuation plans
- the dated FreqUI, chart, LSRI, QQE MOD, Research, and A-share feature plans from
  2026-07-03 through 2026-07-08

These documents preserve implementation rationale, exact test commands, compatibility
constraints, and review history. Their checkbox state was not consistently updated after
publication and must not be used to infer current progress.

## Supersession map

- Phase 2B Task 7: use
  `plans/2026-07-14-runtime-registry-v2-phase2b-task7-contract-completion.md` for the
  completed contract repair.
- Phase 2C Task 1 interface and sequencing: use
  `specs/2026-07-15-phase2c-runtime-driver-contract-design.md` and its matching plan.
- Phase 2C Task 3 and Task 4: use the dated 2026-07-16 repair/clarification plans and
  acceptance reports.
- Phase 2C Task 7: use the 2026-07-17 Task 7A/7B plans, design, and acceptance reports.
- Runtime Registry v2 design sections 13.4, 21.4, and 21.5: use
  `specs/2026-07-30-runtime-access-rebaseline-design.md` for Runtime Access route breadth,
  first-operation/audit contract, internal authentication, and dependency ordering. All
  other safety constraints in the 2026-07-12 design remain governing.
- Phase 2D Tasks 5-10: the rebaselined Phase 2D plan replaces the old 49-route/token-first
  sequence with retained Tasks 5-8, but those tasks are not an active backlog until an
  exact-SHA baseline receipt and a separate one-journey resume decision exist.
- Phase 2E: use the retained rebaselined plan only after explicit reauthorization.
  Research, Spot, and Futures each use an
  independent service cycle: disposable read candidate, final authoritative sync, write
  migration, then listener removal. Operations are added only with their producers and
  consumers.
- For the current multi-market target architecture, use the approved 2026-07-12 design;
  the 2026-07-11 architecture document is retained as explicitly superseded design
  history.

## Acceptance evidence

Files under `reports/` are frozen historical evidence. Status text such as "merge
pending" describes the moment when a report was written; do not rewrite it after later
publication. Use the current Root `main` history and remote refs to determine final merge
state.

Operational runbooks under `../operations/` are current runtime documentation and are not
historical implementation plans. Some are enforced directly by automated tests.
