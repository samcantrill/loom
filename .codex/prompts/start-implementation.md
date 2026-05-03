Start the `loom` v0 Phase 1 implementation workflow as the managing agent.

Repository: `/home/samcantrill/work/loom`
Base branch: `develop`
Worktree root: `/home/samcantrill/work/loom-worktrees`
Full plan: `docs/implementation-plans/implementation-plan-v0.md`
Manager prompt: `.codex/prompts/phase-loop-management.md`
Assigned phase: `Phase 1 — Foundation`
Phase branch: `codex/add-foundation-skeleton`
Phase worktree: `/home/samcantrill/work/loom-worktrees/add-foundation-skeleton`

First, make sure the current workflow/docs changes needed to start Phase 1 are
committed or otherwise present on `develop`. Then follow the manager workflow
for Phase 1 only.

The plan quality gate has already passed in
`docs/implementation-plans/implementation-plan-v0.md`. Confirm that the plan
still records the gate as passed before assigning Phase 1 work. If the gate is
missing, not passed, or has unresolved blocking findings, stop and report the
blocker instead of starting implementation. Do not rerun Phase 0 unless the user
explicitly asks.

Maintain a loop budget while managing the workflow. A gate may consume only the
review/refinement passes allowed by `.codex/prompts/phase-loop-management.md`.
Before assigning any reviewer or refiner, check whether that gate's pass has
already been used in the current thread, expanded phase plan, PR body, or
implementation-plan notes. If it is unclear, assume the budget is consumed and
report the blocker instead of starting another automated pass.

Start by reading:

- `AGENTS.md`
- `.codex/prompts/phase-loop-management.md`
- `docs/implementation-plans/implementation-plan-v0.md`
- `docs/structure.md`
- Any existing Phase 1 plan in `docs/phases/`

Phase 1: foundation

Goal:

- Create the package skeleton, public import surface, shared errors,
  timestamp/id helpers, and import-boundary guardrails without implementing
  runtime behavior.

Required Phase 1 workflow:

1. Confirm Phase 1 is the next pending phase and earlier required gates are
   satisfied.
2. Check for an existing Phase 1 branch, worktree, expanded phase plan, or PR.
   If one exists, inspect it and resume safely instead of creating duplicates.
3. Assign Phase 1 planning to `loom_phase_planner` using
   `.codex/prompts/implementation-phase-planning.md`. The draft expanded phase
   plan must use branch `codex/add-foundation-skeleton`, worktree
   `/home/samcantrill/work/loom-worktrees/add-foundation-skeleton`, and a
   `docs/phases/` filename matching the branch summary.
4. Assign the committed draft phase plan to `loom_phase_plan_expander` using
   `.codex/prompts/implementation-phase-plan-expansion.md`.
5. Assign implementation and phase-scoped tests to `loom_phase_executor` using
   `.codex/prompts/implementation-phase-execution.md`.
6. Assign at most one bounded implementation/test refinement pass to
   `loom_phase_refiner` using
   `.codex/prompts/implementation-test-refinement.md`, only if the phase
   implementation refinement budget is still unused.
7. Assign PR preparation to `loom_pr_preparer` using
   `.codex/prompts/pull-request-preparation.md`. Ensure `make validate-pr` and
   `make test-summary` are run or any unavailable checks are clearly justified
   in the expanded phase plan and PR body.
8. Stop after the Phase 1 PR is opened or the PR body is prepared. Report the
   branch, worktree, expanded phase plan path, PR link or reason it was not
   opened, validation evidence, accepted risks, remaining blockers, and exact
   files changed.

Phase 1 scope reminders:

- Add `loom.ids`, `loom.errors`, and `loom.timestamps`.
- Add import-safe package skeletons only for these Phase 1 paths:
  `src/loom/records`, `src/loom/provenance`, `src/loom/serialization`,
  `src/loom/io`, `src/loom/config`, `src/loom/pipeline`,
  `src/loom/pipeline/graph`, `src/loom/pipeline/planning`,
  `src/loom/pipeline/execution`, `src/loom/pipeline/executors`,
  `src/loom/pipeline/stores`, and `src/loom/cli`.
- Defer deeper nested packages such as config recipes/instantiate, I/O
  sources/codecs, concrete stores, and concrete executors unless an import-safe
  unsupported stub is required by Phase 1 public import tests.
- Define simple ID aliases only: `RecordID`, `ResourceKey`, `CodecKey`,
  `ArtifactID`, `ArtifactType`, `RunID`, and `StageID`.
- Define broad catchable errors: `LoomError`, `ValidationError`,
  `ContractError`, `ArtifactError`, `ConfigError`, `PipelineError`,
  `ExecutionError`, and `IOErrorBase`.
- Define UTC-only timestamp helpers: `utc_now`, `utc_timestamp`,
  `safe_timestamp_for_path`, and `parse_timestamp`.
- Keep deferred functionality import-safe and make unsupported callables fail
  explicitly with a clear `LoomError` subclass when called.
- Update `loom.__init__` only with stable cheap public exports that are
  available in Phase 1.

Rules:

- Do not start Phase 2 or any later implementation phase.
- Do not implement config composition, recipes, object construction, codecs,
  stores, planning, execution, or hard config runtime dependencies.
- Do not create phase work directly in the original checkout.
- Do not approve, merge, or clean up the Phase 1 PR/worktree unless the user
  explicitly asks for that follow-up.
- Do not loop on review/refinement; after the bounded pass, escalate blockers to
  the user.
- Keep `loom` domain-neutral and aligned with `docs/structure.md`.
- Make the smallest reasonable assumption when ambiguous and document it in the
  expanded phase plan and PR body.
