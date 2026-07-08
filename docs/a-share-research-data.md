# A-Share Research Data

This document is for operators running the Phase 1B A-share OHLCV research-data flow.

Phase 1B downloads raw A-share OHLCV into standardized local research CSV files, then
verifies those files through the Research chart and Research backtest APIs. It does not
enable A-share live trading, dry-run trading, broker execution, funds flow, news,
announcements, research reports, or AI document ingestion.

## Supported In Phase 1B

Phase 1B downloads raw A-share OHLCV into local research CSV files for:

```text
1m, 5m, 15m, 30m, 60m, 1d
```

Research chart and backtest read these local files through `local_csv`. They do
not call `akshare`, Eastmoney, Sina, Tencent, or `mootdx` during API requests.

Phase 1B also supports:

- writing normalized local CSV files under the configured research data root;
- writing a manifest for each collector run;
- verifying chart candles and the current research SMA backtest from those local files.

Not supported in Phase 1B:

- A-share live trading or dry-run trading;
- broker connectivity, order placement, wallet state, force-entry, or force-exit behavior;
- HK/US market ingestion;
- funds flow, news, announcements, research reports, financial statements, or AI document
  ingestion;
- provider-backed chart or backtest requests.

For Phase 2 market-correctness rules, see
[A-Share Market Correctness](a-share-market-correctness.md). Phase 2 adds local
calendar/status side-channel metadata and research backtest rule checks; it does not change the
Phase 1 `1d`/`raw` OHLCV data contract.

For Phase 3A feature/event/document side-data, see
[A-Share Side Data](a-share-side-data.md). Side-data artifacts are stored under the configured
side-data root and must not be mixed into the Phase 1 OHLCV CSV files.

## Data Contract

The supported Phase 1B operator contract is:

```text
timeframe: 1m, 5m, 15m, 30m, 60m, 1d
adjustment: raw
columns: date,open,high,low,close,volume
```

The standard CSV columns are exactly:

```text
date,open,high,low,close,volume
```

Each data file is named as:

```text
{instrument}-{timeframe}.csv
```

For example:

```text
ft_userdata/user_data/research_data/a_share/600519.SH-1d.csv
```

The collector also writes a run manifest next to the data root:

```text
ft_userdata/user_data/research_data/a_share/.manifests/{run_id}.json
```

The configured research bot decides the data root. The current example config declares
`research_bots[].data_source.type` as `local_csv` and `root` as `research_data/a_share`, so
with `ft_userdata/user_data/config.research.example.json` the files land under:

```text
ft_userdata/user_data/research_data/a_share/
```

## Provider Boundary

The optional provider dependency is the `research_ashare` extra in the backend
`freqtrade` package. It installs `akshare` for the collector provider.

`akshare` is used only by the collector CLI/provider path:

```text
tools/download_a_share_research_data.py
  -> AkshareAshareOhlcvProvider
  -> AShareOhlcvCollector
  -> local CSV files and manifest
```

Research chart and backtest API requests do not call `akshare`. They read already-collected
local files through `local_csv`:

```text
local CSV files
  -> LocalCsvResearchDataSource
  -> /api/v1/research/chart_candles
  -> /api/v1/research/backtest
```

This separation is intentional. Backtests and charts are reproducible from local files and do
not depend on provider availability, network behavior, or provider-side schema changes during
API requests.

## Windows PowerShell Flow

Run these commands from the repository root:

```powershell
cd G:\AI_Trading\freqtrade-cn
```

Install the optional A-share research provider dependency into the backend virtual
environment:

```powershell
freqtrade\.venv\Scripts\python -m pip install -e ".\freqtrade[research_ashare]"
```

If you prefer activating the backend virtual environment first, run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[research_ashare]"
cd ..
```

## Download Raw Multi-Timeframe OHLCV

```powershell
.\freqtrade\.venv\Scripts\python tools\download_a_share_research_data.py `
  --config ft_userdata\user_data\config.research.example.json `
  --bot-id a-share-local `
  --instruments 688017.SH `
  --timeframes 1m 5m 15m 30m 60m 1d `
  --adjustment raw
```

Minute data from `akshare.stock_zh_a_minute` is recent-history data. The
provider returns about `1970` bars per requested minute period, and timerange is
applied as a local post-filter.

Expected collector output is one line per requested instrument/timeframe, for example:

```text
ok: 688017.SH-1m.csv rows=...
ok: 688017.SH-5m.csv rows=...
ok: 688017.SH-15m.csv rows=...
ok: 688017.SH-30m.csv rows=...
ok: 688017.SH-60m.csv rows=...
ok: 688017.SH-1d.csv rows=...
```

Inspect the generated files:

```powershell
Get-ChildItem ft_userdata\user_data\research_data\a_share
Get-Content ft_userdata\user_data\research_data\a_share\688017.SH-1m.csv -TotalCount 5
```

The first CSV line must be:

```text
date,open,high,low,close,volume
```

Inspect the latest manifest:

```powershell
$manifest = Get-ChildItem ft_userdata\user_data\research_data\a_share\.manifests\*.json |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

Get-Content $manifest.FullName
```

The manifest records the run id, market, provider, provider version, requested instruments,
requested timeframes, adjustment, timerange, per-file rows, per-file status, and warnings.

## Verify Through Research APIs

Start the backend webserver with the research config in one PowerShell terminal:

Research `local_csv` roots are resolved under the configured user data directory, so webserver
verification explicitly uses the same `--userdir` as the collector.

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m freqtrade webserver `
  --config ..\ft_userdata\user_data\config.research.example.json `
  --userdir ..\ft_userdata\user_data
```

In another PowerShell terminal, create the Basic Auth header from the example config:

```powershell
cd G:\AI_Trading\freqtrade-cn

$pair = "freqtrader:change-me"
$headers = @{
  Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
}
```

Verify that the API can list local A-share instruments:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8080/api/v1/research/instruments?bot_id=a-share-local" `
  -Headers $headers
```

Verify chart candles from the local CSV:

```powershell
$chartBody = @{
  bot_id = "a-share-local"
  instrument = "688017.SH"
  timeframe = "1m"
  limit = 20
  adjustment = "raw"
} | ConvertTo-Json

$chart = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8080/api/v1/research/chart_candles" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $chartBody

$chart | Select-Object pair, timeframe, chart_timeframe, length
```

Verify the research backtest from the same local data:

```powershell
$backtestBody = @{
  bot_id = "a-share-local"
  instrument = "688017.SH"
  timeframe = "1m"
  initial_cash = 100000
  strategy = @{
    type = "sma_cross"
    fast = 5
    slow = 20
  }
} | ConvertTo-Json -Depth 4

$backtest = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8080/api/v1/research/backtest" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $backtestBody

$backtest.metrics
```

These API checks should work without calling `akshare`. If the local CSV is missing, the API
returns a missing-OHLCV error instead of downloading data on demand.

## A-share chart axis behavior

A-share OHLCV files keep real timestamps. Research charts compress non-trading time in the
display axis when API metadata returns `meta.axis.mode = "trading_session"`.

This means:

- 09:30-11:30 and 13:00-15:00 candles are drawn as adjacent trading bars.
- Lunch break, overnight gaps, weekends, and holidays do not consume horizontal chart space.
- Tooltip and crosshair labels still show the original candle timestamp.
- Backtests and market rules continue to use real timestamps, trading calendars, T+1,
  limit-up/down, and suspension state.
- Missing candles inside an open trading session remain data-quality issues and must not be
  hidden as closed-market compression.

## Unsupported Inputs

`qfq` and `hfq` remain unsupported in Phase 1B. Feature-aware backtest and
side-data layers remain `1d`-only until minute side-data alignment is designed.

Do not use this flow as evidence that A-share live trading, dry-run trading, HK/US ingestion,
news/AI ingestion, or adjusted-price support exists. Those are outside Phase 1B.
