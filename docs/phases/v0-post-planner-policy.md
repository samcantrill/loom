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
- Draft pass: completed by `loom_phase_planner` in commit `d5db52e`.
- Refine pass: completed by `loom_phase_planner` in this planning pass. This
  document is decision-complete for executor handoff.
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
- `plan_pipeline()` currently writes only `ExecutionPlan.to_dict()` to
  `plan.json` through `RunStore.write_plan()`. Phase 5 must preserve that
  persistence behavior.
- `_plan_stage()` has four distinct policies interleaved: selector-driven
  skip/outside-only handling, upstream binding/invalidation, pending-input
  action choice, and direct resume/fingerprint action choice.
- `_bind_inputs_and_invalidation()` currently performs real typed work but is
  annotated as `Mapping[str, object]` and accesses
  `ResolvedInputBinding.source_stage_id` and `source_output_name` through
  `type: ignore`. Removing this workaround is the primary typing cleanup for
  this phase.
- Upstream invalidation currently treats reusable upstream plans as providers,
  treats non-reused dependencies as invalidating, and uses
  `_is_unavailable_reuse_provider()` to distinguish a blocked upstream provider
  from a normal pending upstream input. Those semantics must be preserved.
- `_unique_reasons()` deduplicates repeated selector, pending-input, and
  invalidation reasons by reason code, message, stage, upstream, input, and
  output fields. Preserve the same ordered first-seen behavior unless a test
  documents a deliberate change.
- `src/loom/pipeline/planning/selectors.py` already owns selector
  normalization and eligibility state. This phase should reuse that boundary
  rather than invent a second selector model.
- `Selection.is_reuse_provider()` is part of the selector result even though the
  current planner mostly relies on `eligible_to_run=False` plus direct resume
  decisions for provider-only stages. Preserve provider-only planning behavior
  for `only_stages`.
- `src/loom/pipeline/planning/resume.py` already owns direct same-run resume
  checks and returns `DirectResumeResult`. This phase should keep store reads
  and artifact validation there.
- `check_stage_resume()` owns prior status/input/output/fingerprint reads,
  artifact-index validation, artifact-store validation, and stale/reuse reason
  construction. Do not move store IO into explanation or action helpers.
- `src/loom/pipeline/planning/fingerprints.py` already owns semantic stage
  fingerprint construction. This phase may route calls through a planner helper
  but must not change semantic inputs or fingerprint policy constants.
- `StageFingerprintPayload` is currently schema version 2 with policy
  `loom.stage.semantic` version 2. Do not bump these constants, and do not add
  runtime/resource hints or explanation metadata to the fingerprint payload.
- `src/loom/pipeline/planning/models.py` already owns strict plan,
  fingerprint, reason, resume-check, and stage-plan serialization. Any
  explanation models should be separate from persisted `ExecutionPlan` records.
- `ExecutionPlan.to_dict()` includes `kind: "loom.execution_plan"` and
  `schema_version: 1`. Keep this stable unless a blocker is recorded and the
  manager explicitly accepts a persistence change.
- The current planner receives graph bindings as `Mapping[str, object]` and
  uses `# type: ignore[attr-defined]` to access binding fields. Phase 5 should
  use the `ResolvedInputBinding` type from `loom.pipeline.graph.bindings`.
- `docs/structure.md` still describes a target `planning/` package with
  `plan.py` and `invalidation.py`, while the current source package has
  `models.py`, `planner.py`, `selectors.py`, `resume.py`, and
  `fingerprints.py`. Phase 5 should align the structure document with the
  implemented planner decomposition.
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

## Planned Module Boundaries

- `src/loom/pipeline/planning/planner.py`
  remains the orchestration entrypoint for `plan_pipeline()`. After extraction,
  it should read as a topological loop that delegates selector facts, input
  invalidation, fingerprint construction, resume checks, action choice, stage
  plan assembly, and persistence.
- `src/loom/pipeline/planning/selectors.py`
  remains the selector normalization and eligibility module. Avoid duplicating
  `Selection` or selector validation elsewhere.
- `src/loom/pipeline/planning/invalidation.py`
  should be added for typed upstream input binding and invalidation policy. It
  owns converting `ResolvedInputBinding` plus prior `StagePlan` facts into
  `BoundInput`, `PendingInput`, and upstream `PlanReason` values.
- `src/loom/pipeline/planning/actions.py`
  should be added for action-decision policy. It owns choosing `RUN`, `REUSE`,
  `SKIP`, `STALE`, or `BLOCKED` from selector, invalidation, direct resume, and
  force-selector facts. It should not read stores or compute fingerprints.
- `src/loom/pipeline/planning/fingerprints.py`
  continues to own stage fingerprint construction. Phase 5 may add a small
  planner-facing wrapper only if it improves orchestration readability.
- `src/loom/pipeline/planning/resume.py`
  continues to own direct resume checks, prior persisted state reads, artifact
  validation, and stale/reuse reason construction.
- `src/loom/pipeline/planning/explanations.py`
  should be added for typed diagnostics built from an existing
  `ExecutionPlan`. It must not perform store IO, execute stages, or mutate plan
  records.
- `src/loom/pipeline/planning/models.py`
  remains the persisted execution-plan and fingerprint model module. Add
  explanation data classes here only if cyclic imports make a separate
  `explanations.py` impossible; the preferred boundary is a separate module.

## Detailed Implementation Slices

### Slice 1: Characterize Existing Policy

- Add focused tests before moving logic where coverage is thin:
  - provider-only `only_stages` behavior when an upstream provider is reusable;
  - provider-only `only_stages` behavior when the upstream provider is not
    reusable and downstream becomes blocked with
    `UNAVAILABLE_UPSTREAM_INPUT`;
  - duplicate invalidation reasons remain first-seen ordered and deduplicated;
  - `from_stage` force still turns a reusable selected stage into `RUN` while
    preserving `base_action=REUSE`;
  - persisted `plan.json` stays exactly `ExecutionPlan.to_dict()` and does not
    include explanation records.
- Prefer public `plan_pipeline()` assertions for characterization tests. Add
  helper-module unit tests only after a helper exists.

### Slice 2: Extract Typed Invalidation Policy

- Add `src/loom/pipeline/planning/invalidation.py` with a small immutable result
  type, for example:

  ```python
  @dataclass(frozen=True, slots=True)
  class InputInvalidationResult:
      bound_inputs: Mapping[str, BoundInput]
      pending_inputs: tuple[PendingInput, ...]
      invalidated_by: tuple[PlanReason, ...]

      @property
      def blocking_reasons(self) -> tuple[PlanReason, ...]: ...

      @property
      def invalidating_reasons(self) -> tuple[PlanReason, ...]: ...
  ```

- Add a helper shaped like:

  ```python
  def evaluate_input_invalidation(
      *,
      stage: StageSpec,
      bindings: Mapping[str, ResolvedInputBinding],
      prior_plans: Mapping[str, StagePlan],
  ) -> InputInvalidationResult: ...
  ```

- Move upstream reason construction, unavailable-provider classification, and
  ordered deduplication into this module. Keep reason codes and messages stable
  unless the characterization tests prove an existing message is wrong.
- Type the helper with `ResolvedInputBinding` from
  `loom.pipeline.graph.bindings` so `planner.py` no longer needs
  `Mapping[str, object]` or `type: ignore[attr-defined]`.
- Preserve these action-causing categories:
  - blocking: `UPSTREAM_SKIPPED`, `UPSTREAM_BLOCKED`,
    `UNAVAILABLE_UPSTREAM_INPUT`;
  - invalidating: `UPSTREAM_WILL_RUN`, `UPSTREAM_STALE`,
    `PENDING_UPSTREAM_INPUT`.

### Slice 3: Extract Action-Decision Policy

- Add `src/loom/pipeline/planning/actions.py` with a small decision type, for
  example:

  ```python
  @dataclass(frozen=True, slots=True)
  class StageActionDecision:
      action: PlanAction
      base_action: PlanAction
      fingerprint_status: FingerprintStatus
      fingerprint: StageFingerprintRecord | None
      resume_check: ResumeCheck | None
      reasons: tuple[PlanReason, ...]
      reusable_outputs: Mapping[str, ArtifactRef]
  ```

- Add helpers for the three current action branches:
  - selector skip/outside-only decisions;
  - pending-input or upstream-invalidation decisions before fingerprinting;
  - direct resume decisions after fingerprinting, including force-selector
    override.
- Preserve the current force behavior exactly: forced selected stages run even
  when direct resume says `REUSE`, keep `base_action` from the direct resume
  result, clear `reusable_outputs`, and retain selector plus resume reasons.
- Keep stage-plan assembly in `planner.py` unless moving it into `actions.py`
  clearly improves readability. The action helper should not need
  `PipelineSpec`, `RunStore`, or `ArtifactStore`.
- Unit-test the action helper with simple `PlanReason`, `InputInvalidationResult`,
  and `DirectResumeResult` values so future policy changes are localized.

### Slice 4: Add Explanation Surface

- Add `src/loom/pipeline/planning/explanations.py`.
- Preferred public API:

  ```python
  PLAN_EXPLANATION_SCHEMA_VERSION = 1

  @dataclass(frozen=True, slots=True)
  class StageExplanation: ...

  @dataclass(frozen=True, slots=True)
  class PlanExplanation: ...

  def explain_plan(plan: ExecutionPlan) -> PlanExplanation: ...
  ```

- `PlanExplanation` should include:
  - `schema_version`;
  - `kind`, using `loom.plan_explanation`;
  - `run_id`;
  - `pipeline_name`;
  - `selectors`;
  - `resume`;
  - `stage_order`;
  - per-stage explanations in plan order;
  - `summary`.
- `StageExplanation` should include enough typed facts for CLI/preflight to
  report why a stage will run, reuse, skip, or block without parsing text:
  - `stage_name`;
  - `action`;
  - `base_action`;
  - `fingerprint_status`;
  - ordered `reason_codes`;
  - all `reasons`;
  - selector reasons;
  - invalidation reasons;
  - resume reasons;
  - `pending_inputs`;
  - `bound_inputs`;
  - reusable output names or refs;
  - upstream and downstream stage names;
  - prior and current fingerprint digest strings when available.
- Build explanations from existing `StagePlan` and `ResumeCheck` facts only.
  Do not read stores, rebuild fingerprints, re-run selector logic, or require
  explanation construction during `plan_pipeline()`.
- Add strict plain-data `to_dict()` / `from_dict()` helpers if practical in the
  same style as existing planning models. At minimum, tests must prove
  `explain_plan(plan).to_dict()` is deterministic and contains no
  non-plain-data values.
- Export `PlanExplanation`, `StageExplanation`, `explain_plan`, and the schema
  constant from `loom.pipeline.planning` only after package tests are updated.
  Do not export low-level invalidation/action helper types at package top level
  unless a stable consumer exists.

### Slice 5: Rewire Planner Orchestration

- Update `plan_pipeline()` and `_plan_stage()` to use:
  - `normalize_selectors()` for selector policy;
  - `evaluate_input_invalidation()` for bound/pending inputs and upstream
    invalidation;
  - `build_stage_fingerprint()` for semantic fingerprint construction only
    when all inputs are bound;
  - `check_stage_resume()` for direct reuse/stale checks;
  - action-decision helpers for final action and reasons;
  - `_stage_plan()` or an equivalent focused constructor for `StagePlan`.
- Remove the current planner `type: ignore` comments tied to input bindings.
- Keep `_persist_plan()` behavior unchanged.
- Keep `__all__` in `planner.py` limited to `plan_pipeline`.

### Slice 6: Docs And Public API Alignment

- Update `docs/structure.md` so the target/current planning package lists
  `models.py`, `planner.py`, `selectors.py`, `invalidation.py`, `actions.py`,
  `resume.py`, `fingerprints.py`, and `explanations.py` with accurate
  responsibilities.
- Update `docs/features/pipeline-graph.md` to state that graph binding returns
  typed `ResolvedInputBinding` values consumed by planner invalidation policy.
- Update `docs/features/resume.md` to replace the deferred
  `planning.invalidation` note with the implemented Phase 5 boundary and to
  state that `PlanExplanation` is derived beside `ExecutionPlan`.
- Update `docs/features/preflight.md` to direct future preflight/CLI diagnostics
  to `plan_pipeline()` plus `explain_plan()` instead of duplicating planner,
  selector, resume, or fingerprint logic.
- Update `docs/features/fingerprints.md` only to clarify that explanations may
  summarize fingerprint policy/digest facts and later diff payloads, while
  semantic fingerprint inputs and policy version remain unchanged.
- Update package API tests to reflect new stable explanation exports and keep
  root `loom` / `loom.pipeline` exports unchanged.

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

## Implementation Commit Guidance

- Commit 1: characterization tests for current planner outcomes and persistence
  stability.
- Commit 2: invalidation helper extraction and typing cleanup.
- Commit 3: action-decision helper extraction.
- Commit 4: explanation models, builder, package exports, and tests.
- Commit 5: docs updates and any final cleanup from validation.

This grouping is guidance, not a mandate. Keep commits coherent and avoid
mixing docs-only cleanup with behavior-sensitive refactors when it would make
review harder.

## Suite-Level Test Obligations

- Package: update `tests/package/test_pipeline_planning_api.py` for any new
  public explanation exports and keep import-boundary tests proving
  `loom.pipeline.planning` does not import config, execution, executor, CLI, or
  project modules. Also keep `plan_pipeline` out of `loom.__all__` and
  `loom.pipeline.__all__`.
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
- Narrow implementation checks:
  - `uv run pytest tests/unit/loom/pipeline/planning`
  - `uv run pytest tests/integration/pipeline/test_planning_resume.py`
  - `uv run pytest tests/integration/pipeline/test_plan_persistence.py`
  - `uv run pytest tests/package/test_pipeline_planning_api.py`
  - `uv run pytest tests/package/test_import_boundaries.py`
- PR preparation: run `make validate-pr` before opening/preparing the Phase 5
  PR and run `make test-summary` so the PR body can report package, unit,
  contract, integration, e2e, and opt-in/config-extra evidence.

## Acceptance Checklist

- `planner.py` no longer owns upstream invalidation and action-decision policy
  inline.
- Planner binding types use `ResolvedInputBinding`; the current
  binding-related `type: ignore` comments are gone.
- `ExecutionPlan` schema version, kind, persisted fields, and `plan.json`
  persistence behavior remain unchanged.
- Stage fingerprint schema/policy constants remain unchanged and no
  non-semantic runtime/resource hints enter fingerprint payloads.
- `PlanExplanation` or the chosen equivalent is typed, deterministic, separate
  from plan persistence, and derivable from an `ExecutionPlan`.
- Package public exports and import-boundary tests reflect only stable
  explanation-facing APIs.
- Docs describe the implemented planner boundaries and continue to defer CLI,
  preflight command, runner lifecycle, and future executor behavior.

## Slice Evidence (Phase 5)

- Slice 1 (characterization): added and preserved helper-level tests for binding
  extraction, invalidation reasons, action decisions, plan explanation round-trip,
  and planner persistence separation.
- Slice 2 (invalidation extraction): implemented in
  `src/loom/pipeline/planning/invalidation.py` with typed
  `ResolvedInputBinding` handling and deduplicated reason helpers.
- Slice 3 (action-policy extraction): implemented in
  `src/loom/pipeline/planning/actions.py` for selector/pending/invalidation and
  resume-based final actions.
- Slice 4 (explanation surface): implemented in
  `src/loom/pipeline/planning/explanations.py` with typed models and
  `PlanExplanation`/`StageExplanation` dataclasses.
- Slice 5 (planner rewiring): preserved topological orchestration order in
  `src/loom/pipeline/planning/planner.py` and retained existing persisted
  `ExecutionPlan` shape during persistence.
- Slice 6 (docs/API): added planning export updates and updated docs in
  `docs/structure.md`, `docs/features/pipeline-graph.md`,
  `docs/features/resume.md`, `docs/features/preflight.md`, and
  `docs/features/fingerprints.md`.

Validation evidence:

- `PYTHONPATH=src /home/samcantrill/work/loom/.venv/bin/pytest tests/unit/loom/pipeline/planning`
  (35 passed)
- `PYTHONPATH=src /home/samcantrill/work/loom/.venv/bin/pytest tests/integration/pipeline/test_planning_resume.py`
  (4 passed)
- `PYTHONPATH=src /home/samcantrill/work/loom/.venv/bin/pytest tests/integration/pipeline/test_plan_persistence.py`
  (2 passed)
- `PYTHONPATH=src /home/samcantrill/work/loom/.venv/bin/pytest tests/package/test_pipeline_planning_api.py`
  (5 passed)
- `PYTHONPATH=src /home/samcantrill/work/loom/.venv/bin/pytest tests/package/test_import_boundaries.py`
  (12 passed)
- `/home/samcantrill/work/loom/.venv/bin/ruff check` on changed files
  (pass)
- `git diff --check`
  (pass)

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
- Review traps:
  - explanation records accidentally persisted in `plan.json`;
  - helper extraction changing provider-only `only_stages` behavior;
  - action helpers importing stores or artifact stores;
  - explanations rebuilding fingerprints or reading stores;
  - public exports pulling in execution, executor, config, CLI, or project
    modules;
  - tests that assert helper internals instead of stable planner outcomes.

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
- Implementation refinement and PR review budgets are currently unused. Later
  workflow stages get at most one automated implementation refinement pass and
  one PR review pass unless the user explicitly resets the budget.
