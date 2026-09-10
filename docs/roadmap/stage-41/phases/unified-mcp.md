# Phase 8 Execution Plan: Unified MCP And Skills

## Metadata

- Status: pending
- Roadmap stage and phase: 41 / 8
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p8-unified-mcp
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: published develop after Phase 7 merges; record exact SHA at execution preparation
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 8: Unified MCP And Skills
- Dependencies: Phase 7 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: source predecessor pending; no unresolved planning blocker

## Objective And Context

MCP runs, observes and cancels through the same native service/run owners, with updated skills and no private lifecycle.

Stage 40 delivers the adapter and skills; Phases 2–3 deliver the native run/cancel/availability methods. This phase updates those existing consumers only. It is sequenced after the sweep phase for one-PR-at-a-time integration, not because MCP depends on sweep internals.

Requirements: FR-41-01/05/13/14. Design: DQ-41-01/06.
Validation ownership: VAL-41-12 (MCP/skills/imports).

## Current Source And Harness

- Published Stage 40 MCP adapter, registered tool schema, optional dependency lane and skills/loom-prepare, loom-run, loom-monitor, loom-diagnose; reconcile exact paths.
- Phase 2 run/cancel operation contract and Phase 3 deployment availability/public facade.
- Existing native operation/report size limits, coordinator identity guard, typed errors, read/operator policy and diagnostic models.
- Stage 40 tool parity/process disconnect and isolated MCP import tests; reuse its actual real-session qualification hook.

## Scope

Update deployment selection, loom_run and loom_cancel_run_operation tools, native delegation and four existing skills. Keep useful prepare-only/submit/inspect/wait/cancel tools and optional stdio operation. No remote MCP host, worker provisioning or private queue.

Assume the predecessor's accepted contracts and existing qualified installations.
Each phase includes its code, owner-level tests, current docs and replaced-code
removal. Preserve unrelated work and current scientific/resource meaning.

## Implementation Walkthrough And Examples

### Make tools call the delivered native lifecycle

The Stage 40 adapter already translates tool calls into native client calls.
This phase changes its high-level run tool to use the durable prepare/admit
operation and the explicit deployment availability behavior delivered by
Phases 2–3. It must not implement a separate sequence of prepare, wait and
submit calls whose continuation disappears when the assistant disconnects.

This sketch shows delegation only. `request` is decoded through the native
request model, `deployment` is an explicitly authorized selection, and `client`
is the configured coordinator client with its normal identity/policy guards.
Tool decorators, transport serialization and result bounding remain with the
existing adapter; these functions are not a complete server implementation.

```python
import loom


def loom_run(request, deployment):
    return loom.run(request, deployment=deployment, wait=False)


def loom_cancel_run_operation(operation_id):
    return client.cancel_run_operation(operation_id)
```

The calls target the planned native interfaces documented in
[Phase 2](durable-run-operation.md#implementation-walkthrough-and-examples) and
[Phase 3](service-startup-lifetime.md#implementation-walkthrough-and-examples).
The adapter reuses their models and semantics rather than maintaining duplicate
request schemas or a private operation store. Preserve useful prepare-only,
prepared-receipt submission, inspection, wait and cancellation tools as thin
calls to their existing owners.

### Keep startup, acceptance and cancellation explicit

Importing Loom, constructing a client or starting the stdio server remains
inert with respect to service startup. An explicit ensure/run tool can start
configured local services. The adapter preserves native authorization, bounded
results, typed errors, coordinator identity guards and recovery references for
unknown outcomes. It does not install project code, write service secrets or
provision remote workers.

An accepted run operation continues if MCP exits during preparation. Its
`applied` state means admission was accepted, not that the experiment finished;
monitoring follows the native run afterward. Cancellation is another explicit
mutation: `loom_cancel_run_operation` returns the native cancellation control
operation, so waiting on that result follows cancellation settlement.
`loom_cancel_preparation` remains prepare-only and cannot emulate the
publish/admit race. Disconnecting a tool caller is not a cancellation request.

### Update the four existing skills at their owning interfaces

| Skill | Behavior to document and exercise |
| --- | --- |
| `loom-prepare` | Prepare only; stop at the exact prepared receipt and explain that admission is separate. |
| `loom-run` | Submit the unified run request with explicit deployment selection; retain accepted/uncertain operation and recovery references. |
| `loom-monitor` | Reconnect and query native operation/run state; distinguish admission settlement from execution completion. |
| `loom-diagnose` | Explain scheduler observations, retained result evidence and service cleanup separately from the experiment's result. |

For example, after losing the tool response, the run skill recovers using the
same native request/operation references; it does not start a new run with new
IDs. Monitoring can then reconnect from another client to the same coordinator.
Tools and skills share that behavior with Python and CLI callers.

VAL-41-12 checks delegation, preserved errors/references, inert construction and
disconnect during accepted preparation in the optional stdio lane. Phase 2
owns the causal admission/cancellation race tests; this phase proves the adapter
calls that owner and reports its result. Real assistant-session qualification
is recorded separately from local adapter evidence.

## Fixed Contracts And Private Discretion

MCP delegates to the same native availability/run operation. Update the Stage 40
stdio adapter to accept an explicit protected deployment selection, keeping
constructors/server startup inert until a tool explicitly ensures/runs services.
Add a high-level `loom_run` tool over the Phase 2 run contract; keep useful native
prepare, submit, inspect, wait and cancel tools as thin calls to the same owners.
Expose run-operation cancellation through `loom_cancel_run_operation`, delegating
to Phase 2's named native method and returning its control operation. Keep
`loom_cancel_preparation` for prepare-only; tools never emulate the publish/admit
race with separate client-side calls.
One run tool is not another orchestrator: accepted prepare-to-admit chaining stays
with the native operation even if MCP exits. Keep native bounds, typed errors,
coordinator identity guards and unknown-outcome references; no private MCP state.

Update four existing skills in place: prepare-only stops at its receipt; run uses
the unified accepted operation; monitor reconnects/queries; diagnose distinguishes
run result, scheduler evidence and service cleanup. Tools do not install code,
write service secrets or provision workers. MCP remains optional and stdio only.

### Delivery boundary

An explicit tool can ensure configured services and accept a durable run. Server construction remains inert; preparation-only remains distinct. Expose native accepted/uncertain/recovery references and cleanup evidence unchanged.

### Cross-phase handoff

Phase 9 consumes updated public tool/skill docs and removal dispositions. Existing skill invocation semantics and native operation truth have one owner; future adapter edits must not reintroduce a client-side continuation/cancellation race.

### Removal owned here

Replace old run-skill submit-only instructions where unified run is intended. Remove duplicate MCP orchestration and superseded tool wiring while retaining the explicitly supported low-level native operations. Update current examples alongside tools.

Private helper names, local wiring and intermediate representations remain
implementation discretion. Public behavior, durable identity, trust, failure and
cross-phase meanings above are fixed. No compatibility aliases or state resets.

## Proportionality

Extend the existing optional adapter and four skills. Constructor side effects, new storage, schema translation frameworks and separate scheduling are unnecessary.

## Invariant Ownership

| Invariant | Owner | Reachable boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Native operation is authoritative | Adapter delegation and native coordinator | MCP exits during accepted preparation | Stranded work or private lifecycle | VAL-41-12 process disconnect/native parity |
| Correct cancellation target | Native cancel_run_operation | Tool cancels before/after target admission | Acknowledged cancel races work | Delegate exact native method/control result; reuse Phase 2 race evidence |
| Bounded authorized tools | Existing native transport/policy | Wrong identity, oversized report, unavailable service | Mutation of wrong owner or unbounded output | Adapter propagation and native error/reference assertions |
| Optional imports remain inert | Package/adapter boundary | Base import or MCP startup | Unexpected dependency/service launch | Isolated Stage 40 import/tool lane |

## Implementation Slices

1. Wire explicit deployment/run/cancel tools to delivered native owners, retaining required tool bounds and identity guards.
2. Update four skills and examples for prepare-only, accepted run, reconnect, diagnostics and explicit cancellation.
3. Remove superseded adapter orchestration and prove native parity, process disconnect and isolated dependency behavior.

## Test And Validation Plan

| Suite | Obligation | Minimal evidence |
| --- | --- | --- |
| Package/isolated SDK | Required | Use published Stage 40 MCP lane; base import and server construction do not start services. |
| Unit/contract | Required | Tools call native ensure/run/cancel, preserve errors/references/limits and prepare-only semantics. |
| Integration/E2E | Required | Synthetic prepare/run/reconnect/cancel and disconnect during accepted preparation through stdio. |
| Real assistant session | Environment-dependent qualification | Reuse/requalify Stage 40 discovery/run tools where available; record unrun claims explicitly. |

Target existing source-mirrored tests and add focused assertions where the new
contract requires them. Resolve predecessor-renamed test paths at preparation.
Run optional-runtime commands only with their qualified environment. A local
fixture is not live-site evidence; record missing qualification explicitly.

Use the exact isolated MCP package/SDK and process-test commands published by Stage 40; its modules and make lane are not implemented at this evidence revision. Record resolved commands in this card at execution preparation.

Final implementation gate; reuse a fresh receipt only while relevant code,
tests, dependency/build and validation configuration remain unchanged:

    make validate-pr
    make test-summary

Do not repeat complete backend/fault matrices in consumer phases. Expand tests
only for changed shared contracts, new failures or a remaining accepted concern.

## Risks, Review, And Stops

Stop for a native handoff conflict; fix that owner rather than emulating it in MCP. Live-session absence is a qualification gap. Do not install dependencies into active project environments or submit scientific workloads as acceptance fixtures.

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
- Independent implementation review: required for tool authorization/side effects and cancellation delegation
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
| Residual risk and cleanup | Optional MCP/real-session qualification pending |
