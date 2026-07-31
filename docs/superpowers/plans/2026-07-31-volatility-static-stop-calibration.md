# VolatilitySystem Static-Stop Calibration

**Status:** active, preregistered strategy-research protocol; calibration not yet run

**Decision owner:** local strategy researcher

**Product authority:** [../STRATEGY.md](../STRATEGY.md)

**Preceding evidence:**
[Phase 1 Futures Validation Dogfood](../reports/2026-07-31-phase1-futures-validation-dogfood-acceptance.md)

## Goal

Test one minimal, falsifiable claim with the existing authoritative Freqtrade engine:

> `VolatilitySystem` lets failed three-hour breakouts become unnecessarily large losses
> because its effective `stoploss = -1` leaves the opposite breakout as the only normal
> loss exit. A static 10% stop anchored at the initial entry should reduce those tail
> losses without changing the market thesis, signals, leverage, stake policy, or
> pyramiding policy.

This is a risk-control experiment, not a search for a profitable parameter. A safer but
still losing candidate is rejected. No result from this plan can establish future
profit, Paper eligibility, or Live safety.

## Why this is the next smallest healthy experiment

The accepted Q1 2025 receipt had only nine trades and lost 2.021%. A trade-level audit
found that the largest losses were fast reversals which remained open until an opposite
breakout:

- three unscaled trades lost approximately 14.0%, 10.2%, and 17.3%;
- the first scaled short lost approximately 11.5% after first moving materially in its
  favor;
- `minimal_roi = {"0": 100}` is practically unreachable and `stoploss = -1` permits a
  loss far beyond the intended research risk budget;
- at fixed 2x leverage, a 10% Freqtrade stop risk corresponds to approximately a 5%
  adverse underlying-price move.

The audit also rejected three tempting but weaker first changes:

1. **Do not change to `crossed_above` now.** All 13 Q1 initial and scale-in orders came
   from the first shifted row of a distinct signal episode. None was caused by the
   second or third forward-filled row. Replacing the level predicate would mostly remove
   redundant dataframe rows, not the observed orders or reversals.
2. **Do not disable pyramiding now.** Four trades scaled once, but the three largest
   unscaled losses remain unexplained by pyramiding. Exposure reduction alone is not a
   repair of the loss-exit mechanism.
3. **Do not add the observed `strength > 1.3` filter.** That threshold separated the nine
   Q1 trades retrospectively and is therefore data-mined. Testing it as if it were an
   ex-ante rule would reward overfitting.

The original strategy description also presents the system as a continuation strategy,
warns that noise can defeat it on small timeframes, and notes the absence of stop-loss
and take-profit controls. That is useful hypothesis context, not evidence that any fixed
stop will work: [TradingView source](https://www.tradingview.com/script/3hhs0XbR/).

## Frozen candidate

The candidate differs from the accepted baseline in exactly one effective setting:

```text
stoploss: -1 -> -0.10
```

For calibration, apply this through one isolated configuration overlay. Do not edit the
tracked strategy first. This keeps the accepted baseline intact and lets Strategy
Evidence bind the changed effective setting. Only a candidate which passes every
calibration and holdout Gate may update the two tracked strategy copies.

The value is derived from a simple initial-position risk policy, not from a Backtest
sweep:

- maximum configured stake: 100 USDT;
- starting research wallet: 1,000 USDT;
- maximum open trades: one;
- the normal initial half-position risks approximately 5 USDT, or 0.5% of the starting
  wallet, before fees, funding, gaps, and slippage;
- 100 USDT opened at the same stop anchor would risk approximately 10 USDT, or 1%.

This is not a guaranteed 1% account-risk cap. Freqtrade keeps the static stop anchored at
the initial entry when `adjust_trade_position` adds a later tranche. Because this
strategy normally adds only after price moves in its favor, that later tranche may be
farther from the original stop and total position loss can exceed 10 USDT. The
predeclared worst-trade Gate below must catch that failure. Re-anchoring after a fill,
disabling pyramiding, or changing stake sizing would be a second semantic change and is
outside this study.

No other stop value may be run in this study. If `-0.10` fails, this candidate is
rejected; it is not retuned.

## Frozen data split

The local OKX series were inspected for coverage and continuity only. No signals,
trades, chart, return, or P&L were inspected after Q1 2025 before these boundaries were
selected.

| Role | Freqtrade request timerange | Intended scored interval | State |
|---|---|---|---|
| Calibration | `20240701-20250701` | 2024-07-01 00:00 UTC through the engine's 2025-07-01 boundary | May be opened |
| Holdout | `20250702-20260702` | 2025-07-02 00:00 UTC through the engine's 2026-07-02 boundary | Sealed until calibration PASS |

The one-day gap makes the effective result endpoints strictly disjoint under the current
FreqUI comparator; equal endpoints are not a cross-window review. Funding history starts
on 2024-06-30, before calibration, and Futures/mark data provide the 499-hour causal
prefix. The holdout ends before the measured 2026-07-08 data endpoint.

The repository cannot prove that no human has ever viewed this interval. The current
research record asserts only that this study and its delegated audits did not inspect
holdout performance. If contrary evidence appears, relabel it a verification window and
do not claim untouched holdout evidence.

## Frozen common inputs

Both baseline and candidate use:

- venue/product: OKX isolated Futures;
- pair: `BTC/USDT:USDT` only;
- timeframe: `1h`;
- primary Futures, mark, and funding-rate series from one isolated copied data directory;
- common resolved `startup_candle_count = 499`;
- stake 100 USDT, starting wallet 1,000 USDT, and one maximum open trade;
- explicit fee ratio `0.0005` per fill, matching the accepted conservative 0.05% model;
- fixed strategy leverage 2x;
- protections off, FreqAI off, Backtest cache `none`;
- the same order types, pair metadata, engine source, and configuration, except for the
  one candidate stop setting;
- forced closure at the requested end boundary, reported separately from normal exits.

The copied data directory is temporary research input. It prevents exchange
initialization from rewriting the main user-data cache and must not be committed.

## Execution order

### 1. Coverage-only preflight

Before any calibration metrics are produced, verify:

- Futures and mark series are continuous at one-hour cadence across both windows and
  their 499-hour prefixes;
- the funding series covers both windows at its native cadence;
- the candidate overlay contains only `{"stoploss": -0.10}`;
- Root, backend, strategy, Python package, and input-file identities are recorded;
- the holdout command is not executed.

Coverage failure is `INSUFFICIENT`. Do not move a boundary after seeing performance.

### 2. Calibration baseline

Run unchanged `VolatilitySystem` on the calibration window first. Export trades with
cache disabled into the isolated result directory. This is the named baseline.

### 3. Calibration candidate

Run the same command with the one stoploss overlay. No source, parameter, window, pair,
fee, wallet, stake, leverage, or engine change is allowed.

For a formal positive comparison, first run the baseline API service with its unchanged
`stoploss = -1` configuration and retain that exact DataSnapshot. `BacktestRequest` has
no stoploss field, so run the candidate through the same image/source with the isolated
service-level `-0.10` configuration overlay and replay the retained baseline data. Do
not represent the candidate as a per-request override.

Interpret metrics only if FreqUI reports `SAME-WINDOW STRATEGY CHANGE`, with:

- the same full DataSnapshot;
- the same captured Execution Context;
- exactly equal effective scored endpoints;
- valid and different Strategy Evidence.

Any mismatch is `INVALID`; P&L must not be interpreted.

### 4. Calibration Gates

Check sample sufficiency before performance. The population is every exported scored
trade, including `force_exit`; do not filter by exit reason, direction, duration, or
profit. Missing, malformed, or non-numeric fields and NaN values are `INVALID`. Numeric
infinity is invalid except a positive infinite `profit_factor` backed by exactly zero
gross loss.

| Gate | Required result |
|---|---|
| Closed trades | Result field `total_trades >= 20` for both baseline and candidate |
| Direction coverage | `trade_count_long >= 5` and `trade_count_short >= 5` for both |
| Candidate total profit | Finite result field `profit_total > 0` after modeled fees and funding |
| Improvement | `candidate.profit_total - baseline.profit_total >= 0.01` |
| Profit factor | Valid candidate `profit_factor >= 1.10` |
| Expectancy | Finite candidate `expectancy > 0` |
| Account drawdown | Finite `candidate.max_drawdown_account < 0.10` and `<= baseline.max_drawdown_account` |
| Tail-loss mechanism | Minimum `trades[*].profit_ratio >= -0.105` across all exported trades |

The 0.50 percentage-point allowance around the nominal stop covers modeled fees,
funding, candle gaps, and execution rounding; it is not permission to change the stop.

If any sufficiency Gate misses, the study is `INSUFFICIENT`. If any performance Gate
misses, the candidate is `REJECTED`. In both cases the holdout remains sealed.

### 5. Safety analysis for a calibration survivor

Only after the metric Gates pass:

- run Lookahead Analysis on the calibration window with limit orders disabled and a
  minimum/target of 20; require successful completion, at least 20 analyzed signals,
  `has_bias = false`, zero biased entries/exits, and no biased indicators;
- run Recursive Analysis with startup counts 299, 499, and 999; require finite results
  and absolute API-reported relative variance below `0.0001` (0.01%) on the 499 row for
  every reported indicator. The API reports each count against its full-data reference;
  999 is a larger diagnostic count, not a pairwise 499-versus-999 denominator.

The stop setting does not change indicator or signal code, but the larger calibration
receipt removes the previous five-signal evidence weakness. A safety-analysis failure
rejects the candidate without opening holdout.

### 6. One holdout spend

Only one frozen calibration survivor may open the holdout:

1. run the unchanged baseline on holdout and retain its data;
2. replay the same retained data for the unchanged candidate;
3. require the same same-window identity and sufficiency Gates;
4. require every calibration performance Gate again without changing thresholds;
5. separately compare candidate calibration with candidate holdout and require FreqUI
   `CROSS-WINDOW REVIEW`: different DataSnapshot, the same Strategy Evidence and
   Execution Context, and strictly disjoint effective scored windows.

A holdout miss rejects the candidate. A pass means only that one fixed candidate
survived one bounded retrospective holdout. It does not activate Paper or Live trading.

## Anti-hunting rules

After the first candidate calibration begins, any change to the semantic edit, stop
value, warmup, pair, timeframe, data routes, engine/configuration, windows, thresholds,
or selected metrics terminates this study. In particular:

- no alternate stop values, Hyperopt, grid, Bayesian search, or manual sweep;
- no post-hoc subperiod, long-only, short-only, regime, or signal-strength rescue;
- no second candidate on the sealed holdout;
- no retry after partial performance becomes visible, except an infrastructure-only
  rerun with byte-identical inputs;
- no promotion based only on lower loss, lower drawdown, or a prettier chart.

A different semantic edit is a new study and needs a new preregistration and a holdout
which is not represented as fresh after it has been viewed.

## Repository change policy

Before the first calibration run, the only repository changes authorized by this plan
are this protocol and its documentation routing. The candidate overlay, isolated data,
logs, and Backtest artifacts remain temporary and untracked. After a run, its factual
acceptance, rejection, insufficiency, or invalidity report is also authorized.

If every Gate passes, the implementation is exactly:

1. change `stoploss = -1` to `stoploss = -0.10` in the authoritative strategy submodule;
2. apply the identical one-line change to the packaged runtime copy;
3. verify byte-identical tracked copies and Python compilation, then replay both frozen
   windows with the exact tracked source; require its trades and metrics to equal the
   overlay candidate before issuing new formal baseline/candidate and cross-window
   receipts, because moving the setting into source intentionally changes Strategy
   Evidence identity;
4. commit the strategy submodule first, then the Root pointer and runtime copy;
5. write a bounded acceptance report with exact identities and evidence limits.

If any Gate fails, do not change strategy code: write the factual report, preserve the
accepted baseline, delete temporary artifacts, and leave all repositories clean.

## Explicit non-goals

- no new API, database, Experiment CRUD, optimizer, ranker, scheduler, or AI daemon;
- no new indicator, regime filter, take-profit, cooldown, trailing stop, or stake model;
- no dynamic RuntimeInstance, Paper Observation, exchange write, or real-money order;
- no claim of statistical significance, robust profitability, or stable future return.
