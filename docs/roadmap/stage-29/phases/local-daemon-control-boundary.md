# Phase 1 Execution Plan: Local Daemon And Control Boundary

## Metadata

- Status: pending
- Roadmap stage and phase: v29 Phase 1
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p1-local-daemon-control-boundary`
- Worktree root and path: record during phase preparation; default to the
  `loom-worktrees` sibling of the discovered control checkout
- Base revision: current `origin/develop` after Stage 28 remotely merges
- PR target: `develop`
- PR title: `Stage 29 phase 1: add the durable local daemon boundary`
- Dependencies: Stage 28 merged; planning `FR-1` through `FR-5`, `FR-7` through
  `FR-10`, `FR-12`, `FR-13`, and `FR-15`; `DQ-1`, `DQ-2`, `DQ-4`, and `DQ-6`
- Workflow path: expanded because the first durable assignment/journal schema
  and process-start fault boundary causally interact; use at most one phase-
  planner refinement if current source changes leave that risk unresolved
- Blockers: Stage 28 merge only; no design blocker

## Objective And Context

- Vertical outcome: a user starts one co-located per-user daemon, submits a
  resident-profile whole-run item through its coordinator endpoint, observes it
  queued/running/terminal across separate CLI invocations, and cancels a real
  contained process. The coordinator and agent communicate through the same
  versioned control records and state machine later used remotely.
- Earlier dependency: existing queue records/SQLite repository/service,
  authority application/client/service generation, managed-local admission and
  process lifecycle, queue CLI, and Stage 27's immutable plan contract.
- Later work explicitly out of scope: remote agent admission, several live
  agents, target routing, offer expiry across hosts, real-host TLS receipt,
  drain/resume/reload, active-process restart recovery, payload transfer,
  placement policy, or coordinator HA.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/queue/{models,repository,_sqlite,service,controller,client}.py` for
    queue identity, guarded mutation, dispatch attempts, and compatibility;
  - `src/loom/queue/{local,managed_local,assignments,status,config}.py` for
    admission, process groups, journal evidence inputs, cancellation, and pool
    configuration;
  - `src/loom/authority/{app,services,supervisor,routes}/` and
    `pipeline/stores/{authority_client,authority_protocol}.py` for composed
    service startup, version/idempotency/error conventions, and HTTP clients;
  - `src/loom/cli/{queue,authority,main,formatting}.py` for thin lifecycle and
    job operations; and
  - `docs/structure.md`, `docs/features/{queue,execution,run-store,state,cli,
    protocols,testing}.md` for ownership and observable behavior.
- Existing tests and seams: queue model/repository/service/controller/local-
  adapter/runtime unit and integration suites; authority protocol/client/app/
  supervisor tests; real local process-group cancellation; queue and authority
  CLI E2E; package import tests; fake clocks/process runners/transports.
- Import, dependency, and harness constraints: keep `loom.queue` root imports
  cheap; FastAPI/uvicorn already exist for the authority service, while runtime
  clients stay standard-library/fakeable; default tests cannot bind public
  interfaces, need certificates, or depend on a daemon left running.

## Scope

In scope:

- import-light versioned wire values and validation for agent registration,
  one full offer, work request, assignment acceptance/report, heartbeat, and
  structured rejection, limited to fields fixed by planning;
- private/additive coordinator storage for admitted local agent identity,
  assignments, cancellation intent/reference, and atomic one-active-assignment
  mutation without adding methods to public `QueueRepository`;
- a generation-scoped in-memory session/full-offer cache for the co-located
  agent, including revision/expiry validation without durable presence history;
- queue coordinator routes composed into the authority application, a narrow
  coordinator client, request IDs/idempotency, loopback-default startup, and
  rejection of insecure non-loopback configuration;
- one agent runtime and minimal local journal that persist assignment acceptance
  and one `process_execution_id` before invoking existing local process,
  admission, assignment, renewal, cancellation, and cleanup behavior;
- one named resident profile resolved only from trusted local daemon config,
  with safe identity/capability projection and pre-start mismatch rejection;
- daemon lifecycle configuration/supervision and thin Python/CLI submit, list,
  status, and cancel operations over the endpoint, while preserving existing
  config-local queue commands and Python enqueue; and
- canonical ownership/protocol/CLI/test docs plus a co-located operational
  example that leaves no background process after the test.

Out of scope:

- persisting heartbeats/offers, exposing credentials or resident paths, adding
  arbitrary shell-command submission, or using an assignment as run authority;
- renaming `queue_item_id`, changing required pre-enqueue `run_uri`, rewriting
  schema-v1 records, or expanding `QueueRepository` for daemon-only operations;
- separate queue/authority web frameworks, an inbound agent server, broker,
  WebSocket/gRPC, general daemon base class, plugin registry, or resource-pool
  hierarchy; and
- claiming restart recovery for a process that may still be running. This phase
  must gate such state as ambiguous for Phase 3 rather than reattach or restart.

Assumptions:

- the co-located agent has one configured stable `agent_id`, one contribution
  per global pool, and uses loopback without TLS while still exercising role and
  protocol validation;
- resident project/config and local run/artifact paths already exist on the
  agent, matching current queue launch assumptions; and
- exact route names, table layout, journal files, supervisor state paths, token
  representation, and polling intervals are private unless an existing public
  CLI/JSON convention requires stability.

## Fixed Contracts And Private Discretion

- Observable behavior: daemon start is ready only after authority/queue storage,
  coordinator routes, and local agent registration/offer succeed. Submit is
  durable before it returns. Work stays queued until accepted. Status labels
  queue, assignment, run-authority, and same-session process observations.
  Cancellation reaches terminal only after exit observation and cleanup.
- Public or durable shapes: keep `queue_item_id`, `run_uri`, `pool_name`,
  `agent_id`, `agent_session_id`, `offer_revision`, `assignment_id`,
  `dispatch_attempt`, and `process_execution_id` distinct. Assignment stores the
  service generation, agent session, offer revision, and target identifiers.
  Session/offer values have codecs for the wire but are never replayed as
  durable truth after restart.
- Trust and failure boundaries: authored daemon/resident config is trusted;
  network/CLI payload shape, identity, role, size, revision, idempotency, and
  transition are validated. The journal write failure prevents acceptance or
  start. A response failure after mutation is safely retryable.
- Cross-phase contracts: Phase 2 may add remote agents and eligibility but must
  use these exact assignment/journal transitions. Phase 3 may reconcile a new
  session but cannot reinterpret an expired offer or possible process start as
  proof of death.
- Reproducibility and compatibility: existing local queue behavior and defaults
  do not contact a daemon. Resident profile identity/config fingerprint is safe
  evidence; private paths/environment are neither offered nor persisted in
  status. Existing queue and authority CLI envelopes remain readable.
- Private choices the executor may simplify: whether loopback calls traverse a
  socket or injected transport in focused tests, file/SQLite journal encoding,
  route grouping, service objects, transaction helpers, and formatting helpers.

## Proportionality

- Existing seam reused: the queue repository/controller path remains selection
  authority; authority generation/idempotency supplies service fencing;
  `LocalQueueDispatchAdapter` and providers remain process/resource authority.
- Material additions and current justification: assignment storage is required
  between durable selection and remote-capable acceptance; the journal is
  required between acceptance and process start; HTTP composition is required
  for later outbound agents and already has a current co-located consumer.
- Optional hardening and future capability deferred: key rotation UI, audit-log
  export, rate limiting beyond bounded requests, alternate auth providers,
  journal compaction, log streaming, payload plugins, and HA.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| At most one active assignment exists for `(queue_item_id, dispatch_attempt)`. | Private coordinator transaction | duplicate work requests or response retry | duplicate execution | SQLite barrier integration |
| Current generation/session/offer is named by every assignment mutation. | Coordinator service/cache | stale client or daemon restart | stale agent mutates work | protocol and fake-clock negatives |
| Assignment is journalled before `ACCEPTED`; process identity is journalled before start. | Agent runtime/journal | crash or journal I/O failure | untraceable possible process | injected failures around both writes |
| One assignment starts at most one process. | Agent journal/runtime | duplicate assignment delivery/report retry | duplicate side effects | process-runner spy plus restart readback |
| Cancel terminal follows observed process exit and resource release. | Local adapter/agent report | cancel-versus-exit race | false terminal/free capacity | real process-group integration |
| Queue, assignment, and run facts retain observation source. | Joined status builder | missing/lagging authority or process evidence | false lifecycle claim | exact joined-status scenarios |

## Implementation Slices

1. Add and contract-test the minimum wire/error values, private assignment
   repository operations, schema admission, and generation/session/offer cache.
2. Compose coordinator routes/client/auth hooks with the authority app and add
   hermetic retry, idempotency, insecure-bind, malformed/version/role tests.
3. Build the resident-profile agent runtime and journal around the existing
   local adapter, proving persist-before-accept/start and duplicate suppression.
4. Add co-located daemon lifecycle plus endpoint-backed Python/CLI submit,
   list/status/cancel and preserve all existing queue/authority command forms.
5. Complete real-process loopback E2E, restart ambiguity gate, docs/example,
   import/public-surface checks, and repository-wide validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | cheap intentional protocol/agent imports | explicit exports; no CLI/routes/vendor imports |
| Unit | required | codecs, validation, cache expiry, journal, auth/idempotency | exact fields/transitions; secret/path exclusions; injected I/O faults |
| Contract | required | queue compatibility, assignment storage, protocol and CLI JSON | v1 records/read APIs unchanged; stable structured errors |
| Integration | required | SQLite race, composed app/client, real local adapter | one assignment/process; retry safe; cancel cleanup ordering |
| E2E / opt-in | co-located required; real host deferred to Phase 2 | separate CLI invocations and daemon lifecycle | submit/status/cancel/terminal plus clean supervisor teardown |

Targeted commands:

    uv run pytest -q tests/unit/loom/queue tests/contracts/test_queue_* tests/integration/queue tests/integration/authority
    uv run pytest -q tests/e2e/test_queue_cli.py tests/e2e/test_authority_supervisor_cli.py
    uv run pytest -q tests/package/test_queue_api.py tests/package/test_import_boundaries.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: an atomic assignment invariant implemented outside the durable
  transaction, a journal acknowledgement window that can start twice, route
  composition that conflates queue and run authority, and CLI/status leakage of
  trusted launch/profile data.
- Review focus: every crash edge around offer/accept/journal/start; public
  `QueueRepository` and schema-v1 compatibility; source-labelled joined status;
  import direction; supervisor cleanup.
- Stop if: a resident Loom job cannot use existing launch/materialization
  assumptions without general payload transport; service generation cannot
  fence sessions without changing authority semantics; one-active-assignment
  cannot be atomic in the coordinator repository; or secure remote composition
  would require a new hard runtime dependency.
- Accepted debt and revisit trigger: loopback is the only production topology
  after this phase; advance only when its state machine and fault tests pass.

## Executor Handoff

- Read section range: this entire phase plan; manifest `Shared Constraints`;
  planning `Behavior Baseline`, `Minimum Design`, `Expanded Design Review`, and
  validation rows for co-located, competing/retried delivery, and cancel/loss.
- Safe implementation slices: execute the five slices in order; route/file
  splitting and private schemas are discretionary within fixed contracts.
- Decisions not to revisit: queue identity, pre-enqueue run URI, ephemeral
  presence, composed authority app, public repository compatibility, resident
  mode, persist-before-start, and no active-process reattachment.
- Conditions requiring manager action: any stop condition above, Stage 28
  changes to plugin/resident reconstruction that conflict, or a required public
  CLI/durable schema choice absent from the planning contract.

## Workflow State

- Manager preparation: complete at planning baseline; refresh after Stage 28
  merges
- Expanded planning: use at most one phase-planner only if the refreshed source
  leaves assignment/journal crash ordering unresolved
- Implementation: pending
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: pending risk classification after implementation
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none / details |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
