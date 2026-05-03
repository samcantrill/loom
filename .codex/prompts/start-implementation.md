Start the `loom` v0 phase workflow as the managing agent.

Repository: `/home/samcantrill/work/loom`
Base branch: `develop`
Worktree root: `/home/samcantrill/work/loom-worktrees`
Full plan: `docs/implementation-plans/implementation-plan-v0.md`
Manager prompt: `.codex/prompts/phase-loop-management.md`

First, make sure the current workflow/docs changes are committed or otherwise present on `develop`.
Then follow the manager workflow for Phase 0 only. Do not start phase
implementation yet; the process is still being refined.

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

Phase 0: plan quality gate

1. Review `docs/implementation-plans/implementation-plan-v0.md` once using `loom_plan_reviewer` and `.codex/prompts/implementation-plan-review.md`.
2. If there are blocking findings, perform one refinement pass using `.codex/prompts/implementation-plan-refinement.md`.
3. Run one confirmation review. If blocking findings remain, mark/report the blocker and stop. Do not loop indefinitely.
4. Update the plan quality gate status in `docs/implementation-plans/implementation-plan-v0.md`.
5. Stop after Phase 0. Report the plan-quality-gate result, any accepted risks,
   any remaining blockers, and the exact files changed.

Rules:

- Do not start Phase 1 or any later implementation phase.
- Do not create phase worktrees or phase branches.
- Do not loop on review/refinement; after the bounded pass, escalate blockers to
  the user.
- Do not open, approve, or merge phase PRs.
- Keep `loom` domain-neutral and aligned with `docs/structure.md`.
- Make the smallest reasonable assumption when ambiguous and document it in the
  plan-quality-gate notes.
