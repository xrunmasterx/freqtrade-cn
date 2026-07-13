# A-Share Market Correctness

This document describes the Phase 2 research-only market-correctness layer.

## Scope

Phase 2 improves research backtest correctness by adding local side-channel metadata for
A-share trading days and per-instrument daily status. It does not enable live trading,
dry-run trading, broker execution, account synchronization, or order placement.

The current public Research chart/backtest API continues to read local canonical OHLCV files.
The Phase 2 calendar/status/rules checks are loaded through the research bot
`market_data` profile when local cache files are configured and available. The
research backtest engine receives those files as `ResearchMarketContext`.

## Inputs

Calendar cache:

```text
ft_userdata/user_data/research_data/a_share_meta/calendar/trade_dates.csv
```

Columns:

```text
date,is_open,source
```

Daily status cache:

```text
ft_userdata/user_data/research_data/a_share_meta/status/daily_status.csv
```

Columns:

```text
date,instrument,suspended,limit_up,limit_down,volume,listed_date,delisted_date,source
```

These files are side-channel market metadata. They must not be mixed into the six-column OHLCV
CSV contract:

```text
date,open,high,low,close,volume
```

For Phase 3A feature/event/document side-data artifacts, see
[A-Share Side Data](a-share-side-data.md). Those artifacts live beside calendar/status metadata
under the configured side-data root, but remain separate from OHLCV CSV files.

## Seed Tools

The metadata seed tools live at the parent repository level:

```powershell
cd G:\AI_Trading\freqtrade-cn
freqtrade\.venv\Scripts\python tools\download_a_share_market_calendar.py
freqtrade\.venv\Scripts\python tools\download_a_share_daily_status.py
```

The tools import `akshare` only when an actual download is requested. Importing the modules or
running `--help` must not import `akshare` or touch the network:

```powershell
cd G:\AI_Trading\freqtrade-cn
freqtrade\.venv\Scripts\python tools\download_a_share_market_calendar.py --help
freqtrade\.venv\Scripts\python tools\download_a_share_daily_status.py --help
```

Default outputs:

```text
ft_userdata/user_data/research_data/a_share_meta/calendar/trade_dates.csv
ft_userdata/user_data/research_data/a_share_meta/status/daily_status.csv
```

## Rules

Research backtests with `ResearchMarketContext` apply these conservative A-share rules:

- 100 shares per lot.
- Commission on entry and exit.
- Stamp tax on exit.
- T+1 based on trading days, not natural days.
- No fills while suspended.
- No fills when volume is zero.
- No buy fills at or above limit-up.
- No sell fills at or below limit-down.
- No fills before listing date or after delisting date.

When a fill is blocked, the research backtest result includes a warning such as:

```text
Blocked buy fill on 2024-01-03 00:00:00+00:00
Blocked sell fill by T+1 on 2024-01-02 02:30:00+00:00
```

Closed-day OHLCV rows are not silently rescheduled to the next trading day in Phase 2. If a future
phase needs closed-day bar validation, delayed fills, or calendar-based data cleaning, that should
be specified as a separate data-quality contract.

## Provider Boundary

Chart/backtest requests read local canonical files only. They must not call akshare, Eastmoney,
Tencent, Sina, mootdx, cninfo, iwencai, or any other live provider.

Provider seed tools may call external providers and must write local CSV files before research APIs
consume them.

## Future Phases

Phase 3A adds the first local feature/event/document side-data stores for funds flow,
limit-up pool events, and announcement indexes. Those artifacts align with candle timestamps but
remain side-channel data, not extra OHLCV columns. Sector membership currently has smoke-provider
coverage only and is not wired into the collector/store.

Phase 4 should add portfolio-level research backtesting. Phase 5 should add AI evidence retrieval.
Future live trading belongs behind separate `BrokerAdapter` and `ExecutionEngine` interfaces, not
the research data adapters.
