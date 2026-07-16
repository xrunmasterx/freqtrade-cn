# Runtime Registry v2 Phase 2C Task 4A Contract Repair

**Status:** Implementation clarification
**Date:** 2026-07-16
**Applies to:** Phase 2C Task 4A and the Task 4B pre-mutation boundary

## 1. Problem

The original Task 4A plan correctly requires a pure, dependency-free
`LaunchSnapshot` compiler, but the implemented Phase 2B/2C contracts do not yet carry
enough trusted information to compile a production launch.

Four concrete gaps are present in the merged code:

1. `RuntimeSpecCompiler` validates `strategy_class_name` in the compile request but
   `RuntimeSpecPayload` does not persist it. A restarted Supervisor therefore cannot
   recover the exact strategy class from the immutable RuntimeSpec.
2. The committed runtime-policy documents contain only allowed policy IDs. They do not
   define executable argv templates, mount roles and targets, environment bindings,
   health timing and argv, resource values, runtime user, working directory, internal
   ports, or deterministic network-name derivation.
3. A pure compiler cannot inspect the host filesystem and therefore cannot itself prove
   that a source is not a symlink, junction, reparse point, device, named pipe, or path
   that escaped after validation.
4. `LocalFileSecretProvider` returns an open `SecretMaterialHandle` containing a file
   descriptor, reference ID, and version ID, while `LaunchSnapshot.SecretMount` requires
   a host `Path`. There is no reviewed conversion from the live provider lease to a
   revalidatable Docker mount source.

Implementing only the two original Task 4A files would hide these gaps behind test-only
fixtures. It would not create a launch chain that Task 4B can safely consume.

## 2. Goals

- Preserve a pure `python -S` snapshot compiler with no filesystem, environment, Git,
  database, Docker, subprocess, network, or clock I/O.
- Persist every command-affecting RuntimeSpec field needed to recover one exact Bot
  release, beginning with `strategy_class_name`.
- Commit actual launch-policy content rather than treating an allowlisted ID as an
  executable policy definition.
- Make material, state, and secret path provenance explicit and revalidatable at the
  final Task 4B pre-mutation boundary.
- Keep `LaunchSnapshot` internal and reject every mapping/public API/repository ingress.
- Preserve compatibility for already-persisted Phase 2B RuntimeSpecs without silently
  inventing missing launch material.

## 3. Non-goals

- No Docker or Compose action in Task 4A.
- No runtime network create/connect/disconnect/remove action; those remain Task 5.
- No health polling, retry, ambiguous outcome recovery, or failure latch; those remain
  Task 6.
- No Supervisor daemon, lease loop, lifecycle CLI, or online exchange access; those
  remain Task 7.
- No fallback strategy name, command, host path, secret path, network name, or resource
  value may be guessed from an instance kind, market, account, environment, or legacy
  service name.

## 4. Architecture resolution

Task 4A is split into three independently reviewable slices. The pure compiler remains
the only component that can create `LaunchSnapshot`, but it consumes provider-minted,
typed capabilities rather than pretending that path strings prove filesystem provenance.

```text
committed RuntimeSpec + committed launch-policy catalog
        + verified material/state/secret leases
        + exact DriverIdentity
    -> pure correlation and compilation
    -> internal LaunchSnapshot
    -> Task 4B pure validation + lease/path revalidation
    -> one validated Compose mutation kernel
```

### 4.1 Task 4A-1: Recoverable RuntimeSpec launch identity

Add `strategy_class_name` to `RuntimeSpecPayload` and emit it from
`RuntimeSpecCompiler._build_payload()`.

Compatibility policy:

- the field is optional only for decoding an already-persisted legacy RuntimeSpec;
- canonical validation omits an absent optional field so an existing digest remains
  truthful;
- every newly compiled RuntimeSpec includes a validated strategy class;
- Task 4A compilation rejects a legacy RuntimeSpec with no strategy class using one fixed,
  redacted policy error;
- there is no default such as `SampleStrategy` outside the already-closed paper-probe
  compile request;
- an operator must recompile/re-register a legacy RuntimeSpec before dynamic launch.

This is a compatibility read path, not a compatibility launch path.

### 4.2 Task 4A-2: LaunchSnapshot authority-binding seam

Add one required lowercase SHA-256 `launch_authority_digest` to the internal
`LaunchSnapshot` value. It has no default or legacy fallback because a LaunchSnapshot is
an attempt-scoped internal value and is never restored from an API, mapping, or repository.
Every internal construction site must provide it explicitly, and mapping ingress remains
rejected.

This field is only the structural seam for the later authority check. Possessing or copying
a digest does not prove that the rest of a snapshot is authorized. Task 4A-5 must receive an
independently injected typed authority, deterministically compile the complete expected
snapshot, require full snapshot equality, and also require this digest to match. It must
reject a snapshot that copies the correct digest but changes any identity, argv,
environment, mount, port, health, user, or resource field.

### 4.3 Task 4A-3: Committed executable launch-policy catalog

Add a canonical committed launch-policy catalog whose entries contain actual values.
The existing policy-ID registries remain allowlists and do not become executable content.
The catalog loader performs Git/blob/digest verification before it mints a frozen typed
`ResolvedLaunchPolicyBundle`.

The closed bundle contains:

- exact policy IDs and source commit/digest;
- a command token template using a closed token enum, never a shell string;
- closed non-secret environment bindings;
- working directory and non-root runtime user;
- mount-role definitions and fixed absolute container targets;
- internal ports only;
- complete health profile argv and bounded timing/retries;
- concrete integer CPU, memory, and process limits;
- deterministic network-name rules, not caller-supplied names.

Only these command token bindings are initially permitted:

- committed literal;
- RuntimeSpec `strategy_class_name`;
- a fixed target produced by an exact mount role;
- a fixed state-layout target.

No generic string formatting, environment expansion, shell interpolation, arbitrary
executable, or caller-provided argument is permitted.

The loader is I/O-capable and is not part of `tools.runtime_snapshot`. The pure compiler
accepts only the typed bundle and rechecks that every policy ID, template revision/digest,
RuntimeSpec field, and component commit matches.

The compiled snapshot carries one lowercase SHA-256 `launch_authority_digest` binding the
RuntimeSpec digest, committed template binding, complete resolved policy bundle, and
non-secret material-role manifest. This requires an explicit internal contract amendment
to `LaunchSnapshot`; otherwise the future driver could perform only structural blacklist
validation and could not prove equality with the committed launch authority.

### 4.4 Task 4A-4: Provider-minted source leases

Filesystem provenance is split deliberately:

- material/state/secret providers perform real path resolution, type, permission,
  containment, link/reparse, ownership, and identity checks;
- providers mint immutable attempt-scoped verified-source/lease values;
- the pure compiler checks exact type, role, target, IDs, versions, roots, ordering, and
  cross-object correlations without performing I/O;
- the Task 4B driver revalidates the exact source identity and active lease immediately
  before render/action mutation;
- a closed/expired/missing lease or changed filesystem identity fails before any Docker
  subprocess.

The provider capability must distinguish these roles:

- committed runtime config;
- committed strategy material;
- committed safety policy;
- exactly one managed writable state allocation;
- version-pinned secret material.

Secret requirements:

- the provider, never the compiler, determines the source path;
- the lease retains reference ID, version ID, provider identity, source identity, and an
  open lifetime covering compiler, repository `begin_attempt`, driver launch, and result
  recording;
- no raw secret value can enter RuntimeSpec, resolved attempt material, policy bundle,
  `LaunchSnapshot.argv`, normal environment, read-only config mounts, logs, or errors;
- closing the lease invalidates future source access/revalidation;
- Task 4B may render only a source that still matches the provider-held lease.

The pure compilation authority and the live provider capability remain separate types.
`tools/runtime_preparation_lease.py` retains the exact material, state, and secret leases
that minted one `LaunchCompilationAuthority`; its pre-action method revalidates all three
sources before any runtime mutation. The managed-state provider also retains an internal
immutable projection of every minted mount field. Public mount DTO identity alone is not
treated as proof because a frozen Python object can still be modified by privileged
in-process code.

## 5. Task 4A-5 pure compiler contract

`tools/runtime_snapshot.py` exposes only frozen typed inputs and these operations:

```python
compile_launch_snapshot(
    spec,
    template,
    policies,
    state,
    secrets,
    materials,
    identity,
) -> LaunchSnapshot

validate_launch_snapshot(snapshot) -> None
validate_rendered_snapshot(rendered) -> None
```

The exact grouping may use one frozen compilation-input object to keep the function
surface small. Raw mappings are rejected at every ingress and are never forwarded to
`LaunchSnapshot.model_validate()`.

The final signatures must retain the expected authority explicitly rather than consult a
global default catalog:

```python
validate_launch_snapshot(snapshot, expected_authority) -> None
validate_rendered_snapshot(rendered, snapshot, expected_authority) -> None
```

Both validators require `snapshot.launch_authority_digest` to equal the canonical digest
of `expected_authority`. That equality is necessary but not sufficient: the launch
validator deterministically recompiles the complete expected snapshot from the typed
authority and requires exact snapshot equality. The rendered validator first performs
that full check and then proves that the rendered policy exactly represents the snapshot
plus fixed hardening. The Task 4B driver obtains the authority from its injected
committed-catalog/material authority resolver and revalidates attempt-scoped leases; it
never reconstructs an authority from caller data or treats a caller-carried digest as an
authority.

Compilation must prove:

- RuntimeSpec payload digest equals `identity.runtime_spec_digest`;
- RuntimeSpec state allocation equals both state lease and identity;
- RuntimeSpec image/material/template/component identities equal resolved attempt
  material and the committed policy/template inputs;
- strategy class exists and is inserted only through the closed command token;
- resolved secret reference/version pairs are exact, sorted, unique, and equal to the
  RuntimeSpec and attempt material;
- material roles and mount targets are exact, sorted, unique, and non-overlapping;
- network names are derived by the closed policy and exactly equal identity;
- environment names are from the closed allowlist and contain no secret-class names;
- exact image, one state mount, non-root user, internal-only ports, bounded health and
  resource values are present.

The current Freqtrade image entrypoint also requires three secret-file path environment
bindings: `FT_API_PASSWORD_FILE`, `FT_JWT_SECRET_FILE`, and `FT_WS_TOKEN_FILE`. Task 4A-5
therefore amends the internal `LaunchSnapshot` with a frozen typed
`SecretPathEnvironmentBinding` tuple. Each binding contains only an approved environment
name and the target of its exact `SecretMount`; it cannot contain a secret value, caller
string, or host source path. The ordinary `EnvironmentEntry` contract continues rejecting
secret-class names. The pure compiler derives these bindings from the closed policy and
secret mounts, includes them in the complete authority digest and equality check, and the
Task 4B renderer may emit only those exact path-valued bindings. Without this typed field,
the paper probe is not launchable and Task 4A-5 cannot be accepted.

## 6. Final rendered-policy validator

The pure rendered validator accepts one internal typed rendered-container-policy value,
not arbitrary Compose YAML/JSON. It rejects any representation of:

- restart other than `no`;
- host networking, host PID/IPC, privileged mode, devices, added capabilities, or Docker
  socket/named-pipe access;
- host-published ports;
- more than one writable mount or any writable input/secret mount;
- missing `cap_drop=ALL`, `no-new-privileges`, or read-only root filesystem;
- caller labels, container/project overrides, arbitrary networks, shell command strings,
  raw credentials, or non-allowlisted environment;
- source/target/role changes relative to the compiled snapshot.

The pure validator checks attested structure. Task 4B separately performs real filesystem
and lease revalidation immediately before mutation. Neither check substitutes for the
other.

## 7. Implementation order

1. **Task 4A-1:** Backend-compatible RuntimeSpec `strategy_class_name` persistence and
   migration tests; publish Backend first and update the Root gitlink only after review.
2. **Task 4A-2:** amend the internal `LaunchSnapshot` contract with the exact
   `launch_authority_digest` binding and preserve mapping-ingress rejection.
3. **Task 4A-3:** committed executable policy schema/content, loader, mutation tests, and
   exact paper-probe policy fixture.
4. **Task 4A-4:** material/state/secret provider lease contracts and lifecycle tests.
5. **Task 4A-5:** pure `runtime_snapshot` compiler, ingress tests, mutation tests, and
   import-purity tests.
6. Independent architecture/security and code/test reviews, focused regression, full Root
   regression, Backend publication, Root gitlink integration, and Root Safety.
7. Only after all Task 4A gates pass may Task 4B introduce a concrete Docker actor.

## 8. Acceptance criteria

Task 4A is complete only when all of the following are proven:

1. a new RuntimeSpec persists its exact strategy class while legacy specs remain readable
   but are rejected for launch;
2. the committed policy source contains complete executable definitions, not only IDs;
3. no pure compiler or validator performs I/O, including import-time I/O;
4. no test fixture can substitute a generic mapping for a trusted compiler input;
5. provider tests prove real link/reparse/escape/identity rejection and lease closure;
6. compiler tests prove exact cross-object correlation and deterministic output;
7. rendered-policy mutation tests prove every forbidden Docker capability fails closed;
8. Task 4B has enough retained provenance to revalidate every host source immediately
   before mutation;
9. no Docker, exchange, network mutation, or online operation occurs in Task 4A;
10. all focused and existing Phase 2B/2C regression gates pass with no open Critical or
    Important review finding.
