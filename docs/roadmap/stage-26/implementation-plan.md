# Roadmap Stage 26 Implementation Plan: Operational Correctness And Notifications

Status: draft; expanded design review pending
Roadmap stage: `v26`
Planning document: `docs/roadmap/stage-26/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 1 pending
Blockers: expanded design review and final manager quality gate

## Summary

- Goal: make existing stage authoring, artifacts, logs, and lifecycle behavior
  easy to use correctly, then add one service-neutral lifecycle-notification
  feature over committed events.
- Approved behavior and requirement IDs: planning `FR-1` through `FR-10` cover
  the stage-author path, executor-specific logging truth, evidence-backed
  correctness fixes, generic notification values/policy/protocol/registration,
  safe message projection, explicit Python setup, and unchanged validation
  gates.
- Key design constraints and decision IDs: `FQ-1` through `FQ-8` and `DQ-1`
  through `DQ-8` retain current artifact, lifecycle, event, sink, observer,
  plugin-activation, and test-harness owners.
- Minimum useful change: one simple downstream-operations guide plus a small
  `loom.pipeline.notifications` adapter that selects significant lifecycle
  events, produces allowlisted messages, calls a project notifier, and reuses
  existing sink failure/link evidence.
- Complexity deliberately excluded: a notification dispatcher/store/receipt
  schema, arbitrary templates or payload predicates, provider SDKs, async
  queues, retry/deduplication/delivery guarantees, generic scheduling,
  resource-usage sampling, new resume policy, and validation-gate/profile work.
- Validation and phase-shaping source: planning `Examples And Validation` and
  `Phase Shaping`; combined tests are limited to commit/observation,
  failure/continuation, and external-reference/link identity.
- Out of scope: every planning deferral, Stage 25 queue policy, Stage 27 GPU
  setup, Stage 28 plugin activation/subscriptions, Stage 29 daemon/agent work,
  and domain-specific payload meaning.

## Shared Constraints

- Architecture and dependency direction:
  - stage code uses the `StageContext` facade and returns `ArtifactRef` values;
    it never receives a public mutable store handle;
  - runner/lifecycle/store commits remain authoritative and precede events;
  - event registry remains the only callback dispatcher and owns callback
    ordering/failure capture;
  - `loom.pipeline.notifications` may consume import-light event/sink/plain-data
    contracts, but event/store/runner modules do not import provider code; and
  - provider clients, credentials, formatting, and network behavior remain in
    trusted project code or optional plugins.
- Shared public and durable contracts:
  - no event, observer, lifecycle, artifact, queue, resource, resume, or plugin
    schema changes;
  - notification severity/message/policy and notifier protocol are immutable
    in-process values; only `NotificationMessage.to_dict()` exposes a plain
    adapter projection;
  - `register_lifecycle_notifier(...)` registers one ordinary named event sink
    and uses that same name for optional observer-link evidence; and
  - notification selection does not replace Stage 28 exact registry
    subscriptions. Before or without Stage 28, the sink may receive and ignore
    unselected events.
- Shared reproducibility, compatibility, and import constraints:
  - no notifier registration means zero notification discovery or work;
  - defaults select only the six planning-approved significant event types;
  - arbitrary event payloads, exception/reason text, config, commands,
    environment, logs, and artifact contents never enter default messages;
  - existing sinks, executors, log paths, CLI output, and validation commands
    remain compatible; and
  - no runtime dependency is added.
- Shared invariant ownership:
  - feature specs/source own behavior; the downstream guide owns the simple
    user journey;
  - executor/store/SLURM manifests own captured stream paths;
  - project code owns separate file handlers and domain log content;
  - notification policy/projector owns selection, severity, and safe fields;
  - notifier owns delivery; event registry owns failure isolation; sink context
    and store own observer-link recording.
- Decisions no phase may reopen: only notifications are a Stage 26 feature; no
  generic scheduler, resource sampler, new resume policy, new PR gate/profile,
  provider adapter, outbox/retry/delivery guarantee, mutable callback, generic
  redactor/template engine, or durable notification schema.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `stage-author-correctness-and-logging` | pending | `docs/roadmap/stage-26/phases/stage-author-correctness-and-logging.md` | `agent/stage-26-p1-stage-author-correctness-and-logging` | pending | Downstream guide, artifact/log/event docs, examples, demonstrated compatibility corrections | Give stage authors one truthful operational path before adding notification behavior. |
| 2 | `generic-lifecycle-notifications` | pending | `docs/roadmap/stage-26/phases/generic-lifecycle-notifications.md` | `agent/stage-26-p2-generic-lifecycle-notifications` | pending | Notification public surface, event projection/registration, observer evidence, example/docs/tests | Deliver safe, explicit, service-neutral lifecycle notifications without changing run correctness. |

Phase 1 is independently useful and contains no new feature family. Phase 2
adds the stage's single feature over the corrected lifecycle documentation and
existing post-commit event path.

## Quality Gate

- Planning gate: maintainer narrowed Stage 26 to correctness, documentation,
  logging, and generic notifications; all former scheduler, resume, usage, and
  gate/profile work is explicitly deferred.
- Manager review: pending expanded design result and final cross-artifact check.
- Optional independent review: not yet needed; use only if the corrected
  manifest/phase plans retain a material public-contract risk.
- Correction: pending the single expanded design-safety result if it produces
  concrete findings.
- Ready for implementation: no; design review and final manager gate pending.
- Accepted risks: synchronous notifier latency; delivery may occur before a
  process dies without recording an external link; run URIs may expose path-
  shaped identity; CLI/plugin activation is sequenced separately in Stage 28.
- Revisit triggers: measured latency plus accepted async requirement; accepted
  at-least-once/idempotency contract; selected first-party provider; non-local
  artifact-writer need; or Stage 28 event-subscription contract drift.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending |
