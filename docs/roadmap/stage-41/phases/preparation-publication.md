# Phase 1 Execution Plan: Preparation And Publication

## Metadata

- Status: pending
- Roadmap stage and phase: 41 / 1
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p1-preparation-publication
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: published develop containing Stage 40; record exact SHA at execution preparation
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 1: Preparation And Publication
- Dependencies: Published Stage 40; Stage 41 plan and nine-phase split approved on 2026-09-10
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: source predecessor pending; no unresolved planning blocker

## Objective And Context

Prepare exact invocation intent and publish a truthful, replayable target through the selected authority.

Stage 40 supplies assigned preparation in an installed environment. This phase extends that existing publication journey, proving preparation-to-prepared-receipt through both supported authority families. Phase 2 adds automatic admission; Phase 3 adds service startup.

Requirements: FR-41-07/08; supporting FR-41-01/09/13. Design: DQ-41-04.
Validation ownership: VAL-41-01 (state/reuse), VAL-41-07.

## Current Source And Harness

- Published Stage 40 PrepareRunRequest and assigned preparation; reconcile actual source and schema versions before implementation.
- `src/loom/queue/managed_local_preparation.py`, `local_daemon_runtime.py`: exact composed publication, runtime requirements and current Slurm/authority exclusions.
- `src/loom/pipeline/stores/coordinator_authority.py`, `src/loom/queue/coordinator_authority.py`, authority repositories/routes: creation, transitions and authenticated access.
- `src/loom/pipeline/runtime/options.py`, `pipeline/status.py`, scheduler/readiness consumers and `cli/options.py`: invocation semantics and lifecycle transitions.
- Existing managed preparation, runtime options, coordinator authority and all-reuse/planner tests; Stage 40 source/report limits remain authoritative.

## Scope

Own immutable overlays/overrides/run options, selected-authority creation/publication, Slurm-profile preparation validation and correct pre-execution status. Change the transition/readiness consumers with their publication owner. Service startup, automatic run admission and backend execution changes belong to later phases.

Assume the predecessor's accepted contracts and existing qualified installations.
Each phase includes its code, owner-level tests, current docs and replaced-code
removal. Preserve unrelated work and current scientific/resource meaning.

## Implementation Walkthrough And Examples

### What changes and why

Preparation answers: which exact experiment will Loom execute? The existing
publisher accepts checked composition, but currently rejects configured Slurm
profiles/non-embedded authority and initializes an embedded target as RUNNING.
This phase extends that publisher and its authority boundary, rather than adding
another preparation engine. A prepared target must describe the work faithfully
before any of its pipeline stages execute.

The following Python-shaped example shows the planned request fields, including
the Stage 41 extensions. It is an illustrative target API example, not executable
against the current checkout; profile/root aliases require protected deployment
configuration. Constructors and internal helpers are not newly fixed by examples.

```python
preparation = PrepareRunRequest(
    operation_id="run-demo-001",
    run_name="demo-001",
    source={
        "mode": "shared",
        "root": "projects",
        "path": "demo",
        "include": ["configs"],
    },
    config_path="configs/experiment.yaml",
    preparation_profile="project-python",
    overlays=["configs/site.yaml"],
    overrides=["model.width=64"],
    run_options={
        "selectors": {"force_stages": ["train"]},
        "tags": {"experiment": "demo"},
    },
)
```

This only constructs intent. It does not call prepare-only and then reuse that
accepted operation as a different kind. Phase 2 can submit this request as part
of a run; a separate prepare-only invocation uses its own operation identity.

### Preparation-to-publication handoff

An eligible agent composes/checks the captured inputs in an existing installed
environment. It returns the exact checked composition and execution requirements.
The coordinator publisher persists those values and their provenance without
composing them again. Source capture provides preparation inputs; it does not
install the project or deliver arbitrary target-stage code/data.

Publication creates/transitions the target through its selected authority.
Embedded storage and authenticated authority are two implementations of that
boundary. Runtime coordinator logic must not construct a convenient replacement
database when the configured authority is unavailable.

```text
CREATED
   | checked target published
   v
PLANNED
   | first confirmed pipeline-stage execution
   v
RUNNING
   | execution and accepted results resolve
   v
terminal outcome
```

This is the target run's state, separate from the preparation operation and its
managed child. A reuse/skip-only target can terminalize without RUNNING. Changing
only a CLI label would leave readiness and transition consumers inconsistent;
update those owners together.

### Contracts illustrated

If publication succeeded but its response was lost, replay returns the same
prepared target. It must not recompose modified files or allocate another run.
Changed accepted intent conflicts. The VAL-41-01/07 checks below prove this
publication behavior, truthful state, authority-family support and preservation
of invocation controls. Preparation stops at its receipt in this phase; automatic
admission belongs to the [durable run operation](durable-run-operation.md).

## Fixed Contracts And Private Discretion

Extend Stage 40 preparation with ordered `overlays` (captured relative files),
ordered `overrides` (existing config strings), and sparse serializable
`run_options` using the current RunOptions composition/precedence rules. Persist
them in accepted intent and provenance. Preserve selectors, reuse, reliability,
timeouts, resources, tags/notes and plugin identity at their existing validators.
Reject obsolete executor/adapter inputs explicitly; never silently drop controls.
RunOptions validator registries/live closures are not serialized runtime inputs.

One publisher consumes the checked composition once. Add the required create/
publish operation to the selected embedded or authenticated authority boundary;
keep backend database construction out of runtime coordinator adapters. Prove
replay after publication/authority partial failure. Preserve Stage 40 source,
installed-code and report limits; this does not deploy the project's code/data.

Create the target run as CREATED, publish it as PLANNED, and move to RUNNING on
first confirmed executing-stage evidence. Queued/admitted is not RUNNING. A
reuse/skip-only plan can reach terminal status without a worker. Update authority
transition/readiness consumers together, preserving expected revisions/fences.

### Delivery boundary

A prepared receipt is the complete outcome here. Preparation-only remains terminal at publication. Slurm-targeted plans can be validated/published, but this phase does not enable a new dispatch route or claim the later agent-owned Slurm journey. Unsupported source/environment combinations still fail explicitly.

### Cross-phase handoff

Phase 2 consumes the exact prepared receipt and immutable invocation intent; Phase 5 consumes the checked Slurm profile requirements. Keep the existing prepare-only operation kind and projection bounds unchanged. Reconnecting reconciles unchanged intent; changed experiment configuration is a new run, and checkpoint recovery remains project-owned.

### Removal owned here

Remove the superseded unconditional embedded/RUNNING initialization and family rejection branches only when their replacements are covered. Delete abandoned publisher helpers with no remaining consumer; preserve pure composition/planner primitives.

Private helper names, local wiring and intermediate representations remain
implementation discretion. Public behavior, durable identity, trust, failure and
cross-phase meanings above are fixed. No compatibility aliases or state resets.

## Proportionality

Extend one publisher and selected-authority boundary. Reuse Stage 40 capture/composition/report schemas and current RunOptions validation. No extra preparation store, environment installer, recomposition path or scientific substitution.

## Invariant Ownership

| Invariant | Owner | Reachable boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Exact preparation intent | Preparation request/composition owner | Overlay/override or same-ID retry changed | Different experiment under one identity | VAL-41-07 immutable provenance/conflict |
| One selected-authority publication | Publisher and authority create/transition boundary | Transport loss or partial publication | Duplicate/partial target or wrong store | VAL-41-07 embedded/authenticated replay |
| Truthful pre-start state | Authority transitions and readiness consumers | Preadmission publication or reuse-only plan | False running state or stalled completion | VAL-41-01 CREATED/PLANNED/start/all-reuse |

## Implementation Slices

1. Reconcile Stage 40 publication source and extend immutable invocation controls with existing validators and provenance.
2. Route create/publication through the selected authority; cover partial failure and same-ID replay through both supported families.
3. Change lifecycle/readiness transitions together, cover all-reuse and queued cases, and enable checked Slurm-profile preparation without new dispatch.
4. Remove replaced publication helpers/rejections and update preparation/API documentation with the delivered family and state semantics.

## Test And Validation Plan

| Suite | Obligation | Minimal evidence |
| --- | --- | --- |
| Package/contract | Required | Optional imports stay inert; preparation controls, provenance and native receipt shape preserved. |
| Unit | Required | Changed intent conflicts; exact option precedence; CREATED/PLANNED/RUNNING and reuse-only transitions. |
| Integration | Required | Embedded/authenticated publication, partial failure/replay, Slurm-profile preparation, one target receipt. |
| Live deployment | Deferred to owner | No new real scheduler/container claim; later execution phases own qualification. |

Target existing source-mirrored tests and add focused assertions where the new
contract requires them. Resolve predecessor-renamed test paths at preparation.
Run optional-runtime commands only with their qualified environment. A local
fixture is not live-site evidence; record missing qualification explicitly.

    uv run --extra config pytest tests/unit/loom/queue/test_managed_local_preparation.py tests/contracts/test_runtime_options_contract.py tests/contracts/test_local_daemon_authority_contract.py tests/integration/authority/test_coordinator_authority_api.py

Final implementation gate; reuse a fresh receipt only while relevant code,
tests, dependency/build and validation configuration remain unchanged:

    make validate-pr
    make test-summary

Do not repeat complete backend/fault matrices in consumer phases. Expand tests
only for changed shared contracts, new failures or a remaining accepted concern.

## Risks, Review, And Stops

Stop for a published Stage 40 conflict or an accepted invocation control that cannot survive the process/publication boundary. A root reset or silent control drop is not a remedy. Missing installed environments remain explicit readiness failures.

## Executor Handoff

Read planning.md Behavior Baseline, the requirement/design/validation IDs above,
this whole card and the actual published predecessor contracts. Implement the
listed slices within the stated ownership. Do not reopen agreed lifecycle,
grant-before-start, sole submission/finalization ownership or hard cutover.
Manager action is for a demonstrated public/durable or accepted-behavior conflict,
not private helper choices. You are not alone in the codebase; preserve others' edits.

## Workflow State

- Manager preparation: approved card; execution revision/worktree pending
- Planning review: original design review and corrected run/cancel contracts retained; nine-phase mapping checked locally
- Implementation: not started
- Refiner: not used
- Pre-submit gate: not run
- Independent implementation review: required for selected-authority publication and lifecycle transitions
- Blocker corrections: 0/3
- PR and merge: not started

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Not started |
| Tests added, updated or intentionally removed | None; planning only |
| Validated revision/tree and evidence | Pending implementation |
| Validation-relevant changes after evidence | None |
| Replaced-code removal / retained primitive consumers | Pending this phase's removal audit |
| PR, review and merge | Pending |
| Residual risk and cleanup | Published Stage 40 and authority integration evidence pending |
