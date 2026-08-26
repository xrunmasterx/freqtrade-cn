# Multi-Timeframe Regime Research: 50 Fixed Candidates

Status: preregistered before the first performance run.

## Question

Can a 15-minute BTC/USDT perpetual strategy improve regime fit by using closed 4-hour
and daily direction, switching between a trend entry and a range entry, and requiring
observable participation/funding evidence without relying on leverage or a selected
recent window?

## Data and execution

- Source: the retained OKX BTC/USDT:USDT 5-minute snapshot under
  `ft_userdata/user_data/data/okx-btc-usdt-swap-full-20260813`.
- Derived candles: UTC, left-labelled and left-closed `15m`, `1h`, `4h`, and `1d` bars.
  Each derived bar contains only source rows in its interval. The derivation manifest
  records source and output SHA-256 values.
- Funding: observed OKX settlement rows only. No funding rows are synthesized for signal
  features. Freqtrade's zero leading-gap fallback is reported separately and is not used
  to satisfy a funding gate.
- Engine: the local Freqtrade `backtesting` command, one isolated BTC pair, one open
  position, market-style fills, 1x leverage returned by the strategy.
- Cost scenarios: `0.0006` and `0.0010` fee per side. A candidate cannot be promoted from
  the stressed scenario by using the baseline scenario only.
- No paper/live process, exchange write, or deployment is part of this study.

## Temporal split

The split is fixed before looking at candidate metrics:

| Stage | Interval (UTC, end exclusive) | Use |
| --- | --- | --- |
| Development | 2021-09-01 through 2024-12-31 | Screen the 50 fixed variants |
| Validation | 2025-01-01 through 2025-12-31 | Evaluate only frozen development survivors |
| Prospective check | 2026-01-01 through the last complete local candle | Reported as retrospective because the window is locally visible |

The final partial day is never presented as a complete holdout.

## Fixed candidate matrix

There are exactly `5 regime profiles x 5 entry profiles x 2 participation profiles = 50`
variants. Regime profiles vary only the 4h/1d EMA pair, ADX floor, and past slope floor.
Entry profiles are three Donchian breakouts, one breakout-retest, and one Bollinger/RSI
range reversion. `P0` requires prior 96-bar relative volume; `P1` additionally requires
an observed 1h funding rate favourable to the proposed side. The complete expanded list
is emitted from `VARIANT_SPECS` and copied into the run manifest before execution.

No parameter is changed after development results are read. At most the top three
development survivors (ranked by the fixed screen score below) are sent to validation and
the prospective check; if fewer than three pass, all passing candidates are carried.

## Metrics and gates

Metrics are read from the Freqtrade result JSON/ZIP. Strict payoff is recomputed as
`mean(positive profit_ratio) / abs(mean(negative profit_ratio))`, excluding zero-profit
trades. Sharpe uses Freqtrade's reported result field and its documented daily-return
annualization; a missing value is a failure, not zero-filled evidence.

Development screen gates (minimum 30 trades):

- win rate `> 50%`;
- strict payoff `> 2.0`;
- Sharpe `>= 1.5`;
- profit factor `> 1.0` and net profit positive after fees;
- no liquidation and account drawdown `< 20%`;
- at least three of four fixed development calendar blocks profitable.

Validation/prospective gates use the same metric thresholds with minimum 15/10 trades,
respectively. A strategy is **qualified** only if it passes both fee scenarios in every
stage with sufficient samples. Small-sample rows remain `INSUFFICIENT_SAMPLE`, never
green-qualified.

The development ranking is lexicographic:

1. worst calendar-block profit;
2. Sharpe;
3. strict payoff;
4. profit factor;
5. win rate;
6. lower drawdown.

This ranking is fixed before execution and is not changed to rescue a preferred strategy.

## Audit requirements

Each round records the exact command, strategy source hash, config hash, data manifest hash,
timerange, fee scenario, Freqtrade ZIP path/hash, raw metric payload, and a trade
fingerprint. Any missing artifact, failed process, or funding-coverage violation is
recorded as a failed round. Lookahead/recursive checks are separate safety evidence and
cannot turn a performance failure into a pass.
