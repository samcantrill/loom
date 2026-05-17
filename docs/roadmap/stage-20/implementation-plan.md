# Roadmap Stage 20 Implementation Plan: Runtime Events And Event Sinks

Status: Phase 2 merged; Phase 3 in progress
Roadmap stage: `v20`
Planning document: `docs/roadmap/stage-20/planning.md`
Workflow: `.codex/workflows/roadmap-stage-implementation.md`
Target branch: `develop`
Current phase: Phase 3 `runtime-event-dispatch` in progress
Blockers:

- None. Implementation-plan quality gate passed on 2026-05-17 after
  `loom_plan_reviewer` review, bounded refinement, and confirmation review.

## Summary

- Goal: implement audit-ready runtime event records and observe-only event sink
  contracts over committed Loom facts without making observers part of
  execution correctness.
- Source functionality-agreement gate: confirmed in
  `docs/roadmap/stage-20/planning.md`; FR-1 through FR-6 are closed.
- Approved behavior: events are audit facts, not current state; event records
  remain compatible with existing schema-v1 logs; event sinks are explicit,
  trusted, observe-only callbacks; event persistence is enabled by default when
  sinks are explicitly configured unless disabled; callback failures are
  visible and best-effort.
- Source behavior confirmation: complete in the planning artifact after user
  approval of behavior, design agreement, design-safety review, examples,
  validation strategy, and four-phase split.
- Key design constraints: keep Loom domain-neutral, dependency-light,
  import-light, plain-data-compatible, fake/local-test friendly, and explicit
  about Stage 19 reliability inputs and Stage 21 cleanup boundaries.
- Source design-agreement gate: confirmed. Use one canonical versioned
  `PipelineEventRecord` family with schema-v1 projection; add import-light
  `loom.pipeline.event_sinks`; append/project committed events before sink
  dispatch; persist callback failures and observer links as event-adjacent
  facts; load plugins only through explicit `loom.plugins.event_sinks` action.
- Future-roadmap impact: Stage 21 cleanup can later reuse event resources
  without Stage 20 performing deletion; service-specific MLflow, W&B, webhook,
  notification, OpenTelemetry, or streaming sinks remain external plugins over
  the generic Stage 20 model.
- Reusable interface, adapter, or protocol assumptions: event resources,
  event records, `EventSink`, `EventSinkRegistry`, `EventSinkContext`,
  dispatch results, callback failure records, observer-link records, narrow
  structural context protocols, and plugin-loading adapters remain generic and
  store/executor/service neutral.
- Examples covered: ordered lifecycle audit logs, schema-v1 compatibility,
  committed Stage 19 fact projection, observe-only sink dispatch, best-effort
  callback failure records, non-durable explicit persistence opt-out dispatch,
  narrow observer-link writeback, and explicit event-sink plugin loading.
- Source phase shaping: four phases confirmed in the planning artifact.
- Source plan quality gate: passed on 2026-05-17.
- Out of scope: cleanup and deletion operations, retention enforcement,
  run-collection GC, service-specific notification/tracking sinks, distributed
  streaming, strict audit-failure mode, cross-run retry budgets,
  resource-aware retry escalation, event-driven mutation of core runtime facts,
  and domain-specific metric/tracking semantics.

## Goal

Stage 20 turns Loom's existing lifecycle event foundation into a durable,
audit-ready runtime event contract and introduces a narrow event sink API for
external observers.

Users should be able to inspect ordered, typed, resource-linked runtime events
without importing project code, and trusted integration code should be able to
observe committed runtime facts without mutating plans, configs, artifacts,
stage outputs, statuses, retry decisions, transaction records, or core store
records.

## Context

Current source already includes the foundations Stage 20 builds on:

- `loom.pipeline.events` defines schema-v1 `PipelineEvent`,
  `PipelineEventRecord`, run/stage scopes, plain-data payload validation, and
  strict serialization.
- `loom.pipeline.execution.eventing` emits current run and stage lifecycle
  events through a `RunEventStore`.
- `loom.pipeline.stores` exposes `RunEventStore` append/read behavior and local
  `events.jsonl` persistence.
- Local, SQLite authority, service authority, and fake authority paths already
  exercise ordered event append/read behavior.
- `loom.plugins.entrypoints` defines `LOOM_EVENT_SINKS_GROUP`, while contract
  tests currently keep event sinks listing-only until registry contracts land.
- Stage 19 planning and implementation planning define the retry, timeout,
  transaction, and failure facts Stage 20 should project after those facts are
  committed.

The implementation must preserve authority/store facts as the source of truth.
Events are append-only audit projections, and sinks observe those projections;
neither becomes a parallel execution or state authority.

## Planning Readiness

- Source planning notes: `docs/roadmap/stage-20/planning.md`
- Functionality and behavior baseline: complete. The notes lock event grammar,
  schema-v1 compatibility, committed-fact projection, programmatic registry,
  observe-only dispatch, narrow observer-link writeback, callback failure
  records, explicit plugin loading, preflight warnings, persistence defaults,
  and narrow read-only inspection.
- Design-safety review: passed. The review required two revisions: keep
  `loom.pipeline.event_sinks` independent of store modules and broad store
  protocols, and make persistence-disabled dispatch identity explicitly
  non-durable.
- Examples and validation strategy: complete. Validation is package/import,
  unit, contract, integration, diagnostics/CLI, docs, and final-suite focused.
- Phase shaping: complete. Four phases are recorded below.
- Implementation readiness blockers from planning: none after final planning
  confirmation on 2026-05-17.
- Accepted risks and revisit triggers:
  - Stage 19 implementation is not yet merged in this checkout. Revisit if
    final Stage 19 reliability facts materially differ from the approved
    implementation-plan assumptions.
  - Schema-v1 event projection is compatibility debt. Revisit when a documented
    compatibility window can remove or archive v1 projection.
  - Explicitly disabling event persistence weakens durable auditability. Revisit
    when strict audit mode is planned or users need sink dispatch to require
    persistence.
  - Observer-link schema starts intentionally narrow. Revisit if downstream
    integrations need richer observer summaries.
  - Plugin loader accepted shapes exclude configured constructors. Revisit if
    downstream plugins need declarative sink construction at the plugin-loader
    layer.

## Desired Outcome

When all phases are complete:

- `loom.pipeline.events` provides canonical versioned event records, event
  resource refs, event ids, occurred timestamps, event names, primary and
  related resources, payload conventions, causal predecessor links, and
  schema-v1 compatibility projection.
- Local `events.jsonl` remains append-only and machine-readable.
- Store/read-model paths expose ordered event records, callback failure facts,
  and narrow observer-link facts without treating events as current state.
- `loom.pipeline.event_sinks` provides import-light `EventSink`,
  `EventSinkRegistry`, `EventSinkContext`, dispatch result, callback failure,
  observer-link, and structural context protocol types.
- Runtime execution appends/projects events only after durable facts exist and
  dispatches sinks after append/projection.
- Persistence-disabled sink dispatch, when explicitly selected, uses
  non-durable event envelopes and produces warning diagnostics.
- Callback failures are recorded and best-effort by default.
- `loom.plugins.event_sinks` or equivalent explicit loader registers
  `loom.event_sinks` entry points only when requested.
- Diagnostics and CLI/read models, where implemented, present event
  persistence, sink registration, callback failure, and observer-link facts as
  read-only information.

## Non-Goals

- No cleanup, deletion, retention enforcement, artifact GC, or run-collection
  GC.
- No service-specific sinks or bundled clients for MLflow, W&B, Slack, email,
  Teams, PagerDuty, webhook delivery, OpenTelemetry, hosted telemetry, or
  streaming systems.
- No distributed event streaming or strict audit-failure mode.
- No cross-run retry budgets, resource-aware retry escalation, or reliability
  policy changes beyond projecting committed Stage 19 facts.
- No event-driven mutation of plans, configs, artifacts, stage outputs,
  statuses, retry decisions, transaction records, or core store records.
- No ambient plugin loading, global sink registry, or import-time sink
  discovery.
- No broad event-management or mutating sink CLI.
- No domain-specific metric extraction, model/checkpoint semantics, or project
  tracking keys in core event contracts.

## Constraints

- Follow `docs/structure.md` boundaries and `docs/GLOSSARY.md` vocabulary.
- Keep `loom.pipeline.events` and `loom.pipeline.event_sinks` import-light.
  They must not import concrete stores, executors, diagnostics, CLI modules,
  plugin discovery, optional service SDKs, or backend clients.
- `loom.pipeline.event_sinks` must not import `loom.pipeline.stores` or broad
  store protocols. Sink context/writeback protocols must be narrow and
  structural.
- Stores persist event, callback failure, and observer-link facts but do not
  execute sinks.
- Execution emits/projects events and dispatches explicitly supplied
  registries but does not own plugin discovery.
- Plugins load entry points into supplied registries but do not own event
  payloads, names, ordering, or failure policy.
- Diagnostics and CLI read public APIs and store/read-model facts.
- Event records and persisted facts must remain strict, versioned where needed,
  and plain-data-compatible.
- Every phase PR must run targeted validation, `make validate-pr`, and
  `make test-summary` unless a command is unavailable and the phase PR records
  the reason.

## Design Principles

- Committed facts before events. Runtime events project facts only after the
  corresponding state, submission, reliability, transaction, or callback fact
  exists.
- Events before sink dispatch. Sink callbacks observe the event record or
  explicitly non-durable event envelope after append/projection.
- One canonical event family. Avoid parallel runtime event types unless the
  plan quality gate finds a blocker in the compatibility approach.
- Observe-only by construction. Sinks receive narrow context and cannot mutate
  core runtime correctness.
- Explicit setup over ambient behavior. Registries and plugin loading are
  supplied by trusted project/runtime setup, not loaded globally or at import
  time.
- Read models over log scraping. Diagnostics and CLI inspect public records and
  read models rather than parsing executor logs or treating event logs as
  current state.
- Generic contracts first. Service-specific delivery, metric extraction, and
  streaming adapters remain downstream integrations.

## Key Design Choices

| Decision | Selected approach | Consequence |
| --- | --- | --- |
| Event grammar | Evolve canonical `PipelineEventRecord` to Stage 20 grammar with schema-v1 projection | One event family serves stores, audit logs, sinks, future cleanup, and service plugins |
| Compatibility | Keep existing local records readable/projectable; do not rewrite old logs eagerly | Adds maintained compatibility debt but protects existing `events.jsonl` readers |
| Resource vocabulary | Add generic primary/related event-resource refs and bounded payload conventions | Future consumers avoid parsing unstable payload-only subjects |
| Emission ordering | Commit fact, append/project event, then dispatch sinks | Observers never see facts that failed to commit |
| Persistence opt-out | Enable persistence by default for sink-enabled runs; explicit disable uses non-durable envelope and warning | Preserves user opt-out while making audit weakness visible |
| Sink module | Add `loom.pipeline.event_sinks` for protocols, registry, dispatch result, failure records, and narrow context | Separates strict records from observer mechanics without importing stores |
| Writeback | Allow only narrow observer-link/external-reference facts through explicit context | Integrations can add traceability without arbitrary run metadata mutation |
| Callback failures | Persist event-adjacent failure facts and do not recursively dispatch ordinary failure events by default | Failures are visible without callback loops |
| Plugin loading | Add explicit `loom.plugins.event_sinks` loader after registry stability; entry point name is deterministic registry name | Plugin discovery remains opt-in and separate from event semantics |
| CLI and diagnostics | Add cheap warnings and narrow read-only inspection only where useful | Presentation does not own event behavior |

## Event And Envelope Schema Contract

Phase execution plans may choose helper names and internal class layout, but
they must preserve the semantic field contract below unless the implementation
plan is updated and reviewed again.

Canonical durable event records:

| Field | Stage 20 contract | Compatibility requirement |
| --- | --- | --- |
| `schema_version` | New records use the next event schema version, expected to be `2`. | Schema-v1 records remain readable through projection. |
| `event_id` | Stable event identifier stored with new durable records. | Schema-v1 projection derives a deterministic compatibility id from `run_uri` and `sequence`; it must not rewrite old logs. |
| `run_uri` | Run URI for the event stream and store partition. | Same meaning as schema-v1 `run_uri`. |
| `sequence` | Positive durable per-run append sequence allocated by the store. | Same meaning as schema-v1 `sequence`; do not use this field for non-durable dispatch ordering. |
| `occurred_at` | Timestamp for when the runtime fact occurred. | Schema-v1 `timestamp` projects to `occurred_at`; readers may keep a compatibility alias only as an adapter detail. |
| `event_type` | Canonical public event-name field using the existing dotted lowercase event type convention. | Preserve schema-v1 `event_type`; do not add a separate persisted `event_name` field. |
| `primary_resource` | Plain-data event-resource ref for the subject of the event, with `kind` and stable identifiers such as `run_uri`, `stage_name`, submitted-operation id, transaction id, artifact ref, or callback id. | Schema-v1 run scope projects to a run resource; stage scope projects to a stage resource. |
| `related_resources` | Ordered plain-data tuple/list of additional event-resource refs. | Schema-v1 stage scope should relate the parent run resource. |
| `payload` | Bounded plain-data mapping for stable external projection metadata and selected provenance facts. | Schema-v1 payload projects unchanged unless a documented compatibility helper adds derived resource metadata outside persisted v1 bytes. |
| `causal_predecessor` | Optional event-resource or event-reference link to the causal predecessor. | Schema-v1 records project with no causal predecessor unless the source payload has a documented compatible reference. |

Event sink dispatch input:

| Envelope case | Required identity semantics | Sequence semantics | Callback-failure reference |
| --- | --- | --- | --- |
| Durable dispatch | Envelope references a persisted `PipelineEventRecord` with `durability = "durable"`, `event_id`, `run_uri`, `event_type`, `occurred_at`, and durable `sequence`. | `sequence` is the store-allocated per-run event sequence. Any sink dispatch ordering metadata must not replace durable sequence semantics. | Failure records reference `event_id`, `run_uri`, `event_type`, `durability`, `sequence`, and `occurred_at`. |
| Non-durable dispatch | Envelope carries `durability = "non_durable"`, generated `event_id`, `run_uri`, `event_type`, `occurred_at`, event resources, payload, and warning diagnostics. | `sequence` is absent or null. Use a positive in-process per-run `dispatch_sequence` clearly marked non-durable. Do not fabricate a durable store sequence. | Failure records reference `event_id`, `run_uri`, `event_type`, `durability`, `dispatch_sequence`, and `occurred_at`, and diagnostics must say durable callback-failure inspectability is reduced. |

Callback failure records:

- Include sink name, failure type/message/detail, timestamp, and an event
  reference using the durable or non-durable identity fields above.
- May include a causal predecessor pointing at the triggering event reference.
- Are event-adjacent facts, not ordinary sink-dispatched events by default.

## Conflicts And Tradeoffs

- A canonical event family keeps the public model coherent but requires a
  schema-v1 projection layer. The plan accepts that debt because parallel event
  families would duplicate store and sink semantics.
- Requiring persistence for all sink dispatch would maximize auditability, but
  the planning artifact confirms an explicit disable escape hatch. The plan
  mitigates this with non-durable identity and diagnostics.
- Narrow observer-link writeback is less powerful than passing full store
  handles to sinks, but it preserves observe-only correctness and keeps future
  service plugins from depending on store internals.
- Programmatic registry before plugin loading delays plugin ergonomics, but it
  avoids locking an immature public sink contract.
- CLI inspection is useful only if it fits existing read-only surfaces. The
  plan allows Phase 4 to defer broad CLI presentation while still documenting
  Python/read-model inspection.

## Maintainability Assessment

The four-phase split keeps the highest-risk contract changes reviewable:
records and compatibility first, observer contracts second, runtime ordering
third, and plugin/diagnostic presentation last. This avoids interleaving public
event grammar, store facets, runtime dispatch, and plugin loading in one PR.

The main maintainability constraint is preserving import direction. Event
records and sink protocols must remain plain model/protocol modules. Store
implementations, execution dispatch, plugin discovery, diagnostics, and CLI
presentation should depend on those contracts rather than the reverse.

## Extensibility Assessment

The plan keeps future store backends, executors, cleanup features, event
streams, strict audit mode, and service-specific sinks possible by using
generic event resources, versioned records, instance-local registries, narrow
structural context protocols, and explicit plugin adapters.

Future integrations should consume event records or event sink callbacks over
committed facts. They should not extend core Loom by adding service-specific
fields, dependencies, or semantics to event records.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Schema-v1 event projection | Existing `PipelineEventRecord` and `events.jsonl` readers need compatibility | A documented compatibility window can remove or archive v1 projection |
| Explicit persistence disable weakens durable auditability | Planning confirms persistence is default for sink-enabled runs but can be disabled | Strict audit mode planning or user demand for persistence-required sink dispatch |
| Observer-link schema starts narrow | Prevents broad run metadata/store mutation by sinks | Multiple downstream integrations need richer observer summaries |
| Callback failure facts are event-adjacent rather than recursively dispatched | Avoids callback loops and failure amplification | Users need external monitoring of sink failures through explicit opt-in sinks |
| Plugin loader excludes configured constructors | Keeps initial plugin loading deterministic and simple | Downstream plugins need declarative sink configuration at loader level |
| Stage 19 dependency is planned but not merged in this checkout | Stage 20 needs retry/timeout/transaction facts but should not block planning on local merge state | Final Stage 19 implementation changes committed fact names, IDs, or record shape materially |

## Implementation Workflow State

- Implementation-plan quality gate: passed
- Review pass: complete by `loom_plan_reviewer`; one blocking finding reported
  for public event/envelope schema completeness, with three related concerns
- Refinement pass: complete. The plan now records the event/envelope schema
  contract, Phase 2 persistence ownership, offline evidence/import validation,
  and `docs/structure.md` documentation routing.
- Confirmation review: complete by `loom_plan_reviewer`; no remaining findings
- Automatic merge mode: enabled after phase PRs pass automated review,
  validation, CI, and target-branch gates
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Default phase base/target: `develop`; each phase execution planner must
  recompute and record the actual stack predecessor and PR target before
  creating its worktree.
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`
- Workflow path: expanded path is expected for every phase because Stage 20
  changes public records/protocols, durable facts, runtime dispatch ordering,
  plugin readiness, diagnostics, and possible CLI/read-model behavior.

## Phased Implementation

The phases below are ordered so each PR has a coherent contract boundary:
event records first, sink contracts second, runtime dispatch third, and plugin
or presentation work last. Phase execution plans may refine exact file lists,
but must preserve the programmatic-before-plugin-loading sequence.

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `event-grammar-compatibility` | merged | `codex/event-grammar-compatibility` | [#187](https://github.com/samcantrill/loom/pull/187) | `loom.pipeline.events`, store event readers | Evolve event grammar and preserve schema-v1 compatibility | Package/import, event unit, store contract/integration, `make validate-pr`, `make test-summary` | Ordered audit log, schema-v1 compatibility |
| 2 | `event-sink-registry-observer-facts` | merged | `codex/event-sink-registry-observer-facts` | [#188](https://github.com/samcantrill/loom/pull/188) | `loom.pipeline.event_sinks`, store failure/link facets | Add sink registry, dispatch result, callback failure, and observer-link facts | Package/import, sink unit, store contract/integration, `make validate-pr`, `make test-summary` | Observe-only dispatch, callback failure, observer links |
| 3 | `runtime-event-dispatch` | in_progress | `codex/runtime-event-dispatch` | pending | `loom.pipeline.execution`, lifecycle, eventing | Dispatch events from committed runtime and Stage 19 facts | Eventing/runner/lifecycle unit and integration tests, diagnostics tests, `make validate-pr`, `make test-summary` | Committed fact projection, non-durable opt-out dispatch |
| 4 | `event-sink-plugins-diagnostics` | pending | `codex/event-sink-plugins-diagnostics` | pending | `loom.plugins`, diagnostics, CLI/read models, docs | Add explicit plugin loading, warnings, inspection, docs, and final evidence | Plugin unit/contract, diagnostics/CLI tests as changed, docs, `make validate-pr`, `make test-summary` | Explicit plugin loading, read-only inspection |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Implementation-plan quality gate | Repository workflow | Initial review completed with one blocker; bounded refinement applied; confirmation review found no remaining findings | resolved |

## Phase 1: Event Grammar And Compatibility

Status: merged
Slug: `event-grammar-compatibility`
Branch: `codex/event-grammar-compatibility`
Worktree: `/home/samcantrill/work/loom-worktrees/event-grammar-compatibility`
PR: [#187](https://github.com/samcantrill/loom/pull/187)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase changes public event records
and compatibility behavior

### Scope

- Goal: evolve the canonical event record family to the Stage 20 grammar while
  preserving schema-v1 local event compatibility.
- Files/modules owned:
  - `src/loom/pipeline/events.py` or an adjacent import-light events package
    if the phase plan justifies splitting the module
  - local and authority-compatible event read/write paths as needed
  - event package/API and import-boundary tests
  - event model, local store, and event compatibility tests
- Behavior implemented:
  - The event field contract in `Event And Envelope Schema Contract`,
    including `event_id`, `occurred_at`, canonical `event_type`,
    `primary_resource`, `related_resources`, `causal_predecessor`, durable
    `sequence`, and bounded payload conventions.
  - Schema-v1 projection/read compatibility for existing local `events.jsonl`
    and store records.
  - Strict plain-data serialization and malformed-record errors with useful
    record/file context.
- Decisions applied: one canonical event family, append-only logs, event logs
  as audit facts, schema-v1 compatibility.
- Examples or docs covered: ordered lifecycle audit log and schema-v1
  compatibility readback.
- Out of scope:
  - Event sink registry or dispatch.
  - Callback failure and observer-link persistence.
  - Plugin loading.
  - Broad CLI presentation.
  - Cleanup, service clients, streaming, and strict audit mode.
- Dependencies: confirmed planning artifact and current event/store tests.

### Tasks

- Implement the durable record field names from `Event And Envelope Schema
  Contract`; phase planning may only choose helper/class names and must not
  rename the canonical persisted fields without returning to implementation-plan
  review.
- Add event-resource and causal-link value objects or plain-data contracts.
- Update `PipelineEventRecord` serialization/deserialization and projection
  helpers while preserving schema-v1 behavior.
- Update local and authority-compatible event append/read tests for ordering,
  schema versioning, and malformed record handling.
- Add package/import-boundary tests proving event records avoid plugins, CLI,
  concrete stores, executors, diagnostics, optional service SDKs, and backend
  clients.
- Update feature docs only where grammar compatibility needs immediate
  documentation in this phase.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/test_events.py` | Target event API, import boundaries, serialization, and schema-v1 compatibility | yes |
| `uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py tests/contracts/test_authority_store_contract.py tests/integration/pipeline/test_local_stores.py` | Target event store compatibility and local `events.jsonl` behavior | yes |
| `uv run pytest tests/unit/loom/pipeline/test_offline_evidence.py tests/integration/authority/test_offline_import_api.py` | Target existing event serialization consumers and authority audit-event replay | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: new records round trip, old schema-v1 records read or
  project correctly, and event ordering remains deterministic per run.
- Design-decision evidence: no parallel event family and no eager local log
  rewrite.
- Future-roadmap compatibility evidence: event resources and causal links can
  represent future cleanup, service-sink, streaming, export/import, and
  provenance facts.
- Interface, adapter, or protocol reuse evidence: record helpers are generic
  and store/executor neutral.
- Documentation evidence: docs or docstrings identify compatibility behavior
  and event-as-audit-fact semantics.
- Domain-neutrality evidence: no service-specific fields, metric names, or
  project tracking semantics in core records.

### Phase Workflow State

- Phase execution plan: completed in
  `docs/roadmap/stage-20/phases/event-grammar-compatibility.md`
- Planning/refinement budget: expanded path; draft and refine completed
- Implementation/refinement budget: used
- PR review budget: used by manager local review
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed before PR creation
- Merge record: merged into `develop` by squash merge after final target-branch
  verification and GitHub CI success; merge commit
  `e6564ce250bcb586c86aa0456bf2f6e1fb9b37f5`

### Risks And Stop Conditions

- Risks: breaking existing `events.jsonl`, creating import cycles, hiding
  compatibility failures, or overfitting event resources to Stage 19 only.
- Stop conditions: schema-v1 records cannot be read/projected without silent
  data loss; event record imports require plugins/stores/executors; a parallel
  event family becomes necessary.
- Assumptions: exact Stage 19 fact field names can be projected later through
  Phase 3 adapters if not final in this phase.

### Completion Summary

- Implementation: schema-version 2 `PipelineEventRecord` grammar,
  `EventResourceRef`, `EventReference`, deterministic schema-v1 projection,
  local and authority-compatible v2 persistence, offline evidence/import
  compatibility, focused tests, and minimal reliability docs implemented in
  `codex/event-grammar-compatibility`.
- Validation: `make validate-pr` passed after implementation refinement; `make
  test-summary` passed with overall status passed.
- PR: [#187](https://github.com/samcantrill/loom/pull/187) opened and merged
  against `develop`; final pre-merge verification confirmed base `develop`,
  head `codex/event-grammar-compatibility`, and GitHub CI `checks` success.
- Merge: squash-merged into `develop` at
  `e6564ce250bcb586c86aa0456bf2f6e1fb9b37f5`.
- Follow-up: Phase 2 should start from updated `develop`; no successor branch
  depends on `codex/event-grammar-compatibility`.

## Phase 2: Sink Registry And Observer Facts

Status: merged
Slug: `event-sink-registry-observer-facts`
Branch: `codex/event-sink-registry-observer-facts`
Worktree: `/home/samcantrill/work/loom-worktrees/event-sink-registry-observer-facts`
PR: [#188](https://github.com/samcantrill/loom/pull/188)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates public sink protocols
and durable observer facts

### Scope

- Goal: add an import-light event sink contract, instance-local registry,
  dispatch result model, callback failure record, and narrow observer-link
  writeback surface without runtime plugin loading.
- Files/modules owned:
  - new `src/loom/pipeline/event_sinks.py` or
    `src/loom/pipeline/event_sinks/` package
  - store/read-model facets for callback failures and observer links
  - package/API and import-boundary tests
  - sink registry and fake sink tests
  - store contract and local integration tests for persisted observer facts
- Behavior implemented:
  - `EventSink`, `EventSinkRegistry`, `EventSinkContext`, dispatch result,
    callback failure record, observer-link record, and narrow structural
    observer-link recorder protocols.
  - Deterministic instance-local registry behavior for duplicate/replace or
    duplicate-rejection semantics selected in the phase plan.
  - Plain-data-compatible callback failure and observer-link serialization,
    persistence, and readback.
  - Mutation-boundary tests proving sinks cannot receive broad store or runtime
    mutation handles.
- Decisions applied: programmatic registry first, observe-only by construction,
  no store imports from `event_sinks`, no plugin-owned event semantics.
- Examples or docs covered: observe-only sink dispatch, best-effort callback
  failure record, and narrow observer-link writeback.
- Out of scope:
  - Runtime dispatch wiring.
  - Plugin entry point loading.
  - Service-specific sinks.
  - Global registries or ambient plugin loading.
  - Broad run metadata, lifecycle, retry, transaction, artifact, or status
    mutation APIs.
- Dependencies: Phase 1 event grammar and compatibility.

### Tasks

- Finalize callable/protocol shapes and registry duplicate behavior in the
  phase execution plan.
- Implement sink registry and dispatch result types without importing concrete
  stores, diagnostics, CLI, plugins, executors, or service clients.
- Add callback failure and observer-link records plus narrow structural context
  protocols.
- Add store/read-model facets for failure/link facts in this phase, keeping
  stores as persistence owners and not sink executors. Phase 3 writes runtime
  instances through these facets.
- Add mutation-boundary tests with fake sinks and fake structural contexts.
- Update docs or docstrings for observe-only guarantees and writeback limits.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/test_event_sinks.py` | Target sink API, import boundaries, registry behavior, and mutation boundaries | yes |
| `uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_authority_store_contract.py tests/unit/loom/pipeline/stores tests/integration/pipeline/test_local_stores.py` | Target callback failure and observer-link store/read facets as changed | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: registries are explicit and instance-local, fake sinks can
  be registered/dispatched deterministically, callback failures and observer
  links serialize/read back, and broad mutation handles are absent.
- Design-decision evidence: `loom.pipeline.event_sinks` avoids store imports
  and sinks remain observe-only.
- Future-roadmap compatibility evidence: strict audit mode, streaming adapters,
  and service plugins can wrap the same registry/result/failure/link contracts.
- Interface, adapter, or protocol reuse evidence: context protocols are narrow,
  structural, and store-neutral.
- Documentation evidence: docs or docstrings record writeback limits and
  failure-policy defaults.
- Domain-neutrality evidence: observer links are generic external references,
  not service-specific telemetry fields.

### Phase Workflow State

- Phase execution plan: completed in
  `docs/roadmap/stage-20/phases/event-sink-registry-observer-facts.md`
- Planning/refinement budget: expanded path; draft and refine completed
- Implementation/refinement budget: used after Pyright found missing HTTP
  authority-adapter observer-fact methods and narrow unit test callables
- PR review budget: used by manager local review on 2026-05-17; no blocking
  findings found
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phase 1 merged or valid as stack predecessor
- Merge record: merged into `develop` by squash merge after final target-branch
  verification and GitHub CI success; merge commit
  `f0c9f36c5253f490508e3cb8207a2f21da44cb94`

### Risks And Stop Conditions

- Risks: store/sink import cycle, broad context power, ambiguous duplicate sink
  names, observer-link schema creep, or callback failure recursion.
- Stop conditions: sink context requires full `RunStore`; failure/link records
  need arbitrary run metadata mutation; registry behavior cannot be deterministic
  without a global registry.
- Assumptions: runtime callback invocation and persistence-disabled dispatch are
  Phase 3 scope; the failure/link record types and store/read facets are Phase
  2 scope.

### Completion Summary

- Implementation: import-light event sink contracts, deterministic
  instance-local registry, dispatch result models, callback failure and
  observer-link records, local JSONL observer-fact sidecars, SQLite/service
  authority persistence, authority adapter forwarding, fake authority support,
  package/import tests, unit tests, store contract tests, authority contract
  tests, local integration coverage, and docs updates implemented in
  `codex/event-sink-registry-observer-facts`.
- Validation: targeted package/event-sink suite passed with 72 tests; targeted
  store contract/local integration suite passed with 225 tests; `make
  validate-pr` passed; `make test-summary` passed with overall status passed.
- PR: [#188](https://github.com/samcantrill/loom/pull/188) opened against
  `develop`; verified base `develop`, head
  `codex/event-sink-registry-observer-facts`, state `OPEN`; GitHub CI `checks`
  passed before merge.
- Merge: squash-merged into `develop` at
  `f0c9f36c5253f490508e3cb8207a2f21da44cb94`.
- Follow-up: Phase 3 branch `codex/runtime-event-dispatch` was replayed onto
  updated `develop`; no successor branch still depends on
  `codex/event-sink-registry-observer-facts`.

## Phase 3: Runtime Dispatch From Committed Facts

Status: in_progress
Slug: `runtime-event-dispatch`
Branch: `codex/runtime-event-dispatch`
Worktree: `/home/samcantrill/work/loom-worktrees/runtime-event-dispatch`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase changes runtime ordering,
failure policy, and persistence defaults

### Scope

- Goal: wire event append/projection and sink dispatch into runtime paths after
  durable facts exist.
- Files/modules owned:
  - `src/loom/pipeline/execution/eventing.py`
  - `src/loom/pipeline/execution/runner.py`
  - `src/loom/pipeline/execution/lifecycle.py`
  - `src/loom/pipeline/execution/authority_adapter.py` where needed for
    authority-compatible projection
  - diagnostics/preflight helpers only for persistence-disabled warning paths
  - execution, local store, diagnostics, and integration tests
- Behavior implemented:
  - Central append/project/dispatch helper used by runtime emission points.
  - Event projection from committed run/stage lifecycle, submission, retry,
    timeout, and transaction facts where Stage 19 facts are available.
  - Event persistence enabled by default when sinks are explicitly configured
    unless disabled.
  - Explicit persistence-disabled dispatch through the non-durable event
    envelope semantics defined in `Event And Envelope Schema Contract`, with
    event id, occurred timestamp, in-process per-run dispatch sequence, and
    warning diagnostics.
  - Best-effort callback failure recording without changing run correctness and
    without recursively dispatching ordinary failure events by default.
- Decisions applied: committed facts first, event append/projection second,
  sink dispatch third, visible best-effort failures, explicit non-durable
  opt-out semantics.
- Examples or docs covered: committed reliability fact projection,
  non-durable opt-out dispatch, and callback failure behavior in runtime path.
- Out of scope:
  - Plugin-discovered loading.
  - Strict audit mode.
  - Distributed streaming.
  - Cleanup and retention.
  - Event-driven retry or status mutation.
  - Cross-run retry budgets and resource-aware retry escalation.
- Dependencies: Phases 1 and 2; Stage 19 facts if merged or available as stack
  predecessor.

### Tasks

- Define the central append/project/dispatch helper shape in the phase
  execution plan before implementation.
- Wire run/stage lifecycle events through the new ordering helper.
- Project Stage 19 reliability, retry, timeout, and transaction facts if
  available; otherwise add compatibility shims or documented deferrals that do
  not invent reliability semantics.
- Add explicit registry/config plumbing without ambient plugin loading.
- Implement default persistence behavior for sink-enabled runs and explicit
  persistence-disable warnings.
- Record callback failures best-effort with causal references to the triggering
  event/envelope, using the Phase 2 store/read facets.
- Add integration tests proving sinks see committed facts and observer failures
  do not change run correctness.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/execution/test_eventing.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/test_event_sinks.py` | Target append/project/dispatch ordering and failure policy | yes |
| `uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_local_stores.py` | Exercise local runtime event ordering, resume/failure paths, and store reads | yes |
| `uv run pytest tests/unit/loom/diagnostics tests/integration/diagnostics` | Target persistence-disabled warnings or preflight behavior as changed | yes, if diagnostics changed |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: runtime sinks receive only committed facts, dispatch follows
  append/projection when persistent, non-durable envelopes are marked as such,
  and callback failures remain best-effort.
- Design-decision evidence: no sink-driven mutation and no dispatch before
  committed fact/event availability.
- Future-roadmap compatibility evidence: strict audit mode can later reject
  non-durable dispatch and streaming adapters can consume the same envelope.
- Interface, adapter, or protocol reuse evidence: dispatch helper accepts
  explicit registry/context inputs and works with fake/local tests.
- Documentation evidence: docs or notes describe default persistence and
  explicit opt-out warnings.
- Domain-neutrality evidence: runtime events avoid service-specific delivery or
  tracking semantics.

### Phase Workflow State

- Phase execution plan: completed in
  `docs/roadmap/stage-20/phases/runtime-event-dispatch.md`
- Planning/refinement budget: expanded path; draft and refine completed; Phase
  2 merged and Phase 3 replayed onto `develop` before PR preparation
- Implementation/refinement budget: one pass available because this phase
  changes runtime ordering and failure policy
- PR review budget: one automated review pass available
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phases 1 and 2 merged; Stage 19 dependency state
  must be recorded in Phase 3 completion notes if projection remains deferred
- Merge record: pending

### Risks And Stop Conditions

- Risks: dispatch before commit, callback failure loops, ambiguous non-durable
  identity, accidental ambient plugin loading, or Stage 19 fact mismatch.
- Stop conditions: committed-fact projection requires changing Stage 19
  reliability semantics; persistence-disabled dispatch cannot be made visibly
  non-durable; callback failures must fail runs by default for correctness.
- Assumptions: Stage 19 facts are available by merge order or can be projected
  through stable approved-plan assumptions without redefining reliability.

### Completion Summary

- Implementation: pending
- Validation: pending
- PR: pending
- Merge: pending
- Follow-up: pending

## Phase 4: Plugins, Diagnostics, Inspection, And Docs

Status: pending
Slug: `event-sink-plugins-diagnostics`
Branch: `codex/event-sink-plugins-diagnostics`
Worktree: `/home/samcantrill/work/loom-worktrees/event-sink-plugins-diagnostics`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase changes plugin readiness,
diagnostics, possible CLI/read-model surfaces, and feature docs

### Scope

- Goal: expose explicit event sink plugin loading and narrow operational
  visibility once records, registry, and runtime dispatch are stable.
- Files/modules owned:
  - new `src/loom/plugins/event_sinks.py` or equivalent plugin adapter module
  - `src/loom/plugins/__init__.py` and `src/loom/plugins/entrypoints.py` as
    needed for readiness exports
  - `src/loom/diagnostics/` and `src/loom/cli/` only for read-only warnings or
    inspection that fit existing surfaces
  - feature docs for reliability, plugins, run-store, provenance, preflight,
    CLI, and testing as affected
  - `docs/structure.md` when public module boundaries or durable sidecar/file
    layout change
  - plugin, diagnostics, CLI, package, contract, and docs tests
- Behavior implemented:
  - Explicit `loom.event_sinks` entry point loading into a supplied registry.
  - Accepted plugin shapes: callable sink, no-arg sink class, and no-arg
    factory returning a sink.
  - Deterministic registry names from entry point names unless registry naming
    support is added explicitly.
  - Clear load/registration failure reporting.
  - Plugin group readiness moves from listing-only to registry-ready.
  - Preflight warnings for unsupported event persistence, sink registration,
    and callback failure policy where practical.
  - Narrow read-only event/failure/link inspection only if existing CLI/read
    surfaces support it cleanly.
  - Final docs and validation evidence.
- Decisions applied: explicit plugin loading, plugin layer does not own event
  semantics, diagnostics/CLI are readers, no service-specific sinks.
- Examples or docs covered: explicit plugin sink loading and read-only
  inspection.
- Out of scope:
  - Ambient plugin loading.
  - Configured constructors in plugin loader.
  - Service-specific sink packages.
  - Mutating event or sink CLI.
  - Cleanup, retention, streaming, strict audit mode.
- Dependencies: Phases 1 through 3.

### Tasks

- Add explicit event sink entry point loader and exports following existing
  plugin adapter patterns.
- Update plugin readiness constants/contracts from listing-only to
  registry-ready for `loom.event_sinks`.
- Add unit/contract tests for accepted shapes, invalid shapes, duplicate
  registration, strict/best-effort behavior, and listing without loading.
- Add preflight diagnostics that stay cheap and avoid ambient plugin loading.
- Decide in the phase execution plan whether CLI event inspection is included.
  If included, keep it read-only and add CLI/integration tests. If excluded,
  document the stable Python/read-model inspection path.
- Update feature docs for event grammar, sink contracts, plugin loading,
  callback failure defaults, diagnostics, inspection, deferrals, and accepted
  debt.
- Update `docs/structure.md` if the final `event_sinks` module path or durable
  event/failure/link layout changes repository structure guidance.
- Run final targeted checks, `make validate-pr`, and `make test-summary`.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/plugins/test_entrypoints.py tests/unit/loom/plugins/test_adapters.py tests/contracts/test_plugin_discovery_contract.py tests/contracts/test_plugin_future_groups_contract.py tests/package/test_plugins_api.py` | Target explicit event sink plugin loading and readiness contracts | yes |
| `uv run pytest tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/unit/loom/diagnostics/test_preflight_plugins.py tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_cli_preflight_contract.py` | Target diagnostics and preflight behavior as changed | yes |
| `uv run pytest tests/unit/loom/cli tests/integration/diagnostics tests/e2e/test_cli_core.py tests/e2e/test_cli_runs_e2e.py` | Target CLI/read-only inspection if changed | yes, if CLI changed |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: event sink plugins load only through explicit action,
  invalid plugins fail clearly, readiness contracts are intentional, and
  diagnostics/inspection remain read-only.
- Design-decision evidence: plugin loading does not define event semantics or
  load ambiently.
- Future-roadmap compatibility evidence: service-specific sinks remain external
  packages over generic Stage 20 contracts.
- Interface, adapter, or protocol reuse evidence: loader registers into a
  supplied registry and accepts generic sink shapes.
- Documentation evidence: feature docs and testing docs reflect final behavior,
  deferrals, accepted debt, and suite obligations.
- Domain-neutrality evidence: examples use fake/generic sinks and no service
  clients.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: expanded path; draft and refine expected
- Implementation/refinement budget: one pass available because this phase
  changes plugin readiness and user-visible diagnostics/docs
- PR review budget: one automated review pass available
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phases 1 through 3 merged or valid stack
  predecessors
- Merge record: pending

### Risks And Stop Conditions

- Risks: ambient plugin loading, plugin-layer event semantics, CLI scope creep,
  configured constructor overreach, or final import-boundary drift.
- Stop conditions: event sink plugin loading requires importing runtime
  execution or stores at plugin import time; CLI inspection requires mutating
  commands; default tests require network/service plugins.
- Assumptions: explicit Python/programmatic loading remains sufficient for core
  Loom; configured plugin construction can be added later if needed.

### Completion Summary

- Implementation: pending
- Validation: pending
- PR: pending
- Merge: pending
- Follow-up: pending

## Cross-Phase Validation

- Full relevant test command: each phase PR must run targeted tests for its
  owned modules plus `make validate-pr`; PR preparation must run
  `make test-summary`.
- Docs/template checks: `git diff --check`, affected docs tests where present,
  feature-doc consistency for reliability, run-store, provenance, preflight,
  plugins, CLI, and testing, and `docs/structure.md` consistency when public
  module or file-layout contracts change.
- Domain-neutrality checks: no service clients, service-specific sink names,
  hosted telemetry, notification dependencies, domain metric semantics, or
  real cloud/network dependencies in default tests.
- Import-boundary checks: `loom.pipeline.events` and
  `loom.pipeline.event_sinks` remain import-light; `event_sinks` does not
  import store modules; plugins load into supplied registries; diagnostics/CLI
  read public records/read models.
- Example/demo checks: ordered audit log, schema-v1 compatibility, committed
  Stage 19 fact projection, observe-only fake sink dispatch, callback failure
  record, non-durable opt-out warning, observer-link writeback, and explicit
  plugin loading.
- Manual review focus: event schema compatibility, offline evidence/import
  replay compatibility, dispatch ordering, persistence-disabled identity,
  observer-link mutation boundary, callback failure recursion avoidance,
  plugin-readiness contract changes, and final docs/validation evidence.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| Public event/envelope schema was not decision-complete | blocker | Added `Event And Envelope Schema Contract` covering schema-v1 mapping, canonical field names, `event_type` compatibility, durable sequence semantics, non-durable envelope semantics, and callback-failure event references | resolved |
| Phase 2 persistence boundary was ambiguous | concern | Clarified that Phase 2 owns callback failure and observer-link record types plus store/read facets; Phase 3 writes runtime instances through those facets | resolved |
| Targeted validation missed offline event serialization consumers | concern | Added Phase 1 validation for offline evidence/import and authority audit-event replay and cross-phase manual review focus | resolved |
| `docs/structure.md` was missing from docs update path | concern | Added `docs/structure.md` to Phase 4 file ownership, docs tasks, and cross-phase docs checks when module/file layout changes | resolved |

Gate result:

- Status: passed
- Review evidence: initial `loom_plan_reviewer` review blocked on public
  schema completeness; bounded refinement applied for all findings;
  confirmation review found no remaining findings and recommended pass with
  notes.
- Accepted risks:
  - Stage 19 implementation dependency may require phase-level adjustment if
    final reliability fact shapes differ from the approved Stage 19 plan.
  - Schema-v1 event projection remains compatibility debt.
  - Explicit persistence-disabled sink dispatch is accepted auditability debt.
  - Observer-link and plugin-loader surfaces intentionally start narrow.
- Revisit triggers:
  - Strict audit mode planning.
  - Stage 21 cleanup/retention planning.
  - Downstream service plugins needing richer observer-link summaries or
    configured plugin constructors.
  - A documented schema-v1 compatibility removal/archive window.

## Final Approval

- Approval status: approved for Phase 1 execution planning.
- Approved scope: four-phase Stage 20 implementation plan covering event
  grammar/compatibility, sink registry and observer facts, runtime dispatch
  from committed facts, and plugins/diagnostics/inspection/docs.
- Accepted risks:
  - Stage 19 implementation dependency may require phase-level adjustment if
    final reliability fact shapes differ from the approved Stage 19 plan.
  - Schema-v1 event projection remains compatibility debt.
  - Explicit persistence-disabled sink dispatch is accepted auditability debt.
  - Observer-link and plugin-loader surfaces intentionally start narrow.
- Deferred items: cleanup/deletion/retention, service-specific sinks,
  distributed streaming, strict audit mode, cross-run retry budgets,
  resource-aware retry escalation, event-driven mutation, mutating event CLI,
  and domain-specific tracking semantics.
