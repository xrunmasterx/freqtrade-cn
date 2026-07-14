# Task 7.5: typed operator CLI, one-shot carrier, and Root Safety closure

## Assumptions and corrected boundaries

- The fixed paper probe remains the only writable use case in this task. It is
  Digital Assets / Spot / Bitget / paper / `SampleStrategy`; no lifecycle or
  trading command is added.
- `platform_operator` keeps the Task 7.4 database allowlist: `CONNECT`, `USAGE`,
  and `SELECT, INSERT` on the seven registration tables. This task must not add
  `UPDATE`, `DELETE`, `TRUNCATE`, sequence, routine, secret-version, lifecycle,
  Docker, or exchange authority.
- The CLI does not accept a repository path, Git ref, commit, DSN, market,
  product, venue, environment, strategy, artifact path, policy, image, command,
  mount, port, network, Compose project, secret, or lifecycle verb.
- The reviewed operator image owns the exact root commit identity in the
  read-only file `/opt/platform-operator/root-commit`. The CLI reads that full
  lowercase object ID and revalidates the committed blobs against the mounted
  checkout evidence. It never resolves a caller-selected ref.
- The existing `CommittedGitStore` clean-check requires HEAD, index, refs,
  objects, and checkout metadata. Therefore the smallest compatible mount is
  the normal checkout's complete `.git` directory, read-only, plus only the
  reviewed non-secret worktree paths. Rewriting the trust module to consume an
  object-only store is outside this task. Linked-worktree `.git` indirection is
  rejected operationally; a normal recursive checkout is required.
- Docker/Compose administrators remain platform root. They can override an
  entrypoint, mount, or environment and are outside the operator service's
  isolation claim. Normal operators use only the reviewed wrapper/CI invocation
  and typed arguments.
- Local execution in this task remains offline. No Docker, PostgreSQL, network,
  runtime, exchange, or trading process is started without separate authority.

## Verifiable delivery slices

### 1. Typed CLI

Create `tools/runtime_registry_cli.py` and focused tests.

- `runtime-template validate` performs only committed template, policy, and
  paper-probe artifact validation.
- `runtime-template publish --actor platform-operator` constructs
  `SqlTemplateRepository` and calls
  `RuntimeApplicationService.publish_template`.
- `runtime-registry register-paper-probe --actor platform-operator` and
  `runtime-registry compile --actor platform-operator` construct
  `SqlPaperProbeRegistrationRepository` and call the same
  `RuntimeApplicationService.ensure_paper_probe_registration` method with the
  same fixed request.
- `runtime-registry status --instance-id phase2-spot-paper-probe` calls
  `RuntimeApplicationService.registration_status`.
- Parsing finishes before any database engine or service is constructed.
  Unknown/raw-power arguments exit 2. Application failures expose one stable
  code only. Success is compact, sorted canonical JSON containing only fixed
  identifiers, status, commit IDs, and digests.

### 2. Independent operator image and Compose carrier

- Add `platform-operator-image` after `runtime-image`; only this stage installs
  Git and copies the reviewed operator modules into a fixed image path.
- Add a final pass-through stage from `runtime-image` so the default integrated
  image remains the ordinary runtime image.
- Extend the committed image builder with one explicit operator build command.
  It builds the fixed target from the already verified committed context,
  passes `CommitIdentity.root` as the sole root-commit build argument, and
  verifies the exact provenance labels.
- Add `platform-operator` as a one-shot Compose service: no `container_name`, no
  ports, `restart: "no"`, read-only root filesystem, all capabilities dropped,
  no-new-privileges, only `platform-db`, only the operator database secret, and
  a fixed image-owned CLI entrypoint.
- Mount `.git` read-only and only `ops/adapter-templates`,
  `ops/runtime-policies`, `ft_userdata/user_data/config.example.json`,
  `ft_userdata/user_data/strategies/sample_strategy.py`, and
  `ops/config/trading-safety.json` at matching synthetic-worktree paths. Do not
  mount the full worktree, runtime state, secret roots, Bot configs, or Docker
  socket.

### 3. Real PostgreSQL Root Safety gate

- Provision and mount the operator database secret in CI.
- Run the PostgreSQL-backed template and registration repository selectors,
  including concurrency/advisory-lock coverage, with JUnit skip count exactly
  zero.
- Build the committed operator image, run validate, publish, register/compile,
  and status twice through the fixed carrier, and compare stable outputs.
- Prove raw-power and live-environment flags fail before database construction.
- Connect with the actual operator login and prove only the seven-table
  `SELECT, INSERT` allowlist. Prove database/schema/table/column/sequence/routine
  and PostgreSQL 17 `MAINTAIN` denials.
- Contaminate PUBLIC/null/default ACLs and fixed-role direct routine EXECUTE and
  relation MAINTAIN. A fixed-role routine ownership contamination must make
  reconciliation fail closed; after administrator ownership restoration, the
  rerun must remove the supported ACL drift. Repeat the effective denial probes.
- Preserve the existing network, temporary-volume, and cleanup drift checks.

### 4. Review and gitlink

- Review backend Task 7 commits independently before staging the root gitlink.
- Review the root CLI/operator/workflow diff independently and repair every
  Major or Minor finding.
- Only after both reviews and all offline gates pass, update the root `freqtrade`
  gitlink to the exact reviewed backend commit and record progress.
- Publishing, PR creation, online Root Safety execution, and merge remain
  separately authorized actions.
