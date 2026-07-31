# VolatilitySystem Breakout-Episode Risk Calibration

**Status:** completed; candidate rejected at the pre-performance 499-candle signal-parity
Gate; B/S/C performance, safety analysis, and holdout were not opened

**Decision date:** 2026-07-31

**Preceding evidence:**
[VolatilitySystem Static-Stop Calibration Rejection](../reports/2026-07-31-volatility-static-stop-calibration-rejection.md)

**Outcome evidence:**
[VolatilitySystem Breakout-Episode Risk Calibration Rejection](../reports/2026-08-01-volatility-breakout-episode-risk-calibration-rejection.md)

## Decision question

Test exactly one mechanism-derived policy:

> Can `VolatilitySystem` keep its existing breakout threshold and persistent exit
> behavior, but treat each false-to-true entry-eligibility transition as one entry
> opportunity, retain the existing half-stake initial allocation, disable additional
> fills, and use
> the already-frozen `-0.10` trade stop without repeating the static-stop candidate's
> re-entry and averaged-fill failure paths?

This is development research on already-viewed history. It is not a fresh validation,
an optimizer trial, a Paper authorization, or a profit claim.

## First-principles mechanism

The current strategy combines four behaviors:

1. a completed three-hour `close_change` and ATR are causally merged into the one-hour
   strategy dataframe;
2. `close_change > atr.shift(1)` or its short-side mirror remains entry-eligible for
   every one-hour row on which the level predicate is true;
3. a stop can close the sole position while that eligibility is still true, so a later
   row may open the same direction again;
4. `adjust_trade_position()` can add a second fill on a later same-side eligibility
   transition, after which Freqtrade recalculates the average open rate and static-stop
   anchor.

The rejected `-0.10` stop changed occupancy and produced ten additional entry
timestamps. It also exercised the averaged-fill stop path. A stop value alone therefore
does not define either re-arming or after-fill risk.

The smallest coherent correction is a finite-frame breakout policy:

- entry is armed only on an observable transition where the unchanged eligibility
  predicate changes from false to true and both the current and preceding inputs are
  finite;
- eligibility must become false before the same side can arm again;
- every trade retains the existing half-stake initial allocation and receives no
  additional entry fill;
- the fixed `-0.10` stop is anchored to that single fill;
- opposite-side exit eligibility remains level-based and persistent, preserving retry
  behavior rather than turning exits into one-shot pulses.

Freqtrade owns the deterministic immediate-fill Futures reversal used by Backtesting: it
has an explicit second pass after an opposite-direction close. That does not establish
equivalent dry/live behavior for the committed ten-minute GTC limit entry and exit
policy. Dry/live processes exits before entries, but an unfilled old-side exit can keep
the pair occupied until the one-row opposite edge has disappeared; a canceled or timed-
out empty entry can also be reconsidered while the same latest candle remains visible.
The offline candidate needs no delayed pulse, queue, database lookup, or mutable strategy
state, but it is not Paper-promotable without a later explicit execution-policy decision.

## Alternatives deliberately rejected

| Alternative | Reason for rejection |
|---|---|
| Directly uncomment `crossed_above(close_change, atr)` | Changes both persistence and the threshold; the current strategy uses `atr.shift(1)` |
| Directional regime latched until an opposite breakout | Has potentially unbounded memory, can diverge after restart or a finite 499-candle load, and blocks later independent same-side episodes |
| Two-row entry pulse | Can re-enter after a same-candle stop on the second pulse |
| One-hour delayed entry | Adds timing drift and still cannot guarantee a live limit exit will fill within that retry |
| Cooldown/protection | Adds a tunable duration and may block legitimate opposite reversals |
| `confirm_trade_entry()` plus trade history or mutable state | Adds persistence, restart, database, and backtest/live parity risks that the dataframe edge does not need |
| Another stop value, Hyperopt, or parameter sweep | Reuses viewed history for result hunting rather than testing the observed mechanism |

## Frozen candidate semantics

Use three roles but only one new candidate.

| Role | Purpose | Frozen behavior |
|---|---|---|
| B — system baseline | Accepted reference | `stoploss = -1`, persistent entry eligibility, half initial stake, existing possible adjustment |
| S — mechanism control | Reproduce the rejected paths | B plus the already-rejected `stoploss = -0.10`; never promotion-eligible |
| C — sole candidate | Test the bounded lifecycle policy | finite-frame eligibility edge, persistent exit eligibility, unchanged half initial stake, no adjustment, `stoploss = -0.10` |

The raw predicates remain exactly:

```python
long_eligible = dataframe["close_change"] > dataframe["atr"].shift(1)
short_eligible = -dataframe["close_change"] > dataframe["atr"].shift(1)
```

Candidate entries are exactly the rising edges whose current and preceding predicate
inputs are both finite:

```python
threshold = dataframe["atr"].shift(1)
long_valid = np.isfinite(dataframe["close_change"]) & np.isfinite(threshold)
short_valid = long_valid

enter_long = (
    long_valid
    & long_valid.shift(1, fill_value=False)
    & long_eligible
    & ~long_eligible.shift(1, fill_value=False)
)
enter_short = (
    short_valid
    & short_valid.shift(1, fill_value=False)
    & short_eligible
    & ~short_eligible.shift(1, fill_value=False)
)
```

`np.isfinite()` must yield false for NaN, positive infinity, and negative infinity. Tests
also cover threshold equality, where neither side is eligible. This is an observable
finite-frame crossing, not an unbounded durable episode identity.
A true run beginning immediately after invalid/NaN inputs is a boundary-unknown run: it
is recorded but intentionally not armed. A cold restart that begins after a crossing does
not create a catch-up entry. The study must prove that every scored development signal is
identical when calculated from the offline 499-candle minimum, the actual returned OKX
two-call cold frame (capped at 600 primary rows), the actual returned warmed-cache frame
(capped at `300 + 499 = 799` rows), the first-finite-row restart boundary, and the longer
admitted development history. Record the actual frame lengths; neither cap is claimed as
a guaranteed return size. That evidence is required only on the development window now;
the same check may touch holdout rows only after the one holdout spend is authorized.

Candidate exits deliberately remain the existing persistent opposite eligibility:

```python
exit_short = long_eligible
exit_long = short_eligible
```

The remaining candidate changes are fixed as one lifecycle policy:

- `stoploss = -0.10`;
- `custom_stake_amount()` remains unchanged and returns `proposed_stake / 2`;
- `position_adjustment_enable = False`;
- remove the now-disabled `adjust_trade_position()` implementation and only the imports
  made unused by that removal;
- keep `startup_candle_count = 499`, timeframe `1h`, leverage `2.0`, ROI, indicators,
  resampling, pair, fee, funding, mark-price route, order settings, and all other inputs
  unchanged.

This is one bounded system candidate: one half-stake allocation per observable crossing.
It intentionally reduces the maximum position from the baseline's possible two-fill
100 USDT exposure to one approximately 50 USDT fill. That conservative exposure change
is part of the complete policy, so a pass cannot attribute performance to the edge,
no-adjustment rule, smaller maximum exposure, or stop separately.

## Causal opportunity ledger and mechanism endpoint

For each side, a finite **eligibility episode** is a maximal consecutive run of admitted
one-hour rows on which that side's unchanged raw predicate is true and its inputs are
finite. A true run whose immediately preceding inputs are invalid is boundary-unknown,
has no armed crossing, and is counted separately. The admitted prefix participates in
episode boundaries; the scored-window boundary must never reset an episode.

Freqtrade shifts strategy signals forward one candle before execution. Therefore every
Backtest order or fill is associated with the strategy signal row immediately preceding
its execution row, never merely with the same displayed timestamp.

For every valid in-window armed crossing, first classify a signal whose shifted execution
row is absent or is the engine's deliberately non-entry final row as
`end_boundary_censored`; no order is expected and this predeclared class is excluded from
the canonical opportunity denominator but reported separately. Classify every remaining
crossing at its shifted execution row as exactly `free`, `open_same_side`, or
`open_opposite_side`. Record:

- raw long and short eligibility, validity, episode ID, armed crossing, and shifted
  entry/exit signals on every admitted row;
- for `free`, exactly one successful initial entry order and fill;
- for `open_same_side`, the occupancy block and absence of an initial or adjustment fill;
- for `open_opposite_side`, the old-side close and candidate reversal outcome, including
  whether the opposite initial fill occurs at the same Backtest timestamp;
- every exported successful entry and exit order plus the standard aggregate rejected,
  canceled, replaced, and timed-out counters;
- trade, side, stake, leverage, stop/exit reason, fee, and funding association;
- whether an initial trade repeats an episode already entered after a stop;
- whether a trade receives more than one successful entry order.

The frozen mechanism endpoint is:

```text
lifecycle_violations =
    candidate successful entry orders beyond the first one for each trade
  + candidate initial trades that repeat an already-entered eligibility episode

opportunity_failures =
    noncensored free-pair armed crossings without one successful initial entry order
  + open-opposite armed crossings without the expected same-timestamp Backtest reversal
  + open-same-side armed crossings that create any entry fill
  + noncensored armed crossings with any disposition outside the three frozen classes

mechanism_failures = lifecycle_violations + opportunity_failures
```

With one pair, no protections, and one global slot, there is no authorized fourth block:
pair occupancy is already represented by the two open classes, and a free pair necessarily
has the global slot. Any other noncensored no-order outcome is a mechanism failure; it
cannot be explained after results are visible. Candidate success requires every frozen
denominator to reconcile and
`mechanism_failures == 0`. A zero lifecycle count cannot compensate for silently missed
opportunities or lost reversals.

The mechanism control must empirically exercise both targeted paths:

- at least one S trade has more than one successful entry fill; and
- at least one S stop exit is followed by an S initial entry in the same still-contiguous
  eligibility episode.

If either control path is absent, the study is `INSUFFICIENT`; a structurally clean
candidate cannot be credited for removing a mechanism the run did not exercise.

## Frozen implementation and data identity

The preregistration commit is the implementation authority before any performance output.
Freeze and report exact hashes for:

- Root, backend, frontend, and strategy revisions;
- both unchanged baseline strategy copies;
- temporary S overlay and temporary C source;
- image, Python/Freqtrade/CCXT/TA-Lib/technical versions;
- effective configuration and request;
- primary Futures, mark, funding, and leverage-tier inputs;
- every retained/replayed Backtest artifact.

Use the already-viewed development timerange `20240701-20250701`, OKX isolated Futures,
`BTC/USDT:USDT`, `1h`, one maximum open trade, 100 USDT configured stake, 1,000 USDT
starting wallet, 2x strategy leverage, fee ratio `0.0005`, historical funding, and cache
`none`.

Run in the fixed order B, S, C. B captures and retains the exact standard data. S and C
must replay B's retained rows. All three artifacts must bind:

- the same complete DataSnapshot, including the 499-candle Futures prefix, mark, funding,
  routes, and exact rows;
- the same captured Execution Context Evidence;
- the same exact engine-reported scored endpoints;
- valid and different Strategy Evidence where the strategy behavior differs.

FreqUI must classify the decision pair B-vs-C as `SAME-WINDOW STRATEGY CHANGE`. S is a
bounded positive mechanism control, so its replay identity and different Strategy
Evidence are verified directly from the artifacts; an S-vs-C UI load is optional product
dogfood, not a scientific Gate. Any unknown or different required identity makes the
affected comparison `INVALID`, regardless of P&L.

### Frozen order and reconciliation definitions

Missing/malformed order fields and failures of count or arithmetic identities are
`INVALID`. Fully present, internally coherent values that violate the stake, one-fill,
or must-zero counter policy are valid observations and are classified only as
`REJECTED` by the later Exposure/lifecycle Gates.

- A **successful entry order** is one element of exported `trades[*].orders` with
  `ft_is_entry = true` and a non-null `order_filled_timestamp`. Standard Backtest ZIPs
  intentionally expose minified successful/open orders, not unfilled order IDs or full
  terminal status history. Each exported array element counts once, and its count must
  equal the trade's `nr_of_successful_entries`.
- The **initial successful entry order** is the earliest successful entry order for one
  trade.
  Any later successful entry order for that trade is an additional fill and violates C.
- Candidate stake is `orders[*].amount * orders[*].safe_price / leverage`, excluding the
  fee-inclusive exported `cost`, and is reconciled to the trade `stake_amount`. It must
  equal half the engine's 100 USDT proposed stake within
  `max(1e-8 USDT, one admitted amount-precision quantum * fill_price / leverage)` and
  must never exceed `50 USDT + tolerance`.
- `timedout_entry_orders`, `canceled_trade_entries`, and `canceled_entry_orders` must all
  be zero for C. In Backtesting, `rejected_signals` counts only a signal which reaches and
  fails `trade_slot_available`; same-pair occupancy is bypassed earlier and is not part of
  that counter. This one-pair study therefore requires `rejected_signals = 0`. Report
  `timedout_exit_orders` and `replaced_entry_orders` separately and require each to be
  zero.
- For each role independently, exported trade count equals `total_trades`; long/short
  counts equal the aggregates; every successful order belongs to exactly one trade; the
  order-derived entry count equals each trade's successful-entry count; episode and
  opportunity denominators recompute from that role's admitted rows;
  `sum(trades[*].profit_abs) == profit_total_abs`; and
  `profit_total == profit_total_abs / 1000` within `1e-8` before displayed rounding.
  Trade `profit_abs` is already net of opening/closing fees and signed Futures funding;
  audit those components against each trade and its orders separately, but never add
  them to net profit a second time. B, S, and C are not required to have equal trades or
  orders.
- Across roles, only raw eligibility, validity, episode denominators, DataSnapshot,
  captured context, and scored endpoints are required to be equal. Strategy signals,
  trades, orders, fills, and outcomes are expected to differ and are compared rather than
  asserted equal.

The previous report already coverage-scanned and hashed source files containing dates
through 2026-07-08. Therefore this document does not claim the holdout bytes were never
read. "Sealed" means the `20250702-20260702` rows have not been selected for strategy
indicators, signals, trades, performance, or result inspection. Do not run another
holdout coverage or signal scan before an authorized spend.

## Pre-performance development Gate

Before any B/S/C performance command:

1. write focused synthetic tests first and observe them fail against the unchanged
   strategy where the candidate contract differs;
2. implement one temporary C source outside tracked repository paths with exactly the
   frozen semantics above;
3. make the tests pass without changing the semantic contract;
4. verify long/short symmetry, the exact shifted-ATR threshold, one pulse per contiguous
   finite episode, false-then-true re-arm, boundary-unknown fail-closed behavior,
   persistent exit eligibility, unchanged half proposed stake, disabled adjustment, and
   the fixed stop;
5. prove the engine's immediate-fill opposite-direction Backtest reversal with the
   existing focused Futures reversal test or an equivalent bounded test;
6. add candidate-specific execution tests for an old-side limit exit still open on the
   next candle and for empty entry timeout/cancel/reissue behavior. These tests must
   demonstrate and ledger the dry/live non-equivalence; they do not convert the offline
   candidate into a Paper-safe policy;
7. compare every raw eligibility, validity flag, entry, and exit signal in the scored
   development rows across the 499-candle offline minimum, the actual recorded cold and
   warmed-cache return lengths, synthetic cap checks at 600 and 799 rows, the
   first-finite-row restart boundary, and longer available prehistory. Exact signal
   parity is required; the prior near-zero last-row ATR variance is not enough for a
   discrete edge;
8. freeze the passing temporary candidate source and test hashes before any metric becomes
   visible.

An implementation mistake may be corrected only before performance output and without
changing the frozen semantics. If any 499/cold/warm/longer signal comparison fails, reject
the candidate and do not increase warmup after seeing the result.

## Minimum sufficiency

First apply every frozen identity, implementation, finite-value, required-order-field,
order-count, opportunity-denominator, and arithmetic reconciliation validity rule; a miss
is `INVALID`, not a sample failure.
Only a valid study evaluates these sufficiency conditions before performance:

| Gate | Requirement |
|---|---|
| Closed trades | B and C each `>= 20` |
| Direction coverage | B and C each have at least 5 long and 5 short trades |
| Episode coverage | At least 20 finite eligibility episodes, including at least 5 per direction |
| Stop exercise | C has at least 5 genuine `stop_loss` exits, including at least 1 per direction |
| Mechanism control | S exercises at least one additional fill and one same-episode stop re-entry |

These are operational floors, not power calculations. Missing any floor is
`INSUFFICIENT`; do not widen the window or open holdout.

## Performance and risk Gates

Use every exported trade, including `force_exit`. All values must be present, numeric,
finite, and net of the frozen fees and historical funding model. Every Gate is a veto;
there is no score or ranking.

| Gate | Requirement for C |
|---|---|
| Primary mechanism | `mechanism_failures == 0` after the opportunity denominator has passed validity |
| Total profit | `profit_total > 0` |
| Improvement | `C.profit_total - B.profit_total >= 0.01` |
| Profit factor | finite `profit_factor >= 1.10`, or positive infinity only when gross loss is exactly zero |
| Expectancy | finite `expectancy > 0` |
| Direction balance | net long profit `> 0` and net short profit `> 0` across all trades on each side |
| Account drawdown | finite `max_drawdown_account < 0.10` and `<= B.max_drawdown_account` |
| Trade loss | every `trades[*].profit_ratio >= -0.105` |
| Exposure | no liquidation, noncensored disposition outside the frozen three classes, stake clamp, stake above `50 USDT + tolerance`, leverage other than 2x, additional entry fill, timed-out/canceled/replaced entry, or timed-out exit |

Reduced exposure, fees, and funding from removing adjustment fills are part of the bounded
lifecycle policy and must not be normalized away. Apply the frozen non-double-counting
profit equations and audit per-trade fees and signed `funding_fees` separately. Any
unexplained cost difference is `INVALID`.

Report `force_exit` count, direction, and P&L separately. Recompute only total-profit
sign, one-percentage-point improvement, and per-direction profit with force-exit cashflow
set to zero in both B and C. This diagnostic may downgrade an apparent pass to
`INSUFFICIENT / BOUNDARY-SENSITIVE`; it may never rescue a canonical failure.

## Safety analysis for a metric survivor

Only if every sufficiency, mechanism, performance, and risk Gate passes:

1. run Lookahead Analysis on development with limit orders disabled and minimum/target
   20; require successful completion, at least 20 analyzed signals, `has_bias = false`,
   zero biased entries/exits, and no biased indicators;
2. run Recursive Analysis at 299, 499, and 999 startup candles; require successful finite
   output and absolute API-reported relative variance below `0.0001` on the 499 row for
   every reported indicator. The API map is sparse: after successful completion, an empty
   result or a missing 499 key means exact zero for that entry; explicit NaN/Infinity or
   an analysis error is `INVALID`, while an explicit finite value whose absolute value is
   `>= 0.0001` is `REJECTED`. This is last-row indicator evidence only; the earlier exact
   signal parity Gate remains independently required;
3. audit the exact episode/opportunity/signal/order ledger, one-fill invariant, stop
   labels, half-stake invariant, fee/funding reconciliation, force exit, and Freqtrade
   candle-path assumptions.

Lookahead or Recursive output is not revision/DataSnapshot/context-bound in the current
product. Record its exact source/config/data hashes and limitations; do not represent its
green UI alone as formal receipt evidence.

## One holdout spend

Only after the exact frozen C survives every development and safety Gate may the B/C
holdout pair generate strategy output for `20250702-20260702`:

1. run unchanged B first and retain its exact rows;
2. replay those exact rows for unchanged C; do not run S or an alternate candidate;
3. require B-vs-C same-window data/context/endpoints and different valid strategy evidence;
4. require every B/C validity rule, including zero scored boundary-unknown armed
   crossings and every per-role reconciliation predicate, then require the B/C
   trade/direction floors, raw finite-episode floor, C stop floor, C
   lifecycle/opportunity endpoints, and every performance/risk/boundary threshold; there
   is no S control requirement on holdout;
5. after B has spent the window and before interpreting C performance, repeat C's exact
   499/cold/warm/longer signal-parity check on only the now-authorized holdout rows;
6. compare C development with C holdout and require FreqUI `CROSS-WINDOW REVIEW`: different
   DataSnapshots, identical C Strategy Evidence and Execution Context, and strictly
   disjoint scored endpoints.

The first visible holdout indicator, signal, trade, or metric is the single spend. Stop
after its first valid result whether it passes, fails, or is insufficient. An
infrastructure-only rerun is permitted only if no strategy output became visible and all
semantic and input hashes remain byte-identical.

A holdout pass would mean only that this fixed bounded candidate survived one retrospective
replication. It would not establish statistical significance, robust profitability,
future stability, Paper eligibility, or a profit guarantee.

## Classification and stop rules

Classify in strict order and stop at the first applicable class: `INVALID` evidence or
implementation first; otherwise `INSUFFICIENT` observation floors; otherwise `REJECTED`
valid and sufficient outcome failures. The same fact may not appear in two classes.

### `INVALID`

- any required DataSnapshot, captured-context, endpoint, replay, source, configuration,
  or input mismatch;
- missing/gapped Futures, mark, or funding input; current, zero, or synthetic funding
  fallback; cache reuse; malformed or non-finite result fields;
- raw eligibility, validity, or episode denominators differ where the candidate promises
  identical inputs;
- candidate implementation differs from the frozen semantics;
- any boundary-unknown run creates an armed crossing in the scored interval;
- any required order field is missing/malformed, or any order-count,
  opportunity-denominator, fee, funding, result, or per-role arithmetic identity fails;
- Lookahead or Recursive analysis errors, or any explicit non-finite analysis value;
- holdout strategy output before authorization.

### `INSUFFICIENT`

- any sample, direction, episode, stop, Lookahead-signal, or control-exercise floor misses;
- an apparent pass depends on force-exit boundary cashflow.

### `REJECTED`

- any exact 499/cold/warm/longer signal-parity check fails;
- `mechanism_failures` is nonzero;
- any performance, risk, exposure, Lookahead-bias, explicit finite Recursive-variance,
  or lifecycle threshold fails;
- either direction's net profit is non-positive;
- the one holdout repeat fails after a valid spend.

No canonical miss may be rescued by another stop, full-stake variant, delayed/two-row
pulse, directional latch, longer warmup, side/subperiod selection, altered threshold,
Hyperopt, or a prettier chart.

## Repository change policy

Before performance, the only tracked changes authorized are this preregistration and its
documentation routing. Temporary candidate code, tests, isolated data, logs, and result
artifacts stay outside tracked paths.

If the candidate is rejected, insufficient, or invalid after output is visible:

- do not edit either tracked `VolatilitySystem` copy;
- write one factual report;
- remove temporary artifacts and services;
- leave all repositories clean.

Only if every development, safety, and holdout Gate passes:

1. apply the frozen candidate semantics to the authoritative strategy submodule;
2. apply the identical source to the packaged runtime copy;
3. add one focused Root strategy test covering the frozen signal, exit, stake,
   no-adjustment, prefix-parity, and byte-identity contracts;
4. commit the strategy submodule first, then the Root pointer, runtime copy, test, and
   documentation;
5. replay development and holdout with the exact tracked source and require trades and
   metrics to reproduce the temporary candidate before writing acceptance evidence.

## Explicit non-goals

- no backend, frontend, API, database, chart, Experiment CRUD, optimizer, ranker,
  scheduler, daemon, or AI strategy-generation loop;
- no cooldown, regime filter, new indicator, take-profit, trailing stop, alternate stop,
  parameter search, or second candidate;
- no dynamic RuntimeInstance, Paper Observation, exchange write, or real-money order;
- no claim of causal component attribution, statistical significance, robust profit,
  calibrated tail probability, or likely future return.
