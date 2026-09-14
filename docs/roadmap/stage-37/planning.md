# Roadmap Stage 37 Planning: Stage Process-Containment Ownership

Status: approved and ready for implementation planning
Roadmap stage: 37
Evidence tree: `/nas/home/can134/work/loom-worktrees/stage-context-containment-owner`
at `308d132b0a79b6ddd8514e68cd71c4583f557f90`; relevant dirty paths: this
Stage 37 planning artifact only
Planning route: expanded because one new public stage-author API communicates a
cross-process containment ownership boundary
Current gate: expanded design-safety review passed after one bounded correction
Blockers: none

This file is current authoritative state. The downstream rphys reference
experiment needs to launch child processes differently when a stage owns its
descendants and when an enclosing execution boundary owns the complete process
group. The maintainer selected a first-class Loom contract instead of a
project-specific environment variable and explicitly authorized the Loom
update and pull request on 2026-09-01.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Loom constructs every current `StageContext`; ordinary paths and the two resident entry boundaries are identifiable without route inference in stage code. | None. | Preserve these owners. |
| Functionality | A stage can read one immutable typed value telling it whether the stage or its enclosing execution boundary owns descendant containment. | None; maintainer selected option B. | Carry the locked contract into one phase. |
| Design | Add one enum and one keyword-only context field; ordinary routes use `STAGE`, while agent-supervised and SLURM-bootstrap resident entries use `OUTER_BOUNDARY`. | None; removal-first review corrected the former `LOOM` name. | Keep boundary-specific containment mechanisms private. |
| Validation | Public/default/type behavior, ordinary/direct propagation, and both resident production entries have named owners. | None. | Use focused propagation tests plus existing containment suites. |
| Detailed plan | Not yet drafted. | None. | Draft the manifest and one phase card. |
| Approval | The maintainer chose option B and authorized implementation/PR. | Exact API must remain within this approved minimum. | Do not add adjacent execution policy. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `src/loom/pipeline/context.py` and package API tests | `StageContext` is a frozen public stage-author facade. Existing callers can construct it without runtime services, and invalid public values are rejected with `PipelineValidationError`. | Public shape, compatibility, and validation owner. | FR-1, FR-2 |
| `runner.py` and `stage_worker.py` | The runner has two context constructors, ordinary durable worker reconstruction has one, and `execute_resident_stage_worker_request` has one distinct managed constructor. | Complete propagation inventory. | FR-2 |
| `_agent_process_supervisor.py`, managed/agent result paths, and `slurm_bootstrap.py` | An agent resident root is launched in a supervised process group; the SLURM bootstrap runs inside the scheduler job boundary. Each enclosing boundary retains its own containment mechanism. | Meaning and producers of outer-boundary containment. | FR-2, FR-3 |
| Direct worker and context tests | Direct worker reconstruction is observable through a fake executor; context tests already cover immutability, defaults, and invalid public input. | Small causal coverage rather than a topology matrix. | FR-1, FR-4 |
| `docs/features/pipeline.md`, `execution.md`, and `docs/GLOSSARY.md` | Stage context is generic and immutable; executor, agent, and containment owners are already distinguished. | Domain-neutral wording and documentation placement. | FR-3 |
| rphys Stage 78 | A current downstream consumer otherwise needs an ambient variable to decide whether nested action processes may form their own session. That variable can drift from the actual Loom route. | Demonstrated consumer and failure. | FR-1..FR-4 |

- User-visible outcome: stage code can branch on a documented, typed Loom fact
  instead of guessing from environment, metadata, parent PID, or executor name.
- Existing end-to-end path: ordinary runner/direct worker construction reaches
  stage code with stage-owned cleanup; agent-supervised and SLURM-bootstrap
  resident workers reach the same stage API inside an enclosing containment
  boundary.
- Included scope: one public enum, one immutable keyword-only `StageContext`
  field, explicit values at all current Loom constructors, public docs, and
  focused package/unit/worker coverage.
- Non-goals and deferrals: no authored config key, environment injection,
  persisted schema, fingerprint change, automatic child management, signal
  helper, process inspection, cgroup abstraction, executor capability, or
  promise for routes that do not supply a proven enclosing boundary.
- Current consumer and demonstrated failure: a managed resident stage that
  starts a detached child can escape the supervisor's group; forcing all stages
  to inherit instead would leave ordinary/direct stages without a complete
  cleanup owner.
- Public or durable surfaces affected: the Python `loom.pipeline` API changes;
  no durable or wire representation changes.

## Minimum Useful Change

- Export `ProcessContainmentOwner` with exactly `STAGE` and `OUTER_BOUNDARY`
  values.
- Add keyword-only `StageContext.process_containment_owner`, defaulting to
  `STAGE` for compatible manual/test construction while rejecting strings and
  other untyped values.
- Pass `STAGE` explicitly at Loom's ordinary runner and direct worker context
  construction sites. The agent-supervised resident and SLURM-bootstrap entry
  paths explicitly select `OUTER_BOUNDARY` when entering their shared resident
  execution helper.
- Document the obligation: `STAGE` means the stage owns every child it starts;
  `OUTER_BOUNDARY` means children must remain in inherited containment while the
  stage still handles normal child completion and reaping.
- Defer helpers that launch, signal, wait, or verify child processes. The
  current consumer needs an ownership fact, not another subprocess framework.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | `loom.pipeline` publicly exposes a two-state process-containment owner, and `StageContext` exposes one immutable typed value to stage code. | No route names, project terms, free-form strings, or generic capability registry. | Existing lazy pipeline exports and frozen context. | Package export, enum identity, frozen/default/type tests. | locked |
| FR-2 | Every current Loom context path assigns the supported owner: ordinary runner and direct durable worker are `STAGE`; agent-supervised and SLURM-bootstrap resident entries select `OUTER_BOUNDARY`. | No inference from metadata, executor name, environment, PID, or authored config. | Current context constructors and two production resident callers. | Direct reconstruction assertion, both resident entry assertions, and exact constructor audit. | locked |
| FR-3 | Documentation states what each owner guarantees and requires, including that `OUTER_BOUNDARY` is valid only where an enclosing execution boundary owns descendant containment and does not transfer normal child-result/reaping duties. | No hostile-code sandbox, Windows guarantee, scheduler-wide mechanism, or signal API. | Existing POSIX agent-supervisor and scheduler-job containment boundaries. | Documentation assertions/review and source linkage. | locked |
| FR-4 | Existing callers that omit the new keyword continue with conservative stage ownership, while explicit invalid values fail during context construction before stage code runs. | No string coercion or compatibility alias. | Dataclass keyword-only default and `PipelineValidationError`. | Existing context suite plus invalid string/object cases. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1..FR-4 | Use a first-class Loom context contract rather than an rphys environment variable. | Loom alone knows the real execution boundary; context is already the stage-author runtime facade. | One additive public API. | locked by maintainer 2026-09-01 |
| FQ-2 | FR-1, FR-4 | Preserve omitted construction as `STAGE` and require exact enum instances when explicitly supplied. | Stage ownership does not claim an unavailable outer supervisor and avoids breaking existing tests/downstream context fixtures. | Loom's own constructors must still pass values explicitly so propagation is reviewable. | repo-resolved |
| FQ-3 | FR-2, FR-3 | Reserve `OUTER_BOUNDARY` for execution entries backed by an enclosing containment owner. | The agent supervisor and scheduler job provide different mechanisms but impose the same obligation on stage-launched children: remain inherited. | Other executors remain stage-owned until they prove the same contract. | locked after design review |

## Behavior Baseline

- Existing `StageContext(...)` construction without the new keyword observes
  `ProcessContainmentOwner.STAGE`.
- An ordinary in-process stage, prepared direct worker, or reconstructed durable
  stage worker observes `STAGE`.
- A stage invoked through either supported resident production entry observes
  `OUTER_BOUNDARY`; direct use of the shared helper must explicitly provide its
  owner rather than infer one from the helper name.
- A stage seeing `STAGE` may establish its own subprocess session/group but must
  terminate, wait, and prove its descendants gone before returning.
- A stage seeing `OUTER_BOUNDARY` must keep children inside the inherited boundary and
  must not signal that outer group. It still owns ordinary child communication,
  timeout decision, and immediate-child reaping. The enclosing execution
  boundary owns whole-group cancellation/containment under its existing
  boundary-specific contract.
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
  constructor is shared by the agent-supervised worker and SLURM bootstrap
  production paths, so it must not encode the agent supervisor as the owner.
  The non-stage value describes the enclosing execution boundary and is
  produced only when that boundary, whether the managed process supervisor or
  scheduler job, owns descendant containment.
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
| Explicit values at four constructors | Omissions would hide propagation errors and weaken future route review; the resident constructor is reached from both agent-supervised and SLURM-bootstrap production boundaries. | Rely only on the default or infer ownership from the resident helper name. | keep explicit propagation, but name the non-stage owner for the common enclosing boundary rather than one Loom implementation |
| Persisted owner, config schema, fingerprint, process helper, registry | No current consumer requires authoring, replay, or generic process operations. | Add machinery for future routes. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1 | Name the public type `ProcessContainmentOwner` and field `process_containment_owner`; use values `STAGE` and `OUTER_BOUNDARY`. | `execute_resident_stage_worker_request` is called by both `_resident_stage_worker` under Loom's agent process supervisor and `slurm_bootstrap` inside a scheduler job. The public fact names the common containment owner observed by stage code, not one implementation that may supply it. | `OUTER_BOUNDARY` needs precise docs, but avoids implying that Loom's local agent owns scheduler containment. | locked after bounded design-review correction |
| DQ-2 | FR-2, FR-4 | Default only for compatibility, but require every internal Loom context path to propagate a value explicitly at the point where the enclosing containment owner is known. | Maintains downstream source compatibility while keeping ordinary, agent-supervised resident, and SLURM-bootstrap propagation auditable without inference from metadata or helper names. | External manual construction can choose `OUTER_BOUNDARY`, as with other public context facts; docs define the required guarantee. Exact private parameter or local wiring remains implementation discretion. | locked after bounded design-review correction |
| DQ-3 | FR-3 | Do not add a helper that launches or kills subprocesses. | rphys already owns domain action execution and needs only the ownership fact. | Stage authors remain responsible for correct subprocess code. | repo-resolved |
| DQ-4 | FR-2, FR-3 | Do not persist or fingerprint this value. | It is a live Loom execution-boundary fact derived after route selection, not authored scientific intent. | Comparing runs does not reveal this fact from snapshots. | repo-resolved; revisit only if durable audit becomes a current requirement |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Non-stage owner name overstates one implementation | FR-1..FR-3; DQ-1..DQ-2 | `execute_resident_stage_worker_request` has two production callers: `_resident_stage_worker` runs under `AgentProcessSupervisor`, while `slurm_bootstrap` runs inside a scheduler job. The original `LOOM` name would have misidentified the common outer owner. The enum and field remain justified; no registry, persisted state, route enum, or helper is needed. | Replaced the member and prose with implementation-neutral `OUTER_BOUNDARY`; propagation covers both production resident callers while exact private wiring remains open. | corrected; review passed |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Manual/test context | Omitted value must remain compatible and explicit invalid values must fail. | `StageContext.__post_init__`. | Unit default, explicit enum, immutability, invalid string/object. | planned |
| Ordinary execution | A direct stage must not incorrectly rely on Loom containment. | Runner and durable worker constructors. | Existing fake-executor request assertions plus constructor audit. | planned |
| Managed resident execution | An agent-supervised or SLURM-bootstrap stage must remain in its enclosing containment boundary instead of detaching. | The production entry boundary selects `OUTER_BOUNDARY`; `AgentProcessSupervisor` and the scheduler job independently own their containment mechanisms. | Focused propagation assertions for the agent-supervised and SLURM-bootstrap entry paths; existing boundary-specific tests retain containment-proof ownership. | planned |
| Public use | Downstream imports remain intentional and cheap. | Lazy `loom.pipeline` export. | Package export/import-boundary suite. | planned |

Causal interactions requiring combined coverage:

- Resident propagation and enclosing containment are causally linked. Existing
  boundary-specific agent-supervisor and SLURM tests own their containment
  behavior; focused Stage 37 assertions own only propagation into stage code.
  Duplicating either cancellation matrix is unnecessary.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Stage containment ownership | A downstream stage reads the correct owner in ordinary and resident Loom execution. | Public context enum/field, all constructors/entry callers, docs/tests; no persistence/config/process framework. | Current agent-supervisor and scheduler-job boundaries plus StageContext API. | Package and context tests, direct-worker assertion, both resident entry propagation assertions, full gates. | accepted |

One phase is intentional: the public value has no useful contract until both
ordinary and managed constructors propagate it, while all changes remain within
one small stage-context boundary.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Maintainer option-B choice; FR-1..FR-4 and FQ-1..FQ-3. | pass |
| Minimum design justified | One current rphys consumer and a reachable nested-process escape; existing context seam reused. | pass |
| Complexity delta proportionate | Enum + field + boundary-aware constructor wiring; no schema, config, registry, route enum, or process helper. | pass |
| Contracts and private discretion clear | Default/type semantics and `STAGE`/`OUTER_BOUNDARY` names are fixed; local wiring and test helpers remain private. | pass |
| Invariant ownership and validation proportionate | Context owns typing, each production entry path owns propagation, and the enclosing agent/scheduler boundary retains containment-proof ownership. | pass |
| Phases vertical and reviewable | One end-to-end public-contract phase remains sufficient after the naming correction. | pass |
| No unresolved blocker | The single review finding was corrected in place without adding machinery. | pass |

Gate result: passed after one bounded design-review correction. The stage is
ready for compact implementation-plan and phase-card drafting.
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
| More owner states | deferred | Only stage and enclosing-boundary ownership are supported today. | A supported executor proves a materially different responsibility. |
| Non-POSIX containment semantics | deferred | Current demonstrated failure and enclosing owners use POSIX process-group or scheduler-job containment. | Maintained Windows or non-process-group managed execution. |
