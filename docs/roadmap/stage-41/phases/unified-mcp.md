# Phase 8 Execution Plan: Unified MCP And Skills

## Metadata

- Status: in_progress
- Roadmap stage and phase: 41 / 8
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p8-unified-mcp
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: `daab4d1eeeb2d5ba827e31f81bbb6e4fc8517eec` (published Phase 7 completion metadata after PR 317)
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 8: Unified MCP And Skills
- Dependencies: Phase 7 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: pre-submit identity guard runs after native binding/startup writes; scoped correction 1 pending

## Objective And Context

MCP runs, observes and cancels through the same native service/run owners, with updated skills and no private lifecycle.

Stage 40 delivers the adapter and skills; Phases 2–3 deliver the native run/cancel/availability methods. This phase updates those existing consumers only. It is sequenced after the sweep phase for one-PR-at-a-time integration, not because MCP depends on sweep internals.

Requirements: FR-41-01/05/13/14. Design: DQ-41-01/06.
Validation ownership: VAL-41-12 (MCP/skills/imports).

## Current Source And Harness

- Delivered `src/loom/mcp/{__init__,_server}.py`, thirteen registered tools and `skills/{loom-prepare,loom-run,loom-monitor,loom-diagnose}`. `loom_submit_run` exists; high-level `loom_run` and `loom_cancel_run_operation` are new consumers. Tests live in `tests/{unit/loom/mcp,contracts/test_mcp_tools.py,integration/mcp}`.
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
This phase adds the high-level run tool using the durable prepare/admit
operation and the explicit deployment availability behavior delivered by
Phases 2–3. It must not implement a separate sequence of prepare, wait and
submit calls whose continuation disappears when the assistant disconnects.

This sketch shows delegation only. `request` is decoded through the native
request model, `server_deployment` is the server's protected startup selection,
and `client` resolves that same deployment with its normal identity/policy guards.
Tool decorators, transport serialization and result bounding remain with the
existing adapter; these functions are not a complete server implementation.

```python
import loom


def loom_run(request):
    return loom.run(request, deployment=server_deployment, wait=False)


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

MCP delegates to the same native availability/run operation. Select one protected
deployment at stdio-server startup with `loom-mcp --deployment PATH`; resolve that
path from the server process cwd, and its references relative to the deployment.
Run, prepare, submit, query, wait and cancel all resolve the same bound coordinator
identity. Tool calls cannot supply an arbitrary deployment/connection override.
This replaces the adapter's endpoint/connection startup selectors; the native
client constructors remain useful. Constructors/server startup stay inert until
an explicit run ensures configured services. Existing preparation/query tools
connect and report availability; they do not implicitly create services.
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

### One binding, native deadlines and explicit retry

The deployment resolver must work before first local creation and after restart:
all tools use its resulting expected coordinator identity, never a stale client
captured before binding. Discovery remains available while services are offline.
Keep read-only tool annotations truthful; use `loom_run` as the startup-capable
mutation rather than adding a separate ensure tool without a current consumer.

Run returns after durable run-operation acceptance (`wait=False`). Pass the
adapter's existing absolute request deadline through the native availability/run
composition, including capacity acquisition and startup; each native wait remains
bounded at 25 seconds within the current 30-second request budget. Startup timeout
before dispatch yields a native not-applied outcome and releases startup holds;
possible dispatch retains unknown-outcome IDs for reconciliation. SDK cancellation
or EOF does not translate into cancellation of accepted work. In-progress native
calls retain adapter capacity until their bounded completion, preserving ordinary
query/cancel capacity while waits are active.

Update `loom_prepare_run` to expose P1's ordered invocation controls through native
decoders. Retain `loom_submit_run` for exact prepared receipts and expose the
native optional `retry_failed_revision` for explicitly requested retry. Run replay
never invents that revision, and an unsupported authority capability remains an
explicit refusal. Update the four skills and relocated behavior trials together;
reconnect retains the same deployment/coordinator and original request identities.

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

Use the delivered isolated SDK/config lane, including schema, native delegation,
stdio EOF/cancellation, wrong-owner guards, near-limit reports and relocated skill
trials. Extend it with cold startup, all tools using one creation/restart binding,
no per-call deployment override, startup deadline/unknown-response behavior,
explicit retry forwarding and preserved read-only discovery. P2 owns the causal
run/admission cancellation races; these adapter checks prove delegation.

    make test-mcp-extra

`make validate-pr` and `make test-summary` already include this lane. A standalone
run is useful while iterating; do not add another summary run just to render the
same evidence. Preserve all approved final gates below.

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

- Manager preparation: passed on the manifest's persistent stage worktree and
  canonical Phase 8 branch at the Base revision above. Phase 7 PR 317 merged as
  `6ca596a806dde5b0594f4a1e96d91bbe188e3e7a`; completion metadata is published,
  synchronization verified matching stage/local/fetched/advertised develop, and
  exact local/remote predecessor branches are retired. All predecessor agents
  and phase-owned processes are terminal. Successor start/preflight passed.
- Source reconciliation: the delivered optional adapter captures a client at
  construction and selects endpoint/connection on its CLI. Native `loom.run`
  owns availability, durable acceptance, bounded observation and cleanup;
  `deployment.ensure_available` owns creation/restart bindings. Resolve current
  clients through that native deployment owner after creation/restart; ordinary
  tools remain connect-only and construction/discovery remain inert. The adapter
  must not copy binding state or compose private prepare/wait/submit continuation.
  Current native templates include exact/reconciled mode; decode supplied native
  intent without dropping invocation controls or adding MCP reconciliation policy.
- Native integration scope: any missing connect-only resolver, absolute-deadline
  plumbing or identity/error handoff belongs in the existing deployment/run owner,
  with its current consumers and causal tests. Preserve the accepted native
  lifecycle and protected bindings; no new durable schema or deployment mode.
  Stop for a demonstrated accepted-contract conflict, not a private helper choice.
- Validation selection: existing MCP unit/contract/stdio and isolated-import
  consumers; complete invocation/explicit retry; cold startup and creation/restart
  binding; same-owner errors; capacity/deadline/EOF behavior; relocated skill trials
  and current example/docs. Add native deployment/run checks if those boundaries
  change. Both final make gates remain binding. Reuse prior backend qualification
  and record the actual assistant-session gap separately from local fixtures.
- Named refinement: none; fixed public/durable/trust contracts are sufficient.
- Execution delegation: one executor is justified for the coupled optional
  adapter, native binding/deadline integration, four operational skills and stdio
  lifecycle tests. The manager owns the manifest, delivery and independent review;
  no children, extra branches or lifecycle sidecars are permitted.
- Planning review: original accepted contracts retained; 2026-09-12 published-source amendments and current readiness receipt are owned by the manifest Quality Gate
- Implementation: complete and validated at `294f31d7aaf0f90cd21d36c2a234832c61a0f931`; fifteen tools, native binding/deadline integration, four skills and current docs are committed. Both mandatory gates pass; manager delivery and independent review remain pending.
- Refiner: not used
- Pre-submit gate: product blocker identified at `6fa59d78ad980e8c22016c11ae680762a944b2ad`; the first scoped correction below is required before review/delivery.
- Independent implementation review: required for tool authorization/side effects and cancellation delegation
- Scoped correction 1: the supported `loom_run` call accepts an optional saved
  coordinator guard. Its native composition calls `ensure_available`, which calls
  `_bind` before checking that guard. A cold selected deployment with a conflicting
  expected owner therefore creates the deployment, publishes its binding and
  writes `startup-attachment:<operation_id>` before returning conflict/not-applied.
  This violates the accepted expected-identity guard before mutation. The manager
  reproduced all three writes through the exact native composition used by MCP;
  `/tmp/loom-p8-owner-guard-before.log` records the causal failure. No daemon/job
  launched and the disposable fixture was cleaned.
  Enforce the expected identity at the native binding/availability owner before
  durable creation/binding/startup-hold writes. Preserve valid first creation
  without a supplied owner, correct-owner existing-root connection/restart and
  same-owner remote/local selections. Use existing protected identity/binding
  owners rather than a separate MCP check-then-start sequence. Add causal native
  and MCP coverage for a refused cold mismatch and unchanged existing binding/
  startup state, then affected checks and both fresh required gates. No new
  product contract, durable format, refiner or reviewer is needed.
- Blocker corrections: 1/3 (first correction pending)
- PR and merge: not started

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | `src/loom/mcp` binds one protected deployment, resolves current native clients, delegates durable run and named cancellation, and forwards ordered invocation/explicit receipt retry. Native deployment/run and service qualification helpers share the absolute startup deadline without qualifying workers during connect-only reads. Four skills, MCP docs/example and directly affected native/package/SDK tests updated. |
| Tests added, updated or intentionally removed | Inert public discovery, no per-call selectors, complete native request/deadline/error/control forwarding, explicit receipt retry, capacity retention after SDK cancellation, unified stdio disconnect, cold creation/restart binding, connect-only missing-root refusal, and qualification deadline refusal. Existing source/report/identity/authorization/optional-import checks retained. One existing native deployment fixture assertion was narrowed for Pyright. |
| Validated revision/tree and evidence | Both mandatory gates passed on clean candidate `294f31d7aaf0f90cd21d36c2a234832c61a0f931`, tree `7307610ba9fdba808739b275fb9e84cb47b14fe0`. `make validate-pr`: Ruff/Pyright pass; default 3374 passed/2 skipped, config-extra 297 passed/18 skipped, MCP 44 passed; wheel/sdist built. `make test-summary`: 3717 passed, 18 skipped, zero failures/errors across seven suites. The 160-test focused selection and causal logs, final gate logs, Markdown summary and seven XML/coverage suites are retained under `/tmp/loom-stage41-p8-evidence/`; 24 final gate/report files were byte-verified against originals. |
| Validation-relevant changes after evidence | Manager found the identity-before-binding blocker above. Initial gates remain evidence for their exact revision; the scoped correction requires fresh affected checks and both final gates before review. |
| Replaced-code removal / retained primitive consumers | Removed endpoint/connection MCP startup selectors and captured-client wiring. Current registration docs, package CLI test, stdio fixtures and four skills use deployment binding. Retained native prepare-only, exact receipt submit/explicit failed-revision retry, observation and cancellation consumers. Native Python client endpoint/connection constructors and their separate CLI consumers remain supported. |
| PR, review and merge | Pending |
| Residual risk and cleanup | Live Codex and physical NAS qualification remain unrun: this session exposes no Loom tools and predecessor evidence does not establish those trials. Local synthetic/SDK evidence makes no physical qualification claim. Both gate terminals and phase-owned test/service processes are terminal; process inspection found only unrelated historical supervisors and current rphys work, which were preserved. |


### Validation selection and causal findings

The affected contracts are the protected native binding, availability and startup
deadline, durable acceptance/cancellation, invocation fidelity, bounded adapter
capacity, optional imports, and portable skill behavior. Focused selectors are
`tests/unit/loom/mcp`, `tests/contracts/test_mcp_tools.py`,
`tests/integration/mcp`, `tests/integration/queue/test_service_lifetime.py`,
`tests/unit/loom/queue/test_deployment.py` and
`tests/unit/loom/queue/test_resident_readiness.py` in the isolated locked MCP/config
environment. The final gates also cover package imports and remaining native
consumers. Expansion triggers are a changed native boundary, failing supported
consumer, or missing accepted coverage; both approved final gates remain required.

A connect-only resolver initially reused full service loading. That qualified
workers on reads and exceeded the existing query/cancel capacity latency check.
It now reads protected routing and the retained binding; native handshake owns
the live identity check, while ensure/reload owns full installation validation.
Native availability also passes the original deadline into contained readiness
probes so a configured 120-second probe cannot extend a 30-second MCP request.
Probe containment remains with its existing owner. An expired startup is reported
as native `start_run` not-applied with original operation/queue references.

### Relocated skill behavior trials

The four updated skill directories passed skill-creator `quick_validate.py` after
independent copying to `/tmp/loom-p8-relocated-skills-o5mqmv4u`. They contain no
repository-relative supporting resources. Implementer behavioral simulations
using those relocated instructions produced these continuations:

| Input scenario | Continuation and stopping point |
| --- | --- |
| Build/checksum prepare-only with authored source/profile and overlays | Forward ordered controls to prepare; return the exact prepared receipt/report and stop before admission. |
| Transform/report prepare-and-run on the configured deployment | Send the complete native `loom_run` request; retain the accepted operation and coordinator; one requested status observation does not turn admission into execution success. |
| Reopened status-only session with saved owner/operation | Query that operation on the same deployment with its owner guard, distinguish applied admission from run completion, then stop. |
| Small inline failing preflight and scheduler-exit evidence | Explain the actual failing check; distinguish scheduler observation, authority result and service cleanup; no inferred repair or cancellation. |
| Large report with null inline evidence and no artifact reader | Preserve the aggregate status and exact pinned report reference; state that full checks were not read rather than claiming missing or downloaded evidence. |
| Lost unified-run response | Query the original operation on the same bound owner; preserve request/recovery identities and replay only identical intent if needed, without fresh IDs or inferred retry authorization. |
| Explicit run cancellation versus receipt retry | Cancel through `loom_cancel_run_operation` and observe its returned control ID; an explicitly authorized receipt retry alone forwards the observed `retry_failed_revision`, while ordinary replay omits it. |

These are scoped behavioral simulations, not an independent evaluator pass or a
live assistant qualification. The mandatory implementation reviewer can assess
them with the actual changed skills; native/stdio tests own runtime evidence.


### Final gate evidence

- Candidate revision/tree: `294f31d7aaf0f90cd21d36c2a234832c61a0f931` /
  `7307610ba9fdba808739b275fb9e84cb47b14fe0` (clean before both gates).
- Archive: `/tmp/loom-stage41-p8-evidence/loom-p8-validate-pr.log`,
  `loom-p8-test-summary.log`, `test-summary.md`, and the seven directories under
  `test-summary/` containing `junit.xml`, `coverage.json` and `.coverage`.
  Causal/targeted/static logs are retained alongside these final receipts.
- The summary's 18 skips are existing opt-in Docker/Apptainer acceptance; the
  default lane's two optional-import skips are covered by its separate extra
  lane. No scientific workload, worker provisioning, physical deployment or live
  assistant-session qualification was performed.
- A final process inspection found no remaining phase-owned runtime, MCP, pytest
  or harness process. Unrelated historical supervisors and current rphys work
  were left intact. No branch transition, push, PR or merge was performed by
  the executor. The manager owns subsequent gates and delivery.
