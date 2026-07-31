# Phase 1 Futures Validation Dogfood Acceptance

**Status:** accepted as a bounded existing-capability dogfood receipt; the tested
`VolatilitySystem` candidate is rejected for Paper promotion

**Acceptance date:** 2026-07-31

## Decision

The existing standard Freqtrade Backtest, Lookahead Analysis, Recursive Analysis, and
evidence-guided two-result comparison are sufficient for the current Futures strategy
validation loop. No shared multi-strategy API, scored-window-only digest, persisted
baseline/candidate role, optimizer, ranker, or new research engine is justified by this
dogfood.

One strategy defect was found and repaired: both tracked copies of `VolatilitySystem`
now declare `startup_candle_count = 499`. This is the smallest tested candidate that made
the strategy's resampled ATR indicators converge to a negligible reported variance in
the bounded Recursive Analysis run. It is evidence-derived for this strategy and data
shape; it is not claimed as a universal minimum.

The candidate did not demonstrate a performance improvement. On the controlled Q1 2025
run it lost 2.021%, compared with 1.751% for `FSampleStrategy`. The workflow is accepted;
the candidate is not.

## Frozen implementation identity

| Component | Accepted identity |
|---|---|
| Root | `e1553633de53fdd81afc037c580b7d5b2d300402` |
| Backend | `3209d437450fd1cc72903d9cc5ae8225bd7f8fb6` |
| Frontend | `515b00cccb882c3f304bab18d0eb5520f934901e` |
| Strategies | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` |
| Docker image | `freqtrade-cn:dogfood-e155363` |
| Image identity | `sha256:749e372bfee2bc5d263608f37d7e7ceb2ae4f9ff93dc271d6637e6e6311bc30a` |
| Isolated dogfood origin | `http://127.0.0.1:18084` |

The isolated port preserves the existing 8083 webserver route semantics without
interfering with a configured compatibility service. The image build used the exact
working-tree contents above. The current Docker frontend build stage does not have Git
metadata and therefore does not emit a trustworthy frontend commit in its UI version
label; the immutable image identity and the separately recorded source SHAs are the
traceability boundary for this receipt.

## Protocol

- Venue and product: OKX Futures, isolated-margin configuration.
- Pair: `BTC/USDT:USDT` only.
- Primary timeframe: `1h`.
- Scored Backtest window: `2025-01-01T00:00:00Z` through
  `2025-04-01T00:00:00Z`.
- Standard offline inputs: primary Futures candles plus mark and funding-rate series.
- Stake and wallet: 100 USDT stake, 1,000 USDT starting wallet, one maximum open trade.
- Protections: disabled for both compared runs.
- Backtest cache: `none` for both compared runs.
- Evidence capture: exact DataSnapshot, Strategy Evidence v2, and Execution Context
  Evidence enabled; retained replay rows enabled.
- Controlled warmup: configuration-level `startup_candle_count = 499` for both
  strategies. This uses Freqtrade's existing resolved-strategy override and is captured
  by Strategy Evidence v2.
- Recursive Analysis window: `2025-01-01` through `2025-08-01`, with startup counts
  299, 499, and 999.
- Lookahead Analysis window: Q1 2025, minimum and target trade amounts both 5, with the
  limit-order diagnostic option enabled.

The common warmup is a comparison protocol, not a product feature. It makes both runs
admit the same causal prefix before the same scored window. The comparator continues to
use full DataSnapshot identity and is not weakened to scored rows only.

## Negative control: native warmups fail closed

The first baseline/candidate pair used each strategy's native warmup. It had the same
captured execution context and the same displayed scored window, but different admitted
market-data identities:

| Run | Primary rows | Primary start | DataSnapshot |
|---|---:|---|---|
| `FSampleStrategy` baseline | 2,191 | `2024-12-30T18:00:00Z` | `data-snapshot-ed13ed53b0b665d0d205882a5cdc8116c9fb84aaf1c3e414f4ceb78f00f40511` |
| `VolatilitySystem` candidate | 2,660 | `2024-12-11T05:00:00Z` | `data-snapshot-861ae99bdaa06af52beb965d22f5ceafac15ed2764f9a86c0394c7afead55d9e` |

FreqUI correctly rendered `NOT COMPARABLE FOR THESE REVIEWS`. This is desired
fail-closed behavior: equal score dates alone do not prove equal admitted data.

## Controlled comparison receipt

With the common 499-candle warmup, both runs captured:

- DataSnapshot
  `data-snapshot-861ae99bdaa06af52beb965d22f5ceafac15ed2764f9a86c0394c7afead55d9e`;
- Execution Context Evidence
  `execution-context-evidence-7e8386e1c34c301e843e04eb1688ed290a355b71b3836aabee7202cb2e3e7e67`;
- 5,092 total rows across three standard series, including 2,660 primary Futures rows
  from `2024-12-11T05:00:00Z` through `2025-04-01T00:00:00Z`;
- the same effective Q1 scored window.

Their Strategy Evidence identities differ, as intended:

| Role | Strategy | Revision | Strategy Evidence | Trades | Total profit |
|---|---|---|---|---:|---:|
| Baseline | `FSampleStrategy` | `experiment-revision-bb7eaf7b1329d3af4e3db427248a4c3937a6e868752534f27ffbf53d28344c62` | `strategy-evidence-e78ad192a42be0f0fb8e4e6948837184b03f07791c015ec2104d3c34f0548e05` | 5 | -1.751% / -17.510 USDT |
| Candidate | `VolatilitySystem` | `experiment-revision-d3f1b29c69ce61cab103bc105aa073ef9d51c77ad5ef122dd68e8067bc25fcad` | `strategy-evidence-4a71648327f30d328b10d1f85c1b5639191060f2b87d29b252f4d40c7ad61b30` | 9 | -2.021% / -20.211 USDT |

The retained artifacts are:

- baseline:
  `backtest-result-2026-07-31_10-38-44_336909-b4db4fc28199422187420ecfe7b952d4`;
- candidate:
  `backtest-result-2026-07-31_10-38-47_499773-9084a096ec9143fb94307c08e77e5e55`.

FreqUI rendered `SAME-WINDOW STRATEGY CHANGE` and `SAME CAPTURED SCOPE`, while keeping
the distinct strategy evidence visible. This classification permits neutral review of
the observed delta only. It does not establish causality, robustness, future profit, or
Paper eligibility.

## Analysis receipts

### Lookahead Analysis

The exact-image API and UI run ended successfully:

- `has_bias = false`;
- total signals: 5;
- biased entry signals: 0;
- biased exit signals: 0;
- biased indicators: none reported.

This means no lookahead bias was detected in this small bounded sample. Five signals are
not broad evidence, and allowing limit orders makes the diagnostic less conclusive. The
result is not a proof that the strategy is globally free of bias.

### Recursive Analysis

The strategy's declared startup count was reported as 499. Both `atr` and
`resample_180_atr` returned the same API-reported relative variance:

| Startup candles | Reported variance | Approximate percent |
|---:|---:|---:|
| 299 | `-0.000252796524` | `-0.0252796524%` |
| 499 | `-0.000001724418` | `-0.0001724418%` |
| 999 | `0.000000000002` | `0.0000000002%` |

This supports 499 as a practical startup boundary for the present validation loop. It
does not prove convergence for every venue, pair, timeframe, or future strategy change.

## Verification and review

- Both tracked strategy files compiled with Python and had identical content hashes
  after the repair.
- Docker built the frozen implementation into the image identity recorded above.
- Exact-image Backtest, Lookahead Analysis, and Recursive Analysis requests all ended
  successfully.
- The controlled pair was verified both through API receipts and through the real FreqUI
  comparison journey.
- An independent implementation Gate reported no P0, P1, or P2 finding for the
  `startup_candle_count = 499` repair.
- Independent design audits agreed that a common configuration-level warmup is the
  lightest truthful protocol. A shared multi-strategy API or weaker data comparator
  would add lifecycle and artifact complexity without solving a demonstrated user
  problem.

## Accepted boundary and next action

Accepted:

- keep the 499-candle strategy startup repair;
- keep the comparator's existing fail-closed full-data rule;
- use the maximum required startup count across a pair whenever two strategies are
  compared on one scored window;
- use the standard 8083-equivalent Freqtrade Backtest and analysis routes as the sole
  current validation authority.

Not accepted or activated:

- promotion of `VolatilitySystem` to Paper;
- persisted baseline/candidate or calibration/holdout roles;
- automatic ranking, Hyperopt UI, AI daemon, or continuous strategy generation;
- Experiment CRUD, StrategyRelease/BotRelease, dynamic RuntimeInstance, Paper
  Observation, Runtime Access, platform cutover, or Live trading.

The next healthy step is strategy research using the existing engine: form one explicit
hypothesis, rerun baseline and candidate with a common warmup, then require a credible
in-window result before spending a disjoint historical window as holdout evidence. New
platform code should be considered only when that repeated user journey exposes a
specific missing capability.

## Evidence limits

This receipt covers one pair, one primary timeframe, one in-sample quarter, and very few
trades. It does not establish statistical significance, walk-forward validity, unused
holdout provenance, artifact authenticity, complete environmental reproducibility,
broader market robustness, safe contract execution, Paper eligibility, or future
profit. No exchange write or real-money operation was performed.
