# MTF Regime Research Implementation Amendment

Effective: 2026-08-14 UTC, before the official 50-variant development screen.

The following changes were made after resolver/data-path smoke diagnostics and before
any development candidate was ranked. The two annual smoke ZIPs in this directory are
diagnostic only; they are not part of `results.json`, were not used to select a variant,
and do not change the preregistered matrix or gates.

- Candidate classes are explicit subclasses so Freqtrade's source resolver can load each
  preregistered name. The 50 codes, profiles, and order remain unchanged.
- The runner passes the retained data's `okx` directory to Freqtrade, matching its
  `futures/` path contract.
- Startup warmup is fixed at 1,200 candles. This covers the longest 200-period daily
  informative EMA and avoids applying an invalid 20,000-day informative lookback on
  Windows.
- `use_exit_signal` is enabled so the already-preregistered 72-hour custom exit is
  actually evaluated; no force-exit is accepted as a qualifying result.
- Funding informative data is loaded without synthetic gap filling and is merged without
  forward-fill. P1 therefore uses only a directly observed settlement row; the normal
  backtest funding ledger already uses `fill_up_missing=False`.
- The offline wrapper supplies one static, broad leverage tier and a local market
  definition. It performs no exchange or network write and the strategy still returns
  exactly 1.0 leverage.
- Missing 4h/1d regime evidence is `neutral`, not `range`, so the range leg also
  abstains when higher-timeframe evidence is absent.

The temporal windows, fee scenarios, minimum samples, metric definitions, ranking rule,
and promotion gates in `PREREGISTRATION.md` are unchanged. Any later change requires a
new dated amendment before the affected stage is run.
