# Phase 5 Execution Plan: Agent-Owned Slurm Jobs

## Metadata

- Status: pending
- Roadmap stage and phase: 41 / 5
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p5-agent-slurm-jobs
- Worktree: manifest root, suffix `stage-41-p5-agent-slurm-jobs`
- Base revision: published develop after Phase 4 merges; record exact SHA at execution preparation
- PR target: develop
- PR title: Move the complete Slurm job lifecycle to its assigned agent
- Dependencies: Phase 4 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: source predecessor pending; no unresolved planning blocker

## Objective And Context

One assigned agent submits, observes, cancels and recovers the exact Slurm job without duplicate submission or capacity accounting.

Consume Phase 1 checked Slurm preparation, Phase 3 lifetime and Phase 4 execution handles. Keep the proven grant/bootstrap and current result relay for the connected journey. Phase 6 supplies the stronger result-delivery guarantee after compute exit during coordinator downtime.

Requirements: FR-41-06/09/10/12/15; supporting FR-41-13. Design: DQ-41-03/07.
Validation ownership: VAL-41-08/09.

## Current Source And Harness

- `src/loom/pipeline/executors/slurm/ready_stage.py`: SQLiteReadyStageSubmissions, SlurmReadyStageProfile, exact operation markers/handles and uncertain-call discovery.
- `src/loom/queue/slurm_ready_stage.py`, `slurm_bootstrap.py`: assignment/grant/start, native report relay and current bound workspace.
- `src/loom/queue/agent_sessions.py`, `agent_session_transport.py`, `local_daemon_runtime.py`, `deployment.py`: authorized offers, placement and role transport.
- `src/loom/queue/local_daemon_execution.py`: former coordinator submission owner and retained-work checks.
- Existing unit/integration ready-stage Slurm tests, scheduler command fakes and real-process agent transport seams; Phase 6 owns completed-job storage qualification.

## Scope

Move the external-call journal and complete job lifecycle together: authorized profile capacity, agent assignment, submission intent/acknowledgement, bounded observation, grant fencing, cancellation and restart. Preserve existing result/finalizer wiring until Phase 6 extends transport.

Assume the predecessor's accepted contracts and existing qualified installations.
Each phase includes its code, owner-level tests, current docs and replaced-code
removal. Preserve unrelated work and current scientific/resource meaning.

## Implementation Walkthrough And Examples

### What changes and why

The coordinator chooses an authorized submit agent/profile and retains the
assignment. The assigned agent owns the exact Slurm external-call journal,
scheduler commands and durable observations. Existing ready-stage submission
mechanics move to that owner; the coordinator must lose the ability to submit
the same assignment in this phase.

Internal pseudocode illustrates the boundary. These helper names are not a new
public interface or prescribed storage design:

```python
operation = journal.open_or_create(
    operation_id=assignment.submission_operation_id,
    exact_request=assignment.submission_request,
)

# The owner checks accepted intent/cancellation and durably records SUBMITTING.
if journal.claim_first_submission(operation):
    outcome = invoke_sbatch_once(operation.request)
    journal.record_outcome(operation, outcome)
else:
    reconcile_existing_submission(operation)
```

The claim is serialized at the single submission owner. An accepted outcome has
an exact cluster/job handle; a definite rejection and an uncertain outcome remain
different facts. A command can reach Slurm while its response is lost. If the
agent crashes before recording the response, the retained SUBMITTING operation
must reconcile that possibility instead of invoking sbatch again.

### Recover the same external job

| Stable operation-marker evidence | Recovery action |
| --- | --- |
| One exact matching job | Recover that handle and continue observation |
| No match in available evidence | Remain unresolved; absence alone does not permit resubmission |
| Multiple matches | Report conflict; do not select a convenient job |

This is at most one automatic invocation for this submission operation. A later
attempt can be authorized by the existing run retry policy after the relevant
execution/failure/containment conditions resolve; it is a distinct operation.
Agent/coordinator restart preserves the original accepted identities and reopens
their retained records. A missing original journal is not an empty new submitter.

### Submission capacity, grants and cancellation

A submit agent advertises authorized external profiles, not the GPUs that Slurm
will allocate. If two agents offer profile gpu-batch with a shared outstanding
limit of ten jobs, together they still have ten reservations. The submit host
does not need to advertise the requested compute GPUs as local resources.
Unknown/live submissions retain their reservations; Slurm owns actual allocation
enforcement and its reported resource evidence.

The agent observes live/accounting evidence through the existing bounded squeue/
sacct command mechanisms and reports source/freshness. Helper exit, queue absence
and scheduler completion are separate observations. They cannot independently
commit a Loom result or release an unresolved assignment.

Submission permission also differs from permission to execute project code:

```text
coordinator assigns -> agent submits -> Slurm starts restricted bootstrap
                                             |
                                             v
                              current input checks and start grant
                                             |
                                             v
                                       stage worker
```

Already-granted work may continue during coordinator downtime. Ungranted work
waits with bounded reconnection/deadline behavior. Cancellation first records
authority intent, then suppresses an unissued call or discovers/cancels the exact
job. A successful scancel command does not itself prove containment. Grant checks
prevent a cancelled pending attempt from starting later.

VAL-41-08/09 checks cover helper exit with live work, shared quota, response loss,
restart and cancellation races. Submission, uncertainty, cancellation and recovery
remain one implementation unit. This phase uses current typed result relay for
connected execution; [Phase 6](slurm-result-recovery.md) completes recovery of
results after compute exit during coordinator downtime.

## Fixed Contracts And Private Discretion

### Profile, placement and capacity

Experiments select a permitted Slurm profile and declare existing normalized
resource requirements. Protected site configuration supplies cluster identity,
submit-host qualification, account/partition/QoS, resource translation, bounded
command/time/poll policy, coordinator trust/bootstrap access, installed worker
environment or container and compute/submit-agent result-root bindings. Secrets,
arbitrary scheduler commands and service policy never come from stage parameters.

Extend the existing authorized agent inventory/offer with external submission
profiles, distinct from local compute capacity. The coordinator policy must
authorize the agent/profile pair; self-advertisement alone is insufficient.
Slurm GPU demand does not require submit-host GPUs or reserve them as local
compute. Preparation still needs its own eligible installed preparation worker.

Coordinator assigns exactly one submit agent and allowed backend/profile revision
to an attempt. Retain existing run/attempt/assignment/fence identity plus the
agent owner, exact submission operation ID, protected profile snapshot and result
binding. Reuse current schema/value types where meanings match; version changed
wire/durable forms and fail before mutation on incompatible versions.

Run stage slots and profile `max_outstanding` reservations stay with coordinator
placement. A profile's outstanding quota is shared across its authorized submit
agents, keyed by the stable profile identity, not multiplied per offer or reset
by profile revision. Agent records acknowledge the same reservations and do not
create a second aggregate count. Unknown/live submissions retain reservations;
submission-helper exit, offer expiry or observer loss cannot release them.
Slurm owns actual allocated compute enforcement and its reported control evidence.

### One external-call owner and reconciliation

The assigned agent persists intent and SUBMITTING before at most one automatic
sbatch invocation for the exact operation. Reuse the current ready-stage journal
and command runner under the agent root. Persist accepted handle, definite
rejection or uncertainty before acknowledging to the coordinator. Coordinator
retains assignment intent and acknowledged backend projection; it never calls
sbatch for these assignments. Co-location uses the same application contract.

Backend evidence carries assignment/operation/profile/agent identity, native
submission disposition, nullable exact cluster/job handle and timestamped source
observations. Use the existing idempotent agent outbox/acknowledgement conventions;
replayed or stale process-session messages do not create a new operation. Private
poll grouping and local helper objects remain implementation discretion.

After restart reopen the same agent journal and handles before offering free
capacity. A new coordinator process epoch does not erase an accepted attempt's
execution identity. Discover an uncertain call using its existing stable marker
in live/accounting evidence: one exact match repairs, zero remains unknown,
multiple conflict. Do not transfer submission authority to another agent merely
because the original agent is unreachable. Lost expected agent state is explicit
unresolved recovery, not permission to reconstruct an empty submitter.

Observe squeue for live jobs and sacct for available accounting using bounded
commands/backoff; sstat is optional resource-statistics evidence. Retain observed
time, acceptance time and source/freshness using existing inspection conventions.
Queue absence/accounting delay is unknown. A successfully exited helper does not
terminalize a stage; scheduler COMPLETED does not establish valid outputs.

### Start, cancellation and containment

Retain the restricted compute bootstrap. Submission permission is distinct from
permission to start project code: current assignment/input checks and the existing
start grant precede effects. Already-granted work may finish during coordinator
loss. Ungranted jobs reconnect with bounded backoff until the configured bootstrap
deadline; expiry produces a retained failure diagnostic, never an offline grant.
No automatic resubmission is inferred from deadline expiry or scheduler requeue.

Explicit cancellation first records authority intent/fence. Agent suppresses a
not-yet-issued call; if submission is in-flight/uncertain it discovers and cancels
the exact job. Pending work receives exact scancel while the start fence prevents
a new grant. Running work follows backend cancellation and containment observation.
Replaying cancellation never creates a fresh submission or grants stale work.

Job/descendant containment, accepted stage result and output publication are
separate facts. A cancel command's exit or a valid result alone does not prove
safe capacity release. Preserve existing allocation-delegated resource evidence;
do not claim local measured isolation. Late wrapper/accounting status cannot
overwrite an already committed output; reconcile discrepancies at the native
failure/settlement owner. Unresolved work prevents run-owned service retirement.

### Delivery boundary

This phase proves the connected Slurm execution/control journey using existing typed bootstrap result delivery. Reconcile coordinator-only, agent-only and joint restarts around job-handle ownership while result delivery remains available. Do not claim results can be recovered after their current storage disappears; Phase 6 supplies durable shared retention and completed-job recovery. These limits describe development delivery, not the final Stage 41 Slurm promise.

### Cross-phase handoff

Phase 6 consumes the exact agent/assignment/attempt/fence/submission identity and bound result references, forwards evidence through the same finalizer and adds retained delivery to service quiescence. Keep result/containment separate and reservations held for unknown execution throughout both phases.

### Removal owned here

Move, rather than copy, the sbatch operation owner. Delete the coordinator invocation path for the newly agent-bound assignments in this same PR. Remove its orphan dispatch helpers when their callers move; a second possible submitter is a blocker, even temporarily for one assignment.

Private helper names, local wiring and intermediate representations remain
implementation discretion. Public behavior, durable identity, trust, failure and
cross-phase meanings above are fixed. No compatibility aliases or state resets.

## Proportionality

Reuse ready-stage command/marker machinery, agent outbox and native authority. Do not separate submission from the uncertainty/cancel/recovery behavior that makes moving the owner safe. No failover submitter, generic scheduler or local PID abstraction for external jobs.

## Invariant Ownership

| Invariant | Owner | Reachable boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| One external-call owner | Assigned agent journal | Crash or lost response around sbatch | Duplicate external job | VAL-41-08/09 at-most-one automatic call and exact handle |
| Authorized shared quota | Coordinator policy/placement | Two agents offer one profile; revision/restart | Unauthorized or excess reservations | VAL-41-08 quota shared and no local GPU debit |
| Start/cancel fence | Authority and restricted bootstrap | Cancel races uncertain submit or queued start | Work starts after cancellation | VAL-41-09 both race orderings/exact scancel |
| Truthful recovery/release | Backend journal and accepted projection | Queue absence, accounting delay, agent outage | Blind retry or early capacity release | VAL-41-09 unknown stays unresolved; source/freshness |

## Implementation Slices

1. Bind allowed submit agents/profiles and shared reservations into the current assignment/offer contract.
2. Relocate journal and sbatch ownership with durable acknowledgement; remove the former coordinator invocation for those assignments.
3. Complete bounded observations, uncertain-call discovery, exact cancellation and restart before exposing the backend journey.
4. Exercise connected fake-scheduler runs and grant/outage control races; update agent/Slurm docs and remove replaced dispatch helpers.

## Test And Validation Plan

| Suite | Obligation | Minimal evidence |
| --- | --- | --- |
| Unit/contract | Required | Intent before sbatch, exact disposition/handle, authorization, quota and no host-GPU requirement. |
| Integration | Required | Helper exits while stage remains live; coordinator/agent/joint restart around journal boundaries; no second sbatch. |
| Causal cancellation/E2E | Required | Uncertain submit/cancel and queued grant races; public run/inspect/cancel; retained work prevents shutdown. |
| Live HPC result qualification | Owned by Phase 6 | Local fake-scheduler evidence does not establish site permissions or completed-job durable storage. |

Target existing source-mirrored tests and add focused assertions where the new
contract requires them. Resolve predecessor-renamed test paths at preparation.
Run optional-runtime commands only with their qualified environment. A local
fixture is not live-site evidence; record missing qualification explicitly.

    uv run --extra config pytest tests/unit/loom/queue/test_slurm_ready_stage.py tests/integration/queue/test_slurm_ready_stage.py tests/integration/queue/test_agent_session_transport.py

Final implementation gate; reuse a fresh receipt only while relevant code,
tests, dependency/build and validation configuration remain unchanged:

    make validate-pr
    make test-summary

Do not repeat complete backend/fault matrices in consumer phases. Expand tests
only for changed shared contracts, new failures or a remaining accepted concern.

## Risks, Review, And Stops

Stop if the coordinator can still submit the same assignment, original agent state is silently recreated, or unknown work releases reservations. Agent loss/accounting absence may remain unresolved; automatic takeover is outside scope. Submission, cancellation and uncertain-call recovery stay in one PR.

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
- Independent implementation review: required for external-call ownership, fencing and capacity
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
| Residual risk and cleanup | Completed-job result durability and site qualification delivered by Phase 6 |
