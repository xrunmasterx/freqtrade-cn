# Superpowers Documentation Index

**Current status date:** 2026-07-31

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
  is implemented and independently accepted at frontend
  `515b00cccb882c3f304bab18d0eb5520f934901e`. It adds a fail-closed interpretation for
  exactly two loaded results without adding a backend, split ledger, roles, score,
  ranking, optimizer, Paper, or Runtime scope.
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
| Latest completed implementation | `plans/2026-07-31-phase1-evidence-guided-backtest-pair.md` | Completed; exact-SHA acceptance pending report commit |
| Latest acceptance evidence | `reports/2026-07-31-phase1-backtest-execution-context-evidence-acceptance.md` | Accepted execution-context receipt |
| Active implementation | None | Next step is bounded Futures-oriented dogfood |
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
