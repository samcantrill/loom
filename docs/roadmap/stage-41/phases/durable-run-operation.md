# Phase 2 Execution Plan: Durable Run Operation

## Metadata

- Status: pending
- Roadmap stage and phase: 41 / 2
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p2-durable-run-operation
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: published develop after Phase 1 merges; record exact SHA at execution preparation
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 2: Durable Run Operation
- Dependencies: Phase 1 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: source predecessor pending; no unresolved planning blocker

## Objective And Context

An accepted run reaches its exact admission after client loss and supports race-safe cancellation and observation against existing services.

Use the persistent coordinator and agents delivered by Stage 40, plus Phase 1 publication. The first end-to-end native run is useful before local autostart is introduced. Phase 3 wires the root CLI/Python convenience facade and configured service lifecycle.

Requirements: FR-41-01/05/08/09/12; supporting FR-41-14. Design: DQ-41-01/04.
Validation ownership: VAL-41-01 (persistent run), VAL-41-05 (run cancellation).

## Current Source And Harness

- Published Stage 40 `src/loom/coordinator.py`, PrepareRunRequest, LocalDaemonOperation, Unix/HTTPS codecs and expected-coordinator guard.
- `src/loom/queue/_preparation_operations.py`, `local_daemon.py`: dedicated preparation table, reconciliation, operation projection and target admission. Published submit also accepts an explicit `retry_failed_revision`; default replay cannot retry failed work.
- `src/loom/diagnostics/run_inspection.py`: native execution/settlement observation, bounded evidence and failure projection.
- Existing agent-session transport, managed preparation, daemon production and CLI/native receipt tests; proposed `tests/contracts/test_unified_run_contract.py` covers the new operation.

## Scope

Own RunRequest, start_run, cancel_run_operation, durable continuation, operation projection, native wait/detach behavior and local/HTTPS parity. Use existing persistent service connections and native CLI control plumbing. Do not launch services or create deployment roots in this phase.

Assume the predecessor's accepted contracts and existing qualified installations.
Each phase includes its code, owner-level tests, current docs and replaced-code
removal. Preserve unrelated work and current scientific/resource meaning.

## Implementation Walkthrough And Examples

### What changes and why

An accepted request to prepare and run an experiment must proceed even if its
client disappears during preparation. The coordinator therefore retains both
preparation intent and the continuation into target admission. The client can
observe this process, but is no longer the only component remembering the next
step. Extend the dedicated preparation lifecycle persistence and native operation projection, and reuse admission replay.

This planned public-interface sketch assumes an already-connected Stage 40
client and an unsubmitted preparation value such as the one in
[Phase 1](preparation-publication.md#implementation-walkthrough-and-examples).
It is explanatory target code, not a currently runnable example.

```python
request = RunRequest(
    preparation=preparation,
    queue_item_id="admit-demo-001",
)

operation = client.start_run(request)
```

### Identities and completion mean different things

| Reference | Meaning |
| --- | --- |
| operation_id | The accepted request to prepare and admit work; taken from preparation.operation_id |
| run_uri | The durable identity of the prepared target experiment |
| queue_item_id | The stable requested target-admission identity used for replay |
| admission receipt | The coordinator's accepted admission and its native references |

Retries carry the original identities. If an acceptance response is lost, the
client reports/reconciles those IDs instead of inventing another request. The
coordinator's public identity is also retained and checked on reconnect.

| Operation kind | Meaning of applied |
| --- | --- |
| prepare_run | The exact prepared target has been published |
| run | The exact target admission has been accepted |

Publication alone cannot complete a run operation. Once its admission is accepted,
the operation's applied state remains an admission fact; waiting for the experiment
then follows execution and settlement. Default wait must not mistake that first
terminal operation state for finished training. Early detach returns the operation
reference even if no target admission exists yet.

### Cancellation across the publication/admission boundary

```python
# Only when the user explicitly requests cancellation.
cancellation = client.cancel_run_operation(operation.operation_id)
```

The returned object is the cancellation control operation. Observe its settlement,
not merely the original run operation's applied state. The coordinator serializes
cancellation with the admission continuation:

```text
Cancellation wins before admission:
    suppress the continuation
    retain any prepared receipt and settle the preparation child
    never admit the suppressed target later

Admission wins first, including a lost admission response:
    recover the exact admission through its fixed queue identity
    delegate cancellation to the existing native run/admission owner
```

Crash recovery repeats the same control operation and target IDs. An already
admitted run retains its original applied admission fact while cancellation has
its own progress. Ctrl-C, EOF, timeout and closing a client detach observation;
they do not implicitly enter this cancellation path.

### Contracts illustrated

A client lost during preparation cannot strand accepted run intent. A cancelled
continuation cannot be admitted by a delayed callback. VAL-41-01/05 tests exercise
both cancellation/admission orderings and lost responses using deterministic
barriers. Acceptance, continuation and cancellation stay in one implementation
unit because each depends on the same ownership decision.

## Fixed Contracts And Private Discretion

Extend the native facade with these plain-data contracts, using existing native
identifier/receipt models rather than duplicate job records:

| Shape | Required meaning |
| --- | --- |
| RunRequest | `preparation`: Stage 40 PrepareRunRequest; `queue_item_id`: stable native target-admission identity |
| CoordinatorClient.start_run(request) | Durably accepts kind `run` by extending native preparation persistence, using preparation.operation_id as its operation ID; returns LocalDaemonOperation |
| Run result projection | Existing preparation result, plus requested `queue_item_id`, nullable native target `admission` and nullable cancellation-operation reference; coordinator_id and operation_id available from acceptance |
| CoordinatorClient.cancel_run_operation(operation_id) | Returns a native kind `cancel_run` control operation with a stable ID derived from the target operation ID; atomically suppresses an unadmitted continuation or links cancellation of its exact admission |
| High-level return | Native operation/reference and latest native run/admission inspection when available, safe deployment binding and per-service cleanup outcome; no embedded credentials/configuration or new lifecycle status enum |

Reuse the preparation operation machinery and state enum for kind `run`; do not
create a separate prepare-only operation for the same request. Run intent includes
the continuation and exact target queue ID; same operation ID with changed intent
or kind conflicts. Kind `prepare_run` remains terminal `applied` at publication,
and `cancel_preparation` retains that prepare-only meaning. For kind `run`,
publication alone is nonterminal: remain pending/applying until the exact target
admission is durably accepted (`applied`), suppressed (`cancelled` after required
child settlement), or fails/conflicts with retained publication evidence. Applied
means admission accepted, not experiment success; default wait then follows that
admission through execution/settlement. A successful publication triggers the
existing idempotent admission even after caller/coordinator restart; publish-to-
admit crashes replay the same identities. No client-side-only chain or independent
run orchestration database. Preserve Stage 40's bounded operation
projection, reserving required admission references before publication; large
reports remain referenced through its existing mechanism.

Generate CLI IDs once before the first mutation, print the recovery reference,
and retain them for uncertain-call retries. Python callers can supply exact IDs.
`--detach`/`wait=False` returns at durable run-operation acceptance, possibly before
target admission. Ctrl-C/EOF during observation returns the same known reference;
a lost acceptance response is reported as uncertain with the original IDs.
Default wait observes target terminal settlement plus this invocation's cleanup
decision; timeout_seconds bounds this observation after durable acceptance, with
startup/connection bounded separately by deployment/transport policy. Timeout
detaches. Closing a client has no cancellation effect.

`cancel_run_operation` authorizes and durably records cancellation through the
coordinator operation owner. Serialize its intent against continuation admission.
If cancellation wins, no target may later be admitted; retain any prepared receipt
and settle the preparation child. If admission won, including a lost admission
response, resolve the fixed queue ID and delegate to the existing native
admission/run cancellation owner. A crash between those steps replays the same
control operation and target IDs. No acknowledged suppression may race a later
admission. The cancellation result retains its target operation/admission references
and native control evidence; it remains pending until suppression/child settlement
or linked native cancellation settles. Cancelling an already admitted run does not
rewrite the original run operation's `applied` admission fact. Existing terminal-run
cancellation behavior remains with the native owner. CLI/MCP wait on the returned
cancellation operation, not the original admission operation's state.

### Durable facts and recovery order

The predecessor has a dedicated `preparation_operations` table and hard-coded
prepare projections, not a generic run-operation engine. Extend that native owner
and its projection/dispatch readers. Durably retain kind, exact target queue ID,
publication receipt, admission linkage and cancellation-control linkage. A separate
native cancellation control record is required by its independently observable
settlement; it does not introduce a second run database. SQL layout and private
helper names remain discretionary. Changed-kind or changed-intent reuse conflicts.
Preserve preparation principal ownership for replay/cancellation and existing
query/client/operator authorization; another connection does not change ownership.

Retain the exact published receipt before the first target admission call. Recovery
with that receipt reopens the fixed admission identity and resumes admission only
if necessary; it does not call the publisher's planning-based replay check after
the target may have executed. Reconcile lost admission replies from native durable
admission state before deciding cancellation won. Original accepted run intent
never requests `retry_failed_revision`, including after terminal failure. Explicit
retry remains a separate prepared-admission request, with its existing authority
capability and one-continuation-per-failed-revision semantics. The old in-process
`pipeline.execution.models.RunRequest` is a different model: expose the new plain
request as `loom.coordinator.RunRequest` and remove old public owners in P9.

Publication can already be claimed when run cancellation arrives. It may finish
and retain its receipt, but cancellation must still serialize against target
admission. Do not inherit prepare-only's publication-wins cancellation endpoint
as the run cancellation implementation. Preserve `cancel_preparation` for kind
`prepare_run`; refuse it for kind `run` and route that caller to `cancel_run_operation`.
Its stable control ID and target references survive restart and lost replies.

The 64 KiB operation budget covers all mandatory run and cancel references,
including requested queue identity and the complete retained admission receipt.
Check the prospective required projection before target publication/admission;
omit only optional complete preflight detail via its pinned report. Retain the
acceptance receipt rather than embedding a growing admission-detail read model.
Current execution/diagnostic inspection remains separately queried. Never accept
work that can only be projected by silently truncating a mandatory receipt.

### Delivery boundary

All services are already running for this delivery. Phase 3 exposes the final lazy loom.run and ordinary loom run convenience entrypoints, using these unchanged run-operation and observation semantics. Its deployment selection and startup policy are not replaced by a temporary connection format here.

### Cross-phase handoff

Phase 3 calls this native operation after service availability; Phase 8 delegates tools to the same run/cancel methods. The operation kind, exact IDs, bounded projections and cancellation owner are fixed across both handoffs.

### Removal owned here

Remove duplicate client-side prepare/wait/submit chains where this native operation replaces them. Preserve preparation-only and native submit APIs. Do not create an alternative new CLI orchestrator to bridge Phase 3.

Private helper names, local wiring and intermediate representations remain
implementation discretion. Public behavior, durable identity, trust, failure and
cross-phase meanings above are fixed. No compatibility aliases or state resets.

## Proportionality

Reuse the operation table, state enum, preparation engine and admission replay. Run/cancel kinds are needed for accepted work and the publication/admission race; no second job database or per-client lifecycle.

## Invariant Ownership

| Invariant | Owner | Reachable boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Accepted run outlives caller | Coordinator run-operation owner | Client exits during preparation or admission response is lost | Stranded run or duplicate admission | VAL-41-01 one eventual target with same IDs |
| Correct terminal point | Run/prepare operation projection | Publication finishes before target admission | Wait returns too early | VAL-41-01 prepare applied versus run nonterminal |
| Cancellation cannot lose admission race | Run-operation owner and native cancellation | Cancel in publish/admit gap; lost admission response; restart | Acknowledged suppression followed by new work | VAL-41-05 both serialized orderings/replay |
| Detach does not cancel | Native observation facade | EOF/Ctrl-C/timeout/closed client | Unexpected termination | VAL-41-05 live continuation and recovery reference |

## Implementation Slices

1. Add native run/cancel models and durable linkage using the existing operation engine; preserve prepare-only semantics.
2. Implement publication-to-admission replay and the serialized cancellation path, including both crash/race orderings.
3. Expose native local/HTTPS calls and observation through persistent services; prove client loss, detach, terminal wait and typed receipts.
4. Update operation/API docs and remove replaced client-side orchestration duplicates.

## Test And Validation Plan

| Suite | Obligation | Minimal evidence |
| --- | --- | --- |
| Package/contract | Required | Native exports are cheap; bounded receipts, run/prepare terminal points, local/HTTPS semantics. |
| Unit | Required | Same ID/kind/intent checks, fixed queue identity, cancellation control state and deterministic replay. |
| Integration/E2E | Required | Persistent two-stage run; detach during preparation; publish/admit crash; cancellation on both sides; one admission. |
| Startup/container/HPC | Deferred to owner | Phases 3–6 own those newly introduced behaviors. |

Target existing source-mirrored tests and add focused assertions where the new
contract requires them. Resolve predecessor-renamed test paths at preparation.
Run optional-runtime commands only with their qualified environment. A local
fixture is not live-site evidence; record missing qualification explicitly.

    uv run --extra config pytest tests/integration/queue/test_local_daemon_production.py tests/integration/queue/test_agent_session_transport.py tests/unit/loom/queue/test_managed_local_preparation.py

Add targeted cases to the existing preparation/native transport fixtures: crash
after publication but before receipt persistence; crash after retained receipt but
before admission; lost admission reply followed by actual target execution; and
cancellation before/after admission while publication was already claimed. Assert
one admission, no post-admission replanning and settlement of the returned cancel
control. Also prove same-ID replay of FAILED never retries, explicit native retry
retains its revision/capability rules, cross-principal mutation conflicts and the
required run/cancel projections fit or refuse before target effects.

    uv run --extra config pytest tests/integration/queue/test_preparation_operations.py tests/unit/loom/test_coordinator.py tests/unit/loom/queue/test_local_daemon.py

Final implementation gate; reuse a fresh receipt only while relevant code,
tests, dependency/build and validation configuration remain unchanged:

    make validate-pr
    make test-summary

Do not repeat complete backend/fault matrices in consumer phases. Expand tests
only for changed shared contracts, new failures or a remaining accepted concern.

## Risks, Review, And Stops

Keep acceptance, continuation and cancellation in this one PR; they cannot be split into independently safe deliveries. Stop if the native authority/admission boundary cannot serialize suppression with accepted work. Do not emulate the race with client-side calls.

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
- Independent implementation review: required for durable continuation and cancellation boundary
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
| Residual risk and cleanup | Persistent-service execution/cancellation evidence pending |
