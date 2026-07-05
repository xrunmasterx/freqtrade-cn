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

For visible chart changes, rebuild and restart the local container, then verify
`http://127.0.0.1:8081/graph`.
