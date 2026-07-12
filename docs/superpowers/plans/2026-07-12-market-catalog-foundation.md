# Market Catalog Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 market, product, venue, scope, and capability catalog as an authenticated read-only API without changing the behavior of the three legacy services.

**Architecture:** Add immutable catalog domain contracts and a default catalog inside the backend submodule, place repository and SQL persistence behind a narrow control-plane interface, and expose the current snapshot through authenticated `/api/v2/catalog`. Existing v1 research and trading APIs, Compose services, ports, configs, SQLite state, and runtime safety controls remain unchanged.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, SQLAlchemy 2, pytest, Ruff, root standard-library `unittest`, Git submodules, GitHub Actions.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-07-12-multi-market-research-trading-platform-design.md`.
- The migration is backward-compatible; Spot 8081, Futures 8082, and Research 8083 must keep their existing behavior.
- Markets and products are domain objects, not service names.
- Research is a workspace concept; the existing `ResearchBotProfile` name remains only as a v1 compatibility type in this phase.
- Research scope may be broader and read-only; execution authority is not introduced in this phase.
- No live execution path, order path, exchange write, account secret, or `dry_run` behavior changes.
- Planned markets and products must not claim unavailable runtime capability.
- The v2 catalog API is authenticated and read-only.
- The platform SQL boundary is separate from each Freqtrade bot's SQLite database.
- Do not add PostgreSQL, Redis, ClickHouse, TimescaleDB, Kafka, or a distributed scheduler to the runtime Compose stack in this phase.
- Do not add arbitrary Compose, image, command, volume, host-path, port, or secret inputs.
- Existing P0 provenance, immutable launch snapshot, TOCTOU, read-only input, state isolation, health readiness, backup/restore, and emergency controls remain unchanged.
- Use strict RED -> GREEN TDD for every behavior change.
- Commit backend-submodule tasks in the backend repository; update the root gitlink only after the backend task reviews pass.

---

## Phase boundary

Phase 0 is complete through the approved architecture specification. This plan implements only Phase 1. Runtime Registry v2 is a separate plan written after these interfaces pass review.

The Phase 1 deliverable is intentionally read-only:

```text
Domain contracts
  -> default immutable catalog
  -> product capability baseline
  -> repository boundary
  -> authenticated API v2
  -> legacy A-share profile mapping
```

It does not create bots, workspaces, runtime instances, or live capabilities.

## Execution preflight

At the start of implementation, record immutable review bases in the ignored
Subagent-Driven ledger:

```powershell
$env:PHASE1_ROOT_BASE = (git rev-parse HEAD).Trim()
$env:PHASE1_BACKEND_BASE = (git -C freqtrade rev-parse HEAD).Trim()
$env:PHASE1_FRONTEND_BASE = (git -C frequi rev-parse HEAD).Trim()
$env:PHASE1_STRATEGIES_BASE = (git -C freqtrade-strategies rev-parse HEAD).Trim()
"root=$env:PHASE1_ROOT_BASE"
"backend=$env:PHASE1_BACKEND_BASE"
"frontend=$env:PHASE1_FRONTEND_BASE"
"strategies=$env:PHASE1_STRATEGIES_BASE"
```

Expected backend base before execution:

```text
32597d05d1c9388585cf37e6db310b8daad2eaa1
```

If the backend base differs, stop before editing and reconcile the reviewed
branch state. The root base is intentionally captured at execution time because
this plan commit becomes the implementation base.

## File structure

### Backend submodule: `freqtrade/`

- Create `freqtrade/markets/catalog.py`: immutable market, product, venue, scope, and catalog contracts.
- Create `freqtrade/markets/default_catalog.py`: built-in Phase 1 catalog snapshot.
- Create `freqtrade/markets/capability_policy.py`: product-policy capability decisions and reason codes.
- Create `freqtrade/platform/__init__.py`: public control-plane persistence exports.
- Create `freqtrade/platform/catalog_repository.py`: repository protocol, static repository, SQL record, and SQL repository.
- Create `freqtrade/rpc/api_server/api_catalog.py`: authenticated read-only v2 catalog router.
- Create `tests/markets/test_catalog.py`: catalog contract, validation, and default-snapshot tests.
- Create `tests/platform/test_catalog_repository.py`: repository and SQL round-trip tests.
- Create `tests/rpc/test_api_catalog.py`: authentication and response-contract tests.
- Modify `freqtrade/markets/instrument.py`: add the explicit digital-asset market while retaining the legacy `contract` enum value.
- Modify `freqtrade/markets/__init__.py`: export the new contracts.
- Modify `freqtrade/research/profiles.py`: provide an explicit legacy A-share/equity scope mapping without changing v1 response fields.
- Modify `freqtrade/rpc/api_server/api_schemas.py`: add v2 response models only.
- Modify `freqtrade/rpc/api_server/webserver.py`: mount the authenticated v2 router.
- Modify `tests/research/test_profiles.py`: cover legacy scope derivation.
- Modify `tests/rpc/test_api_research.py`: prove the v1 response remains unchanged.

### Root repository

- Modify `.github/workflows/root-safety.yml`: run the Phase 1 backend selectors and Ruff checks.
- Modify `tests/test_root_safety_workflow.py`: require the selectors in the executable backend step and reject comment-only mutations.
- Update the `freqtrade` gitlink after the reviewed backend commits.

---

### Task 1: Immutable market and product contracts

**Files:**
- Create: `freqtrade/freqtrade/markets/catalog.py`
- Modify: `freqtrade/freqtrade/markets/instrument.py`
- Modify: `freqtrade/freqtrade/markets/__init__.py`
- Test: `freqtrade/tests/markets/test_catalog.py`

**Interfaces:**
- Produces: `CatalogStatus`, `ProductType`, `MarketDefinition`, `ProductDefinition`, `VenueDefinition`, `MarketScope`, and `MarketCatalog`.
- Preserves: `MarketType.CONTRACT == "contract"`, `MarketType.A_SHARE`, `MarketType.HK_STOCK`, and `MarketType.US_STOCK`.
- Adds: `MarketType.DIGITAL_ASSET == "digital_asset"`.

- [ ] **Step 1: Write failing domain-contract tests**

Add `freqtrade/tests/markets/test_catalog.py`:

```python
import pytest
from pydantic import ValidationError

from freqtrade.markets import (
    CatalogStatus,
    MarketCatalog,
    MarketDefinition,
    MarketScope,
    MarketType,
    ProductDefinition,
    ProductType,
    VenueDefinition,
)


def test_market_type_adds_digital_asset_without_removing_contract() -> None:
    assert MarketType.DIGITAL_ASSET == "digital_asset"
    assert MarketType.CONTRACT == "contract"


def test_market_catalog_rejects_duplicate_and_dangling_definitions() -> None:
    market = MarketDefinition(
        market_id=MarketType.DIGITAL_ASSET,
        display_name="Digital Assets",
        status=CatalogStatus.ACTIVE,
    )
    product = ProductDefinition(
        market_id=MarketType.DIGITAL_ASSET,
        product_id=ProductType.SPOT,
        display_name="Spot",
        status=CatalogStatus.ACTIVE,
    )

    with pytest.raises(ValidationError, match="duplicate market"):
        MarketCatalog(markets=(market, market), products=(product,), venues=())

    with pytest.raises(ValidationError, match="unknown market"):
        MarketCatalog(
            markets=(),
            products=(product,),
            venues=(),
        )


def test_market_scope_requires_products_and_is_immutable() -> None:
    scope = MarketScope(
        market_id=MarketType.DIGITAL_ASSET,
        product_ids=(ProductType.PERPETUAL,),
        venue_ids=("okx",),
    )

    assert scope.product_ids == (ProductType.PERPETUAL,)
    with pytest.raises(ValidationError, match="at least one product"):
        MarketScope(market_id=MarketType.DIGITAL_ASSET, product_ids=())
    with pytest.raises(ValidationError):
        scope.venue_ids = ("bybit",)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
cd freqtrade
python -m pytest tests/markets/test_catalog.py -q -p no:cacheprovider
```

Expected: collection fails because the catalog exports do not exist and `MarketType.DIGITAL_ASSET` is undefined.

- [ ] **Step 3: Add the explicit market enum**

In `freqtrade/freqtrade/markets/instrument.py`, add one member without changing legacy values:

```python
class MarketType(StrEnum):
    DIGITAL_ASSET = "digital_asset"
    CONTRACT = "contract"
    A_SHARE = "a_share"
    HK_STOCK = "hk_stock"
    US_STOCK = "us_stock"
```

- [ ] **Step 4: Implement the immutable catalog contracts**

Create `freqtrade/freqtrade/markets/catalog.py` with these exact public contracts:

```python
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from freqtrade.markets.instrument import MarketType


class CatalogStatus(StrEnum):
    ACTIVE = "active"
    PLANNED = "planned"
    DISABLED = "disabled"


class ProductType(StrEnum):
    SPOT = "spot"
    MARGIN = "margin"
    PERPETUAL = "perpetual"
    DELIVERY_FUTURE = "delivery_future"
    OPTION = "option"
    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"
    CONVERTIBLE_BOND = "convertible_bond"
    WARRANT = "warrant"
    CBBC = "cbbc"


class CatalogModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class MarketDefinition(CatalogModel):
    market_id: MarketType
    display_name: str = Field(min_length=1)
    status: CatalogStatus


class ProductDefinition(CatalogModel):
    market_id: MarketType
    product_id: ProductType
    display_name: str = Field(min_length=1)
    status: CatalogStatus


class VenueDefinition(CatalogModel):
    venue_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    market_id: MarketType
    display_name: str = Field(min_length=1)
    status: CatalogStatus
    product_ids: tuple[ProductType, ...]


class MarketScope(CatalogModel):
    market_id: MarketType
    product_ids: tuple[ProductType, ...]
    venue_ids: tuple[str, ...] = ()
    instrument_keys: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_products(self) -> "MarketScope":
        if not self.product_ids:
            raise ValueError("market scope requires at least one product")
        return self


class MarketCatalog(CatalogModel):
    schema_version: Literal[1] = 1
    markets: tuple[MarketDefinition, ...]
    products: tuple[ProductDefinition, ...]
    venues: tuple[VenueDefinition, ...]

    @model_validator(mode="after")
    def validate_references(self) -> "MarketCatalog":
        market_ids = [market.market_id for market in self.markets]
        if len(market_ids) != len(set(market_ids)):
            raise ValueError("duplicate market definition")
        product_keys = [
            (product.market_id, product.product_id)
            for product in self.products
        ]
        if len(product_keys) != len(set(product_keys)):
            raise ValueError("duplicate product definition")
        known_markets = set(market_ids)
        known_products = set(product_keys)
        for product in self.products:
            if product.market_id not in known_markets:
                raise ValueError("product references unknown market")
        venue_ids = [venue.venue_id for venue in self.venues]
        if len(venue_ids) != len(set(venue_ids)):
            raise ValueError("duplicate venue definition")
        for venue in self.venues:
            if venue.market_id not in known_markets:
                raise ValueError("venue references unknown market")
            for product_id in venue.product_ids:
                if (venue.market_id, product_id) not in known_products:
                    raise ValueError("venue references unknown product")
        return self

    def products_for(self, market_id: MarketType) -> tuple[ProductDefinition, ...]:
        return tuple(
            product for product in self.products if product.market_id == market_id
        )
```

Add these imports and `__all__` entries in
`freqtrade/freqtrade/markets/__init__.py`:

```python
from freqtrade.markets.catalog import (
    CatalogStatus,
    MarketCatalog,
    MarketDefinition,
    MarketScope,
    ProductDefinition,
    ProductType,
    VenueDefinition,
)
```

```python
    "CatalogStatus",
    "MarketCatalog",
    "MarketDefinition",
    "MarketScope",
    "ProductDefinition",
    "ProductType",
    "VenueDefinition",
```

- [ ] **Step 5: Run focused tests and Ruff**

Run:

```powershell
python -m pytest tests/markets/test_catalog.py tests/markets/test_instrument.py -q -p no:cacheprovider
ruff check freqtrade/markets/catalog.py freqtrade/markets/instrument.py freqtrade/markets/__init__.py tests/markets/test_catalog.py
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 6: Commit the backend task**

```powershell
git add freqtrade/markets/catalog.py freqtrade/markets/instrument.py freqtrade/markets/__init__.py tests/markets/test_catalog.py
git commit -m "feat(markets): add immutable catalog contracts"
```

---

### Task 2: Default catalog and capability baseline

**Files:**
- Create: `freqtrade/freqtrade/markets/default_catalog.py`
- Create: `freqtrade/freqtrade/markets/capability_policy.py`
- Modify: `freqtrade/freqtrade/markets/__init__.py`
- Test: `freqtrade/tests/markets/test_catalog.py`

**Interfaces:**
- Produces: `CapabilityName`, `CapabilityDecision`, `ProductCapabilityPolicy`, `CatalogSnapshot`, and `default_catalog_snapshot() -> CatalogSnapshot`.
- The default snapshot revision is exactly `builtin-market-catalog-v1`.
- A denied capability always has a non-empty stable reason code.

- [ ] **Step 1: Add failing default-snapshot tests**

Append:

```python
from freqtrade.markets import CapabilityName, default_catalog_snapshot


def test_default_catalog_declares_target_markets_without_claiming_live() -> None:
    snapshot = default_catalog_snapshot()

    assert snapshot.revision_id == "builtin-market-catalog-v1"
    assert {market.market_id for market in snapshot.catalog.markets} == {
        MarketType.DIGITAL_ASSET,
        MarketType.A_SHARE,
        MarketType.HK_STOCK,
        MarketType.US_STOCK,
    }
    assert snapshot.capability(
        MarketType.DIGITAL_ASSET,
        ProductType.PERPETUAL,
        CapabilityName.PAPER_TRADING,
    ).allowed is True
    live = snapshot.capability(
        MarketType.DIGITAL_ASSET,
        ProductType.PERPETUAL,
        CapabilityName.LIVE_TRADING,
    )
    assert live.allowed is False
    assert live.reason_code == "live_lane_not_enabled"


def test_planned_product_capability_has_a_reason() -> None:
    snapshot = default_catalog_snapshot()
    decision = snapshot.capability(
        MarketType.US_STOCK,
        ProductType.OPTION,
        CapabilityName.BACKTEST,
    )

    assert decision.allowed is False
    assert decision.reason_code == "market_adapter_not_installed"
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest tests/markets/test_catalog.py -q -p no:cacheprovider
```

Expected: import failure for the capability and default-catalog interfaces.

- [ ] **Step 3: Implement capability contracts**

Create `freqtrade/freqtrade/markets/capability_policy.py`:

```python
from enum import StrEnum

from pydantic import Field, model_validator

from freqtrade.markets.catalog import CatalogModel, ProductType
from freqtrade.markets.instrument import MarketType


class CapabilityName(StrEnum):
    MARKET_DATA = "market_data"
    RESEARCH = "research"
    BACKTEST = "backtest"
    SIMULATION = "simulation"
    PAPER_TRADING = "paper_trading"
    LIVE_TRADING = "live_trading"
    SHORT = "short"
    LEVERAGE = "leverage"
    OPTIONS_CHAIN = "options_chain"
    OPTIONS_BACKTEST = "options_backtest"
    OPTIONS_EXECUTION = "options_execution"
    MANUAL_ORDER = "manual_order"
    AI_ORDER_INTENT = "ai_order_intent"


class CapabilityDecision(CatalogModel):
    allowed: bool
    reason_code: str | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> "CapabilityDecision":
        if self.allowed and self.reason_code is not None:
            raise ValueError("allowed capability cannot have a denial reason")
        if not self.allowed and not self.reason_code:
            raise ValueError("denied capability requires a reason code")
        return self

    @classmethod
    def allow(cls) -> "CapabilityDecision":
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason_code: str) -> "CapabilityDecision":
        return cls(allowed=False, reason_code=reason_code)


class ProductCapabilityPolicy(CatalogModel):
    market_id: MarketType
    product_id: ProductType
    decisions: dict[CapabilityName, CapabilityDecision] = Field(default_factory=dict)

    def decision(self, capability: CapabilityName) -> CapabilityDecision:
        return self.decisions.get(
            capability,
            CapabilityDecision.deny("capability_not_declared"),
        )
```

- [ ] **Step 4: Implement the complete built-in snapshot**

Create `freqtrade/freqtrade/markets/default_catalog.py`. Define all four markets and the product sets in the approved design. Use these exact status rules:

- digital asset, A-share: `ACTIVE`;
- Hong Kong, US: `PLANNED`;
- digital spot and perpetual: `ACTIVE`;
- A-share equity, ETF, index, convertible bond: `ACTIVE`;
- every other initial product: `PLANNED`.

Define:

```python
from functools import cache

from freqtrade.markets.capability_policy import (
    CapabilityDecision,
    CapabilityName,
    ProductCapabilityPolicy,
)
from freqtrade.markets.catalog import (
    CatalogModel,
    CatalogStatus,
    MarketCatalog,
    MarketDefinition,
    ProductDefinition,
    ProductType,
    VenueDefinition,
)
from freqtrade.markets.instrument import MarketType


class CatalogSnapshot(CatalogModel):
    revision_id: str
    catalog: MarketCatalog
    product_policies: tuple[ProductCapabilityPolicy, ...]

    def capability(
        self,
        market_id: MarketType,
        product_id: ProductType,
        capability: CapabilityName,
    ) -> CapabilityDecision:
        for policy in self.product_policies:
            if policy.market_id == market_id and policy.product_id == product_id:
                return policy.decision(capability)
        return CapabilityDecision.deny("product_policy_not_declared")
```

Use these exact declarative rows in the same file:

```python
_MARKET_ROWS = (
    (MarketType.DIGITAL_ASSET, "Digital Assets", CatalogStatus.ACTIVE),
    (MarketType.A_SHARE, "A-Share", CatalogStatus.ACTIVE),
    (MarketType.HK_STOCK, "Hong Kong", CatalogStatus.PLANNED),
    (MarketType.US_STOCK, "US Stock", CatalogStatus.PLANNED),
)

_PRODUCT_ROWS = (
    (MarketType.DIGITAL_ASSET, ProductType.SPOT, "Spot", CatalogStatus.ACTIVE),
    (MarketType.DIGITAL_ASSET, ProductType.MARGIN, "Margin", CatalogStatus.PLANNED),
    (MarketType.DIGITAL_ASSET, ProductType.PERPETUAL, "Perpetual", CatalogStatus.ACTIVE),
    (
        MarketType.DIGITAL_ASSET,
        ProductType.DELIVERY_FUTURE,
        "Delivery Future",
        CatalogStatus.PLANNED,
    ),
    (MarketType.DIGITAL_ASSET, ProductType.OPTION, "Option", CatalogStatus.PLANNED),
    (MarketType.A_SHARE, ProductType.EQUITY, "Equity", CatalogStatus.ACTIVE),
    (MarketType.A_SHARE, ProductType.ETF, "ETF", CatalogStatus.ACTIVE),
    (MarketType.A_SHARE, ProductType.INDEX, "Index", CatalogStatus.ACTIVE),
    (
        MarketType.A_SHARE,
        ProductType.CONVERTIBLE_BOND,
        "Convertible Bond",
        CatalogStatus.ACTIVE,
    ),
    (MarketType.A_SHARE, ProductType.OPTION, "Option", CatalogStatus.PLANNED),
    (MarketType.HK_STOCK, ProductType.EQUITY, "Equity", CatalogStatus.PLANNED),
    (MarketType.HK_STOCK, ProductType.ETF, "ETF", CatalogStatus.PLANNED),
    (MarketType.HK_STOCK, ProductType.INDEX, "Index", CatalogStatus.PLANNED),
    (MarketType.HK_STOCK, ProductType.WARRANT, "Warrant", CatalogStatus.PLANNED),
    (MarketType.HK_STOCK, ProductType.CBBC, "CBBC", CatalogStatus.PLANNED),
    (MarketType.HK_STOCK, ProductType.OPTION, "Option", CatalogStatus.PLANNED),
    (MarketType.US_STOCK, ProductType.EQUITY, "Equity", CatalogStatus.PLANNED),
    (MarketType.US_STOCK, ProductType.ETF, "ETF", CatalogStatus.PLANNED),
    (MarketType.US_STOCK, ProductType.INDEX, "Index", CatalogStatus.PLANNED),
    (MarketType.US_STOCK, ProductType.OPTION, "Option", CatalogStatus.PLANNED),
)

_DIGITAL_PRODUCTS = (
    ProductType.SPOT,
    ProductType.MARGIN,
    ProductType.PERPETUAL,
    ProductType.DELIVERY_FUTURE,
    ProductType.OPTION,
)
```

Build the catalog with these exact helpers:

```python
def _markets() -> tuple[MarketDefinition, ...]:
    return tuple(
        MarketDefinition(
            market_id=market_id,
            display_name=display_name,
            status=status,
        )
        for market_id, display_name, status in _MARKET_ROWS
    )


def _products() -> tuple[ProductDefinition, ...]:
    return tuple(
        ProductDefinition(
            market_id=market_id,
            product_id=product_id,
            display_name=display_name,
            status=status,
        )
        for market_id, product_id, display_name, status in _PRODUCT_ROWS
    )


def _venues() -> tuple[VenueDefinition, ...]:
    return tuple(
        VenueDefinition(
            venue_id=venue_id,
            market_id=MarketType.DIGITAL_ASSET,
            display_name=display_name,
            status=CatalogStatus.ACTIVE,
            product_ids=_DIGITAL_PRODUCTS,
        )
        for venue_id, display_name in (
            ("okx", "OKX"),
            ("binance", "Binance"),
            ("bybit", "Bybit"),
            ("gate", "Gate"),
        )
    )
```

Build every product policy; do not infer availability from catalog presence:

```python
def _deny_all(
    market_id: MarketType,
    product_id: ProductType,
    reason_code: str,
) -> ProductCapabilityPolicy:
    return ProductCapabilityPolicy(
        market_id=market_id,
        product_id=product_id,
        decisions={
            capability: CapabilityDecision.deny(reason_code)
            for capability in CapabilityName
        },
    )


def _policies() -> tuple[ProductCapabilityPolicy, ...]:
    policies: list[ProductCapabilityPolicy] = []
    for market_id, product_id, _display_name, _status in _PRODUCT_ROWS:
        if market_id == MarketType.DIGITAL_ASSET and product_id in {
            ProductType.SPOT,
            ProductType.PERPETUAL,
        }:
            policies.append(
                ProductCapabilityPolicy(
                    market_id=market_id,
                    product_id=product_id,
                    decisions={
                        CapabilityName.MARKET_DATA: CapabilityDecision.allow(),
                        CapabilityName.RESEARCH: CapabilityDecision.allow(),
                        CapabilityName.BACKTEST: CapabilityDecision.allow(),
                        CapabilityName.SIMULATION: CapabilityDecision.allow(),
                        CapabilityName.PAPER_TRADING: CapabilityDecision.allow(),
                        CapabilityName.LIVE_TRADING: CapabilityDecision.deny(
                            "live_lane_not_enabled"
                        ),
                    },
                )
            )
        elif market_id == MarketType.A_SHARE and product_id == ProductType.EQUITY:
            policies.append(
                ProductCapabilityPolicy(
                    market_id=market_id,
                    product_id=product_id,
                    decisions={
                        CapabilityName.MARKET_DATA: CapabilityDecision.allow(),
                        CapabilityName.RESEARCH: CapabilityDecision.allow(),
                        CapabilityName.BACKTEST: CapabilityDecision.allow(),
                        CapabilityName.PAPER_TRADING: CapabilityDecision.deny(
                            "execution_adapter_not_installed"
                        ),
                        CapabilityName.LIVE_TRADING: CapabilityDecision.deny(
                            "execution_adapter_not_installed"
                        ),
                    },
                )
            )
        elif market_id == MarketType.DIGITAL_ASSET and product_id == ProductType.OPTION:
            policies.append(
                _deny_all(market_id, product_id, "options_adapter_not_installed")
            )
        elif market_id in {MarketType.HK_STOCK, MarketType.US_STOCK}:
            policies.append(
                _deny_all(market_id, product_id, "market_adapter_not_installed")
            )
        else:
            policies.append(
                _deny_all(market_id, product_id, "product_adapter_not_installed")
            )
    return tuple(policies)
```

The policy baseline must use these explicit outcomes:

| Scope | Allowed | Denied reason |
|---|---|---|
| digital asset spot/perpetual | market data, research, backtest, simulation, paper | live: `live_lane_not_enabled` |
| A-share equity | market data, research, backtest | paper/live: `execution_adapter_not_installed` |
| digital asset option | none in Phase 1 | `options_adapter_not_installed` |
| Hong Kong and US products | none in Phase 1 | `market_adapter_not_installed` |
| all undeclared capabilities | none | `capability_not_declared` |

Return a cached immutable snapshot:

```python
@cache
def default_catalog_snapshot() -> CatalogSnapshot:
    return CatalogSnapshot(
        revision_id="builtin-market-catalog-v1",
        catalog=MarketCatalog(
            markets=_markets(),
            products=_products(),
            venues=_venues(),
        ),
        product_policies=_policies(),
    )
```

Add these exports to `freqtrade/freqtrade/markets/__init__.py`:

```python
from freqtrade.markets.capability_policy import (
    CapabilityDecision,
    CapabilityName,
    ProductCapabilityPolicy,
)
from freqtrade.markets.default_catalog import (
    CatalogSnapshot,
    default_catalog_snapshot,
)
```

Add the same five public names to `__all__`. Venue presence is descriptive
and does not enable a runtime or live capability.

- [ ] **Step 5: Run focused tests and Ruff**

```powershell
python -m pytest tests/markets/test_catalog.py -q -p no:cacheprovider
ruff check freqtrade/markets/default_catalog.py freqtrade/markets/capability_policy.py freqtrade/markets/__init__.py tests/markets/test_catalog.py
```

Expected: PASS and no Ruff errors.

- [ ] **Step 6: Commit**

```powershell
git add freqtrade/markets/default_catalog.py freqtrade/markets/capability_policy.py freqtrade/markets/__init__.py tests/markets/test_catalog.py
git commit -m "feat(markets): define default catalog capabilities"
```

---

### Task 3: Catalog repository and SQL persistence boundary

**Files:**
- Create: `freqtrade/freqtrade/platform/__init__.py`
- Create: `freqtrade/freqtrade/platform/catalog_repository.py`
- Create: `freqtrade/tests/platform/test_catalog_repository.py`

**Interfaces:**
- Produces: `CatalogRepository.current() -> CatalogSnapshot`.
- Produces: `StaticCatalogRepository` and `SqlCatalogRepository`.
- SQL persistence uses a separate SQLAlchemy `PlatformBase`; it must not import or share Freqtrade trade-model sessions.
- Production database wiring is not enabled in this phase.

- [ ] **Step 1: Write failing repository tests**

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from freqtrade.markets import default_catalog_snapshot
from freqtrade.platform import SqlCatalogRepository, StaticCatalogRepository


def test_static_catalog_repository_returns_the_exact_snapshot() -> None:
    snapshot = default_catalog_snapshot()
    repository = StaticCatalogRepository(snapshot)

    assert repository.current() is snapshot


def test_sql_catalog_repository_round_trips_an_immutable_revision() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = SqlCatalogRepository(engine)
    repository.initialize_schema()
    snapshot = default_catalog_snapshot()

    repository.publish(snapshot, created_at=datetime(2026, 7, 12, tzinfo=UTC))

    assert repository.current() == snapshot
    with pytest.raises(ValueError, match="catalog revision already exists"):
        repository.publish(snapshot, created_at=datetime(2026, 7, 12, tzinfo=UTC))
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/platform/test_catalog_repository.py -q -p no:cacheprovider
```

Expected: import failure for `freqtrade.platform`.

- [ ] **Step 3: Implement the repository boundary**

Create `freqtrade/freqtrade/platform/catalog_repository.py` with:

```python
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import JSON, DateTime, Engine, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from freqtrade.markets import CatalogSnapshot


class CatalogRepository(Protocol):
    def current(self) -> CatalogSnapshot: ...


class StaticCatalogRepository:
    def __init__(self, snapshot: CatalogSnapshot) -> None:
        self._snapshot = snapshot

    def current(self) -> CatalogSnapshot:
        return self._snapshot


class PlatformBase(DeclarativeBase):
    pass


class CatalogRevisionRecord(PlatformBase):
    __tablename__ = "platform_catalog_revisions"

    revision_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class SqlCatalogRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def initialize_schema(self) -> None:
        PlatformBase.metadata.create_all(
            self._engine,
            tables=[CatalogRevisionRecord.__table__],
        )

    def publish(self, snapshot: CatalogSnapshot, *, created_at: datetime) -> None:
        with Session(self._engine) as session:
            if session.get(CatalogRevisionRecord, snapshot.revision_id) is not None:
                raise ValueError("catalog revision already exists")
            session.add(
                CatalogRevisionRecord(
                    revision_id=snapshot.revision_id,
                    payload=snapshot.model_dump(mode="json"),
                    created_at=created_at.astimezone(UTC),
                )
            )
            session.commit()

    def current(self) -> CatalogSnapshot:
        with Session(self._engine) as session:
            record = session.scalar(
                select(CatalogRevisionRecord).order_by(
                    CatalogRevisionRecord.created_at.desc(),
                    CatalogRevisionRecord.revision_id.desc(),
                )
            )
            if record is None:
                raise LookupError("market catalog is not initialized")
            return CatalogSnapshot.model_validate(record.payload)
```

Create `freqtrade/freqtrade/platform/__init__.py`:

```python
from freqtrade.platform.catalog_repository import (
    CatalogRepository,
    SqlCatalogRepository,
    StaticCatalogRepository,
)

__all__ = [
    "CatalogRepository",
    "SqlCatalogRepository",
    "StaticCatalogRepository",
]
```

- [ ] **Step 4: Add empty and revision-order tests**

Add these exact tests:

```python
def test_sql_catalog_repository_requires_an_initialized_snapshot() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = SqlCatalogRepository(engine)
    repository.initialize_schema()

    with pytest.raises(LookupError, match="market catalog is not initialized"):
        repository.current()


def test_sql_catalog_repository_returns_the_latest_revision() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = SqlCatalogRepository(engine)
    repository.initialize_schema()
    first = default_catalog_snapshot()
    second = first.model_copy(update={"revision_id": "builtin-market-catalog-v2"})

    repository.publish(first, created_at=datetime(2026, 7, 12, 1, tzinfo=UTC))
    repository.publish(second, created_at=datetime(2026, 7, 12, 2, tzinfo=UTC))

    assert repository.current() == second
```

- [ ] **Step 5: Run focused tests and Ruff**

```powershell
python -m pytest tests/platform/test_catalog_repository.py -q -p no:cacheprovider
ruff check freqtrade/platform tests/platform/test_catalog_repository.py
```

Expected: PASS and no Ruff errors.

- [ ] **Step 6: Commit**

```powershell
git add freqtrade/platform tests/platform/test_catalog_repository.py
git commit -m "feat(platform): add catalog repository boundary"
```

---

### Task 4: Authenticated read-only Catalog API v2

**Files:**
- Create: `freqtrade/freqtrade/rpc/api_server/api_catalog.py`
- Create: `freqtrade/tests/rpc/test_api_catalog.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/webserver.py`

**Interfaces:**
- Produces: authenticated `GET /api/v2/catalog`.
- Produces: `GET /api/v2/catalog/markets/{market_id}/products`.
- No POST, PUT, PATCH, or DELETE catalog route is added.
- Response revision is exactly `builtin-market-catalog-v1`.

- [ ] **Step 1: Write failing API tests**

Create `tests/rpc/test_api_catalog.py` with this fixture and authentication
helper, followed by the tests below:

```python
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from requests.auth import _basic_auth_str

from freqtrade.enums import RunMode
from freqtrade.loggers import setup_logging, setup_logging_pre
from freqtrade.rpc.api_server import ApiServer


_TEST_USER = "FreqTrader"
_TEST_PASS = "SuperSecurePassword1!"
_JWT_SECRET_KEY = "99980ff8fcf77f21ef610adb46b788c505b8483897bc26203b5591eefe0d15"


@contextmanager
def make_catalog_client(default_conf, mocker):
    default_conf["runmode"] = RunMode.WEBSERVER
    default_conf["api_server"] = {
        "enabled": True,
        "listen_ip_address": "127.0.0.1",
        "listen_port": 8080,
        "CORS_origins": ["http://example.com"],
        "jwt_secret_key": _JWT_SECRET_KEY,
        "username": _TEST_USER,
        "password": _TEST_PASS,
    }
    setup_logging_pre()
    setup_logging(default_conf)
    mocker.patch("freqtrade.rpc.api_server.ApiServer.start_api", MagicMock())
    api_server = ApiServer(default_conf)
    try:
        with TestClient(api_server.app) as client:
            yield client
    finally:
        ApiServer.shutdown()


@pytest.fixture
def catalog_client(default_conf, mocker):
    with make_catalog_client(default_conf, mocker) as client:
        yield client


def authenticated_get(client: TestClient, url: str):
    return client.get(
        url,
        headers={
            "Authorization": _basic_auth_str(_TEST_USER, _TEST_PASS),
            "Origin": "http://example.com",
        },
    )


def test_catalog_v2_requires_authentication(catalog_client) -> None:
    response = catalog_client.get("/api/v2/catalog")

    assert response.status_code == 401


def test_catalog_v2_returns_the_immutable_default_snapshot(catalog_client) -> None:
    response = authenticated_get(catalog_client, "/api/v2/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert payload["revision_id"] == "builtin-market-catalog-v1"
    assert {market["market_id"] for market in payload["catalog"]["markets"]} == {
        "digital_asset",
        "a_share",
        "hk_stock",
        "us_stock",
    }


def test_catalog_v2_lists_products_and_rejects_unknown_market(catalog_client) -> None:
    response = authenticated_get(
        catalog_client,
        "/api/v2/catalog/markets/digital_asset/products",
    )
    assert response.status_code == 200
    assert {item["product_id"] for item in response.json()["products"]} >= {
        "spot",
        "perpetual",
        "option",
    }

    missing = authenticated_get(
        catalog_client,
        "/api/v2/catalog/markets/unknown/products",
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "unknown_market"
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/rpc/test_api_catalog.py -q -p no:cacheprovider
```

Expected: 404 for the new routes.

- [ ] **Step 3: Add response models**

In `api_schemas.py`, add:

```python
class CatalogResponse(BaseModel):
    revision_id: str
    catalog: MarketCatalog
    product_policies: tuple[ProductCapabilityPolicy, ...]


class CatalogProductsResponse(BaseModel):
    market_id: MarketType
    products: tuple[ProductDefinition, ...]
```

Import the domain contracts explicitly from `freqtrade.markets`.

- [ ] **Step 4: Implement the read-only router**

Create `api_catalog.py`:

```python
from fastapi import APIRouter
from fastapi.exceptions import HTTPException

from freqtrade.markets import MarketType, default_catalog_snapshot
from freqtrade.rpc.api_server.api_schemas import (
    CatalogProductsResponse,
    CatalogResponse,
)


router = APIRouter()


@router.get("/catalog", response_model=CatalogResponse)
def catalog() -> CatalogResponse:
    return CatalogResponse(**default_catalog_snapshot().model_dump())


@router.get(
    "/catalog/markets/{market_id}/products",
    response_model=CatalogProductsResponse,
)
def catalog_products(market_id: str) -> CatalogProductsResponse:
    try:
        resolved_market = MarketType(market_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_market", "message": "Unknown market."},
        ) from None
    snapshot = default_catalog_snapshot()
    products = snapshot.catalog.products_for(resolved_market)
    if not any(
        market.market_id == resolved_market
        for market in snapshot.catalog.markets
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_market", "message": "Unknown market."},
        )
    return CatalogProductsResponse(
        market_id=resolved_market,
        products=products,
    )
```

- [ ] **Step 5: Register the authenticated v2 router**

In `webserver.py`, import `api_catalog` beside the other routers and mount:

```python
app.include_router(
    api_catalog,
    prefix="/api/v2",
    tags=["Catalog"],
    dependencies=[Depends(http_basic_or_jwt_token)],
)
```

Do not add `is_research_mode`, `is_trading_mode`, or `is_webserver_mode`; the catalog is a global authenticated read-only resource.

- [ ] **Step 6: Run API and legacy selectors**

```powershell
python -m pytest tests/rpc/test_api_catalog.py tests/rpc/test_api_research.py::test_research_bots_returns_public_profile_without_data_root -q -p no:cacheprovider
ruff check freqtrade/rpc/api_server/api_catalog.py freqtrade/rpc/api_server/api_schemas.py freqtrade/rpc/api_server/webserver.py tests/rpc/test_api_catalog.py
```

Expected: PASS and no Ruff errors.

- [ ] **Step 7: Commit**

```powershell
git add freqtrade/rpc/api_server/api_catalog.py freqtrade/rpc/api_server/api_schemas.py freqtrade/rpc/api_server/webserver.py tests/rpc/test_api_catalog.py
git commit -m "feat(api): expose authenticated market catalog"
```

---

### Task 5: Legacy A-share research scope mapping

**Files:**
- Modify: `freqtrade/freqtrade/research/profiles.py`
- Modify: `freqtrade/freqtrade/research/__init__.py`
- Modify: `freqtrade/tests/research/test_profiles.py`
- Modify: `freqtrade/tests/rpc/test_api_research.py`

**Interfaces:**
- Produces: `research_profile_scope(profile: ResearchBotProfile) -> MarketScope`.
- Existing v1 `GET /api/v1/research/bots` response remains byte-for-field compatible: `id`, `label`, `market`, and `capabilities`; no `product_id`, path, or secret field is added.

- [ ] **Step 1: Write failing compatibility tests**

Append to `test_profiles.py`:

```python
from freqtrade.markets import ProductType
from freqtrade.research import research_profile_scope


def test_legacy_a_share_profile_maps_to_equity_scope(tmp_path) -> None:
    profile = load_research_profiles(
        {
            "user_data_dir": tmp_path,
            "research_bots": [
                {
                    "id": "a-share-local",
                    "label": "A Share Local",
                    "market": "a_share",
                    "data_source": {
                        "type": "local_csv",
                        "root": "research_data/a_share",
                    },
                }
            ],
        }
    )[0]

    scope = research_profile_scope(profile)

    assert scope.market_id == MarketType.A_SHARE
    assert scope.product_ids == (ProductType.EQUITY,)
```

Add to `test_api_research.py`:

```python
def test_research_bots_v1_shape_is_unchanged(research_client) -> None:
    response = client_get(research_client, f"{BASE_URI}/research/bots")

    assert response.status_code == 200
    assert set(response.json()["bots"][0]) == {
        "id",
        "label",
        "market",
        "capabilities",
    }
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/research/test_profiles.py::test_legacy_a_share_profile_maps_to_equity_scope tests/rpc/test_api_research.py::test_research_bots_v1_shape_is_unchanged -q -p no:cacheprovider
```

Expected: import failure for `research_profile_scope`; the v1-shape test passes.

- [ ] **Step 3: Implement the compatibility mapper**

In `profiles.py`:

```python
def research_profile_scope(profile: ResearchBotProfile) -> MarketScope:
    if profile.market == MarketType.A_SHARE:
        return MarketScope(
            market_id=MarketType.A_SHARE,
            product_ids=(ProductType.EQUITY,),
        )
    raise ResearchConfigError(
        f"Unsupported research profile market: {profile.market}"
    )
```

Import `MarketScope` and `ProductType`, and export the function from `research/__init__.py`. Do not modify `ResearchBotProfile` fields or v1 response construction.

- [ ] **Step 4: Run focused and complete research-profile tests**

```powershell
python -m pytest tests/research/test_profiles.py tests/rpc/test_api_research.py -q -p no:cacheprovider
ruff check freqtrade/research/profiles.py freqtrade/research/__init__.py tests/research/test_profiles.py tests/rpc/test_api_research.py
```

Expected: PASS and no Ruff errors.

- [ ] **Step 5: Commit**

```powershell
git add freqtrade/research/profiles.py freqtrade/research/__init__.py tests/research/test_profiles.py tests/rpc/test_api_research.py
git commit -m "refactor(research): map legacy profile scope"
```

---

### Task 6: Root Safety selectors and root gitlink integration

**Files:**
- Modify: `.github/workflows/root-safety.yml`
- Modify: `tests/test_root_safety_workflow.py`
- Modify: root gitlink `freqtrade`

**Interfaces:**
- Root Safety's executable `Run backend P0 regressions` step must run the catalog, repository, API, and legacy-profile selectors.
- The workflow test must fail if selectors appear only in a comment or unrelated step.

- [ ] **Step 1: Add failing workflow assertions**

In `tests/test_root_safety_workflow.py`, add:

```python
MARKET_CATALOG_BACKEND_SELECTORS = (
    "tests/markets/test_catalog.py",
    "tests/platform/test_catalog_repository.py",
    "tests/rpc/test_api_catalog.py",
    "tests/research/test_profiles.py",
)
```

Add:

```python
def test_backend_regressions_execute_market_catalog_selectors(self) -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    step = named_workflow_step(workflow, BACKEND_REGRESSION_STEP)

    for selector in MARKET_CATALOG_BACKEND_SELECTORS:
        with self.subTest(selector=selector):
            self.assertIn(f"            {selector} \\\n", step)


def test_rejects_market_catalog_selector_only_present_in_comment(self) -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    selector = MARKET_CATALOG_BACKEND_SELECTORS[0]
    mutated = workflow.replace(
        f"            {selector} \\\n",
        f"            # {selector} \\\n",
        1,
    )
    step = named_workflow_step(mutated, BACKEND_REGRESSION_STEP)

    self.assertNotIn(f"            {selector} \\\n", step)
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -S -m unittest tests.test_root_safety_workflow.RootSafetyWorkflowTests.test_backend_regressions_execute_market_catalog_selectors -v
```

Expected: FAIL because the workflow does not contain the selectors.

- [ ] **Step 3: Add selectors and Ruff paths to Root Safety**

Extend the backend pytest command before `-q`:

```yaml
            tests/markets/test_catalog.py \
            tests/platform/test_catalog_repository.py \
            tests/rpc/test_api_catalog.py \
            tests/research/test_profiles.py \
```

Extend the existing Ruff command with:

```yaml
            freqtrade/markets/catalog.py \
            freqtrade/markets/default_catalog.py \
            freqtrade/markets/capability_policy.py \
            freqtrade/platform \
            freqtrade/rpc/api_server/api_catalog.py \
            freqtrade/research/profiles.py \
            tests/markets/test_catalog.py \
            tests/platform/test_catalog_repository.py \
            tests/rpc/test_api_catalog.py \
            tests/research/test_profiles.py
```

Keep the standard-library root gate before dependency installation and keep the runtime-dependent selector after backend regression execution.

- [ ] **Step 4: Update the reviewed backend gitlink**

After all backend task reviews pass:

```powershell
git add freqtrade
```

Verify:

```powershell
git diff --cached --submodule=log
```

Expected: only the reviewed backend commit range plus the workflow and workflow-test changes.

- [ ] **Step 5: Run root RED/GREEN and backend selectors**

```powershell
python -S -m unittest tests.test_root_safety_workflow -v
python -S -m unittest discover -s tests -p "test_*.py" -v
cd freqtrade
python -m pytest tests/markets/test_catalog.py tests/platform/test_catalog_repository.py tests/rpc/test_api_catalog.py tests/research/test_profiles.py tests/rpc/test_api_research.py -q -p no:cacheprovider
ruff check freqtrade/markets freqtrade/platform freqtrade/rpc/api_server/api_catalog.py freqtrade/research/profiles.py tests/markets/test_catalog.py tests/platform/test_catalog_repository.py tests/rpc/test_api_catalog.py tests/research/test_profiles.py
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit the root integration**

```powershell
git add .github/workflows/root-safety.yml tests/test_root_safety_workflow.py freqtrade
git commit -m "ci: gate market catalog foundation"
```

---

### Task 7: Phase 1 final verification and review handoff

**Files:**
- No production changes.
- Update only ignored Subagent-Driven reports and progress ledger during execution.

**Interfaces:**
- Produces the exact backend and root commit ranges for independent review.
- Does not push, change PR Draft state, or merge without separate authorization.

- [ ] **Step 1: Verify backend scope and clean state**

```powershell
git -C freqtrade status --short --branch
git -C freqtrade diff --check "$env:PHASE1_BACKEND_BASE..HEAD"
git -C freqtrade log --oneline "$env:PHASE1_BACKEND_BASE..HEAD"
```

Expected: clean backend worktree and only Phase 1 commits.

- [ ] **Step 2: Verify root scope and clean state**

```powershell
git status --short --branch
git diff --check "$env:PHASE1_ROOT_BASE..HEAD"
git diff --stat "$env:PHASE1_ROOT_BASE..HEAD"
git submodule status --recursive
```

Expected: clean root worktree; backend gitlink points to the reviewed backend head; frontend and strategies gitlinks are unchanged.

- [ ] **Step 3: Run the complete local Phase 1 gate**

```powershell
python -S -m unittest discover -s tests -p "test_*.py" -v
cd freqtrade
python -m pytest tests/markets tests/platform/test_catalog_repository.py tests/research/test_profiles.py tests/rpc/test_api_catalog.py tests/rpc/test_api_research.py -q -p no:cacheprovider
ruff check freqtrade/markets freqtrade/platform freqtrade/rpc/api_server/api_catalog.py freqtrade/research/profiles.py tests/markets tests/platform/test_catalog_repository.py tests/rpc/test_api_catalog.py tests/research/test_profiles.py
```

Expected: all commands exit 0.

- [ ] **Step 4: Dispatch independent reviews**

Use Subagent-Driven task review after each task. After Task 6, create an exact review package for:

- backend base to backend head;
- root base to root head.

The final reviewer must separately return:

- specification-compliance verdict;
- code-quality/security verdict;
- compatibility verdict for v1 Research and all three legacy services;
- confirmation that no live/order/runtime behavior changed.

- [ ] **Step 5: Record the Phase 2 entry gate**

Phase 2 planning may begin only when:

- every Task 1-6 review is approved;
- all local gates are green;
- the v2 catalog is authenticated and read-only;
- v1 Research response shape is unchanged;
- default capabilities do not advertise live, Hong Kong, US, or options execution;
- the root and backend exact heads are known.

Publishing, fresh remote recursive checkout, exact-SHA Root Safety, and PR-state changes require a separate authorized publication step.
