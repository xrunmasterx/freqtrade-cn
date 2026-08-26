# Multi-Timeframe Regime-Switch Research: 50 Fixed Candidates

Status: frozen before candidate results are inspected.

## Question

Does a causal 15-minute BTC/USDT perpetual strategy improve stability by switching
between a low-ADX reversal leg and a closed-4h/1d trend-continuation leg, while
using mark/futures basis and observed funding only as participation gates?

## Fixed design

The matrix is exactly `5 regime profiles x 5 signal profiles x 2 participation
profiles = 50` variants. Regime profiles change only the closed 4h/1d EMA pair,
the low-ADX ceiling, and whether the range leg, trend leg, or both are enabled.
Signal profiles freeze the ATR deviation, RSI thresholds, target, initial stop,
activation, profit lock, trailing distance, and maximum hold. Participation P0
uses an observed mark/futures basis; P1 additionally requires a fresh funding row
whose sign is favorable to the position and uses a narrower basis band.

No candidate changes after any development result is read. All candidates return
exactly `1.0` leverage, use one BTC perpetual pair and one open position, and use
the same causal higher-timeframe merge and mark audit.

The dynamic stop is monotone: it starts at the fixed initial stop, can tighten only
after the favorable activation threshold, and then uses a fixed entry lock and/or
fixed favorable-rate trail. The target and maximum-hold exits are fixed by the
signal profile. Same-candle conflicts are resolved by the Freqtrade detail path and
are not replaced with an optimistic custom simulator.

## Data and split

The authoritative data root is
`ft_userdata/runtime/freqtrade-futures/data-mtf-capital-regime-research`, with the
manifest and 1h mark hash recorded in the run manifest. Development is
`2021-09-01` through `2025-01-01` (end exclusive), split into calendar blocks D1
through D4. Validation is `2025-01-01` through `2026-01-01`; the prospective check
is `2026-01-01` through the last complete local candle. Validation and prospective
are opened only for complete development survivors.

Fees are `0.0006` and `0.0010` per side. Funding is taken from the mark-inclusive
Freqtrade artifact; no synthetic fallback is used. No exchange write, Paper, Live,
leverage increase, or current-profit claim is authorized.

## Gates

Every development candidate needs at least 30 trades, win rate `>50%`, strict
average payoff `>2`, reported Sharpe `>=1.5`, PF `>1`, positive net profit after
costs, account drawdown `<20%`, no force exits, valid mark audit, and at least
three profitable D1-D4 blocks. If there is no complete development survivor,
validation and prospective are not opened and the result is recorded as
`NO_DEVELOPMENT_SURVIVOR`.
