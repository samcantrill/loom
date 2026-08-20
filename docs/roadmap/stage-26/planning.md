# Roadmap Stage 26 Planning: Operational Correctness And Notifications

Status: draft; expanded design-safety review complete with minimum-design
corrections; cross-artifact reconciliation and manager gate pending
Roadmap stage: v26
Evidence tree: `/home/can134/work/active/loom` on `develop` at
`314e418192c3d46635b7f4754ea29ef736809f7d`; relevant pre-existing dirty
paths: `docs/roadmap.md`, `docs/roadmap/stage-27/`,
`docs/roadmap/stage-28/`, and `docs/roadmap/stage-29/`
Planning route: expanded because the one new feature is a public notification
contract that crosses the committed-event and external-side-effect boundary
Current gate: removal-first design review passed; reconcile the manifest and
linked phase plans, then run the manager quality gate
Blockers: none

Stage 26 makes existing Loom behavior easier to use correctly. It consolidates
stage-author, artifact, logging, lifecycle-event, and operational guidance,
corrects demonstrated mismatches between docs and implemented behavior, and
adds one feature: generic lifecycle notifications over the existing event-sink
path.

It does not add scheduling, resource-usage measurement, new resume semantics,
new validation gates, or service-specific notification clients.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Stage context, artifact helpers, executor logs, lifecycle events, event sinks, examples, tests, and adjacent plans were inspected at the stated tree. | None. | Preserve existing owners and durable formats. |
| Functionality | The maintainer narrowed the stage to correctness/documentation/logging plus generic notifications; every other former Stage 26 feature is deferred. | None. | Hold the accepted scope. |
| Design | Notifications reuse lifecycle events, `EventSinkRegistry`, failure facts, and observer links. The public addition is limited to severity/message/notifier values plus one registration helper; custom severity-map state stays private to the registered sink. | None. Removal-first review removed the public policy wrapper and generic facts bag, and bounded non-durable and evidence behavior. | Reconcile the linked manifest and phase plan with the reviewed surface. |
| Validation | Hermetic unit, contract, integration, and runnable-example coverage is sufficient. Existing external suites remain opt-in and no PR-gate policy changes. | None. | Keep causal coverage focused on commit, selection, bounded projection, failure, and evidence. |
| Detailed plan / approval | Two vertical phases are shaped. The maintainer approved the narrowed product scope in this planning request. | The pre-review manifest and Phase 2 plan still describe the removed policy wrapper/facts bag and add an unjustified notification-specific error type. | Reconcile linked artifacts, then run the manager quality gate. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `StageContext`, artifact specs, and store boundaries | Stages already receive `ArtifactRef` inputs and narrow load/save/register/path helpers. Direct mutable stores are intentionally hidden. | Preferred stage-author path and domain boundary. | FR-1, FR-3 |
| Local, subprocess, Docker, Apptainer, and SLURM execution | Stream paths and capture exist, but behavior differs: local capture is opt-in and incompatible with parallel execution, process executors capture child streams, and SLURM may have wrapper and Loom-stage logs. | Logging truth table and corrections. | FR-2, FR-3 |
| Runtime event model and runner/lifecycle emitters | Lifecycle events normally follow the corresponding durable lifecycle write. `run.preparation_failed` is a demonstrated exception at the evidence revision: a fresh run emits before its `FAILED` write, even though the feature spec says corresponding state changes precede events. Current emitted names also include cancellation and preparation failure that older prose omits. | Lifecycle catalog, Phase 1 ordering correction, and notification source. | FR-3 through FR-7 |
| `EventSinkRegistry`, `RuntimeEventDispatcher`, and observer facts | Explicit sinks run synchronously after event append/reference creation. The registry isolates callback failures and attempts to persist failure evidence; a successful callback may record an observer link, whose write can itself fail after the external effect. | Reuse instead of a second notification dispatcher or delivery log, without overstating evidence guarantees. | FR-4 through FR-7 |
| Plugin and Stage 28 plans | Event sinks are registry-ready; Stage 28 owns explicit CLI/plugin activation and exact registry subscriptions. | Keep Stage 26 Python-first and avoid conflicting filter ownership. | FR-5, FR-7, FR-10 |
| Examples and test harness | Captured-log and synthetic pipeline examples are hermetic and runnable; external container/SLURM suites already remain opt-in. | Simple code snippets, executable proof, and unchanged gates. | FR-8, FR-9 |
| Adjacent roadmap work | Stage 25 is queue-local; Stage 27 is GPU setup; Stage 28 is extension activation; Stage 29 is daemon/agent design. | Explicit deferrals and non-overlap. | FR-10 |

- User-visible outcome: a stage author can answer, from one short guide, where
  to write outputs and temporary files, how to return artifacts, what Loom does
  with stdout/stderr and Python logging, where logs are found, which lifecycle
  facts are authoritative, and how to attach a small notification adapter.
- Existing end-to-end path: stage returns `ArtifactRef` values -> executor
  captures supported streams -> runner commits lifecycle status/artifacts ->
  runner appends a lifecycle event -> event registry invokes explicit
  observe-only sinks -> failure or external-link evidence is attempted.
- Included scope: one downstream-operations guide with high-level examples;
  focused source/docs/test corrections for demonstrated current behavior;
  an authoritative lifecycle-event table; a service-neutral notification
  message, severity mapping, notifier protocol, and registration helper; one
  dependency-free runnable example; and proportional local validation.
- Non-goals and deferrals: generic or stage scheduling, cross-pool policy,
  resource-usage observation or sampling, resource recommendations, process
  reattachment, new resume/reuse semantics, validation-gate changes, new
  external acceptance profiles, service-specific adapters, asynchronous
  delivery, retries, cursors, outboxes, deduplication, guaranteed delivery,
  mutable/fatal hooks, and domain payload parsing.
- Current consumers, boundaries, or demonstrated failures: stage authors have
  working primitives but guidance is scattered; lifecycle-event prose omits
  currently emitted cancellation/preparation events; users can implement a raw
  event sink but must currently invent selection, severity, a bounded message
  shape, and observer-link handling themselves.
- Public or durable surfaces affected: one import-light
  `loom.pipeline.notifications` module plus a reusable module-level
  `loom.pipeline.events.validate_event_type` export. Neither is re-exported
  from the root `loom` facade. Event, event-reference, sink-failure,
  observer-link, run, stage, artifact, queue, resource, and resume schemas
  remain unchanged.

## Minimum Useful Change

- Smallest useful behavior: document and prove the existing operational
  path, then let a Python caller register a notifier that receives small,
  bounded lifecycle messages for selected exact event types.
- Closest existing capability and reuse decision: `EventSinkRegistry` remains
  the dispatcher, `PipelineEventRecord` remains the source fact,
  `EventSinkFailureRecord` remains failure evidence, and
  `EventObserverLinkRecord` remains the optional successful external link. No
  parallel notification registry, event type, or store is added.
- Why a new surface is required: a raw event sink is intentionally generic. A
  notification consumer still needs one shared default event-to-severity map,
  bounded projection, a service-neutral message, and correct failure/link
  integration. The helper snapshots an optional caller mapping; no separate
  public policy object is needed. Repeating the adapter rules in every
  Slack/email/webhook plugin would produce inconsistent lifecycle behavior.
- Explicitly deferred behavior: all provider SDKs and delivery guarantees.
  Project or plugin code owns credentials, network clients, provider payloads,
  and provider-specific response parsing.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | One guide shows managed object save, local file registration, temporary workspace use, input loading, and direct `ArtifactRef` returns. | No mutable store exposure, implicit outputs, remote writer API, or domain schemas. | Existing `StageContext` and artifact stores. | Runnable snippets and focused context contracts. | locked |
| FR-2 | Logging guidance distinguishes executor stdout/stderr, stage-owned file logging, tracebacks, queue-attempt logs, and SLURM wrapper logs across supported modes. | No log aggregation, remote streaming, structured logging framework, or new log path API. | Existing executors, CLI logs, stores, and examples. | Truth-table review plus local/subprocess examples and existing adapter tests. | locked |
| FR-3 | Canonical docs and examples match implemented public behavior; any reachable mismatch is fixed at its authoritative owner with the smallest compatible change. Fresh-run preparation failure must commit `FAILED` before emitting `run.preparation_failed`, restoring the existing feature-spec ordering rule without changing terminal open-existing status. | Documentation review cannot invent new behavior or broaden preparation-failure state semantics. | Source, tests, feature specs, glossary. | Targeted regression for each source change, including preparation ordering; link/snippet checks for docs. | locked |
| FR-4 | Add immutable, import-light notification severity/message values and a structural notifier protocol. | In-process handoff, not a policy model, durable message schema, or service client. | Pipeline events and plain-data vocabulary. | Package, validation, immutability, and plain projection tests. | locked |
| FR-5 | The helper's default severity map selects significant terminal/failure events and maps them to `info`, `warning`, or `error`; callers may supply another exact event-to-severity mapping, which the helper validates and snapshots. | No public policy wrapper, predicates, payload expressions, priorities, rate limits, or mutable routing. An empty supplied map is a valid no-op. Stage 28 still owns registry subscription filtering. | One event-name validator owned by `pipeline.events`. | Default/custom/empty/ignored/invalid cases. | locked |
| FR-6 | Notification messages have a closed field set and derive human-readable text only from an event-specific allowlist; they never copy arbitrary event payloads, exception/reason text, reason detail, config, commands, environment, log content, or artifact payloads. | There is no extensible `facts` bag. `EventReference` and optional stage identity include `run_uri`/project identifiers, so the message is bounded rather than audience-redacted; adapters own any further suppression. | Current event reference/record/resource shapes. | Exact `to_dict()` field-set and text tests with secret-like excluded payload values. | locked |
| FR-7 | A registration helper adapts a notifier into one named event sink. It delivers after the corresponding lifecycle commit when one exists, lets the registry isolate exceptions without failing the run, and attempts an observer link when the notifier returns an external reference. | Synchronous best-effort observation only; failure/link persistence can fail and no replay or delivery guarantee is claimed. | Registry, dispatcher, sink context, observer records. | Committed-state read, reference-only input, failure-continues, link identity, and no-run-mutation integration tests. | locked |
| FR-8 | Documentation and one dependency-free example explain notification setup with small Python snippets and show where service-specific code belongs. | No first-party Slack, Discord, email, webhook, or tracking adapter. | Example harness and public Python runner. | Runnable example asserts selected messages and failure isolation. | locked |
| FR-9 | Validation stays hermetic and uses existing package/unit/contract/integration/e2e layers. Existing external runtime suites remain opt-in and `make validate-pr`/`make test-summary` keep their current meanings. | No new PR gates, environment profiles, credentials, network, container, GPU, or cluster requirement. | Current harness. | Targeted commands followed by the unchanged repository gates during implementation. | locked |
| FR-10 | Scheduling, resources, resume, queue, plugin activation, and lifecycle ownership remain compatible and outside Stage 26 except for correcting inaccurate cross-references. | No hidden policy or schema expansion. | Adjacent accepted plans. | Public import/diff scope review and existing regression suites. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1 through FR-3 | Stage purpose | Treat correctness as alignment of existing behavior, tests, examples, and docs—not a bucket for new operational features. | Some attractive improvements remain deferred. | locked |
| FQ-2 | FR-2 | Log ownership | Loom owns executor-captured streams and their paths; project code owns its logging configuration and any separate files. A file that must be a durable pipeline output is declared and registered as an artifact. | Loom does not automatically discover arbitrary log files. | locked |
| FQ-3 | FR-4 through FR-7 | Notification base | Build on lifecycle events emitted after corresponding commits when they exist, and on observe-only sinks. | Delivery is synchronous and may add caller-visible latency. | locked |
| FQ-4 | FR-5 | Default signal | Notify run completion/failure/cancellation/preparation failure and stage failure/cancellation. Leave routine stage completion opt-in to avoid noise. | Some users will customize the map. | locked |
| FQ-5 | FR-6 | Message boundary | Use a closed message shape and finite allowlist, not generic recursive redaction or an extensible facts mapping. Treat run/stage identity as potentially audience-sensitive. | Messages contain less diagnostic detail; users follow the permitted identity to Loom logs and status, and adapters suppress identity for less-trusted audiences. | locked |
| FQ-6 | FR-7 | Failure policy | Existing best-effort sink behavior remains authoritative: construct a failure result, attempt its durable write, continue later observers, and never change run correctness. | No alert-delivery or failure-evidence guarantee. | locked |
| FQ-7 | FR-7, FR-8 | Activation | Stage 26 is Python-first. Stage 28 separately owns exact plugin/CLI activation and registry subscriptions. | CLI notification selection arrives only through the accepted Stage 28 path. | locked |
| FQ-8 | FR-9, FR-10 | Deferred former scope | Remove usage sampling; defer scheduler, reuse, acceptance-profile/gate, and other former Stage 26 topics without replacement machinery. | The roadmap no longer assigns those capabilities to Stage 26. | locked |

## Behavior Baseline

- Included and default behavior: no notifier means no notification work or
  discovery. Registering one notifier uses the default exact event/severity map
  unless the caller supplies another mapping, which is copied at registration.
  An explicitly empty mapping performs no calls. `run.completed` is `info`;
  `run.cancelled` and `stage.cancelled` are `warning`; preparation, run, and
  stage failures are `error`.
- Input-shape behavior: durable `PipelineEventRecord` inputs may contribute
  finite allowlisted detail and stage identity. A non-durable `EventReference`
  produces an identity-only message with no reconstructed stage or payload
  detail; the adapter never reaches through the sink context to query stores.
- Failure and unsupported behavior: malformed custom maps, messages, or
  provider results fail validation. Callback exceptions produce a registry
  failure result and a best-effort persisted sink-failure fact. Other sinks and
  the run continue. Provider retries, async queues, authentication, timeouts,
  and network policy are adapter responsibilities.
- Reproducibility and durable behavior: notification mappings and messages are
  in-process values. The triggering event stays durable by default; sink
  failures and returned external references reuse existing durable observer
  facts when their writes succeed. A notification can be sent and the process
  can die or a link write can fail before recording its external reference, so
  exactly-once or at-least-once delivery is not claimed.
- Explicit deferrals: no generic scheduler, resource sampler, new resume mode,
  PR-gate/profile change, service adapter, notification replay, or payload
  predicate.

## Minimum Design

- Modules and ownership:
  - `loom.pipeline.notifications` owns notification values, event projection,
    the private default severity map, notifier protocol, and notifier
    registration.
  - `loom.pipeline.events` continues to own event identity and validation.
  - `loom.pipeline.event_sinks` continues to own dispatch order, callback
    failure capture, registry identity, and observer-link context.
  - runner/lifecycle/store code continues to own authoritative state commits
    and event emission. Notification code never writes lifecycle state.
  - project/plugins own service clients, credentials, provider formatting, and
    provider response semantics.
- Fixed public, durable, trust-boundary, and cross-phase contracts:
  - `NotificationSeverity` is a `StrEnum` with `INFO = "info"`,
    `WARNING = "warning"`, and `ERROR = "error"`.
  - `NotificationMessage` is a frozen, slotted in-process value with
    `event_reference`, `severity`, `title`, `body`, and optional `stage_name`.
    `to_dict()` provides exactly those adapter-ready plain fields; there is no
    generic facts mapping, schema version, or `from_dict()` because Loom does
    not persist or reconstruct messages. Title/body are presentation text, not
    machine-readable policy inputs.
  - `validate_event_type(value: object) -> str` is the events module's single
    dotted-name validator for event construction, notification-map
    normalization, and later Stage 28 subscriptions. It is intentional in
    `loom.pipeline.events.__all__` but not a root convenience export.
  - There is no notification-specific error hierarchy. Event-name failures use
    the authoritative event validation error; ordinary type/value failures at
    message, notifier, and result boundaries use normal `TypeError` or
    `ValueError` behavior.
  - `Notifier` is a structural protocol with
    `notify(message: NotificationMessage) -> EventObserverExternalRef | None`.
    Returning a reference asks Loom to append the existing observer-link fact;
    `None` means the provider supplied no durable external identity.
  - `register_lifecycle_notifier(registry, *, name, notifier,
    severities: Mapping[str, NotificationSeverity] | None = None) -> None`
    validates once, snapshots the supplied mapping (or uses the private six-
    event default), and registers one ordinary event sink under `name`.
    Event-name syntax delegates to `validate_event_type`; notification code
    does not clone its regex. The helper requires a callable `notifier.notify`,
    accepts only `None` or an `EventObserverExternalRef` result, and owns the
    same name used for any observer link, avoiding a second caller-supplied
    identity. It does not mutate global state.
  - Event, failure, observer-link, run, stage, config, and plugin activation
    schemas do not change. Stage 28 registry subscriptions remain a dispatch
    optimization/activation contract; Stage 26 severity mapping decides which
    events become notification messages even when an observe-all registry
    invokes it.
- Data and control flow:
  1. Runner/lifecycle commits the corresponding status, outputs, or failure
     when that event represents a state change; Phase 1 restores this order for
     fresh-run preparation failure.
  2. Existing dispatcher appends or references the event.
  3. Existing registry calls the registered notification sink.
  4. The captured severity map either ignores the exact event type or selects a
     severity.
  5. Projector builds a small message from event identity/resource. For a full
     record it may use only: the primary stage resource; `failed_stage` for
     `run.failed`; `cancelled_stage` for `run.cancelled`; `failure_type` for
     run/stage failure; `error_type` for preparation failure; `attempt` for
     stage failure/cancellation; and nested reason `code` for cancellation.
     These values may form title/body or optional `stage_name` but are never
     exposed as a generic mapping. Missing or wrong-shaped optional values are
     omitted rather than recursively copied. Custom-selected event types get
     generic event-identity text unless explicitly listed above. Reference-
     only events stay identity-only.
  6. Notifier performs its external side effect.
  7. A returned external reference is validated and the helper attempts an
     observer link. An exception becomes a registry failure and a best-effort
     sink-failure write; neither changes the run.
- Private implementation discretion: exact projector helper names, title/body
  wording, internal immutable mapping construction, clock injection for tests,
  and whether the registered sink is a closure or private class.
- Extension and compatibility seams: existing user-written `EventSink`
  implementations continue to work. A Stage 28 plugin can construct/register
  the notification sink through its accepted activation path without changing
  notification message semantics.
- Import and dependency direction: notifications may import event and event-
  sink contracts plus serialization/timestamp primitives. Event, sink, runner,
  store, CLI, and root modules do not import a provider SDK. No dependency is
  added.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| One downstream-operations guide | Current stage-author/logging questions span many specs. | Add more scattered paragraphs. | keep one canonical guide |
| `NotificationMessage` | Provider adapters need one bounded, service-neutral handoff. | Pass raw event records to every provider. | keep; in-process only |
| Severity enum and exact mapping | Current requirement includes severity with useful defaults and Python customization. | Hard-code every event or let adapters disagree. | keep the enum; normalize one mapping privately in the helper |
| Public policy value | The helper only needs a validated snapshot at registration; no independent consumer persists, composes, or passes policy objects. | Accept a normal mapping and close over an immutable copy. | remove |
| Notification-specific error type | No caller needs to distinguish notification validation from the existing event/type/value boundaries. | Reuse the authoritative event error and normal type/value errors. | remove |
| `Notifier` protocol | Separates Loom projection/lifecycle from provider delivery. | Require every provider to implement full `EventSink`. | keep structural method only |
| Registration helper | Must bind registry name to failure/link evidence correctly. | Ask callers to duplicate names in a custom sink. | keep one helper |
| Extensible message `facts` mapping | No current provider or durable consumer needs a second semi-structured payload, and it weakens the allowlist boundary. | Put finite bounded context in human-readable title/body and optional stage identity. | remove |
| Notification delivery/result schema | Existing failure/link facts already cover available evidence. | Add receipt/outbox records. | remove |
| Generic redactor/template engine | Allowlisted lifecycle fields meet the current safety need. | Support arbitrary payload templates. | remove |
| Built-in service adapter | No selected provider or dependency reason. | Choose Slack/webhook now. | defer |
| Usage sampler/scheduler/resume/gate work | Maintainer explicitly removed it from this stage. | Retain roadmap placeholders. | remove/defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1 through FR-3 | Documentation owner | New downstream guide owns the simple journey; feature specs retain detailed contracts and link to it. | One additional top-level doc. | locked |
| DQ-2 | FR-2 | Logging correction rule | Test/fix only reachable mismatches; document executor differences rather than normalizing them behind new APIs. | Backend behavior remains intentionally different. | locked |
| DQ-3 | FR-4, FR-7 | Architecture | Notifications are an adapter over the event registry, not a dispatcher/store subsystem. | Inherits synchronous best-effort semantics. | locked |
| DQ-4 | FR-4, FR-6 | Message durability | Message is immutable/plain-projectable but not durable or reconstructable, and carries no extensible facts bag. | Re-delivery must rebuild from a durable event in later work. | locked |
| DQ-5 | FR-5 | Filtering owner | The helper's captured severity map owns notification semantics; Stage 28 event registry owns whether a callback is invoked for an exact subscription. | The notifier sink may receive-and-ignore events before Stage 28. | locked |
| DQ-6 | FR-6 | Projection boundary | Form text only from finite event-specific fields. Never accept a facts bag, payload template, raw-payload passthrough, or audience-safety claim in Stage 26. | Less custom content; identity may still require adapter-side suppression. | locked |
| DQ-7 | FR-7 | Observer evidence | Reuse best-effort sink-failure and optional external-ref writes; do not promise a delivery receipt when a provider returns none or evidence persistence fails. | Successful delivery may have no durable success link, and a failure fact may itself be unavailable. | locked with accepted risk |
| DQ-8 | FR-8 through FR-10 | Delivery and validation scope | Python-first, dependency-free proof; no network adapter or gate change. | Provider integration is demonstrated as project code rather than tested live. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| EDR-1: extra public value/error surfaces are not justified | FR-4 through FR-6; DQ-4 through DQ-6 | No current consumer persists, composes, or independently exchanges a policy object; no selected provider needs a second semi-structured payload; and the linked Phase 2 draft adds a notification error class with no distinct recovery path. These additions enlarge compatibility and disclosure surfaces beyond the required Python registration path. | Accept and snapshot a normal exact event-to-severity mapping in the helper. Remove `LifecycleNotificationPolicy`, `NotificationMessage.facts`, and a dedicated `NotificationError`; keep finite context in title/body and optional stage identity, with existing event/type/value errors. | resolved: removed |
| EDR-2: preparation failure violates the claimed commit ordering | FR-3, FR-7; DQ-3 | At revision `314e418`, `_record_preparation_failure` emits `run.preparation_failed` before a fresh run's `FAILED` write, contrary to the existing execution-spec rule. A notifier could observe stale `CREATED` state. | Phase 1 must write the fresh-run `FAILED` state before emitting the event while preserving the current rule that a terminal open-existing run is not reset. Phase 2 claims a preceding lifecycle commit only where a corresponding state change exists. | resolved in minimum design; implementation required in Phase 1 |
| EDR-3: the sink contract also supplies reference-only events | FR-6, FR-7 | `event_persistence="non_durable"` dispatches `EventReference`, which has no resource scope or payload. Requiring stage/failure facts would invent data or force a store read through an intentionally narrow context. | Support reference-only messages with event identity, severity, and generic text; leave `stage_name` absent and do not reconstruct payload detail. Add focused coverage instead of changing event schemas. | resolved |
| EDR-4: "safe/redacted" and durable-evidence wording overclaims | FR-6, FR-7; FQ-5, FQ-6 | `EventReference` includes `run_uri`, stage identifiers can be project-sensitive, external-ref identifiers are adapter-authored, and the registry swallows failure-recorder errors to preserve run correctness. | Describe messages as closed/bounded, require adapters to suppress identity and return only safe external identifiers for their audience, and describe failure/link persistence as best-effort. | resolved |
| EDR-5: event-name validation must have one owner | FR-5; DQ-5 | The evidence revision keeps event-name validation private in `pipeline.events`; cloning the dotted-name regex in notifications would duplicate an invariant that Stage 28 subscriptions also need. | Make the events module's validator reusable and call it from notification-map normalization. Do not add a second notification grammar or a root-level convenience export. | resolved |
| EDR-6: remaining adapter surface is proportionate | FR-4 through FR-7; DQ-3 through DQ-8 | Severity/message values, one structural notifier method, and the registration helper each have a current role in the selected Python path. They remain domain-neutral, import-light, in-process, and compose with the existing registry/failure/link owners. | Keep only those surfaces; retain all delivery, provider, scheduling, sampling, resume, gate/profile, and service-adapter deferrals. | pass |

## Examples And Validation

Preferred managed-object output:

```python
def run(self, context, inputs):
    summary = {"count": len(inputs)}
    return {
        "summary": context.save_artifact(
            "summary",
            summary,
            artifact_type="json",
            codec_key="json.v1",
        )
    }
```

Preferred local-file output and temporary workspace:

```python
def run(self, context, inputs):
    scratch = context.local_workspace_path("parts", "part-0001.tmp")
    build_part(scratch)  # temporary/intermediate unless explicitly registered

    model_path = context.local_output_path("model", suffix=".bin")
    build_model(model_path)
    return {
        "model": context.register_local_artifact(
            "model", model_path, artifact_type="model"
        )
    }
```

Notification setup remains ordinary explicit Python composition:

```python
class ProjectNotifier:
    def __init__(self, client):
        self.client = client

    def notify(self, message):
        response = self.client.send(message.to_dict())
        return EventObserverExternalRef(
            kind="project_notification",
            identifiers={"message_id": response.message_id},
        )

registry = EventSinkRegistry()
register_lifecycle_notifier(
    registry,
    name="notifications.project",
    notifier=ProjectNotifier(client),
)

result = runner.run(
    RunRequest(
        config=composed,
        run_uri=run_uri,
        event_sink_registry=registry,
    )
)
```

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Managed save versus file registration | Returned output is a declared `ArtifactRef`; workspace files are not implicit outputs. | `StageContext`/artifact store. | Contract plus runnable stage snippet. | planned |
| Stream/log truth | Local pass-through/capture, subprocess/container child streams, Python handlers, queue logs, and SLURM wrapper/stage logs are described without overclaim. | Executor/store/SLURM manifest. | Existing tests plus focused local/subprocess example assertions. | planned |
| Lifecycle catalog | Docs include every currently emitted run/stage lifecycle name and commit ordering. | Runner/lifecycle/events. | Focused source audit and integration event sequence. | planned |
| Default notification selection | Routine events and `stage.completed` do not notify; the six default significant events do. | Notification severity map. | Exact unit table. | planned |
| Bounded message | Secret-like arbitrary payload values never enter message fields or text; identity exposure is explicit. | Notification projector and downstream adapter trust boundary. | Exact `to_dict()` field-set/text unit tests. | planned |
| Committed observation | Notifier handling `stage.failed`/`run.completed`, and fresh-run `run.preparation_failed` after Phase 1, can read matching committed state. | Runner/store then dispatcher. | One integration case per causally distinct stage/run/preparation boundary. | planned |
| Reference-only observation | Non-durable `EventReference` produces a useful generic message without invented stage/payload detail. | Dispatcher then notification projector. | Focused unit or existing non-durable integration extension. | planned |
| Failure isolation | Raising notifier creates a failure result and best-effort failure fact, later sink runs, and final run result is unchanged. | Existing registry. | Reuse/extend event-sink integration test. | planned |
| External link | Returned provider reference records one link with matching sink/event identity. | Registration helper/context/store. | Integration round trip. | planned |
| No provider | Dependency-free fake notifier proves the public path; no network is used. | Example harness. | Runnable e2e/example test. | planned |

Causal interactions requiring combined coverage:

- committed lifecycle state + notification projection + callback observation;
- durable record versus reference-only input + bounded projection;
- notifier exception + failure persistence + later observer/run success; and
- returned external reference + helper-owned sink identity + observer-link
  persistence.

Everything else stays in focused unit, package, docs, or existing executor
tests rather than a backend Cartesian matrix.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Stage-author correctness and logging | One simple downstream guide, corrected stage/artifact/log/event documentation, small runnable snippets, and only demonstrated compatibility fixes. | Docs/examples plus current authoritative owners; no notification API, new log API, scheduler, resource sampler, resume, or gate work. | Current `develop`; preserve Stage 27-29 dirty work. | Stage output/workspace and logging examples are truthful; lifecycle catalog matches source; fresh preparation failure is committed before observation; targeted tests and docs checks pass. | pending |
| 2. Generic lifecycle notifications | Public notification severity/message/protocol/helper, private captured severity mapping, observer failure/link integration, dependency-free example, and final docs. | `loom.pipeline.notifications` over existing events/sinks; no public policy object, facts bag, provider SDK, plugin activation change, outbox/retry, or new durable schema. | Phase 1 merged so source/docs event truth is settled; Stage 28 exact-filter ownership unchanged. | Selected events produce bounded messages for record/reference inputs; ignored events do nothing; failures do not alter runs; external refs link correctly when persistence succeeds; full gate passes. | pending |

Two phases keep correction work from being hidden inside a feature PR. Phase 1
is independently useful to every stage author. Phase 2 adds exactly one feature
over the corrected and documented lifecycle path.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Maintainer narrowed scope; FR/FQ rows cover outputs, logs, correctness, notifications, and explicit deferrals. | pass |
| Minimum design justified | Existing event/sink/failure/link path is reused; public policy/facts abstractions and parallel dispatcher/store/provider code are absent. | pass |
| Complexity delta proportionate | Policy object, facts bag, delivery schema, templates, redactor engine, provider adapter, scheduler, sampler, resume, and gate machinery are removed/deferred. | pass |
| Contracts and private discretion clear | Public in-process shapes, reference-only behavior, trust boundary, and ownership are fixed; presentation wording/helpers remain private. | pass |
| Invariant ownership and validation proportionate | Four causal interactions; event-name validation has one owner; no backend matrix or external environment requirement. | pass |
| Phases vertical and reviewable | Correction/guidance first, one notification feature second. | pass |
| No unresolved blocker | No product blocker remains; linked artifacts require mechanical reconciliation with the reviewed design. | pass |

Gate result: expanded design review passed with the corrections in EDR-1
through EDR-5 and no blocker. Planning is not ready for implementation until
the linked manifest/phase plan are reconciled and the manager quality gate
passes.

Accepted risks and revisit triggers:

- Synchronous notifiers can add latency. Revisit only with measured impact and
  an accepted async delivery requirement.
- A provider can deliver successfully and fail before returning/recording its
  external reference. Revisit only with an accepted at-least-once/idempotency
  contract; do not infer delivery from absence of failure.
- A notifier exception message and returned external-reference identifiers are
  adapter-authored inputs to existing durable observer facts. Project adapters
  must avoid credentials or sensitive payloads in both; Stage 26 adds no
  generic scrubber.
- `run_uri` can contain a local path. It remains the canonical run identity;
  adapters that send to a less trusted audience may replace its presentation,
  but Loom does not add a second run identifier here.
- Stage 28 activation is sequenced separately. Stage 26 Python usage remains
  useful without it.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Stage theme | Operational correctness, simple guidance, logging truth, and generic notifications only. | Direct maintainer decision. | New stage proposal, not Stage 26 scope growth. |
| Artifacts/workspace | Use current `StageContext` facade and explicit returned refs. | Existing invariant owner is sufficient. | A non-local writer consumer needs a public boundary. |
| Logging | Document existing executor differences; separate project file logging from captured streams. | A uniform logging framework is not required. | Demonstrated cross-executor correctness failure. |
| Notification transport | Project/plugin notifier behind a structural protocol. | Keeps Loom service-neutral and dependency-light. | A provider is explicitly selected for first-party support. |
| Filtering | Exact event-to-severity mapping is captured by the helper; Stage 28 retains registry subscription ownership. | Avoid a public policy wrapper and conflicting dispatcher contracts. | Stage 28 contract changes before implementation. |
| Delivery guarantee | Synchronous best-effort with attempted failure/link facts. | Matches existing observe-only contract and requires no durable machinery. | Accepted at-least-once requirement with idempotency design. |
| Generic scheduling | Deferred beyond Stage 26. | No current Stage 26 consumer; separate ownership decisions required. | Dedicated planning request. |
| Resume/reuse semantics | Existing behavior remains; new semantics deferred beyond Stage 26. | Maintainer explicitly removed it. | Dedicated accepted requirement. |
| Resource usage | Sampler/observation records and allocation-versus-usage policy removed from the roadmap stage. | No current sampler consumer and maintainer explicitly removed it. | Dedicated evidence-backed stage. |
| Acceptance profiles and PR gates | No new profiles or gate changes. Existing opt-in suites remain documented as current behavior. | External environments are not reliable default prerequisites. | Dedicated validation-stage decision. |
| Service adapters | Slack, Discord, email, webhook, and tracking adapters remain downstream/plugins. | Avoid credentials, SDKs, and provider policy in core. | Selected adapter with an explicit dependency/design reason. |
| Domain content | No metrics/checkpoints/artifact/log payload parsing in core. | Loom remains domain-neutral. | Never without a new generic contract and consumer. |
