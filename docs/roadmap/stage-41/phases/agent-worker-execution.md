# Phase 4 Execution Plan: Agent Worker Execution

## Metadata

- Status: pending
- Roadmap stage and phase: 41 / 4
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p4-agent-worker-execution
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: published develop after Phase 3 merges; record exact SHA at execution preparation
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 4: Agent Worker Execution
- Dependencies: Phase 3 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: source predecessor pending; no unresolved planning blocker

## Objective And Context

Native and configured container attempts use the same agent-owned worker and result boundary with correct resource and containment evidence.

Phases 2–3 already run through current managed native workers. This phase completes the actual native/container consumer path and leaves a small backend handle seam for agent-owned external jobs in Phase 5.

Requirements: FR-41-06/09; supporting FR-41-03/05/13. Design: DQ-41-03.
Validation ownership: VAL-41-06, VAL-41-05 (containment), VAL-41-03 (authorized capacity).

## Current Source And Harness

- `src/loom/queue/_remote_stage_execution.py`: ResidentExecutionProfile and execution-only stage requests/results.
- `src/loom/queue/_agent_process_supervisor.py`, `agent_sessions.py`, `local_daemon_execution.py`: durable supervision, authorized offers and release evidence.
- `src/loom/pipeline/executors/containers.py`, `_container_resources.py` and Slurm container launch primitives only where reused by actual consumers.
- Stage 39 resource contracts, worker/supervisor tests, container executor contracts and opt-in Docker/Apptainer hooks.

## Scope

Own the native/container agent execution boundary, installed environment binding, process containment, resource enforcement and current worker/result semantics. No Slurm submission move, general executor registry or environment build service.

Assume the predecessor's accepted contracts and existing qualified installations.
Each phase includes its code, owner-level tests, current docs and replaced-code
removal. Preserve unrelated work and current scientific/resource meaning.

## Implementation Walkthrough And Examples

### What changes and why

The worker agent is a service that spans many attempts. For each assignment, it
selects the authorized execution profile and creates an execution-only worker.
This phase consolidates native/container launch at that boundary while reusing
resident execution, resource enforcement and the durable process supervisor.

The following is internal pseudocode. Helper names and handle representation are
implementation choices, not additions to the public API or a new plugin protocol.

```python
profile = resolve_authorized_profile(assignment)

# The supervisor owns durable launch intent and recovery evidence internally.
handle = supervisor.start_attempt(
    assignment=assignment,
    command=profile.worker_command(assignment),
)

send_execution_observation(handle)
```

The launch cannot rely on saving a handle in the transient caller after process
creation. The supervisor retains intent before effects and enough evidence to
reconcile an interrupted start. Losing an agent observer must not leave the only
record of running work in that observer's memory.

### Assignment and environment boundary

A conceptual assignment carries these facts through the existing typed request:

```text
assignment
  |- run and pipeline-stage identity
  |- attempt identity and current execution authorization
  |- exact inputs and serializable parameters
  |- selected installed environment/profile
  `- resource and declared-output requirements
```

Native Python and container profiles choose different launch mechanics while
preserving the same input/output and scientific meaning. Project code is
constructed inside the selected environment. Importable definitions and plain
values cross the process boundary; arbitrary live closures do not. The worker
executes only its assignment and never recursively invokes public loom.run.

Agent policy authorizes profiles and resource offers; a self-reported capability
does not grant permission. Preserve selected devices, supported limits, installed
code identity, failure/reliability evidence and current-fence result publication.
Container support applies to the configured qualified runtime; this phase alone
does not qualify containers under Slurm or inside an allocation.

### Worker completion and containment

If the root worker exits while a child process remains active, the root exit is
one observation. The supervisor still owns containment and its durable evidence.
Capacity cannot be released merely because one PID disappeared. Results go through
the established agent/coordinator/authority path; the agent does not independently
commit outputs.

The local handle identifies supervised execution. Phase 5's handle identifies an
external Slurm job, so the shared private seam must leave room for that real
difference. It must not equate helper-process exit with assignment completion.
VAL-41-03/05/06 checks below exercise authorized resources, native/container
environment binding, observer loss, surviving descendants and stale results.

## Fixed Contracts And Private Discretion

Every executable stage selects an authorized agent plus backend/profile. Native
and container share process supervision and the same execution-only request/
result boundary; construct project code in the selected environment. Container
launch reuses existing executor/resource behavior, not arbitrary host commands.
Expose a narrow backend-specific handle/evidence seam for Phase 5; do not impose
process-exit completion on future Slurm handles. Internal helper/module names,
co-hosting when permitted and backend object layout remain private discretion.

Native and container profiles preserve input/output and scientific meaning. Project code is importable and values serializable; live closures are not persisted inputs. Workers execute only their assigned attempt and never invoke public run. Preserve authorized capacity, selected devices, installed code, failure/reliability provenance and output commit fencing.

### Delivery boundary

Native and explicitly configured container workers now exercise the complete public run journey. Qualification applies to the selected runtime/environment; this phase does not promise container operation under Slurm or within an allocation.

### Cross-phase handoff

Phase 5 consumes the backend handle/evidence seam without treating external-job lifetime as local helper lifetime. Its implementation may simplify private layout; fixed ownership, result and resource meanings do not change.

### Removal owned here

Remove replaced native/container launch duplicates and execution-only helpers with no remaining callers. Extract only pure helpers still needed by current workers; do not preserve a recursive full-run engine as worker implementation.

Private helper names, local wiring and intermediate representations remain
implementation discretion. Public behavior, durable identity, trust, failure and
cross-phase meanings above are fixed. No compatibility aliases or state resets.

## Proportionality

Use existing resident requests, executor launch mechanics and supervisor. A small backend-specific handle seam serves current native/container execution and the accepted Slurm consumer; no speculative plugin framework.

## Invariant Ownership

| Invariant | Owner | Reachable boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| One attempt worker | Agent execution-only boundary | Container/native child construction or restart | Recursive run or wrong project code | VAL-41-06 exact request/installed identity |
| Owned process containment | Supervisor and executor | Observer exit, timeout, descendant survives root | Orphan work or early capacity release | VAL-41-05/06 native control evidence |
| Authorized resource semantics | Agent policy and executor resource owner | Untrusted offer or invalid runtime binding | Wrong devices or overstated limits | VAL-41-03/06 existing Stage 39 assertions |
| One output commit | Existing authority finalizer | Late/stale duplicate worker report | Wrong attempt publishes | Current fence/replay tests, no second finalizer |

## Implementation Slices

1. Consolidate installed native/container worker construction behind the existing agent-owned request/result boundary.
2. Preserve resource assignment, supervision, cancellation and recovery evidence; expose the minimal backend handle seam.
3. Exercise native/container public runs, remove obsolete launch helpers and update runtime/deployment examples with qualified limits.

## Test And Validation Plan

| Suite | Obligation | Minimal evidence |
| --- | --- | --- |
| Package/contract | Required | Cheap imports, execution-only request identity and resource policy unchanged. |
| Unit/integration | Required | Native/container selected environment, observer loss, timeout/descendants, exact output and containment. |
| Public journey | Required | Same synthetic pipeline reaches valid outputs through supported native and fake-container launch seams. |
| Real container | Environment-dependent qualification | Existing Docker/Apptainer acceptance; record unsupported/unrun site/runtime combinations. |

Target existing source-mirrored tests and add focused assertions where the new
contract requires them. Resolve predecessor-renamed test paths at preparation.
Run optional-runtime commands only with their qualified environment. A local
fixture is not live-site evidence; record missing qualification explicitly.

    uv run --extra config pytest tests/contracts/test_container_executor_contract.py tests/unit/loom/queue/test_agent_process_supervisor.py tests/integration/queue/test_agent_service_lifecycle.py

    LOOM_RUN_DOCKER_ACCEPTANCE=1 uv run pytest tests/container_acceptance

    LOOM_RUN_APPTAINER_ACCEPTANCE=1 uv run pytest tests/container_acceptance

Final implementation gate; reuse a fresh receipt only while relevant code,
tests, dependency/build and validation configuration remain unchanged:

    make validate-pr
    make test-summary

Do not repeat complete backend/fault matrices in consumer phases. Expand tests
only for changed shared contracts, new failures or a remaining accepted concern.

## Risks, Review, And Stops

Stop if a supported executor cannot honor current containment/resource/result contracts under agent ownership. Live optional-runtime absence is an evidence gap, not permission to invent another backend. Preserve actual scientific and resource controls during extraction.

## Executor Handoff

Read planning.md Behavior Baseline, the requirement/design/validation IDs above,
this whole card and the actual published predecessor contracts. Implement the
listed slices within the stated ownership. Do not reopen agreed lifecycle,
grant-before-start, sole submission/finalization ownership or hard cutover.
Manager action is for a demonstrated public/durable or accepted-behavior conflict,
not private helper choices. You are not alone in the codebase; preserve others' edits.

## Workflow State

- Manager preparation: approved card; execution revision/worktree pending
- Planning review: original design review and corrected run/cancel contracts retained; nine-phase mapping checked locally
- Implementation: not started
- Refiner: not used
- Pre-submit gate: not run
- Independent implementation review: required for process/resource ownership and launch removal
- Blocker corrections: 0/3
- PR and merge: not started

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Not started |
| Tests added, updated or intentionally removed | None; planning only |
| Validated revision/tree and evidence | Pending implementation |
| Validation-relevant changes after evidence | None |
| Replaced-code removal / retained primitive consumers | Pending this phase's removal audit |
| PR, review and merge | Pending |
| Residual risk and cleanup | Real container/runtime qualification pending |
