# Roadmap v10 Planning Notes: DB-Backed Service Supervisor And Offline Authority Import

## Metadata

- Roadmap version: v10
- Source roadmap:
  `docs/implementation-plans/implementation-roadmap.md`
- Roadmap reframing note: v10 was previously reserved for run bundles and
  exporters. After v9-post landed, the immediate gap is operational authority
  service behavior: v9-post provides an authority-backed runtime and an
  in-memory co-located service, but not a durable service supervisor,
  persistent service database, strict online/offline policy, true offline
  import, or service-backed workspace coordination. Run bundles move to v11.
- Previous version status: v9-post is implemented and merged. It makes
  service-backed authority the default runtime path, rejects run-local SQLite
  as a supported runtime authority backend, and routes mutating runtime
  entrypoints through authority-backed stores.
- Planning notes status: draft
- Current discussion stage: Functionality and behavior confirmation readback
- Stage gates:
  - Roadmap framing: version outcome, target audience, planning priority, and
    service-supervisor rationale captured from discussion; awaiting final
    stage readback confirmation
  - Intent discovery: goals, non-goals, constraints, and operational realities
    captured from discussion; awaiting final stage readback confirmation
  - Feature brainstorming: include/defer direction drafted; awaiting final
    stage readback confirmation
  - Functionality and behavior confirmation: behavior drafted; awaiting user
    confirmation before context checkpoint and design decision review
  - Context compaction/reset checkpoint: not started
  - Design decision review: not started
  - Phase shaping: not started
  - Handoff: not started
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v9-post.md`
  - `docs/implementation-plans/implementation-plan-v9.md`
  - No v10 implementation plan exists yet.
- Related feature docs:
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/execution.md`
  - `docs/features/reliability.md`
  - `docs/features/resume.md`
  - `docs/features/remote-stores.md`
  - `docs/features/sweeps.md`
  - `docs/features/run-catalog.md`
  - `docs/features/slurm.md`
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/structure.md`
- Blockers:
  - None known for planning.
  - Implementation planning must verify current v9-post code paths for
    `AuthorityConfig`, `create_authority_backed_serial_run_store`,
    `LocalAuthorityService`, `ServiceAuthorityStore`,
    `WorkspaceCoordinationStore`, deferred finalization envelopes, CLI authority
    flags, diagnostics, preflight, and SLURM handoff.
  - Repository evidence check resolved on 2026-05-11: local `develop` was
    synced to `origin/develop` after the v9-post phase stack landed. The current
    code inventory contains the intended v9-post service baseline, including
    `AuthorityConfig`, `LocalAuthorityService`, `ServiceAuthorityStore`, and
    `create_authority_backed_serial_run_store(...)`. Implementation planning
    should still verify exact call paths before naming new v10 APIs.

## User Direction Captured

The next roadmap step should make authority service behavior operationally
clear and durable, not merely convenient for local development.

Requested behavior:

```text
If endpoint is configured:
  connect or fail

If endpoint is not configured or not reachable:
  fail by default and explain how to run offline first

If offline-first execution is explicitly requested:
  run offline, write import evidence, and require later sync/import
```

The user also wants:

- true offline behavior: a run can happen without an authority-created
  run/stage/attempt first, then later import into authority as equivalent truth;
- full cross-run workspace coordination through the service backend, including
  sweeps, global counters, and shared resource limits;
- later roadmap items pushed back so v10 can focus on the service supervisor
  and authority durability gap.
- strict behavior consistently across every system entrypoint;
- online-first execution as the preferred runtime mode;
- no backwards-compatible support or migration path for old implicit local
  authority behavior.

## Workflow Stage Readback

The current planning discussion has effectively moved beyond initial roadmap
framing into functionality and behavior confirmation, but the workflow still
requires an explicit readback before starting the design-decision review.

Roadmap framing locked decisions:

- V10 is the service-supervisor and offline-authority-import version.
- The primary audience is users and operators who need production-like
  authority behavior across independent CLI commands, Python entrypoints,
  workers, submitted jobs, and future sweep/resource workflows.
- The user-visible outcome is stricter and more predictable execution:
  authority-backed online runs by default, explicit offline-first runs when
  requested, and no hidden local service creation from runtime commands.
- The planning priority is correctness and operational clarity over local
  convenience.

Intent discovery locked decisions:

- V10 should hard-swap production-like mutating runtime behavior to shared
  authority resolution.
- V10 should deprecate co-located service language as a user-facing mode in
  favor of online versus offline.
- The authority server should be durable, DB-backed, supervisor-owned, and
  discoverable through explicit endpoint or registry metadata.
- Offline runs are acceptable only as local evidence until imported into
  authority.
- Workspace coordination should be service-backed through generic primitives,
  not through per-client direct DB access.

Feature brainstorming include/defer readback:

- Include strict authority resolution, DB-backed authority server, explicit
  supervisor lifecycle, service registry, shared client protocol, lifecycle
  state diagrams, authority-backed workspace coordination, simple named
  resource leases, local offline resource coordination, offline evidence, and
  offline import.
- Include scheduler-ready request/decision value objects and interfaces where
  they prevent future refactors.
- Defer a full global workflow scheduler, hosted multi-tenant service
  operations, authentication/authorization beyond local trusted metadata,
  high availability, external worker daemon management, remote artifact payload
  movement, cryptographic offline attestation, and domain-specific equivalence.

Functionality and behavior confirmation draft:

- Online mode is preferred and strict. Explicit endpoints or registry-discovered
  endpoints must connect and pass health/readiness checks before lifecycle
  mutation.
- If no online authority is available, runtime entrypoints fail by default with
  guidance for starting/configuring the supervisor or choosing explicit
  offline-first execution.
- Offline-first mode must be explicitly requested. It writes offline evidence
  and does not create authority run/stage/attempt truth until import.
- Python helpers follow the same policy as CLI entrypoints.
- Runtime commands do not implicitly start in-memory or DB-backed authority
  services. Service startup belongs to explicit supervisor commands or trusted
  supervisor APIs.
- The runner owns DAG orchestration and stage execution decisions; the authority
  server owns accepted lifecycle/resource mutations; the supervisor owns server
  process lifecycle.
- Online resource limits are generic authority-backed named integer leases.
  Offline resource limits are run-local only and must record that no cross-run
  guarantee existed.
- Interrupted stage attempts restart from scratch on resume.
- Terminal lifecycle states do not reopen by ordinary mutation.
- `SUBMITTED -> RUNNING` is allowed only when Loom regains active execution
  control after external scheduler acceptance.
- Offline import turns accepted local evidence into authority-owned truth with
  import provenance and conflict/equivalence checks.

Open readback questions before the checkpoint:

1. Does this readback correctly capture the functionality and behavior you want
   v10 to plan around?

Resolved repository-baseline question:

- Local `develop` has been reconciled with `origin/develop`, so the v10
  implementation-plan draft should start from the completed v9-post service
  baseline now visible in the source tree.

## User Understanding And Expectation Probe

The user is explicitly testing whether their mental model of v9-post is
accurate enough to shape v10. Planning should not assume that all terms are
settled. The implementation plan must preserve the distinction between
implemented behavior, desired behavior, and open policy choices.

Current user understanding signals:

- The user understands that v9-post introduced authority-backed runtime paths,
  but is unsure whether the implemented service is a durable service or an
  in-memory co-located fixture.
- The user understands that service connection policy matters and prefers a
  production-like connect-or-fail default over silent local service creation.
- The user is uncertain whether "managed service", "allocation-scoped service",
  and "co-located service" are implemented operational modes or mostly
  configuration/capability vocabulary.
- The user is uncertain where per-run lifecycle authority ends and cross-run
  workspace coordination begins.
- The user is uncertain whether current deferred finalization already solves
  offline-first runs. It does not; v10 must treat true offline import as a
  separate feature.
- The user expects v10 to clarify ownership: who starts the service, who stops
  it, who manages discovery, who owns DB state, who runs stages, and who owns
  run and stage lifecycle transitions.

Confirmed expectations from this discussion:

- Runtime entrypoints should not silently create an unrelated in-memory service
  as the production-like default.
- All system entrypoints should follow the same connection and offline policy
  for consistency. Python APIs, CLI commands, workers, submitted jobs, SLURM
  operations, diagnostics, and preflight should not each invent separate
  authority resolution behavior.
- Online service-backed execution is preferred whenever possible.
- If an endpoint is configured, Loom should connect to it and fail closed if it
  is unavailable.
- `loom run` should fail by default when no endpoint is configured or the
  configured endpoint is not accessible. The failure should include concrete
  guidance for starting/configuring the service and for running offline-first
  with later import/sync.
- Python helpers should also prefer online execution. If online authority is
  unavailable and offline-first has been explicitly requested, they should run
  offline and emit import evidence rather than silently starting an authority
  service.
- The concept of "co-located service" should be reconsidered or deprecated as
  a user-facing runtime mode. V10 should prefer clearer online/offline mode
  language, with any local service startup treated as supervisor-managed online
  infrastructure rather than an implicit fallback.
- If a local supervised service is kept, it should be DB-backed for ordinary
  runtime operation, not only in-memory.
- The in-memory service may remain for deterministic tests or explicit
  development fixtures, but should not be confused with durable runtime
  authority.
- The service supervisor/registry is expected to be real product machinery,
  not just the existing module-level singleton.
- The supervisor should place artifacts in an explicit directory specified
  when the supervisor is started.
- The supervisor should expose service endpoints for status, readiness, health,
  and runtime clients. FastAPI is a possible implementation option to evaluate,
  but v10 planning must weigh dependency cost against stdlib or smaller
  transports.
- Restart behavior should be explicit. Connecting services should be able to
  distinguish unavailable, starting, ready, unhealthy, stale, and incompatible
  supervisor states.
- Long-running stages must not depend on stale cached service assumptions. Each
  lifecycle update should revalidate service availability or use a connection
  protocol with health/lease renewal and acknowledged mutations.
- True offline import means a run may execute before authority has any
  run/stage/attempt records, and authority later imports equivalent evidence
  transactionally.
- Authority-backed workspace coordination should cover sweeps, global counters,
  shared resource limits, and cross-run leases through the same authority server
  boundary.
- V10 should hard-swap to the new behavior. It should not preserve migration or
  compatibility support for old implicit local-only runtime behavior.

Key uncertainty to resolve before implementation planning:

- Whether the first DB-backed authority server should use stdlib SQLite behind
  the server only, or a backend abstraction with SQLite as the first
  implementation.
- Whether the service registry is project-local, run-collection-local,
  workspace-local, allocation-local, user-global, or some combination selected
  by deployment profile.
- What explicit supervisor restart behavior should look like when a registered
  service is stopped but its DB and artifact directory still exist.
- How strong offline equivalence must be: plan/input/output fingerprints only,
  or also artifact checksums, config/provenance, runtime metadata, logs, and
  environment/code provenance.
- Whether offline import should be accepted only for v10-created offline
  evidence manifests or if any older local materialization directories should
  be rejected outright under the hard-swap policy.
- Whether service-backed workspace coordination should replace direct
  `sqlite_coordination` use for all production-like paths immediately, while
  keeping direct SQLite coordination only as private tests or transitional
  implementation internals behind the authority server.
- Which transport should back the supervisor API: existing stdlib manager
  transport, HTTP/FastAPI, another ASGI stack, or an internal protocol with
  optional HTTP diagnostics.

Remaining questions to ask the user during planning:

1. Should service lifecycle commands be under `loom authority ...`,
   `loom backend ...`, or both?
2. Where should local project service registry files live?
3. If a registry points to a stopped service but the DB exists, what exact
   fail-closed diagnostic and explicit restart command should Loom show?
4. Is stdlib SQLite behind the authority server an acceptable first durable DB
   backend if clients never open it directly?
5. Should imported offline runs be visually marked as imported in status,
   catalog, and diagnostics?
6. Should offline import require v10-created evidence manifests, or should it
   attempt best-effort import of older local materialization directories?
7. What level of proof is required for "equivalent" offline import?
8. Should service-backed workspace coordination become required before v12
   sweeps, or can v12 begin with sequential sweeps and optional service
   coordination?
9. Should the supervisor API use FastAPI/HTTP for operational clarity, or avoid
   that dependency until there is a stronger need?

## Current v9-Post Baseline

V9-post provides the authority-backed runtime boundary:

- `AuthorityConfig()` defaults to `co_located_service`.
- `create_authority_backed_serial_run_store(...)` resolves the selected
  authority config, creates a `PerRunAuthorityStore`, and combines it with
  local materialization through `AuthorityBackedSerialRunStore`.
- `LocalAuthorityService.start()` starts a stdlib `BaseManager` process that
  hosts `_ServiceAuthorityCore`.
- `ServiceAuthorityStore` is a client that calls the service proxy.
- Endpoint-less co-located configs currently start a process-local shared
  `LocalAuthorityService`.
- Explicit service endpoints are connected to and health-checked; unavailable
  services fail closed.
- Runtime mutations go through authority-backed stores rather than bare
  `LocalRunStore`.
- Deferred finalization envelopes can be reconciled through authority when
  authority already knows the run, stage, attempt, and submitted operation.
- `WorkspaceCoordinationStore` exists as a separate contract; current service
  authority does not yet provide the full cross-run workspace coordination
  backend.

Important limitation:

- The current local service core is in-memory. It is not a durable DB-backed
  service, and the process-local singleton is not a registry or supervisor that
  independent commands can reliably discover and reuse.
- Endpoint-less co-located startup is current behavior, not desired v10
  behavior. V10 should hard-swap to strict online/offline mode semantics.

## Problem Statement

V9-post made the authority boundary correct, but service lifecycle is still too
implicit for production-like behavior. Independent commands must not silently
start their own authority service, because separate in-memory services would
produce separate authority states. That is convenient for tests and one-process
local runs, but not a sound default for multi-command, multi-controller,
worker, SLURM, or offline import workflows.

V10 should turn the service from a fixture-like runtime convenience into a
durable authority service with explicit ownership:

- who starts it;
- who stops it;
- where its endpoint and auth metadata are recorded;
- what DB backs it;
- what workspace/allocation it owns;
- how clients discover it;
- what happens when it is missing, stale, unhealthy, or incompatible;
- how offline evidence enters authority later;
- how cross-run coordination shares the same authority server boundary.

## Version Outcome

V10 should deliver a DB-backed authority server plus an explicit supervisor, with
durable service behavior needed before later features rely on authority across
independent commands, multiple runs, sweeps, remote stores, containers, and
reliability policies.

At the end of v10:

- runtime entrypoints use one shared authority-resolution policy;
- configured endpoints connect or fail;
- missing or unavailable online authority fails by default with guidance for
  starting/configuring the supervisor or running offline-first;
- offline-first execution is explicit and records import evidence;
- authority server state survives process restart through the selected DB
  backend;
- independent commands can discover or receive the same workspace/allocation
  service endpoint;
- service-backed per-run lifecycle and service-backed workspace coordination
  are both available;
- true offline run evidence can be imported into authority only when Loom can
  prove equivalence and avoid conflicts.

## Conceptual Ownership Model

### Design Judgement

The v10 structure is appropriate if it is treated as a small control-plane
boundary, not as several independent systems.

The useful decoupling is:

- orchestration is separate from authority;
- service process lifecycle is separate from run/stage lifecycle;
- persistence internals are hidden behind the authority API;
- artifact payloads and local files remain materialization, not lifecycle truth;
- workspace-wide atomic coordination is separate from high-level sweep policy;
- scheduler policy can be introduced later without owning persistence or DB
  internals.

The design becomes over-coupled or too complicated if:

- the runner starts or restarts authority processes as a hidden side effect;
- workers or CLIs open the authority DB directly;
- the authority server decides which stages to schedule;
- the supervisor accepts run/stage lifecycle mutations;
- authority persistence grows directly into a sweep scheduler or resource planner;
- every call site has its own authority-resolution policy.

The simpler pattern to aim for is a ports-and-adapters control plane:

```text
CLI/Python/worker entrypoint
  -> AuthorityResolver
  -> AuthorityClient
  -> AuthorityServer
  -> AuthorityRepository
```

`PipelineRunner` remains the orchestration engine. It should see one
`AuthorityClient`-shaped dependency, not the supervisor, registry, transport, or
database.

If Loom later becomes more of a workflow manager, add a scheduler as a policy
component beside authority rather than merging scheduler policy into authority
persistence:

```text
online entrypoint
  -> AuthorityResolver
  -> SchedulerClient
  -> WorkflowScheduler
  -> AuthorityClient
  -> AuthorityServer
  -> AuthorityRepository

offline entrypoint
  -> LocalScheduler
  -> PipelineRunner / RunController
  -> local/offline evidence
```

This preserves a stable public model:

- authority is truth and guarded mutation;
- scheduler is policy for what admitted work should start next;
- runner/controller executes one pipeline run or one assigned run/stage plan;
- executor/worker runs one concrete stage attempt.

The long-term scheduler may be global and resource-aware, but it should still
communicate through authority APIs and leases. It should not open the authority
DB directly.

Generic workflow-engine principles to borrow without over-building:

- keep orchestration, admission control, execution, persistence, and
  materialization separate;
- make state transitions explicit and guarded rather than inferred from files;
- make leases/fencing the boundary for concurrent work;
- keep workers dumb: they execute assigned work and report results, but do not
  decide global policy;
- keep resource coordination as admission control in v10, while reserving a
  scheduler policy port for future optimization and global queueing;
- expose small ports that can have local/offline and service-backed adapters.

V10 should not implement a full global scheduler, but it should avoid public
interfaces that would make one hard to add. Loom's runner can remain a single-run
DAG orchestrator for now while the authority server provides the durable
admission and coordination primitives needed by concurrent runners and future
schedulers.

### Naming Direction

`AuthorityService` and `AuthorityServiceSupervisor` are too close in everyday
language. V10 should choose names that make ownership obvious.

Preferred names to evaluate during implementation planning:

| Name | Owns | Does not own |
| --- | --- | --- |
| `PipelineRunner` | One pipeline run's orchestration: plan, ready-stage selection, executor calls, failure policy. | Service startup, DB access, cross-run scheduling policy. |
| `AuthorityResolver` | Shared entrypoint policy: endpoint/registry lookup, strict connect-or-fail, explicit offline selection. | Process startup unless called through an explicit supervisor API. |
| `AuthorityClient` | The client-side protocol used by runners, workers, CLI, diagnostics, and import tools. | Persistence, process lifecycle, scheduling decisions. |
| `AuthorityServer` | The running control-plane API that accepts/rejects run, stage, lease, commit, import, and coordination mutations. | Starting/stopping itself, choosing stages to run, interpreting domain artifacts. |
| `AuthoritySupervisor` | Operational lifecycle: start, stop, restart, readiness, health, registry, process identity, service artifact directory. | Run/stage state transitions and output commits. |
| `AuthorityRegistry` | Durable endpoint/reference metadata for a workspace or allocation. | Health decisions beyond recorded facts and validation helpers. |
| `AuthorityRepository` | Private DB adapter used only by `AuthorityServer`. | Public API behavior or direct client access. |
| `WorkspaceCoordinator` | Generic atomic workspace primitives exposed by the server: counters, leases, resource limits, recovery scans. | Sweep planning, trial generation, or stage scheduling. |
| `RunResourceCoordinator` | Offline/run-local resource admission for one run only. | Cross-run guarantees or workspace-wide limits. |
| `WorkflowScheduler` | Future policy component that chooses admitted work to start based on resources, time, priority, fairness, or queue state. | Authority persistence, DB access, or artifact interpretation. |
| `LocalScheduler` | Offline/local scheduler implementation for one run or one local process. | Workspace-wide guarantees. |
| `RunController` | Future narrower name for the active execution controller currently embodied by `PipelineRunner`. | Global scheduling policy or authority process lifecycle. |

Using `AuthorityServer` rather than `AuthorityService` should make the
distinction clearer: the server handles authority requests; the supervisor
handles whether that server process exists and is usable.

### Runner Ownership

`PipelineRunner` should continue to own orchestration decisions:

- resolve the run request;
- plan the DAG;
- decide which stages are ready;
- schedule serial or bounded parallel local stage execution;
- invoke executors;
- handle failure policy;
- request lifecycle mutations from authority.

It should not own durable service process lifecycle except through an authority
resolver/supervisor API.

Scheduler-ready interpretation:

- In unscheduled mode, `PipelineRunner` can continue to plan and execute a run
  directly after authority/resource admission succeeds.
- In future global-scheduled mode, a `WorkflowScheduler` can decide when a run or
  stage should start, then delegate execution to a `PipelineRunner` or narrower
  `RunController`.
- `PipelineRunner` is not deprecated by a scheduler; it becomes the execution
  controller used by either local/offline scheduling or global online scheduling.
- Avoid making `PipelineRunner.run(...)` the only public shape forever. V10
  should preserve enough seams for future methods such as prepare, claim,
  execute-ready-stage, and finalize to become scheduler-driven without rewriting
  stores or executors.

### Authority Supervisor Ownership

A new or expanded supervisor layer should own operational service lifecycle:

- resolve authority config from API, CLI, environment, workspace registry, or
  allocation context;
- connect to an existing endpoint and health-check it;
- start a DB-backed local or allocation-scoped service only through explicit
  supervisor commands or explicit trusted API calls;
- write and validate registry metadata;
- write service-owned artifacts under a directory specified when the
  supervisor starts;
- detect stale process IDs, stale endpoints, incompatible database schema, and
  service generation mismatches;
- stop or leave running services according to ownership policy;
- expose diagnostics and preflight facts;
- expose readiness and health endpoints so clients can distinguish starting,
  ready, unhealthy, stale, incompatible, and unavailable states;
- define restart behavior explicitly.

### Authority Server Ownership

The authority server process should own all mutable authority state behind its
API:

- run admission and run lifecycle;
- controller leases;
- stage lifecycle;
- stage attempts;
- stage leases and fencing tokens;
- submitted operations;
- output commits and artifact facts;
- audit events;
- snapshots and recovery;
- workspace coordination records, through generic coordination primitives;
- global counters and resource leases, without becoming a sweep scheduler.

Clients and workers must not open the authority DB directly.

### Local File Ownership

Local files remain materialization:

- artifact payloads;
- logs;
- config snapshots;
- provenance documents;
- worker request/result files;
- generated manifests;
- offline evidence records.

They may provide evidence for import or reconciliation, but they are not active
lifecycle truth by themselves.

## Online And Offline Authority Resolution Policy

V10 should replace silent endpoint-less service startup with strict online and
offline modes shared by Python, CLI, workers, submitted jobs, SLURM,
diagnostics, and preflight.

Proposed behavior:

1. If an endpoint is explicitly configured, connect and health-check it.
2. If a workspace or allocation registry is configured, read the service
   reference, connect, and verify workspace id, generation, and health.
3. If no online authority is available and offline-first mode is not explicitly
   requested, fail before lifecycle mutation with a clear diagnostic that
   explains how to start/configure the supervisor or rerun in offline-first
   mode.
4. If no online authority is available and offline-first mode is explicitly
   requested, run offline using the offline evidence contract and do not create
   authority lifecycle records until import/sync.
5. If a local service needs to be started, it is started by explicit supervisor
   lifecycle commands or trusted API calls, not as an implicit fallback from a
   run command.

Resolved policy:

- All entrypoints follow the same policy.
- `loom run` fails by default when online authority is unavailable.
- Python helpers run offline only when offline mode has been explicitly
  requested; they do not silently start a service.
- User-facing mode language should prefer online and offline over co-located.
- Any local service startup is supervisor-owned online infrastructure.

Open design choices:

- Where should workspace registry files live, for example `.loom/authority/`
  under a project/workspace root versus a user cache directory?
- Should supervisor-owned services stop at parent process exit, at allocation
  teardown, or remain running until an explicit `loom authority stop` command?
- Which flag/API names represent explicit offline-first execution and later
  import/sync?
- Which flag/API names represent explicit supervisor startup?

## Full Runtime Conversion Policy

V10 should convert mutating runtime and control paths to the authority-first
structure rather than adding the new service beside the old local mutation path.
This is a hard swap for production-like behavior, not a compatibility layer.

The conversion scope includes:

- `loom run` admission, run creation, stage transitions, attempt creation,
  output commit, failure handling, cancellation, interruption, and resume;
- Python helpers that execute pipelines or mutate run/stage lifecycle state;
- the current `PipelineRunner` path, which should become authority-client
  driven while retaining responsibility for local DAG execution;
- worker and submitted-job entrypoints such as `loom stage run`,
  `loom stage-job run`, and `loom prepared-run continue`;
- SLURM live submission, cancellation, status mutation, and continuation paths;
- offline-first execution evidence creation and later authority import;
- diagnostics and preflight reporting for selected authority mode, service
  health, registry source, DB profile, and offline import readiness;
- workspace and resource coordination used by runtime execution.

Read-only local surfaces may remain local when they are inspecting materialized
files rather than changing lifecycle truth. Examples include log inspection,
artifact payload browsing, local config/provenance snapshots, and catalog scans
over exported or materialized run directories. These surfaces must not mutate
run, stage, attempt, lease, resource, or workspace coordination state. Where a
read-only command can show either authority-backed state or local materialized
state, it should label the source so users know whether they are looking at
authoritative state or local evidence.

Why convert in v10:

- avoid two lifecycle sources of truth;
- make strict online/offline policy consistent across every entrypoint;
- ensure future scheduler and resource decisions can rely on one authority API;
- make offline import an explicit conversion from evidence to truth instead of
  a partial merge of local records;
- reduce per-entrypoint special cases and hidden startup behavior.

Implementation guardrails:

- all production-like lifecycle mutations should pass through shared authority
  resolution and an `AuthorityClient`-style boundary;
- direct local store mutation may remain only for offline evidence writers,
  read-model/materialization utilities, and tests/fixtures that explicitly
  exercise file formats or repository internals;
- in-memory authority behavior should be reserved for tests and development
  fixtures, not ordinary runtime fallback;
- no compatibility shim is required for old implicit local-only behavior.

## DB-Backed Authority Server

The current service core is in-memory. V10 should add a DB-backed authority
server core behind a stable API.

Required DB design stance:

- define a storage/repository interface that hides DB-specific internals from
  the supervisor and public authority API;
- keep the DB schema private;
- make authority API behavior the contract, not SQL tables;
- keep clients and workers from opening the DB directly;
- make it realistic to add a different DB backend later without rewriting
  runner, worker, CLI, supervisor, or diagnostics code.

Likely first backend:

- standard-library SQLite opened only by the authority server process;
- private schema;
- no client-side direct DB access;
- transaction boundaries around guarded transitions, attempt allocation,
  lease renewal/release/failure, submitted-operation updates, output commits,
  workspace coordination operations, and imports.

Database options to evaluate:

| Option | Fit | Tradeoffs |
| --- | --- | --- |
| SQLite behind the authority server | Strong first local DB candidate because it is standard-library, transactional, simple to test, and adequate when the server is the only DB writer. | Not a hosted multi-tenant database; care needed around service restart, locking, and filesystem assumptions. |
| PostgreSQL | Strong future managed-service candidate with mature concurrent transaction behavior and operational tooling. | Adds dependency and setup burden; likely optional integration rather than default local path. |
| DuckDB | Useful analytical embedded DB, but not a natural fit for concurrent authoritative writes. | Poor default for lifecycle authority unless a narrow read/projection use case appears. |
| LMDB or similar embedded KV stores | Potentially strong embedded durability/performance story. | Adds non-stdlib dependency and a lower-level data model; likely premature before SQLite proves insufficient. |
| Direct client-opened database | Not acceptable for v10 runtime authority. | Reintroduces bypass paths and weakens service ownership. |

This is different from the removed transitional SQLite runtime authority:

- removed behavior: clients/workers open run-local SQLite authority directly;
- v10 behavior: clients/workers talk to `AuthorityServer`; only the server opens
  its private DB.

Durability requirements:

- service restart can reload run, stage, lease, submitted-operation, commit,
  snapshot, audit, and workspace coordination state;
- schema version checks fail loudly for unsupported old/new DBs;
- leases and service generation handle restart semantics explicitly;
- import and output commit operations are atomic.

## Server API And Client Interaction

The implementation may expose operational and authority routes through one
process, but the logical owners must stay separate:

- `AuthoritySupervisor` owns operational routes.
- `AuthorityServer` owns authority mutation routes.

Supervisor operational endpoint categories:

- liveness: the process is reachable;
- readiness: the authority server is ready to accept lifecycle mutations;
- health: DB schema, DB connectivity, lease clock, service generation, and
  registry state are valid;
- capabilities: per-run and workspace coordination capabilities;
- diagnostics: redacted service, registry, DB, and deployment-profile facts.

Authority server API categories:

- run admission, controller leases, and guarded run transitions;
- stage attempt allocation, stage leases, and guarded stage transitions;
- submitted operations and deferred finalization reconciliation;
- output commits and artifact facts;
- offline import;
- generic workspace coordination operations.

If one FastAPI or HTTP application hosts both categories, route ownership should
still be explicit in code so operational handlers cannot mutate lifecycle state.

Transport options:

| Option | Fit | Tradeoffs |
| --- | --- | --- |
| Existing stdlib manager transport | Minimal dependencies and similar to v9-post fixture. | Weak operational UX; less natural for health/readiness endpoints and external process tooling. |
| FastAPI/HTTP | Clear health/readiness endpoint model and easy client interaction from separate processes. | Adds runtime dependencies; must be justified and isolated if adopted. |
| Minimal stdlib HTTP server | Avoids dependencies while giving explicit endpoints. | More custom protocol code and less ergonomic validation/routing. |
| gRPC or similar RPC | Strong typed RPC story. | Heavy for current needs and likely out of scope. |

FastAPI is a candidate, not yet a decision. The implementation plan should
choose a transport deliberately and record dependency tradeoffs.

Client interaction requirements:

- clients should query readiness before starting a mutating run;
- long-running stages should not assume a service remains healthy because it
  was healthy at launch;
- each lifecycle mutation should either revalidate service availability or use
  a connection/session protocol with lease renewal and failure detection;
- mutating calls should return explicit acknowledgements that include revision,
  accepted/rejected status, and reason details;
- clients should retry only where the operation is idempotent or where an
  acknowledgement/revision check can prove whether the mutation committed;
- timeout behavior should be controlled by the caller with clear diagnostics.

## Workspace And Allocation Registry

V10 needs a registry/supervisor layer, not just a service class.

The registry should be scoped so unrelated work does not accidentally share
authority:

- workspace id;
- authority reference id;
- endpoint;
- auth metadata or pointer to trusted auth metadata;
- DB path or managed service reference;
- process id where applicable;
- service generation/epoch;
- started-at and last-health timestamps;
- deployment profile;
- supported capabilities;
- redacted diagnostic summary.

Safety checks:

- stale process id detection;
- stale endpoint detection;
- registry lock or atomic update;
- workspace id mismatch rejection;
- generation mismatch diagnostics;
- schema compatibility checks;
- explicit replacement/restart policy.

## Per-Run Lifecycle Through Authority

The authority server must preserve the v9/v9-post per-run lifecycle model:

1. create or import run;
2. acquire controller lease;
3. transition run statuses through guarded transitions;
4. plan stages and persist plan evidence;
5. allocate stage attempts;
6. issue stage leases and fencing tokens;
7. record submitted operations where applicable;
8. record output commits atomically;
9. release or fail leases;
10. produce snapshots, recovery records, cleanup candidates, and audit events.

The runner schedules work. The authority server decides whether lifecycle
mutations are valid and durable.

### Run State Model

Current run status vocabulary:

- `CREATED`: authority has admitted the run identity and metadata.
- `PLANNED`: the execution plan and plan evidence have been persisted.
- `RUNNING`: a controller is actively orchestrating local or service-visible
  execution.
- `SUBMITTED`: execution has been handed to an external submission mechanism,
  such as a scheduler-backed flow.
- `SUCCEEDED`: terminal success.
- `FAILED`: terminal failure.
- `CANCELLED`: terminal cancellation.
- `INTERRUPTED`: interrupted execution. Resume does not continue an interrupted
  stage attempt in place; it creates new work from the last authoritative safe
  boundary.

Expected ordinary online transition shape:

```text
no authority run
  -> CREATED
  -> PLANNED
  -> RUNNING
  -> SUCCEEDED

RUNNING
  -> FAILED
  -> CANCELLED
  -> INTERRUPTED

PLANNED
  -> SUBMITTED

SUBMITTED
  -> SUCCEEDED
  -> FAILED
  -> CANCELLED
  -> INTERRUPTED
```

Resolved lifecycle policy:

- `SUBMITTED -> RUNNING` is acceptable only when Loom regains active execution
  control after an external scheduler accepted the work. Examples include a
  submitted job starting a Loom worker, or a controller reconnecting and taking
  over finalization of previously submitted work. It is not a generic retry path.
- `INTERRUPTED` is not a continuation checkpoint. Resuming an interrupted run or
  stage creates new work from the last authoritative safe boundary; interrupted
  stages restart from scratch as new attempts.
- Terminal states do not reopen by ordinary mutation. Any future rerun/retry
  behavior should create new attempts, replacement runs, or explicit
  supersession records rather than rewriting terminal facts.
- Offline import converts local evidence into authority truth when accepted.
  Import may either replay lifecycle events or create an imported authoritative
  snapshot, but the accepted result becomes authority-owned truth with import
  provenance.

V10 should reject any unmodelled transition with a structured reason. A caller
may request a transition; only authority can accept it.

### Stage State Model

Stage status vocabulary and v10 decision:

- `PENDING`: a planned or prepared stage attempt exists but is not executing.
- `RUNNING`: a stage attempt is actively executing under a lease.
- `SUBMITTED`: a stage attempt has been submitted to an external mechanism.
- `SUCCEEDED`: terminal success with committed output facts.
- `FAILED`: terminal failure.
- `BLOCKED`: terminal non-execution because upstream or planning requirements
  were not satisfied.
- `SKIPPED`: terminal non-execution because selection or reuse policy skipped it.
- `STALE`: non-executable stale-plan diagnosis unless v10 explicitly keeps it
  as a persisted status.
- `CANCELLED`: terminal cancellation.
- `INTERRUPTED`: if added for stages, a non-continuable interrupted attempt that
  must restart from scratch on resume. The current code's `StageStatus` does not
  yet include this value, so the implementation plan must either add it or map
  interrupted stage attempts to an existing terminal status with an explicit
  reason.

Expected ordinary stage transition shape:

```text
no stage record
  -> PENDING
  -> RUNNING
  -> SUCCEEDED

RUNNING
  -> FAILED
  -> CANCELLED

PENDING
  -> SUBMITTED

SUBMITTED
  -> RUNNING
  -> SUCCEEDED
  -> FAILED
  -> CANCELLED

PENDING
  -> BLOCKED
  -> SKIPPED

RUNNING
  -> INTERRUPTED
```

Required stage lifecycle guarantees:

- Attempt allocation, lease issue, and fencing token creation are authority
  mutations.
- A runner or worker can execute a stage only while it holds a valid attempt
  lease or can prove an accepted submitted-operation handoff.
- Output success is an authority commit, not just files appearing in a stage
  artifact directory.
- Long-running stages renew leases or revalidate authority before final commit.
- Authority rejects stale completion attempts after cancellation, replacement,
  lease expiry, or fencing-token mismatch.
- Interrupted stage attempts are never resumed in place. A later resume creates a
  new attempt and re-executes the stage from scratch.
- `STALE` should be clarified during implementation planning: prefer modelling
  it as a plan reason that produces `BLOCKED`/`FAILED`, rather than a durable
  execution status, unless a concrete read-model use case requires keeping it.

## Cross-Run Workspace Coordination Through Authority

V10 should bring `WorkspaceCoordinationStore` behavior behind the authority
server boundary, but only as generic coordination primitives.

Scope candidates:

- workspace records;
- sweep records;
- trial references;
- run URI references;
- global counters;
- named resource limits;
- resource leases;
- trial leases;
- cross-run recovery scans;
- capability diagnostics for cross-run coordination.

This should replace any need for clients to open a separate SQLite coordination
store for production-like service-backed operation. A private SQLite
implementation may still exist behind the authority server.

Important distinction:

- Per-run lifecycle says what happened inside one run.
- Workspace coordination says whether an atomic cross-run reservation, counter
  update, lease, or recovery scan is valid.
- Sweep logic decides what trials to create, which configurations to run, and
  how to interpret results. That should remain outside the authority server.

V10 should make both available through the same authority server/supervisor boundary,
without making the runner a scheduler or sweep engine.

### Resource Coordination Policy

Resolved v10 resource-coordination direction:

- Online resource coordination lives in `AuthorityServer`; do not add a separate
  `WorkspaceResourceSupervisor` process or registry.
- The public dependency should be a small `WorkspaceCoordinator` or
  `ResourceCoordinator` port exposed through `AuthorityClient`.
- Workspace resources are generic named integer limits, counters, and leases.
  Examples include `cpu`, `gpu`, `trial`, or project-defined slots after
  validation.
- The authority server answers "may this owner reserve this resource amount
  now?" It does not choose which pipeline, trial, or stage should run next.
- `PipelineRunner` still decides ready stages from the DAG. Before launching a
  ready stage, it asks the coordinator to acquire required leases. It launches
  only after acknowledged lease acquisition.
- Stage/resource leases should share the same long-running-work discipline:
  lease renewal, release/failure on terminal outcomes, fencing-token validation,
  and recovery scans for expired leases.
- Multi-pipeline coordination uses the same workspace-scoped authority
  primitives. Independent runners do not communicate directly with one another.
- Offline-first runs use only a run-local `RunResourceCoordinator` or equivalent
  adapter. It can limit concurrency within that run, but it must record evidence
  that no cross-run resource guarantee existed.
- Stage `ResourceRequest` declarations remain the source of requested resources,
  but only entries that can be mapped to integer named limits participate in v10
  shared lease admission. Unsupported or non-integer resource quantities should
  remain executor metadata with diagnostics unless a later version defines a
  mapping.

Rejected v10 alternatives:

- A separate workspace resource service: clearer isolation, but another process,
  registry, health surface, and failure mode before the design needs it.
- Runner-only resource pools: useful for one process, but cannot enforce
  cross-run limits.
- Scheduler policy embedded directly in authority persistence: would couple the
  authority server to DAG and sweep policy and force a scheduler refactor too
  early. A future `WorkflowScheduler` should be a separate policy component that
  uses authority APIs.

### Scheduler Extension Policy

V10 should be scheduler-ready without implementing a general scheduler.

Sufficient v10 behavior:

- Strict authority-backed lifecycle and resource admission.
- Generic resource leases and counters that can be used by local runners,
  future global schedulers, and future sweep controllers.
- Clear acknowledgements/rejections for attempts to claim work or reserve
  resources.
- Public ports that separate scheduling policy from authority mutation.

Future global scheduler behavior:

- A `WorkflowScheduler` may optimize run and stage start decisions based on
  resources, queue state, priority, fairness, wall-time estimates, or placement.
- The scheduler should use `AuthorityClient`, `WorkspaceCoordinator`, and
  resource leases to make decisions durable and fenced.
- The scheduler may be co-hosted by the same supervised process as
  `AuthorityServer`, but code ownership should remain separate.
- The scheduler may dispatch work to `PipelineRunner`/`RunController` instances,
  workers, subprocesses, SLURM, or later container executors.

Local/offline scheduler behavior:

- Offline-first runs should use a local scheduler/resource coordinator because
  they cannot provide workspace guarantees.
- The local scheduler can maximize resources within the one run or local process,
  but it must record that cross-run coordination was unavailable.

Public interface implication:

- Treat scheduling requests as data: requested resources, earliest start or
  timeout policy, priority metadata, owner identity, run URI, stage name,
  attempt identity, and provenance.
- Return explicit scheduling/admission outcomes: accepted with leases, rejected
  with reasons, blocked/waitable with diagnostics, or not implemented for
  unsupported resource semantics.
- Keep expressive `ResourceRequest` models. V10 should implement simple integer
  named leases first and raise clear unsupported/not-implemented diagnostics for
  resource semantics it cannot enforce yet.

## True Offline Run Import

Deferred finalization is not the same as offline-first execution.

Existing deferred finalization:

1. Authority already knows the run, stage, attempt, owner, and submitted
   operation.
2. Worker cannot reach authority.
3. Worker writes a deferred result envelope.
4. A reconciler later asks authority to accept or reject that envelope.

Requested true offline behavior:

1. A run executes without an authority-created run/stage/attempt.
2. The run writes enough offline evidence locally.
3. Later, a user imports that run into authority.
4. Authority accepts it only if Loom can prove the imported lifecycle and
   outputs are equivalent to the offline evidence and do not conflict with
   existing authority state.

Evidence likely required:

- run URI and optional import target URI;
- execution plan and plan fingerprint;
- config snapshots and composition/source provenance;
- stage order and dependency graph;
- stage input bindings and input fingerprints;
- stage attempts and terminal statuses;
- output artifact refs;
- artifact checksums and sizes where local payloads are available;
- failure records and traceback/log refs;
- runtime metadata and executor identity;
- timestamps and event/audit log;
- code/environment provenance where available;
- schema versions for every evidence record.

Import transaction behavior:

- reject if target run already exists unless an explicit collision policy is
  selected;
- reject missing required evidence;
- reject incompatible schema versions;
- reject changed plan/input fingerprints unless a defined equivalence policy
  permits them;
- reject missing or mismatched artifact payload/checksum evidence when required;
- create authoritative run/stage/attempt/commit facts atomically when accepted;
- mark imported runs with import provenance and evidence references;
- leave local files as materialization, not active truth.

Existing machinery to reuse:

- run URI model;
- execution plans;
- stage input/output records;
- fingerprints;
- artifact refs and artifact indexes;
- config/provenance documents;
- deferred envelope validation patterns;
- authority snapshots, commits, and revisions;
- run catalog summaries and warnings.

Missing machinery:

- offline execution evidence schema;
- offline event/audit log contract;
- equivalence checker;
- authority import transaction;
- conflict/collision policy;
- import diagnostics;
- CLI/API entrypoint;
- test fixtures for accepted and rejected imports.

## Public Surfaces To Consider

Potential Python APIs:

- `resolve_authority(...)` returning an `AuthorityClient` or explicit
  offline-mode decision
- `start_authority_server(...)` through `AuthoritySupervisor`
- `connect_authority(...)` returning an `AuthorityClient`
- `inspect_authority_server(...)`
- `stop_authority_server(...)` through `AuthoritySupervisor`
- `run_offline(...)` or equivalent explicit offline execution entrypoint
- `import_offline_run(...)`
- `create_authority_repository(...)` for private server-side DB adapters
- `create_workspace_coordinator(...)` for generic coordination primitives
- `create_run_resource_coordinator(...)` or equivalent run-local offline
  resource adapter
- `SchedulingRequest` / `SchedulingDecision` value objects for future scheduler
  ports, even if v10 only uses them for admission diagnostics
- `SchedulerClient` and `WorkflowScheduler` names reserved for future online
  policy components; v10 should not expose a half-implemented global scheduler

Potential CLI groups:

- `loom authority status`
- `loom authority start`
- `loom authority stop`
- `loom authority connect`
- `loom authority doctor`
- `loom run --offline` or equivalent explicit offline-first flag
- `loom authority import-offline`
- shared authority flags on existing runtime commands:
  `--authority-endpoint`, `--authority-reference`, `--authority-workspace`,
  `--authority-profile`, and an explicit offline-first option.

The final command names should be chosen during implementation planning after
checking existing CLI structure.

## Acceptance Criteria Draft

- Every production-like lifecycle-mutating entrypoint uses shared authority
  resolution before creating or changing run, stage, attempt, lease, resource,
  or workspace coordination state.
- `loom run`, Python execution helpers, `PipelineRunner`, worker entrypoints,
  stage-job entrypoints, prepared-run continuation, and SLURM live mutation
  paths are converted to authority-client-driven behavior.
- No production-like mutating command writes lifecycle truth directly to a local
  run store except through explicit offline evidence creation or authority
  import.
- Read-only local inspection commands either read authoritative service state or
  clearly label local materialized/evidence state and do not mutate lifecycle
  records.
- Endpoint-configured runtime commands connect to that endpoint or fail before
  lifecycle mutation.
- Commands do not silently start an in-memory or DB-backed authority server as
  a fallback from runtime execution.
- `loom run` fails by default when online authority is missing or unreachable
  and prints actionable guidance for starting/configuring a supervisor or
  choosing explicit offline-first execution.
- Python helpers follow the same policy: online-first by default, explicit
  offline-first only when requested, no implicit authority server startup.
- Any local authority server startup uses explicit supervisor commands or trusted API
  calls and creates DB-backed online authority for ordinary runtime operation.
- The in-memory authority server remains test/development fixture behavior only.
- Independent commands can discover and connect to the same workspace or
  allocation authority server through registry metadata.
- Authority server state persists across process restart.
- Supervisor artifacts are stored under an explicit startup-provided directory.
- Supervisor readiness, health, liveness, capability, and diagnostic endpoints
  are available to clients.
- Long-running stages renew leases or revalidate authority health before
  lifecycle updates, and mutating calls return acknowledgements with revisions
  or rejection reasons.
- Clients and workers cannot bypass the authority server by opening the DB directly.
- Per-run lifecycle conformance passes against the DB-backed authority server.
- Workspace coordination conformance passes against the authority-backed
  coordination backend.
- Concurrent run controllers can mutate distinct runs through one authority server.
- Bounded parallel stages in one run are scheduled by the runner but fenced and
  committed by the authority server.
- Online resource limits are enforced through authority-backed generic resource
  leases, while offline-first runs enforce only run-local limits and record that
  no cross-run resource guarantee was available.
- The authority server does not directly schedule DAG stages, sweep trials, or
  pipelines in v10; scheduler-ready request/decision data leaves room for a
  future `WorkflowScheduler` to do that through authority APIs.
- Offline run import accepts complete equivalent evidence and rejects stale,
  conflicting, incomplete, unsafe, or schema-incompatible evidence.
- Diagnostics and preflight explain selected authority server, registry, DB, workspace,
  deployment profile, capabilities, and online/offline policy.

## Out Of Scope For v10

- Hosted multi-tenant service operations.
- Authentication and authorization beyond existing trusted local metadata and
  endpoint/authkey style handoff.
- High availability and distributed consensus.
- Full online `WorkflowScheduler`, external workflow orchestration, queues, or
  worker daemons. V10 may reserve request/decision value objects and ports, but
  should not implement global scheduling policy.
- Remote artifact payload movement.
- Domain-specific output equivalence.
- Cryptographic signing or attestation of offline runs.
- Migration or compatibility support for old implicit local-only runtime
  behavior.
- Full sweep execution semantics; v10 provides coordination backend support so
  later sweep versions can use it.
- Run bundles/exporters; now v11.

## Candidate Phase Shape

Potential phases for the future implementation plan:

1. **Ports And Resolution**
   - Define authority resolution, client/server ports, repository boundaries,
     mode policy, registry schema, CLI/API flag shape, and conformance tests
     before converting callers.
2. **DB-Backed Authority Core**
   - Add persistent DB-backed authority server implementation for per-run lifecycle,
     storage abstraction, conformance, restart durability, acknowledged
     mutations, health/readiness/liveness endpoints, supervisor artifact
     ownership, and no direct client DB access.
3. **Runtime Entrypoint Migration**
   - Convert `loom run`, Python helpers, `PipelineRunner`, worker entrypoints,
     stage-job execution, prepared-run continuation, SLURM live mutation paths,
     diagnostics, and preflight to shared authority-first online/offline
     behavior.
4. **Resource And Workspace Coordination**
   - Implement authority-backed `WorkspaceCoordinationStore` behavior, generic
     resource leases, counters, run/trial references, cross-run recovery, and
     scheduler-ready request/decision value objects without implementing full
     workflow scheduling policy.
5. **Offline Evidence And Import**
   - Define offline evidence records, equivalence checks, import transaction,
     CLI/API, and accepted/rejected import tests.

Phase boundaries should be reviewed after the code inventory. If the DB schema
and authority supervisor are too large for one phase, split the DB-backed
authority core into schema/conformance and supervisor lifecycle phases. If
runtime adoption is too broad for one phase, split it by entrypoint class while
preserving the hard rule that no converted mutating path keeps the old local
lifecycle mutation behavior.

## Open Questions

- Where should the registry live for ordinary local projects, shared HPC
  allocations, and user-global managed services?
- What is the minimum DB backend for v10: stdlib SQLite behind the authority
  server only, or an abstract service DB interface plus one SQLite
  implementation?
- Should supervisor transport use FastAPI/HTTP, stdlib manager, stdlib HTTP, or
  another protocol?
- How should service-owned leases behave after service restart: expire all
  active leases, preserve unexpired leases with generation checks, or require a
  recovery action?
- Should offline import recreate intermediate lifecycle transitions or record a
  compact imported snapshot with import provenance?
- What artifact checksum guarantees are required for accepting offline imports
  when payloads are remote, missing, or intentionally metadata-only?
- Should imported offline runs be marked as `imported` in metadata only, or is
  a first-class lifecycle reason enough?
- Which commands own service lifecycle UX: existing `loom backend ...`,
  a new `loom authority ...`, or both?
- What should happen when a workspace registry points to an unavailable service
  but the DB path is present: what diagnostic should runtime clients show, and
  which explicit supervisor command or trusted API call owns restart?
- What exact name should the offline-first flag/API use, and should it be
  available for all executors at v10 launch?

## Notes For Implementation Planning

- Re-read `docs/features/run-store.md`, `docs/features/execution.md`,
  `docs/features/sweeps.md`, `docs/features/slurm.md`, and
  `docs/features/reliability.md` before drafting the implementation plan.
- Verify all v9-post service and authority modules before naming new APIs.
- Keep DB schema private and service-owned.
- Do not reintroduce client-opened run-local SQLite authority.
- Keep cross-run workspace coordination separate from per-run lifecycle in the
  public model, even if the same service and DB back both.
- Keep default tests deterministic and local. Real multi-host, HPC, and network
  service tests should remain opt-in unless a local deterministic fixture is
  enough.
