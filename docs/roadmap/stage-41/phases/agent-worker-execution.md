# Phase 4 Execution Plan: Agent Worker Execution

## Metadata

- Status: in_progress
- Roadmap stage and phase: 41 / 4
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p4-agent-worker-execution
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: `fcaf20b25e48ff8c4f1e06f9dfbe1e9f969604d3` (published Phase 3 completion metadata after PR 310)
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 4: Agent Worker Execution
- Dependencies: Phase 3 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: none; Phase 3 merged, completion metadata published and stage/control/live develop synchronized

## Objective And Context

Native and configured container attempts use the same agent-owned worker and result boundary with correct resource and containment evidence.

Phases 2–3 already run through current managed native workers. This phase completes the actual native/container consumer path and leaves a small backend handle seam for agent-owned external jobs in Phase 5.

Requirements: FR-41-06/09; supporting FR-41-03/05/13. Design: DQ-41-03.
Validation ownership: VAL-41-06, VAL-41-05 (containment), VAL-41-03 (authorized capacity).

## Current Source And Harness

- `src/loom/queue/_remote_stage_execution.py`: ResidentExecutionProfile and execution-only stage requests/results.
- `src/loom/queue/_agent_process_supervisor.py`, `agent_sessions.py`, `local_daemon_execution.py`: durable supervision, authorized offers and release evidence.
- `src/loom/pipeline/executors/containers.py`, `_container_resources.py`, `docker/{executor,commands}.py`, `apptainer/{executor,commands,_timeout}.py` and Slurm container launch primitives only where reused by actual consumers.
- `src/loom/queue/deployment.py`, `resident_readiness.py`, `_resident_stage_worker.py` and `src/loom/pipeline/execution/stage_worker.py`: protected installed profile, readiness and exact execution-only child construction.
- Published resource contracts, worker/supervisor tests, container executor contracts and opt-in Docker/Apptainer hooks. Include #301 report metadata and #306 supervisor schema 3/native terminal qualification, not only the original Stage 39 evidence.

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

### Preserve published completion and execution evidence

Native worker success requires the supervisor's verified successful completion,
including zero unreaped-root exit and no other owned process-group members before
containment signals. Preserve parent-owned `managed_successful_exit` in durable
result/replay; child-supplied metadata, root exit alone or a legacy unqualified
receipt cannot authorize success. Keep process observation failure, containment
and the scientific result distinct. Reuse the current supervisor's schema and
qualification owner rather than a new success predicate in the public facade.

Preserve report-v3 executor metadata and its public redaction policy through
native/container delivery, failure, cancellation and replay. Retain the native
parent's exact `managed_output_predecessor` from the admitted worker request when
calling the authority commit owner; a lost response must not replace it with the
latest observed output head. Slurm has separate backend completion/containment
evidence; P5/P6 must not fabricate a local successful-exit qualification from a
scheduler state. Existing scope-qualified worker proofs stay at their owners.

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

Preserve the published supervisor qualification, late-result and output-predecessor
regressions while converting launch owners. Cover root-first exit with surviving
work, an unavailable process observation, a child-forged success marker, and
replay after supervisor continuity rotation/lost commit reply. Report metadata
must retain its native safe view without fabricating facts for older reports.

    uv run --extra config pytest tests/integration/pipeline/test_managed_local_execution.py tests/unit/loom/queue/test_agent_process_supervisor.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py

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

- Manager preparation: passed on 2026-09-12 in the manifest's persistent stage
  worktree and this phase branch. Phase 3 PR 310 merged as
  `a4bedaa2624750de2b3c28a42e9a950065d16bb6`; completion metadata is the Base
  revision above. Synchronization verified matching stage, local develop,
  fetched origin/develop and advertised develop. Exact local and remote Phase 3
  branches were retired, all predecessor agents/processes are terminal, and
  successor start/preflight passed on the clean branch.
- Source reconciliation: published Phase 3 supplies protected deployment
  availability, immutable per-role lifetime, native run composition and exact
  outstanding-poll recovery. ResidentExecutionProfile/ResidentWorkerLaunchProfile
  currently bind installed project/Python/environment; ResidentWorkerLaunch
  starts `_resident_stage_worker`, which constructs one request with
  `execute_resident_stage_worker_request` and LocalExecutor. Embedded and outbound
  execution both retain launch intent through the existing supervisor. Docker
  and Apptainer have existing command/resource/containment owners; consolidate
  their actual resident consumer rather than adding another execution engine.
  Published native successful-exit qualification, exact output predecessor,
  report-v3 metadata and transport bounds remain binding at their existing owners.
- Named refinement: none needed. Accepted native/container ownership, result,
  resource and installed-environment contracts remain unchanged. Private backend
  handle/profile layout is implementation discretion. Record any changed durable
  format interpretation with its producer/reader and preserve fail-before-mutation
  behavior for incompatible retained state; no new registry or build service.
- Coverage selection: exact installed code/environment and assignment identity;
  authorized profile/resource binding; native and fake Docker/Apptainer public
  run journeys; observer loss, timeout and surviving descendants; native parent
  success qualification and exact output-predecessor replay; report-v3 safe
  metadata and removal/import boundaries. Preserve existing publication, run,
  lifetime and supervisor tests when their consumers change. Expand for changed
  shared contracts, new failures or unresolved accepted concerns. Both full
  commands below remain required; predecessor evidence is reused only for
  unchanged contracts and is not this phase's completion evidence.
- Retained-consumer handoff: Phase 3's Exact retained consumers and successor
  owners assigns this phase the subprocess, Docker, Apptainer, runtime-profile,
  failing-run and local-diagnostics executable examples. Convert those actual
  journeys and their assertions to public managed runs; preserve the separate
  Phase 6 Slurm and Phase 9 remaining-owner boundaries.
- Environment qualification: local version queries find Docker 29.8.0 and
  Singularity-CE 3.10.4-focal; no `apptainer` or Slurm commands, enabled physical
  acceptance flags or configured approved SIF are available. Version discovery
  does not qualify actual execution or containment. Required fake-container and
  native public journeys remain executable; physical runtime/site gaps must stay
  explicit under this card's environment-dependent qualification row. Do not
  pull/build an image or introduce an alternative backend to erase that gap.
- Execution delegation: one executor is justified by the coupled installed
  profile, native/container launch, durable supervision, resource/result and
  executable-example changes. The manager retains manifest, pre-submit, PR,
  independent review and delivery ownership; no child delegation or overlapping
  source writes.
- Planning review: original accepted contracts retained; 2026-09-12 published-source amendments and current readiness receipt are owned by the manifest Quality Gate
- Implementation: prepared; execution pending
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
