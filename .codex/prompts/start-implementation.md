Implement `loom` v0 using the repository’s phase workflow.

Repository: `/home/samcantrill/work/loom`
Base branch: `develop`
Full plan: `docs/implementation-plans/implementation-plan-v0.md`
Manager prompt: `.codex/prompts/phase-loop-management.md`

First, make sure the current workflow/docs changes are committed or otherwise present on `develop`.
Then follow the repo workflow exactly.

Start by reading:
- `AGENTS.md`
- `.codex/prompts/phase-loop-management.md`
- `docs/implementation-plans/implementation-plan-v0.md`

Phase 0: plan quality gate

1. Review `docs/implementation-plans/implementation-plan-v0.md` using `loom_plan_reviewer` and `.codex/prompts/implementation-plan-review.md`.
2. If there are blocking findings, refine the plan using `.codex/prompts/implementation-plan-refinement.md`.
3. Re-review until blocking findings are resolved or explicitly accepted with revisit triggers.
4. Update the plan quality gate status in `docs/implementation-plans/implementation-plan-v0.md`.

Then implement Phases 1-9 sequentially.

For each phase:

1. Use the branch listed in `docs/implementation-plans/implementation-plan-v0.md`.
2. Create a separate git worktree using the repository convention.
3. Use `loom_phase_implementer` with `.codex/prompts/implementation-phase-assignment.md`.
4. Create an expanded phase plan in `docs/phases/`.
5. Implement only the assigned phase.
6. Add or update relevant tests.
7. Run:
    - `uv run ruff check .`
    - `uv run pyright`
    - `uv run pytest`
    - `uv build`
8. Refine failures with `.codex/prompts/implementation-test-refinement.md`.
9. Prepare or open a PR targeting `develop`.
10. Review the PR with `loom_phase_reviewer` using `.codex/prompts/pull-request-review.md`.
11. If approved and checks pass, the managing agent may merge to `develop` using the automatic merge policy in `AGENTS.md`.
12. After merge, update `docs/implementation-plans/implementation-plan-v0.md` on `develop` to `merged`, record summary/checks/follow-ups, remove the phase worktree, run `git worktree prune`, and continue to the next phase.

Rules:

- Do not skip phases.
- Do not implement future phases early.
- Implementation agents must not merge.
- Only the managing agent may merge, after review approval and passing validation/CI.
- If GitHub merge or push permissions are unavailable, stop and report the exact blocker.
- Keep `loom` domain-neutral and aligned with `docs/structure.md`.
- Make the smallest reasonable assumption when ambiguous and document it in the phase plan and PR body.
