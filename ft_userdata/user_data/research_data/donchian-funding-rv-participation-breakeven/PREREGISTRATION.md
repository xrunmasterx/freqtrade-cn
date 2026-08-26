# OKX BTC Donchian Funding/RV Participation Break-Even F5 Preregistration

Status: frozen retrospective research protocol. All admitted rows are the already-frozen
F3 development snapshot with timestamps strictly before 2024. This study can produce only
retrospective development evidence; validation, pseudo-OOS, Paper, Live, and any other data
or performance stage are unauthorized.

## Authority and data boundary

`FREEZE.json` in this directory is the external byte-identity authority. It binds this
runner, its focused tests, this preregistration, the frozen F3 base runner, the frozen F3
`FREEZE.json`, the existing development manifest, and the same three physical development
Feather inputs. Runtime performance requires explicit `--stage development` and an explicit
`--freeze-sha256` equal to the external SHA-256 of this `FREEZE.json`. Every bound artifact
and input is hashed successfully before the manifest is interpreted or a Feather is opened.

The only admitted execution inputs remain:

- `donchian-funding-rv/development-data/BTC_USDT_USDT-5m-futures.feather`;
- `donchian-funding-rv/development-data/BTC_USDT_USDT-15m-futures.feather`;
- `donchian-funding-rv/development-data/BTC_USDT_USDT-1h-funding_rate.feather`.

The runner contains no source-data path and no path to a file containing 2024 or later.
The F3 physical pre-2024 checks, manifest contract, development interval, 48-hour label
boundary, funding coverage rules, and cross-timeframe audit remain unchanged. The default
command prints only the mechanical plan. Validation and pseudo-OOS fail closed before input
read. No result file is written.

## Unique candidate F5

The base D20 events, F3 funding/RV conditions, official 15m source, closed-candle decision
time, and official 5m entry are unchanged. There is exactly one candidate, F5. It passes
only when F3 and both additional conditions A and B pass:

```text
F5 = F3 AND A AND B

A:
  CLV = clip((2 * close - high - low) / (high - low), -1, 1)
  direction * CLV >= 0.35
  body_atr = abs(close - open) / ATR14 >= 0.30
  true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
  ATR14 = true_range.ewm(alpha=1/14, adjust=False).mean()

B:
  relative_volume = current_volume / volume.rolling(96).mean().shift(1) >= 0.80
```

All A and B values use the already-closed official 15m signal candle. The relative-volume
denominator contains exactly the prior 96 closed 15m volumes and excludes the current
signal volume. A zero high-low range, unavailable ATR, nonpositive prior-volume mean, or
any other unavailable required value fails the corresponding condition closed. The
accept-all comparator keeps the identical D20 base events and the identical execution
engine, including the 1R break-even rule below, but does not apply F3, A, or B.

## Frozen execution, 1R break-even, and accounting

The 4% target, initial 1.5% stop, 48-hour maximum hold, `max_open_trades=1`, stable long
priority at equal decision time, and permission to re-enter at the exact prior exit
timestamp remain unchanged. Target gaps remain capped at the target. Stop gaps use the
worse open. Within a 5m candle, stop remains first when stop and target both touch. The
48-hour open is evaluated before that candle's range. Actual funding in
`(entry_time, exit_time]`, 1x full-wallet accounting, and all F3 invalidity rules remain
unchanged.

The only added risk rule is a one-way 1R break-even stop. One R is an underlying-price
favorable move of 1.5% from entry: `high >= entry * 1.015` for a long or
`low <= entry * 0.985` for a short. A bar activates break-even only after the complete bar
has first been evaluated under the existing deadline, gap, stop-first, and target rules and
has not exited. The activating bar continues to use the initial stop; the break-even stop
becomes eligible only on the next 5m bar. Once activated it never moves back.

The break-even stop is the baseline cash-cost proxy:

```text
long  = entry * (1 + 0.0006) / (1 - 0.0006)
short = entry * (1 - 0.0006) / (1 + 0.0006)
```

After activation, a gap through that stop exits at the worse open and intrabar stop-first
ordering is unchanged. Baseline, stress, and severe all use this same baseline break-even
price; it never moves with scenario fee rate. Funding is still added separately to final
profit, so this price covers only the frozen baseline cash-cost proxy and does not promise
funding-inclusive net zero.

Per-side fee rates remain baseline `0.0006`, stress `0.0010`, and severe `0.0015`. Entry
fee, exit fee, price profit, actual funding cash, wallet update, profit ratio, profit factor,
strict payoff, and account drawdown use exactly the frozen F3 formulas.

## Frozen development gate

Every F3 hard development gate is retained without addition or relaxation. F5 baseline
must have at least 30 trades, at least five long and five short trades, win rate at least
40%, winners and losers, strict payoff at least 2, profit factor greater than 1.2, positive
net profit, drawdown below 25%, and zero left-open trades. F5 stress must have profit factor
greater than 1, positive net profit, and drawdown below 30%. Relative to accept-all
baseline, F5 profit factor must improve by at least 0.15 and drawdown must not be higher.
Severe is reported only. Any failed hard condition is `DEVELOPMENT_REJECTED`; later stages
remain unauthorized regardless of outcome.
