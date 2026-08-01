# VolatilitySystem Bounded True-Range Research Receipt

**Status:** sealed by the commit containing this report; development performance remains
unopened until that commit and a clean worktree are independently verified

**Decision date:** 2026-08-01

**Preregistered protocol:**
[VolatilitySystem Bounded True-Range Episode Development Screen](../plans/2026-08-01-volatility-bounded-true-range-episode-screen.md)

**Durable receipt:**
[non-executable byte inventory and canonical runtime receipt](../receipts/2026-08-01-volatility-bounded-true-range/README.md)

## Decision

Seal one exact development-only B-then-C research attempt without opening its Backtest
results. The temporary candidate, its deterministic tests, the exhaustive restart tool,
the shared request contract, the one-shot controller, the fail-closed validator, and the
minimum portable image evidence are now preserved byte for byte under non-executable
documentation suffixes.

This is a reproducibility and admission decision, not a strategy result. No Backtest
command, strategy performance metric, result ZIP, trade, Lookahead Analysis, Recursive
Analysis, Hyperopt, Paper Runtime, exchange write, or Live operation was started or
inspected under this study before this receipt. Neither tracked `VolatilitySystem` copy
was edited. The candidate has not passed or failed its development performance Gates.

The commit containing this report may authorize only the protocol's single atomic
development B-then-C spend. It does not authorize a retry after visible strategy output,
a parameter change, a second candidate, a tracked strategy edit, the prospective spend,
Paper, or Live.

## Frozen authority

The semantic protocol was committed before candidate performance at Root
`788d2256cc772f51e9442e3d3f25e4649aa5b4a9`. Its committed plan bytes had SHA-256
`00834a9b12963b1f062c79fb82732fb297d5a6f6b893f7caa8b54184024de81b`.

| Component | Frozen identity |
|---|---|
| Root source boundary | `788d2256cc772f51e9442e3d3f25e4649aa5b4a9` |
| Backend | `3823205239281af56c34f4ff07f1674edddbe6db` |
| Frontend | `820bcc81d8665f22969aa0f888fa1d3c548bac4d` |
| Strategies | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` |
| Both accepted B strategy mirrors | 6,618 bytes; SHA-256 `fed33eceed8bec65f5c47d1727aa4a18b70f15d064b20000eb653622bb16fe85` |
| Temporary candidate C | 14,447 bytes; SHA-256 `41e9aad2be1dd262bbc715cefa414c23293d4abea66e17a2cef3ac8559db3923` |
| Immutable research image | `sha256:fb7bc20017bae79af1f7533c8b2018098bb627306d9c2286fb9b1501551fe03c` |
| Image tag observation | `freqtrade-cn:p0-788d2256cc77-382320523928-820bcc81d866` |
| Platform | `linux/amd64` |
| Portable image identity | 4,764 bytes; SHA-256 `69bcc0b555a4dbc530ec94928b846e8348463b4d1b54eef6777279783a513982` |
| Canonical runtime receipt | 1,509 bytes; SHA-256 `3c5bffdc81d9f59c641ed2401ccb9f35379575081ac309168f030fca19191056` |

The image identity records a local immutable Engine image record, source/package/UI and
entrypoint probes, and a clean four-repository source boundary. It does not claim registry
availability, registry-independent rebuild reproducibility, raw OCI object rehashing, or
future local availability. The exact immutable image must therefore be retained outside
Git; a rebuild with the same Dockerfile is not a substitute for this study.

## Data admission before performance

The credential-free admission tool opened only the four declared local OKX inputs. Its
canonical receipt is 5,568 bytes with SHA-256
`9bf627200e26944bbfa6ba764ca809566a64f28797fa6a9b96862ce69c03ea25`
and portable semantic summary SHA-256
`5ad952715905d854a36b38fbb37f29f4b62c894760477e67e7f25c1ff8eaed3a`.
The raw receipt is not tracked because it contains local absolute paths.

| Logical input | Bytes | SHA-256 | Admitted facts |
|---|---:|---|---|
| Futures one-hour Feather | 595,146 | `fda58d314cbcacd8605d5b4996030b9fb73eb2544ed35b9ef64ffeca6a252369` | 22,071 hourly rows; standard gap fill enabled |
| Mark one-hour Feather | 484,234 | `6e4a742f05a36df2a0894583463ae7904c56596d824ac5a7c444be7dbce9c86f` | 22,071 admitted hourly rows after the permitted normalization |
| Funding-rate Feather | 32,026 | `2a49b31fc35be0e3a26f4199fd773998a811ae19dd9e82a181c2fbfdf1c8fe94` | 2,214 eight-hour rows; no gap fill |
| OKX leverage tiers | 13,231,201 | `fbfb3a0b96cd713a4050a8393c912a114634f953c69cc56440623f457ba2016e` | 422 pairs, 36,929 tiers, 99 BTC tiers |

The scored development interval remains the half-open
`[2024-07-01T00:00:00Z, 2025-07-01T00:00:00Z)` interval with 8,760
hourly targets. Rows outside that interval were admitted only for the frozen 499-row
performance prefix, 799-row restart audit, funding calculation, or exact-end sentinel
rules. Admission did not calculate signals, trades, results, or performance.

## Exhaustive restart evidence before performance

The frozen real-candidate restart matrix ran in eight shards and was independently merged
and verified. The verification receipt is 5,622 bytes with SHA-256
`5f67db599c52a68a50aff1f4bd2acd06b78ed13c3bb0306105f349493cf1ec4f`
and semantic summary SHA-256
`7ea04aee4547f953ad46e5ec0b4ace50b0c9d3de3e1b753a11a8a7318028f6e1`.

| Matrix fact | Result |
|---|---:|
| Shards | 8 |
| Unique scored targets | 8,760 |
| Fresh-strategy resolver calls / records | 43,800 / 43,800 |
| Exact comparisons | 35,040 |
| Mismatches | **0** |
| One-hour source-bucket offsets | 2,920 targets at each offset 0, 1, and 2 |
| Executed distinct frames per target | full reference, 499, 599, 600, and 799 rows |
| Merged record stream | 274,868,097 bytes; SHA-256 `59cfbb45a931845809eda556564538ca0ba6bd6677556e35be9e17f91b2ad492` |
| Prior drift-witness ordinals | 5,658, 5,659, and 5,660 included |

This proves the frozen candidate's declared indicator, validity, eligibility, pulse, exit,
and source-bucket outputs are restart-stable on the complete development matrix. It is
deterministic-mechanics evidence only and contains no profit or trade result.

## Canonical one-shot runtime receipt

The canonical runtime receipt has exactly `schema`, `image_id`, and `files`. The caller
must supply its expected SHA-256 independently; the host controller verifies that hash
before parsing the receipt and then binds all 13 inputs below.

| Logical binding | Bytes | SHA-256 |
|---|---:|---|
| `admission` | 5,568 | `9bf627200e26944bbfa6ba764ca809566a64f28797fa6a9b96862ce69c03ea25` |
| `restart` | 5,622 | `5f67db599c52a68a50aff1f4bd2acd06b78ed13c3bb0306105f349493cf1ec4f` |
| `image_identity` | 4,764 | `69bcc0b555a4dbc530ec94928b846e8348463b4d1b54eef6777279783a513982` |
| `contract` | 15,035 | `c05ef3a3987eec55994b9a7d007da1e183ac2213f4ae58416032eb1afc8d8790` |
| `config` | 1,794 | `0685d9f364b9fd208c437b1c5511c20b4ee9d28780a220f24059225cb5a5b37e` |
| `b_request` | 379 | `48f9256adec70f0afc666a7acd7e6eadc05306eaeae58669d999f0af620b87fc` |
| `c_template` | 437 | `fd5e4cf0027e89db1d839eb80e61b9dca8f1e4df9d7a0859719fbd81ace54868` |
| `b_strategy` | 6,618 | `fed33eceed8bec65f5c47d1727aa4a18b70f15d064b20000eb653622bb16fe85` |
| `b_strategy_mirror` | 6,618 | `fed33eceed8bec65f5c47d1727aa4a18b70f15d064b20000eb653622bb16fe85` |
| `c_strategy` | 14,447 | `41e9aad2be1dd262bbc715cefa414c23293d4abea66e17a2cef3ac8559db3923` |
| `validator` | 92,592 | `540c04d25fbd6aedd64c5036607f06ced66c7922fe75618d0b5e2915a7d1f72c` |
| `controller` | 63,152 | `09f40adabf89facdf162afdd1294d776b77a158dc0a5d8fc233d6e0687bca960` |
| `backend_source_manifest` | 62,850 | `89fbada1b25a3cc707e34103642c05557bb8d56d3170e4c139bf794a3c2a773d` |

The controller also requires the receipt-bound `controller` bytes to equal the code that
is actually executing. Recomputing an alternate controller, its input binding, and the
entire receipt therefore cannot replace this frozen host authority.

## Execution and validation boundary

The independently re-Gated controller is intentionally a one-use adapter, not a new
research framework:

- B stages exactly the admitted Futures, mark, funding, and leverage inputs, captures and
  retains one standard DataSnapshot, and uses the unchanged baseline source.
- C stages only leverage plus B's sealed native replay inputs, omits
  `retain_data_snapshot`, and uses the frozen candidate source.
- B and C run sequentially in the same immutable image on one attempt-specific ordinary
  Docker bridge. The bridge is credential-free but not isolated: attempt-peer,
  host-gateway, LAN, and outbound reachability are explicit residual risks.
- Both roles publish no ports, run as `1000:1000` in `/freqtrade`, use a read-only root,
  drop all capabilities, set `no-new-privileges`, and use only the exact bounded mounts
  plus `/tmp:rw,noexec,nosuid,nodev,size=64m`.
- The first visible B output spends the attempt before the first result POST. Original
  B/C ZIP, metadata, and pointer bytes are sealed and never rewritten or wrapped.
- One path-sorted, 19-kind manifest is passed to the same image running the validator
  with `--network none`. The validator writes one canonical report and launches no
  secondary analysis or replay.
- The report must carry the exact observed network/security disclosure. A cleanup failure
  cannot be reported as controller success, while an earlier primary error retains
  precedence.

The C accounting contract requires exactly one entry and one full exit per trade, 2x
leverage, and an initial stake of exactly 50 USDT within `1e-8`. It derives order counts
from standard nested filled orders, assigns stable array ordinals, and does not invent
trade IDs, exchange amount precision, contract size, or a sidecar. Historical funding is
reconstructed from B's native replay rows through the pinned engine loader,
`combine_funding_and_mark(..., None)`, inclusive cumulative-amount intervals,
`calculate_funding_fees`, and `FtPrecise`.

## Independent repair and re-Gate

The first cross-integration Gate returned `P0=0, P1=4, P2=1`. Before this receipt was
created, focused RED tests exposed and the smallest implementation changes closed:

1. the former below-half stake acceptance;
2. the former loose controller report parser;
3. missing report-carried ordinary-bridge security and residual-risk truth;
4. cleanup failures that could formerly return semantic success;
5. missing reconstructed `c_template` receipt binding; and
6. the coordinator-added executing-controller self-binding requirement.

Using the Python environment that imports frozen backend `382320523`, two independent
coordinator rounds each passed 34 contract/controller tests plus 90 subtests and 52
validator tests. Ruff passed with cache disabled. The original independent reviewer then
re-Gated the final hashes and returned **PASS, P0=0, P1=0** with the same 34/90 and 52
test results. Its only P2 finding was a pre-existing Ruff cache outside every frozen
directory; that exact cache was removed, and a forced recursive scan then reported zero
`__pycache__`, `.pytest_cache`, `.ruff_cache`, `.pyc`, or `.pyo` artifacts.

## Durable evidence boundary

Hash and byte count alone cannot reconstruct temporary source after its deletion.
Accordingly, the durable receipt stores the exact 20 non-executable byte copies listed in
its README, deduplicating only the byte-identical B mirrors. The restart tool and several
tests retain non-secret absolute path constants from the verification host. Those evidence
copies are intentionally byte-exact and host-specific; they are not portable execution
entrypoints, and the one-shot controller receives its runtime paths independently.

The following remain deliberately outside Git and are represented only by hashes and
portable facts:

- raw admission and restart receipts because they contain local absolute paths;
- the four market inputs, the 274 MB merged restart records, and all eight shards;
- Docker inspect/history/build/probe/UI records and raw OCI/image objects;
- the immutable image itself, which must remain in approved immutable local storage;
- logs, caches, spent-lease, state/work directories, secrets, and eventual native result
  artifacts.

No generated API, exchange, or runtime secret is stored or hashed in this receipt.

## Closed boundary and next action

The repository may proceed only after the receipt package, its canonical receipt SHA,
this report, and the updated routing documents are committed and an independent receipt
Gate confirms byte preservation in both the worktree and Git index. The next permitted
strategy action is then exactly one B-then-C development spend under the frozen
controller.

Any `INVALID`, `INSUFFICIENT`, or `REJECTED` classification stops the study and requires
one factual report. Only
`METRIC-SURVIVOR_PENDING_ANALYSES` may open the already accepted Lookahead and Recursive
analyses. Even a resulting `DEVELOPMENT-SURVIVOR` does not authorize changing either
tracked strategy: the separately admitted
`[2026-10-01T00:00:00Z, 2027-10-01T00:00:00Z)` prospective spend and a later independent
acceptance remain mandatory.

This receipt makes no profit guarantee, significance claim, Paper recommendation, or
claim that retrospective performance predicts future return.
