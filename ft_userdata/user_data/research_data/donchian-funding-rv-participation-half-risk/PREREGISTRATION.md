# OKX BTC Donchian Funding/RV Participation Half-Risk F6 Preregistration

Status: frozen retrospective research protocol. All admitted rows are the already-frozen
F3 development snapshot with timestamps strictly before 2024. This study can produce only
retrospective development evidence; validation, pseudo-OOS, Paper, Live, and any other data
or performance stage are unauthorized.

## Authority and data boundary

`FREEZE.json` in this directory is the external byte-identity authority. It binds this
runner, its focused tests, this preregistration, the frozen F5 runner and `FREEZE.json`, the
frozen F3 runner and `FREEZE.json`, the existing development manifest, and the same three
physical development Feather inputs. Runtime performance requires explicit
`--stage development` and an explicit `--freeze-sha256` equal to the external SHA-256 of
this `FREEZE.json`. Every bound artifact and input is hashed successfully before the
manifest is interpreted or a Feather is opened.

The only admitted execution inputs remain:

- `donchian-funding-rv/development-data/BTC_USDT_USDT-5m-futures.feather`;
- `donchian-funding-rv/development-data/BTC_USDT_USDT-15m-futures.feather`;
- `donchian-funding-rv/development-data/BTC_USDT_USDT-1h-funding_rate.feather`.

The runner contains no source-data path and no path to a file containing 2024 or later.
The F3 physical pre-2024 checks, manifest contract, development interval, 48-hour label
boundary, funding coverage rules, and cross-timeframe audit remain unchanged. The default
command prints only the mechanical plan. Validation and pseudo-OOS fail closed before input
read. No result file is written.

## Unique candidate F6

The base D20 events, official closed 15m source, F3 funding/RV conditions, F5 participation
conditions A and B, closed-candle decision time, and official 5m entry remain unchanged.
There is exactly one candidate, F6:

```text
F6 = F3 AND A AND B
```

F3, A, and B are exactly those frozen by F5. No direction filter, alternate threshold,
parameter variant, or grid is admitted. The accept-all comparator keeps the identical D20
base events and the identical F6 execution engine, but does not apply F3, A, or B.

## Frozen execution and accounting

The 4% target, initial 1.5% stop, 48-hour maximum hold, `max_open_trades=1`, stable long
priority at equal decision time, and permission to re-enter at the exact prior exit
timestamp remain unchanged. Target gaps remain capped at the target. Stop gaps use the
worse open. Within a 5m candle, stop remains first when stop and target both touch. The
48-hour open is evaluated before that candle's range. Actual funding in
`(entry_time, exit_time]`, 1x full-wallet accounting, and all F3 invalidity rules remain
unchanged.

The only new rule is a one-way fixed half-risk price stop. One R remains an underlying-price
favorable move of 1.5% from entry: `high >= entry * 1.015` for a long or
`low <= entry * 0.985` for a short. A bar activates the new stop only after the complete bar
has first been evaluated under the existing deadline, gap, stop-first, and target rules and
has not exited. The activating bar continues to use the initial stop. The fixed stop becomes
eligible only on the next 5m bar and never moves back:

```text
long  = entry * 0.9925
short = entry * 1.0075
```

After activation, a gap through the fixed stop exits at the worse open and intrabar
stop-first ordering is unchanged. Baseline, stress, and severe all use the same fixed stop
price and therefore the same price-exit path for a given trade. Funding remains a separate
accounting item and never changes the stop price.

Per-side fee rates remain baseline `0.0006`, stress `0.0010`, and severe `0.0015`. Entry
fee, exit fee, price profit, actual funding cash, wallet update, profit ratio, profit factor,
strict payoff, and account drawdown use exactly the frozen F3/F5 formulas. Leverage remains
1x, the full available wallet remains entry notional, initial wallet remains 1000 USDT, and
no price slippage is added beyond the frozen cash-equivalent fee proxy.

## Frozen development gate

Every F3/F5 hard development gate is retained without addition or relaxation. F6 baseline
must have at least 30 trades, at least five long and five short trades, win rate at least
40%, winners and losers, strict payoff at least 2, profit factor greater than 1.2, positive
net profit, drawdown below 25%, and zero left-open trades. F6 stress must have profit factor
greater than 1, positive net profit, and drawdown below 30%. Relative to accept-all
baseline, F6 profit factor must improve by at least 0.15 and drawdown must not be higher.
Severe is reported only. Failure of any hard condition is `DEVELOPMENT_REJECTED`; all later
stages remain unauthorized regardless of outcome.
