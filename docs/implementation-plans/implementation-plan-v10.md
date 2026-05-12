# Implementation Plan v10: DB-Backed Authority Supervisor And Offline Import

## Metadata

- Status: refined draft
- Source planning notes: `docs/implementation-plans/roadmap-v10-planning-notes.md`
- Draft pass: complete on 2026-05-11 from confirmed roadmap v10 planning notes
- Refine pass: complete on 2026-05-11 after design-choice follow-up
- Design-choice review: complete after follow-up on 2026-05-11; refinement
  should preserve explicit state directories, hybrid replay-level offline
  import, strict import collision rejection, and hybrid resource admission
- Plan quality gate: passed on 2026-05-11 after one refinement pass and
  confirmation review
- Phase work status: Phase 15 merged; Phase 16 pending

Related artifacts and references:

- `docs/implementation-plans/implementation-roadmap.md`
- `docs/implementation-plans/implementation-plan-v9-post.md`
- `docs/structure.md`
- `docs/features/run-store.md`
- `docs/features/slurm.md`
- `docs/features/sweeps.md`
- `src/loom/pipeline/stores/service_authority.py`
- `src/loom/pipeline/stores/authority.py`
- `src/loom/pipeline/stores/coordination.py`
- `src/loom/pipeline/stores/sqlite_authority.py`
- `src/loom/pipeline/stores/sqlite_coordination.py`
- `src/loom/config.py`
- `src/loom/cli/authority.py`
- `src/loom/cli/backend.py`
- `src/loom/cli/main.py`

## Goal

Implement v10 as a durable, service-backed authority system for Loom: a DB-backed
FastAPI authority server with explicit supervisor lifecycle, workspace-local
registry discovery, strict online/offline resolver policy, service-backed
workspace coordination, generic resource leases, and true offline import from
versioned v10-created evidence manifests.

The outcome should replace the current endpoint-less co-located runtime default
with explicit authority selection for mutations, while preserving a clear
offline-first path that never pretends local evidence is authoritative until it
has been imported through the authority service.

## Context

The current post-v9 baseline has strong boundary pieces but still leaves major
runtime authority gaps:

- `AuthorityConfig()` can default to a co-located local service, which makes
  writes appear service-backed while still allowing implicit startup in normal
  execution paths.
- Explicit service endpoints can be connected and health-checked, but the local
  service core is not yet the durable FastAPI supervisor envisioned by the
  roadmap.
- `SQLitePerRunAuthorityStore` is documented as private transitional storage
  and unsupported as a runtime backend, but the durable service repository is
  not yet implemented.
- Workspace coordination is still a separate store boundary, not part of the
  same authority service contract.
- SLURM deferred finalization can capture weaker local state, but there is no
  versioned evidence manifest with a strict equivalence checker and atomic
  import transaction.
- Diagnostics and read-only inspection surfaces do not consistently label
  whether state came from authoritative service truth, a registry record, or
  local offline evidence.

v10 closes those gaps by making the authority service the only online mutation
path, making offline execution explicit, and treating offline evidence import as
a first-class transaction with strong proof requirements.

## Desired Outcome

By the end of v10:

- Online runtime mutations go through a FastAPI-backed `AuthorityClient` and a
  service-owned private repository.
- The service has an explicit supervisor lifecycle: `loom authority start`,
  `status`, `doctor`, `stop`, and `restart`.
- Supervisor startup requires an explicit state directory; v10 does not infer a
  hidden workspace-local service DB/artifact location.
- Workspaces have a local allocation registry under `.loom/authority/` that
  records endpoint and generation facts without making stale records safe to
  reuse.
- Resolver policy fails closed: no hidden endpoint-less service startup in
  normal mutation paths, no implicit DB mutation by clients, and explicit
  offline-first mode when no authority is selected.
- Workspace coordination state, counters, leases, sweeps, trial references, and
  recovery scans are served through the same authority boundary.
- Generic named integer resource leases are available through authority and
  coordinator abstractions, enough for scheduler-ready local admission without
  introducing a global scheduler. Capacity exhaustion fails fast by default;
  explicit caller-selected wait/timeout policy can perform bounded waiting.
- Offline execution writes versioned evidence manifests with enough proof to
  import accepted runs into the authority service atomically.
- Accepted imports write authority facts plus import provenance and
  replay-level offline evidence/audit history.
- Import rejects incomplete, conflicting, stale, unsafe, schema-incompatible, or
  non-v10 evidence rather than performing best-effort reconstruction, and v10
  strictly rejects target run collisions rather than replacing or forking.
- Read models, status, preflight, backend diagnostics, catalog, and import
  summaries label state source clearly.

## Non-Goals

- Hosted multi-tenant operation, authentication, authorization, or TLS policy.
- A global scheduler, queueing worker daemon, or cross-workspace scheduling
  service.
- Fairness, priority, unbounded queueing, or distributed placement for resource
  admission.
- Direct-database authority as a supported v10 runtime mutation profile.
- Full sweep orchestration redesign beyond preserving and service-backing
  existing coordination semantics.
- Converting existing deferred-finalization envelopes into v10 offline import
  manifests.
- Remote artifact transfer, object-store persistence contracts, or distributed
  payload movement.
- Cryptographic attestation of offline evidence beyond recorded fingerprints,
  checksums, sizes, schema versions, and provenance facts.
- Domain-specific equivalence rules for research outputs.
- Best-effort import of pre-v10 local run directories or historical ad hoc
  evidence.
- Offline import replacement, fork-on-collision, or repair workflows.
- Implicit workspace-local supervisor state-directory defaults.
- Making the SQLite schema a public API.
- Direct client access to the private authority DB.
- Changing the existing stage status enum unless source-level implementation
  proves that the current enum cannot represent an offline or interrupted fact
  safely.

## Constraints

- Keep Loom domain-neutral.
- Preserve source-tree layout and boundaries described in `docs/structure.md`.
- Treat authored configs as trusted project code.
- Do not introduce heavyweight runtime dependencies without an explicit design
  reason. FastAPI is accepted for v10 transport, but it must be isolated behind
  transport/server boundaries.
- The private repository can start with SQLite, but all client-facing behavior
  must go through authority protocols rather than SQL details.
- Normal online mutation paths must not implicitly start an authority service.
- Existing `direct_database` authority configuration must be treated as an
  unsupported/reserved runtime mutation profile in v10 with explicit
  diagnostics, not as permission for clients or workers to open the private
  authority DB.
- Supervisor lifecycle commands must require explicit state-directory selection
  and report the selected state directory in diagnostics.
- Offline mode must be explicit and must produce evidence, not authority truth.
- Offline import must preserve replay-level evidence history without
  representing offline events as originally authority-observed online
  mutations.
- Test obligations must favor deterministic local tests by default. External
  service, process, and scheduler coverage should be opt-in when it is slow,
  flaky, or environment-dependent.
- Phase execution plans must confirm exact current source paths before editing;
  this plan intentionally sets durable boundaries and acceptance criteria, not
  exhaustive patch instructions.
- Before each phase PR is prepared, run `make validate-pr` and `make
  test-summary`, or record why either command could not run.

## Design Principles

- **Authority is a service boundary, not a file path.** Runtime clients may know
  endpoint and generation facts, but only the service owns durable mutation.
- **Fail closed before convenience.** Missing, stale, incompatible, or unhealthy
  authority references should produce actionable diagnostics instead of starting
  hidden services or writing local fallback state.
- **Keep offline honest.** Offline execution can be useful and reproducible, but
  it remains local evidence until an authority import transaction accepts it.
- **Ports and adapters first.** Resolver, client, server, supervisor,
  repository, and coordination responsibilities should remain separable so
  later transports or repositories can be added without rewriting runners.
- **Private persistence, public protocol.** SQLite details are allowed inside
  the service; protocol models and read views are the compatibility surface.
- **Small phases with explicit decisions.** v10 deliberately uses many smaller
  phases so design choices are reviewed near their implementation point.
- **Use existing concepts where they fit.** Preserve current run, stage, attempt,
  operation, artifact, SLURM, and coordination language unless a phase proves a
  new concept is needed.

## Key Design Choices

- Use FastAPI as the local authority HTTP transport.
- Keep protocol models transport-independent so the FastAPI layer is an adapter,
  not the core authority API definition.
- Use a service-owned private SQLite repository for v10 durability.
- Include a backend abstraction inside the service repository layer, but avoid
  exposing SQL tables or paths as client API.
- Use a workspace-local registry under `.loom/authority/` for allocation-scoped
  endpoint and generation records.
- Require explicit supervisor state directories for authority lifecycle commands;
  v10 runtime commands and supervisor commands do not infer or create hidden
  default service state.
- Treat registry entries as hints that must be validated by health/readiness and
  workspace/generation checks.
- Split online resolver outcomes from offline resolver outcomes so offline-first
  execution is a selected mode, not a fallback accident.
- Preserve runner-side DAG orchestration; the authority server owns mutation,
  leases, fencing, and read models, not stage scheduling policy.
- Bring workspace coordination behind the authority server after core run/stage
  mutation is already service-backed.
- Add generic resource leases after workspace coordination is service-backed, so
  admission can be implemented without introducing a global scheduler.
- Resource admission defaults to fail fast when capacity is unavailable, but
  callers may explicitly request bounded waiting with a timeout. Admission
  decisions should still model accepted, rejected, and blocked/waitable
  outcomes.
- Write offline evidence before import support, so the import phase can validate
  real v10 evidence shape rather than inventing it in reverse.
- Represent imported runs through provenance/read-model fields and a
  replay-level import evidence/audit timeline rather than a new lifecycle state
  unless source-level review proves a lifecycle state is needed.
- Reject offline import collisions by default in v10; future import policy
  models may reserve replace or fork behavior, but v10 import should not mutate
  an existing target run.

## Conflicts And Tradeoffs

- **FastAPI dependency vs. dependency minimalism:** FastAPI is accepted because
  the user selected it for v10 and it gives Loom a conventional local HTTP
  service boundary. The dependency must be justified, isolated, and tested
  without spreading framework objects into core runtime code.
- **SQLite-first repository vs. future backends:** SQLite is the right local
  durability default, but it should remain private to the service. Repository
  interfaces and protocol conformance tests carry future compatibility.
- **Fail-closed resolver vs. local convenience:** v10 intentionally makes some
  formerly convenient local paths require explicit `loom authority start` or
  explicit offline mode. Better diagnostics are required to keep this usable.
- **Many smaller phases vs. workflow overhead:** Eighteen phases add planning
  overhead, but the design has durable API, persistence, coordination,
  scheduler, and offline-import decisions. Smaller phases make those decisions
  reviewable.
- **Strict offline import vs. legacy usability:** Rejecting legacy or incomplete
  evidence means some old local data cannot be imported. This is intentional to
  avoid corrupting authority truth.
- **Explicit state directories vs. local convenience:** Requiring explicit
  supervisor state directories makes service-owned DB/artifact state clear, but
  makes local startup more verbose. Registry discovery is intentionally not a
  hidden persistence default.
- **Hybrid import detail vs. schema size:** Preserving replay-level offline
  evidence alongside accepted authority facts improves auditability, but it
  makes import persistence broader than a compact snapshot.
- **Bounded waiting vs. scheduler creep:** Resource admission supports explicit
  wait/timeout behavior, but v10 must not grow an unbounded queue, priority
  scheduler, or global placement policy.
- **Service-backed coordination vs. runner simplicity:** Moving coordination
  behind the service improves consistency, but it requires careful transition
  so existing sweep and trial behavior remains understandable.

## Maintainability Assessment

The plan is maintainable if phases preserve narrow ownership boundaries:

- Resolver policy lives outside transports and repositories.
- Protocol models are stable and independently testable.
- FastAPI routes adapt protocol calls instead of becoming business logic.
- Repository tests prove durability and fencing behavior without forcing CLI or
  runner involvement.
- Runtime migrations happen only after server, repository, registry, and
  supervisor contracts exist.
- Diagnostics and read models label source and authority policy consistently.

The biggest maintainability risks are framework leakage, SQL leakage, resolver
special cases, and duplicated online/offline mutation logic. Phase execution
plans must explicitly watch for those risks.

## Extensibility Assessment

v10 should leave room for:

- alternate authority transports;
- alternate service repositories;
- richer scheduler admission;
- hosted authority processes;
- future auth/TLS policy;
- richer import provenance;
- stronger artifact verification;
- additional resource classes;
- richer sweep orchestration.

The primary extensibility mechanism is stable protocol and repository ports, not
premature generalized infrastructure. Each phase should add only the extension
points needed for the behavior it implements.

## Technical Debt Ledger

| Debt | Accepted For v10 Because | Revisit Trigger |
| --- | --- | --- |
| FastAPI becomes a runtime dependency | User selected HTTP/FastAPI as the authority transport and the service boundary needs a conventional local server | Framework objects leak into core runtime modules, packaging impact is larger than expected, or tests require network-heavy setup |
| SQLite is the first durable authority repository | Local supervisor durability is the immediate need and SQLite is already consistent with existing private store direction | Hosted authority, multi-writer service operation, or remote deployment becomes a roadmap goal |
| Registry is workspace-local and allocation-scoped | It gives deterministic local discovery without a user-global service manager | Users need safe cross-workspace discovery or multi-authority management |
| No legacy/offline best-effort import | Authority truth requires strong equivalence and provenance guarantees | A later migration feature defines a separate, explicitly weaker conversion workflow |
| Explicit supervisor state directories are required | Avoids hidden service DB/artifact creation and keeps operator ownership clear | Local UX friction dominates v10 usage or a later profile system defines safe explicit defaults |
| Offline import stores replay-level evidence plus accepted facts | Keeps imported authority truth honest while preserving audit detail | Import schema becomes too duplicated or a later replay tool needs a different event projection |
| Import collisions are strict rejects in v10 | Keeps the first import transaction atomic and avoids accidental overwrite/fork semantics | A future migration, repair, or archival workflow defines explicit collision strategies |
| Existing `direct_database` authority profile is rejected/reserved for runtime mutation | v10 makes service protocol, not DB files, the authority contract | A future managed deployment explicitly defines a direct database protocol with safety guarantees |
| Deferred finalization remains a separate weaker profile | Existing envelopes reconcile authority-known submitted attempts and are not true offline runs | A later roadmap unifies deferred envelopes with offline evidence under a designed compatibility contract |
| No global scheduler in v10 | Resource leases and runner admission are enough for scheduler-ready behavior | Cross-run prioritization, queueing, or distributed placement becomes required |
| Resource admission supports explicit bounded waiting only | Shared resource limits need optional waiting, but default execution should remain deterministic | Users need fairness, priority, unbounded queueing, or distributed placement |
| Exact CLI wording may evolve in phase plans | Source inventory may reveal existing command names and parser constraints | CLI phase finds ambiguity that affects user-facing compatibility |
| Stage status enum is preserved initially | Existing states may be sufficient when offline provenance is separated from lifecycle | Implementation proves interrupted/offline/imported facts cannot be represented without semantic overload |

## Plan Quality Gate

Status: passed on 2026-05-11.

Before any phase execution begins, this plan must receive a `loom_plan_reviewer`
review covering:

- maintainability;
- extensibility;
- future compatibility;
- conflicting design choices;
- accepted technical debt and revisit triggers;
- test strategy;
- phase scope boundaries;
- reviewability.

If the review finds blocking issues, perform one refinement pass and one
confirmation review. If blocking findings remain after the allowed plan quality
gate loop, mark this plan blocked instead of starting phase work.

Implementation phases may begin after normal phase selection and execution-plan
creation.

Review history:

- Initial `loom_plan_reviewer` review on 2026-05-11 did not pass. Blocking
  findings: unclear Phase 15/16 resource-lease boundary; deferred-finalization
  replacement/retirement not scoped; existing `direct_database` authority
  surface not resolved.
- Refinement pass on 2026-05-11 clarified that Phase 15 reports existing
  resource methods as unsupported until Phase 16, Phase 16 implements
  resource-limit/resource-lease accounting and runner admission,
  deferred-finalization remains a separate weaker profile outside offline
  import, and `direct_database` is rejected/reserved for v10 runtime mutation.
- Confirmation review on 2026-05-11 found no blocking findings. Residual
  implementation risk: Phase 15 must distinguish service-backed coordination
  conformance that reports resource methods unsupported until Phase 16 from
  existing resource-capable local coordination tests.

## Phased Implementation

### Phase 1: Authority Mode And Resolver Contracts

- Status: merged
- Branch: `codex/authority-mode-resolution`
- PR: https://github.com/samcantrill/loom/pull/119

**Goal**

Define the authority selection contract that all later online/offline behavior
will use.

**Scope**

- Add explicit records for online authority mode, offline-first mode, resolver
  inputs, resolver outcomes, and failure diagnostics.
- Cover CLI/config/environment inputs shared by future runtime, supervisor, and
  diagnostics paths.
- Encode the strict no-implicit-start policy for mutation-capable online paths.
- Classify existing `direct_database` authority configuration as an
  unsupported/reserved v10 runtime mutation profile with diagnostics.
- Distinguish unavailable authority, stale registry, incompatible generation,
  unhealthy service, and explicit offline selection.
- Preserve existing service APIs while introducing the new contracts.

**Out Of Scope**

- FastAPI server or client implementation.
- SQLite durable repository.
- Runtime caller migration.
- Registry file persistence.
- Supervisor lifecycle commands.

**Acceptance Criteria**

- Resolver contract types are importable from stable non-transport modules.
- Missing authority references fail closed for online mutation mode.
- `direct_database` authority configuration is parsed only far enough to produce
  a clear unsupported/reserved-profile diagnostic for v10 runtime mutation.
- Explicit offline-first resolution succeeds with a non-authoritative outcome.
- Diagnostics include actionable next steps without starting a service.
- Existing tests that rely on current authority stores still pass or are
  intentionally adjusted without changing runtime behavior.

**Test Expectations**

- Package: import-boundary tests for resolver contract modules.
- Unit: resolver input normalization, outcome classification, diagnostic
  rendering, and strict missing-authority behavior.
- Contract: compatibility tests proving future clients can distinguish online,
  offline, stale, incompatible, and unavailable outcomes.
- Contract: direct-database inputs map to unsupported/reserved outcomes, not
  online clients or private DB access.
- Integration: minimal CLI/config/env resolution tests if current parser/config
  boundaries support them without adding a server.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

This phase creates the semantic root of v10. Poor naming or mixed
responsibilities here would spread through every later phase, so the phase
execution plan must inventory existing `AuthorityConfig`, CLI, and store factory
usage before editing.

**Future Compatibility**

The contracts should allow future transports and hosted authorities by
describing authority capability and reference facts without assuming localhost,
SQLite, or FastAPI.

**Alternatives Rejected**

- Continuing to infer online/offline behavior from missing endpoints.
- Treating offline mode as an exception path.
- Letting callers start a local service as part of resolver failure handling.

**Debt Introduced**

The first phase may leave most callers using old behavior. That is acceptable
only because later adoption phases are explicit.

**Reviewability**

Review should focus on contract clarity, naming, and whether failure modes are
complete enough for later CLI and runner migration.

**Notes**

- Confirm whether `AuthorityConfig()` defaults need to remain temporarily for
  backward-compatible construction during this phase.

**Completion Summary**

Phase 1 merged on 2026-05-11:

- Branch: `codex/authority-mode-resolution`
- PR: https://github.com/samcantrill/loom/pull/119
- Target branch: `develop`
- Merge commit: `9007c8c1cdd163d82eae81aa799da6cfdf217954`
- Implementation summary: added side-effect-free authority resolver contracts,
  explicit online/offline outcomes, supplied registry/health facts, reserved
  direct-database diagnostics, opt-in CLI resolver-mode parsing, and package,
  unit, contract, and integration coverage.
- Validation before PR: `make validate-pr` passed after escalation for local
  socket permissions; `make test-summary` passed with overall 1619 passed, 12
  skipped, and 1213 deselected.
- GitHub CI: `checks` succeeded before merge on 2026-05-11.
- Automated review: manager review found no blocking scope, correctness, or
  test-evidence issues after the pre-submit blocker fix recorded in the phase
  artifact.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-mode-resolution` at merge time.
- Follow-up notes: current runtime factories intentionally keep existing
  compatibility behavior until Phase 10 adopts strict resolver outcomes.

### Phase 2: Authority Client And Server Protocol Models

- Status: merged
- Branch: `codex/authority-protocol-models`
- PR: https://github.com/samcantrill/loom/pull/120

**Goal**

Define transport-independent authority protocol models before binding them to
FastAPI or persistence.

**Scope**

- Add request, response, acknowledgement, rejection, revision, capability,
  readiness, and error-envelope models.
- Cover run lifecycle, stage lifecycle, operation submission, output commit,
  artifact facts, lease/fencing facts, snapshots, and read-model essentials at
  the protocol level.
- Define protocol version and schema compatibility fields.
- Provide model validation and round-trip tests.
- Keep models independent from FastAPI imports and private repository schemas.

**Out Of Scope**

- HTTP route implementation.
- Durable DB mutation.
- CLI adoption.
- Runner adoption.
- Offline evidence manifests.

**Acceptance Criteria**

- Protocol model modules can be used by a client adapter and a server adapter
  without importing FastAPI or SQLite.
- Error envelopes can carry resolver, validation, conflict, stale-generation,
  unsupported-capability, and internal-error categories.
- Acknowledgements expose enough revision/fencing facts for clients to avoid
  blind writes.
- Capabilities are explicit enough for diagnostics and future compatibility
  checks.

**Test Expectations**

- Package: import tests proving protocol modules do not depend on transport or
  repository modules.
- Unit: validation, serialization, defaulting, enum/category coverage, and
  version compatibility helpers.
- Contract: golden-shape tests for representative requests and responses.
- Integration: in-memory fake client/server protocol conformance if useful.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

The protocol model surface becomes the public compatibility layer for v10.
Models should be explicit and boring rather than clever.

**Future Compatibility**

Include version and capability fields so future clients can fail cleanly against
older or newer authority services.

**Alternatives Rejected**

- Letting FastAPI request models define the core protocol.
- Reusing private store dataclasses directly as wire models.
- Returning unstructured dictionaries for mutation acknowledgements.

**Debt Introduced**

Some protocol operations may be broader than immediately implemented. Keep this
bounded to operations already represented by the roadmap and existing runtime
concepts.

**Reviewability**

Review should compare protocol operations against existing store abstractions
and ensure there are no SQL or FastAPI details in the public model layer.

**Notes**

- The phase execution plan should decide whether to use standard-library
  dataclasses, existing local helpers, or a dependency introduced with FastAPI
  only after inspecting current project patterns.

**Completion Summary**

Phase 2 merged on 2026-05-11:

- Branch: `codex/authority-protocol-models`
- PR: https://github.com/samcantrill/loom/pull/120
- Target branch: `develop`
- Merge commit: `fde4041e6d46249eb519fac98aed7cf84c61eb45`
- Implementation summary: added transport-independent authority protocol value
  models, public store exports, version/schema readiness payloads, request and
  response envelopes, accepted/rejected result shapes, explicit fence fields,
  structured rejection categories, package, unit, and contract coverage,
  readiness conflict validation, serialized local event appends, and
  high-entropy atomic temp paths for parallel run-store writes.
- Validation before merge: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`
  passed; `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with overall
  1636 passed, 12 skipped, and 1230 deselected.
- GitHub CI: `checks` succeeded before merge on 2026-05-11.
- Automated review: reviewer found a readiness-version conflict bug and a CI
  event-sequence race; blocker resolution fixed both and the later same-target
  atomic temp-file collision exposed by CI, with no blocking findings remaining
  at merge time.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-protocol-models` at merge time.
- Follow-up notes: Phase 3 should adapt these plain-data values into FastAPI
  route payloads without moving transport or repository concerns back into the
  protocol model module.

### Phase 3: FastAPI Transport Skeleton

- Status: merged
- Branch: `codex/authority-fastapi-skeleton`
- PR: https://github.com/samcantrill/loom/pull/121

**Goal**

Introduce the FastAPI server adapter and deterministic local test harness without
adding durable authority mutation yet.

**Scope**

- Add the FastAPI runtime dependency with explicit packaging rationale.
- Create the authority app boundary.
- Define route ownership between operational supervisor routes and authority
  mutation routes.
- Implement health, liveness, readiness, version, and capability stubs.
- Add dependency injection points for future repository and service objects.
- Add local deterministic tests that do not require a long-running external
  process.

**Out Of Scope**

- Durable SQLite repository.
- Real mutation route behavior.
- Supervisor process management commands.
- Workspace registry writes.
- Runtime caller migration.

**Acceptance Criteria**

- The FastAPI app can be constructed in tests without starting an external
  server process.
- Health/liveness/readiness endpoints return structured protocol-compatible
  data.
- Route modules do not contain repository implementation.
- Core runtime modules do not import FastAPI.
- Dependency and packaging changes are documented in the phase plan and PR
  body.

**Test Expectations**

- Package: import-boundary tests ensuring FastAPI imports remain in transport
  modules.
- Unit: app construction and dependency wiring.
- Contract: response-shape tests for health/readiness/capability endpoints.
- Integration: in-process FastAPI test-client coverage for stubs.
- E2E: not required.
- Opt-in: external server smoke test only if practical and stable.

**Design Impact**

This phase introduces a major dependency and the concrete service process
surface. It must keep framework details out of core authority semantics.

**Future Compatibility**

Dependency injection and route grouping should permit later hosted service
deployment, alternate lifecycle commands, and repository substitution.

**Alternatives Rejected**

- Using ad hoc HTTP handlers.
- Starting a service from tests as the only validation path.
- Letting the server skeleton decide persistence semantics.

**Debt Introduced**

Operational route behavior is initially stubbed. That debt is retired by the
supervisor and mutation API phases.

**Reviewability**

Review should inspect imports, dependency declarations, test isolation, and
whether the route split is clear enough for future phases.

**Notes**

- Confirm dependency grouping in `pyproject.toml` and avoid pulling in optional
  extras that are not needed for local authority service operation.

**Completion Summary**

Phase 3 merged on 2026-05-11:

- Branch: `codex/authority-fastapi-skeleton`
- PR: https://github.com/samcantrill/loom/pull/121
- Target branch: `develop`
- Merge commit: `700f3bb66875e711825148377c5260d5a22a11b6`
- Implementation summary: added FastAPI as the explicit runtime service
  dependency, `httpx` as dev-only TestClient support, the lightweight
  `loom.authority` package, in-process app construction, injected service
  facts, supervisor health/live/ready/version/capability routes, and a
  non-mutating `/v1/authority` route-group boundary for future mutation APIs.
- Validation before merge: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`
  passed; `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with overall
  1646 passed, 12 skipped, and 1240 deselected.
- GitHub CI: `checks` succeeded before merge on 2026-05-11.
- Automated review: manager review found no scope, dependency,
  import-boundary, route-contract, or validation-evidence blockers after the
  bounded implementation refinement recorded in the phase artifact.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-fastapi-skeleton` at merge time.
- Follow-up notes: Phase 4 can use the injected service/repository boundary for
  private schema/versioning work without moving FastAPI imports into core store
  protocol modules.

### Phase 4: Private Repository Schema And Versioning

- Status: merged
- Branch: `codex/authority-repository-schema`
- PR: https://github.com/samcantrill/loom/pull/122

**Goal**

Create the service-owned durable repository foundation with private SQLite
schema versioning and transaction boundaries.

**Scope**

- Add private repository module(s) for the authority server.
- Define SQLite connection handling, schema bootstrap, schema version checks,
  transaction wrapper, generation metadata, and repository identity metadata.
- Add explicit compatibility errors for missing, newer, older, or corrupt
  repository schemas.
- Prove clients cannot treat the DB as public API through source boundaries and
  tests.
- Keep repository behavior below protocol/server layers.

**Out Of Scope**

- Full run or stage lifecycle implementation.
- FastAPI route mutation wiring.
- Registry files.
- Supervisor commands.
- Offline import.

**Acceptance Criteria**

- A new private SQLite repository can be initialized under an explicit service
  state directory.
- Schema version and service generation facts are persisted.
- Transactions are explicit and testable.
- Repository compatibility errors map cleanly to protocol/server errors in
  later phases.
- Public clients have no path that opens or mutates the private DB directly.

**Test Expectations**

- Package: import-boundary tests for repository privacy.
- Unit: schema creation, version checks, transaction commit/rollback, generation
  metadata, and compatibility errors.
- Contract: repository error categories align with protocol error envelopes.
- Integration: file-backed SQLite tests using temporary directories.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

This phase defines durable state ownership. It must make it hard for later code
to bypass the service boundary for convenience.

**Future Compatibility**

Repository interfaces should leave room for alternate backends while avoiding a
large abstraction framework.

**Alternatives Rejected**

- Reusing `SQLitePerRunAuthorityStore` as the runtime backend.
- Publishing SQL schema as a compatibility promise.
- Letting every route open its own ad hoc connection.

**Debt Introduced**

The initial repository contains schema foundation before lifecycle tables are
fully useful. That is intentional and retired by the next two repository phases.

**Reviewability**

Review should inspect schema privacy, migration/version strategy, transaction
semantics, and how generation metadata will support restart and fencing.

**Notes**

- The phase execution plan should inventory `sqlite_authority.py` and
  `sqlite_coordination.py` before deciding what to reuse or copy.

**Completion Summary**

Phase 4 merged on 2026-05-11:

- Branch: `codex/authority-repository-schema`
- PR: https://github.com/samcantrill/loom/pull/122
- Target branch: `develop`
- Merge commit: `aa3a42b011043c2b428b7290a0e788eaafc2fdd8`
- Implementation summary: added the private `loom.authority._repository`
  SQLite foundation with explicit state-directory initialization, schema
  version and service-generation metadata, typed repository identity facts,
  structured compatibility failures for missing, older, newer, and corrupt
  repositories, and explicit transaction commit/rollback handling. Added
  package privacy, unit, contract, and file-backed integration coverage while
  keeping repository symbols out of the public `loom.authority` root.
- Validation before PR: targeted Ruff, Pyright, and focused package/unit/
  contract/integration pytest passed. `UV_CACHE_DIR=/tmp/uv-cache make
  validate-pr` passed; `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed
  with overall 1664 passed, 12 skipped, and 1258 deselected.
- GitHub CI: `checks` succeeded before merge on 2026-05-11.
- Automated review: manager review found no scope, privacy-boundary,
  schema-compatibility, transaction, PR-body, or validation-evidence blockers.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-repository-schema` at merge time.
- Follow-up notes: Phase 5 can build run lifecycle repository behavior on the
  private schema foundation without exposing direct DB access through public
  APIs.

### Phase 5: Run Lifecycle Repository

- Status: merged
- Branch: `codex/authority-run-lifecycle`
- PR: https://github.com/samcantrill/loom/pull/123

**Goal**

Persist run lifecycle authority behavior in the private repository.

**Scope**

- Implement run admission records.
- Persist lifecycle transitions, controller leases, run snapshots, audit events,
  cleanup/recovery records, and revision facts.
- Enforce valid transition ordering and stale revision rejection at repository
  level.
- Add read models needed by later diagnostics and API phases.
- Keep the implementation repository-level only.

**Out Of Scope**

- Stage lifecycle persistence.
- FastAPI mutation routes.
- Runtime caller migration.
- Workspace coordination.
- Offline import.

**Acceptance Criteria**

- Repository tests can admit a run, transition it through valid states, reject
  invalid transitions, and read back snapshots/audit events.
- Controller lease facts are persisted and validated.
- Revisions/fencing facts prevent stale run-level mutation.
- Cleanup/recovery records are durable and queryable.
- Behavior remains below the service API boundary.

**Test Expectations**

- Package: repository modules remain private.
- Unit: transition validation, stale revision rejection, lease persistence,
  audit record creation, snapshot read models.
- Contract: repository conformance against run lifecycle semantics expected by
  protocol models.
- Integration: temp SQLite file-backed lifecycle sequences.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

This phase turns run lifecycle state into durable authority truth. It should not
try to solve stage execution or scheduler decisions yet.

**Future Compatibility**

The run lifecycle repository should preserve enough audit and revision facts for
future recovery, import provenance, and hosted authority diagnostics.

**Alternatives Rejected**

- Encoding lifecycle state only in event logs with no current read model.
- Reusing in-memory local service state as the source of truth.
- Letting runners own durable run state directly.

**Debt Introduced**

Run persistence exists before server routes expose it. That is retired by Phase
7.

**Reviewability**

Review should focus on transition semantics, revision/fencing behavior, and
whether audit data is sufficient without being over-modeled.

**Notes**

- Phase execution should compare repository semantics to existing
  `PipelineRunStore` expectations.

**Completion Summary**

Phase 5 merged on 2026-05-11:

- Branch: `codex/authority-run-lifecycle`
- PR: https://github.com/samcantrill/loom/pull/123
- Target branch: `develop`
- Merge commit: `d08823733bc9c63ae67af510245b220360d8a746`
- Implementation summary: advanced the private authority repository to schema
  version 2 with cross-run run lifecycle tables, repository revisions, run
  admission and transitions, expected-revision checks, controller lease
  acquire/renew/release/fail with fencing and TTL checks, submitted operation
  persistence, audit event persistence, cleanup candidate records, recovery
  records, and run-level recovery scanning. The work remains private to
  `loom.authority._repository` and does not add route, stage, attempt, output,
  artifact, runtime, or public export behavior.
- Validation before PR: targeted Ruff, Pyright, and focused package/unit/
  contract/integration pytest passed. `UV_CACHE_DIR=/tmp/uv-cache make
  validate-pr` passed; `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed
  with overall 1673 passed, 12 skipped, and 1267 deselected.
- GitHub CI: `checks` succeeded before merge on 2026-05-11.
- Automated review: manager review found no scope, private-boundary,
  schema-versioning, revision/fencing, controller-lease, cleanup/recovery,
  PR-body, or validation-evidence blockers.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-run-lifecycle` at merge time.
- Follow-up notes: Phase 6 can extend the private repository with stage,
  attempt, output, artifact, and stage-lease behavior on top of schema version
  2 or a deliberate successor version.

### Phase 6: Stage Lifecycle Repository

- Status: merged
- Branch: `codex/authority-stage-lifecycle`
- PR: https://github.com/samcantrill/loom/pull/124

**Goal**

Persist stage, attempt, operation, output, artifact, and stage-lease authority
behavior in the private repository.

**Scope**

- Implement stage transition persistence.
- Implement attempt allocation and attempt terminal-state records.
- Persist submitted-operation records.
- Persist output commits and artifact facts.
- Implement stage lease/fencing checks and stale-commit rejection.
- Add repository read models needed by later APIs and diagnostics.

**Out Of Scope**

- FastAPI mutation routes.
- Runner and worker migration.
- SLURM live path migration.
- Offline evidence manifests.
- Resource admission leases.

**Acceptance Criteria**

- Repository tests cover stage transition ordering, attempt allocation, output
  commit, artifact fact persistence, and submitted operation state.
- Stale stage leases and stale generations cannot commit outputs or terminal
  attempts.
- Artifact records can carry checksum/size/reference fields needed by future
  offline evidence and diagnostics.
- No runtime caller uses the repository directly.

**Test Expectations**

- Package: private repository import-boundary coverage.
- Unit: stage transition validation, attempt allocation uniqueness, lease
  renewal/expiry logic where applicable, output commit idempotence/conflicts,
  artifact fact persistence.
- Contract: repository conformance against protocol stage lifecycle operations.
- Integration: temp SQLite file-backed multi-stage and retry sequences.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

This phase defines the highest-risk mutation semantics for online execution.
Lease and fencing behavior must be explicit because later runner, worker, and
SLURM paths depend on it.

**Future Compatibility**

The schema should leave room for future attempt metadata, deferred
finalization, offline import provenance, and scheduler admission decisions.

**Alternatives Rejected**

- Treating stage outputs as append-only facts with no fencing.
- Collapsing operation submission and attempt lifecycle into one unstructured
  blob.
- Solving resource admission in the same phase.

**Debt Introduced**

Stage repository behavior remains inaccessible to real clients until the
mutation API phase.

**Reviewability**

Review should emphasize stale write rejection, idempotence, output/artifact
facts, and compatibility with current stage execution paths.

**Notes**

- If source review proves `StageStatus.INTERRUPTED` or another lifecycle value
  is required, document the proof and narrow the enum change to this phase.

**Completion Summary**

Phase 6 merged on 2026-05-11:

- Branch: `codex/authority-stage-lifecycle`
- PR: https://github.com/samcantrill/loom/pull/124
- Target branch: `develop`
- Merge commit: `402be7fb775d0e244bf8aeb01a57f0f07a30fb74`
- Implementation summary: advanced the private authority repository to schema
  version 3 with cross-run stage state, attempts, stage leases, output commits,
  and artifact facts. Added private stage transition, attempt allocation,
  stage lease renew/release/fail, terminal attempt, and output commit methods
  with expected-revision, service-generation, TTL, and fencing checks. Run
  snapshots now include durable stage attempts, active leases, latest commits,
  and artifact facts. The work remains private to
  `loom.authority._repository` and does not add route, runtime, registry,
  supervisor, resource-admission, or offline-import behavior.
- Validation before PR: targeted Ruff, Pyright, and focused package/unit/
  contract/integration pytest passed. `UV_CACHE_DIR=/tmp/uv-cache make
  validate-pr` passed; `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed
  with overall 1683 passed, 12 skipped, and 1277 deselected after an isolated
  unrelated flaky integration test passed on rerun.
- GitHub CI: `checks` succeeded before merge on 2026-05-11.
- Automated review: manager review found no scope, private-boundary,
  stage-lifecycle, lease/fencing, stale-generation, PR-body, or
  validation-evidence blockers.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-stage-lifecycle` at merge time.
- Follow-up notes: Phase 7 can wire the private repository to FastAPI mutation
  routes and client protocol behavior without exposing private DB access.

### Phase 7: Authority Server Mutation API

- Status: merged
- Branch: `codex/authority-mutation-api`
- PR: https://github.com/samcantrill/loom/pull/125

**Goal**

Wire the private repository into the FastAPI authority routes and client
protocol so online mutation can be exercised through the service boundary.

**Scope**

- Implement FastAPI routes for run and stage lifecycle mutations.
- Implement corresponding `AuthorityClient` transport adapter behavior.
- Map repository acknowledgements, revisions, conflicts, stale leases,
  unsupported capabilities, and internal errors into protocol responses.
- Add timeout/error mapping for client calls.
- Add service-boundary conformance tests.
- Preserve existing runtime callers until later adoption phases.

**Out Of Scope**

- Supervisor process lifecycle commands.
- Registry discovery.
- Runner migration.
- Workspace coordination.
- Resource leases.
- Offline import.

**Acceptance Criteria**

- A test client can perform representative run and stage lifecycle mutations
  against a FastAPI app backed by a temp SQLite repository.
- Mutations return structured acknowledgements or structured rejections.
- Client behavior does not expose SQL paths or private schema details.
- Capability/readiness responses reflect repository availability and schema
  compatibility.
- Timeout and connection failures map to resolver/client diagnostics rather
  than raw framework tracebacks.

**Test Expectations**

- Package: client modules do not import repository implementation.
- Unit: client error mapping, route request validation, response conversion.
- Contract: protocol conformance tests for success, conflict, stale generation,
  unsupported capability, and internal error envelopes.
- Integration: in-process FastAPI plus temp SQLite repository mutation flows.
- E2E: optional local process smoke if stable; not required for default suite.
- Opt-in: external server process tests may be added under an opt-in marker.

**Design Impact**

This phase creates the usable online authority service boundary. All later
runtime migration depends on its correctness and diagnostics.

**Future Compatibility**

The client should be replaceable by another transport adapter as long as the
protocol model is preserved.

**Alternatives Rejected**

- Letting runtime code call repository methods directly during migration.
- Returning HTTP status codes without structured protocol errors.
- Combining supervisor lifecycle with mutation API before the service boundary
  is validated.

**Debt Introduced**

The service can be tested in-process before lifecycle commands make it easy to
run as a managed local supervisor.

**Reviewability**

Review should inspect route/core separation, client error behavior, protocol
coverage, and whether repository errors are faithfully represented.

**Notes**

- Phase execution should verify whether current `AuthorityClient` names can be
  extended or whether new names are needed to avoid semantic confusion.

**Completion Summary**

Phase 7 merged on 2026-05-11:

- Branch: `codex/authority-mutation-api`
- PR: https://github.com/samcantrill/loom/pull/125
- Target branch: `develop`
- Merge commit: `5dbb72757b24406f3a41847a546bea2a1a4b4246`
- Implementation summary: added a repository-backed mutation service that maps
  protocol envelopes to private repository run, stage, lease,
  submitted-operation, and output-commit methods; added FastAPI mutation
  routes under `/v1/authority`; added a repository-free stdlib HTTP
  `AuthorityClient`; updated repository-backed service capabilities and
  manifest behavior; and added package, unit, contract, and integration
  coverage for structured acknowledgements and rejections.
- Validation before PR: targeted Ruff, Pyright, and focused package/unit/
  contract/integration pytest passed. `UV_CACHE_DIR=/tmp/uv-cache make
  validate-pr` passed after public export tests were updated for the new
  client surface; `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with
  overall 1694 passed, 12 skipped, and 1288 deselected.
- GitHub CI: `checks` succeeded before merge on 2026-05-11.
- Automated review: manager review found no scope, route/service/client
  separation, private-boundary, protocol-mapping, PR-body, or
  validation-evidence blockers.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-mutation-api` at merge time.
- Follow-up notes: Phase 8 can add workspace-local registry records that
  describe authority allocation without making stale records safe to use.

### Phase 8: Workspace Registry Records

- Status: merged
- Branch: `codex/authority-registry-records`
- PR: [#126](https://github.com/samcantrill/loom/pull/126)

**Goal**

Add workspace-local registry records that describe authority allocation without
making stale records safe to use.

**Scope**

- Create registry read/write helpers for `.loom/authority/` records.
- Persist endpoint, supervisor state directory reference, workspace identity,
  service generation, capability/version metadata, allocation scope, timestamps,
  and redacted diagnostics metadata.
- Use atomic file updates.
- Add validation for stale, missing, incompatible, wrong-workspace, wrong
  generation, and unavailable authority references.
- Add allocation-scoped hooks for later supervisor and resolver phases.

**Out Of Scope**

- Starting or stopping a supervisor process.
- Runtime resolver adoption.
- User-global discovery.
- Service DB mutation.
- Offline import.

**Acceptance Criteria**

- Registry records are written atomically and can be parsed deterministically.
- Registry records never contain secrets or unredacted sensitive endpoint
  payloads.
- Wrong-workspace, stale-generation, unsupported-version, and unavailable
  service cases produce distinct diagnostics.
- Registry helpers can be used without importing FastAPI route modules.
- Existing workspaces without registry records fail closed in online mutation
  mode.

**Test Expectations**

- Package: registry helpers remain independent from transport internals where
  possible.
- Unit: serialization, redaction, atomic write behavior, validation categories,
  stale record handling.
- Contract: registry validation maps to Phase 1 resolver outcomes.
- Integration: temp workspace `.loom/authority/` file behavior.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

The registry is the user-facing discovery artifact. Its behavior must be strict
because stale local files are otherwise a tempting but unsafe authority shortcut.

**Future Compatibility**

Record shape should permit later user-global discovery references without
requiring runtime clients to trust global state by default.

**Alternatives Rejected**

- User-global registry as the default discovery mechanism.
- Recording raw process implementation details that clients depend on.
- Allowing stale records to trigger implicit restart.

**Debt Introduced**

Registry records are available before lifecycle commands populate them in normal
use. The supervisor phase retires that gap.

**Reviewability**

Review should inspect record schema, redaction, atomicity, failure categories,
and how stale records guide users toward explicit status/restart commands.

**Notes**

- The exact `.loom/authority/` filenames should be chosen in the phase plan
  after checking existing `.loom` layout expectations.

**Completion Summary**

- Phase execution plan: `docs/phases/authority-registry-records.md`.
- PR body: `docs/phases/authority-registry-records-pr-body.md`.
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-registry-records`.
- Stack target: `develop`; verified PR target is `develop` with head
  `codex/authority-registry-records`.
- Merge: PR #126 squash-merged to `develop` on 2026-05-11 with merge commit
  `b1bf0a93c07ed47485c2550e73159b6b086aef85`.
- Implementation summary: added versioned workspace and allocation-scoped
  registry records, deterministic `.loom/authority/` path helpers, atomic JSON
  write/read helpers, recursive sensitive metadata redaction, endpoint safety
  checks that preserve non-sensitive query strings, fail-closed validation
  statuses, resolver-hint conversion, and service-health fact conversion.
- Validation: targeted Ruff passed; targeted Pyright passed; targeted pytest
  passed with 18 registry tests after the automated review fix.
  `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed with Ruff clean, Pyright
  clean, default pytest 1271 passed / 18 skipped / 14 deselected,
  config-extra 420 passed / 1300 deselected, and build success.
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package 67 passed /
  1 skipped, unit 921 passed / 1 skipped, contract 145 passed / 2 skipped,
  integration 125 passed / 8 skipped / 10 deselected, e2e 39 passed /
  1 deselected, and config-extra 420 passed / 1300 deselected.
- Review and CI: managing-agent automated review completed on 2026-05-11; one
  bounded fix hardened malformed JSON validation and endpoint query preservation.
  GitHub CI `checks` passed in 2m33s on
  <https://github.com/samcantrill/loom/actions/runs/25666089159/job/75338797631>.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-registry-records` at merge time, and the
  remote branch was deleted by the merge command.
- Follow-up notes: Phase 9 can write these workspace-local records from
  supervisor lifecycle commands.

### Phase 9: Supervisor Lifecycle Commands

- Status: merged
- Branch: `codex/authority-supervisor-lifecycle`
- PR: [#127](https://github.com/samcantrill/loom/pull/127)

**Goal**

Implement explicit local authority supervisor lifecycle commands and generation
handling.

**Scope**

- Add `loom authority start`, `status`, `doctor`, `stop`, and `restart`
  behavior.
- Require an explicit supervisor state directory. Do not add a workspace-local
  default service state directory in v10.
- Start the FastAPI authority service against the private repository.
- Update workspace registry records after successful readiness.
- Use health/readiness checks for status and doctor output.
- Handle service generation changes on restart and produce fail-closed guidance
  for stale clients.

**Out Of Scope**

- Migrating runtime callers.
- Workspace coordination service API.
- Resource admission.
- Offline import.
- User-global discovery.

**Acceptance Criteria**

- Users can explicitly start, inspect, stop, and restart a local authority
  supervisor.
- Start requires an explicit state directory argument or equivalent explicit
  configuration, and diagnostics always report the selected state directory.
- Status and doctor output distinguish process health, readiness, repository
  schema compatibility, registry state, and generation mismatches.
- Start does not silently overwrite incompatible repository state.
- Restart produces new generation facts or otherwise invalidates stale clients
  safely.
- Commands do not make normal runtime mutation paths start hidden supervisors.

**Test Expectations**

- Package: CLI command imports do not leak FastAPI into core runtime.
- Unit: command planning, state-dir validation, registry update, generation
  handling, diagnostic formatting.
- Contract: supervisor readiness maps to protocol capability/readiness models.
- Integration: local process or in-process service lifecycle tests where stable.
- E2E: a minimal CLI lifecycle smoke test if it can run deterministically.
- Opt-in: slower real-process lifecycle tests under an opt-in marker if needed.

**Design Impact**

This phase makes the authority service operationally real. The UX must be
explicit enough to replace implicit co-located service startup.

**Future Compatibility**

The lifecycle shape should permit later hosted process managers and user-global
discovery without making those required now.

**Alternatives Rejected**

- Starting a supervisor automatically from `loom run`.
- Treating status as a raw process check without service readiness.
- Reusing backend diagnostics as the lifecycle command surface.

**Debt Introduced**

Supervisor lifecycle may remain local-only and single-user in v10.

**Reviewability**

Review should focus on lifecycle idempotence, stale generation invalidation,
process cleanup, diagnostics, and whether commands are safe in repeated local
development use.

**Notes**

- The phase execution plan must verify existing `loom authority` command shape
  before adding or renaming subcommands.

**Completion Summary**

- Phase execution plan: `docs/phases/authority-supervisor-lifecycle.md`.
- PR body: `docs/phases/authority-supervisor-lifecycle-pr-body.md`.
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-supervisor-lifecycle`.
- Stack target: `develop`; verified PR target is `develop` with head
  `codex/authority-supervisor-lifecycle`.
- Merge commit: `49c013cc56bbc09933b837e5f69caf93065bde0c`.
- Implementation summary: added explicit `loom authority start/status/doctor/stop/restart`
  commands, authority-owned supervisor process/state/registry helpers, a private
  repository-backed FastAPI server entrypoint, restart generation rotation, and
  `uvicorn` as the bounded ASGI server dependency needed to run the existing
  FastAPI app.
- Validation: targeted Ruff passed; targeted Pyright passed; targeted pytest
  passed with 54 selected phase tests during implementation, and the final
  review-fix supervisor unit run passed with 7 tests.
  `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed with Ruff clean, Pyright
  clean, default pytest 1285 passed / 18 skipped / 14 deselected, config-extra
  420 passed / 1314 deselected, and build success.
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package 68 passed /
  1 skipped, unit 931 passed / 1 skipped, contract
  146 passed / 2 skipped, integration 126 passed / 8 skipped / 10 deselected,
  e2e 40 passed / 1 deselected, and config-extra 420 passed / 1314 deselected.
- Review and CI: managing-agent automated review completed on 2026-05-11; one
  bounded fix made startup fail immediately if the child process exits before
  readiness. GitHub CI `checks` passed in 2m42s on
  <https://github.com/samcantrill/loom/actions/runs/25668370100/job/75346782820>.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-supervisor-lifecycle` at merge time, and
  the remote branch was deleted by the merge command.
- Follow-up notes: Phase 10 can adopt the registry records and supervisor
  lifecycle facts from strict resolver and factory paths without adding hidden
  startup.

### Phase 10: Strict Resolver And Factory Adoption

- Status: merged
- Branch: `codex/authority-resolver-adoption`
- PR: <https://github.com/samcantrill/loom/pull/128>

**Goal**

Adopt the new strict authority resolver in shared Python factories and CLI
factory paths without migrating every runtime entrypoint yet.

**Scope**

- Make shared authority/run-store factory paths use Phase 1 resolver outcomes.
- Connect endpoint and registry references only after health/readiness checks.
- Fail closed for missing or invalid online authority in mutation-capable
  factory paths.
- Reject `direct_database` authority selection for v10 runtime mutation with
  migration guidance toward FastAPI service authority or explicit offline mode.
- Preserve explicit offline-first factory outcomes.
- Update CLI and diagnostics plumbing needed to surface resolver guidance.
- Keep runtime migration narrow to central factories, not every caller.

**Out Of Scope**

- Full `PipelineRunner` and `loom run` migration.
- Worker, continuation, and SLURM migration.
- Workspace coordination service migration.
- Offline evidence writer.

**Acceptance Criteria**

- Central factories no longer implicitly start a co-located service for online
  mutation mode.
- Endpoint and registry references are validated before a client is returned.
- `direct_database` config/env/CLI selections no longer create mutation-capable
  runtime stores or clients in v10 paths.
- Offline-first selection returns an explicitly non-authoritative local/evidence
  path where supported.
- Diagnostics point to `loom authority status` and `loom authority restart
  --state-dir ...` or equivalent concrete commands for stale/unavailable
  authorities.
- Existing tests are updated to select explicit in-memory/test authority where
  appropriate.

**Test Expectations**

- Package: no new direct repository imports in public factory paths.
- Unit: factory resolution cases, health-check behavior, stale registry
  diagnostics, direct-database rejection, offline selection.
- Contract: factory outcomes match Phase 1 resolver outcome categories.
- Integration: CLI/factory tests against in-process FastAPI authority where
  stable.
- E2E: not required.
- Opt-in: external authority process tests may be opt-in.

**Design Impact**

This phase is where v10 behavior starts replacing the old implicit default. It
must balance compatibility in tests with strict runtime semantics.

**Future Compatibility**

Resolver adoption should allow future endpoint reference types, hosted authority
discovery, and alternate transports without changing runtime call sites again.

**Alternatives Rejected**

- Updating every runtime caller before the shared factories are correct.
- Keeping endpoint-less local startup as the silent default.
- Letting stale registry records fall back to offline mutation.
- Keeping direct-database runtime mutation as a compatibility fallback.

**Debt Introduced**

Some runtime entrypoints may still bypass the new factories until later phases.
That debt is tracked by the dedicated migration phases.

**Reviewability**

Review should inspect old default behavior removal, test fixture updates, and
clarity of user-facing failure messages.

**Notes**

- Phase execution should produce an inventory of remaining runtime entrypoints
  after the central factory adoption.

**Completion Summary**

- Phase execution plan:
  `docs/phases/authority-resolver-adoption.md`
- PR body: `docs/phases/authority-resolver-adoption-pr-body.md`
- Stack target: root phase PR targeting `develop`
- Implementation summary: added strict resolver-backed authority factory
  helpers, routed central run-store factories through explicit authority
  resolution, removed endpoint-less hidden service startup from public factory
  paths, preserved trusted `authority_store=` injection, kept read-only planning
  from constructing mutation stores, and updated diagnostics/catalog behavior
  for missing authority.
- Test and example updates: mutation-capable tests, CLI flows, subprocess/SLURM
  paths, and executable examples now use explicit service configs or injected
  stores where authority state crosses process boundaries.
- Validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed; `UV_CACHE_DIR=/tmp/uv-cache make test-summary`
  passed with overall 1740 passed / 0 failed / 0 errors / 12 skipped / 1334
  deselected.
- Review and CI: managing-agent automated review completed with no blocking
  findings; GitHub CI `checks` passed on
  <https://github.com/samcantrill/loom/actions/runs/25704175728/job/75470625510>.
- Merge metadata: PR #128 was squash-merged into `develop` as `6ce630a` after
  confirming the PR target was exactly `develop`, the PR was open, and CI had
  passed.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-resolver-adoption` at merge time.
- Follow-up notes: Phase 11 should adapt `PipelineRunner` and `loom run` onto
  service-backed online mutation. Phases 12 and 13 still own continuation,
  worker, subprocess, and SLURM migration. Phase 17 owns true offline evidence
  writer/import behavior.

### Phase 11: Python Runner And `loom run` Online Path

- Status: merged
- Branch: `codex/authority-run-online-path`
- PR: <https://github.com/samcantrill/loom/pull/129>

**Goal**

Move the primary Python runner and `loom run` online execution path onto the
strict resolver and service-backed authority client.

**Scope**

- Convert `PipelineRunner`, `run_pipeline`, Python execution helpers, and
  `loom run` online execution to use strict authority resolution.
- Preserve runner-side DAG orchestration and stage launch logic.
- Route run and stage lifecycle mutations through `AuthorityClient`.
- Surface authority endpoint, generation, capability, and source facts in
  relevant run diagnostics.
- Update tests to explicitly start/use an in-process or fixture authority.

**Out Of Scope**

- Subprocess worker continuation migration.
- `loom stage run`, `loom stage-job run`, and prepared-run continuation
  migration.
- SLURM live submission migration.
- Workspace coordination service API.
- Offline evidence writer.

**Acceptance Criteria**

- `loom run` online mode fails closed when no valid authority is selected.
- Online `loom run` against a ready authority records run and stage lifecycle
  mutations through the service-backed client.
- Runner orchestration remains local and deterministic.
- Tests no longer rely on hidden co-located service startup.
- User-facing errors distinguish "start an authority" from "select offline
  mode".

**Test Expectations**

- Package: runner modules depend on authority client/resolver ports, not
  private server repository modules.
- Unit: runner authority selection, mutation call sequencing, diagnostic
  rendering, no-implicit-start behavior.
- Contract: fake `AuthorityClient` tests for lifecycle call order and rejection
  handling.
- Integration: `loom run` or runner tests with in-process FastAPI/temp SQLite
  authority.
- E2E: a small deterministic `loom run` online smoke if current test suite
  supports CLI execution.
- Opt-in: external supervisor process run test if needed.

**Design Impact**

This phase changes the default online user path. It should avoid changing DAG
semantics while making authority selection explicit.

**Future Compatibility**

Keeping DAG orchestration in the runner allows later scheduler/resource phases
to add admission decisions without turning the authority into a scheduler.

**Alternatives Rejected**

- Moving DAG scheduling into the authority server.
- Allowing runner fallback to local authoritative mutation.
- Migrating worker continuation paths in the same phase.

**Debt Introduced**

Continuation and external-worker paths still need migration, so mixed behavior
may exist temporarily behind clear phase boundaries.

**Reviewability**

Review should compare old and new run flows, focusing on mutation ownership,
error UX, and ensuring only Phase 11 paths changed.

**Notes**

- Phase execution must document any temporarily skipped runner-adjacent paths in
  the phase plan.

**Completion Summary**

- Phase execution plan:
  `docs/phases/authority-run-online-path.md`
- PR body: `docs/phases/authority-run-online-path-pr-body.md`
- Stack target: root phase PR targeting `develop`
- Implementation summary: added HTTP authority lease/submitted-operation client
  calls, captured readiness facts during strict HTTP authority resolution,
  introduced `AuthorityClientBackedPerRunAuthorityStore`, and wired ready HTTP
  authority references into the primary `create_authority_backed_serial_run_store()`
  path for Python runner and `loom run` online execution.
- Test updates: added no-extra unit coverage for the HTTP-backed runner adapter,
  mutation API integration coverage for leases/submitted operations,
  config-extra local runner coverage through an in-process FastAPI authority,
  and a supervisor-backed CLI smoke aligned with the existing optional-config
  test policy.
- Validation: targeted Ruff/Pyright passed; targeted pytest passed with 26
  passed / 2 skipped; `tests/package/test_pipeline_store_api.py` passed with 11
  tests; `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed; `UV_CACHE_DIR=/tmp/uv-cache make test-summary`
  passed with package 69 passed / 1 skipped, unit 942 passed / 1 skipped,
  contract 146 passed / 2 skipped, integration 127 passed / 8 skipped / 10
  deselected, e2e 39 passed / 2 deselected, and config-extra 422 passed / 1326
  deselected.
- Review and CI: managing-agent automated review completed with no blocking
  findings; GitHub CI `checks` passed on
  <https://github.com/samcantrill/loom/actions/runs/25706042258/job/75476254033>.
- Merge metadata: PR #129 was squash-merged into `develop` as `d93e19f` after
  confirming the PR target was exactly `develop`, the PR was open, and CI had
  passed.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-run-online-path` at merge time.
- Follow-up notes: audit events remain local-only for HTTP-backed runner stores
  until a service audit route exists. Phase 12 still owns continuation and
  local/subprocess worker migration.

### Phase 12: Local/Subprocess Worker Continuation Paths

- Status: merged
- Branch: `codex/authority-worker-continuations`
- PR: <https://github.com/samcantrill/loom/pull/130>

**Goal**

Move local worker, subprocess, stage, stage-job, and prepared-run continuation
paths onto explicit authority references and service-backed mutation.

**Scope**

- Convert subprocess worker launch handoffs to carry authority endpoint,
  generation, capability, and lease/fencing facts.
- Convert `loom stage run`, `loom stage-job run`, and `loom prepared-run
  continue` paths to enforce authority references.
- Add lease renewal or revalidation where existing execution duration requires
  it.
- Ensure stale workers fail closed before mutating terminal states or outputs.
- Update continuation diagnostics and tests.

**Out Of Scope**

- SLURM live operation migration.
- Offline evidence writer.
- Resource lease admission.
- Workspace coordination service migration.

**Acceptance Criteria**

- Worker/continuation commands require explicit authority facts for online
  mutation.
- Stale generation, stale lease, incompatible capability, or unavailable
  authority prevents mutation with actionable diagnostics.
- Output commits and terminal attempt updates go through `AuthorityClient`.
- Existing local/subprocess execution tests pass with explicit authority
  fixtures.
- Prepared-run continuation does not silently mutate local authority state.

**Test Expectations**

- Package: continuation commands do not import server repository modules.
- Unit: handoff serialization, authority fact validation, stale generation and
  lease rejection, diagnostic rendering.
- Contract: fake-client tests for terminal update and output commit behavior.
- Integration: subprocess or command-level continuation tests with in-process or
  fixture authority where stable.
- E2E: minimal local subprocess continuation smoke if already practical.
- Opt-in: slower process-bound tests under opt-in marker if needed.

**Design Impact**

This phase protects the most common split-process mutation risks. Fencing facts
must be explicit in command handoffs.

**Future Compatibility**

Authority handoff records should be reusable by SLURM and future remote workers.

**Alternatives Rejected**

- Letting workers re-resolve authority from workspace registry only.
- Allowing missing lease facts to proceed and rely on server conflicts later.
- Folding SLURM migration into the same phase.

**Debt Introduced**

SLURM generated commands may still use transitional behavior until Phase 13.

**Reviewability**

Review should inspect command handoff shape, stale-write handling, and test
coverage around failed continuations.

**Notes**

- Phase execution should inventory all generated local command paths before
  editing.

**Completion Summary**

- Phase execution plan:
  `docs/phases/authority-worker-continuations.md`
- PR body: `docs/phases/authority-worker-continuations-pr-body.md`
- Stack target: root phase PR targeting `develop`
- Implementation summary: confirmed Phase 11 runtime hooks already enforce the
  required local/subprocess authority handoffs, then added regression coverage
  for stage-worker fencing validation, subprocess authority config propagation,
  CLI authority/fencing routing, prepared-run fail-closed authority store
  creation, and supervisor-backed subprocess execution.
- Test updates: added focused tests in
  `tests/unit/loom/pipeline/execution/test_stage_worker.py`,
  `tests/unit/loom/pipeline/executors/test_subprocess_executor.py`,
  `tests/unit/loom/cli/test_stage_cli.py`,
  `tests/unit/loom/cli/test_stage_job_cli.py`,
  `tests/unit/loom/cli/test_prepared_run_cli.py`, and
  `tests/e2e/test_authority_supervisor_cli.py`.
- Validation: targeted Ruff/Pyright passed; focused unit coverage passed with
  49 tests; focused supervisor e2e passed with 1 test; focused split-process
  integration coverage passed with 11 tests; `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`
  passed; `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package
  69 passed / 1 skipped, unit 948 passed / 1 skipped, contract 146 passed / 2
  skipped, integration 127 passed / 8 skipped / 10 deselected, e2e 39 passed /
  2 deselected, and config-extra 422 passed / 1332 deselected.
- Review and CI: managing-agent automated review completed with no blocking
  findings; GitHub CI `checks` passed on
  <https://github.com/samcantrill/loom/actions/runs/25707106589/job/75479503915>.
- Merge metadata: PR #130 was squash-merged into `develop` as `f5b4ac6` after
  confirming the PR target was exactly `develop`, the PR was open, and CI had
  passed.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-worker-continuations` at merge time.
- Follow-up notes: no production runtime changes were required for Phase 12;
  prepared-run replay remains intentionally fail-closed, and SLURM live
  continuation migration remains Phase 13 scope.

### Phase 13: SLURM Live Operation Paths

- Status: merged
- Branch: `codex/authority-slurm-live-paths`
- PR: https://github.com/samcantrill/loom/pull/131

**Goal**

Move SLURM live submission, status observation, cancellation, and continuation
paths onto shared authority resolution and service-backed mutation.

**Scope**

- Update SLURM live submission to carry authority references, generation facts,
  and lease/fencing data.
- Update generated handoff commands to use the same authority enforcement as
  local workers.
- Route live scheduler status observation and cancellation mutations through
  the service-backed authority client where authority truth is required.
- Preserve deferred-finalization as a distinct weaker profile for
  authority-known submitted attempts; do not convert it into v10 offline import
  evidence in this phase.
- Remove `direct_database` as an admitted live-worker mutation profile for v10
  SLURM paths, replacing it with service authority or explicit deferred/offline
  profiles as appropriate.
- Update SLURM diagnostics to label live authority-backed state versus deferred
  or local evidence state.

**Out Of Scope**

- Offline evidence manifest writer.
- Offline import transaction.
- Global scheduler or queueing.
- Resource admission leases.
- Full rewrite of SLURM configuration semantics.

**Acceptance Criteria**

- SLURM live paths fail closed when a required authority reference is missing,
  stale, or unavailable.
- Generated SLURM commands carry enough authority facts for remote continuation
  to validate generation and fencing.
- Live cancellation/status mutations use `AuthorityClient` where they affect
  authoritative state.
- Deferred-finalization remains explicitly labeled as weaker/non-authoritative
  submitted-attempt evidence, not true offline import evidence.
- SLURM live profile admission no longer treats `direct_database` as a
  supported v10 runtime mutation authority.
- SLURM tests cover generated commands and authority-reference diagnostics.

**Test Expectations**

- Package: SLURM modules depend on authority client/resolver ports, not private
  repository modules.
- Unit: generated command content, authority fact propagation, cancellation and
  status mutation behavior with fake clients, direct-database profile rejection.
- Contract: handoff records align with Phase 12 continuation authority facts.
- Integration: local deterministic SLURM adapter tests that do not require a
  real cluster.
- E2E: not required in default suite.
- Opt-in: real or simulated scheduler tests remain opt-in.

**Design Impact**

This phase brings external scheduler-facing live behavior under the same
authority discipline without pretending Loom has a global scheduler.

**Future Compatibility**

The handoff shape should support future scheduler adapters and resource
admission decisions.

**Alternatives Rejected**

- Treating SLURM as a special authority exception.
- Requiring real SLURM in default validation.
- Collapsing deferred-finalization into true offline import before manifests
  exist.
- Preserving direct-database live-worker admission as a v10 compatibility path.

**Debt Introduced**

Deferred-finalization remains a weaker, separate profile in v10. It is not a
legacy/offline import path unless a later roadmap defines a compatibility
contract.

**Reviewability**

Review should focus on generated command safety, clear state-source labeling,
and avoiding environment-dependent default tests.

**Notes**

- Phase execution must preserve documented SLURM examples unless the phase plan
  explicitly records a user-facing CLI change.

**Completion Summary**

Phase 13 merged PR #131 into `develop` with squash commit
`9ab7bd1098728ddb6af26a7fe5ce8c0c1102f35e` from
`codex/authority-slurm-live-paths`. The phase added a shared SLURM live
authority guard, requires service-profile authority-backed stores before live
submission/status/cancellation mutation, records authority mutation-source
metadata for live SLURM snapshots, rejects `direct_database` for live-worker
admission, and updates deterministic SLURM tests and fixtures for fail-closed
local-store behavior plus authority argument handoffs.

Validation evidence: focused Ruff passed; focused Pyright passed; focused
SLURM unit/integration tests passed with 100 tests; focused optional-config
SLURM e2e tests passed outside the restricted sandbox with 14 tests;
`make validate-pr` passed; `make test-summary` passed with package 69
passed/1 skipped, unit 954 passed/1 skipped, contract 146 passed/2 skipped,
integration 127 passed/8 skipped/10 deselected, e2e 39 passed/2 deselected,
and config-extra 422 passed/1338 deselected.

Automated review and merge notes: manager review found no blocking scope or
correctness issues; `gh pr view 131 --json baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup,mergeStateStatus`
verified target `develop`, head `codex/authority-slurm-live-paths`, clean merge
state, and successful CI before merge. The GitHub squash merge succeeded; local
branch deletion was deferred until the phase worktree cleanup because the
branch was checked out there.

### Phase 14: Diagnostics, Preflight, And Read-Only Source Labeling

- Status: merged
- Branch: `codex/authority-diagnostics-labeling`
- PR: https://github.com/samcantrill/loom/pull/132

**Goal**

Make diagnostics and read-only surfaces explicit about authority selection,
state source, capabilities, and online/offline policy.

**Scope**

- Update backend diagnostics, authority diagnostics, preflight, status/catalog
  read models, and local inspection surfaces.
- Label selected authority, registry source, service endpoint, repository
  profile, capabilities, schema/protocol compatibility, generation, and
  online/offline policy.
- Label displayed state as authoritative service truth, registry hint,
  materialized local state, deferred-finalization state, or offline evidence.
- Add read-only handling for unavailable authority that does not mutate local
  state.
- Improve user guidance for stale, missing, incompatible, or unhealthy
  authorities.

**Out Of Scope**

- New mutation APIs.
- Workspace coordination service migration.
- Offline evidence writer or import.
- Supervisor lifecycle behavior beyond diagnostics.

**Acceptance Criteria**

- User-facing diagnostics no longer imply local evidence is authority truth.
- Status/catalog/preflight paths show source labels for every state snapshot
  they display.
- Missing authority guidance distinguishes start/status/restart from explicit
  offline mode.
- Backend diagnostics remain available for lower-level troubleshooting but do
  not replace `loom authority` lifecycle commands.
- Tests cover representative labeling cases.

**Test Expectations**

- Package: read-only diagnostics do not import private repository modules unless
  through server/client read APIs.
- Unit: label selection, diagnostic formatting, source classification, guidance
  text.
- Contract: diagnostics consume resolver/capability/readiness models correctly.
- Integration: CLI/read-model tests against in-process service and offline
  evidence fixtures where available.
- E2E: minimal CLI output smoke if stable.
- Opt-in: external process diagnostics tests if needed.

**Design Impact**

This phase is important UX debt repayment after strict resolver adoption. It
keeps fail-closed behavior understandable.

**Future Compatibility**

Source labels should be durable enough to describe future hosted authorities,
imported runs, and richer offline evidence.

**Alternatives Rejected**

- Hiding source distinctions to keep output shorter.
- Letting backend diagnostics continue to be the primary authority lifecycle UX.
- Treating unavailable authority as permission to scan and display local state
  as if it were current truth.

**Debt Introduced**

Labels may initially be verbose. Later UX passes can compact them only after
semantics are stable.

**Reviewability**

Review should inspect user-visible wording, source-label completeness, and
whether read-only paths stay mutation-free.

**Notes**

- Phase execution should update docs/examples only where diagnostics output is
  already documented and affected.

**Completion Summary**

Phase 14 merged on 2026-05-12:

- Branch: `codex/authority-diagnostics-labeling`
- PR: https://github.com/samcantrill/loom/pull/132
- Target branch: `develop`
- Merge commit: `b19dc70d68381135ff70ab7acac0640866623716`
- Implementation summary: added shared source-label helpers and additive labels
  across backend diagnostics, status/stage/submitted-operation summaries,
  artifact/log summaries, preflight details, run catalog summaries, catalog
  warnings, and CLI text output; moved shared source-label vocabulary to
  `loom.state_sources` after automated review found that `loom.runs` must not
  import `loom.diagnostics`.
- Validation before merge: `make validate-pr` passed; `make test-summary`
  passed with overall 1758 passed, 12 skipped, and 1351 deselected.
- GitHub CI: `checks` succeeded before merge on 2026-05-12.
- Automated review: manager review found one import-boundary blocker, fixed it
  with a neutral shared module and package-boundary regression test, then found
  no remaining blocking scope, correctness, or test-evidence issues.
- Stack maintenance: root phase merged directly to `develop`; no successor
  branch depended on `codex/authority-diagnostics-labeling` at merge time.
- Follow-up notes: Phase 17/18 should reuse the shared source vocabulary when
  attaching real offline evidence and import state.

### Phase 15: Workspace Coordination Service API

- Status: merged
- Branch: `codex/authority-workspace-coordination`
- PR: https://github.com/samcantrill/loom/pull/133

**Goal**

Bring workspace coordination state behind the authority server boundary.

**Scope**

- Add protocol/client/server operations for workspace records, sweep records,
  trial references, run URI references, counters, non-resource coordination
  leases, recovery scans, and diagnostics.
- If the existing workspace coordination protocol exposes resource-limit or
  resource-lease methods before Phase 16, report them as unsupported through
  capability/error responses rather than implementing resource accounting here.
- Adapt existing `WorkspaceCoordinationStore` behavior to a service-backed
  authority path.
- Reuse or migrate private SQLite coordination concepts behind the service
  repository boundary.
- Add conformance tests for workspace coordination through the service boundary.
- Preserve existing coordination semantics unless source review proves a change
  is required.

**Out Of Scope**

- Full sweep orchestration redesign.
- Generic resource leases for scheduler admission.
- Resource-limit and resource-lease accounting, except unsupported capability
  reporting for existing protocol methods.
- Offline evidence writer.
- Hosted multi-workspace coordination service.

**Acceptance Criteria**

- Workspace coordination mutations go through `AuthorityClient`/server APIs in
  online mode.
- Existing sweep/trial/counter/lease semantics remain covered by tests.
- Resource-limit and resource-lease methods exposed by existing coordination
  protocols are either absent from the Phase 15 service capability surface or
  return explicit unsupported-capability errors until Phase 16.
- Recovery scans and diagnostics can identify coordination state source and
  authority generation.
- Direct client mutation of SQLite coordination files is removed or clearly
  limited to private service internals.
- Coordination service behavior composes with existing run authority facts.

**Test Expectations**

- Package: runtime coordination users depend on service/client ports, not
  private SQLite modules.
- Unit: protocol conversion, counter semantics, non-resource lease semantics,
  unsupported resource-lease capability errors, recovery scan classification,
  diagnostics.
- Contract: coordination conformance tests run against fake/in-memory and
  service-backed implementations where appropriate.
- Integration: in-process FastAPI/temp SQLite coordination flows.
- E2E: narrow sweep/trial smoke if already stable and deterministic.
- Opt-in: larger sweep integration tests if needed.

**Design Impact**

This phase unifies run authority and workspace coordination under one service
boundary, reducing split-brain risk between run state and coordination state.

**Future Compatibility**

Keeping coordination behind the same authority client prepares for richer sweep
control and resource admission without a separate coordination daemon.

**Alternatives Rejected**

- Leaving workspace coordination as a separate local DB for online service mode.
- Rewriting sweep semantics in the same phase.
- Treating coordination leases as scheduler resources before generic resource
  leases exist.
- Implementing resource-limit/resource-lease accounting before the dedicated
  resource phase.

**Debt Introduced**

Some legacy local coordination helpers may remain for offline/evidence or test
fixtures if clearly labeled and not used as online authority mutation.

**Reviewability**

Review should focus on preserving existing non-resource coordination semantics,
avoiding split-brain writes, keeping sweep changes out of scope, and ensuring
resource methods fail explicitly until Phase 16.

**Notes**

- Phase execution must inventory current sweep and coordination tests before
  deciding which conformance fixtures to add.

**Completion Summary**

- Phase execution plan: `docs/phases/authority-workspace-coordination.md`
- PR body: `docs/phases/authority-workspace-coordination-pr-body.md`
- Implementation summary: added typed workspace-coordination protocol result
  fields, authority client route constants and methods, mutation service/routes,
  private service-owned coordination state, and a service-backed
  `WorkspaceCoordinationStore` adapter.
- Resource leases and resource limits remain explicitly unsupported through the
  service path until Phase 16.
- Validation: final `make validate-pr` passed; final `make test-summary`
  passed with package 70 passed / 1 skipped, unit 959 passed / 1 skipped,
  contract 151 passed / 2 skipped, integration 128 passed / 8 skipped /
  10 deselected, e2e 39 passed / 2 deselected, and config-extra 422 passed /
  1350 deselected.
- Automated review and merge: manager review found no blocking findings; final
  pre-merge check verified PR #133 targeted `develop`, CI `checks` succeeded,
  and merge state was `CLEAN`.
- Merge: PR #133 squash-merged into `develop` on 2026-05-12 at merge commit
  `01098f9778968b94663d06b38561da9a66b710eb`.
- Stack maintenance: root PR merged into `develop`; no predecessor or successor
  branch.

### Phase 16: Resource Leases And Scheduler-Ready Admission

- Status: pending
- Branch: `codex/authority-resource-leases`
- PR: TBD

**Goal**

Add generic named integer resource leases through the authority/coordinator
boundary and use them for scheduler-ready runner admission.

**Scope**

- Define resource pool, request, grant, lease, release, expiry, recovery, and
  diagnostic protocol values.
- Implement service-backed named integer resource limits and leases.
- Turn any Phase 15 unsupported resource-limit/resource-lease methods into
  supported service-backed resource accounting with conformance tests.
- Add runner-side admission before launching local work, with default fail-fast
  behavior when capacity is unavailable and explicit bounded wait/timeout
  behavior only when requested by the caller.
- Release leases on success/failure and recover stale leases through authority
  recovery behavior.
- Expose scheduler-ready request/decision values for accepted, rejected, and
  blocked/waitable outcomes without implementing a global scheduler.

**Out Of Scope**

- Cluster-wide scheduler replacement.
- Priority queues, fairness policy, or distributed placement.
- Domain-specific resource semantics.
- Offline import.

**Acceptance Criteria**

- Resource leases are generic and domain-neutral.
- Existing workspace coordination resource-limit/resource-lease protocol
  methods, if present, become supported through the authority service in this
  phase.
- Runner admission can request and release named integer resources through the
  authority client.
- Capacity exhaustion fails fast by default with structured diagnostics.
- Explicit bounded wait/timeout policy can wait for capacity and then either
  acquire leases or return a blocked/rejected decision.
- Stale or expired leases are recovered deterministically.
- Admission rejections are visible and actionable.
- Tests prove resource accounting remains correct across success, failure,
  cancellation, default fail-fast rejection, bounded waiting, timeout, and
  recovery cases.

**Test Expectations**

- Package: resource lease users depend on authority/coordinator ports.
- Unit: request validation, capacity accounting, lease grant/release/expiry,
  fail-fast admission, bounded wait/timeout behavior, recovery behavior, and
  admission diagnostics.
- Contract: fake-client and service-backed resource lease conformance,
  including existing workspace coordination resource methods.
- Integration: runner admission with in-process service-backed resources.
- E2E: small local run with resource admission if deterministic.
- Opt-in: scheduler-adapter/resource integration tests if environment-dependent.

**Design Impact**

This phase creates the scheduler-ready admission layer while deliberately
stopping short of scheduler ownership.

**Future Compatibility**

The request/decision model should be able to support future scheduler adapters,
additional resource types, bounded waiting, and richer admission policy.

**Alternatives Rejected**

- Hard-coding CPU/GPU-specific semantics.
- Adding a global scheduler in v10.
- Letting workers self-admit without authority-coordinated leases.
- Unbounded implicit waiting when capacity is unavailable.

**Debt Introduced**

Admission policy remains simple named integer capacity with explicit bounded
waiting only. Fairness, priority, unbounded queues, and distributed placement
are deferred.

**Reviewability**

Review should inspect race behavior, accounting invariants, runner integration,
bounded wait/timeout behavior, default fail-fast diagnostics, and recovery
semantics.

**Notes**

- The phase execution plan should identify existing config fields or CLI inputs
  for resource requests before adding new user-facing configuration.

**Completion Summary**

TBD.

### Phase 17: Offline Evidence Writer

- Status: pending
- Branch: `codex/authority-offline-evidence`
- PR: TBD

**Goal**

Implement explicit offline-first execution evidence so offline runs can later be
imported into authority truth.

**Scope**

- Add explicit offline-first execution mode where no authority truth exists yet.
- Write versioned offline evidence manifests.
- Record execution plan, config/provenance, stage graph/order, input
  fingerprints, attempt terminal states, output references, artifact checksums
  and sizes when local payloads exist, failure/log references, runtime metadata,
  schema versions, and local event/audit logs.
- Support run-local resource coordination evidence for offline execution.
- Add diagnostics that clearly state the run is local evidence, not
  authoritative service state.

**Out Of Scope**

- Importing evidence into the authority service.
- Best-effort legacy run reconstruction.
- Converting existing deferred-finalization envelopes into offline evidence
  manifests.
- Cryptographic attestation.
- Remote artifact movement.
- Online authority mutation behavior.

**Acceptance Criteria**

- Explicit offline-first runs produce a versioned evidence manifest.
- Manifest data is sufficient for the Phase 18 equivalence checker to validate
  execution identity, stage order, terminal states, outputs, and artifact facts.
- Offline diagnostics never describe evidence as authority truth.
- Incomplete local evidence is detected and labeled.
- Online mode does not write offline evidence as a fallback for authority
  failure.

**Test Expectations**

- Package: offline evidence writer does not import server repository internals.
- Unit: manifest schema validation, fingerprint/checksum capture, event log
  ordering, incomplete evidence diagnostics, offline resource evidence.
- Contract: manifest golden-shape tests and compatibility checks.
- Integration: small offline-first run producing evidence in a temp workspace.
- E2E: deterministic CLI offline run smoke if stable.
- Opt-in: large artifact checksum or filesystem-heavy tests if needed.

**Design Impact**

This phase defines the only evidence shape that v10 import will trust. It must
be strict enough to reject ambiguous history.

**Future Compatibility**

Manifest versioning should allow later stronger verification, additional
artifact stores, and richer provenance without accepting underspecified v10
evidence.

**Alternatives Rejected**

- Reconstructing evidence from arbitrary run directories.
- Writing evidence only as human-readable logs.
- Treating failed online authority mutation as permission to continue offline
  without explicit mode selection.
- Treating deferred-finalization envelopes as v10 offline evidence.

**Debt Introduced**

Offline evidence cannot become authority truth until Phase 18. Existing
deferred-finalization envelopes remain a separate weaker profile.

**Reviewability**

Review should inspect manifest completeness, source labeling, schema versioning,
and the absence of online fallback behavior.

**Notes**

- Phase execution should include fixture manifests that Phase 18 can reuse.

**Completion Summary**

TBD.

### Phase 18: Offline Import Transaction

- Status: pending
- Branch: `codex/authority-offline-import`
- PR: TBD

**Goal**

Import accepted v10 offline evidence manifests into the authority service
atomically, with clear provenance and strict rejection behavior.

**Scope**

- Add import API and CLI surface.
- Implement a strong equivalence checker for v10-created evidence manifests.
- Validate execution plan, config/provenance, stage graph/order, input
  fingerprints, attempt states, outputs, artifact facts, failures/logs, runtime
  metadata, and schema versions.
- Reject incomplete, conflicting, stale, unsafe, schema-incompatible, or non-v10
  evidence.
- Define strict collision rejection for existing target run identities, with
  conflict diagnostics and no v10 overwrite/fork behavior.
- Import accepted evidence into the authority repository in a single atomic
  transaction as accepted authority facts plus import provenance and a
  replay-level evidence/audit timeline.
- Expose import provenance in status, catalog, diagnostics, and read models.

**Out Of Scope**

- Legacy/pre-v10 import.
- Best-effort repair of incomplete evidence.
- Import or conversion of existing deferred-finalization envelopes.
- Remote artifact upload or payload copying.
- Domain-specific semantic equivalence.
- Global scheduler behavior.

**Acceptance Criteria**

- Import accepts only complete, compatible v10 evidence manifests.
- Rejected evidence reports concrete rejection reasons without mutating
  authority state.
- Accepted imports create authoritative run/stage/attempt/output/artifact facts
  with import provenance and replay-level offline evidence history.
- If the target run identity already exists, import rejects before mutation.
- Import is atomic: partial import cannot be observed after validation failure
  or transaction failure.
- Status/catalog/diagnostics clearly distinguish imported authority state from
  live online authority state where relevant.
- Tests cover accepted import, every major rejection class, collision policy,
  and rollback behavior.

**Test Expectations**

- Package: import CLI/API uses service/client/repository boundaries correctly;
  clients still do not mutate SQLite directly.
- Unit: equivalence checker, schema compatibility, collision policy, rejection
  diagnostics, provenance mapping.
- Contract: manifest compatibility and import protocol conformance.
- Integration: import fixture manifests into temp service-backed repository and
  read back authority state.
- E2E: CLI import smoke using Phase 17 offline evidence fixture if stable.
- Opt-in: large-artifact or slow filesystem import tests if needed.

**Design Impact**

This phase completes v10 by making offline execution useful without weakening
authority truth. It is intentionally strict and should prefer rejection over
ambiguous mutation.

**Future Compatibility**

Import provenance and manifest versioning should allow later migration tools,
stronger verification, and richer artifact backends without treating current
manifests as ad hoc directories.

**Alternatives Rejected**

- Best-effort import of old local run directories.
- Importing deferred-finalization envelopes as if they were true offline runs.
- Importing partial evidence and marking missing data as unknown.
- Adding a separate imported lifecycle state before proving it is necessary.
- Overwriting or forking an existing authority run on import collision.

**Debt Introduced**

No legacy import path, deferred-envelope import path, or collision-resolution
path is provided. If users need migration, repair, replacement, deferred-envelope
conversion, or archival import later, it should be a separate workflow with
explicit risk labeling.

**Reviewability**

Review should focus on atomicity, rejection coverage, collision policy,
provenance visibility, and evidence/schema compatibility.

**Notes**

- Phase execution should reuse Phase 17 fixture manifests and add intentionally
  invalid fixtures for each rejection class.

**Completion Summary**

TBD.

## Cross-Phase Review Notes

- Phase plans must record branch, stack predecessor, base branch, PR target
  branch, and worktree path before implementation begins.
- Phase plans must include design impact, future compatibility, alternatives
  rejected, debt introduced, reviewability, and budget status.
- Expanded path is expected for most v10 phases because the work touches public
  protocol, persistence, resolver policy, runtime execution, SLURM behavior,
  workspace coordination, and offline import semantics.
- Each phase should implement only its assigned scope and avoid future-phase
  behavior, even when adjacent source files are nearby.
- The managing agent must update phase status in this plan using only:
  `pending`, `in_progress`, `pr_open`, `approved`, `merged`, or `blocked`.
- PR preparation for each phase must summarize suite evidence from `make
  validate-pr` and `make test-summary`, or record exact blockers.
