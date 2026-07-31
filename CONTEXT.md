# Shared Domain Context

This glossary defines the product language shared by the Root repository, backend, and
FreqUI. It describes domain meaning, not current implementation status; use
`docs/superpowers/README.md` for the current development state.

## Delivery terms

### Product Phase 1

The current user-outcome program: first pass the Baseline Capability Gate, then make a
separate decision about a governed Experiment-to-Paper slice. It is not the "Phase 1
Market Catalog" taxonomy in the dated platform architecture.

_Avoid:_ unqualified "Phase 1" when the product program and architecture taxonomy could
both be meant.

### Baseline Capability Gate

Acceptance of the existing strategy-validation loop using compatibility services:
minute-candle observation, strategy indicators and signals, execution evidence, and
authoritative Freqtrade backtesting. It does not accept a managed RuntimeInstance, a
dynamic Paper Bot, or a platform cutover.

_Avoid:_ 8081 gate, Paper acceptance, Runtime acceptance.

### Compatibility Service

A fixed pre-cutover service retained to preserve an existing product journey and provide
migration evidence. It is not a Runtime Registry `RuntimeInstance` and is not the
permanent product model.

_Avoid:_ fixed Bot, Compatibility Runtime, permanent service.

## Market and chart terms

### Minute-Candle Near-Real-Time Observation

Read-only observation whose minimum candle timeframe is one minute and whose fastest
normal polling cadence is approximately ten seconds. It is neither a raw-trade tick
stream nor an exact real-time, low-latency, or HFT guarantee.

_Avoid:_ tick-level feed, real-time stream, high-frequency trading.

### Forming Candle

The final candle whose interval has not reached its close boundary. Its market values and
Watch Indicators may change; it cannot create an official Strategy Signal.

_Avoid:_ final candle, immutable candle.

### Closed Candle

A candle whose interval has reached its close boundary and is eligible for official
strategy-indicator and signal semantics. Closed means interval-complete, not immune to a
later provider correction.

_Avoid:_ immutable candle.

### Watch Indicator

An observation aid calculated from the chart's market candles. A value on the Forming
Candle is provisional and is not evidence of what a strategy evaluated or used.

_Avoid:_ strategy indicator, decision evidence.

### Strategy Indicator

Indicator output from the strategy's analyzed-data contract, based on closed strategy
candles. It is not recomputed by FreqUI and must never be silently replaced by a Watch
Indicator.

_Avoid:_ chart indicator when the source matters.

### Strategy Signal

A strategy entry or exit condition aligned to a closed candle. A signal is not an Order,
Fill, Trade, or proof that execution occurred.

_Avoid:_ executed signal, actual trade.

### Trade

A persisted position lifecycle in a named environment, distinct from the Orders and
Fills that implement it. Qualify it as Paper Trade, Live Trade, or Simulated Backtest
Trade whenever the environment affects meaning.

_Avoid:_ actual trade, real trade.

### Execution Marker

A chart point derived from recorded Paper execution or simulated backtest evidence at its
recorded time and price. It must not be inferred from a Strategy Signal.

_Avoid:_ buy/sell signal marker when the point represents execution.

### Strategy Context Match

The condition that chart data and execution evidence bind to the same exact strategy
identity and relevant revision/release context. A matching display name alone is not
sufficient, and UI selection must not cause unrelated Runtime trades to be overlaid.

Gate A compatibility payloads can reject an explicit strategy-name mismatch and, when
both sides provide it, a strategy-timeframe mismatch. A name/timeframe match or a legacy
Trade missing either field is not a formal Strategy Context Match and must not be
promoted as governed Paper evidence.

_Avoid:_ same strategy when only names were compared.

## Validation and release terms

### Authoritative Backtest

A backtest executed by the standard Freqtrade backtest engine and presented from its
standard result/history contract. The simplified Research SMA calculation is not an
authoritative backtest.

_Avoid:_ Research backtest, second backtest engine.

### StrategyExperiment

A mutable research workspace that holds the user's evolving strategy-validation intent
and parameters. Formal runs never bind only to this mutable identity.

_Avoid:_ release, immutable experiment.

### ExperimentRevision

An immutable snapshot of a StrategyExperiment's strategy identity, parameters, data
selection, and validation configuration. Backtest, analysis, release, and later Paper
evidence bind to the exact revision. Formal comparison additionally requires the exact
content-addressed DataSnapshot and environment identity; a timerange or mutable data
directory is not enough.

_Avoid:_ mutable experiment, run result, StrategyRelease.

### DataSnapshot

An immutable, content-addressed manifest of the exact normalized offline market-data
series made available to Backtest, Lookahead, and Recursive Analysis. It identifies
logical input content independently of storage paths and formats. It does not by itself
prove that row payload is retained or replayable; strategy artifacts, environment
identity, and Paper Observation remain separate.

_Avoid:_ mutable data directory, latest data.

### DataSnapshot Replay Bundle

A result-local, versioned Backtest ZIP payload containing the canonical DataSnapshot
rows plus their admission-role routes. It allows the existing Backtest engine to consume
the same retained standard market data without falling back to mutable OHLCV files. It
does not restore archived strategy code, exchange simulation inputs, or the complete
software environment, and it does not promise the same result.

_Avoid:_ DataSnapshot ID, dataset catalog, Environment Identity, reproducible result.

### Freqtrade Run ID

Freqtrade's deterministic backtest cache fingerprint over effective strategy config,
loaded parameter-file values, and strategy source bytes. Repeated equivalent inputs can
share it. It is neither a unique execution-attempt identity nor proof of the historical
candle contents.

_Avoid:_ ExperimentRevision ID, BacktestRun ID, DataSnapshot ID.

### Backtest Strategy Evidence

A versioned, run-scoped record identifying the primary strategy source captured for
execution and the supported Freqtrade-resolved parameters used by an Authoritative
Backtest. Legacy v1 covers its original bounded parameter set; context-bound v2 owns the
exact declared Freqtrade-resolved strategy execution-setting allowlist, captured after
`ft_bot_start`, including custom ROI enablement and the protection list actually consumed,
so those values are not misclassified as environmental drift. It is not a StrategyRelease,
transitive dependency closure, Environment Identity, or authenticity proof.

_Avoid:_ Freqtrade Run ID, strategy version, StrategyRelease.

### Backtest Execution Context Evidence

A versioned, run-scoped fingerprint of the declared core-runtime versions, effective
simulation configuration, and admitted-pair exchange simulation facts sealed by an
Authoritative static-PairList Spot or Futures Backtest. Equality means only that declared
scope matched. The effective configuration includes the proxy-wallet balance that clamps
available capital; the exchange scope includes only a formula-consumed liquidation taker
rate, not a general fee model. It is not Environment Identity, authenticity proof,
equal-result proof, or environment restoration. Dynamic PairList execution has no v1
context claim.

_Avoid:_ Environment Identity, environment snapshot, reproducible environment.

### Backtest Revision Receipt

A deterministic manifest attached to the standard Freqtrade backtest result and history
to correlate an Experiment ID, validated Backtest request, Freqtrade Run ID, and engine
version. An absent `data_snapshot_id` is pre-formal provenance; a bound DataSnapshot adds
exact standard market-data identity. Optional replay evidence can bind a result-local
DataSnapshot Replay Bundle, but the receipt is still not complete environment/effective-
config proof, an immutable Experiment ledger, or Paper acceptance evidence.

_Avoid:_ formal ExperimentRevision when exact data content is unbound, StrategyRelease.

### Same-Window Strategy-Change Review

A neutral retrospective comparison of exactly two Authoritative Backtest results whose
exact DataSnapshot, bounded Backtest Execution Context Evidence, and effective scored
window match while valid Backtest Strategy Evidence differs. It identifies a controlled
comparison shape; it does not prove that the strategies share revision lineage, that one
is a baseline or candidate, or that an observed metric difference is an improvement.

_Avoid:_ StrategyRevision comparison, controlled experiment, candidate win.

### Cross-Window Review

A neutral retrospective comparison of exactly two Authoritative Backtest results whose
valid Backtest Strategy Evidence and bounded Backtest Execution Context Evidence match,
while exact DataSnapshots differ and effective scored windows are strictly disjoint. It
describes historical window sensitivity only. It does not prove that either window was
untouched, out of sample, representative, or predictive of future performance.

_Avoid:_ passed holdout, out-of-sample proof, robustness proof.

### StrategyRelease

An immutable content-addressed strategy artifact accepted for governed execution, with
its exact source and parameter identities. A branch, path, strategy name, or dirty
working tree is not a release identity.

_Avoid:_ strategy version, strategy path, running strategy.

### BotRelease

An immutable binding of one StrategyRelease, an environment, account bindings, risk
policy, and capability snapshot. Material changes create another release rather than
mutating a running Bot in place.

_Avoid:_ mutable Bot config, Bot instance.

### RuntimeInstance

A stable managed execution identity owned by an immutable release/revision and its
governed RuntimeSpec and state allocation. A restart creates a new attempt; a fixed
compatibility service, container, process, or port is not itself a RuntimeInstance.

_Avoid:_ container, process, service, RuntimeAttempt.

### Paper Observation

A time-bounded, read-only inspection of outputs and state produced by a Paper
RuntimeInstance. It is not a runtime identity, an exact replay guarantee, or formal
acceptance merely because a compatibility service ran in dry-run mode.

_Avoid:_ Paper Bot, paper_probe, Compatibility Service.
