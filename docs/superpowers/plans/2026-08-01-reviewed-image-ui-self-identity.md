# Phase 1 Reviewed Image UI Self-Identity

**Status:** Implemented; exact-image acceptance pending

**Design Gate:** PASS; P0 = 0, P1 = 0

**Product authority:** [Product Strategy and Delivery Policy](../STRATEGY.md)

**Triggering evidence:**
[Lookahead Analysis Sufficiency Truthfulness Repair Acceptance](../reports/2026-08-01-lookahead-analysis-sufficiency-truthfulness-repair-acceptance.md)

## User problem

The accepted combined image contains the correct backend and newly built FreqUI, but the
image cannot accurately identify that FreqUI from inside the running product:

- the committed Docker build context deliberately contains no `.git` metadata and its
  Node builder contains no Git executable, so Vite compiles `__COMMIT_HASH__=unknown`;
- the Dockerfile writes the historical value `local-frequi-f5a81466` to
  `ui/.uiversion`, while `/ui_version` reads `ui/installed/.uiversion`; and
- the last hand-built Buildx acceptance image bypassed the repository's existing
  reviewed-image helper and therefore contains no Root/backend/frontend revision labels.

This does not change chart, Backtest, Recursive Analysis, or Lookahead Analysis behavior
and remains a P2 for the current local product. It does make incident reports and future
atomic frontend/backend deployment harder to verify. API 2.56 is specifically unsafe to
deploy backend-first to an old FreqUI, so an accurate combined-image identity has concrete
operational value before another image-based feature slice.

The user question for this slice is deliberately small:

> For a formally reviewed combined image, can the image labels, `/ui_version`, and the
> visible UI name the exact FreqUI commit fixed by the committed Root tree, while normal
> ad-hoc development builds remain usable and visibly non-reviewed?

## First-principles decision

Identity must be supplied by the component that knows the whole committed composition.
The FreqUI builder must not guess its identity from unavailable Git metadata, and a caller
provided build argument or label is not independently trusted merely because it contains
40 hexadecimal characters.

The existing reviewed-image path already establishes the useful local trust boundary:

```text
clean Root checkout
  -> backend/frontend gitlinks from the committed Root tree
  -> matching clean submodule checkouts
  -> git-archive build context containing only those commits
  -> complete Root/backend/frontend image labels
  -> immutable image ID
```

This slice reuses that path. `tools/image_provenance.py` passes the already-derived full
frontend object ID into Docker and verifies the embedded result after the build. The
Docker build argument transports a verified fact; it does not establish that fact by
itself.

Local Buildx VCS/SLSA metadata is only corroborating build-record metadata. For a local
directory context it is not an independently signed or trusted source-to-image proof.
The preceding acceptance report remains frozen historical evidence, but this narrower
interpretation governs future claims: source-input control comes from the clean checkout,
gitlink checks, and committed archive; the immutable digest identifies the resulting
image; local Buildx metadata does not prove a trusted or hermetic supply chain.

## Two build lanes

| Lane | Revision source | Result when no exact revision is available | Formal acceptance |
|---|---|---|---|
| Reviewed combined image | `CommitIdentity.frontend`, derived from the committed Root gitlink | fail closed before returning an accepted image ID | eligible after all checks |
| Ad-hoc Root Docker/Compose build | optional Docker argument, default `unknown` | builds and visibly reports `local-frequi-unknown` | never eligible |
| Standalone FreqUI checkout | existing local Git fallback | keeps the local development behavior; `unknown` only when Git is unavailable | outside this Root-image contract |

The Dockerfile and `docker-compose.yml` do not define whether a build is reviewed.
`tools/image_provenance.py` is the reviewed boundary. Therefore:

- no revision variable is made unconditionally required by the Dockerfile;
- no `${VAR:?required}` interpolation or build args are added to Compose;
- ordinary `docker build .`, `docker compose build`, emergency Compose commands, and
  standalone `pnpm build` remain usable; and
- an ad-hoc image carrying `unknown` cannot pass the reviewed-image verifier.

## Embedded identity contract

The Root Dockerfile exposes one optional builder argument:

```text
FREQUI_COMMIT_HASH=unknown
```

For a reviewed build, both the runtime and platform-operator helpers pass the exact full
`CommitIdentity.frontend` value. The FreqUI Vite configuration follows these rules:

1. an explicit non-`unknown` value must be a complete lowercase 40- or 64-hex Git object
   ID; a short, uppercase, whitespace-polluted, or otherwise malformed value fails the
   build;
2. explicit `unknown` remains the honest ad-hoc Docker state;
3. when the variable is absent, the existing standalone local Git fallback remains, and
   its output is trimmed; and
4. Git failure without a reviewed value produces the explicit `unknown` development
   marker, never a historical or fabricated revision.

After the same builder stage successfully compiles the bundle, it writes, without a
trailing newline:

```text
/frequi/dist/.uiversion = local-frequi-<FREQUI_COMMIT_HASH>
```

The existing `COPY /frequi/dist -> ui/installed` operation then moves the bundle and its
marker together. The historical parent-directory write is removed.

FreqUI continues to combine the backend-served UI version and its compiled commit at the
single settings-store boundary. It suppresses duplication only when the served value is
exactly `local-frequi-<compiled-commit>`. Every other combination retains the existing
`<served-version>-<compiled-commit>` form so that a different revision, an ordinary
release version, or a noncanonical string that merely ends in `unknown` stays visible
instead of being hidden. A reviewed image therefore displays the full frontend SHA once;
an ad-hoc image displays the exact canonical `local-frequi-unknown` once.

## Reviewed-image verification

The existing exact Root/backend/frontend label names and exact-set validation remain
unchanged:

```text
org.freqtrade-cn.revision.root
org.freqtrade-cn.revision.backend
org.freqtrade-cn.revision.frontend
```

No second label namespace is introduced. In particular, this slice does not add a
strategies label: `freqtrade-strategies` is not copied into the image, while the actual
runtime strategy is mounted and has separate Backtest/Experiment evidence. Labeling the
image with that gitlink would overstate its contents and runtime behavior.

After label inspection, the reviewed-image helper reads the marker from the immutable
image ID with one fixed Python command in an ephemeral container. The verifier uses:

- no network;
- a read-only root filesystem;
- all capabilities dropped;
- `no-new-privileges`;
- the existing unprivileged `1000:1000` user;
- no mounts or secrets;
- a temporary Docker cidfile whose validated exact container ID is used for forced
  cleanup if the Docker client errors or times out;
- captured output and a fixed timeout; and
- an exact byte-for-byte comparison with
  `local-frequi-<CommitIdentity.frontend>`.

Missing, empty, short, `unknown`, mismatched, or newline-suffixed markers fail closed.
The helper returns an accepted immutable image ID only after both label and marker checks
pass. The marker proves internal self-description consistency under the locally trusted
build process; it is not a cryptographic proof that a third-party builder compiled the
claimed source.

## Scope

FreqUI:

- prefer and validate the explicit full commit supplied by the reviewed Root build;
- keep standalone local Git fallback and ad-hoc `unknown` behavior;
- trim the Git fallback output;
- avoid duplicating an identical commit already present at the end of `/ui_version`;
- add focused unit coverage for identical, ordinary release, and mismatched version
  combinations; and
- run production builds with valid full revisions plus rejection checks for malformed
  explicit revisions.

Root packaging:

- pass the optional revision into the FreqUI builder;
- write the exact no-newline marker into the built `dist` copied to `ui/installed`;
- remove the historical wrong-path marker;
- pass `CommitIdentity.frontend` in both reviewed runtime and operator build commands;
- verify the marker from the immutable image ID before accepting either image; and
- extend the existing provenance unit tests without changing Compose or creating a new
  build system.

Documentation:

- record this approved plan as the active bounded implementation;
- record the reviewed-versus-ad-hoc distinction and the narrower local Buildx evidence
  boundary;
- leave frozen historical acceptance reports unchanged; and
- retain all existing strategy, market-data, Runtime, Paper, Live, and holdout gates.

## Acceptance

- The reviewed build commands derive and pass the full frontend object ID from
  `CommitIdentity.frontend`; no CLI or environment input can choose the reviewed identity.
- Runtime and operator command tests require the frontend build argument and retain the
  complete exact Root/backend/frontend label set.
- Explicit valid 40- and 64-hex revisions build; explicit short, uppercase, whitespace,
  non-hex, or otherwise malformed revisions fail. Standalone FreqUI and ad-hoc Root
  builds remain usable without a reviewed value.
- `ui/installed/.uiversion` contains exactly
  `local-frequi-<full frontend object ID>` with no newline; the old historical value and
  parent-directory marker are absent from the reviewed identity path.
- The reviewed helper checks the marker from the immutable image ID with the stated
  isolation flags and rejects every mismatch before returning success.
- `/ui_version` returns the exact marker and the packaged browser displays the same full
  frontend identity once, with no `unknown`, stale `f5a81466`, or duplicated SHA.
- Canonical reviewed and canonical ad-hoc markers deduplicate, while an ordinary release,
  a different SHA, and a noncanonical value ending in `unknown` remain visibly combined.
- A simulated marker-read timeout removes only the exact container ID captured through
  the temporary cidfile and leaves no verifier container behind.
- The reviewed image's three existing revision labels match the committed Root tree.
- A normal ad-hoc `docker compose config` and build path still work without revision
  environment variables and cannot pass reviewed-image verification.
- Focused root unit tests, focused FreqUI unit tests, FreqUI typecheck/build/changed-file
  lint, Compose rendering, `git diff --check`, reviewed exact-image construction, isolated
  `/ui_version`, and packaged-browser verification pass.
- No market data, retired holdout, strategy execution, Backtest, Recursive Analysis,
  Lookahead Analysis, exchange connection, Paper, Live, or trading database is used.

## Rejected alternatives

### Copy `.git` or install Git in the Root UI builder

Rejected. The committed archive intentionally excludes repository metadata and is the
stronger input boundary. Adding Git only lets a component guess; it does not improve the
Root-controlled composition proof.

### Require revision args in Dockerfile or Compose

Rejected. Compose cannot derive a submodule SHA, and required interpolation would break
normal builds plus emergency commands that do not build at all. Reviewed fail-closed
behavior belongs in the existing reviewed wrapper.

### Trust build args, labels, or `/ui_version` independently

Rejected. They are caller-controlled declarations. They become useful evidence only
when the reviewed helper derives their values from the committed tree, builds the
committed archive, and checks the resulting immutable image consistently.

### Add strategies or a second embedded-revision label

Rejected. Strategies are not packaged in this image, and the existing three revision
labels already describe every repository component that is actually built into it.

### Add `/build-info`, a registry, signatures, SBOM, or remote SLSA verification

Deferred. Those are separate publication and supply-chain decisions. This local P2 does
not justify a new API, service, database, signing system, remote builder, or release
platform.

## Explicit non-goals

- no backend API schema/version, route, authentication, persistence, or analysis change;
- no `docker-compose.yml`, Runtime manifest, platform registry, operator lifecycle, or
  deployment topology change;
- no chart, Backtest, Recursive Analysis, Lookahead Analysis, strategy, Experiment,
  StrategyRelease, BotRelease, RuntimeInstance, Paper, Live, or AI behavior change;
- no strategy-repository image label, market-data access, strategy evaluation, holdout
  assignment/use, performance evidence, promotion, or profitability claim; and
- no claim of trusted SLSA provenance, hermetic/reproducible builds, complete dependency
  resolution, or third-party-verifiable source origin.
