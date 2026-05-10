# Implementation Plan v9-post: Authority-Backed Runtime Unification And Service Backend

## Metadata

- Status: active implementation plan
- Related planning notes:
  `docs/implementation-plans/roadmap-v9-post-planning-notes.md`
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v9.md`
  - `docs/implementation-plans/implementation-roadmap.md`
- Related source docs:
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/execution.md`
  - `docs/features/reliability.md`
  - `docs/features/resume.md`
  - `docs/features/remote-stores.md`
  - `docs/features/sweeps.md`
  - `docs/features/run-catalog.md`
  - `docs/features/slurm.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/structure.md`
- Draft pass: complete on 2026-05-10 from confirmed v9-post planning notes
  and refreshed `LocalRunStore` inventory.
- Refine pass: local quality-gate refinement complete on 2026-05-10 for public
  naming transition, service topology, backend-dependency risks, and HPC
  deployment/fallback capability modeling; whole-plan implementation detail
  pass complete for shared configuration, capability gates, service records,
  worker handoff, deferred envelopes, test fixtures, candidate module
  ownership, draft CLI/environment surfaces, service constraints, and concrete
  admission diagnostics.
- Plan quality gate: passed on 2026-05-10 by formal `loom_plan_reviewer`
  review; no blocking or non-blocking findings remain.
- Blockers:
  - None for phase start.
  - Phase 7 must prove that the selected service backend provides the declared
    consistency guarantees without hiding a direct shared-file authority path
    behind service terminology.
  - Phase 8 must keep deferred finalization clearly weaker than live worker
    authority.

## Goal

Implement the post-v9 authority unification step.

V9 introduced per-run authority contracts, a run-local SQLite authority
backend, materialization read models, authority-backed serial execution,
bounded local parallel execution, backend diagnostics, and workspace
coordination contracts. V9-post removes the remaining runtime and behavior-read
escape hatches so every supported run and stage lifecycle mutation enters
through authority-backed stores.

This plan also introduces a concrete service/database authority backend for
concurrent terminals, concurrent stages, multi-host workers, and HPC submitted
jobs. The service backend must provide one source of truth for active
lifecycle state and must declare the consistency guarantees it actually
provides.

## Context

The current codebase contains three overlapping store roles:

- Active lifecycle authority: v9 `PerRunAuthorityStore`,
  `WorkspaceCoordinationStore`, and `AuthorityBackedSerialRunStore` machinery.
- Local runtime store: `LocalRunStore` and `LocalRunStorePaths`, which still
  expose lifecycle methods and local path/materialization helpers through the
  same type family.
- Derived and diagnostic readers: run catalog, status, diagnostics, preflight,
  plan, and materialization read-model code that may still reach into local
  run files for behavior.

That overlap is not a naming problem alone. Direct Python runner usage, SLURM
planning/submission, stage worker commands, stage-job continuation,
prepared-run continuation, cancellation/status helpers, examples, and many
tests still construct or assume `LocalRunStore` as a runtime-capable store.
Those paths undermine the v9 authority model because they can bypass guarded
transitions, leases, fencing tokens, submitted-operation records, output
commits, revisions, snapshots, and recovery scans.

The target naming model is:

- `RunStore`: public authority surface that manages runs, run admission,
  run-level leases, run lifecycle, submitted operations, snapshots, and access
  to scoped stage handles.
- `StageStore`: scoped authority surface within a run that manages stage
  lifecycle, attempts, stage leases, fencing, submitted state, output commits,
  terminal state, recovery, and cleanup candidates.
- `WorkspaceCoordinationStore` or a later workspace-specific name: separate
  non-run coordination for sweep/resource/global counters where those facts are
  not naturally run lifecycle.
- `RunArtifactStore`: programmatic per-run artifact/materialization interface.
- `StageArtifactStore`: programmatic per-stage artifact/materialization
  interface.

`RunArtifactStore` and `StageArtifactStore` must never expose lifecycle
methods or behavior summaries. Local files remain useful for payloads, logs,
config snapshots, provenance, generated manifests, worker request/result
materialization, and later bundle/export inputs. They are not active truth.

## Desired Outcome

When all phases are complete:

- No supported mutating entrypoint creates, resumes, submits, finalizes,
  cancels, or updates a run through `LocalRunStore` alone.
- New run and stage mutations always go through authority-backed `RunStore` and
  scoped `StageStore` semantics.
- Direct mutating `PipelineRunner(LocalRunStore(...))` usage hard-fails.
- Public Python examples and docs use an authority-backed factory, not
  `LocalRunStore`.
- SLURM dry-run/live submission, stage workers, stage-job continuation,
  prepared-run continuation, cancellation, scheduler-status observation, and
  worker finalization use authority-backed submitted-operation and lifecycle
  updates.
- Status, catalog, plan, diagnostics, and preflight use authority read models
  for lifecycle behavior.
- Local run and stage directory access is artifact/materialization-only.
- Old local-only lifecycle read compatibility is not preserved.
- A generic authority interface and conformance harness covers run lifecycle,
  stage lifecycle, leases, fencing, submitted operations, output commits,
  snapshots, stale transitions, and recovery.
- A concrete service/database backend implements those contracts and declares
  its actual consistency guarantees for concurrent terminals, multi-host
  workers, and HPC submitted jobs.
- HPC deployment modes are explicit capability profiles, including managed
  service, allocation-scoped service, direct transactional database when
  proven, and deferred finalization fallback when compute nodes cannot reach
  authority.
- Runtime and read systems support the concrete service backend through the
  public factory/configuration path.
- Concurrency-sensitive modes are strictly capability-gated. Loom rejects
  concurrent stages, concurrent run admission, multi-host workers, sweeps,
  shared resource counters, or live submitted-job commits when the selected
  backend/profile cannot prove the required guarantees.
- Run-local SQLite authority is removed from supported runtime behavior after
  service-backed parity. Derived catalog SQLite sidecars may remain as
  rebuildable projections only.

## Non-Goals

- No migration of historical v0-v8 local-only run directories into authority.
- No lifecycle interpretation of old local-only files as supported behavior.
- No deletion of local artifact, log, config, provenance, generated manifest,
  worker handoff, or payload materialization files.
- No scheduler, worker daemon, queue, adaptive sweep runner, or workflow
  engine.
- No remote artifact payload movement or remote object-store authority.
- No hosted production operations, authentication, authorization, tenancy, or
  high-availability deployment.
- No assumption that long-running login-node processes are allowed or reliable
  on every HPC cluster.
- No claim that every HPC topology supports live worker commits. Clusters with
  blocked compute-to-authority networking may support only deferred
  finalization.
- No support claim for SQLite files on arbitrary shared filesystems as a
  multi-host authority mechanism.
- No public SQL schema contract for users.
- No changes to core run or stage status enums solely to encode UI phases.

## Constraints

- Keep `loom` domain-neutral.
- Preserve source-tree and import boundaries from `docs/structure.md`.
- Keep store contracts and store implementations under `loom.pipeline.stores`
  unless plan review identifies a stronger boundary.
- Keep execution orchestration in `loom.pipeline.execution`.
- Keep CLI modules as presentation over public APIs and diagnostics.
- Keep `loom.runs` as a derived query facade, not an active state authority.
- Keep public imports stable, typed, and cheap.
- Do not introduce heavyweight runtime dependencies without an explicit design
  reason recorded in the phase plan and PR body.
- Default validation must remain local and deterministic.
- Real HPC, multi-host, or external-service tests must stay opt-in unless the
  repository later provides a local deterministic service fixture.
- HPC support must be capability-declared by topology. The implementation must
  not silently assume a long-running login-node daemon or compute-to-login
  networking.
- Mutating operations must fail closed when authority is missing,
  unavailable, stale, incompatible, or unable to prove required capabilities.
- Unsupported concurrency must fail before scheduling or worker launch. The
  implementation must not submit work and then discover that leases,
  cross-run coordination, or live commits are unavailable.
- Use `make validate-pr` before phase PR review and `make test-summary` before
  PR preparation.

## Design Principles

- One active lifecycle source of truth. Local files and derived projections are
  not fallback behavior stores.
- Authority contracts before caller migration. Runtime paths should move onto
  a contract that is already testable.
- Public names should reflect ownership. `RunStore` manages runs; scoped
  `StageStore` manages stages within a run; artifact stores manage
  materialized files only.
- Stage success is an authority commit, not proof that files exist.
- Submitted work is structured state. Submission, observation, cancellation,
  retry, and worker finalization must not be flattened into local status files.
- Leases and fencing are correctness mechanisms, not diagnostics.
- Service-backed consistency claims must be declared and tested. Unsupported
  modes should fail loudly.
- Deployment topology is part of backend capability. Managed services,
  allocation-scoped services, direct transactional databases, and deferred
  finalization have different guarantees and must not be presented as
  equivalent.
- Fallback modes must degrade features, not correctness. If a worker cannot
  reach authority, it may write materialized result envelopes, but only a later
  authority-backed reconciler can make lifecycle success visible.
- Capability checks are admission checks. If the requested mode needs a
  guarantee the selected backend/profile does not provide, the operation fails
  before creating competing lifecycle writers or submitted jobs.
- Backends can vary physically while preserving logical boundaries between
  run lifecycle, stage lifecycle, workspace coordination, and materialization.
- Keep review units small enough that store contract changes, caller
  migrations, backend implementation, backend adoption, and SQLite removal can
  each be reviewed on their own merits.

## Key Design Choices

- Reserve `RunStore` for the public authority surface that manages runs.
- Expose `StageStore` as a scoped handle under a run, sharing the parent
  authority's transaction/revision boundary.
- Keep workspace coordination separate for non-run sweep/resource/global
  counters, even if one physical service database stores all records.
- Split local filesystem helpers into artifact/materialization stores before
  broad runtime migration.
- Make direct local-only runtime mutation fail, rather than warning.
- Do not preserve old local lifecycle read compatibility.
- Define backend-neutral authority interfaces and a conformance harness before
  the concrete service backend.
- Implement a concrete Loom authority service backend in v9-post.
- Add a separate HPC deployment/fallback phase after the concrete backend so
  the plan does not assume an unmanaged long-running login-node service.
- Enforce strict capability gates for concurrent stages, concurrent runs,
  multi-host workers, sweeps, and shared resource coordination.
- Treat run-local SQLite authority as transitional v9 machinery and remove it
  from supported runtime behavior after service-backed parity.
- Keep derived catalog SQLite sidecars separate from active authority and
  retain them only as rebuildable projections where useful.

## Public API Transition Rules

The current codebase already has a path-shaped `RunStore` protocol that mixes
runtime lifecycle methods with local filesystem responsibilities. V9-post
intentionally reclaims `RunStore` for authority-backed run lifecycle. The
transition rules are:

- Phase 1 records every current `RunStore`, `LocalRunStore`, and
  `LocalRunStorePaths` usage with its target role.
- Phase 2 introduces the authority-backed `RunStore` and scoped `StageStore`
  interfaces behind a public factory.
- Phase 3 moves local path, artifact, log, config, provenance, manifest, and
  worker-file behavior into artifact/materialization interfaces.
- Any temporary alias must be narrow, documented as transitional, and unable to
  perform mutating runtime lifecycle behavior without authority.
- By Phase 10, public runtime imports must not present path-shaped local stores
  as run lifecycle stores.

## Concrete Service Backend Direction

The concrete backend for this plan is a Loom authority service: clients talk to
a single configured authority endpoint through the public `RunStore` factory,
and the service owns all run, stage, submitted-operation, lease, commit,
snapshot, and coordination records. The service may expose one physical
database internally, but the public API remains split into run, scoped stage,
and workspace-coordination responsibilities.

The service is an authority control-plane process, not a scheduler. Runtime
entrypoints connect to an explicitly configured endpoint, or to a deterministic
local service fixture in tests. The plan does not require an implicit daemon to
be started for every local run. If the configured service is unreachable,
mutating operations fail closed and leave any local materialization
recoverable.

The service may use an internal database as a private implementation detail.
If that internal database is SQLite, only the service process may open the
database file; clients and workers must never coordinate by sharing the SQLite
file directly. A direct database adapter may be added only if it proves the same
multi-host and fencing guarantees through the conformance harness and declares
the operational assumptions it requires.

The service backend must provide:

- unique run admission and stable `run_uri` registration;
- monotonic revisions for committed lifecycle changes;
- compare-and-set run and stage transitions;
- run-level controller leases;
- stage attempt allocation;
- stage leases with fencing tokens;
- idempotent submitted-operation writes and observations;
- transactional output commits that bind attempt id, fence token, artifact
  facts, cleanup candidates, and terminal stage success;
- revisioned snapshots that expose active, stale, expired, abandoned,
  submitted, terminal, and cleanup states;
- recovery scans for expired leases and abandoned attempts;
- failure-closed behavior when the service is unavailable or a client has stale
  credentials, stale revisions, expired leases, or foreign fencing tokens.

The default implementation should avoid a heavyweight always-on dependency if
the same guarantees can be achieved with a repository-local service process and
standard-library client transport. If Phase 7 selects PostgreSQL or another
external database instead, the phase execution plan must justify the runtime
dependency, keep it optional until the adoption/default phases, and provide
deterministic default tests plus opt-in real-database coverage.

This plan removes direct run-local SQLite authority from runtime behavior. It
does not require deleting every non-authoritative SQLite projection, and it
does not allow SQLite on a shared filesystem to be described as a multi-host
authority backend.

## HPC Deployment And Fallback Capability Model

The implementation must not assume that an unmanaged login-node process can run
forever. Many clusters limit, kill, or discourage long-running login-node
processes, and some clusters block compute nodes from connecting back to login
nodes or arbitrary TCP ports. V9-post therefore treats deployment topology as
part of the authority capability model.

Supported capability profiles should be explicit:

- Managed service authority: a project, user, or site-managed service endpoint
  is reachable from submit hosts and compute workers. This supports live worker
  leases, lease renewal, submitted-operation observation, immediate output
  commits, cancellation observation, and recovery.
- Allocation-scoped service authority: a scheduler-managed service runs inside
  an allocation or service job and stores durable state externally or in a
  persistent service-private location. This can support live worker authority
  for the lifetime of the allocation when workers can reach the service.
- Direct transactional database authority: clients connect to a real database
  service that proves the same transition, lease, fencing, and revision
  guarantees. This avoids a Loom service process but requires explicit
  credentials, dependency, and network assumptions.
- Deferred finalization fallback: compute workers cannot reach authority, so
  they write sealed result envelopes and materialized outputs to the shared
  filesystem. A controller or reconciler that can reach authority later accepts
  or rejects those envelopes through `RunStore`/`StageStore`.

Deferred finalization is a weaker capability, not a local-authority fallback.
Workers in that mode must not mark stages succeeded, update run/stage status,
renew live leases, or commit output directly. They can only produce
materialization plus a result envelope containing the run URI, stage name,
attempt id, submitted-operation id, plan/fingerprint evidence, output manifest,
exit status, scheduler job id, timestamps, and diagnostics. The reconciler then
performs the guarded authority transition. If the run was cancelled, retried,
or superseded while the worker was offline, authority rejects the stale result.

A single process may act as both lifecycle runner and service only for local
development, deterministic tests, or explicitly declared single-process
topologies. It must not advertise durable multi-host capability. Robust HPC
live-worker operation needs either an independently managed service, a
scheduler-managed allocation service, or a direct database authority that all
participants can reach.

### Deployment Profile Implications

The profiles differ mostly by who keeps authority alive, who can reach it, and
whether worker commits happen live or later through reconciliation.

| Profile | How it runs | Single run with multiple stages | Multiple concurrent runs | Main tradeoff |
| --- | --- | --- | --- | --- |
| Zero-setup co-located authority | `loom run` starts or embeds a local authority service for that process or host. The service owns private persistence; local files are still only materialization. | Good for ordinary local serial or bounded local parallel runs. Leases, attempts, commits, and retries work while the runner/service is alive. If the process dies, recovery depends on the private persisted authority state and restart path. | Weak for independent terminals and not multi-host unless they explicitly connect to the same service. Separate co-located runs have no shared cross-run counters or leases. | Best no-setup UX, weakest distributed guarantees. Must be labeled single-process or single-host. |
| Managed service authority | A user, project, or site-managed authority endpoint runs independently of any one run. | Strong live semantics: workers can acquire/renew leases, commit outputs immediately, observe cancellation, and recover stale attempts. | Strongest profile for concurrent terminals, concurrent runs, global counters, sweep trial leases, and shared diagnostics. | Requires service deployment, monitoring, endpoint security, and reachability from workers. |
| Allocation-scoped service authority | Scheduler starts a service inside an allocation or service job; workers in that allocation connect to it. State must be service-private and durable enough for the intended recovery scope. | Strong within the allocation while the service is healthy. Good when login-node daemons are not allowed but compute nodes can talk inside an allocation. | Good for runs sharing the same allocation. Weak across separate allocations unless they share a higher-level authority or transactional database. | Service lifetime is tied to scheduler allocation; queueing and post-allocation recovery need explicit handling. |
| Direct transactional database authority | Clients connect directly to a real database service that proves transactions, revisions, leases, fencing, and server-side time semantics. | Strong live semantics if compute workers can reach the DB and credentials are handled safely. | Strong for concurrent runs if the database supports the required isolation, lock, and recovery behavior. | Avoids a Loom service process, but adds database operations, schema migration, credential propagation, connection limits, and optional dependencies. |
| Deferred finalization fallback | Offline workers write sealed result envelopes and materialized outputs. A controller or reconciler later commits or rejects results through authority. | Correct but less live. Stage dependencies, retries, and success visibility wait for reconciliation. Cancellation is best-effort through the scheduler and stale results are rejected later. | Correct but lagged. Cross-run counters and live status cannot rely on offline workers; reconciliation becomes the point where authority changes. | Supports clusters without compute-to-authority networking, but does not provide live worker leases, live commits, or immediate status. |

There is no supported "just use local files as the store" fallback. A user who
wants a simple run without setting up a service should get the zero-setup
co-located authority profile, not `LocalRunStore` lifecycle mutation. That
profile can be the easy default for local development, but it must declare
single-process or single-host capabilities and fail loudly when a requested
feature needs multi-host authority.

## Strict Capability Gates

Every mutating entrypoint must evaluate the requested execution mode against
the selected authority backend and deployment profile before doing irreversible
work. When a guarantee is missing, Loom should reject the request with a
diagnostic that names the selected profile, missing capability, requested
feature, and safer alternatives.

Required gates:

- Single serial local run: requires authority-backed run lifecycle and
  artifact/materialization access. It may use zero-setup co-located authority.
- Bounded concurrent stages in one run: requires atomic attempt allocation,
  stage leases, fencing tokens, atomic output commits, revisioned snapshots,
  and recovery scans in the same run authority.
- Multiple independent runs from one terminal: allowed when each run has
  authority-backed lifecycle state. Shared counters, global limits, sweeps, or
  shared resource leases require cross-run coordination.
- Concurrent runs from multiple terminals or hosts in one workspace: requires
  shared run admission, unique run registration, cross-run coordination, and
  consistent reads from a common authority. Separate co-located authorities are
  not enough for shared workspace semantics.
- Live multi-host workers or submitted jobs: require a backend/profile that
  workers can reach while running, plus leases, fencing, backend-owned time or
  declared clock semantics, and failure-closed commit behavior.
- Deferred finalization workers: allowed only when selected explicitly or when
  diagnostics choose the fallback profile before submission. They cannot renew
  live leases or commit success directly.
- Sweeps, global resource limits, and trial/resource leases: require workspace
  coordination capabilities. They must not be implemented by directory scans or
  independent per-run stores.

Strictness rules:

- Do not auto-downgrade live worker mode to deferred finalization after jobs
  have been submitted.
- Do not run concurrent stages by relying on local filesystem locks when the
  backend lacks stage lease and fenced commit guarantees.
- Do not allow multiple controllers to mutate the same run unless the selected
  backend declares controller/run lease support for that topology.
- Do not claim cross-run concurrency or sweep safety when every run uses a
  separate co-located authority with no shared coordination.
- Read-only diagnostics may inspect weaker or historical layouts, but mutating
  commands must not use those layouts as behavior authority.

## Whole-Plan Implementation Details

These details are shared across phases and should be treated as defaults unless
a phase execution plan records a better local decision.

Public construction and configuration:

- Add one public authority factory, with `create_run_store(...)` as the draft
  name, that hides concrete backend classes from normal users.
- Use an explicit configuration object for authority selection. It should carry
  backend kind, deployment profile, endpoint or local-service reference,
  workspace id, persistence location when relevant, and redaction rules for
  diagnostics.
- Resolve configuration in a predictable order: explicit Python/CLI argument,
  run or workspace config, environment, then zero-setup co-located authority
  only for modes whose required capabilities fit that profile.
- Store or pass an authority reference, not concrete credentials, in worker and
  submitted-job handoff records. Diagnostics must redact sensitive endpoint or
  credential material.

Capability admission:

- Define a small internal required-capability model derived from the execution
  request: serial run, bounded parallel stages, subprocess worker, SLURM live
  worker, deferred finalization worker, multi-run submission, sweep/trial
  coordination, shared resource counter, and read-only inspection.
- Run capability admission before creating or mutating run/stage lifecycle
  records that would be hard to roll back. SLURM live submission and worker
  launch must be gated before jobs are submitted.
- Use distinct diagnostics for unsupported capability, unavailable authority,
  stale transition, expired lease, foreign fence, incompatible schema, and
  read-only historical layout.
- Keep read-only behavior separate. Read-only diagnostics may show why a layout
  is unsupported for mutation, but they must not silently promote local files
  into lifecycle truth.

Service data model:

- A service backend may physically use one database, but the logical records
  should stay aligned with authority scopes: workspaces, runs, run leases,
  stages, stage attempts, stage leases, submitted operations, output commits,
  artifact facts, recovery records, audit events, resource leases, counters,
  and deferred result envelopes.
- Stage data lives in run-scoped records keyed by `run_uri` and `stage_name`;
  it is not one database per stage.
- Revisions should be monotonically allocated by the authority backend for
  committed lifecycle changes. Callers should compare revisions or expected
  status rather than infer state from filesystem mtimes.
- Backend-owned time is preferred for lease expiry. If a backend cannot own
  time, its capability declaration must describe the clock assumptions and any
  unsupported deployment profiles.

Transaction boundaries:

- Run admission must atomically create or register the `run_uri`, initial
  status, workspace reference, metadata, and initial revision.
- Stage attempt allocation must atomically select the next attempt, record the
  owner, write the initial attempt state, and optionally issue the stage lease.
- Stage output commit must atomically verify attempt id, lease id, fencing
  token, current stage state, and absence of prior commit before recording
  artifact facts, cleanup candidates, terminal stage status, and revision.
- Submitted-operation create/update must be idempotent by submission id or
  idempotency key so status/cancel/retry paths are replay-safe.
- Deferred result reconciliation must atomically validate the envelope against
  the recorded attempt/submission and either commit or record a rejection
  reason.

Worker and submitted-job handoff:

- Handoff records should include `run_uri`, stage name, attempt id, owner id,
  submitted-operation id when present, deployment profile, authority reference,
  lease id and fencing token for live authority mode, artifact/materialization
  references, and plan/fingerprint evidence.
- Live worker handoff requires authority reachability and lease/fence
  material. Deferred-finalization handoff must explicitly omit live commit
  authority and instruct the worker to write a sealed result envelope.
- Worker finalization code must have one branch for live authority commit and a
  separate branch for deferred envelope materialization. They must not share a
  local-status fallback.

Deferred result envelopes:

- An envelope should be plain-data serializable and include run URI, stage
  name, attempt id, submitted-operation id, plan/fingerprint evidence, command
  exit status, scheduler job id if any, output manifest, materialized refs,
  timestamps, diagnostics, and producer identity.
- The envelope is evidence for reconciliation, not state. It becomes lifecycle
  truth only if authority accepts it through a guarded transition.
- Reconciliation must reject stale, duplicate, cancelled, superseded,
  malformed, or foreign-attempt envelopes and record enough diagnostic detail
  for users to understand the rejection.

Testing fixtures and harnesses:

- The authority conformance harness should be backend-parametric and reusable
  by in-memory fakes, the transitional SQLite authority, and the service
  backend while SQLite remains in the test matrix.
- Add deterministic local service fixtures for start/connect/health/stop,
  killed service, unavailable service, blocked worker networking, concurrent
  controllers, concurrent stages, stale worker commits, and deferred
  reconciliation.
- Keep real HPC, real database service, and real multi-host tests opt-in.
  Default tests should simulate topology failures locally.

Phase dependency reminders:

- Phase 2 owns shared authority interfaces, capability vocabulary, factory
  shape, and conformance harness. Later phases should not create alternate
  capability or factory systems.
- Phase 3 owns local artifact/materialization interfaces. Later phases should
  use those interfaces for files instead of reaching back into `LocalRunStore`.
- Phases 4-6 close local mutation and read fallback paths before the concrete
  service backend becomes the recommended path.
- Phase 7 proves the service backend in isolation.
- Phase 8 proves deployment profiles and fallback semantics.
- Phase 9 adopts the service/profile machinery across all runtime/read
  systems.
- Phase 10 removes transitional runtime SQLite authority without deleting
  non-authoritative catalog projections by accident.

## Candidate Implementation Surface

These names are implementation defaults for phase planning. A phase may refine
them, but it should not introduce parallel concepts with different names.

Candidate public and internal names:

- `AuthorityConfig`: plain-data configuration for backend selection,
  deployment profile, endpoint/reference, workspace id, local state path, and
  redaction policy.
- `AuthorityReference`: safe-to-serialize worker/submitted-job reference to an
  authority endpoint or local service handle. It should not embed raw
  credentials in logs, manifests, or diagnostics.
- `AuthorityBackendKind`: enum-like value for co-located service, managed
  service, direct transactional database, transitional SQLite, and test fake.
- `AuthorityDeploymentProfile`: enum-like value for `co_located`,
  `managed_service`, `allocation_scoped`, `direct_database`, and
  `deferred_finalization`.
- `RequiredAuthorityCapability`: internal required-capability value derived
  from execution mode.
- `CapabilityAdmissionResult` and `CapabilityAdmissionError`: structured
  admission outcome used before runner start, SLURM submission, worker launch,
  continuation, cancellation, and diagnostics.
- `RunStore`: authority-backed run lifecycle interface.
- `StageStore`: run-scoped stage lifecycle interface.
- `RunArtifactStore` and `StageArtifactStore`: artifact/materialization-only
  interfaces.
- `DeferredStageResultEnvelope`: plain-data worker result envelope for
  deferred finalization.

Candidate module ownership:

- `src/loom/pipeline/stores/authority.py`: current authority models and any
  low-level lifecycle records that remain backend-neutral.
- `src/loom/pipeline/stores/run_authority.py` or a refined
  `stores/authority.py`: public `RunStore` and scoped `StageStore` protocols
  once the existing path-shaped `RunStore` is renamed.
- `src/loom/pipeline/stores/config.py`: `AuthorityConfig`,
  `AuthorityReference`, deployment profile, backend kind, redaction helpers,
  and plain-data serialization.
- `src/loom/pipeline/stores/factory.py`: `create_run_store(...)` and backend
  registry/factory resolution.
- `src/loom/pipeline/stores/admission.py`: required-capability derivation and
  admission diagnostics, if keeping this near store capabilities is cleaner
  than placing it under execution.
- `src/loom/pipeline/stores/service_models.py`: backend-neutral service
  request/response and persisted-record shapes if the service transport needs
  plain-data messages.
- `src/loom/pipeline/stores/service_client.py` and
  `src/loom/pipeline/stores/service_server.py`: optional service client/server
  implementation, kept import-light from package roots.
- `src/loom/pipeline/stores/service_backend.py`: service-owned persistence
  implementation when it is not better split into a subpackage.
- `src/loom/pipeline/stores/artifact_store.py`,
  `local_artifacts.py`, and possibly a new materialization module: run/stage
  artifact store protocols and local implementation.
- `src/loom/pipeline/execution/authority_adapter.py`: adapter between runner
  orchestration and authority-backed run/stage stores.
- `src/loom/pipeline/execution/deferred_results.py`: envelope writing,
  validation helpers, and reconciliation orchestration if this does not belong
  under stores.
- `src/loom/pipeline/executors/slurm/*`: submission, status, cancellation,
  and manifest changes only through public authority config/handoff models.
- `src/loom/diagnostics/backend.py` and `preflight.py`: backend/profile
  diagnostics and admission explanations.
- `tests/support/authority_stores.py`: in-memory fake authority and service
  fixtures while keeping production code import-light.

Draft CLI and environment surface:

- CLI flags should prefer explicit authority options over hidden global state:
  `--authority-backend`, `--authority-profile`, `--authority-endpoint`,
  `--authority-workspace`, and `--authority-state` are draft names.
- Environment variables may mirror those options for subprocess and scheduler
  handoff, for example `LOOM_AUTHORITY_BACKEND`,
  `LOOM_AUTHORITY_PROFILE`, `LOOM_AUTHORITY_ENDPOINT`,
  `LOOM_AUTHORITY_WORKSPACE`, and `LOOM_AUTHORITY_STATE`.
- Sensitive credentials should not be represented directly in these draft
  variables unless the later phase adds explicit redaction and secret-source
  rules. Prefer references to configured credentials.
- `loom authority serve`, `loom authority check`, and
  `loom authority profile` are draft command names for service startup,
  reachability/capability diagnostics, and profile explanation if the CLI needs
  dedicated commands.
- Existing `loom backend ...` diagnostics should either route to the new
  authority diagnostics or remain a lower-level debug command with clear
  boundaries.

Candidate service constraints:

- `runs`: unique `run_uri`; workspace id; run status; creation/update
  revisions; metadata; active controller lease reference if modeled directly.
- `stages`: unique `(run_uri, stage_name)`; status; revision; reason.
- `stage_attempts`: unique attempt id and unique
  `(run_uri, stage_name, attempt_number)`; owner; status; revision.
- `leases`: unique lease id; kind; run URI; optional stage/attempt;
  owner id; fencing token; acquired/renewed/expires timestamps; state;
  revision.
- `submitted_operations`: unique `(run_uri, submission_id)` and optional
  idempotency key; scheduler metadata; state observations; revision.
- `output_commits`: unique `(run_uri, stage_name)` so a stage has one visible
  successful commit; attempt id; output names; materialized refs; revision.
- `artifact_facts`: keyed by commit id and artifact name; stores committed
  artifact refs/facts, not payload bytes.
- `deferred_result_envelopes`: unique envelope id and idempotency key; run URI;
  stage; attempt; producer; validation state; rejection reason; revision of
  reconciliation decision.
- `revisions`: monotonic per backend scope, or monotonic per workspace/run
  with the scope encoded clearly in returned `BackendRevision` values.
- `audit_events`: append-only diagnostic evidence linked to committed
  revisions, not authoritative state by itself.

Concrete admission examples:

- `loom run --parallel 4` with co-located single-process authority is allowed
  only when the local profile declares stage leases and fenced commits for that
  process/host. It must not imply multi-host safety.
- `loom run --executor slurm --live-workers` with deferred-finalization profile
  fails before `sbatch`; users must select a live authority profile or an
  explicit deferred-finalization mode.
- `loom run --executor slurm --deferred-finalization` with blocked worker
  networking may submit jobs, but generated scripts must write result
  envelopes and must not carry live commit authority.
- Multiple concurrent `loom run` invocations in one workspace may proceed only
  when the selected profile supports shared run admission or the runs are
  explicitly isolated with no shared workspace counters/resources.
- Future sweep execution requires workspace coordination; independent per-run
  co-located authorities are insufficient.

Concrete failure diagnostics:

- `authority.unavailable`: endpoint cannot be reached or service health fails.
- `authority.unsupported_capability`: selected backend/profile lacks a required
  capability for the requested execution mode.
- `authority.schema_incompatible`: backend exists but schema/version is not
  compatible.
- `authority.stale_transition`: expected revision/status no longer matches.
- `authority.lease_expired`: lease exists but expired before mutation/commit.
- `authority.foreign_fence`: worker has a lease/fencing token that does not
  match the active authority record.
- `authority.local_lifecycle_disallowed`: a local file or old local store was
  offered for mutating lifecycle behavior.
- `authority.deferred_rejected`: deferred envelope was stale, malformed,
  duplicate, superseded, cancelled, or inconsistent with authority records.

Concrete review checkpoints:

- Phase 2 should leave exactly one public factory path and exactly one
  required-capability vocabulary.
- Phase 3 should leave no lifecycle methods on artifact/materialization
  interfaces.
- Phase 5 should prove that SLURM submission cannot occur before capability
  admission.
- Phase 7 should prove service transaction boundaries before system-wide
  adoption starts.
- Phase 8 should prove deferred finalization cannot be mistaken for live
  authority.
- Phase 9 should prove every entrypoint uses the shared authority config and
  handoff records.
- Phase 10 should prove runtime SQLite authority is gone while catalog SQLite
  projection behavior still works if retained.

## Run Lifecycle Contract

The authority-backed run lifecycle is:

- Run is admitted through `RunStore`, which records a unique `run_uri`, initial
  run metadata, and revision.
- Controller opens or resumes a run by acquiring or renewing a run-level lease
  with an owner id and fencing material where required.
- Planning and submitted-operation setup are recorded through guarded updates.
- Run status transitions carry expected prior status or revision and return the
  resulting revision.
- Cancellation and interruption are authority transitions that also record
  submitted-operation observations where relevant.
- Run finalization is derived from authoritative stage terminal facts and is
  committed through `RunStore`.
- Snapshots are revisioned and include stage summaries, active leases, stale or
  expired work, submitted operations, cleanup candidates, and recovery hints.
- Recovery scans identify expired leases, abandoned attempts, stale submitted
  work, and incomplete commits without reading local files as behavior.

## Stage Lifecycle Contract

The authority-backed stage lifecycle is:

- A stage is selected from the execution plan and opened through its parent
  run's scoped `StageStore`.
- Stage attempt allocation is atomic and records the attempt id, owner id,
  planned action, and initial revision.
- A worker or controller acquires a stage lease and fencing token before
  mutating stage lifecycle or finalizing output.
- Running or submitted state is recorded through guarded transitions.
- Submitted-operation facts are written with idempotency keys or submission ids
  so submit, retry, observe, and cancel paths are replay-safe.
- Local files may be materialized before commit, but they do not imply success.
- Output commit atomically records attempt id, fencing token, artifact refs or
  facts, cleanup candidates, terminal success, and resulting revision.
- Failure, cancellation, blocking, stale transition, and expired-lease outcomes
  are authority facts.
- Stale commits with missing, expired, or foreign fencing tokens fail before
  visible success.
- Recovery scans can identify abandoned attempts and produce retry or cleanup
  candidates without trusting local status files.

## Cross-Run Coordination Contract

Cross-run coordination is handled by the authority service or a separate
workspace coordination surface when the facts are not run lifecycle facts.

Required responsibilities include:

- unique run allocation or admission across concurrent terminals;
- optional run admission limits and global counters;
- sweep/trial claim records and trial leases for future sweep work;
- named resource leases and recovery scans;
- references from coordination records to authoritative `run_uri` values;
- diagnostics for stale claims, unavailable coordination, and unsupported
  multi-host capabilities.

The implementation may store run, stage, and workspace coordination rows in one
database, but public callers should not use a workspace authority object to
mutate ordinary run or stage lifecycle.

## Initial LocalRunStore Migration Map

Phase 1 must refresh this map with a full `rg -n
"LocalRunStore|LocalRunStorePaths"` pass and line-item disposition for every
hit. The current draft baseline is:

| Area | Current files | Current role | Required action |
| --- | --- | --- | --- |
| Default local/subprocess run | `src/loom/cli/run.py`, `src/loom/pipeline/execution/authority_adapter.py` | Authority-backed runtime with local path/materialization helpers. | Keep authority behavior, move local helpers behind artifact stores, and later select the service backend. |
| Direct Python runner construction | `src/loom/pipeline/execution/runner.py`, Python examples, runner tests | Local-only runtime mutation escape hatch. | Hard-fail mutating local-only stores and migrate examples/tests to the authority factory. |
| SLURM dry-run/live | `src/loom/cli/run.py`, `src/loom/pipeline/executors/slurm/*` | Planning, submission, submitted state, manifests, status, and cancellation mix local files and runtime behavior. | Move lifecycle/submission facts to authority; keep manifests/scripts/logs as materialization. |
| Stage worker CLI | `src/loom/cli/stage.py`, `src/loom/pipeline/execution/stage_worker.py` | Worker can construct local runtime store. | Require authority config, attempt id, owner id, lease, and fencing token. |
| Stage-job continuation | `src/loom/cli/stage_job.py`, `src/loom/pipeline/execution/continuation.py` | Submitted stage finalization can use local store. | Finalize through authority only. |
| Prepared-run continuation | `src/loom/cli/prepared_run.py`, `src/loom/pipeline/execution/continuation.py` | Whole-run continuation can resume local records. | Acquire run authority and guarded run/stage transitions. |
| Plan/resume reads | `src/loom/cli/plan.py`, planning/resume tests | Runtime-adjacent behavior read path. | Read lifecycle behavior from authority; use artifact stores for local root/path selection only. |
| Execution local paths | `runner.py`, `stage_attempts.py`, `continuation.py`, subprocess and SLURM helpers | Local stage dirs, artifact roots, worker requests/results, logs, generated artifacts. | Replace `LocalRunStorePaths` with run/stage artifact-materialization protocols. |
| Diagnostics/preflight | `src/loom/diagnostics/*` | Mixed authority reads and local file inspection. | Use authority for behavior; inspect local files/logs/artifacts only as materialization. |
| Run catalog/extraction | `src/loom/runs/_scan.py`, `src/loom/runs/_extract.py`, catalog tests | Derived projection with local lifecycle fallback risk. | Source lifecycle facts from authority read models; local scans discover materialization only. |
| Store primitive tests | `tests/contracts/test_store_contract.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py` | Tests local file store as both lifecycle and layout primitive. | Split authority contracts from artifact/materialization contracts. |
| Runtime behavior tests | runner, local execution, resume, parallel, subprocess, worker, stage-job, SLURM, CLI tests | Many tests normalize `LocalRunStore` runtime use. | Replace with authority-backed factories/fakes and add local-only rejection regression tests. |
| Public examples/docs | `examples/execution/*`, `examples/operations/*`, `docs/features/*` | Several examples teach direct `LocalRunStore` runtime use. | Use public authority factory; document local artifact access separately. |

## Conflicts And Tradeoffs

- Service process versus direct database: a service endpoint gives one
  reachable authority for HPC workers and avoids giving jobs database
  credentials, but it introduces a process that must be configured and
  reachable. A direct database adapter may follow later if it can prove the
  same contracts.
- Dependency footprint versus database maturity: PostgreSQL or another mature
  database can provide strong transactional behavior but adds operational and
  dependency cost. A Loom service implementation can keep dependencies small
  but must avoid inventing unsupported distributed guarantees.
- Hard-fail local mutation versus gradual migration: hard failure causes test
  and example churn, but warning-only behavior would keep the split-brain
  lifecycle path alive.
- Removing local lifecycle reads versus old-run convenience: strict authority
  semantics are clearer and safer, but users with old local-only runs lose a
  supported lifecycle read path unless a separate migration tool is designed.
- Removing run-local SQLite authority versus local developer convenience:
  SQLite authority has useful deterministic tests today, but keeping it as a
  supported runtime backend weakens the final multi-host consistency story.

## Maintainability Assessment

The plan reduces long-term maintenance cost by eliminating the current
`LocalRunStore` role overlap. After the migration, lifecycle behavior has one
contract surface, local materialization has a different contract surface, and
derived query code reads from authority snapshots instead of reconstructing
behavior from files.

Short-term churn is high. The migration touches store contracts, runner
construction, CLI helpers, worker finalization, SLURM paths, diagnostics,
catalog extraction, examples, and many tests. The ten-phase split keeps the
churn reviewable and avoids combining backend implementation with system-wide
adoption.

## Extensibility Assessment

Mandatory authority-backed lifecycle state enables later retries, timeouts,
cleanup, deterministic sweeps, bundle/export truth capture, service-backed
remote workers, and HPC diagnostics without revisiting every entrypoint. The
generic conformance harness keeps future backends from encoding behavior
through one implementation's incidental details.

The service backend is intentionally a state authority, not a scheduler. That
keeps room for future scheduler, queue, worker-daemon, sweep, and remote-store
work to build on the same lifecycle facts without being forced into this plan.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Historical local-only lifecycle reads are not preserved. | Preserving them would keep local files as a behavior source. | Users require an explicit old-run migration or archival inspection tool. |
| Temporary aliases may exist for renamed local materialization machinery. | Phased migration needs stable intermediate imports while callers move. | Phase 9 completes service adoption or Phase 10 removes SQLite authority. |
| SQLite authority may remain during Phases 1-9. | Existing v9 tests and adapters provide a bridge while service backend lands. | Phase 10 starts; service backend parity is proven. |
| Service deployment/auth/tenancy are deferred. | Current scope is lifecycle consistency, not hosted operations. | Users need shared production authority beyond trusted local/HPC environments. |
| Exact service storage internals are finalized in Phase 7. | The implementation must balance dependency footprint and consistency evidence. | Plan review or Phase 7 phase planning rejects the dependency/guarantee tradeoff. |
| Deferred finalization fallback is weaker than live worker authority. | Some HPC topologies block compute-to-authority networking, but correctness can still be preserved by reconciling sealed results later. | Users need live cancellation, live status, lease renewal, or immediate commits on a cluster where workers cannot reach authority. |
| Formal plan quality gate review budget is fully consumed. | The formal reviewer passed the plan with no findings, and the workflow allows only one initial review pass. | Do not reopen the plan quality gate unless the plan content changes materially before phase work. |

## Quality Gate Refinement Notes

Local quality-gate review checked the draft against maintainability,
extensibility, future compatibility, conflicting design choices, technical debt,
test strategy, and reviewability.

Findings addressed in this refinement:

- The plan now states how the existing path-shaped `RunStore` name is migrated
  without leaving it as a lifecycle-compatible local store.
- The service backend direction now distinguishes an authority service process
  from direct shared database/file access.
- The plan now states that service-owned SQLite, if selected internally, is not
  the same as direct run-local SQLite authority and cannot be opened by
  clients or workers.
- Phase 7 now has clearer service lifecycle, health, and dependency review
  obligations.
- The plan now adds a distinct HPC deployment/fallback phase so login-node
  daemon assumptions, blocked compute networking, co-located runner/service
  limitations, and deferred finalization are reviewed explicitly.
- The plan now records cross-phase implementation details for factory/config
  construction, capability admission, service record shape, transaction
  boundaries, worker handoff, deferred envelopes, and deterministic topology
  tests.
- The plan now records candidate module ownership, draft CLI/environment
  options, service constraints, concrete admission examples, failure diagnostic
  codes, and per-phase review checkpoints.
- The plan now records that formal `loom_plan_reviewer` review is still
  required before implementation.

Residual review risks for the formal gate:

- Phase 7 may still be large if the service protocol, persistence engine,
  client, diagnostics, and concurrency tests cannot fit in one reviewable PR.
- Phase 2 must handle the existing public `RunStore` protocol carefully so
  import churn does not obscure behavior changes.
- Phase 8 introduces a weaker deferred-finalization capability; review must
  confirm it cannot be confused with live worker authority.
- Phase 10 must avoid deleting non-authoritative catalog SQLite projections
  while removing runtime SQLite authority.

## Plan Quality Gate

Status: passed on 2026-05-10.

Formal `loom_plan_reviewer` review completed on 2026-05-10 with no blocking
or non-blocking findings. The reviewer found the plan scope-complete,
phase-bounded, domain-neutral, and covered by suite-level test obligations plus
PR validation evidence expectations.

Budget status:

- Initial plan review: used on 2026-05-10.
- Refinement pass: not needed because the review found no blockers.
- Confirmation review: not needed because the initial formal review found no
  blockers and no refinement changed the plan.

Accepted risks to watch during phase execution:

- Phase 7 service backend PR size.
- Phase 2 public `RunStore` transition churn.
- Phase 8 deferred-finalization semantics.
- Phase 10 separation of runtime SQLite authority removal from derived catalog
  SQLite projections.

## Phased Implementation

### Phase 1 - Exhaustive Inventory And Lifecycle Contracts

Status: merged
Branch: `codex/authority-inventory-contracts`
PR: https://github.com/samcantrill/loom/pull/109

Goal:

- Establish the complete migration map and strict lifecycle contract before
  behavior changes.

Scope:

- Run an exhaustive `LocalRunStore` and `LocalRunStorePaths` inventory across
  source, tests, examples, feature docs, and implementation docs.
- Classify every hit as runtime mutation, authority read, artifact or
  materialized file access, test helper, docs/example, or historical artifact.
- Update this plan or a linked phase artifact with the line-item migration map.
- Document run lifecycle, stage lifecycle, submitted-operation lifecycle, and
  failure-closed behavior as authority contracts.
- Define that local files cannot be used for run/stage behavior reads.

Out of scope:

- Implementing new store interfaces.
- Moving runtime entrypoints.
- Implementing service/database authority.

Acceptance criteria:

- Every current local-store runtime and behavior-read path has an explicit
  disposition.
- Lifecycle contracts identify guarded transitions, leases, fencing, revisions,
  snapshots, output commits, submitted-operation updates, and recovery scans.
- Local directory access is explicitly artifact/materialization-only.
- The phase records exact follow-up ownership for source, tests, examples, and
  docs.

Test expectations:

- Package: import-boundary review only.
- Unit: not required unless contract constants or diagnostics are introduced.
- Contract: not required.
- Integration: not required.
- E2E: not required.
- Opt-in: not required.

Design impact:

- High. This phase prevents undercounting local-store escape hatches.

Future compatibility:

- The inventory becomes the source of truth for later phase scoping and review.

Alternatives rejected:

- Relying on ad hoc migration while editing callers.

Debt introduced:

- None intended.

Reviewability:

- Review focuses on inventory completeness and lifecycle precision.

Completion summary:

- PR #109 opened on 2026-05-10 against `develop`; automated PR review found
  no blocking findings, GitHub CI `checks` passed, and the PR was squash-merged
  into `develop` as `7d3df7fd395036fa86b4365baa2e57755f8680f0`.
- Added `docs/phases/authority-inventory-contracts.md` with refreshed
  `LocalRunStore`, `LocalRunStorePaths`, path-shaped `RunStore`, and local
  helper inventory evidence; a migration map with future-phase ownership; and
  run, stage, submitted-operation, and failure-closed authority contracts.
- Validation before PR opening: `make validate-pr` passed Ruff, Pyright,
  default harness, config-extra, and build; `make test-summary` passed with
  overall 1534 passed, 12 skipped, 1128 deselected, and 0 failed/errors.
- Follow-up: Phase 2 can use the inventory and contracts to define the public
  authority interfaces and conformance harness.
- Stack maintenance: no successor branch existed at merge time, and the Phase
  1 remote branch was requested for deletion by the merge command.

### Phase 2 - Generic RunStore/StageStore Interfaces And Conformance Harness

Status: merged
Branch: `codex/run-stage-store-contracts`
PR: https://github.com/samcantrill/loom/pull/110

Goal:

- Define the generic authority contract and prove it with backend-neutral
  conformance tests before selecting implementation details.

Scope:

- Introduce or rename public authority interfaces around `RunStore` and scoped
  `StageStore`.
- Rename or split the existing path-shaped `RunStore` protocol so the new
  public name does not preserve local lifecycle behavior by accident.
- Define the public factory/configuration surface, with
  `loom.pipeline.stores.create_run_store(...)` as the preferred draft name.
- Define backend capability declarations for single-host, multi-host,
  service-backed, shared-filesystem-safe, lease TTL, monotonic revision,
  transaction isolation, recovery scans, and clock semantics.
- Define the required-capability admission model used by runner, CLI, SLURM,
  workers, diagnostics, and future sweep callers.
- Build a conformance harness for run lifecycle, stage lifecycle, leases,
  fencing, submitted operations, output commits, snapshots, stale transitions,
  and recovery.
- Keep compatibility adapters only where they are needed for later migration
  phases, and mark them transitional.

Out of scope:

- Migrating all runtime entrypoints.
- Implementing the concrete service/database backend.
- Removing SQLite authority.

Acceptance criteria:

- `RunStore` manages run admission/opening, run lifecycle, run-level leases,
  submitted operations, snapshots, and access to scoped stage stores.
- `StageStore` is scoped within a run and manages stage lifecycle, attempts,
  leases, submissions, commits, terminal state, and recovery facts.
- Existing path-shaped local store protocols are either renamed to
  artifact/materialization responsibilities or kept behind transitional names
  that cannot satisfy mutating runtime authority checks.
- The conformance harness can run against any authority backend implementation.
- Capability diagnostics are explicit enough for callers to fail loudly when a
  requested mode is unsupported.
- The factory/configuration surface can represent co-located, managed service,
  allocation-scoped, direct database, and deferred-finalization profiles
  without exposing implementation classes.

Test expectations:

- Package: public exports and import boundaries for authority interfaces and
  factory.
- Unit: interface validation, configuration parsing, and capability
  diagnostics.
- Contract: full authority conformance harness.
- Integration: minimal factory smoke tests.
- E2E: not required.
- Opt-in: not required.

Design impact:

- Very high. This phase defines the API all runtime paths and backends depend
  on.

Future compatibility:

- Enables future service, remote, retry, sweep, and HPC behavior without
  rewriting the runtime store API.

Alternatives rejected:

- Encoding the authority contract only in a concrete backend.
- Making `StageStore` independent from the parent run transaction boundary.

Debt introduced:

- Transitional adapters may exist until migration phases remove legacy usage.

Reviewability:

- Review focuses on public naming, interface scope, capability vocabulary, and
  conformance coverage.

Completion summary:

- PR #110 opened on 2026-05-10 against `develop`; branch
  `codex/run-stage-store-contracts`.
- Automated review found no blocking findings; GitHub CI `checks` passed and
  merge state was `CLEAN` before approval metadata was recorded.
- PR #110 was squash-merged into `develop` on 2026-05-10 as
  `dd4a212ca6b444d74151fa5ed6936cc1a1042987`.
- Implemented public authority `RunStore` and scoped `StageStore` protocols,
  `AuthorityConfig`/`AuthorityReference`, backend-kind and deployment-profile
  vocabulary, capability-admission diagnostics, `create_run_store(...)`, and a
  public authority adapter over existing per-run authority stores.
- Renamed the current path-shaped aggregate to `LegacyRunStore` and moved
  existing runtime call sites to the explicit transitional import.
- Added reusable public authority conformance coverage for in-memory and
  transitional SQLite adapters, plus package/unit/contract/integration tests.
- Validation before PR opening: `make validate-pr` passed Ruff, Pyright,
  default tests, config-extra tests, and build; `make test-summary` passed
  with package 57 passed, unit 834 passed, contract 107 passed, integration
  89 passed, e2e 39 passed, config-extra 420 passed, and 0 failures/errors.
- Merge checks: final `gh pr view` verified base `develop`, head
  `codex/run-stage-store-contracts`, state `OPEN`, CI `checks` success, and
  no merge commit before merge. A metadata-only approval push produced one
  failed CI run in
  `tests/integration/pipeline/test_parallel_execution.py::test_bounded_parallel_runs_independent_stages_concurrently`;
  the same test passed locally, the failed job was rerun once, and the rerun
  passed before merge.
- Stack maintenance: no successor branch existed at merge time, and the Phase
  2 remote branch was requested for deletion by the merge command.

### Phase 3 - RunArtifactStore And StageArtifactStore Split

Status: merged
Branch: `codex/artifact-store-split`
PR: https://github.com/samcantrill/loom/pull/111

Goal:

- Preserve useful local and future remote file access without allowing local
  files to masquerade as lifecycle state.

Scope:

- Rename or split useful local filesystem machinery into `RunArtifactStore`
  and `StageArtifactStore`, or equivalent artifact/materialization names
  finalized by the phase execution plan.
- Move config snapshots, provenance docs, logs, generated manifests, worker
  handoff files, local directories, and payload refs behind these interfaces.
- Remove or block local lifecycle reads and writes from artifact surfaces.
- Update tests that currently treat `LocalRunStore` as the local file layout
  primitive.
- Document that artifact/materialization stores are not lifecycle stores.

Out of scope:

- Runtime entrypoint migration.
- Service/database implementation.
- Artifact payload remote-store operations beyond interface boundaries.

Acceptance criteria:

- Artifact/materialization interfaces do not expose status, attempts, leases,
  submitted operations, output commits, snapshots, recovery, or behavior
  summaries.
- Existing local file needs are covered without importing lifecycle authority
  through local files.
- `LocalRunStore` is no longer documented as a local lifecycle reader.
- Any retained alias is transitional and cannot be used as a mutating runtime
  store.

Test expectations:

- Package: import-boundary tests for artifact interfaces.
- Unit: path safety, artifact/log/config/provenance helpers, and absence of
  lifecycle methods.
- Contract: artifact/materialization contract tests.
- Integration: local materialization round trips.
- E2E: not required.
- Opt-in: not required.

Design impact:

- High. This phase separates useful local files from lifecycle authority.

Future compatibility:

- Keeps room for remote artifact materialization without weakening authority
  semantics.

Alternatives rejected:

- Keeping `LocalRunStore` as the catch-all local interface.
- Preserving old local status readers as compatibility.

Debt introduced:

- Temporary aliases may remain while callers migrate.

Reviewability:

- Review focuses on local interface capability and absence of lifecycle access.

Completion summary:

- PR #111 opened on 2026-05-10 against `develop`; branch
  `codex/artifact-store-split`.
- Implemented `RunArtifactStore` and `StageArtifactStore` protocols plus
  local wrappers that expose materialization paths, config/provenance, logs,
  worker handoff files, workspaces, and generated files without lifecycle
  methods.
- Added package, unit, contract, and integration tests proving the
  artifact/materialization boundary and preserving payload `ArtifactStore`
  behavior.
- Validation before PR opening: `make validate-pr` passed Ruff, Pyright,
  default tests, config-extra tests, and build; `make test-summary` passed
  with package 57 passed, unit 836 passed, contract 108 passed, integration
  90 passed, e2e 39 passed, config-extra 420 passed, and 0 failures/errors.
- Automated review approved the PR on 2026-05-10 with no blocking findings;
  the review confirmed the diff stays within the artifact/materialization
  boundary and does not expose lifecycle authority through the new wrappers.
- Merged PR #111 into `develop` on 2026-05-10 with merge commit
  `2a12ceb6ccf681c7ccc1f24ef854825ac186d3e3`. Final GitHub CI `checks`
  passed after one rerun of the known flaky
  `test_bounded_parallel_runs_independent_stages_concurrently` failure on the
  docs-only review metadata head. The Phase 4 successor branch was prepared
  for rebase onto updated `develop`.

### Phase 4 - Python Runner And Public Example Migration

Status: merged
Branch: `codex/python-runner-authority`
PR: https://github.com/samcantrill/loom/pull/112

Goal:

- Make direct Python runtime execution authority-only.

Scope:

- Make mutating `PipelineRunner` usage reject local-only runtime stores.
- Replace direct Python examples and docs that teach
  `PipelineRunner(run_store=LocalRunStore(...))`.
- Update package/API tests and runtime tests that normalize local-only runner
  construction.
- Add clear diagnostics for local-only mutating attempts.
- Keep artifact/materialization examples separate from execution examples.

Out of scope:

- CLI worker and SLURM migration.
- Concrete service/database backend.
- Historical local-run migration.

Acceptance criteria:

- Direct mutating `PipelineRunner(LocalRunStore(...))` hard-fails.
- Public examples use the authority-backed factory.
- Tests distinguish runtime authority from artifact/materialization helpers.
- Serial execution remains default and authority-backed.

Test expectations:

- Package: public API examples/import tests.
- Unit: runner rejection, factory behavior, and diagnostics.
- Contract: authority-backed runner behavior through conformance fake or
  adapter.
- Integration: local/subprocess execution and resume through authority-backed
  stores.
- E2E: Python example execution where existing docs tests cover it.
- Opt-in: not required.

Design impact:

- High. This phase changes the primary Python extension surface.

Future compatibility:

- Future users can rely on authority-backed attempts, leases, commits, and
  snapshots through Python APIs.

Alternatives rejected:

- Warning-only deprecation.

Debt introduced:

- `create_authority_backed_serial_run_store` remains a transitional bridge
  that combines authority lifecycle writes with local materialization paths.
  Changed-config same-run re-execution remains failure-closed when the
  transitional SQLite authority already has a stage output commit, rather than
  overwriting authoritative commits without explicit supersede semantics.

Reviewability:

- Review focuses on public API behavior and direct local-store rejection.

Completion summary:

- Phase execution plan drafted and refined on 2026-05-10 in
  `docs/phases/python-runner-authority.md`.
- Initially started from `codex/artifact-store-split`; after Phase 3 merged,
  branch `codex/python-runner-authority` was rebased onto updated `develop`
  and the PR target was reset to `develop`.
- Implemented a `PipelineRunner` guard that rejects bare `LocalRunStore`
  instances before mutation and routes public Python examples to
  `create_authority_backed_serial_run_store(...)`.
- Exposed the authority-backed serial factory from `loom.pipeline.execution`
  without adding eager optional imports.
- Updated package, unit, integration, docs-example, and e2e coverage so
  mutating Python execution uses authority-backed stores, while direct
  `LocalRunStore` tests remain scoped to local file behavior.
- Validation before PR opening: `make validate-pr` passed Ruff, Pyright,
  default tests, config-extra tests, and build; `make test-summary` passed
  with package 57 passed, unit 837 passed, contract 108 passed, integration
  90 passed, e2e 39 passed, config-extra 420 passed, and 0 failures/errors.
- PR #112 opened on 2026-05-10 against `develop`; initial verification
  confirmed base `develop`, head `codex/python-runner-authority`, state
  `OPEN`, and CI `checks` in progress.
- Automated review approved the PR on 2026-05-10 with no blocking findings;
  GitHub CI `checks` passed on the PR-open head.
- Final merge verification on 2026-05-10 confirmed PR #112 still targeted
  `develop`, head `codex/python-runner-authority`, and GitHub CI `checks`
  passed.
- PR #112 was squash-merged into `develop` on 2026-05-10 as
  `96f4392892ddead16b17ccf15e723b6791d7dfb3`. The branch was kept temporarily
  because Phase 5 had already been started as stacked successor branch
  `codex/cli-worker-authority`.

### Phase 5 - CLI, Worker, Submitted Job, And SLURM Migration

Status: merged
Branch: `codex/cli-worker-authority`
PR: https://github.com/samcantrill/loom/pull/113

Goal:

- Close operational runtime mutation escape hatches.

Scope:

- Move `loom run`, SLURM dry-run/live submission, `loom stage run`,
  `loom stage-job run`, and `loom prepared-run continue` to authority-backed
  `RunStore`/`StageStore` construction.
- Move SLURM cancellation and scheduler-status mutation to authority-backed
  submitted-operation observations and guarded run/stage transitions.
- Run capability admission before submitting SLURM jobs, launching workers, or
  materializing live-commit handoff records.
- Ensure workers and submitted jobs carry run URI, attempt id, owner id,
  lease/fencing material, and backend configuration needed for safe finalize.
- Ensure local manifests, scripts, worker files, and logs remain
  artifact/materialization only.
- Add failure diagnostics for missing authority, stale transitions, expired
  leases, and foreign fencing tokens.

Out of scope:

- Concrete service/database backend.
- New scheduler, worker daemon, queue, retry, or timeout policy.
- Real SLURM acceptance changes beyond existing opt-in coverage.

Acceptance criteria:

- No supported CLI, worker, or submitted mutating entrypoint constructs
  `LocalRunStore` as runtime authority.
- Submitted operations are idempotent and authority-recorded.
- Worker finalization cannot succeed without active authority and correct
  fencing.
- SLURM live paths fail before submission when the selected backend/profile
  cannot prove live worker commit semantics.
- SLURM dry-run and live paths materialize scripts/manifests without making
  those files lifecycle truth.

Test expectations:

- Package: CLI imports remain presentation-only.
- Unit: CLI helper construction, worker requests, submitted-operation updates,
  cancellation/status transitions, and failure diagnostics.
- Contract: submitted-operation and stage commit behavior in authority harness.
- Integration: SLURM dry-run/live with fakes, worker continuation, stage-job
  continuation, prepared-run continuation, cancellation/status paths.
- E2E: CLI run, CLI stage/job continuation where deterministic, and CLI SLURM
  dry-run.
- Opt-in: real SLURM acceptance remains opt-in.

Design impact:

- Very high. This phase changes operational execution paths most likely to run
  on HPC or from separate terminals.

Future compatibility:

- Future HPC, container, and remote workers inherit authority-fenced
  finalization.

Alternatives rejected:

- Migrating only `loom run` while leaving worker or submitted paths local-only.

Debt introduced:

- Service backend still follows in a later phase, so authority may temporarily
  use transitional backend implementations.

Reviewability:

- Review should be split by entrypoint family with concrete validation for
  each migrated command path.

Completion summary:

- Phase execution plan drafted on 2026-05-10 in
  `docs/phases/cli-worker-authority.md`; branch
  `codex/cli-worker-authority` was rebased onto updated `develop` after Phase
  4 merged.
- Routed CLI worker, submitted job, prepared-run continuation, SLURM
  dry-run/live preparation, cancellation, and scheduler-status helpers through
  authority-backed runtime stores.
- Added fail-closed SLURM live authority admission so unsupported transitional
  authority profiles reject before scheduler submission.
- Threaded authority attempt, lease, owner, and fencing metadata through
  stage-job and worker finalization paths.
- Validation before PR opening: `make validate-pr` passed Ruff, Pyright,
  default tests, config-extra tests, and build; `make test-summary` passed with
  package 57 passed, unit 837 passed, contract 108 passed, integration 90
  passed, e2e 39 passed, config-extra 420 passed, and 0 failures/errors.
- PR #113 opened on 2026-05-10 against `develop`; initial verification
  confirmed base `develop`, head `codex/cli-worker-authority`, and state
  `OPEN`.
- Automated review on 2026-05-10 found no blocking findings; local validation
  remained the merge evidence.
- GitHub CI initially failed the known
  `test_bounded_parallel_runs_independent_stages_concurrently` flake, then the
  failed job was rerun and `checks` passed.
- Final merge verification on 2026-05-10 confirmed PR #113 still targeted
  `develop`, head `codex/cli-worker-authority`, merge state `CLEAN`, and CI
  `checks` succeeded.
- PR #113 was squash-merged into `develop` on 2026-05-10 as
  `5bd4a8c376df35e4186e10942dca9acf403b1d10`.

### Phase 6 - Authority Read Models For Status, Catalog, Plan, And Diagnostics

Status: merged
Branch: `codex/authority-read-models`
PR: https://github.com/samcantrill/loom/pull/114

Goal:

- Ensure user-visible read paths do not infer lifecycle behavior from local
  files.

Scope:

- Route status, catalog, plan-resume reads, diagnostics, preflight, and
  extraction behavior through authority read models where lifecycle behavior is
  involved.
- Allow local artifact/materialization interfaces to expose files, logs,
  payloads, generated artifacts, and materialized refs only.
- Remove or loudly reject old local-only lifecycle read compatibility.
- Add diagnostics for local-only historical runs that explain artifact-only
  access and lack of supported lifecycle state.

Out of scope:

- Bundle/export behavior that belongs to v10.
- Historical migration into authority.

Acceptance criteria:

- `loom status`, catalog summaries, plan resume decisions, and diagnostics use
  authority for run/stage behavior.
- Local run/stage directories are exposed only as artifacts/materialization.
- Old local-only lifecycle reads are not preserved as supported behavior.
- Read-model tests prove local status files cannot override authority facts.

Test expectations:

- Package: run-catalog/status APIs avoid local lifecycle imports.
- Unit: read-model selection, local-file rejection for behavior, diagnostics,
  and old-run messaging.
- Contract: authority snapshot/read-model coverage.
- Integration: status, catalog, plan, diagnostics, and preflight over
  authority-backed runs.
- E2E: CLI status/logs/runs commands where applicable.
- Opt-in: not required.

Design impact:

- High. This phase prevents local lifecycle compatibility from reentering
  through read paths.

Future compatibility:

- Bundles, sweeps, dashboards, and reliability features can depend on
  authority-backed facts.

Alternatives rejected:

- Keeping local status files as a fallback behavior source.

Debt introduced:

- Users with old local-only runs may need external or manual migration if they
  need lifecycle behavior.

Reviewability:

- Review focuses on read-path behavior and strict local artifact-only access.

Completion summary:

- Phase execution plan drafted and refined on 2026-05-10 in
  `docs/phases/authority-read-models.md`.
- PR #114 opened against `develop` from branch
  `codex/authority-read-models`.
- Local automated review on 2026-05-10 found no blocking findings.
- `make validate-pr` and `make test-summary` passed before PR review.
- Final merge verification on 2026-05-10 confirmed PR #114 targeted
  `develop`, head `codex/authority-read-models`, merge state `CLEAN`, and CI
  `checks` succeeded.
- PR #114 was squash-merged into `develop` on 2026-05-10 as
  `ce79059ef4921e9e356d8ca0b05f9c45deb644ba`.

### Phase 7 - Concrete Service/Database Backend

Status: merged
Branch: `codex/authority-service-backend`
PR: https://github.com/samcantrill/loom/pull/115

Goal:

- Implement the concrete authority service backend needed for concurrent
  terminals, multi-host workers, and HPC submitted jobs, while keeping
  system-wide adoption for a separate phase.

Scope:

- Implement the first concrete service/database backend behind the generic
  `RunStore`/`StageStore` contracts.
- Provide a service client selected through the public factory/configuration
  path.
- Implement the logical service record model for workspaces, runs, run leases,
  stages, attempts, stage leases, submitted operations, commits, artifact facts,
  recovery records, audit events, resource leases, counters, and deferred
  result envelopes where needed by later phases.
- Document the backend feature set: multi-host consistency, transaction
  isolation, revisions, leases/fencing, idempotency, snapshots, recovery,
  stale transition handling, service unavailability, and clock/TTL semantics.
- Add local service/database configuration and diagnostics.
- Add explicit service lifecycle behavior for start/connect/health/stop in
  deterministic tests, without implying that Loom starts an unmanaged daemon
  for every run.
- Prove the backend against the conformance harness.
- Demonstrate concurrent run admission and concurrent stage mutation against
  the service backend with deterministic synthetic stages.
- Record the backend topology assumptions that the HPC deployment phase must
  turn into user-facing capability profiles.

Out of scope:

- Hosted production operations, authentication, authorization, and tenancy.
- A distributed scheduler or work queue.
- Remote artifact payload movement.
- Refactoring every runtime/read system to default to or fully exercise the
  new backend.
- Removing SQLite authority.

Acceptance criteria:

- The concrete backend passes the generic conformance harness.
- The service client cannot bypass the service by opening a shared authority
  database file directly.
- Run, stage, submitted-operation, lease, and output-commit transaction
  boundaries match the whole-plan implementation details.
- Backend diagnostics declare the consistency guarantees it proves and the
  deployment modes it does not support.
- Service health and unavailability behavior is covered by deterministic tests.
- Multi-process or service-backed integration tests demonstrate concurrent
  run/stage behavior with deterministic synthetic stages.
- HPC and multi-host workflows have explicit backend requirements and failure
  modes.
- The backend is selectable in targeted tests without becoming the default
  runtime authority.
- Any new dependency is optional or explicitly justified as required for the
  selected backend.
- If the service uses SQLite internally, tests prove that clients interact
  through the service boundary and that shared-filesystem SQLite is not
  advertised as a supported multi-host authority mode.

Test expectations:

- Package: optional backend modules do not add heavyweight imports to core
  packages.
- Unit: backend config, capability diagnostics, stale transitions, lease
  failure, idempotency, unavailable service, and client error mapping.
- Contract: full conformance harness.
- Integration: local service/database adapter with concurrent controllers and
  workers.
- E2E: CLI configured against the service/database backend if practical.
- Opt-in: real HPC or externally hosted database tests only.

Design impact:

- Very high. This phase defines Loom's durable consistency story beyond
  run-local files.

Future compatibility:

- Supports later sweeps, retry/recovery, remote workers, containers, and HPC
  execution without another authority rewrite.

Alternatives rejected:

- Treating SQLite on shared filesystems as multi-host authority.
- Letting HPC jobs finalize locally when authority is unreachable.
- Combining backend implementation with all caller adoption.

Debt introduced:

- Hosted operations and tenancy remain deferred.
- If the backend initially uses a minimal local service process, later
  production database adapters may still be needed.

Reviewability:

- Review focuses on backend correctness, consistency claims, failure-closed
  behavior, dependency footprint, and conformance evidence, not on all caller
  migrations.

Completion summary:

- Phase execution plan drafted and refined on 2026-05-10 in
  `docs/phases/authority-service-backend.md`.
- PR #115 opened against `develop` on 2026-05-10 from branch
  `codex/authority-service-backend`.
- Implementation adds the stdlib local authority service backend, public
  factory selection for service backend kinds, honest capability diagnostics,
  and conformance/integration coverage for concurrent clients.
- Local validation passed with `make validate-pr` and `make test-summary`.
  GitHub CI `checks` passed after rerunning a transient unrelated parallel
  execution test failure.
- PR #115 was squash-merged into `develop` on 2026-05-10 as
  `590e8ba56cc371c6e8ccee0ce354248b99cc36a4`.

### Phase 8 - HPC Deployment Modes And Fallback Capabilities

Status: pr_open
Branch: `codex/hpc-authority-deployment`
PR: https://github.com/samcantrill/loom/pull/116

Goal:

- Make authority deployment explicit for HPC and multi-host environments,
  including clusters where login-node services are killed or compute nodes
  cannot reach the authority endpoint.

Scope:

- Define capability profiles for managed service authority,
  allocation-scoped service authority, direct transactional database authority,
  co-located single-process authority, and deferred finalization fallback.
- Add configuration and diagnostics that describe which profile is selected,
  which guarantees it provides, and which runtime features are unavailable.
- Add preflight checks for service reachability, compute-to-authority
  networking assumptions, service health, lease clock semantics, endpoint
  propagation, and authority unavailability behavior.
- Define scheduler-managed service patterns for allocation-scoped operation,
  including service start, health check, endpoint distribution, shutdown, and
  recovery behavior.
- Implement or specify deferred finalization fallback: offline workers write
  sealed result envelopes and materialized outputs, and a controller or
  reconciler later commits or rejects them through authority.
- Define the envelope schema, idempotency/rejection behavior, and reconciliation
  transaction boundary.
- Ensure co-located runner/service mode is marked single-process or
  single-host only and cannot claim durable multi-host capability.
- Update SLURM dry-run/live planning docs and tests to show how each supported
  profile carries endpoint/configuration, attempt, owner, and fencing material.

Out of scope:

- Hosted production operations, authentication, authorization, tenancy, or
  high-availability service management.
- A scheduler, queue, worker daemon, or adaptive retry policy.
- Treating shared filesystem result envelopes as lifecycle authority.
- Making deferred finalization equivalent to live worker authority.

Acceptance criteria:

- No documented or tested HPC path assumes an unmanaged long-running login-node
  daemon is always allowed.
- Capability diagnostics distinguish live worker authority from deferred
  finalization and from single-process development/test authority.
- Preflight can report blocked or unproven compute-to-authority networking as
  an unsupported live-worker topology.
- Deferred finalization workers cannot mutate run/stage lifecycle directly.
- Deferred result envelopes are accepted only through guarded authority
  reconciliation and are rejected when stale, cancelled, superseded, malformed,
  or inconsistent with the recorded attempt/submission.
- Envelope schema and reconciliation diagnostics are stable enough for worker
  and controller code to share without importing scheduler-specific modules.
- Service death or unreachability causes mutating workers to fail closed and
  leaves materialization recoverable.
- Tests cover service-unreachable workers, killed service during execution,
  offline result envelope reconciliation, stale envelope rejection, and
  co-located runner/service capability downgrades.

Test expectations:

- Package: public capability/profile imports remain cheap and optional.
- Unit: profile selection, preflight diagnostics, endpoint propagation,
  envelope validation, stale rejection, and capability downgrade behavior.
- Contract: authority conformance continues to cover live authority profiles;
  deferred finalization has a separate reconciliation contract.
- Integration: deterministic local simulations for managed service,
  allocation-scoped service, blocked worker networking, and deferred
  reconciliation.
- E2E: SLURM dry-run and representative fake-live flow for each supported
  profile where deterministic.
- Opt-in: real HPC topology tests only.

Design impact:

- Very high. This phase prevents the service backend from depending on an
  unrealistic login-node daemon assumption and makes fallback behavior honest.

Future compatibility:

- Future retries, sweeps, cancellation, and dashboards can inspect backend
  capabilities before promising live worker behavior on a specific cluster.

Alternatives rejected:

- Treating a login-node service as the only supported HPC deployment model.
- Letting workers mark success locally when authority is unreachable.
- Advertising deferred finalization as full live multi-host authority.

Debt introduced:

- Deferred finalization gives weaker live status and cancellation semantics
  until a cluster can provide reachable authority.

Reviewability:

- Review focuses on capability honesty, failure-closed behavior, and whether
  every fallback preserves authority as the only lifecycle writer.

Completion summary:

- Phase execution plan drafted and refined on 2026-05-10 in
  `docs/phases/hpc-authority-deployment.md`.
- PR #116 opened against `develop` on 2026-05-10 from branch
  `codex/hpc-authority-deployment`.
- Implementation adds backend-neutral authority deployment diagnostics,
  deterministic live-worker preflight, deferred result envelopes, guarded
  authority reconciliation, and SLURM handoff documentation.

### Phase 9 - System-Wide Service Backend Adoption

Status: pending
Branch: `codex/service-backend-adoption`
PR: pending

Goal:

- Refactor Loom's runtime and read systems to use, configure, diagnose, and
  support the concrete service/database backend.

Scope:

- Route runner construction, public factories, CLI commands, workers,
  submitted-job continuations, SLURM planning/submission/cancel/status,
  status/catalog/plan/diagnostics/preflight, examples, and tests through the
  concrete backend where service-backed authority is selected.
- Add backend configuration resolution for terminals, subprocess workers,
  stage jobs, and HPC jobs, including endpoint propagation and safe diagnostic
  redaction.
- Route service-backed and deferred-finalization HPC profiles through the
  appropriate runtime/read paths without local lifecycle fallback.
- Use the shared authority reference and redaction model in every worker,
  submitted-job, CLI, and diagnostics handoff path.
- Prove that every supported mutating entrypoint can run against the concrete
  backend.
- Update docs and examples to show backend selection and service-backed
  execution without exposing internal backend classes.
- Keep SQLite authority available only as transitional support until the final
  removal phase.

Out of scope:

- Implementing the concrete backend itself.
- Removing SQLite authority.
- Hosted production operations, authentication, authorization, and tenancy.

Acceptance criteria:

- All runtime and behavior-read systems support the concrete backend through
  the public factory/configuration path.
- Worker and HPC handoff records carry the information needed to reconnect to
  the concrete authority backend without local lifecycle fallback.
- Worker and HPC handoff records declare the selected deployment profile and
  refuse live commits when only deferred finalization is available.
- Capability admission runs consistently across Python API, CLI, subprocess,
  SLURM, continuation, cancellation, status observation, and diagnostics
  entrypoints.
- Status, catalog, plan, diagnostics, and preflight behave correctly against
  service-backed runs.
- Tests and examples cover service-backed execution and read paths.
- SQLite authority remains clearly transitional and is not the recommended
  runtime backend.

Test expectations:

- Package: public factory and import-boundary tests for service-backed
  selection.
- Unit: configuration resolution, endpoint propagation, CLI construction,
  worker handoff, diagnostics, and redaction.
- Contract: existing conformance harness continues to cover backend behavior.
- Integration: runner, subprocess, worker, stage-job, SLURM fake flows,
  status/catalog/plan/diagnostics/preflight against the concrete backend and
  declared HPC profiles.
- E2E: CLI run and representative worker/submitted flows against the concrete
  backend where practical.
- Opt-in: real HPC or multi-host tests only.

Design impact:

- Very high. This phase makes the concrete backend operational across Loom
  without mixing adoption work into backend implementation.

Future compatibility:

- Later backends can follow the same implementation phase plus adoption phase
  pattern.

Alternatives rejected:

- Combining backend implementation and all system refactors in one oversized
  phase.
- Switching defaults before every runtime/read system supports the concrete
  backend.

Debt introduced:

- SQLite authority remains temporarily available until the final removal phase.

Reviewability:

- Review focuses on call-site coverage, configuration propagation,
  operational diagnostics, and service-backed behavior across systems.

Completion summary:

- Pending.

### Phase 10 - Service Default And SQLite Authority Removal

Status: pending
Branch: `codex/service-default-sqlite-removal`
PR: pending

Goal:

- Complete the transition by making the service/database backend the runtime
  authority path and removing run-local SQLite authority from supported runtime
  behavior.

Scope:

- Switch default runtime authority selection away from run-local SQLite.
- Hard deprecate and remove SQLite authority runtime use after service backend
  parity is established.
- Keep derived SQLite catalog sidecars only as rebuildable projection data
  where still applicable.
- Update docs, diagnostics, tests, examples, and feature docs to reflect the
  final backend matrix.
- Remove public runtime imports or configuration paths that expose run-local
  SQLite authority as a supported backend.

Out of scope:

- Removing all SQLite usage from derived non-authoritative projections if those
  projections remain useful.
- Historical migration of old local-only runs.
- Hosted service operations/auth/tenancy.

Acceptance criteria:

- New runtime authority no longer uses `SQLitePerRunAuthorityStore`.
- Attempts to configure removed SQLite runtime authority fail with clear
  diagnostics.
- Docs and examples present the service/database backend as the supported
  runtime authority.
- Derived catalog SQLite sidecars remain clearly non-authoritative if retained.
- The conformance matrix no longer treats run-local SQLite authority as a
  supported runtime backend.

Test expectations:

- Package: imports no longer expose SQLite authority as public runtime API.
- Unit: backend selection, deprecation/removal diagnostics, and projection
  separation.
- Contract: conformance harness excludes removed SQLite authority from the
  supported runtime backend matrix.
- Integration: default runtime path uses service/database authority.
- E2E: CLI default run through service/database authority where practical.
- Opt-in: not required unless backend operations need external services.

Design impact:

- High. This phase removes the transitional backend and simplifies future
  runtime assumptions.

Future compatibility:

- Future phases can assume service/database-backed lifecycle state.

Alternatives rejected:

- Keeping SQLite authority as a permanent dev/test runtime backend.

Debt introduced:

- None intended; any retained derived SQLite projections must be documented as
  non-authoritative.

Reviewability:

- Review focuses on removal completeness and avoiding accidental deletion of
  non-authoritative catalog projections.

Completion summary:

- Pending.
