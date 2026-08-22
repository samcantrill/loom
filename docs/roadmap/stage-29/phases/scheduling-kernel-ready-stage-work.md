# Phase 1 Execution Plan: Scheduling Kernel And Ready-Stage Work

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 1
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p1-scheduling-kernel-ready-stage-work`
- Worktree root and path: record during phase preparation
- Base revision: current clean `origin/develop`
- PR target: `develop`
- PR title: `feat(scheduling): add kernel and durable ready-stage work`
- Dependencies: implemented pipeline planner, per-run authority, runtime resource
  requests, Stage 25 policy-validation patterns, and Stage 28 explicit extension
  composition/conformance patterns
- Workflow path: expanded because this phase establishes subsystem-public
  extension contracts, one authority-owned attempt-preparation transition, and
  one new durable coordinator projection
- Blockers: none; rediscover exact source names and current tests before editing

## Objective And Context

- Vertical outcome: Loom has one authoritative answer to “which exact stage
  attempts are ready?” and one pure deterministic answer to “where could this
  already-ready attempt fit?” An admitted run can be reconciled into durable
  `StageWorkRecord` projections and evaluated against an immutable local
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
  Phases 4–8 own remote trust, transport, GPU placement, controls, and recovery.

This is the one deliberate foundation phase in the eight-phase plan. Its
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
  - site-owned hard limits, allowed kinds, preference weights, and search bounds.
- Keep `max_parallel_stages` as separate run-orchestrator admission policy. It
  limits exposed/active work for the run but is not a resource request, hard or
  soft placement rule, or part of the `ResolvedStagePlacement` fingerprint.
- Keep authored/runtime resource validation owned by the existing
  `ResourceValidator` contract. A higher-level pipeline-runtime adapter converts
  canonical validated `ResourceEntry` values to scheduling-owned immutable
  entry views. A `ResourcePlanner` receives those views and owns scheduling-time
  merge, feasibility proposals, exact claims, and safe failure explanations.
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
  bounded candidate orchestration, deterministic ordering, hard-before-soft
  evaluation, proposal validation, stable tie-breaking, and mutation exclusion.
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
- Add explicit instance-local registries. Registration is duplicate-safe;
  composition is trusted deployment code; registries freeze before work is
  admitted; submitted/durable data can select only an allowed registered kind
  and can never import or deserialize an implementation.
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
  - honors per-run parallel-stage limits;
  - materializes or refreshes rebuildable `StageWorkRecord` projections;
  - blocks descendants or derives run completion from authority truth.
- Add the stage-work subset of a semantic coordinator-state store protocol, with
  SQLite production and in-memory test implementations. It exposes atomic
  domain operations rather than generic CRUD. Stage work stores attempt,
  readiness/order evidence, upstream commit identities, resolved-placement
  fingerprint, and scheduling diagnostic state, but never owns stage success,
  output truth, or retry decisions.
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
- Fair-share, preemption, gang/distributed stages, general constraint solver,
  process-global registry, automatic plugin loading, payload-selected callables,
  or root-level `Scheduler` re-export.

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
    claim_contracts: tuple[ResourceClaimContractDescriptor, ...]

    def resolve_request(
        self,
        authored: ValidatedResourceEntryView | None,
        runtime: ValidatedResourceEntryView | None,
    ) -> ResourceRequestResolution: ...

    def propose_claims(
        self,
        request: ResolvedResourceRequest,
        opportunity: ResourceOpportunity,
        budget: SearchBudget,
    ) -> ClaimSearchResult: ...


class SchedulingPolicy(Protocol):
    descriptor: SchedulingComponentDescriptor

    def select(
        self,
        candidates: tuple[ValidatedCandidate, ...],
        context: PolicyContext,
    ) -> PolicySelection: ...
```

The final names may follow repository conventions, but the authority limits are
fixed. A planner proposes exact claims; hard rules only reject; preferences only
score feasible candidates; policy selects an existing candidate ID or waits.
None receives a store, live clock, network client, authority, or launcher.
`ValidatedResourceEntryView` is an immutable scheduling input, not an authored
codec; `loom.pipeline.runtime` owns conversion from and back to the existing
validated `ResourceEntry`/`ResourceRequest` values.

All ambiguity is represented explicitly:

```text
resource resolution  = ABSENT | RESOLVED | INVALID
claim search          = COMPLETE | EXHAUSTED
claim validation      = VALID | INVALID
rule-spec resolution  = RESOLVED | INVALID
hard evaluation       = PASS | REJECT | INDETERMINATE
preference evaluation = SCORE | INDETERMINATE
policy selection      = SELECT | WAIT
```

`None`, an empty iterable, an exception, an unknown candidate ID, a missing
required evaluation, oversized output, or search-budget exhaustion must never
be interpreted as infeasibility or permission to mutate.

### Capacity and component identity

A proposed claim exposes coordinator-accountable atoms separately from trusted
provider-specific data:

```python
@dataclass(frozen=True)
class CapacityAtom:
    capacity_key: str
    amount: ExactQuantity


@dataclass(frozen=True)
class ResourceClaim:
    resource_kind: str
    contract: ResourceClaimContractDescriptor
    atoms: tuple[CapacityAtom, ...]
    provider_data_version: int
    provider_data: Mapping[str, PlainData]
```

The kernel validates uniqueness, positivity, normalization, bounds, snapshot
revision, and contract shape. Provider data cannot be used as hidden accounting.
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
`StageWorkRecord` is disposable and rebuildable. If it disagrees with the
authority, the authority wins and reconciliation repairs or retires the
projection. A scheduler decision derived from it is data only and is stale as
soon as any input version changes. Phase 1 creates no workspace, worker request,
resource claim, assignment, execution lease, artifact transfer, or process.
REUSE/SKIP/BLOCKED reconciliation may still perform the pre-existing
authority-owned controller transitions and output-reference commits required by
the execution plan; those are not new scheduler-owned lifecycle mutations.

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
| One exact prepared attempt per readiness generation | Per-run authority preparation transaction | Replayed reconciliation, restart, or concurrent orchestrators | Duplicate attempts or skipped retry ownership | Expected-revision, idempotency, concurrency, and restart tests |
| Controller-only actions retain authority ownership | Existing plan-action/authority operations | New orchestrator projection | Reuse/skip/block truth duplicated or descendant unlocked early | Existing runner/orchestrator trace-equivalence and output-commit tests |
| Authored minima cannot be weakened | Runtime placement resolver and resource planner | Exact-stage runtime policy | Under-requested execution | Merge/property/boundary tests |
| Mandatory feasibility cannot be overridden | `SchedulingKernel` | Custom rule/policy result | Invalid placement | Invalid-output and mutation-sentinel tests |
| Preference cannot create feasibility | Kernel hard-before-soft order | Custom scorer | OOM or policy bypass | Feasibility-neutrality tests |
| Stage work is not lifecycle truth | Coordinator projection reconciler | Stale/crashed projection writer | False readiness/terminal status | Restart and authority-disagreement tests |
| Component selection is inert data | Frozen registry/composition root | Runtime or durable payload | Code loading/trust violation | Codec/import/unknown-ID tests |
| Built-in decisions are deterministic | Kernel/default policy | Mapping/registration order | Irreproducible placement | Permutation and stable-tie tests |
| Phase 1 cannot launch | Composition boundary | Accidental executor/provider dependency | Side effect before saga exists | Dependency/import checks and launcher sentinel |

## Implementation Slices

1. Add exact quantity, component/claim-contract descriptors, closed result
   values, frozen registries, four pure protocols, CPU/memory/default rule and
   policy implementations, and `loom.testing` conformance.
2. Implement `ResolvedStagePlacement` parsing/resolution and the fixed pure
   kernel with bounds, mandatory checks, deterministic FIFO-with-safe-bypass,
   explanations, and proposal validation.
3. Extract the shared readiness predicate and route existing runner readiness
   through it; split semantic `PENDING` attempt preparation from the current
   local worker-materialization helper; add controller-action reconciliation
   and durable `StageWorkRecord`/store operations.
4. Integrate orchestrator-to-snapshot-to-decision without reservation or launch;
   add restart/rebuild, downstream custom-component, import, and no-mutation
   evidence plus canonical documentation/public exports.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Cheap intentional exports and dependency direction | Import `loom.scheduling` and `loom.testing` without loading `loom.pipeline`, runtime/network/database modules; no root re-export; pipeline-runtime adapter imports scheduling in the allowed direction |
| Unit | Required | Quantities, resolution, rule order, bounds, deterministic selection | Integer CPU, byte memory, invalid fractions, hard-before-soft, stable ties, EXHAUSTED versus infeasible |
| Contract | Required | Downstream protocol authority and fail-closed output | Synthetic planner/rule/scorer/policy; invalid IDs, exceptions, oversize, mutation sentinels, descriptor drift |
| Integration | Required | Authority preparation, readiness, and durable projection | Train/evaluate, diamond, reuse/skip/failure/retry, concurrent/replayed preparation, per-run parallel limit, restart/rebuild with no duplicate attempt |
| E2E / opt-in | Deferred | No process or external system is allowed in Phase 1 | Phase 2 owns the first execution E2E; assert launcher/provider/transport sentinels remain untouched |

Targeted commands are fixed during phase preparation from discovered tests.
Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: accidentally exposing a broad scheduler API; retaining two
  readiness interpreters; treating incomplete search as infeasible; allowing
  custom output to bypass mandatory checks; making stage work authoritative;
  importing pipeline resources into the pure subsystem and creating a cycle; or
  reusing the current `RUNNING`/lease allocation semantics for preparation.
- Review focus: import direction, immutable closed values, explicit registry
  composition, kernel result validation, readiness extraction, exact-attempt
  idempotency, and absence of execution side effects.
- Stop if: canonical runtime requests cannot be composed without weakening;
  readiness cannot be shared without a public behavior change; stage work would
  need to own lifecycle truth; an exact `PENDING` attempt cannot be prepared
  atomically without taking an execution lease; a pure protocol requires a live
  store/launcher or runtime import of `loom.pipeline`; or a required quantity
  cannot be represented exactly.
- Accepted debt: initial bounded enumeration and FIFO-with-safe-bypass may be
  suboptimal. Revisit only with measured workloads, not speculation.

## Executor Handoff

- Read: this file in full, the Stage 29 manifest shared constraints, planning
  FR-2–FR-9 and FR-22–FR-24, and current source/tests discovered on the phase
  branch.
- Safe implementation order: the four slices above. Preserve a runnable test
  tree after each slice and do not implement Phase 2 assignment operations.
- Decisions not to revisit: fixed kernel, narrow protocols, explicit frozen
  composition, separate validator/planner identity, exact quantities, one
  readiness predicate, authority-owned idempotent `PENDING` preparation,
  authority-owned existing controller actions, rebuildable stage work, and no
  execution side effects.
- Manager action required if any stop condition is met or a public/durable shape
  must differ materially from the manifest.

## Workflow State

- Manager preparation: planning complete; record worktree/base and rediscover
  exact source/test commands before spawning the executor
- Expanded planning: required by public extension and durable projection risks;
  the stage-level design and plan reviews are complete
- Implementation: pending
- Refiner: not used
- Pre-submit gate: pending
- Independent review: decide during phase preparation from the remaining public
  protocol/migration risk
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
