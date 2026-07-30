# Backtest Artifact Secret Redaction Acceptance Report

**Acceptance date:** 2026-07-31

**Status:** accepted for newly written Backtest artifacts at exact implementation SHAs;
historical local artifact remediation remains pending separate operator authorization

**Plan:**
[Backtest Artifact Secret Redaction](../plans/2026-07-31-backtest-artifact-secret-redaction.md)

## 1. Accepted outcome

The shared Freqtrade configuration sanitizer now prevents the known credential-bearing
configuration fields from being copied into newly written Backtest ZIPs. Both CLI and
API Backtests already converge on the same `store_backtest_results()` writer, so one
backend correction protects both paths without an API version, schema, UI, history
loader, or result-format change.

The accepted implementation:

- preserves existing exchange, Telegram, Discord, API-password, and webhook redaction;
- adds CoinGecko API key, API JWT/WS, external producer WS, and RemotePairList bearer
  token redaction;
- traverses list-shaped producer and pairlist configuration so every entry is handled;
- masks only the password component of `db_url`, retaining non-secret connection
  provenance;
- deep-copies before sanitizing and preserves explicit `show_sensitive=True` behavior;
- leaves result, metadata, strategy source/parameter, market-change, wallet, filename,
  and history-loading contracts unchanged.

This is a forward-write security correction. It does not claim that old archives were
rewritten or that credentials copied previously have been revoked.

## 2. Exact implementation identity

The accepted Root implementation is the parent of this documentation-only acceptance
commit. This report does not claim that its own later Markdown was present in that
implementation commit.

| Repository | Accepted implementation commit |
|---|---|
| Root | `014c0f677c6d99684bfdb880149f199b47748687` |
| Backend `freqtrade/` | `c8fb9af73b6bb354d599ff62c350f8b72a3bb3cd` |
| Frontend `frequi/` | `a71cf5b1134a86e43a55eec7b46ec8093fd27e6c` (unchanged) |
| Strategies | `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4` (unchanged) |

All commits are local on branch `xrunmasterx/phase1-complete-development`. This
acceptance did not push a branch or create a pull request.

## 3. Verified credential boundary

The sanitizer uses exact configuration paths rather than heuristic key-name matching.
The accepted set covers:

- all previously supported dedicated exchange credential aliases;
- `coingecko.api_key`;
- `telegram.token` and `telegram.chat_id`;
- `discord.webhook_url` and `webhook.url`;
- `api_server.password`, `api_server.jwt_secret_key`, and `api_server.ws_token`;
- every `external_message_consumer.producers[*].ws_token`;
- every `pairlists[*].bearer_token`;
- the password component, if present, in `db_url`.

The sanitizer does not erase every arbitrary field named like a credential. Custom CCXT
options, arbitrary strategy configuration, URLs that may contain caller-invented query
secrets, and external files remain outside this exact-path contract. Adding a real new
credential-bearing configuration field requires adding its explicit path and a test.

## 4. Verification evidence

Test-first evidence demonstrated the failure before implementation: both the direct
sanitizer test and real ZIP test retained their credential sentinels. After the fix and
the audit-discovered RemotePairList/database corrections, the final gates were:

| Gate | Result |
|---|---:|
| `tests/test_configuration.py` | 76 passed |
| `tests/optimize/test_optimize_reports.py` | 17 passed |
| `tests/test_misc.py` plus `test_start_show_config` | 39 passed |
| Total related pytest | 132 passed |
| Ruff over related configuration/source/tests | passed |
| Backend and Root `git diff --check` | passed |

The real ZIP regression parses the archived configuration member, proves that no test
credential sentinel remains, verifies every new path plus unchanged legacy paths, and
confirms ordinary fields and strategy/result ZIP members are retained.

## 5. Orchestrated audits and Gate

Orca orchestration created and verified tracked dispatches for four independent,
read-only workers; none modified files:

| Task | Result |
|---|---|
| `task_75561ef1e94e` — source/call-chain audit | Found RemotePairList bearer-token omission and recommended password-only DB URI masking; both were incorporated |
| `task_a4ab92ca26a3` — historical artifact inventory | Counted affected local artifacts without exposing values and confirmed none are tracked in reachable Git refs |
| `task_3cf4c8f1eb6b` — tests/docs audit | Confirmed the single sanitizer/ZIP boundary and forward-only documentation requirements |
| `task_b98f6671b18d` — independent final Gate | PASS; P0=0, P1=0, P2=0 within the forward-write contract |

The final reviewer independently ran the 132-test selection, Ruff, and Root/backend
whitespace gates against the latest shared working tree.

## 6. Historical local artifact finding

The read-only inventory found 191 parseable local Backtest ZIP configuration snapshots:

- 190 under the compatibility user-data result directory;
- one under the Research runtime result directory;
- filesystem modification times spanning 2026-07-03T15:11:25Z through
  2026-07-30T17:38:51Z;
- 184 containing non-placeholder API-server JWT and WS fields;
- seven containing placeholders only;
- zero archive/config parse failures;
- zero operational ZIPs or archived configuration members tracked by the current Git
  indexes or any locally reachable Git ref.

The audit did not print, copy, hash, measure, or partially disclose any credential value.
These 184 artifacts remain an operational exposure until access restriction, sanitized
replacement verification, original-retention action, and issuer-side rotation/revocation
are separately authorized and completed. Redaction alone cannot invalidate an exposed
credential.

The governing [runtime secret runbook](../../operations/runtime-secrets.md) explicitly
requires operator authorization for each service rotation because it invalidates current
sessions and requires service recreation and client reauthentication. This acceptance
does not broaden that authority and therefore performed no rotation, deletion, rewrite,
or quarantine.

## 7. Safety and compatibility

- No actual credential value was displayed, logged, committed, compared, hashed, or
  copied into a report.
- No operational config, secret file, Backtest ZIP, backup, container, service, session,
  database, or exchange state was mutated.
- No frontend, strategy, chart, Experiment receipt, DataSnapshot, Runtime, Paper, Live,
  real-order, or exchange-write behavior changed.
- Historical artifacts remain ignored operational state; this report records counts and
  authorization boundaries, not their contents.

## 8. Acceptance decision and next boundary

The forward-write Backtest Artifact Secret Redaction slice is accepted at the exact
implementation SHAs above with no unresolved P0/P1/P2 inside that contract.

This does not declare the historical operational exposure remediated. That work remains
pending explicit operator authority. The next development candidate remains a bounded
Backtest strategy-evidence binding: capture the loaded primary strategy source and
resolved parameter identities without prematurely creating StrategyRelease, CAS,
Environment Identity, Runtime, Paper, or Live infrastructure.
