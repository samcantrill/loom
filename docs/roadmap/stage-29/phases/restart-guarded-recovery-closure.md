# Phase 9A Execution Plan: Managed Supervisor And Restart Closure

## Metadata

- Status: blocked
- Roadmap stage and phase: Stage 29, Phase 9A
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9a-restart-guarded-recovery-closure`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-29-p9a-restart-guarded-recovery-closure`
- Base revision: clean `origin/develop` at
  `44d06f329be6660fb12ab3ccc37cc443681733f2`
- PR target: `develop`
- PR title: `feat(scheduling): close managed restart supervision`
- Dependencies: Phases 1–3D, 4A, 5A, 6, 7B, and 8A merged. Blocked
  Phase 9 source candidate `ef3be2f` and metadata head `65f51cd` are
  selective read-only evidence, not a dependency base or supported schema.
- Workflow path: expanded because privileged irreversible fencing, process
  evidence, stale results, retry, and session replacement interact. The
  behavior/design contract is already finalized; one independent implementation
  review remains required.
- Blockers: correction 3/3 found a new concrete configuration-identity conflict
  before making source changes. Current remote agents support multiple protected
  `ResidentExecutionProfile` values, but foundation `ea6e06c` binds the entire
  supervisor root to one `profile_fingerprint`; the first selected profile makes
  every other configured profile fail. Restricting the current public remote
  configuration to one profile is not an accepted requirement. Fresh Phase 9B
  instead binds the supervisor to the canonical complete allowed profile set and
  selects one exact member per launch. No PR is opened for this phase.

## Objective And Context

- Vertical outcome: both embedded/local and remote HTTP agents execute through
  one separately running durable supervisor, and the agent application can
  restart against intact journal/workspace/supervisor state without launching a
  second managed root, losing a valid result, or advertising capacity before the
  complete retained set is reconciled.
- Selectively reuse only the validated resident-worker hard cut and supervisor
  foundation from blocked Phase 9/early Phase 9A. Fresh schema identities reject
  every old or blocked-candidate root; no migration or PID adoption is supported.
- Phase 9C owns coordinator/SLURM restart, positive-containment guarded recovery,
  authority terminal-or-close/retry, and physical-release separation.
- Phase 9D owns complete different-session replacement, final joined/public
  operations and operational docs, full Stage 29 E2E, validation, and summary.
- Coordinator HA, power fencing, checkpoint migration, supervisor HA, and
  automatic takeover remain out of scope.

## Current Source And Harness

- Current `origin/develop` contains no Phase 9 production source. Selectively
  restore only the validated `ef3be2f` resident-worker hard cut from the
  blocked branch; do not import its roadmap metadata, branch history, or any
  abandoned schema identity.
- Reuse all durable coordinator/authority/agent/transfer/control facts, expected-
  state operations, execution fences, role locks, component/config identities,
  outbox acknowledgements, SLURM submission/bootstrap/observation facts,
  retained profile descriptors, and status/audit from earlier phases.
- The current managed execution boundary is not restart evidence. Embedded
  execution stores `_ManagedWorkerHandle` thread objects only in
  `SQLiteAgentJournal._process_handles`; the remote agent stores `Popen` objects
  only in `LocalDaemonAgentHttpClient._processes` while its durable workspace
  records only a PID and `process_execution_id`. Neither owner can rebind a live
  or contained process to exact `(assignment_id, process_execution_id)` evidence
  after the agent process exits. PID/workspace presence or absence cannot repair
  that gap.
- The embedded helper also accepts optional in-process execution services
  (`executor`, artifact-store/resource-validator/plugin objects, and a Python
  `process_launcher`). The production daemon supplies none of them, and the
  remote resident path already supports only the fixed serializable worker
  request. They are an obsolete test/helper seam, not a supported managed
  execution contract. The approved compatibility-free cut removes them from the
  managed path instead of making arbitrary Python objects serializable.
- The current `SlurmReadyStageProfile` similarly supplies operation discovery,
  `squeue`/`sacct` observation, `scancel`, and job-private capability revocation,
  but no operation can produce an exact positive-containment receipt. Those
  mechanisms remain reconciliation/control inputs, never recovery evidence.
- Reuse the current fixed resident-stage-worker request/result path, but replace
  both managed handle maps with the one agent-side supervisor boundary fixed
  below. `record_retry_decision_for_stage_result()` remains the existing
  reliability evaluator and `RunOrchestrator` already consumes authority-owned
  retry decisions, but production `LocalDaemonExecution` does not currently
  compose that evaluator. Generalize/compose this existing path as fixed below;
  do not create recovery-local retry rows or policy. Rediscover SQLite
  corruption/schema behavior and user-service documentation conventions only
  where the slices below require them.
- Use real child-process barriers plus fake clocks/transports. Recovery tests must
  exercise process/output state, not only mock status flags.
- Phase-specific tests and `make validate-pr` were required here. Full Stage 29
  E2E and `make test-summary` remain Phase 9D-owned after Phase 9C merges.

## Scope

In scope:

- Finalize one protected `ResidentWorkerLaunchProfile` containing exact
  descriptor, resolved project root, and Python executable. Bind it in local and
  remote protected configuration, supervisor configuration fingerprint, and
  canonical launch digest.
- Implement one separately running, separately locked, locally authenticated
  queue-owned supervisor service/client. Explicit fresh agent-root
  initialization creates its current schema and stable supervisor identity;
  ordinary start is open-only and requires the service before agent availability.
- Persist the complete launch identity before spawn; make exact launch replay
  idempotent; classify only `NOT_ACCEPTED`, `STARTING`, `RUNNING`, `EXITED`,
  `CONTAINED`, or `UNKNOWN`. A stop acknowledgement is not containment.
- Materialize the complete permitted child environment before launch. Never
  merge ambient supervisor state at spawn.
- Prove `CONTAINED` only after the continuously owning supervisor establishes
  that the complete process group cannot execute or resume. Continuity loss,
  endpoint loss, PID presence/absence, root exit, or an unbound result is
  `UNKNOWN`.
- Generalize the private queue assignment workspace for both embedded/local and
  remote agents. Stage immutable inputs before launch, run only the fixed
  resident worker, retain outputs/results, and import them through the ordinary
  journal/coordinator/authority path.
- Move/split embedded managed composition under `loom.queue`; remove optional
  executor/artifact-store/resource-validator/plugin/process-launcher services,
  `_ManagedWorkerHandle`, journal `_process_handles`, and remote
  `_processes` as production lifecycle owners. Pipeline execution never imports
  queue.
- Hard-cut local and remote agent journal/workspace/root schemas. Old, missing,
  corrupt, copied, or profile/supervisor-mismatched state fails before session
  resume, work polling, or capacity offer with
  `managed_supervisor_state_requires_reinitialization`.
- Complete same-session restart: acquire the role lock, force zero availability,
  reconstruct every retained assignment/claim/profile/event/result/output/outbox
  reference, join exact supervisor receipts, replay normal results and releases,
  retain unknown claims unavailable, then publish only a fresh full observation.
- Preserve Phase 5 coordinator/authority restart semantics and exact execution
  fences with causal regressions.
- Add focused supervisor-before-agent service guidance and managed restart
  diagnostics needed to operate this vertical path.

Out of scope:

- No SLURM restart or containment helper, manual recovery close, retry decision,
  different-session replacement, broad CLI recovery workflow, or final Stage 29
  validation/summary in this phase; Phase 9C/9D own them.
- No legacy compatibility, implicit current-process profile, second process
  owner, PID adoption, timeout takeover, automatic failover, or claim release
  while work is unknown.

## Fixed Contracts And Private Discretion

### Same-session restart state machine

```text
supervisor continuity and protected identity verified
  -> agent role lock acquired
  -> current journal/workspace schemas opened and identity verified
  -> availability forced to zero and work requests suppressed
  -> nonterminal assignment/process/output set reconstructed
  -> each exact supervisor launch/query receipt joined to its journal binding
  -> coordinator authenticated and session resumed
  -> ordered events/results/outputs replayed and durably acknowledged
  -> physical claims released/reconciled or retained unavailable
  -> resources/config observed
  -> fresh availability published
```

The one authoritative managed-process owner is a separately running,
agent-local supervisor. It is mandatory in both production compositions:
embedded/local execution and `LocalDaemonAgentHttpClient` use the same client
and protocol. The supervisor is application infrastructure under `loom.queue`,
not a public scheduler/executor/plugin protocol. `loom.queue` may consume the
import-light `StageWorkerRequest`/`StageWorkerResult` and the fixed resident
worker entrypoint from `loom.pipeline.execution`; `loom.pipeline.execution`,
`loom.scheduling`, stores, and public root imports must not import the supervisor
or queue application. The agent journal/workspace owns assignment, provider,
event, transfer, and result replay facts, but no longer owns an in-memory process
handle or infers process state. The supervisor exclusively owns spawn, process-
group containment, exit observation, and containment evidence.

Initialization creates a protected, separately locked supervisor root and one
stable `supervisor_id` bound to the configured `agent_id`; ordinary start is
open-only. One live supervisor continuity epoch may span any number of agent
daemon restarts. The supervisor uses a protected local authenticated endpoint
and accepts only a fixed, fully materialized resident-worker launch
specification, never an authored command or Python callable. Both managed paths
stage the existing execution-only request in an agent-private assignment
workspace before launch. Exact private file layout, IPC syntax, and process-
group mechanism remain discretionary.

The supervisor root is the protected `supervisor` child of the existing
`agent_root`; it is derived by `LocalDaemonConfig`/`AgentTlsClientConfig`, not an
independently authored path. Explicit fresh agent-root initialization creates
and binds it, the separately running supervisor service opens and locks it, and
the agent daemon/client only opens the matching endpoint. An absent, old, or
mismatched supervisor root fails before resume or availability. This adds no
second public configuration choice and gives both embedded and remote managed
paths the same lifecycle.

The fixed launch specification contains only canonical plain data: the staged
`StageWorkerRequest`, workspace/result locations, the bounded environment
derived from retained provider commands (including GPU bindings), and the
complete identity below. Remove `executor`, `artifact_store_factory`,
`selected_plugin_records`, `resource_validator_registry`, and `process_launcher`
from `run_managed_local_assignment`; do not preserve an alternate callable
branch. Orchestration callbacks that stay in the agent process are not part of
the launch specification. Tests that need start failure or launch races inject
them at the supervisor client/protocol boundary or use the real supervisor's
fault barriers, while lower-level stage-worker tests continue to cover custom
execution services outside managed execution.

The shared staged assignment workspace is private queue application
infrastructure. Extract/generalize the existing queue-owned
`_RemoteAssignmentWorkspace` for both embedded/local and remote agents; it may
import `StageWorkerRequest`, `StageWorkerResult`, and the resident worker
entrypoint from `loom.pipeline.execution`. Move/split the embedded composition
currently named `run_managed_local_assignment` above that queue-owned workspace
and supervisor client, and remove it from the pipeline execution surface. The
pipeline package retains generic worker models/execution and does not import
`loom.queue`. This is the existing documented direction—agent application owns
physical binding/execution—and does not create a public workspace or supervisor
protocol.

### Fixed local resident launch-profile decision

The shared workspace removes any need to serialize or reconstruct
`LocalRunStore`: the parent stages each immutable input before launch, the
resident worker writes outputs under the assignment workspace, and the queue
composition imports those outputs through the ordinary authority path. What is
not currently configured for embedded execution is the child process's exact
Python executable, project root, and durable environment/project/executor
descriptor.

Add one required protected `ResidentWorkerLaunchProfile` value
containing that descriptor plus resolved `project_root` and
`python_executable`. `LocalDaemonConfig` binds one local value, and the existing
remote `ResidentExecutionProfile` composes the same launch-profile value with
its capacity inventory. The launch profile is included in the supervisor
configuration fingerprint and launch digest; initialization records it and
ordinary restart requires an exact match. This preserves one owner for launch
environment while local capacity remains owned by the existing local daemon
capacity fields. Under the approved hard cut, configs and roots without this
value are rejected rather than inferred or migrated.

Rejected alternative: deriving the profile from `sys.executable` and
`Path.cwd()` at agent start would avoid one explicit config value, but a restart
from another environment/directory could silently launch different code under
the retained execution fence.

The durable launch identity is:

```text
supervisor_id + supervisor_continuity_epoch
+ agent_id + session_id
+ assignment_id + process_execution_id + execution_fence
+ launch_operation_id + canonical_launch_spec_digest
```

Before calling the supervisor, the agent journal durably records that complete
identity and the supervisor descriptor/configuration fingerprint. `launch` is
idempotent by `launch_operation_id`: an exact replay returns the same accepted
record and a changed field conflicts. The continuously running supervisor
persists acceptance before spawning one new process group and never spawns a
second root for an accepted operation. Its bounded query result is one of
`NOT_ACCEPTED`, `STARTING`, `RUNNING`, `EXITED`, `CONTAINED`, or `UNKNOWN`, and
echoes the complete identity, supervisor revision, and launch-spec digest.
`EXITED` carries the root exit and optional durable worker-result digest but does
not prove that descendants are gone. `CONTAINED` carries the final exit/result
digest, if any, and is issued only after the supervisor that continuously owned
the boundary has positively observed that its complete process group can no
longer execute or resume. An idempotent `request_stop` is bound to the same
launch identity plus one control operation ID; its acknowledgement means only
requested, and only a later `CONTAINED` query is containment. `UNKNOWN`, endpoint
absence, an identity/configuration/continuity mismatch, a raw PID, an unbound
result file, or a stop acknowledgement proves nothing.

Restart reconciliation is causal:

- `NOT_ACCEPTED` permits submission of the same recorded launch operation, not a
  new start fence or operation. This covers a crash after journal intent but
  before the supervisor call.
- `STARTING` or `RUNNING` resumes observation/control without launch.
- `EXITED` retains the result but continues to withhold the claim while any
  descendant can execute. `CONTAINED` plus a matching result digest imports the
  result into the ordinary journal/outbox path. Positive containment without a
  valid result becomes the existing bounded executor-infrastructure failure; it
  is not a recovery close.
- `UNKNOWN` or any mismatch keeps the exact claims/capacity unavailable and the
  assignment unknown. The agent does not allocate around it or invoke launch.

If the supervisor process itself loses its continuity epoch, it must mark every
previously nonterminal record unknown and must not adopt or kill by PID. This
phase guarantees agent restart under a continuous configured supervisor, not
supervisor HA, reboot fencing, or recovery after supervisor-state loss. A
managed positive-containment proof used by privileged recovery is the
supervisor's persisted `CONTAINED` receipt for the complete launch identity;
status or an agent assertion cannot synthesize it.

### Fixed shared resident-assignment bundle decision

Both managed paths use one current queue-private, assignment-local bundle and
workspace. Generalize the existing remote request/workspace rather than adding
an embedded-only format. Exact private names may differ, but there is one schema
and one codec with this semantic content:

```python
@dataclass(frozen=True)
class ResidentAssignmentBundle:
    assignment_id: str
    stage_work_id: str
    attempt_id: str
    offer_id: str
    claim_id: str
    profile: ResidentProfileDescriptor
    stage_name: str
    attempt: int
    prepared_at: str
    executor_name: str
    fingerprint: Mapping[str, PlainData]
    resolved_runtime: Mapping[str, PlainData]
    worker_metadata: Mapping[str, PlainData]
    inputs: tuple[ResidentInputManifest, ...]
    declared_outputs: tuple[str, ...]
    claims: tuple[ResourceClaim, ...]
    provider_descriptors: tuple[SchedulingComponentDescriptor, ...]
```

This is the existing `_DeliveredExecutionRequest` semantic payload made shared;
the existing `_RemoteAssignmentWorkspace` becomes the one resident assignment
workspace. No compatibility aliases or second schema remain. The bundle does
not carry the coordinator's run URI, a run-store root, an arbitrary host path,
an authored command, a Python object, or credentials. It is durably persisted
before acceptance and is included, by exact canonical digest, in the supervisor
launch specification.

For embedded/local execution, the queue parent projects the already-prepared
`StageWorkerRequest` into this bundle exactly as the remote-delivery parent does:

1. Parse the required `ResidentWorkerLaunchProfile.descriptor` as the existing
   exact `ResidentProfileDescriptor`; local and remote therefore bind identical
   project/environment/executor identity without duplicating capacity fields.
2. Convert each `StageWorkerRequest.inputs` artifact with the existing no-follow
   regular-file manifest operation, then copy its bounded bytes into
   `assignments/<assignment_id>/inputs` and verify size/digest before acceptance.
3. Persist claims/provider descriptors, accept, grant, and construct the child
   `StageWorkerRequest` only from assignment-local input/log/result paths. The
   child uses `loom-agent:<assignment_id>` as its private run identity.
4. Retain and digest-check result/output bytes in the same workspace. The queue
   parent maps the exact child result/failure identity back to the journal-owned
   original `run_uri`, constructs `ArtifactRef` values only for verified retained
   outputs, and feeds that result into the existing journal/coordinator/authority
   finalization and physical-release order.

The local projection reads the original run store only in the parent while
preparing the existing `StageWorkerRequest` and source input bytes. Neither the
supervisor nor child receives `LegacyRunStore`, an artifact-store factory,
plugins, validators, an executor object, or a callable launcher. Workspace bytes
stay retained for restart/replay and are removed only after the existing durable
result/output acknowledgements and physical release permit cleanup.

`LocalDaemonConfig` therefore requires one protected
`ResidentWorkerLaunchProfile`; there is no default derived from `sys.executable`
or the current directory. Its descriptor must be the exact plain-data encoding
of `ResidentProfileDescriptor`. `ResidentExecutionProfile.launch_profile`
continues to provide the same value for remote agents. Missing, extra, malformed,
or mismatched descriptor fields fail the hard-cut initialization/open boundary.

### Private discretion

Supervisor IPC syntax, private file layout, service-manager syntax, bounded
reconciliation retry, and process-group implementation remain private. The
separate owner/service lifetime, exact launch/profile identity, bounded states,
positive containment requirement, queue import direction, hard-cut schemas,
zero-availability restart order, and no-repeat launch are fixed.

## Proportionality

- One supervisor and one workspace serve two current production managed paths;
  no public extension protocol or generic process framework is added.
- Existing worker request/result, journal, provider, event, output, and authority
  facts are reused. The phase adds only the missing restart-proof process owner
  and reconciliation composition.
- SLURM recovery, guarded authority close/retry, and session replacement are
  deferred to their linked vertical consumers rather than partially implemented.

## Invariant Ownership

| Invariant | Owner | Invalid boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Exact launch operation creates at most one root | Supervisor | Crash before/after durable acceptance/spawn | Duplicate stage effects | Real child sentinel at every edge and exact replay/conflict tests |
| Agent restart never becomes supervisor restart | Deployment/service composition | Agent process exit/reopen | Lost containment evidence | Agent-restart-while-worker-running tests in both paths |
| Restart begins with zero availability | Agent startup/reconciler | Retained offer/poll | Capacity collision | No-offer/no-poll barriers until complete reconciliation |
| Only continuous process-group proof is contained | Supervisor | Root exit, PID, endpoint loss, stop ack | Unsafe release/takeover | Descendant/ignored-signal, supervisor-loss, mismatch negatives |
| Missing/corrupt/copied state is not empty state | Root/schema owner | Open/init boundary | Duplicate ownership | Identity/schema/permission/copy tests before side effect |
| Verified result follows the ordinary authority path | Journal/coordinator adapter | Result-before-agent-receipt/restart | Lost or stale output | Result/output/outbox replay and exact-fence tests |
| Unknown work retains physical capacity | Provider/reconciler | Incomplete receipt/release | Concurrent reuse | Capacity remains withheld until ordinary release |

## Implementation Slices

1. Correct the supervisor foundation into the separately running locked/
   authenticated service/client, exact profile/environment/launch codec, positive
   process-group containment owner, and fresh hard-cut root schema.
2. Generalize the existing remote request/workspace into the fixed resident
   bundle above; project embedded inputs/results exactly; route both managed
   paths through it and the supervisor. Remove both old process owners and all
   obsolete resident/managed callable service hooks.
3. Implement same-session startup reconciliation at zero availability, exact
   supervisor query/replay, ordinary result/output/outbox completion, retained
   unknown capacity, fresh provider observation, service guidance, diagnostics,
   and Phase 5 restart regressions.

## Test And Validation Plan

| Suite | Required behavior |
| --- | --- |
| Package/type | Queue-private supervisor remains non-public; pipeline imports no queue; strict current schemas/profiles type-check |
| Unit | Exact launch/profile/environment and resident-bundle codecs, local projection/replay/conflict, bounded states, lock/auth, continuity loss, process-group containment, schema/identity rejection |
| Contract | Local and remote managed paths expose identical supervisor-backed start/query/result semantics; old roots and callable launch paths reject |
| Integration | Real child barriers for crash before acceptance, after acceptance, while running, after result-before-journal, descendant containment, agent restart, result/output replay, zero availability, fresh observation |
| Regression | Phase 5 coordinator/authority restart preserves valid fences/results with the new supervisor records |
| Focused commands | Supervisor unit tests; managed-local integration; agent-session transport restart tests; local-daemon production tests; package import tests; Ruff and Pyright on changed paths |

Run all phase-specific suites before `make validate-pr`. Full Stage 29 E2E and
`make test-summary` remain Phase 9D-owned after Phase 9C merges.

## Risks, Review, And Stops

- Main risks: an in-process object masquerading as the separate supervisor;
  ambient environment outside the launch digest; root-exit/PID treated as group
  containment; old root opened as empty; agent offer/poll before reconciliation;
  either old process owner retained; result replay bypassing exact authority.
- Stop if a qualifying managed path cannot use the fixed resident worker/
  workspace, the separate service cannot continuously own the process group, or
  positive group containment cannot be proven without a new external authority.
- Do not stop for Phase 9C/9D work; it is explicitly outside this phase.
- Independent review is required because containment and restart can affect later
  authority close/retry safety.

## Executor Handoff

- Read this file, blocked Phase 9 plan, candidate `ef3be2f`, foundation
  `ea6e06c`, environment correction `24b8c9c`, Phase 8A completion, and the
  linked Phase 5 restart evidence.
- Implement only this phase's three slices completely. Do not implement or
  partially scaffold Phase 9C/9D behavior.
- Preserve the accepted hard cut and explicit launch profile. Replace, rather
  than adapt, both old in-memory process owners.
- Use real separately running supervisor/agent processes and causal barriers;
  mock state flags alone do not prove restart or containment.
- Finish the phase-specific gates and commit source/tests/docs. Do not edit
  roadmap metadata or perform GitHub operations.
- Escalate only a concrete new blocker meeting the stop conditions above.

## Workflow State

- Manager preparation: complete on clean merged Phase 8A baseline `44d06f3`;
  Phase 9 blocked evidence and fresh Phase 9A branch/worktree recorded
- Expanded planning: scope reshaped manager-locally into managed restart (9A),
  SLURM guarded recovery/retry (9B), and replacement/final operations (9C)
  without changing any accepted behavior or boundary
- Implementation: foundation `ea6e06c` and exact-environment correction
  `24b8c9c` committed; separate service, production paths, and restart remain
- Refiner: first turn stopped on the missing exact embedded workspace projection;
  manager fixed that queue-private contract. The one directly related final turn
  then stopped, without source changes, on the single-profile supervisor versus
  supported multi-profile remote configuration conflict
- Pre-submit gate: pending
- Independent review: required
- Blocker corrections: 3/3 exhausted; correction 1 fixed ambient environment,
  correction 2 identified the shared-bundle gap without source changes, and
  correction 3 identified the profile-set conflict without source changes
- PR and merge: no PR; Phase 9A is blocked read-only evidence. Fresh Phase 9B
  starts from current `origin/develop` with a complete-set supervisor identity

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Foundation `ea6e06c`: resident-worker hard cut; new private single-profile supervisor launch/profile/receipt store; supervisor-root initialization hook; remote profile projection. Correction `24b8c9c` makes launch environment exact. No production integration landed. |
| Tests added or updated | New supervisor exact-replay/conflict and continuity-loss tests. Refiner reran supervisor, remote-stage-execution, and managed-local focused suites: 26 passed. |
| Validated revision/tree state and evidence | Manager-committed source evidence through `24b8c9c`; roadmap disposition at the current blocked head. No full gate claimed. |
| Validation-relevant changes after evidence | None; both refiner turns made no source changes. |
| PR, review, and merge | No PR opened; correction 3/3 exhausted. |
| Residual risk and cleanup | Single-profile supervisor cannot serve the supported multi-profile remote configuration. Branch/worktree retained read-only; fresh Phase 9B owns the canonical complete profile-set fix and full vertical outcome. |
