# Phase 1 Reviewed Image UI Self-Identity Acceptance Report

**Acceptance date:** 2026-08-01

**Status:** accepted at exact implementation SHAs and one retained immutable local
image; no market-data analysis, strategy execution, retired-holdout use, Backtest,
Recursive Analysis, Lookahead Analysis, exchange request, trading database, Runtime,
Paper, Live, remote push, merge, release, or deployment

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Reviewed Image UI Self-Identity](../plans/2026-08-01-reviewed-image-ui-self-identity.md)

**Triggering evidence:**
[Lookahead Analysis Sufficiency Truthfulness Repair Acceptance](2026-08-01-lookahead-analysis-sufficiency-truthfulness-repair-acceptance.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `39177df06d12a2c87a61779a245b1a5b723aa91a` |
| `freqtrade/` backend | `8b1ec82765cc0eb59da0287cd62dd892b62f0f11` (unchanged) |
| `frequi/` frontend | `212c91216e395335b7c9e32b0bf059436bd6bb96` |
| `freqtrade-strategies/` | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` (unchanged and not packaged) |

The Root implementation commit has tree
`59dae66b9535e9be67841b083d994c8bea0f03c3` and directly pins all three submodule
SHAs above. The frontend implementation commit is
`fix: embed reviewed UI revision`; the Root implementation commit is
`fix: verify reviewed UI identity`.

This report and the final status updates are a later documentation-only commit. They do
not replace the implementation identity, frontend gitlink, or image identity accepted
here.

## 2. Accepted user outcome

A formally reviewed combined image can now identify the exact FreqUI commit selected by
the committed Root tree at all three relevant surfaces:

1. the existing Root/backend/frontend image labels;
2. the public `/ui_version` response; and
3. the visible packaged FreqUI version string.

The full frontend object ID is displayed once. The UI does not append a second copy when
the backend marker is exactly `local-frequi-<compiled-commit>`. An ordinary release
version, a different revision, or a noncanonical value that merely ends in `unknown`
continues to show both values so a mismatch is not hidden.

Normal local Docker and Compose development remains available. Without an explicitly
supplied build argument, the Root Dockerfile defaults to the honest marker
`local-frequi-unknown`. A raw build remains ineligible for formal acceptance even if a
caller manually supplies a full revision. No required revision interpolation was added
to Compose, so emergency `stop`, `down`, `ps`, and `logs` behavior is unchanged.

## 3. Trust and evidence boundary

The accepted identity chain is:

```text
clean committed Root checkout
  -> exact backend/frontend gitlinks from the Root tree
  -> matching clean submodule checkouts
  -> committed Git archives used as the Docker context
  -> exact Root/backend/frontend labels
  -> exact embedded frontend marker
  -> immutable Docker image ID
  -> actual /ui_version and packaged-browser behavior
```

`FREQUI_COMMIT_HASH` transports the already-derived frontend identity into the Docker
builder. It does not establish trust by itself. A caller-provided build argument, an OCI
label, or `/ui_version` is not independently authoritative merely because it contains a
full hexadecimal object ID.

The reviewed wrapper remains the authority because it derives identity from the clean
committed tree, rejects dirty or mismatched submodule checkouts, builds committed
archives, validates the exact label set, and reads the marker from the immutable image
ID before returning success.

This acceptance does not claim a signed source-to-image attestation, trusted SLSA level,
hermetic or reproducible build, SBOM, registry publication, artifact authenticity, or
third-party-verifiable supply chain. Local Buildx metadata from the preceding slice is
historical corroboration only and is not used as an independent trust root here.

`freqtrade-strategies` is deliberately absent from the image labels. The strategy
submodule is not copied into the combined image, and operational strategies are separate
read-only runtime inputs with their own experiment and backtest evidence. Adding a
strategy label would overstate the image's contents and behavior.

## 4. Implemented contract

The Root Dockerfile now exposes one optional builder argument:

```text
FREQUI_COMMIT_HASH=unknown
```

The reviewed runtime and operator build commands pass the exact full frontend object ID
from `CommitIdentity.frontend`. FreqUI accepts only:

- an exact explicit `unknown`; or
- a complete lowercase 40- or 64-hex Git object ID.

An explicit empty, short, uppercase, whitespace-polluted, non-hex, or otherwise malformed
value fails closed. Only an actually absent variable may use the existing standalone
checkout Git fallback, and that output is trimmed. Git failure produces `unknown`.

After the same builder stage completes the production bundle, it writes without a
trailing newline:

```text
/frequi/dist/.uiversion = local-frequi-<FREQUI_COMMIT_HASH>
```

The existing whole-directory copy places that file at the backend's actual read path,
`ui/installed/.uiversion`. The historical `local-frequi-f5a81466` value and the incorrect
parent-directory marker write were removed.

After label inspection, both reviewed build helpers read the marker from the immutable
image ID in an ephemeral container with no network, a read-only root filesystem, all
capabilities dropped, `no-new-privileges`, UID/GID `1000:1000`, no mounts or secrets, a
fixed Python command, captured output, and a bounded timeout. A private temporary cidfile
permits cleanup of only a validated exact 64-hex container ID if the Docker client errors
or times out. Empty, short, `unknown`, mismatched, or newline-suffixed output is rejected.

## 5. Automated verification

No check in this section read market data or executed a strategy or analysis command.

| Check | Result |
|---|---:|
| Focused FreqUI version and Vite-resolution Vitest | 2 files, 16 passed |
| Full FreqUI Vitest | 47 files, 308 passed |
| FreqUI typecheck | passed |
| FreqUI production build with full 40-hex revision | passed; full revision present in bundle |
| Explicit short-revision production build | failed closed with the expected validation error |
| Full 40/64, `unknown`, absent, Git-failure, and malformed resolver matrix | passed in focused tests |
| New FreqUI file Prettier check | passed |
| FreqUI changed-file ESLint | 0 errors |
| Root provenance unit tests | 13 passed |
| Root provenance, committed-context, and Compose-wrapper suite | 68 passed |
| Root changed-file Ruff check | passed |
| Docker Compose config without revision environment | passed |
| Root and FreqUI `git diff --check` | passed |

The full Vitest run exited successfully while printing the pre-existing Happy DOM
fetch-abort and fork `EPROTO` teardown noise. The production build retained existing
third-party pure-annotation, chunk-size, and plugin-timing warnings.

ESLint reported no errors. It also reported existing CRLF-versus-Prettier warnings in
`vite.config.ts` and `src/stores/settings.ts`. Those files already used CRLF; the slice
did not normalize their unrelated lines merely to manufacture a broad formatting diff.
All newly added files and the changed Node TypeScript project file passed Prettier.

## 6. Orchestrated independent Gates

Read-only reviewers separately examined product priority, deployment compatibility,
security/evidence boundaries, the design, the frontend implementation, and the Root
packaging implementation. They made no repository changes and did not access market or
holdout data.

| Review | Result |
|---|---|
| Product priority audit | proceed as a bounded P2; no new platform or product surface |
| Deployment compatibility audit | preserve reviewed/ad-hoc dual lanes; no required Compose argument |
| Security/evidence audit | build args and labels are transport/evidence, not an independent trust root |
| Design Gate | PASS; P0/P1 = 0; two P2 hardening suggestions absorbed before implementation |
| Initial frontend implementation Gate | FAIL; one P1 explicit-empty-string fail-open |
| Frontend re-Gate at `212c9121...` | PASS; P0/P1/P2 = 0 |
| Root implementation Gate | PASS; P0/P1/P2 = 0 |
| Exact-image Gate | PASS; P0/P1 = 0; one P2 raw-build wording precision issue corrected |
| Acceptance-documentation Gate | PASS; P0/P1/P2 = 0 |

The frontend P1 was closed by distinguishing `undefined` from every explicitly provided
value. Explicit empty input now reaches strict validation instead of silently falling
back to Git. The focused resolver tests directly cover the complete boundary rather than
relying only on end-to-end build invocations.

The design P2 suggestions were also incorporated: FreqUI deduplicates only an exact
canonical marker, and the immutable-image marker verifier uses a private cidfile plus
validated exact-ID timeout cleanup.

The exact-image Gate independently re-read the 53 marker bytes with no newline, checked
the three-label exact set, confirmed the compiled bundle contains the full frontend SHA
once and neither stale identity, and found no container or port residue. It initially
noted that raw builds default to `unknown` only when no explicit argument is supplied.
README.docker, STRATEGY, and this report now state that narrower fact and retain the more
important invariant: every raw build remains non-reviewed regardless of a caller value.
The final documentation Gate then passed with no remaining finding.

## 7. Exact reviewed image

The formal helper built and accepted:

```text
tag:
  freqtrade-cn:p0-39177df06d12-8b1ec82765cc-212c91216e39
immutable Docker image ID:
  sha256:51faa9d18e1f1a715c416c3361742431f24a7302dee5ba266ee8f56d3996b89c
platform: linux/amd64
size: 322,506,652 bytes
```

The tag is a local convenience. The immutable image ID is the runtime evidence identity.
The image's exact labels are:

```text
org.freqtrade-cn.revision.root=39177df06d12a2c87a61779a245b1a5b723aa91a
org.freqtrade-cn.revision.backend=8b1ec82765cc0eb59da0287cd62dd892b62f0f11
org.freqtrade-cn.revision.frontend=212c91216e395335b7c9e32b0bf059436bd6bb96
```

The helper then read the marker from this immutable ID and accepted the exact bytes:

```text
local-frequi-212c91216e395335b7c9e32b0bf059436bd6bb96
```

No marker-verification container remained after the helper returned.

## 8. Ad-hoc compatibility and rejection

A second build used the normal Root Dockerfile without any revision argument. It
succeeded and produced temporary image ID
`sha256:8e1893b290341c24dd494780767f12add48a1b4a60c29be9ac146adf699fda12`.

Its embedded marker was exactly:

```text
local-frequi-unknown
```

Its labels were `null`. The formal label inspection rejected it, and the immutable
marker verifier rejected `unknown` against the reviewed frontend identity. This proves
that compatibility does not become accidental acceptance. The temporary ad-hoc tag and
image were deleted after verification.

## 9. Isolated API and packaged-browser acceptance

The reviewed image was started by immutable ID in one temporary webserver-only
container:

```text
container ID:
  b7021f72fc56cbb3b46f9a3cf8e2b79e08fc16460e9a0332888824281557b34c
endpoint: http://127.0.0.1:18088
```

The container used dynamic UID/GID `12345:12345`, a read-only root filesystem, all
capabilities dropped, `no-new-privileges:true`, a no-exec temporary filesystem, and a
loopback-only published port. Its mounts were one read-only temporary config, three
read-only random temporary API secret files, one writable temporary state directory,
and two read-only empty directories in place of strategy and research data. It received
no strategy content, market data, retained result, or trading database.

The `webserver` startup performed Freqtrade's local exchange-name/configuration check.
Logs showed no market loading, CCXT request, exchange URL, database open, strategy
execution, Backtest, Recursive Analysis, or Lookahead Analysis. The acceptance therefore
does not use the startup check as market or strategy evidence.

The public endpoint returned:

```json
{"version":"local-frequi-212c91216e395335b7c9e32b0bf059436bd6bb96"}
```

A real headless branded-Chrome session loaded the FreqUI files served by that same
container. At a mobile viewport it opened the actual navigation dialog and verified:

- the browser received the exact `/ui_version` response above;
- the visible UI contained the exact complete identity once;
- `local-frequi-unknown` was absent;
- historical `f5a81466` was absent; and
- no duplicate appended frontend SHA was visible.

The first browser probe looked for the textual icon name `menu`, but the packaged
Iconify SVG correctly contains only path data. The probe was corrected to use the
button's actual accessibility contract, `aria-haspopup="dialog"`; the product was not
changed. The final browser assertion passed and the captured screenshot visually showed
the complete identity in the open mobile menu.

## 10. Cleanup and decision

After evidence collection:

- the temporary webserver container was stopped and removed by its verified exact ID;
- the temporary config, random credentials, empty inputs, state, and screenshot under
  `C:\Users\dezhengu\AppData\Local\Temp\freqtrade-ui-identity-39177df` were removed;
- loopback port `18088` had no listener;
- no container derived from the accepted image remained;
- the temporary ad-hoc image was removed;
- the reviewed tag and immutable image ID were retained for local reproduction; and
- Root, backend, frontend, and strategies were clean before this documentation update.

Phase 1 Reviewed Image UI Self-Identity is accepted at the exact implementation SHAs in
Section 1 and the immutable image in Section 7. There is no unresolved P0, P1, or known
P2 inside its declared local packaging boundary.

This acceptance closes the previously recorded embedded-UI-provenance P2. It does not
upgrade the preceding Lookahead result into stronger strategy evidence and does not prove
strategy correctness, representative coverage, robustness, restart stability, Paper or
Live eligibility, current or future profitability, or a trusted third-party supply
chain. No strategy candidate is active. The former `20250702-20260702` holdout remains
retired, and no replacement holdout is assigned by this packaging acceptance.
