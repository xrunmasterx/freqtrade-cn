# Multi-Timeframe Capital-Regime Research: 50 Fixed Candidates

Status: frozen before the first candidate development result for this amendment.

## Question

Does a 15-minute BTC/USDT perpetual strategy improve regime fit by trading only when
closed 4-hour and daily direction agree, while using causal mark/futures basis,
observed funding freshness, volatility, and participation filters? A disagreement or
weak higher-timeframe state is flat; there is no unvalidated range strategy leg.

## Data and accounting

- Source: retained OKX BTC/USDT:USDT 5-minute snapshot under
  `ft_userdata/user_data/data/okx-btc-usdt-swap-full-20260813`.
- Derived data: UTC, left-labelled and left-closed `15m`, `1h`, `4h`, and `1d` futures
  candles. The data preparation manifest records every source and derived SHA-256.
- Mark: the authoritative `1h-mark` file is required and is copied into the research
  data root. It is used both for the basis feature and the Freqtrade funding ledger.
- Funding: observed OKX settlement rows only. No synthetic rows are added to signal
  features. A funding signal observation is valid only while its age is at most 8 hours.
- Basis: mark/futures 1h values are merged after the informative candle closes; a basis
  observation is valid only while its age is at most 2 hours.
- Engine: local Freqtrade `backtesting`, one BTC pair, one open position, market-style
  fills, and exactly 1x leverage returned by the strategy.
- Fee scenarios: baseline `0.0006` and stress `0.0010` per side. Funding costs are
  reported from the mark-inclusive Freqtrade result, not estimated from a fallback rate.

## Temporal split

| Stage | UTC interval (end exclusive) | Use |
| --- | --- | --- |
| Development | 2021-09-01 through 2024-12-31 | Screen all 50 fixed variants |
| Validation | 2025-01-01 through 2025-12-31 | Evaluate only development survivors |
| Prospective check | 2026-01-01 through the last complete local candle | Retrospective report only |

The final partial local day is never labelled a complete holdout. Factor diagnostics
are descriptive development evidence and are not performance validation.

## Fixed candidate matrix

There are exactly `5 regime profiles x 5 signal profiles x 2 participation profiles =
50` variants. Regime profiles vary the closed 4h/1d EMA pairs, ADX floors, and slope
floors. Signal profiles vary only the prior-channel length, directional candle quality,
ATR/volume floor, momentum allowance, and one of breakout, retest, or expansion entry
shapes. Participation P0 uses mark/futures basis and age checks but does not require a
funding gate; P1 additionally requires an observed side-favourable funding rate and the
stricter basis band. All profiles are expanded from `VARIANT_SPECS` before execution.

No parameter, side rule, exit, fee, data path, or ranking rule may be changed after a
development result is inspected. Every candidate uses the same 3% ROI target, 1.2%
stop, stale-loss exit, and maximum-hold rule supplied by its frozen signal profile.

## Metrics and gates

Strict payoff is recomputed from non-zero trade returns as
`mean(positive profit_ratio) / abs(mean(negative profit_ratio))`. Freqtrade's reported
daily-wallet Sharpe is used; a missing value is a failure. The requested Sharpe floor
of 1.5 is interpreted as an absolute reported Sharpe value, not 1.5 percent.

Development requires at least 30 trades and all of:

- win rate `> 50%`;
- strict payoff `> 2.0`;
- Sharpe `>= 1.5`;
- profit factor `> 1.0` and positive net profit after fee and funding;
- account drawdown `< 20%`, with no liquidation or forced exit;
- at least three of four fixed development calendar blocks profitable;
- mark/funding result audit present, with no missing mark ledger for the scored window.

Validation and prospective checks use the same quality thresholds with minimum samples
of 15 and 10 trades. A candidate is qualified only if it passes both fee scenarios in
every stage. Insufficient-sample rows remain non-qualifying and are never substituted
with a short-window diagnostic.

The development ranking is fixed lexicographically: worst calendar-block profit,
Sharpe, strict payoff, profit factor, win rate, then lower drawdown. At most the top
three candidates that pass the complete development screen may proceed. If zero
candidates pass development, validation and prospective work are not opened and the
study closes as `NO_DEVELOPMENT_SURVIVOR`.

## Audit and safety boundary

Each round records the exact command, source/config/manifest hashes, timerange, fee,
Freqtrade ZIP path and hash, raw result payload, funding-fee sum, and trade fingerprint.
Missing artifacts, failed processes, stale side-data violations, or a zero-mark funding
ledger are failed rounds. Lookahead and recursive checks are separate safety evidence;
they cannot turn a performance failure into a pass. This offline study authorizes no
exchange write, Paper promotion, Live deployment, leverage change, or current/future
profit claim.
