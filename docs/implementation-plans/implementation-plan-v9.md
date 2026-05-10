# Implementation Plan v9: Persistence And Concurrency Foundation

## Metadata

- Status: plan quality gate passed; ready for phase implementation
- Related planning notes:
  `docs/implementation-plans/roadmap-v9-planning-notes.md`
- Related source docs:
  - `docs/implementation-plans/implementation-roadmap.md`
  - `docs/implementation-plans/implementation-plan-v8.md`
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/execution.md`
  - `docs/features/reliability.md`
  - `docs/features/run-catalog.md`
  - `docs/features/sweeps.md`
  - `docs/features/remote-stores.md`
  - `docs/features/artifacts.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/slurm.md`
  - `docs/features/testing.md`
  - `docs/loom.md`
  - `docs/structure.md`
- Draft pass: complete on 2026-05-09 from confirmed roadmap v9 planning notes
- Refine pass: complete on 2026-05-09 from local hidden-decision and
  downstream-compatibility review
- Post-review decision pass: complete on 2026-05-09; submitted operations,
  Phase 4/5 public hard-swap split, fenced worker finalization, artifact
  commit semantics, and backend-owned lease time are recorded
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no
  blocking or non-blocking findings remained.
- Blockers: none.

## Goal

Implement Loom's v9 persistence and concurrency foundation.

V9 replaces the active local-file run-state truth path for new runs with a
SQLite-first authoritative backend behind backend-neutral contracts. It also
establishes the stage attempt, lease, submitted-operation, output commit,
revision, capability, projection, read-model, materialization, and cross-run
coordination semantics required by future bounded parallel DAG execution, large
sweeps,
shared-filesystem operation, remote-capable stores, bundles/exporters, and
stronger service backends.

This is a hard swap for new active run state. There is no old-run migration
path and no legacy local-file fallback.

## Context

V8 is complete and merged. It added `loom.runs.RunCatalog`, local collection
listing, a rebuildable SQLite sidecar catalog, metadata-only comparison,
warning-returning result models, and `loom runs index/list/diff` commands. The
v8 catalog is explicitly derived: it accelerates query and comparison behavior
but does not own run truth.

The current active execution path is still built around a local run-store
directory and mostly serial mutation. That is workable for one local controller
but insufficient as the foundation for:

- multiple stage writers in one run;
- concurrent or distributed sweep trials;
- recovery from abandoned attempts and leases;
- shared filesystems with uncertain lock, mtime, rename, and visibility
  guarantees;
- remote or service-backed stores with explicit consistency limits;
- active state queries that must not rely on derived projections or stale
  human-readable files.

The confirmed v9 direction is to make a stronger backend authoritative for
active run state and to keep user-facing query projections derived from that
authority. The refinement pass makes explicit that this is a larger refactor
than the initial six-phase draft: it touches storage, execution,
materialization, query, diagnostics, local parallelism, and future
coordination boundaries.

## Desired Outcome

When all phases are complete:

- New active runs use the SQLite-first authoritative backend automatically.
- Runner, resume, status, diagnostics, catalog refresh, and future sweep
  consumers read live truth from backend contracts where current state matters.
- Legacy human-readable state files such as status or artifact index files are
  not live truth and are not fallback truth for new runs.
- Local files may still exist for logs, artifact payloads, config/provenance
  copies, worker materialization, and later derived exports, but not as the
  active state authority.
- A backend-neutral authoritative run read model exists for status, catalog,
  diagnostics, and later bundle/export input. It is not a user-facing export or
  snapshot workflow in v9.
- The authoritative per-run backend owns run, stage, attempt, run/controller
  lease, stage lease, submitted-operation, output commit, artifact fact,
  event/audit, revision, and snapshot records for one run.
- The per-run SQLite database is run-local and travels with the run root for
  ordinary local movement. Its exact path, schema, and table names remain
  private implementation details.
- A separate workspace/sweep coordination authority owns only cross-run facts:
  workspace or sweep identity, trial references, trial leases, resource leases,
  global concurrency counters, `run_uri` references, and recovery scans.
- `RunCatalog`, status summaries, backend diagnostics, and future sweep
  dashboards remain projections over authoritative revisions or snapshots.
- `RunStatus` and `StageStatus` remain coarse. Attempt, lease, commit,
  recovery, reason, owner, message, detail, and display-phase information lives
  in first-class records or derived lifecycle snapshots.
- Submitted-operation records are first-class authoritative facts. Coarse
  `SUBMITTED` run or stage statuses are summaries, not the scheduler or worker
  submission truth.
- Per-stage committed artifact facts are authoritative. Run-level artifact
  indexes are derived or transactionally materialized views, not independent
  truth.
- Audit events are not authoritative state, but they carry backend revision or
  sequence evidence so diagnostics and later event sinks can relate events to
  committed runtime facts.
- `loom backend ...` exposes minimal read-only backend inspection and
  debugging commands without repair, mutation, export, SQL, or snapshot
  behavior.
- Bounded local parallel stage execution is available through Python API and
  CLI when explicitly requested and when backend capabilities are present.
- Serial execution remains the default.
- Explicit parallel requests fail loudly if required backend capabilities are
  missing.
- Shared-filesystem and remote-store assumptions produce loud diagnostics when
  the selected backend cannot prove required guarantees.
- Default validation remains local, deterministic, synthetic, and
  filesystem-only.

## Non-Goals

- No migration path for v0-v8 local run directories.
- No legacy local-file state compatibility mode or fallback for new active
  runs.
- No human-readable live-state files as a correctness requirement.
- No user-facing derived export or snapshot workflow in v9.
- No backend repair or mutation CLI commands.
- No public SQLite schema or supported external SQL query contract.
- No full arbitrary shared-filesystem support.
- No full remote authoritative store implementation.
- No Postgres, hosted service, cloud SDK, or scheduler-backed backend
  implementation.
- No distributed controller or scheduler-backed parallel execution policy.
- No multi-controller execution for one run.
- No full sweep runner, adaptive sweep algorithm, fairness policy, or
  scheduler queue semantics.
- No dynamic DAG mutation, dynamic fan-out, or runtime creation of arbitrary
  stage definitions.
- No domain-specific metric, artifact payload, or project-code interpretation.

## Constraints

- Keep `loom` domain-neutral.
- Preserve source-tree boundaries from `docs/structure.md`.
- Keep persistence contracts and local backend implementations under the
  pipeline store boundary unless plan review identifies a stronger boundary.
- Keep execution orchestration in `loom.pipeline.execution`.
- Keep sweep/workspace coordination separate from per-run stage lifecycle.
- Keep `loom.runs` as a derived query facade, not an active state authority.
- Keep CLI modules as presentation over public APIs and diagnostics.
- Use `run_uri` as the stable public identity for runs.
- Treat authored configs as trusted project code, but do not import project
  stage code for backend inspection, catalog refresh, status, recovery, or
  bundle-ready metadata reads.
- Use the Python standard-library `sqlite3` module for the v9 backend.
- Do not add heavyweight runtime dependencies without a separate design reason.
- Keep transactions short and make compare-and-set, lease, commit, and revision
  boundaries explicit.
- Capability failures must be loud for explicitly requested parallel,
  shared-filesystem, or remote-capable behavior.
- Default tests must not require network services, real clusters, hosted
  trackers, or non-local databases.
- Use `make validate-pr` before phase PR review and `make test-summary` before
  PR preparation.

## Design Principles

- One active source of truth. Do not dual-write SQLite and human-readable files
  as coequal active state.
- Backend-neutral contracts first. SQLite is the first implementation, not the
  public contract.
- Strict authority boundaries. Per-run correctness, cross-run coordination,
  and derived query projection are separate responsibilities.
- Coarse machine status, rich structured detail. Durable status values remain
  stable while attempts, leases, commits, reasons, and display snapshots carry
  concurrency detail.
- Submitted work is structured state. Scheduler submissions, worker handoff,
  cancellation attempts, and partial submission facts must not be flattened
  into status strings or ad hoc files.
- Success is a committed fact. A stage succeeds only after committed output and
  artifact facts are durable.
- Payload presence is not authority. Artifact payloads, logs, config snapshots,
  and worker files are materialized files; backend commit facts decide what is
  active truth.
- Capabilities are part of correctness. Backends must declare whether they can
  support atomic transitions, attempt allocation, leases, commits, revisions,
  recovery scans, consistent reads, and cross-run coordination.
- Queries use projections, not alternate truth. Catalogs and dashboards may
  cache but must validate against authoritative backend evidence.
- Read models are internal compatibility surfaces. They allow status, catalog,
  diagnostics, and future bundles to share one truth path without exposing
  SQLite internals.
- Parallel execution should validate the backend through real behavior without
  turning v9 into a distributed scheduler.
- Future stronger backends should be optional adapters that can satisfy the
  same runner semantics.

## Key Design Choices

- Add backend-neutral per-run authority contracts before SQLite implementation.
- Implement the first authoritative backend with stdlib SQLite for new runs.
- Use a hybrid authority model:
  - per-run backend for run/stage/attempt/lease/commit/artifact/revision facts;
  - workspace/sweep coordination backend for cross-run trial/resource/global
    concurrency facts;
  - catalog and status projections for query acceleration and presentation.
- Remove legacy local-file active-state fallback for new runs.
- Define an authoritative run snapshot/read model before bundles, sweeps, or
  diagnostics reach into backend internals.
- Keep `RunStatus` and `StageStatus` coarse.
- Add first-class attempt, lease, commit, recovery, structured reason, message,
  backend revision, and derived lifecycle snapshot models.
- Add first-class submitted-operation records for scheduler submissions,
  worker handoff, cancellation attempts, active submission snapshots, and
  partial submitted-work facts.
- Make per-stage artifact commit facts authoritative.
- Treat append-only events as audit and diagnostics records, not the primary
  state machine.
- Make `RunCatalog` and status reads validate against authoritative revisions
  or snapshots.
- Keep `loom backend ...` read-only in v9.
- Add opt-in bounded local parallel stage execution with serial default.
- Use one active run controller per run in v9. The controller may coordinate
  multiple stage workers or local stage leases, and submitted workers may
  self-finalize attempt-scoped facts only through backend fencing tokens, but
  multi-controller execution for the same run is deferred.
- Use a default bounded-parallel failure policy that stops leasing new stages
  after terminal failure while allowing already-running attempts to finish.
- Add a policy flag that can continue scheduling independent non-dependent
  ready DAG branches after an unrelated failure.
- Support static runtime-conditioned DAG outcomes as persisted lifecycle facts.
  A not-selected branch is represented as `StageStatus.SKIPPED` plus a
  structured outcome/reason such as `not_selected`, not as a new status.
- Add a compact workspace/sweep coordination contract in v9 so v11 sweeps and
  future multi-run concurrency do not retrofit cross-run lease semantics later.

## Hidden Decisions Locked By V9

- **Run-local authority placement:** the per-run SQLite authority is created
  inside the run root or an equivalent run-local location that moves with the
  run. Exact path and table names are private.
- **Portability contract:** ordinary local movement of a run root preserves the
  authoritative backend. Explicit export/import in v10 must use the
  authoritative read model instead of depending on private SQLite tables.
- **Schema evolution:** v9 initializes and reads the current v9 schema. Unknown
  newer schemas and unsupported older active-state schemas fail loudly. V9 does
  not perform destructive automatic migrations. Future schema migrations require
  explicit roadmap or phase scope.
- **Controller model:** v9 has one active run controller per run. Stage workers
  may be concurrent, but they operate under controller-owned scheduling and
  backend-enforced stage leases. Local and subprocess workers remain
  controller-finalized by default. Submitted or scheduler-backed workers may
  self-finalize attempt-scoped facts only with a valid backend-issued
  attempt/lease fencing token. Run finalization remains controller or recovery
  owned. Multi-controller distributed execution is deferred.
- **Submitted-operation model:** submitted work is represented by
  authoritative per-run records, including submission ids, scheduler or worker
  operation ids, active state snapshots, cancellation attempts, and partial
  submission facts. `SUBMITTED` statuses are coarse summaries over these
  records, not the scheduler truth.
- **Lease model:** lease records carry owner identity, attempt id, fencing
  token, acquired/renewed/expires timestamps, release/failure reason, and
  backend revision evidence. Lease acquire, renew, and expire comparisons use
  the backend-owned clock. The SQLite backend uses a local UTC clock and is
  safe only for local or same-host coordination; shared-filesystem or
  multi-host coordination must be capability-gated with loud diagnostics until
  a stronger backend provides central time semantics. Tests use injectable
  clocks or TTLs so lease expiry is deterministic.
- **Artifact commit model:** staged payload writes are not authoritative. A
  stage output becomes active only when the backend records the output commit
  and artifact facts. Commit validates declared outputs plus payload existence
  and checksums when supported, then records output commit, artifact facts,
  derived artifact-index updates, terminal stage status, backend revision, and
  event evidence in one backend transaction where the backend can provide that
  guarantee. If backend commit fails after payload staging, the stage commit
  fails and staged payloads become cleanup candidates. If backend commit
  succeeds and a payload later disappears, backend truth remains committed and
  diagnostics warn about the missing payload.
- **Event ordering:** events are audit-only but include event id, event time,
  event name, resource identifiers, and backend revision or sequence evidence.
  They do not drive state transitions.
- **Static branch outcomes:** skipped, not-selected, and blocked outcomes are
  lifecycle facts over a planned static graph. V9 does not create runtime stage
  definitions or mutate the planned graph shape.
- **Workspace/sweep boundary:** the workspace/sweep authority references
  ordinary `run_uri` values and owns cross-run admission/resource facts only.
  It does not duplicate per-stage run state and does not replace the derived
  run catalog.

## Downstream Compatibility Contract

- **V10 run bundles and exporters:** consume the authoritative run read model
  for metadata-only bundle manifests, completed-run inspection, payload
  selection metadata, checksums, and stale/corrupt warnings. V10 must not read
  private SQLite tables or legacy local state files as truth.
- **V11 deterministic sweeps:** remain deterministic collections of ordinary
  runs. Sequential sweep manifests can stay document-shaped; the v9
  workspace/sweep coordination contract is a future concurrency foundation, not
  the mandatory canonical store for simple sequential sweeps.
- **V12 plugins:** can later discover backend, exporter, and event sink
  adapters without importing plugin code during core status, catalog,
  diagnostic, or recovery paths.
- **V13 remote store contract:** depends on v9 capability vocabulary and
  artifact commit semantics. Remote refs remain metadata until explicitly
  materialized; cache/staging files are not authority.
- **V14 remote store operations:** can add upload/download/materialization over
  committed artifact facts without changing per-run lifecycle semantics.
- **V15/V16 containers and HPC:** can use the same worker materialization,
  submitted-operation records, durable read model, and fenced worker
  finalization path so container or scheduler jobs do not reconstruct state
  from ad hoc local files.
- **V17 reliability policies and event sinks:** reuse v9 attempt, lease, commit,
  submitted-operation, revision, event ordering, reason, and cleanup-candidate
  records. Retry, timeout, cancellation, and submitted-worker policy decisions
  build on committed output transactions instead of inventing a second state
  machine.
- **V18 cleanup and retention:** uses cleanup candidate records and committed
  artifact facts to avoid deleting active or ambiguous payloads.

## Conflicts And Tradeoffs

- Hard swap vs compatibility: v9 accepts that old local run directories are not
  migrated so the new active state model can avoid split-brain fallback paths.
- SQLite-first vs future stronger backends: SQLite gives immediate
  transaction and constraint support without new dependencies, but it is not
  the final answer for high-concurrency distributed controllers or remote
  authority.
- Hybrid authority vs simpler storage: two authority scopes add design surface,
  but they keep per-run correctness separate from cross-run scheduling and
  avoid promoting the derived catalog into active truth.
- Coarse statuses vs operational detail: keeping statuses stable requires more
  structured side records, but avoids public enum churn and mirrors the
  coarse-machine-state plus display/detail split seen in mature orchestrators.
- Read-only backend CLI vs operational convenience: v9 gives inspection and
  diagnostics but defers repair/export so debugging tools cannot become unsafe
  mutation paths or alternate state workflows.
- Internal read model vs no snapshot surface: v9 needs one backend-neutral
  read path for status/catalog/diagnostics/future bundles, but it must not
  become a user-facing export feature ahead of v10.
- Bounded local parallelism vs broader scheduler behavior: v9 validates real
  concurrent claim/commit semantics without committing to distributed
  controller, queue, fairness, or scheduler integration policy.
- Projection freshness vs query speed: catalog/status reads must validate
  against backend revisions for current truth, accepting refresh overhead where
  necessary.

## Maintainability Assessment

The primary maintainability risk is split-brain state. This plan avoids that by
making the per-run backend the active authority for new runs and by explicitly
demoting local state files, run catalogs, status summaries, and events to
payload, projection, or audit roles unless they are written transactionally as
backend facts.

The second risk is overloading one database with every responsibility. The
hybrid design keeps run correctness and cross-run coordination separate. The
same SQLite implementation may support both scopes locally, but the contracts
must not let workspace/sweep tables mutate per-stage state or let per-run
tables own sweep resource policy.

The third risk is public API sprawl. Phase 1 must define a small protocol and
model vocabulary and avoid exposing SQLite table details. Capability records,
result records, diagnostics, and read models should be stable; schema layout
should remain private.

The fourth risk is runner/query drift. Runner, resume, status, catalog, and CLI
paths must call shared store/query helpers rather than reimplementing state
interpretation. The refined eight-phase split separates contracts, backend,
materialization/read models, write-path swap, read-path swap, diagnostics,
parallelism, and workspace coordination so drift is reviewable.

The fifth risk is concurrency behavior that is correct only under tests. The
plan requires contract tests and synthetic concurrent worker tests for attempts,
leases, commits, recovery, loud capability failures, projection freshness, and
materialization boundaries.

The sixth risk is later roadmap coupling to private SQLite. The authoritative
read model and downstream compatibility contract prevent bundles, sweeps,
remote stores, reliability, and cleanup from reaching into private schema.

## Extensibility Assessment

The backend contract is the main extension point. Later Postgres, service, or
remote-capable backends should satisfy the same transition, lease, commit,
revision, snapshot, and recovery semantics without changing runner behavior.

The hybrid authority model supports future v11 deterministic sweeps and
multi-run concurrency. Sweep controllers can claim trial and resource leases in
the workspace coordination scope, then delegate each trial to ordinary per-run
execution. Future scheduler-backed execution can map the same coordination
records to worker pools, queue slots, scheduler jobs, or service-side
controllers.

Keeping status coarse preserves compatibility for Python API, CLI JSON, and
future dashboards. Derived lifecycle snapshots can gain fields or selected
stable display phases later if user automation proves it needs them.

Derived catalog and status projections remain replaceable. A future remote
catalog service can be added only if it declares whether it is authoritative or
a projection and preserves the run backend as the conflict winner for active
truth.

The read-only backend CLI gives users and implementers visibility into the new
backend without creating long-term obligations around repair or export. V10
bundle/export work can later design derived snapshots explicitly using the v9
read model as input.

Materialization is explicit enough for containers, SLURM, and remote stores to
coexist: workers may receive files or paths as handoff material, while state
readers and commit logic continue to use backend facts.

Submitted-operation records and fenced worker self-finalization keep current
SLURM-style submitted work on the same lifecycle model as local workers.
Future scheduler adapters can add richer queue state, retry policy, and
cancellation behavior by extending submitted-operation detail rather than
special-casing status files or inventing another authority.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| V9 does not migrate old local run directories | The user explicitly chose a hard swap and no compatibility fallback to avoid split-brain active truth. | Users need to inspect or bundle old runs through new tools, or V10 import/export work defines a safe derived migration path. |
| SQLite is the only authoritative backend implemented in v9 | It provides standard-library transactions and constraints without heavyweight dependencies. | Multi-host writers, high write concurrency, remote authority, or service-backed sweeps require capabilities SQLite cannot safely provide. |
| SQLite lease time uses a local UTC clock | V9 SQLite coordination is intentionally local or same-host; a service backend is the right place for central time semantics. | Shared-filesystem, multi-host, scheduler-backed, or remote-controller execution needs safe distributed lease expiry. |
| Two authority scopes increase conceptual surface | Strict separation prevents per-run correctness, cross-run coordination, and derived query projection from being confused. | V11 sweep execution or the first non-SQLite backend shows the contracts cannot share capability vocabulary cleanly. |
| Phase 4 keeps backend selection internal before the public hard swap | The write-path integration must be independently mergeable without exposing new public runs to read paths that still use legacy assumptions. | Phase 5 completes backend-backed planning, resume, status, and catalog reads and enables the public SQLite-first default. |
| Submitted worker self-finalization expands the backend commit surface | Scheduler afterok and future submitted workers need to commit attempt-scoped outputs without a controller-side collector. | Reliability, retry, or scheduler work needs broader worker authority, run finalization from workers, or stronger distributed fencing. |
| Derived lifecycle snapshots are not a durable status enum | This avoids premature public enum expansion while preserving detailed inspection. | API or CLI users need stable display-phase values for automation rather than human inspection. |
| Workspace/sweep coordination may be contract-heavy before full sweeps exist | It prevents v11 from retrofitting trial/resource leases into the wrong authority. | The contract cannot be validated with local conformance tests, or v11 requires primitives that v9 omitted. |
| Read-only backend CLI omits repair/export convenience | It keeps diagnostics from becoming mutation or alternate truth workflows. | V10 bundle/export or a later reliability plan defines explicit safety rules for derived snapshots or repair. |
| Internal authoritative read model exists before public export workflows | Status, catalog, diagnostics, and future bundles need one truth path. | V10 export/import makes a public read/export contract and can promote or reshape the model deliberately. |
| Static runtime-conditioned DAG outcomes are supported, dynamic DAG mutation is deferred | Static outcome facts cover near-term branch behavior without destabilizing planning, provenance, and replay semantics. | Users need dynamic fan-out/fan-in or runtime stage creation as a first-class pipeline feature. |
| V9 phase count grows from six to eight | The hard swap spans storage, materialization, execution write paths, query read paths, diagnostics, parallelism, and coordination. | Plan review finds adjacent phases are small enough to combine without losing reviewability. |
| Schema migration is loud-fail only in v9 | Avoids hidden destructive migration during the first authoritative backend swap. | A future roadmap version needs to preserve active v9 runs across schema changes. |

## Plan Quality Gate

- Status: passed on 2026-05-09
- Local pre-gate review findings: incorporated in the post-review decision
  pass before the required reviewer gate.
- Required reviewer: `loom_plan_reviewer`; completed on 2026-05-09 with no
  blocking or non-blocking findings.
- Required before: creating any v9 phase execution plan or starting Phase 1
  implementation; satisfied.
- Review focus:
  - whether the plan prevents split-brain truth between SQLite state, local
    files, derived catalogs, events, and workspace/sweep coordination;
  - whether transaction, compare-and-set, attempt allocation, lease, commit,
    revision, snapshot, schema-version, read-model, materialization, and
    recovery semantics are concrete enough before implementation phases depend
    on them;
  - whether submitted-operation records are first-class enough for current
    SLURM submitted status and future scheduler-backed execution;
  - whether the Phase 4 internal write-path integration and Phase 5 public hard
    swap split keeps both phases independently mergeable;
  - whether fenced worker self-finalization is strict enough for submitted
    workers without creating multi-controller run ownership;
  - whether artifact commit semantics and backend-owned lease time are precise
    enough for concurrent and scheduler-backed futures;
  - whether the hybrid authority boundary is strict enough and does not let
    workspace/sweep coordination become another run-state backend;
  - whether the coarse status plus structured record model is understandable
    for API and CLI users;
  - whether the SQLite-first backend remains replaceable by Postgres, service,
    or remote-capable adapters;
  - whether v10 bundles, v11 sweeps, v13/v14 remote stores, and v17 reliability
    can build on v9 without reaching into private SQLite tables or legacy state
    files;
  - whether the read-only `loom backend ...` surface is minimal and does not
    imply repair, export, snapshot, mutation, or supported SQL access;
  - whether bounded parallel execution is scoped enough for one phase and
    capability-gated loudly;
  - whether shared-filesystem and remote-store limitations are explicit;
  - whether package, unit, contract, integration, e2e, and opt-in test
    obligations are sufficient.
- Loop budget:
  - Initial review: used on 2026-05-09 by `loom_plan_reviewer`.
  - Gate refinement pass: not needed; no findings required refinement.
  - Confirmation review: not needed; the initial reviewer decision found the
    plan ready for phase implementation without blockers.
- Current gate result: passed. Phase implementation may begin.

## Phased Implementation

### Phase 1 - Authority Contracts, Schema Policy, And Compatibility Surface

Status: merged
Branch: `codex/persistence-contracts`
PR: https://github.com/samcantrill/loom/pull/101

Goal:

- Define backend-neutral authority contracts, schema policy, capability
  vocabulary, read-model shape, and compatibility boundaries before behavior
  depends on them.

Scope:

- Add per-run authoritative backend protocols or equivalent contracts.
- Add compact workspace/sweep coordination protocols or equivalent contracts.
- Add backend capability models for atomic transitions, attempt allocation,
  lease acquisition/renewal/release/expiry, atomic output commit, revisioned
  snapshots, recovery scans, consistent reads, per-run coordination, and
  cross-run coordination.
- Add value models for stage attempts, run/controller leases, stage leases,
  submitted operations, output commits, artifact facts, backend revisions,
  lifecycle snapshots, structured reason codes, messages, detail payloads,
  recovery facts, cleanup candidates, and static conditional outcomes.
- Add the authoritative run read-model contract used by status, catalog,
  diagnostics, and future bundle/export work.
- Add schema-version policy models or errors for current schema, unsupported
  older active-state schemas, and unsupported newer schemas.
- Define event audit records with backend revision or sequence evidence without
  making events authoritative.
- Keep `RunStatus` and `StageStatus` coarse.
- Add errors, unsupported-capability results, and diagnostic records suitable
  for API and CLI presentation.
- Add fake or in-memory conformance stores sufficient to test the contract.
- Update `docs/structure.md` and relevant feature docs if module boundaries or
  public exports change.

Out of scope:

- No SQLite schema or real SQLite backend.
- No runner hard swap.
- No parallel execution behavior.
- No backend CLI commands.
- No user-facing export or snapshot command.
- No full sweep runner or dynamic DAG condition language.

Acceptance criteria:

- Contracts express create/open semantics, guarded status transitions, attempt
  allocation, lease ownership, lease renewal, lease expiry, release/failure
  records, atomic output commits, artifact facts, revisioned snapshots, schema
  checks, and recovery scans.
- The read model includes run status, stage statuses, attempts, leases,
  submitted operations, commits, artifact facts, materialized
  payload/log/config/provenance refs, revision evidence, schema version, and
  warnings.
- Submitted-operation contracts can record, list, inspect, and summarize
  scheduler or worker submissions, active submission snapshots, cancellation
  attempts, and partial submitted-work facts without widening status enums.
- Workspace/sweep contracts express only cross-run identity, trial references,
  trial leases, resource leases, global concurrency counters, run references,
  and recovery scans.
- Capability models can state whether a backend supports per-run coordination,
  cross-run coordination, both, or neither.
- Unsupported capability and unsupported schema failures are machine-readable
  and suitable for loud CLI/API diagnostics.
- Status enums are not widened for transient lease, claim, commit, retry,
  display, or not-selected phases.
- Derived snapshots can explain current lifecycle detail without becoming the
  transition authority.
- Import boundaries keep stores independent of CLI and project code.

Test expectations:

- Package: public imports for new contracts and models are cheap and stable.
- Unit: model validation, serialization, submitted-operation records, reason
  codes, capability records, schema errors, read-model warnings, and
  unsupported-capability errors.
- Contract: fake/in-memory store conformance for transitions, leases, commits,
  submitted operations, revisions, snapshots, read models, schema checks, and
  recovery scan shape.
- Integration: not required beyond import-boundary checks.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase establishes the public and semi-public surface that later phases
  must implement without depending on SQLite-specific details.

Future compatibility:

- The contract should be implementable by future Postgres, service,
  scheduler-aware, or remote-capable backends.
- The read model lets v10 bundles and later diagnostics consume authoritative
  metadata without reading private tables.
- Workspace/sweep contracts should be sufficient for future multi-run
  concurrency without implementing full sweep execution.

Alternatives rejected:

- SQLite-specific runner APIs.
- A contract-only plan without a real backend in later phases.
- Widening `StageStatus` for every coordination phase.
- Treating events or derived catalogs as state authority.
- Letting v10 bundles define the first authoritative metadata read path.

Debt introduced:

- Fake conformance stores may hide real SQLite transaction issues until Phase
  2 implements the backend.

Reviewability:

- Review protocol method names, model fields, authority boundaries, capability
  names, schema policy, read-model fields, error shapes, and import boundaries
  before any implementation depends on them.

Notes:

- Exact class and module names may be refined during the phase, but semantics
  and authority boundaries must remain intact.
- Phase execution planning should enumerate current store and runner concepts
  that map to the new contracts.

Completion summary:

- Merged into `develop` on 2026-05-09T14:41:44Z by PR #101
  (`6ecabf921e8d2e788c5ef748e999bd5b95b5528e`).
- Implemented backend-neutral store contracts under `loom.pipeline.stores`:
  per-run authority protocols and result records, capability diagnostics,
  loud schema policy, authoritative read-model records, and workspace/sweep
  coordination records. The existing local-file `RunStore` and
  `LocalRunStore` remain separate from the v9 authority contracts.
- Added deterministic in-memory conformance stores in test support plus
  package, unit, and contract coverage for exports, import boundaries, model
  validation and round-trip serialization, per-run transition/lease/commit
  behavior, and cross-run workspace coordination.
- Automated PR review found a Phase 1 contract-completeness blocker around
  cross-run lease/recovery identity and exported record round trips. Blocker
  resolution pass 1/3 added `TrialLeaseRecord`,
  `ResourceLeaseRecord.workspace_id`, `CoordinationRecoveryRecord`, and
  `from_dict` round-trip APIs/tests for exported contract records.
- Validation: `make validate-pr` passed; final `make test-summary` passed with
  1422 passed, 11 skipped, 1020 deselected, 0 failed, and 0 errors. GitHub CI
  `checks` passed before merge.
- Follow-up: Phase 2 must implement the SQLite backend behind these contracts
  without exposing private table names or treating test fakes as production
  backends. Phase 1 remote branch cleanup was required because the merge
  completed even though the local `gh pr merge` checkout cleanup step hit the
  existing `develop` worktree.

### Phase 2 - Per-Run SQLite Backend And Transaction Semantics

Status: merged
Branch: `codex/sqlite-run-backend`
PR: https://github.com/samcantrill/loom/pull/102

Goal:

- Implement the first per-run authoritative backend and transaction semantics
  behind the Phase 1 contracts using Python standard-library SQLite.

Scope:

- Add the SQLite backend under the pipeline store boundary with stable exports
  through the contract surface.
- Define private run-local database placement, private schema, and
  schema-version management for run records, stage records, attempts, leases,
  submitted operations, output commits, artifact facts, cleanup candidates,
  events/audit, backend revisions, and snapshot reads for one run.
- Implement transaction boundaries, constraints, guarded transitions, attempt
  number allocation, lease ownership, lease renewal, lease expiry, lease
  release/failure, submitted-operation writes, cancellation attempt records,
  output commit ordering, artifact fact writes, cleanup candidate writes, event
  revision evidence, and revision increments.
- Implement recovery scan helpers for abandoned leases and interrupted
  attempts.
- Implement schema initialization and loud failures for unsupported schemas.
- Add conformance coverage for supported capabilities and loud unsupported
  capabilities.
- Document SQLite limitations for shared filesystems, high write concurrency,
  multi-host controllers, and remote authority.

Out of scope:

- No runner hard swap.
- No local materialization helpers beyond backend facts required for this
  phase.
- No workspace/sweep coordination backend.
- No broad backend CLI.
- No public SQL schema contract.
- No old-run migration.

Acceptance criteria:

- The SQLite backend satisfies the per-run authority contract.
- The backend is run-local and portable with ordinary local run-root movement.
- Atomic transitions and output commits are guarded by backend state, not by
  file existence alone.
- Attempt allocation is monotonic and concurrency-safe within SQLite's local
  guarantees.
- Only one active non-speculative stage lease can own a stage at a time.
- Lease expiry and recovery scans produce deterministic recovery facts.
- Submitted-operation records are persisted, revisioned, listable, and usable
  to derive coarse `SUBMITTED` lifecycle summaries.
- Stage success can be recorded only after commit and artifact facts are
  durable in authoritative state.
- Cleanup candidates are recorded for abandoned or failed staged payloads when
  the backend can identify them.
- Backend revisions advance on state changes and can be used by projections and
  events.
- Unsupported schema and unsupported backend capabilities fail with explicit
  diagnostics.

Test expectations:

- Package: SQLite backend imports without optional dependencies.
- Unit: schema initialization, schema failure mapping, transaction helpers,
  guarded updates, submitted-operation persistence, revision behavior, event
  sequence/revision evidence, and error mapping.
- Contract: full per-run conformance suite against SQLite.
- Integration: concurrent synthetic connections for claims, leases, commits,
  submitted operations, recovery scans, schema checks, cleanup candidate
  records, and revisioned snapshots.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase creates the new active-state substrate but leaves existing serial
  execution paths unchanged until the write-path swap.

Future compatibility:

- Private schema must not leak into runner, CLI, bundle, catalog, or diagnostic
  contracts so stronger backends can replace SQLite later.
- Capability declarations should make SQLite's distributed and shared-FS limits
  visible to future phases.

Alternatives rejected:

- Adapting the old local-file store to mimic leases without transactional
  guarantees.
- Making the SQLite schema public.
- Requiring Postgres or a service process in v9.
- Performing destructive automatic schema migrations in the first backend.

Debt introduced:

- SQLite concurrency and filesystem semantics are acceptable for the local
  first backend but are not a complete distributed coordination solution.

Reviewability:

- Review schema privacy, run-local placement, transaction scope, constraints,
  schema policy, recovery behavior, revision semantics, and conformance
  coverage independently of runner changes.

Notes:

- Table names are private. Database placement must satisfy the run-local
  portability contract.

Completion summary:

- Merged into `develop` on 2026-05-09T16:05:48Z by PR #102
  (`2e20b289582115a12c55c07186174e3e10260c11`).
- Implemented `loom.pipeline.stores.sqlite_authority.SQLitePerRunAuthorityStore`
  as the first run-local stdlib-SQLite backend behind the Phase 1
  `PerRunAuthorityStore` contract. The backend keeps its database/schema
  private inside the run root, declares honest per-run capabilities, loudly
  reports unsupported schemas, and leaves the root `loom.pipeline.stores`
  import free of `sqlite3`.
- Added short transactional revision semantics for run/stage transitions,
  monotonic attempt allocation, controller/stage leases with owner/fencing
  checks, submitted-operation persistence with current-`run_uri`
  reconstruction, audit event sequence evidence with private revision linkage,
  output commit/artifact fact transactions, cleanup candidates representable
  from backend facts, snapshots, and recovery scans.
- Expanded-path implementation refinement fixed incomplete-schema handling,
  schema initialization transaction scope, expired lease release/failure,
  active-lease bypass by unleased attempts, terminal-state output commits, and
  stage-lease release on successful output commit.
- Automated PR review found one blocking lifecycle regression: a new attempt
  could be allocated after a stage output commit and regress the stage from
  `SUCCEEDED` to `RUNNING`. Blocker resolution pass 1/3 added the transactional
  guard against existing commits or terminal stage state plus regression
  coverage.
- Validation: `make validate-pr` passed; final `make test-summary` passed with
  1439 passed, 11 skipped, 1037 deselected, 0 failed, and 0 errors. GitHub CI
  `checks` passed before merge.
- Follow-up: Phase 3 should consume the SQLite backend through snapshots and
  Phase 1 read-model records only; do not expose table names or treat the
  SQLite module as a status/catalog/export query surface.

### Phase 3 - Materialization Boundary And Authoritative Read Models

Status: merged
Branch: `codex/materialization-read-models`
PR: https://github.com/samcantrill/loom/pull/103

Goal:

- Define and implement the materialization boundary and backend-neutral
  authoritative read models before runner and query paths are swapped.

Scope:

- Implement authoritative run snapshot/read APIs over the Phase 2 backend.
- Include run status, stage statuses, attempts, leases, submitted operations,
  commits, artifact facts, materialized payload/log/config/provenance refs,
  cleanup candidates, event revision evidence, schema version, warnings, and
  backend revision in the read model.
- Implement local materialization helpers for logs, artifact payloads,
  config/provenance copies, worker request/result handoff files, and any
  required path helpers without making those files active truth.
- Define how read-model warnings represent unsupported schema, missing
  materialized payloads, stale projections, partial commits, and actively
  changing runs.
- Add bundle-ready metadata read behavior for completed runs without adding
  user-facing export/snapshot CLI.
- Keep legacy local state files outside the read-model truth path.

Out of scope:

- No serial runner hard swap.
- No catalog/status read-path swap.
- No backend CLI.
- No user-facing export, import, or snapshot command.
- No workspace/sweep coordination backend.

Acceptance criteria:

- Status, catalog, diagnostics, and later bundles can consume one authoritative
  read model without reading SQLite internals.
- The read model exposes submitted-operation detail separately from coarse
  `SUBMITTED` run or stage statuses.
- The read model distinguishes backend facts from materialized file references.
- Missing or corrupt materialized payload/log/config/provenance files are
  warnings or errors according to the read request, but they do not create
  alternate state truth.
- Legacy human-readable status or artifact index files are not read as current
  truth.
- Bundle-ready metadata reads do not import project code or load artifact
  payloads.

Test expectations:

- Package: read-model imports remain independent of CLI and project code.
- Unit: read-model serialization, warning taxonomy, materialization
  classification, submitted-operation projection, schema warning mapping, and
  no-fallback helpers.
- Contract: authoritative snapshot/read-model contract over fake and SQLite
  backends.
- Integration: SQLite-backed synthetic runs with missing payloads, partial
  materialization, submitted operations, cleanup candidates, and revisioned
  reads.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase creates the shared truth-consumption surface that prevents later
  status, catalog, diagnostics, and bundle work from coupling to private
  backend details.

Future compatibility:

- V10 bundles can use the read model as input for manifest creation.
- Remote stores can reuse the materialization distinction for metadata-only
  refs, staging, and cache records.
- Reliability and cleanup can consume cleanup candidates and commit facts.

Alternatives rejected:

- Letting each consumer define its own SQLite query shape.
- Reusing legacy `status.json` or `artifacts.json` as the read model.
- Adding a user-facing export/snapshot command in v9.

Debt introduced:

- The read model becomes an internal compatibility surface that must remain
  coherent as later backends are added.

Reviewability:

- Review the distinction between authoritative facts and materialized files,
  the read-model fields, warning semantics, and absence of legacy fallback.

Notes:

- The read model may be public or private according to package-boundary review,
  but it must be stable enough for later v9 phases and v10 planning.

Completion summary:

- Merged into `develop` on 2026-05-09T17:44:51Z by PR #103
  (`9b37986a9d43139036ef41b930e019a5150a77f2`).
- Added `materialization_read_models` as the backend-neutral authoritative
  read/materialization layer over `PerRunAuthorityStore` snapshots and schema
  checks, with request options for metadata-only reads, strict warning
  handling, materialization verification, stale projection warnings, active-run
  revision warnings, and completed-run bundle metadata.
- Added local materialized-ref classification for artifact payloads, stage
  logs, config snapshots, provenance documents, and worker handoff files while
  preserving backend facts as authority. Missing and corrupt materialized refs
  are reported as machine-readable warnings or strict read errors without
  changing lifecycle truth.
- Added package, unit, contract, and SQLite integration coverage for import
  boundaries, materialization diagnostics, checksum corruption warnings,
  unsupported-schema warning-only reads, strict failures, partial commits,
  cleanup-candidate carry-through, and bundle metadata.
- Automated PR review found one blocker around warning-only unsupported-schema
  reads and one coverage gap for partial commits and cleanup candidates.
  Blocker-resolution pass 1/3 fixed the schema-warning fallback and refreshed
  PR evidence; 2/3 blocker-resolution passes remain unused.
- Validation: `make validate-pr` passed; final `make test-summary` passed with
  1460 passed, 0 failed, 0 errors, 11 skipped, and 1055 deselected. GitHub CI
  `checks` passed before merge.
- Follow-up: Phase 4 should use this read/materialization boundary for
  serial write-path integration rather than coupling runner code to private
  SQLite details or legacy local status/artifact files.

### Phase 4 - Serial Execution Write-Path Integration

Status: merged
Branch: `codex/serial-write-integration`
PR: https://github.com/samcantrill/loom/pull/104

Goal:

- Integrate serial run creation and mutation with SQLite-backed authority
  behind internal/test-selectable construction while preserving the public
  serial default until Phase 5.

Scope:

- Add internal/test-selectable SQLite-backed runner construction for new runs
  without making it the public default until Phase 5.
- Update serial planning and runner write paths to create and mutate active
  state through the authoritative backend.
- Replace run-level lock-file write authority with the backend run/controller
  lease or equivalent serialized controller ownership for new runs.
- Write submitted-operation records, coarse `SUBMITTED` run/stage summaries,
  cancellation attempts, and partial submitted-work facts through backend
  contracts where current submitted paths need them.
- Write stage attempts, inputs, fingerprints, worker handoff references,
  failures, output commits, artifact facts, provenance refs, cleanup
  candidates, and run/stage status through backend contracts.
- Preserve local files only for logs, artifact payloads, config/provenance
  copies, worker materialization, and other non-authoritative payloads.
- Ensure subprocess and prepared-worker handoff paths can materialize files but
  commit final state through backend authority.
- Preserve local/subprocess controller-finalized behavior while adding the
  backend contract path for submitted or scheduler-backed workers to
  self-finalize attempt-scoped facts with a valid attempt/lease fencing token.
- Enforce staged-payload commit semantics: declared output validation,
  existence/checksum validation where supported, backend output commit,
  artifact facts, derived artifact-index update, terminal stage status,
  revision, and event evidence commit together where backend capabilities allow.
- Preserve user-visible serial execution semantics as closely as possible.
- Update tests and fixtures that assumed local files were live write truth.
- Document the absence of old-run migration and legacy fallback.

Out of scope:

- No public default backend flip; Phase 5 owns the public hard swap.
- No bounded parallel stage scheduling.
- No catalog/status read-path swap except where needed to validate write-path
  behavior.
- No workspace/sweep coordination implementation.
- No backend repair/export/snapshot CLI.
- No old-run migration or compatibility mode.

Acceptance criteria:

- Internal/test SQLite-backed serial runs initialize and mutate active state
  through backend authority.
- Existing public serial runner behavior remains unchanged until Phase 5 makes
  backend reads authoritative.
- Serial execution success, failure, cancellation, submitted operation, commit
  failure, and worker handoff writes use backend truth on the SQLite-backed
  path.
- Stage success is impossible without durable backend commit and artifact
  facts.
- Missing or invalid worker fencing tokens fail loudly for submitted-worker
  self-finalization. Valid tokens allow only attempt-scoped finalization facts,
  not run finalization or global coordination mutation.
- Failed or abandoned staged payloads are not committed outputs.
- Backend commit failure after payload staging records failure/cleanup
  candidates rather than active outputs.
- Local payload/log/config/provenance files remain available where existing
  workflows need them.
- Old v0-v8 migration is absent by design and documented.
- Existing serial write-path tests pass after being updated to the new
  authority.

Test expectations:

- Package: no import cycles between execution, stores, runs, diagnostics, and
  CLI.
- Unit: runner/backend adapter behavior, controller ownership, commit ordering,
  submitted-operation writes, materialization writes, worker handoff writes,
  worker fencing-token checks, and no-fallback write checks.
- Contract: backend conformance remains passing after runner integration.
- Integration: serial run success/failure/commit-failure/subprocess handoff,
  submitted operation, invalid fencing token, and valid self-finalizing worker
  flows against SQLite truth.
- E2E: local serial pipeline e2e tests updated for SQLite-backed write truth.
- Opt-in: none.

Design impact:

- This is the write-path integration point that proves execution can mutate
  backend authority without exposing a public hard swap before read consumers
  are ready.

Future compatibility:

- Runner code must depend on backend contracts so future backends do not
  require another execution write-path refactor.
- Local materialization should remain narrow so V10 bundles and remote stores
  can reason about payloads separately from active state.
- Submitted-worker self-finalization must stay fenced so future SLURM,
  container, and scheduler workers can commit attempt results without becoming
  run controllers.

Alternatives rejected:

- Publicly auto-selecting the backend before planning, resume, status, and
  catalog reads are backend-backed.
- Dual-writing local files and SQLite as coequal truth.
- Silent fallback to legacy local state.
- Migration tooling in v9.
- Retaining file locks as the active controller authority for new runs.

Debt introduced:

- The backend path is internal/test-selectable for one phase, so public
  behavior does not change until Phase 5 completes the read-path swap and
  enables the public default.

Reviewability:

- Review state write call sites, controller ownership, commit ordering,
  submitted-operation writes, worker fencing, materialization boundaries,
  serial behavior parity, and test fixture updates.

Notes:

- This phase intentionally excludes the public hard swap and broad read/query
  conversion so the write-path diff stays independently reviewable.

Completion summary:

- Merged into `develop` on 2026-05-09T19:31:05Z by PR #104
  (`b1b6944a1b66af56488d6b4de256ac4ce75c2cb0`).
- Added the internal/test-selectable `AuthorityBackedSerialRunStore` adapter
  for SQLite-backed serial execution, pairing local materialization paths with
  `PerRunAuthorityStore` active write authority while preserving the public
  `LocalRunStore` default.
- Routed SQLite-backed serial run creation/opening, controller ownership,
  run/stage transitions, stage attempts and leases, submitted-operation
  records, output commits, artifact facts, audit events, and authoritative
  artifact reads through backend contracts.
- Preserved config/provenance/log/stage input/fingerprint/worker handoff and
  output documents as local materialized evidence, not active state truth.
  Conflicting local status/output/artifact-index files do not override
  backend-backed reads on the internal SQLite path.
- Added internal stage-job authority fencing checks for SQLite-backed
  continuation. Stage-job requests must provide backend attempt id, lease id,
  owner id, and fencing token matching worker-request metadata and the active
  backend lease; the SQLite-backed path commits only the target attempt and
  does not finalize run status.
- Automated PR review found one blocking continuation issue: the initial
  implementation allowed SQLite-backed stage-job continuation without explicit
  backend fencing and could finalize run status. Blocker-resolution pass 1/3
  fixed the fenced continuation path and refreshed PR evidence; 2/3
  blocker-resolution passes remain unused.
- Accepted debt: Phase 1-3 authority contracts expose cleanup-candidate reads
  but no backend-neutral cleanup-candidate writer, and do not expose an
  attempt-failure writer separate from stage/lease failure. Phase 4 records
  failed stage/run facts and failed leases where possible instead of adding
  private SQLite mutation surface or broadening the public protocol.
- Validation: `make validate-pr` passed; final `make test-summary` passed with
  1475 passed, 0 failed, 0 errors, 12 skipped, and 1065 deselected. GitHub CI
  `checks` passed before merge.
- Follow-up: Phase 5 should enable the public SQLite-first default and move
  live planning/resume/status/catalog reads to backend snapshots/read models,
  retiring Phase 4's compatibility shims for new runs where backend truth is
  available.

### Phase 5 - Public Serial Hard Swap And Read-Path Swap

Status: merged
Branch: `codex/public-backend-swap`
PR: #105 - https://github.com/samcantrill/loom/pull/105

Goal:

- Enable the public SQLite-first hard swap for new serial runs by moving live
  truth reads for planning, resume, status, diagnostics inputs, and catalog
  refresh to backend snapshots/revisions.

Scope:

- Enable SQLite-backed authority as the public default for new serial runs with
  no user setup.
- Update planning/resume reads to consume backend facts and read models instead
  of legacy local state files for new runs.
- Update run status and stage status inspection to use authoritative backend
  snapshots and lifecycle summaries, including submitted-operation detail
  behind coarse `SUBMITTED` statuses.
- Update `RunCatalog` extraction/refresh to validate against backend revisions
  or read-model evidence.
- Remove or retire legacy live-state read/write paths for new runs where Phase
  4 kept them reachable only for public-default compatibility.
- Prove stale, missing, corrupt, or contradictory legacy human-readable state
  files cannot become fallback truth for new runs.
- Preserve derived catalog warning behavior while making backend truth the
  conflict winner.
- Update docs and tests for no-migration/no-fallback behavior.

Out of scope:

- No backend CLI commands beyond test helpers.
- No bounded parallel execution.
- No workspace/sweep coordination implementation.
- No user-facing export/snapshot command.

Acceptance criteria:

- New public serial runs initialize with the SQLite authoritative backend by
  default.
- Serial execution, failure, cancellation, resume, status, and artifact summary
  reads work through backend truth.
- Submitted-operation detail is available through backend-backed read models
  and status summaries without treating status files as truth.
- Catalog/status reads validate current state against authoritative revisions
  or snapshots.
- Deleting or corrupting legacy human-readable state files cannot cause new run
  live-state readers to fall back to them.
- Derived projections cannot override authoritative backend facts.
- Old v0-v8 migration remains absent by design and documented.
- Existing serial e2e behavior passes after being updated to the new authority.

Test expectations:

- Package: no import cycles between planning, execution, stores, runs,
  diagnostics, and CLI.
- Unit: status derivation, resume reads, catalog extraction, revision
  validation, submitted-operation projection, public default selection, and
  no-fallback checks.
- Contract: read-model and backend conformance remain passing after read-path
  integration.
- Integration: serial run resume/status/catalog/artifact-summary flows against
  SQLite truth, submitted-operation read flows, plus corrupt/missing
  legacy-file no-fallback cases.
- E2E: local serial pipeline e2e tests updated for SQLite-backed read truth.
- Opt-in: none.

Design impact:

- This phase completes the public hard swap for serial live-state write and
  read surfaces.

Future compatibility:

- V10 bundles, V11 sweep status, and future dashboards can build on the same
  backend read-model path instead of adding new SQLite queries.

Alternatives rejected:

- Reading old local state files for current truth.
- Letting `RunCatalog` query private SQLite tables directly.
- Combining the full write-path and read-path swap into one PR.
- Keeping the backend path internal-only after read consumers are backend-backed.

Debt introduced:

- Old v0-v8 run directories are intentionally unsupported by new live-state
  readers unless future import/export work defines a safe path.

Reviewability:

- Review read call sites, conflict rules, no-fallback tests, derived projection
  freshness, and catalog/status behavior changes.

Notes:

- This phase may add warnings for unsupported old-run schemas, but it must not
  implement migration.

Completion summary:

- Merged on 2026-05-09 into `develop` by PR #105 at merge commit
  `62b390f756a3f3bb5428e58eb36691aaa7b86334`.
- Implementation: public local/subprocess serial `loom run` defaults now
  create an authority-backed serial run store with run-local SQLite authority;
  SLURM preparation remains on explicit local materialization stores. Status,
  artifact, submitted-operation, and catalog current-summary reads use backend
  snapshots, authority revisions, or backend-neutral read models for
  authoritative runs. Catalog scans report missing, malformed, or unsupported
  authority stores as warnings and no longer depend on the execution adapter
  for summary extraction.
- Automated review: initial PR review found missing-authority fallback
  blockers in diagnostics/catalog reads and a catalog import-boundary issue.
  Blocker-resolution pass 1/3 fixed those issues; manager follow-up review
  confirmed no remaining blocking findings.
- Checks: `make validate-pr` passed after blocker resolution: Ruff, Pyright,
  default harness (1038 passed, 18 skipped, 14 deselected), config-extra
  harness (420 passed, 1066 deselected), and `uv build`. `make test-summary`
  passed with 1483 passed, 0 failed, 0 errors, 12 skipped, and 1077
  deselected. GitHub CI `checks` passed before merge.
- Follow-up: Phase 6 should add the read-only backend diagnostics CLI and
  API-level diagnostic models on top of the authoritative read paths introduced
  here, without adding mutation, repair, export, SQL, or snapshot behavior.

### Phase 6 - Read-Only Backend Diagnostics CLI

Status: merged
Branch: `codex/backend-diagnostics`
PR: https://github.com/samcantrill/loom/pull/106

Goal:

- Make the new authority inspectable and keep derived projections honest
  without creating mutation, repair, export, SQL, or snapshot workflows.

Scope:

- Add minimal read-only `loom backend ...` CLI commands for backend
  capabilities, authoritative run facts, attempts, leases, submitted
  operations, commits, revisions, schema information, materialization
  diagnostics, and consistency diagnostics.
- Add Python API helpers used by the CLI so presentation code does not parse
  backend internals.
- Add stale projection and actively changing backend warnings where relevant.
- Add loud preflight diagnostics for shared-filesystem and remote-store
  assumptions that the selected backend cannot prove.
- Ensure backend inspection imports no project stage code and loads no artifact
  payloads.

Out of scope:

- No backend mutation, repair, cleanup, export, import, SQL, or snapshot
  command.
- No remote authoritative backend.
- No dashboard UI.

Acceptance criteria:

- `loom backend ...` commands are read-only and report machine-readable
  diagnostics suitable for text and JSON presentation.
- CLI commands can show enough attempt, lease, commit, schema, materialization,
  submitted-operation, and revision detail to debug active runs.
- Shared-filesystem and remote capability gaps are explicit warnings or
  failures, not silent assumptions.
- Tests prove CLI inspection does not mutate backend state.
- CLI modules do not read private SQLite tables directly.

Test expectations:

- Package: CLI imports remain thin and do not make backend internals public.
- Unit: diagnostic model serialization, capability warning mapping, schema
  diagnostics, submitted-operation diagnostics, materialization warnings,
  projection freshness handling, and read-only guard behavior.
- Contract: projection reads validate against backend revisions or snapshots.
- Integration: CLI/API diagnostics over synthetic SQLite-backed runs,
  submitted-operation records, stale projection warnings, unsupported schema
  diagnostics, and no-mutation checks.
- E2E: backend CLI smoke tests for text and JSON output.
- Opt-in: none.

Design impact:

- This phase establishes how users and future tools inspect authoritative state
  while preserving the projection-only role of catalogs and summaries.

Future compatibility:

- V10 exports can later add derived snapshot behavior separately.
- Future service/remote backends can implement the same diagnostic models
  without exposing local SQLite tables.

Alternatives rejected:

- Repair commands in the backend CLI.
- Export/snapshot commands in v9.
- Reading legacy human-readable files for current truth.
- Querying private SQLite tables directly from CLI modules.

Debt introduced:

- Some operational repairs remain manual or deferred until a later reliability
  or export plan defines safe mutation semantics.

Reviewability:

- Review CLI command scope, read-only guarantees, projection validation,
  schema/materialization diagnostics, machine-readable output, and import
  boundaries.

Notes:

- The CLI spelling should stay minimal. Add only commands needed for inspection
  and debugging, not administration.

Completion summary:

- Merged into `develop` on 2026-05-09 at merge commit
  `f6f173af904ee0bba07c965498ab4adf141e8a04`.
- Implemented read-only `loom backend inspect` and `loom backend
  capabilities` plus backend-neutral diagnostics helpers under
  `loom.diagnostics`, with text and JSON output for schema, revision,
  lifecycle, submitted-operation, cleanup/recovery, materialization, and
  capability diagnostics.
- Preserved import boundaries by keeping CLI presentation out of private
  SQLite tables and exporting diagnostics lazily from `loom.diagnostics`.
- Automated review: initial PR review found that
  `loom backend inspect --verify-materialization` could delegate to checksum
  verification and read artifact payload bytes. Blocker-resolution pass 1/3
  fixed diagnostics to use existence-only verification while preserving
  checksum verification as the default for existing read-model callers; manager
  follow-up review confirmed the blocker was resolved.
- Checks: `make validate-pr` passed after blocker resolution: Ruff, Pyright,
  default harness (1056 passed, 18 skipped, 14 deselected), config-extra
  harness (420 passed, 1084 deselected), and `uv build`. `make test-summary`
  passed with 1501 passed, 0 failed, 0 errors, 12 skipped, and 1095
  deselected. GitHub CI `checks` passed before merge.
- Follow-up: Phase 7 should reuse capability diagnostics for explicit
  parallel-execution requirements and keep the serial default unchanged.

### Phase 7 - Bounded Parallel Stage Execution

Status: merged
Branch: `codex/parallel-stage-execution`
PR: https://github.com/samcantrill/loom/pull/107

Goal:

- Validate the concurrency contract with opt-in user-facing bounded local
  parallel stage execution.

Scope:

- Add Python API and CLI controls for maximum parallel stage execution, with
  serial behavior as the default.
- Implement ready-stage selection for independent static DAG branches based on
  committed upstream outputs and persisted static conditional outcomes.
- Implement controller-owned local scheduling with backend-enforced atomic
  ready-stage claim, attempt allocation, lease acquisition, lease renewal,
  lease expiry handling, and abandoned-lease recovery.
- Use backend-owned lease time for acquire, renew, expire, and recovery
  decisions, with SQLite limited to local or same-host coordination.
- Implement output commit ordering so stage success depends on durable commit
  and artifact facts.
- Add default failure behavior that stops leasing new stages after terminal
  failure while allowing already-running attempts to finish and record durable
  outcomes.
- Add a failure policy flag that continues launching independent non-dependent
  ready branches after an unrelated failure.
- Fail loudly when explicit parallel execution is requested and the selected
  backend lacks required capabilities.
- Preserve serial default behavior and serial test expectations.

Out of scope:

- No distributed multi-controller execution.
- No scheduler-backed parallel execution.
- No speculative execution.
- No dynamic DAG mutation, dynamic fan-out, or runtime stage definition
  creation.
- No full sweep or multi-run scheduler behavior.

Acceptance criteria:

- `max_parallel_stages=1` or the default path remains serial.
- Explicit bounded parallel execution runs independent stages concurrently
  against the SQLite backend.
- Concurrent workers cannot double-claim the same stage.
- Lease expiry and recovery behavior uses backend-owned time, not
  caller-owned filesystem timestamps.
- Stage success is based on committed outputs and artifact facts.
- Failed dependencies block dependents after failure is durable.
- The default policy stops new leases after terminal failure and allows active
  attempts to finish.
- The alternate policy can continue independent non-dependent branches.
- Explicit parallel requests fail loudly if claim, lease, commit, revision, or
  recovery capabilities are missing.
- Runtime-conditioned static DAG outcomes are persisted as lifecycle facts
  without mutating the planned graph shape.
- KeyboardInterrupt or controller interruption records durable interruption or
  lease-abandonment facts without marking ambiguous work as succeeded.

Test expectations:

- Package: API/CLI option imports do not introduce optional dependencies.
- Unit: ready-stage selection, failure policy decisions, capability preflight,
  backend-clock lease decisions, controller interruption handling, and
  lifecycle snapshot derivation.
- Contract: backend capability requirements for parallel execution.
- Integration: synthetic DAGs with independent branches, dependency failures,
  skipped/not-selected/blocked outcomes, lease expiry, abandoned attempts,
  controller interruption, and recovery.
- E2E: bounded local parallel CLI/API runs with deterministic synthetic stages
  and serial default checks.
- Opt-in: optional stress or timing-sensitive concurrency tests may be marked
  opt-in if they are not deterministic enough for the default suite.

Design impact:

- This phase turns the backend contract into visible execution behavior while
  keeping distributed and scheduler-backed policy deferred.

Future compatibility:

- The same claim, lease, attempt, commit, and recovery semantics should support
  future scheduler-backed workers and service controllers.
- Static conditional outcome facts leave room for later dynamic DAG design
  without overloading v9 execution.

Alternatives rejected:

- Silent serial fallback after explicit parallel request.
- Local thread/process scheduling without backend claims and leases.
- Treating process exit as stage success before commit.
- Adding scheduler-specific queues or fairness policy in v9.
- Supporting multiple active controllers for the same run in v9.

Debt introduced:

- Bounded local parallelism may not expose all distributed failure modes that a
  later service or scheduler backend must handle.

Reviewability:

- Review capability preflight, claim/lease invariants, controller ownership,
  commit ordering, failure policy behavior, serial default preservation, and
  deterministic test design.

Notes:

- Phase execution planning should choose the smallest API/CLI flag names that
  are compatible with future scheduler-backed controls.

Completion summary:

- Merged into `develop` on 2026-05-09 at merge commit
  `43a05aa803e0c4f59c6af265827279c3da865831`.
- Implemented validated Python and CLI parallel controls, a controller-owned
  bounded local scheduler, authoritative capability preflight, stage lease
  renewal, deterministic failure policies, and loud unsupported
  backend/executor/capture errors while preserving the serial default.
- Automated review: manager review found a blocking scheduler edge case where
  plan-level `BLOCKED` actions could be short-circuited as generic upstream
  blocks and fail-fast scheduling could continue within the same submission
  pass. Blocker-resolution pass 1/3 fixed the issue and added integration
  coverage for skipped-upstream plan blockers under both default and
  `continue_independent` policies; manager follow-up review confirmed no
  remaining blocking findings.
- Checks: `make validate-pr` passed after blocker resolution: Ruff, Pyright,
  default harness (1074 passed, 18 skipped, 14 deselected), config-extra
  harness (420 passed, 1103 deselected), and `uv build`. `make test-summary`
  passed with 1520 passed, 0 failed, 0 errors, 12 skipped, and 1114
  deselected. GitHub CI `checks` passed before merge.
- Follow-up: Phase 8 should keep cross-run coordination separate from per-run
  stage execution truth and preserve the serial/default paths introduced in
  earlier v9 phases.

### Phase 8 - Workspace/Sweep Coordination Foundation

Status: pr_open
Branch: `codex/workspace-coordination`
PR: https://github.com/samcantrill/loom/pull/108

Goal:

- Establish the compact cross-run coordination foundation required for future
  multi-run concurrency and large sweeps without implementing full sweep
  execution.

Scope:

- Implement the workspace/sweep coordination contract defined in Phase 1 using
  local SQLite or the selected local backend approach.
- Support workspace or sweep identity records.
- Support trial manifest references or trial reference records.
- Support trial lease records with owners, timestamps, renewals, expiry,
  release/failure, backend-owned time semantics, and recovery scans.
- Support named resource leases and global concurrency counters.
- Support ordinary `run_uri` references from trial/workspace records to
  per-run authoritative backends.
- Add capability declarations that distinguish per-run coordination,
  cross-run coordination, and combined support.
- Add documentation showing how v11 deterministic sweeps, future multi-run
  concurrency, scheduler-backed execution, and service backends build on this
  boundary.
- Document that v11 sequential sweep manifests remain compatible and are not
  forced to become database-first by this foundation.

Out of scope:

- No full sweep runner.
- No adaptive sweep algorithm.
- No distributed controller.
- No fairness policy.
- No scheduler queue semantics.
- No remote service backend.
- No per-stage run-state duplication inside workspace/sweep tables.
- No replacement for simple v11 deterministic sweep manifests.

Acceptance criteria:

- Workspace/sweep coordination stores cross-run facts only.
- Per-run stage lifecycle remains owned by each run's authoritative backend.
- Trial and resource leases are claimable, renewable, releasable, expirable,
  and recoverable through the coordination contract.
- Local SQLite coordination declares local or same-host lease safety only and
  produces loud capability diagnostics for multi-host assumptions.
- Global concurrency counters are guarded by backend state and recover from
  abandoned leases where possible.
- Coordination records reference ordinary `run_uri` values rather than copying
  run state.
- Catalog and sweep/dashboard summaries remain derived projections.
- Documentation clearly states deferred v11 and later behavior.
- Sequential deterministic sweeps can still be built as ordinary run
  collections with manifests, while future concurrent sweeps can opt into the
  coordination foundation.

Test expectations:

- Package: coordination exports remain import-light and domain-neutral.
- Unit: trial/resource lease models, counter updates, capability declarations,
  and recovery decisions.
- Contract: fake/in-memory and SQLite/local conformance for coordination
  primitives.
- Integration: concurrent synthetic trial claims, resource lease contention,
  abandoned lease recovery, and run reference reads.
- E2E: not required unless a minimal CLI/API smoke path is introduced.
- Opt-in: none.

Design impact:

- This phase completes the hybrid authority boundary by adding the cross-run
  coordination side without turning v9 into sweep execution.

Future compatibility:

- V11 sweeps can build deterministic trial planning, claiming, retry, and
  resource limits on this contract when needed while keeping simple sequential
  behavior document-driven.
- Future service or scheduler backends can replace the local coordination
  implementation while preserving per-run semantics.

Alternatives rejected:

- Putting sweep leases inside per-run state.
- Making `RunCatalog` the sweep/workspace authority.
- Deferring all coordination contracts until v11.
- Implementing full scheduler or fairness policy in v9.
- Making the coordination store mandatory for simple sequential sweeps.

Debt introduced:

- The coordination contract may need refinement once concrete v11 sweep
  workflows exercise it.

Reviewability:

- Review that cross-run records do not duplicate per-stage state, capability
  declarations are clear, recovery semantics are deterministic, docs keep
  deferred sweep behavior explicit, and simple sequential sweeps remain
  supported.

Notes:

- If Phase 8 exposes any CLI surface, keep it diagnostic only unless a later
  implementation-plan refinement explicitly expands the scope.

Completion summary:

- PR opened against `develop`: https://github.com/samcantrill/loom/pull/108.
- Implementation adds cross-run coordination protocol extensions, a private
  local SQLite workspace coordination backend, in-memory conformance support,
  and package/unit/contract/integration coverage for workspace/sweep identity,
  trial references, fenced trial/resource leases, guarded counters, resource
  limits, local/same-host capability diagnostics, recovery scans, and ordinary
  `run_uri` references without per-run lifecycle duplication.
- Documentation updates clarify that v11 sequential deterministic sweeps can
  remain manifest-shaped and opt into coordination only for concurrent trial
  admission or resource limits.
- Expanded-path refinement found and fixed a fake/SQLite conformance gap for
  duplicate workspace/sweep identity failures; no blocker-resolution passes
  were used.
- Checks: `make validate-pr` passed after refinement: Ruff, Pyright, default
  harness (1088 passed, 18 skipped, 14 deselected), config-extra harness
  (420 passed, 1117 deselected), and `uv build`. `make test-summary` passed
  with 1534 passed, 0 failed, 0 errors, 12 skipped, and 1128 deselected.
- Follow-up: automated PR review and GitHub CI must pass before merge.
