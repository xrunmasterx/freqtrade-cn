# ADR: Bind Backtest comparisons to bounded execution-context evidence

**Date:** 2026-07-31

**Status:** accepted for implementation after five independent design Gates

## Context

Retained DataSnapshot replay holds the admitted standard market rows constant, and
Backtest Strategy Evidence identifies the captured primary source and supported resolved
parameters. The standard engine still initializes the current software libraries,
effective simulation settings, pair evaluation order, exchange markets, fees, precision,
limits, Futures options, and leverage tiers. A candidate result can therefore change even
when its data and intended strategy change are controlled.

The user does not yet need an environment registry or restoration system. The immediate
decision is narrower: may a baseline-versus-candidate metric delta remain eligible for
strategy attribution, or is it confounded by changed or unknown execution context?

## Decision

Add optional `Backtest Execution Context Evidence v1` to the existing Backtest Revision
Receipt. The actual `Backtesting` instance owns a single-assignment
`seal_execution_context(data)` operation. Both the CLI `Backtesting.start()` path and the
active API background path call it immediately after their own `load_bt_data()` returns
and before prior-result reuse, strategy lifecycle callbacks, or indicator evaluation. The
API may retrieve the sealed artifact but may not construct it.

The persisted submanifest is deliberately small:

| Field | Meaning |
|---|---|
| `schema_version` | Evidence schema, initially `1` |
| `canonicalization` | `freqtrade-backtest-execution-context-evidence-v1` |
| `hash_algorithm` | `sha256` |
| `core_runtime_scope` | `freqtrade_python_numeric_exchange_versions_v1` |
| `effective_config_scope` | `standard_backtest_effective_config_v1` |
| `exchange_simulation_scope` | `admitted_pair_exchange_simulation_v1` |
| `core_runtime_id` | Domain-separated digest of the fixed runtime-version allowlist |
| `effective_config_id` | Domain-separated digest of the effective simulation allowlist |
| `exchange_simulation_id` | Domain-separated digest of admitted-pair exchange facts |
| `evidence_id` | Domain-separated digest of the preceding manifest fields |

Only these scopes and component identities are persisted in the receipt, sidecar, result,
and history. The canonical component payloads are sealed in memory and discarded after
hashing. They contain no free-form config, raw exchange response, `info` blob, credential,
URL, path, environment variable, host, user, network, container, repository, Runtime
Registry, or mutable operational identifier.

V1 admits only standard non-FreqAI Spot or Futures Backtests with
`enable_dynamic_pairlist=false`. Dynamic PairList execution is rejected with
`execution_context_evidence_dynamic_pairlist_unsupported`: the engine may refresh and
reorder its whitelist on every main candle, so an initial pair list is not the executed
order trace. For Futures Cross Margin, scalar `dry_run_wallet` and an object containing at
most the effective proxy currency are admitted; an object containing any other currency
is rejected before `Wallets(...)` construction with
`execution_context_evidence_cross_margin_wallet_conversion_unsupported`. V1 does not add
an exchange-rate snapshot, ticker dependency, order trace, random-state capture, or
PairList replay.

### Evidence ownership

The three comparison axes must not hash the same intended-change value under different
meanings:

| Owner | V1/V2 responsibility |
|---|---|
| DataSnapshot | Exact admitted standard market-data routes and rows, including timeframe and candle-type route metadata |
| Backtest Strategy Evidence v2 | Primary source, hyperopt parameter values, and every Freqtrade-resolved strategy execution setting listed below |
| Backtest Execution Context Evidence v1 | Curated runtime versions, static evaluated-pair order, external simulation controls, and loaded admitted-pair exchange facts |
| Backtest Revision Receipt | Experiment/request correlation and Freqtrade Run ID; not a fallback context identity |

Execution-context capture therefore server-forces Strategy Evidence v2. Its
`parameter_scope` is `resolved_freqtrade_strategy_parameters_v2`; the canonical parameter
payload retains the existing named hyperopt parameter spaces and adds the exact resolved
values read from the executing `IStrategy` for:

- `minimal_roi`, `timeframe`, `stoploss`, `trailing_stop`,
  `trailing_stop_positive`, `trailing_stop_positive_offset`, and
  `trailing_only_offset_is_reached`;
- `use_custom_stoploss`, `use_custom_roi`, `process_only_new_candles`, `order_types`,
  `order_time_in_force`, `stake_currency`, `stake_amount`,
  `startup_candle_count`, and `unfilledtimeout`;
- `use_exit_signal`, `exit_profit_only`, `ignore_roi_if_entry_signal`,
  `exit_profit_offset`, `disable_dataframe_checks`,
  `ignore_buying_expired_candle_after`, `position_adjustment_enable`,
  `max_entry_position_adjustment`, `max_open_trades`, `can_short`, and the exact
  `protections` list supplied to `ProtectionManager` when protections are enabled.

Appendix B is the complete normative v2 schema, payload, digest, lifecycle, and
compatibility contract. Existing Strategy Evidence v1 remains loadable. A new
context-bound result always uses a validated v2 artifact, so an intended change to one of
these values changes the strategy axis and does not independently change the context axis.

### Core-runtime scope

The fixed v1 payload is defined normatively in Appendix A. It contains Freqtrade version,
Python implementation/version/cache tag, and fixed distribution-version keys for CCXT,
NumPy, pandas, SciPy, TA-Lib, technical, and ft-pandas-ta. Version discovery uses
`importlib.metadata.version()` with those exact distribution names and does not import or
enumerate optional modules. This is a declared diagnostic scope, not dependency closure, a
package inventory, an SBOM, or exact native build attestation. Missing required version
facts fail requested capture.

### Effective-config scope

The fixed v1 payload is defined normatively in Appendix A. It contains only the static
ordered evaluated pairs, literal false dynamic-pairlist state, actual fee, effective
starting-capital mode/value, effective wallet proxy currency and wallet-allocation
controls, protection/position-stacking toggles, amount reserve, and applicable Futures
liquidation/funding controls. It contains no strategy-resolved value, pairlist
implementation/configuration, timeframe, timerange, candle route, storage path,
export/notes/logging/API setting, credential, or replay source filename.

### Exchange-simulation scope

The fixed v1 payload is defined normatively in Appendix A. It contains the loaded exchange
class/id/name, trading and margin modes, precision modes, exactly four applicable Futures
options, and a sorted safe projection of only evaluated pairs from `exchange._markets`.
Futures additionally binds the already loaded parsed `exchange._leverage_tiers` for those
pairs. The builder never accesses the lazy `exchange.markets` property, reloads markets,
fetches exchange state, or constructs a second Exchange.

Canonical JSON uses UTF-8, sorted object keys, compact separators, finite JSON values, and
normalizes negative zero. Component and aggregate SHA-256 inputs use the exact separate
domain prefixes in Appendix A. Market-map insertion order is canonicalized by sorting
projected entries by pair. Evaluated pair order and parsed leverage-tier list order are
preserved because the engine consumes both semantically.

## Comparison and UI policy

API 2.55 adds `capture_execution_context_evidence`. Updated FreqUI requests it
automatically for supported, non-FreqAI, non-dynamic revision-bound Backtests. Retention
and replay force it server-side and receive the same admission errors if their current run
is dynamic or otherwise unsupported. There is no checkbox: unlike retained row payload,
this evidence has no material user-selected storage lifecycle.

The evidence remains orthogonal to schema-1/schema-2 data state and to strategy evidence:

- fewer than two results, or any missing, malformed, or unsupported evidence, is
  `UNKNOWN`;
- valid unequal evidence IDs are `DIFFERENT`;
- valid equal evidence IDs are `SAME CAPTURED SCOPE`.

Result, history, selector, and comparison surfaces show the aggregate state and the three
component states. `DIFFERENT` or `UNKNOWN` is confounded and ineligible for attribution,
ranking, learning, or promotion as strategy improvement. `SAME CAPTURED SCOPE` is only
eligible for later robustness analysis; it does not prove causality or generalization.

## Consequences

- Spot and Futures are supported without changing exchange initialization or adding
  network behavior.
- Existing API 2.54 and older clients, legacy results, and schema-1/schema-2 receipts
  without this optional field remain loadable and show `UNKNOWN`.
- Capture failure produces no bound receipt or artifact. Requested capture forces a fresh
  Backtesting instance and bypasses prior-result reuse.
- The engine rejects unsupported Cross Margin object wallets before `Wallets(...)` can
  request a conversion rate or ticker. It does not attempt to capture or replay exchange
  conversion state.
- Every exported context-bound run uses the existing ZIP-first temporary publication
  protocol before atomic metadata/latest-pointer publication, including ordinary capture
  and replay without re-retention. Failure removes the new temporary/final artifacts and
  does not replace the prior latest pointer.
- The writer includes the evidence submanifest when deriving `revision_id`, but current
  read paths do not recompute that outer ID. V1 therefore makes no read-side outer-binding
  claim. Backend schema and FreqUI strictly recompute only the evidence aggregate ID from
  its persisted manifest; component payloads were deliberately discarded.
- Imported strategy helpers, arbitrary strategy I/O, FreqAI/model state, random/time
  behavior, native-library/CPU differences outside the declared version scope, mutable
  external services, and complete dependency/build identity remain unbound.
- Equal evidence does not guarantee equal results, complete reproducibility, environment
  restoration, artifact authenticity, Paper eligibility, contract-trading safety, or
  future profitability.

## Rejected alternatives

- **Persist the complete effective config or sanitized config:** it leaks operational
  context, still misses arbitrary secrets and resolved runtime facts, and creates a broad
  unstable contract.
- **Persist raw markets/options or exchange responses:** it exposes unbounded provider
  payloads and unrelated instruments while adding no comparison decision.
- **Reuse RuntimeSpec, Docker identity, Phase 2D snapshots, or Paper probe artifacts:**
  those describe different execution journeys and would falsely make Runtime/Paper
  infrastructure authoritative for standard Backtesting.
- **Capture all installed packages, host details, or an SBOM:** noisy, path-sensitive,
  fingerprinting-prone, incomplete for native/import closure, and unnecessary for this
  comparison gate.
- **Capture dynamic PairList config, seed, RNG state, or per-candle order:** configuration
  alone is not the executed trace; a complete trace/replay format is a separate feature.
  V1 fails closed instead.
- **Restore the source environment now:** this would require artifact trust, environment
  lifecycle, exchange emulation, StrategyRelease, and Runtime policy far beyond the
  current user decision.

## Appendix A: normative v1 identity contract

This appendix is normative. A field not listed here does not participate in v1 identity.
All component payloads exist only long enough to canonicalize and hash them.

### A.1 Canonical scalar and container rules

- `string` means a non-empty Python `str`, serialized byte-for-byte as JSON without
  trimming, path expansion, case folding, or fallback conversion.
- `integer` means Python `int` with `bool` rejected.
- `finite_number` means Python `int | float` with `bool`, NaN, and infinities rejected,
  serialized as `float(value)`, with either signed zero serialized as `0.0`.
- `boolean` means Python `bool`; `nullable_*` additionally permits JSON `null`.
- Enum sources serialize their `.value` string.
- Fixed objects contain exactly the keys in these tables. Source mapping keys not on the
  positive allowlist are ignored; missing required inputs fail capture. Lists preserve
  order unless a table explicitly says they are sorted.
- Canonical bytes are `json.dumps(payload, ensure_ascii=False, allow_nan=False,
  separators=(",", ":"), sort_keys=True).encode("utf-8")`. There is no `default=`,
  `str(value)`, repr, or other fallback.

Stable failures are `execution_context_evidence_source_missing` for an absent required
input, `execution_context_evidence_not_canonical` for a wrong type/value,
`execution_context_evidence_missing_dependency` for a required distribution version,
`execution_context_evidence_dynamic_pairlist_unsupported` for dynamic PairList,
`execution_context_evidence_trading_mode_unsupported` outside Spot/Futures, and
`execution_context_evidence_payload_too_large` for the bounds in A.7. A second requested
seal fails with `execution_context_evidence_already_sealed`; the capture-disabled method
is a no-op. Futures Cross Margin object wallets containing a currency other than
`exchange.get_proxy_coin()` fail before `Wallets(...)` construction with
`execution_context_evidence_cross_margin_wallet_conversion_unsupported`. A Futures
exchange class that overrides the dry-run liquidation formula without declaring whether
that formula consumes the bounded taker rate fails with
`execution_context_evidence_liquidation_formula_unsupported`.

### A.2 Core-runtime payload

The component object has exactly these fields:

| Serialized key | Authoritative source | Type/rule |
|---|---|---|
| `schema_version` | literal `1` | integer |
| `scope` | literal `freqtrade_python_numeric_exchange_versions_v1` | string |
| `freqtrade_version` | `freqtrade.__version__` | string |
| `python.implementation` | `sys.implementation.name` | string |
| `python.version` | `platform.python_version()` | string |
| `python.cache_tag` | `sys.implementation.cache_tag` | string |
| `distributions.ccxt` | `importlib.metadata.version("ccxt")` | string |
| `distributions.numpy` | `importlib.metadata.version("numpy")` | string |
| `distributions.pandas` | `importlib.metadata.version("pandas")` | string |
| `distributions.scipy` | `importlib.metadata.version("scipy")` | string |
| `distributions.ta_lib` | `importlib.metadata.version("TA-Lib")` | string |
| `distributions.technical` | `importlib.metadata.version("technical")` | string |
| `distributions.ft_pandas_ta` | `importlib.metadata.version("ft-pandas-ta")` | string |

The distribution map is fixed; no installed-package enumeration or optional-module import
is permitted.

### A.3 Effective-config payload

The component object has exactly these fields:

| Serialized key | Authoritative source at the seal point | Type/rule |
|---|---|---|
| `schema_version` | literal `1` | integer |
| `scope` | literal `standard_backtest_effective_config_v1` | string |
| `evaluated_pair_order` | `list(data.keys())` returned by `load_bt_data()` | non-empty ordered unique list of strings |
| `dynamic_pairlist` | `backtesting.dynamic_pairlist` | must be literal `false` |
| `fee` | `backtesting.fee` | finite_number |
| `capital.mode` | `available_capital` iff that key exists in `backtesting.config`, otherwise `dry_run_wallet` | exact string literal |
| `capital.starting_balance` | `backtesting.starting_balance` | finite_number |
| `capital.wallet_proxy_currency` | the value returned by `backtesting.exchange.get_proxy_coin()` and used to admit/construct `Wallets` | string |
| `capital.initial_proxy_wallet_free` | `backtesting.wallets.get_free(capital.wallet_proxy_currency)` at the seal point, before any simulated trade | finite_number |
| `capital.tradable_balance_ratio` | `null` in `available_capital` mode, otherwise `backtesting.config["tradable_balance_ratio"]` | nullable finite_number |
| `capital.amend_last_stake_amount` | `backtesting.config["amend_last_stake_amount"]` | boolean |
| `capital.last_stake_amount_min_ratio` | configured value only when amendment is true, otherwise `null` | nullable finite_number |
| `position_stacking` | `backtesting._position_stacking` | boolean |
| `protections_enabled` | `backtesting.enable_protections` | boolean |
| `amount_reserve_percent` | `backtesting.config.get("amount_reserve_percent", DEFAULT_AMOUNT_RESERVE_PERCENT)` | finite_number |
| `liquidation_buffer` | `backtesting.exchange.liquidation_buffer` for Futures, otherwise `null` | nullable finite_number |
| `futures_funding_rate` | `backtesting.config.get("futures_funding_rate")` for Futures, otherwise `null` | nullable finite_number |

Pairlist handler names/configuration are excluded because only static execution is admitted
and the resulting ordered universe is captured. Data route/timeframe/timerange/candle-type
facts remain owned by DataSnapshot. Every Strategy Evidence v2 value remains excluded.

The proxy currency is resolved once by the engine before wallet construction and retained
for both wallet admission and the later payload. In Futures Cross Margin, a scalar
`dry_run_wallet` is normalized by `Wallets` into that currency. For object form, every key
must equal that currency; otherwise capture fails before `Wallets.__init__()` calls
`update()`. Spot and Isolated Futures keep their current wallet behavior. The raw wallet
mapping and any conversion rate or ticker are not serialized.

`available_capital` does not replace the initial proxy-wallet balance in the engine:
`Wallets.get_available_stake_amount()` clamps the available-capital total against current
free proxy currency. The one finite `initial_proxy_wallet_free` scalar therefore remains
part of every mode's context even though it is often redundant with the dry-wallet
starting balance. It is read from the already-constructed Backtest `Wallets` at the seal
point, reveals no other currency, and adds no conversion, ticker, or exchange call.

### A.4 Exchange-simulation top-level payload

The component object has exactly these fields:

| Serialized key | Authoritative source | Type/rule |
|---|---|---|
| `schema_version` | literal `1` | integer |
| `scope` | literal `admitted_pair_exchange_simulation_v1` | string |
| `exchange_class` | `f"{type(exchange).__module__}.{type(exchange).__qualname__}"` | string |
| `exchange_id` | `exchange.id` | string |
| `exchange_name` | `exchange.name` | string |
| `trading_mode` | `exchange.trading_mode.value` | exact `spot` or `futures` |
| `margin_mode` | `exchange.margin_mode.value` | `null` for Spot; exact `cross` or `isolated` for Futures |
| `precision_mode` | `backtesting.precision_mode` | integer |
| `precision_mode_price` | `backtesting.precision_mode_price` | integer |
| `options` | A.5 | fixed object |
| `markets` | A.5 | one entry per evaluated pair, sorted by `pair` |
| `leverage_tiers` | A.6 | one entry per evaluated Futures pair, sorted by `pair`; empty for Spot |

The builder reads `exchange._markets` directly after normal engine loading. Missing
evaluated markets fail capture; it must not touch the lazy `exchange.markets` property.

### A.5 Options and admitted-market projection

`options` has exactly four keys. For Spot, the three strings are `null` and
`uses_leverage_tiers` is `false`. For Futures their sources and types are:

| Serialized key | Authoritative source | Type/rule |
|---|---|---|
| `funding_fee_timeframe` | `exchange.get_option("funding_fee_timeframe")` | string |
| `mark_ohlcv_timeframe` | `exchange.get_option("mark_ohlcv_timeframe")` | string |
| `mark_ohlcv_price` | `exchange.get_option("mark_ohlcv_price")` | string |
| `uses_leverage_tiers` | `exchange.get_option("uses_leverage_tiers", True)` | boolean |

Each `markets` entry has exactly this fixed shape. `market` below is
`exchange._markets[pair]`; absent optional CCXT keys normalize to `null`.

| Serialized key | Source | Type/rule |
|---|---|---|
| `pair` | evaluated-pair dictionary key | string |
| `symbol` | `market["symbol"]` | string |
| `base`, `quote`, `settle`, `type` | same-named `market.get(...)` | nullable string |
| `active`, `spot`, `margin`, `swap`, `future`, `option`, `linear`, `inverse` | same-named `market.get(...)` | nullable boolean |
| `contract_size` | `market.get("contractSize")` | nullable finite_number |
| `liquidation_taker_rate` | the engine-owned frozen value described below | nullable finite_number |
| `precision.amount`, `precision.price` | `market.get("precision", {}).get(...)` | nullable finite_number |
| `limits.amount.min`, `limits.amount.max` | `market.get("limits", {}).get("amount", {}).get(...)` | nullable finite_number |
| `limits.price.min`, `limits.price.max` | `market.get("limits", {}).get("price", {}).get(...)` | nullable finite_number |
| `limits.cost.min`, `limits.cost.max` | `market.get("limits", {}).get("cost", {}).get(...)` | nullable finite_number |
| `limits.leverage.min`, `limits.leverage.max` | `market.get("limits", {}).get("leverage", {}).get(...)` | nullable finite_number |

Market map/provider order is not semantic; the projected list is sorted by `pair`.
Unrelated markets and every unlisted field, including `info`, raw maker/taker blobs, URLs,
and provider-specific extensions, are ignored.

`liquidation_taker_rate` binds only the narrow fee input used by the current dry-run
liquidation formula. It is `null` for Spot and for a Futures implementation that does not
consume that input. The current implementation declaration is exact:

| Dry-run liquidation implementation | Declaration |
|---|---|
| base `Exchange.dry_run_liquidation_price` | consumes the rate |
| `Bitget.dry_run_liquidation_price` | consumes the rate |
| `Binance`, `Bybit`, and `Hyperliquid` overrides | does not consume the rate |

Every class that overrides the formula must explicitly declare one of those two states;
there is no inherited guess for a new override. When the rate is consumed, the seal
resolves it from already-loaded state using the engine's current expression exactly:
`exchange._markets[pair]["taker"] or
exchange._api.describe().get("fees", {}).get("trading", {}).get("taker", 0.001)`.
`describe()` is local CCXT metadata, not an exchange request. The finite result is stored
in a single-assignment per-pair map on the executing Exchange. The base and Bitget
liquidation implementations call one small helper that returns this frozen value while
capture is active; when capture is disabled the helper preserves the current expression.
The context builder and later simulation therefore cannot resolve different rates. This
does not create a general fee model and does not bind entry/exit trading fees.

### A.6 Parsed leverage-tier projection

Spot serializes `leverage_tiers: []`. Futures serializes one object
`{"pair": pair, "tiers": [...]}` for each evaluated pair, sorted by pair. If
`uses_leverage_tiers` is true, `exchange._leverage_tiers[pair]` must exist and be non-empty.
If false and no entry exists, `tiers` is empty; an existing loaded entry is still bound.

Each tier preserves its engine list position and has exactly:

| Serialized key | Parsed tier source | Type/rule |
|---|---|---|
| `min_notional` | `tier["minNotional"]` | finite_number |
| `max_notional` | `tier["maxNotional"]` | nullable finite_number |
| `maintenance_margin_rate` | `tier["maintenanceMarginRate"]` | finite_number |
| `max_leverage` | `tier["maxLeverage"]` | finite_number |
| `maintenance_amount` | `tier["maintAmt"]` | nullable finite_number |

Tier order is identity because `get_max_leverage()` and reverse tier lookup iterate the
loaded list. Duplicate rows are neither removed nor rejected; their positions remain part
of the canonical array.

### A.7 Bounds, digests, and load-time validation

- At most 1,000 evaluated pairs and 50,000 total parsed tier rows are admitted.
- The sum of the three canonical component payloads must not exceed 16 MiB.
- Construction is one fixed-depth pass, `O(pairs + tiers)`, with no recursion over
  provider-controlled objects, package scan, import of optional numeric modules, market
  reload, fetch, or second Exchange.

Component IDs are:

| ID | Exact SHA-256 input |
|---|---|
| `core-runtime-<hex>` | `b"freqtrade-backtest-core-runtime-id-v1\0" + core_runtime_bytes` |
| `effective-config-<hex>` | `b"freqtrade-backtest-effective-config-id-v1\0" + effective_config_bytes` |
| `exchange-simulation-<hex>` | `b"freqtrade-backtest-exchange-simulation-id-v1\0" + exchange_simulation_bytes` |

The aggregate identity payload is exactly the persisted manifest fields
`schema_version`, `canonicalization`, `hash_algorithm`, `core_runtime_scope`,
`effective_config_scope`, `exchange_simulation_scope`, `core_runtime_id`,
`effective_config_id`, and `exchange_simulation_id`, excluding `evidence_id`. Its ID is:

`execution-context-evidence-<sha256(b"freqtrade-backtest-execution-context-evidence-id-v1\0" + canonical_manifest_bytes)>`.

Backend models forbid extra persisted fields, validate exact literals/prefixes, and
recompute this aggregate ID. FreqUI applies the same strict aggregate validation before
showing a comparison state. Because component payloads are intentionally absent after the
seal, load paths validate component-ID shape but do not claim to recompute component
digests.

## Appendix B: normative Strategy Evidence v2 contract

This appendix is normative for every Strategy Evidence artifact newly captured by the
API 2.55 implementation. Existing stored v1 artifacts remain valid under their unchanged
contract; they are never relabeled or upgraded in place.

### B.1 Persisted manifest and version dispatch

The v2 persisted manifest contains exactly:

| Field | Required value |
|---|---|
| `schema_version` | integer literal `2` |
| `canonicalization` | `freqtrade-backtest-strategy-evidence-v2` |
| `hash_algorithm` | `sha256` |
| `strategy` | executing `strategy.get_strategy_name()`, non-empty string |
| `source_scope` | `primary_strategy_module` |
| `parameter_scope` | `resolved_freqtrade_strategy_parameters_v2` |
| `source_digest` | `strategy-source-` plus 64 lowercase hex |
| `parameters_digest` | `strategy-parameters-` plus 64 lowercase hex |
| `evidence_id` | `strategy-evidence-` plus 64 lowercase hex |

Backend and frontend models dispatch on `schema_version` and define a discriminated union
of exact v1 and v2 models. Both versions forbid extra or missing fields, validate their own
literal canonicalization and scope, and recompute their own evidence ID. A v1 manifest is
validated only with the existing v1 domain and payload rules. A v2 manifest is validated
only with this appendix. There is no permissive model containing mixed v1/v2 literals.

After API 2.55 is advertised, every newly built Strategy Evidence artifact is v2.
Schema-1/schema-2 revision receipts containing stored v1 evidence remain loadable.
Comparing v1 with v2 cannot yield strategy `SAME`, even if their source digests happen to
match. Every receipt containing `execution_context_evidence` must contain valid Strategy
Evidence v2 for the same strategy; otherwise revision validation and binding fail with
`execution_context_strategy_evidence_v2_required`.

### B.2 Canonical parameter payload

The byte payload hashed by `parameters_digest` has exactly this nesting:

```json
{
  "schema_version": 2,
  "strategy": "<executing strategy name>",
  "parameter_scope": "resolved_freqtrade_strategy_parameters_v2",
  "resolved_parameters": {
    "parameters": {
      "<space>": {
        "<parameter name>": "<canonical parameter value>"
      }
    },
    "settings": {
      "minimal_roi": {},
      "timeframe": "",
      "stoploss": 0.0,
      "max_open_trades": -1.0,
      "trailing": {
        "trailing_stop": false,
        "trailing_stop_positive": null,
        "trailing_stop_positive_offset": 0.0,
        "trailing_only_offset_is_reached": false
      },
      "use_custom_stoploss": false,
      "use_custom_roi": false,
      "process_only_new_candles": true,
      "order_types": {},
      "order_time_in_force": {},
      "stake_currency": "",
      "stake_amount": 0.0,
      "startup_candle_count": 0,
      "unfilledtimeout": {},
      "use_exit_signal": true,
      "exit_profit_only": false,
      "ignore_roi_if_entry_signal": false,
      "exit_profit_offset": 0.0,
      "disable_dataframe_checks": false,
      "ignore_buying_expired_candle_after": 0.0,
      "position_adjustment_enable": false,
      "max_entry_position_adjustment": -1.0,
      "can_short": false,
      "protections": []
    }
  }
}
```

The values in this example are shape illustrations, not defaults. Every key shown is
required, and no other key is allowed at these fixed object levels.

Canonical bytes use the same exact JSON operation as A.1. Only named hyperopt parameter
values use recursive canonicalization. They permit JSON null, bool, string, Python int,
finite Python float, list/tuple, or string-keyed dict. Signed zero becomes `0.0`; fallback
conversion, set ordering, enum/repr, NaN, and infinities are rejected with
`strategy_evidence_parameters_not_canonical`. Settings and protections use the fixed
positive allowlists below and never enter this open recursive path.

`strategy.enumerate_parameters()` is read after `ft_bot_start()` has loaded resolved
hyperopt values. Each yielded name and `parameter.space` must be a non-empty string.
`parameter.value` is normalized by the preceding rule. A duplicate `(space, name)` fails
with `strategy_evidence_duplicate_parameter`; iteration order is not identity because the
result is a canonical object map.

### B.3 Exact resolved-setting sources and types

Except for `protections`, every source below is read exactly once into the pending
engine-owned snapshot immediately after `_set_strategy()` has attached DataProvider and
Wallets, forced `order_types["stoploss_on_exchange"] = false`, and completed
`strategy.ft_bot_start()`, but before indicator evaluation.

| Serialized key | Authoritative source | Type/rule |
|---|---|---|
| `minimal_roi` | `strategy.minimal_roi` | object whose source keys are non-negative Python integers (bool rejected), serialized as decimal strings, and whose values are finite numbers |
| `timeframe` | `strategy.timeframe` | non-empty string |
| `stoploss` | `strategy.stoploss` | finite_number |
| `max_open_trades` | `strategy.max_open_trades` | finite_number, or positive infinity normalized to `-1.0`; bool rejected |
| `trailing.trailing_stop` | `strategy.trailing_stop` | boolean |
| `trailing.trailing_stop_positive` | `strategy.trailing_stop_positive` | nullable finite_number |
| `trailing.trailing_stop_positive_offset` | `strategy.trailing_stop_positive_offset` | finite_number |
| `trailing.trailing_only_offset_is_reached` | `strategy.trailing_only_offset_is_reached` | boolean |
| `use_custom_stoploss` | `strategy.use_custom_stoploss` | boolean |
| `use_custom_roi` | `strategy.use_custom_roi` | boolean |
| `process_only_new_candles` | `strategy.process_only_new_candles` | boolean |
| `order_types` | `strategy.order_types` after the engine's Backtest override | exact B.3.1 fixed object |
| `order_time_in_force` | `strategy.order_time_in_force` | exact B.3.1 fixed object |
| `stake_currency` | `strategy.stake_currency` | non-empty string |
| `stake_amount` | `strategy.stake_amount` | literal string `unlimited` or finite_number |
| `startup_candle_count` | `strategy.startup_candle_count` | non-negative integer |
| `unfilledtimeout` | `strategy.unfilledtimeout` | exact B.3.1 fixed object |
| `use_exit_signal` | `strategy.use_exit_signal` | boolean |
| `exit_profit_only` | `strategy.exit_profit_only` | boolean |
| `ignore_roi_if_entry_signal` | `strategy.ignore_roi_if_entry_signal` | boolean |
| `exit_profit_offset` | `strategy.exit_profit_offset` | finite_number |
| `disable_dataframe_checks` | `strategy.disable_dataframe_checks` | boolean |
| `ignore_buying_expired_candle_after` | `strategy.ignore_buying_expired_candle_after` | finite_number; bool rejected |
| `position_adjustment_enable` | `strategy.position_adjustment_enable` | boolean |
| `max_entry_position_adjustment` | `strategy.max_entry_position_adjustment` | finite_number; bool rejected |
| `can_short` | `strategy.can_short` | boolean |
| `protections` | B.4 | ordered list of exact method-specific fixed objects |

The table is the complete v2 settings allowlist. It does not capture arbitrary strategy
attributes, imported-helper closure, callback return traces, random/time/network state, or
custom I/O. A source-code change that introduces such behavior remains visible only in the
primary-source digest; equal v2 evidence is not a determinism claim.

#### B.3.1 Fixed order-setting allowlists

These three maps never accept arbitrary keys:

- `order_types` requires `entry`, `exit`, `stoploss`, and
  `stoploss_on_exchange`. The first three are exact `limit` or `market`, and
  `stoploss_on_exchange` is boolean. Optional keys are `force_exit`, `force_entry`, and
  `emergency_exit` with the same two string literals; `stoploss_price_type` with exact
  `last`, `mark`, or `index`; and `stoploss_on_exchange_interval` and
  `stoploss_on_exchange_limit_ratio` as finite numbers. The Backtest-forced
  `stoploss_on_exchange: false` is the captured value.
- `order_time_in_force` contains exactly required `entry` and `exit`. Each value is one of
  `GTC`, `FOK`, `IOC`, `PO`, or its lowercase form.
- `unfilledtimeout` may contain only `entry`, `exit`, `exit_timeout_count`, and `unit`.
  The three numeric values are finite numbers and `unit`, when present, is exact
  `minutes` or `seconds`. An empty object remains valid where the existing Webserver path
  supplies no timeout configuration.

A missing required key, unknown key, wrong type, or unsupported literal fails with
`strategy_evidence_settings_unsupported`. The failure occurs before artifact or ZIP
creation; unknown values are neither ignored nor serialized.

### B.4 Protection and capture lifecycle

Strategy Evidence v2 uses a two-stage engine-owned capture so the evidence is both
post-`ft_bot_start()` and identical to the protection configuration the engine consumes:

1. `_set_strategy_list()` captures immutable primary-module source bytes before any
   strategy lifecycle callback, as v1 already does.
2. `_set_strategy()` completes the normal Backtest override and `ft_bot_start()`, then
   canonicalizes the parameter map and every B.3 setting except `protections` into a
   pending snapshot. These values are not reread when the artifact is finalized.
3. If protections are disabled, the engine appends literal `protections: []` and finalizes
   the v2 artifact before indicator evaluation.
4. If protections are enabled, `_load_protections()` evaluates
   `strategy.protections` exactly once at its existing lifecycle point. The value must be a
   list. Each entry is validated against the exact positive allowlist below without
   mutation; the same validated list object is canonicalized and supplied to
   `ProtectionManager`. The artifact is finalized before the first protection check or
   trading-loop iteration.
5. A context-bound run must have exactly one finalized v2 artifact for its executing
   strategy before receipt binding. Missing, duplicate, or v1 finalization fails closed;
   the API cannot fill or reconstruct any part of it.

This preserves the existing protection evaluation time and avoids evaluating a property
twice. It intentionally does not move protection construction ahead of indicator
calculation.

Only the four built-in protection methods that the current resolver can load with
`user_subdir=None` are supported. Every entry requires `method`. All four permit the
common optional keys `stop_duration`, `stop_duration_candles`, `lookback_period`, and
`lookback_period_candles` as finite numbers with bool rejected, plus `unlock_at` as a
string accepted by the existing `%H:%M` validation. Existing mutual-exclusion validation
between minute/candle durations and `unlock_at` remains authoritative.

Method-specific optional keys are:

| `method` | Additional allowed keys and types |
|---|---|
| `CooldownPeriod` | none |
| `LowProfitPairs` | `trade_limit`: finite_number; `required_profit`: finite_number; `only_per_side`: boolean |
| `MaxDrawdown` | `trade_limit`: finite_number; `max_allowed_drawdown`: finite_number; `calculation_mode`: exact `ratios` or `equity` |
| `StoplossGuard` | `trade_limit`: finite_number; `required_profit`: finite_number; `only_per_pair`: boolean; `only_per_side`: boolean |

An unknown method, unknown key, wrong type, or unsupported literal fails with
`strategy_evidence_protection_unsupported` before the list reaches
`ProtectionManager` or any archive member is written. Missing optional keys retain the
existing protection defaults; list order remains identity. A new protection method or
new consumed key requires a later evidence schema rather than silently entering v2.

### B.5 Strategy Evidence v2 resource bounds

- At most 4,096 distinct `(space, parameter name)` entries and 64 protection entries are
  admitted.
- Recursive hyperopt parameter values have maximum depth 8, where the parameter value is
  depth 0 and each list/tuple/dict child increases depth by one.
- Across recursive parameter values, at most 16,384 nodes are admitted. Each scalar,
  container, and mapping key consumes one node.
- Every string key or value in the canonical parameter payload is at most 16 KiB after
  UTF-8 encoding.
- The complete canonical parameter payload in B.2 is at most 1 MiB.

The builder checks depth and budgets before descending or allocating the corresponding
normalized container. Exceeding any bound fails with
`strategy_evidence_payload_too_large` before any artifact member or ZIP is created.
Construction is `O(nodes + parameters + protections)`; settings and protections are
fixed-depth projections.

### B.6 Digest inputs and retained-artifact compatibility

The v2 source digest preserves the existing source component identity:

`strategy-source-<sha256(exact captured primary-module source bytes)>`.

The v2 parameter digest is:

`strategy-parameters-<sha256(b"freqtrade-backtest-strategy-parameters-v2\0" + canonical_parameter_payload_bytes)>`.

The v2 evidence identity payload is exactly the persisted manifest fields
`schema_version`, `canonicalization`, `hash_algorithm`, `strategy`, `source_scope`,
`parameter_scope`, `source_digest`, and `parameters_digest`, excluding `evidence_id`.
Its ID is:

`strategy-evidence-<sha256(b"freqtrade-backtest-strategy-evidence-id-v2\0" + canonical_manifest_bytes)>`.

V1 continues to use its existing undomained parameter digest and
`b"freqtrade-backtest-strategy-evidence-id-v1\0"` aggregate domain. Loaders select the
formula from the validated schema version; they never try one formula and fall back to the
other. Existing retained v1 source, parameter-file, and evidence-payload members remain
readable. New v2 artifacts retain the same member roles, but their evidence payload is the
exact B.2 canonical byte sequence.
