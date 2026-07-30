# Chart Data Source Rules

This document is the standing contract for adding chart indicators, strategy overlays,
decision evidence, or chart UI behavior in this repository.

## Core Principle

Market candles are the shared coordinate system. Every chart value must align by candle
identity, not by row index:

```text
pair + candle_type + timeframe + candle_open_time
```

Derived values are not just numbers. They must carry source, timeframe, alignment, coverage,
and trust level through chart metadata.

## Observation and Decision Time

The minimum near-real-time watch timeframe is `1m`; its fastest normal polling cadence
is approximately `10s`. This is minute-candle observation, not a raw-trade tick stream,
an exact real-time guarantee, or an HFT path.

The final market candle may be forming and may change between polls. Market OHLCV and
Watch Indicators may describe that row, but a Watch Indicator on it is provisional.
Official Strategy Indicators and Strategy Signals use closed strategy candles only:

- an equal-timeframe strategy series omits an unclosed final source row;
- a lower-chart-timeframe alignment may carry the latest closed continuous strategy value
  forward, but this does not mean the forming chart candle was evaluated;
- entry/exit signals align to an exact closed candle open and are never forward-filled;
- `last_candle_complete`, alignment, and `provisional` metadata must preserve this
  distinction through the UI.

## Source Domains

### Market

Market data owns OHLCV and the visible chart timeline. It is the base layer for all chart
composition. Do not let indicators or strategies redefine candle identity.

### Watch

Watch indicators are chart-observation indicators calculated for the selected chart timeframe.
They are useful for manual analysis, but they are not evidence of what the bot used to trade.
Examples: MA, RSI, MACD, Supertrend, QQE MOD.

Rules:

- Add watch indicator calculations in backend chart/shared indicator code, not in FreqUI.
- Prefix legacy dataframe columns with `watch_` only when the column remains in the flattened API.
- Expose labels, coverage, panel, visibility, and source through `meta.layers`.

### Strategy

Strategy output comes from the bot strategy/analyzed dataframe and the strategy export contract
such as `plot_config`.

Rules:

- Do not recompute strategy indicators in FreqUI.
- Do not substitute missing strategy values with watch values.
- Use `strategy_<timeframe>_<column>` only for legacy flattened columns.
- Preserve and report alignment: `direct`, `forward_fill`, `hidden`, or `unavailable`.
- If chart timeframe is higher than strategy timeframe, hide unsupported continuous overlays and
  return a warning instead of inventing aggregation.
- A strategy entry/exit signal is decision evidence, not evidence that an Order, Fill, or
  Trade occurred.

### Execution

Execution evidence comes from persisted Paper Trades/Orders/Fills or simulated backtest
results at their recorded time and price.

Rules:

- Keep execution markers in a separate series/layer, legend entry, and tooltip from
  Strategy Signals.
- Never synthesize an execution marker from an entry/exit signal column.
- Never overlay Runtime execution evidence when its strategy context does not match the
  chart's exact strategy/revision/release context. A matching strategy name alone is not
  sufficient when stronger identity is available.
- Gate A compatibility payloads expose strategy name and usually strategy timeframe, but
  no revision/release identity. Suppress explicitly mismatched names and, when both sides
  provide it, mismatched strategy timeframes. Retain a Trade with missing strategy or
  timeframe only for legacy compatibility, and treat those cases or a name/timeframe
  match as weak compatibility evidence rather than formal exact-context proof.
- Use the existing `execution` source metadata when execution evidence is represented in
  the chart contract.

### Decision Snapshot

Decision snapshots are the highest-trust evidence for explaining real bot decisions.

Rules:

- Store decision-time evidence in persistence, not in current recomputation.
- Expose decision evidence through metadata sidecar points: `meta.layers[].points`.
- Align points by `timestamp = candle_open` in milliseconds.
- Do not add decision evidence fields to legacy `columns`, `data`, or `plot_config`.
- A decision snapshot sidecar failure must not break the base chart response.

## Metadata Contract

Every chart layer should describe itself with:

```text
id, source, status, label, timeframe, alignment, series, points, warnings
```

Every series should describe:

```text
column, label, source, kind, panel, timeframe, visible, coverage, provisional
```

Coverage is user-facing trust information. Calculate it after final trimming and preserve
missing values as missing values.

`provisional=true` means the displayed value can change because its own source candle
is forming. It must not be used to label a closed-candle Strategy Indicator or Signal as
provisional decision output.

## Window Semantics

Keep these concepts separate:

- Data window: rows returned by the backend, currently `limit`.
- Display window: initial frontend viewport, currently `chartDefaultCandleCount`.
- Warmup window: extra rows needed for indicator calculation.
- Strategy coverage window: actual range available from the analyzed dataframe.

Do not use one setting to mean all four.

## UI Rules

FreqUI should render from metadata when available:

- Legend labels come from `ChartSeriesMeta.label`.
- Tooltip groups come from `ChartLayerMeta.source` and `label`.
- Decision evidence appears above strategy output and watch indicators.
- Strategy Signals and execution markers remain separately labelled and visually
  distinguishable even when they share a candle timestamp.
- A strategy-context mismatch suppresses execution markers and reports why; it never
  displays a plausible but unrelated trade.
- One visible crosshair selection must map to one candle timestamp and one data index.
- Candle-time bars must be visually centered on their `candle_open_time`. When multiple bar
  series share a panel and x axis, render them as timestamp-overlaid evidence, not as
  category-grouped bars.
- Multi-state histograms should prefer one logical bar series with state-driven color. If legacy
  compatibility requires separate bar columns, FreqUI must still preserve the same timestamp
  center for every bar series.

Fallbacks may exist for old responses, but new work should improve metadata rather than add
more column-name heuristics.

## Test Requirements

When adding or changing chart features, add tests that prove:

- Legacy `columns`, `data`, and `plot_config` remain compatible unless intentionally changed.
- `meta.layers` identifies the correct source, status, alignment, labels, and coverage.
- Watch and strategy data are never silently substituted for each other.
- Decision snapshot evidence appears only for matching candle timestamps.
- Live responses retain the Forming Candle for market/watch observation while official
  Strategy Signals remain absent until their source candle closes.
- Strategy Signals and execution markers cannot substitute for each other.
- Mismatched strategy execution evidence is not rendered.
- Frontend tooltip and legend behavior still work without metadata fallback.
- Multiple candle-time bar series on the same axis remain centered on the selected candle
  timestamp.

Recommended local checks:

```powershell
cd freqtrade
.\.venv\Scripts\python -m pytest tests/rpc/test_chart_data.py tests/rpc/test_chart_indicators.py -q

cd ..\frequi
pnpm vitest run tests/unit/candleChartTooltip.spec.ts tests/unit/candleChartSeries.spec.ts
pnpm typecheck
```

For visible chart changes, rebuild and restart the owning local container, then verify the
journey on its owning origin:

- current Baseline Capability Gate: `http://127.0.0.1:8081/graph`;
- later platform-owned base or Runtime Access overlay charts, only after an explicit
  Phase 2D resume: `http://127.0.0.1:8090/platform-chart`.

Passing the compatibility `8081/graph` journey proves neither a platform-chart change
on 8090 nor formal dynamic Paper acceptance.
