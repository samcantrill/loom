# Roadmap Stage <N> Planning

Planning layout: `planning-manifest-and-cards-v1`
Status: draft
Evidence root / branch / revision / relevant dirty paths:
Roadmap source:
Implementation manifest: `docs/roadmap/stage-<N>/implementation-plan.md`

This manifest owns stage routing, material decisions, and approval. Domain cards
own detailed contracts; the implementation manifest owns phase shaping and final
readiness. Link those owners without duplicating their definitions. Git owns
superseded wording; keep current state sufficient to resume.

## Current State

- Outcome and current task:
- Open decisions/blockers and exact owners:
- Next action:

## Gate Ledger

| Gate | Owning evidence | Status / next action |
| --- | --- | --- |
| Complete draft | indexed contracts and implementation cards | pending |
| Independent final review | implementation manifest readiness receipt | pending |
| Approval and landing | approval below and exact landed paths/revision | pending |

## Planning Card Index

| Card | Exact path | Coherent domain scope | Owned IDs | Dependencies | Status |
| --- | --- | --- | --- | --- | --- |
| PC-<N>-<card-slug> | `docs/roadmap/stage-<N>/planning/<card-slug>.md` |  |  |  | draft |

Every detailed ID has one authoritative card. Update paths, links, ownership,
and dependencies together when splitting a card.

## Stage Outcome And Scope

- Operator-visible outcome and current consumers:
- Included contract areas (card links):
- Prerequisites and adjacent roadmap dependencies:
- Stage-wide non-goals and explicit deferrals:

## Minimum Useful Change

- Existing end-to-end path:
- Closest existing capability and reuse decision:
- Reason for a new or separate surface:
- Smallest implementation and material boundary/failure it addresses:

## Cross-Card Constraints

Link authoritative definitions for shared architecture, runtime/provenance,
public/durable boundaries, and dependency ordering. Do not repeat card text.

## Cross-Card Design Review Findings

Final review findings and their resolution live in the implementation manifest.
Link any cross-card issue here when needed for routing; card-local decisions
remain at their contract owner.

## Phase Shaping

Link the implementation manifest's phase index and phase-boundary evidence.
Do not maintain another phase allocation table here.

## Specialist Pass Ledger

Only record actual optional help. Final independent review has its receipt in
the implementation manifest. Follow `.codex/prompts/subagent-lifecycle.md`.

| Role / runtime | Context mode | Named question / bounded paths | Result and manager verification |
| --- | --- | --- | --- |

For a spawned task, Context mode is `fork_turns=none; file-backed`.

## Decision Log

Record material maintainer choices and reopenings at their owner; link the
result here only when it changes stage routing. Omit routine chronology.

| Decision | Owning card/IDs | Rationale / remaining action |
| --- | --- | --- |

## Approval And Landing Handoff

- Approval status and maintainer evidence:
- Approved scope, accepted risks, and deferrals (owner links):
- Final readiness receipt (implementation manifest section):
- Exact roadmap source and packet paths:
- Landed revision and selected implementation base:
- Relevant post-review changes and disposition:
