# OKX BTC Donchian Funding/RV F3 Preregistration

Status: frozen retrospective research protocol. Every window described here has already
been historically exposed. This study can only produce retrospective development evidence;
it is not fresh validation, pseudo-OOS, Paper, or Live evidence.

## Authority and data boundary

`FREEZE.json` in this directory is the independent byte-identity authority. It binds the
final runner, focused tests, single-purpose development-data preparer, this preregistration,
the development-data manifest, and all three physical development Feather inputs. This
section intentionally points to that authority instead of embedding mutable SHA values and
creating a self-reference cycle.

The runner's only admitted inputs are the physical files below, under this directory's
`development-data/`:

- `BTC_USDT_USDT-5m-futures.feather` (execution path only);
- `BTC_USDT_USDT-15m-futures.feather` (event and RV only);
- `BTC_USDT_USDT-1h-funding_rate.feather` (actual settlement events only; `open` is the rate).

The standalone preparer is data-identity work only: from the three source files bound in its
code it mechanically writes rows with `date < 2024-01-01T00:00:00Z`, records source and
derived SHA-256, row count, first/last timestamp, and cutoff in `development-data/manifest.json`,
and refuses to run if the output directory already exists. It computes no event, label,
trade, or performance value. The performance runner contains no source/full/pre-2025 data
path and cannot select such a mode.

The engine rejects every other path, including source/full snapshots, 1h/4h price candles,
mark candles, Binance data, and runtime/backtest artifacts. It rejects any admitted physical
input whose maximum timestamp is at or after `2024-01-01T00:00:00Z`; it never reads a file
containing 2024 and then crops it. Development event decision times remain
`[2022-03-01T00:00:00Z, 2024-01-01T00:00:00Z)`. Events whose full 48-hour label horizon
reaches 2024 are excluded, and every opened position must exit before 2024. Validation and
pseudo-OOS are fail-closed and unauthorized.

Official 15m and 5m candles have separate roles. The 15m series is never reconstructed from
5m. Known small cross-timeframe historical revisions mean equality is not assumed; every
development report must disclose counts of official 15m rows, comparable complete 5m groups,
OHLC revision mismatches, and missing/incomplete groups.

## Frozen event and F3

There is exactly one base event. On official closed 15m candles, its prior channel is
`high.rolling(20).max().shift(1)` and `low.rolling(20).min().shift(1)`. A long event is the
first close above the prior upper channel after a non-breakout close; a short event is the
symmetric first close below the prior lower channel. `decision_time = date + 15 minutes`.
The entry is the official 5m open exactly at `decision_time`.

RV24 is exactly
`sqrt(rolling_sum_96(log(close / close.shift(1)) ** 2))`: the current closed 15m return plus
the prior 95 returns. No forming candle participates.

There is exactly one candidate, F3, with no fitted model or tunable threshold:

```text
direction * last_known_actual_funding_rate <= -0.0000352449
and rv24 <= 0.0269415
```

Funding uses the final actual settlement event whose timestamp is `<= decision_time`.
Predicted or future funding is forbidden. Missing as-of funding fails F3 closed. The
accept-all comparator uses the identical base events and execution engine without the F3
selector.

Actual settlement timestamps are strictly increasing and cover both ends of the development
window with at most ten hours to either boundary. Every internal interval from 2022-03-01 is
at most ten hours. The official exceptional schedule is frozen as
`2022-12-18 08:00Z -> 18:00Z` (10h), followed by `18:00Z -> 2022-12-19 00:00Z` (6h);
`2022-12-18 16:00Z` is not a missing event. The source's `2022-02-25 08:00Z` absence is
before development and does not invalidate this window. Any larger internal development
gap makes the entire stage `INVALID`, and each opened trade independently verifies that its
at-most-48-hour funding path contains no gap or uncovered endpoint over ten hours before
settlement rates are summed.

## Frozen execution and accounting

Signals are confirmed at the 15m close and entered at the next 5m open. The underlying-price
target is 4%, stop is 1.5%, and maximum holding time is 48 hours. A 5m candle touching both
barriers exits stop-first. A stop gap exits at the worse 5m open; a target gap exits at the
target and never receives a price better than the barrier. At 48 hours the position exits at
that timestamp's first official 5m open before evaluating that candle's range. Missing 5m
candles, a missing exact entry/deadline candle, duplicates, or timestamp disorder makes the
entire stage `INVALID`.

Events are stably ordered by `decision_time`, long before short at equal time. With
`max_open_trades=1`, events during an open position are ignored and never queued. An event at
the exact exit timestamp may enter after the prior exit. Leverage is 1x, initial wallet is
1000 USDT, the full available wallet is entry notional, and margin semantics are isolated.

For wallet `W`, entry `E`, exit `X`, and direction `d`, quantity is `q=W/E`. Entry fee is
`q*E*fee`, exit fee is `q*X*fee`, and price PnL is `d*q*(X-E)`. Actual funding events in
`(entry_time, exit_time]` are accumulated as
`-d*q*E*sum(actual_rate)`: a positive rate costs a long and benefits a short. Entry notional
is deliberately the funding cash base because mark data is forbidden. No price slippage is
added. Fee rates per side are baseline `0.0006` (5 bp taker proxy plus 1 bp cash-equivalent
slippage proxy), stress `0.0010`, and severe `0.0015`.

## Frozen development gate

Profit factor uses `profit_abs`; strict payoff uses `profit_ratio`. A zero/missing required
denominator is N/A and fails. The F3 baseline must have at least 30 trades, at least five
long and five short trades, win rate at least 40%, both winners and losers, strict payoff at
least 2, profit factor greater than 1.2, positive net profit, account drawdown below 25%, and
zero left-open trades. F3 stress must have profit factor greater than 1, positive net profit,
and drawdown below 30%. Relative to accept-all baseline, F3 profit factor must improve by at
least 0.15 and drawdown must not be higher. Severe is reported but has no additional pass
gate. Failure of any required condition is `DEVELOPMENT_REJECTED`; no later data may be read.

The default command only prints the frozen mechanical plan. Performance execution requires
both explicit `--stage development` and `--freeze-sha256` equal to the exact external SHA-256
of `FREEZE.json`. The runner verifies the manifest, itself, the focused tests, preparer,
preregistration, and all three execution inputs before reading any Feather. It writes no
result file. Validation and pseudo-OOS remain unimplemented/fail-closed.
