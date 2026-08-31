# Roadmap Stage 36 Implementation Plan

Status: approved
Roadmap stage: 36
Planning document: docs/roadmap/stage-36/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: 1
Blockers: none

## Summary

- Goal: make the existing managed-local runtime directly copyable as a
  standalone single-machine project lifecycle.
- Approved behavior and requirement IDs: FR-1 through FR-8.
- Key design constraints and decision IDs: FQ-1 through FQ-4 and DQ-1 through
  DQ-4; embedded-only facade, one config owner, exact replay, no new schema.
- Minimum useful change: public preparation facade plus the real-service
  `managed-local-basic` consumer.
- Complexity deliberately excluded: advanced routes, plugins, repair/delete,
  content relay, PKI, and process-manager installation.
- Validation and phase-shaping source: planning Examples And Validation and
  Phase Shaping.
- Out of scope: any scheduler, daemon protocol, authority, or durable-format
  redesign.

## Shared Constraints

- Architecture and dependency direction: examples depend only on public Loom;
  queue preparation may compose existing pipeline/config APIs; lower owners do
  not import queue.
- Shared public and durable contracts: one lazy preparation function and frozen
  receipt; all persisted files retain current schemas.
- Shared reproducibility, compatibility, and import constraints: config/root/
  profile identity has one protected owner; exact replay writes nothing; base
  imports remain cheap.
- Shared invariant ownership: existing exact runtime record owns executable
  intent; the new facade owns preparation ordering and replay; daemon/authority
  ownership is unchanged.
- Decisions no phase may reopen: no advanced routes, schema, repair, deletion,
  implicit config search, remote service, or artifact byte query.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | standalone-managed-local-starter | pending | docs/roadmap/stage-36/phases/standalone-managed-local-starter.md | agent/stage-36-p1-standalone-managed-local-starter | pending | queue preparation facade/export, managed-local-basic project/example, docs and tests | Copy, prepare, execute, inspect, and restart one embedded managed-local run through the real service. |

## Quality Gate

- Planning gate: passed; requirements, design, proportionality, validation, and
  single vertical phase are locked.
- Manager review: passed against current `develop` at `3990d79`.
- Optional independent review: not needed on the lean route; no unresolved
  durable or trust-boundary choice remains.
- Correction: not needed.
- Ready for implementation: yes; maintainer approval recorded 2026-08-31.
- Accepted risks: partial state is not repaired; advanced compositions stay on
  the low-level API; local E2E cannot certify a site process manager.
- Revisit triggers: implementation requires a new durable schema, changes an
  owner boundary, or cannot validate replay without mutation.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
