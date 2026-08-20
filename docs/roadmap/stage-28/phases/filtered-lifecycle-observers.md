# Phase 3 Execution Plan: Filtered Lifecycle Observers

## Metadata

- Status: pending
- Roadmap stage and phase: v28 Phase 3
- Manifest: `docs/roadmap/stage-28/implementation-plan.md`
- Branch: `agent/stage-28-p3-filtered-lifecycle-observers`
- Worktree root and path: record during phase preparation; default to the
  `loom-worktrees` sibling of the discovered control checkout
- Base revision: current `origin/develop` after Phase 2 remotely merges
- PR target: `develop`
- PR title: `Stage 28 phase 3: add filtered lifecycle observers`
- Dependencies: Phase 2 merged; planning `FR-1` through `FR-3` and `FR-8`
  through `FR-12`; `DQ-2`, `DQ-4`, `DQ-7`, `DQ-8`; `EDR-5` through `EDR-8`;
  Stage 26 must not have assigned exact event-name filtering to a conflicting
  owner
- Workflow path: fast; filter semantics and ownership passed the expanded stage
  review, with manager escalation only if Stage 26 changed that contract
- Blockers: none on the reviewed evidence base

## Objective And Context

- Vertical outcome: a downstream sink selected from Python or CLI receives only
  exact subscribed committed lifecycle events in whichever process owns the
  commit, while callback failures remain observable and non-fatal.
- Earlier dependency: Phase 2's exact activation manifest/process allowlists and
  existing Stage 20 event records, sink registry/loader, runner dispatcher,
  observer-link/failure stores, and continuation event helpers.
- Later work explicitly out of scope: notification severity/message policy,
  Slack/email/webhook adapters, payload predicates, mutation hooks, fatal mode,
  async delivery, replay cursors, outboxes, retries, and delivery guarantees.

## Current Source And Harness

- Relevant files/symbols:
  - `pipeline/event_sinks.py`: sink/context/failure/link records and registry;
  - `pipeline/events.py`: authoritative event-type validation and records;
  - `plugins/event_sinks.py`: callable/class/factory normalization;
  - `execution/eventing.py`: durable append before dispatch and sink context;
  - `execution/runner.py`/`models.py`: `RunRequest.event_sink_registry` and
    runner-owned dispatcher;
  - `execution/lifecycle.py` and `continuation.py`: stage/run commit events;
  - run-store event/failure/link protocols and implementations; and
  - run, prepared-run, stage-job, and preflight CLI composition roots.
- Existing tests/seams: event model/registry/dispatcher unit tests, event sink
  plugin adapter tests, package API tests, authority/store event contracts,
  runner lifecycle integration, stage-job continuation integration, cleanup
  retention of event-adjacent records, and CLI run E2E.
- Constraints: dispatch follows authoritative append/commit; sink context stays
  narrow; plugin code is explicit/trusted; no service dependency; a subprocess
  stage worker does not own parent lifecycle commits and must not receive sinks.

## Scope

In scope:

- immutable exact event-type subscription and sink-registration values;
- backward-compatible registry registration, item inspection, filtering, and
  callback-result behavior;
- event-sink plugin normalization for a registration value while preserving
  all current callable/class/factory forms as observe-all;
- Phase 2 activation at preflight/run lifecycle roots and applicable prepared-
  run/stage-job continuation roots;
- dispatcher threading through continuation/lifecycle helpers that currently
  append directly without a supplied registry;
- readiness/conformance/doc updates and committed-state/failure proof; and
- a complete documented table of current emitted event types and which process
  owns each emission.

Out of scope:

- adding an event solely to create more callback points unless a current
  lifecycle transition already lacks its committed event;
- any callback return value that changes plan, state, retry, timeout, output,
  artifact, config, queue, or authority behavior;
- asynchronous/background execution, concurrency bounds, sink timeout/retry,
  persisted subscription/config, delivery checkpoint, replay API, or external
  service adapter; and
- passing sinks into direct subprocess workers whose parent commits results.

Assumptions:

- current event type strings are the stable filter vocabulary; subscriptions do
  not introduce aliases, globs, prefixes, severity, or payload matching;
- selected sink plugins are installed in self-finalizing continuation
  environments; and
- synchronous callback latency is accepted existing behavior and is documented,
  not redefined as a delivery SLA.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - `registry.register(name, sink)` and existing plugin sinks observe all events
    exactly as before;
  - a subscription uses exact equality on `EventReference.event_type`;
  - a non-matching sink is not called and produces no callback result, failure,
    or observer link for that event;
  - matching sinks retain registry registration order; one failure is recorded
    best-effort and does not stop later matching sinks or change run status;
  - durable mode appends the event before dispatch, and a `stage.completed` sink
    can read committed outputs/status; and
  - only the lifecycle-owning process receives sink activations.
- Public shapes:
  - frozen `EventSinkSubscription(event_types: tuple[str, ...])` validates a
    non-empty iterable with the authoritative event-name validator, removes no
    duplicates silently, and stores a unique sorted tuple;
  - frozen `EventSinkRegistration(sink: EventSink,
    subscription: EventSinkSubscription | None = None)` validates callability;
  - `EventSinkRegistry.register(name, sink, *, subscription=None)` remains the
    direct API; the registry may internally normalize to registrations; and
  - plugin targets may normalize to `EventSinkRegistration`; plain callable,
    no-argument class, or no-argument factory returning a callable retains an
    all-events subscription.
- Conformance compatibility: `check_event_sink_contract` accepts a plain sink
  or `EventSinkRegistration` and reports `contract="loom.event_sink"`, version
  2. Its required finding order is `event_sink.callable`,
  `event_sink.subscription`, then `event_sink.invoke` for each event in caller
  order that the subscription should dispatch. The v1 callable/invoke meanings
  remain; version 2 records the new subscription validation/selection semantic.
  The other Phase 1 contract names, versions, and code catalogs do not change.
- Trust/failure boundaries: subscriptions filter immutable event identity only;
  sink context still exposes run URI/event reference plus existing link/failure
  recording; exceptions are bounded failure facts and callback return values
  are ignored.
- Cross-phase: `plugin_activations` schema and group/name/target comparison are
  unchanged. Run/preflight allow `loom.event_sinks`; direct stage worker rejects
  it; stage-job/prepared continuation accepts it only when it owns events.
- Reproducibility/compatibility: no event, event-reference, failure/link, store,
  or run schema changes; filter state is implementation construction, while the
  plugin activation identity remains provenance. Existing event order and
  persistence settings remain.
- Private discretion: internal registration container, lookup optimization,
  dispatcher plumbing helpers, whether skipped sinks are iterated or indexed,
  and CLI composition helper reuse.

## Proportionality

- Existing seam reused: `EventSinkRegistry`, plugin adapter, Phase 2 activation,
  `RunRequest.event_sink_registry`, `RuntimeEventDispatcher`, lifecycle event
  helpers, and failure/link storage.
- Material additions/current justification: exact allowlists prevent every
  observer from doing its own filtering; continuation wiring makes CLI-selected
  observers usable where remote lifecycle commits actually occur.
- Deferred hardening: predicates, severity mapping, sink priority/concurrency,
  async queues, strict/fatal observers, delivery receipts/cursors/outboxes,
  retry/idempotency protocols, and first-party service adapters.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Event-name validity has one owner | Pipeline event validation reused by subscription | user/plugin subscription | filter never matches or accepts malformed vocabulary | invalid/duplicate/empty/exact-name unit cases |
| Filtered dispatch calls only matches | Event sink registry | multiple registrations/subscriptions | unwanted side effect/noise | mixed observe-all and disjoint allowlists |
| Dispatch observes committed fact | runner/lifecycle/store then dispatcher | reordered continuation helper | callback reads stale status/artifacts | callback reads authority/store at `stage.completed` |
| Sink failure cannot alter correctness | registry/dispatcher | raising callback/failure recorder | run fails or later sink skipped | failure + later success + final run status assertions |
| Only lifecycle owner constructs sinks | CLI/continuation composition root | activation subset propagation | duplicate notifications or worker side effects | exact parent/worker/stage-job activation args |
| Observer evidence references triggering event | sink context/store | sink records link/failure | unauditable external reference | existing contract plus filtered integration cases |

## Implementation Slices

1. Add subscription/registration public values and compatible registry
   normalization/filtering with focused unit/package tests.
2. Extend event-sink plugin normalization and Phase 1 conformance/readiness for
   filtered registrations without changing observe-all plugins.
3. Activate selected sinks in run/preflight composition, pass no sink records to
   direct stage workers, and reuse Phase 2 comparison/provenance.
4. Thread a dispatcher/registry through stage-job and prepared continuation
   lifecycle emissions so only their commit-owning process observes events.
5. Add post-commit, exact-filter, failure-order, and activation-subset
   integration/E2E proof; update lifecycle/plugin/reliability/CLI/testing docs.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | public compatibility/import safety | new types intentional; old imports/callable plugin forms unchanged; no activation on import/help |
| Unit | required | subscription/registry/plugin normalization | validation, exact match, observe-all, order, failures, registration factory forms |
| Contract | required | sink/store/activation semantics | conformance report, failure/link references, applicable group allowlists |
| Integration | required | commit-owner dispatch | runner and stage-job callback reads committed status; subprocess worker gets no sink |
| E2E / opt-in | required local; external deferred | CLI user journey | explicitly selected synthetic sink sees only `stage.completed`; no service/network |

Targeted commands:

    .venv/bin/pytest -q tests/package/test_pipeline_event_sinks_api.py tests/unit/loom/pipeline/test_event_sinks.py tests/unit/loom/pipeline/execution/test_eventing.py tests/unit/loom/plugins/test_adapters.py
    .venv/bin/pytest -q tests/contracts/test_cli_plugins_contract.py tests/contracts/test_authority_store_contract.py tests/integration/pipeline/test_stage_job_continuation.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/e2e/test_cli_runs_e2e.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: filter validation duplicated from event grammar, callback before
  commit, sinks loaded in the wrong process, compatibility break for callable
  factories, or accidental delivery guarantees in docs.
- Review focus: `DQ-8`/`EDR-7`, exact activation subsets, all continuation emit
  call sites, post-commit evidence, and unchanged failure policy.
- Stop if: Stage 26 assigns exact filter semantics to another owner; correct
  continuation dispatch needs new durable cursor/outbox state; a callback must
  mutate runtime behavior; or avoiding duplicate sinks requires a new authority
  coordination protocol.
- Accepted debt/revisit: synchronous sinks may add latency and crash before
  callback completion; revisit only with an accepted at-least-once delivery
  requirement and idempotency/authority design.

## Executor Handoff

- Read: this plan plus planning `FR-1` through `FR-3`, `FR-8` through `FR-12`,
  `DQ-2`, `DQ-4`, `DQ-7`, `DQ-8`, and `EDR-5` through `EDR-8`.
- Safe slices: the five numbered slices; prove registry compatibility before
  continuation plumbing.
- Do not revisit: exact allowlists, observe-all default, post-commit sync order,
  best-effort failures, no direct-worker sinks, or no delivery machinery.
- Manager action required for: a Stage 26 ownership conflict, new event/durable
  schema, mutable/fatal callback request, or service/async dependency.

## Workflow State

- Manager preparation: complete
- Expanded planning: not needed unless Stage 26 changed exact-filter ownership
- Implementation: pending one `loom_phase_executor`
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: manager-local fast path
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none / pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
