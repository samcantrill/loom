# Phase 1 Execution Plan: Scheduling Kernel And Ready-Stage Work

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 1
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p1-scheduling-kernel-ready-stage-work`
- Worktree root: `/home/can134/work/active/loom-worktrees`; phase path:
  `stage-29-p1-scheduling-kernel-ready-stage-work`
- Base revision: `24b5d210a258bed2a7ab87973aadefecefd6d753` (clean
  `origin/develop`)
- PR target: `develop`
- PR title: `feat(scheduling): add kernel and durable ready-stage work`
- Dependencies: implemented pipeline planner, per-run authority, runtime resource
  requests, Stage 25 policy-validation patterns, and Stage 28 explicit extension
  composition/conformance patterns
- Workflow path: expanded because this phase establishes subsystem-public
  extension contracts, one authority-owned attempt-preparation transition, and
  one new durable coordinator projection
- Blockers: none

## Objective And Context

- Vertical outcome: Loom has one authoritative answer to “which exact stage
  attempts are ready?” and one pure deterministic answer to “where could this
  already-ready attempt fit?” Every semantic ready attempt in the bounded
  reconciliation window can be represented by a durable
  `StageWorkRecord` projection and evaluated against an immutable local
  resource snapshot without reserving capacity, binding the attempt to an
  assignment, or launching a process. The authority idempotently creates or
  returns the exact `PENDING` attempt before the projection names it.
- Earlier dependency: current `PipelineRunner` already evaluates dependency
  readiness in memory, runtime resources already validate `ResourceRequest`, and
  the authority already persists plans, attempts, statuses, and output commits.
  This phase extracts those semantics instead of inventing replacements.
- Later work explicitly out of scope: Phase 2 owns every execution side effect
  from logical reservation through local process release, including worker
  request/input materialization. Phase 3 owns daemon/public facade migration.
  Phases 4–9 own remote trust, transport, GPU placement, explicit ready-stage
  SLURM delegation, controls, and recovery.

This is the one deliberate foundation phase in the nine-phase plan. Its
boundary is safe to merge independently because the kernel is pure, authority
adds only the idempotent semantic preparation of a `PENDING` attempt as a new
lifecycle operation, existing authority-owned controller actions remain in
their current semantic owners, and stage work is a rebuildable projection.
Existing execution remains
callable, but all current and future managed paths must consume the extracted
readiness predicate rather than retain a second DAG interpretation.

## Current Source And Harness

- Relevant seams to rediscover on the phase branch:
  - pipeline planning models and `PlanAction` handling;
  - `PipelineRunner` readiness/parallel-stage loop;
  - prepared-stage attempt and authority status/output queries;
  - `StageSpec.resource_request`, exact-stage runtime options, and
    `ResourceRequest` validators;
  - queue ordering and injected-policy result validation;
  - Stage 28 instance-local registries, activation manifests, and
    `loom.testing` reports.
- Rediscovery at base `24b5d21` found these exact source owners:
  - `src/loom/pipeline/execution/runner.py` owns the serial/parallel execution
    loops, controller-only `PlanAction` transitions, and the current parallel
    `_next_ready_stage` dependency check;
  - `src/loom/pipeline/execution/stage_attempts.py` owns the current local-only
    `prepare_stage_attempt`, while `src/loom/pipeline/stores/authority.py`,
    `src/loom/pipeline/stores/sqlite_authority.py`,
    `src/loom/authority/_repository.py`, and
    `src/loom/authority/mutation_service.py` own the present allocation
    protocols and adapters;
  - `src/loom/pipeline/resources.py` owns the existing authored/runtime resource
    codec and validator registry; exact-stage options are resolved under
    `src/loom/pipeline/runtime/`;
  - `src/loom/queue/selection.py` is the current fixed-eligibility/injected-
    preference validation precedent, while
    `src/loom/pipeline/executors/base.py` and
    `src/loom/pipeline/runtime/capabilities.py` provide the Stage 28
    instance-local registry/descriptor patterns; and
  - `src/loom/testing/checks.py` and `src/loom/testing/reports.py` own current
    bounded conformance checks and immutable reports.
- Existing focused regression suites are
  `tests/unit/loom/pipeline/execution/test_runner.py`,
  `tests/unit/loom/pipeline/execution/test_stage_attempts.py`,
  `tests/unit/loom/pipeline/planning/`,
  `tests/unit/loom/pipeline/test_runtime_resources.py`,
  `tests/unit/loom/pipeline/stores/test_sqlite_authority.py`,
  `tests/unit/loom/authority/test_repository_stage_lifecycle.py`,
  `tests/contracts/test_authority_store_contract.py`,
  `tests/contracts/test_authority_repository_contract.py`,
  `tests/unit/loom/testing/test_contracts.py`, and the package import/API suites.
- Current `prepare_stage_attempt` is not the Phase 1 authority operation: it
  requires local run-store path helpers and combines attempt numbering, bound
  inputs/fingerprint, workspace creation, worker-request persistence, and
  reliability records. Split semantic attempt preparation from Phase 2 local
  execution materialization rather than moving that helper wholesale.
- Current `PerRunAuthorityStore.allocate_stage_attempt` and its SQLite adapter
  move an attempt to `RUNNING` and may create a stage lease. Stage 29 requires a
  distinct expected-state/idempotent preparation operation that leaves the
  exact attempt `PENDING` and unassigned; the existing allocation semantics must
  not be reused unchanged.
- Both authority implementations use versioned SQLite schemas and already
  contain historical attempt rows created by the current execution paths. Any
  schema change needed for preparation identity/readiness evidence must preserve
  those rows and the existing allocation path. A historical `PENDING` attempt
  that lacks Stage 29 preparation identity is not silently adopted or
  backfilled as schedulable work; it remains with its current compatibility or
  recovery owner unless an explicit authority operation can reconcile it under
  the fixed expected state. No generic migration registry or placeholder
  coordinator history is required for this phase.
- Existing tests to reuse include planner DAG tests, runner dependency/reuse/
  failure tests, runtime-resource validation, queue ordering, protocol import
  tests, and extension conformance tests.
- `loom.scheduling` must remain import-light. It may depend on core typed values
  and standard-library protocols, but not `loom.pipeline` at runtime, queue
  repositories, authority clients, SQLite, artifacts, routes, processes,
  executors, project code, vendor SDKs, or CLI modules. Today
  `loom.pipeline.__init__` eagerly imports runtime, so importing
  `loom.pipeline.resources` from scheduling would create a real cycle once
  runtime consumes scheduling.
- The phase executor must start from the existing end-to-end readiness path and
  preserve unrelated work. Suggested private module names are not contracts.

## Scope

In scope:

- Add one `ResolvedStagePlacement` construction path that combines:
  - authored stage `ResourceRequest` as semantic minima;
  - exact-stage runtime refinements that cannot weaken those minima;
  - run and pool defaults that affect this stage's placement, including pool and
    optional target/default resource policy;
  - site-owned hard limits, allowed kinds, preference weights, and search bounds;
  - one closed immutable execution route: default `managed_agent`, or an
    explicitly named site-authorized `slurm` profile descriptor/fingerprint.
    Route/profile identity enters the placement fingerprint. No resource,
    candidate, preference, elapsed wait, or availability state may infer or
    change it. This phase defines/resolves the route value only; Phase 7 owns
    SLURM request mapping, admission, submission, and bootstrap execution.
- Keep `max_parallel_stages` as separate assignment-admission policy. It does
  not hide dependency-ready unassigned work and is not a resource request,
  placement rule, preference, or part of the `ResolvedStagePlacement`
  fingerprint. Phase 1 projects all semantic ready work in its bounded window;
  Phase 2 atomically enforces the limit when reserving an assignment.
- Keep authored/runtime resource validation owned by the existing
  `ResourceValidator` contract. A higher-level pipeline-runtime adapter converts
  canonical validated `ResourceEntry` values to scheduling-owned immutable
  entry views. A `ResourcePlanner` receives those views and owns scheduling-time
  merge, canonical validation of an inventory/availability opportunity,
  intrinsic quantity/unit/mode/per-instance/same-resource-topology feasibility,
  complete exact-claim search, claim validation, and safe failure explanations.
  Runtime validates/rebuilds the canonical existing `ResourceRequest` for the
  resolved placement. The view is not a second authored or durable schema;
  durable resolved resources retain validator and planner descriptors separately.
- Add import-light immutable/versioned scheduling values for exact quantities,
  inventory and availability snapshots, capacity atoms, claims, candidates,
  explanations, tagged hard/preference specs, selected decisions, and closed
  result states.
- Add public subsystem-level structural protocols:
  - `ResourcePlanner` for one resource kind;
  - `HardConstraintEvaluator` for additive candidate rejection;
  - `PreferenceScorer` for bounded scoring of already-feasible candidates;
  - `SchedulingPolicy` for selecting one existing validated candidate or wait.
- Add one concrete `SchedulingKernel` that owns mandatory eligibility checks,
  complete bounded per-resource/composite candidate orchestration,
  deterministic ordering, hard-before-soft evaluation, site-tier preference
  aggregation, durable-time fallback eligibility, grouped-work proposal
  validation, stable tie-breaking, and mutation exclusion.
  There is no replaceable lifecycle scheduler.
- Provide deterministic built-in CPU and memory planner implementations through
  the pipeline-runtime integration layer, plus scheduling-owned built-in target/
  attribute hard rules, neutral/default preference behavior, and default FIFO-
  with-safe-bypass scheduling policy. CPU accepts positive integers only;
  memory normalizes to integer bytes. The concrete planners implement the public
  scheduling protocol without reversing the package dependency.
- Add immutable `SchedulingComponentDescriptor` and
  `ResourceClaimContractDescriptor` values. Component identity includes contract
  version, implementation version/fingerprint, non-secret canonical
  configuration fingerprint, and supported data versions. Planner and eventual
  provider identities remain distinct from their negotiated wire claim contract.
- Add explicit instance-local configuration-epoch registries. Registration is
  duplicate-safe; composition is trusted deployment code; registries freeze
  before work is admitted. They distinguish active bindings for fresh
  resolution from exact descriptor-keyed retained bindings for referenced
  nonterminal work or live claims; a reconstruction/reload that cannot retain
  a required descriptor fails closed. Submitted/durable data can select only an
  allowed registered kind and can never import or deserialize an implementation.
- Add bounded `loom.testing` conformance checks for the four pure protocols.
  Checks use caller-supplied semantic samples and cannot discover code, access
  hardware, certify termination, or replace kernel validation.
- Extract one import-light authority-side readiness predicate over persisted
  plan, exact attempt state, committed upstream results/outputs, cancellation,
  and retry facts. Use it from `PipelineRunner`, the new orchestrator, and the
  later authority assignment revalidation seam.
- Extend the per-run authority with one semantic expected-state operation for
  ready-stage preparation. In one authority transaction it revalidates the
  readiness generation, creates the next exact attempt once or returns the
  already-prepared attempt for the same idempotency identity, records immutable
  bound-input/readiness evidence, and leaves the attempt `PENDING` without an
  execution lease or assignment. Only authority/reliability facts may authorize
  a fresh attempt generation.
- Add a durable `RunOrchestrator` reconciliation step that:
  - resolves REUSE, SKIP, and blocked actions without agent capacity by invoking
    the existing authority-owned action/output/lifecycle semantics rather than
    copying their truth into coordinator state;
  - invokes that authority operation for only ready `PlanAction.RUN` stages;
  - projects all semantic ready work in the bounded window without consuming a
    per-run parallel-stage slot;
  - materializes or refreshes rebuildable `StageWorkRecord` projections;
  - blocks descendants or derives run completion from authority truth.
- Add the stage-work subset of a semantic coordinator-state store protocol, with
  SQLite production and in-memory test implementations. It exposes atomic
  domain operations rather than generic CRUD. Stage work stores attempt,
  readiness/order evidence, upstream commit identities, resolved-placement
  fingerprint, and scheduling diagnostic state, but never owns stage success,
  output truth, or retry decisions. Its immutable semantic key includes the
  admitted-run identity, stage, attempt, and readiness generation. Create-or-
  return must reproduce one stable `stage_work_id`; rebuild may refresh a
  projection revision but cannot re-key or discard a record referenced by an
  assignment, control, event, or retained component binding.
- Produce scheduling decisions and explanations from immutable snapshots for
  tests and later coordinator use. Phase 1 must not persist a reservation or
  assignment and must not call a resource provider, artifact adapter, or
  launcher.

Out of scope:

- Coordinator reservation, authority bind/unbind/grant, agent journal,
  `AgentResourceProvider`, local artifact staging, executor invocation, or
  release. Phase 2 owns them as one causal saga.
- Persistent daemon/client lifetime, process role locks, public queue migration,
  remote protocols, mTLS, offers, GPU inventory, artifact bytes, cancellation
  controls, or recovery.
- SLURM command invocation, scheduler-capacity modeling, directive/request
  mapping, submission records, bootstrap credentials, external status/cancel,
  automatic agent/SLURM fallback, or allocation-fed agents. Phase 7 fills only
  the already-resolved explicit SLURM route.
- Fair-share, preemption, gang/distributed stages, general constraint solver,
  process-global registry, automatic plugin loading, payload-selected callables,
  proof-carrying partial search, or root-level `Scheduler` re-export.

These exclusions are structural, not synonyms for features already present.
The completed managed-agent path may place different pipeline stages on
different agents, but one managed `Candidate` fits one exact stage wholly on
one agent. An explicit SLURM-routed stage is not an agent candidate and is
handled by Phase 7 after readiness. A distributed
stage/gang proposal would combine several agents and require all-or-none batch
reservation and group launch/failure semantics. Priority selects unstarted work;
preemption would checkpoint/stop and release an existing assignment. Fair-share
would add durable user/project usage and entitlement accounting rather than a
placement score. A general constraint solver would optimize variables for
several work items/agents and return a snapshot-bound batch, rather than choose
one existing validated pair. None may be implemented behind the current scorer
or policy protocols without an accepted owner and mutation contract.

Assumptions:

- Authored project/deployment configuration is trusted. Runtime/API/durable data
  is versioned inert data.
- A candidate describes one complete stage placement on one agent. Multi-agent
  or global transactional resources remain out of scope.
- Existing whole-run execution can remain during this phase only as a
  compatibility path; it must consume the shared readiness predicate and cannot
  become a second source of readiness semantics.

## Fixed Contracts And Private Discretion

### Pure extension boundary

The shape is structural rather than inheritance-based:

```python
class ResourcePlanner(Protocol):
    descriptor: SchedulingComponentDescriptor
    resource_kind: str
    claim_contracts: tuple[ResourceClaimContractDescriptor, ...]

    def resolve_request(
        self,
        authored: ValidatedResourceEntryView | None,
        runtime: ValidatedResourceEntryView | None,
    ) -> ResourceRequestResolution: ...

    def validate_opportunity(
        self,
        inventory: ResourceInventoryEnvelope,
        availability: ResourceAvailabilityEnvelope,
    ) -> OpportunityValidationResult: ...

    def propose_claims(
        self,
        request: ResolvedResourceRequest,
        opportunity: ValidatedResourceOpportunity,
        budget: ClaimSearchBudget,
    ) -> ClaimSearchResult: ...

    def validate_claim(
        self,
        request: ResolvedResourceRequest,
        claim: ResourceClaim,
    ) -> ClaimValidationResult: ...


class SchedulingPolicy(Protocol):
    descriptor: SchedulingComponentDescriptor

    def select(
        self,
        context: PolicyContext,
    ) -> PolicyDecision: ...
```

The final names may follow repository conventions, but the authority limits are
fixed. A planner validates its opportunity, proposes a complete exact-claim
result, and validates each claim. Hard rules only reject complete placements;
preferences return bounded utility/quality-band contributions; policy sees a
bounded tuple of grouped `WorkEvaluation` values and selects one existing
`(stage_work_id, candidate_id)` or waits.
None receives a store, live clock, network client, authority, or launcher.
`ValidatedResourceEntryView` is an immutable scheduling input, not an authored
codec; `loom.pipeline.runtime` owns conversion from and back to the existing
validated `ResourceEntry`/`ResourceRequest` values.

This is the first `loom.scheduling` public surface, so there is no legacy
scheduler API to migrate or alias. Export only the approved protocols, their
required immutable boundary values, and the fixed kernel from that subsystem;
do not add a root-package facade, compatibility shim, abstract lifecycle
scheduler, or public registry base. Method decomposition, helper classes, and
intermediate candidate/search representations that are not needed in protocol
annotations or durable codecs remain private.

All ambiguity is represented explicitly:

```text
resource resolution  = ABSENT | RESOLVED | INVALID
opportunity validation = VALID | INVALID
claim search          = COMPLETE | EXHAUSTED
claim validation      = VALID | INVALID
rule-spec resolution  = RESOLVED | INVALID
hard evaluation       = PASS | REJECT | INDETERMINATE
preference evaluation = SCORE(utility, quality_band) | INDETERMINATE
policy selection      = SELECT | WAIT
```

`None`, an empty iterable, an exception, an unknown work/candidate pair, a
missing required evaluation, oversized output, or search-budget exhaustion must
never be interpreted as infeasibility or permission to mutate. Every resource
search and the composite product must report `COMPLETE` before any candidate
for that work is assignable. `EXHAUSTED` stays indeterminate; Stage 29 accepts
no planner-supplied winner proof. The default policy may bypass that work for a
later complete feasible item without relabelling the older work.

Preference resolution assigns immutable IDs, site-owned ordered tiers, bounded
weights, utility ranges, and optional quality-band schemas. The kernel uses
checked integer multiplication/addition to form one total per tier and compares
the vector lexicographically, followed by a stable identity tie-break. An
optional fallback gate names one guarded preference: before
`ready_at + wait_duration`, evaluated at the snapshot's explicit `as_of`, only
its `PREFERRED` band is selectable; afterward declared `FALLBACK` candidates
re-enter. Policy cannot bypass this gate, and vectors are comparable only among
candidates for the same work.

### Capacity and component identity

A proposed claim exposes coordinator-accountable atoms separately from trusted
provider-specific data:

```python
@dataclass(frozen=True)
class CapacityAtom:
    owner_resource_kind: str
    local_capacity_key: str
    amount: ExactQuantity
    unit: str
    granularity: ExactQuantity


@dataclass(frozen=True)
class ResourceClaim:
    resource_kind: str
    contract: ResourceClaimContractDescriptor
    atoms: tuple[CapacityAtom, ...]
    provider_data_version: int
    provider_data: Mapping[str, PlainData]
```

The kernel validates namespace ownership, uniqueness, positivity, exact unit and
granularity, normalization, bounds, snapshot revision, and contract shape. A
planner may consume only atoms in its own resource namespace; cross-resource
requirements are evaluated only after a complete placement exists. Provider
data cannot be used as hidden accounting.
The trusted planner/provider pair owns resource-specific semantics and final
binding; Loom does not claim to sandbox a dishonest implementation.

### Prepared attempt and ready-stage projection

The readiness predicate remains the sole semantic owner:

```python
ready = evaluate_attempt_readiness(
    plan=authority.plan(run_uri),
    attempt=authority.current_attempt(run_uri, stage_name),
    committed_outputs=authority.committed_outputs(run_uri),
    cancellation=authority.cancellation(run_uri),
)

if ready.action is PlanAction.RUN:
    prepared = authority.ensure_prepared_attempt(
        expected_readiness=ready.evidence,
        preparation_id=ready.preparation_id,
        bound_inputs=ready.bound_inputs,
    )
    coordinator.reconcile_stage_work(
        ready=ready,
        attempt=prepared.attempt,
        placement=resolved_placement,
    )
```

The name above is illustrative; the contract is the atomic behavior. Replaying
the same preparation identity returns the same exact `PENDING` attempt. A
changed readiness generation, terminal fact, or unauthorized retry fails
closed rather than allocating another attempt.

The prepared attempt and its bound-input/readiness evidence are authority truth.
`StageWorkRecord` content is disposable and rebuildable, but its identity is
stable for the immutable semantic key. If it disagrees with authority, authority
wins and reconciliation repairs or retires only an unreferenced projection;
referenced stale work remains joinable and ineligible until its owners reconcile.
A scheduler decision derived from it is data only and is stale as soon as any
input version changes. Phase 1 creates no workspace, worker request, resource
claim, assignment, execution lease, artifact transfer, or process.
REUSE/SKIP/BLOCKED reconciliation may still perform the pre-existing
authority-owned controller transitions and output-reference commits required by
the execution plan; those are not new scheduler-owned lifecycle mutations.

Preparation is the one Phase 1 cross-store causal chain:

1. The coordinator durably creates or returns a narrow preparation intent with
   one stable operation ID and request digest derived from the admitted run,
   stage, readiness generation, expected authority state, and bound-input
   evidence.
2. The authority revalidates that expected state and, in one transaction,
   creates or returns the exact `PENDING` attempt and commits the matching
   operation receipt. Exact replay returns the same attempt; the same operation
   ID with a different digest, a changed generation, a terminal fact, or a
   retry not authorized by authority facts fails closed.
3. Only the confirmed authority result may create or refresh the
   `StageWorkRecord`; its semantic key uses that exact attempt and readiness
   generation. A crash after either durable commit is repaired by replaying the
   same operation, never by allocating a new attempt or deriving identity from
   coordinator projection state.

This requires only semantic intent/create-or-return operations in the Phase 1
coordinator-store subset, not a generic outbox, saga framework, transport
adapter, or lifecycle service. Phase 1 uses an internal direct composition and
exposes no caller-controlled identity; Phase 3 owns the captured-principal,
authorizer, and scoped coordinator-authority application boundary, and Phase 4
adds authenticated remote transport. Likewise, later-phase assignment/control/
event references constrain future deletion and re-keying, but Phase 1 must not
add placeholder tables or a generic reference registry for them. Its store
simply exposes no operation that re-keys an existing semantic record, and it
retains descriptor references that current Phase 1 work actually records.

### Private discretion

The executor may choose private module names, indexes, batching strategy,
internal candidate representation, and diagnostic aggregation. It may simplify
helpers aggressively. It may not change public protocol authority, closed
outcomes, identity separation, readiness ownership, or the no-execution-side-
effect boundary.

## Proportionality

- Existing seams reused: `ResourceRequest`, validators, execution plans,
  authority queries, queue policy validation, registries, and conformance
  reports.
- Material additions: one pure scheduling package, one narrow authority
  preparation operation, and one rebuildable durable projection, each required
  by the accepted per-stage/global scheduler.
- Deliberately deferred: reservation/lifecycle plugin APIs, resource discovery,
  a constraint DSL, general solver, and any process/network behavior.
- The foundation-phase exception is justified by review size and safety: it
  establishes the public pure contract and the sole readiness owner before any
  side-effecting consumer can depend on them.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| One readiness interpretation | Shared authority-side predicate | Existing runner and new orchestrator | Dependency bypass or divergent restart | DAG, reuse, failure, retry, and cancellation tests call both consumers |
| One exact prepared attempt per readiness generation | Coordinator preparation-intent transaction plus per-run authority preparation/receipt transaction | Crash before send, response loss after authority commit, replay, restart, or concurrent reconcilers | Duplicate attempts, unexplained authority mutation, or skipped retry ownership | Persist-before-call, expected-state/digest conflict, post-commit response-loss, concurrency, and restart tests |
| Rebuild preserves stage-work identity | Coordinator stage-work transaction | Projection refresh, store reopen, or changed diagnostics | Orphan assignment/event or duplicate work | Deterministic/create-or-return identity, referenced-retention, and rebuild tests |
| Historical attempts are not reinterpreted as prepared work | Authority schema migration and preparation operation | Existing `PENDING`/`RUNNING` rows without a readiness-generation receipt | An old execution becomes newly schedulable or changes lifecycle ownership | Pre-migration fixture/open, unchanged-row, compatibility-allocation, and no-implicit-backfill tests |
| Controller-only actions retain authority ownership | Existing plan-action/authority operations | New orchestrator projection | Reuse/skip/block truth duplicated or descendant unlocked early | Existing runner/orchestrator trace-equivalence and output-commit tests |
| Authored minima cannot be weakened | Runtime placement resolver and resource planner | Exact-stage runtime policy | Under-requested execution | Merge/property/boundary tests |
| Resource opportunity and intrinsic feasibility have one owner | Resource planner plus kernel envelope checks | Custom inventory/availability and planner result | Repeated parser failure, unit disagreement, or duplicate GPU/resource rules | Malformed-opportunity, intrinsic-semantics, and claim-validation conformance tests |
| Assignment uses only a complete search product | `SchedulingKernel` | Bounded custom planner or composite product | An omitted candidate could be the feasible/preferred winner | Per-resource/product exhaustion, boundary, permutation, and no-mutation tests |
| Mandatory feasibility cannot be overridden | `SchedulingKernel` | Custom rule/policy result | Invalid placement | Invalid-output and mutation-sentinel tests |
| Preference cannot create feasibility or violate site precedence/fallback | Kernel hard-before-soft, tier aggregation, and fallback gate | Custom scorer/policy or restart-relative time | OOM, client weight escalation, overflow, or early fallback | Feasibility-neutrality, tier, overflow, band, durable-time restart, and stable-tie tests |
| Policy preserves work boundaries | Kernel-created grouped `WorkEvaluation` context | Custom cross-work policy | Comparing unrelated score vectors or selecting exhausted work | Unknown-pair, cross-work, typed-wait, and safe-bypass tests |
| Ready projection does not consume a run slot | Orchestrator projection; Phase 2 assignment transaction owns enforcement | Multiple ready branches | Compatible capacity idles or later cycles over-admit | Blocked-first-branch projection and Phase 2 hand-off tests |
| Stage work is not lifecycle truth | Coordinator projection reconciler | Stale/crashed projection writer | False readiness/terminal status | Restart and authority-disagreement tests |
| Component selection is inert and reconstructable | Epoch-frozen active/retained registry composition root | Runtime/durable payload or config reload | Code loading, semantic reinterpretation, or stranded pending work | Codec/import/unknown-ID plus pending-reference restart/reload tests |
| Built-in decisions are deterministic | Kernel/default policy | Mapping/registration order | Irreproducible placement | Permutation and stable-tie tests |
| Phase 1 cannot launch | Composition boundary | Accidental executor/provider dependency | Side effect before saga exists | Dependency/import checks and launcher sentinel |

## Implementation Slices

1. Add exact quantity, component/claim-contract descriptors, closed result
   values, active/retained epoch registries, four pure protocols, CPU/memory/
   default rule and policy implementations, and `loom.testing` conformance.
2. Implement `ResolvedStagePlacement` parsing/resolution and the fixed pure
   kernel with opportunity/claim validation, complete-only claim/product
   search, mandatory checks, checked site-tier preference vectors, quality-band
   fallback, grouped work evaluations, deterministic FIFO-with-safe-bypass,
   explanations, and proposal validation.
3. Extract the shared readiness predicate and route existing runner readiness
   through it; split semantic `PENDING` attempt preparation from the current
   local worker-materialization helper; add the minimal coordinator preparation-
   intent operation, atomic authority receipt, controller-action reconciliation,
   and durable `StageWorkRecord`/store operations. Preserve historical attempts
   without inventing preparation evidence or later-phase reference tables.
4. Integrate orchestrator-to-snapshot-to-decision without reservation or launch;
   add restart/rebuild, downstream custom-component, import, and no-mutation
   evidence plus canonical documentation/public exports.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Cheap intentional exports and dependency direction | In a fresh interpreter import and resolve the public `loom.scheduling` protocol annotations without loading `loom.pipeline`, runtime/network/database modules; no root re-export; pipeline-runtime adapter imports scheduling in the allowed direction |
| Unit | Required | Quantities, resolution, search completeness, rule order, preference algebra, bounds, deterministic selection | Integer CPU, byte memory, invalid fractions, namespaced atoms, hard-before-soft, tier dominance, checked overflow, bands/fallback at durable `as_of`, stable ties, `EXHAUSTED` versus infeasible |
| Contract | Required | Downstream protocol authority and fail-closed output | Synthetic planner/rule/scorer/policy; malformed opportunity/claim, incomplete search, invalid work/candidate pair, exceptions, oversize, mutation sentinels, descriptor drift, retained-binding reconstruction |
| Integration | Required | Authority preparation, readiness, and durable projection | Train/evaluate, diamond, blocked-first-branch visibility, reuse/skip/failure/retry; persist intent then inject failure before authority call, after authority commit/before the caller receives the result, and after receipt of that result/before projection, with replay producing one `PENDING` attempt, one matching receipt, and the exact same `stage_work_id`; concurrent changed-state/digest conflict; no projection-time parallel-slot suppression |
| Migration/reopen | Required | Existing authority data and new projection durability | Open a pre-change authority fixture without changing historical attempt identity/status or manufacturing preparation evidence; current allocation remains compatible; create/reopen/rebuild the new coordinator store with stable IDs and strict unsupported-version failure. Do not synthesize assignment/control/event references that Phase 1 does not own |
| E2E / opt-in | Deferred | No process or external system is allowed in Phase 1 | Phase 2 owns the first execution E2E; assert launcher/provider/transport sentinels remain untouched |

Targeted development commands use the repository's locked development
environment and the exact affected suites, with new Stage 29 paths added beside
their owning behavior:

    uv run --locked --group dev pytest tests/unit/loom/scheduling tests/unit/loom/pipeline/test_runtime_resources.py tests/unit/loom/pipeline/planning tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/execution/test_stage_attempts.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/unit/loom/authority/test_repository_stage_lifecycle.py tests/unit/loom/testing/test_contracts.py
    uv run --locked --group dev pytest tests/contracts/test_authority_store_contract.py tests/contracts/test_authority_repository_contract.py tests/package/test_import_boundaries.py tests/package/test_pipeline_planning_api.py tests/package/test_pipeline_store_api.py tests/package/test_testing_api.py

The executor may split these commands while developing and must update paths if
new tests are placed at a more specific existing owner. The stable final gate is
unchanged.
Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: accidentally exposing a broad scheduler API; retaining two
  readiness interpreters; treating incomplete search as infeasible; allowing
  custom output to bypass mandatory checks; duplicating intrinsic resource
  semantics in hard rules; using undefined scalar preference precedence;
  comparing scores across work items; making stage work authoritative or
  re-keying it during rebuild; projecting before the authority preparation
  receipt is durable; retrying preparation under a fresh operation identity
  after an indeterminate result; manufacturing readiness evidence for legacy
  attempts or scaffolding later-phase reference owners;
  importing pipeline resources into the pure subsystem and creating a cycle; or
  reusing the current `RUNNING`/lease allocation semantics for preparation.
- Review focus: import direction, immutable closed values, explicit registry
  epochs/retention, opportunity/claim validation, complete search, preference/
  fallback algebra, grouped policy result validation, readiness extraction,
  persist-intent/authority-receipt/projection ordering, exact-attempt/stage-work
  identity idempotency, preservation of historical attempts, and absence of
  execution side effects or later-phase placeholder machinery.
- Stop if: canonical runtime requests cannot be composed without weakening;
  readiness cannot be shared without a public behavior change; stage work would
  need to own lifecycle truth; an exact `PENDING` attempt cannot be prepared
  atomically with its operation receipt and without taking an execution lease;
  preserving historical attempts requires inventing readiness/preparation
  evidence; the stage-work semantic key cannot be reproduced solely from the
  confirmed authority result and admitted-run identity; a pure protocol requires
  a live store/launcher or runtime import of `loom.pipeline`; or a required
  quantity cannot be represented exactly.
- Accepted debt: complete bounded enumeration can leave a large work item
  `EXHAUSTED`, and FIFO-with-safe-bypass may be suboptimal. Revisit proof-
  carrying partial search or fairness only with measured workloads.

## Executor Handoff

- Read: this file in full, the Stage 29 manifest shared constraints, planning
  FR-2–FR-9 and FR-22–FR-24, and current source/tests discovered on the phase
  branch.
- Safe implementation order: the four slices above. Preserve a runnable test
  tree after each slice and do not implement Phase 2 assignment operations.
- Decisions not to revisit: fixed kernel, narrow protocols, complete-only
  search, checked site-tier/fallback semantics, grouped policy context, explicit
  active/retained epoch composition, separate validator/planner identity,
  exact quantities and namespaced capacity, one
  readiness predicate, authority-owned idempotent `PENDING` preparation,
  coordinator intent before authority mutation, authority-owned existing
  controller actions, rebuildable stage work, preservation without implicit
  legacy backfill, and no execution side effects.
- Manager action required if any stop condition is met or a public/durable shape
  must differ materially from the manifest.

## Workflow State

- Manager preparation: complete at base `24b5d21`; worktree, exact source owners,
  focused regressions, and harness commands recorded
- Expanded planning: complete at evidence revision `8db4ae6`; the bounded
  refinement fixed the causal intent/authority-receipt/projection order,
  preserved historical attempts without implicit backfill, made the fresh-
  process public import check explicit, and excluded generic saga, transport,
  and later-phase reference scaffolding; approved behavior/design unchanged
- Implementation: complete through the bounded blocker correction; shared readiness, atomic prepared-attempt receipts, and rebuildable ready-stage work projection added without assignment or launch
- Refiner: completed one qualified blocker correction at `671fc89`
- Pre-submit gate: running final validation
- Independent review: required after manager validation because the phase adds
  subsystem-public protocols, a durable projection, and an authority lifecycle
  transition whose dependency and migration boundaries materially interact
- Blocker corrections: 1/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Shared readiness evaluation and runner consumer; authority `PENDING` preparation receipt; SQLite ready-stage projection/orchestrator; intentional runtime facade expectation. No assignment, lease, provider, or launch behavior added. |
| Tests added or updated | Authority receipt replay/conflict and durable stage-work replay identity; runtime facade export expectation updated. |
| Validated revision/tree state and evidence | Focused tests pass: orchestration, prepared-attempt receipt, and runtime facade import boundary. Final gates running. |
| Validation-relevant changes after evidence | Qualified correction after `671fc89`; no other phase-plan or manifest changes. |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
