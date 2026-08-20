# Phase 2 Execution Plan: Generic Lifecycle Notifications

## Metadata

- Status: planned
- Roadmap stage and phase: Stage 26, Phase 2
- Manifest: `docs/roadmap/stage-26/implementation-plan.md`
- Branch: `agent/stage-26-p2-generic-lifecycle-notifications`
- Worktree root and path: manager-recorded `loom-worktrees` sibling;
  `<worktree-root>/stage-26-p2-generic-lifecycle-notifications`
- Base revision: current `origin/develop` after Phase 1 remotely merges
- PR target: `develop`
- PR title: `Stage 26 phase 2: add generic lifecycle notifications`
- Dependencies: Phase 1 remotely merged; planning `FR-4` through `FR-10`,
  `FQ-3` through `FQ-8`, `DQ-3` through `DQ-8`, and resolved expanded-review
  findings
- Workflow path: expanded because a public notifier contract performs an
  external side effect after committed lifecycle events
- Blockers: Phase 1 remote merge; expanded design result must be resolved in
  the finalized planning document

## Objective And Context

- Vertical outcome: a Python caller registers one project notifier and receives
  small, safe messages for selected committed lifecycle outcomes; notifier
  failures are visible but cannot change run correctness, and a returned
  provider identity is linked to the triggering event.
- Earlier dependency: Phase 1 settles the current lifecycle-event catalog,
  logging/artifact guidance, and any demonstrated compatibility corrections.
- Later work explicitly out of scope: Stage 28 CLI/plugin activation and exact
  registry subscriptions; provider-specific adapters; asynchronous or durable
  delivery machinery; every deferred former Stage 26 topic.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/pipeline/events.py` owns `PipelineEventRecord`,
    `EventReference`, resource identity, and event-name validation.
  - `src/loom/pipeline/event_sinks.py` owns the instance-local registry,
    ordered best-effort dispatch, `EventSinkFailureRecord`,
    `EventObserverExternalRef`, and `EventObserverLinkRecord`.
  - `src/loom/pipeline/execution/eventing.py::RuntimeEventDispatcher` appends
    durable events before dispatch and supplies the narrow observer context.
  - `RunRequest.event_sink_registry` and `event_persistence` already wire
    explicit Python observers through the normal runner path.
  - local and authority-backed stores already persist and read failure/link
    facts; no notification-specific store capability exists or is needed.
- Existing tests and seams:
  - event-sink unit tests prove registration order, duplicate rejection,
    failure continuation, narrow context, and observer links;
  - eventing/runner integration tests prove post-append and post-status dispatch
    plus non-durable warning behavior; and
  - plugin tests already accept callable event sinks, but Stage 28 owns runtime
    activation and subscription changes.
- Import, dependency, or harness constraints:
  - keep the new module import-light and service-neutral;
  - no HTTP client, templating, async, queue, email, Slack, Discord, webhook, or
    tracking dependency in core or tests;
  - explicit module imports are preferred; do not widen the root `loom` facade;
  - notification messages are plain-projectable but are not new persisted
    records; and
  - default validation must remain network-free and deterministic.

## Scope

In scope:

- Add `src/loom/pipeline/notifications.py` with the finalized public surface:
  - `NotificationError` for notification value/adapter validation;
  - `NotificationSeverity` with `info`, `warning`, and `error` values;
  - immutable `NotificationMessage` carrying the triggering
    `EventReference`, severity, title, body, optional stage name, and immutable
    plain-data facts, plus an adapter-ready `to_dict()`;
  - immutable `LifecycleNotificationPolicy` mapping exact valid event names to
    severities, with the planning-approved default map;
  - structural `Notifier.notify(message)` returning
    `EventObserverExternalRef | None`; and
  - `register_lifecycle_notifier(registry, *, name, notifier, policy=None)`.
- Export only these intentional names from the explicit module and lock them in
  a package-surface test. Do not add a top-level `loom` export.
- Default event/severity map:
  - `run.completed` -> `info`;
  - `run.cancelled` and `stage.cancelled` -> `warning`; and
  - `run.preparation_failed`, `run.failed`, and `stage.failed` -> `error`.
  Routine creation/open/planning/start, stage planning/start/completion/reuse/
  skip/block, and cleanup events are ignored unless supplied in a custom exact
  mapping.
- Build deterministic title/body text and an event-specific fact allowlist.
  Permitted facts are limited to applicable scalar/list identity facts such as
  `status`, `attempt`, `action`, `failure_type`, `failed_stage`, and safe reason
  `code`. Extract stage identity from the event resource when available.
- Never copy a whole event payload or include exception/reason messages,
  nested reason detail, config, environment, command, log text/path, artifact
  payload/ref metadata, or arbitrary user metadata. `run_uri`, event type/time,
  event identity, and optional stage name remain in the message.
- Accept a durable `PipelineEventRecord` or non-durable `EventReference` through
  the existing sink contract. Reference-only messages contain identity and
  severity with no invented payload/stage facts; durable event persistence is
  the recommended normal path and existing dispatcher warnings remain.
- Adapt notifier exceptions by allowing them to propagate to
  `EventSinkRegistry`, which remains the sole failure-recording/continuation
  owner. Do not catch and reclassify provider failures inside the notification
  layer.
- When a notifier returns an `EventObserverExternalRef`, append one
  `EventObserverLinkRecord` with the helper-owned registration name and exact
  context event reference. `None` is a valid success with no external link.
  Any invalid returned value raises `NotificationError` and becomes a normal
  sink failure.
- Extend `docs/downstream-operations.md`, reliability/plugin/testing docs, and
  README/example routing with high-level notification setup and delivery-limit
  language.
- Add `examples/operations/lifecycle-notifications/` or an equivalently small
  dependency-free runnable example. It should use a recording/project-style
  notifier, exercise selected/ignored messages, optionally return a synthetic
  external ref, and demonstrate a failing notifier without a network call.

Out of scope:

- Modifying `EventSinkRegistry` subscriptions, plugin entry-point activation,
  CLI flags/config, worker reconstruction, or Stage 28 activation evidence.
- A `NotificationRecord`, receipt log, cursor, outbox, delivery worker,
  background thread, async function, retry/backoff, deduplication key,
  rate-limit policy, replay command, or at-least/exactly-once claim.
- Provider base classes, provider names, credentials, URL/email validation,
  HTTP/SMTP behavior, message-size splitting, markdown/block formatting, or a
  first-party service adapter.
- Arbitrary templates, payload predicates, regex/glob filters, user expressions,
  stage selectors, severity thresholds beyond the exact event mapping, or
  strict/fatal callback policy.
- Scheduling, queue policy, resource usage, new resume semantics, acceptance
  environments, PR gates, or domain parsing.

Assumptions:

- The existing event and observer facts remain sufficient after Phase 1's
  source audit.
- Provider projects can translate `NotificationMessage.to_dict()` into their
  service shape and hold credentials outside Loom.
- Synchronous best-effort delivery is useful for the first feature even though
  it is not a reliability guarantee.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - without registration, runs behave exactly as before;
  - a registered notifier receives only policy-selected messages;
  - default messages carry no arbitrary payload data;
  - notifier invocation follows the matching committed lifecycle fact;
  - one notifier failure does not fail the run or suppress later sinks; and
  - a returned external reference creates one observer link for the exact
    registry name/event.
- Public or durable shapes:
  - exact public notification shapes are the planning `Minimum Design` shapes,
    subject to the resolved expanded-review correction;
  - `NotificationMessage.to_dict()` returns only
    `event_reference`, `severity`, `title`, `body`, `stage_name`, and `facts`;
  - there is no `schema_version`, `from_dict()`, notification persistence, or
    new store protocol; and
  - existing event/sink/failure/link schemas and callable sink compatibility do
    not change.
- Trust and failure boundaries:
  - project notifier code is trusted explicit code and owns external effects;
  - allowlisted projection is the only core redaction boundary;
  - provider exceptions and invalid return values are observer failures, not
    lifecycle failures; and
  - absence of failure/link evidence never proves whether an external service
    delivered a message.
- Cross-phase contracts:
  - consume Phase 1's exact event catalog and terminology;
  - do not duplicate Stage 28 subscription/activation semantics; a future
    Stage 28 registration may avoid invoking the notification sink for ignored
    events, but message selection remains unchanged; and
  - leave service adapters and stronger delivery semantics for separate
    evidence-backed stages.
- Reproducibility and compatibility: default titles/bodies and fact projection
  are deterministic for the supplied event. Callback order and timestamps keep
  existing event/sink semantics. No discovery occurs on import or default run.
- Private choices the executor may simplify: internal sink closure/class,
  helper decomposition, immutable mapping mechanics, test clock injection,
  exact concise English title/body wording, and whether fact allowlists use one
  table or focused functions.

## Proportionality

- Existing seam reused: event reference/record, event-name validation,
  registry dispatch, run request injection, dispatcher ordering, observer
  external refs/links/failures, local/authority store capabilities, and
  dependency-free examples.
- Material additions and current justification: one safe message type, one
  exact severity policy, one provider protocol, and one identity-safe
  registration helper prevent each notification plugin from reimplementing
  lifecycle selection/redaction/evidence.
- Optional hardening and future capability deferred: every durable/async/
  guaranteed-delivery mechanism, provider implementation, templates, richer
  filters, strict mode, and CLI/plugin activation.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Notification follows commit | runner/lifecycle/store then dispatcher | reordered emit or alternate helper | alert contradicts authoritative state | integration callback reads committed run/stage status |
| Selection/severity is exact | notification policy | malformed/custom map | missed or noisy alert | unit table for defaults/custom/ignored/invalid |
| Message is allowlisted | notification projector | event payload contains secret/free text | external disclosure | exact `to_dict` field/fact assertions with sentinel secrets |
| Registry name owns evidence identity | registration helper/registry | duplicated user-supplied sink name | link cannot be tied to callback | helper registration plus link round trip |
| Provider result is bounded | notifier adapter | arbitrary return object | false observer evidence | None/ref/invalid result cases |
| Provider failure cannot alter run | existing registry | raising notifier/failure recorder | failed run or skipped later observers | combined failure/later-success/final-status test |
| No delivery guarantee is implied | docs/public contract | missing outbox/replay window | operator assumes alert reliability | wording/API review and absence of durable API |

## Implementation Slices

1. Add and package-test the notification error, severity, message, policy, and
   structural notifier values with immutable/plain-data validation.
2. Implement exact default/custom selection and allowlisted deterministic event
   projection, including reference-only behavior.
3. Add the registration helper over `EventSinkRegistry`, notifier invocation,
   invalid-result handling, and observer-link integration without changing the
   registry/store contracts.
4. Add focused unit/contract/integration tests for commit ordering, safe
   projection, selected/ignored events, failure continuation, link identity,
   non-durable limitation, and default compatibility.
5. Add the dependency-free example and finalize downstream/reliability/plugin/
   testing/roadmap docs, then run full validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | intentional cheap public surface | exact `notifications.__all__`; no provider/root import |
| Unit | required | values, policy, projection, helper | validation/immutability; six defaults; custom/ignored; safe facts; None/ref/invalid return |
| Contract | required | downstream structural notifier and unchanged sink/store boundaries | class need not inherit Loom; normal registry/failure/link contracts remain sufficient |
| Integration | required | post-commit delivery and failure isolation | notifier reads committed state; exception records failure; later sink/final run unchanged; ref link exact |
| E2E / opt-in | required hermetic example; external deferred | copyable user journey | selected safe messages and ignored routine event, zero network/provider dependency |

Targeted commands:

    uv run pytest -q tests/package/test_pipeline_notifications_api.py tests/unit/loom/pipeline/test_notifications.py
    uv run pytest -q tests/unit/loom/pipeline/test_event_sinks.py tests/unit/loom/pipeline/execution/test_eventing.py
    uv run pytest -q tests/contracts/test_notification_contract.py tests/integration/pipeline/test_local_execution.py
    uv run pytest -q tests/e2e/test_examples_e2e.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: duplicating event-registry filtering, accidentally defining a
  durable notification record, leaking arbitrary payloads, swallowing provider
  errors before existing failure capture, mismatching observer sink identity,
  implying guaranteed delivery, or colliding with Stage 28 activation work.
- Review focus: minimal public surface, allowlist completeness, post-commit
  evidence, helper name/link identity, unchanged run status on failure, import
  cost, example simplicity, and explicit limitations.
- Stop if:
  - useful notification delivery requires a new event/store schema, outbox,
    background process, or provider dependency;
  - source audit shows notifications cannot observe committed state through the
    current dispatcher;
  - safe provider integration requires arbitrary payload/template support;
  - Stage 28 exact subscription/activation contracts conflict rather than
    compose with notification policy; or
  - a material notifier/result/redaction choice cannot be resolved from the
    finalized planning agreement.
- Accepted debt and revisit trigger: synchronous delivery may add latency and
  has an ambiguous crash window around the external side effect. Revisit only
  with measured need and an accepted idempotency/delivery design.

## Executor Handoff

- Read section range: this entire plan plus planning `FR-4` through `FR-10`,
  `FQ-3` through `FQ-8`, `DQ-3` through `DQ-8`, and resolved expanded-review
  rows.
- Safe implementation slices: the five numbered slices; land value/projection
  tests before external-effect registration integration.
- Decisions not to revisit: existing event registry/observer facts, exact
  event map, allowlisted fields, in-process message, best-effort failure,
  Python-first setup, no provider/durable/async machinery, and all former Stage
  26 deferrals.
- Conditions requiring manager action: any stop condition, need for a new
  public/durable shape, Stage 28 ownership conflict, or source change outside
  notification/event/doc/example/test ownership.

## Workflow State

- Manager preparation: pending Phase 1 merge and finalized expanded-review
  correction
- Expanded planning: stage-level design-safety review result recorded in
  planning; no separate phase planner unless a concrete residual risk remains
- Implementation: pending one `loom_phase_executor`
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: manager-local unless the implemented public boundary has
  a material residual risk
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
