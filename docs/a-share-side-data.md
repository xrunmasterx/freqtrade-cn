# A-Share Side Data

This document describes the Phase 3A research-only side-data layer for A-share
feature, event, and document artifacts.

## Scope

Phase 3A adds local side-data artifacts that can be discovered through the Research
datasets API and optionally overlaid on Research chart candles. It does not change
the Phase 1 OHLCV CSV contract:

```text
timeframe: 1d
adjustment: raw
columns: date,open,high,low,close,volume
```

Do not add side-data columns to OHLCV files. OHLCV files remain under the configured
`research_bots[].data_source.root`; side-data artifacts live under
`research_bots[].side_data.root`.

Phase 3A supports these dataset IDs:

```text
fund_flow_daily
limit_pool
announcements
```

The example research config enables all three datasets for `a-share-local`.

## Local Layout

The example config sets both the Phase 2 metadata root and the Phase 3A side-data
root to:

```text
ft_userdata/user_data/research_data/a_share_meta
```

Calendar and daily status remain in the Phase 2 metadata paths:

```text
calendar/trade_dates.csv
status/daily_status.csv
```

Side-data artifacts use sibling directories under the same meta root:

```text
features/fund_flow_daily/{instrument}.csv
events/limit_pool/{trade_date}.jsonl
documents/announcements/{instrument}.jsonl
.manifests/{run_id}.json
```

The local side-data store currently reads:

- `fund_flow_daily` as instrument-scoped feature CSV.
- `limit_pool` as market-scoped event JSONL.
- `announcements` as instrument-scoped document JSONL.

Manifest paths are relative to the side-data root.

## Collect

Run the collector from the repository root:

```powershell
cd G:\AI_Trading\freqtrade-cn

freqtrade\.venv\Scripts\python tools\download_a_share_side_data.py `
  --config ft_userdata\user_data\config.research.example.json `
  --bot-id a-share-local `
  --datasets fund_flow_daily limit_pool announcements `
  --instruments 600519.SH 000001.SZ `
  --timerange 20240101-20240701
```

The CLI defaults to:

```text
--provider akshare
```

`limit_pool` and `announcements` collection require `market_data.calendar` in the
research bot profile. The collector loads that calendar from the configured
`market_data.meta_root` before calling the provider.

Successful stdout is a JSON run summary. If any artifact fails, stderr includes a
short failure header and one short line per failed artifact, while stdout still
contains the JSON summary. The CLI exits with code `1` when `summary.failed` is
non-zero, and code `0` otherwise. Config, timerange, profile, provider setup, and
calendar errors exit with code `2`.

The collector writes successful artifacts atomically and records all per-artifact
statuses in `.manifests/{run_id}.json`.

## Verify API

Start the backend webserver with the research config:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade

.\.venv\Scripts\python -m freqtrade webserver `
  --config ..\ft_userdata\user_data\config.research.example.json `
  --userdir ..\ft_userdata\user_data
```

The Research datasets API lists local side-data descriptors:

```powershell
$pair = "freqtrader:change-me"
$headers = @{
  Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
}

Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8080/api/v1/research/datasets?bot_id=a-share-local&instrument=600519.SH" `
  -Headers $headers
```

The chart API can request side layers alongside local candles:

```powershell
$chartBody = @{
  bot_id = "a-share-local"
  instrument = "600519.SH"
  timeframe = "1d"
  limit = 120
  adjustment = "raw"
  side_layers = @{
    features = @("fund_flow_daily")
    events = @("limit_pool")
    documents = @("announcements")
  }
} | ConvertTo-Json -Depth 4

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8080/api/v1/research/chart_candles" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $chartBody
```

Chart responses include requested side-data overlays through chart metadata layers
and, for feature datasets, prefixed feature columns such as:

```text
feature_fund_flow_daily_main_net_inflow
```

The Research backtest API loads Phase 2 `market_data` automatically through the
profile and applies `ResearchMarketContext` when local calendar/status files are
available. Backtest requests do not consume `side_layers`.

## Provider Boundary

Provider calls happen only in collector/provider tooling paths:

```text
tools/download_a_share_side_data.py
  -> AkshareAshareSideDataProvider
  -> AShareSideDataCollector
  -> local side-data artifacts and manifests
```

Research chart, backtest, and datasets API requests read local artifacts only. They
must not call `akshare`, Eastmoney, or other live providers during API requests.

The `a-stock-data-direct` sector-membership provider is currently smoke-provider
coverage only. It is not wired into the collector or local store in Phase 3A.

## Frontend Validation

FreqUI Research currently exposes one optional selection for each side-data kind:

```text
Feature data
Event data
Document data
```

Each control is single-select. Refreshing the chart sends `side_layers` with zero
or one dataset ID per kind. Running a backtest does not send or consume side-data
layers.

If no local artifact is available for a dataset, the dataset selector should not
offer it as an available option. If a requested chart layer has no points in the
visible candle window, the backend reports that layer as unavailable in chart
metadata rather than downloading data on demand.

## Failure Handling

Collector failures are per artifact where possible. A failed artifact is recorded
in the JSON summary and manifest with `status: "error"`, `rows: 0`, and a sanitized
error string. Other requested artifacts can still succeed in the same run.

Research API behavior remains local-file based:

- missing OHLCV returns a missing-OHLCV response for chart/backtest;
- missing side-data config returns an empty datasets list;
- invalid side-data requests return sanitized 400 responses;
- missing optional side-data does not alter existing OHLCV chart/backtest behavior
  unless chart layers explicitly request it.

## Not Supported

Phase 3A does not provide:

- A-share live trading, dry-run trading, broker execution, or order placement;
- strategy feature consumption of side-data artifacts;
- AI retrieval, RAG, PDF ingestion, document parsing, or report summarization;
- provider-backed chart, backtest, or datasets API requests;
- side-data columns inside Phase 1 OHLCV CSV files;
- adjusted-price side-data contracts;
- automatic collection from the frontend.
