# Research Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current Research feature honest, bounded, and recoverable by fixing API contract mismatches, A-share execution semantics, service gating, malformed input handling, UI request states, and local Docker/config separation.

**Architecture:** Keep this as a hardening pass, not a full market-platform rewrite. The backend remains FastAPI + Pydantic + pandas, but research-only concerns get explicit boundaries: request contract validation in `api_research.py`, reusable research data-window helpers in `freqtrade/research`, minimal market rules in `freqtrade/markets`, and UI state handling in the Research Pinia store/view. Unsupported features fail fast instead of silently producing misleading research results.

**Tech Stack:** Python, pandas, Pydantic v2, FastAPI, pytest, Ruff, TypeScript, Vue 3, Pinia, Vitest, Docker Compose.

---

## Assumptions

- This plan targets `G:\AI_Trading\freqtrade-cn` on branch `feature/a-share-market-framework-v1`.
- The first repair wave should prevent wrong research conclusions and unstable demos.
- `qfq/hfq` will not be implemented in this wave because no adjustment factor data source exists. Non-raw adjustment must return an explicit API error.
- `timerange` should be implemented because the repository already has `TimeRange.parse_timerange` and `trim_dataframe`.
- Full job-based backtesting, persistent caches, full MarketRegistry, and multi-market adapters are intentionally out of scope for this repair wave.
- Existing path-leak safety tests are stronger than the audit request for raw traceback logging. This plan adds safe request context and exception class logging, but does not log unsanitized exception messages that may contain local paths.

## Success Criteria

- Non-raw research adjustment returns a clear `501` response and never returns raw candles under a qfq/hfq label.
- Non-empty `timerange` filters both chart and backtest input before results are produced.
- A-share intraday backtest cannot close a long position on the same trading date as entry.
- Research routes are unavailable on trading-mode services unless explicitly research-enabled in webserver mode.
- Bad `research_bots` config returns a structured 400/503-class API error instead of a raw internal exception.
- A stray invalid CSV filename does not break instrument discovery.
- Research UI distinguishes loading, error, empty, and stale-success states, and disables duplicate requests.
- The default docs/config guide users to separate trading and research configs.

## File Structure

### Backend: `freqtrade`

- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
  - API boundary validation, error mapping, safe logging, response limits.
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
  - Research instrument availability DTOs and backtest response model.
- Modify: `freqtrade/freqtrade/rpc/api_server/deps.py`
  - Add research-mode dependency.
- Modify: `freqtrade/freqtrade/rpc/api_server/webserver.py`
  - Gate Research router with research-mode dependency.
- Modify: `freqtrade/freqtrade/research/chart.py`
  - Apply timerange before `tail(limit)` and return effective metadata.
- Modify: `freqtrade/freqtrade/research/backtesting.py`
  - Use market rules for A-share lot/fees/T+1.
- Modify: `freqtrade/freqtrade/research/data_source.py`
  - Skip invalid CSV names during discovery and expose available timeframes.
- Modify: `freqtrade/freqtrade/research/profiles.py`
  - Convert malformed profile config to a typed research config error.
- Add: `freqtrade/freqtrade/research/windowing.py`
  - Parse and apply research timerange using existing Freqtrade utilities.
- Add: `freqtrade/freqtrade/research/exceptions.py`
  - Shared typed exceptions for profile/config/unsupported-feature failures.
- Add: `freqtrade/freqtrade/markets/rules.py`
  - Minimal A-share market rules for this wave.
- Test: `freqtrade/tests/rpc/test_api_research.py`
- Test: `freqtrade/tests/research/test_chart.py`
- Test: `freqtrade/tests/research/test_backtesting.py`
- Test: `freqtrade/tests/research/test_data_source.py`
- Test: `freqtrade/tests/research/test_profiles.py`
- Test: `freqtrade/tests/markets/test_rules.py`

### Frontend: `frequi`

- Modify: `frequi/src/stores/research.ts`
  - Loading/error/in-flight state and typed request failures.
- Modify: `frequi/src/types/research.ts`
  - Instrument availability, effective adjustment/window metadata, request state types.
- Modify: `frequi/src/views/ResearchView.vue`
  - Loading/error rendering, duplicate request protection, available timeframe options, data credibility display.
- Modify: `frequi/src/components/layout/NavBar.vue`
  - Hide or de-emphasize Research when the active API is not research-capable.
- Modify: `frequi/src/locales/en.ts`
- Modify: `frequi/src/locales/zh-CN.ts`
- Test: `frequi/tests/unit/researchStore.spec.ts`
- Test: `frequi/tests/component/ResearchView.spec.ts`

### Parent Repository

- Add: `ft_userdata/user_data/config.research.example.json`
- Modify: `ft_userdata/user_data/config.example.json`
  - Remove `research_bots` from the trading example.
- Modify: `README.docker.md`
  - Copy separate configs and document single-service startup.
- Modify: `docker-compose.yml`
  - Add healthchecks and optional service profiles if agreed during execution.

---

## Task 1: Research API Contract Honesty

**Fixes:** B-1, B-2, part of P-1, part of P-2.

**Files:**
- Add: `freqtrade/freqtrade/research/windowing.py`
- Add: `freqtrade/freqtrade/research/exceptions.py`
- Modify: `freqtrade/freqtrade/research/chart.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Test: `freqtrade/tests/rpc/test_api_research.py`
- Test: `freqtrade/tests/research/test_chart.py`

- [ ] **Step 1: Write failing tests for unsupported adjustment**

Add to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_chart_rejects_unsupported_adjustment(research_client) -> None:
    response = client_post(
        research_client,
        f"{BASE_URI}/research/chart_candles",
        data={
            "bot_id": "a-share-local",
            "instrument": "600519.SH",
            "timeframe": "1d",
            "adjustment": "qfq",
        },
    )

    assert response.status_code == 501
    assert response.json()["detail"] == "Research adjustment qfq is not supported yet."
```

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_chart_rejects_unsupported_adjustment -q
```

Expected: FAIL because qfq currently succeeds and returns raw candles.

- [ ] **Step 2: Write failing tests for chart timerange filtering**

Extend the `research_client` fixture data in `freqtrade/tests/rpc/test_api_research.py` to contain at least three daily rows:

```python
(data_root / "600519.SH-1d.csv").write_text(
    "date,open,high,low,close,volume\n"
    "2026-07-06,1700,1710,1690,1705,100000\n"
    "2026-07-07,1705,1715,1700,1710,200000\n"
    "2026-07-08,1710,1720,1705,1715,300000\n",
    encoding="utf-8",
)
```

Add:

```python
def test_research_chart_applies_timerange_before_limit(research_client) -> None:
    response = client_post(
        research_client,
        f"{BASE_URI}/research/chart_candles",
        data={
            "bot_id": "a-share-local",
            "instrument": "600519.SH",
            "timeframe": "1d",
            "timerange": "20260707-20260707",
            "limit": 500,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["length"] == 1
    assert body["data"][0][0].startswith("2026-07-07")
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_chart_applies_timerange_before_limit -q
```

Expected: FAIL because chart currently returns unfiltered tail rows.

- [ ] **Step 3: Write failing tests for backtest timerange filtering**

Add to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_backtest_applies_timerange(research_client) -> None:
    response = client_post(
        research_client,
        f"{BASE_URI}/research/backtest",
        data={
            "bot_id": "a-share-local",
            "instrument": "600519.SH",
            "timeframe": "1d",
            "timerange": "19900101-19900131",
            "strategy": {"type": "sma_cross", "fast": 1, "slow": 2},
            "initial_cash": 100000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["trade_count"] == 0
    assert body["metrics"]["final_equity"] == 100000
    assert body["equity_curve"] == []
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_backtest_applies_timerange -q
```

Expected: FAIL because backtest currently uses all rows.

- [ ] **Step 4: Add typed research exceptions**

Create `freqtrade/freqtrade/research/exceptions.py`:

```python
class ResearchConfigError(ValueError):
    pass


class ResearchUnsupportedFeatureError(ValueError):
    pass
```

- [ ] **Step 5: Add timerange helper**

Create `freqtrade/freqtrade/research/windowing.py`:

```python
from pandas import DataFrame

from freqtrade.configuration.timerange import TimeRange
from freqtrade.data.converter.converter import trim_dataframe
from freqtrade.exceptions import ConfigurationError
from freqtrade.research.exceptions import ResearchConfigError


def apply_research_timerange(dataframe: DataFrame, timerange_text: str | None) -> DataFrame:
    if not timerange_text:
        return dataframe

    try:
        timerange = TimeRange.parse_timerange(timerange_text)
    except ConfigurationError as exc:
        raise ResearchConfigError(f"Invalid research timerange: {timerange_text}") from exc

    return trim_dataframe(dataframe, timerange, df_date_col="date").reset_index(drop=True)
```

- [ ] **Step 6: Apply timerange in chart service**

In `freqtrade/freqtrade/research/chart.py`, import the helper:

```python
from freqtrade.research.windowing import apply_research_timerange
```

Change the load/trim block in `build_research_chart_candles_response`:

```python
dataframe = LocalCsvResearchDataSource(profile.data_root).load_ohlcv(
    payload.instrument,
    payload.timeframe,
)
dataframe = apply_research_timerange(dataframe, payload.timerange)
dataframe = dataframe.tail(payload.limit).reset_index(drop=True)
```

- [ ] **Step 7: Reject unsupported adjustment and apply timerange in API**

In `freqtrade/freqtrade/rpc/api_server/api_research.py`, import:

```python
from freqtrade.research.exceptions import ResearchConfigError, ResearchUnsupportedFeatureError
from freqtrade.research.windowing import apply_research_timerange
```

Add:

```python
def _reject_unsupported_adjustment(adjustment: str) -> None:
    if adjustment != "raw":
        raise ResearchUnsupportedFeatureError(
            f"Research adjustment {adjustment} is not supported yet."
        )
```

In `research_chart_candles`, call `_reject_unsupported_adjustment(payload.adjustment)` before building the response.

In `research_backtest`, after `load_ohlcv`, add:

```python
dataframe = apply_research_timerange(dataframe, request.timerange)
```

Handle exceptions:

```python
except ResearchUnsupportedFeatureError as e:
    raise HTTPException(status_code=501, detail=str(e))
except ResearchConfigError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 8: Run focused backend tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py tests/research/test_chart.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit task**

Run:

```powershell
git add freqtrade/research/windowing.py freqtrade/research/exceptions.py freqtrade/research/chart.py freqtrade/rpc/api_server/api_research.py tests/rpc/test_api_research.py tests/research/test_chart.py
git commit -m "fix: honor research timerange and reject unsupported adjustment"
```

---

## Task 2: A-Share Market Rules and T+1 Enforcement

**Fixes:** A-3 core risk, B-3.

**Files:**
- Add: `freqtrade/freqtrade/markets/rules.py`
- Modify: `freqtrade/freqtrade/markets/__init__.py`
- Modify: `freqtrade/freqtrade/research/backtesting.py`
- Test: `freqtrade/tests/markets/test_rules.py`
- Test: `freqtrade/tests/research/test_backtesting.py`

- [ ] **Step 1: Write failing market rules tests**

Create `freqtrade/tests/markets/test_rules.py`:

```python
import pandas as pd

from freqtrade.markets.rules import AShareMarketRules


def test_a_share_rules_block_same_day_sell():
    rules = AShareMarketRules()
    entry_date = pd.Timestamp("2026-07-06 10:00:00+08:00")
    execution_date = pd.Timestamp("2026-07-06 14:00:00+08:00")

    assert not rules.can_sell(entry_date, execution_date)


def test_a_share_rules_allow_next_trading_date_sell():
    rules = AShareMarketRules()
    entry_date = pd.Timestamp("2026-07-06 10:00:00+08:00")
    execution_date = pd.Timestamp("2026-07-07 09:30:00+08:00")

    assert rules.can_sell(entry_date, execution_date)


def test_a_share_rules_round_to_whole_lots():
    rules = AShareMarketRules()

    assert rules.whole_lot_shares(cash=10000, price=12.3) == 800
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_rules.py -q
```

Expected: FAIL because `freqtrade.markets.rules` does not exist.

- [ ] **Step 2: Write failing intraday backtest test**

Add to `freqtrade/tests/research/test_backtesting.py`:

```python
def test_research_backtest_enforces_a_share_t_plus_one_for_intraday_data() -> None:
    dataframe = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-07-06 09:30:00+08:00",
                    "2026-07-06 10:00:00+08:00",
                    "2026-07-06 10:30:00+08:00",
                    "2026-07-06 11:00:00+08:00",
                    "2026-07-06 14:00:00+08:00",
                    "2026-07-07 09:30:00+08:00",
                ],
                utc=True,
            ),
            "open": [10, 8, 12, 13, 7, 7],
            "high": [10, 8, 12, 13, 7, 7],
            "low": [10, 8, 12, 13, 7, 7],
            "close": [10, 8, 12, 7, 7, 7],
            "volume": [100, 100, 100, 100, 100, 100],
        }
    )

    result = run_research_backtest(
        "600519.SH",
        dataframe,
        ResearchBacktestConfig(initial_cash=10000, fast=1, slow=2),
    )

    assert all(trade["entry_date"][:10] != trade["exit_date"][:10] for trade in result.trades)
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_backtesting.py::test_research_backtest_enforces_a_share_t_plus_one_for_intraday_data -q
```

Expected: FAIL because same-day exit is currently allowed.

- [ ] **Step 3: Implement minimal A-share rules**

Create `freqtrade/freqtrade/markets/rules.py`:

```python
from typing import Any

import pandas as pd


class AShareMarketRules:
    lot_size: int = 100
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001

    def whole_lot_shares(self, cash: float, price: float) -> int:
        lot_cost = price * self.lot_size * (1 + self.commission_rate)
        return int(cash // lot_cost) * self.lot_size

    def entry_fee(self, trade_value: float) -> float:
        return trade_value * self.commission_rate

    def exit_fee(self, trade_value: float) -> tuple[float, float]:
        commission = trade_value * self.commission_rate
        stamp_tax = trade_value * self.stamp_tax_rate
        return commission, stamp_tax

    def can_sell(self, entry_date: Any, execution_date: Any) -> bool:
        entry_ts = pd.Timestamp(entry_date)
        execution_ts = pd.Timestamp(execution_date)
        return execution_ts.date() > entry_ts.date()
```

Update `freqtrade/freqtrade/markets/__init__.py`:

```python
from freqtrade.markets.rules import AShareMarketRules
```

Add `"AShareMarketRules"` to `__all__`.

- [ ] **Step 4: Use rules in backtesting**

In `freqtrade/freqtrade/research/backtesting.py`, import:

```python
from freqtrade.markets.rules import AShareMarketRules
```

Change `ResearchBacktestConfig` so market rule constants are no longer independently configurable there:

```python
class ResearchBacktestConfig(BaseModel):
    initial_cash: float = Field(gt=0, allow_inf_nan=False)
    fast: int = Field(default=20, ge=1)
    slow: int = Field(default=60, ge=2)
```

At the start of `run_research_backtest`, add:

```python
rules = AShareMarketRules()
```

Replace same-day-unsafe sell condition:

```python
if (
    int(signal_row.exit_long)
    and shares > 0
    and entry is not None
    and rules.can_sell(entry["date"], row_date)
):
```

Replace fee and whole-lot calculations:

```python
commission, stamp_tax = rules.exit_fee(trade_value)
shares_to_buy = rules.whole_lot_shares(cash, open_price)
commission = rules.entry_fee(trade_value)
```

- [ ] **Step 5: Run market and backtest tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_rules.py tests/research/test_backtesting.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit task**

Run:

```powershell
git add freqtrade/markets/rules.py freqtrade/markets/__init__.py freqtrade/research/backtesting.py tests/markets/test_rules.py tests/research/test_backtesting.py
git commit -m "fix: enforce a-share market rules in research backtests"
```

---

## Task 3: Research Service Gate and Config Error Mapping

**Fixes:** A-1, R-1.

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/deps.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/webserver.py`
- Modify: `freqtrade/freqtrade/research/profiles.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Test: `freqtrade/tests/rpc/test_api_research.py`
- Test: `freqtrade/tests/research/test_profiles.py`

- [ ] **Step 1: Write failing test for trading-mode research route**

Add to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_bots_requires_research_webserver_mode(default_conf, tmp_path, mocker) -> None:
    default_conf["runmode"] = RunMode.OTHER
    default_conf["user_data_dir"] = tmp_path
    default_conf["research_bots"] = [
        {
            "id": "a-share-local",
            "label": "A Share Local",
            "market": "a_share",
            "data_source": {"type": "local_csv", "root": "research_data/a_share"},
        }
    ]
    default_conf["api_server"] = {
        "enabled": True,
        "listen_ip_address": "127.0.0.1",
        "listen_port": 8080,
        "CORS_origins": ["http://example.com"],
        "jwt_secret_key": _JWT_SECRET_KEY,
        "username": _TEST_USER,
        "password": _TEST_PASS,
    }
    mocker.patch("freqtrade.rpc.api_server.ApiServer.start_api", MagicMock())
    apiserver = ApiServer(default_conf)

    with TestClient(apiserver.app) as client:
        response = client_get(client, f"{BASE_URI}/research/bots")

    assert response.status_code == 503
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_bots_requires_research_webserver_mode -q
```

Expected: FAIL because the current route is available in `RunMode.OTHER`.

- [ ] **Step 2: Write failing malformed profile tests**

Add to `freqtrade/tests/research/test_profiles.py`:

```python
import pytest

from freqtrade.research.exceptions import ResearchConfigError


def test_load_research_profiles_raises_config_error_for_missing_data_source(tmp_path) -> None:
    config = {
        "user_data_dir": tmp_path,
        "research_bots": [{"id": "bad", "label": "Bad", "market": "a_share"}],
    }

    with pytest.raises(ResearchConfigError, match="research_bots\\[0\\].data_source"):
        load_research_profiles(config)
```

Add to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_bots_returns_config_error_for_malformed_profile(research_client, mocker) -> None:
    mocker.patch(
        "freqtrade.rpc.api_server.api_research.load_research_profiles",
        side_effect=ResearchConfigError("research_bots[0].data_source is required"),
    )

    response = client_get(research_client, f"{BASE_URI}/research/bots")

    assert response.status_code == 400
    assert response.json()["detail"] == "research_bots[0].data_source is required"
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_profiles.py::test_load_research_profiles_raises_config_error_for_missing_data_source tests/rpc/test_api_research.py::test_research_bots_returns_config_error_for_malformed_profile -q
```

Expected: FAIL until profile loading and API mapping are fixed.

- [ ] **Step 3: Implement `is_research_mode` dependency**

In `freqtrade/freqtrade/rpc/api_server/deps.py`, add:

```python
def is_research_mode(config=Depends(get_config)):
    if config["runmode"] != RunMode.WEBSERVER or not config.get("research_bots"):
        raise HTTPException(status_code=503, detail="Research service is not enabled.")
    return None
```

In `freqtrade/freqtrade/rpc/api_server/webserver.py`, import `is_research_mode` with the other deps and change Research router registration:

```python
dependencies=[Depends(http_basic_or_jwt_token), Depends(is_research_mode)],
```

Update the `research_client` fixture in `tests/rpc/test_api_research.py` from `RunMode.OTHER` to `RunMode.WEBSERVER`.

- [ ] **Step 4: Convert profile loader errors**

In `freqtrade/freqtrade/research/profiles.py`, import `ValidationError` and `ResearchConfigError`, then wrap each raw profile:

```python
from pydantic import BaseModel, Field, ValidationError
from freqtrade.research.exceptions import ResearchConfigError


def load_research_profiles(config: dict[str, Any]) -> list[ResearchBotProfile]:
    try:
        user_data_dir = Path(config["user_data_dir"])
    except KeyError as exc:
        raise ResearchConfigError("user_data_dir is required for research profiles") from exc

    profiles = []
    for index, raw_profile in enumerate(config.get("research_bots", [])):
        try:
            data_source = ResearchDataSourceConfig(**raw_profile["data_source"])
            profiles.append(
                ResearchBotProfile(
                    id=raw_profile["id"],
                    label=raw_profile["label"],
                    market=MarketType(raw_profile["market"]),
                    data_source=data_source,
                    data_root=user_data_dir / data_source.root,
                )
            )
        except KeyError as exc:
            raise ResearchConfigError(f"research_bots[{index}].{exc.args[0]} is required") from exc
        except (TypeError, ValueError, ValidationError) as exc:
            raise ResearchConfigError(f"research_bots[{index}] is invalid: {exc}") from exc
    return profiles
```

- [ ] **Step 5: Map config errors in API**

In `freqtrade/freqtrade/rpc/api_server/api_research.py`, catch `ResearchConfigError` in `research_bots`, `_get_research_profile`, chart, and backtest paths:

```python
except ResearchConfigError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_profiles.py tests/rpc/test_api_research.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit task**

Run:

```powershell
git add freqtrade/rpc/api_server/deps.py freqtrade/rpc/api_server/webserver.py freqtrade/research/profiles.py freqtrade/rpc/api_server/api_research.py tests/research/test_profiles.py tests/rpc/test_api_research.py
git commit -m "fix: gate research api and report profile config errors"
```

---

## Task 4: CSV Discovery Robustness and Timeframe Availability

**Fixes:** R-2, B-4, S-2 first step.

**Files:**
- Modify: `freqtrade/freqtrade/research/data_source.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Test: `freqtrade/tests/research/test_data_source.py`
- Test: `freqtrade/tests/rpc/test_api_research.py`

- [ ] **Step 1: Write failing data source tests**

Add to `freqtrade/tests/research/test_data_source.py`:

```python
def test_local_csv_research_data_source_skips_invalid_csv_names(tmp_path) -> None:
    (tmp_path / "600519.SH-1d.csv").write_text(
        "date,open,high,low,close,volume\n2026-07-06,1700,1710,1690,1705,100000\n",
        encoding="utf-8",
    )
    (tmp_path / "notes.csv").write_text("manual notes\n", encoding="utf-8")

    data_source = LocalCsvResearchDataSource(tmp_path)

    assert [instrument.key for instrument in data_source.list_instruments()] == ["600519.SH"]


def test_local_csv_research_data_source_lists_available_timeframes(tmp_path) -> None:
    for timeframe in ["1d", "5m"]:
        (tmp_path / f"600519.SH-{timeframe}.csv").write_text(
            "date,open,high,low,close,volume\n2026-07-06,1700,1710,1690,1705,100000\n",
            encoding="utf-8",
        )

    data_source = LocalCsvResearchDataSource(tmp_path)

    assert data_source.available_timeframes("600519.SH") == ["1d", "5m"]
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_data_source.py::test_local_csv_research_data_source_skips_invalid_csv_names tests/research/test_data_source.py::test_local_csv_research_data_source_lists_available_timeframes -q
```

Expected: FAIL because invalid names currently raise and no availability method exists.

- [ ] **Step 2: Write failing API availability test**

Add to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_instruments_returns_available_timeframes(research_client) -> None:
    response = client_get(
        research_client,
        f"{BASE_URI}/research/instruments?bot_id=a-share-local",
    )

    assert response.status_code == 200
    instruments = response.json()["instruments"]
    assert instruments[0]["key"] == "600519.SH"
    assert "1d" in instruments[0]["available_timeframes"]
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_instruments_returns_available_timeframes -q
```

Expected: FAIL because response currently contains only `Instrument`.

- [ ] **Step 3: Skip invalid CSV names and add availability method**

In `freqtrade/freqtrade/research/data_source.py`, add logging:

```python
import logging

logger = logging.getLogger(__name__)
```

Change invalid filename handling:

```python
if match is None:
    logger.warning("Skipping invalid research data filename: %s", path.name)
    continue
```

Add method:

```python
def available_timeframes(self, instrument_key: str) -> list[str]:
    instrument_key = _normalize_a_share_instrument_key(instrument_key)
    prefix = f"{instrument_key}-"
    timeframes = []
    for path in self.root.glob(f"{instrument_key}-*.csv"):
        timeframe = path.stem.removeprefix(prefix)
        if _TIMEFRAME_RE.fullmatch(timeframe):
            timeframes.append(timeframe)
    return sorted(set(timeframes))
```

- [ ] **Step 4: Add response DTO for availability**

In `freqtrade/freqtrade/rpc/api_server/api_schemas.py`, add:

```python
class ResearchInstrumentResponse(Instrument):
    available_timeframes: list[str] = Field(default_factory=list)


class ResearchInstrumentsResponse(BaseModel):
    instruments: list[ResearchInstrumentResponse]
```

Replace the previous `ResearchInstrumentsResponse` definition.

- [ ] **Step 5: Return availability from API**

In `freqtrade/freqtrade/rpc/api_server/api_research.py`, update `research_instruments`:

```python
data_source = _get_local_csv_data_source(profile)
instruments = data_source.list_instruments()
return {
    "instruments": [
        {
            **instrument.model_dump(mode="json"),
            "available_timeframes": data_source.available_timeframes(instrument.key),
        }
        for instrument in instruments
    ]
}
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_data_source.py tests/rpc/test_api_research.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit task**

Run:

```powershell
git add freqtrade/research/data_source.py freqtrade/rpc/api_server/api_schemas.py freqtrade/rpc/api_server/api_research.py tests/research/test_data_source.py tests/rpc/test_api_research.py
git commit -m "fix: make research instrument discovery resilient"
```

---

## Task 5: Research UI Loading, Errors, and Data Credibility

**Fixes:** R-4, B-4 UI impact, B-5 UI impact, A-1 frontend capability use.

**Files:**
- Modify: `frequi/src/types/research.ts`
- Modify: `frequi/src/stores/research.ts`
- Modify: `frequi/src/views/ResearchView.vue`
- Modify: `frequi/src/components/layout/NavBar.vue`
- Modify: `frequi/src/locales/en.ts`
- Modify: `frequi/src/locales/zh-CN.ts`
- Test: `frequi/tests/unit/researchStore.spec.ts`
- Test: `frequi/tests/component/ResearchView.spec.ts`

- [ ] **Step 1: Extend frontend research types**

In `frequi/src/types/research.ts`, add fields:

```ts
export interface ResearchInstrument {
  key: string;
  market: ResearchMarket;
  venue: string;
  symbol: string;
  currency: string;
  asset_type: string;
  display_name?: string | null;
  available_timeframes: string[];
}

export interface ResearchRequestState {
  loading: boolean;
  error: string | null;
}
```

- [ ] **Step 2: Write failing store state tests**

Add to `frequi/tests/unit/researchStore.spec.ts`:

```ts
it('sets chart loading and error state on chart failure', async () => {
  const store = useResearchStore();
  authenticatedApi.post.mockRejectedValueOnce({
    response: { data: { detail: 'Research chart data unavailable' } },
  });

  await expect(
    store.loadChart({
      bot_id: 'a-share-research',
      instrument: '600519.SH',
      timeframe: '1d',
    }),
  ).rejects.toBeTruthy();

  expect(store.chartState.loading).toBe(false);
  expect(store.chartState.error).toBe('Research chart data unavailable');
});

it('prevents duplicate backtest requests while one is in flight', async () => {
  const store = useResearchStore();
  let resolveRequest: (value: unknown) => void = () => {};
  authenticatedApi.post.mockReturnValue(
    new Promise((resolve) => {
      resolveRequest = resolve;
    }),
  );
  const payload = {
    bot_id: 'a-share-research',
    instrument: '600519.SH',
    timeframe: '1d',
    initial_cash: 100000,
    strategy: { type: 'sma_cross' as const, fast: 5, slow: 20 },
  };

  const first = store.runBacktest(payload);
  const second = store.runBacktest(payload);
  resolveRequest({ data: { instrument: '600519.SH', strategy: 'sma_cross', capability: { kind: 'research_backtest', execution: 'none' }, trades: [], equity_curve: [], metrics: {}, signals: [], warnings: [] } });
  await Promise.all([first, second]);

  expect(authenticatedApi.post).toHaveBeenCalledTimes(1);
});
```

Run:

```powershell
pnpm vitest run tests/unit/researchStore.spec.ts
```

Expected: FAIL because request state does not exist.

- [ ] **Step 3: Implement store state**

In `frequi/src/stores/research.ts`, add:

```ts
function errorMessage(error: unknown): string {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof error.response === 'object' &&
    error.response !== null &&
    'data' in error.response &&
    typeof error.response.data === 'object' &&
    error.response.data !== null &&
    'detail' in error.response.data
  ) {
    return String(error.response.data.detail);
  }
  return 'Research request failed.';
}

const botsState = reactive<ResearchRequestState>({ loading: false, error: null });
const instrumentsState = reactive<ResearchRequestState>({ loading: false, error: null });
const chartState = reactive<ResearchRequestState>({ loading: false, error: null });
const backtestState = reactive<ResearchRequestState>({ loading: false, error: null });
```

Wrap each async action with:

```ts
if (chartState.loading) {
  return chartData.value;
}
chartState.loading = true;
chartState.error = null;
try {
  const { data } = await getResearchApi().post<ResearchChartResponse>('/research/chart_candles', payload);
  chartData.value = data;
  return data;
} catch (error) {
  chartState.error = errorMessage(error);
  throw error;
} finally {
  chartState.loading = false;
}
```

Apply the same pattern to bots, instruments, and backtest actions using their own state objects.

- [ ] **Step 4: Write failing component tests**

Add to `frequi/tests/component/ResearchView.spec.ts`:

```ts
it('disables research actions while requests are loading', async () => {
  const { pinia, store } = installResearchStore();
  store.chartState.loading = true;

  const wrapper = mountResearchView(pinia);
  await flushPromises();

  expect(wrapper.find('[data-test="refresh-chart"]').attributes('disabled')).toBeDefined();
});

it('renders research chart errors', async () => {
  const { pinia, store } = installResearchStore();
  store.chartState.error = 'Research chart data unavailable';

  const wrapper = mountResearchView(pinia);
  await flushPromises();

  expect(wrapper.text()).toContain('Research chart data unavailable');
});

it('only shows available timeframes for the selected instrument', async () => {
  const { pinia, store } = installResearchStore();
  store.instruments = [
    {
      key: '600519.SH',
      market: 'a_share',
      venue: 'SSE',
      symbol: '600519',
      currency: 'CNY',
      asset_type: 'equity',
      available_timeframes: ['1d'],
    },
  ];
  store.selectedInstrument = '600519.SH';

  const wrapper = mountResearchView(pinia);
  await flushPromises();

  expect(wrapper.find('[data-test="timeframe-select"]').text()).toContain('1d');
  expect(wrapper.find('[data-test="timeframe-select"]').text()).not.toContain('5m');
});
```

Run:

```powershell
pnpm vitest run tests/component/ResearchView.spec.ts
```

Expected: FAIL until the view uses state and availability.

- [ ] **Step 5: Update ResearchView state rendering**

In `frequi/src/views/ResearchView.vue`, add:

```ts
const selectedInstrumentMeta = computed(() =>
  researchStore.instruments.find(
    (instrument) => instrument.key === researchStore.selectedInstrument,
  ),
);

const timeframeOptions = computed(() =>
  (selectedInstrumentMeta.value?.available_timeframes.length
    ? selectedInstrumentMeta.value.available_timeframes
    : ['1d']
  ).map((value) => ({ label: value, value })),
);

const chartActionDisabled = computed(
  () => !hasSelection.value || researchStore.chartState.loading,
);

const backtestActionDisabled = computed(
  () => !hasSelection.value || researchStore.backtestState.loading,
);
```

Replace the hardcoded `timeframeOptions` constant with the computed version above.

Change button bindings:

```vue
:disabled="chartActionDisabled"
:loading="researchStore.chartState.loading"
```

and:

```vue
:disabled="backtestActionDisabled"
:loading="researchStore.backtestState.loading"
```

Add an inline error block above the chart:

```vue
<UAlert
  v-if="researchStore.chartState.error"
  color="error"
  variant="soft"
  :title="researchStore.chartState.error"
  data-test="research-chart-error"
/>
```

Add basic data credibility text near the chart heading:

```vue
<span class="text-xs text-neutral-500">
  {{ researchStore.chartData?.data_start }} - {{ researchStore.chartData?.data_stop }}
  · {{ adjustment }}
  · {{ researchStore.chartData?.warnings?.join('; ') }}
</span>
```

- [ ] **Step 6: Add front-end capability gating in nav**

In `frequi/src/components/layout/NavBar.vue`, add a computed helper:

```ts
const canOpenResearch = computed(() => botStore.canRunBacktest);
```

Change the research nav item:

```ts
{
  label: t('nav.research'),
  to: '/research',
  visible: canOpenResearch.value,
  icon: 'i-mdi-chart-timeline-variant',
}
```

This is intentionally coarse because the UI cannot know research capabilities until it contacts the selected API. The backend gate remains the source of truth.

- [ ] **Step 7: Run frontend tests**

Run:

```powershell
pnpm vitest run tests/unit/researchStore.spec.ts tests/component/ResearchView.spec.ts
pnpm typecheck
```

Expected: PASS.

- [ ] **Step 8: Commit task**

Run:

```powershell
git add src/types/research.ts src/stores/research.ts src/views/ResearchView.vue src/components/layout/NavBar.vue src/locales/en.ts src/locales/zh-CN.ts tests/unit/researchStore.spec.ts tests/component/ResearchView.spec.ts
git commit -m "fix: add research ui request states"
```

---

## Task 6: Config, Docker, and Local Operational Boundaries

**Fixes:** A-2, P-4, R-5, R-6.

**Files:**
- Add: `ft_userdata/user_data/config.research.example.json`
- Modify: `ft_userdata/user_data/config.example.json`
- Modify: `README.docker.md`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Split example configs**

Create `ft_userdata/user_data/config.research.example.json` from the current research shape. It must contain `research_bots` and webserver-safe minimal Freqtrade fields required for startup.

Remove the `research_bots` block from `ft_userdata/user_data/config.example.json` so the trading example no longer advertises research profiles.

- [ ] **Step 2: Update README setup commands**

In `README.docker.md`, replace:

```powershell
Copy-Item ft_userdata\user_data\config.example.json ft_userdata\user_data\config.json
Copy-Item ft_userdata\user_data\config.example.json ft_userdata\user_data\config.research.json
```

with:

```powershell
Copy-Item ft_userdata\user_data\config.example.json ft_userdata\user_data\config.json
Copy-Item ft_userdata\user_data\config.research.example.json ft_userdata\user_data\config.research.json
```

Add single-service startup examples:

```powershell
docker compose up -d freqtrade
docker compose up -d freqtrade-research
```

- [ ] **Step 3: Add Docker healthchecks**

In `docker-compose.yml`, add this healthcheck to each HTTP service:

```yaml
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8080/api/v1/ping || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
```

`curl` exists in the runtime image because the root `Dockerfile` installs it.

- [ ] **Step 4: Add optional compose profiles**

Add:

```yaml
    profiles: ["trading"]
```

to `freqtrade` and `freqtrade-futures`, and:

```yaml
    profiles: ["research"]
```

to `freqtrade-research`.

Document the consequence in `README.docker.md`:

```powershell
docker compose --profile research up -d
docker compose --profile trading up -d
```

- [ ] **Step 5: Validate compose config**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
docker compose config
```

Expected: command exits successfully and shows healthcheck blocks.

- [ ] **Step 6: Commit task**

Run:

```powershell
git add ft_userdata/user_data/config.example.json ft_userdata/user_data/config.research.example.json README.docker.md docker-compose.yml
git commit -m "config: split research docker defaults"
```

---

## Task 7: Safe Logging and Response Limits

**Fixes:** R-3, part of P-1, part of P-2.

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Modify: `freqtrade/freqtrade/research/backtesting.py`
- Test: `freqtrade/tests/rpc/test_api_research.py`

- [ ] **Step 1: Write failing response limit test**

Add to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_backtest_rejects_too_many_rows(research_client, mocker) -> None:
    dataframe = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5001, freq="1min", tz="UTC"),
            "open": [1.0] * 5001,
            "high": [1.0] * 5001,
            "low": [1.0] * 5001,
            "close": [1.0] * 5001,
            "volume": [1.0] * 5001,
        }
    )
    mocker.patch(
        "freqtrade.rpc.api_server.api_research.LocalCsvResearchDataSource.load_ohlcv",
        return_value=dataframe,
    )

    response = client_post(
        research_client,
        f"{BASE_URI}/research/backtest",
        data={"bot_id": "a-share-local", "instrument": "600519.SH", "timeframe": "1m"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Research backtest input exceeds 5000 rows."
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_backtest_rejects_too_many_rows -q
```

Expected: FAIL because no row limit exists.

- [ ] **Step 2: Add row limits**

In `freqtrade/freqtrade/rpc/api_server/api_research.py`, add:

```python
MAX_RESEARCH_BACKTEST_ROWS = 5000


def _reject_large_backtest_input(row_count: int) -> None:
    if row_count > MAX_RESEARCH_BACKTEST_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"Research backtest input exceeds {MAX_RESEARCH_BACKTEST_ROWS} rows.",
        )
```

Call after timerange filtering and before `run_research_backtest`:

```python
_reject_large_backtest_input(len(dataframe))
```

Chart already has `limit <= 2000`, so do not add a second chart response limit in this task.

- [ ] **Step 3: Add safe error context**

Replace broad chart exception logging:

```python
except Exception as e:
    logger.error(
        "Research chart data unavailable: error_type=%s bot_id=%s instrument=%s timeframe=%s",
        type(e).__name__,
        payload.bot_id,
        payload.instrument,
        payload.timeframe,
    )
    raise HTTPException(status_code=502, detail="Research chart data unavailable")
```

Replace broad backtest exception logging similarly:

```python
except Exception as e:
    logger.error(
        "Research backtest unavailable: error_type=%s bot_id=%s instrument=%s timeframe=%s",
        type(e).__name__,
        request.bot_id,
        request.instrument,
        request.timeframe,
    )
    raise HTTPException(status_code=502, detail="Research backtest unavailable")
```

Do not use `logger.exception` here because existing tests intentionally prevent private local paths from appearing in API-visible logs.

- [ ] **Step 4: Run API tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py -q
```

Expected: PASS, including existing path-leak tests.

- [ ] **Step 5: Commit task**

Run:

```powershell
git add freqtrade/rpc/api_server/api_research.py tests/rpc/test_api_research.py
git commit -m "fix: bound research backtest requests"
```

---

## Full Verification

Run backend:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/markets/test_rules.py tests/research tests/rpc/test_api_research.py -q
.\.venv\Scripts\python -m ruff check freqtrade/markets freqtrade/research freqtrade/rpc/api_server tests/markets tests/research tests/rpc/test_api_research.py
```

Run frontend:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm vitest run tests/unit/researchStore.spec.ts tests/component/ResearchView.spec.ts
pnpm typecheck
pnpm build
```

Run compose validation:

```powershell
cd G:\AI_Trading\freqtrade-cn
docker compose config
```

Run behavior smoke checks after starting research service:

```powershell
docker compose --profile research up -d --build
curl -fsS http://127.0.0.1:8083/api/v1/ping
```

Manual UI checks:

- Open `http://127.0.0.1:8083/research`.
- Confirm only available timeframes appear for `600519.SH`.
- Confirm `qfq/hfq` selections either do not appear or produce a visible unsupported-feature error.
- Confirm chart/backtest buttons disable while requests are in flight.
- Confirm bad `timerange` returns a visible error.

## Execution Order

1. Task 1 first, because it prevents silent wrong research output.
2. Task 2 second, because it fixes market-correctness for intraday backtests.
3. Task 3 third, because changing Research route gating affects API tests and fixtures.
4. Task 4 fourth, because frontend availability depends on backend instrument metadata.
5. Task 5 fifth, because it consumes the backend availability and error semantics.
6. Task 7 can run before or after Task 5, but after Task 1 so timerange filtering exists.
7. Task 6 last, because it changes local operations and should be verified after app behavior is stable.

## Deferred Work

- Full qfq/hfq implementation with adjustment factors and explicit data lineage.
- Full MarketRegistry and pluggable HK/US adapters.
- Backtest job API with pagination/downsampling for equity/signals/trades.
- File-mtime based OHLCV cache and manifest index.
- Separate read-only market-data volume and per-service writable user data directories.
