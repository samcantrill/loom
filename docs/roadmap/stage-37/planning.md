# Roadmap Stage 37 Planning: Stage Process-Containment Ownership

Status: approved for implementation; expanded design-safety review pending
Roadmap stage: 37
Evidence tree: `/nas/home/can134/work/loom-worktrees/stage-context-containment-owner`
at `308d132b0a79b6ddd8514e68cd71c4583f557f90`; relevant dirty paths: this
Stage 37 planning artifact only
Planning route: expanded because one new public stage-author API communicates a
cross-process containment ownership boundary
Current gate: minimum design recorded; independent design-safety review next
Blockers: none before review

This file is current authoritative state. The downstream rphys reference
experiment needs to launch child processes differently when a stage owns its
descendants and when Loom's managed worker boundary owns the complete process
group. The maintainer selected a first-class Loom contract instead of a
project-specific environment variable and explicitly authorized the Loom
update and pull request on 2026-09-01.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Loom constructs every current `StageContext`; the resident managed-worker path already has a distinct constructor and an outer supervisor that proves group containment before accepting its result. | None. | Preserve these owners. |
| Functionality | A stage can read one immutable typed value telling it whether the stage or Loom owns descendant containment. | None; maintainer selected option B. | Pressure-test the minimum design. |
| Design | Add one enum and one keyword-only context field; set the resident route to Loom ownership and every ordinary route to stage ownership. | Independent design-safety review pending. | Run the expanded review. |
| Validation | Public/default/type behavior, every current construction route, and resident propagation have named owners. | Final suite placement pending review. | Shape one vertical phase. |
| Detailed plan | Not drafted before design-safety review. | Review must pass. | Draft the manifest and phase card afterward. |
| Approval | The maintainer chose option B and authorized implementation/PR. | Exact API must remain within this approved minimum. | Do not add adjacent execution policy. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `src/loom/pipeline/context.py` and package API tests | `StageContext` is a frozen public stage-author facade. Existing callers can construct it without runtime services, and invalid public values are rejected with `PipelineValidationError`. | Public shape, compatibility, and validation owner. | FR-1, FR-2 |
| `runner.py` and `stage_worker.py` | The runner has two context constructors, ordinary durable worker reconstruction has one, and `execute_resident_stage_worker_request` has one distinct managed constructor. | Complete propagation inventory. | FR-2 |
| `_agent_process_supervisor.py` and managed/agent result paths | A resident root is launched with `start_new_session=True`; Loom retains the process-group ID, escalates TERM/KILL, proves the group vanished, and checks the result digest before result trust. | Meaning of Loom-owned containment. | FR-2, FR-3 |
| Direct worker and context tests | Direct worker reconstruction is observable through a fake executor; context tests already cover immutability, defaults, and invalid public input. | Small causal coverage rather than a topology matrix. | FR-1, FR-4 |
| `docs/features/pipeline.md`, `execution.md`, and `docs/GLOSSARY.md` | Stage context is generic and immutable; executor, agent, and containment owners are already distinguished. | Domain-neutral wording and documentation placement. | FR-3 |
| rphys Stage 78 | A current downstream consumer otherwise needs an ambient variable to decide whether nested action processes may form their own session. That variable can drift from the actual Loom route. | Demonstrated consumer and failure. | FR-1..FR-4 |

- User-visible outcome: stage code can branch on a documented, typed Loom fact
  instead of guessing from environment, metadata, parent PID, or executor name.
- Existing end-to-end path: ordinary runner/direct worker construction reaches
  stage code with stage-owned cleanup; the managed resident worker reaches the
  same stage API inside a supervisor-owned process group.
- Included scope: one public enum, one immutable keyword-only `StageContext`
  field, explicit values at all current Loom constructors, public docs, and
  focused package/unit/worker coverage.
- Non-goals and deferrals: no authored config key, environment injection,
  persisted schema, fingerprint change, automatic child management, signal
  helper, process inspection, cgroup abstraction, executor capability, or
  promise for routes that do not use the resident supervisor.
- Current consumer and demonstrated failure: a managed resident stage that
  starts a detached child can escape the supervisor's group; forcing all stages
  to inherit instead would leave ordinary/direct stages without a complete
  cleanup owner.
- Public or durable surfaces affected: the Python `loom.pipeline` API changes;
  no durable or wire representation changes.

## Minimum Useful Change

- Export `ProcessContainmentOwner` with exactly `STAGE` and `LOOM` values.
- Add keyword-only `StageContext.process_containment_owner`, defaulting to
  `STAGE` for compatible manual/test construction while rejecting strings and
  other untyped values.
- Pass `STAGE` explicitly at Loom's ordinary runner and direct worker context
  construction sites, and pass `LOOM` only from the resident worker boundary
  whose supervisor supplies positive process-group containment.
- Document the obligation: `STAGE` means the stage owns every child it starts;
  `LOOM` means children must remain in the inherited containment boundary while
  the stage still handles normal child completion and reaping.
- Defer helpers that launch, signal, wait, or verify child processes. The
  current consumer needs an ownership fact, not another subprocess framework.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | `loom.pipeline` publicly exposes a two-state process-containment owner, and `StageContext` exposes one immutable typed value to stage code. | No route names, project terms, free-form strings, or generic capability registry. | Existing lazy pipeline exports and frozen context. | Package export, enum identity, frozen/default/type tests. | locked |
| FR-2 | Every current Loom context constructor assigns the supported owner: ordinary runner and direct durable worker are `STAGE`; resident managed worker is `LOOM`. | No inference from metadata, executor name, environment, PID, or authored config. | Current four construction sites and resident supervisor. | Direct reconstruction assertion plus resident execution assertion; exact constructor audit. | locked |
| FR-3 | Documentation states what each owner guarantees and requires, including that `LOOM` is valid only where Loom supplies an outer containment proof and does not transfer normal child-result/reaping duties. | No hostile-code sandbox, Windows guarantee, scheduler-wide promise, or signal API. | Existing POSIX resident supervisor behavior. | Documentation assertions/review and source linkage. | locked |
| FR-4 | Existing callers that omit the new keyword continue with conservative stage ownership, while explicit invalid values fail during context construction before stage code runs. | No string coercion or compatibility alias. | Dataclass keyword-only default and `PipelineValidationError`. | Existing context suite plus invalid string/object cases. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1..FR-4 | Use a first-class Loom context contract rather than an rphys environment variable. | Loom alone knows the real execution boundary; context is already the stage-author runtime facade. | One additive public API. | locked by maintainer 2026-09-01 |
| FQ-2 | FR-1, FR-4 | Preserve omitted construction as `STAGE` and require exact enum instances when explicitly supplied. | Stage ownership does not claim an unavailable outer supervisor and avoids breaking existing tests/downstream context fixtures. | Loom's own constructors must still pass values explicitly so propagation is reviewable. | repo-resolved |
| FQ-3 | FR-2, FR-3 | Reserve `LOOM` for the resident worker boundary backed by positive group containment. | The supervisor already owns launch, group identity, escalation, disappearance proof, and result-digest ordering. | Other executors remain stage-owned until they prove the same contract. | repo-resolved |

## Behavior Baseline

- Existing `StageContext(...)` construction without the new keyword observes
  `ProcessContainmentOwner.STAGE`.
- An ordinary in-process stage, prepared direct worker, or reconstructed durable
  stage worker observes `STAGE`.
- A stage invoked by `execute_resident_stage_worker_request` observes `LOOM`.
- A stage seeing `STAGE` may establish its own subprocess session/group but must
  terminate, wait, and prove its descendants gone before returning.
- A stage seeing `LOOM` must keep children inside the inherited boundary and
  must not signal that outer group. It still owns ordinary child communication,
  timeout decision, and immediate-child reaping. Loom owns whole-group
  cancellation/containment and trusts the result only after positive proof.
- Raw strings, unknown enums, or unrelated objects are rejected. The fact is
  not authored configuration, durable provenance, or a fingerprint input.

## Minimum Design

- `loom.pipeline.context` owns `ProcessContainmentOwner(StrEnum)` and the
  `StageContext.process_containment_owner` field because both are import-light
  stage-author contracts.
- The field is keyword-only and defaults to `STAGE`. `StageContext.__post_init__`
  requires an exact enum instance; it does not coerce strings.
- `loom.pipeline.__getattr__` lazily exposes both `StageContext` and the enum,
  and `__all__` plus the package test make the public surface intentional.
- All Loom-owned context constructors pass an explicit enum. The resident
  constructor is the sole current `LOOM` producer; it is already reached only
  beneath the managed process supervisor.
- Feature documentation adds the field and its operational obligations to the
  existing StageContext sections. No new top-level feature document or durable
  record is needed.
- Private discretion includes exact local test helpers, whether propagation is
  asserted through a fake executor or artifact-producing support stage, and
  prose placement within the existing sections.
- Dependency direction remains queue supervisor -> resident worker boundary ->
  import-light pipeline context. Pipeline context does not import queue or an
  executor implementation.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Two-value public enum | A current stage must distinguish two incompatible child-launch obligations without guessing. | Boolean flag. | keep; the enum names the owner and leaves no polarity ambiguity |
| Keyword-only context field | Stage code needs the fact through its existing public runtime facade. | Metadata or environment key. | keep; those are untyped, forgeable, and can drift from the constructor route |
| Explicit values at four constructors | Omissions would hide propagation errors and weaken future route review. | Rely only on the default. | keep |
| Persisted owner, config schema, fingerprint, process helper, registry | No current consumer requires authoring, replay, or generic process operations. | Add machinery for future routes. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1 | Name the public type `ProcessContainmentOwner` and field `process_containment_owner`; values are `STAGE` and `LOOM`. | The names describe responsibility rather than route or launch mechanism. | `LOOM` is intentionally a guarantee, not an executor identity. | locked within approved option B |
| DQ-2 | FR-2, FR-4 | Default only for compatibility, but require every internal Loom constructor to pass a value explicitly. | Maintains downstream source compatibility while keeping route propagation auditable. | External manual construction can choose `LOOM`, as with other public context facts; docs define the required guarantee. | repo-resolved |
| DQ-3 | FR-3 | Do not add a helper that launches or kills subprocesses. | rphys already owns domain action execution and needs only the ownership fact. | Stage authors remain responsible for correct subprocess code. | repo-resolved |
| DQ-4 | FR-2, FR-3 | Do not persist or fingerprint this value. | It is a live Loom execution-boundary fact derived after route selection, not authored scientific intent. | Comparing runs does not reveal this fact from snapshots. | repo-resolved; revisit only if durable audit becomes a current requirement |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Removal-first and public-contract review | FR-1..FR-4; DQ-1..DQ-4 | Pending independent review of naming, default safety, owner guarantee, import direction, and absence of speculative machinery. | Run one `loom_design_safety_reviewer`; apply at most one bounded correction if needed. | pending |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Manual/test context | Omitted value must remain compatible and explicit invalid values must fail. | `StageContext.__post_init__`. | Unit default, explicit enum, immutability, invalid string/object. | planned |
| Ordinary execution | A direct stage must not incorrectly rely on Loom containment. | Runner and durable worker constructors. | Existing fake-executor request assertions plus constructor audit. | planned |
| Managed resident execution | A resident stage must inherit the supervisor group instead of detaching. | Resident context constructor under `_agent_process_supervisor`. | Focused resident request executing a stage that reports the enum. | planned |
| Public use | Downstream imports remain intentional and cheap. | Lazy `loom.pipeline` export. | Package export/import-boundary suite. | planned |

Causal interactions requiring combined coverage:

- Resident propagation and supervisor containment are causally linked. Existing
  real-process supervisor tests own the containment proof; the new focused
  resident test owns only propagation into stage code. Duplicating the full
  cancellation matrix is unnecessary.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Stage containment ownership | A downstream stage reads the correct owner in ordinary and resident Loom execution. | Public context enum/field, all constructors, docs/tests; no persistence/config/process framework. | Current resident supervisor and StageContext API. | Package and context tests, direct-worker assertion, resident propagation integration, full gates. | pending review |

One phase is intentional: the public value has no useful contract until both
ordinary and managed constructors propagate it, while all changes remain within
one small stage-context boundary.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Maintainer option-B choice; FR-1..FR-4 and FQ-1..FQ-3. | pass |
| Minimum design justified | One current rphys consumer and a reachable nested-process escape; existing context seam reused. | pass |
| Complexity delta proportionate | Enum + field + constructor wiring; no schema, config, registry, or helper. | pass pending review |
| Contracts and private discretion clear | Owner semantics/default/public names fixed; local test mechanics remain private. | pass pending review |
| Invariant ownership and validation proportionate | Context owns typing, constructors own propagation, supervisor retains containment proof. | pass pending review |
| Phases vertical and reviewable | One end-to-end public-contract phase. | pass pending review |
| No unresolved blocker | Independent expanded review not yet run. | block |

Gate result: blocked only on the required expanded design-safety review.
Accepted risks and revisit triggers: the contract is POSIX-oriented because the
current managed supervisor uses process groups; add another owner value only
for a supported route with a different proven obligation. Durable recording is
deferred until a concrete audit/resume consumer needs it.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Project environment variable | rejected | It duplicates Loom route truth and can drift. | Never as compatibility for this new API. |
| Automatic subprocess lifecycle helper | deferred | The current consumer already owns process execution semantics. | Multiple current stage authors duplicate the same safe helper. |
| Durable/fingerprint evidence | deferred | The value is runtime-derived and not an authored scientific input. | A current inspection or replay decision requires it. |
| More owner states | deferred | Only stage and Loom-resident owners are supported today. | A supported executor proves a materially different responsibility. |
| Non-POSIX containment semantics | deferred | Current demonstrated failure and supervisor are POSIX process-group based. | Maintained Windows or non-process-group managed execution. |
