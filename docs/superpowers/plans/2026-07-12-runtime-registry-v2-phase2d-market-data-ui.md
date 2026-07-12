
# Phase 2D Market Data, Runtime Access Reads, and UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve Bot-independent canonical candles and full refresh policy through 8090, add closed-policy read access to healthy Bot/Research runtimes, and migrate FreqUI watch/Research reads without losing strategy overlays or multi-timeframe behavior.

**Architecture:** `MarketDataQueryService` owns public candle reads, canonical freshness metadata, TTL/coalescing, and provider adapters. `RuntimeAccessGateway` resolves exact Registry endpoints and signs short-lived instance-bound internal tokens; runtime API middleware verifies a platform public key, target instance, route group, and method. FreqUI authenticates once to platform-control and composes platform base candles with optional runtime-owned overlays.

**Tech Stack:** FastAPI, Pydantic v2, httpx, ccxt public APIs, asyncio, cryptography/PyJWT, Vue 3, Pinia, Axios, Vitest, pytest, Ruff.

## Global Constraints

- Follow the master plan and completed Phase 2A-2C interfaces.
- Public market-data adapters receive no API key, secret, password, or exchange-write capability.
- Base candles remain available when a Bot is stopped.
- Read Gateway accepts named closed routes only, follows no redirects, and never retries to another target.
- Runtime tokens have exact audience `instance_id`, route group, HTTP method, short expiry, unique request ID, and platform signature.
- A runtime can verify tokens but cannot mint tokens for itself or another runtime.
- Refresh policy and forming/closed semantics match the approved specification exactly.
- Strategy/AI/chart refresh is read-only and never triggers execution.

---

## File Structure

### Backend submodule

- Create `freqtrade/platform/market_data_domain.py`: candle/freshness/policy DTOs and read protocol.
- Create `freqtrade/platform/market_data_policy.py`: committed refresh-policy loader.
- Create `freqtrade/platform/market_data_cache.py`: bounded TTL and in-flight coalescing.
- Create `freqtrade/platform/market_data_adapters.py`: closed OKX/Bitget public adapters.
- Create `freqtrade/platform/market_data_service.py`: validation, cache, provider selection.
- Create `freqtrade/platform/runtime_access_domain.py`: named routes, grant claims, stable failures.
- Create `freqtrade/platform/runtime_access_policy.py`: committed read route policy.
- Create `freqtrade/platform/runtime_access_gateway.py`: Registry target resolution and bounded forwarding.
- Create `freqtrade/platform_control/api_market_data.py`, `api_runtime_access.py`, and `chart_service.py`.
- Create `freqtrade/platform_control/policies/market-data-refresh-v1.json`.
- Create `freqtrade/platform_control/policies/runtime-access-read-v1.json`.
- Modify Freqtrade API authentication/dependencies to accept valid platform internal read tokens only on approved routes.
- Add backend tests.

### Frontend submodule

- Create `src/composables/platformLoginInfo.ts` and `platformApi.ts`.
- Create `src/types/platform.ts` and `marketData.ts`.
- Create `src/stores/platform.ts`, `marketData.ts`, and `runtimeAccess.ts`.
- Modify `useLiveChartDataset.ts`, `useResearchChartAutoRefresh.ts`, `research.ts`, and relevant views/types.
- Add unit/component/E2E fixtures and tests.

### Root

- Add platform signing private key/public key bootstrap and exact mounts.
- Extend runtime templates and snapshot policy to mount public key plus instance identity read-only.
- Add CI/Root Safety market-data and read-Gateway gates.

---

### Task 1: Versioned refresh policy and canonical candle contracts

**Files:**
- Create: `freqtrade/freqtrade/platform_control/policies/market-data-refresh-v1.json`
- Create: `freqtrade/freqtrade/platform/market_data_domain.py`
- Create: `freqtrade/freqtrade/platform/market_data_policy.py`
- Modify: `freqtrade/freqtrade/platform/__init__.py`
- Test: `freqtrade/tests/platform/test_market_data_policy.py`
- Test: `freqtrade/tests/platform/test_market_data_domain.py`

**Interfaces:**
- Produces `MarketDataRefreshPolicy`, `RefreshPolicyEntry`, `CanonicalCandle`, `CandleSnapshot`, `MarketDataKey`, `DataFreshness`.
- `60m` canonicalizes to `1h`; unknown timeframes raise `unknown_timeframe`.
- Response carries policy revision and recommended/effective interval.

- [ ] **Step 1: Write RED policy tests**

```python
EXPECTED = {
    "1m": 10_000,
    "3m": 30_000,
    "5m": 60_000,
    "15m": 60_000,
    "30m": 60_000,
    "1h": 180_000,
    "2h": 300_000,
    "4h": 300_000,
    "6h": 600_000,
    "8h": 600_000,
    "12h": 600_000,
    "1d": 900_000,
    "3d": 900_000,
    "1w": 900_000,
    "2w": 900_000,
    "1M": 900_000,
    "1y": 900_000,
}

def test_refresh_policy_matches_existing_ui_contract() -> None:
    policy = load_refresh_policy()
    assert {key: policy.interval_ms(key) for key in EXPECTED} == EXPECTED
    assert policy.interval_ms("60m") == 180_000
    with pytest.raises(UnknownTimeframe, match="unknown_timeframe"):
        policy.interval_ms("unknown")
```

Add DTO tests proving timezone-aware event/ingestion/availability timestamps, exact integer OHLCV timestamps, finite numeric prices, and `forming` mutually exclusive with `closed`.

- [ ] **Step 2: Run RED**

```powershell
cd freqtrade
python -m pytest tests/platform/test_market_data_policy.py tests/platform/test_market_data_domain.py -q -p no:cacheprovider
```

Expected: missing policy/domain.

- [ ] **Step 3: Add committed policy**

```json
{
  "schema_version": 1,
  "revision_id": "market-data-refresh-v1",
  "aliases": {"60m": "1h"},
  "entries": {
    "1m": 10000,
    "3m": 30000,
    "5m": 60000,
    "15m": 60000,
    "30m": 60000,
    "1h": 180000,
    "2h": 300000,
    "4h": 300000,
    "6h": 600000,
    "8h": 600000,
    "12h": 600000,
    "1d": 900000,
    "3d": 900000,
    "1w": 900000,
    "2w": 900000,
    "1M": 900000,
    "1y": 900000
  }
}
```

Loader uses package resources, canonical JSON, `extra="forbid"`, unique aliases, positive intervals, and no user override.

- [ ] **Step 4: Implement canonical DTOs and run GREEN**

```powershell
python -m pytest tests/platform/test_market_data_policy.py tests/platform/test_market_data_domain.py -q -p no:cacheprovider
ruff check freqtrade/platform/market_data_domain.py freqtrade/platform/market_data_policy.py tests/platform/test_market_data_policy.py tests/platform/test_market_data_domain.py
git add freqtrade/platform_control/policies/market-data-refresh-v1.json freqtrade/platform/market_data_domain.py freqtrade/platform/market_data_policy.py freqtrade/platform/__init__.py tests/platform/test_market_data_policy.py tests/platform/test_market_data_domain.py
git commit -m "feat(platform): define canonical market data policy"
```

Expected: complete cadence matrix and contract tests pass.

---

### Task 2: Bounded cache and in-flight request coalescing

**Files:**
- Create: `freqtrade/freqtrade/platform/market_data_cache.py`
- Test: `freqtrade/tests/platform/test_market_data_cache.py`

**Interfaces:**
- Produces async `MarketDataCache.get_or_load(key, max_age_ms, loader)`.
- One loader per exact `MarketDataKey`; waiters share result/exception.
- Bounded entry count, monotonic clock, no stale-as-fresh behavior.

- [ ] **Step 1: Write RED concurrency tests**

```python
@pytest.mark.asyncio
async def test_identical_concurrent_requests_use_one_loader() -> None:
    calls = 0
    release = asyncio.Event()

    async def loader():
        nonlocal calls
        calls += 1
        await release.wait()
        return snapshot()

    first = asyncio.create_task(cache.get_or_load(key(), 10_000, loader))
    second = asyncio.create_task(cache.get_or_load(key(), 10_000, loader))
    release.set()
    assert await first == await second
    assert calls == 1

@pytest.mark.asyncio
async def test_expired_value_is_not_returned_as_fresh() -> None:
    clock.advance(10.001)
    result = await cache.get_or_load(key(), 10_000, new_loader)
    assert result.snapshot_id == "new"
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_market_data_cache.py -q -p no:cacheprovider
```

Expected: missing cache.

- [ ] **Step 3: Implement cache**

Use one `asyncio.Lock`, dictionaries for completed entries and in-flight tasks, `time.monotonic()`, exact key equality, LRU eviction only for completed entries, and `asyncio.shield()` so one cancelled waiter does not cancel the shared upstream call. Exceptions remove the in-flight entry and do not overwrite the last successful entry as fresh.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_market_data_cache.py -q -p no:cacheprovider
ruff check freqtrade/platform/market_data_cache.py tests/platform/test_market_data_cache.py
git add freqtrade/platform/market_data_cache.py tests/platform/test_market_data_cache.py
git commit -m "feat(platform): coalesce market data reads"
```

---

### Task 3: Closed OKX/Bitget public candle adapters and catalog correction

**Files:**
- Create: `freqtrade/freqtrade/platform/market_data_adapters.py`
- Create: `freqtrade/freqtrade/platform_control/policies/digital-asset-instruments-v1.json`
- Modify: `freqtrade/freqtrade/markets/default_catalog.py`
- Test: `freqtrade/tests/platform/test_market_data_adapters.py`
- Test: `freqtrade/tests/markets/test_catalog.py`

**Interfaces:**
- Supports approved public OHLCV only for registered venue/product/instrument/provider-symbol mappings.
- Initial required mappings include OKX perpetual and Bitget spot acceptance instruments.
- Catalog revision advances to `builtin-market-catalog-v2` and includes venue `bitget`.

- [ ] **Step 1: Write RED adapter/security tests**

```python
def test_bitget_is_catalogued_for_spot() -> None:
    snapshot = default_catalog_snapshot()
    bitget = next(v for v in snapshot.catalog.venues if v.venue_id == "bitget")
    assert ProductType.SPOT in bitget.product_ids

@pytest.mark.asyncio
async def test_public_adapter_constructs_exchange_without_credentials(mocker) -> None:
    factory = mocker.patch("ccxt.async_support.bitget")
    await adapter.fetch_candles(bitget_spot_key(), limit=100)
    config = factory.call_args.args[0]
    assert "apiKey" not in config
    assert "secret" not in config
    assert "password" not in config
```

Add tests rejecting unknown venue/product/instrument/timeframe, limit outside `1..1000`, provider redirects, and any config containing credential/write fields.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_market_data_adapters.py tests/markets/test_catalog.py -q -p no:cacheprovider
```

Expected: adapter missing and Bitget catalog assertion fails.

- [ ] **Step 3: Implement closed mappings and adapter**

The committed instrument file maps exact domain IDs to provider symbols; callers never send provider symbols. Adapter factory supports only `okx` and `bitget`, sets `enableRateLimit=True`, disables credential loading, calls `fetch_ohlcv()` only, closes clients in `finally`, rejects non-list/malformed/non-monotonic responses, and converts milliseconds to canonical UTC timestamps.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_market_data_adapters.py tests/markets/test_catalog.py -q -p no:cacheprovider
ruff check freqtrade/platform/market_data_adapters.py freqtrade/markets/default_catalog.py tests/platform/test_market_data_adapters.py tests/markets/test_catalog.py
git add freqtrade/platform/market_data_adapters.py freqtrade/platform_control/policies/digital-asset-instruments-v1.json freqtrade/markets/default_catalog.py tests/platform/test_market_data_adapters.py tests/markets/test_catalog.py
git commit -m "feat(platform): add public digital asset candles"
```

---

### Task 4: MarketDataQueryService and API v2

**Files:**
- Create: `freqtrade/freqtrade/platform/market_data_service.py`
- Create: `freqtrade/freqtrade/platform_control/api_market_data.py`
- Modify: `freqtrade/freqtrade/platform_control/app.py`
- Test: `freqtrade/tests/platform/test_market_data_service.py`
- Test: `freqtrade/tests/platform_control/test_api_market_data.py`

**Interfaces:**
- GET `/api/v2/market-data/candles` with closed catalog IDs, canonical timeframe, bounded limit.
- Returns `CandleSnapshot` including policy/freshness/degradation.
- No exchange write or control DB high-frequency storage.

- [ ] **Step 1: Write RED API/service tests**

```python
def test_candle_api_returns_policy_and_forming_state(client, auth_headers) -> None:
    response = client.get(
        "/api/v2/market-data/candles",
        params={
            "market_id": "digital_asset",
            "product_id": "perpetual",
            "venue_id": "okx",
            "instrument_id": "BTC-USDT-SWAP",
            "timeframe": "1m",
            "limit": 100,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["refresh_policy_revision"] == "market-data-refresh-v1"
    assert payload["recommended_refresh_ms"] == 10_000
    assert payload["candles"][-1]["state"] in {"forming", "closed"}

def test_unknown_timeframe_fails_closed(client, auth_headers) -> None:
    response = client.get(
        "/api/v2/market-data/candles",
        params={**valid_params(), "timeframe": "7m"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_timeframe"
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_market_data_service.py tests/platform_control/test_api_market_data.py -q -p no:cacheprovider
```

Expected: missing service/router.

- [ ] **Step 3: Implement query service and stable failures**

Validation order: catalog capability -> registered venue/product/instrument -> timeframe policy -> bounded limit -> cache -> adapter -> canonical validation -> freshness. Provider/rate-limit/timeout errors return stable codes and retain last successful data only with explicit `stale=true`; never label it fresh.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_market_data_service.py tests/platform_control/test_api_market_data.py -q -p no:cacheprovider
ruff check freqtrade/platform/market_data_service.py freqtrade/platform_control/api_market_data.py tests/platform/test_market_data_service.py tests/platform_control/test_api_market_data.py
git add freqtrade/platform/market_data_service.py freqtrade/platform_control/api_market_data.py freqtrade/platform_control/app.py tests/platform/test_market_data_service.py tests/platform_control/test_api_market_data.py
git commit -m "feat(platform): expose canonical candle queries"
```

---

### Task 5: Closed Runtime Access read policy and instance-bound tokens

**Files:**
- Create: `freqtrade/freqtrade/platform_control/policies/runtime-access-read-v1.json`
- Create: `freqtrade/freqtrade/platform/runtime_access_domain.py`
- Create: `freqtrade/freqtrade/platform/runtime_access_policy.py`
- Create: `freqtrade/freqtrade/platform/runtime_access_tokens.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_auth.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/deps.py`
- Test: `freqtrade/tests/platform/test_runtime_access_policy.py`
- Test: `freqtrade/tests/platform/test_runtime_access_tokens.py`
- Test: `freqtrade/tests/rpc/test_runtime_access_auth.py`

**Interfaces:**
- Named read groups: `bot_status_read`, `bot_logs_read`, `bot_chart_read`, `research_catalog_read`, `research_chart_read`.
- Internal token claims: issuer, audience instance ID, attempt ID, route group, method, request ID, issued/expiry.
- Runtime validates platform Ed25519 public key and its immutable instance/attempt identity.

- [ ] **Step 1: Write RED token confusion tests**

```python
def test_token_for_one_instance_cannot_target_another(keypair) -> None:
    token = issue_runtime_token(
        private_key=keypair.private,
        instance_id="runtime-a",
        attempt_id="attempt-a-1",
        route_group="bot_status_read",
        method="GET",
        request_id="request-1",
    )
    with pytest.raises(RuntimeAccessDenied, match="runtime_access_audience_mismatch"):
        verify_runtime_token(
            token,
            public_key=keypair.public,
            expected_instance_id="runtime-b",
            expected_attempt_id="attempt-b-1",
            route_group="bot_status_read",
            method="GET",
        )

def test_research_identity_cannot_receive_bot_route(policy) -> None:
    assert policy.authorize(
        owner_kind="workspace_worker",
        environment="paper",
        route_group="bot_status_read",
        method="GET",
    ).code == "runtime_route_owner_denied"
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_runtime_access_policy.py tests/platform/test_runtime_access_tokens.py tests/rpc/test_runtime_access_auth.py -q -p no:cacheprovider
```

Expected: missing policy/token middleware.

- [ ] **Step 3: Add exact read policy**

Each policy entry contains route ID, owner kinds, environments, methods, fixed upstream path, request/response size limit, timeout, and retry mode. The compatibility read inventory is explicit:

```text
GET  /ping
GET  /trades
GET  /status
GET  /locks
GET  /pair_candles
POST /pair_candles
POST /chart_candles
GET  /pair_history
POST /pair_history
GET  /plot_config
GET  /strategies
GET  /strategy/{strategy_name}
GET  /freqaimodels
GET  /hyperopt-loss
GET  /exchanges
GET  /available_pairs
GET  /markets
GET  /performance
GET  /entries
GET  /exits
GET  /mix_tags
GET  /profit_all
GET  /profit
GET  /whitelist
GET  /blacklist
GET  /daily
GET  /weekly
GET  /monthly
GET  /balance
GET  /historic_balance
GET  /show_config
GET  /logs
GET  /pairlists/available
GET  /pairlists/evaluate/{job_id}
GET  /background/{job_id}
GET  /background
GET  /recursive_analysis/{job_id}
GET  /lookahead_analysis/{job_id}
GET  /trades/{trade_id}/custom-data
GET  /sysinfo
GET  /backtest
GET  /backtest/history
GET  /backtest/history/result
GET  /backtest/history/{filename}/market_change
GET  /backtest/history/{filename}/{strategy_name}/wallet
GET  /research/bots
GET  /research/instruments
GET  /research/datasets
POST /research/chart_candles
```

Read retry is at most once and only before any response bytes; no redirect following. POST routes in this list are schema-validated reads and must be proven side-effect-free. `GET /backtest/abort` is intentionally excluded because its behavior is a write and belongs to Phase 2E's never-retry policy. A contract test compares this list with read calls in `frequi/src/stores/ftbot.ts` and `frequi/src/stores/research.ts`. The policy contains no arbitrary host/port.

Use EdDSA JWT with maximum 30-second lifetime. Private key exists only in platform-control exact secret mount; runtimes mount public key read-only. Tokens are never returned to the browser or logged.

- [ ] **Step 4: Add runtime verification dependency**

Gateway-authenticated internal requests carry the token in a dedicated Authorization bearer flow. Middleware validates signature/issuer/audience/attempt/route/method/expiry before calling the route. Existing user Basic/JWT behavior remains unchanged on pre-cutover endpoints.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_runtime_access_policy.py tests/platform/test_runtime_access_tokens.py tests/rpc/test_runtime_access_auth.py -q -p no:cacheprovider
ruff check freqtrade/platform/runtime_access_domain.py freqtrade/platform/runtime_access_policy.py freqtrade/platform/runtime_access_tokens.py freqtrade/rpc/api_server/api_auth.py freqtrade/rpc/api_server/deps.py tests/platform/test_runtime_access_policy.py tests/platform/test_runtime_access_tokens.py tests/rpc/test_runtime_access_auth.py
git add freqtrade/platform_control/policies/runtime-access-read-v1.json freqtrade/platform/runtime_access_domain.py freqtrade/platform/runtime_access_policy.py freqtrade/platform/runtime_access_tokens.py freqtrade/rpc/api_server/api_auth.py freqtrade/rpc/api_server/deps.py tests/platform/test_runtime_access_policy.py tests/platform/test_runtime_access_tokens.py tests/rpc/test_runtime_access_auth.py
git commit -m "feat(platform): authenticate instance-bound runtime reads"
```

---

### Task 6: Runtime Access Gateway read forwarding

**Files:**
- Create: `freqtrade/freqtrade/platform/runtime_access_gateway.py`
- Create: `freqtrade/freqtrade/platform_control/api_runtime_access.py`
- Modify: `freqtrade/freqtrade/platform_control/app.py`
- Test: `freqtrade/tests/platform/test_runtime_access_gateway.py`
- Test: `freqtrade/tests/platform_control/test_api_runtime_access.py`

**Interfaces:**
- Routes contain instance ID plus named route ID and typed payload only.
- Resolves healthy active attempt and exact internal endpoint from Registry.
- Records request/result metadata without bodies/tokens/secrets.
- Stable failures: `runtime_unavailable`, `runtime_identity_mismatch`, `runtime_route_denied`, `runtime_upstream_timeout`.

- [ ] **Step 1: Write RED forwarding/security tests**

```python
@pytest.mark.asyncio
async def test_gateway_uses_registry_endpoint_not_request_target(gateway, httpx_mock) -> None:
    result = await gateway.read(
        instance_id="runtime-a",
        route_id="bot_status",
        caller_target="http://evil.invalid",
    )
    assert result.code == "request_field_forbidden"
    assert httpx_mock.get_requests() == []

@pytest.mark.asyncio
async def test_stopped_runtime_has_no_fallback(gateway, httpx_mock) -> None:
    gateway.repository.return_value = stopped_instance()
    result = await gateway.read("runtime-a", "bot_status")
    assert result.code == "runtime_unavailable"
    assert httpx_mock.get_requests() == []
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_runtime_access_gateway.py tests/platform_control/test_api_runtime_access.py -q -p no:cacheprovider
```

Expected: missing gateway/router.

- [ ] **Step 3: Implement exact resolution and forwarding**

Load instance/attempt/endpoint in one consistent read transaction. Require healthy, non-latched, exact endpoint attempt/spec/network identity. Construct target from repository-owned alias + fixed internal port + policy-owned path. Use `httpx.AsyncClient(follow_redirects=False)`, bounded connect/read/write/pool timeouts, response-size cap, and header allowlist. Strip hop-by-hop, Cookie, upstream Authorization, Host, and forwarding headers. Mint one internal token per request.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_runtime_access_gateway.py tests/platform_control/test_api_runtime_access.py -q -p no:cacheprovider
ruff check freqtrade/platform/runtime_access_gateway.py freqtrade/platform_control/api_runtime_access.py tests/platform/test_runtime_access_gateway.py tests/platform_control/test_api_runtime_access.py
git add freqtrade/platform/runtime_access_gateway.py freqtrade/platform_control/api_runtime_access.py freqtrade/platform_control/app.py tests/platform/test_runtime_access_gateway.py tests/platform_control/test_api_runtime_access.py
git commit -m "feat(platform): proxy governed runtime reads"
```

---

### Task 7: Platform chart composition with optional strategy overlay

**Files:**
- Create: `freqtrade/freqtrade/platform_control/chart_service.py`
- Create: `freqtrade/freqtrade/platform_control/api_chart.py`
- Test: `freqtrade/tests/platform_control/test_chart_service.py`
- Test: `freqtrade/tests/platform_control/test_api_chart.py`

**Interfaces:**
- POST `/api/v2/charts/live` accepts market/product/venue/instrument/timeframe/limit and optional runtime instance ID.
- Always loads platform base candles.
- Optional healthy Bot read adds strategy layers/signals; failure adds warning without clearing base.
- Refresh never triggers strategy evaluation.

- [ ] **Step 1: Write RED overlay degradation tests**

```python
@pytest.mark.asyncio
async def test_stopped_bot_keeps_base_chart(chart_service) -> None:
    chart_service.market_data.return_value = base_snapshot()
    chart_service.runtime_access.return_value = RuntimeAccessFailure("runtime_unavailable")

    result = await chart_service.live_chart(request(runtime_id="runtime-a"))

    assert len(result.data) == len(base_snapshot().candles)
    assert result.meta.layers[0].source == "market"
    assert "Strategy overlay unavailable" in result.warnings

def test_chart_route_has_no_order_or_strategy_evaluation_dependency(app) -> None:
    dependencies = route_dependencies(app, "/api/v2/charts/live")
    assert "OrderIntent" not in dependencies
    assert "StrategyEvaluator" not in dependencies
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform_control/test_chart_service.py tests/platform_control/test_api_chart.py -q -p no:cacheprovider
```

Expected: missing chart service/router.

- [ ] **Step 3: Implement composition**

Convert canonical candles into existing chart-compatible base columns. Read existing Bot `chart_candles` only through named `bot_chart_read`; extract only strategy/decision/execution layers and align by instrument/timeframe/open/data-as-of. Mark forming/provisional versus closed/confirmed. Never present recomputed data as decision snapshot.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/platform_control/test_chart_service.py tests/platform_control/test_api_chart.py tests/rpc/test_chart_data.py tests/rpc/test_chart_composition.py -q -p no:cacheprovider
ruff check freqtrade/platform_control/chart_service.py freqtrade/platform_control/api_chart.py tests/platform_control/test_chart_service.py tests/platform_control/test_api_chart.py
git add freqtrade/platform_control/chart_service.py freqtrade/platform_control/api_chart.py tests/platform_control/test_chart_service.py tests/platform_control/test_api_chart.py
git commit -m "feat(platform): compose live charts independently of bots"
```

---

### Task 8: FreqUI platform session and market-data stores

**Files:**
- Create: `frequi/src/composables/platformLoginInfo.ts`
- Create: `frequi/src/composables/platformApi.ts`
- Create: `frequi/src/types/platform.ts`
- Create: `frequi/src/types/marketData.ts`
- Create: `frequi/src/stores/platform.ts`
- Create: `frequi/src/stores/marketData.ts`
- Create: `frequi/src/stores/runtimeAccess.ts`
- Test: `frequi/tests/unit/platformApi.spec.ts`
- Test: `frequi/tests/unit/marketDataStore.spec.ts`
- Test: `frequi/tests/unit/runtimeAccessStore.spec.ts`

**Interfaces:**
- Platform API defaults to same-origin `/api/v2`; development override is one validated loopback URL.
- `marketDataStore.loadLiveChart()` coalesces exact keys and stores applied refresh interval/policy/freshness.
- Runtime access store accepts instance ID + named route; no URL/port field.

- [ ] **Step 1: Write RED frontend tests**

```ts
it('uses one platform api and never a bot url for base candles', async () => {
  await store.loadLiveChart(request);
  expect(platformApi.post).toHaveBeenCalledWith('/charts/live', request);
  expect(botApi.post).not.toHaveBeenCalled();
});

it('stores the server applied refresh interval', async () => {
  platformApi.post.mockResolvedValue({ data: fixture({ recommended_refresh_ms: 10_000 }) });
  await store.loadLiveChart(request);
  expect(store.refreshIntervalMs).toBe(10_000);
});
```

- [ ] **Step 2: Run RED**

```powershell
cd frequi
pnpm exec vitest run tests/unit/platformApi.spec.ts tests/unit/marketDataStore.spec.ts tests/unit/runtimeAccessStore.spec.ts
```

Expected: missing modules/stores.

- [ ] **Step 3: Implement platform client/stores**

Reuse the current access/refresh token behavior with `/api/v2/token/login` and `/api/v2/token/refresh`; do not mark a Bot offline on platform network errors. The request type has only catalog IDs, timeframe, limit, and optional `runtime_instance_id`. Key serialization is deterministic and in-flight requests coalesce.

- [ ] **Step 4: Run GREEN, typecheck, lint, and commit frontend task**

```powershell
pnpm exec vitest run tests/unit/platformApi.spec.ts tests/unit/marketDataStore.spec.ts tests/unit/runtimeAccessStore.spec.ts
pnpm typecheck
pnpm exec eslint --quiet src/composables/platformLoginInfo.ts src/composables/platformApi.ts src/types/platform.ts src/types/marketData.ts src/stores/platform.ts src/stores/marketData.ts src/stores/runtimeAccess.ts tests/unit/platformApi.spec.ts tests/unit/marketDataStore.spec.ts tests/unit/runtimeAccessStore.spec.ts
git add src/composables/platformLoginInfo.ts src/composables/platformApi.ts src/types/platform.ts src/types/marketData.ts src/stores/platform.ts src/stores/marketData.ts src/stores/runtimeAccess.ts tests/unit/platformApi.spec.ts tests/unit/marketDataStore.spec.ts tests/unit/runtimeAccessStore.spec.ts
git commit -m "feat(ui): add platform market data client"
```

---

### Task 9: Migrate live charts and Research reads to 8090

**Files:**
- Modify: `frequi/src/composables/useLiveChartDataset.ts`
- Modify: `frequi/src/composables/useResearchChartAutoRefresh.ts`
- Modify: `frequi/src/stores/research.ts`
- Modify: `frequi/src/views/TradingView.vue`
- Modify: `frequi/src/views/ChartsView.vue`
- Modify: `frequi/src/views/ResearchView.vue`
- Modify: `frequi/src/utils/tradeChartRefresh.ts`
- Test: existing and new frontend unit/component/E2E tests.

**Interfaces:**
- Visible chart schedules with server policy; current local map is bootstrap fallback only.
- Hidden page pauses; visibility resume refreshes immediately.
- Research reads use named Runtime Access routes, not `activeBot.api`.
- Bot stop preserves base chart and marks overlay unavailable.

- [ ] **Step 1: Add RED compatibility tests**

```ts
it.each([
  ['1m', 10_000], ['3m', 30_000], ['5m', 60_000], ['15m', 60_000],
  ['30m', 60_000], ['1h', 180_000], ['60m', 180_000], ['2h', 300_000],
  ['4h', 300_000], ['6h', 600_000], ['8h', 600_000], ['12h', 600_000],
  ['1d', 900_000], ['3d', 900_000], ['1w', 900_000], ['2w', 900_000],
  ['1M', 900_000], ['1y', 900_000],
])('preserves %s cadence through platform policy', async (timeframe, expected) => {
  platformApi.post.mockResolvedValue({ data: chartFixture(timeframe, expected) });
  await store.loadLiveChart(chartRequest(timeframe));
  expect(store.refreshIntervalMs).toBe(expected);
});

it('keeps base candles when runtime overlay is unavailable', async () => {
  platformApi.post.mockResolvedValue({ data: baseOnlyFixture('runtime_unavailable') });
  await wrapper.vm.refreshAll();
  expect(wrapper.find('[data-test="candle-chart"]').exists()).toBe(true);
  expect(wrapper.text()).toContain('Strategy overlay unavailable');
});
```

Add Research test proving no active Bot API client is required.

- [ ] **Step 2: Run RED**

```powershell
pnpm exec vitest run tests/unit/tradeChartRefresh.spec.ts tests/unit/useLiveChartDataset.spec.ts tests/unit/useResearchChartAutoRefresh.spec.ts tests/unit/researchStore.spec.ts tests/component/TradingViewLiveChart.spec.ts tests/component/ChartsViewLiveChart.spec.ts tests/component/ResearchView.spec.ts
```

Expected: tests fail because current stores use active Bot APIs/local-only cadence.

- [ ] **Step 3: Implement migration**

`useLiveChartDataset` requests `/charts/live` through market-data store and schedules from response policy, falling back to the exact current map only before first successful response. `research.ts` uses platform Runtime Access named routes and selected Workspace Worker instance ID. Preserve manual refresh, loading de-duplication, hidden-tab pause, zoom state, existing chart response shape, and backtest manual-only behavior.

- [ ] **Step 4: Run GREEN, build, and commit frontend task**

```powershell
pnpm exec vitest run tests/unit/tradeChartRefresh.spec.ts tests/unit/useLiveChartDataset.spec.ts tests/unit/useResearchChartAutoRefresh.spec.ts tests/unit/researchStore.spec.ts tests/component/TradingViewLiveChart.spec.ts tests/component/ChartsViewLiveChart.spec.ts tests/component/ResearchView.spec.ts
pnpm typecheck
pnpm lint-ci
pnpm build
git add src/composables/useLiveChartDataset.ts src/composables/useResearchChartAutoRefresh.ts src/stores/research.ts src/views/TradingView.vue src/views/ChartsView.vue src/views/ResearchView.vue src/utils/tradeChartRefresh.ts tests
git commit -m "feat(ui): route live research charts through platform control"
```

---

### Task 10: Signing material, Root Safety, and Phase 2D integration

**Files:**
- Modify: `tools/bootstrap_runtime.py`
- Modify: `ops/runtime-policies/mount-policies.json`
- Modify: `tools/runtime_snapshot.py`
- Modify: `.github/workflows/root-safety.yml`
- Modify: `tests/test_root_safety_workflow.py`
- Create: `tests/test_runtime_access_signing.py`
- Create: `docs/operations/runtime-access-gateway.md`
- Update backend/frontend gitlinks.

**Interfaces:**
- Platform-control mounts exact Ed25519 private key; runtimes mount public key only.
- Root Safety runs full cadence, adapter no-credential, Gateway confusion, runtime-token, frontend base-without-Bot, and no-write-trigger selectors.

- [ ] **Step 1: Write RED root signing/mount tests**

```python
def test_runtime_mount_contains_public_key_not_private_key(self) -> None:
    snapshot = compile_snapshot(application_runtime())
    rendered = json.dumps(snapshot, sort_keys=True)
    self.assertIn("runtime_access_public_key", rendered)
    self.assertNotIn("runtime_access_private_key", rendered)

def test_platform_control_has_private_key_but_no_bot_secret_root(self) -> None:
    service = render_compose()["services"]["platform-control"]
    rendered = json.dumps(service, sort_keys=True)
    self.assertIn("runtime_access_private_key", rendered)
    self.assertNotIn("ft_userdata/secrets/freqtrade/", rendered)
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_access_signing tests.test_root_safety_workflow -v
```

Expected: missing signing contract/gates.

- [ ] **Step 3: Implement bootstrap/mount/CI**

Generate Ed25519 pair only during explicit bootstrap; harden private key, publish fixed public key, never rotate silently, and record non-secret key ID. Add executable CI selectors and mutation tests. Document routes, token claims, target resolution, timeouts, stable errors, logs/audit redaction, and emergency disable.

- [ ] **Step 4: Verify Phase 2D and commit root integration**

```powershell
python -S -m unittest tests.test_runtime_access_signing tests.test_runtime_access_network tests.test_root_safety_workflow -v
Push-Location freqtrade
python -m pytest tests/platform/test_market_data_policy.py tests/platform/test_market_data_cache.py tests/platform/test_market_data_adapters.py tests/platform/test_market_data_service.py tests/platform/test_runtime_access_policy.py tests/platform/test_runtime_access_tokens.py tests/platform/test_runtime_access_gateway.py tests/platform_control/test_api_market_data.py tests/platform_control/test_api_runtime_access.py tests/platform_control/test_chart_service.py tests/rpc/test_runtime_access_auth.py -q -p no:cacheprovider
ruff check freqtrade/platform freqtrade/platform_control tests/platform tests/platform_control tests/rpc/test_runtime_access_auth.py
Pop-Location
Push-Location frequi
pnpm exec vitest run tests/unit/platformApi.spec.ts tests/unit/marketDataStore.spec.ts tests/unit/runtimeAccessStore.spec.ts tests/unit/useLiveChartDataset.spec.ts tests/unit/useResearchChartAutoRefresh.spec.ts tests/unit/researchStore.spec.ts tests/component/TradingViewLiveChart.spec.ts tests/component/ResearchView.spec.ts
pnpm typecheck
pnpm lint-ci
pnpm build
Pop-Location
git add tools/bootstrap_runtime.py ops/runtime-policies/mount-policies.json tools/runtime_snapshot.py .github/workflows/root-safety.yml tests/test_root_safety_workflow.py tests/test_runtime_access_signing.py docs/operations/runtime-access-gateway.md freqtrade frequi
git commit -m "ci: gate phase2d market data and runtime reads"
```

Expected: all offline backend/frontend/root gates pass and worktree is clean.
