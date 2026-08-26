# Binance Taker PriceFlow DNS Retry — Supplemental Preregistration

Status: **FROZEN BEFORE THE ONLY PERFORMANCE RETRY**
Scope: **execution adapter only; no strategy, data, cost, gate, or window change**

## 1. Why a retry is permitted

The first launch stopped while Freqtrade was loading current OKX public market metadata because
the local resolver mapped `www.okx.com` to an unreachable address. It stopped before backtest data
or the strategy was loaded. The archived attempt contains zero ZIP files, zero JSON result files,
no performance marker, no evaluated development gate, and no opened 2024 directory.

The hash-bound incident receipt is:

- path:
  `ft_userdata/user_data/research_data/binance-taker-priceflow-confirmation/attempts/20260812T210043Z-okx-dns-abort/infrastructure-abort-receipt.json`
- SHA-256: `c1ddf6751545fff7b47bb3b6c6316294d410ec7e2223c8cbad28b3bcbb70b86c`

This launch is classified as `INFRASTRUCTURE_ABORT_BEFORE_PERFORMANCE`, so one retry is allowed.
If the retry creates any backtest ZIP or emits any performance marker listed in that receipt, it
consumes the single performance run even if it later fails. No second performance retry is allowed.

## 2. Unchanged frozen research contract

The original preregistration remains authoritative and is not modified:

- path:
  `ft_userdata/user_data/research_data/binance-taker-priceflow-confirmation/PREREGISTRATION.md`
- SHA-256: `b62a968947223fade20e4048c0a7301e2be173a30f3390c36d97e72a9d03c8d0`

The original runner also remains byte-for-byte unchanged:

- path: `tools/run_binance_taker_priceflow_research.py`
- SHA-256: `4d38bb01bd839e0f99ce6ae4374e8fe1866019bed200aff796567808d4b32991`

Therefore the frozen strategy, sidecar, market data, leverage tier, pair, 15m/5m timeframes,
1x leverage, 0.0006 fee per side, funding semantics, wallet, protections, development window,
retrospective 2024 window, result parser, and all gates are unchanged. Development failure still
stops before 2024; 2024 remains retrospective and cannot authorize paper or live trading.

## 3. Frozen DNS execution adapter

The retry adds only a task-scoped Python startup adapter:

- adapter path: `tools/okx_dns_override/sitecustomize.py`
- adapter SHA-256: `f14afd88c4c1090a10e7482c75f3427bbfd69a71e5940536998d6cf0951e5b2e`
- DNS evidence path:
  `ft_userdata/user_data/research_data/binance-taker-priceflow-confirmation/execution-adapter/dns-google-www-okx-A.json`
- DNS evidence SHA-256: `07e61573aeaad6b10d7e445593efaddc0aa75ac7e2fbde55637c1daaf101947d`

The adapter changes only `socket.getaddrinfo` calls whose normalized hostname is exactly
`www.okx.com`. It returns the two Google DoH-verified Cloudflare addresses `172.64.144.82` and
`104.18.43.174`. Every other hostname delegates to the original resolver. The request URL,
HTTP `Host`, TLS SNI, and certificate verification remain `www.okx.com`; TLS is not disabled and
the IP address is never used as the HTTPS hostname.

No `.pyc` file or other executable cache is allowed under `tools/okx_dns_override` at launch or
after execution. The retry sets `PYTHONDONTWRITEBYTECODE=1` before the parent Python process starts,
and the frozen runner preserves that environment variable for its Freqtrade child. Because the
adapter directory must be cache-free before launch, Python can execute only the hash-bound source;
the environment variable then prevents a new unbound bytecode cache from being written.

The adapter passed Python compilation, Ruff, an exact-address assertion, a non-target delegation
assertion using `localhost`, and an HTTPS request to the OKX public BTC-USDT-SWAP instruments
endpoint with status 200 and OKX code 0. These are infrastructure checks only and read no strategy
performance.

As already disclosed by the original preregistration, OKX market and precision metadata remain a
live public API dependency and are not frozen historical inputs. The adapter fixes only the local
DNS routing failure; it does not freeze or alter the API response.

## 4. Exact retry invocation and checks

Immediately before launch, an external check must verify the original preregistration, original
runner, adapter, DNS evidence, and incident receipt hashes above, and verify that the active
`results` path does not exist. It must also recursively verify that the adapter directory contains
zero `.pyc` files. `PYTHONPATH` must be set exactly to the absolute resolved
`tools/okx_dns_override` directory, not appended to an existing value, and
`PYTHONDONTWRITEBYTECODE` must be set exactly to `1`. `PYTHONPYCACHEPREFIX` must be absent so Python
cannot read an alternate cache tree. The command is otherwise the original frozen command:

```powershell
if (Get-ChildItem 'tools\okx_dns_override' -Recurse -File -Filter '*.pyc') {
  throw 'Unbound adapter bytecode exists'
}
$null = Remove-Item Env:PYTHONPYCACHEPREFIX -ErrorAction SilentlyContinue
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = (Resolve-Path 'tools\okx_dns_override').Path
.\freqtrade\.venv\Scripts\python.exe tools\run_binance_taker_priceflow_research.py `
  --prereg-sha256 b62a968947223fade20e4048c0a7301e2be173a30f3390c36d97e72a9d03c8d0
```

After the process returns and before accepting any result, the same external check must verify all
five hashes again and verify that the adapter directory still contains zero `.pyc` files. The
original runner independently reverifies its original frozen file set after each Freqtrade
subprocess and before accepting any result archive.
