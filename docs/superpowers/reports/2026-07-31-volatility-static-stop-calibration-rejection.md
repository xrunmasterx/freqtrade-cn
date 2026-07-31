# VolatilitySystem Static-Stop Calibration Rejection

**Status:** rejected at the preregistered calibration Gate; safety analysis and holdout
were not opened

**Decision date:** 2026-07-31

**Preregistered protocol:**
[VolatilitySystem Static-Stop Calibration](../plans/2026-07-31-volatility-static-stop-calibration.md)

## Decision

Reject the isolated `stoploss: -1 -> -0.10` candidate and preserve both tracked
`VolatilitySystem` copies unchanged.

The candidate passed the two sample-sufficiency Gates but failed all six performance
and risk Gates. It changed total profit from `+2.7856%` to `-0.6799%`, reduced profit
factor from `1.2762` to `0.9492`, made expectancy negative, increased account drawdown
from `3.7498%` to `6.2781%`, and missed the tail-loss allowance with a worst exported
trade of `-10.6359%`.

This is an early, fail-closed rejection. The preregistered formal API/FreqUI comparison
was completed on the calibration window and confirmed that the metric delta is eligible
for interpretation. Per the frozen protocol, Lookahead Analysis, Recursive Analysis,
the sealed holdout, alternate stop values, tracked strategy edits, Paper, and Live were
not authorized.

## Frozen implementation identity

The protocol was committed before the first calibration result at Root
`e064afc422cb06b25fa4ec120130155e03c89611`.

| Component | Executed identity |
|---|---|
| Root | `e064afc422cb06b25fa4ec120130155e03c89611` |
| Backend | `3209d437450fd1cc72903d9cc5ae8225bd7f8fb6` |
| Frontend | `515b00cccb882c3f304bab18d0eb5520f934901e` |
| Strategies | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` |
| Imported engine | `2026.7-dev-3209d4374` from the recorded backend worktree |
| Formal comparison image | `freqtrade-cn:static-stop-formal-e064afc` |
| Formal comparison image identity | `sha256:29112df64b4d66c41e51b1a1bdd4dfd01cec4201c4dc4e1772f549b07f970948` |
| Isolated formal comparison origin | `http://127.0.0.1:18085` |
| Both tracked strategy files | SHA-256 `FED33ECEED8BEC65F5C47D1727AA4A18B70F15D064B20000EB653622BB16FE85` |
| Candidate overlay | one property, `{"stoploss": -0.10}`; SHA-256 `EE71893A7F8BCFF1EDA9B93A3ED071DAB9370FD126F42DB9C60C84FC2A1ABDE3` |

Both Backtest ZIPs embed the same strategy-source hash shown above. The archived input
configuration differs at top level only in `config_files` and the candidate's added
`stoploss = -0.10`. Its example file retains broader defaults, so it is not the
authority for CLI overrides. The result payload records the effective simulation
inputs: one `BTC/USDT:USDT` pair, `1h`, 100 USDT stake, 1,000 USDT starting wallet, one
maximum open trade, OKX isolated Futures, protections off, no FreqAI model, and fee
ratio `0.0005` on every exported fill.

## Input and artifact evidence

The coverage-only preflight found 22,071 continuous one-hour Futures rows and 22,071
continuous one-hour mark rows from `2024-01-01 00:00 UTC` through
`2026-07-08 14:00 UTC`. Funding contained 2,214 continuous native eight-hour rows from
`2024-06-30 16:00 UTC` through `2026-07-08 08:00 UTC`. Each frozen one-year request had
8,760 primary and mark rows and 1,095 funding rows before causal warmup handling.

| Temporary input | SHA-256 |
|---|---|
| `BTC_USDT_USDT-1h-futures.feather` | `FDA58D314CBCACD8605D5B4996030B9FB73EB2544ED35B9EF64FFECA6A252369` |
| `BTC_USDT_USDT-1h-mark.feather` | `6E4A742F05A36DF2A0894583463AE7904C56596D824AC5A7C444BE7DBCE9C86F` |
| `BTC_USDT_USDT-1h-funding_rate.feather` | `2A49B31FC35BE0E3A26F4199FD773998A811AE19DD9E82A181C2FBFDF1C8FE94` |
| `leverage_tiers_USDT.json` | `C846F26C1ED0745F14374E90A3AC6C8415C0E228CB9D7C2B62B0B2C0DD01B062` |

| Temporary CLI result | ZIP SHA-256 | Metadata SHA-256 |
|---|---|---|
| Baseline `backtest-result-2026-07-31_20-03-22.zip` | `1BC1B275E45843E43A760EBE2047139209D566206442A133811920CB7EDC4CC6` | `EC2F9C20454A73F431DEAF2716C05DBC27C9D7DAD761EF00D4494EA4BDFC4BBD` |
| Candidate `backtest-result-2026-07-31_20-03-59.zip` | `CB04D0E07BE46C028A20DAF3EB80EE04E0F5BBAF56088C64FE9CE85501D2A61F` | `E3F95B0816E2B0FF733F2721E19C9C1FAEB86CB93BCAFF75C354C3309DBEA5F5` |

The first baseline invocation pointed Freqtrade at the parent of the copied OKX data
directory. It stopped before producing performance metrics and only refreshed a
temporary leverage-tier cache. The infrastructure-only rerun corrected the data path
from the temporary parent to its `okx` child without changing the frozen semantic
inputs, source, candidate, thresholds, or window.

The result ZIPs were evidence inputs for this report, not repository artifacts. Their
names and hashes are retained above so the report states exactly what was inspected;
the files are deleted during the required temporary-workspace cleanup.

## Formal API and FreqUI comparison receipt

The baseline API run retained its exact DataSnapshot in the Backtest ZIP. The candidate
service used the same image and source with only the isolated `stoploss = -0.10`
service-level overlay, then replayed the baseline ZIP rather than reading current market
files. This matches the preregistered boundary: stoploss is a resolved strategy setting,
not a `BacktestRequest` field.

| Role | API artifact | Revision | Strategy Evidence | ZIP SHA-256 | Metadata SHA-256 |
|---|---|---|---|---|---|
| Baseline | `backtest-result-2026-07-31_12-40-45_255537-5ae2ea18eccc4c64a298c7b505d20c98` | `experiment-revision-5950b1a102c11ef86e9a5c2ae71169ecfc74f43ae8676cd064f4ba90cf359f3b` | `strategy-evidence-4a71648327f30d328b10d1f85c1b5639191060f2b87d29b252f4d40c7ad61b30` | `640303020B7B59B0CC1708F1E2118689B6A2C0A54F157446ADC00E56F46B11DA` | `CF05018897DD1FF8F78E7D43A8CA1ECC402E1571D4D4D27E8FE232D940C6B450` |
| Candidate | `backtest-result-2026-07-31_12-42-01_965899-af86e2b3d590491295a517f0b6abfe54` | `experiment-revision-15784000062120e15e0c479b5850944bd7371a27758c788e38b68691f4860439` | `strategy-evidence-295b6bac0a278c10af71dbdaec2c6f6ba02535941772ef0252fbee0dba6735a5` | `88BAEDBED12298CD67516A305FC608930C864769747917AF2B143E43EBDAC7FD` | `5391E16858AA205BF4DC3FBA92A9F4B2B05D932773227E4714D6F02A4A20980A` |

Both results bind:

- DataSnapshot
  `data-snapshot-402c17d4c14e1333e39a58c67c75d615e266b4dcec28856fe4453d49e803a980`,
  containing 19,117 canonical rows across Futures, mark, and funding-rate series;
- Execution Context Evidence
  `execution-context-evidence-7e8386e1c34c301e843e04eb1688ed290a355b71b3836aabee7202cb2e3e7e67`,
  including identical core-runtime, effective-config, and admitted-pair exchange
  simulation component identities;
- exact scored endpoints `2024-07-01 00:00 UTC` and `2025-07-01 00:00 UTC`.

Their valid Strategy Evidence identities differ because the resolved stoploss differs.
The candidate receipt names the baseline artifact as its replay source and contains no
retained-row payload of its own. Its Backtest metrics exactly reproduce the independent
CLI candidate metrics below; the baseline API metrics likewise reproduce the CLI
baseline.

The real FreqUI loaded both API history rows and rendered:

- `SAME-WINDOW STRATEGY CHANGE`;
- the same standard offline market-data identity;
- different strategy-evidence identities;
- `SAME CAPTURED SCOPE` for core runtime, effective simulation configuration, and
  admitted-pair exchange simulation.

The visually inspected comparison screenshot had SHA-256
`25BD9DE5C95E55D201D88A2CF99938AC7DB7DB469672882D0D440BD07B187FB5`.
It and the formal Backtest artifacts were temporary evidence rather than repository
assets. They were removed during pre-commit cleanup after the independent Gate verified
their hashes and visible classification. The same Gate found that the first draft had
incorrectly called this preregistered comparison skipped; the comparison above closed
that P1 before the report was committed. It did not open safety analysis, the holdout,
another parameter, or another historical window.

## Calibration result

Both runs scored the exact engine-reported interval `2024-07-01 00:00 UTC` through
`2025-07-01 00:00 UTC` with timerange `20240701-20250701`.

| Metric | Baseline `stoploss = -1` | Candidate `stoploss = -0.10` | Candidate delta |
|---|---:|---:|---:|
| Closed trades | 30 | 40 | +10 |
| Long / short trades | 15 / 15 | 15 / 25 | 0 / +10 |
| Total profit | +2.7856% / +27.8565 USDT | -0.6799% / -6.7992 USDT | -3.4656 percentage points |
| Wins / losses / win rate | 12 / 18 / 40.0% | 11 / 29 / 27.5% | -12.5 percentage points |
| Profit factor | 1.2762 | 0.9492 | -0.3270 |
| Expectancy | +0.9285 USDT | -0.1700 USDT | -1.0985 USDT |
| Account max drawdown | 3.7498% / 39.8343 USDT | 6.2781% / 66.1557 USDT | +2.5283 percentage points |
| Worst exported trade | -17.2756% | -10.6359% | +6.6398 percentage points |
| Market change | +70.5365% | +70.5365% | 0 |

The exported trade arrays contained exactly the declared trade counts. All required
metrics and every `trades[*].profit_ratio` were present, numeric, and finite. Each run
included one `force_exit` trade at `-1.4874%`; no exit reason was filtered from the Gate.

## Preregistered Gate evaluation

| Gate | Required | Observed | Result |
|---|---|---|---|
| Closed trades | both `>= 20` | baseline 30; candidate 40 | PASS |
| Direction coverage | both long `>= 5` and short `>= 5` | baseline 15/15; candidate 15/25 | PASS |
| Candidate total profit | `> 0` | `-0.00679922094` | **FAIL** |
| Improvement | candidate minus baseline `>= 0.01` | `-0.03465571611` | **FAIL** |
| Profit factor | `>= 1.10` | `0.9491866702` | **FAIL** |
| Expectancy | `> 0` | `-0.1699805235` USDT | **FAIL** |
| Account drawdown | candidate `< 0.10` and `<=` baseline | `0.0627813064`, versus baseline `0.0374982164` | **FAIL** |
| Tail-loss mechanism | minimum exported trade `>= -0.105` | `-0.1063585715` | **FAIL** |

The decision is therefore `REJECTED`, not `INSUFFICIENT` and not `INVALID`.

## What the failure says about the mechanism

The stop did reduce the magnitude of the single worst trade, but that local improvement
did not make the strategy safer as a system:

- the candidate produced 15 ordinary `stop_loss` exits and four engine-labelled
  `trailing_stop_loss` exits, even though the configured strategy has
  `trailing_stop = false`;
- all 30 baseline entry timestamps also appeared in the candidate, while the candidate
  added ten new entry timestamps; the earlier stop exits released the sole trade slot
  and changed which later persistent signals could be entered;
- five stop exits were followed by another candidate entry within three hours and seven
  within 24 hours;
- all four `trailing_stop_loss` trades had two entry fills. After an additional fill,
  Freqtrade recalculated the average open rate and called `adjust_stop_loss`; when the
  resulting static stop was tighter in the favorable direction, the engine marked the
  stop as trailing because it differed from the initial stop. It never loosened the
  stop. The label does not mean strategy-level trailing was enabled;
- fees, funding, candle execution, and the adjusted-position path allowed the candidate
  worst net trade to reach `-10.6359%`, beyond the preregistered `-10.5%` allowance.

The first-principles lesson is that a stop is not an isolated loss clamp when the entry
condition can remain or become actionable again and only one position may be open. It
changes position occupancy, subsequent entries, direction mix, fees, and the full trade
path. The next hypothesis must model re-arming and adjusted-position risk together; a
tighter or wider number alone is not a justified follow-up.

## Closed boundary

- The sealed `20250702-20260702` holdout was not executed or inspected by this study.
- Lookahead and Recursive Analysis were skipped because the metric Gates failed first.
- The isolated API/FreqUI comparison used only the calibration window and was stopped
  after the positive identity receipt; no Paper runtime, exchange write, or real-money
  operation was started.
- No alternate stop, parameter sweep, post-hoc subperiod, direction rescue, or strategy
  source edit was attempted.
- The accepted 499-candle startup repair and both tracked `stoploss = -1` strategy copies
  remain the repository baseline.
- Temporary data, configuration overlays, result ZIPs, and delegated audit workspaces
  were removed before this report was committed; only their identities, hashes, and
  findings remain in this report.

The viewed calibration interval is now development evidence for future research and
must not be represented as fresh validation. The untouched holdout remains sealed, but
no new candidate is active. A distinct follow-up requires a new preregistration before
performance execution and must state honestly how the already-viewed development
evidence informed it.

## Evidence limits

This rejection covers one strategy, one pair, one timeframe, one venue configuration,
one fixed stop value, and one historical calibration interval. It falsifies this
candidate under the frozen protocol; it does not prove that the baseline is profitable,
that another risk policy will work, that the holdout would fail, or that future returns
will resemble this Backtest. No result here is a profit guarantee or authorization for
Paper or Live trading.
