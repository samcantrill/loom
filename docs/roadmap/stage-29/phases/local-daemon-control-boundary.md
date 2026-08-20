# Phase 1 Execution Plan: Unified Local Daemon And Control Boundary

## Metadata

- Status: pending
- Roadmap stage and phase: v29 Phase 1
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p1-local-daemon-control-boundary`
- Worktree root and path: record during phase preparation; default to the
  `loom-worktrees` sibling of the discovered control checkout
- Base revision: current `origin/develop` after Stage 28 remotely merges
- PR target: `develop`
- PR title: `Stage 29 phase 1: unify managed execution behind durable assignments`
- Dependencies: Stage 28 merged; revised Stage 25 selection implemented;
  planning `FR-1` through `FR-10`, `FR-12`, `FR-13`, `FR-15` through `FR-17`
  and `DQ-1`, `DQ-2`, `DQ-4`, `DQ-6`, `DQ-8`, `DQ-9`
- Workflow path: expanded because managed-path migration, first durable
  assignment/journal schema, and process-start crash ordering interact
- Blockers: Stage 28/Stage 25 sequencing only

## Objective And Context

- Vertical outcome: command-scoped managed operations,
  `ManagedLocalQueueRuntime`, and a co-located per-user daemon all select,
  assign, admit, launch, report, and cancel one resident-profile run through the
  same coordinator, direct-client, assignment, agent-runtime, journal, and
  existing local adapter path.
- Existing classes/methods remain usable without a background daemon or network,
  but they delegate to the common composition and no longer own an independent
  managed claim-and-dispatch loop.
- Earlier dependency: revised Stage 25 selector, current queue/SQLite/service,
  authority app/client/generation, Stage 23/24 managed admission/process safety,
  queue CLI, and Stage 27 immutable plan contract.
- Later Phase 2 substitutes an authenticated HTTP client for remote agents and
  adds several offers/targets. Phase 3 adds control/recovery. Neither may add
  another scheduler or agent runtime.

## Current Source And Harness

- Relevant source:
  - `queue/controller.py` directly claims and dispatches in `run_once()` and
    `run_cycle()` and owns in-process recovery/session state;
  - `queue/managed_local.py` constructs service/controller/local adapter and
    owns serving/drain behavior;
  - `queue/{models,repository,_sqlite,service}.py` own queue identity, CAS,
    attempts, audit, and public repository compatibility;
  - `queue/{local,assignments,status,config}.py` own admission, process groups,
    cancellation, assignment providers, and status facts; and
  - authority app/client/supervisor and CLI modules provide transport,
    idempotency, service generation, lifecycle, and formatting seams.
- Tests cover repository/controller/runtime, authority protocol/app/client,
  local process cancellation, CLI E2E, imports, and fake clocks/processes. Stage
  25 adds selection/eligibility/race coverage before this phase.
- Keep `loom.queue` root cheap. Standard-library/fakeable clients remain the
  runtime boundary; default tests bind no public interface, need no certificate,
  and leave no daemon running.

## Scope

In scope:

- Import-light versioned values and validation for local agent registration,
  full offer, work request, assignment receipt/accept/report, heartbeat, and
  structured rejection using fields fixed by planning.
- One queue coordinator application service that resolves exact opportunities,
  invokes revised Stage 25 eligibility/preference, creates/advances assignments,
  owns cancellation intent, and builds source-labelled status. It imports no
  HTTP route, CLI, local adapter, agent runtime, or vendor implementation.
- One narrow `QueueCoordinatorClient`-shaped port and a direct in-process client
  that forwards the same value objects to coordinator service methods without
  bypassing validation, idempotency, fencing, or transitions.
- Private/additive coordinator storage for admitted local identity, assignments,
  cancellation reference/intent, and atomic one-active-assignment transitions,
  without adding daemon methods to public `QueueRepository`.
- Assignment lifecycle: atomic `OFFERED` reserves the queued candidate;
  `DECLINED`/`EXPIRED` before acceptance leaves it queued and attempt unchanged;
  `ACCEPTED` authorizes/maps to claimed attempt; `RUNNING` maps to dispatched;
  one terminal report completes both source-labelled views.
- Generation-scoped in-memory local session/full-offer cache with exact revision
  and expiry validation. Presence history is not persisted.
- One agent runtime and durable local journal. Persist offered receipt before
  local profile/resource admission; on failure persist/report `DECLINED` and
  release; on success persist acceptance plus one `process_execution_id`,
  receive idempotent coordinator acknowledgement, then invoke existing process,
  renewal, cancellation, and cleanup behavior.
- One resident profile resolved from trusted local composition only, with safe
  capability/config fingerprint and pre-start mismatch rejection.
- Migrate managed `QueueController.run_once()`, `run_cycle()`, foreground/local
  client operations, and `ManagedLocalQueueRuntime` construction/serve/cancel/
  status to compose the coordinator, direct client, and common agent runtime.
  Preserve truthful public return shapes through facade translation; do not
  leave a managed direct claim/dispatch fallback.
- Compose queue routes with the authority application and add an HTTP client
  implementation of the same port for loopback conformance and external CLI.
  Loopback is default; insecure non-loopback startup is rejected. Remote agent
  admission/TLS credentials remain Phase 2.
- Co-located daemon lifecycle with an exclusive per-state-root process lock and
  exclusive coordinator-store activation before generation change. A second
  process reports the existing daemon and exits; it never kills or silently
  replaces it. Readiness follows store recovery, route setup, local agent
  journal reconciliation/registration, and a fresh full offer.
- Environment/supervisor resolution for deployment-specific bind/endpoint and
  certificate/credential-file references, with validation and redaction before
  startup. Committed examples use only `machine-A` and abstract placeholders;
  raw secrets and resolved host paths never appear in config examples, CLI
  arguments, status, diagnostics, or errors.
- Endpoint-backed submit/list/status/cancel, canonical docs, and an operational
  example with deterministic teardown and graceful session relinquish.

Out of scope:

- Several/remotely admitted agents, hard targeting, cross-host expiry/TLS
  receipt, reconfiguration, active-process restart resolution, payload transfer,
  placement policy, or coordinator HA.
- A second scheduler/runtime; topology flags in coordinator/selector/agent;
  mandatory local HTTP; public repository expansion; queue identity rename;
  schema-v1 rewrite; general daemon/client framework; broker/WebSocket/gRPC;
  policy registry; resource-pool hierarchy.
- Claiming restart recovery for a possibly live process. Gate as ambiguous for
  Phase 3 rather than reattach/restart.

Assumptions:

- The co-located/local agent has a stable configured `agent_id`, a fresh session,
  and one contribution per selected managed pool. Command-scoped use creates
  the same values in process and closes them safely at completion.
- Resident project/config/run/artifact paths already exist locally, matching
  current assumptions.
- Exact module/class/route/table/journal/supervisor names remain private except
  fixed wire/CLI JSON contracts.

## Fixed Contracts And Private Discretion

- Observable behavior: same queue, opportunity, and policy produce the same
  selected item and assignment transitions from `run_once`, managed cycle,
  direct daemon agent, or loopback HTTP agent. Transport-specific evidence is
  excluded when comparing normalized traces.
- No-network compatibility: existing managed APIs do not require a daemon or
  socket, but they do create/use the same coordinator assignment and agent
  journal state through the direct client.
- Public/durable shapes: retain queue/run/pool/agent/session/offer/assignment/
  attempt/process identities. `OFFERED` is separate from `CLAIMED`; acceptance
  is the execution authorization. Session/offer codecs are wire values but not
  restart truth.
- Trust/failure: authored resident config is trusted; every client value still
  receives shape, revision, idempotency, fence, and transition validation.
  Journal failure prevents acceptance/start. Response failure after durable
  mutation is retryable. Coordinator reports are committed before
  acknowledgement and unacknowledged agent journal results replay after
  restart/reconnect.
- Cross-phase: Phase 2 may add HTTP auth/remote admission and more opportunities
  only; it reuses the service/client/assignment/agent contracts. Phase 3 may
  reconcile but cannot reinterpret possible start or expiry as death.
- Compatibility: public facade calls remain where truthful; default ordering is
  revised Stage 25 oldest eligible. Delegated adapters remain outside the
  managed agent path. Safe profile/fingerprint evidence excludes paths/env.
- Private choices: facade result adapters, direct client class name, whether
  focused loopback tests serialize, SQLite/file journal, route grouping,
  transaction helpers, lock representation, supervisor layout, and polling
  intervals. The exclusive-lock behavior and configuration-source separation
  are fixed.

## Proportionality

- Reuse Stage 25 selector, queue identity/SQLite, authority generation/
  idempotency, local adapter/providers/process containment, and public facades.
- Assignment storage is required between coordinator and accept; journal is
  required between accept and process start; direct client is required to avoid
  both mandatory networking and a second implementation.
- Defer remote admission, reconfiguration, data plane, alternate auth, key UI,
  metrics, journal compaction, HA, and general frameworks.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| All managed entrypoints reach the same coordinator and agent methods. | Composition/facade constructors | retained direct controller loop | behavioral drift | method spy + normalized traces |
| Same opportunity/policy has same decision through direct and HTTP clients. | Coordinator + Stage 25 selector | route/client owns policy or changes values | topology drift | client conformance suite |
| At most one active assignment exists for item/attempt. | Coordinator transaction | duplicate pulls/retry | duplicate execution | SQLite barrier |
| Current generation/session/offer fences every assignment mutation. | Coordinator transaction | stale client/restart | stale mutation | protocol/fake-clock negatives |
| Receipt precedes admission; accepted process ID and acknowledgement precede start. | Agent journal/runtime | crash or response loss | stranded/duplicate process | fault injection at every edge |
| One assignment starts at most one process. | Agent runtime | duplicate delivery/restart | duplicate side effect | process spy/journal readback |
| Cancel terminal follows observed exit and resource release. | Agent runtime report gate | cancel/exit race | false terminal/free capacity | real process-group test |
| Queue/assignment/run facts remain source-labelled. | Status builder | projection inference | false lifecycle | exact status scenarios |
| A second daemon using one state root/store cannot become active. | Daemon activation composition | concurrent start or stale PID marker | two coordinators/agents mutate one state | real process-lock/store-activation race |
| Deployment values do not leak through config projection or errors. | Daemon config loader/status boundary | environment and secret-file resolution | credentials or host details exposed | allowlist/redaction and malformed-env tests |

## Implementation Slices

1. Add work/assignment/client value contracts, coordinator service, private
   storage/CAS, local offer cache, and transition tests.
2. Add direct client and common agent journal/runtime around existing local
   admission/adapter, proving all persist/ack/start crash edges.
3. Recompose `QueueController` and `ManagedLocalQueueRuntime` managed operations
   as compatibility facades; remove/disable managed direct claim-dispatch flow
   and prove normalized parity.
4. Compose HTTP routes/client with authority app, add idempotency/insecure-bind/
   malformed/version/role tests, and run the same client conformance suite.
5. Add co-located daemon process/store activation guards, environment-resolved
   deployment config, CLI/docs `machine-A` example, and real-process command/
   runtime/daemon E2E with clean teardown and repository-wide validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Intentional cheap client/agent values. | Explicit-module exports; no root routes/vendor/supervisor import. |
| Unit | required | Values, cache, state machine, journal, facade delegation, environment resolution. | Exact transitions; no managed direct fallback; fault injection; no resolved secret projection. |
| Contract | required | Client semantics, queue/repository compatibility, CLI JSON. | Direct/HTTP same application result; v1/read APIs unchanged. |
| Integration | required | SQLite assignment race, local adapter, facade parity, composed app. | One assignment/process; same normalized trace; cancel cleanup. |
| E2E / opt-in | command/managed/co-located/loopback required; `machine-A`/`machine-B` remote receipt deferred | Real resident lifecycle and duplicate startup. | Same selected item/transitions; separate CLI calls; second daemon rejected; clean teardown. |

Targeted commands:

    uv run pytest -q tests/unit/loom/queue tests/contracts/test_queue_* tests/integration/queue tests/integration/authority
    uv run pytest -q tests/e2e/test_queue_cli.py tests/e2e/test_authority_supervisor_cli.py
    uv run pytest -q tests/contracts/test_queue_python_api_contract.py tests/package/test_import_boundaries.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: facade secretly retains direct dispatch, direct client skips
  validation, queue/assignment transition mismatch, journal start twice,
  transaction invariant split, route policy, or trusted launch-data leakage.
- Review focus: call graph from every managed entrypoint; exact state mapping;
  crash order; one active assignment; client conformance; public repository/
  schema compatibility; source-labelled status; import direction; teardown.
- Stop if truthful facade mapping requires two lifecycle owners, an active
  managed path cannot use assignment without a breaking public change, one
  assignment cannot be atomic, resident work requires data transfer, generation
  cannot fence sessions, or secure HTTP needs a new heavyweight dependency.
- Accepted debt: after Phase 1 remote production is not enabled and active
  restart remains ambiguous. Phase 2/3 advance only after common local traces
  and fault tests pass.

## Executor Handoff

- Read this plan; manifest Shared Constraints; planning Behavior Baseline,
  Minimum Design, Expanded Design Review; revised Stage 25 fixed contracts; and
  current controller/runtime/local adapter source.
- Execute five slices in order. Phase 1 is incomplete if any managed local
  entrypoint still schedules directly instead of delegating through the common
  coordinator/assignment/agent path.
- Do not revisit queue identity, one core, facade migration, direct/HTTP port,
  oldest-eligible selection, ephemeral offers, resident mode, persist-before-
  start, public repository compatibility, or no reattachment.
- Return for any stop condition, Stage 28/25 drift, unavoidable public API/schema
  choice, or inability to preserve truthful facade results.

## Workflow State

- Manager preparation: complete; refresh after Stage 28 and Stage 25 merge
- Expanded planning: unified cross-stage design and topology/lifecycle
  refinement approved. Use an optional planner only if refreshed source leaves
  assignment/facade crash ordering unresolved.
- Implementation: pending
- Refiner: optional only for qualified blocker; unused
- Pre-submit gate: pending
- Independent review: required due lifecycle migration risk
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none recorded |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
