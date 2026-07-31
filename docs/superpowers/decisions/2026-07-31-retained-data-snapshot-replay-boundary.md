# ADR: Result-local retained DataSnapshot replay

**Date:** 2026-07-31

**Status:** accepted for implementation

## Context

The accepted DataSnapshot v1 contract identifies the normalized logical OHLCV rows
admitted to a standard Freqtrade Backtest, but it retains only manifests and hashes.
When local history files are corrected, replaced, or removed, a researcher can tell that
two old results used different data but cannot run a new candidate against the old rows.

The next slice must close that user loop without creating a general dataset platform.
The irreversible choices are where the payload lives, how source-role routing is
retained without changing the accepted DataSnapshot identity, and what "replay" is
allowed to claim.

## Decision

Each newly retained API-2.54 standard Backtest stores one replay bundle inside its
existing Backtest ZIP. The bundle contains:

- the unchanged DataSnapshot v1 manifest;
- the exact existing canonical 48-byte row encoding, once per unique series digest;
- an ordered route manifest mapping each admitted `primary`, `detail`, `informative`,
  `funding`, or `mark` observation to its series digest; and
- a domain-separated `replay-payload-...` identity over the replay manifest.

The receipt binds a small replay-evidence record containing the DataSnapshot ID, row
encoding, and replay-payload ID. Source roles remain outside DataSnapshot v1, so the
accepted `data-series-...` and `data-snapshot-...` identities do not change. Reusing one
logical series through more than one role stores its row bytes once while retaining each
route.

Replay is selected from one existing history row. The browser sends only the result stem
and source strategy name; it never sends a filesystem path or candle rows. The server
resolves the local in-directory ZIP and sidecar, verifies the receipt, replay manifest,
member inventory, sizes, every series digest, the DataSnapshot digest, and route
references, then supplies the reconstructed frames to the existing Freqtrade
Backtesting/DataProvider paths.

Every standard OHLCV access in replay mode is replay-only. A missing, corrupt,
ambiguous, newly requested, or unconsumed route fails the run. It never falls back to
`history.load_data`, `load_pair_history`, latest candles, or exchange OHLCV. A fresh
DataSnapshot recorder must observe the complete retained route set and reproduce the
source DataSnapshot ID before a new result is published.

The current installed strategy is executed and may have different captured source or
resolved parameters. Archived Python, parameter, config, analysis, and joblib members
are never executed as replay authority. Retention and replay force capture of the current
strategy evidence even when a raw client omits that optional request flag. The new
receipt records that evidence and the effective current request, so a compatible strategy
change can be compared against the same retained data.

Replay does not freeze the complete execution context. Freqtrade may still initialize
current exchange simulation inputs such as markets, fees, precision, options, and
Futures leverage tiers. Those inputs, the software/container environment, imported
helpers, and arbitrary strategy I/O remain explicitly unbound. The user-facing promise
is therefore "same retained standard market data under the current execution context,"
not "the same result" or "complete reproducibility."

## Publication and resource boundary

Replay retention is an explicit opt-in in both the API and updated FreqUI because row
payload has material disk cost. It requires an Experiment ID, DataSnapshot capture,
server-enforced current strategy-evidence capture, an exported result, and the existing
unsupported-input exclusions. Selecting an existing bundle for replay does not
automatically duplicate it into the new result; the user may separately retain that
result when another independent replayable artifact is useful.

The result ZIP is written to a unique sibling temporary file, closed, fully replay-
verified, and atomically published before the metadata sidecar and latest-result pointer
are published. The API uses a collision-resistant result suffix. A failure before ZIP
publication leaves no addressable replay artifact or bound receipt.

Version 1 accepts at most 1,000,000 unique canonical rows, or 48,000,000 row bytes, per
replay bundle. The limit matches the accepted measured DataSnapshot scale and prevents
an unbounded local decompression/memory commitment. Ordinary legacy or capture-only
Backtests are not reinterpreted as replayable.

Canonical row members use ZIP `STORED`: the measured compression CPU cost exceeded the
accepted end-to-end retention gate, while direct storage preserved a 0.777-second
capture-and-verified-publication path at the one-million-row limit. The resulting maximum
artifact cost is approximately 48 MB plus bounded ZIP and manifest overhead. Retention
therefore remains explicit and off by default; a shared content-addressed store is
reconsidered only if measured disk pressure justifies its additional lifecycle policy.

Replay reads exact fixed member names without extraction. Duplicate names, unexpected
members below the replay prefix, traversal-like names, non-canonical manifests,
unsupported schemas or encodings, inventory mismatches, and over-limit payloads fail
closed. Deleting a Backtest result deletes its embedded replay payload through the
existing result lifecycle.

## Consequences

- A user can change or remove the original candle files and still run the existing
  authoritative Freqtrade engine against the retained logical rows.
- Existing schema-1, schema-2-without-replay, API-2.52, API-2.53, and legacy artifacts
  remain loadable but are visibly not replayable.
- Results remain self-contained with respect to the retained market rows and deletion;
  no reference counting, garbage collector, snapshot database, or new storage root is
  required.
- Identical data is duplicated across result ZIPs. This is accepted until measured disk
  pressure justifies a separate content-addressed store and its lifecycle policy.
- Hash verification detects corruption and mismatches but does not prove authenticity
  against an actor able to rewrite both payload and receipt.
- Equal replayed DataSnapshot and strategy evidence still do not prove equal results,
  Paper eligibility, contract-trading safety, or future profitability.

## Rejected alternatives

### External CAS or snapshot database now

Rejected as premature. It would add references, concurrent deduplication, quotas,
garbage collection, result deletion semantics, import/export bundling, and another
operational root before storage pressure has been measured.

### Separate payload file beside each result

Rejected because two-object publication and deletion create dangling-reference and
cleanup behavior without adding user value over the existing ZIP.

### Restore archived strategy and complete environment during replay

Rejected because executing archived code and recreating exchange/environment inputs
would expand this slice into StrategyRelease, Environment Identity, effective-config,
artifact-trust, and offline-exchange simulation work. Those are separate evidence gates.

### Generic snapshot picker, upload, or CRUD

Rejected. The first journey needs only one action on a verified retained Backtest result.
Untrusted uploads and a catalog would introduce lifecycle and archive-security policies
that the local history workflow does not need.
