# Phase 5 Execution Plan: Planner Policy Decomposition And Explanations

## Metadata

- Status: in_progress
- Branch: `codex/v0-post-planner-policy`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-planner-policy`
- Phase execution plan path: `docs/phases/v0-post-planner-policy.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Source phase: `Phase 5 - Planner Policy Decomposition And Explanations`
- PR: pending
- Stack predecessor: none
- Base branch: `develop` at `235e068da580d261510f9fdda351e8d37a0da3f7`
- Target branch: `develop`
- Serial human merge gate: active. The Phase 5 implementation PR must target
  `develop`, request review from `samcantrill` when GitHub allows it, and
  mention `@samcantrill` in the PR body or an immediate fallback PR comment.
  Codex must not approve or merge the PR. The manager must wait for human merge
  into `develop` before starting Phase 6.
- Merge eligibility: root serial phase. The Phase 5 PR is merge-eligible only
  after human review and human merge into `develop`; there is no stack
  predecessor to retarget from.
- Successor dependency notes: Phase 6 must not start while Phase 5 is only
  `pr_open` or `approved`; Phase 6 may start only after the Phase 5 PR is
  verified as `MERGED` into `develop` and this implementation plan records
  Phase 5 as `merged`.
- Plan quality gate: passed in
  `docs/implementation-plans/implementation-plan-v0-post.md`; no blocking
  plan-review findings remain.
- Plan quality gate loop budget: initial plan review used, automated plan
  refinement pass used, confirmation review used. Do not consume another
  plan-quality review loop without explicit manager instruction.
- Draft pass: completed by `loom_phase_planner` in this planning pass.
- Refine pass: pending; the next planning commit must make this artifact
  decision-complete before implementation starts.
- Phase implementation refinement budget: unused.
- PR review budget: unused.
- Setup limitations: local `develop` matched the manager-provided Phase 5 start
  commit `235e068`. No remote synchronization was attempted during planning
  because the assignment provided the updated base.
- Blockers: none.

## Objective

Keep current planning and same-run resume behavior deterministic while splitting
planner policy into smaller typed helpers and adding an explanation surface that
future CLI and preflight code can consume without parsing private planner
internals or duplicating resume logic.

The persisted `ExecutionPlan` remains the execution contract. Explanation data
must sit beside it as a typed diagnostic view and must not become required for
executing a plan or reading existing `plan.json` files.

## Full-Plan Context

Phase 1 is merged and established recursive immutability, shared strict schema
helpers, and no-extra/config-extra validation evidence. Phase 2 is merged and
established capability-oriented stores, run-scoped artifact stores,
`ArtifactAddress`, and the narrower stage-author `StageContext` facade. Phase 3
is merged and established explicit stage factories plus semantic fingerprint
policy v2. Phase 4 is merged and established runtime/resource/event/lock
foundations plus durable blocked status vocabulary.

Phase 5 resolves finding 4 from the implementation plan: planning policy
concentration. This phase may reorganize planner internals and expose diagnostic
models, but it must preserve Phase 3 fingerprint semantics and must not start
the Phase 7 runner lifecycle decomposition.

Explicit recipe catalogs, runner lifecycle refactoring, subprocess/container/
SLURM execution, retries, timeouts, remote stores, catalogs, bundles, sweeps,
cleanup, retention, plugin discovery, and final migration notes remain
future-phase work.

## Stack Context

- Root or stacked phase: root serial phase.
- Current predecessor branch or PR: none; Phase 4 was human-merged into
  `develop`.
- Why this base branch is correct: serial human-merge-gate mode starts each
  phase from updated `develop`; Phase 4 merge notes say Phase 5 must continue
  from updated `develop`, and this worktree records `develop` at
  `235e068da580d261510f9fdda351e8d37a0da3f7`.
- Retarget/rebase plan after predecessor merge: not applicable because there is
  no unmerged predecessor and the PR target is already `develop`.
- Branch cleanup constraints: keep the phase branch and worktree until the
  human-owned PR has merged into `develop` and no successor branch depends on
  it.

## Source Phase Summary

- Goal: keep planning deterministic while making selector, invalidation,
  resume, fingerprint, action, and explanation policy testable independently.
- Required scope:
  - Extract typed planner helpers for selector eligibility, upstream
    invalidation, resume checks, action selection, fingerprinting, and
    diagnostic construction.
  - Keep `ExecutionPlan` as the persisted execution contract.
  - Add a separate typed `PlanExplanation` or equivalent diagnostic surface for
    CLI/preflight consumers.
  - Preserve the semantic-only fingerprint policy defined in Phase 3.
  - Remove or tighten loosened typing around input bindings where the current
    planner path has type erosion.
  - Update `docs/structure.md`, `docs/features/pipeline-graph.md`,
    `docs/features/resume.md`, `docs/features/preflight.md`, and
    `docs/features/fingerprints.md`.
- Required checkpoints:
  - Helper extraction happens around existing behavior before model-shape
    changes.
  - Explanation models are derived from planning facts and do not change plan
    execution.
  - `plan.json` keeps the current execution-plan schema unless a blocker is
    discovered and explicitly recorded.
  - Type erosion around graph input bindings is removed from planner internals.
- Acceptance criteria:
  - Existing planning and resume behavior is preserved.
  - Explanation tests can inspect action reasons and invalidation causes without
    parsing CLI text or private planner internals.
  - CLI-facing planning helpers do not duplicate planning, resume, or selector
    semantics.
  - `ExecutionPlan` files remain stable execution records, not presentation
    envelopes.

## Current Source And Harness Findings

- `src/loom/pipeline/planning/planner.py` currently orchestrates graph
  construction, selector normalization, input binding, upstream invalidation,
  fingerprint computation, resume checks, action choice, `StagePlan`
  construction, and optional persistence.
- `src/loom/pipeline/planning/selectors.py` already owns selector
  normalization and eligibility state. This phase should reuse that boundary
  rather than invent a second selector model.
- `src/loom/pipeline/planning/resume.py` already owns direct same-run resume
  checks and returns `DirectResumeResult`. This phase should keep store reads
  and artifact validation there.
- `src/loom/pipeline/planning/fingerprints.py` already owns semantic stage
  fingerprint construction. This phase may route calls through a planner helper
  but must not change semantic inputs or fingerprint policy constants.
- `src/loom/pipeline/planning/models.py` already owns strict plan,
  fingerprint, reason, resume-check, and stage-plan serialization. Any
  explanation models should be separate from persisted `ExecutionPlan` records.
- The current planner receives graph bindings as `Mapping[str, object]` and
  uses `# type: ignore[attr-defined]` to access binding fields. Phase 5 should
  use the `ResolvedInputBinding` type from `loom.pipeline.graph.bindings`.
- Package tests currently assert `loom.pipeline.planning.__all__` and import
  boundaries. Adding explanation exports requires matching package tests and
  must not import config, execution, executor, CLI, or project modules.
- Existing unit and integration tests cover selector behavior, direct resume,
  stage fingerprinting, plan persistence, and planning against local stores.

## In-Scope Work

- Keep `plan_pipeline()` as the main public planning entrypoint.
- Extract typed upstream input and invalidation policy from `planner.py` into a
  planning-owned helper module.
- Extract action-decision policy from `planner.py` so pending-input, blocked,
  resume, stale, reuse, and force-selector behavior can be tested without
  constructing a full synthetic pipeline for every branch.
- Tighten planner binding types to use `ResolvedInputBinding` and remove the
  current planner `object` and `type: ignore` workaround.
- Add a separate typed explanation surface that can be built from an
  `ExecutionPlan`, including per-stage action, base action, reason codes,
  selector causes, upstream invalidation causes, resume reasons, pending inputs,
  reusable outputs, and fingerprint status.
- Export only stable explanation-facing symbols from
  `loom.pipeline.planning`. Keep low-level policy helpers module-scoped or
  submodule-scoped unless the implementation proves they are needed as public
  API.
- Preserve `ExecutionPlan` and `StagePlan` persisted shapes unless a directly
  necessary explanation field cannot be derived from existing plan facts.
- Update docs that own the changed planning boundaries and public contracts:
  `docs/structure.md`, `docs/features/pipeline-graph.md`,
  `docs/features/resume.md`, `docs/features/preflight.md`, and
  `docs/features/fingerprints.md`.

## Out-of-Scope Work

- No runner lifecycle decomposition, lock acquire/release integration, event
  emission during execution, or failed-run blocked descendant persistence
  through `PipelineRunner`; Phase 7 owns those integrations.
- No CLI command implementation, CLI text rendering, preflight command
  implementation, or run-catalog display work.
- No semantic fingerprint policy changes, policy-version bump, new fingerprint
  inputs, or change that makes runtime/resource hints semantic by default.
- No recipe catalog redesign, fresh-catalog composition path, plugin discovery,
  subprocess, SLURM, container, remote store, catalog, bundle, sweep, retry,
  timeout, cleanup, retention, or distributed lock behavior.
- No compatibility bridge or migration for persisted plan files beyond keeping
  the current `ExecutionPlan` schema stable.
- No broad rewrite of graph validation, run stores, artifact stores, execution,
  config composition, provenance capture, or package optional-dependency
  behavior.
- No future phase implementation or PR preparation in this planning pass.

## Assumptions

- The existing `ExecutionPlan` fields already contain enough data to derive
  explanation records for Phase 5; the implementation should not add fields to
  plan persistence unless tests reveal a concrete missing diagnostic fact.
- `PlanExplanation` is a typed API model for programmatic diagnostics. It can
  support plain-data serialization for CLI/preflight JSON output, but
  `plan_pipeline(..., persist=True)` must continue writing only the execution
  plan.
- Existing selector semantics, same-run resume behavior, and fingerprint
  semantics are correct and should be preserved by characterization tests before
  helper extraction.
- Planner policy helpers may remain internal submodule APIs during this phase.
  Future CLI work can depend on the public explanation builder rather than every
  lower-level helper.

## Initial Implementation Slices

1. Characterize current planning behavior.
   Add focused tests for selected-by reasons, upstream invalidation reasons,
   force-selector override after reusable state, and persisted plan stability
   where current coverage is thin.
2. Extract typed upstream input policy.
   Move `_bind_inputs_and_invalidation`, upstream reason construction, and
   duplicate-reason handling out of `planner.py`; type the helper around
   `ResolvedInputBinding`, `BoundInput`, `PendingInput`, `PlanReason`, and
   `StagePlan`.
3. Extract action decision policy.
   Move the pending-input, blocked, direct-resume, and force-selector action
   branches into testable helper functions or a small decision object while
   preserving the current `StagePlan` results.
4. Add explanation models and builder.
   Add a typed `PlanExplanation` surface beside `ExecutionPlan` and a builder
   that derives explanations from an existing plan without store reads or CLI
   formatting.
5. Update package exports and import-boundary tests.
   Export only stable explanation-facing symbols and keep planning imports
   lightweight.
6. Update docs and final validation evidence.
   Document the planner module boundaries, explanation surface, and explicit
   deferrals.

## Suite-Level Test Obligations

- Package: update `tests/package/test_pipeline_planning_api.py` for any new
  public explanation exports and keep import-boundary tests proving
  `loom.pipeline.planning` does not import config, execution, executor, CLI, or
  project modules.
- Unit: add or update tests for invalidation helper output, action decision
  helper output, explanation model serialization, explanation derivation from
  stage plans, selector reasons, direct resume reasons, and unchanged semantic
  fingerprint inputs.
- Contract: no store, artifact, executor, or stage protocol changes are
  planned. The existing contract suite must remain green; add contract tests
  only if an implementation choice changes a public planning/store boundary.
- Integration: keep local planning/resume and plan-persistence integration tests
  passing. Add integration coverage that proves persisted `plan.json` is still
  an `ExecutionPlan` and explanation construction is separate from persistence.
- E2E: no new end-to-end behavior is expected because no CLI or runner behavior
  changes are in scope. Run the existing e2e suite through the PR validation
  gate; add e2e coverage only if implementation unexpectedly changes user
  visible local-run behavior.
- Opt-in suites: no optional dependency behavior is intentionally changed.
  Preserve no-extra import behavior and config-extra validation evidence through
  the existing `make validate-pr` and `make test-summary` gates.
- PR preparation: run `make validate-pr` before opening/preparing the Phase 5
  PR and run `make test-summary` so the PR body can report package, unit,
  contract, integration, e2e, and opt-in/config-extra evidence.

## Design Impact

This phase makes planning easier to extend without turning the public
`PipelineRunner` facade or future CLI commands into the place where selector,
resume, invalidation, and fingerprint policy are reimplemented.

The implementation should reduce coupling inside `planner.py` while keeping the
current plan data model stable and inspectable.

## Future Compatibility

Future CLI `plan`, diagnostics/preflight, sweeps, and reliability work can use
one planner-owned explanation surface instead of duplicating policy rules. The
Phase 7 runner decomposition can continue to consume `ExecutionPlan` as the
execution contract without learning diagnostic presentation concerns.

## Alternatives Rejected

- Embed explanation records directly into persisted `ExecutionPlan` documents.
  Rejected because the implementation plan requires `ExecutionPlan` to remain
  the execution contract rather than a presentation envelope.
- Implement explanations only as formatted CLI strings. Rejected because Phase
  5 is pre-CLI and future tools need typed diagnostics.
- Reopen semantic fingerprint policy or bump fingerprint policy versions.
  Rejected because Phase 3 already made the selected semantic-only policy.
- Delay all planner decomposition until CLI work. Rejected because the whole
  point of this phase is to keep future CLI/preflight thin and policy-reusing.

## Debt Introduced

- Low-level policy helper modules may remain internal until CLI/preflight work
  proves the stable public helper surface. Revisit when v2 CLI starts.
- Explanation records may initially summarize fingerprint facts and reason
  chains rather than compute detailed payload diffs. Revisit when CLI explain
  output needs field-level fingerprint diffs.
- `ExecutionPlan` schema stays stable, so any missing diagnostic fact should be
  added only after a concrete consumer requires it and the migration cost is
  reviewed.

## Reviewability

- Keep commits grouped around characterization tests, helper extraction,
  explanation models, and docs.
- Avoid mixing behavior changes into module extraction. If a behavior change is
  unavoidable, add a test that names it and record why it is within Phase 5.
- Reviewers should compare before/after planning outcomes for selector, resume,
  stale, reuse, skipped, blocked, forced, and pending-input cases.
- Public API review should focus on keeping `ExecutionPlan` stable while making
  explanation records easy for CLI/preflight to consume.

## Handoff Notes

- Start implementation from
  `src/loom/pipeline/planning/planner.py`,
  `src/loom/pipeline/planning/models.py`,
  `src/loom/pipeline/planning/resume.py`,
  `src/loom/pipeline/planning/selectors.py`,
  `src/loom/pipeline/planning/fingerprints.py`, and
  `src/loom/pipeline/graph/bindings.py`.
- Keep changes within Phase 5 planning, tests, and docs. Do not touch unrelated
  workflow/control files.
- The later Phase 5 PR must target `develop`, notify `samcantrill`, and stop at
  the serial human merge gate.
