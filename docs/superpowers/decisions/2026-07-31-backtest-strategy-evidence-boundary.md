# ADR: Bind Backtest evidence to captured primary source and resolved parameters

**Date:** 2026-07-31

**Status:** accepted for implementation

## Context

The existing Freqtrade Run ID and Backtest ZIP look like strategy identity evidence, but
both can reread mutable files after the strategy has already been loaded. A long Backtest
can therefore execute one strategy while its cache fingerprint or archived source and
parameter file describe a later edit. Merely showing the Run ID would expose this
ambiguity; creating StrategyRelease now would also activate release persistence,
promotion, and Runtime concerns that Product Phase 1 has explicitly paused.

## Decision

Add an independently versioned `Backtest Strategy Evidence` submanifest to the existing
Backtest Revision Receipt. Capture the exact primary-module source bytes that the resolver
compiles, restore them after strategy construction, and seal an engine-owned copy before
strategy lifecycle callbacks. Then capture the supported resolved Freqtrade parameter values after
`ft_bot_start` and before indicator evaluation. Domain-separated SHA-256 component
digests identify those two retained payloads; the enclosing revision digest binds the
submanifest.

API 2.53 exposes an optional capture request. Updated FreqUI requests it automatically
for revision-bound Backtests, while clients that omit it and all existing schema-1,
schema-2, and legacy results keep their current contract. The evidence object is
orthogonal to DataSnapshot, so the outer receipt schemas do not multiply merely to
represent another independently missing or present identity.

When capture is requested, the ZIP writer receives the same in-memory source and
canonical resolved-parameter payloads used to create the digests. It preserves the
existing source/optional parameter member names from load-time snapshots and adds one
per-strategy evidence member for the resolved payload; it must not reread the strategy or
adjacent parameter file after execution. Capture failure produces no bound receipt or
artifact.

## Consequences

- Result, history, selector, and comparison views can report strategy evidence as same,
  different, or unknown independently of market-data identity.
- Freqtrade Run ID remains a native cache fingerprint, and engine version remains partial
  provenance; neither is renamed or promoted to exact strategy/environment identity.
- The boundary covers the primary strategy module and Freqtrade's supported resolved
  parameter surface. Imported modules, FreqAI models, arbitrary strategy I/O, runtime
  mutation after capture, dependency/environment identity, replay retention, artifact
  authenticity, Paper acceptance, and profitability remain unproven.
- The component identities may inform a future StrategyRelease, but this decision creates
  no release object, registry, CAS, promotion workflow, or Runtime dependency.

## Rejected alternatives

- **Only display Run ID and engine version:** too weak and currently TOCTOU-prone.
- **Create StrategyRelease now:** too broad for the offline validation journey and would
  prematurely cross the paused Gate B boundary.
