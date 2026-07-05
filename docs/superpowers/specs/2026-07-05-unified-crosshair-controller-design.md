# Unified Crosshair Controller Design

## Background

The candle chart currently uses ECharts native x-axis pointers in several places:

- each time xAxis has its own axisPointer
- tooltip has its own axisPointer
- the global axisPointer links all x axes

In a multi-grid chart this creates multiple visual owners for the same vertical guide. ECharts can link axis values, but it still renders and updates pointer elements per grid/axis. That is why the main candle panel and indicator panels can show visibly different vertical dashed lines.

This is a frontend interaction/rendering issue. The backend returns static candle and indicator rows. Hovering the mouse does not ask the backend to recalculate MACD, RSI, QQE MOD, Supertrend, or any other indicator.

## Goal

There must be one canonical selected candle row and one visible vertical guide line for the whole candle chart. All tooltip values must be read from that same selected row.

## Non-Goals

- Do not change indicator calculations.
- Do not change API response shape.
- Do not redesign the tooltip layout.
- Do not refactor chart data or subplot generation outside the crosshair boundary.

## Design

### Source of Truth

The source of truth is a chart-local crosshair selection:

- `dataIndex`: the selected row in the rendered candle dataset
- `timestamp`: the `__date_ts` value for that row

Mouse movement converts the pointer x pixel to the main time axis value, snaps it to the nearest real candle row, and stores that result. The temporary scroll-past row is not selectable.

### Rendering

Native ECharts x-axis pointer lines are disabled visually. They may still exist internally for tooltip triggering, but they are not allowed to draw the vertical guide.

The only visible vertical guide is a chart-level `graphic` line. Its x coordinate comes from converting the selected timestamp back through xAxis 0. Its y range is the union of all visible grid rectangles, so it covers the candle panel, volume, and indicator panels as one continuous line.

The horizontal price guide is drawn only when the pointer is inside the main candle grid. It uses the main y-axis coordinate and shows the price label on the configured price side.

### Tooltip Accuracy

The tooltip formatter receives normal ECharts params, but before rendering it normalizes each param to the active crosshair selection. That means the displayed OHLC and indicator values come from the same selected row even if ECharts passes stale params during rapid pointer movement.

### Failure Behavior

If the pointer is outside all chart grids, the crosshair graphic is removed and the tooltip is hidden.

If ECharts cannot resolve a grid rectangle or x pixel, the crosshair is hidden for that event rather than drawing an approximate line.

## Tests

- Unit test that time-axis pointer options are visually hidden.
- Component test that all CandleChart x axes use hidden native pointers and the tooltip pointer is not visible.
- Unit test that tooltip formatting normalizes values to the active crosshair row.
- Unit test that nearest-row selection clamps and snaps deterministically.

## Success Criteria

- The chart has at most one visible vertical dashed guide during hover.
- The selected candle and all visible indicator tooltip values use one `dataIndex`.
- The fix works regardless of the number of visible subplots.
- No backend indicator code changes are required.
