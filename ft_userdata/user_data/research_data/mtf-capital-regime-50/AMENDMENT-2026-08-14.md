# MTF Capital-Regime Research Amendment

Effective: 2026-08-14 UTC, before the amended development screen.

This amendment opens a new independent study directory. Existing `mtf-regime-50`
results, source files, and receipts remain historical and are not overwritten.

## Changes from the prior MTF screen

- The derived runtime now includes the authoritative 1h mark-price Feather file. The
  prior runtime omitted it, so its recorded funding fees were zero and cannot support
  a mark-inclusive cost claim.
- A new strategy source defines 50 explicit resolver-loadable classes using closed 4h/1d
  directional gating, asymmetric long/short candle and momentum rules, mark/futures
  basis, funding observation-age caps, volatility, and relative-volume participation.
  Neutral/range states abstain rather than routing to a second strategy leg.
- A causal factor diagnostic is persisted before performance scoring. It can describe
  regime, funding, basis, volatility, and breakout forward returns, but it cannot select
  a validation candidate or relax a performance gate.
- The amended runner must stop after development when no candidate passes all frozen
  gates. It may not send a merely high-profit or small-sample diagnostic to validation.
- Mark/funding coverage and the summed per-trade funding fees are mandatory receipt
  fields. Any result that cannot be audited against the mark file is non-qualifying.

## Unchanged boundaries

The temporal split, two fee scenarios, 1x leverage, one-pair/one-position execution,
closed-candle informative alignment, no exchange/network writes, and no Paper/Live
promotion remain unchanged. Any later parameter or protocol change requires another
dated amendment before the affected stage runs.
