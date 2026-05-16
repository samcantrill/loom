# Roadmap Stage 19 Planning: Reliability Policies And Transactions

## Metadata

- Roadmap stage: v19
- Source roadmap: `docs/roadmap.md`
- Previous version status:
  - `docs/roadmap/stage-16/planning.md` exists and records Stage 16 ready for
    implementation-plan drafting.
  - `docs/roadmap/stage-16/implementation-plan.md` exists and records Stage 16
    complete with all phases merged and no known blocker.
  - `docs/roadmap/stage-17/planning.md` exists in the current checkout as an
    untracked working-tree artifact and records Stage 17 in capability triage;
    this Stage 19 planning pass treats it as useful context only and does not
    modify it.
  - `docs/roadmap/stage-18/` does not exist in the current checkout. Stage 18
    context comes from `docs/roadmap.md` and `docs/features/container-executors.md`.
- Planning artifact status: ready for implementation-plan drafting
- Current discussion stage: implementation-plan handoff
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
  - Implementation readiness: passed
  - Handoff: ready
- Related implementation plan: `docs/roadmap/stage-19/implementation-plan.md`
- Related feature docs:
  - `docs/features/reliability.md`
  - `docs/features/execution.md`
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/artifacts.md`
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/container-executors.md`
  - `docs/features/slurm.md`
- Blockers: none
- Accepted risks:
  - Stage 18 has no planning artifact in the current checkout, so Stage 19
    must carry explicit compatibility assumptions for Apptainer/SLURM-container
    execution until Stage 18 planning exists.
  - Exact reliability record file layout remains implementation-plan detail.
  - Stage 19 rollback/cleanup records do not perform Stage 21 deletion or
    retention behavior.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` v19 | Stage 19 makes retry, timeout, failure classification, status detail, stage-attempt transaction, and retry-safety decisions explicit and inspectable across executors. | roadmap scope | This is now the reliability-core item after the split. |
| `docs/roadmap.md` v19 | Requires shared retry, timeout, failure-category, and reliability policy models. | public model scope | These models likely become reusable public or semi-public contracts. |
| `docs/roadmap.md` v19 | Requires status detail records that keep machine policy status stable while adding lifecycle phase, reason code, and message. | status design | Stage 19 should not expand `RunStatus` or `StageStatus` for every backend-specific case. |
| `docs/roadmap.md` v19 | Requires retry planning around safe output transactions, explicit idempotency assumptions, and persisted retry decision records. | retry behavior | Automatic retry must be conservative and data-recorded. |
| `docs/roadmap.md` v19 | Requires timeout support where executors can enforce it, with warnings and metadata where they cannot. | timeout behavior | Capability-aware enforcement is central; unsupported behavior must be visible. |
| `docs/roadmap.md` v19 | Requires explicit stage-attempt transaction records for begin, stage, commit, rollback or failure, and cleanup outcomes. | persisted records | These records define when staged artifacts become authoritative and when retry is safe. |
| `docs/roadmap.md` v19 | Requires global concurrency lease models for future sweeps and shared-resource environments. | coordination scope | Current authority/coordination code already has trial and resource leases; planning must decide what remains in Stage 19. |
| `docs/roadmap.md` v19 | Defers runtime event grammar expansion, event sink contracts, plugin-discovered event sink loading, cleanup/deletion, retention, full run-collection GC, service-specific sinks, distributed event streaming, advanced backoff, cross-run retry budgets, and resource-aware retry escalation. | explicit deferrals | Prevents Stage 19 from absorbing new v20, v21, or service-integration work. |
| `docs/roadmap.md` v20 | Stage 20 now owns runtime event records, event grammar, `EventSink`, `EventSinkRegistry`, plugin-discovered sink loading, and callback failure records. | successor boundary | Stage 19 may create reliability facts that v20 emits as events later. |
| `docs/roadmap.md` v21 | Stage 21 now owns cleanup, retention metadata, explicit deletion, and run-collection GC. | successor boundary | Stage 19 may record cleanup-relevant transaction outcomes but should not implement deletion. |
| `docs/roadmap.md` deferred candidates | OpenTelemetry, W&B, JSONL audit, webhook, or notification sinks should be service-specific plugins over the v20 event sink model. | future adapter boundary | Core should provide event contracts and failure policy later, not service delivery in v19. |
| `docs/features/reliability.md` | Reliability owns retry policy, timeout policy, failure recovery metadata, cleanup semantics, event hook record shape, artifact retention metadata, and conservative deletion rules. | feature scope | Retry/timeout/transaction portions belong to Stage 19, event hooks to Stage 20, and cleanup/retention to Stage 21. |
| `docs/features/reliability.md` | Retry is safe only after a clear failed status, safe output transaction semantics, and policy allowance; validation and graph failures should not be retried. | retry boundary | Supports conservative default behavior. |
| `docs/features/reliability.md` | Timeout enforcement differs for subprocess, SLURM, and containers; unsupported enforcement should warn and record metadata. | executor compatibility | Planning must handle local/subprocess, SLURM, Docker, and Apptainer differently. |
| `docs/features/reliability.md` | Existing event foundation is local `events.jsonl`; callback hooks and plugin-discovered event sinks are deferred until later. | successor bridge | Those deferred hooks now belong to v20 after the roadmap split. |
| `docs/features/execution.md` | Stage commit ordering is prepare, run, validate, commit, finalize; outputs and artifact index precede `SUCCEEDED`, and failure metadata precedes `FAILED`. | transaction ordering | Stage-attempt transaction records should preserve this ordering. |
| `docs/features/state.md` | `StageStatusRecord` has stable status plus message, owner, metadata, attempt, timestamps, and attempt increments on retry or rerun. | status foundation | Status detail can layer on stable statuses rather than changing enums. |
| `docs/features/preflight.md` | Reliability features should emit explicit warnings when selected policies are unsupported or environment-dependent. | diagnostics | Stage 19 should add preflight checks without performing heavy external work by default. |
| `docs/features/testing.md` | Default suites should avoid real clusters, containers, cloud services, network services, and heavy optional dependencies. | validation | Stage 19 validation must rely on fake executors and local stores by default. |
| `docs/GLOSSARY.md` | `executor` runs one stage through a backend; `RunStore` is the public authority-backed run lifecycle surface; `LocalRunStore` is local materialization; authority is the backend-neutral lifecycle truth. | vocabulary | Planning should avoid treating local event files or local store helpers as authoritative state after v9-post/v10. |
| `src/loom/pipeline/status.py` | Current run and stage status records have stable enums, message, metadata, owner, attempt, and timestamps. | status compatibility | New detail/reason records should avoid enum churn. |
| `src/loom/pipeline/stores/read_models.py` | Current authority read models include `LifecycleReason`, `StageAttempt`, `LeaseRecord`, `LeaseKind`, `LeaseState`, `RecoveryRecord`, materialized refs, and cleanup candidates. | authority foundation | Some Stage 19 concepts already have partial authority/read-model vocabulary. |
| `src/loom/pipeline/stores/coordination.py` | Current coordination contracts include trial and resource lease records, acquisition, renewal, release, failure, recovery, and diagnostics. | global lease foundation | Stage 19 planning must decide whether to reuse, generalize, or narrow the roadmap's global concurrency lease requirement. |
| `src/loom/pipeline/runtime/_models.py` and `src/loom/pipeline/specs.py` | `retry`, `timeout`, and related runtime/stage fields are explicitly deferred or rejected in current model parsing. | config/runtime gap | Stage 19 must introduce accepted policy inputs deliberately. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Workflow and templates | `.codex/workflows/roadmap-stage-planning.md`, `.codex/prompts/roadmap-stage-planning-facilitate.md`, `.codex/prompts/roadmap-stage-functionality-agreement.md`, `.codex/prompts/roadmap-stage-design-agreement.md`, `.codex/prompts/roadmap-stage-design-safety-review.md`, `.codex/templates/roadmap-stage-planning.md` | Workflow requires a startup briefing and clarification gate before capability triage; design-safety review is required before implementation-plan drafting. | Design-safety review and follow-up recheck are complete; examples/validation and phase shaping are confirmed. |
| Roadmap docs | `docs/roadmap.md` v17-v21, deferred integration candidates, module coverage table | Stage 19 is now reliability policy and transaction semantics between container execution and the new runtime-events/event-sinks item. It touches execution, stores, state, preflight, CLI, and testing. | Stage 18 has no planning artifact in this checkout. |
| Feature docs | `reliability.md`, `execution.md`, `run-store.md`, `state.md`, `runtime-resources.md`, `preflight.md`, `cli.md`, `artifacts.md`, `container-executors.md`, `slurm.md`, `testing.md` by targeted sections and search | Feature docs support conservative retry, capability-aware timeout, transaction ordering, explicit diagnostics, and default fake/local testing. | Later design pass should reread focused sections for exact public model names once functionality is confirmed. |
| Source and tests | `execution/stage_attempts.py`, `execution/lifecycle.py`, `stores/run_store.py`, `stores/read_models.py`, `stores/coordination.py`, `runtime/_models.py`, `runtime/capabilities.py`, status and executor capability tests | Current source has status records, authority lifecycle reasons, stage attempts, resource/trial leases, capability diagnostics, and deferred retry/timeout fields. | Design pass should inspect runner/executor resolution and SLURM/container modules when deciding timeout and retry integration points. |
| Prior or adjacent plans | Stage 16 planning and implementation plan; Stage 17 untracked planning artifact; roadmap Stage 18 | Stage 16 defers retry/timeout/events to later reliability work; the roadmap split assigns retry/timeout/transactions to Stage 19, events/sinks to Stage 20, and cleanup/retention to Stage 21. Stage 17 planning expects later reliability policy to wrap Docker. Stage 18 must be treated as roadmap-only context. | Stage 18 implementation-plan specifics are unavailable. |

## Roadmap Extraction

Baseline roadmap outcome:

- Add shared reliability policy data for retry, timeout, failure categories,
  status detail, transaction records, and selected concurrency lease behavior.
- Make automatic retry conservative, explicit, and persisted as decisions
  rather than hidden in executor control flow.
- Make timeout behavior executor-capability-aware across local, subprocess,
  SLURM, Docker, and Apptainer/Singularity paths, with visible unsupported
  warnings and metadata.
- Add stage-attempt transaction records that make begin, execution, commit,
  rollback or failure, cleanup outcome, committed outputs, failed attempts,
  and retry eligibility unambiguous.
- Add preflight warnings and CLI inspection where useful for reliability
  policies, transaction records, timeout support, and unsupported leases.

Prerequisites:

- Stable local/subprocess/SLURM execution contracts and the stage-worker path.
- Stage-attempt, lifecycle reason, lease, submitted-operation, and authority
  read-model foundations from v9 through v11.
- Runtime resource and executor descriptor capability validation from v4 and
  later executor stages.
- External artifact and payload materialization records from v15/v16 for
  transaction and cleanup-relevant facts.
- Docker and HPC container executor surfaces from v17/v18, or explicit
  compatibility assumptions if planning starts before Stage 18 is detailed.

Primary feature docs:

- `reliability.md`
- `execution.md`
- `run-store.md`
- `state.md`
- `artifacts.md`
- `preflight.md`
- `cli.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Cleanup and deletion operations.
- Runtime event grammar, event sink contracts, plugin-discovered sink loading,
  and callback failure policy.
- Artifact retention policy enforcement and full run-collection garbage
  collection.
- Service-specific notifications and tracking sinks such as MLflow, W&B,
  Slack, email, Teams, PagerDuty, webhooks, OpenTelemetry, and hosted telemetry.
- Distributed event streaming.
- Advanced exponential backoff.
- Retry budgets across runs.
- Resource-aware retry escalation.
- Worker-daemon prefetch, advanced scheduling, and worker-health orchestration
  beyond the v11 queue controller.
- Domain-specific metric extraction, metric optimization, project semantics,
  or external tracking-service semantics.

Future-roadmap touchpoints:

- Stage 20 should consume Stage 19 transaction, retry, timeout, and failure
  facts to emit audit-ready events and dispatch observe-only event sinks.
- Stage 21 should consume Stage 19 transaction and cleanup-outcome facts for
  conservative cleanup/retention without changing retry semantics.
- Future service-specific event sink plugins should consume the Stage 20 event
  and sink contracts without requiring core Loom to ship delivery clients.
- Future remote stores and orchestration adapters should report capability and
  failure facts into the same policy model instead of defining separate
  semantics.
- Future distributed tracing or telemetry, if ever selected, should be a
  plugin or adapter projection over the Stage 20 runtime event contract, not a core
  dependency or replacement for authority/store truth.

Compatibility obligations:

- Stable run and stage status enums remain the machine policy vocabulary.
  Status detail, reason codes, and messages explain status without creating
  backend-specific enum churn.
- Authority-backed run/store contracts remain the source of active lifecycle
  truth; local files remain materialized records and projections.
- Default execution remains no-retry unless policy explicitly permits retry.
- Default tests remain local, deterministic, and network-free.
- Default install must not add heavy notification, telemetry, cloud, container,
  or cluster dependencies.

## Stage Briefing

What this stage is:

- Stage 19 is Loom's reliability-policy and stage-attempt transaction stage.
  It turns a narrowed set of deferred runtime concerns into explicit data:
  retries, timeouts, failure categories, status detail, transaction outcomes,
  and selected lease behavior.
- The central theme is not "retry everything" or "send notifications." The
  central theme is making correctness decisions inspectable, conservative,
  capability-aware, and reusable across all executors.

Why this stage exists:

- Earlier stages intentionally keep execution simple and backend-specific facts
  narrow: local and subprocess execution persist failures; SLURM records
  submitted operations and scheduler outcomes; queueing and authority add
  lifecycle and lease records; containers add backend invocation metadata.
  Stage 19 unifies the reliability layer those systems need to share.
- Users need to know why a run failed, whether a stage can be retried safely,
  whether a timeout was enforced, and which transaction transition made staged
  outputs authoritative. Those answers should come from durable Loom records
  instead of executor-specific control flow or logs.

Impacted or linked work:

- `loom.pipeline.execution` is likely the main orchestration owner for retry
  decisions, transaction ordering, and timeout integration.
- `loom.pipeline.status` or adjacent state/read-model modules likely need
  status detail or reason records that layer on existing stable status enums.
- `loom.pipeline.stores` needs persistence and read contracts for retry
  decisions, transaction records, timeout outcomes, status details, and
  possibly enhanced lease records.
- `loom.pipeline.runtime` and executor descriptors likely need policy and
  capability validation for retry and timeout support.
- `loom.diagnostics.preflight` and CLI surfaces should explain unsupported or
  partially supported reliability policies without doing expensive remote,
  cluster, or container work by default.
- `docs/features/reliability.md`, `execution.md`, `state.md`, `run-store.md`,
  `preflight.md`, `cli.md`, and `testing.md` will likely need updates to align
  with final design choices.

Likely public surfaces and durable artifacts:

- Reliability policy records for retry and timeout settings.
- Failure category or reason-code records that describe failure class without
  changing core status enums.
- Status detail records or embedded details for lifecycle phase, reason code,
  message, and debug-safe payloads.
- Retry decision records that capture eligibility, reason, selected policy,
  attempt number, and next action.
- Timeout outcome records that distinguish enforced, observed, unsupported,
  and timed-out behavior.
- Stage-attempt transaction records for begin, running/staged, commit,
  rollback/failure, and cleanup outcome.
- Preflight diagnostics for unsupported or partially supported policy features.
- CLI/API inspection paths for reliability and transaction records where they are
  useful and stable.

Structure rationale:

- The stage should start with requirements and behavior, because small wording
  differences have durable design impact: whether retry is default-on, whether
  timeouts are config or resource policy, whether status detail is embedded or
  separate, and whether global concurrency leases are new records or an
  extension of existing coordination contracts.
- The design pass should be explicit and bounded. Stage 19 spans execution,
  stores, diagnostics, CLI, and persistent records, so it has public API,
  schema, failure-semantics, and future-adapter risk. It should receive
  design-safety review before implementation-plan drafting.

Visible assumptions, risks, and constraints:

- Recommended default: automatic retry remains off unless a policy explicitly
  permits another attempt and the previous attempt is transactionally safe to
  retry.
- Recommended default: timeout policy is capability-aware and should not create
  two competing ways to express the same wall-time behavior in runtime resources
  and reliability policy.
- Recommended default: status enums stay stable; status detail/reason records
  carry the extra explainability.
- Risk: Stage 19 can become too broad if it tries to solve cleanup, telemetry
  delivery, distributed tracing, retry backoff strategy, scheduler health, and
  resource-aware orchestration. Those should remain explicit deferrals unless
  the user intentionally changes the roadmap.
- Risk: Stage 18 has no planning artifact here, so timeout and failure-category
  behavior for Apptainer/SLURM-container composition must be generic enough not
  to assume one final Stage 18 implementation shape.
- Risk: existing authority and coordination lease records already cover some
  global lease behavior. Stage 19 should avoid inventing a parallel lease model
  unless a requirement clearly needs it.

User clarification questions and resolved answers:

- The user agrees the stage is quite large and asked whether it should be split
  into two roadmap items, and what a reasonable feature split would be. Current
  confirmed split: Stage 19 covers core reliability policy and transaction
  semantics; Stage 20 covers runtime event sink delivery and plugin loading;
  Stage 21 keeps cleanup/deletion separate.
- The user confirmed the split and asked to focus on the Stage 19 planning
  workflow. Continue with narrowed roadmap framing and intent discovery for
  reliability policies and transactions only.
- The user agreed with the narrowed framing: target users need reliable
  local/subprocess/SLURM/container failure, timeout, transaction, and retry
  behavior; the user-visible outcome is inspectable failure cause, retry
  eligibility, timeout enforcement, and safe output commit state; planning
  priority is correctness and durable records first, convenience CLI second,
  automation breadth last. The user asked what "automation" means in this
  context.
- The user agreed with conservative automation scope, and asked to consider how
  those automations should be implemented: which interfaces and base adapters
  Stage 19 should provide, and how to account for useful event-driven external
  actions. Current planning stance: Stage 19 should provide reliability policy,
  classifier, evaluator/planner, timeout, transaction, and store interfaces that
  future automation can consume; event-driven external actions remain Stage 20
  unless an intentionally minimal internal event handoff is needed to keep the
  Stage 20 contract from retrofitting Stage 19 records later.
- The user agreed with the interface/base-adapter boundary: Stage 19 separates
  facts, decisions, and actions; runtime-changing automation goes through
  runner/authority reliability interfaces; Stage 20 projects committed facts to
  observe-only event sinks and external actions.

## User Intent

Target audience:

- Users running local/subprocess/SLURM/container stages who need reliable
  failure, timeout, transaction, and retry behavior.

User-visible outcome:

- Users can inspect why a stage failed, whether retry is allowed, whether
  timeout was enforced, and whether outputs were safely committed.

Success criteria:

- Retry, timeout, failure category, status detail, transaction, and lease
  decisions are persisted as durable records and can be inspected without
  reading executor-specific logs.
- Conservative retry only occurs when explicit policy permits it and recorded
  transaction state proves retry safety.
- Timeout behavior is capability-aware and visibly records enforced,
  delegated, observed, unsupported, and timed-out outcomes as applicable.
- Runtime-changing automation is implemented through runner/authority
  interfaces, not external callbacks.

Non-goals:

- Runtime event grammar and event sinks; Stage 20 owns them.
- Cleanup, deletion, retention enforcement, and run-collection GC; Stage 21
  owns them.
- Service-specific notifications, telemetry clients, tracking-service
  semantics, and external event-driven actions in core Stage 19.
- Advanced backoff, cross-run retry budgets, resource-aware retry escalation,
  executor migration, and scheduler health orchestration.

Constraints:

- Keep retry opt-in and conservative by default.
- Preserve stable run and stage status enums; add detail/reason records instead
  of enum churn.
- Keep default tests local, deterministic, and free of real clusters,
  containers, cloud services, network services, and heavy optional
  dependencies.
- Keep Stage 18 compatibility generic because no Stage 18 planning artifact
  exists in this checkout.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- Split confirmed. Stage 19 is narrowed to reliability policies, status detail,
  retry/timeout behavior, stage-attempt transaction records, retry safety, and
  selected lease compatibility. Stage 20 owns runtime events and event sinks.
  Stage 21 owns cleanup and retention.
- Target audience: users running local/subprocess/SLURM/container stages who
  need reliable failure, timeout, transaction, and retry behavior.
- User-visible outcome: users can inspect why a stage failed, whether retry is
  allowed, whether timeout was enforced, and whether outputs were safely
  committed.
- Planning priority: correctness and durable records first; convenience CLI
  second; automation breadth last.

Intent discovery locked decisions:

- Confirmed. The user wants Stage 19 to define implementation-facing
  interfaces/base adapters for conservative retry/timeout automation and to
  avoid blocking useful event-driven external actions in Stage 20.
- Stage 19 should define `FailureClassifier`, `RetryPolicyEvaluator`,
  executor timeout capability/adapter, stage-attempt transaction store,
  reliability store facets, and a runner-owned reliability controller shape.
- Event-driven external actions are useful, but Stage 19 should only make
  records event-ready through stable IDs, timestamps, run/stage/attempt
  references, transaction IDs, reason codes, and causal links.
- Event sinks in Stage 20 may observe and create external side effects, but
  they must not trigger retry/cancel/status/artifact/transaction correctness
  behavior.

Capability triage and candidate-functional-requirement readback:

- Confirmed. Included capabilities: reliability policy records, failure
  classification/status detail, transaction records, retry decisions, timeout
  outcomes, reliability store facets, interface/base adapters, event-ready
  record identity, narrow lease compatibility, preflight diagnostics, and
  narrow read-only inspection. Deferrals: runtime events/event sinks,
  cleanup/retention, service-specific integrations, advanced retry
  orchestration, resource escalation, executor migration, scheduler health
  orchestration, and parallel lease models.

Functionality-agreement readback:

- Confirmed. The functionality-agreement queue is resolved with repo-supported
  recommendations and user confirmation. Locked decisions: primary outcome is
  conservative inspectability; Stage 20 owns event sinks and external actions;
  retry is opt-in and runner/authority-owned; Stage 19 reuses or hardens
  existing lease contracts narrowly; read-only inspection stays narrow; timeout
  is a reliability policy with executor capability outcomes, not a competing
  resource-model field.

Functionality and behavior confirmation readback:

- Confirmed by user. The behavior baseline below translates the confirmed
  functionality agreement into included behavior, defaults, failure diagnostics,
  explicit deferrals, and out-of-scope behavior.

Design-agreement follow-up:

- Confirmed. The design pass reloaded `docs/structure.md`, design-safety
  review instructions, feature evidence, and current source. Locked shape:
  add import-light reliability models/protocols under `loom.pipeline`, compose
  runner-owned retry/timeout/transaction behavior in `loom.pipeline.execution`,
  extend store/read-model facets without replacing existing authority facts,
  keep CLI/diagnostics as readers of stored facts, and place authored
  reliability policy under `runtime.reliability` with stage-level overrides
  under `runtime.stage_options.<stage>.reliability`.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | User confirmed splitting the original broad Stage 19 into Stage 19 reliability/transactions, Stage 20 events/sinks, and Stage 21 cleanup/retention. User also confirmed the target audience, user-visible outcome, priority order, and conservative automation framing. | Retry off by default unless policy and transaction safety allow it; status enums remain stable; Stage 20 owns events/sinks; Stage 21 owns cleanup/deletion. | None. | Complete intent discovery. |
| Intent discovery | Conservative automation should be enabled through explicit interfaces and base adapters rather than hidden executor control flow. Event-driven external actions are useful but belong to Stage 20; Stage 19 records should be event-ready. | Automation acts only from explicit policy plus recorded facts. | None. | Capability triage. |
| Capability triage and candidate functional requirements | Included/deferred capability set confirmed, including narrow lease reuse/hardening and narrow read-only inspection. | Include records/interfaces first, automation only through runner/authority, event-ready facts without event sinks. | None. | Functionality-agreement review. |
| Functionality agreement review | Requirement queue confirmed: reliability records, failure/status detail, transaction records, conservative retry, timeout outcomes, reliability read models, adapter interfaces, event-ready identifiers, narrow lease compatibility, preflight diagnostics, and narrow inspection. | Timeout is reliability policy; retry stays opt-in; read-only inspection is narrow; Stage 20 owns events/sinks; Stage 21 owns cleanup/retention. | None. | Behavior baseline confirmed. |
| Functionality and behavior confirmation | User approved the drafted behavior baseline. | Conservative inspectability over broad automation; runtime-changing actions through runner/authority only. | None. | Context compaction/reset checkpoint. |
| Context compaction/reset checkpoint | Checkpoint recorded in this artifact; design pass reloaded workflow, design prompt, structure docs, feature docs, and source context. | Treat confirmed functionality and behavior as binding unless explicitly reopened. | None. | Design agreement review. |
| Design agreement review | Proposed implementation shape and dependency-ordered design queue confirmed, including `runtime.reliability` plus stage-level reliability overrides. | Prefer import-light reliability contracts, runner-owned actions, store-owned persistence, diagnostics/CLI as readers, and event-ready facts without event sinks. | None. | Design-safety review. |
| Design safety review | Completed; no design-safety blockers remain. Upheld the confirmed public config path, the narrowed Stage 19/20/21 boundary, runner/authority-owned retry, store-owned durable reliability facts, and event-ready records without event sink contracts. Follow-up recheck after the examples update also passed. | Treat public config and persisted record shape as durable; keep implementation-plan detail focused on versioned records, generic protocols, and explicit validation. | None. | Implementation-plan handoff. |
| Examples and validation strategy | Confirmed by user after the structured config and failed-attempt flow examples were incorporated below. | Default tests use fake/local executors and stores; real clusters/containers remain opt-in or deferred. | None. | Phase shaping. |
| Phase shaping | Confirmed as six reviewable phases. | Split contracts/config, persistence, transaction/classification, timeout/diagnostics, retry automation, and inspection/docs. | None. | Implementation readiness. |
| Implementation readiness | Passed after design-safety recheck of the structured examples, validation strategy, and phase split. | Carry confirmed examples, validation, and six-phase split into implementation-plan drafting. | None. | Handoff. |
| Handoff | Ready for implementation-plan drafting. | Use this planning artifact as the primary source for the Stage 19 implementation plan. | None. | Draft implementation plan. |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Shared reliability policy models | include | Required by v19 roadmap. | Covers retry, timeout, failure category, and policy serialization. |
| Failure classification and status detail records | include | Required by v19 roadmap to explain status without enum expansion. | Stable failure categories plus human/debug detail should feed retry, timeout, diagnostics, catalog, and future events. |
| Stage-attempt transaction records | include | Required by v19 roadmap. | Defines when staged outputs become authoritative, when cleanup facts exist, and when retry is safe. |
| Conservative retry decisions | include | Required by v19 roadmap and reliability docs. | Retry must depend on failed attempt, policy allowance, classifier output, and safe transaction semantics. |
| Timeout support and unsupported metadata | include | Required by v19 roadmap. | Enforcement is executor-capability-specific; unsupported/delegated/observed outcomes must be visible. |
| Reliability store facets and read models | include | Required so records are durable and inspectable. | Store contracts should append/read policy decisions, transaction records, timeout outcomes, and status details. |
| Interface and base adapter surfaces | include | User requested implementation-facing automation adapters. | Covers `FailureClassifier`, `RetryPolicyEvaluator`, timeout capability/adapter, transaction store, reliability store facets, and runner-owned reliability controller. |
| Event-ready record identity and causal references | include | Prevents Stage 20 from retrofitting Stage 19 records. | Provide stable IDs, timestamps, run/stage/attempt refs, transaction IDs, reason codes, and causal links without implementing event emission. |
| Global/resource lease compatibility | include, narrow | Required by roadmap, but current coordination code already has resource/trial leases. | Reuse or harden existing authority/coordination lease contracts where possible; no new scheduler or worker-health orchestration. |
| Preflight diagnostics for reliability policy support | include | Required by roadmap and preflight docs. | Warnings/errors for unsupported retry, timeout, transaction, and lease policies should stay cheap by default. |
| Read-only CLI/API inspection | include, narrow | Roadmap says CLI inspection where useful and user approved the narrow path. | Scope is narrow inspection of reliability/transaction facts only; avoid broad new operations. |
| Rich runtime event grammar | defer | New Stage 20 owns audit-ready runtime event grammar and compatibility/versioning for `events.jsonl`. | Stage 19 should record facts that Stage 20 can emit later. |
| Programmatic event sink registry | defer | New Stage 20 owns `EventSink` and `EventSinkRegistry`. | Stage 19 should not introduce observer contracts. |
| Plugin-discovered event sink loading | defer | New Stage 20 owns event sink plugin loading after registry semantics stabilize. | `loom.event_sinks` remains out of Stage 19 scope. |
| Event sink callback failure records | defer | New Stage 20 owns callback failure records and best-effort observer policy. | Stage 19 can ignore observer failures because observers are not in scope. |
| Cleanup/deletion/retention/GC | defer | Stage 21 owns this work. | Stage 19 may emit cleanup outcome facts only. |
| Service-specific sinks and telemetry delivery | defer | Roadmap defers service integrations to plugins or future candidates. | Core should not ship Slack, email, W&B, MLflow, OpenTelemetry, webhook, or notification clients. |
| Advanced retry orchestration | defer | Roadmap explicitly defers advanced backoff, cross-run budgets, and resource-aware retry escalation. | Stage 19 should not add adaptive retry policy or multi-run retry management. |
| Executor migration and scheduler health automation | defer | User agreed automation breadth is not the priority. | Do not auto-resubmit to another executor/pool or add scheduler health orchestration. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Lock the primary Stage 19 user-visible outcome. | none | 1 | Make retry, timeout, failure-category, status-detail, transaction, and retry-safety decisions inspectable and conservative across executors, rather than optimizing for aggressive automation. | Sets the scope for all later retry, timeout, transaction, and lease decisions. | Already confirmed by user. | confirmed |
| FRQ-2 | Lock whether Stage 19 includes event sink or external-action behavior. | FRQ-1 | 2 | Defer event grammar, event sinks, callback failures, plugin loading, and event-driven external actions to Stage 20; make Stage 19 records event-ready. | Prevents Stage 19 from mixing correctness semantics with observer side effects while preserving future usefulness. | Already confirmed by user. | confirmed |
| FRQ-3 | Lock retry default and retry automation boundary. | FRQ-1 | 3 | Retry remains opt-in and only occurs through runner/authority after explicit policy, classified failure, and safe transaction state allow it. | Prevents hidden retry behavior and keeps executor control flow consistent. | Already confirmed by user. | confirmed |
| FRQ-4 | Decide lease scope for Stage 19. | FRQ-1 | 4 | Reuse or harden existing authority/coordination resource lease contracts for reliability policy compatibility; avoid a parallel global lease model. | The roadmap names global concurrency leases, but source already has resource/trial lease records. Scope must avoid duplicate concepts. | Confirmed by user. | confirmed |
| FRQ-5 | Decide read-only CLI/API inspection scope. | FRQ-1 | 5 | Include narrow inspection for reliability and transaction facts only if it materially improves the user-visible outcome. | Useful inspection belongs in Stage 19, but broad CLI operations can distract from durable records. | Confirmed by user. | confirmed |
| FRQ-6 | Lock timeout expression and support boundary. | FRQ-1 | 6 | Treat timeout as reliability policy with executor capability outcomes, avoiding competing timeout fields in resource models. | Prevents two conflicting ways to express wall time and keeps capability diagnostics coherent. | Confirmed by user. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Reliability policy records | none | Define shared retry, timeout, failure-category, and reliability policy records. | Makes policy explicit, serializable, and stable across executors. | Include policy model parsing/serialization and safe defaults; defer advanced backoff, cross-run budgets, and resource escalation. | Users can inspect selected reliability policy and see when a policy is unsupported. | Runtime validates and records policy data rather than hiding policy in executors. | Cross-executor reliability configuration. | Unit and contract serialization tests. | confirmed |
| FR-2 | Failure classification and status detail | FR-1 | Classify failures into stable categories and persist status detail/reason records without expanding status enums. | Retry, diagnostics, catalog display, and future events need reasoned failures while stable status vocabulary remains intact. | Include classifier interface, reason code, lifecycle phase, message, and debug-safe detail; defer domain-specific failure categories. | Users can inspect a failed stage and see a stable reason/category plus human-readable detail. | Executors report facts; classifier and runner create durable status detail. | Cross-executor failure diagnostics. | Unit tests for classifier defaults plus integration tests for local/subprocess/fake executor failures. | confirmed |
| FR-3 | Stage-attempt transaction records | FR-1 | Persist transaction lifecycle records for begin, running/staged, commit, rollback/failure, and cleanup outcome. | Retry safety and committed-output truth depend on knowing which attempt state became authoritative. | Include transaction IDs, run/stage/attempt refs, timestamps, status, reason, and causal links; defer deletion behavior. | Users can inspect whether outputs were safely committed or left in failed/staged state. | Runner/store record transaction transitions in order around output validation and commit. | Retry-safe output lifecycle. | Contract and integration tests for successful commit, commit failure, rollback/failure, and cleanup-outcome records. | confirmed |
| FR-4 | Retry decisions and runner-owned automation | FR-1, FR-2, FR-3 | Evaluate retry eligibility and persist retry decisions before any automatic retry. | Conservative retry must be explainable and safe. | Include evaluator interface, persisted decision, retry-disabled behavior, max-attempt handling, non-retryable validation/graph failures, and runner-owned next-attempt execution; defer advanced backoff and cross-run budgets. | Users can see why a retry did or did not happen. | Runner calls evaluator using policy, classification, attempt history, and transaction state; executor does not decide high-level retry. | Safe automatic retry. | Unit tests for evaluator plus integration tests for retry-disabled, retry-allowed, max-attempt, and non-retryable failures. | confirmed |
| FR-5 | Timeout capability and outcome records | FR-1 | Define timeout policy and record whether timeout was enforced, delegated, observed, unsupported, or timed out. | Timeout behavior varies by executor and must not be assumed. | Include capability diagnostics and outcome records; defer scheduler-specific advanced timeout interpretation beyond current executor facts. | Users can see whether timeout was applied and how. | Timeout adapter/capability reports support; runner records outcomes and warnings. | Capability-aware timeout behavior. | Unit tests for policy/outcome serialization and fake executor tests for support states. | confirmed |
| FR-6 | Reliability store facets and read models | FR-1, FR-3 | Add append/read surfaces for reliability policy decisions, transaction records, timeout outcomes, status details, and retry decisions. | Durable records need backend-neutral store contracts. | Include local and authority-compatible facets/read models; preserve local materialization versus authority truth boundaries. | Inspection can read reliability records without executor-specific log parsing. | Store implementations validate, persist, and read records without deciding policy. | Backend-neutral reliability persistence. | Contract tests against local/fake authority stores. | confirmed |
| FR-7 | Interface and base adapter surface | FR-1 | Provide implementation-facing protocols/base adapters for classifier, retry evaluator, timeout capability/adapter, transaction store, reliability store facets, and reliability controller. | Future executors and Stage 20 event projection need stable extension points. | Include generic contracts only; defer service-specific and event-sink adapters. | Users get consistent behavior across executors while adapter authors get clear contracts. | Runtime composes classifier/evaluator/adapters through runner/authority paths. | Extensible reliability automation. | Package/API tests and contract tests with fake adapters. | confirmed |
| FR-8 | Event-ready reliability records | FR-3, FR-4, FR-5 | Include stable IDs, timestamps, run/stage/attempt refs, transaction IDs, reason codes, and causal links in Stage 19 records. | Stage 20 should emit events from committed facts without inferring meaning or retrofitting schemas. | Include event-ready identifiers only; defer event grammar and sinks. | No direct Stage 19 event UI; future events can point to precise reliability facts. | Records carry enough references for later event projection. | Future event-sink compatibility. | Serialization tests asserting required identity/reference fields. | confirmed |
| FR-9 | Lease compatibility and reliability diagnostics | FR-1 | Reuse or harden existing authority/coordination lease records where reliability policy needs named keys, slot counts, duration, renewal, and failure behavior. | The roadmap names global concurrency leases, but the source already has lease contracts. | Include compatibility review and targeted hardening only; defer new scheduler behavior, worker-health orchestration, and v13 concurrent sweeps. | Users see clear diagnostics when a selected policy cannot be honored because of lease/capability support. | Preflight/runtime use existing lease capabilities or report unsupported policy. | Shared-resource compatibility. | Contract tests for lease renewal/failure behavior and unsupported diagnostics. | confirmed |
| FR-10 | Read-only reliability inspection | FR-2, FR-3, FR-4, FR-5, FR-6 | Expose useful read-only inspection for reliability policies, status detail, transaction records, retry decisions, and timeout outcomes. | The user-visible outcome depends on inspectability, but broad CLI operations are not the core. | Python read models plus narrow CLI output where existing status/logs commands naturally expose the facts. | Users can inspect reliability facts from APIs and, where useful, CLI. | CLI/read models present stored facts without mutating state. | Debuggable reliability records. | Integration/e2e tests if CLI is included; otherwise contract tests for read models. | confirmed |

## Behavior Baseline

Included functionality:

- Reliability policy records for retry, timeout, failure category, status
  detail, transaction behavior, and narrow lease compatibility.
- Failure classification and status detail records that layer reason/category
  information on stable run and stage statuses.
- Stage-attempt transaction records with stable IDs, timestamps, run/stage/
  attempt references, transaction IDs, reason codes, and causal links.
- Retry decision records and runner-owned retry evaluation for opt-in retry
  only after explicit policy, classified failure, and safe transaction state.
- Timeout policy and timeout outcome records for enforced, delegated, observed,
  unsupported, and timed-out behavior.
- Backend-neutral reliability store facets and read models for policy,
  status-detail, transaction, retry-decision, and timeout facts.
- Implementation-facing interfaces and base adapters for classification,
  retry evaluation, timeout capability/adaptation, transaction persistence,
  reliability reads/writes, and runner-owned reliability control.
- Event-ready record identity and causal references without Stage 20 event
  grammar or event sinks.
- Preflight diagnostics and narrow read-only API/CLI inspection for reliability
  facts where useful and stable.

User-visible behavior:

- Users can inspect the selected reliability policy, classified failure reason,
  status detail, transaction/commit state, retry decision, timeout outcome, and
  unsupported-policy diagnostics without reading executor-specific logs.
- Users can tell whether an attempt's outputs became authoritative, whether a
  retry was allowed or skipped, and whether timeout was enforced, delegated,
  observed, unsupported, or reached.
- CLI exposure is narrow and read-only: it should appear only where existing
  status/logs-style commands can naturally show stored reliability facts.

Default behavior:

- Retry is disabled unless an explicit policy permits another attempt and the
  prior attempt is safe to retry according to recorded transaction state.
- Stable run and stage status enums remain the machine-policy vocabulary;
  detail and reason records explain the status.
- Timeout is expressed as reliability policy. Unsupported timeout behavior is
  visible through preflight/runtime diagnostics and persisted metadata.
- Executors report facts and capability outcomes; the runner/authority
  reliability layer decides retry and transaction correctness.

Failure behavior and diagnostics:

- Validation and graph/configuration failures are non-retryable by default.
- Failed attempts record classification, status detail, transaction state, and
  retry decision before any next-attempt action.
- Commit failures do not mark partial outputs authoritative.
- Unsupported retry, timeout, transaction, or lease policies surface cheap
  preflight diagnostics where possible and runtime warnings/metadata when
  support can only be known during execution.

Explicit deferrals:

- Stage 20 owns runtime event grammar, event sink contracts, event sink
  registry/loading, callback failure policy, plugin-discovered event sinks, and
  event-driven external actions.
- Stage 21 owns cleanup, deletion, retention metadata/enforcement, and
  run-collection garbage collection.
- Future work owns service-specific notifications, telemetry/tracking sinks,
  advanced backoff, cross-run retry budgets, resource-aware retry escalation,
  executor migration, and scheduler/worker-health orchestration.

Out-of-scope behavior:

- Event sinks do not trigger retry, cancellation, status mutation, artifact
  mutation, or transaction correctness decisions in Stage 19.
- Stage 19 does not introduce a parallel global lease model or scheduler
  orchestration layer.
- Stage 19 does not define domain-specific failure categories, metric
  semantics, tracking-service payloads, or service delivery clients.

Context compaction/reset checkpoint:

- Checkpoint status: complete
- Notes path: `docs/roadmap/stage-19/planning.md`
- Resume instruction: Reread `docs/roadmap/stage-19/planning.md` and
  `.codex/prompts/roadmap-stage-design-agreement.md`; treat the confirmed
  functionality and behavior baseline as binding and continue from the current
  discussion stage recorded in metadata.
- Functionality and behavior reopened after checkpoint: not applicable yet

## Proposed Implementation Shape

Likely modules or packages:

- `loom.pipeline.reliability` should be the import-light home for reliability
  policy models, failure classification/status-detail records, transaction
  records, retry-decision records, timeout outcome records, and subsystem
  protocols. It may import foundational pipeline/status/serialization types,
  but must not import concrete executors, CLI, diagnostics, plugin loading, or
  optional backends.
- `loom.pipeline.runtime` should own authored and resolved reliability policy
  configuration because retry and timeout are invocation policy, not artifact
  data and not resource requests. The confirmed public config path is
  `runtime.reliability` plus `runtime.stage_options.<stage>.reliability`.
- `loom.pipeline.execution` should own the runner integration: prepare
  transaction records, classify failures, evaluate retry decisions, call
  timeout adapters/capability reporters, and schedule any allowed next attempt.
- `loom.pipeline.executors` should report execution facts and timeout
  capability/outcomes but should not decide retry policy or mutate reliability
  records directly except through existing execution result surfaces.
- `loom.pipeline.stores` should persist reliability facts and expose read-model
  facets. Existing status, stage-attempt, output-commit, lease, recovery, and
  event records should be reused or extended by association instead of replaced.
- `loom.diagnostics.preflight` and `loom.cli` should remain presentation/read
  layers over public runtime validation and store/read-model APIs.

Likely public classes, functions, or protocols:

- `ReliabilityPolicy`, `RetryPolicy`, `TimeoutPolicy`.
- `FailureCategory`, `FailureClassification`, `StatusDetailRecord`.
- `StageAttemptTransactionRecord`, `StageAttemptTransactionState`.
- `RetryDecisionRecord`, `RetryDecision`, `RetryDisposition`.
- `TimeoutOutcomeRecord`, `TimeoutOutcome`.
- `FailureClassifier`, `RetryPolicyEvaluator`, `TimeoutCapabilityReporter`,
  `TimeoutAdapter`, `ReliabilityRecordStore` or narrowly named store facets,
  and a runner-facing reliability controller protocol.
- Runtime option fields for run-level `runtime.reliability` and stage-level
  `runtime.stage_options.<stage>.reliability` policy.

Likely internal helpers:

- Policy normalization and merge helpers for run-level defaults plus stage-level
  overrides.
- Default failure classifier that maps current `ExecutionFailure.failure_type`,
  exit code, signal, timeout outcome, cancellation, and executor metadata into
  stable failure categories.
- Default retry evaluator that uses policy, classification, attempt history,
  max attempts, and transaction state.
- Transaction writer helpers around attempt preparation, stage execution,
  output validation, output commit, failure, rollback/failure, and cleanup
  outcome recording.
- Timeout capability diagnostics that adapt existing executor descriptor
  capability reporting without adding timeout to `ResourceRequest`.
- Read-model assembly helpers for compact status/log/CLI presentation.

Data flow:

- Authored config/runtime options produce a resolved per-stage
  `ReliabilityPolicy`.
- Preflight validates selected executor/store capabilities and reports
  unsupported retry, timeout, transaction, or lease policy cheaply where
  possible.
- Runner prepares a stage attempt, records transaction begin/prepared facts, and
  invokes the executor with resolved runtime and reliability metadata.
- Executor returns outputs or structured failure facts plus timeout/capability
  metadata. Executor facts are input to classification; they are not the retry
  decision itself.
- Runner records status detail, transaction transition, timeout outcome, and
  retry decision. If retry is allowed, the runner schedules the next attempt and
  records the decision before acting.
- Store/read models expose reliability records to APIs, preflight/inspection,
  CLI, and future Stage 20 event projection.

Dependency direction:

- `pipeline.reliability` depends only on foundational value, status,
  serialization, and timestamp modules.
- `pipeline.runtime` may depend on `pipeline.reliability` policy models for
  parsing and safe metadata.
- `pipeline.execution` depends on reliability protocols/models, runtime
  resolved policy, executors, and stores.
- `pipeline.stores` depends on reliability record models for persistence and
  read models, but reliability models must not depend on concrete store
  implementations.
- `diagnostics` depends on runtime validation and public read APIs; `cli`
  depends on diagnostics/read APIs. Runtime, execution, stores, and executors
  must not import diagnostics or CLI.

Extension points and flexibility boundaries:

- Extension points are classifier, retry evaluator, timeout capability/adapter,
  and store/read facets. They are generic over executor/store facts and must not
  encode SLURM, Docker, Apptainer, W&B, OpenTelemetry, or notification semantics.
- Retry actions remain runner/authority-owned; external event sinks and service
  integrations observe later Stage 20 events only.
- Timeout support is capability-reported and may be enforced, delegated,
  observed, unsupported, or timed out; it does not become a resource request.
- Lease behavior reuses existing authority/coordination lease contracts where
  possible and adds only diagnostics or narrow hardening needed for reliability
  policy compatibility.

Generic interface, adapter, or protocol shape:

- Classifier input should be a generic failure context containing run/stage/
  attempt refs, existing `ExecutionFailure`, status, executor name, exit/signal,
  timeout outcome, transaction state, and plain metadata.
- Retry evaluator input should be a policy, classification, attempt count,
  transaction state, and prior decision/attempt facts; output is a persisted
  decision with disposition, reason code, and next-action metadata.
- Timeout adapters should report support and outcome; concrete executors may
  enforce or delegate timeout but do not decide retry.
- Store protocols should append/read durable record types by run/stage/attempt
  references and preserve authority/local materialization boundaries.
- Records should carry stable IDs, timestamps, attempt references, transaction
  IDs, reason codes, and causal links for Stage 20 event projection.

Future-roadmap impact:

- Stage 20 can project reliability, transaction, retry, timeout, and failure
  facts into event records and observe-only sinks without inferring semantics
  from executor logs or status messages.
- Stage 21 can use transaction and cleanup-outcome facts for cleanup/retention
  planning without changing retry semantics or output authority rules.
- Future service-specific sinks, tracing, and hosted telemetry should remain
  plugins over Stage 20 event contracts, not dependencies of Stage 19.
- Future remote stores and orchestration adapters should implement the same
  reliability store/protocol contracts rather than inventing backend-specific
  retry or timeout semantics.

Compatibility constraints:

- Do not expand stable run/stage status enums for backend-specific reasons.
- Do not treat local `events.jsonl` as the source of reliability truth.
- Do not introduce a parallel global lease model.
- Do not make retry default-on.
- Do not add heavy notification, telemetry, cloud, container, or cluster
  dependencies to the default install.
- Preserve existing local run materialization and authority boundaries; any
  new local files must be versioned, inspectable, and compatible with
  authority-backed records.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Module ownership for reliability contracts. | FR-1, FR-7 | 1 | recorded recommendation | Add `loom.pipeline.reliability` as the import-light home for policy, record, and protocol types; keep execution/store/runtime integration in their existing subsystem packages. | Avoids hiding durable reliability contracts inside runner code while preserving source-tree dependency direction. | Repo structure and feature scope give a clear answer; no user input needed. | confirmed |
| DAQ-2 | Public config/runtime surface for reliability policy. | DAQ-1, FR-1, FR-5 | 2 | recorded recommendation | Add typed run-level and stage-level `reliability` policy under runtime options: `runtime.reliability` and `runtime.stage_options.<stage>.reliability`, instead of top-level `retry`/`timeout` fields or `ResourceRequest` timeout. | This locks a public authored-config/API path and determines how policy merges with executor/runtime options. | Confirmed by user and upheld by design-safety review. | confirmed |
| DAQ-3 | Reliability record persistence shape. | DAQ-1 | 3 | recorded recommendation | Persist reliability facts as versioned typed records with append/read store facets and read models, associated with existing run/stage/attempt/output-commit records rather than embedded only in status metadata. | Keeps facts durable, inspectable, and event-ready without overloading status files. | Repo store/read-model evidence gives a clear answer; design-safety review should challenge file-layout and authority compatibility. | confirmed |
| DAQ-4 | Failure classification and status detail design. | DAQ-1, FR-2 | 4 | auto-approved | Map current `ExecutionFailure` and executor facts into stable failure categories plus `StatusDetailRecord`; preserve `RunStatus` and `StageStatus` enums. | Prevents enum churn while improving diagnostics and retry inputs. | Behavior baseline and source status model already lock this; design-safety review upheld it. | confirmed |
| DAQ-5 | Transaction design around output commits. | DAQ-1, FR-3 | 5 | recorded recommendation | Add explicit stage-attempt transaction records around prepare/run/commit/failure/cleanup transitions and link them to existing `OutputCommitRecord` rather than replacing output commits. | Retry safety and authoritative output truth need a transaction timeline without discarding existing authority facts. | Repo authority/read-model shape gives a clear answer; no user input needed. | confirmed |
| DAQ-6 | Retry controller ownership. | DAQ-1, FR-4 | 6 | auto-approved | Keep retry decisions in runner/authority reliability flow using a pure evaluator; executors report facts and never own high-level retry policy. | Prevents hidden backend-specific retry behavior. | User already confirmed the automation boundary; design-safety review upheld it. | confirmed |
| DAQ-7 | Timeout capability and outcome integration. | DAQ-2, FR-5 | 7 | recorded recommendation | Extend runtime/executor capability diagnostics and executor result metadata to distinguish enforced, delegated, observed, unsupported, and timed-out outcomes; do not add timeout to resource requests. | Makes timeout capability-aware across local, subprocess, SLURM, and containers. | Timeout boundary is confirmed; only config path remains open through DAQ-2. | confirmed |
| DAQ-8 | Lease compatibility. | FR-9 | 8 | auto-approved | Reuse and harden existing authority/coordination leases and diagnostics; do not add a parallel global lease model. | Avoids duplicate lease semantics and preserves existing resource/trial lease foundations. | User already confirmed narrow reuse/hardening; design-safety review upheld it. | confirmed |
| DAQ-9 | Event-ready record boundary. | FR-8 | 9 | auto-approved | Include stable identifiers, timestamps, reason codes, transaction IDs, and causal links, but do not define Stage 20 event grammar, sink registry, or callback failure policy. | Preserves Stage 20 compatibility without mixing correctness with observer side effects. | User already confirmed Stage 20 owns event sinks/actions; design-safety review upheld it. | confirmed |
| DAQ-10 | Inspection and presentation boundary. | FR-10 | 10 | recorded recommendation | Expose read-only Python read models first and add narrow CLI output only where status/logs-style commands naturally present stored facts. | Keeps user-visible inspectability without creating broad new mutating CLI operations. | User already confirmed the narrow inspection scope. | confirmed |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Future-roadmap impact | Interface, adapter, or protocol impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Module ownership for reliability contracts. | Add `loom.pipeline.reliability` for import-light reliability policy, records, and protocols; keep integration in runtime/execution/stores/diagnostics/CLI. | Not asked; repo-supported recommendation. | Hiding all contracts inside `execution`; adding top-level `loom.reliability`; putting protocols in package-wide `loom.protocols`. | Reliability is pipeline-specific but cross-cuts execution, stores, runtime, and future events. | Improves locality and keeps runner code from becoming the public contract. | Gives future executors/stores a stable subsystem contract without importing concrete backends. | Stage 20 and Stage 21 can consume typed reliability facts. | New subsystem protocols must stay generic and import-light. | Package/API import tests plus serialization tests for public models. | Minor new package surface; revisit if design-safety review finds it too broad. | confirmed |
| DAQ-2 | Public config/runtime surface for reliability policy. | Add `reliability` policy under run-level and stage-level runtime options: `runtime.reliability` and `runtime.stage_options.<stage>.reliability`. | Approved by user. | Top-level `retry`/`timeout`; timeout as resource field; executor-specific adapter-only policy. | Retry/timeout are invocation policy and must merge with executor/runtime options without becoming resources. | A stable typed path is maintainable, but public naming is durable. | Stage-level overrides remain flexible; future policy keys can extend `ReliabilityPolicy`. | Future orchestration and event projection can read one resolved policy shape. | Adds typed policy fields to runtime option models and resolved metadata. | Runtime parsing/merge tests, config docs, preflight tests. | Public config path is durable; revisit if design-safety review finds it too broad, too narrow, or incompatible with future runtime config evolution. | confirmed |
| DAQ-3 | Reliability record persistence shape. | Persist typed versioned records through store facets/read models and associate them with current stage attempts, status records, output commits, and leases. | Not asked; repo-supported recommendation. | Store reliability facts only in status metadata; infer reliability from events/logs; replace existing authority records. | Durable facts need backend-neutral reads and must not overload status/events. | Keeps persistence explicit and testable. | Future stores implement narrow facets; future readers do not parse executor logs. | Stage 20 and Stage 21 consume committed facts directly. | Adds reliability store/read protocols and local/authority implementation obligations. | Store contract tests and local/authority read-model tests. | File layout details remain implementation-plan work; design-safety review should challenge migration risk. | confirmed |
| DAQ-4 | Failure classification and status detail design. | Add stable categories and status-detail records derived from `ExecutionFailure` and executor facts while preserving status enums. | Confirmed through behavior baseline. | New backend-specific status enum values; domain-specific category taxonomy. | Stable statuses remain policy vocabulary; detail carries explanation. | Reduces enum churn and keeps status consumers stable. | Categories can grow conservatively without becoming domain semantics. | Events can point to detail records later. | Adds classifier protocol and status-detail record type. | Unit tests for classifier defaults and status-detail serialization. | Category set may need refinement after executor coverage expands. | confirmed |
| DAQ-5 | Transaction design around output commits. | Add transaction records for attempt lifecycle and link committed output transitions to existing output commit records. | Confirmed through behavior baseline. | Treat output commits alone as full transaction history; replace output commits with transaction records. | Retry safety needs pre-commit and failure states as well as commit facts. | Makes failure/commit ordering explicit. | Future cleanup can reason from transaction and cleanup-outcome facts. | Stage 21 can consume transaction outcomes. | Adds transaction record model and store append/read facets. | Integration tests for success, failure, commit failure, rollback/failure, and cleanup outcome records. | Rollback semantics may start as recorded failure/cleanup outcome rather than physical deletion. | confirmed |
| DAQ-6 | Retry controller ownership. | Runner/authority reliability flow evaluates and records retry decisions before scheduling a next attempt. | Confirmed by user. | Executor-owned retry; hidden retry loops; event-sink-triggered retry. | Keeps correctness decisions centralized and inspectable. | Avoids backend-specific hidden control flow. | Custom evaluators can be swapped without changing executors. | Future orchestration can consume decisions without redefining retry. | Adds evaluator protocol and runner controller integration. | Unit tests for evaluator and integration tests for retry disabled/allowed/max-attempt/non-retryable cases. | Advanced backoff and cross-run budgets remain deferred. | confirmed |
| DAQ-7 | Timeout capability and outcome integration. | Model timeout as reliability policy with executor capability and outcome records; do not add timeout to `ResourceRequest`. | Confirmed by user, including the DAQ-2 config path. | Resource timeout field; assuming all executors enforce timeout; executor-specific timeout schemas. | Avoids two wall-time meanings and records unsupported behavior. | Keeps resource model focused on resource hints/limits. | New executors report capability/outcome through generic contracts. | Future adapters can observe timeout facts as events. | Adds timeout policy/outcome records and timeout adapter/capability protocol. | Policy normalization, preflight, fake executor, and subprocess timeout tests. | Scheduler-specific wall-time interpretation can evolve behind adapter metadata. | confirmed |
| DAQ-8 | Lease compatibility. | Reuse/harden existing resource/trial/stage/controller lease records and diagnostics; no parallel lease model. | Confirmed by user. | New global lease record family; scheduler health orchestration. | Current coordination contracts already cover named resource leases and renewal/failure. | Avoids duplicate concepts. | Future backends can strengthen existing lease capability guarantees. | Later sweeps/adapters can consume current lease contracts. | May add diagnostics or small record-field hardening only when needed. | Contract tests for lease renewal/failure and unsupported diagnostics. | Revisit if existing leases cannot express a Stage 19 reliability requirement. | confirmed |
| DAQ-9 | Event-ready record boundary. | Add stable IDs and causal links in reliability records but no event sink or observer contract. | Confirmed by user. | Stage 19 event sink registry; event-triggered runtime actions. | Keeps correctness separate from observers. | Reduces Stage 19 scope and future refactor risk. | Stage 20 can project events from committed facts. | Direct successor dependency for v20. | Records must include enough references for event projection. | Serialization tests asserting identity/reference fields. | Revisit only if Stage 20 cannot project from committed facts. | confirmed |
| DAQ-10 | Inspection and presentation boundary. | Read-only Python read models first; narrow CLI presentation through existing status/logs-style commands where useful. | Confirmed by user. | Broad reliability CLI operations; mutating retry/cleanup commands. | Inspectability matters, but operations beyond read-only would expand scope. | Keeps CLI thin over public APIs. | Future commands can build on read models without changing records. | Stage 20/21 can add separate inspection for events/cleanup. | Adds read-model/presentation contracts, not mutation APIs. | Read-model tests and CLI integration/e2e only if CLI output changes. | Revisit if users cannot inspect key facts without a new command. | confirmed |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | recorded recommendation | Could this live in existing modules only? Rejected because reliability records/protocols would otherwise be scattered across runner, runtime, and stores. | FR-1, FR-7, behavior baseline. | Upheld by design-safety review with import-light boundary constraints. | confirmed |
| DAQ-2 | recorded recommendation | Public config path is durable and not fully determined by source evidence, but the user approved `runtime.reliability` plus stage-level overrides and design-safety review found no contradiction. | FR-1, FR-5, behavior baseline. | Carry normalization and merge-semantics obligations into validation and phase shaping. | confirmed |
| DAQ-3 | recorded recommendation | Could status metadata or events be enough? Rejected because status/events are not the reliability source of truth. | FR-3, FR-6, FR-8. | Upheld by design-safety review with versioned store/read-model obligations. | confirmed |
| DAQ-4 | auto-approved | Could status enums expand? Rejected by confirmed behavior and current status model. | FR-2. | Upheld by design-safety review. | confirmed |
| DAQ-5 | recorded recommendation | Could output commits be the transaction record? Rejected because retry needs pre-commit/failure states. | FR-3, FR-4. | Upheld by design-safety review with Stage 21 cleanup boundary constraints. | confirmed |
| DAQ-6 | auto-approved | Could executors retry locally? Rejected by confirmed automation boundary. | FR-4. | Upheld by design-safety review. | confirmed |
| DAQ-7 | recorded recommendation | Could timeout be a resource field? Rejected by confirmed timeout boundary. | FR-5. | Upheld by design-safety review with separate operational-timeout constraints. | confirmed |
| DAQ-8 | auto-approved | Could a new lease family simplify reliability? Rejected because current coordination contracts already cover the shape. | FR-9. | Upheld by design-safety review. | confirmed |
| DAQ-9 | auto-approved | Could Stage 19 add event sinks now? Rejected by confirmed v20 boundary. | FR-8. | Upheld by design-safety review. | confirmed |
| DAQ-10 | recorded recommendation | Could CLI be broader? Rejected by confirmed narrow inspection scope. | FR-10. | Upheld by design-safety review. | confirmed |

## Design Safety Review

| Finding | Affected decision or requirement | Future-roadmap or compatibility risk | Interface, adapter, or protocol reuse risk | Recommended planning revision | Status |
| --- | --- | --- | --- | --- | --- |
| Public reliability config path is durable but coherent. The confirmed `runtime.reliability` plus `runtime.stage_options.<stage>.reliability` shape avoids top-level retry/timeout fields and avoids overloading `ResourceRequest`. | DAQ-2, FR-1, FR-5 | Future runtime config evolution could be constrained if merge semantics, unset versus explicit-disable semantics, and unknown-field rejection are not specified before implementation. | Policy models must remain generic and typed; executor-specific timeout or retry keys should live in adapter metadata only when they are facts, not policy. | Keep DAQ-2 upheld. Require the implementation plan to define normalization and merge rules for run-level defaults and stage-level overrides, including disabled policy, omitted policy, and unsupported-policy diagnostics. | recorded recommendation |
| `loom.pipeline.reliability` is a reasonable subsystem boundary only if it stays import-light and model/protocol focused. | DAQ-1, FR-7 | A broad subsystem could become a dumping ground for runner behavior, diagnostics, CLI presentation, or future event sinks. | Classifier/evaluator/timeout/store protocols remain reusable only if they depend on generic contexts and plain records, not concrete executors, stores, diagnostics, or plugin loading. | Keep DAQ-1 as a recorded recommendation. Add package/API validation obligations that `pipeline.reliability` imports cheaply and that execution, stores, runtime, diagnostics, and CLI keep the documented dependency direction. | recorded recommendation |
| Reliability records should be durable store facts, not status metadata, event records, or executor logs. | DAQ-3, FR-3, FR-6, FR-8 | Stage 20 events and Stage 21 cleanup would otherwise have to infer semantics from unstable messages or local-only logs. | Store facets remain reusable only if append/read contracts are keyed by run/stage/attempt/transaction references and preserve authority versus local materialization boundaries. | Keep DAQ-3. Require versioned record schemas, read-model tests, and explicit association with existing `StageAttempt`, `OutputCommitRecord`, `LeaseRecord`, and status records rather than replacement. Treat exact local file layout as implementation-plan detail. | recorded recommendation |
| Stable status enums plus status detail records remain safer than expanding `RunStatus` or `StageStatus`. | DAQ-4, FR-2 | Backend-specific enum growth would break planning/resume/catalog consumers and make Stage 20 event compatibility harder. | Failure classification stays reusable only if categories are generic runtime categories, with backend-specific data in metadata/detail fields. | Uphold DAQ-4 as auto-approved. Require classifier defaults to use existing `ExecutionFailure`, executor facts, timeout outcomes, and generic metadata while preserving current status enums. | auto-approved |
| Transaction records are needed in addition to existing output commits, but rollback and cleanup wording must not imply Stage 21 deletion behavior. | DAQ-5, FR-3, FR-4 | If Stage 19 records physical deletion or retention behavior, it will preempt Stage 21 and risk destructive semantics too early. | Transaction protocols should model ordered transitions and cleanup outcome facts, not cleanup execution strategies. | Keep DAQ-5. Clarify that Stage 19 records cleanup outcome/candidate facts and transaction failure/rollback status; explicit deletion, retention enforcement, and GC remain Stage 21. | recorded recommendation |
| Runner/authority-owned retry is the right correctness boundary. | DAQ-6, FR-4 | Executor-local hidden retry loops or event-triggered retry would make persisted decisions incomplete and undermine Stage 20 observe-only semantics. | Retry evaluator can be reused only if it is pure over policy, failure classification, attempt history, and transaction state, with action scheduling owned by runner/authority code. | Uphold DAQ-6 as auto-approved. Require retry decisions to be persisted before any next-attempt action and require tests for disabled, allowed, max-attempt, non-retryable, and unsafe-transaction cases. | auto-approved |
| Timeout belongs in reliability policy, but implementation must avoid confusing stage timeout with resource admission wait time or authority service control timeouts. | DAQ-7, FR-5 | Future executor adapters could expose incompatible wall-time semantics if the policy is not normalized into generic outcomes. | Timeout adapters stay generic only if support is reported as enforced, delegated, observed, unsupported, or timed out, with executor-specific scheduler/container details in metadata. | Keep DAQ-7. Require validation that no new `ResourceRequest` timeout field is introduced and that existing resource-admission or authority-supervisor timeout settings are documented as separate operational controls. | recorded recommendation |
| Existing lease contracts should be reused or narrowly hardened; a parallel global lease model is not justified. | DAQ-8, FR-9 | A second lease model would split authority truth and make later sweeps/adapters choose between incompatible lease semantics. | Lease compatibility remains reusable if named keys, slot counts, duration, renewal, release/failure, and diagnostics map onto existing `LeaseRecord`, `ResourceLeaseRecord`, and coordination protocols where possible. | Uphold DAQ-8 as auto-approved. Require the implementation plan to identify any missing lease fields or diagnostics before adding fields, and to reject scheduler-health orchestration in Stage 19. | auto-approved |
| Event-ready reliability records are useful, but Stage 19 must not define event names, event sink APIs, callback policy, or plugin loading. | DAQ-9, FR-8 | Premature event contracts would constrain Stage 20 and mix observer side effects with reliability correctness. | Causal references stay reusable if they are plain identifiers and links on committed facts rather than a hidden event grammar. | Uphold DAQ-9 as auto-approved. Keep only stable IDs, timestamps, run/stage/attempt refs, transaction IDs, reason codes, and causal links in Stage 19 records. | auto-approved |
| Narrow read-only inspection is acceptable, but mutating CLI/API operations remain out of scope. | DAQ-10, FR-10 | Broad retry, cleanup, event, or mutation commands would pull Stage 20/21 work into Stage 19 and expand public CLI lock-in. | Presentation remains reusable when CLI reads public read models and diagnostics only. | Keep DAQ-10. Implementation planning should make CLI output optional and scoped to existing status/logs-style commands unless read-model inspection alone cannot satisfy the user-visible outcome. | recorded recommendation |
| Stage 18 has no planning artifact in this checkout, so Stage 19 must not encode one final Apptainer/SLURM-container implementation shape. | FR-5, FR-7, DAQ-7 | Container timeout and failure facts may differ after Stage 18 is planned or implemented. | Timeout/failure protocols remain reusable only if they accept generic executor name, command/container/scheduler metadata, exit/signal facts, and capability outcomes without backend-specific required fields. | Carry the Stage 18 compatibility assumption into implementation-plan quality gates and require fake executor tests for unsupported/delegated/observed timeout behavior. | accepted risk |

Gate result:

- Status: passed
- Reviewer: Codex design-safety review pass on 2026-05-16
- Blockers:
  - None for design safety.
- Recorded recommendations:
  - Define reliability policy normalization and stage override merge semantics
    before implementation begins.
  - Keep `loom.pipeline.reliability` import-light and limited to policy,
    record, and protocol contracts.
  - Persist reliability facts as versioned store/read-model records associated
    with existing authority records; do not use status metadata, events, or
    executor logs as the source of truth.
  - Model Stage 19 cleanup only as transaction cleanup-outcome facts or cleanup
    candidates; leave deletion, retention enforcement, and GC to Stage 21.
  - Keep timeout policy separate from resource admission and authority service
    control timeouts.
  - Reuse or narrowly harden existing lease contracts instead of creating a
    parallel lease family.
  - Keep event readiness to stable identifiers and causal links; defer event
    grammar and sinks to Stage 20.
- Future-roadmap impact summary:
  - Stage 20 can project reliability facts into audit-ready events if Stage 19
    records stable identifiers, timestamps, reason codes, transaction IDs, and
    causal links without defining event names or observer contracts.
  - Stage 21 can consume transaction cleanup-outcome facts and cleanup
    candidates if Stage 19 avoids deletion and retention enforcement.
  - Future remote stores, orchestration adapters, and service integrations can
    reuse the same classifier/evaluator/timeout/store contracts if Stage 19
    keeps executor-specific details in metadata rather than public policy keys.
- Generic interface, adapter, and protocol assessment:
  - The proposed classifier, retry evaluator, timeout adapter/capability,
    reliability store/read facet, and runner controller surfaces are generic
    enough for implementation-plan drafting when they are expressed over plain
    runtime facts, existing authority references, and typed reliability records.
  - No service-specific, scheduler-health, event-sink, telemetry, or cleanup
    execution adapter should be introduced in Stage 19.
- Planning revisions required:
  - Reflect the recorded recommendations in validation and phase shaping before
    implementation-plan drafting.
- Accepted risks:
  - Stage 18 details are unavailable in this checkout; Stage 19 must use
    generic timeout/failure capability interfaces and fake executor validation
    until Apptainer/SLURM-container specifics are locked elsewhere.
  - Exact local file layout for reliability record materialization remains
    deferred to implementation planning; the design-safety requirement is
    versioned, inspectable, authority-compatible records.
  - Rollback may initially mean recorded transaction failure and cleanup
    outcome/candidate facts, not physical deletion; destructive cleanup remains
    Stage 21.
- Revisit triggers:
  - Reopen planning if reliability policy merge semantics cannot distinguish
    omitted policy from explicit disablement.
  - Reopen planning if existing authority/coordination lease records cannot
    express named resource keys, slot counts, duration, renewal, and renewal
    failure diagnostics without a public contract change.
  - Reopen planning if Stage 20 cannot project events from Stage 19 committed
    facts without adding event-specific fields to Stage 19 records.
  - Reopen planning if Stage 18 introduces container timeout or failure
    contracts that contradict the generic Stage 19 capability model.

Design-safety recheck result:

- Status: passed
- Reviewer: `loom_design_safety_reviewer` recheck on 2026-05-16 after the
  structured examples, validation strategy, code-integration map, and six-phase
  split were confirmed.
- Blockers:
  - None.
- Non-blocking recommendation addressed in this artifact:
  - Clarified that representative `max_attempts` means total attempts,
    including the initial attempt, and aligned the conceptual allowed-retry
    example with a stage that inherits the run-level `max_attempts: 2` policy.
- Carried recommendation:
  - Implementation planning must preserve the existing Stage 19 cleanup
    boundary: cleanup wording means transaction cleanup-outcome/candidate facts
    only, not deletion or retention enforcement.
- Readiness assessment:
  - Ready for implementation-plan drafting. No unresolved `needs discussion`
    or `blocked` decisions remain; Stage 20 event/sink and Stage 21 cleanup/
    retention boundaries are preserved.

## Practical Design Notes

Public Python API surface:

- Confirmed: import-light models/protocols under `loom.pipeline.reliability`, with
  runtime option integration through `loom.pipeline.runtime` and read-model
  access through store/inspection APIs.

CLI surface:

- Confirmed: narrow read-only presentation through existing status/logs-style
  commands where stored reliability facts improve diagnosis; no mutating retry,
  cleanup, or event-sink commands in Stage 19.

Persisted records and file layout:

- Confirmed: versioned reliability records linked to run/stage/attempt,
  transaction, output commit, retry decision, timeout outcome, and status-detail
  facts. Exact local file layout remains implementation-plan detail, but
  records must be inspectable and authority-compatible.

Import boundaries and dependencies:

- Confirmed: reliability models stay import-light; runtime may import policy
  models; execution composes policies with executors/stores; stores persist
  records; diagnostics/CLI read public APIs only.

Failure modes and diagnostics:

- Confirmed: unsupported policy is visible through preflight/runtime diagnostics;
  commit failure records transaction failure and does not mark outputs
  authoritative; retry decisions are recorded before any next attempt.

Extension points and flexibility boundaries:

- Confirmed: extension points are classifier, retry evaluator, timeout capability/
  adapter, reliability store/read facets, and runner-owned controller hooks.
  No service-specific, event-sink, telemetry, or scheduler-health semantics.

Generic interfaces, adapters, and protocols:

- Confirmed: protocols consume generic failure, timeout, transaction, and
  capability facts; they must not encode one executor, store backend, scheduler,
  container runtime, or external integration.

Future-roadmap compatibility:

- Confirmed: Stage 20 projects committed reliability facts into events and
  observe-only sinks; Stage 21 consumes transaction/cleanup-outcome facts for
  cleanup and retention.

Maintainability assessment:

- Confirmed: centralizing reliability contracts reduces runner/store scattering.
  The confirmed public config path in DAQ-2 is durable and now carries explicit
  normalization and merge-semantics obligations for implementation planning.

Extensibility assessment:

- Confirmed: generic classifier/evaluator/timeout/store protocols support future
  executors and stores without introducing service-specific dependencies.

Flexibility and expansion assessment:

- Confirmed: record schemas are expected to be versioned; advanced backoff,
  cross-run budgets, resource escalation, external actions, and cleanup remain
  explicit future extensions.

Scalability and future compatibility:

- Confirmed: store/read facets should support authority-backed records and local
  materialization without relying on events/log parsing or destructive
  migration.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Exact local reliability-record file layout deferred from roadmap planning. | The planning artifact has enough safety constraints for implementation-plan drafting without preselecting path names or storage internals. | Revisit during implementation planning before any store phase starts, and require authority-compatible versioned records. |
| Stage 18 container execution specifics unavailable in this checkout. | The user explicitly narrowed Stage 19 and accepted carrying compatibility assumptions until Stage 18 planning exists. | Revisit if Stage 18 records conflict with generic timeout/failure capability assumptions. |
| Rollback semantics start as recorded transaction failure and cleanup outcome/candidate facts. | Physical deletion, retention enforcement, and GC are Stage 21 responsibilities and should not be smuggled into Stage 19. | Revisit in Stage 21 cleanup/retention planning. |

## Examples And Demonstrations

The examples below are the agreed structure for explaining Stage 19 behavior in
the implementation plan. They are intended to make the reliability layer
concrete before phase work starts: policy is authored in runtime config, the
runner resolves and applies it, executors report facts, stores persist
decisions, and diagnostics/inspection read the committed reliability records.

### Representative Authored Policy

The exact field names remain implementation-plan detail, but the confirmed
public config path is:

```yaml
runtime:
  reliability:
    retry:
      max_attempts: 2
      retry_on:
        - timeout
        - executor_failure
    timeout:
      wall_time_seconds: 1800
      grace_seconds: 30

  stage_options:
    train:
      reliability:
        retry:
          max_attempts: 1
        timeout:
          wall_time_seconds: 3600
```

Required behavior:

- Run-level `runtime.reliability` provides defaults.
- `runtime.stage_options.<stage>.reliability` overrides those defaults for one
  stage.
- Omitted policy is distinct from explicitly disabled policy.
- `max_attempts` means total attempts, including the initial attempt. The
  implementation plan locks this as the Stage 19 public retry policy field.
- Retry remains off unless the resolved policy, failure classification,
  remaining attempt budget, and transaction safety all allow it.
- Timeout is reliability policy, not a `ResourceRequest` field.

### Canonical Failed-Attempt Flow

The implementation plan should preserve this control-flow shape:

1. Runtime parses and normalizes the authored reliability policy.
2. Runtime resolves the effective policy for the target stage.
3. Preflight checks whether the selected executor can support the requested
   timeout and reliability behavior.
4. The runner allocates a stage attempt and starts a transaction record.
5. The executor runs once and reports facts, such as `ExecutionFailure`,
   process exit code, signal, cancellation, executor metadata, or timeout
   outcome.
6. The failure classifier emits `FailureClassification` and
   `StatusDetailRecord` without adding backend-specific status enums.
7. The transaction record captures whether outputs were committed, failed,
   ambiguous, or cleanup-relevant.
8. The retry evaluator writes a `RetryDecisionRecord` before any next attempt
   is scheduled.
9. If retry is allowed, runner/authority code schedules the next attempt.
10. If retry is denied, the stage remains failed with an inspectable reason.

Conceptual allowed retry record:

```text
stage: preprocess
attempt: 1
decision: retry
reason: classified_timeout
max_attempts: 2
transaction_safe: true
next_attempt: 2
```

Conceptual denied retry record:

```text
stage: train
attempt: 1
decision: do_not_retry
reason: unsafe_transaction_state
transaction_safe: false
```

### Code Integration Examples

| Current area | Stage 19 behavior | Design constraint |
| --- | --- | --- |
| `loom.pipeline.runtime` | Parses and resolves `runtime.reliability` plus stage-level reliability overrides. | Do not revive top-level deferred `retry`/`timeout` fields or add timeout to resources. |
| `loom.pipeline.reliability` | Defines import-light policy, classification, transaction, retry-decision, timeout-outcome, and protocol records. | Do not import concrete executors, stores, diagnostics, CLI, plugins, or optional backends. |
| `loom.pipeline.execution` | Composes transaction recording, failure classification, timeout outcomes, retry decisions, and runner-owned next attempts. | Executors report facts; runner/authority code owns retry action. |
| `loom.pipeline.executors` | Reports execution failures, timeout facts, and capability outcomes. | No hidden executor-local retry loops. |
| `loom.pipeline.stores` | Persists reliability facts as versioned records linked to existing run, stage, attempt, status, lease, and output-commit facts. | Do not use event logs, status metadata, or executor logs as the source of truth. |
| `loom.pipeline.runtime.capabilities` and diagnostics | Report unsupported or partial reliability behavior cheaply. | Real clusters, containers, cloud services, and network services stay out of default validation. |
| CLI/read models | Expose read-only reliability facts where existing status/logs-style surfaces naturally fit. | No mutating retry, cleanup, or event-sink commands in Stage 19. |

### Behavior Examples

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| Reliability policy merge | Run-level `runtime.reliability` defaults merge with `runtime.stage_options.<stage>.reliability`, distinguishing omitted policy from explicit disablement. | runtime options parser | reliability/runtime docs plus unit tests | confirmed |
| Retry-safe failed stage | A failed attempt with uncommitted outputs is eligible for one retry only when policy allows it. | local or fake executor | reliability docs plus unit/integration tests | confirmed |
| Unsafe transaction blocks retry | A failed attempt with committed or ambiguous partial outputs records retry denial before any next attempt. | fake store or fake executor | reliability/execution docs plus evaluator and integration tests | confirmed |
| Unsupported timeout | A selected executor cannot enforce timeout, so preflight and persisted metadata warn clearly. | fake executor descriptor | preflight docs plus contract tests | confirmed |
| Distinct timeout outcomes | Enforced, delegated, observed, unsupported, and timed-out outcomes are recorded without adding timeout to `ResourceRequest`. | fake executor and subprocess-style adapter | runtime/reliability docs plus fake executor tests | confirmed |
| Transaction commit failure | A stage reaches execution but commit fails; Loom records transaction status and retry eligibility without reporting partial outputs as authoritative. | fake store or fake executor | reliability/execution docs plus integration tests | confirmed |
| Status detail without enum churn | A failure records category, reason code, lifecycle phase, and message while preserving stable `RunStatus` and `StageStatus` values. | local/fake executor failure | state/reliability docs plus serialization and integration tests | confirmed |
| Lease compatibility diagnostic | A selected reliability policy requiring named resource lease behavior reports unsupported or renewal-failure diagnostics through existing lease contracts. | fake coordination capability set | reliability/preflight docs plus lease contract tests | confirmed |
| Read-only reliability inspection | Stored policy, status detail, transaction, retry decision, and timeout facts are available through read models and narrow status/logs-style CLI output when included. | local run store | run-store/cli docs plus read-model and CLI tests if CLI changes | confirmed |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package and import boundaries | `loom.pipeline.reliability` imports cheaply and does not import concrete executors, diagnostics, CLI, plugins, or optional backends. | Package/API import tests. | package / unit | `make validate-pr`; targeted package tests | confirmed |
| Policy records and runtime merge | Retry/timeout/reliability policy serialization, unknown-field rejection, omitted versus disabled semantics, run-level defaults, and stage-level overrides. | Unit and contract tests. | unit / contract | targeted runtime/reliability tests; `make validate-pr` | confirmed |
| Failure classification and status detail | Existing `ExecutionFailure`, exit code, signal, timeout outcome, cancellation, executor metadata, and store commit failure map to stable categories and detail records without status enum expansion. | Unit and integration tests. | unit / integration | targeted reliability/execution tests; `make validate-pr` | confirmed |
| Transaction records | Begin, prepared/running/staged, commit, rollback/failure, cleanup outcome/candidate, causal links, and retry eligibility are recorded in order. | Unit, contract, and integration tests. | unit / contract / integration | targeted store/execution tests; `make validate-pr` | confirmed |
| Store/read-model facets | Local and authority-compatible stores append/read policy, status-detail, transaction, retry-decision, and timeout records as versioned facts associated with existing authority records. | Store contract and read-model tests. | contract / integration | targeted store tests; `make validate-pr` | confirmed |
| Retry safety | No retry without explicit policy, classified retryable failure, remaining attempts, and safe transaction state; decisions persist before any next attempt. | Unit and integration tests with fake stages. | unit / integration | targeted evaluator/runner tests; `make validate-pr` | confirmed |
| Timeout support | Enforced, delegated, observed, unsupported, and timed-out outcomes are distinct; no timeout field is added to `ResourceRequest`; operational timeouts remain separate. | Unit, contract, and fake executor integration tests. | unit / contract / integration | targeted runtime/executor/preflight tests; `make validate-pr` | confirmed |
| Lease compatibility | Existing authority/coordination lease records cover named keys, slot counts, duration, renewal, failure, and unsupported diagnostics or record a bounded gap. | Contract tests for fake/local coordination stores. | contract / integration | targeted coordination/store tests; `make validate-pr` | confirmed |
| Preflight diagnostics | Unsupported retry, timeout, transaction, and lease policies produce cheap, explicit diagnostics without real clusters, containers, cloud services, network services, or heavy optional dependencies. | Contract and integration tests. | contract / integration | targeted preflight tests; `make validate-pr` | confirmed |
| Read-only inspection | Read models and optional narrow CLI output expose reliability facts without mutating state. | Read-model tests; CLI integration/e2e only if CLI output changes. | integration / e2e | targeted CLI/read-model tests; `make validate-pr` | confirmed |
| Final PR evidence | Required suite gate and summary evidence are captured for PR preparation. | Full repository validation. | validation gate | `make validate-pr`; `make test-summary` before PR preparation | confirmed |
| Opt-in/external environments | Real SLURM/container/cluster behavior is not required by default; fake executors validate generic contracts until Stage 18 specifics exist. | Optional only when environment is available. | opt-in | no default command; document skipped opt-in coverage in PR evidence | confirmed |

## Phase Sketch

### Phase 1 - Reliability Contracts And Runtime Policy

Goal:

- Add import-light reliability policy, record, and protocol contracts plus the
  public runtime config surface.

Scope:

- Create `loom.pipeline.reliability` models/protocols for reliability policy,
  retry policy, timeout policy, failure classification/status detail,
  transaction, retry decision, timeout outcome, and generic classifier/
  evaluator/timeout/store/controller protocol shapes.
- Add `runtime.reliability` and
  `runtime.stage_options.<stage>.reliability` parsing, serialization,
  unknown-field rejection, and merge semantics.
- Define omitted versus explicit-disabled policy behavior.

Out of scope:

- Runner retry behavior, transaction persistence, timeout enforcement, store
  implementations, CLI output, event sinks, cleanup/deletion.

Acceptance criteria:

- Public model imports are cheap and typed.
- Runtime policy merge rules are documented and tested.
- No timeout field is added to `ResourceRequest`.

Test expectations:

- Package: import-boundary checks for `loom.pipeline.reliability`.
- Unit: policy and record serialization, merge, validation, disabled/unset
  semantics.
- Contract: runtime option round-trip contracts.
- Integration: none required beyond runtime parsing.
- E2E: none.
- Opt-in: none.

Design impact:

- Establishes the public config/API surface and import-light contract boundary.

Future compatibility:

- Gives Stage 20/21 and future executors/stores stable typed facts without
  service-specific policy keys.

Alternatives rejected:

- Top-level `retry`/`timeout`, timeout in `ResourceRequest`, executor adapter
  metadata as the only policy surface, event-sink policy.

Debt introduced:

- Exact persistence file layout remains deferred.

Reviewability:

- Narrow API/config diff with focused serialization and runtime tests.

### Phase 2 - Reliability Persistence And Read Models

Goal:

- Add store/read-model facets for reliability facts without replacing existing
  authority records.

Scope:

- Persist versioned status-detail, transaction, retry-decision, timeout-outcome,
  and policy fact records keyed by run/stage/attempt and causal references.
- Associate records with existing `StageAttempt`, `OutputCommitRecord`,
  `LeaseRecord`, status, and materialized local records.
- Add local and authority-compatible read contracts and fake/local contract
  coverage.

Out of scope:

- Runner retry automation, timeout enforcement, event grammar, cleanup deletion,
  broad CLI commands.

Acceptance criteria:

- Reliability records are durable store facts, not status metadata, event logs,
  or executor-log parsing.
- Records are versioned, inspectable, and authority-compatible.

Test expectations:

- Package: imports remain boundary-safe.
- Unit: record validation and serialization.
- Contract: store append/read facets and read-model association tests.
- Integration: local run-store persistence and fake authority behavior.
- E2E: none.
- Opt-in: none.

Design impact:

- Defines the persistence surface implementation phases will depend on.

Future compatibility:

- Enables Stage 20 event projection and Stage 21 cleanup/retention planning.

Alternatives rejected:

- Embedding all reliability facts in status metadata, event logs, or executor
  logs.

Debt introduced:

- Local file paths may still be refined in the implementation plan before store
  work begins.

Reviewability:

- Store-focused diff with contract tests before runner behavior changes.

### Phase 3 - Transaction And Failure Classification Integration

Goal:

- Record transaction/status-detail facts around stage attempts and classify
  failures without changing status enums.

Scope:

- Integrate transaction begin/prepared/running/staged/commit/failure/cleanup
  outcome recording into stage attempt lifecycle.
- Add default failure classifier over `ExecutionFailure`, exit code, signal,
  timeout outcome, cancellation, executor metadata, store commit failures, and
  plain detail.
- Persist status detail before final failed status where applicable.
- Ensure commit failures do not mark partial outputs authoritative.

Out of scope:

- Automatic retry, timeout enforcement implementation, Stage 21 deletion or
  retention behavior.

Acceptance criteria:

- Successful commit, stage failure, cancellation, commit failure, and cleanup
  outcome facts are ordered and inspectable.
- Stable `RunStatus` and `StageStatus` enums are preserved.

Test expectations:

- Package: no new import cycles.
- Unit: classifier and transaction state validation.
- Contract: transaction/read-model persistence.
- Integration: fake/local runner paths for success, failure, cancellation, and
  commit failure.
- E2E: minimal local failure flow if CLI/API behavior changes.
- Opt-in: none.

Design impact:

- Establishes retry-safety evidence before retry automation exists.

Future compatibility:

- Stage 21 cleanup can consume cleanup-outcome/candidate facts without Stage 19
  deleting files.

Alternatives rejected:

- Treating `OutputCommitRecord` alone as the full transaction history.

Debt introduced:

- Rollback means recorded transaction failure and cleanup outcome/candidate
  facts, not physical deletion.

Reviewability:

- Execution/store behavior change isolated before retry loops are introduced.

### Phase 4 - Timeout Capability And Reliability Diagnostics

Goal:

- Add capability-aware timeout outcomes and cheap reliability diagnostics.

Scope:

- Add timeout capability/outcome reporting for enforced, delegated, observed,
  unsupported, and timed-out cases.
- Integrate fake executor and subprocess-style timeout behavior where feasible.
- Add preflight/runtime diagnostics for unsupported retry, timeout,
  transaction, and lease policies.
- Reuse or narrowly harden existing authority/coordination lease diagnostics.
- Document separation between reliability timeout and resource admission or
  authority service operational timeouts.

Out of scope:

- Scheduler-health orchestration, executor migration, resource-aware retry
  escalation, real cluster/container requirements in default tests.

Acceptance criteria:

- Unsupported or partial timeout support is visible and persisted.
- No resource timeout field is introduced.
- Lease policy gaps surface as diagnostics, not a new parallel lease model.

Test expectations:

- Package: no concrete executor imports from reliability contracts.
- Unit: timeout outcome serialization and diagnostics.
- Contract: fake executor capability and lease diagnostics.
- Integration: preflight diagnostics and fake/subprocess-style timeout paths.
- E2E: none by default.
- Opt-in: real SLURM/container tests only if available and documented.

Design impact:

- Locks capability-aware timeout behavior before retry policy consumes timeout
  failures.

Future compatibility:

- Keeps Stage 18 container specifics generic and Stage 20 event projection
  fact-based.

Alternatives rejected:

- Treating timeout as a resource request or assuming all executors enforce it.

Debt introduced:

- Backend-specific timeout metadata remains plain detail until later executor
  stages require stronger contracts.

Reviewability:

- Diagnostics/capability diff with fake executors and no external service
  dependency.

### Phase 5 - Retry Decisions And Runner-Owned Automation

Goal:

- Implement conservative opt-in retry using persisted decisions and transaction
  safety evidence.

Scope:

- Add default retry evaluator over policy, failure classification, attempt
  history, max attempts, transaction state, and timeout outcome.
- Persist retry decisions before any next-attempt scheduling.
- Add runner-owned next-attempt behavior for explicit allowed retry only.
- Preserve non-retryable validation, graph/config, cancellation, unsafe
  transaction, max-attempt, and unsupported-policy behavior.

Out of scope:

- Advanced backoff, cross-run retry budgets, resource-aware escalation,
  executor-local retry loops, event-triggered retry.

Acceptance criteria:

- Retry is off by default.
- Allowed and denied retry decisions are explainable and durable.
- Executors report facts; runner/authority code owns retry action.

Test expectations:

- Package: import boundaries unchanged.
- Unit: evaluator matrix for disabled, allowed, denied, max-attempt,
  non-retryable, timeout, and unsafe transaction cases.
- Contract: retry-decision record persistence.
- Integration: fake runner stages demonstrating no retry, one retry, denied
  retry, and persisted decision ordering.
- E2E: minimal local retry flow if public behavior warrants it.
- Opt-in: none.

Design impact:

- Introduces the only Stage 19 runtime-changing automation.

Future compatibility:

- Future orchestration can consume decisions without changing executor
  semantics.

Alternatives rejected:

- Hidden executor retry, event-sink-triggered retry, default-on retry.

Debt introduced:

- Advanced retry orchestration remains deferred.

Reviewability:

- Behavior-heavy phase with focused evaluator and runner tests.

### Phase 6 - Read-Only Inspection, Documentation, And Final Validation

Goal:

- Expose reliability facts for users and complete documentation and validation
  evidence.

Scope:

- Add read-only Python read-model access and narrow CLI status/logs-style
  presentation where materially useful.
- Update `reliability.md`, `execution.md`, `run-store.md`, `state.md`,
  `preflight.md`, `cli.md`, and `testing.md` for final behavior.
- Run final validation and collect suite evidence for PR preparation.

Out of scope:

- Mutating retry commands, cleanup commands, event sink commands, service
  notifications, telemetry clients.

Acceptance criteria:

- Users can inspect policy, status detail, transaction state, retry decisions,
  timeout outcomes, and unsupported-policy diagnostics.
- CLI remains a thin read-only wrapper when included.
- Final evidence records `make validate-pr` and `make test-summary` or clearly
  justified unavailable checks.

Test expectations:

- Package: public imports stay stable.
- Unit: formatting/read-model helpers if added.
- Contract: read-model output contracts.
- Integration: local read-model inspection and CLI output if included.
- E2E: narrow CLI/status/logs e2e only if public CLI output changes.
- Opt-in: none by default.

Design impact:

- Completes the user-visible inspectability outcome without broad mutation
  surfaces.

Future compatibility:

- Keeps Stage 20/21 separate while making their future facts visible through
  committed records.

Alternatives rejected:

- Broad reliability command group, cleanup commands, event sink operations.

Debt introduced:

- If CLI output is deferred, implementation plan must explain how Python/read
  models alone satisfy the Stage 19 user-visible outcome.

Reviewability:

- Final presentation/docs/validation phase after correctness behavior lands.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | Startup extraction, narrowed scope, intent, capability triage, confirmed functionality agreement, and confirmed behavior baseline from `docs/roadmap.md` v19 plus user confirmations. | pass | Keep traceability current if design scope changes. |
| Requirement-to-design traceability | Functional requirements map to proposed implementation shape and confirmed DAQ-1 through DAQ-10. | pass | Keep traceability current if design-safety review changes the design. |
| Design-safety review completed | Completed in this artifact, with a follow-up recheck passing after the examples and validation structure update. | pass | Carry recorded recommendations and accepted risks into implementation-plan drafting. |
| Future-roadmap impact considered | Stage 20 event projection and Stage 21 cleanup/retention touchpoints are drafted and design-safety reviewed. | pass | Preserve Stage 20/21 boundaries during validation and phase shaping. |
| Generic interface, adapter, and protocol flexibility considered | Classifier, retry evaluator, timeout adapter/capability, store/read facet, and runner controller protocol shape reviewed as generic enough with constraints recorded above. | pass | Keep protocols plain, import-light, and backend-neutral in implementation planning. |
| Example-to-validation traceability | Examples and validation strategy are confirmed with suite obligations for policy merge, failure classification, transactions, stores, retry, timeout, leases, preflight, inspection, final validation, and opt-in coverage. | pass | Carry the examples and suite obligations into implementation-plan drafting. |
| Phase-shaping readiness | Six-phase sketch confirmed: contracts/runtime policy, persistence/read models, transaction/classification, timeout/diagnostics, retry automation, and inspection/docs/final validation. | pass | Carry the phase boundaries into implementation-plan drafting. |
| Unresolved blocked or needs-discussion functionality or design decisions | No unresolved functionality or design decisions remain after DAQ-2 approval, design-safety review, and design-safety recheck. | pass | Proceed to implementation-plan drafting. |

Readiness result:

- Status: ready for implementation-plan drafting
- Implementation-plan drafting blockers:
  - None.
- Accepted risks:
  - Stage 18 details are roadmap-only until a Stage 18 artifact exists.
  - Exact reliability record file layout remains implementation-plan detail.
  - Stage 19 rollback/cleanup records do not perform Stage 21 deletion or
    retention behavior.
- Assumptions to carry forward:
  - Stage 18 details are roadmap-only until a Stage 18 artifact exists.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Do you have clarifying questions about the Stage 19 briefing before we move into capability triage? | Roadmap framing | Answer from repo evidence and record resolved clarifications. | resolved |
| What should narrowed Stage 19 optimize for relative to the roadmap description? | User intent, capability triage, later design choices | Optimize for conservative, inspectable, cross-executor retry/timeout/transaction contracts. | resolved |
| Should the current Stage 19 roadmap item be split? | Roadmap framing, capability triage, phase sizing, future roadmap numbering | Split applied in `docs/roadmap.md`: Stage 19 reliability/transactions, Stage 20 events/sinks, Stage 21 cleanup/retention. | resolved |
| Should Stage 19 reuse/harden existing authority/coordination lease contracts instead of adding a parallel global lease model? | Capability triage, functionality agreement, design shape | Reuse/harden existing contracts narrowly. | resolved |
| Should Stage 19 include narrow read-only CLI inspection, or keep inspection as Python/read-model only until later? | Capability triage, user-visible behavior, validation | Include read models and only add CLI where existing status/logs commands naturally expose the facts. | resolved |
| Should timeout be a reliability policy with executor capability outcomes, avoiding a competing resource timeout field? | Functionality agreement, behavior baseline, design shape | Yes; treat timeout as reliability policy and record unsupported/delegated/observed/enforced/timed-out outcomes. | resolved |
| Is the drafted behavior baseline complete enough to start design agreement? | Behavior confirmation, design agreement | Use the baseline above unless the user revises included behavior, defaults, failure diagnostics, deferrals, or out-of-scope behavior. | resolved |
| Should authored reliability policy live under `runtime.reliability` with stage-level overrides under `runtime.stage_options.<stage>.reliability`? | DAQ-2, public config/API surface, runtime parsing, preflight, docs | Yes; keep retry/timeout as typed runtime reliability policy instead of top-level `retry`/`timeout`, resource timeout, or executor-specific adapter metadata. | resolved |
| Are the structured examples, validation strategy, and six phase boundaries acceptable for implementation-plan readiness? | Examples, validation strategy, phase shaping, implementation readiness | User accepted the structure; use the confirmed examples, suite obligations, and six-phase split. | resolved |

## Handoff Notes

Implementation-plan draft inputs:

- Use this confirmed planning artifact as the primary source for
  `docs/roadmap/stage-19/implementation-plan.md`.
- Required inputs include the representative authored policy, canonical
  failed-attempt flow, code-integration map, confirmed validation strategy,
  confirmed six-phase split, design-safety findings, accepted risks, and
  Stage 20/21 boundaries.
- Draft status: created in `docs/roadmap/stage-19/implementation-plan.md`;
  implementation-plan quality gate passed on 2026-05-16 after
  `loom_plan_reviewer` review, bounded refinement, and confirmation review.

Design-safety review result:

- Passed with recorded recommendations and accepted risks. The follow-up
  design-safety recheck after the examples/validation update also passed. No
  design-safety blockers remain.

Validation and phase-shaping inputs:

- Confirmed in this artifact. Inputs include the representative authored
  policy, canonical failed-attempt flow, code-integration map, examples and
  validation table, plus the six-phase sketch covering contracts/runtime
  policy, persistence/read models, transaction/classification, timeout/
  diagnostics, retry automation, and inspection/docs/final validation.

Plan-quality-gate risks:

- Stage 19 spans public models, persisted records, execution semantics,
  store/authority contracts, diagnostics, and CLI inspection. The eventual
  implementation plan will need a strong plan quality gate and likely multiple
  reviewable phases.

Assumptions to carry forward:

- Runtime events and event sinks move to Stage 20.
- Cleanup/deletion remains Stage 21.
- Service-specific sinks remain plugin/future work after the Stage 20 event
  sink model exists.
- Retry remains conservative and opt-in unless user feedback changes the
  planning priority.
- Stage 18 compatibility is based on roadmap and feature docs only until Stage
  18 planning exists.
