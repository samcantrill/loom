# Phase 7 Execution Plan: Explicit Ready-Stage SLURM Delegation

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 7
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p7-slurm-ready-stage-delegation`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-29-p7-slurm-ready-stage-delegation`
- Base revision: clean `origin/develop`
  `b57d65d7790e88eb63bf25f1ff98c762d4853aa2`
- PR target: `develop`
- PR title: `feat(scheduling): delegate explicit ready stages to SLURM`
- Dependencies: Phase 6 [PR #241](https://github.com/samcantrill/loom/pull/241)
  passed CI and squash-merged as `2c6d366`; Phase 1 provides immutable route,
  ready-work, request, and descriptor contracts; Phase 2 provides tagged
  assignments, authority bind/grant/fence, and the execution-only stage worker;
  Phase 3 provides crash-durable coordinator state and scoped application
  views; Phase 5 provides authenticated input/output relay and result replay
- Workflow path: expanded because a durable database mutation, an external
  nontransactional `sbatch` side effect, a scheduler-started bootstrap, an
  authority grant, and output commit interact causally
- Blockers: none. The prior command-seam blocker is superseded by correction
  1/3: profile-owned versioned operation comments and bounded exact discovery
  are now being added without changing historical whole-run callers.

## Objective And Context

- Vertical outcome: once an exact stage attempt becomes dependency-ready, a
  stage explicitly configured with one authorized SLURM profile is submitted as
  one batch job. SLURM chooses the node, but the batch job launches authored
  stage code only after a fixed Loom bootstrap authenticates, inputs are
  durable, and the authority creates the current execution fence. A verified
  fenced Loom result and accessible outputs, not SLURM state alone, complete the
  stage and unlock descendants.
- Earlier dependency: Phases 1–6 prove dependency-aware stage scheduling,
  resource semantics, durable assignment/fencing, resident-project execution,
  authenticated relay, and GPU request resolution on managed agents. This phase
  adds one concrete external target without changing readiness, run ownership,
  authority lifecycle ownership, or the pure managed-agent scheduling kernel.
- Later work explicitly out of scope: Phase 8 integrates run cancellation,
  profile reload, and control/status fan-out across managed and SLURM targets.
  Phase 9 owns privileged resolution of submission/start uncertainty and retry.
  This phase supplies the exact primitive observation/cancel/reconcile evidence
  those phases require; it does not add automatic fallback, allocation-fed
  agents, or another external scheduler.

## Current Source And Harness

- Relevant files and symbols to re-check during phase preparation:
  - `src/loom/pipeline/runtime/placement.py` already owns the closed
    `ExecutionRouteKind`/`ExecutionRoute` values and includes the route in the
    resolved placement fingerprint; `src/loom/pipeline/orchestration.py`
    currently filters the managed route before kernel scheduling, leaving the
    explicit SLURM route for this phase;
  - `src/loom/queue/slurm.py` and `SlurmQueueDispatchAdapter` currently own
    historical whole-run delegated queue dispatch and conservative
    `START_UNCERTAIN` classification;
  - `src/loom/pipeline/executors/slurm/commands.py` and `SlurmCommandRunner`
    already isolate `sbatch`, `squeue`, `sacct`, and `scancel` command calls for
    deterministic fakes;
  - `src/loom/pipeline/executors/slurm/resources.py` already contains
    `map_slurm_resources` and `build_sbatch_directives`, but its current schema
    must be assessed against the Stage 29 resolved request and non-weakening
    mapping rule;
  - `src/loom/pipeline/executors/slurm/scripts.py`, `planning.py`, `live.py`, and
    `submission.py` provide deterministic script/manifest, scheduler state, and
    parsable job-ID seams where their ownership remains appropriate;
  - `src/loom/pipeline/execution/slurm_controller.py` currently owns live
    whole-run/single-job/`afterok` flows. It persists `SUBMITTING`, but several
    command/parse failures become definite failure; that lifecycle must not be
    reused unchanged for ready-stage submission ambiguity;
  - `src/loom/pipeline/execution/continuation.py`, `StageJobRunRequest`, and
    `run_stage_job` are the present stage-job surface. Phase 2 must already have
    extracted the execution-only worker that avoids whole-run lock and direct
    lifecycle-finalization assumptions;
  - `src/loom/pipeline/execution/managed_local.py` now owns
    `ManagedAssignment`, `SQLiteCoordinatorAssignments`, and the durable
    `SQLiteAgentJournal.start_once` gate, while
    `src/loom/pipeline/execution/stage_worker.py` owns the execution-only worker;
  - `src/loom/queue/local_daemon_execution.py`,
    `src/loom/queue/agent_sessions.py`, and
    `src/loom/queue/_remote_stage_execution.py` are the current Phase 3/5
    coordinator, authenticated application, exact relay, and result owners.
- Existing tests and seams:
  - unit tests under `tests/unit/loom/pipeline/executors/slurm/` cover command,
    resource, script, status, cancellation, and submission behavior;
  - `tests/unit/loom/queue/test_slurm_adapter.py`, delegated queue contracts, and
    live SLURM integration/E2E tests protect historical behavior;
  - fake command runners and status fixtures must remain the required CI path;
    `tests/slurm_acceptance/` remains opt-in real-cluster evidence;
  - Phase 2 assignment/launcher sentinels and Phase 5 loopback relay harness are
    reused to prove one authored root and accessible output commit.
- Import, dependency, or harness constraints:
  - do not import SLURM/vendor/process code into import-light `loom.scheduling`;
  - keep resource translation and script/command mechanics under the existing
    SLURM executor boundary, with durable orchestration in the coordinator
    application/store;
  - no real SLURM installation, cluster account, network endpoint, or GPU is
    required by default validation;
  - do not turn the concrete Stage 29 consumer into a generic external-backend
    plugin protocol without another accepted consumer.

## Scope

In scope:

- Resolve every exact stage to one immutable execution route. Preserve
  `managed_agent` as the default. The SLURM variant must name exactly one
  site-authorized profile and retain its stable descriptor and non-secret
  configuration fingerprint in stage work and assignment evidence.
- Reject unknown, disabled, unauthorized, malformed, or changed-profile route
  values at the owning boundary. Lack of agent capacity, a preference score,
  elapsed wait, profile outage, submission failure, or scheduler state must not
  change the resolved route or choose another profile.
- Add a protected, instance-local SLURM profile registry owned by deployment
  composition. A profile describes only site-controlled behavior needed now:
  stable identity/version; allowed account/partition/QoS; safe resource and hard-
  rule mappings; command adapter; outstanding-submission limit; deterministic
  scheduler-visible operation metadata; resident project/environment/bootstrap
  capability; coordinator identity/endpoint; credential delivery; data path;
  bounded inspection/reconciliation; and output/result retention assumptions.
- Preflight each enabled profile before service readiness or mark only that
  profile unavailable with a safe diagnostic, according to the existing Stage
  29 degraded-start contract. Validate executable/adapter capability, directive
  allowlists, mapping completeness, credential reference permissions, resident
  project/environment fingerprint, relay reachability contract, operation-ID
  discoverability, status/cancel capability, bounds, and secret redaction.
- Translate the canonical resolved request and applicable hard constraints to
  one immutable `SlurmStageRequest`. The mapper must account for every required
  semantic or reject the route. It may reuse existing CPU, memory, GPU count,
  and generic-resource directive builders only where their exact meaning is
  compatible. It must not silently discard VRAM, device model/topology,
  custom-resource, agent target, executor, or artifact requirements.
- Treat SLURM eligibility as representability plus operational/profile
  admission. Do not treat unallocated nodes as offers, predict queue delay,
  reserve a particular node/GPU, or claim that a mapped request is presently
  satisfiable. SLURM remains responsible for choosing a node after `sbatch`.
- Add a tagged SLURM assignment target alongside the managed-agent target. The
  target consumes one atomic run `max_parallel_stages` slot and one configured
  profile outstanding-submission slot, but no agent capacity atom, offer, pool
  claim, provider binding, or agent session.
- Bind the exact authority-owned `PENDING` attempt to that assignment before
  submission. Prepare immutable work/request/input-access evidence and a
  deterministic script digest before the external-call boundary. A mapping,
  staging, profile, or authorization failure before submission must not invoke
  `sbatch`.
- Introduce one crash-durable SLURM stage submission record. It joins run,
  stage, attempt, readiness generation, stage work, assignment, issuer epoch,
  profile descriptor/fingerprint, canonical request/script digests, stable
  submission operation ID, scheduler cluster/job handle when known, bootstrap
  identities, dispatch state, bounded external observations, result/output
  state, and primitive cancel state without becoming authority lifecycle truth.
- Persist submission intent and then `SUBMITTING` before invoking `sbatch`.
  Permit at most one automatic invocation for the stable operation ID. Classify
  only three call outcomes: `ACCEPTED(job_id)`, `DEFINITELY_REJECTED`, or
  `OUTCOME_UNKNOWN`. A timeout, interruption, malformed success response,
  exception without positive non-acceptance, failure to persist a returned
  handle, or restart from `SUBMITTING` is unknown and never authorizes another
  call.
- Put the stable operation ID in bounded scheduler-visible metadata and the
  bootstrap registration. Reconcile a missing handle through the configured
  command/status seam: exactly one full identity match may repair the record;
  multiple matches are conflict; no match remains unknown unless the adapter
  returns positive evidence that acceptance was impossible. Queue/accounting
  absence and retention expiry are not positive evidence.
- Generate a deterministic SLURM script that invokes only a fixed Loom
  bootstrap with safe opaque identifiers/references. Authored stage command
  text, raw `SBATCH` directives, arbitrary preludes, service credentials,
  direct authority endpoints/credentials, secret environment values, and host
  paths supplied by the job must not enter the script or scheduler metadata.
- Expose a restricted bootstrap application view. Authenticate and authorize an
  exact profile, assignment, submission operation, scheduler job/cluster
  handle, bootstrap incarnation, request digest, issuer epoch, and current
  credential-policy revision. The bootstrap may only register/reconcile itself,
  transfer exact inputs/outputs, request the exact grant, report start/result
  evidence, inspect its cancellation, and replay that assignment's facts.
- Allow bootstrap registration to race the `sbatch` response and repair the
  same handle association, but never to create a new assignment or overwrite a
  conflicting handle. Require input/request durability before grant. Authority
  grant atomically promotes the bound attempt to `SUBMITTED` and creates the
  execution fence before authored code may start.
- Reuse the Phase 2 execution-only worker after the bootstrap durably records
  grant and start intent. The authoritative start permit is assignment/fence
  scoped and consumable once: an exact retry may return recorded state, while a
  duplicate/requeued bootstrap incarnation cannot receive a second root-launch
  authorization. Preserve safety if that conservative gate loses liveness
  across a crash between permit and actual process creation.
- Advance authority to `RUNNING` only from exact current-fence confirmed process
  evidence. Retain ambiguous launch as unknown and never relaunch it
  automatically. Continue an already-granted stage through temporary
  coordinator loss when inputs and authorization are already durable.
- Reuse the Phase 5 bounded artifact relay for input staging, output transfer,
  manifest verification, and coordinator/backend-accessible `ArtifactRef`s.
  A bootstrap is one-shot rather than an indefinite daemon outbox, so bound
  retention/retry exhaustion must surface explicit degraded/unknown state and
  never false success.
- Commit success only from an authenticated exact-fence Loom result plus
  verified accessible outputs. Preserve separate authority, dispatch,
  scheduler-observation, bootstrap/process, transfer/result, control, and
  service-health axes. SLURM `COMPLETED` alone is not success; a delayed SLURM
  observation cannot invalidate an already verified current-fence Loom result.
- Inspect only exact known or reconciled handles through bounded `squeue`/
  `sacct`-like values. Missing/lagged/unavailable observation is unknown. Provide
  an idempotent exact-handle `scancel`-like primitive whose success means only
  cancellation requested; Phase 8 owns run-level cancellation sequencing and
  fan-out.
- On coordinator restart, reopen every nonterminal submission record, retain
  the exact profile implementation/configuration needed by it, inspect known
  handles, reconcile unknown handles by stable identity, and accept exact old-
  issuer bootstrap/result replay only through the Stage 29 reconciliation path.
  No restart state may invoke `sbatch` again.
- Keep existing whole-run delegated queue dispatch, live single-job, and
  `afterok` planning/controller behavior and durable identities unchanged.
  Compatibility tests must prove a stage-level profile cannot accidentally
  route through those owners and their status/cancel paths remain readable.
- Add safe diagnostics for unknown/unauthorized profile, profile unavailable,
  unmappable request/rule, profile admission full, staging blocked, submission
  rejected/unknown/conflict, bootstrap awaiting coordinator/input/grant,
  scheduler status unavailable, completed without Loom result, result retention
  exhaustion, and cancel requested/settling. Diagnostics must expose stable safe
  IDs/codes only, not commands, paths, raw exceptions, account data, or secrets.

Out of scope:

- Automatic managed-agent-to-SLURM fallback, SLURM-to-agent fallback, multiple-
  profile ranking, elapsed-time route change, cost/queue-delay prediction, or
  using preference scores to choose the external route.
- Agents running inside acquired allocations, automatic allocation submission/
  provisioning, elastic capacity, job arrays, multi-stage `afterok` submission,
  gang/distributed stages, scheduler preemption/checkpoint resume, transparent
  SLURM requeue, or fair-share accounting.
- A generic `ExternalScheduler` protocol, remote submit gateway, DRMAA/REST
  integration, plugin discovery, or a universal scheduler constraint language.
  The current consumer uses the existing fakeable SLURM command boundary.
- Exactly-once `sbatch`, exactly-once authored effects, automatic retry of
  unknown work, or treating weak absence/timeout/operator text as containment.
- Allowing authored pipeline configuration to supply raw directives, commands,
  scripts, submit hosts, credential providers, live credentials, or profile
  implementation code.
- Replacing SLURM policy, modeling exact live cluster capacity, selecting the
  eventual node, or enforcing resource use after SLURM starts the job beyond
  Loom's existing stage execution/provider capabilities.
- Full run cancellation/retry/recovery user flows. Phase 8 composes ordinary
  cancellation; Phase 9 owns positive-containment close/retry.

Assumptions:

- The selected deployment has a submit-capable coordinator-side SLURM command
  adapter and scheduler-visible stable metadata that can find an exact
  submission operation within configured retention bounds.
- Compute nodes can run the fixed resident Loom bootstrap, authenticate back to
  the coordinator through a protected profile-owned delivery mechanism, and
  use the configured bounded artifact path.
- Project code/config is trusted workload code, but SLURM profile and service
  credentials remain protected deployment state and are not stage-authored.
- A conservative unknown state and possible manual intervention are acceptable
  when the database/external-call gap cannot be resolved positively.

## Fixed Contracts And Private Discretion

### Explicit route and profile

The observable route is closed and immutable for one stage work item:

```python
@dataclass(frozen=True)
class ResolvedExecutionRoute:
    kind: Literal["managed_agent", "slurm"]
    profile_id: str | None
    profile_descriptor: ComponentDescriptor | None
    profile_configuration_fingerprint: str | None
```

The SLURM variant requires all profile fields. The managed variant forbids
them. The exact private dataclass/module may change, but durable/wire encoding
must be versioned, plain data, strict about illegal combinations, and included
in the resolved placement fingerprint.

Illustrative trusted configuration and authored selection remain separate:

```yaml
# Protected site configuration.
slurm_profiles:
  training:
    partition: gpu
    account: configured-account
    max_outstanding: 8
    resource_mapping: strict
    bootstrap_environment: resident-loom
    data_path: coordinator-relay

# Authored/runtime stage selection may name only an authorized alias.
runtime:
  stages:
    train:
      placement:
        execution_route:
          kind: slurm
          profile: training
```

If `training` is unavailable, `train` waits or fails with that exact route
diagnostic. It does not run on a managed agent or another SLURM profile.

### Tagged target and admission

```python
AssignmentTarget = ManagedAgentTarget | SlurmStageTarget

@dataclass(frozen=True)
class SlurmStageTarget:
    profile_id: str
    profile_descriptor: ComponentDescriptor
    request_fingerprint: str
    submission_operation_id: str
```

The exact class names are private. The tagged semantic is fixed: a managed
target owns exact agent claim references; a SLURM target owns an exact retained
profile/submission reference and no agent claim. The coordinator reservation
transaction checks both the run slot and profile outstanding limit before
authority binding. Replays return the same assignment; a changed route/request/
profile fingerprint conflicts.

### Submission state and atomicity boundary

```text
exact attempt PENDING + ready
  -> reserve SLURM assignment/run/profile slot
  -> bind exact attempt (still PENDING)
  -> prepare immutable request/script/input-access evidence
  -> persist SUBMISSION_INTENT
  -> persist SUBMITTING
  -> call sbatch once
  -> ACCEPTED(job_id) | DEFINITELY_REJECTED | OUTCOME_UNKNOWN
```

`SUBMITTING` is the irreversible safety boundary. Loom cannot atomically commit
SQLite and submit to SLURM, so Stage 29 chooses at-most-one automatic call over
automatic liveness recovery. Reconciliation is permitted; resubmission of the
same operation is not.

```python
class SlurmSubmitOutcome(Enum):
    ACCEPTED = "accepted"
    DEFINITELY_REJECTED = "definitely_rejected"
    OUTCOME_UNKNOWN = "outcome_unknown"
```

Only a concrete bounded adapter result that positively proves no job was
accepted may return `DEFINITELY_REJECTED`. Raw exceptions, timeout, caller
cancellation, process death, an unusable success response, or an uncommitted
job ID return `OUTCOME_UNKNOWN`. Safe adapter error codes/evidence are durable;
raw stdout/stderr/commands are not durable public status.

The stable operation ID must be present in a scheduler-visible field that the
configured resolver can match exactly and in bootstrap registration. Discovery
has closed cardinality behavior:

```text
one exact match   -> persist/confirm that handle
zero matches      -> remain unknown unless positive non-acceptance is proven
multiple matches  -> durable conflict; grant none
```

### Gated bootstrap and one authored root

```text
SLURM starts fixed Loom bootstrap
  -> authenticate assignment/submission/job/bootstrap incarnation
  -> reconcile exact scheduler handle
  -> stage and verify immutable request + inputs
  -> request exact grant
  -> authority binds fence and changes PENDING -> SUBMITTED
  -> record grant/start intent
  -> consume one root-launch authorization
  -> run execution-only stage worker
  -> report exact-fence process/result/output evidence
```

Bootstrap start is not stage start. The grant/start gate must survive a
duplicate process or scheduler requeue. Once any incarnation consumes or may
have consumed root-launch authorization, another incarnation cannot launch.
This is deliberately conservative: a crash in the uncertainty gap can strand
the stage for Phase 9 instead of risking duplicate authored effects.

The bootstrap credential is not an agent or coordinator credential. It is
short-lived or one-use, assignment/profile/digest scoped, and limited to the
bootstrap view. How the protected deployment makes it available without
putting secret bytes in the script, arguments, scheduler metadata, or authored
environment is private to the concrete profile provider and must pass
conformance/preflight.

### Result, scheduler observation, and cancellation truth

The joined view retains separate axes:

```text
authority: PENDING | SUBMITTED | RUNNING | terminal
dispatch:  INTENT | SUBMITTING | ACCEPTED | REJECTED | UNKNOWN
SLURM:     pending | running | terminal | unavailable/unknown
bootstrap: registered | input-ready | granted | start/result facts
transfer:  input/output progress | accessible final refs
control:   requested | effective | settling | terminal
```

Only authority owns lifecycle terminality. `SLURM=COMPLETED` does not mean
success; success needs the current-fence Loom result and verified accessible
outputs. Conversely, a valid committed Loom result is not rolled back because
SLURM accounting is late or unavailable.

An exact-handle `scancel` response means only that cancellation was requested.
It does not release the run/profile slot, close authority lifecycle, prove
process containment, or authorize retry. The primitive stores bounded exact-
handle evidence for Phases 8 and 9.

### Cross-phase contracts

- Phase 1 must already preserve route/profile fingerprint in resolved placement
  and stage work; this phase fills the closed SLURM route rather than widening
  route selection dynamically.
- Phase 2 owns the tagged assignment/run-slot transaction, authority bind/grant
  fence, and execution-only worker. This phase extends its target union and
  reuses its fence/launcher contract rather than creating SLURM-only lifecycle.
- Phase 3 coordinator storage must gain semantic SLURM submission operations
  and protected bootstrap application view without exposing generic CRUD.
- Phase 5 relay owns bytes and accessible final refs. This phase supplies a
  bootstrap principal/assignment but does not create host-path shortcuts.
- Phase 6 resource resolution supplies exact canonical requirements. The SLURM
  mapper either represents all applicable requirements or rejects the route;
  it cannot weaken them to make submission possible.
- Phase 8 owns run-level cancel ordering and profile reload/retention. Phase 9
  owns manual containment/close/retry. This phase supplies typed evidence only.

### Reproducibility and compatibility

- Persist canonical request/profile/script fingerprints and the exact selected
  profile descriptor for every submission. A later profile reload does not
  reinterpret nonterminal work.
- Deterministic scripts must vary only with canonical semantic inputs. Secret
  material and volatile scheduler observation never enter their digest.
- Existing whole-run delegated SLURM manifests, queue records, imports, CLI
  behavior, and live/`afterok` state remain readable and behaviorally unchanged.
- Mixed-route runs retain one managed-stage run owner: for example,
  `preprocess(managed_agent) -> train(slurm:training) -> evaluate(managed_agent)`.
  The coordinator does not transfer run ownership to the historical delegated
  SLURM controller.

### Private choices the executor may simplify

- Exact private module/class/table names, normalized internal dataclasses,
  indexes, transaction helper structure, command-result wrapper, and script
  renderer layout are discretionary when ownership and durable semantics hold.
- The first implementation may use bounded direct lookup/linear reconciliation
  with the existing `SlurmCommandRunner`; no generic gateway or solver is
  required.
- Scheduler metadata may use any safe configured field that is exact and
  queryable in the target environment. The field/value format must be
  versioned, bounded, collision-resistant, and tested, but is not a universal
  public SLURM naming convention.
- Status display wording is private. Owner-labelled axes, safe codes, freshness,
  and no lifecycle inference are fixed.

## Proportionality

- Existing seam reused: current SLURM command runner, directive/resource
  mapping, deterministic script helpers, job-ID parsing, status/cancel adapters,
  and fake/opt-in test harness; Stage 29 ready work, tagged assignment,
  authority fence, execution-only worker, and relay.
- Material additions and current justification: one resolved route/profile,
  retained profile registry, tagged SLURM target, durable submission operation,
  conservative reconciliation, restricted bootstrap view, and external status
  axis are the smallest boundaries needed to submit a ready stage without
  duplicate submission/start or false lifecycle completion.
- Optional hardening and future capability deferred: generic external-scheduler
  protocol, remote gateway, automatic route/profile policy, allocation-fed
  agents, arrays, transparent requeue, checkpointing, stronger credential
  delivery variants, independent durable object-store result upload, and richer
  cluster telemetry wait for a demonstrated consumer.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Every stage work item has exactly one immutable authorized route/profile | Runtime resolver plus coordinator admission | Authored/runtime config, profile reload, compatibility reads | Unexpected external submission or silent fallback | Default/explicit/unknown/disabled/changed/no-fallback tests |
| Every mapped SLURM request preserves all applicable hard semantics | Concrete SLURM mapper/profile | Canonical custom/GPU/VRAM/topology/agent rules | Under-requested resources or ignored constraint | Complete-map/reject matrix and directive snapshot tests |
| A SLURM assignment consumes run/profile slots but no agent capacity | Coordinator reservation transaction | Concurrent dispatch, replay, restart | Oversubscription, leaked slots, or phantom agent claim | Atomic limit/replay/release and mixed-target tests |
| One operation invokes `sbatch` automatically at most once | Coordinator submission store/dispatcher | Crash or timeout before/during/after command | Duplicate batch jobs and authored effects | Persist/call/response/commit crash matrix with one-call sentinel |
| Submit outcomes cannot turn uncertainty into rejection | Concrete command adapter plus dispatcher classifier | Exceptions, malformed output, process interruption | Unsafe unbind/retry and duplicate submission | Closed-outcome contract tests |
| A missing handle is repaired only by one exact identity match | Submission reconciler | `squeue`/`sacct` lag, retention, duplicate names | Wrong-job adoption or duplicate grant | Zero/one/multiple/conflicting discovery tests |
| Batch startup cannot launch authored code before current-fence grant | Authority CAS plus bootstrap view | Early scheduler start, coordinator outage, forged bootstrap | Unfenced execution and lifecycle corruption | Bootstrap-before-handle/input/grant tests |
| One assignment/fence permits at most one authored root invocation | Coordinator/authority start permit plus bootstrap journal | Duplicate/requeued bootstrap, lost response, crash | Duplicate user effects | Two-incarnation and every-start-edge launcher sentinel |
| Bootstrap authority is exact, least-privilege, and secret-safe | Transport identity, authorizer, profile credential provider | Script/env/metadata injection or stolen/expired credential | Remote code execution or cross-run mutation | Scope/replay/expiry/redaction/injection tests |
| SLURM terminal state never substitutes for Loom result/output truth | Authority result CAS plus artifact relay/status projector | `COMPLETED`, accounting lag, missing result | False success or premature descendants | Terminal/result/output race matrix |
| `scancel` acknowledgement is a request, not containment/release | SLURM control adapter plus joined status | Command success, lagged/missing observation | Unsafe retry or capacity release | Cancel primitive and no-terminal-inference tests |
| Restart reconciles and never resubmits | Coordinator startup reconciler | `INTENT`, `SUBMITTING`, accepted, unknown states | Duplicate batch job | Restart matrix over every durable edge |
| Historical whole-run SLURM ownership remains unchanged | Existing queue/live controllers plus compatibility facade | Shared helpers/schema changes | Regression or two lifecycle owners | Existing contract/integration/E2E suites plus route-separation test |

## Implementation Slices

Use five reviewable slices.

1. Add the closed route/profile model, protected profile registry/preflight, and
   strict canonical request/hard-rule mapping. Extend resolved placement,
   stage-work fingerprinting, safe diagnostics, and tagged assignment encoding,
   but do not call SLURM. Prove no fallback and compatibility reads first.
2. Add semantic coordinator-store operations for profile-slot reservation,
   immutable submission intent, `SUBMITTING`, closed outcome recording, exact
   handle association, and startup reconciliation. Compose the existing
   `SlurmCommandRunner` behind a concrete ready-stage dispatcher and prove one
   call under crash/timeout/replay before enabling bootstrap execution.
3. Add deterministic fixed-bootstrap script construction, stable scheduler-
   visible operation identity, exact zero/one/multiple discovery, restricted
   bootstrap authentication/application view, and handle-registration races.
   Keep authored execution blocked through this slice.
4. Reuse Phase 5 input relay, then connect the bootstrap through Phase 2
   authority grant/start permit and execution-only worker. Add result/output
   replay and owner-labelled scheduler/bootstrap axes; prove one root and no
   success before accessible output commit.
5. Add exact-handle observation and primitive cancel evidence, coordinator
   restart reconciliation, mixed-route E2E, historical SLURM regression, safe
   preflight/diagnostics, and opt-in real-cluster receipt. Update all affected
   feature/reference documents without claiming Phase 8/9 behavior early.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Public imports remain intentional and cheap; no SLURM import enters pure scheduling | Package/import checks pass; existing SLURM imports remain compatible |
| Unit | required | Route/profile validation, strict request mapping, deterministic script, closed submit classification, operation discovery, bootstrap authorization, status mapping | Unknown fields/combinations reject; no ignored hard rule; stable digest; zero/one/multiple outcomes; redaction holds |
| Contract | required | Durable tagged assignment/submission codec/store semantics and restricted bootstrap view | Exact replay succeeds; changed digest/profile/identity conflicts; at-most-one call/root; no broad role permissions |
| Integration | required | Coordinator/authority/dispatcher/bootstrap/worker/relay lifecycle under crash and outage | Persist-before-call, bootstrap-before-response, grant/start/result races, restart without resubmit, accessible refs before success |
| E2E / opt-in | mixed | Simulated mixed-route run is required; historical SLURM regression is required; real cluster is environment-dependent | `preprocess(agent) -> train(SLURM) -> evaluate(agent)` order and one owner; opt-in receipt records exact profile/job/result without gating default CI |

Required causal matrices:

- submission durability edge × command outcome:
  before intent, after intent, after `SUBMITTING`, command not invoked, accepted
  response lost, malformed success, definite rejection, handle-persist failure;
- bootstrap edge × coordinator/authority availability:
  before handle record, before input-ready, before grant, after grant response
  loss, after start intent, ambiguous launch, result/output replay;
- scheduler observation × Loom result:
  pending/running/completed/failed/cancelled/missing/unavailable against no result,
  current-fence success, current-fence failure, stale/conflicting result;
- duplicate identity × operation:
  exact replay, changed digest/profile/job/bootstrap incarnation, retired/expired
  credential, two exact scheduler matches;
- route/profile state × candidate state:
  agents available/unavailable, profile enabled/unavailable/full, mappable/
  unmappable resources, ensuring no cross-route fallback.

Targeted commands (confirm exact selectors during phase preparation):

    pytest -q tests/unit/loom/pipeline/executors/slurm
    pytest -q tests/unit/loom/queue/test_slurm_adapter.py
    pytest -q tests/contracts/test_queue_delegated_slurm_contract.py
    pytest -q tests/integration/queue/test_delegated_slurm_controller.py
    pytest -q tests/integration/pipeline -k slurm
    pytest -q tests/e2e -k slurm

Add targeted Stage 29 package/contract/integration selectors established by
Phases 1–5 for route, assignment, coordinator store, bootstrap view, execution-
only worker, relay, status, and restart. Do not invent unstable test paths in
this planning artifact; record the concrete commands during phase preparation.

Current Stage 29 adjacent selectors:

    pytest -q tests/unit/loom/scheduling/test_kernel.py
    pytest -q tests/unit/loom/pipeline/execution/test_managed_local.py
    pytest -q tests/unit/loom/queue/test_remote_stage_execution.py
    pytest -q tests/unit/loom/queue/test_agent_sessions.py
    pytest -q tests/integration/pipeline/test_managed_local_execution.py
    pytest -q tests/integration/queue/test_managed_local_controller.py
    pytest -q tests/integration/queue/test_agent_session_transport.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: accidentally reusing a whole-run controller as lifecycle owner;
  weakening a hard resource request during directive mapping; calling `sbatch`
  twice after uncertainty; launching authored code before grant; granting two
  bootstrap incarnations; leaking credentials through script/metadata/logs;
  treating scheduler completion/cancel acknowledgement as Loom terminality; or
  breaking existing SLURM behavior through shared-helper/schema changes.
- Review focus: route immutability/no fallback; store transaction around run and
  profile slots; exact persist-before-call edge; closed unknown classification;
  stable-operation discovery cardinality; bootstrap role scope and one-root
  gate; result/output authority; restart; and historical compatibility.
- Stop if:
  - the selected cluster cannot expose a safe exact operation identity for
    reconciliation or cannot deliver assignment-scoped bootstrap credentials
    without exposing secret bytes;
  - Phase 2 lacks a genuinely execution-only worker or at-most-one start permit,
    or Phase 5 lacks a bootstrap-usable authenticated artifact path;
  - a required hard resource/constraint can only be silently weakened;
  - current coordinator storage cannot durably distinguish `SUBMITTING` from a
    definitely unattempted state without reopening an accepted contract;
  - implementing the route requires changing historical whole-run SLURM
    lifecycle/durable semantics rather than composing narrow shared helpers;
  - validation finds any path to a second `sbatch` or authored root.
- Accepted debt and revisit trigger: conservative unknown may strand a job when
  the command was never invoked; accounting retention may prevent automatic
  repair; one-shot result retention is bounded; the coordinator host must be
  submit-capable; and real-cluster evidence is opt-in. Revisit only with a
  concrete need for a remote submit gateway, durable direct object backend,
  automatic route policy, allocation-fed agents, transparent requeue, or
  stronger scheduler identity/containment APIs.

## Executor Handoff

- Read section range: this entire phase plan; Stage 29 planning sections
  `Requirements`, `Explicit ready-stage SLURM route`, `Deployment configuration,
  bootstrap, and communication`, `Correctness Boundaries`, `Examples And
  Validation`, and `Phase Shaping`; manifest shared constraints and Phase 7 row;
  current SLURM feature docs and source files named above.
- Safe implementation slices: use the five slices in order. Keep `sbatch`
  disabled until route/profile mapping and durable `SUBMITTING` tests pass; keep
  authored root launch disabled until bootstrap/grant/one-start tests pass.
- Decisions not to revisit: explicit one-profile route only; no automatic
  fallback/ranking; SLURM is not an offer; coordinator owns durable submission;
  at-most-one automatic call; bootstrap before authored code; authority fence
  and result remain canonical; accessible outputs before success; no generic
  backend protocol; existing whole-run SLURM unchanged.
- Conditions requiring manager action: any public/durable compatibility change;
  inability to preserve a hard requirement; inability to establish exact
  operation/credential identity on the supported cluster; a demonstrated need
  to widen the bootstrap role; or any duplicate submit/launch path. Optional
  ergonomics, richer telemetry, additional profiles, or another backend are not
  blockers and remain deferred.

## Workflow State

- Manager preparation: complete at clean `origin/develop` `b57d65d`; dedicated
  branch/worktree, repository `samcantrill/loom`, verified Phase 6 merge,
  current route, assignment/start, worker, relay/result, SLURM seams, exact test
  selectors, target/title, and stop conditions recorded
- Expanded planning: no extra planner pass needed. Current source/harness
  matches the recorded external-call, bootstrap trust, and durable compatibility
  boundaries; the independent review remains required after implementation.
- Implementation: in progress; correction 1/3 adds the profile-owned operation
  marker and command discovery seam before ready-stage dispatch wiring.
- Refiner: not needed unless the executor returns one qualified blocker
- Pre-submit gate: pending manager-local validation and diff/contract review
- Independent review: expected because the phase contains an external submit
  ambiguity and remote execution authorization boundary; confirm against the
  current workflow risk at phase preparation
- Blocker corrections: 1/3 — superseded command-seam blocker; add profile-owned
  operation comment/discovery rather than treating job status as identity.
- PR and merge: pending; squash merge to `develop` after all gates pass

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | No implementation changes. The phase completion record was updated to retain the blocker. |
| Tests added or updated | None; implementation was stopped before a safe concrete submission path could be added. |
| Validated revision/tree state and evidence | Targeted exploratory unit coverage passed before it was removed; final tree contains only this completion-record update. Evidence: `src/loom/pipeline/executors/slurm/commands.py` defines `squeue` as `%i|%T|%r` and `sacct` as `JobIDRaw,State,ExitCode`, neither containing the required scheduler-visible operation metadata. |
| Validation-relevant changes after evidence | Completion-record update only; full validation was not run because no implementation was retained. |
| PR, review, and merge | pending |
| Residual risk and cleanup | Blocked. A profile-owned exact operation-discovery capability (including bounded safe parsing and zero/one/multiple cardinality) is required before `SUBMITTING` can be safely reconciled. No `sbatch`, bootstrap, authority, or historical whole-run SLURM path was changed. |
