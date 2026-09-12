# Phase 2 Execution Plan: Durable Run Operation

## Metadata

- Status: in_progress
- Roadmap stage and phase: 41 / 2
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p2-durable-run-operation
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: `383e9d473f479516db892f135693dd282100d526` (published Phase 1 completion metadata after PR 308)
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 2: Durable Run Operation
- Dependencies: Phase 1 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: none; Phase 1 merged, metadata published and stage/control/live develop synchronized

## Objective And Context

An accepted run reaches its exact admission after client loss and supports race-safe cancellation and observation against existing services.

Use the persistent coordinator and agents delivered by Stage 40, plus Phase 1 publication. The first end-to-end native run is useful before local autostart is introduced. Phase 3 wires the root CLI/Python convenience facade and configured service lifecycle.

Requirements: FR-41-01/05/08/09/12; supporting FR-41-14. Design: DQ-41-01/04.
Validation ownership: VAL-41-01 (persistent run), VAL-41-05 (run cancellation).

## Current Source And Harness

- Published Stage 40 `src/loom/coordinator.py`, PrepareRunRequest, LocalDaemonOperation, Unix/HTTPS codecs and expected-coordinator guard.
- Shared native call/validation/dispatch owners remain `src/loom/queue/_coordinator_client.py` and `_coordinator_control.py`, with `local_daemon_transport.py` and `agent_session_transport.py` providing Unix/HTTPS transport. Keep diagnostics-dependent observation above queue in `loom.coordinator`.
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

- Manager preparation: passed on 2026-09-12 in the manifest's persistent stage
  worktree and this card's phase branch. Phase 1 PR 308 merged as
  `c133d1798a73d3a4e8903527aa813a70b7659091`; completion metadata published as
  the Base revision above. The shared synchronization gate verified stage,
  local develop, fetched origin/develop and advertised develop equality. Both
  exact Phase 1 branch refs were retired after verification; unrelated checkouts
  were preserved. Successor `start` and `preflight` passed on a clean worktree.
- Source reconciliation: Phase 1 now supplies immutable invocation controls,
  selected-owner recovery and PLANNED publication. The existing dedicated
  preparation table/projections, native client/control dispatch, query/wait and
  admission/cancellation owners remain as assumed by this card. Its listed
  existing test paths are present; the unified-run contract suite is new work.
  Root version 14 is the published predecessor; any required durable format
  change must use the existing incompatible-root refusal rule.
- Named refinement: none needed. Reuse the independent readiness receipt;
  accepted run/cancel identities, serialized ownership, projection budget,
  persistent-service boundary and all required checks remain unchanged.
- Coverage selection: native request/codec/authorization and bounded projections;
  deterministic publication/admission/cancellation crash orderings; retained
  exact admission and no implicit failed-admission retry; persistent two-stage
  execution and observation through both transports. Reuse the existing
  preparation, coordinator-client, admission and transport fixtures. Expand
  only for relevant failures, newly affected consumers or unresolved accepted
  coverage; both `make validate-pr` and `make test-summary` remain required.
- Execution delegation: one executor is justified by the coupled durable
  acceptance/continuation/cancellation and transport/observation changes.
  The manager retains pre-submit acceptance, PR/review/delivery and manifest
  ownership; no child delegation or overlapping source writes.
- Planning review: original accepted contracts retained; 2026-09-12 published-source amendments and current readiness receipt are owned by the manifest Quality Gate
- Implementation: native run acceptance/continuation, independent cancellation,
  bounded projections and existing-service observation are implemented. Owner-level
  checks and both required full commands passed; manager pre-submit and delivery
  remain pending.
- Durable ownership: schema 15 extends preparation rows with kind and exact queue
  identity; the native cancellation table holds independent control progress.
  Publication is retained before admission, and the immutable admission receipt
  and applied run fact commit in the native admission transaction. The existing
  cycle lock serializes suppression and admission. Preparation-only remains
  publication-terminal. Cancellation paging reuses the bounded in-memory rowid
  cursor pattern so unsettled earlier controls cannot starve later controls.
- Native surfaces: `loom.coordinator.RunRequest`, `start_run`,
  `cancel_run_operation` and `observe_run`; existing Unix/HTTPS codecs and role
  dispatch own transport parity. One cumulative observation deadline covers reads
  and waits; timeout/Ctrl-C/EOF preserve references and never cancel. Raw CLI
  start/cancel controls issue one native mutation using request-file IDs. No
  startup, deployment creation, ordinary run facade or temporary CLI orchestrator
  was introduced.
- Refiner: not used
- Pre-submit gate: passed on 2026-09-12 at executor handoff
  `172d2080f6168945647190ed7637000fa34f1f41`. The manager checked the full
  implementation and correction diffs, accepted run/cancel/replay/observation
  contracts, removal scope, both required command receipts and all seven JUnit
  reports. The tested runtime tree is unchanged; the only subsequent changes
  are execution metadata. `git diff --check` passed. No implementation blocker
  remains; independent review of the actual PR is still required.
- Independent implementation review: required for durable continuation and cancellation boundary
- Blocker corrections: 2/3. Manager reproduced caller preparation stealing the
  stable `cancel-run-` identity after run acceptance. Reserve that native control
  namespace at public preparation and management-operation acceptance boundaries;
  cover both creation orderings and retain ordinary query/cancellation access.
  The second manager correction restores the unrelated scheduling/time-control
  schemas after accidental insertion of run-specific columns. Those fields remain
  only on preparation operations; existing operator tests cover the restoration.
- Additional boundary probe: a 31,900-character queue ID can be accepted but its
  full publication/admission projection refused. Cancellation now validates its
  actual retained references rather than requiring the refused hypothetical
  admission. Every run projection reserves its mandatory cancellation link.
- First final-gate attempt: `make validate-pr` on `a650b51733a91a229303685b06b27c3c323f63f6`
  (tree `cf27b5a52d6e4ce157885a7aa0abaa9a725e2634`) exited 2 after a deliberate
  SIGINT to its verified pytest process once the schema regression was confirmed.
  Ruff/Pyright had passed; interrupted baseline evidence was 629 passed, 2 skipped,
  269 deselected in 410.08 seconds. This is incomplete evidence, not a gate pass;
  `/tmp/loom-stage41-p2-validate-pr.log` retains the actual outcome. Its owned
  fixture supervisors exited during pytest cleanup. The corrected full-gate
  receipt below supersedes this incomplete attempt.
- Correction checks: isolated locked Python 3.12/config pytest selected
  `test_run_operations.py::test_publication_budget_refusal_still_allows_bounded_cancellation`,
  `test_local_daemon.py::test_forward_clock_jump_degrades_without_advancing_and_requires_recovery`
  and `test_local_daemon.py::test_scheduling_reload_is_local_atomic_and_durable`:
  3 passed; `/tmp/loom-stage41-p2-corrections.log`. The earlier owner selection
  (cancellation paging, native child release, bounded publication, root/upgrade
  checks) passed 17 cases; `/tmp/loom-stage41-p2-owner-checks.log`.
- Final validation: **passed** on clean commit
  `7f343c90b9f79bf14a731d75979c03638f02c196`, tree
  `78bcc2d8f9d4619b528a1c0aa605d4f49795f078`, using Python 3.12 and the
  harness's isolated locked dependency lanes.
  - `make validate-pr`: exit 0. Ruff and Pyright passed; baseline 3341 passed,
    2 skipped, 270 deselected; config-extra 240 passed, 18 skipped,
    3382 deselected; MCP-extra 36 passed, 3577 deselected; source and wheel builds
    passed. Log: `/tmp/loom-stage41-p2-validate-pr-final.log`.
  - `make test-summary`: exit 0. Package 127, unit 2336, contract 302,
    integration 508, e2e 70, config-extra 240 and MCP-extra 36 passed; zero
    failures/errors. The summary reports 3619 passed and 18 skipped across its
    documented lanes. Log: `/tmp/loom-stage41-p2-test-summary.log`; commands,
    deselections, coverage and JUnit evidence: `build/test-summary.md` and
    `build/test-summary/<suite>/junit.xml`.
    The manager archived and byte-verified the summary plus all seven JUnit
    reports at `/tmp/loom-stage41-p2-summary-evidence/` before later phases
    reuse the harness output paths.
  - The two baseline skips are the dotenv-dependent queue journey checks;
    both executed successfully in the summary's config-enabled e2e lane.
    All 18 config-extra skips are opt-in physical container acceptance: 13
    Apptainer namespace/timeout cases and one each for Docker smoke, Apptainer
    smoke, SIF build, resource enforcement and scheduling-only resources. These
    skips do not qualify physical container/fleet/HPC execution. The summary
    also retains two coroutine RuntimeWarnings from unchanged monitor UI tests;
    no test failed.
- Evidence reconciliation: the final full commands include the 38-case native
  run/transport/observation selection, the 17 owner cases and the three correction
  checks, after all relevant source/test edits. Only this card's Workflow State
  and Completion Record were updated after the final evidence; runtime, tests,
  dependencies, build and validation configuration are unchanged.
- Cleanup: all owned validation terminals completed. Fixture service cleanup
  passed; five phase-owned temporary edit scripts were removed. Validation logs
  and the harness report/JUnit artifacts remain for the manager. The persistent
  stage worktree and branch remain in place for the manager's delivery workflow.
- PR and merge: not started

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Coordinator facade; native request/client/control and preparation/admission owners; raw queue CLI; downstream operations documentation. Schema 15 refuses incompatible schema-14 roots without mutation. |
| Tests added, updated or intentionally removed | New unified-run contract and durable run integration suites; native observation/CLI/import tests; preparation child-release and projection-budget cases extended to run intent; root/upgrade checks updated for schema 15. No accepted predecessor coverage removed. |
| Validated revision/tree and evidence | Both `make validate-pr` and `make test-summary` passed on `7f343c90b9f79bf14a731d75979c03638f02c196`, tree `78bcc2d8f9d4619b528a1c0aa605d4f49795f078`. Exact outcomes, logs, skipped qualification and report/JUnit paths are in the final validation receipt above. |
| Validation-relevant changes after evidence | None. Only this card's execution/completion metadata changed after the tested commit. |
| Replaced-code removal / retained primitive consumers | Existing coordinator facade and raw CLI contained no production prepare/wait/submit orchestration chain to remove. Preparation-only and explicit prepared submission/retry remain separate native primitives and retain their tests. The old in-process execution RunRequest remains with its Phase 9 removal owner. |
| PR, review and merge | Manager pre-submit passed; PR, independent review and delivery remain pending. |
| Residual risk and cleanup | No unresolved implementation blocker. Evidence is local synthetic services and mutual TLS fixtures; physical qualification remains with its owning phases. Owned validation processes completed, fixture cleanup passed, and temporary edit scripts were removed. Logs and harness artifacts remain available; stage worktree/branch are retained for manager delivery. |
