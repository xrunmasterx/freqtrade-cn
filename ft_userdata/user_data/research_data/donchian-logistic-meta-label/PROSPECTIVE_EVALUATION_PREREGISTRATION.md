# Donchian Logistic Prospective Evaluation Preregistration

Status: gate mathematics, timing, evidence boundary, and fail-closed states are preregistered
before the prospective boundary. The evaluator is deliberately plan-only and `NOT_READY` until
the complete candidate chain, final manifest, authoritative materializer schema, and input
artifacts are frozen. No candidate backtest, performance file, network resource, paper trade, live
trade, or historical result was read to produce this document or its implementation.

This document is candidate-specific. It does not define a generic backtest engine or an optimizer,
and it does not replace the standard Freqtrade engine as the trade, fee, funding, liquidation, or
PnL authority.

## Boundary and final-freeze rule

The scheduled prospective start `R` is `2026-08-14T00:00:00Z`.

The complete final chain must be byte-frozen strictly before `R`. The final manifest must bind at
least the candidate preregistration, strategy, config, frozen model, signal builder, V7 recorder
and freeze, V8 recorder and freeze, this evaluation preregistration, the evaluator, and their exact
lowercase SHA-256 identities. Matching filenames or strategy names are not identity evidence.

If the complete chain is not frozen before scheduled `R`, the manifest must not pretend that the
scheduled boundary remains usable. It must explicitly record `DEFERRED`, the actual freeze time,
and a later 5-minute-aligned effective `R` that is strictly after the complete freeze. All elapsed
checkpoints then move by the same amount and are calculated from that effective `R`. A late chain
without this explicit prospective deferral is `INVALID`; it cannot backfill the missed interval.

The release-to-date evaluation instant is also fixed in the final manifest before effective `R`.
It is not the wall-clock time at which a favorable report happens to be requested. Changing or
choosing that instant after observing performance is `INVALID`.

## Frozen candidate and accounting identity

- Candidate: `donchian-logistic-meta-label-v1` / `DonchianLogisticProspectiveStrategy`.
- Exchange/instrument: OKX `BTC/USDT:USDT` USDT perpetual only.
- Timeframe: `5m`.
- Directions: long and short.
- Margin and leverage: isolated, exactly `14x` for every position. A requested, admitted, or
  recorded trade at any other leverage is `INVALID`, not a lower-risk substitute.
- Starting wallet: exactly `1000 USDT` at effective `R`.
- Capacity: `max_open_trades=1`, stake `unlimited`, `tradable_balance_ratio=1.0`, no
  `available_capital`, no position stacking, and no position adjustment.
- Wallet policy: all-wallet compounding within one continuous ledger per fee scenario.

There are three frozen fee scenarios:

| Scenario | Fee input per side | Meaning | Decision role |
|---|---:|---|---|
| baseline | `0.0006` | `0.0005` (5 bp) OKX public-base taker proxy plus `0.0001` (1 bp) cash-slippage proxy | Gate |
| stress | `0.0010` | Combined conservative fee/slippage stress | Survival Gate |
| severe | `0.0015` | Combined severe diagnostic | Report only |

The baseline composition is a preregistered accounting proxy. It is not a claim that the exchange
alone charges 6 bp, nor is it a credentialed-account fee-tier assertion. Freqtrade's fee input
receives the combined proxy. The three scenarios cannot be substituted, averaged, or selected
after observing results.

## One continuous wallet and checkpoint semantics

Each fee scenario owns one continuous wallet, natural-trade ledger, open-position state, funding
state, and complete 5-minute marked-equity path beginning at effective `R` with `1000 USDT`.
Nothing resets at an intermediate checkpoint.

The fixed elapsed checkpoints are:

| Endpoint | Scheduled instant when `R=2026-08-14T00:00:00Z` | Role |
|---|---|---|
| `D7` | `2026-08-21T00:00:00Z` | Mandatory early report only |
| `D30` | `2026-09-13T00:00:00Z` | Primary hard Gate |
| `D90` | `2026-11-12T00:00:00Z` | Longer-horizon Gate |
| `D180` | `2027-02-10T00:00:00Z` | Longer-horizon Gate |
| `D365` | `2027-08-14T00:00:00Z` | Longer-horizon Gate |
| `RELEASE_TO_DATE` | Final-manifest precommit | Longer-horizon Gate at the precommitted instant |

At a checkpoint, a naturally open position remains open. It is marked using the last complete,
authoritative 5-minute candle available at or before the checkpoint, the frozen scenario's
hypothetical closing cost, and every exact funding settlement accrued through that time. Its
wallet, basis, side, amount, funding state, and strategy state continue unchanged after the
checkpoint.

Checkpoint `force_exit` is forbidden by this continuous-ledger contract. A Freqtrade terminal
`force_exit` from an independently ended run must not be called a natural strategy exit, injected
into the continuous ledger, or used as the next checkpoint's initial wallet. Independently run
rolling windows, terminal wallets, and returns must never be concatenated, added, or multiplied to
manufacture the continuous path.

## Authoritative input and self-recomputation boundary

The current evaluator has no artifact-reading or execution mode. This is intentional: V8 and the
final prospective materializer are not yet frozen, so accepting an ad hoc result or reported
equity number would create a false `PASS` path.

A future activation is valid only when a non-self-referential final manifest and an independently
supplied manifest digest bind a strict materializer contract with all of the following:

1. The exact standard Freqtrade result and engine receipt, including argv, exit code, UTC start and
   end, Freqtrade/container identity, stdout/stderr/result hashes, and zero unbound overrides.
2. The exact strategy, config, signal sidecar, complete V7/V8 prefixes, `5m` OHLCV, mark opens,
   funding settlements, and every materialized file hash consumed by the run.
3. Normalized trade rows that are derived from, and checked row-for-row against, the bound standard
   Freqtrade result. A handwritten metric summary or unbound copy of trade rows is insufficient.
4. Enough per-position fields to independently recompute the standard result: at minimum exact
   open/close times and rates, amount/stake, side, leverage, entry/exit fee inputs, natural exit
   reason, and funding contribution. Every row must use `14x` and carry funding evidence even when
   its actual contribution is zero.
5. One complete, unique, ordered 5-minute account path from effective `R`. For every row the
   materializer must independently recompute wallet and marked equity from the bound position
   state, exact price/mark input, scenario fee, and accrued exact funding. Supplied wallet/equity
   values are only cross-checks; they are never their own numerical authority.
6. A proof that no intermediate reset, deposit, withdrawal, rolling-result input, position stack,
   checkpoint liquidation, or result selection entered the path.

Until that schema and every required artifact are final-frozen, the tool must remain `NOT_READY`.
Adding a permissive reader later without first freezing and testing the derivation and identity
contract cannot activate evaluation.

Missing but not-yet-due evidence is `PENDING`. A due checkpoint whose otherwise valid authoritative
materialization is not complete is `NOT_READY`. Once a purported sealed artifact is supplied,
wrong schema, missing required fields, duplicate JSON keys, `NaN`/infinity, an unknown sentinel,
identity or hash mismatch, wrong fee, leverage other than `14`, funding fallback, missing funding
lineage, incomplete 5-minute path, unbound equity, or a checkpoint `force_exit` is `INVALID`.

## Decimal metric recomputation

All gate metrics are recomputed; Freqtrade's reported aggregate values are cross-checks only.
Binary floating-point inputs are not admitted to the normalized metric boundary. JSON number
lexemes or canonical decimal strings are converted directly to `Decimal`, and all values must be
finite.

Only trades naturally closed by the checkpoint enter closed-trade metrics. A position still open
at the checkpoint enters equity and drawdown but not win rate, payoff, profit factor, direction
counts, or closed-trade sample counts.

- Net return: `checkpoint_equity / 1000 - 1` from the continuous marked account path.
- Win rate: natural closed trades with `profit_abs > 0` divided by all natural closed trades.
  `profit_abs == 0` is a draw in the denominator and is not a win.
- Strict payoff: arithmetic mean of strictly positive `profit_ratio` divided by the absolute
  arithmetic mean of strictly negative `profit_ratio`.
- Profit factor: gross strictly positive `profit_abs` divided by the absolute gross strictly
  negative `profit_abs`.
- Maximum drawdown: maximum peak-to-subsequent-trough decline over every authoritative 5-minute
  marked-equity row from effective `R` through the checkpoint.
- Liquidations: count of natural closed rows whose exact exit reason is `liquidation`.
- Direction diagnostics: the same counts and metrics separately for long and short natural closes.
- Best-trade concentration: largest positive natural-close `profit_abs` divided by gross positive
  natural-close `profit_abs`.

With no natural closed trades, win rate, strict payoff, and profit factor are `N/A`. With no winner
or no loser, strict payoff is `N/A`. With positive gross profit and zero gross loss, profit factor
uses the explicit `+infinity` sentinel; with no positive gross profit and at least one loss it is
zero. With no positive gross profit, best-trade concentration is `N/A`. JSON `Infinity` is never an
accepted representation.

Any `N/A` required by a Gate yields `INSUFFICIENT`, never `PASS` or performance `FAIL`.

## Auxiliary robustness sufficiency

Each classified checkpoint/scenario must have all of the following before it can be sufficient:

- at least 30 natural closed trades;
- at least 5 natural closed long trades;
- at least 5 natural closed short trades;
- at least 1 winner; and
- at least 1 loser.

Failure is `INSUFFICIENT`. These are explicitly auxiliary robustness constraints added to prevent
a tiny or one-sided sample from satisfying ratios. They are not represented as the user's literal
performance threshold. They cannot turn a failing economic Gate into a pass.

## Performance and survival Gates

All comparisons below use exact Decimal values. `>=` boundaries are inclusive; `>` and `<`
boundaries are strict.

### D30 primary Gate

Baseline `0.0006` must satisfy every condition:

- net return `>= 100%`;
- win rate `>= 40%`;
- strict payoff `> 2.0`;
- profit factor `> 1.2`;
- maximum drawdown `< 25%`; and
- liquidation count `== 0`.

Stress `0.0010` must satisfy every survival condition:

- net return `> 0`;
- profit factor `> 1.0`;
- maximum drawdown `< 30%`; and
- liquidation count `== 0`.

Severe `0.0015` is mandatory report-only evidence. It cannot repair baseline or stress.

### D90, D180, D365, and release-to-date Gates

At each endpoint, baseline must satisfy:

- net return `> 0`;
- win rate `>= 40%`;
- strict payoff `> 2.0`;
- profit factor `> 1.2`;
- maximum drawdown `< 25%`; and
- liquidation count `== 0`.

Stress uses the same survival Gate as D30: net return `> 0`, profit factor `> 1.0`, maximum
drawdown `< 30%`, and zero liquidations. Severe remains report only. D7 is report only under all
three fee scenarios.

A later checkpoint, severe scenario, retrospective replay, different historical interval, or
alternative fee assumption cannot rescue a failed frozen Gate. No rolling checkpoint may be
searched to choose the best date. No parameter, model, threshold, feature, candidate rule, fee,
leverage, or data source may change in response to prospective performance.

## State machine

- `PENDING`: the fixed checkpoint time has not arrived.
- `NOT_READY`: the checkpoint is due but final freeze or complete authoritative inputs are not yet
  available, or the current plan-only evaluator cannot independently recompute them.
- `INVALID`: a supplied identity, schema, hash, timing, fee, leverage, funding, accounting,
  completeness, or continuous-state contract is violated.
- `INSUFFICIENT`: structurally valid and complete evidence lacks the auxiliary sample or a required
  defined metric.
- `FAIL`: valid, complete, sufficient evidence misses at least one applicable economic or survival
  threshold.
- `PASS`: valid, complete, sufficient evidence satisfies every applicable threshold; for D7 or
  severe, this means only that the mandatory report is structurally complete and sufficiently
  sampled, not that the scenario passed an economic Gate.

Identity/completeness states take precedence over metric interpretation. A malformed artifact is
not a strategy loss, and an incomplete artifact is not zero exposure, zero funding, or zero return.

## Current CLI and authorization boundary

The default invocation is:

```powershell
python tools/evaluate_donchian_logistic_prospective.py
```

It prints one deterministic JSON plan with `status=NOT_READY`. It performs no filesystem write,
network call, subprocess execution, backtest, or performance read. There is deliberately no
`--execute`, artifact ingestion, or reported-equity acceptance path in this revision.

The module's pure Decimal helpers freeze formula and boundary behavior for synthetic unit tests.
They may report whether mathematical thresholds are met, but deliberately cannot emit a `PASS`
acceptance status. Only a future fully bound, self-recomputing materializer path may combine those
formulas with authoritative artifacts and enter the state machine.

Even a future complete prospective `PASS` is research evidence only. It does not create a
StrategyRelease and does not authorize Paper, Live, exchange writes, capital allocation, or a
change to the candidate.
