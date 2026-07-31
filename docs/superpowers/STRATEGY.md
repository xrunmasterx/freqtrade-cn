# Product Strategy and Delivery Policy

**Status:** Governing product and delivery strategy

**Current status authority:** [README.md](README.md)

**Latest completed execution plan:**
[Phase 1 Backtest Execution Context Evidence](plans/2026-07-31-phase1-backtest-execution-context-evidence.md)

**Active execution plan:** none; a new slice requires explicit first-principles selection

## Product purpose

The near-term product helps a local strategy researcher answer three questions with
evidence:

1. Is the market view current enough to review the strategy?
2. What indicators, signals, and executions did the strategy produce, and which source
   does each point come from?
3. Does the same strategy pass comparable, evidence-bound Freqtrade backtesting and
   safety analysis before any governed Paper observation?

The first supported execution scope is digital-asset Spot in Paper/dry-run conditions.
Live trading, exchange writes, and real-money acceptance are outside the current program.

## First-principles delivery rules

1. Restore the smallest complete user loop before expanding the platform architecture.
2. Freqtrade remains the sole authority for Backtest, Lookahead Analysis, Recursive
   Analysis, and Paper execution; do not create a second generic backtest engine.
3. Market observation and strategy decision time are different. The Forming Candle may
   refresh for watch purposes, while official strategy indicators and signals use closed
   candles.
4. A Strategy Signal and an executed or simulated Trade are different evidence and must
   remain visually and semantically separate.
5. Formal comparisons require exact strategy, revision/release, data, and environment
   identity; matching names are not enough. Gate A uses the available strategy name and,
   when both sides provide it, timeframe to suppress explicit compatibility mismatches;
   these fields are still weak compatibility evidence, not formal Paper proof.
6. Reuse accepted behavior and existing compatibility services until a measured user
   problem justifies migration.
7. A passed prerequisite permits a new decision; it does not automatically activate
   every paused roadmap item.

## Product Phase 1

Product Phase 1 is deliberately split into two gates. It is distinct from the dated
architecture's "Phase 1 Market Catalog" taxonomy.

### Gate A: Baseline Capability Gate — accepted

Accept the existing core workflow before adding new platform features:

- 8081 `/graph`: one-minute near-real-time market watch, strategy `plot_config`
  indicators, and closed-candle strategy entry/exit points;
- 8081 `/trade`: observation and operations for the existing preconfigured dry-run Spot
  compatibility service;
- 8083 `/backtest`: complete standard Freqtrade backtest, history, comparison, and
  result visualization;
- 8083 `/lookahead_analysis` and `/recursive_analysis`: Freqtrade's supporting
  strategy-safety analyses;
- 8083 `/research`: retained compatibility capability only; its simplified SMA
  calculation is frozen and is not the authoritative backtest.

The two origins are intentional for the baseline: 8081 runs Freqtrade in `trade` mode,
while the standard backtest and analysis APIs require the existing 8083
`webserver` mode. Unifying them is not a Gate A requirement.

### Gate A.1: Revision-bound authoritative Backtest — accepted

The first post-baseline slice stays entirely inside the existing authoritative 8083
Backtest journey. A user supplies a stable Experiment ID, the standard engine creates a
deterministic revision receipt, and the result/history views retain that provenance.

This receipt binds the request, native strategy/cache fingerprint, and engine version. It
does not yet bind exact candle content: `data_snapshot_id` remains null, result caching is
bypassed, and the UI must state that the result is not formally reproducible or eligible
for Paper acceptance. This is a provenance step toward Gate B, not Gate B execution.

### Gate A.2: Exact standard data identity — accepted

The next bounded slice stays on the same Backtest form and engine. API 2.52 adds an
automatic, capability-gated capture of the normalized primary/startup, detail,
informative, and Futures auxiliary market-data series actually admitted to a standard
Backtest. A content-addressed manifest is bound into receipt schema 2; no snapshot picker,
data-management dashboard, or second engine is added.

This gate answers whether two results used the same standard offline market-data content.
It does not archive the source rows, bind arbitrary strategy I/O or the complete software
environment, make the result artifact tamper-resistant, qualify Paper execution, or
predict future profit.

### Gate A.3: Exact primary strategy evidence — accepted

API 2.53 keeps the same authoritative Backtest form and engine while binding the exact
primary-module source captured for execution and the supported resolved Freqtrade
parameters into the existing revision receipt and export artifact. Result, history,
selector, and comparison views report same, different, or unknown independently of
DataSnapshot identity.

This gate does not create StrategyRelease or prove imported helpers, FreqAI model/data,
the complete environment, artifact authenticity, retained replay, Paper eligibility, or
future profit.

### Gate A.4: Backtest execution-context evidence — accepted

API 2.55 keeps the same authoritative Backtest form and engine while sealing three
bounded fingerprints for the core runtime versions, effective simulation configuration,
and admitted-pair exchange simulation facts actually used by the run. Result, history,
selector, and comparison views report this context as same, different, or unknown
independently of DataSnapshot and strategy evidence.

To keep those axes truthful, every newly captured strategy artifact upgrades to normative
Strategy Evidence v2: the exact declared Freqtrade-resolved strategy execution settings,
including custom ROI enablement and the protection list actually consumed, remain on the
intended-change axis and are excluded from context. Open settings/protection maps are
replaced by exact positive allowlists and the recursive hyperopt surface is resource
bounded. Existing v1 evidence remains loadable.

The user decision is whether a candidate-versus-baseline metric delta is comparable
within the captured scope or is confounded by changed or unknown execution context.
Only same captured context makes the pair eligible for later robustness analysis;
different or unknown context must not be rewarded, ranked, learned from, or promoted as
strategy improvement.

This gate supports static-PairList Spot and Futures without adding exchange calls. Dynamic
PairList and FreqAI fail closed because their executed order/model identity is not bound.
Cross Margin object wallets that would require a mutable ticker conversion also fail
closed before wallet construction. The context binds the one proxy-wallet free balance
that still clamps `available_capital`, without retaining the wallet map. The exchange
projection freezes the narrow taker-rate input used by applicable dry-run liquidation
formulas, but does not create a general fee model. The gate does not persist raw config or
exchange responses, enumerate the host, restore an environment, create an SBOM/container
identity, bind imported helpers or arbitrary strategy I/O, guarantee the same result,
establish artifact authenticity, qualify Paper, or predict profit.

### Gate B: Governed Experiment-to-Paper — not active

After Gate A passes and one explicit next-journey decision is recorded, the smallest
formal Paper path may be designed around:

`StrategyExperiment -> ExperimentRevision -> StrategyRelease -> BotRelease -> dynamic RuntimeInstance`

Gate B must create a new isolated runtime from explicit Experiment parameters. The
preconfigured 8081 service and the Phase 2 `paper_probe` design are not formal Gate B
acceptance.

## Current route responsibilities

| Journey | Current owner | Product meaning |
|---|---|---|
| Live watch and strategy review | 8081 `/graph` | Forming market candle plus closed-candle strategy evidence |
| Compatibility runtime observation/operations | 8081 `/trade` | Existing dry-run Spot service; not formal dynamic Paper |
| Authoritative offline validation | 8083 `/backtest` | Standard Freqtrade engine and results |
| Bias/recursion checks | 8083 analysis routes | Standard Freqtrade tools |
| Simplified Research SMA calculation | 8083 `/research` | Frozen compatibility behavior; not product authority |
| Platform-owned chart and Runtime Access | 8090 future surface | Paused; no current acceptance role |

## Now, next, later

### Now

- Gate A is accepted at exact Root/backend/frontend SHAs with no unresolved P0 defect.
- Gate A.1 is accepted at exact Root/backend/frontend/strategy SHAs with no unresolved
  review finding.
- Gate A.2 DataSnapshot binding is accepted at Root `a933df5b`, backend `05f3d5845`,
  frontend `a71cf5b1`, and strategies `dbd5b0b`, with no unresolved P0/P1 finding.
- The forward-write Backtest artifact credential-redaction gap is accepted at Root
  `014c0f677` and backend `c8fb9af73`. Historical artifact remediation and credential
  rotation remain separately authorized operations.
- Gate A.3 Backtest Strategy Evidence is accepted at Root `091a797a3`, backend
  `d254eed96`, frontend `29097e95b`, and unchanged strategies `dbd5b0b`, with no
  unresolved Blocker, High, or Medium finding inside its boundary.
- Result-local Retained DataSnapshot Replay is accepted at Root `02563c1d`, backend
  `9baff126f`, frontend `e2b5e36c`, and unchanged strategies `dbd5b0b`. It reuses the
  same retained standard market rows under the current execution context and does not
  claim the same result, full environment reproduction, Paper eligibility, or profit.
- Gate A.4 Backtest Execution Context Evidence is accepted at Root `290fecbe8`, backend
  `3209d4374`, frontend `17e88f2d6`, and unchanged strategies `dbd5b0b21`, with no
  unresolved Blocker, High, or Medium finding. Its boundary remains a static-PairList,
  receipt-local, three-component correlation fingerprint, one engine-owned CLI/API seal,
  a fail-closed Cross Margin wallet rule, proxy-wallet stake-clamp binding,
  formula-consumed liquidation-rate binding, allowlisted and resource-bounded Strategy
  Evidence v2, and an existing Backtest UI extension. It is not Environment Identity or
  an environment-restoration platform.
- Preserve Phase 2D Tasks 1-4 as reusable, unpublished backend assets.
- Keep Phase 2D Tasks 5-8, Phase 2E, Experiment UI, dynamic Runtime, Paper Observation,
  and new Research scope paused.

### Next

No implementation plan is active. Reassess whether a small revision-bound
robustness/holdout evidence slice is the next real user need before activating it. Keep
optimization/ranking, continuous AI insight capture, dynamic RuntimeInstance, formal
Paper Observation, Experiment UI, and platform cutover paused until their prerequisites
and user journey are separately selected.

### Later

- dynamic BotRelease-owned Paper RuntimeInstances;
- bounded Paper Observation and evidence;
- platform UI consolidation and controlled compatibility cutover;
- additional venues, products, research markets, and only then separately governed Live
  execution.

## Non-goals for Gate A

- raw trade ticks, sub-minute candles, WebSocket market streaming, or HFT;
- provisional official signals on the Forming Candle;
- a browser Python editor, Hyperopt UI, arbitrary parameter sweep, walk-forward optimizer,
  or second backtest engine;
- a new all-in-one workstation or a new 8090 chart;
- Experiment, BotRelease, RuntimeInstance, Supervisor, or cutover implementation;
- requiring a Paper trade to happen during the acceptance window;
- Live trading, real orders, exchange writes, or listener retirement.

## Resume policy

A paused track resumes only when all of the following are recorded:

1. the Baseline Capability Gate passed at exact Root/backend/frontend SHAs;
2. no unresolved P0 baseline defect remains;
3. one next user journey and its measurable acceptance gate were explicitly selected;
4. the existing paused plan was reviewed against current product language and topology.

Passing Gate A alone does not resume Phase 2D Task 5, dynamic Runtime, Paper Observation,
Experiment UI, or Phase 2E.
