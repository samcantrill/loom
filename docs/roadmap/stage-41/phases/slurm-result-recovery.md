# Phase 6 Execution Plan: Slurm Result Recovery

## Metadata

- Status: pending
- Roadmap stage and phase: 41 / 6
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p6-slurm-result-recovery
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: published develop after Phase 5 merges; record exact SHA at execution preparation
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 6: Slurm Result Recovery
- Dependencies: Phase 5 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: source predecessor pending; no unresolved planning blocker

## Objective And Context

A job can finish and its compute process exit during coordinator downtime; the recovered submit agent delivers the same result for one authority commit.

Phase 5 provides the single submission owner and exact handles. This phase completes Stage 41 connected Slurm durability without changing grants, cancellation authority or creating a filesystem-success path.

Requirements: FR-41-09/11/12/15; supporting FR-41-04/06/13. Design: DQ-41-05/07.
Validation ownership: VAL-41-10/11.

## Current Source And Harness

- `src/loom/queue/slurm_ready_stage.py::SlurmBootstrapWorkspace.retain_result`, `slurm_bootstrap.py`: typed report/outputs and current callback flow.
- Phase 5 agent journal/outbox and assignment/result references; Phase 3 retained-work lifetime predicate.
- Existing native report/artifact transfer, coordinator assignment store and authority finalizer with current fences and idempotent output commits.
- `tests/integration/queue/test_slurm_ready_stage.py`, malformed/stale transfer tests and `tests/slurm_acceptance/test_real_slurm_live_operations.py`.
- [Slurm feature contract](../../../features/slurm.md) and existing protected profiles; qualified shared artifacts do not qualify role SQLite storage.

## Scope

Own attempt-bound durable shared result retention, manifest-last publication, submit-agent ingestion, acknowledgement-controlled cleanup and completed-job outage evidence. Complete site/profile documentation and available live qualification; no offline starts, new allocation product or failover.

Assume the predecessor's accepted contracts and existing qualified installations.
Each phase includes its code, owner-level tests, current docs and replaced-code
removal. Preserve unrelated work and current scientific/resource meaning.

## Implementation Walkthrough And Examples

### What changes and why

Phase 5 can recover the identity and control of an external job. This phase makes
its result recoverable after the compute process has disappeared:

```text
Coordinator goes down.
Training finishes and writes its retained result.
Slurm job and compute worker exit.
Coordinator/submit agent reopen their retained state.
Submit agent delivers the result for one authority commit.
```

A callback cannot provide that guarantee alone. The accepted assignment binds
an attempt-owned durable result location available to compute and submit agent,
with protected mappings if their mount prefixes differ. Reuse existing typed
reports and artifact descriptors; add only the required shared transport.

### Durable publication before notification

This is internal publication pseudocode, not a new public API. Each write helper
must provide the storage contract required by the qualified profile; an in-memory
write or incomplete copy does not establish durability.

```python
write_output_files_durably(result.outputs)
write_execution_report_durably(result.report)

# Referenced bytes/report are complete before the manifest becomes visible.
atomic_publish_manifest(result.manifest)

notify_best_effort()
```

The manifest binds the report and declared outputs to the coordinator, assigned
agent, assignment, attempt, execution fence and submission operation. It carries
their paths, byte counts and digests using the accepted schemas/bounds. The fence
is the authority's current execution authorization for that attempt; copying an
old report into a new directory cannot make it current.

The submit agent reads only its assignment's bound location, checks contained
non-link regular files and declared content, and forwards valid evidence through
the existing result transport. It must not scan arbitrary project directories for
files that resemble outputs. A checkpoint/model file by itself is not a result.

### Finalization, acknowledgement and containment

| Fact | Meaning |
| --- | --- |
| Slurm reports completion | Scheduler evidence about the exact job |
| Valid typed report and complete outputs are retained | Evidence is available for result finalization |
| Authority accepts the result | The output commit is valid for the accepted attempt |
| Execution containment is established | Relevant execution resources can be released |

Coordinator/authority remains the sole finalizer. It validates the current fence
and performs the existing idempotent commit/replay. Submit-agent delivery does not
become an independent filesystem-success authority. Duplicate delivery after a
lost acknowledgement must return the same accepted result, not commit twice.

Transport cleanup waits for final acknowledgement or the existing permitted
terminal rejection disposition. Neither client nor bootstrap exit deletes
unacknowledged evidence. A valid result does not itself prove the job/descendants
are contained; unresolved execution/delivery still participates in service lifetime.

### HPC qualification and proof

VAL-41-10 exercises compute exit during coordinator loss, later ingestion, partial
or stale manifests and separate commit/containment/retention facts. VAL-41-11 owns
real-site qualification: permitted service/submit location, grant reachability,
installed worker environment, durable result storage and any claimed container
binding. Shared artifact storage does not automatically qualify role SQLite roots
for shared-database operation. Same-root restart preserves exact identities; it
does not reconstruct lost journals or add cross-host failover/offline starts.

## Fixed Contracts And Private Discretion

### Durable shared result transport

Initial Slurm qualification requires a protected durable result root accessible
to compute and submit agent, with explicit path bindings if their mount prefixes
differ. It is separate from role SQLite roots and may reuse a qualified shared
workspace. No discovery scans or arbitrary experiment output paths are accepted.
Accepted assignment binds the exact attempt-owned location before job launch.

Reuse the current typed execution report and output-artifact descriptor shapes.
The transport manifest fixes schema, coordinator/agent/assignment/attempt/fence
and submission-operation identity; report digest/size; declared artifact logical
names with relative regular-file paths, digests and byte counts. Reuse existing
identity fields/references rather than copying a full configuration into it.
Current report/artifact size and transfer bounds remain authoritative and are
checked before acceptance/publication; a required finite site retention quota
must not be satisfied by deleting unacknowledged outputs. Exceeding a bound is
an explicit retained delivery/storage failure, not stage success.

Bootstrap durably publishes artifact bytes, then the report, then the complete
manifest atomically last, before any best-effort notification. Interrupted copies
or incomplete manifests are not results. Submit agent accepts only its bound
location, checks contained non-link regular-file paths and bytes, and forwards
report/artifacts through the existing assignment/result transport. Existing
bootstrap notifications may wake reconciliation; they are not the sole delivery
guarantee. The submit agent can deliver after the batch process has exited.

Coordinator/authority is the sole finalizer: validate the current accepted fence,
apply normal commit/replay and acknowledge durable completion. Transport cleanup
requires that final acknowledgement (or an explicit existing terminal rejection
disposition allowing retirement); no client/observer/bootstrap exit deletes
unacknowledged evidence. Malformed, partial, digest-conflicting or stale evidence
remains diagnostic and cannot establish success. A stale process-session token
does not by itself invalidate correctly retained work under a still-valid attempt;
recovery reauthenticates delivery through its original submit agent.

This is one new transport into the current finalizer. It adds no filesystem-success
authority, independent completion database or offline start capability.

### Existing bounds and finalizer evidence

At the inspected base, the native report/transfer contract caps aggregate artifact
bytes at 64 MiB. Shared result storage does not bypass that transfer ceiling or
the existing report decoder bounds. Preserve them and refuse oversized delivery
with retained diagnostic evidence; larger checkpoints/artifacts require separate
accepted work. Site retention quota covers retained attempts and must not erase
unacknowledged bytes to manufacture availability. Do not claim arbitrary-size HPC
outputs in examples or qualification.

Use remote report version 3's executor metadata and the existing public redaction
owner. Preserve actual container/worker and agent-owned scheduler observations
through recovered delivery. Do not upgrade older reports by fabricating missing
execution evidence. Native successful-exit qualification stays with its supervisor;
Slurm completion and containment remain separately evidenced by the batch backend.
Where the current finalizer uses a retained output predecessor, initial delivery
and lost-ack replay must supply that same admitted predecessor; neither a shared
manifest nor a newer output head can substitute authorization for a commit.

### HPC deployment boundary

The supported first journey uses a site-permitted service/submit host and a
reachable restartable coordinator. A command that can fork is not proof that the
site permits a daemon there. Same-root restart is supported; journal loss,
cross-host database copying and transparent service failover are not.

Document that the same command can be used inside an already-granted allocation
only with separately qualified allocated-resource/native/container and required
srun step binding. No detection-based nested sbatch, allocation provisioning or
new allocation-only product is delivered. Official command semantics are in
[sbatch](https://slurm.schedmd.com/sbatch.html),
[squeue](https://slurm.schedmd.com/squeue.html),
[sacct](https://slurm.schedmd.com/sacct.html) and
[srun](https://slurm.schedmd.com/srun.html); actual site qualification is separate.

### Delivery boundary

This phase completes the promised finish-during-outage Slurm journey. A permitted site, reachable grant endpoint, installed environment and qualified durable result root remain prerequisites. Missing live access blocks that deployment claim, not truthful local implementation completion. Native Slurm workers are baseline; containers require the selected site/runtime to be qualified.

### Cross-phase handoff

Phases 7–8 consume unchanged public run/inspection operations. Phase 9 reuses this qualification receipt unless later changes invalidate it. Compute result publication, agent ingestion, authority acknowledgement and retirement must be implemented and validated together.

### Removal owned here

Replace callback-only result-delivery assumptions with the acknowledged transport; retain a callback only as a useful notification/current transport hook. Delete duplicate report/finalization helpers and unsupported storage claims as their owners are replaced.

Private helper names, local wiring and intermediate representations remain
implementation discretion. Public behavior, durable identity, trust, failure and
cross-phase meanings above are fixed. No compatibility aliases or state resets.

## Proportionality

Add one transport into the current finalizer using existing report/artifact identities and bounds. Durable shared bytes are required because compute can exit during outage. No separate success database, arbitrary output scan or generic storage framework.

## Invariant Ownership

| Invariant | Owner | Reachable boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Complete bound durable result | Bootstrap publisher and agent reader | Compute exits during outage; interrupted/corrupt writes | Lost output or false completion | VAL-41-10 manifest-last, bound regular files and digest checks |
| One authority commit | Existing coordinator/authority finalizer | Duplicate or stale report after reconnect | Wrong attempt publishes | VAL-41-10 one commit/current fence |
| Acknowledged cleanup and safe release | Transport owner plus containment owner | Report valid but not acknowledged or job uncontained | Lost replay evidence or early capacity reuse | VAL-41-10 independent output/containment/retention |
| Qualified deployment claim | Site profile and acceptance evidence | Unsupported mount, host policy or compute reachability | Advertised recovery cannot work | VAL-41-11 real-site receipt or explicit gap |

## Implementation Slices

1. Bind the qualified compute/agent result locations and finite existing transfer/retention constraints to exact assignments.
2. Publish bytes/report/manifest durably, ingest only bound checked evidence, and integrate the current finalizer plus acknowledgement cleanup.
3. Prove compute exit during coordinator outage, stale/partial evidence, replay and containment; expose native freshness/cleanup diagnostics.
4. Run available site/container qualification and update Slurm/deployment examples with actual limits and remove callback-only assumptions.

## Test And Validation Plan

| Suite | Obligation | Minimal evidence |
| --- | --- | --- |
| Unit/contract | Required | Manifest identity, bounds, path/digest checks and no cleanup before acknowledgement. |
| Integration/causal | Required | Compute exits while coordinator is down; recovered agent delivers; one commit; stale/partial/corrupt output cannot succeed. |
| Public E2E | Required | Same run/inspect lifecycle with fake scheduler; missing report/accounting is distinct from success; unresolved delivery retains services. |
| Real Slurm/container | Environment-dependent qualification | Submit-host policy, grants, resource limits, durable result visibility after job exit/restart, selected container binding when claimed. |

Target existing source-mirrored tests and add focused assertions where the new
contract requires them. Resolve predecessor-renamed test paths at preparation.
Run optional-runtime commands only with their qualified environment. A local
fixture is not live-site evidence; record missing qualification explicitly.

    uv run --extra config pytest tests/unit/loom/queue/test_slurm_ready_stage.py tests/integration/queue/test_slurm_ready_stage.py tests/integration/queue/test_agent_session_transport.py

    LOOM_RUN_SLURM_ACCEPTANCE=1 LOOM_SLURM_ACCEPTANCE_ROOT=/qualified/shared/path uv run pytest tests/slurm_acceptance

Extend the outage/manifest cases with preserved version-3 container/execution
metadata, aggregate artifact bytes at/over the native bound, and lost commit
acknowledgement replay against the exact retained predecessor. A well-formed
report or scheduler COMPLETED must not substitute for required backend success
or containment evidence. Reuse P4's native supervisor proof tests unchanged.

Final implementation gate; reuse a fresh receipt only while relevant code,
tests, dependency/build and validation configuration remain unchanged:

    make validate-pr
    make test-summary

Do not repeat complete backend/fault matrices in consumer phases. Expand tests
only for changed shared contracts, new failures or a remaining accepted concern.

## Risks, Review, And Stops

Stop if required output cannot survive compute exit or cannot traverse the existing finalizer with its accepted identity. Keep role databases on their qualified storage and retain unknown evidence. Missing site access remains a qualified evidence gap, never a claimed pass.

## Executor Handoff

Read planning.md Behavior Baseline, the requirement/design/validation IDs above,
this whole card and the actual published predecessor contracts. Implement the
listed slices within the stated ownership. Do not reopen agreed lifecycle,
grant-before-start, sole submission/finalization ownership or hard cutover.
Manager action is for a demonstrated public/durable or accepted-behavior conflict,
not private helper choices. You are not alone in the codebase; preserve others' edits.

## Workflow State

- Manager preparation: approved card; execution revision/worktree pending
- Planning review: original accepted contracts retained; 2026-09-12 published-source amendments and current readiness receipt are owned by the manifest Quality Gate
- Implementation: not started
- Refiner: not used
- Pre-submit gate: not run
- Independent implementation review: required for result filesystem/transport/commit and cleanup boundary
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
| Residual risk and cleanup | Live site/container and durable shared-storage qualification pending |
