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
- Planning notes status: implementation-plan refinement complete; plan quality
  gate passed
- Current discussion stage: Design-choice follow-up and implementation-plan
  refinement complete; `docs/implementation-plans/implementation-plan-v10.md`
  passed plan quality gate review on 2026-05-11
- Stage gates:
  - Roadmap framing: version outcome, target audience, planning priority, and
    service-supervisor rationale captured from discussion; confirmed in
    functionality/behavior readback on 2026-05-11
  - Intent discovery: goals, non-goals, constraints, and operational realities
    captured from discussion; confirmed in functionality/behavior readback on
    2026-05-11
  - Feature brainstorming: include/defer direction confirmed in
    functionality/behavior readback on 2026-05-11
  - Functionality and behavior confirmation: confirmed by user on 2026-05-11
  - Context compaction/reset checkpoint: recorded on 2026-05-11; next pass must
    reload these notes and start design-decision triage without reopening
    behavior unless the user explicitly asks
  - Design decision review: complete after follow-up on 2026-05-11. The notes
    record recommendations plus user-confirmed choices for transport, registry,
    offline evidence eligibility, explicit state directories, hybrid import
    with replay-level evidence, strict import collision rejection, and hybrid
    resource lease admission behavior.
  - Phase shaping: expanded 18-phase shape confirmed by user on 2026-05-11
  - Handoff: user confirmed comprehensive implementation-plan drafting on
    2026-05-11; draft created at
    `docs/implementation-plans/implementation-plan-v10.md`
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v10.md`
  - `docs/implementation-plans/implementation-plan-v9-post.md`
  - `docs/implementation-plans/implementation-plan-v9.md`
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

Functionality and behavior confirmation confirmed on 2026-05-11:

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

User confirmation:

- The user confirmed that this readback correctly captures the functionality and
  behavior v10 should plan around.

Resolved repository-baseline question:

- Local `develop` has been reconciled with `origin/develop`, so the v10
  implementation-plan draft should start from the completed v9-post service
  baseline now visible in the source tree.

## Context Compaction/Reset Checkpoint

Checkpoint status:

- Recorded on 2026-05-11 after user confirmation of functionality and behavior.

Notes path:

- `docs/implementation-plans/roadmap-v10-planning-notes.md`

Resume instruction:

- Resume with `.codex/workflows/roadmap-version-planning.md` and this planning
  notes file. Reload the confirmed functionality and behavior from this
  checkpoint, the roadmap v10 entry, the v9-post implementation plan, relevant
  feature docs, and current source boundaries. Do not reopen functionality or
  behavior unless the user explicitly asks. Start the design decision review by
  drafting and recording the maintainability/extensibility decision queue.
  Record clear repo-supported recommendations directly, and ask the user only
  about high-impact decisions with no strong default.

Selected functionality:

- Strict shared authority resolution across production-like mutating CLI,
  Python, worker, submitted-job, SLURM, diagnostics, and preflight entrypoints.
- DB-backed, supervisor-owned authority server with persistent per-run lifecycle,
  stage lifecycle, submitted-operation, output-commit, audit, recovery, and
  workspace coordination state.
- Explicit service supervisor and registry for endpoint discovery, process
  lifecycle, readiness, health, stale-process detection, generation checks, and
  service-owned artifact directories.
- Authority-backed generic workspace coordination, global counters, named
  integer resource leases, and cross-run recovery scans through the same
  authority server boundary.
- Explicit offline-first execution that writes import evidence and uses only
  run-local resource coordination until import.
- True offline import that accepts local evidence into authority only after
  equivalence and conflict checks.
- Scheduler-ready request/decision value objects and ports, without implementing
  a global workflow scheduler in v10.

Confirmed behavior and defaults:

- Online service-backed authority is the preferred default.
- Explicit endpoints and registry-discovered endpoints must connect and pass
  health/readiness checks before lifecycle mutation.
- Missing or unreachable online authority fails closed by default with guidance
  for starting/configuring the supervisor or selecting explicit offline-first
  execution.
- Runtime commands and Python helpers do not implicitly start in-memory or
  DB-backed services.
- Service startup belongs only to explicit supervisor commands or trusted
  supervisor APIs.
- Clients and workers must talk to the authority API and must not open the
  authority DB directly.
- The runner owns DAG orchestration and stage execution decisions. The authority
  server owns accepted lifecycle, commit, lease, and resource mutations. The
  supervisor owns server process lifecycle.
- Online resource coordination is generic named integer lease admission through
  authority. Offline resource coordination is run-local and records that no
  cross-run guarantee existed.
- Interrupted stage attempts restart from scratch on resume.
- Terminal lifecycle states do not reopen through ordinary mutation.
- `SUBMITTED -> RUNNING` is allowed only when Loom regains active execution
  control after external scheduler acceptance.
- Imported offline runs become authority-owned truth with import provenance
  after accepted import.

Explicit deferrals:

- Hosted multi-tenant operations, authentication/authorization beyond trusted
  local metadata, high availability, distributed consensus, full online
  workflow scheduler, queues, worker daemons, full sweep execution semantics,
  remote artifact payload movement, cryptographic offline attestation,
  domain-specific equivalence, run bundles/exporters, and compatibility support
  for old implicit local-only runtime behavior.

Open design-review questions to triage after reset:

- Registry scope and file location for ordinary local projects, shared HPC
  allocations, and user-global managed services.
- Minimum v10 DB shape: stdlib SQLite behind the authority server only versus a
  backend interface with SQLite as the first implementation.
- Supervisor transport: existing stdlib manager, FastAPI/HTTP, minimal stdlib
  HTTP, or another protocol.
- Service restart and lease-generation policy.
- Offline import representation: replayed lifecycle transitions versus compact
  imported snapshot with import provenance.
- Evidence strength and artifact checksum requirements for accepted offline
  imports.
- Imported-run visibility in status, catalog, and diagnostics.
- CLI ownership and names for service lifecycle and offline-first/import flows.
- Fail-closed diagnostic and explicit restart command when a registry points to
  an unavailable service but a DB/artifact directory still exists.

## Design Decision Review Triage

Triage status:

- Started on 2026-05-11 after the context checkpoint. The confirmed
  functionality and behavior are stable inputs and should not be reopened unless
  the user explicitly asks.
- Repo evidence reviewed: v10 roadmap entry, v9-post implementation plan,
  `docs/structure.md`, `docs/features/run-store.md`,
  `docs/features/execution.md`, `docs/features/slurm.md`,
  `docs/features/sweeps.md`, current authority/service/coordination modules,
  CLI command modules, and `pyproject.toml`.
- Current user-facing decision batch: follow-up design-choice review complete;
  next stage is implementation-plan refinement.

Design-decision review queue:

| Decision | Classification | Why it matters | User feedback needed | Status |
| --- | --- | --- | --- | --- |
| Authority ownership boundaries and naming | recorded recommendation | Keeps runner, resolver, client, server, supervisor, repository, and coordinator responsibilities separate so v10 does not grow into an implicit scheduler or direct database API. | None. Repo evidence strongly supports the existing ports-and-adapters boundary. | confirmed |
| Shared online/offline authority resolution policy | recorded recommendation | Prevents per-entrypoint fallback behavior and keeps CLI, Python, workers, SLURM, diagnostics, and preflight consistent. | None. Functionality/behavior gate already confirmed strict online-first and explicit offline-first behavior. | confirmed |
| Service-owned private repository with SQLite as first backend | recorded recommendation | Determines persistence boundaries and dependency cost. Clients must never open the authority DB directly. | None for the first implementation default. The plan can revisit when a hosted or multi-tenant backend is needed. | confirmed |
| Supervisor transport and dependency policy | needs discussion | Affects health/readiness UX, dependency footprint, client protocol stability, and future hosted-service compatibility. | User selected FastAPI/HTTP for v10. | confirmed |
| Registry scope, file layout, and restart UX | needs discussion | Determines how independent commands find the same service without accidental cross-project sharing, and how users recover from stopped or stale services. | User confirmed the workspace-local registry and fail-closed restart model. | confirmed |
| Service restart, generation, and lease validity | recorded recommendation | Restart policy protects output commits and resource releases from stale controllers and workers after a service process restarts. | None. Repo lease/fencing patterns strongly support generation-based invalidation plus recovery. | confirmed |
| Authority-backed workspace coordination through the same server boundary | recorded recommendation | Avoids a second operational service while preserving the existing separation between per-run lifecycle and cross-run coordination facts. | None. Functionality/behavior gate already confirmed this direction. | confirmed |
| Offline evidence eligibility and equivalence strength | needs discussion | Determines whether import is strict enough to become authority truth without accidental legacy migration or weak artifact proof. | User confirmed v10-created manifests only and strong equivalence proof. | confirmed |
| Imported-run visibility in status, catalog, and diagnostics | recorded recommendation | Keeps imported truth inspectable without inventing a separate lifecycle source. | None. Read-model and diagnostic patterns already support source/provenance labeling. | confirmed |
| CLI command ownership for lifecycle, diagnostics, offline, and import flows | recorded recommendation | Keeps operational lifecycle commands distinct from existing backend diagnostics while preserving shared authority flags. | None unless the user wants to reopen command naming. | confirmed |
| Stage interruption and stale-plan representation | recorded recommendation | Avoids unnecessary status enum churn while preserving restart-from-scratch semantics through attempts, reasons, and recovery records. | None. Existing status model and v9-post constraints favor reason/provenance records over new durable statuses. | confirmed |
| Test and validation boundaries | recorded recommendation | Keeps default validation deterministic while still requiring service durability, concurrency, import, and failure-mode coverage. | None. Existing test markers and AGENTS checks give a clear default. | confirmed |

Recorded recommendations:

1. Keep authority ownership names and boundaries explicit:
   `AuthorityResolver` selects online/offline policy, `AuthorityClient` is the
   client-side protocol, `AuthorityServer` accepts/rejects lifecycle and
   coordination mutations, `AuthoritySupervisor` owns process lifecycle and
   registry metadata, and `AuthorityRepository` is private server persistence.
   `PipelineRunner` continues to orchestrate one run and request authority
   mutations; it must not start services as a hidden side effect.
   Alternatives rejected: runner-owned service startup, direct client DB access,
   authority-owned scheduling policy, and per-entrypoint authority resolution.
   Revisit trigger: a future roadmap version introduces a real
   `WorkflowScheduler` or hosted service operations.
2. Use a service-owned repository abstraction with standard-library SQLite as
   the first durable backend. The abstraction exists so PostgreSQL or another
   managed database can be added later, but v10 should not add a mandatory
   runtime dependency or expose SQL/schema details as public contract.
   Alternatives rejected: client-opened SQLite, making PostgreSQL mandatory in
   v10, DuckDB for authoritative writes, and public SQL tables. Debt accepted:
   SQLite is local/single-service-writer infrastructure, not hosted
   multi-tenant authority. Revisit trigger: production deployment needs
   concurrent hosted service operations or external DB administration.
3. On supervisor restart, use a new service generation and treat active leases
   from the previous generation as non-committable until renewed, failed, or
   recovered through authority. Persist run/stage/attempt/resource facts in the
   DB, but fail closed for stale worker/controller commits that cannot prove the
   current generation and fencing token. Alternatives rejected: preserving all
   leases blindly across restart, and silently allowing stale commits based only
   on old in-process state. Revisit trigger: a future HA/service-cluster design
   introduces stronger session recovery.
4. Put workspace coordination behind the same `AuthorityServer` boundary while
   retaining a distinct `WorkspaceCoordinator`/`WorkspaceCoordinationStore`
   protocol. Do not add a second resource supervisor service in v10.
   Alternatives rejected: runner-only resource pools, separate resource service,
   and scheduler policy embedded in authority persistence. Revisit trigger:
   future sweep or scheduler work proves the single server boundary is too
   coarse operationally.
5. Mark accepted offline imports with import provenance visible to status,
   catalog, diagnostics, and backend inspection, without making `imported` a new
   ordinary lifecycle state. Alternatives rejected: hiding import status in a
   private DB row, or creating a parallel imported-run catalog. Revisit trigger:
   users need query/filter semantics that provenance labels cannot support.
6. Keep `loom backend ...` for backend inspection/capability diagnostics and add
   `loom authority ...` for service lifecycle, registry, doctor/status, and
   offline import operations. Keep shared authority flags on mutating commands.
   Prefer a short explicit offline flag such as `--offline` or
   `--offline-first`, with final spelling chosen during implementation planning
   against existing CLI conventions. Alternatives rejected: putting process
   lifecycle under `loom backend`, and duplicating lifecycle commands in both
   groups. Revisit trigger: CLI review finds the new group conflicts with
   established user-facing vocabulary.
7. Preserve the existing stage status enum unless implementation evidence shows
   a real read-model need for `StageStatus.INTERRUPTED`. Represent interrupted
   and stale-plan details with attempt records, lifecycle reasons, recovery
   records, and diagnostics. Alternatives rejected: adding durable statuses
   solely for UI phases, and treating `STALE` as active lifecycle truth where a
   plan/reason record is enough. Revisit trigger: status/catalog consumers need
   stable first-class interrupted-stage filtering.
8. Keep validation local and deterministic by default. Add unit, contract, and
   integration coverage for the service repository, resolver policy, registry
   safety, restart/lease behavior, workspace coordination, and offline import.
   Keep real network, external service, HPC, and multi-host suites opt-in unless
   a deterministic local fixture can prove the behavior.

User-confirmed design decisions:

1. Use FastAPI/HTTP as the v10 supervisor and authority API transport.
   User feedback: selected FastAPI from the transport options. Rationale:
   FastAPI gives a clear operational endpoint model for liveness, readiness,
   health, capabilities, diagnostics, and runtime client calls. It also maps
   naturally to future managed-service or hosted-service deployments.
   Alternatives rejected: extending the current stdlib `BaseManager` transport
   as the product-facing supervisor API, and implementing a custom stdlib HTTP
   protocol in v10. Maintainability impact: introduces runtime dependency and
   API routing concerns, so implementation planning must isolate transport
   handlers from authority mutation logic and keep request/response models
   explicit. Extensibility impact: better future compatibility for external
   tools, operational checks, and managed-service evolution. Debt and revisit
   trigger: dependency cost is accepted for v10; revisit if FastAPI materially
   complicates packaging, optional-dependency policy, or deterministic local
   validation.
2. Use a workspace-local registry for ordinary local services, with explicit
   allocation-scoped and user-global discovery only when configured.
   Selected approach: ordinary project services record registry metadata under
   a workspace-local path such as `.loom/authority/registry.json`; service DB
   and service-owned artifacts live under an explicit supervisor start
   directory; allocation-scoped services use an explicit allocation registry
   path; user-global services are opt-in through endpoint/reference/environment
   configuration rather than default discovery. Stale registry behavior fails
   closed before lifecycle mutation with diagnostics that identify unavailable,
   stale, incompatible, or generation-mismatched authority and point to explicit
   commands such as `loom authority status` and `loom authority restart
   --state-dir ...`. Alternatives rejected: user-global discovery by default,
   silent service restart from runtime commands, and treating a present DB path
   as permission for clients to mutate state directly. Maintainability impact:
   keeps discovery deterministic and project-scoped while making supervisor
   ownership visible. Extensibility impact: leaves room for allocation and
   managed-service profiles without changing the default local model. Debt and
   revisit trigger: users must intentionally start/configure authority; revisit
   if repeated local UX friction outweighs the safety benefit.
3. Accept offline imports only from v10-created offline evidence manifests, with
   strong equivalence proof.
   User feedback: confirmed the recommended default and rejected best-effort
   legacy/local-directory import. Selected approach: offline-first execution
   writes versioned evidence manifests; import accepts only manifests that prove
   the execution plan, config/provenance, stage graph/order, input
   fingerprints, attempt terminal states, output refs, artifact checksums and
   sizes when local payloads exist, failure/log refs, runtime metadata, and
   schema versions. Import rejects incomplete, conflicting, stale, unsafe, or
   schema-incompatible evidence. Alternatives rejected: best-effort import of
   older local materialization directories, import based only on plan/input
   fingerprints, and accepting missing payload/checksum evidence when payloads
   are expected to exist locally. Maintainability impact: keeps the import
   contract explicit and avoids turning historical local files into an
   accidental authority migration layer. Extensibility impact: leaves room for
   future import adapters or legacy migration tools without weakening the v10
   authority contract. Debt and revisit trigger: old local run directories are
   not importable through v10 offline import; revisit only if a future roadmap
   explicitly designs legacy migration.

## Design Choice Follow-Up Review

Follow-up status:

- Started after implementation-plan draft creation because the earlier notes
  marked design decision review complete too aggressively.
- Confirmed functionality and behavior remain stable inputs.
- The current implementation plan should be refined from these confirmed
  decisions before plan quality gate review.

Follow-up triage:

| Decision | Classification | Why it matters | User feedback needed | Status |
| --- | --- | --- | --- | --- |
| Transport choice: FastAPI/HTTP | already confirmed | Affects dependency footprint, health/readiness UX, and hosted-service compatibility. | None unless user reopens it. | confirmed |
| Registry scope: workspace-local default with explicit allocation/global references | already confirmed | Affects discovery safety and accidental cross-project sharing. | None unless user reopens it. | confirmed |
| Offline import eligibility: v10 evidence manifests only | already confirmed | Determines whether import can safely create authority truth. | None unless user reopens it. | confirmed |
| Authority boundary and naming | recorded recommendation | Keeps resolver, client, server, supervisor, repository, coordinator, and runner responsibilities separate. | None. Repo evidence strongly supports this separation. | recorded |
| Private SQLite repository with backend port | recorded recommendation | Keeps DB details private while leaving room for future managed repositories. | None. SQLite is the minimal local durable backend. | recorded |
| Service generation and stale lease policy | recorded recommendation | Prevents stale workers/controllers from committing after restart. | None unless user wants different restart recovery semantics. | recorded |
| State directory ownership and default placement | needs discussion | Determines whether `loom authority start` is explicit but slightly verbose, or convenient but easier to confuse with hidden local state. | User selected explicit state directory only. | confirmed |
| Offline import write model | needs discussion | Determines whether imported runs replay lifecycle events, write compact accepted snapshots, or use a hybrid provenance-preserving import. | User selected hybrid with replay-level information. | confirmed |
| Import collision policy | needs discussion | Determines how import behaves when a target run URI already exists or overlaps with authority state. | User selected strict reject for now. | confirmed |
| Resource lease admission behavior | needs discussion | Determines whether resource pressure fails immediately, waits with timeout, or records waitable decisions for future schedulers. | User confirmed hybrid: default fail fast, explicit bounded wait/timeout policy, and structured accepted/rejected/blocked decisions. | confirmed |
| Schema migration policy for the private authority DB | recorded recommendation | Determines v10 durability compatibility behavior. | None. Since v10 creates the first private service DB, fail loudly on unsupported schemas and add migrations only when schema changes later. | recorded |
| Imported-run lifecycle visibility | recorded recommendation | Avoids inventing an `imported` lifecycle state while keeping provenance visible. | None unless user wants first-class imported filtering. | recorded |

Follow-up discussion batches:

1. State directory ownership/default placement, offline import write model, and
   import collision policy. Confirmed on 2026-05-11.
2. Resource lease admission behavior. Confirmed on 2026-05-11.
3. Final design readback and implementation-plan refinement notes. Recorded on
   2026-05-11.

User-confirmed follow-up design decisions:

1. Require explicit supervisor state directories in v10.
   User feedback: selected "explicit only". Selected approach:
   `loom authority start` requires a state directory argument or equivalent
   explicit configuration; runtime commands still never create or infer an
   authority state directory. Workspace registry records may point to the
   selected state directory after the supervisor starts, but the registry does
   not define a hidden default location for new service state. Alternatives
   rejected: workspace-local default state directory and profile-based
   workspace defaults. Maintainability impact: keeps service-owned DB/artifact
   state visibly operator-owned and avoids confusing registry discovery with
   implicit persistence creation. Extensibility impact: leaves allocation and
   managed-service profiles free to define their own explicit state references
   later. Debt and revisit trigger: local startup is more verbose; revisit only
   if v10 usage shows explicit state-dir selection is a dominant friction point.
2. Use a hybrid offline import write model with replay-level information.
   User feedback: selected "hybrid", with the additional requirement that the
   import preserve replay-level information. Selected approach: an accepted
   import writes authoritative current run/stage/attempt/output/artifact facts
   plus import provenance, and also persists an import evidence/audit timeline
   detailed enough to inspect the offline lifecycle at replay-level granularity.
   The authority must not pretend those offline events were originally
   authority-controlled online mutations, but it must retain enough ordered
   evidence for audit, diagnostics, and later replay-style analysis.
   Alternatives rejected: pure replay as if the authority originally observed
   each event, and compact final snapshot without detailed offline event
   history. Maintainability impact: separates accepted authority truth from
   evidence provenance while preserving detailed auditability. Extensibility
   impact: leaves room for future replay tools, richer import verification, and
   timeline views without weakening authority truth. Debt and revisit trigger:
   import schema is larger; revisit if the audit timeline duplicates too much
   data or becomes hard to query.
3. Use strict import collision rejection in v10.
   User feedback: selected "strict reject for now". Selected approach: if the
   target run URI or equivalent identity already exists in authority state, the
   import is rejected with structured diagnostics and no mutation. V10 may
   define the import policy model so future replace/fork behaviors are possible,
   but it should not implement overwrite or fork-on-collision behavior.
   Alternatives rejected: explicit replace and automatic fork/new URI import.
   Maintainability impact: keeps the first import transaction atomic and easy to
   reason about. Extensibility impact: future migration or repair workflows can
   add collision strategies without changing strict default semantics. Debt and
   revisit trigger: users must choose a clean target authority/run identity;
   revisit when a roadmap version adds migration, repair, or archival import.
4. Use hybrid resource lease admission behavior.
   User feedback: confirmed the recommended hybrid model. Selected approach:
   resource admission defaults to fail fast when capacity is unavailable, but
   callers may explicitly provide a bounded wait/timeout policy. The authority
   returns structured admission decisions that can distinguish accepted with
   leases, rejected with reasons, and blocked/waitable with diagnostics. V10
   runners may wait only when the caller selected a bounded wait policy; v10
   does not add an unbounded queue, priority scheduler, or global placement
   policy. Alternatives rejected: always fail fast, always wait, and returning
   waitable decisions without runner support for explicit bounded waiting.
   Maintainability impact: keeps default execution deterministic while making
   wait behavior explicit and testable. Extensibility impact: preserves a
   scheduler-ready request/decision model for later workflow scheduler work.
   Debt and revisit trigger: no fairness, priority, or distributed placement
   semantics are implemented; revisit when a future scheduler roadmap needs
   queued admission policy.

Final design readback:

- V10 uses FastAPI/HTTP as an isolated authority transport.
- Authority is owned through explicit ports: resolver, client, server,
  supervisor, repository, and workspace coordinator.
- The private service repository starts with SQLite behind the server only.
- Supervisor state directories are explicit only; registry records discover an
  already-started authority but do not create hidden default service state.
- Registry discovery is workspace-local by default, with allocation/global
  references only when explicitly configured.
- Service restart uses generation/fencing to prevent stale lease commits.
- Workspace coordination moves behind the authority server boundary.
- Resource leases are generic named integer leases with default fail-fast
  admission and explicit bounded wait/timeout support.
- Existing `direct_database` authority configuration is rejected/reserved for
  v10 runtime mutation with diagnostics; it is not a compatibility fallback.
- Offline import accepts only v10-created evidence manifests.
- Offline import writes accepted authority facts plus import provenance and
  replay-level evidence/audit information.
- Offline import strictly rejects existing target run identities in v10.
- Existing deferred-finalization envelopes remain a separate weaker profile and
  are not converted into v10 offline import evidence.
- Imported-run visibility uses provenance/read-model labeling rather than a new
  ordinary lifecycle state.

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
  and runtime clients. FastAPI/HTTP is the selected v10 transport; dependency
  cost is accepted and must be isolated behind the transport boundary.
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

Resolved pre-triage design questions:

These were captured before the formal design-decision review queue and have now
been resolved or covered by recorded recommendations.

1. Offline import requires v10-created evidence manifests.
2. Equivalent import requires strong plan, config/provenance, stage, input,
   output, artifact, failure/log, runtime metadata, and schema-version evidence.

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
  V10 should use a hybrid write model: accepted authority facts plus import
  provenance and replay-level offline evidence/audit information. The accepted
  result becomes authority-owned truth, but the import must not pretend offline
  events were originally authority-observed online mutations.

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

Phase-shaping user feedback:

- The initial five-to-six phase shape is too coarse for v10. Each coarse phase
  contains important design and implementation choices that should receive a
  focused phase plan and review. The implementation plan should therefore use a
  larger number of smaller phases and should not merge adjacent phases merely
  for convenience.

Expanded candidate phases for the future implementation plan:

1. **Authority Mode And Resolver Contracts**
   - Define online/offline mode records, authority-resolution outcomes,
     failure-closed diagnostics, shared config/env/CLI inputs, and strict
     no-implicit-start policy. No server, DB, or runtime caller migration yet.
2. **Authority Client And Server Protocol Models**
   - Define transport-independent request, response, acknowledgement, rejection,
     revision, capability, readiness, and error-envelope models used by the
     FastAPI layer and tests.
3. **FastAPI Transport Skeleton**
   - Add the FastAPI application boundary, route ownership split between
     operational supervisor routes and authority mutation routes, dependency
     isolation, local deterministic test fixture, and health/readiness/liveness
     stubs without durable lifecycle mutation.
4. **Private Repository Schema And Versioning**
   - Add the service-owned SQLite repository foundation, private schema helpers,
     schema version checks, transaction wrapper, generation metadata, and tests
     proving clients cannot treat the DB as a public API.
5. **Run Lifecycle Repository**
   - Implement persistent run admission, run transitions, controller leases,
     snapshots, audit events, cleanup/recovery records, and conformance coverage
     at repository level only.
6. **Stage Lifecycle Repository**
   - Implement persistent stage transitions, attempt allocation, stage leases,
     submitted-operation records, output commits, artifact facts, fencing, and
     stale-commit rejection at repository level only.
7. **Authority Server Mutation API**
   - Wire the repository into the FastAPI authority routes and client protocol,
     including accepted/rejected mutation acknowledgements, capability reporting,
     timeout/error mapping, and conformance against the service boundary.
8. **Workspace Registry Records**
   - Implement workspace-local registry records under `.loom/authority/`,
     atomic registry updates, redacted metadata, workspace/generation checks,
     allocation-scoped registry hooks, and stale/unavailable/incompatible
     registry diagnostics. No process lifecycle commands yet.
9. **Supervisor Lifecycle Commands**
   - Implement explicit `loom authority start`, `status`, `doctor`, `stop`, and
     `restart` behavior with FastAPI health/readiness checks, required explicit
     supervisor state directory selection, service generation handling, and
     fail-closed restart guidance.
10. **Strict Resolver And Factory Adoption**
    - Change shared Python factories and CLI authority resolution to use the
      new resolver policy: configured endpoint or registry connects and
      health-checks; missing authority fails by default; offline-first is an
      explicit resolver outcome; `direct_database` is rejected/reserved for v10
      runtime mutation with diagnostics. Do not migrate every runtime entrypoint
      yet.
11. **Python Runner And `loom run` Online Path**
    - Convert `PipelineRunner`, `run_pipeline`, Python execution helpers, and
      `loom run` online execution to the strict resolver and service-backed
      authority client while preserving runner-owned DAG orchestration.
12. **Local/Subprocess Worker Continuation Paths**
    - Convert subprocess workers, `loom stage run`, `loom stage-job run`, and
      `loom prepared-run continue` to carry and enforce authority references,
      generation/fencing facts, lease renewal/revalidation, and fail-closed
      mutation behavior.
13. **SLURM Live Operation Paths**
    - Convert SLURM live submission, generated handoff commands, scheduler
      status observation, cancellation, and continuation behavior to the shared
      authority resolver and service-backed mutation policy, rejecting
      `direct_database` as a v10 live-worker mutation profile and preserving
      deferred-finalization as a distinct weaker profile rather than an offline
      import input.
14. **Diagnostics, Preflight, And Read-Only Source Labeling**
    - Update backend diagnostics, preflight, status/catalog-related read models,
      and read-only local inspection surfaces to report selected authority,
      registry source, DB/service profile, capabilities, online/offline policy,
      and whether displayed state is authoritative service truth or local
      materialized/evidence state.
15. **Workspace Coordination Service API**
    - Bring `WorkspaceCoordinationStore` behavior behind the authority server:
      workspace/sweep records, trial references, counters, non-resource leases,
      run URI references, recovery scans, capability diagnostics, and
      conformance against the service boundary. Existing resource
      limit/resource lease protocol methods should report unsupported capability
      until Phase 16.
16. **Resource Leases And Scheduler-Ready Admission**
    - Add generic named integer resource limits and leases through
      `AuthorityClient`/`WorkspaceCoordinator`, runner resource admission before
      launch, release/failure/recovery behavior, supported service-backed
      implementations for existing resource methods, and scheduler-ready
      request/decision value objects without implementing a global scheduler.
17. **Offline Evidence Writer**
    - Add explicit offline-first execution mode, run-local resource coordination
      evidence, versioned offline evidence manifests, local event/audit logs,
      required provenance/fingerprint/checksum capture, and diagnostics that
      state no authority truth exists yet. Do not convert deferred-finalization
      envelopes into offline evidence.
18. **Offline Import Transaction**
    - Add the import API/CLI, strong equivalence checker, conflict/collision
      policy, atomic authority import transaction, import provenance visible in
      status/catalog/diagnostics, and accepted/rejected import coverage. Do not
      import deferred-finalization envelopes.

Phase-boundary constraints:

- Each phase should have its own phase execution plan with design impact,
  future compatibility, alternatives rejected, debt, and suite obligations.
- Adjacent phases may be split further after source inventory if a phase still
  crosses too many design boundaries. They should be merged only with a clear
  reviewability reason recorded in the implementation plan.
- Runtime migration phases must preserve the hard rule that no converted
  mutating path keeps the old implicit local lifecycle mutation behavior.
- FastAPI dependency and packaging details belong in the transport phase and
  must be visible in the implementation plan's dependency/debt discussion.
- Offline import phases must not broaden into historical local-run migration.

Phase-shaping confirmation:

- The user confirmed the expanded 18-phase shape on 2026-05-11 and wants the
  implementation plan to preserve smaller review units for design-heavy v10
  work.

## Open Questions

- Final CLI spelling for offline-first mode and import commands should be chosen
  during implementation planning after checking existing CLI conventions.
- Phase execution plans may split any v10 phase further if source inventory
  shows the phase still crosses too many review boundaries.

## Handoff Notes

Implementation-plan draft status:

- User confirmed comprehensive implementation-plan drafting on 2026-05-11.
- Draft created at `docs/implementation-plans/implementation-plan-v10.md`.
- Design-choice follow-up completed on 2026-05-11.
- Implementation-plan refinement completed on 2026-05-11.
- Initial `loom_plan_reviewer` quality gate review found three blocking issues:
  Phase 15/16 resource-lease boundary, deferred-finalization disposition, and
  `direct_database` disposition. A bounded refinement pass addressed those
  findings on 2026-05-11.
- Confirmation review passed on 2026-05-11 with no blocking findings.
- Next workflow step is Phase 1 selection and phase execution planning.

Implementation-plan draft inputs:

- Confirmed v10 outcome: DB-backed FastAPI authority server, explicit
  supervisor and workspace-local registry, strict online/offline resolver
  policy, service-backed workspace coordination, generic resource leases, and
  true offline import from v10-created evidence manifests only.
- Confirmed design decisions: ports-and-adapters authority ownership; FastAPI
  transport; service-owned private SQLite repository with a backend abstraction;
  generation-based restart/lease invalidation; workspace-local registry with
  fail-closed stale-service diagnostics; `loom authority ...` for lifecycle and
  import operations; explicit supervisor state directories; hybrid resource
  admission; `direct_database` rejected/reserved for v10 runtime mutation;
  deferred finalization remains separate from offline import; imported-run
  provenance and replay-level evidence visible through read models; no
  historical local-run import through v10 offline import.
- Confirmed phase shape: 18 small phases covering resolver contracts, protocol
  models, FastAPI skeleton, repository schema, run lifecycle, stage lifecycle,
  mutation API, registry records, supervisor commands, resolver/factory
  adoption, online `loom run`, worker continuations, SLURM live paths,
  diagnostics/read labeling, workspace coordination, resource leases, offline
  evidence writer, and offline import transaction.

Plan-quality-gate risks:

- FastAPI adds runtime dependency and packaging/test-surface debt that must be
  justified in the implementation plan.
- Runtime migration touches many entrypoints; implementation planning must keep
  phases small and preserve no-implicit-local-authority behavior as each path is
  converted.
- Service-owned SQLite must not be confused with client-opened SQLite authority.
- Existing direct-database configuration must not remain a live mutation
  compatibility path.
- Existing coordination resource lease methods must have a clear unsupported
  Phase 15 state and supported Phase 16 state.
- Deferred-finalization envelopes must not be confused with true offline import
  evidence.
- Offline import must not become a legacy migration path or weaken authority
  equivalence guarantees.
- Residual implementation risk from confirmation review: Phase 15 must keep
  service-backed coordination conformance clear when resource methods are
  unsupported until Phase 16, because current local coordination tests exercise
  resource-capable protocol methods.

Assumptions to carry forward:

- Local `develop` contains the completed v9-post service baseline.
- Default validation should remain deterministic and local; external network,
  real HPC, and multi-host checks stay opt-in unless a local fixture can prove
  the behavior.
- Implementation planning should verify current source paths before naming new
  public APIs or final CLI flags.

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
