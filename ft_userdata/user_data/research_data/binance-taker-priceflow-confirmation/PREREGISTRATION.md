# Binance Taker PriceFlow Cross-Market Confirmation — Preregistration

Status: **FROZEN BEFORE ANY PERFORMANCE READ**
Scope: **research-only; BTC/USDT:USDT; no Paper or Live authorization**

## 1. Single research question

Test one, and only one, cross-market confirmation rule on the tracked
`PriceFlowContinuationStrategy` signal. No parameter family, search, CUSUM, open interest,
Deribit/options input, leverage experiment, or alternative rule is authorized.

The inherited PriceFlow entry, exit, ROI, stop, and protection semantics are unchanged except
for the final entry confirmation below and the explicit 1x leverage override.

For every 15m strategy candle:

- final long = original PriceFlow long AND `relative_volume >= 0.80` AND
  (`directional_price_accept_long` OR valid lagged Binance taker improvement long);
- final short = original PriceFlow short AND `relative_volume >= 0.80` AND
  (`directional_price_accept_short` OR valid lagged Binance taker improvement short).

Directional price acceptance is frozen as:

- long: `close_location >= 0.35`, `body_atr >= 0.30`, and `close > previous high`;
- short: `close_location <= -0.35`, `body_atr >= 0.30`, and `close < previous low`.

Binance taker imbalance is `2 * taker_buy_base_volume / total_base_volume - 1`. A complete
15m bucket has exactly three 5m constituents. Its approximately ten-minute improvement is
the last constituent imbalance compared with the first constituent imbalance:

- long improvement: last 5m imbalance >= first 5m imbalance;
- short improvement: last 5m imbalance <= first 5m imbalance.

The first and last constituents are ten minutes apart. The complete Binance 15m bucket is
then delayed by one additional 15m strategy candle. The sidecar contract requires:

- `date == source_complete_time`;
- `source_complete_time == bucket_open + 15m`;
- `decision_time == date + 15m`;
- `publication_lag_minutes == 15`;
- `constituent_5m_count == 3`;
- timestamps strictly ordered and unique;
- both the sidecar decision timestamp and the base strategy decision timestamp `< 2025-01-01`.

Missing or contradictory sidecar evidence fails closed. Price acceptance remains the only
alternative to a valid lagged taker improvement.

## 2. Frozen execution semantics

- Pair: `BTC/USDT:USDT` on OKX USDT perpetual futures.
- Strategy timeframe: 15m.
- Detail timeframe: 5m.
- Leverage: exactly 1x for every trade; no leverage run is authorized.
- Fee: 0.0006 per side.
- Max open trades: 1.
- Margin mode: isolated.
- Starting dry-run wallet: 1,000 USDT; unlimited stake within that single-position account.
- Funding: actual retained OKX settlement events from the official monthly swap-rate archives.
- Fixed funding fallback: `0.0000042304172276700455` per 1h mark row, the historical 8h
  mean divided by eight. Under the pinned Freqtrade semantics this is a leading-gap fallback;
  actual retained events are used where present.
- Leverage-tier snapshot: the isolated dataset contains a byte-for-byte copy of the existing
  public OKX cache from
  `ft_userdata/runtime/freqtrade-futures/data/okx/futures/leverage_tiers_USDT.json`, whose
  embedded `updated` value is `2026-08-12 10:33:49.153543+00:00`. It contains the BTC pair and
  99 BTC tiers. The frozen first tier is: tier 1, currency USDT, min/max notional 0/1000,
  maintenance margin rate 0.004, and max leverage 100. This is a current 2026-08-12 constraint
  snapshot applied to a historical backtest, not a time-matched historical tier series. Even
  though the strategy is fixed at 1x with a 1,000 USDT starting wallet, Freqtrade futures
  requires this input, so its exact bytes and first-tier contract are bound and verified.
- Freqtrade: `2026.7-dev-b1121f895`, backend commit
  `b1121f89512f6af1a99b4d3929d4405093363c99`.
- The runner removes every `FREQTRADE__*` environment override before each subprocess. OKX
  markets and precision metadata are nevertheless loaded from the current public OKX API at
  runtime; this is a limitation of the present environment and is disclosed in each stage
  receipt. Frozen files, including the leverage-tier snapshot, are reverified after each
  backtest subprocess returns and before any result metrics are read or accepted.
- Root working commit at freeze: `891d1be2552de994329aaaeea4f174a85bde579e`.
  Exact file hashes below, rather than the dirty working-tree commit alone, are authoritative.

## 3. Frozen datasets

### Binance confirmation source

Source: official Binance Vision monthly USD-M perpetual klines,
`https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/5m/`, symbol
`BTCUSDT`, months 2022-02 through 2024-12. Each of the 35 archives was checked against its
official `.CHECKSUM`; the per-archive URLs and SHA-256 values are frozen in the Binance data
manifest.

- Canonical 5m rows: 306,720.
- First/last open: 2022-02-01 00:00Z / 2024-12-31 23:55Z.
- Missing timestamps: 0; duplicate timestamp rows: 0; unexpected timestamps: 0.
- Required source fields include total base volume and taker-buy base volume.
- Lagged complete-15m sidecar rows: 102,238; no sidecar date or decision time is in 2025+.

### OKX execution and funding source

Execution candles and mark candles came from the official OKX history-candles API through
CCXT/Freqtrade. Funding came only from the 35 official monthly `BTC-USDT-SWAP` funding-rate
archives for 2022-02 through 2024-12.

The final frozen candle inputs are continuous, unique, and contain zero rows at or after
2025-01-01:

| Series | Rows | Final first UTC | Final last UTC |
|---|---:|---|---|
| 5m futures | 306,720 | 2022-02-01 00:00 | 2024-12-31 23:55 |
| 15m futures | 102,240 | 2022-02-01 00:00 | 2024-12-31 23:45 |
| 1h futures | 25,560 | 2022-02-01 00:00 | 2024-12-31 23:00 |
| 4h futures | 6,390 | 2022-02-01 00:00 | 2024-12-31 20:00 |
| 1h mark | 25,560 | 2022-02-01 00:00 | 2024-12-31 23:00 |

The frozen funding file has 3,193 actual normalized event rows; its exact source-event range
is 2022-02-01 00:00Z through 2024-12-31 08:00Z.

### Mandatory 2025 exposure disclosure

The exact-range OKX downloader over-fetched its final page(s), and the finalizer read the
timestamp ranges and removed all rows at or after 2025-01-01 before any strategy indicator or
performance execution. It observed and discarded: 179 5m rows through 2025-01-01 14:50Z; 59
15m rows through 2025-01-01 14:30Z; 239 1h futures rows through 2025-01-10 22:00Z; 209 4h
rows through 2025-02-04 16:00Z; and 39 1h mark rows through 2025-01-02 14:00Z.

Therefore the final inputs contain zero 2025+ rows, but 2025 cannot be claimed as a sealed or
fresh holdout. The authorized 2024 stage below is explicitly a **preregistered retrospective
validation**, not a fresh holdout. No 2025+ performance run is authorized.

## 4. Frozen performance sequence and gates

1. Run development exactly once with logical trade-open window
   `[2022-03-01, 2024-01-01)`. Because the pinned Freqtrade Feather filter and dataframe
   trimmer treat the stop as inclusive, its raw 15m candle timerange is frozen as
   `1646092800-1704066300`: 2022-03-01 00:00Z through 2023-12-31 23:45Z inclusive.
2. Apply all frozen gates below with AND semantics.
3. If any development gate fails, write `DEVELOPMENT_REJECTED`, record that 2024 was not
   opened, and stop immediately.
4. Only if every development gate passes, write a freeze receipt and run the 2024
   retrospective validation exactly once, with logical trade-open window
   `[2024-01-01, 2025-01-01)`. Its raw inclusive 15m candle timerange is frozen as
   `1704067200-1735687800`: 2024-01-01 00:00Z through 2024-12-31 23:30Z inclusive.
   The last allowed open is therefore 23:30Z, and its
   `decision_time = candle_open + 15m` is 23:45Z, strictly before 2025-01-01 00:00Z.
5. Apply the identical gate set to 2024 and terminate as `VALIDATION_PASSED` or
   `VALIDATION_REJECTED`. Either status remains research-only and does not authorize Paper or
   Live trading.

The identical frozen gate set for development and 2024 is:

- trades >= 30;
- win rate >= 40%;
- strict payoff >= 2.0;
- profit factor > 1.2;
- absolute net profit > 0;
- maximum account drawdown < 25%;
- liquidation count == 0.

Strict payoff is the arithmetic mean of positive per-trade `profit_ratio` divided by the
absolute arithmetic mean of negative per-trade `profit_ratio`; both winners and losers must
exist. Profit factor is gross positive `profit_abs` divided by absolute gross negative
`profit_abs`; both positive and negative gross amounts must exist. These two measures must not
be conflated.

## 5. Frozen byte identities

| Artifact | SHA-256 |
|---|---|
| `PriceFlowContinuationStrategy.py` | `ed1bcbb8cb342826b71fc4ea456b6905e5bd9f91341e6da2029f4d3511ef2f8d` |
| `PriceFlowBinanceTakerConfirmationResearchStrategy.py` | `fd9a29132bca1e9157b37acfa0fd3950eb87aeb4e6ca3250c6e9889f94b1bad9` |
| focused strategy test | `9f37a54532f9bdd6d88039a6c75f89ccd58a062a3d481ff8bb5c1bb119e31e21` |
| `research-config.json` | `8d6b2c4f64dd0c51a77c3a38b181a7f7819a449f0df5c376780491d002a49a74` |
| research runner | `4d38bb01bd839e0f99ce6ae4374e8fe1866019bed200aff796567808d4b32991` |
| Binance preparation tool | `46ab9bcbdec60620a9173a651e31fcef2c995810f8fab228a4568c9fde0d829f` |
| OKX finalization tool | `ab8c3f59c74104f29dba8240b78fd5a8da412841462654214973a63524a3bb97` |
| Binance data manifest | `4f2ba86b00e35a151d4c40795ed4140032f33c96df971b21fe91252319ebdb34` |
| Binance canonical 5m Feather | `93caab0c79d2720ff6211e2f8909bbf66c307cc23eb6f85d4e3ac3c0543ca385` |
| Binance lagged 15m sidecar Feather | `c34af1b33798369e747c2349d17258a285632f17e6baef14626a323c19f8873f` |
| OKX data manifest | `d28f954814ed616caea319e7e93ba67833586cd95d566818d91923142f4970c2` |
| OKX 5m futures Feather | `20a5167ff276c28226bc6e85a5ffea91f7dab67ad191626967cc6c6254f77da9` |
| OKX 15m futures Feather | `a8b065b6070c5e59cd021645ec1eb3256dabd2eb546acc276741a3b205235708` |
| OKX 1h futures Feather | `dce2eb3cfe136680413398f4ef39be483d5a8cd3d49b2ed96cd0344c2080dca0` |
| OKX 4h futures Feather | `12a264aa4fcce6ab86b69d021e1c4126c962b401a5fe2445e2bdc75b1951a5da` |
| OKX 1h mark Feather | `2a8a9ba530b17cd8292855772f948fb7d43940cfd312b82c17330e7992e1316b` |
| OKX actual funding Feather | `98fa273cb29c92a75a0fe09b7f36485b1a810986f4254569aad177f1ca42227d` |
| isolated OKX leverage-tier snapshot | `abc2d7352f237a6ce5a99da7ebc2b320b9584ce13f0d5296943e7713bf4f9825` |

Pre-performance mechanics verification at freeze: the focused pytest suite passed 10 tests;
Ruff passed for the research strategy and runner. This is mechanics evidence only; it contains
no performance result.
