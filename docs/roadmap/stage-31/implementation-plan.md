# Roadmap Stage 31 Implementation Plan

Status: approved
Roadmap stage: 31
Planning document: docs/roadmap/stage-31/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: Phase 1 PR open
Blockers: none

## Summary

- Goal: provide a concrete, secret-safe Discord webhook event-sink package and
  opt-in live example over existing committed Loom lifecycle events.
- Approved behavior and requirement IDs: FR-1 through FR-7 in `planning.md`.
- Key design constraints and decision IDs: FQ-1 through FQ-4 and DQ-1 through
  DQ-4; provider code and `httpx` stay downstream, terminal events are the
  default, and callback delivery remains bounded and best effort.
- Minimum useful change: one nested example distribution with an installed
  `loom.event_sinks` entry point, safe Discord projection, fake validation, and
  live usage guidance.
- Complexity deliberately excluded: core notification API, Discord bot,
  Gateway or interactions, message editing, observer links, retries, rate-limit
  sleeping, durable outbox, artifact uploads, and release automation.
- Validation and phase-shaping source: `planning.md` Examples And Validation and
  Phase Shaping.
- Out of scope: all `src/loom` runtime behavior, public API, durable schemas, and
  root runtime dependency changes.

## Shared Constraints

- Architecture and dependency direction: `loom_discord` imports Loom; Loom must
  never import the example package. `httpx` belongs only to the nested project.
- Shared public and durable contracts: reuse `EventSinkRegistration`, exact
  subscriptions, the `loom.event_sinks` entry-point group, committed event
  records, and existing failure facts without changing them.
- Shared reproducibility, compatibility, and import constraints: default tests
  are network-free and credential-free; ordinary Loom imports/builds remain
  unchanged; live execution is explicit and manual.
- Shared invariant ownership: Loom owns event truth, ordering, filtering, and
  failure isolation; the downstream adapter owns provider formatting, timeout,
  credential lookup, and HTTP exception sanitization.
- Decisions no phase may reopen: no core notifier or config schema, no retry or
  outbox, no arbitrary event payload projection, and no raw webhook URL in
  durable or diagnostic output.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | discord-webhook-event-sink | pr_open | docs/roadmap/stage-31/phases/discord-webhook-event-sink.md | agent/stage-31-p1-discord-webhook-event-sink | [#251](https://github.com/samcantrill/loom/pull/251) | downstream example package, extension catalog/docs, focused tests | Deliver copyable remote Discord reporting without changing Loom core. |

## Quality Gate

- Planning gate: passed on 2026-08-28; requirements, external/secret boundary,
  minimum design, validation, and one-phase shape are locked.
- Manager review: passed; the plan starts from the existing end-to-end sink path
  and adds only the provider-specific current consumer.
- Optional independent review: not needed on the lean downstream-example path;
  Stage 20/28 already fixed the public and failure contracts.
- Correction: not needed.
- Ready for implementation: yes.
- Accepted risks: fake HTTP tests prove adapter behavior rather than Discord
  availability; synchronous best-effort delivery can lose notifications during
  external outages.
- Revisit triggers: implementation requires `src/loom`, a root runtime
  dependency, a new durable record, or a delivery guarantee.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | Best-effort external delivery; live Discord is opt-in. | pending |
