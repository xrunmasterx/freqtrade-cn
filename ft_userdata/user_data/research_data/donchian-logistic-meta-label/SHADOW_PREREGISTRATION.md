# Donchian Logistic Prospective Shadow Preregistration

This document fixes the prospective shadow protocol before implementation and before any
network access. The recorder is observational only: it may fetch public market data, but it
must never use credentials, place or manage orders, run continuously, or report aggregate
accuracy, PnL, or returns.

## Fixed artifacts and time boundaries

- Prospective boundary: `2026-08-14T00:00:00Z`, exclusive. A breakout may produce an
  `event_prediction` or `event_excluded` only when its exact `decision_time` is strictly
  greater than this boundary.
- Recursive indicator seed origin: `2022-02-01T00:00:00Z`. Indicators are seeded from the
  existing complete OKX 15-minute snapshot beginning at that instant, followed only by
  append-only, exact-timestamp newer closed candles.
- Frozen model path: `ft_userdata/user_data/research_data/donchian-logistic-meta-label/MODEL.json`.
- Frozen model byte SHA-256:
  `160d63c4622620258ac9c76d9bf14ad5c46e579ed971c4caa61d7093aacaad24`.
- The recorder header binds the byte SHA-256 hashes of the existing base 15-minute and
  5-minute snapshot files. A changed model or snapshot is a hard conflict, not a new run.

Before any network call or journal append, the implementation must independently validate
the complete nested model schema: exact keys, JSON types (including rejection of booleans
where numbers are required), finite numeric values, and all protocol constants. A coherent
self-hash on a malformed model is insufficient. Any model, input, boundary, or existing
journal conflict fails closed.

## One-shot collection protocol

The default invocation prints a deterministic plan and performs no network access and no
writes. Only explicit `--poll-once` performs one restartable collection cycle. Each cycle
uses an unauthenticated public CCXT OKX client and only:

- `fetch_ohlcv("BTC/USDT:USDT", "15m", ...)`;
- `fetch_ohlcv("BTC/USDT:USDT", "5m", ...)`; and
- `fetch_funding_rate_history("BTC/USDT:USDT", ...)`.

Each successful response receives an `observed_at` timestamp taken after the full response
has been received. Only closed candles are eligible. Candle timestamps remain exact and
must never be floored or otherwise rewritten. New candle history must extend the bound
snapshot and journal prefixes without gaps or revisions; malformed, incomplete, revised,
or conflicting data fails closed. A transient network failure appends no predictions and
is retried by a later invocation.

A funding observation preserves the exchange's exact standardized timestamp and rate. It
becomes available only at the first 15-minute boundary strictly after its `observed_at`.
At a decision, funding is eligible only when its event timestamp is no later than the
decision and its age is at most 10 hours.

## Journal and outcomes

The sole runtime output is the gitignored file
`ft_userdata/user_data/logs/donchian-logistic-shadow.jsonl`, guarded by an exclusive
single-writer lock. It is canonical finite JSONL and append-only. A torn trailing record
may be repaired only by truncating that incomplete tail while holding the lock; any
conflict in complete records fails closed.

The journal contains:

1. one immutable header binding this preregistration, the frozen model, the two snapshots,
   the seed origin, prospective boundary, exchange, symbol, and timeframes;
2. exact closed 15-minute and 5-minute candle observations needed to extend the bound
   prefixes;
3. exact funding observations with their post-receipt `observed_at` availability evidence;
4. exactly one atomic `event_prediction` or `event_excluded` for every post-boundary base
   breakout; and
5. one later `label_matured` record when the event has exactly 577 closed 5-minute rows
   from decision through deadline and the observation time is at least 48 hours plus
   5 minutes after decision.

Predictions and exclusions are idempotent by exact event identity. A repeated identical
record is a no-op; a different record for the same identity is a hard conflict. Labels use
the frozen long/short barrier ordering and deadline rules: scan the exact 5-minute path in
timestamp order, apply the model's declared within-candle tie policy, and use the deadline
outcome only when neither barrier was reached earlier. Labels are evidence records only and
must not be aggregated into performance reporting.

Scheduling is deliberately outside this implementation. An operator must invoke
`--poll-once` periodically after the prospective boundary.
