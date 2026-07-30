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

An immutable content-addressed offline dataset identity used by Backtest, Lookahead, and
Recursive Analysis. Paper Observation records what was observed over time and is not
misrepresented as exact DataSnapshot replay.

_Avoid:_ mutable data directory, latest data.

### Freqtrade Run ID

Freqtrade's deterministic backtest cache fingerprint over effective strategy config,
loaded parameter-file values, and strategy source bytes. Repeated equivalent inputs can
share it. It is neither a unique execution-attempt identity nor proof of the historical
candle contents.

_Avoid:_ ExperimentRevision ID, BacktestRun ID, DataSnapshot ID.

### Backtest Revision Receipt

A deterministic manifest attached to the standard Freqtrade backtest result and history
to correlate an Experiment ID, validated Backtest request, Freqtrade Run ID, and engine
version. When its `data_snapshot_id` is absent, it is pre-formal provenance only: it must
not be presented as exact replay proof, a platform-owned immutable Experiment ledger, or
Paper acceptance evidence.

_Avoid:_ formal ExperimentRevision when exact data content is unbound, StrategyRelease.

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
