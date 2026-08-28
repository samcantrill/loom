# Roadmap Stage 33 Implementation Plan

Status: in_progress
Roadmap stage: 33
Planning document: docs/roadmap/stage-33/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: Phase 1 in progress
Blockers: none

## Summary

- Goal: let an operator run a downstream Discord reporter beside a Loom
  coordinator and receive bounded health, queue/admission, active-stage, and
  per-run progress summaries without affecting scheduling.
- Approved behavior and requirement IDs: FR-1 through FR-8 in `planning.md`.
- Key design constraints and decision IDs: FQ-1 through FQ-4 and DQ-1 through
  DQ-5; consume typed joined status through the owner-only socket, project only
  authority/admission facts, suppress timestamp-only changes, and keep delivery
  downstream and best effort.
- Minimum useful change: one reporter class and installed command in the
  existing `loom-discord` nested distribution, plus fake tests and live setup.
- Complexity deliberately excluded: `src/loom` changes, core reporter/event
  APIs, new schemas, remote gateways, bots, inbound control, durable cursors,
  outboxes, dashboards, metrics, and delivery guarantees.
- Validation and phase-shaping source: `planning.md` Examples And Validation and
  Phase Shaping.
- Out of scope: modifying Stage 29 status ownership or the user-owned Stage 32
  plan.

## Shared Constraints

- Architecture and dependency direction: `loom_discord` may import public
  `loom.queue` status/client types; Loom never imports the downstream package.
- Public and durable contracts: only the nested package's reporter and console
  command are new. Loom APIs and all durable/wire shapes remain unchanged.
- Reproducibility and compatibility: existing event-sink behavior remains
  compatible; tests are credential-free and network-free; live reporting is
  manual and the webhook URL remains environment-only.
- Invariant ownership: coordinator/admission and authority facts own reported
  progress; the downstream module owns projection/dedupe/HTTP behavior.
- Decisions no phase may reopen: no raw status dump, fabricated percentage/ETA,
  in-process coordinator HTTP, run-event adaptation, remote gateway, core
  dependency, retry queue, or Stage 32 edit.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | discord-coordinator-progress-reporter | in_progress | docs/roadmap/stage-33/phases/discord-coordinator-progress-reporter.md | agent/stage-33-p1-discord-coordinator-progress-reporter | pending | downstream Discord package, command, docs, and focused tests | Implementation and fresh local validation complete; await PR preparation, review, and merge. |

## Quality Gate

- Planning gate: passed; behavior, design, projection, cadence, failure, and
  trust-boundary agreements are locked.
- Manager review: passed; one downstream phase maps every accepted requirement
  and adds no speculative core machinery.
- Optional independent review: not needed on the lean path; existing Stage 29
  and Stage 31 contracts eliminate a novel public/durable decision.
- Correction: not needed.
- Ready for implementation: yes.
- Accepted risks: same-host socket access, process-local dedupe, and best-effort
  delivery; live Discord availability is not a repository gate.
- Revisit triggers: a second provider-neutral consumer, remote operator access,
  a delivery SLA, or historical telemetry.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | Implementation complete; targeted checks, `make validate-pr`, and `make test-summary` pass on `46383e9`. | Reporter restart sends a fresh summary; delivery remains best effort. | pending |
