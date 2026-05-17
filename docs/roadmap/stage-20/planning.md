# Roadmap Stage 20 Planning: Runtime Events And Event Sinks

## Metadata

- Roadmap stage: v20
- Source roadmap: `docs/roadmap.md`
- Previous version status:
  - `docs/roadmap/stage-19/planning.md` exists in the current checkout and
    records Stage 19 ready for implementation-plan drafting.
  - `docs/roadmap/stage-19/implementation-plan.md` exists in the current
    checkout and records Stage 19 approved for Phase 1 execution planning.
  - Stage 19 files are currently untracked local planning artifacts in this
    checkout, so this Stage 20 planning pass treats them as current local
    context without modifying them.
- Planning artifact status: approved for implementation-plan drafting
- Current discussion stage: implementation-plan drafting
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Capability triage and candidate functional requirements: confirmed
  - Functionality agreement review: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: confirmed
  - Design agreement review: confirmed
  - Design safety review: passed
  - Examples and validation strategy: confirmed
  - Phase shaping: confirmed
  - Implementation readiness: confirmed
  - Handoff: confirmed
- Related implementation plan: `docs/roadmap/stage-20/implementation-plan.md`
- Related feature docs:
  - `docs/features/reliability.md`
  - `docs/features/execution.md`
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/preflight.md`
  - `docs/features/plugins.md`
  - `docs/features/cli.md`
  - `docs/features/provenance.md`
  - `docs/features/testing.md`
- Blockers:
  - None. Final planning confirmation received on 2026-05-17.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` v20 | Stage 20 adds audit-ready runtime event records and observe-only event sink contracts over committed Loom facts. | roadmap scope | Core objective is inspectable events and observer contracts, not execution control. |
| `docs/roadmap.md` v20 | Events cover run and stage lifecycle, submission events, retry decisions, timeout outcomes, stage-attempt transaction transitions, and plugin callback hooks. | event coverage | Stage 19 reliability records should be input facts for Stage 20 emission. |
| `docs/roadmap.md` v20 | Structured event grammar includes event id, sequence, occurred timestamp, event name, primary resource, related resources, payload, and optional causal predecessor. | record shape | Current `PipelineEventRecord` is narrower and should be compatibility input rather than silently replaced. |
| `docs/roadmap.md` v20 | Local `events.jsonl` remains append-only and machine-readable. | persistence | Stage 20 should keep local audit logs inspectable without project code imports. |
| `docs/roadmap.md` v20 | Existing local event records and readers need explicit compatibility or versioning behavior. | migration and compatibility | Current schema version is 1 in `src/loom/pipeline/events.py`. |
| `docs/roadmap.md` v20 | Payloads should include stable metadata for external projections: run URI, stage name, status, timestamps, executor, artifact refs, fingerprints, submitted-operation IDs, retry/timeout decisions, transaction IDs, and selected provenance facts. | payload scope | Payloads must stay generic and plain-data-compatible. |
| `docs/roadmap.md` v20 | `EventSink` and `EventSinkRegistry` are observe-only callbacks over committed runtime facts. | public contract scope | Sinks may write external side effects or explicit metadata links, but cannot mutate core execution state. |
| `docs/roadmap.md` v20 | Programmatic event sink registration comes first; plugin-discovered loading follows after v14 plugin surfaces and the registry are stable. | phase ordering | Avoids coupling event registry design to entry point loading too early. |
| `docs/roadmap.md` v20 | Callback failures are visible and best-effort by default; strict audit failure is deferred. | failure policy | Default observer errors must not change run correctness. |
| `docs/roadmap.md` v20 | Preflight warnings and CLI inspection are in scope where useful. | diagnostics and CLI | These should read explicit capabilities and records, not infer from logs. |
| `docs/roadmap.md` v20 | Cleanup, deletion, retention, full run-collection GC, service-specific sinks, distributed streaming, strict audit mode, cross-run retry budgets, and resource-aware retry escalation are deferred. | scope boundary | Stage 21 owns cleanup and retention. Service delivery belongs to plugins or external wrappers. |
| `docs/roadmap.md` module table | `reliability.md`, `run-store.md`, `provenance.md`, `preflight.md`, `plugins.md`, and `cli.md` all list v20 involvement. | feature-doc routing | Stage 20 crosses records, stores, provenance, plugin discovery, diagnostics, and presentation. |
| `docs/features/reliability.md` | Current event foundation is local `events.jsonl`; callback hooks and plugin-discovered event sinks are deferred. | prerequisite gap | Stage 20 is the deferred event hook and sink stage. |
| `docs/features/reliability.md` | Event sink callbacks receive committed runtime facts and must not mutate plans, configs, artifacts, stage outputs, status transitions, retry decisions, or store records. | observer boundary | This is the central correctness constraint for Stage 20. |
| `docs/features/reliability.md` | Event records are plain-data mappings; local stores allocate contiguous per-run sequence numbers and append JSON lines to `<run_dir>/events.jsonl`. | local persistence | Current implementation already has the foundation but not the full Stage 20 grammar. |
| `docs/features/reliability.md` | When future event sinks are configured, event persistence should be enabled by default unless explicitly disabled. | default policy candidate | Needs behavior confirmation because it affects runtime defaults and volume. |
| `docs/features/run-store.md` | `RunEventStore` exposes `append_event` and `read_events`; event records are audit facts, not current state. | store contract | Stage 20 should preserve authority/store truth as the lifecycle source. |
| `docs/features/provenance.md` | Future event streams should be generic plain data; notification backends belong outside core. | provenance and payload boundary | Supports selected provenance facts without domain interpretation or service clients. |
| `docs/features/plugins.md` | Event sink plugin loading discovers and loads sinks, while reliability and execution define events, persistence, and callback failure policy. | plugin boundary | Plugin layer should not own event semantics. |
| `docs/features/plugins.md` | Programmatic registry registration should exist before entry point loading, with instance-local deterministic tests. | registry default | Supports a programmatic-first implementation shape. |
| `docs/features/plugins.md` | `loom.event_sinks` is listing-only until runtime event models and registry contracts land. | plugin readiness | Stage 20 can promote this group after registry semantics stabilize. |
| `docs/features/plugins.md` | Entry point names should win for event sinks unless registry explicit names are introduced. | naming policy candidate | This can likely be a recorded recommendation during design agreement. |
| `docs/features/cli.md` | Operational commands should wait for underlying APIs; cleanup/export commands should operate through stores. | CLI scope | Stage 20 event inspection should stay read-only over event APIs. |
| `docs/loom.md` | Loom is generic runtime scaffolding; external observers are a design goal, but service-specific behavior is a non-goal. | domain neutrality | Core event contracts must not embed MLflow, W&B, Slack, metrics, or project semantics. |
| `docs/structure.md` | `pipeline/events.py` owns strict pipeline event records; execution emits local lifecycle events; plugins are discovery only. | source boundary | Stage 20 likely updates pipeline, stores, execution, plugins, diagnostics, and CLI without moving semantics into plugins. |
| `docs/GLOSSARY.md` | `run_uri`, `RunStore`, authority, status, artifact refs, fingerprint, and provenance have preferred meanings. | vocabulary | Planning should preserve authority-backed state as source of truth and event records as audit facts. |
| `src/loom/pipeline/events.py` | Existing event model has `EventScope`, `PipelineEvent`, and `PipelineEventRecord` with schema version, run URI, sequence, timestamp, scope, event type, and payload. | current implementation | Stage 20 must decide compatibility/versioning for richer grammar. |
| `src/loom/pipeline/execution/eventing.py` | Current helpers emit run and stage events through `RunEventStore`. | emission foundation | Emission is local lifecycle-focused and lacks sink dispatch. |
| `src/loom/pipeline/stores/run_store.py` | `RunEventStore` is a runtime-checkable protocol. | store interface | A richer event path should remain store-backed and fakeable. |
| `src/loom/plugins/entrypoints.py` | `LOOM_EVENT_SINKS_GROUP` exists as a known plugin group. | plugin foundation | Listing exists; loading is not exported yet. |
| `tests/contracts/test_plugin_future_groups_contract.py` | Future plugin groups, including event sinks, are listing-only and do not export loaders. | compatibility test | Stage 20 will need deliberate contract updates when enabling loader behavior. |
| `docs/roadmap/stage-19/planning.md` | Stage 19 explicitly defers event grammar, event sinks, callback failures, plugin loading, and event-driven external actions to Stage 20. | predecessor boundary | Stage 20 should project committed Stage 19 facts rather than redefine reliability semantics. |
| `docs/roadmap/stage-19/implementation-plan.md` | Stage 19 records stable IDs, timestamps, reason codes, transaction IDs, and causal links for Stage 20 event projection. | predecessor dependency | Stage 20 can consume these identifiers once implemented. |
| `docs/roadmap.md` v21 | Stage 21 owns cleanup, retention metadata, explicit deletion, and run-collection GC. | successor boundary | Stage 20 should not implement cleanup operations, even if it emits cleanup-related events later. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Workflow and templates | `.codex/workflows/roadmap-stage-planning.md`, `.codex/prompts/roadmap-stage-planning-facilitate.md`, `.codex/prompts/roadmap-stage-functionality-agreement.md`, `.codex/prompts/roadmap-stage-design-agreement.md`, `.codex/prompts/roadmap-stage-design-safety-review.md`, `.codex/templates/roadmap-stage-planning.md` | Workflow requires confirmed functionality/behavior before design agreement and design-safety review. Design-agreement and design-safety prompts were reloaded for the resumed pass. | Final planning confirmation remains before implementation-plan drafting. |
| Roadmap docs | `docs/roadmap.md` v20-v21 and module coverage table | v20 is runtime events and event sinks; v21 is cleanup and retention. | Stage 20 implementation plan does not exist yet. |
| Feature docs | `reliability.md`, `run-store.md`, `plugins.md`, `provenance.md`, `cli.md` focused event sections plus roadmap-linked docs list | Feature docs support an observe-only sink boundary, programmatic-first registry, local append-only event persistence, metadata-only plugin listing, and read-only inspection. | Exact event grammar and compatibility policy remain planning decisions. |
| Source and tests | `src/loom/pipeline/events.py`, `src/loom/pipeline/execution/eventing.py`, `src/loom/pipeline/execution/runner.py`, `src/loom/pipeline/execution/lifecycle.py`, `src/loom/pipeline/stores/run_store.py`, `src/loom/pipeline/stores/local_runs.py`, `src/loom/pipeline/stores/sqlite_authority.py`, `src/loom/pipeline/stores/service_authority.py`, `src/loom/pipeline/execution/authority_adapter.py`, `src/loom/plugins/entrypoints.py`, plugin adapter modules, event-related contract/unit/integration tests by `rg` | Current source has schema-v1 event records, run/stage scopes, append/read store protocol, local and authority event persistence, runner/lifecycle emission points, existing plugin adapter patterns, and listing-only `loom.event_sinks` plugin group. | Design-safety review should challenge event schema compatibility, dispatch ordering, and sink-module scope. |
| Prior or adjacent plans | `docs/roadmap/stage-19/planning.md`, `docs/roadmap/stage-19/implementation-plan.md`, `docs/roadmap.md` v21 | Stage 19 is the predecessor that should create reliability facts; Stage 21 consumes cleanup/retention facts later. | Stage 19 implementation is not yet merged in this checkout, so Stage 20 planning must define dependencies on Stage 19 outputs without assuming exact implementation details beyond the approved plan. |

## Roadmap Extraction

Baseline roadmap outcome:

- Add a structured, audit-ready runtime event grammar over committed Loom facts.
- Preserve append-only, machine-readable local event persistence while defining
  compatibility or versioning for existing schema-v1 local events.
- Add observe-only `EventSink` and `EventSinkRegistry` contracts.
- Dispatch event sinks only after the corresponding durable runtime fact exists.
- Record callback failures and continue by default.
- Enable programmatic event sink registration before plugin-discovered loading.
- Load `loom.event_sinks` plugins explicitly after the registry is stable.
- Add useful preflight diagnostics and read-only CLI inspection for event
  persistence and sink behavior.

Prerequisites:

- Existing local event model, event persistence, and event emission helpers.
- Authority-backed run-store and local store event/audit foundations.
- Stage 14 plugin discovery and listing-only future group contracts.
- Stage 19 reliability, retry, timeout, transaction, and failure facts, or
  explicit compatibility assumptions if Stage 20 planning continues before
  Stage 19 implementation is complete.

Primary feature docs:

- `reliability.md`
- `execution.md`
- `run-store.md`
- `state.md`
- `preflight.md`
- `plugins.md`
- `cli.md`
- `provenance.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Cleanup and deletion operations.
- Artifact retention enforcement and full run-collection garbage collection.
- Service-specific notification or tracking sinks such as MLflow, W&B, Slack,
  email, Teams, PagerDuty, webhooks, hosted telemetry, or OpenTelemetry clients.
- Distributed event streaming.
- Strict audit-failure mode that can fail runs when observer callbacks fail.
- Retry budgets across runs.
- Resource-aware retry escalation.
- Event-driven mutation of plans, configs, artifacts, status, retry decisions,
  transaction records, or core store records.
- Domain-specific metric extraction or project-specific tracking semantics.

Future-roadmap touchpoints:

- Stage 21 can consume event records that describe cleanup candidates or cleanup
  outcomes later, but Stage 20 should not perform cleanup or deletion.
- Service-specific notification and tracking plugins can consume Stage 20
  records and sink contracts later without core runtime dependencies.
- Future distributed tracing or event streaming should adapt from the Stage 20
  event contract, not replace authority/store lifecycle truth.
- Future retention, export/import, catalog, and provenance work can consume
  event records as audit facts and selected provenance summaries.

Compatibility obligations:

- Existing `PipelineEventRecord` schema-v1 readers and local `events.jsonl`
  files need a deliberate support or migration path.
- Event records remain plain-data-compatible and useful without importing
  downstream project code.
- Event logs remain audit facts, not the source of current run or stage status.
- Sinks are trusted project/plugin code but observe-only with respect to Loom
  lifecycle correctness.
- Default installation must not add service-specific or heavyweight
  notification, telemetry, cloud, or streaming dependencies.
- Default test coverage should remain local, fake, deterministic, and
  network-free.

## Stage Briefing

What this stage is:

- Stage 20 turns Loom's existing local lifecycle event foundation into an
  audit-ready runtime event system and introduces event sink contracts for
  external observers.
- The stage is not about adding notification services. It defines the generic
  record grammar, persistence compatibility, observe-only callback boundary,
  callback failure records, explicit plugin-loading path, diagnostics, and
  read-only inspection surfaces that later plugins can consume.

Why this stage exists:

- Current Loom already has `PipelineEvent`, `PipelineEventRecord`,
  `RunEventStore`, local `events.jsonl`, lifecycle emission helpers, and
  authority audit-event foundations.
- Those foundations are useful but too narrow for the roadmap's future
  observers because the current record shape lacks a first-class event id,
  primary and related resources, causal predecessor links, richer payload
  conventions, sink-dispatch policy, and callback failure records.
- Stage 19 reliability and transaction planning intentionally made retry,
  timeout, failure, transaction, and causal facts event-ready without defining
  the event grammar or observer contracts. Stage 20 is the point where those
  committed facts become structured runtime events.

Impacted or linked work:

- `loom.pipeline.events` likely needs versioned event record evolution or a new
  adjacent runtime event record that can project existing schema-v1 records.
- `loom.pipeline.execution` likely needs emission points that fire after
  durable lifecycle, submission, retry, timeout, and transaction facts are
  recorded.
- `loom.pipeline.stores` and authority/local implementations likely need
  compatibility-aware event append/read behavior and callback failure record
  persistence.
- `loom.plugins` can move the `loom.event_sinks` group from listing-only toward
  explicit loading after the registry contract exists.
- `loom.diagnostics`, preflight, and CLI may add read-only warnings or
  inspection over event persistence and sink registration.
- `loom.provenance` may receive selected event and sink facts, while preserving
  its role as factual context rather than policy.

Likely public surfaces and durable artifacts:

- Versioned event record data structures or adapters for the richer runtime
  event grammar.
- Event name and resource vocabulary that is stable enough for audit logs and
  plugins.
- `EventSink` and `EventSinkRegistry` contracts.
- Programmatic sink registration API.
- Explicit plugin loader for `loom.event_sinks`, probably adapting from the
  existing plugin discovery helpers.
- Callback failure records.
- Local `events.jsonl` compatibility behavior.
- Read-only event inspection or preflight output where useful.

Structure rationale:

- The stage should start from records and compatibility before adding sink
  dispatch. Sinks need stable events to observe.
- Programmatic registration should come before plugin discovery because it is
  easier to test, avoids import-time discovery, and keeps sink configuration
  explicit.
- Plugin-discovered loading should be a later phase within the stage because
  current plugin contracts deliberately keep `loom.event_sinks` listing-only.
- Callback failure policy belongs near event dispatch and persistence, not in
  generic plugin discovery, because failure behavior depends on runtime event
  semantics.
- CLI and preflight should be readers over the established APIs rather than
  inventing event semantics.

Visible assumptions, risks, and constraints:

- Assumption: Stage 19 will provide event-ready reliability facts with stable
  identifiers, timestamps, reason codes, transaction IDs, and causal links. If
  Stage 19 implementation changes that shape, Stage 20 must adapt through
  explicit projections rather than infer from logs.
- Risk: expanding the current `PipelineEventRecord` directly could break
  existing `events.jsonl` readers or force unnecessary churn into earlier
  store contracts. Planning needs a compatibility decision.
- Risk: event sinks could accidentally become a second semantics layer for
  status, retry, transaction, artifacts, or metrics. The observe-only boundary
  must be explicit and tested.
- Risk: plugin-discovered sinks can run trusted code with side effects. Loading
  should remain explicit, deterministic, and not enabled by ordinary imports.
- Constraint: core Loom must stay domain-neutral and dependency-light. Service
  delivery clients belong in plugins or downstream wrappers.
- Constraint: event payloads must stay plain-data-compatible, bounded, and
  redacted enough for audit and external projection without raw credentials,
  callback objects, or large payloads.

User clarification questions and resolved answers:

- User agreed with the startup briefing and recommended planning priority on
  2026-05-17. No clarifying questions were raised before moving to intent
  discovery.

## User Intent

Target audience:

- Users and maintainers who need inspectable runtime timelines, plus plugin and
  downstream tool authors who need stable observe-only events without importing
  project code or changing Loom run correctness.

User-visible outcome:

- Audit-compatible runtime event records and explicit observe-only sink
  contracts that external tools can consume safely. Planning should prioritize
  event compatibility and generic sink extensibility before notification
  ergonomics, broad CLI surface, or service-specific integrations.

Primary workflows:

- Audit and debugging timelines that explain run, stage, submission, retry,
  timeout, transaction, and callback facts.
- External observer and plugin integration through explicit event sink
  registration.
- Callback failure inspection that lets users see observer failures without
  changing run correctness.

Success criteria:

- Users and tools can read ordered committed-fact events without importing
  project code.
- Plugin and downstream tool authors can register observe-only sinks through a
  stable, generic contract.
- Sink failures are visible and best-effort by default.
- Stage 20 preserves existing event compatibility while enabling richer future
  event projections.

Non-goals:

- Service-specific sinks, distributed event streaming, cleanup/retention
  operations, strict audit-failure mode, event-driven runtime mutation, and
  domain-specific metric or tracking semantics.

Constraints:

- Keep Loom generic, dependency-light, authority-compatible, and fake/local-test
  friendly.
- Keep event payloads plain-data-compatible, bounded, and safe for audit
  projection.
- Keep event logs as audit facts rather than authoritative current state.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- User confirmed the startup briefing and accepted the recommended priority:
  audit-ready event compatibility plus generic observe-only sink contracts
  first; service-specific delivery, cleanup/retention, distributed streaming,
  and strict audit-failure mode remain out of scope for Stage 20.

Intent discovery locked decisions:

- User confirmed the recommended intent defaults on 2026-05-17:
  audit/debugging timelines, external observer and plugin integration, and
  callback failure inspection are the primary workflows; success means ordered
  committed-fact events, stable observe-only sink registration, visible
  best-effort callback failures, and compatibility for existing event records;
  non-goals remain service-specific delivery, cleanup/retention, distributed
  streaming, strict audit-failure mode, event-driven mutation, and
  domain-specific tracking semantics.

Capability triage and candidate-functional-requirement readback:

- User confirmed the recommended capability triage on 2026-05-17. Stage 20
  includes rich event grammar, existing-event compatibility/versioning,
  projection from committed runtime facts, programmatic event sink registry,
  observe-only dispatch, callback failure records, explicit plugin loading,
  preflight warnings, narrow event-persistence defaults when sinks are
  configured, and narrow read-only inspection. It defers service-specific
  delivery, distributed streaming, strict audit-failure mode, cleanup and
  retention, cross-run retry budgets, and resource-aware retry escalation.

Functionality-agreement readback:

- User confirmed the final high-impact functionality defaults on 2026-05-17.
  Event sinks may write only narrow external-link or observer-reference metadata
  through explicit APIs and must not mutate Loom correctness state. When event
  sinks are configured, event persistence is enabled by default unless
  explicitly disabled so observed events and callback failure records remain
  inspectable. The functionality-agreement queue has no unresolved blockers.

Functionality and behavior confirmation readback:

- User confirmed the behavior baseline on 2026-05-17. Stage 20 includes
  audit-ready event records, compatibility/versioning for existing events,
  committed-fact projection, programmatic sink registry, observe-only dispatch,
  narrow external-link writeback, callback failure records, explicit plugin
  loading, preflight warnings, and narrow read-only inspection. Defaults are no
  ambient sink loading, event persistence enabled by default when sinks are
  configured unless disabled, and best-effort visible callback failures.
  Explicit deferrals are service-specific delivery, distributed streaming,
  strict audit mode, cleanup/retention, event-driven mutation, arbitrary
  metadata writes, events as current-state authority, and domain-specific
  tracking semantics.

Design-agreement follow-up:

- Design agreement completed in the resumed context on 2026-05-17. The design
  queue has no unresolved `needs discussion` or `blocked` items. Recorded
  recommendations favor one canonical versioned event-record family with
  schema-v1 compatibility projection, a separate import-light
  `loom.pipeline.event_sinks` module for sink protocols and registry behavior,
  event append before sink dispatch, event-adjacent callback failure records,
  narrow external-link writeback through explicit store APIs, explicit plugin
  loading through `loom.plugins.event_sinks`, and read-only diagnostics/CLI
  surfaces.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Startup briefing confirmed. Stage 20 optimizes for audit-compatible runtime events and generic observe-only sink contracts before plugin ergonomics, broad CLI presentation, or service-specific delivery. | Event logs are audit facts, not current state; sinks are observe-only; callback failures are best-effort by roadmap default; service-specific delivery and cleanup behavior are deferred. | None. | Intent discovery. |
| Intent discovery | Primary workflows are audit/debug timelines, external observer/plugin integration, and callback failure inspection. Success means ordered committed-fact events, stable observe-only sink registration, visible best-effort callback failures, and compatibility for existing event records. | Keep Loom generic, dependency-light, authority-compatible, fake/local-test friendly, plain-data-compatible, and explicit that events are audit facts. | None. | Capability triage. |
| Capability triage and candidate functional requirements | Include event grammar, compatibility/versioning, committed-fact projection, programmatic sink registry, observe-only dispatch, callback failure records, explicit plugin loading, preflight warnings, narrow event-persistence defaults, and narrow read-only inspection. Defer service-specific delivery, distributed streaming, strict audit mode, cleanup/retention, cross-run retry budgets, and resource-aware retry escalation. | Event sinks are explicit trusted setup; event persistence and inspection stay narrow; deferred integrations remain future plugins or later stages. | None. | Functionality-agreement review. |
| Functionality agreement review | Event sinks may write only narrow external-link or observer-reference metadata through explicit APIs; event persistence is enabled by default when sinks are configured unless explicitly disabled. | Callback failures are best-effort and visible; strict audit failure is deferred; no service-specific delivery. | None. | Functionality and behavior confirmation. |
| Functionality and behavior confirmation | Behavior baseline confirmed: audit-ready events, compatibility, committed-fact projection, programmatic registry, observe-only dispatch, narrow external-link writeback, callback failure records, explicit plugin loading, preflight warnings, and narrow read-only inspection. | No ambient sink loading; event persistence is enabled by default when sinks are explicitly configured unless disabled; callback failures are visible and best-effort. | None. | Context checkpoint. |
| Context compaction/reset checkpoint | Functionality and behavior checkpoint recorded in this artifact; resumed design pass started from the artifact without reopening functionality or behavior. | Resume design agreement from this artifact; do not reopen functionality or behavior unless the user explicitly asks. | None. | Design-agreement review. |
| Design agreement review | Proposed implementation shape and design-agreement queue recorded. Decisions favor canonical versioned event records with schema-v1 compatibility, committed-fact append before dispatch, separate sink module/registry, event-adjacent callback failures, narrow external-link writeback, explicit plugin loading, and read-only inspection. | No ambient sink loading; no service-specific delivery; no event-driven core-state mutation; no event logs as authoritative current state. | None. | Design-safety review. |
| Design safety review | Passed after revisions. Tightened `event_sinks` import boundaries and non-durable dispatch identity semantics; upheld canonical event family, narrow CLI, and source-tree ownership. | `event_sinks` defines narrow structural context protocols locally; non-persistent dispatch uses a non-durable envelope and warning. | None. | Examples and validation strategy. |
| Examples and validation strategy | Confirmed examples cover ordered audit logs, schema-v1 compatibility, committed reliability fact projection, observe-only dispatch, callback failure records, non-durable explicit opt-out dispatch, observer-link writeback, and explicit plugin loading. | Validation must include package/API, unit, contract, integration, diagnostics/CLI when implemented, and final project gates. | None. | Phase shaping. |
| Phase shaping | Four-phase shape confirmed: event grammar/compatibility, sink registry and observer facts, runtime dispatch from committed facts, then plugin loading/diagnostics/inspection/docs. | Programmatic registry precedes plugin loading; runtime dispatch follows durable facts; diagnostics and CLI remain read-only. | None. | Implementation readiness. |
| Implementation readiness | Requirements, design, design-safety review, examples, validation, and phase shaping are recorded with no unresolved blockers. | Implementation-plan drafting may proceed from this artifact. | None. | Handoff. |
| Handoff | Use this artifact as the primary source for implementation-plan drafting. | Implementation plan must carry forward accepted debt, Stage 19 dependency assumptions, and plan-quality-gate risk areas. | None. | Implementation-plan draft. |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Rich runtime event grammar | include | Central Stage 20 roadmap outcome. | Functionality agreement should lock audit-ready fields and leave exact type layout to design agreement. |
| Existing event compatibility/versioning | include | Roadmap explicitly requires existing local event records and readers to have a path. | Requirement is explicit compatibility; exact projection/migration shape remains design work. |
| Event projection from committed runtime facts | include | Events must represent store/authority facts, especially Stage 19 reliability facts. | Emission must happen after durable facts exist. |
| Programmatic `EventSink` and `EventSinkRegistry` | include | Roadmap says programmatic registration first. | Likely public or semi-public contract. |
| Observe-only sink dispatch | include | Central correctness boundary. | Must prohibit mutation of core runtime semantics. |
| Callback failure records and best-effort default | include | Roadmap requires visible failures and best-effort default. | Strict failure mode deferred. |
| Plugin-discovered `loom.event_sinks` loading | include | Roadmap includes plugin-discovered sink loading after registry stability. | Should be phased after programmatic registry. |
| Event persistence defaults when sinks configured | include, narrow | Feature docs recommend persistence enabled by default when sinks are configured unless disabled. | Functionality agreement should lock the default because it affects storage volume and inspectability. |
| Read-only CLI event inspection | include, narrow | Roadmap says where useful and user confirmed narrow inclusion. | Should depend on stable read APIs and avoid broad CLI scope. |
| Preflight warnings for event persistence and sink policy | include | Roadmap explicitly includes warnings. | Should remain cheap and local by default. |
| Service-specific notification/tracking sinks | defer | Roadmap defers MLflow, W&B, notifications, webhooks, and telemetry clients. | Future plugins only. |
| Distributed event streaming | defer | Roadmap defers it. | Future adapter over event contract. |
| Strict audit-failure mode | defer | Roadmap defers later strict mode. | Default best-effort only. |
| Cleanup and retention operations | defer | Stage 21 owns cleanup and retention. | Stage 20 can only make events compatible with future cleanup facts. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Lock the primary user-visible outcome for Stage 20. | none | 1 | Audit-ready events and explicit observe-only sinks that external tools can consume without changing run correctness. | This determines whether planning favors audit compatibility, plugin extensibility, CLI inspection, or notification ergonomics. | User confirmed roadmap-framing and intent defaults. | confirmed |
| FRQ-2 | Lock whether service-specific delivery is out of scope. | FRQ-1 | 2 | Defer service-specific MLflow, W&B, Slack, webhook, OpenTelemetry, or hosted telemetry clients. | Keeps Loom domain-neutral and dependency-light. | Repo and roadmap evidence are decisive; user confirmed capability triage. | confirmed |
| FRQ-3 | Lock event compatibility policy for existing schema-v1 records. | FRQ-1 | 3 | Require explicit read/project compatibility for old records rather than silently changing their meaning. | Existing event readers and tests depend on current fields. | Exact projection or migration shape remains design-agreement work. | confirmed |
| FRQ-4 | Lock observe-only sink semantics and allowed metadata writeback. | FRQ-1 | 4 | Sinks can perform external side effects and write explicit external-link metadata through narrow APIs, but cannot mutate core state. | This is the core correctness boundary and affects what plugin authors can do. | User agreed to narrow external-link metadata writeback on 2026-05-17. | confirmed |
| FRQ-5 | Lock default callback failure policy. | FRQ-4 | 5 | Record failure and continue by default; strict mode deferred. | Prevents observer failures from changing run correctness. | Roadmap evidence and user-confirmed intent are decisive. | confirmed |
| FRQ-6 | Lock programmatic registration before plugin-discovered loading. | FRQ-4 | 6 | Build registry and programmatic dispatch first, then explicit `loom.event_sinks` loader. | Gives tests and users a stable API before entry point side effects. | Roadmap and plugin feature docs are decisive. | confirmed |
| FRQ-7 | Lock read-only CLI and preflight scope. | FRQ-3 | 7 | Include narrow inspection and warnings only where useful, no mutating event commands. | Avoids turning CLI into the event semantics owner. | User confirmed narrow inclusion during capability triage. | confirmed |
| FRQ-8 | Lock event persistence default when sinks are configured. | FRQ-3, FRQ-4 | 8 | Enable event persistence by default when sinks are configured unless explicitly disabled. | Sink users need inspectability and callback failure records, but persistence affects storage volume. | User agreed on 2026-05-17. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Audit-ready runtime event records | none | Define structured event records for committed runtime facts with stable identity, ordering, resource links, causal links, payloads, and versioning. | External observers and audit readers need durable, machine-readable facts. | Event model, serialization, local/authority projection, compatibility. | Users can inspect ordered typed events without project code. | Stores append/read versioned records after durable facts exist. | Runtime audit log. | Serialization and compatibility tests. | confirmed |
| FR-2 | Event projection from reliability and lifecycle facts | FR-1 | Emit or project events for lifecycle, submission, retry, timeout, transaction, and callback facts. | Stage 20 consumes Stage 19 rather than redefining reliability semantics. | Emission sequencing and payload conventions. | Event logs explain what happened and why. | Runtime emits after corresponding facts are persisted. | Audit-ready lifecycle and reliability timeline. | Integration tests around ordering after state transitions. | confirmed |
| FR-3 | Observe-only event sink registry | FR-1 | Provide `EventSink` and `EventSinkRegistry` for programmatic callback registration and dispatch, with a narrow external-link metadata writeback boundary. | External tools need a stable observer contract without changing Loom correctness. | Programmatic registry first, no plugin loading until registry stable; metadata writeback limited to explicit external links through narrow APIs. | Users can register project sinks explicitly and retain external tracking links. | Dispatch passes immutable or plain-data event records to sinks; sinks cannot mutate core runtime state. | External observer integration. | Unit/contract tests with fake sinks plus mutation-boundary tests. | confirmed |
| FR-4 | Callback failure visibility | FR-3 | Record sink callback failures and continue by default. | Observer failures must be visible but not alter run correctness. | Failure records, diagnostics, event payload or sidecar records. | Users can inspect failed callbacks. | Runtime catches callback errors, records them, and continues. | Safe observer failures. | Failure injection tests. | confirmed |
| FR-5 | Explicit event sink plugin loading | FR-3 | Add `loom.event_sinks` loading after registry behavior is stable. | Installed trusted packages need explicit discovery and registration. | Entry point loading adapter and provenance/diagnostic summaries. | Users can opt into loading event sink plugins. | Plugin loader validates accepted sink shapes and registers them. | Plugin-provided sinks. | Plugin contract tests for valid, invalid, duplicate, and failure cases. | confirmed |
| FR-6 | Preflight and read-only inspection | FR-1 | Add warnings and narrow CLI or API inspection where useful. | Users need to understand event persistence and sink support. | Cheap diagnostics and read-only presentation. | Users can see event support and callback failures. | Diagnostics read records/capabilities without mutating state. | Operational visibility. | CLI/preflight tests if CLI changes. | confirmed |

## Behavior Baseline

Included functionality:

- Audit-ready runtime event records with stable identity, ordering, resource
  links, payloads, causal links, and explicit compatibility/versioning for
  existing local event records.
- Event projection from committed lifecycle, submission, retry, timeout,
  transaction, callback, and selected provenance facts.
- Programmatic `EventSink` and `EventSinkRegistry` contracts with observe-only
  dispatch.
- Narrow external-link or observer-reference metadata writeback through
  explicit APIs.
- Callback failure records with best-effort default behavior.
- Explicit `loom.event_sinks` plugin loading after registry behavior is stable.
- Preflight warnings and narrow read-only event inspection where useful.

User-visible behavior:

- Users can inspect ordered event records that explain runtime facts without
  importing project code.
- Users can register project sinks explicitly and later opt into plugin-loaded
  sinks.
- Users can see callback failures and external observer links when sinks record
  them.
- Users do not see sinks change run status, retry decisions, transactions,
  artifacts, stage outputs, or planner behavior.

Default behavior:

- Event records remain append-only, machine-readable audit facts when event
  persistence is enabled.
- Event sinks are not enabled by ordinary imports or ambient plugin discovery.
- When event sinks are explicitly configured, event persistence is enabled by
  default unless explicitly disabled.
- Callback failures are recorded and best-effort by default.

Failure behavior and diagnostics:

- Callback failures are captured with sink identity, event reference, failure
  detail, and enough context for inspection while preserving the original run
  correctness outcome.
- Unsupported event persistence, sink registration, or callback failure policy
  should produce explicit diagnostics or preflight warnings where practical.
- Malformed plugin-provided sinks or duplicate sink registration should fail
  the explicit loading/registration action, not ordinary package import.

Explicit deferrals:

- Service-specific sinks, distributed streaming, strict audit-failure mode,
  cleanup and retention operations, cross-run retry budgets, and
  resource-aware retry escalation.
- Automatic loading of event sink plugins without explicit user or programmatic
  action.

Out-of-scope behavior:

- Event sinks mutating plans, configs, artifacts, stage outputs, status
  transitions, retry decisions, transaction records, or core store records.
- Event sinks writing arbitrary run metadata. Stage 20 only includes narrow
  external-link or observer-reference writeback through explicit APIs.
- Event records becoming the source of current lifecycle state.
- Domain-specific metrics, tracking-service semantics, or service-client
  delivery in core Loom.

Context compaction/reset checkpoint:

- Checkpoint status: recorded; reset required before design agreement
- Notes path: `docs/roadmap/stage-20/planning.md`
- Resume instruction: reread this planning artifact and
  `.codex/workflows/roadmap-stage-planning.md`, then follow
  `.codex/prompts/roadmap-stage-design-agreement.md` for Stage 20. Treat
  roadmap framing, intent discovery, capability triage, functionality
  agreement, and behavior baseline as confirmed unless the user explicitly
  reopens them. Start by drafting the proposed implementation shape and
  design-agreement queue from this artifact.
- Functionality and behavior reopened after checkpoint: no

## Proposed Implementation Shape

Likely modules or packages:

- `loom.pipeline.events` remains the canonical import-light event-record module.
  It should evolve `PipelineEventRecord` to the Stage 20 grammar with explicit
  schema-version support and schema-v1 compatibility projection.
- `loom.pipeline.event_sinks` should own import-light sink protocols,
  `EventSinkRegistry`, dispatch results, callback failure records, and narrow
  observer-link writeback context types. Keeping this separate from
  `loom.pipeline.events` prevents the strict record module from becoming a
  plugin or execution module.
- `loom.pipeline.execution.eventing` and runner/continuation/lifecycle call
  sites should append/project events after durable runtime facts are recorded,
  then dispatch to a supplied registry when one is configured.
- `loom.pipeline.stores` should keep `RunEventStore` as the core append/read
  event facet and add narrow facets for event sink failure records and external
  observer links when needed. Stores should read old local schema-v1 event
  lines through compatibility projection rather than rewriting them eagerly.
- `loom.plugins.event_sinks` should adapt the existing plugin-loading helper
  pattern for explicit `loom.event_sinks` loading into a supplied registry.
- `loom.diagnostics`, preflight, and `loom.cli` may add read-only inspection and
  warnings over event persistence, sink registration, callback failure records,
  and unsupported policies.
- `docs/structure.md`, `docs/features/reliability.md`,
  `docs/features/plugins.md`, and CLI/preflight docs should be updated during
  implementation planning to match the final public and file-layout contracts.

Likely public classes, functions, or protocols:

- `PipelineEventRecord` remains the canonical persisted event record name, with
  Stage 20 fields for event id, per-run sequence, occurred timestamp, event
  name, primary resource, related resources, plain-data payload, optional
  causal predecessor, and schema version.
- `PipelineEvent` remains the append request/input object or is narrowed into
  an append request alias for the canonical record family. Existing
  schema-v1-shaped requests should project to the Stage 20 record shape.
- `EventResource` or equivalent plain-data resource reference should represent
  generic event subjects such as run, stage, artifact, submitted operation,
  retry decision, timeout outcome, transaction, plugin callback, or future
  cleanup candidate without encoding service-specific semantics.
- `EventSink` should be a protocol or callable contract over immutable event
  records and an explicit sink context.
- `EventSinkRegistry` should be instance-local, deterministic, and explicit.
  It should support register, replace policy, duplicate rejection, iteration,
  and dispatch through a supplied runtime path.
- `EventSinkContext` should expose only allowed observer behavior, such as
  recording external-link or observer-reference metadata through narrow APIs.
- `EventSinkFailureRecord` and `EventSinkDispatchResult` should capture sink
  identity, event reference, failure type/message/detail, timestamp, and
  causal links.
- `load_event_sink_entry_points(...)` should live under `loom.plugins` using a
  dedicated adapter module after the registry surface is stable.

Likely internal helpers:

- Schema-v1-to-current event projection helpers.
- Event id and causal-link helpers.
- Resource-reference construction helpers for run, stage, artifact, submitted
  operation, reliability decision, transaction, callback, and future cleanup
  resources.
- Bounded payload and redaction projection helpers.
- Event append-and-dispatch helpers that centralize ordering and failure
  policy.
- Plugin value normalization helpers for callable sinks, no-arg sink classes,
  and no-arg factories.
- Preflight and inspection formatters that read event/sink facts without owning
  event semantics.

Data flow:

- Runtime code records the authoritative lifecycle, reliability, transaction,
  submission, or provenance fact first.
- Eventing code projects that committed fact into a `PipelineEventRecord`.
- The run store appends the event if persistence is enabled. Sink-enabled runs
  default to persistence enabled unless explicitly disabled.
- The dispatcher sends the immutable event record to registered sinks after the
  durable fact exists and, when persistence is enabled, after append succeeds.
- Sinks may perform external side effects and may record narrow observer links
  through the supplied context. They cannot mutate runtime correctness state.
- Callback failures are caught, recorded as event-adjacent failure facts when
  persistence is enabled, and returned in dispatch results. They do not change
  run correctness by default.
- Diagnostics and CLI read event records, failure records, and observer links
  rather than parsing executor logs or plugin callback internals.

Dependency direction:

- `loom.pipeline.events` depends only on foundational serialization,
  timestamps, and generic value helpers.
- `loom.pipeline.event_sinks` may depend on event records and serialization,
  but it should not import `loom.pipeline.stores`. It should define narrow
  observer-link recorder protocol or context shapes locally so stores can
  satisfy them structurally without an import cycle.
- `loom.pipeline.execution` imports event records and sink dispatch helpers.
  It remains the writer/emitter of runtime event facts.
- `loom.pipeline.stores` persists event records, failure records, and observer
  links but does not execute sinks or import plugins.
- `loom.plugins.event_sinks` imports the registry/protocol surface and existing
  plugin entry-point helpers. Event semantics remain in pipeline/reliability
  and execution, not in plugins.
- `loom.diagnostics` and `loom.cli` are read-only presentation layers over
  public APIs and store/read-model facts.

Extension points and flexibility boundaries:

- Event resources are generic and extensible through plain-data resource kinds,
  not hard-coded service entities.
- Event names remain lower-case dot-separated Loom runtime facts. Service
  plugins can project them externally but cannot redefine core names.
- Sink registry instances are supplied explicitly by project setup, runtime
  options, or plugin loading. There is no global ambient sink registry.
- Sink callbacks receive immutable/plain-data event facts and a narrow context.
  The context deliberately excludes plan/config/artifact/status/retry/
  transaction mutation APIs.
- Callback failure policy is best-effort by default. Future strict audit mode
  can build on failure records without changing the default contract.
- Distributed streaming remains a future adapter over the event/sink contract.

Generic interface, adapter, or protocol shape:

- `EventSink`: a generic observer protocol over `PipelineEventRecord` plus an
  explicit context, returning `None` or a plain-data-compatible observer result.
- `EventSinkRegistry`: a small registry keyed by deterministic sink name,
  supporting explicit registration, replacement policy, duplicate diagnostics,
  and dispatch iteration.
- `EventSinkContext`: a deliberately narrow adapter for recording external
  observer links and accessing immutable run/event identity. It should not be a
  general `RunStore` handle.
- Event store facets: append/read canonical events, read projected schema-v1
  events, append/read sink failure records, and append/read external observer
  links. Sink context protocols should be narrow structural protocols so the
  sink module does not import store implementations or broad store protocols.
- Plugin adapter: entry-point loading maps accepted plugin values to the
  generic registry; it does not define event names, payloads, or dispatch
  timing.

Future-roadmap impact:

- Stage 21 cleanup can emit or consume cleanup candidate/outcome event
  resources later without Stage 20 implementing deletion.
- Service-specific notification, tracking, telemetry, audit-log, and webhook
  packages can be plugins over `EventSink` without core Loom dependencies.
- Distributed streaming can be a future sink adapter over ordered events rather
  than a replacement for stores or authority.
- Strict audit-failure mode can reuse callback failure records and dispatch
  policy without changing best-effort defaults.
- Export/import, run catalogs, provenance, and comparisons can treat event
  records as audit facts, not authoritative state.

Compatibility constraints:

- Existing schema-v1 `PipelineEventRecord` dictionaries and `events.jsonl`
  lines must remain readable and projectable into the Stage 20 canonical
  record shape.
- Store protocols and package tests that currently use `PipelineEventRecord`
  should migrate deliberately rather than through a parallel event family.
- New event fields must remain plain-data-compatible and bounded.
- Sink-enabled event persistence defaults must not break runs where persistence
  is explicitly disabled; those runs should receive clear diagnostics about
  reduced durable inspectability. Non-persistent dispatch should still use an
  explicit non-durable event envelope with event id, occurred timestamp, and an
  in-process per-run dispatch sequence marked as non-durable rather than
  pretending a store-allocated durable sequence exists.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Event grammar evolution and schema-v1 compatibility. | FR-1 | 1 | recorded recommendation | Keep `PipelineEventRecord` as the canonical event family, evolve it to the Stage 20 grammar, and provide explicit schema-v1 projection/read compatibility. | Durable event logs and store contracts already use this public record name. | Repo evidence gives a clear recommendation; no user input needed. | confirmed |
| DAQ-2 | Event resource and payload vocabulary. | FR-1, FR-2 | 2 | recorded recommendation | Add generic event-resource refs and bounded plain-data payload conventions instead of backend-specific fields or service-specific metric shapes. | Future sinks, cleanup, provenance, and reliability projections need stable generic subjects. | Repo evidence and domain-neutrality rule give a clear recommendation. | confirmed |
| DAQ-3 | Runtime emission and sink dispatch ordering. | FR-2, FR-3, FR-4 | 3 | recorded recommendation | Record durable runtime facts first, append/project the event second, dispatch sinks third, and record callback failures as event-adjacent facts. | Prevents observers from seeing facts that are not authoritative and preserves best-effort failures. | Repo evidence and confirmed behavior give a clear recommendation. | confirmed |
| DAQ-4 | Explicit persistence-disabled behavior for sink-enabled runs. | FR-3, FR-4 | 4 | recorded recommendation | Default persistence on for sink-enabled runs; if explicitly disabled, allow dispatch through a clearly non-durable event envelope and warn that durable event and callback-failure inspectability is reduced. | The user confirmed an explicit persistence opt-out, but sink failures cannot be fully durable without persistence. | This is implied by the confirmed default and feature docs; design-safety review tightened the non-durable identity requirement. | confirmed |
| DAQ-5 | Event sink module and registry shape. | FR-3 | 5 | recorded recommendation | Add `loom.pipeline.event_sinks` with an instance-local `EventSinkRegistry`; avoid a global registry, keep sink contracts separate from strict event records, and avoid importing store modules from the sink module. | Controls public API and import boundaries. | `docs/structure.md`, current plugin adapter patterns, and design-safety import-cycle review give a clear recommendation. | confirmed |
| DAQ-6 | Metadata writeback boundary for sinks. | FR-3 | 6 | recorded recommendation | Use a narrow observer-link store/context API for external links or observer references; do not expose broad run metadata or lifecycle stores to sinks. | Maintains observe-only semantics while supporting useful external integrations. | User already confirmed narrow writeback; exact interface is repo-answerable. | confirmed |
| DAQ-7 | Callback failure record shape and causal links. | FR-4 | 7 | recorded recommendation | Store `EventSinkFailureRecord` facts with sink identity, event reference, failure detail, timestamp, and causal link; do not dispatch failure records recursively to ordinary sinks by default. | Enables auditability and future strict mode without callback loops. | Repo evidence and failure-policy constraints give a clear recommendation. | confirmed |
| DAQ-8 | Plugin loading phase boundary and accepted shapes. | FR-5 | 8 | recorded recommendation | Add `loom.plugins.event_sinks.load_event_sink_entry_points` after registry stability, using accepted callable/no-arg class/no-arg factory shapes and entry point names as deterministic registry names. | Current tests mark `loom.event_sinks` listing-only; enabling loading must be deliberate. | Plugin feature docs and existing adapter code give a clear recommendation. | confirmed |
| DAQ-9 | Read-only diagnostics and CLI scope. | FR-6 | 9 | auto-approved candidate | Add cheap warnings and narrow inspection over event/sink support, callback failures, and observer links; no mutating event CLI. | Prevents CLI from owning event semantics. | Low-risk, traceable to confirmed behavior, and straightforward to validate. | confirmed |
| DAQ-10 | Import/dependency boundary. | FR-1 through FR-6 | 10 | auto-approved candidate | Keep records and sink protocols dependency-light; stores persist facts; execution emits and dispatches; plugins load into a supplied registry; diagnostics/CLI read. | Preserves source-tree boundaries and domain neutrality. | Low-risk application of `docs/structure.md`, subject to design-safety review. | confirmed |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Future-roadmap impact | Interface, adapter, or protocol impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Event grammar evolution and schema-v1 compatibility. | Keep `PipelineEventRecord` as the canonical event family, evolve it to the Stage 20 grammar, and add schema-v1 projection/read compatibility for existing local `events.jsonl` and store records. | Functionality confirmed compatibility/versioning; no separate user feedback required. | Parallel `RuntimeEventRecord` family; silent field changes; eager local log rewrite. | Existing stores, contract tests, and feature docs already use `PipelineEventRecord`; one canonical family avoids duplicate semantics. | Keeps callers on one event contract and localizes migration helpers. | Future event fields can evolve through schema versions without requiring plugins to know old shapes. | Stage 21 and future service plugins consume one canonical event contract. | Adds versioned load/project helpers and possibly event resource value objects. | Serialization, schema-v1 fixture, local/authority read, and package/contract tests. | Debt: v1 projection layer must be maintained until a documented removal window. Revisit if v1 compatibility blocks necessary event semantics. | confirmed |
| DAQ-2 | Event resource and payload vocabulary. | Use generic event-resource refs plus bounded plain-data payload conventions for run, stage, artifact, submitted-operation, retry, timeout, transaction, callback, provenance, and future cleanup subjects. | Functionality confirmed domain-neutral audit records. | Backend-specific top-level fields; service-specific metric names; unstructured payload-only subjects. | Roadmap requires primary and related resources; generic refs preserve domain neutrality. | Reduces ad hoc payload parsing and makes event consumers simpler. | New resource kinds can be added without changing sink protocol shape. | Stage 21 cleanup and future streaming/sinks can reuse the same resource vocabulary. | Introduces a reusable event-resource value object or plain-data contract. | Unit tests for resource refs, payload bounds, redaction, and invalid shapes. | Debt: exact resource-kind registry should stay small initially. Revisit when future resource kinds need validation. | confirmed |
| DAQ-3 | Runtime emission and sink dispatch ordering. | Runtime records committed facts first, appends/projects an event second, then dispatches sinks. Callback failures are recorded after dispatch without changing run correctness. | Confirmed behavior requires committed-fact events and best-effort failures. | Dispatch before store commit; event logs as state authority; sink-driven retry/status updates. | Prevents observers from seeing facts that did not commit and keeps event logs audit-only. | Central append/dispatch helper avoids scattered callback policy. | Future dispatch policies can wrap the same helper. | Strict audit mode can later change policy without changing event grammar. | Adds dispatcher helper used by runner, continuation, and lifecycle paths. | Ordering tests around status/transaction commit then event append then dispatch. | Debt: explicitly persistence-disabled dispatch has reduced durable evidence. Revisit if users need sink dispatch to require persistence. | confirmed |
| DAQ-4 | Explicit persistence-disabled behavior for sink-enabled runs. | Sink-enabled runs enable persistence by default. If explicitly disabled, dispatch may proceed through a non-durable event envelope carrying event id, occurred timestamp, and an in-process per-run dispatch sequence clearly marked as non-durable; diagnostics warn that durable event and callback-failure inspectability is reduced. | User confirmed persistence default with explicit opt-out. | Reject sinks whenever persistence is disabled; silently dispatch without warning; force persistence with no opt-out; fabricate durable store sequence numbers without persistence. | Matches confirmed default while preserving the user's explicit disable escape hatch and avoids ambiguous event identity. | Keeps behavior explicit and testable instead of hidden. | Future strict audit mode can reject disabled persistence for strict deployments. | Service plugins can decide whether their own setup requires durable records. | Adds diagnostics, dispatch result fields, and a non-durable event envelope or marker. | Tests for default persistence, explicit disable warning, non-durable dispatch identity, and non-persistent callback failure handling. | Accepted debt: explicit disable weakens durable auditability. Revisit when strict audit mode is planned. | confirmed |
| DAQ-5 | Event sink module and registry shape. | Add `loom.pipeline.event_sinks` with `EventSink`, `EventSinkRegistry`, dispatch result, failure record, narrow context types, and structural observer-link recorder protocols; registry is instance-local and explicit; the module must not import store implementations or broad store protocols. | Functionality confirmed programmatic registry first. | Global ambient registry; sink registry inside `loom.plugins`; putting sink dispatch into `pipeline.events`; importing `loom.pipeline.stores` from `event_sinks`. | Keeps strict records separate from observer mechanics, avoids import-time plugin behavior, and prevents a store/sink import cycle. | Improves locality and testability. | Multiple runs/tests can use separate registries; future config/runtime setup can supply registries explicitly. | Future plugin, streaming, and strict policies can adapt to the same registry. | Creates a reusable sink protocol and registry contract with narrow structural context. | Package/API tests, import-boundary tests, registry duplicate/replace tests, fake sink dispatch tests. | Debt: new public module path. Revisit if design-safety review or implementation shows the surface is too broad. | confirmed |
| DAQ-6 | Metadata writeback boundary for sinks. | Provide a narrow observer-link context/store API for external links and observer references only; do not expose broad run metadata or lifecycle mutation APIs to sinks. | User confirmed narrow external-link writeback. | Reusing `write_run_user_metadata`; passing a full `RunStore` to sinks; forbidding all link writeback. | Gives integrations useful traceability while preserving observe-only correctness. | Avoids arbitrary metadata coupling and simplifies tests. | New link types can remain plain-data facts without changing core lifecycle records. | Future service plugins can store external references without core service clients. | Adds `EventObserverLink`-like record/context and store facet. | Mutation-boundary tests and link serialization/read tests. | Debt: link schema starts narrow. Revisit if multiple future integrations need richer observer summaries. | confirmed |
| DAQ-7 | Callback failure record shape and causal links. | Store event-adjacent callback failure facts with sink name, event id/sequence, failure type/message/detail, timestamp, and causal predecessor; do not dispatch failure facts recursively to ordinary sinks by default. | Functionality confirmed visible best-effort failures. | Swallow failures; fail run by default; emit recursive sink failure events to every sink. | Avoids callback loops while preserving auditability. | Keeps failure handling centralized and easy to validate. | Future strict mode can promote recorded failures into run policy decisions. | Future notification sinks can choose explicit self-monitoring without default recursion. | Adds `EventSinkFailureRecord` and read APIs. | Failure injection, non-recursion, and causal-link tests. | Debt: failure records are event-adjacent, not ordinary dispatched events by default. Revisit if users need callback-failure events for external monitoring. | confirmed |
| DAQ-8 | Plugin loading phase boundary and accepted shapes. | Add `loom.plugins.event_sinks.load_event_sink_entry_points` after registry stability, accepting callables, no-arg classes, and no-arg factories; entry point name is the deterministic registry name unless explicit registry naming is later added. | Capability triage confirmed explicit plugin loading. | Ambient plugin loading; plugin layer defining event semantics; object-provided names overriding entry point names by default. | Matches existing plugin adapter patterns and feature-doc recommendations. | Keeps plugin discovery generic and isolated from event semantics. | Future plugin groups can follow the same adapter pattern. | Service-specific sinks remain external packages over this loader. | Updates plugin readiness from listing-only to registry-ready for `loom.event_sinks` when implemented. | Plugin contract tests for valid shapes, duplicates, registration failures, strict/best-effort behavior. | Debt: accepted shapes intentionally exclude configured constructors. Revisit if config-built sink factories need direct plugin support. | confirmed |
| DAQ-9 | Read-only diagnostics and CLI scope. | Add cheap preflight warnings and narrow read-only inspection for event persistence support, sink registration, callback failures, and observer links; no mutating event CLI. | Capability triage confirmed narrow inspection. | Broad event-management CLI; CLI-owned event semantics; mutating cleanup/retry/sink commands. | CLI should present public APIs, not own event behavior. | Limits surface area and review burden. | Future commands can expand over read models after core contracts stabilize. | Stage 21 cleanup and service plugins remain separate. | Diagnostics read store capabilities and event/sink records. | CLI/preflight tests only where presentation changes; no network or service tests. | None beyond intentionally narrow first surface. Revisit if users cannot inspect key facts through Python APIs. | confirmed |
| DAQ-10 | Import/dependency boundary. | Keep event records and sink protocols import-light; stores persist facts; execution emits/dispatches; plugins only load into supplied registries; diagnostics/CLI are readers. | Source-tree rules already confirmed by repository guidance. | Records importing plugins/CLI/executors; stores executing sinks; plugins owning event payload semantics. | Directly follows `docs/structure.md` and keeps Loom dependency-light. | Preserves source-tree clarity. | Future stores/executors/sinks can evolve independently. | Avoids locking Stage 21 or service integrations to one backend. | Requires package API and import-boundary tests. | Package, contract, and import tests. | None. Revisit if public imports become too fragmented. | confirmed |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | recorded recommendation | Parallel record family would reduce migration risk but creates duplicate event semantics; one canonical family plus projection is more maintainable. | FR-1 | Record recommendation; send to design-safety review. | confirmed |
| DAQ-2 | recorded recommendation | Payload-only subjects are simpler initially but would make future sink/filter consumers parse unstable payloads. | FR-1, FR-2 | Record recommendation; send to design-safety review. | confirmed |
| DAQ-3 | recorded recommendation | Dispatch before append would reduce latency but risks observers seeing facts that never committed. | FR-2, FR-3, FR-4 | Record recommendation; send to design-safety review. | confirmed |
| DAQ-4 | recorded recommendation | Requiring persistence for all sink dispatch would maximize auditability but contradicts the confirmed explicit disable path. | FR-3, FR-4 | Record accepted debt and revisit trigger; send to design-safety review. | confirmed |
| DAQ-5 | recorded recommendation | A global registry would be convenient but makes tests/order and ambient plugin effects hard to control. | FR-3, FR-5 | Record recommendation; send to design-safety review. | confirmed |
| DAQ-6 | recorded recommendation | Passing full store handles to sinks would be powerful but violates observe-only boundaries. | FR-3 | Record recommendation; send to design-safety review. | confirmed |
| DAQ-7 | recorded recommendation | Recursive failure events are attractive for monitoring but can loop and obscure original runtime facts. | FR-4 | Record recommendation; send to design-safety review. | confirmed |
| DAQ-8 | recorded recommendation | Loading plugins before registry stability would satisfy discovery sooner but would lock an immature public contract. | FR-5 | Record recommendation; send to design-safety review. | confirmed |
| DAQ-9 | auto-approved candidate | Broader CLI could improve usability but would expand scope beyond confirmed narrow inspection. | FR-6 | Keep as auto-approved candidate for reviewer challenge. | confirmed |
| DAQ-10 | auto-approved candidate | A flatter import surface might look simpler, but it would blur source-tree ownership. | FR-1 through FR-6 | Keep as auto-approved candidate for reviewer challenge. | confirmed |

## Design Safety Review

| Finding | Affected decision or requirement | Future-roadmap or compatibility risk | Interface, adapter, or protocol reuse risk | Recommended planning revision | Status |
| --- | --- | --- | --- | --- | --- |
| DSR-1: The `event_sinks` module must not import store modules or broad store protocols. | DAQ-5, DAQ-6, DAQ-10, FR-3 | A store/sink import cycle would make future store backends and service plugins harder to keep isolated. | Passing broad store protocols to sinks would make the observer contract too powerful and too store-shaped. | Revise DAQ-5 and generic interface notes so `loom.pipeline.event_sinks` defines narrow structural context/protocols locally and stores implement them structurally. | resolved |
| DSR-2: Persistence-disabled sink dispatch needs explicit non-durable identity semantics. | DAQ-3, DAQ-4, FR-3, FR-4 | Future strict audit mode and distributed streaming would be confused if non-persistent dispatch pretends to have durable store ordering. | Sinks still need a stable event-shaped input, but it must not masquerade as a durable store record. | Revise DAQ-4 to require a non-durable event envelope with event id, occurred timestamp, and in-process per-run dispatch sequence marked non-durable, plus diagnostics about reduced inspectability. | resolved |
| DSR-3: One canonical event family is acceptable only with explicit migration tests. | DAQ-1, FR-1 | Stage 21 and future service plugins need one event contract; existing schema-v1 logs must not break. | Projection helpers keep the protocol reusable across stores while avoiding a parallel event type. | Keep DAQ-1 and require schema-v1 fixture, local/authority read, and package/contract tests. | upheld |
| DSR-4: Auto-approved CLI and import-boundary decisions are low risk after revisions. | DAQ-9, DAQ-10, FR-6 | Broad CLI or bad imports could constrain future commands, but the current narrow reader-only boundary is acceptable. | Interfaces remain generic and read-oriented. | Keep DAQ-9 and DAQ-10 auto-approved; design-safety review does not reopen them. | upheld |

Gate result:

- Status: passed
- Reviewer: managing agent design-safety review, following
  `.codex/prompts/roadmap-stage-design-safety-review.md`
- Blockers: none after the DSR-1 and DSR-2 planning revisions above.
- Recorded recommendations:
  - Keep one canonical `PipelineEventRecord` family with explicit schema-v1
    projection.
  - Keep `loom.pipeline.event_sinks` import-light and independent of store
    modules.
  - Use non-durable event envelopes when sink dispatch is explicitly allowed
    without event persistence.
  - Keep sink writeback limited to observer links and references.
  - Keep plugin loading explicit through `loom.plugins.event_sinks` after
    registry stability.
- Future-roadmap impact summary:
  - Stage 21 cleanup can reuse event resources and later add cleanup events
    without Stage 20 implementing deletion.
  - Service-specific sinks, streaming adapters, and strict audit mode can build
    on sink registry, dispatch result, and callback failure records.
  - Export/import, run catalogs, comparisons, and provenance can treat events
    as audit facts without changing authority truth.
- Generic interface, adapter, and protocol assessment:
  - Event resources, `EventSink`, `EventSinkRegistry`, `EventSinkContext`,
    observer-link records, and plugin loading are generic enough for future
    stores, executors, and service plugins if context protocols stay narrow and
    structural.
- Planning revisions required:
  - DSR-1 revision applied to DAQ-5, dependency notes, and generic interface
    notes.
  - DSR-2 revision applied to DAQ-4 and compatibility constraints.
- Accepted risks:
  - Schema-v1 event projection remains compatibility debt.
  - Explicitly disabling event persistence weakens durable auditability.
  - Callback failure facts are event-adjacent and not recursively dispatched by
    default.
- Revisit triggers:
  - Strict audit mode planning.
  - Removal or archive window for schema-v1 event compatibility.
  - Downstream service plugins needing richer observer-link summaries or
    configured plugin constructors.

## Practical Design Notes

Public Python API surface:

- `loom.pipeline.events`: canonical versioned event records, event-resource
  refs, schema-v1 compatibility projection, event id and causal-link helpers.
- `loom.pipeline.event_sinks`: `EventSink`, `EventSinkRegistry`,
  `EventSinkContext`, dispatch result, callback failure record, and observer
  link record/context types.
- `loom.plugins`: explicit `load_event_sink_entry_points` export after the
  event sink registry contract is stable.
- Public root `loom.__init__` should not export event or sink types by default.
  Keep event APIs under `loom.pipeline` and plugin loading under
  `loom.plugins`.

CLI surface:

- Narrow read-only inspection only, if implementation planning finds a useful
  existing command surface. Candidate behavior is listing event records,
  callback failures, observer links, and event/sink preflight warnings.
- No mutating event commands, sink enable/disable commands, cleanup commands,
  retry commands, or service-specific notification commands in Stage 20.

Persisted records and file layout:

- Existing local `events.jsonl` remains append-only and machine-readable.
- New appended event lines use the current Stage 20 schema; old schema-v1 lines
  remain readable through projection.
- Callback failure records and observer links should be persisted as
  event-adjacent facts, either in explicit sidecar files or store tables/facets
  selected during implementation planning.
- Exact local filenames or database table names remain implementation-plan
  detail, but they must preserve append/read ordering and avoid treating events
  as authoritative current state.

Import boundaries and dependencies:

- Event records and sink protocols remain dependency-light and should not pull
  in concrete executors, plugin discovery, diagnostics, CLI, or service
  clients.
- `loom.pipeline.event_sinks` should not import `loom.pipeline.stores`; sink
  context/writeback protocols should be narrow and structural.
- Execution emits and dispatches events but does not own plugin discovery.
- Stores persist event, failure, and observer-link facts but do not execute
  sinks.
- Plugins load entry points into a supplied registry but do not own event
  payloads, names, ordering, or failure policy.
- Diagnostics and CLI read public APIs and store/read-model facts.

Failure modes and diagnostics:

- Malformed event records raise clear event/store errors with file or record
  context.
- Unsupported event persistence, explicit persistence-disabled sink dispatch,
  unsupported callback failure persistence, duplicate sink names, invalid plugin
  shapes, and callback failures should be visible through diagnostics or
  preflight where practical.
- Callback failures do not change run correctness by default.
- Strict audit failure remains deferred.

Extension points and flexibility boundaries:

- Event resources and payloads remain generic plain-data facts.
- Event sink registry instances are explicit and local to a configured runtime
  path; no global ambient registry.
- Sink context exposes only observer-link writeback and immutable event/run
  identity, not broad store or lifecycle mutation APIs.
- Plugin loading accepts simple trusted extension shapes but does not solve
  sink configuration; configured sinks should be created through project setup
  or config-built objects and registered programmatically.

Generic interfaces, adapters, and protocols:

- `EventSink` is a generic observer protocol over `PipelineEventRecord`.
- `EventSinkRegistry` is a deterministic registry keyed by sink name.
- `EventSinkContext` is a narrow observer adapter, not a general runtime handle.
- Store facets remain plain append/read contracts for events, callback
  failures, and observer links, while the sink-facing context remains a narrow
  structural protocol rather than a broad store import.
- Plugin loader is an adapter into the registry, not a semantic layer.

Future-roadmap compatibility:

- Stage 21 cleanup can add cleanup candidate/outcome event resource kinds
  without changing sink protocol shape.
- Service-specific sinks can be separate packages over `EventSink`.
- Distributed streaming can be implemented as a future sink or adapter over
  ordered events.
- Strict audit mode can reuse failure records and dispatch results.
- Export/import, run catalogs, comparisons, and provenance can consume event
  records as audit facts.

Maintainability assessment:

- The design keeps one canonical event-record family and centralizes projection,
  append, dispatch, and failure policy. This reduces duplicate event semantics
  but requires a maintained schema-v1 compatibility layer.
- Separating `event_sinks` from `events` avoids turning the record module into
  plugin infrastructure.
- Narrow store facets for observer links and callback failures reduce the risk
  of arbitrary metadata coupling.

Extensibility assessment:

- Generic event resources, instance-local registries, and explicit plugin
  adapters leave room for new stores, executors, cleanup records, and external
  sinks.
- The design deliberately avoids service-specific fields and dependencies.
- Future strict or streaming modes can wrap the dispatch/failure contracts
  without replacing the event grammar.

Flexibility and expansion assessment:

- The event grammar can add resource kinds and payload conventions through
  schema-versioned records.
- Plugin loading can remain optional and explicit even as more groups become
  loadable.
- CLI/read-model presentation can expand later without making CLI the event
  semantics owner.

Scalability and future compatibility:

- Event ordering remains per-run and append-oriented; distributed streaming is
  out of scope.
- Bounded payloads and redaction requirements are necessary to keep event logs
  useful for long runs.
- Explicit persistence-disabled behavior is accepted as an auditability
  tradeoff, with a strict-mode revisit trigger.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Maintain schema-v1 event projection. | Existing `PipelineEventRecord` and `events.jsonl` readers must remain compatible. | Revisit when a documented compatibility window can remove or archive v1 projection. |
| Explicit persistence disable weakens durable callback-failure evidence. | User confirmed persistence is default for sink-enabled runs but can be disabled. | Revisit when strict audit mode is planned or users need sink dispatch to require persistence. |
| Event sink plugin accepted shapes exclude configured constructors. | Keeps plugin loading explicit and simple; configured sinks can be created through project setup or config and registered programmatically. | Revisit if downstream plugins need declarative configuration at the plugin-loader layer. |
| Non-durable sink dispatch uses in-process sequence only. | Explicit persistence disable must remain possible, but it weakens durable ordering and callback-failure evidence. | Revisit when strict audit mode is planned or if users need sink dispatch to require persistence. |

## Examples And Demonstrations

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| Ordered lifecycle event audit log | Run and stage lifecycle events are ordered, typed, resource-linked, and readable without project code imports. | Local run store, authority-compatible event reads, and existing `events.jsonl`. | Unit, contract, integration, and feature-doc example. | confirmed |
| Schema-v1 compatibility readback | Existing schema-v1 `PipelineEventRecord` lines remain readable or projectable through the selected compatibility helper. | Current local `events.jsonl` and store readers. | Unit fixture, local-store integration, and package/API tests. | confirmed |
| Committed reliability fact projection | Stage 19 retry, timeout, submission, and transaction facts appear as events without redefining reliability policy. | Approved Stage 19 reliability records and runner/lifecycle facts. | Unit tests with fake committed facts and integration tests where Stage 19 records are available. | confirmed |
| Programmatic observe-only sink dispatch | Registered sinks receive committed events after append/projection and cannot mutate core runtime state. | Instance-local `EventSinkRegistry` and fake sinks. | Unit, package/API, and mutation-boundary tests. | confirmed |
| Best-effort sink callback failure | A failing sink produces a visible callback failure record and execution continues without recursive ordinary sink dispatch. | Programmatic fake sink and callback failure store/read model. | Unit and integration failure-injection tests. | confirmed |
| Explicit persistence-disabled dispatch | If persistence is explicitly disabled, dispatch uses a non-durable event envelope and diagnostics warn about reduced inspectability. | Sink-enabled run with explicit persistence opt-out. | Unit tests for non-durable identity and diagnostics/preflight tests. | confirmed |
| Narrow observer-link writeback | Sinks can write explicit external links or observer references through a narrow API, not broad run metadata or state mutation. | Observer-link context and store/read model. | Unit, contract, and integration tests for serialization and mutation boundaries. | confirmed |
| Explicit plugin sink loading | `loom.event_sinks` entry points load only through explicit user or programmatic action and register with deterministic names. | Plugin discovery with fake entry points. | Unit and contract tests updating future-group readiness from listing-only to registry-ready. | confirmed |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package/API and import boundaries | Public event and sink APIs are reachable from intended packages without importing plugins, CLI, concrete stores, executors, or service clients. | Package and import-boundary. | Package/import tests. | `tests/package/test_pipeline_store_api.py`, `tests/package/test_plugins_api.py`, `tests/package/test_import_boundaries.py`. | confirmed |
| Event model serialization | Versioned event records, event resources, causal links, and bounded plain-data payloads round trip and reject malformed shapes. | Unit and package. | Event model tests. | `tests/unit/loom/pipeline/test_events.py` plus package API coverage. | confirmed |
| Event compatibility | Existing schema-v1 records remain readable or projectable through the selected compatibility path. | Unit, contract, integration. | Compatibility fixture and store-read tests with old-shaped records. | `tests/unit/loom/pipeline/test_events.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/integration/pipeline/test_local_stores.py`. | confirmed |
| Store event, failure, and observer-link facets | Local and authority-compatible stores append/read ordered events and expose callback failure and observer-link records without treating events as current state. | Unit, contract, integration. | Store contract and backend tests. | `tests/contracts/test_store_contract.py`, `tests/contracts/test_authority_store_contract.py`, store unit tests, and local/sqlite/service integration tests as affected. | confirmed |
| Event ordering and committed-fact projection | Events are appended/projected after durable state transitions and have deterministic per-run ordering. | Unit and integration. | Runner, lifecycle, eventing, and store tests. | `tests/unit/loom/pipeline/execution/test_eventing.py`, `test_runner.py`, `test_lifecycle.py`, and local execution integration tests. | confirmed |
| Sink registry and dispatch | Registered sinks receive committed events, dispatch results are explicit, duplicate/replace behavior is deterministic, and sinks cannot mutate core runtime state. | Unit, package, contract. | Fake sink and registry tests. | New `tests/unit/loom/pipeline/test_event_sinks.py` or equivalent plus package/import tests. | confirmed |
| Callback failures and non-durable dispatch | Sink failures are recorded and best-effort by default; non-persistent dispatch carries non-durable identity and warning semantics. | Unit and integration. | Failure injection and diagnostics tests. | New sink tests plus execution integration and diagnostics tests where the runtime path is wired. | confirmed |
| Plugin loading | Event sink plugins load only through explicit action, accepted shapes are validated, names are deterministic, and plugin group readiness updates intentionally. | Unit and contract. | Entry point adapter tests. | `tests/unit/loom/plugins/test_entrypoints.py`, `tests/unit/loom/plugins/test_adapters.py`, `tests/contracts/test_plugin_discovery_contract.py`, `tests/contracts/test_plugin_future_groups_contract.py`. | confirmed |
| Preflight and CLI | Warnings and inspection are read-only, capability-aware, and do not load event sink plugins ambiently. | Unit, contract, integration when surfaces change. | Diagnostics and CLI tests. | `tests/unit/loom/diagnostics/test_diagnostics_preflight.py`, `tests/unit/loom/diagnostics/test_preflight_plugins.py`, `tests/contracts/test_cli_preflight_contract.py`, CLI tests if inspection commands are added. | confirmed |
| Feature docs | Feature docs describe event grammar, observe-only sink contracts, callback failure defaults, plugin loading, and inspection boundaries. | Docs review and relevant doc tests. | Documentation updates. | `docs/features/reliability.md`, `docs/features/plugins.md`, `docs/features/run-store.md`, `docs/features/provenance.md`, `docs/features/preflight.md`, `docs/features/cli.md` as affected. | confirmed |
| Final validation | Standard PR gates pass after implementation planning and phase work. | Full project gate. | Repository validation. | `make validate-pr`, then `make test-summary` before PR preparation. | confirmed |

## Phase Sketch

### Phase 1 - Event Grammar And Compatibility

Goal:

- Evolve the canonical event record family to the Stage 20 grammar while
  preserving schema-v1 event read compatibility.

Scope:

- Add event id, occurred timestamp semantics, event name, primary and related
  resources, causal predecessor, and bounded payload conventions to the
  canonical `PipelineEventRecord` path.
- Add schema-v1 projection/read compatibility for existing `events.jsonl` and
  store records.
- Update local and authority-compatible event read/append tests where the
  grammar touches persisted shapes.

Out of scope:

- Event sink dispatch, plugin loading, broad CLI presentation, cleanup, service
  clients, and strict audit mode.

Acceptance criteria:

- Old schema-v1 records are still readable or projectable.
- New records are ordered, typed, resource-linked, plain-data-compatible, and
  useful without importing project code.
- Event record imports remain dependency-light.

Test expectations:

- Package: public event APIs and import-boundary coverage.
- Unit: event record/resource/compatibility validation.
- Contract: store compatibility where record shape is contractual.
- Integration: local store `events.jsonl` read/write compatibility.
- E2E: not required for this phase.
- Opt-in: none.

Design impact:

- Public event grammar changes, with explicit compatibility debt.

Future compatibility:

- Future cleanup, streaming, service sinks, and export/import features should
  consume one canonical event family.

Alternatives rejected:

- Parallel runtime event family and eager local log rewrite.

Debt introduced:

- Schema-v1 projection remains maintained compatibility debt.

Reviewability:

- Keep this phase focused on records, compatibility helpers, and store-facing
  tests.

### Phase 2 - Sink Registry And Observer Facts

Goal:

- Add the import-light event sink contract, registry, dispatch result, callback
  failure facts, and observer-link writeback surface without runtime plugin
  loading.

Scope:

- Add `loom.pipeline.event_sinks` with `EventSink`, `EventSinkRegistry`,
  `EventSinkContext`, dispatch results, failure records, and narrow structural
  observer-link recorder protocols.
- Add store/read-model support for callback failure and observer-link facts as
  needed by the dispatch contract.
- Prove registry behavior with fake sinks and mutation-boundary tests.

Out of scope:

- Entry point loading, service-specific sinks, ambient global registries, and
  broad run metadata or lifecycle mutation handles.

Acceptance criteria:

- Registries are instance-local and explicit.
- Sinks receive event-shaped inputs and narrow context only.
- Callback failure and observer-link facts are plain-data-compatible and
  inspectable.
- `loom.pipeline.event_sinks` does not import store modules or broad store
  protocols.

Test expectations:

- Package: `event_sinks` API and import-boundary tests.
- Unit: registry, dispatch result, failure record, and observer-link tests.
- Contract: store facets for failure/link records where added.
- Integration: local backend read/write coverage where records persist.
- E2E: not required.
- Opt-in: none.

Design impact:

- New public protocol/module surface.

Future compatibility:

- Streaming adapters, strict audit mode, and service plugins can wrap the same
  registry and failure/link contracts.

Alternatives rejected:

- Global ambient registry, broad store handles, plugin-owned event semantics,
  and recursive ordinary failure dispatch by default.

Debt introduced:

- Observer-link schema starts intentionally narrow.

Reviewability:

- Keep store facets and sink protocol changes close together so observe-only
  boundaries are easy to audit.

### Phase 3 - Runtime Dispatch From Committed Facts

Goal:

- Wire event append/projection and sink dispatch into runtime paths after
  durable facts exist.

Scope:

- Centralize append/project/dispatch ordering for runner, lifecycle, and
  Stage 19 reliability facts.
- Enable event persistence by default when sinks are explicitly configured
  unless disabled.
- Implement explicit persistence-disabled dispatch through a non-durable event
  envelope with warning diagnostics.
- Record callback failures best-effort without changing run correctness.

Out of scope:

- Plugin-discovered loading, strict audit failure mode, distributed streaming,
  cross-run retry budgets, resource-aware retry escalation, and cleanup.

Acceptance criteria:

- Sinks see only committed facts.
- Dispatch follows append/projection when persistence is enabled.
- Persistence-disabled dispatch is clearly non-durable and diagnostic-visible.
- Callback failures are visible and do not recursively dispatch to ordinary
  sinks by default.

Test expectations:

- Package: no new broad exports.
- Unit: eventing, runner, lifecycle, non-durable dispatch, and failure policy.
- Contract: store assumptions remain stable.
- Integration: local execution, resume/failure paths, and Stage 19 fact
  projection where available.
- E2E: not required unless an existing CLI run path must prove end-to-end
  inspection.
- Opt-in: none.

Design impact:

- Runtime ordering and default persistence behavior change.

Future compatibility:

- Strict audit mode can later reject persistence-disabled sink dispatch without
  changing the basic event grammar.

Alternatives rejected:

- Dispatch before durable fact commit and sink-driven state mutation.

Debt introduced:

- Explicit persistence disable weakens durable auditability.

Reviewability:

- Keep dispatch ordering tests close to runtime integration points.

### Phase 4 - Plugins, Diagnostics, Inspection, And Docs

Goal:

- Expose explicit event sink plugin loading and narrow operational visibility
  once records, registry, and runtime dispatch are stable.

Scope:

- Add `loom.plugins.event_sinks.load_event_sink_entry_points` or equivalent
  explicit loader after registry stability.
- Update plugin readiness contracts for `loom.event_sinks`.
- Add preflight warnings for unsupported persistence, sink registration, and
  callback failure policy where practical.
- Add narrow read-only event/failure/link inspection only if existing CLI/read
  surfaces support it cleanly.
- Update feature docs and run full validation evidence.

Out of scope:

- Ambient plugin loading, configured plugin constructors in the loader,
  service-specific sinks, mutating event CLI, cleanup, retention, and strict
  audit mode.

Acceptance criteria:

- Plugin-discovered event sinks load only through explicit user or
  programmatic action.
- Invalid plugin shapes and registration failures are reported clearly.
- Diagnostics and CLI remain readers and do not define event semantics.
- Feature docs and validation evidence are complete.

Test expectations:

- Package: plugin API/import coverage.
- Unit: plugin loader, diagnostics, and CLI/read-model tests as affected.
- Contract: plugin discovery/readiness and CLI/preflight contracts as affected.
- Integration: diagnostics/CLI tests where a surface changes.
- E2E: not required unless a new user-facing CLI inspection command requires
  end-to-end coverage.
- Opt-in: no network or service-plugin tests.

Design impact:

- Plugin group readiness changes from listing-only to registry-ready.

Future compatibility:

- Service-specific MLflow, W&B, webhook, notification, or streaming sinks remain
  external plugins over the generic Stage 20 model.

Alternatives rejected:

- Ambient plugin load at runtime startup and plugin-layer ownership of event
  payload semantics.

Debt introduced:

- Loader accepted shapes intentionally exclude configured constructors.

Reviewability:

- Place plugin, diagnostics, docs, and final validation together after core
  event/sink semantics are already stable.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | Roadmap extraction, intent, capability triage, functionality agreement, and behavior baseline are confirmed. | pass | None. |
| Requirement-to-design traceability | Proposed implementation shape, design queue, decisions, and practical design notes trace to FR-1 through FR-6. | pass | None. |
| Design-safety review completed | Managing-agent design-safety review passed after DSR-1 and DSR-2 planning revisions. | pass | None. |
| Future-roadmap impact considered | Stage 21 cleanup, service-specific plugins, distributed streaming, strict audit mode, export/import, run catalogs, and provenance touchpoints are recorded and were reviewed during design-safety review. | pass | None. |
| Generic interface, adapter, and protocol flexibility considered | Event resources, sink protocol, registry, context, store facets, and plugin adapter shapes are recorded and were reviewed during design-safety review. | pass | None. |
| Example-to-validation traceability | Confirmed examples map to package/API, unit, contract, integration, diagnostics/CLI, docs, and final validation obligations. | pass | None. |
| Phase-shaping readiness | Four implementation-plan phases are sketched with scope, out-of-scope boundaries, acceptance criteria, test obligations, design impact, future compatibility, alternatives, debt, and reviewability. | pass | None. |
| Unresolved blocked or needs-discussion functionality or design decisions | Functionality and design queues have no unresolved `needs discussion` or `blocked` items. | pass | None. |

Readiness result:

- Status: ready for implementation-plan drafting
- Implementation-plan drafting blockers:
  - None. Final planning confirmation received on 2026-05-17.
- Accepted risks:
  - Stage 19 implementation is not yet merged in this checkout; Stage 20
    planning assumes Stage 19 approved records remain broadly compatible.
  - Explicitly disabling event persistence for sink-enabled runs weakens durable
    auditability.
- Assumptions to carry forward:
  - Events remain audit facts, not authoritative current state.
  - Event sink registration is explicit trusted code setup.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Does the user have clarifying questions about the Stage 20 briefing? | Roadmap framing | Answer before moving to capability triage. | resolved; user agreed with briefing |
| What should Stage 20 optimize for relative to the roadmap description? | Target audience, user-visible outcome, capability prioritization | Prioritize audit-ready compatibility and generic observe-only extensibility. | confirmed |
| Which workflows, done criteria, constraints, and non-goals should drive Stage 20 capability triage? | Intent discovery | Audit/debug timelines, observer/plugin integration, callback failure inspection, visible best-effort failures, compatibility, and no service-specific delivery or cleanup. | confirmed |
| Should the proposed capability include/defer set drive functionality agreement? | Capability triage | Include event grammar, compatibility, committed-fact projection, registry, dispatch, callback failure records, plugin loading, preflight, narrow persistence defaults, and narrow inspection; defer service delivery, streaming, strict mode, cleanup/retention, cross-run retry budgets, and resource-aware retry escalation. | confirmed |
| Should sinks be allowed to write explicit external-link metadata back into run metadata through narrow store APIs? | Functional scope and observer boundary | Include narrow explicit metadata/link writeback, not core state mutation. | confirmed |
| Should event persistence become enabled by default when event sinks are explicitly configured? | Defaults, storage volume, diagnostics | Yes unless explicitly disabled, per feature-doc recommendation. | confirmed |
| Is the drafted behavior baseline complete enough to checkpoint functionality and behavior before design agreement? | Functionality and behavior confirmation | Confirm included behavior, defaults, failure behavior, unsupported behavior, and deferrals as drafted. | confirmed |
| Are there unresolved high-impact design-agreement questions before design-safety review? | Design agreement review | No. All design decisions are recorded recommendations or auto-approved candidates. | resolved |
| Did design-safety review pass? | Design safety review | Yes, after tightening import boundaries and non-durable dispatch identity semantics. | confirmed |
| Is the examples and validation strategy accepted? | Examples and validation strategy | Yes. Examples and suite obligations are confirmed from the design-safety-constrained plan. | confirmed |
| Is the phase shape accepted? | Phase shaping | Yes. Use four phases: event grammar/compatibility, sink registry/observer facts, runtime dispatch, then plugins/diagnostics/inspection/docs. | confirmed |
| Does the user confirm the completed planning artifact is ready for implementation-plan drafting? | Final planning confirmation | User approved on 2026-05-17; draft `docs/roadmap/stage-20/implementation-plan.md` from this artifact. | confirmed |

## Handoff Notes

Implementation-plan draft inputs:

- Ready. Functionality, behavior, design agreement, design-safety review,
  examples, validation strategy, phase shaping, implementation readiness, and
  final planning confirmation are recorded.

Design-safety review result:

- Passed. Required planning revisions were applied for `event_sinks` import
  boundaries and non-durable sink dispatch identity semantics.

Validation and phase-shaping inputs:

- Confirmed validation areas, examples, and four-phase sketch are recorded.

Plan-quality-gate risks:

- Event schema compatibility and sink observe-only boundaries are likely the
  highest-risk plan-quality areas.
- Implementation-plan review should specifically verify schema-v1 compatibility
  evidence, persistence-disabled dispatch warnings, observer-link writeback
  scope, import boundaries, and whether phase scopes preserve the
  programmatic-before-plugin-loading sequence.

Assumptions to carry forward:

- Core Loom remains domain-neutral and does not ship service-specific
  notification, tracking, telemetry, or streaming clients.
- Plugin loading remains explicit.
- Existing local event records need a compatibility path.
