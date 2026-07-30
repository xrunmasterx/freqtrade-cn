# ADR: Content-address normalized logical market data

**Date:** 2026-07-31

**Status:** accepted

## Context

The accepted Backtest Revision Receipt identifies an Experiment ID, the validated
Backtest request, Freqtrade Run ID, and engine version, but its `data_snapshot_id` is
null. A timerange and mutable data directory cannot distinguish a strategy improvement
from downloaded-data drift, provider corrections, cache reuse, or a changed informative
series.

The identity boundary is hard to reverse once IDs appear in retained Backtest history.
Two candidates were evaluated:

- hash source files or a data directory;
- hash the normalized logical rows that Freqtrade actually makes available to the run.

## Decision

`DataSnapshot` identifies the second boundary. Version 1 hashes the exact normalized
offline OHLCV slices admitted to one revision-bound standard Freqtrade Backtest:
primary data including startup rows, detail-timeframe data, every historical
DataProvider informative access, and the raw funding plus selected mark/index/premium
series used by Futures mode.

Each series identity includes venue, pair, timeframe, candle type, selected coverage,
row count, and a SHA-256 digest of canonical rows. Canonical rows use UTC Unix
milliseconds, ordered OHLCV fields, IEEE-754 binary64 values, normalized positive zero,
and no NaN or Infinity. The manifest is order-independent and receives its own
domain-separated SHA-256 `data-snapshot-...` identity.

Capture happens at the existing loader/access boundaries. The normalized frame that is
hashed is also the frame retained by Backtesting or DataProvider, so the implementation
does not hash a later disk re-read. Paths, filenames, mtimes, compression, data-handler
format, credentials, and operational configuration are excluded.

The manifest and digests are retained in the normal Backtest metadata. This decision
does not archive the canonical row payload or add replay selection. Therefore the first
slice proves equality of the bound standard market-data inputs, but does not claim that
the data can be reconstructed after local source files are removed.

## Consequences

- Equivalent JSON, Feather, or Parquet storage can produce the same DataSnapshot when
  Freqtrade admits the same logical rows.
- A selected startup, primary, detail, informative, funding, or mark value change changes
  the DataSnapshot and the enclosing Backtest Revision Receipt.
- Changes to paths, storage encoding, mtimes, unrelated files, or rows outside every
  selected window do not change the identity.
- Revision-bound capture uses a fresh Backtesting/DataProvider instance and fresh data
  load; result-cache reuse remains disabled.
- Receipt schema 2 requires a verified non-null DataSnapshot. Schema 1 remains the
  compatible receipt-only state, and results without a receipt remain legacy/unbound.
- FreqAI, public-trade/orderflow input, and configured external data producers fail a
  capture request until all of their non-OHLCV inputs can be bound. A normal legacy or
  schema-1 Backtest is not changed by this restriction.
- Exchange market metadata, fees, precision, leverage tiers, FreqAI models, arbitrary
  strategy-owned I/O, software dependencies, result-artifact integrity, and data-payload
  retention remain separate identities or later gates. Equal DataSnapshot IDs alone do
  not prove equal results, replayability, Paper acceptance, or future profitability.

## Rejected alternatives

### Hash raw files or the whole directory

Rejected because compression, metadata, format, path, and unselected rows would change
identity without changing Backtesting input, while multiple lazy input paths could still
be missed.

### Hash only primary data or final signal rows

Rejected because detail data, informative series, Futures auxiliaries, and startup rows
can affect results before final rows are produced.

### Build a persistent snapshot object store now

Deferred. A content-addressed row store and “rerun this exact historical snapshot” are
valuable later, but they require retention, cleanup, atomic publication, and replay
policies that are not needed to answer the immediate comparison question. The versioned
manifest is designed so payload retention can be added without changing v1 identity.
