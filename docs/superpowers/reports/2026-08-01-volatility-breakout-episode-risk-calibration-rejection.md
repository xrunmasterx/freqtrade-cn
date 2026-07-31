# VolatilitySystem Breakout-Episode Risk Calibration Rejection

**Status:** rejected at the preregistered pre-performance signal-parity Gate; B/S/C
performance, safety analysis, holdout, Paper, and Live were not opened

**Decision date:** 2026-08-01

**Preregistered protocol:**
[VolatilitySystem Breakout-Episode Risk Calibration](../plans/2026-07-31-volatility-breakout-episode-risk-calibration.md)

## Decision

Reject the isolated breakout-episode candidate and preserve both tracked
`VolatilitySystem` copies unchanged.

The candidate passed its frozen mechanism tests, Backtest execution-semantics tests,
actual 599-candle cold and immediate-warm profiles, 600- and 799-candle profiles, and
first-finite-row restart-boundary check. It nevertheless failed the mandatory offline
499-candle signal-parity profile. The calibrated all-row checker identified three rows
with five differing signal fields across 8,760 scored development rows. A direct rerun
through the imported candidate source, independent of that accelerated checker,
reproduced all three differences.

The protocol classifies any exact 499/cold/warm/longer signal-parity miss as
`REJECTED`. This is not `INVALID`: the frozen source and inputs were verified, the
candidate implementation matched the preregistered semantics, and the failing rows were
confirmed with the real candidate code. It is not `INSUFFICIENT`: the failure occurred
before observation-count floors became applicable. Per the stop rule, no B/S/C
performance command was run under this protocol and no current-study performance result
was produced or inspected.

## Frozen implementation and environment identity

The protocol was committed before candidate performance at Root
`9cb5678d0138e913bc01eaf062006896254e3569`.

| Component | Executed identity |
|---|---|
| Root | `9cb5678d0138e913bc01eaf062006896254e3569` |
| Backend | `3209d437450fd1cc72903d9cc5ae8225bd7f8fb6` |
| Frontend | `515b00cccb882c3f304bab18d0eb5520f934901e` |
| Strategies | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` |
| Both unchanged tracked strategies | SHA-256 `FED33ECEED8BEC65F5C47D1727AA4A18B70F15D064B20000EB653622BB16FE85` |
| Temporary candidate C | SHA-256 `344328D394312778B4B658AFFC16066A3BDC872EDED9F477E0FABFF1E2139F84` |
| Immutable research image | `sha256:66bb9cf0bf865b4920d0c44077cf382c437185524f1e1b165aa0a889af74319e` |
| Runtime versions | Python `3.14.6`; Freqtrade `2026.7-dev`; CCXT `4.5.61`; TA-Lib `0.6.8`; technical `1.6.0` |

Candidate C contained exactly the frozen lifecycle policy:

- unchanged three-hour `close_change` and shifted ATR raw predicates;
- finite current-and-previous false-to-true entry edges;
- unchanged persistent opposite-side exits;
- `stoploss = -0.10`;
- unchanged half proposed stake and 2x leverage;
- disabled position adjustment, with only its now-orphaned implementation and imports
  removed.

It remained a development-only Backtest candidate. The execution tests below also
confirmed that the one-row opposite entry edge is not equivalent under the current
ten-minute GTC limit Paper policy, so even a signal-parity pass would not by itself have
authorized Paper.

## Input identity and evidence boundary

Only rows strictly before `2025-07-01 00:00 UTC` were admitted before candidate import.
The authorized primary frame contained 13,128 contiguous one-hour rows from
`2024-01-01 00:00 UTC` through `2025-06-30 23:00 UTC`; the scored development interval
contained 8,760 rows from `2024-07-01 00:00 UTC` through the exclusive
`2025-07-01 00:00 UTC` endpoint.

| Input | SHA-256 |
|---|---|
| Futures one-hour data | `FDA58D314CBCACD8605D5B4996030B9FB73EB2544ED35B9EF64FFECA6A252369` |
| Mark one-hour data | `6E4A742F05A36DF2A0894583463AE7904C56596D824AC5A7C444BE7DBCE9C86F` |
| Funding-rate data | `2A49B31FC35BE0E3A26F4199FD773998A811AE19DD9E82A181C2FBFDF1C8FE94` |
| OKX leverage tiers | `FBFB3A0B96CD713A4050A8393C912A114634F953C69CC56440623F457BA2016E` |

The public OKX loader probe returned 599 primary candles on a cold load and 599 on the
immediate warmed-cache load. The exchange per-call limit was 300 and the loader used two
calls. The frozen study still required the explicit 499 offline minimum, synthetic 600
cap, and mature admitted 799 cap because `startup_candle_count = 499` is part of the
accepted strategy contract and startup behavior cannot depend silently on incidental
extra exchange rows.

The source Feather files are known to contain later dates and their bytes had already
been coverage-scanned in the preceding study. In this study, no row at or after the
development endpoint was selected for candidate indicators or signals. No holdout
strategy output, trade, performance result, or metric was produced or inspected.

## Pre-performance implementation evidence

All evidence stayed outside tracked repository paths until this report was written.

| Evidence | Result | SHA-256 |
|---|---|---|
| Frozen candidate source | exact frozen semantics | `344328D394312778B4B658AFFC16066A3BDC872EDED9F477E0FABFF1E2139F84` |
| Mechanism harness | baseline RED exited 1 with 19 expected contract failures; candidate GREEN passed 8/8 | `E79A6F61A49C5E59F5969D3FF169EBD1647CFF9661EC9DB2E08524F530E4FCC0` |
| Harness contract | frozen mechanism description | `F8D560CD291D48370B6032962A0F6F2B29C32F4DA54F5C8DA2C047459EAC14D3` |
| Candidate execution-semantics tests | 3/3 passed | `FFA60360E2336FF8A7B3FA3BBEF31EB4C0DC85E6853DBCCCEE1804A37DBC6C0A` |
| Prefix-parity checker | exact-image run described below | `0B80307339ECA4D267F560861A9C8C29B96EF50C20391AF78DE6BB0ECB05E360` |
| Prefix-parity tests | combined exact-image suite passed 19/19 | `4708E74EB349CFECE446FCEA87424283BF91E2114564B70CD6583F3997768587` |
| Direct 499-row mismatch confirmation | all three identified rows reproduced through imported candidate | `67782CA133D735FC389ED9C4E6727E1048363C627BCDEB2F11BC5B5B86970B3E` |
| Timestamp-unit diagnostic | isolated the invalid Pandas 3 microsecond/nanosecond tooling defect | `15DDFC33C787E43EEB45E07A0B207AA72700D3465A4124E53EF6B34D84716D1D` |
| Opportunity-ledger implementation | compiled; tests passed while performance remained sealed | `810A00552AF5F850B5A094439677C49D1047C824B9B2452CBE01A4EB584D6F6A` |
| Opportunity-ledger tests | included in the same 19/19 suite | `0ECB72E9E0091C75B12BDD9EBB0C3B812311974D137E8EF1083B9F7BCFBC0E93` |

The three candidate-specific engine tests proved the bounded execution semantics rather
than assuming Backtest and Paper equivalence:

1. an immediate-fill opposite edge reverses at the same Backtest timestamp;
2. an unfilled old-side GTC limit exit consumes the one-shot opposite edge, then may
   fill later without reversing;
3. an empty entry timeout has no automatic strategy retry; only a later distinct edge
   can enter.

The existing focused Futures immediate-reversal engine test also passed 1/1. These facts
would have been ledger inputs after a parity pass; they did not authorize bypassing the
failed 499 profile.

## Exact signal-parity result

The accelerated all-row evaluator was not trusted without calibration. It first compared
136 deterministic real frames—34 positions for each distinct 499, 599, 600, and 799
length—against the imported candidate and found zero differing fields. It then scanned
all 8,760 scored rows for every frozen profile. A Pandas 3 microsecond-versus-nanosecond
timestamp defect found in the first tooling attempt was fixed and locked by a regression
test. A second invalid attempt completed the window scans but stopped because its
boundary probe supplied too few rows for the upstream resampler to infer an interval;
the probe was changed to require six contiguous one-hour rows and covered by another
regression test. Both tooling failures occurred before this valid classification and
produced no signal file or performance output.

| Profile | Frame length | Scored rows | Differing rows / fields | Result |
|---|---:|---:|---:|---|
| Offline minimum | 499 | 8,760 | 3 / 5 | **FAIL** |
| Actual OKX cold return | 599 | 8,760 | 0 / 0 | PASS |
| Actual immediate warm return | 599 | 8,760 | 0 / 0 | PASS |
| Synthetic cold cap | 600 | 8,760 | 0 / 0 | PASS |
| Mature admitted cap | 799 | 8,760 | 0 / 0 | PASS |

The first-finite-row boundary stress selected a slice beginning
`2024-06-29 05:00 UTC`, made `2024-07-01 00:00 UTC` the first finite scored row, armed
neither side on that boundary-unknown row, and matched all eight fields across the later
8,759 development rows.

The 499 profile differed at exactly these timestamps:

| UTC signal row | Differing fields | Complete-history result | Rolling 499 result |
|---|---|---|---|
| `2025-02-21 18:00` | `short_eligible`, `exit_long` | false, false | true, true |
| `2025-02-21 19:00` | `short_eligible`, `exit_long` | false, false | true, true |
| `2025-02-21 20:00` | `enter_short` | true | false |

All three rows were subsequently recomputed directly through the imported candidate,
not the accelerated evaluator, and reproduced the same differences. At 18:00 and 19:00,
the absolute close change was `1826.199999999997`. Complete history produced a shifted
ATR threshold of `1826.2027252906303`, so the strict short predicate was false. The
rolling 499 frame produced `1826.1996289095964`, so the same strict predicate was true.
At 20:00, the new absolute close change was `1944.5999999999913`. Complete history saw a
false-to-true transition and armed `enter_short`; the rolling frame had already become
true two rows earlier and therefore correctly emitted no new edge under its own history.
The rejection requires only one exact confirmed miss; it does not depend on treating the
calibrated all-row checker's three-row count as proof that no additional mismatch could
exist.

## What the failure says about the design

ATR uses Wilder-style recursive smoothing. A finite window changes its seed and, when
the window begins inside a three-hour bucket, the first resampled candle. Usually that
small residual decays without affecting a decision. Here the raw move sat between the
two ATR values by less than four thousandths of a price unit. The strategy uses a strict
boolean comparison, so a tiny continuous indicator difference became a discrete exit
and entry-lifecycle difference.

The candidate's purpose was to make one observable breakout episode correspond to one
entry opportunity. That contract is only meaningful if every supported startup context
agrees on where the episode begins. On these rows, complete history says the short
episode begins at 20:00 while the 499 frame says it began at 18:00. The entry edge is
therefore not restart-stable at the strategy's declared minimum. Passing the incidental
599-row OKX response does not repair the violated 499 contract, and increasing warmup
after seeing this row would be the exact post-hoc rescue forbidden by the protocol.

The next healthy hypothesis must be preregistered independently. It should address the
source-of-truth boundary directly—for example, a genuinely bounded indicator whose
value is defined only by an explicit finite horizon, or a separately justified product
decision that changes the supported startup contract. It should not rescue this study
with another stop, tolerance around the threshold, longer warmup, delayed pulse,
parameter search, side selection, or the already-viewed failing timestamp.

## Closed boundary

- B, S, and C Backtests were never started under this protocol; no profit, trade,
  drawdown, or risk metric exists for this candidate.
- The development opportunity ledger was implemented and tested but never applied to a
  result because parity failed first.
- Lookahead Analysis, Recursive Analysis, formal API/FreqUI comparison, and the sealed
  `20250702-20260702` holdout were not opened.
- No alternate candidate, warmup, threshold, stop, position size, pair, timeframe, or
  subperiod was tried after the failure became visible.
- Neither tracked strategy was edited. Backend and frontend code were not edited.
- Temporary candidate code, tests, diagnostics, and services were removed before the
  documentation commit; only their hashes and bounded findings remain here.
- No Runtime, Paper, exchange write, or real-money operation was started.

The accepted repository baseline therefore remains the two byte-identical
`stoploss = -1` strategy copies with `startup_candle_count = 499`. No strategy candidate
is active after this rejection. A later study must begin with a new first-principles
question and a new preregistration before any already-viewed development performance is
run again.

## Evidence limits

This report falsifies one exact finite-edge lifecycle candidate under one pair, one-hour
timeframe, three-hour indicator construction, venue configuration, startup contract, and
already-viewed development interval. It does not establish that the baseline is
profitable, that a bounded-indicator variant would pass, that the untouched holdout
would pass or fail, or that future returns will resemble any Backtest. It is not a
profit claim or authorization for Paper or Live trading.
