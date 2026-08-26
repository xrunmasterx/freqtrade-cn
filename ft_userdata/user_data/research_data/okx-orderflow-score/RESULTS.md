# OKX BTC/ETH Order-Flow A-Score Research Result

## Decision

Reject this version for live trading. Its realized expectancy is negative in the complete-data
window, and the window is too short to support an annualized-performance claim.

## Causal data contract

- Instruments: `BTC-USDT-SWAP`, `ETH-USDT-SWAP` only.
- Execution timeframe: 15 minutes; structure timeframes: 1 hour and 4 hours.
- Order flow: official OKX aggressor-side trades aggregated to 5-minute and 15-minute buckets.
- Volume profile: the previous completed UTC day only.
- Open interest: official OKX daily observation delayed by one UTC day.
- Funding: actual settlement observation delayed by one 15-minute candle.
- Tradability: 15-minute ATR/price must be between 0.4% and 4.5%.
- Entry: next 15-minute candle open after a completed signal candle.
- Costs: actual funding plus 0.06% market-order fee on each side in the baseline.

The complete common backtest interval is 2026-07-24 00:00 UTC through
2026-08-23 00:00 UTC. The OKX trade archive available during this run ended at
2026-08-23 16:00 UTC, so later local candles were not used.

## Results

| Run | Trades | Wins | Net return | Net PnL | Profit factor | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline, 0.06% per side | 3 | 0 (0%) | -2.14% | -214.04 USDT | 0.00 | 2.14% |
| Fee stress, 0.10% per side | 3 | 0 (0%) | -2.31% | -230.83 USDT | 0.00 | 2.31% |

Baseline pair attribution:

| Pair | Trades | Net return | Net PnL |
| --- | ---: | ---: | ---: |
| BTC/USDT:USDT | 2 | -1.54% | -153.66 USDT |
| ETH/USDT:USDT | 1 | -0.60% | -60.38 USDT |

Baseline realized funding was +0.36 USDT. Estimated exchange fees from filled order notional were
25.41 USDT. All three entries were grade A; no A+ setup occurred.

## Integrity checks

- Tick-derived 15-minute base volume versus official candles: maximum relative error 0.01024%
  for BTC and 0.00190% for ETH.
- Freqtrade lookahead analysis: no bias; 3 signals, zero biased entries and zero biased exits.
- Focused tests: 12 passed.

## Unavailable fields

No proxy or fabricated values were substituted for these fields:

- Historical best-bid/ask spread. This needs an OKX L2 archive parser that emits causal
  15-minute spread/depth snapshots.
- Historical liquidation clusters. This needs a separate historical liquidation-event source or
  a collector retained prospectively.

The spread hard filter was omitted because this research is restricted to BTC/ETH, matching the
provided specification's high-liquidity exception. Liquidation-cluster bonus points were disabled.
