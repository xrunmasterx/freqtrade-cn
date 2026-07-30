# Backtest Artifact Secret Redaction Plan

**Status:** implementation complete; exact-SHA acceptance report pending

**Branch:** `xrunmasterx/phase1-complete-development`

**Base acceptance:**
[Phase 1 DataSnapshot Binding](../reports/2026-07-31-phase1-data-snapshot-binding-acceptance.md)

## 1. User outcome

Continuous AI strategy iteration can create hundreds of Backtest ZIPs. Every new artifact
must retain the configuration evidence needed to understand the run without copying live
credentials into a long-lived result archive.

This slice fixes the shared configuration sanitizer used by Freqtrade's existing
Backtest ZIP writer. It is a security and evidence-integrity correction, not a new
artifact service, result format, backtest engine, or profitability feature.

## 2. Confirmed problem

The accepted backend already redacted exchange credentials, Telegram identifiers, API
passwords, and webhook endpoints. It did not redact several other credential-bearing
configuration paths:

- CoinGecko API key;
- API-server JWT secret and WebSocket token;
- external message producer WebSocket tokens;
- RemotePairList bearer tokens;
- a password embedded in `db_url`.

Both CLI and API Backtests eventually call the same `store_backtest_results()` function,
which writes `sanitize_config(original_config)` into the ZIP. The correction therefore
belongs in that one sanitizer, not in separate API/UI paths.

A read-only local inventory found 191 parseable Backtest ZIP configuration snapshots;
184 contained non-placeholder API-server JWT/WS values. None of those operational ZIPs
or their archived configuration members is tracked by the current Git indexes or any
locally reachable Git ref. No credential value, fragment, hash, or length was emitted by
the inventory.

## 3. Implementation boundary

- Keep an explicit allowlist of credential paths. Do not redact every field whose name
  merely contains `key`, `token`, `secret`, `password`, or `url`.
- Traverse mappings and configured lists so every producer, pairlist entry, and later
  list-shaped occurrence of an approved path is handled.
- Replace secret credential values with the existing literal `REDACTED`.
- For `db_url`, reuse Freqtrade's existing URI-password masker. Preserve the dialect,
  host, port, database name, and password-free URLs instead of discarding useful
  provenance.
- Preserve deep-copy behavior: sanitizing an artifact must never mutate the operational
  configuration used by the running process.
- Preserve ZIP names, members, result payloads, strategy source/parameter members, and
  history loading behavior.

## 4. Test-first acceptance

1. A focused sanitizer test fails on all newly identified paths before the fix.
2. Scalar and list-valued API WebSocket tokens are redacted.
3. Every producer and RemotePairList entry is handled; non-secret neighbors remain.
4. The source configuration is unchanged.
5. A real Backtest ZIP contains only redacted credentials and a masked database
   password, while its result, strategy, and metadata structure remains compatible.
6. Existing exchange redaction, absent-key behavior, and explicit `show_sensitive=True`
   behavior remain covered.
7. Relevant pytest, Ruff, and `git diff --check` gates pass.
8. An independent read-only Gate Review reports no unresolved P0/P1 within the
   forward-write contract.

## 5. Historical artifact and rotation boundary

The code correction is forward-only. It does not rewrite, delete, quarantine, or upload
existing ZIPs, and replacing text inside an old archive would not revoke a credential
already copied elsewhere.

Existing artifacts must remain access-restricted. Sanitized replacement creation,
verification, original deletion, and issuer-side rotation/revocation are separate
operational actions. The governing runtime-secret runbook requires explicit operator
authorization for each affected service before rotation invalidates sessions. This plan
does not grant that authority and does not expose credential material to perform an
inventory.

## 6. Explicit non-goals

- no Backtest artifact CAS, database, CRUD page, upload path, signing, or encryption;
- no automatic historical ZIP mutation or deletion;
- no automatic credential rotation, service recreation, or session invalidation;
- no generic recursive removal of arbitrary strategy configuration;
- no StrategyRelease, Environment Identity, RuntimeInstance, Paper, or Live scope;
- no change to charts, indicators, signals, comparisons, or exchange writes.

## 7. Verification commands

```powershell
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m pytest `
  tests/test_configuration.py tests/optimize/test_optimize_reports.py `
  tests/test_misc.py tests/commands/test_commands.py::test_start_show_config -q

& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m ruff check `
  freqtrade/configuration tests/test_configuration.py `
  tests/optimize/test_optimize_reports.py tests/test_misc.py `
  tests/commands/test_commands.py
```

## 8. Implementation checklist

- [x] Reproduce the missing redaction through focused and real-ZIP tests.
- [x] Add list-aware exact-path redaction and selective database-password masking.
- [x] Cover all confirmed credential paths without broad heuristic deletion.
- [x] Run relevant pytest and Ruff regression gates.
- [x] Complete independent Gate Review.
- [x] Commit backend first; Root submodule pointer and synchronized docs are staged next.
- [ ] Publish an exact-SHA acceptance report.
