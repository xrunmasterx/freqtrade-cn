# Donchian Logistic Prospective Shadow Preregistration V6

Status: frozen before any V6 `--poll-once`, network access, journal event write,
prospective prediction, label, or performance inspection. This document supersedes
`SHADOW_PREREGISTRATION_V5.md` for every operational poll. V1 through V5 remain
immutable audit evidence. The frozen `MODEL.json`, freezer, training data, features,
coefficients, operational seeds, market/data boundaries, `+5m` execution rule, and
577-row label path are unchanged and must not be retrained or modified.

The recorder is observational only. It may fetch public market data with only
`fetch_ohlcv` and `fetch_funding_rate_history`; it must never use credentials, query
orders, balances, or positions, place or manage trades, run as a daemon or scheduler,
or inspect or report prediction, model, trading, PnL, return, or other performance
results.

## Fixed artifacts and time boundaries

- Prospective boundary: `2026-08-14T00:00:00Z`, exclusive.
- Recursive indicator seed origin: `2022-02-01T00:00:00Z`, inclusive.
- Operational 15-minute snapshot:
  `ft_userdata/user_data/data/okx-btc-usdt-swap-full-20260813/market-data/futures/BTC_USDT_USDT-15m-futures.feather`,
  byte SHA-256 `078f646d904a2964f66b5f0eb40f8e055396a5a43ed994cb25c8d52710626407`.
- Operational 5-minute snapshot:
  `ft_userdata/user_data/data/okx-btc-usdt-swap-full-20260813/market-data/futures/BTC_USDT_USDT-5m-futures.feather`,
  byte SHA-256 `77b4e092736cf2f4484555e6c3c76db30dbe78508aeb1c03d2aceafdaa948851`.
- Frozen model:
  `ft_userdata/user_data/research_data/donchian-logistic-meta-label/MODEL.json`, byte
  SHA-256 `160d63c4622620258ac9c76d9bf14ad5c46e579ed971c4caa61d7093aacaad24`.

Before a network call or append, the recorder must validate this exact V6 byte hash,
the frozen model byte hash and complete nested schema, both operational seed byte
hashes and schemas, exact interval continuity, closed final rows, OHLC envelopes, and
exact F3 overlap. These are structural checks only and authorize no performance
inspection.

## Prospective prediction and deployable execution

For each post-boundary base breakout, `decision_time` is the close boundary of its
15-minute signal candle. Stamp `computed_at` only after all inputs used by the
prediction have been observed. A prediction remains timely only when
`decision_time <= computed_at < decision_time + 5 minutes`. A timely
`event_prediction` stores `execution_time` and `execution_time_ms` equal to the first
strict 5-minute boundary after `computed_at`; under the timely window this is exactly
`decision_time + 5 minutes`. The label entry is the open of that execution candle,
never the decision-time open. Its exact 577-row path and 48-hour horizon begin at
`execution_time`, and its deadline is `execution_time + 48 hours`.

This is the same conservative, deployable `+5m` execution audit frozen in V5. It
deliberately differs from the frozen training label, which used the next official
5-minute open from the historical decision convention. The model is not refitted.
All future V6 evidence therefore measures this stricter operational outcome, not the
frozen training-label outcome.

If `computed_at >= decision_time + 5 minutes`, append exactly one
`event_excluded` with reason `late_computation`, calculate and store no prediction,
and never mature a label. No event record may have `computed_at` before its decision.

## Exact replay with bounded validation work

Before network access and again after the second locked reread, reconstruct the exact
15-minute and 5-minute frames from the bound seeds plus the journal. In each validation
phase, build the 15-minute frame and recursive indicators at most once, and build the
5-minute timestamp index and observation map at most once. Thereafter each event or
label may use logarithmic history lookup, a fixed 577-row label path, or a single linear
total scan; it must not rebuild whole frames, indicators, timestamp arrays, or scan the
whole journal separately for every record.

Recompute every existing `event_prediction` and `event_excluded` field exactly from
the signal row, prefix-available first-seen funding evidence, frozen features, and
`MODEL.json`. Require the exact signal time, direction, exclusion reason or feature
vector, probability, `predicted_positive`, threshold, computation time, and, for a
prediction, execution time. The signal candle and every journal funding or candle
record used for an event must precede the event in journal order and have
`observed_at` no later than its stored `computed_at`. A mismatch or unavailable,
reordered, or late-observed source is journal damage and fails closed.

Recompute every existing `label_matured` field exactly. Require the exact entry,
label, exit reason, execution time, and derived exit time. The label must follow its
matching timely prediction and every required journal 5-minute source row in journal
order. `matured_at` must be at least `deadline + 5 minutes` and no earlier than every
required 5-minute source row's `observed_at`. An excluded event never receives a
label.

Labels scan exactly 577 consecutive 5-minute rows from execution through deadline.
In timestamp order they apply gap stop, gap target, intrabar stop, then intrabar target;
stop wins a same-candle tie, and the deadline open is evaluated before the deadline
range. The stored `exit_time` is the timestamp of the row that determines the result,
including the deadline row for `deadline_open`.

## Network-window prefix integrity

During the pre-network locked read, retain the complete canonical bytes and parsed
records of an existing journal together with its descriptor identity. During the second
locked read, the same pathname must still identify the same descriptor identity and its
content must begin with the exact retained byte prefix. Same-inode truncation, rewrite,
replacement, or reordering fails closed. Only complete canonical records appended after
the retained prefix are permitted during network access. This prefix check precedes
reconciliation and does not make any existing event identity trustworthy without full
replay validation.

Even when reconciliation produces no additions, the append boundary must validate that
the journal pathname still identifies the open descriptor. It must not return success
without that identity check.

## One-shot collection and platform durability

The default invocation prints a deterministic plan and creates neither the evidence
journal nor its lock. Only explicit `--poll-once` runs one collection cycle. The journal
parent directory must already exist; the recorder must not create it recursively.

Serialization uses the fixed gitignored sidecar
`ft_userdata/user_data/logs/donchian-logistic-shadow.jsonl.lock`, never the evidence
file itself. An explicit poll may create this empty persistent coordination file; it is
not evidence and may remain after success or failure. Acquire it for one consistent
pre-network journal read and complete replay validation, release it while fetching, then
acquire it again for reread, prefix and replay validation, reconcile, event/label
preparation, and append. A persistent lock file does not block a later retry.

Remember whether the journal existed during the pre-network locked read. If it existed
and its pathname disappears or changes descriptor identity before the second read, fail
closed and never recreate it. If it was absent and a concurrent writer creates it during
fetch, reread and reconcile that file normally under the second lock.

Under the second lock, finish all validation, event generation, label generation, and
reconciliation before creating a previously absent journal. A validation failure must
leave an initially absent journal absent. Open the evidence journal exactly once in the
locked cycle, and read and append through that same descriptor; do not reopen its
pathname. Require the pathname to identify that descriptor at the append boundary and
after a nonempty write. Existing zero-byte, torn, malformed, noncanonical, duplicate,
reordered, or otherwise damaged journals fail closed without any byte change.

Append canonical finite JSONL and verify that the complete payload length was written.
On POSIX, flush and `fsync` the journal data, then, after first creation, `fsync` the
already-existing parent directory. On Windows, first creation must use `CreateFileW`
with `CREATE_NEW`, `GENERIC_READ | GENERIC_WRITE`, sharing disabled, and
`FILE_FLAG_WRITE_THROUGH`; convert that `HANDLE` to a Python file descriptor, then use
the same complete write, flush, and `os.fsync` sequence. Windows write-through requests
that the system flush data and the NTFS metadata updates caused by that write; V6 makes
no Windows directory-`fsync` claim. A `CreateFileW`, handle conversion, write, flush,
`fsync`, identity, short-write, or crash-partial-write failure fails closed and must
never report success.

The immutable schema-version-3 header binds this V6 preregistration, model, seeds,
origin, boundary, exchange, symbol, and timeframes, and rejects a V5 header. Evidence
identities are idempotent only after prefix and full replay validation: an exact repeat
is a no-op and a different record for the same identity is a hard conflict. Scheduling
remains outside the recorder; an operator invokes explicit `--poll-once` periodically
after the prospective boundary.
