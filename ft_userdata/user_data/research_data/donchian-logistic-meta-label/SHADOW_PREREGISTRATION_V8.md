# Donchian Logistic Publication and Mark/Funding Shadow Preregistration V8

Status: frozen before `2026-08-14T00:00:00Z` and before any V8
`--poll-once`, network access, publication receipt, projection, mark/funding
journal write, or accounting inspection. If this document, the V8 recorder, and
their non-self-referential freeze manifest are not all byte-frozen before that
boundary, V8 is invalid and must never collect evidence. V1 through V7,
`MODEL.json`, and the V7 recorder remain immutable.

V8 adds two independent observational evidence layers without changing V7:

1. publication evidence for when a fully written and replay-validated V7
   `event_prediction` was conservatively known to be published; and
2. exact pinned Freqtrade funding-accounting input from public OKX mark opens
   and funding settlements.

Neither layer is an exchange bill, fill, slippage, order, balance, position, PnL,
return, accuracy, or strategy-performance proof. V8 never chooses an exit or
computes funding cash, fees, PnL, or performance. The frozen Freqtrade candidate
remains the authority for exits and accounting execution.

## Frozen identity and boundary

- Prospective boundary: `2026-08-14T00:00:00Z`, exclusive.
- Exchange: `okx`.
- Symbol: `BTC/USDT:USDT`.
- Mark timeframe: `1h`.
- V7 preregistration SHA-256:
  `7ac3404a0e1b80a8a9896bb0411c23e88c564a6e8ceed5d0aa86fc4f38c962db`.
- V7 recorder SHA-256:
  `dc8869c4803cf6a76c6a24fa441c052cec2dd4d7f58668af9b19d79a9fba6c8c`.
- Frozen model SHA-256:
  `160d63c4622620258ac9c76d9bf14ad5c46e579ed971c4caa61d7093aacaad24`.
- Pinned Freqtrade funding conversion source SHA-256
  (`freqtrade/freqtrade/data/converter/converter.py`):
  `b262fbfe02b2fd81c4c89f3fdf004a0008aed828e20ec0ac75b5d1f9c2c093cb`.
- Pinned Freqtrade funding/mark join source SHA-256
  (`freqtrade/freqtrade/exchange/exchange.py`):
  `384716d8c7df55385ffabc261f05b31d1810d5643cfadb465f19bdcf2a78bf8c`.
- Pinned Freqtrade floor-frequency source SHA-256
  (`freqtrade/freqtrade/exchange/exchange_utils_timeframe.py`):
  `eff0ba69f833dabe101d4fa31f78a6709ab58a3dcedddc8c7e8cdffed4281dc6`.
- Pinned Freqtrade git identity:
  `b1121f89512f6af1a99b4d3929d4405093363c99`.
- Pinned CCXT package version: `4.5.73`.
- Pinned CCXT OKX source SHA-256
  (`freqtrade/.venv/Lib/site-packages/ccxt/okx.py`):
  `69c2c74878abdaab102221dc91d1dcadc7a3da71543a9d45bad5fff3e1d23767`.
- Pinned CCXT base exchange source SHA-256
  (`freqtrade/.venv/Lib/site-packages/ccxt/base/exchange.py`):
  `426784bd6826ba3ca4b9fdcaa4480bba9ae647be7aeb68d1a773e459363bf453`.

`SHADOW_FREEZE_V8.json` is the non-self-referential freeze authority. It records
one `frozen_at` strictly before the boundary plus the exact byte SHA-256 values of
this document and the finished V8 recorder. Before any V8 poll setup, network
call, lock, or write, the recorder must validate the manifest's strict canonical
schema, boundary, paths, V7 hashes, model hash, V8 hashes, and pre-boundary
`frozen_at`. A real poll additionally requires the operator to supply the
manifest's independently recorded byte SHA-256 with
`--freeze-manifest-sha256`; the manifest cannot authenticate its own contents.
The recorder validates that external digest, the strict manifest, and every
bound dependency byte hash before importing or executing the V7 module, opening
a lock, constructing a client, calling a network method, or writing. Both V8
journal headers bind all manifest fields and the manifest byte hash. Editing the
manifest cannot silently preserve an existing header. Tests are verification
artifacts and are deliberately not part of the runtime identity.

## Invocation and public API boundary

The default invocation prints a deterministic plan and performs no network access,
creates no journal or lock, and writes nothing. Only explicit `--poll-once` may
collect. It first calls the frozen V7 `poll_once` wrapper. V8 passes no credentials
and may subsequently call only these public CCXT methods:

- `fetch_ohlcv("BTC/USDT:USDT", "1h", ..., {"price": "mark"})`;
- OKX `publicGetPublicFundingRateHistory(...)`.

V8 first requires public CCXT capability `has["fetchMarkOHLCV"] is True` and
must call `fetch_ohlcv("BTC/USDT:USDT", "1h", ...,
{"price": "mark", "paginate": false})` with a limit no greater than 100. V8
manually advances mark pages and validates every hour, rather than using CCXT's
automatic mark paginator. Funding bypasses CCXT's lossy unified parse/filter layer
and makes exactly one raw call with no `after`, `until`, or `paginate` field:
`publicGetPublicFundingRateHistory({"instId":"BTC-USDT-SWAP",
"before":cursor-1,"limit":100})`. The top-level response must have exactly
`code`, `msg`, and `data`, with `code == "0"`, `msg == ""`, and list `data`.
Before inspecting any item, V8 rejects raw `data` containing 100 or more items;
only a raw response shorter than 100 proves that the newest-page cap was not hit.
Every item then must have exactly `instType`, `instId`, `fundingRate`,
`realizedRate`, and `fundingTime`, identify the frozen swap, lie within the fixed
cursor/cutoff/observation bounds, and appear in strictly decreasing settlement-time
order without duplication. V8 explicitly reverses the admitted rows to ascending
journal order. Operational scheduling must keep the unseen raw funding backlog
below 100 records. V8 must never query or manage
orders, fills, balances, wallets, positions, trades,
leverage, or credentials. It is neither a daemon nor a scheduler.

## Publication receipt and projection journal

The independent canonical JSONL publication journal is
`ft_userdata/user_data/logs/donchian-logistic-publication-v8.jsonl`, protected by
its own fixed `.lock` sidecar.

Before calling V7, V8 takes a locked raw snapshot of the publication journal.
After V7 returns, V8 locks the V7 journal, rereads it through the V7 parser, and
performs complete V7 sequence, event, and label replay validation. Publication
selection reads only `event_prediction`; labels may be validated but must never
select, suppress, or alter an entry projection.

Publication is a two-durable-write protocol. Phase 1 appends and `fsync`s one
label-free `event_projection` for each V7 prediction not already projected. It
binds the symbol, decision, direction, execution time, complete V7 event semantic
SHA-256, and the exact validated V7 journal prefix byte length and SHA-256. It
fixes only entry/execution identity. It does not select an exit, read a label to
select entry, choose a price, calculate a fee, or calculate PnL.

Only after phase 1 append and `fsync` returns does V8 sample UTC
`projection_durable_at`. Phase 2 appends and `fsync`s exactly one first-seen
`publication_receipt` that references the complete projection record SHA-256 and
stores `eligible = projection_durable_at < execution_time`.
`projection_durable_at` cannot predate the event decision; clock regression fails
closed and leaves any already durable phase-1 projection as an orphan. A projection that
already existed without a receipt is first fully reread, replayed, pathname-checked,
and `fsync`ed; the current clock sample after that durability check becomes its
conservative `projection_durable_at`. This normally makes an old orphan projection
late. V8 never backdates it or manufactures a missing pre-execution durability fact.

`write_started_at`, if recorded, is auxiliary only and can never determine
eligibility. The later receipt write time also cannot determine eligibility: the
receipt is retrospective evidence of the already-durable phase 1 projection.
Offline eligibility is determined only by a valid receipt whose
`projection_durable_at` is strictly before execution. A projection with no receipt
is ineligible. An ineligible receipt is permanent and never causes a replacement
order. First writer wins under the publication lock; later exact linkage is an
idempotent no-op and changed linkage is a hard conflict.

Publication evidence is independent of mark/funding collection. Once V7 has
returned and publication replay succeeds, publication additions are durably
appended before mark/funding network calls. A later mark/funding failure must not
erase the publication fact, and a publication success must not be reported as an
accounting success.

## Mark and funding accounting journal

The independent canonical JSONL accounting journal is
`ft_userdata/user_data/logs/donchian-logistic-mark-funding-v8.jsonl`, protected by
its own fixed `.lock` sidecar.

`mark_open_observation` records preserve the exact exchange timestamp and finite
positive open returned by the explicit mark-price `fetch_ohlcv` call. High, low,
close, and volume are deliberately neither inspected nor stored: pinned
Freqtrade funding accounting consumes the current one-hour mark candle's open
with `drop_incomplete=False`. The first mark opens exactly at the boundary.
Thereafter mark opens are strictly consecutive at one-hour intervals with no
duplicate, missing timestamp, overlap, or revision. The currently forming hour
is admissible as soon as it is first returned at or after its open; waiting for
the hour to close would discard the earliest public observation relevant to the
settlement-hour join. The source method and first `observed_at` are immutable.

`funding_settlement` source records preserve both the exact raw `fundingTime`
returned by OKX `publicGetPublicFundingRateHistory` and the finite `realizedRate`.
Funding cadence is not assumed to be eight hours or any other fixed interval. Only
raw timestamps strictly after the boundary are eligible.

For every funding row, V8 fail-closed verifies the raw response directly:
`instType` must be `SWAP`, `instId` must be `BTC-USDT-SWAP`, `fundingTime` must be
canonical integer millisecond text, and `fundingRate` and `realizedRate` must be
finite numeric text. Only `realizedRate` is the accounting input; CCXT unified
funding rows and their filtered `info` projections are neither called nor trusted.
The source method is frozen as
`ccxt.okx.publicGetPublicFundingRateHistory`; the raw item is verified but not
copied into the journal.

V8 pins the current Freqtrade conversion and join semantics. For timeframes longer
than one minute, `ohlcv_to_dataframe` floors the raw millisecond timestamp to its
UTC minute, and `combine_funding_and_mark` performs an exact inner merge on the
resulting `date`. V8 therefore stores:

- `raw_settlement_timestamp_ms`, unchanged from CCXT; and
- `accounting_timestamp_ms`, exactly the UTC-minute floor of the raw timestamp.

It never silently rewrites or discards the raw timestamp. Multiple raw timestamps
mapping to one accounting minute are a collision and fail closed, even if their
rates agree.

A settlement source may be recorded before its exact mark open is available; this
preserves its actual first observation. It remains pending and is not
accounting-ready. Once the one-hour mark open at the exact
`accounting_timestamp_ms` has been observed, V8 must append one
`funding_accounting_join`. That join references the canonical SHA-256 of both the
funding source record and mark-open record and stores exact `open_mark` and
`open_fund`. Both source records must precede it in journal order.

Every settlement whose accounting timestamp is at or before the continuous
observed mark-open tail must have one and only one exact join. A missing mark, a minute that is
not an exact 1h mark open, collision, duplicate, revision, changed rate, changed
mark, missing required join, or conflicting join fails closed before any append.
V8 forbids funding fallback, cadence synthesis, interpolation, nearest-time matching,
and trade-price or index-price proxy substitution.

The source methods and first observations are evidence fields, not semantic
duplicates to overwrite. A repeated API identity with unchanged market values is
an idempotent no-op that preserves the original observation. A changed mark open
or funding rate is a hard revision conflict. For a mark-open record, the only stored
market value subject to this comparison is `open`; forming high, low, close, and
volume are outside the V8 schema.

## Independent replay, prefix integrity, and durability

V8 has its own strict parsers, schemas, identity keys, semantic comparison, replay,
and sequence validators. The V7 parser must never parse either V8 journal. V8 may
copy only the behavior of the frozen V7 module's schema-neutral canonical encoder,
sidecar lock, descriptor open/create, pathname identity, complete-write, flush,
`fsync`, Windows
`CREATE_NEW`/write-through, and POSIX parent-directory durability helpers.

For each V8 journal, the pre-network raw bytes, parsed records, existence, and
descriptor identity are retained. At the second locked read, a preexisting path
must still name the same descriptor identity and the current canonical bytes must
begin with the exact retained byte prefix. Same-inode truncation, rewrite,
replacement, reordering, torn JSON, malformed JSON, noncanonical JSON, zero-byte
files, duplicate identities, and invalid sequence all fail closed without a V8
append. Complete concurrent canonical additions after the prefix are reread,
replayed, and reconciled normally.

All prospective records are schema-validated, reconciled, and fully replayed in
memory before creating an initially absent journal. Creation is exclusive. Append
is canonical finite JSONL through the already-open descriptor, verifies complete
write length and pathname identity, flushes, and `fsync`s data; first POSIX
creation then `fsync`s the existing parent directory. Empty append still verifies
descriptor identity. Scheduling remains outside V8.
