# Product Strategy and Delivery Policy

**Status:** Governing product and delivery strategy

**Current status authority:** [README.md](README.md)

**Latest completed execution plan:**
[Backtest Artifact Secret Redaction](plans/2026-07-31-backtest-artifact-secret-redaction.md)

**Active execution plan:** none; the bounded strategy-evidence slice must be specified
before implementation starts.

## Product purpose

The near-term product helps a local strategy researcher answer three questions with
evidence:

1. Is the market view current enough to review the strategy?
2. What indicators, signals, and executions did the strategy produce, and which source
   does each point come from?
3. Does the same strategy pass reproducible Freqtrade backtesting and safety analysis
   before any governed Paper observation?

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
- Preserve Phase 2D Tasks 1-4 as reusable, unpublished backend assets.
- Keep Phase 2D Tasks 5-8, Phase 2E, Experiment UI, dynamic Runtime, Paper Observation,
  and new Research scope paused.

### Next

After the active security correction passes its exact-SHA Gate, prioritize the smallest
strategy-evidence binding that proves the loaded primary strategy source and resolved
parameters used by a Backtest. Environment identity and retained snapshot payload/replay
remain separate later candidates. Dynamic runtime infrastructure is still not implied
or active.

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
