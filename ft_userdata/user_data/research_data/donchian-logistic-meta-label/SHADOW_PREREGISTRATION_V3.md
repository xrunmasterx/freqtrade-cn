# Donchian Logistic Prospective Shadow Preregistration V3

Status: frozen before any `--poll-once`, network access, journal event write, prospective
prediction, label, or performance inspection. This document supersedes
`SHADOW_PREREGISTRATION_V2.md` for all operational shadow collection. V1 and V2 remain
immutable audit evidence. V3 retains V2's full-snapshot recursive-state bridge and corrects
restart cursors and journal-corruption handling before the first operational poll.

The recorder is observational only. It may fetch public market data but must never use
credentials, place or manage orders, run continuously, or report aggregate accuracy, PnL,
returns, or any other performance result.

## Fixed artifacts and time boundaries

- Prospective boundary: `2026-08-14T00:00:00Z`, exclusive. Only an exact decision time
  strictly after this boundary may produce an `event_prediction` or `event_excluded`.
- Recursive indicator seed origin: `2022-02-01T00:00:00Z`, inclusive.
- Operational base 15-minute snapshot:
  `ft_userdata/user_data/data/okx-btc-usdt-swap-full-20260813/market-data/futures/BTC_USDT_USDT-15m-futures.feather`.
- Operational base 15-minute byte SHA-256:
  `078f646d904a2964f66b5f0eb40f8e055396a5a43ed994cb25c8d52710626407`.
- Operational base 5-minute snapshot:
  `ft_userdata/user_data/data/okx-btc-usdt-swap-full-20260813/market-data/futures/BTC_USDT_USDT-5m-futures.feather`.
- Operational base 5-minute byte SHA-256:
  `77b4e092736cf2f4484555e6c3c76db30dbe78508aeb1c03d2aceafdaa948851`.
- The operational seed is each bound full snapshot sliced from the fixed seed origin. The
  last base timestamp is read from and validated against that bound file; it is not a
  separately hard-coded F3 boundary.
- Frozen model path:
  `ft_userdata/user_data/research_data/donchian-logistic-meta-label/MODEL.json`.
- Frozen model byte SHA-256:
  `160d63c4622620258ac9c76d9bf14ad5c46e579ed971c4caa61d7093aacaad24`.

Before a network call or journal append, the implementation must independently validate the
complete nested model schema, JSON types, finite numeric values, and protocol constants. It
must first validate this exact V3 byte hash, then validate both full-snapshot hashes, their
strict UTC OHLCV schemas, exact interval continuity after slicing from the seed origin, and
closed final rows. The full snapshots' common 2022-2023 interval must match the F3
development snapshots by exact timestamps and OHLCV values; this is structural input parity
only and authorizes no model or market performance inspection. A coherent self-hash does
not admit a malformed artifact.

## Prospective computation window

For every post-boundary base breakout, stamp `computed_at` from the UTC clock used after all
required input responses have been fully received. An `event_prediction` is permitted only
when `computed_at < decision_time + 5 minutes`. If
`computed_at >= decision_time + 5 minutes`, append exactly one `event_excluded` with reason
`late_computation`; do not calculate or store a prediction and never mature a label for that
event. This strict rule forbids outage catch-up from becoming a retrospective prediction.

## One-shot collection protocol

The default invocation prints a deterministic plan and performs no network access and no
writes. Only explicit `--poll-once` performs one restartable collection cycle. Each cycle
uses an unauthenticated public CCXT OKX client and only:

- `fetch_ohlcv("BTC/USDT:USDT", "15m", ...)`;
- `fetch_ohlcv("BTC/USDT:USDT", "5m", ...)`; and
- `fetch_funding_rate_history("BTC/USDT:USDT", ...)`.

Each successful response is stamped with `observed_at` after the full response is received.
Only closed candles are eligible. Exchange timestamps remain exact and are never floored or
rewritten. New rows must extend the bound full-snapshot and journal prefixes without gaps or
revisions. Malformed, incomplete, revised, or conflicting inputs fail closed. A transient
network failure appends no predictions and is retried on a later invocation.

Because the exchange `since` cursor is inclusive, an OHLCV restart after an existing
journal candle starts at exactly `last_timestamp + timeframe_interval`; without a journal
candle it starts at `seed_last_timestamp + timeframe_interval`. A funding restart after an
existing observation starts at exactly `last_timestamp + 1 millisecond`; without one it
starts at `prospective_boundary - 10 hours`. A second poll therefore neither requests nor
appends an already-recorded identity.

A funding observation preserves the exact standardized CCXT timestamp and rate. It becomes
eligible only at the first 15-minute boundary strictly after its `observed_at`. At a
decision, its event timestamp must be no later than the decision and its age must be at most
10 hours.

## Journal and outcomes

The sole runtime output is the gitignored file
`ft_userdata/user_data/logs/donchian-logistic-shadow.jsonl`, protected by an exclusive
single-writer lock. It is canonical finite JSONL and append-only. A torn incomplete tail,
missing final newline, malformed JSON, noncanonical line, invalid record, duplicate, or any
other journal damage fails closed without truncation, repair, append, or any byte change.

The immutable header binds this V3 preregistration, the frozen model, both full operational
snapshots, seed origin, prospective boundary, exchange, symbol, and timeframes. The journal
then contains exact closed candles, exact funding availability evidence, and exactly one
atomic `event_prediction` or `event_excluded` for each post-boundary base breakout. A timely
prediction may later receive one `label_matured` record only after exactly 577 closed
5-minute rows from decision through deadline and observation at least 48 hours plus 5
minutes after decision.

Predictions, exclusions, and labels are idempotent by exact event identity. An identical
repeat is a no-op; a different record for the same identity is a hard conflict. Labels scan
the exact 5-minute path in timestamp order using the frozen long/short order: gap stop, gap
target, intrabar stop, intrabar target, with stop first on a same-candle tie and deadline
open before deadline range. Evidence must never be aggregated into performance reporting.

Scheduling is outside this implementation. An operator must invoke `--poll-once`
periodically after the prospective boundary.
