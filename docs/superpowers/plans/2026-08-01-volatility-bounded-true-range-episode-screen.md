# VolatilitySystem Bounded True-Range Episode Development Screen

**Status:** Preregistered after independent statistical/product and implementation Gates
both returned `P0=0, P1=0, P2=0`. No strategy workload has run. Deterministic source/test
preparation and the one-shot development screen remain blocked until this plan and its
README/STRATEGY routing are committed; development performance also requires the
credential-free research receipt. Runtime, Paper, and Live remain prohibited.

**Decision date:** 2026-08-01

**Governing policy:** [Product Strategy and Delivery Policy](../STRATEGY.md)

**Previous falsifier:**
[VolatilitySystem Breakout-Episode Risk Calibration Rejection](../reports/2026-08-01-volatility-breakout-episode-risk-calibration-rejection.md)

## Decision

Evaluate one integrated, development-only `VolatilitySystem` candidate whose volatility
threshold has finite memory and whose position lifecycle permits at most one half-stake
entry per finite eligibility episode.

The candidate is deliberately the smallest continuation of the rejected study:

- replace recursive Wilder ATR with the arithmetic mean of the preceding 14 complete
  three-hour True Ranges;
- calculate and lag that threshold on the three-hour frame before merging to one-hour
  rows;
- retain the previously preregistered finite false-to-true entry edge, persistent
  opposite exits, `-0.10` stop, half proposed stake, 2x leverage, and no position
  adjustment;
- keep every other strategy and simulation input unchanged.

This is one system hypothesis, not a component-ablation study. A survivor cannot establish
which component caused an outcome. No parameter, side, period, or alternate estimator may
be selected after results are visible.

## User value and claim boundary

The user-facing question is narrow: can the existing strategy idea produce the same
decision after a normal restart while avoiding repeated fills and uncapped episode risk,
and does that fixed policy remain worth studying on the already-viewed development year?

The screen may falsify deterministic mechanics and obviously poor development behavior.
One BTC Futures pair, one one-hour year, and roughly tens of dependent trades cannot prove
statistical significance, regime robustness, tail risk, cross-asset validity, future
profit, or stable return. The strongest possible outcome is
`DEVELOPMENT-SURVIVOR`. It is not acceptance or promotion.

This is an adaptively derived third development hypothesis on reused history. There is no
calibrated family-wise error rate, and the frozen vetoes below are descriptive product
policy rather than statistical power or tail-risk estimates.

## Frozen candidate semantics

### Complete three-hour bars

Input is closed `BTC/USDT:USDT` one-hour OHLCV with UTC timestamps on exact hour
boundaries. Before the standard Freqtrade loader may fill missing candles, create and
hash a pre-normalization inventory whose canonical rows contain timestamp plus float-hex
OHLCV. Require unique timestamps and exact plus-one-hour continuity. Compare the loaded
canonical rows to that inventory byte for byte before B capture; any inserted, removed,
or changed row makes the study `INVALID`.

Volume remains part of DataSnapshot identity but is ignored by the candidate formula and
bucket-validity decision. No candidate-owned volume filter is added.

Preserve every UTC-aligned three-hour slot, including invalid slots. For slot `k` with
start `s`:

- `bucket_ok_k` is true only when the source has exactly the three closed candles at
  `s`, `s + 1h`, and `s + 2h`;
- each required OHLC value is numeric and finite;
- each candle satisfies `L <= min(O, C) <= max(O, C) <= H`;
- `B_k` uses first open, maximum high, minimum low, and last close only when
  `bucket_ok_k` is true.

A partial leading slot and a forming or partial trailing slot remain present but invalid.
Missing or duplicate interior input never collapses the time axis. The temporary research
candidate must not synthesize, interpolate, drop, or forward-fill an invalid source slot.
Online recovery after an exchange data gap is a separate Runtime design problem.

The installed `technical==1.6.0` helper labels a resampled candle at the left boundary and
merges a 180-minute result at `s + 2h`. That timestamp convention is retained, but its
partial-bucket aggregation, dropped invalid rows, mutated frame, and unrestricted
forward-fill are not candidate state authorities.

### Finite volatility threshold

For preserved slots in chronological order:

```text
TR_k =
    max(H_k - L_k, abs(H_k - C_(k-1)), abs(L_k - C_(k-1)))
    only when bucket_ok_(k-1), bucket_ok_k, and s_k - s_(k-1) = 3h
    else NaN

rolling_mean_true_range_k =
    fsum(TR_(k-14), ..., TR_(k-1)) / 14
    only for exactly fourteen finite values from contiguous slots
    else NaN

volatility_threshold_k = 2.0 * rolling_mean_true_range_k
delta_k =
    C_k - C_(k-1)
    only when adjacent bucket slots are valid and exactly 3h apart
    else NaN

valid_k =
    bucket_ok_k
    and every dependency slot is contiguous
    and delta_k and volatility_threshold_k are finite
```

`fsum` means one fixed chronological finite-value reduction, not a recursive estimator,
prefix-dependent rolling accumulator, skipped-value mean, EWMA, or Wilder smoothing. The
14-bar horizon and 2.0 multiplier are inherited from the baseline rather than optimized.
The current bar's True Range is not part of its own threshold.

The first valid indicator decision at `B_k` requires complete contiguous buckets
`B_(k-15) ... B_k`: 16 complete three-hour bars containing 48 constituent one-hour
candles. This is an aligned dependency horizon, not a universal raw-frame length or a
convergence estimate.

| Raw frame starts at UTC bucket offset | Indicator raw rows | Rising-edge raw rows |
|---|---:|---:|
| `0h` | 48 | 51 |
| `+1h` | 50 | 53 |
| `+2h` | 49 | 52 |

The finite semantic dependency remains 48 constituent rows for the indicator and 51 for
the edge. Extra leading rows only discard a partial slot; a target on a non-completion row
may also require one or two trailing mapped rows.

`rolling_mean_true_range` and `volatility_threshold` are the truthful indicator names.
The candidate must not label either value as TA-Lib ATR.

### Eligibility, entries, and exits

On each preserved slot `k`:

```text
long_eligible_k = valid_k and delta_k > volatility_threshold_k
short_eligible_k = valid_k and -delta_k > volatility_threshold_k
```

Eligibility is false when `valid_k` is false. Equality is not eligible. NaN and positive
or negative infinity are invalid.

An entry is armed only when both current and preceding eligibility inputs are valid and
the same-side state changes from false to true:

```text
enter_long_k =
    valid_(k-1) and valid_k and not long_eligible_(k-1) and long_eligible_k
enter_short_k =
    valid_(k-1) and valid_k and not short_eligible_(k-1) and short_eligible_k
```

The entry appears only on the closed one-hour row that completes `B_k`. The state may be
carried across intervening one-hour rows for display and exit decisions, but the entry
pulse may not be forward-filled. A true state immediately after an invalid boundary is
boundary-unknown and cannot create a catch-up entry. Compute the edge on the three-hour
frame before mapping it to one-hour rows.

Opposite eligibility remains the persistent exit authority:

```text
exit_short = long_eligible
exit_long = short_eligible
```

For a slot starting at `s`, threshold, delta, valid, eligibility, and exits map only to
`s + 2h`, `s + 3h`, and `s + 4h`. Entry maps only to `s + 2h`. The next completion at
`s + 5h` replaces the state. An invalid completion maps false validity, eligibility, and
exits and cannot retain a prior true state.

The current and previous edge states together depend on exactly the final 17 complete
three-hour bars, `B_(k-16) ... B_k`. This is the actionable-decision horizon; the
indicator alone has the 48-constituent boundary above, while a rising edge has 51
constituents. `startup_candle_count = 499` remains unchanged and exceeds this declared
semantic minimum for compatibility, but restart correctness is established by exact
output parity, not by calling 499 a convergence approximation.

### Position lifecycle

- `stoploss = -0.10`;
- `custom_stake_amount()` returns `proposed_stake / 2`;
- `position_adjustment_enable = False`;
- no `adjust_trade_position()` behavior;
- at most one successful entry order per trade;
- no second initial trade in an already-entered still-contiguous eligibility episode;
- leverage remains 2.0;
- timeframe, ROI, order types, time-in-force, startup count, and every unlisted parameter
  remain unchanged.

A `-0.10` configured stop is not a guaranteed `-10%` fill during a candle gap. Signal,
Order, Fill, and Trade remain distinct evidence.

## Frozen roles and data domain

Only two roles will be executed after preregistration:

- **B:** the unchanged accepted `VolatilitySystem` baseline, including `stoploss = -1`,
  persistent entries, half initial stake, and enabled adjustment;
- **C:** the single candidate defined above.

The already-rejected static-stop role is not run again. Its previous report remains
historical mechanism evidence, while candidate-specific deterministic tests exercise
stop/re-entry behavior directly. B versus C is an integrated system comparison and makes
no causal component claim. If independent Gate review finds that a third run changes a
current decision rather than merely reproducing an old mechanism, this draft must be
revised before preregistration.

The one-shot development screen freezes:

- already-viewed scored interval
  `[2024-07-01T00:00:00Z, 2025-07-01T00:00:00Z)`, requested as
  timerange `20240701-20250701`;
- OKX isolated Futures, `BTC/USDT:USDT`, `1h`;
- one maximum open trade;
- 100 USDT configured stake and 1,000 USDT starting wallet;
- strategy leverage 2x;
- fee ratio `0.0005`;
- historical Futures, mark, and funding inputs with no current, zero, or synthetic
  fallback;
- cache `none`;
- no protections and no FreqAI.

Two input routes have different purposes and are both frozen. The performance route
includes the 499 closed one-hour source rows immediately before the first scored target,
beginning `2024-06-10T05:00:00Z`, plus admitted mark and funding inputs. The
indicator-only restart-audit route uses the same raw admission contract and full available
primary prehistory, and must contain at least the 799-row suffix through the first scored
target, beginning `2024-05-28T18:00:00Z`. Missing either route makes the study
`INVALID`; the larger audit route does not enlarge the scored interval.

B captures the admitted canonical rows once and C replays those exact rows. Required
DataSnapshot, Execution Context, scored endpoints, and admission routes must match;
Strategy Evidence must be valid and different. Existing accepted Backtest identity,
redaction, retained-row replay, comparison, and chart-source contracts remain authoritative
and are referenced rather than redesigned here.

Freqtrade's timerange trim may retain a row whose timestamp equals the requested stop.
That exact-end row is an unscored execution sentinel only: it cannot complete a new
three-hour bucket, create an indicator decision or edge, or open a trade. Backtest may
process a shifted exit from the final scored strategy row on the sentinel, while its
normal final-row entry suppression remains in force. The sentinel and every outcome it
closes remain included in identity and reconciliation evidence, but never extend the
scored interval.

Do not inspect historical Backtest ZIP archives to source data: prior security audit found
many historical archives with session secrets. Use separately admitted raw market-data
files or a newly redacted B artifact without exposing credentials.

## Prospectively sealed validation protocol

The exclusive half-open interval
`[2026-10-01T00:00:00Z, 2027-10-01T00:00:00Z)`, requested as
`20261001-20271001`, is C's only prospective validation window. At this decision date it
and both declared prefixes below are future data and have not been used for indicators,
signals, trades, or metrics:

- the 499 closed-row Backtest performance prefix begins
  `2026-09-10T05:00:00Z`;
- the separate 799-row-through-first-target restart-audit route begins
  `2026-08-28T18:00:00Z` and uses the same raw admission contract.

The exact-end row, if retained, has the same unscored exit-only sentinel role as in
development and cannot complete a new bucket or open a trade.

Before the earlier restart-audit timestamp and before development performance, commit one
credential-free, content-addressed research receipt containing:

- the exact immutable B and C source bytes and hashes;
- the exact deterministic test bytes and hashes;
- the effective configuration and request;
- the engine, package, image, and strategy identities;
- this window, its 499-row performance-prefix rule, its 799-row restart-audit rule, and
  the data/admission routes below.

The receipt is non-executable documentation evidence, not an installed strategy or
BotRelease. If it is not committed before `2026-08-28T18:00:00Z`, the window loses its
fresh-validation claim and cannot be used.

If and only if C becomes `DEVELOPMENT-SURVIVOR`, then after `2027-10-01T00:00:00Z` run
one atomic B-then-C spend using the receipt's exact sources and tests. B captures the
admitted Futures, mark, and funding rows once; C replays those exact rows. Apply every
development validity, restart-parity, sufficiency, mechanism, performance, risk,
force-exit, Lookahead, and Recursive rule in this document without alteration. Required
DataSnapshot, Execution Context, endpoints, and admission routes match; valid Strategy
Evidence differs.

Before interpreting any prospective metric, execute the frozen every-target,
every-deduplicated-suffix real-strategy restart matrix on the prospective scored rows
using its separately admitted 799-row audit route. Any parity miss consumes the window
and classifies C as `REJECTED`.

A complete pass is classified only as `PROSPECTIVE-SURVIVOR`. It requires a separate
post-spend acceptance Gate before any tracked strategy change and still cannot authorize
Paper while the known GTC signal/order non-equivalence remains unresolved.

The first visible indicator, signal, order, trade, or metric from either role consumes the
window, including an `INVALID`, `INSUFFICIENT`, or `REJECTED` outcome. Only an
infrastructure failure that exposes no candidate output may be retried, and only with
byte-identical semantic and input identities. Any semantic change, path-conditioned
decision, extension, retry after output, or replacement window retires the fresh-validation
claim rather than rescuing C.

This document is the sealed validation protocol; a later operational runbook may reference
it but may not change its rules. It authorizes no collection, execution, Paper, or Live
action now. The retired `20250702-20260702` window remains prohibited.

## Pre-performance development Gate

No market-data or performance command may run until the preregistration commit exists.
After that commit, perform these stages in order:

1. Write focused synthetic tests and observe the candidate-specific tests fail against
   the unchanged baseline where behavior intentionally differs.
2. Implement one temporary C source outside tracked repository paths with exactly this
   contract.
3. Make the tests pass without changing semantics.
4. Run an exhaustive real-strategy restart matrix, not a sample:
   - for every scored target hour `t`, instantiate a fresh real C strategy on all
     admitted closed source rows through `t` and record its target-row output as the
     reference;
   - after removing any exchange forming candle, instantiate another fresh real C
     strategy for each distinct admitted suffix length `N` ending at the same `t`,
     where `N` is the deduplicated set of 499, the recorded cold return length, the
     recorded immediate-warm return length, 599, 600, and 799;
   - record actual cold and immediate-warm lengths even when both are 599, and execute
     identical suffix bytes only once;
   - at target `t` compare aggregate three-hour OHLC, True Range, rolling mean,
     threshold, delta, NaN masks, validity, long/short eligibility, entry pulses,
     exits, and source-bucket identity; compare booleans and identities exactly and
     floating values by float-hex plus exact NaN masks;
   - include every one-hour offset, the first-finite indicator and edge boundaries,
     and the prior `2025-02-21 18:00-20:00 UTC` restart-drift witness within this
     all-target matrix.
5. Freeze temporary C source, test, configuration, request, package, image, input, and
   both accepted B-copy hashes:
   `ft_userdata/user_data/strategies/VolatilitySystem.py` and
   `freqtrade-strategies/user_data/strategies/futures/VolatilitySystem.py`. Commit the
   non-executable research receipt required by the prospective protocol before any
   performance output and before the prospective restart-audit deadline.

Any parity miss rejects C immediately. Do not lengthen warmup, round a threshold, add a
tolerance, or delay the pulse after seeing a witness. Compare exact booleans and validity
masks and use exact or float-hex value comparison rather than a numerical tolerance.

`startup_candle_count = 499` is a compatibility loader and Backtest-trim hint, not a
claim that the live strategy receives a 499-row window. With OKX's 300-candle request
limit the observed cold and immediate-warm frames may both contain 599 closed rows after
pagination, while a mature cache may return a 799-row tail. The matrix records reality
and deduplicates equal byte ranges; it does not manufacture different runs to satisfy a
label.

Canonical episode IDs are intentionally not part of the restart parity surface: an
episode may begin before the finite 17-bucket decision suffix. Derive episode boundaries
once from the admitted full-prehistory ledger for audit only. Do not add runtime episode
state or persistence merely to reproduce an audit identifier.

### Minimum focused test matrix

- pre-normalization gap/duplicate rejection and byte-exact comparison after the standard
  loader, including any loader-inserted flat candle;
- real-strategy complete UTC three-hour aggregation, source identity, and mapping at all
  three possible starting-hour offsets;
- real-strategy partial-leading, partial-trailing, invalid-slot preservation, impossible
  OHLC geometry, NaN/infinity rejection, no unlimited fill, and no state across an
  invalid bucket;
- True Range gap term and fixed 14-value chronological mean;
- threshold lag on the three-hour frame before one-hour merge;
- real-strategy exact first-finite indicator and rising-edge boundaries for every offset,
  including the aligned 48/51-constituent horizons;
- strict equality, long/short symmetry, false-to-true edge, false re-arm, and invalid
  boundary no-catch-up;
- one entry pulse only on the completing one-hour row;
- persistent opposite exits across intervening rows and fail-closed invalid state;
- half proposed stake, 2x leverage, `-0.10` stop, no adjustment, and one-fill invariant;
- real-strategy every-target restart parity for every deduplicated suffix length;
- fresh strategy instances, installed startup count, recorded cold/warm return lengths,
  and the prior restart-drift witness;
- Freqtrade next-candle Backtest signal shift;
- exact-end execution-sentinel exit handling, entry suppression, and prohibition on a
  new three-hour bucket.

Pure helper tests may explain a formula but do not satisfy a real-strategy item or the
restart Gate.

The previous rejection already established that a one-row edge is not equivalent to the
configured limit-entry/limit-exit, GTC, 10-minute dry/live order lifecycle with a
60-second expired-candle overlay and persisted trade/order state. The normal loop manages
existing orders before exits and entries. Consequently a one-row entry can expire with
no retrigger, an unfilled old-side exit can consume the opposite edge, and a timed-out
empty entry receives no new edge. Do not rerun those scenarios in this screen. The known
non-equivalence remains a Paper blocker.

## One-shot development screen

Run B, then C, once. A failed infrastructure attempt may be rerun only if it exposed no
strategy output and all semantic and input hashes remain byte-identical.

Validity is evaluated before sample size or P&L. Required fields, rows, identities,
orders, trades, fees, funding, counts, and arithmetic must reconcile. Any mismatch is
`INVALID` rather than poor performance. Every outcome field must be numeric, finite, and
net of the frozen fees and historical funding model, except the audited trade-derived
profit factor may be positive infinity under the exact zero-loss rule below.

### Minimum sufficiency

| Gate | Requirement |
|---|---|
| Closed trades | B and C each at least 20 |
| Direction coverage | B and C each at least 5 long and 5 short trades |
| Episode coverage | At least 20 C armed episodes, at least 5 per direction; boundary-unknown runs excluded |
| Stop exercise | C has at least 5 genuine `stop_loss` exits and at least 1 per direction |
| Open-same exercise | At least one noncensored C `open_same_side` edge |
| Post-stop exercise | At least one C stop followed by a still-valid same-side row in the same episode |

These are operational floors, not a power calculation. A miss is `INSUFFICIENT`; do not
widen the period or open another pair.

### Opportunity and order ledger

For one side, a C armed episode is a maximal consecutive run of complete three-hour
states where that side is valid and true and whose immediately preceding state is valid
and false. A true run with an absent or invalid predecessor is `boundary-unknown`: report
it separately and exclude it from the C episode floor. The admitted prefix participates
in this classification; the scored-window start never resets an episode. Its canonical
audit ID is `<side>:<first-completion-UTC>`, derived only from the admitted
full-prehistory ledger.

Prefix rows establish predecessor state and episode continuity only. Only an armed
transition whose first-completion timestamp is inside the half-open scored interval is a
scored C episode and may enter either the episode floor or opportunity denominator. A run
armed before the interval and still true inside it is `prefix-active`; report it
separately and exclude it from both denominators.

Freqtrade shifts a strategy signal forward one candle before Backtest execution. Associate
each scored C edge with that shifted execution row. If the row is absent or is the
engine's deliberately non-entry final row, classify it `end_boundary_censored`, report it
separately, and exclude it from the opportunity denominator. Classify every other scored
edge exactly once:

- `free`: no trade is open for the pair;
- `open_same_side`: C already has a trade on the signaled side;
- `open_opposite_side`: C has a trade on the opposite side.

With one pair, one slot, and no protections, no fourth noncensored class is permitted. At
the shifted execution row:

- `free` requires exactly one successful initial entry order;
- `open_same_side` requires no initial or adjustment entry fill;
- `open_opposite_side` requires the old-side Backtest close and exactly one opposite
  initial entry in the expected same-timestamp reversal.

A successful entry order is an exported `trades[*].orders` element with
`ft_is_entry = true` and a non-null `order_filled_timestamp`. Standard Backtest ZIPs do
not expose a complete per-order unsuccessful history, so reconcile unsuccessful behavior
only through the exported aggregate timeout, cancellation, replacement, and rejection
counters.

For every successful entry, recompute stake as
`amount * safe_price / leverage` and exclude fee-inclusive cost fields. The allowed
absolute stake difference is the larger of `1e-8 USDT` and one admitted amount quantum
times fill price divided by leverage. Each trade's order-derived successful-entry count
must equal `nr_of_successful_entries`. Trade totals, side totals, profit, fees, and
historical funding must also reconcile to the exported aggregates.

The exported minified orders and trades are the accounting inputs. For each filled order
`o`, let `q_o = amount`, `p_o = safe_price`, `d = +1` for a long trade and
`d = -1` for a short trade, and `a_o = -1` for an entry or `+1` for an exit.
Use `fee_open` for entry orders and `fee_close` for exit orders:

```text
signed_notional_cashflow_o = d * a_o * q_o * p_o
order_fee_o = abs(q_o * p_o) * applicable_fee_rate

raw_trade_cashflow_abs =
    fsum(signed_notional_cashflow_o for filled orders)
  - fsum(order_fee_o for filled orders)
  + trades[*].funding_fees

trade_derived_profit_abs = float(f'{raw_trade_cashflow_abs:.8f}')
role_derived_profit_abs = fsum(trade_derived_profit_abs for all trades)
role_derived_profit_total = role_derived_profit_abs / 1000 USDT
side_derived_profit_abs = fsum(trade_derived_profit_abs for that side)
```

`trades[*].funding_fees` is already signed: positive is a credit and negative is a
charge. Recompute it through the pinned Freqtrade historical-funding path using the
admitted mark and funding rows for the trade interval; current, zero, or synthetic
fallback remains forbidden. Per-trade funding, `profit_abs`, role totals, side totals,
trade counts, and successful-entry counts must match their derived values within an
absolute `1e-8 USDT` or exact-integer tolerance as applicable. Report both
`raw_trade_cashflow_abs` and `trade_derived_profit_abs`. The latter must use the pinned
engine's exact per-trade `float(f'{raw_trade_cashflow_abs:.8f}')` rounding before every
role, side, gross-profit, or gross-loss reduction; the raw value is decomposition evidence
only. `profit_abs` already contains both order fees and funding, so aggregate it once and
never add or subtract either component again.

The sole profit-factor Gate authority is derived from those reconciled trade profits:

```text
gross_profit = fsum(max(trade_derived_profit_abs, 0))
gross_loss_abs = -fsum(min(trade_derived_profit_abs, 0))

audited_profit_factor =
    gross_profit / gross_loss_abs  when gross_loss_abs > 0
    +Infinity                      when gross_loss_abs = 0 and gross_profit > 0
    0.0                            when gross_loss_abs = 0 and gross_profit = 0
```

When `gross_loss_abs > 0`, the engine-exported `profit_factor` must equal the audited
value within `1e-8`. When `gross_loss_abs = 0`, the pinned engine's exported `0.0` is a
required, reconciled sentinel only; it is not the Gate value.

```text
lifecycle_violations =
    successful entry orders after the first for a C trade
  + C initial trades repeating an already-entered still-contiguous episode

opportunity_failures =
    noncensored free edges without exactly one successful initial entry
  + open-same edges with any entry fill
  + open-opposite edges without the expected close and reversal
  + noncensored edges outside the three exhaustive classes

mechanism_failures = lifecycle_violations + opportunity_failures
```

Every denominator and class must recompute from admitted rows and exported trades.
`mechanism_failures` must be zero. The C aggregate counters
`timedout_entry_orders`, `canceled_trade_entries`, `canceled_entry_orders`,
`replaced_entry_orders`, `timedout_exit_orders`, and `rejected_signals` must each be
zero. A missing field or failed count identity is `INVALID`; a present nonzero value is
`REJECTED`.

### Mechanism and risk vetoes

C requires all of the following:

- `mechanism_failures == 0` and zero adjustment orders;
- initial stake is half the proposed 100 USDT stake within exchange precision and never
  above 50 USDT plus that precision;
- leverage is 2x and no liquidation occurs;
- no trade has `profit_ratio < -0.105`.

### Development outcome vetoes

C must satisfy all of these descriptive development thresholds:

| Gate | Requirement |
|---|---|
| Total profit | `profit_total > 0` |
| Improvement | `C.profit_total - B.profit_total >= 0.01` |
| Profit factor | audited `>= 1.10`, or positive infinity only with exactly zero gross loss and positive gross profit |
| Expectancy | finite and `> 0` |
| Direction balance | net long profit `> 0` and net short profit `> 0` |
| Account drawdown | finite, `< 0.10`, and no worse than B |

Include every trade and `force_exit`. Recompute total-profit sign, improvement, and
per-direction profit with force-exit cashflow set to zero. Boundary dependence can only
downgrade a result to `INSUFFICIENT / BOUNDARY-SENSITIVE`; it cannot rescue a failure.

Only a metric survivor runs the existing Lookahead and Recursive analyses:

- Lookahead runs with limit orders disabled and minimum/target trade counts both 20. It
  must complete, analyze at least 20 signals, report `has_bias = false`, zero biased
  entries and exits, and no biased indicators.
- Recursive runs 299, 499, and 999 startup profiles and must complete with finite output.
  After successful completion, a missing 499 key or empty sparse result means exact zero
  for that entry; an explicit NaN or infinity is `INVALID`, and an explicit finite
  absolute 499-profile relative variance `>= 0.0001` is `REJECTED`.

Recursive is final-candle indicator evidence only. It never replaces the earlier exact
full-window real-strategy parity Gate. Freeze the exact analysis source, configuration,
and data hashes. These analysis outputs are not revision/DataSnapshot/context-bound
receipts in the current product.

## Classification and stop rules

Classify in this order:

1. `INVALID` for identity, data, implementation, completeness, evidence, or arithmetic
   failure;
2. `INSUFFICIENT` for an unmet observation floor or boundary-sensitive apparent pass;
3. `REJECTED` for parity, mechanism, safety, performance, or risk failure;
4. `DEVELOPMENT-SURVIVOR` only if every preceding Gate passes.

Stop at the first class. No miss may be rescued with another estimator, horizon,
multiplier, stop, tolerance, warmup, stake, side, subperiod, asset, Hyperopt run, or
best-of report.

## Repository change policy

Before a result is visible, tracked changes are limited to this preregistration, its
README/STRATEGY routing, and the credential-free non-executable research receipt that
preserves exact B/C source and deterministic test bytes and hashes. The receipt is not
installed, imported, packaged, or exposed as a Runtime strategy. Working copies, admitted
data, logs, and result artifacts remain outside tracked paths.

For every result class:

- write one factual report;
- remove temporary working files and services while retaining the immutable research
  receipt as evidence;
- leave all repositories clean.

Even a `DEVELOPMENT-SURVIVOR` does not authorize editing either tracked
`VolatilitySystem` copy. A tracked strategy change requires both a
`PROSPECTIVE-SURVIVOR` result under the sealed protocol and a separate post-spend
acceptance. Commit the strategy submodule first only after that acceptance.

## Explicit non-goals

- no backend, frontend, API, database, chart component, Experiment CRUD, optimizer,
  ranker, scheduler, daemon, or AI generation loop;
- no third current strategy role, component attribution, parameter sweep, alternative
  range estimator, cooldown, regime filter, take-profit, trailing stop, or new asset;
- no RuntimeInstance, BotRelease, formal Paper Observation, compatibility-runtime
  promotion, exchange write, or real-money order;
- no use of 8081 as formal Paper evidence;
- no profit guarantee or claim that this retrospective screen predicts future return.
