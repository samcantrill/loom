# Phase 4 Execution Plan: Agent Worker Execution

## Metadata

- Status: merged
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

The native handle identifies supervised process execution; the Docker handle
also identifies daemon-owned work. Phase 5's handle identifies an external Slurm
job, so the shared private seam must leave room for those lifetime differences.
It must not equate helper-process exit with assignment completion.
VAL-41-03/05/06 checks below exercise authorized resources, native/container
environment binding, observer loss, surviving descendants and stale results.

## Fixed Contracts And Private Discretion

Every executable stage selects an authorized agent plus backend/profile. Native
and container share the agent/supervisor ownership and execution-only request/
result boundary. Docker additionally requires daemon-owned containment evidence.
Construct project code in the selected environment. Container launch reuses
existing executor/resource behavior, not arbitrary host commands.
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

### Docker identity, completion and recovery

The existing Docker CLI runner records command status, not durable container
ownership. Containing its helper process group does not contain daemon-owned
work. Extend the existing agent/supervisor owner with a bounded Docker handle;
reuse executor resource/command construction. No separate job database, registry,
provisioning service or Slurm implementation is required or authorized.

Before any daemon launch effect, durably bind launch intent to the exact assignment,
attempt/authorization, selected installed profile and daemon endpoint, and a
unique container ownership identity recoverable even if the create response is
lost. Retain the daemon's immutable container ID once known and verify the
ownership binding before observation or cancellation; a reused name or another
daemon's object is not this attempt. Exact names, labels, schema layout and
create/start command sequencing remain private. Persist enough progress to
reconcile loss before creation, after creation and after start without starting
a second container or restarting completed work. Same-ID replay reconciles the
same intent; changed bindings conflict. Unknown effects never authorize a fresh
launch. Preserve installed-image/environment and no-pull/build scope, resource
selection/enforcement and grant-before-start authorization across recovery.

The agent owns observation and cancellation of that exact container through the
selected daemon, including after CLI helper or agent-observer loss. Retain
cancellation intent before effects and reconcile interrupted cancellation until
positive containment evidence is available. Helper exit, timeout, successful
stop-command return or an unavailable daemon are insufficient alone. Missing or
ambiguous container state without retained qualifying evidence remains unknown;
it proves neither backend success nor containment and cannot release capacity.
Only a durably established no-effect outcome may settle an unstarted launch
without container terminal evidence; an absent lookup after an uncertain request
is not such an outcome. Never cancel an unverified foreign container.

Successful Docker execution requires trusted terminal evidence for the exact
owned container, including a successful exit outcome, and a successful
current-fence worker result;
containment separately requires positive evidence that its workload has stopped
and cannot automatically restart. Configure/reconcile lifecycle controls so that
terminal evidence is stable. Record those facts durably before automatic removal
can erase them; defer removal until this capture if necessary. Replay after
removal uses the retained evidence, not absence as a new success predicate.
Retain pending result/acknowledgement and cleanup facts through the existing
owners so loss during evidence capture, result delivery or removal cannot create
a new execution, duplicate accounting, release without containment or bypass the
sole authority finalizer. Cleanup may reconcile removal without rerunning work.

Keep Docker terminal outcome, daemon containment, local helper/process evidence
and scientific result distinct. Do not manufacture `managed_successful_exit`
from daemon state or weaken the native parent's successful-exit qualification.
A helper's valid native qualification alone cannot qualify Docker backend
completion. Preserve exact output-predecessor replay, report-v3 redaction and
existing coordinator release/authority finalization ownership. Record any changed
durable interpretation with its producer/reader; incompatible retained state
fails before mutation under the shared hard-cutover contract.

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
| Owned workload containment | Existing agent/supervisor with backend evidence | Observer/helper loss, timeout, native descendants or daemon-owned container survives | Orphan work or early capacity release | VAL-41-05/06 native qualification and exact Docker containment |
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

P4 owns the Docker daemon-lifetime checks under VAL-41-05/06; retain resource
and authorization assertions under VAL-41-03. Use a stateful fake daemon seam
whose container survives helper loss, not just scripted CLI exit codes. Cover:

- Lost create/start responses and restart on both sides of daemon effects:
  recover the exact owned identity with no duplicate creation/start/accounting;
  same-ID changed intent, wrong endpoint or foreign identity cannot be adopted.
- Helper exit while the container runs, daemon observation failure and missing
  state after uncertain effects: no backend success, release or fresh launch.
- Cancellation interrupted before/after its daemon effect: replay targets only
  the owned container, and capacity stays held until positive containment.
- Terminal zero/nonzero outcomes, restart prevention and worker-result fencing:
  native helper success cannot stand in for Docker completion, and cancellation
  containment cannot stand in for successful scientific execution.
- Loss before/after terminal-evidence persistence and removal, plus lost result
  acknowledgement: removal cannot erase the only evidence; retained evidence
  replays through the existing finalizer with one commit and one capacity release.

These owner tests feed the required configured-container public journey. Existing
physical acceptance remains environment-dependent and must distinguish actual
Docker containment evidence from fake-daemon evidence; no workload launch is
claimed by this planning refinement. Independent review checks durable identity,
unknown-state conservatism and separation from native successful-exit evidence.

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
  and Apptainer have reusable command/resource mechanics. Docker
  `SubprocessDockerCommandRunner.run` retains only CLI status and
  `build_docker_run_command` permits automatic removal; supervisor `contain`
  qualifies only its OwnedProcessGroup. Docker daemon containment is therefore
  an implementation obligation here, not an already reusable containment proof.
  Consolidate actual resident consumers under the existing agent/supervisor owner.
  Published native successful-exit qualification, exact output predecessor,
  report-v3 metadata and transport bounds remain binding at their existing owners.
- Named refinement: one qualified source/contract correction on 2026-09-12.
  Docker helper/process ownership cannot prove daemon-owned containment after
  loss. The Docker identity, completion and recovery contract above resolves this
  preparation uncertainty with a bounded backend handle at the existing owner.
  Accepted native/container public behavior, resource/accounting/authorization,
  installed-environment contracts and nine-phase scope are unchanged. Private
  layout/commands remain discretionary; no implementation or runtime validation
  is claimed by this correction. Manager may resume the same executor.
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
- Implementation: native/container profile, worker, supervisor, report and example
  changes implemented; review correction and both fresh required gates passed.
  The delegated executor
  terminated at a service usage limit before its final handoff. The manager
  verified its committed work, failed terminal gate and process inventory, then
  continued locally without a replacement executor or overlapping writes.
- Refiner: not used
- Pre-submit gate: passed on 2026-09-12. The manager checked the committed scope,
  protected installed-profile selection, execution-only worker boundary, Docker
  durable ownership/containment/recovery, native qualification and exact output
  predecessor, report metadata, changed examples/removals and fresh validation.
  No qualified implementation blocker remains. Independent actual-PR review and
  gated remote delivery subsequently passed.
- Independent implementation review: actual PR head
  `52c273df0757800ab9bb086ff74bff5958ff6a6b` reviewed on 2026-09-12. One product
  blocker: Apptainer namespace exit can race with pidfd signaling, allowing an
  uncaught OSError to terminate the shared supervisor. The manager's bounded
  correction follows the existing namespace owner's behavior: tolerate
  ProcessLookupError while still requiring positive containment; other signaling
  errors return UNKNOWN and retain ownership. The new regression failed for both
  error cases before correction; 36 supervisor, Docker, public backend and
  Apptainer example checks passed afterward. Evidence:
  `build/phase-4/apptainer-signal-race-{before,after}.log`. Both fresh final gates
  passed as recorded below. The same reviewer confirmed the correction at
  `c7e71f98525359b119650c1434a5a34433ed56ca`: no remaining blockers, merge eligible.
  Manager pre-submit acceptance includes this bounded correction.
- Blocker corrections: 3/3; named Docker source/contract preparation correction,
  then the manager's Docker example socket-path correction. The config-extra
  smoke producer supplies a long output root; locating the fixture socket there
  failed before either Docker journey could start. The fixture now owns a short
  temporary socket directory, independent of output location. Both failed smoke
  cases, the paired success/failure e2e journey and configured Docker replay
  passed together (4 passed) in `build/phase-4/socket-regression.log`.
  The third correction is the independent review's Apptainer signaling race above;
  the refiner remains unused. No accepted contract or phase scope changed.
- PR and merge: [PR 311](https://github.com/samcantrill/loom/pull/311) remotely
  squash-merged into develop on 2026-09-12T12:11:32Z as
  `243c86a76f7af171c361283766f67d6102fa5dd0`, from reviewed head
  `c7e71f98525359b119650c1434a5a34433ed56ca`. The delivery gate reverified the
  canonical identity, local validation, independent approval, live merge and
  leased deletion of the exact remote phase branch. Transition to the named
  coordination branch passed; publication/synchronization and exact local branch
  retirement are required before Phase 5 starts.

### Final validation receipt

- Validated implementation revision: `1196926f92285c6857842198936e97f59369ed14`;
  tree: `fd5e4240609f6f46946632566d26809e6cafba24`. Both commands ran on this
  same clean revision, including the Apptainer signaling correction. Subsequent
  changes are phase/manifest execution metadata only.
- `make validate-pr`: exit 0; Ruff passed, Pyright reported zero errors/warnings;
  baseline 3,322 passed / 2 skipped / 294 deselected; config-extra 254 passed /
  18 skipped / 3,363 deselected; MCP 36 passed / 3,582 deselected; sdist and wheel
  built. Command elapsed time: 2,408.61 seconds.
- `make test-summary`: exit 0; 3,614 passed, zero failures/errors, 18 skipped,
  7,218 row-summed deselections. Suite passes: package 127, unit 2,332, contract
  302, integration 516, e2e 47, config-extra 254, MCP 36. Report duration:
  2,772.74 seconds; command elapsed time: 2,884.70 seconds.
- Evidence: `build/phase-4/{validate-pr-review-final,test-summary-review-final}.log`,
  `build/test-summary.md` and seven suite `junit.xml` files. The manager parsed
  all seven XML files (3,632 test cases, including 18 skips) and byte-verified
  their copies, the summary and four before/after/final logs: 12 archived files
  under `/tmp/loom-stage41-p4-review-correction-evidence/`. Archived logs are in
  `phase-4/`. The prior 23-file evidence archive remains unchanged at
  `/tmp/loom-stage41-p4-summary-evidence/`; it records the pre-review revision
  `feed35902ab06db541f4f1028cc1e35da91dd2f7` and earlier validation history.
- Superseded evidence remains inspectable: recovery work interrupted the first
  run; the native metadata merge failure was corrected; the later config-extra
  Docker socket failures were corrected. An additional full baseline encountered
  two ten-second waits in the persisted preprocess/train test. Both roots retained
  successful contained zero-exit workers; all five variants passed unchanged in
  the direct recheck. The unchanged full retry and required summary both passed.
  These earlier runs are not the final passing receipt, and no timeout or
  assertion was relaxed to obtain it.
- The 18 summary skips are opt-in physical acceptance: 13 namespace lifecycle,
  plus Docker smoke, Apptainer smoke, SIF build, CPU/memory and scheduling-only
  acceptance. Local daemon/namespace fixtures establish logical behavior only.
  No physical container, fleet or Slurm qualification, image pull/build or
  external experiment workload is claimed.
- Process cleanup: both manager validation commands are terminal. Final inventory
  found no phase-owned test, worker, fixture or supervisor process. Four older
  supervisors belonging to unrelated work were preserved. No stage branch
  transition occurred only after independent review and verified remote merge.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Complete: installed container profiles and readiness, existing agent/supervisor backend evidence and recovery, result metadata, native/container public examples; manager pre-submit passed |
| Tests added, updated or intentionally removed | Stateful Docker effect/recovery tests, container binding/resources, native/Docker/Apptainer public replay, existing finalizer crash/predecessor assertions with Docker, native regression preservation and converted example assertions |
| Validated revision/tree and evidence | Both required commands passed on `1196926f92285c6857842198936e97f59369ed14`, tree `fd5e4240609f6f46946632566d26809e6cafba24`; exact counts, failed-run dispositions and verified archive in Final validation receipt |
| Validation-relevant changes after evidence | None; execution metadata only after both gates passed with the review correction |
| Replaced-code removal / retained primitive consumers | Unused Apptainer fake launcher removed; old Docker fixture retains only version preflight. Assigned native/container examples now use public run. Existing command/resource/namespace helpers remain current backend consumers; Slurm and remaining full-run removals retain P6/P9 ownership |
| PR, review and merge | PR 311 merged as `243c86a76f7af171c361283766f67d6102fa5dd0`; independent reviewed head `c7e71f98525359b119650c1434a5a34433ed56ca`, no remaining blockers; both full gates and gated delivery passed |
| Residual risk and cleanup | No implementation blocker. Physical runtime qualification remains unavailable and unclaimed; phase-owned processes terminal; exact remote branch deleted; completion metadata and local retirement use the synchronization gate before Phase 5 |
