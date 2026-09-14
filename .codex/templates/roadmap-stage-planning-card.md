# Planning Card: <Title>

Card ID: `PC-<N>-<card-slug>`
Status: draft
Roadmap stage: `<N>`
Planning manifest: `docs/roadmap/stage-<N>/planning.md`
Card path: `docs/roadmap/stage-<N>/planning/<card-slug>.md`
Evidence revision: `<root>` at `<branch>` / `<HEAD>`
Dependencies: none / card links or owned IDs
Owned IDs: `<requirement, queue, decision, example, and validation IDs>`

This card is the authoritative detailed planning state for one coherent domain
contract. Update it throughout drafting and review; do not create pass-specific or
premature phase-specific cards. Keep copied context out, and never shorten
unique current contract detail for brevity. No numerical prose target applies.

## Current Card State

| Current gate | Status | Locked result | Open decisions/blockers | Next action |
| --- | --- | --- | --- | --- |
| Evidence and candidate requirements | pending |  |  |  |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs | Remaining gap |
| --- | --- | --- | --- | --- |
| `docs/roadmap.md` |  | roadmap outcome |  |  |
| Architecture and feature docs |  | constraints and intended behavior |  |  |
| Code, tests, and configuration |  | current capability and seams |  |  |

- Contract-area outcome:
- Included scope:
- Non-goals and deferrals:
- Existing capability and reuse decision:
- Current consumers or demonstrated failures:
- Public, durable, compatibility, or trust boundaries:
- Scope-defining inventory or revision-bound reproduction:

## Capability Triage

| Capability | Decision | Rationale | Requirement IDs | Notes |
| --- | --- | --- | --- | --- |
|  | include / maybe / defer / out of scope |  |  |  |

## Module Behavior Map

| Module or area | Intended behavior | Why it matters | Capability enabled | Requirement IDs | Status |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  | draft |

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Impact | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- | --- |
| FR-<N>-01 |  |  |  |  |  | pending |

## Functionality Agreement Queue

Queue rows reference requirements instead of restating them.

| ID | Requirement IDs | Decision needed | Recommendation and evidence | Impact and trade-off | Exact maintainer feedback needed | State |
| --- | --- | --- | --- | --- | --- | --- |
| FQ-<N>-01 | FR-<N>-01 |  |  | high / medium / low |  | pending triage / repo-resolved / needs maintainer discussion / blocked / locked / deferred |

## Behavior Confirmation

- Included and default behavior:
- Failure and unsupported behavior:
- Resume or interruption behavior:
- Downstream implications:
- Explicit deferrals:
- Why the baseline is locked:

## Complexity Delta

Record only material additions. Future reuse alone does not justify one.

| Addition | Required now because | Current consumer, requirement, boundary, or failure | Current necessity and simpler alternative |
| --- | --- | --- | --- |
|  |  |  |  |

## Proposed Implementation Shape

- Minimum design and why less would fail:
- Modules and ownership:
- Locked public/durable/cross-phase contracts versus private discretion:
- Data flow and dependency direction:
- Component inputs/results and planner/executor boundary:
- Configuration and `_target_` composition:
- Extension and compatibility seams:

## Runtime And Provenance Contract

- Pipeline graph, planning actions, and lifecycle transitions:
- Configuration, inputs/results, and execution boundary:
- Run/artifact identity, serialization, durable formats, and resume:
- Authority/store ownership and process/filesystem trust boundaries:
- Cancellation, failures, observation freshness, and recovery:
- Provenance and parameters required for reproduction:

## Design Decisions

Classification and review evidence live here; do not create a parallel triage
table.

| ID | Requirement IDs | Decision | Classification | Current necessity and simpler alternative | Adversarial/roadmap evidence | Validation | Residual risk | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DD-<N>-01 | FR-<N>-01 |  | auto-approved candidate / recorded recommendation / needs maintainer discussion / blocked |  |  |  |  | pending |

## Design Agreement Queue

| ID | Decision IDs | Decision needed | Recommendation and evidence | Impact and trade-off | Exact maintainer feedback needed | State |
| --- | --- | --- | --- | --- | --- | --- |
| DQ-<N>-01 | DD-<N>-01 |  |  | high / medium / low |  | pending triage / repo-resolved / needs maintainer discussion / blocked / locked / deferred |

## Design Review Findings

| Finding | Requirement or decision IDs | Evidence, affected future item, or reusable seam | Maintainability, runtime/provenance, roadmap, or reuse impact | Required revision, deferral, or queue action | Revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  | pending |

## Functionality And Decision Audit

| Capability or traceability check | Evidence | Resolution | Status |
| --- | --- | --- | --- |
|  |  |  | pending |

## Examples And Demonstrations

| ID | Example | Behavior demonstrated | Project context | Required docs or tests | Status |
| --- | --- | --- | --- | --- | --- |
| EX-<N>-01 |  |  |  |  | pending |

## Validation Strategy

| ID | Accepted behavior or demonstrated risk | Boundary or causal interaction | Authoritative invariant owner | Minimal discriminating coverage | Command/location | Status |
| --- | --- | --- | --- | --- | --- | --- |
| VAL-<N>-01 |  |  |  |  |  | pending |

## Phase Implications

Link implementation phase owners; do not duplicate their allocation or status.

- End-to-end outcome enabled:
- Likely ownership and dependencies:
- Required ordering or cross-card contract:
- Acceptance and proportionate tests:
- Explicit exclusions and executor discretion:

## Assumptions And Deferrals

| Item | Type | Rationale | Revisit trigger |
| --- | --- | --- | --- |
|  | assumption / deferral |  |  |
