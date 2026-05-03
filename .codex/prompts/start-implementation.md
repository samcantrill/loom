Start the `loom` v0 Phase 4 implementation workflow as the managing agent.

Repository: `/home/samcantrill/work/loom`
Base branch: `develop`
Worktree root: `/home/samcantrill/work/loom-worktrees`
Full plan: `docs/implementation-plans/implementation-plan-v0.md`
Manager prompt: `.codex/prompts/phase-loop-management.md`
Assigned phase: `Phase 4 - Config Composition`
Phase branch: `codex/add-config-composition`
Phase worktree: `/home/samcantrill/work/loom-worktrees/add-config-composition`

First, make sure the current workflow/docs changes needed to start Phase 4 are
committed or otherwise present on `develop`. Then follow the manager workflow
for Phase 4 only.

The plan quality gate has already passed in
`docs/implementation-plans/implementation-plan-v0.md`. Confirm that the plan
still records the gate as passed before assigning Phase 4 work. If the gate is
missing, not passed, or has unresolved blocking findings, stop and report the
blocker instead of starting implementation. Do not rerun the plan quality gate
unless the user explicitly asks.

Phases 1, 2, and 3 must be recorded as `merged` before Phase 4 starts. Confirm
that Phase 4 is the next `pending` phase. If any earlier phase is not recorded
as `merged`, or if another phase is unexpectedly pending ahead of Phase 4, stop
and report the blocker.

Maintain the loop budget while managing the workflow. A gate may consume only
the review/refinement passes allowed by `.codex/prompts/phase-loop-management.md`.
Before assigning any reviewer or refiner, check whether that gate's pass has
already been used in the current thread, expanded phase plan, PR body, or
implementation-plan notes. If it is unclear, assume the budget is consumed and
report the blocker instead of starting another automated pass.

Start by reading:

- `AGENTS.md`
- `.codex/prompts/phase-loop-management.md`
- `.codex/templates/README.md`
- `docs/implementation-plans/implementation-plan-v0.md`
- `docs/structure.md`
- `docs/phases/add-foundation-skeleton.md`
- `docs/phases/add-primitives-serialization.md`
- `docs/phases/add-io-basics.md`
- Any existing Phase 4 plan in `docs/phases/`

Phase 4: config composition

Goal:

- Implement trusted YAML config composition and provenance without object
  construction side effects.

Required Phase 4 workflow:

1. Confirm Phase 4 is the next pending phase and earlier required gates are
   satisfied.
2. Check for an existing Phase 4 branch, worktree, expanded phase plan, or PR.
   If one exists, inspect it and resume safely instead of creating duplicates.
3. Assign Phase 4 planning to `loom_phase_planner` using
   `.codex/prompts/implementation-phase-planning.md`. The draft expanded phase
   plan must use branch `codex/add-config-composition`, worktree
   `/home/samcantrill/work/loom-worktrees/add-config-composition`, and a
   `docs/phases/` filename matching the branch summary. Use
   `.codex/templates/phase-assignment.md` for the manager-to-planner handoff
   and `.codex/templates/expanded-phase-plan.md` for the draft plan artifact.
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
8. Stop after the Phase 4 PR is opened or the PR body is prepared. Report the
   branch, worktree, expanded phase plan path, PR link or reason it was not
   opened, validation evidence, accepted risks, remaining blockers, and exact
   files changed.

Phase 4 scope reminders:

- Add hard runtime config dependencies:
  - `omegaconf>=2.3`
  - `pydantic>=2`
  - `pyyaml>=6`
- Add config loading, recursive merge, dot-path overrides, interpolation,
  validation, redaction, provenance, and public `compose_config`.
- Return `ComposedConfig` with resolved config, redacted config, provenance,
  empty `recipe_manifest`, and fingerprint.
- Split config behavior into focused modules for loading, merge, overrides,
  interpolation, validation, redaction, provenance, and composition.
- Keep interpolation behind a local wrapper so non-config modules do not become
  OmegaConf-specific.
- Implement recursive secret-like-key redaction for keys such as `token`,
  `secret`, `password`, `api_key`, `credential`, and `private_key`.
- Until Phase 5 implements recipes, reject `_recipe_` blocks with a clear
  unsupported-recipe `ConfigError` and return an empty recipe manifest for
  configs without recipes.
- Config composition must not write files. Persistence belongs to later runner
  and run-store phases.

Phase 4 acceptance reminders:

- Base config and overlays compose in order.
- Mapping, scalar, list, and explicit-null merge semantics match the plan.
- Overrides parse supported scalar and structured values and apply through dot
  paths with path-aware errors.
- Interpolation resolves through the local wrapper and reports unresolved
  values clearly.
- Required top-level fields are validated.
- `_recipe_` keys fail clearly as unsupported until Phase 5 rather than being
  ignored or partially expanded.
- Secret-like keys are redacted recursively.
- Config provenance and fingerprints change when source inputs change.

Phase 4 test reminders:

- Add focused tests for config loading, merge, overrides, interpolation,
  validation, redaction, composition, and provenance.
- Add package/import-boundary tests as needed to prove `loom.__init__` remains
  cheap and config dependencies do not leak into non-config imports.
- Run relevant targeted tests while implementing, then `make validate-pr` and
  `make test-summary` during PR preparation.

Rules:

- Do not start Phase 5 or any later implementation phase.
- Do not implement recipe expansion, `_target_` object construction, pipeline
  specs, stores, runner behavior, config persistence, sandboxing, allow-list
  mode, or domain-specific config semantics.
- Do not change the Phase 4 hard-dependency decision unless the expanded phase
  plan documents a blocker and the manager escalates it.
- Do not create phase work directly in the original checkout.
- Do not approve, merge, or clean up the Phase 4 PR/worktree unless the user
  explicitly asks for that follow-up.
- Do not loop on review/refinement; after the bounded pass, escalate blockers
  to the user.
- Keep `loom` domain-neutral and aligned with `docs/structure.md`.
- Make the smallest reasonable assumption when ambiguous and document it in the
  expanded phase plan and PR body.
