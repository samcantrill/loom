You are refining a phase execution plan before implementation.
This prompt is intended for the `loom_phase_planner` custom agent.

This is the lower-level "how" pass for the same durable phase artifact created
by `.codex/prompts/phase-execution-plan-draft.md`. Work from the artifact plus
the compacted or current context, not from hidden assumptions in the draft pass.
Refine the same document until it is decision-complete for implementation.

Read:

- `AGENTS.md`
- `docs/implementation-plans/implementation-plan-v0.md`
- The assigned phase
- The draft phase execution plan in `docs/phases/`
- `.codex/templates/phase-execution-plan.md`

Task:

1. Confirm you are inside the dedicated git worktree for this phase under
   `/home/samcantrill/work/loom-worktrees`.
2. Review the draft phase execution plan against the canonical plan, source-tree
   boundaries, current source/tests, and phase acceptance criteria.
3. Refine the phase execution plan until it is decision-complete for implementation:
   approach, interfaces, data flow, edge cases, tests by suite, validation,
   assumptions, and explicit out-of-scope work.
4. Keep the plan limited to the assigned phase and preserve the durable
   handoff sections from `.codex/templates/phase-execution-plan.md`.
5. Add handoff notes for `loom_phase_executor`, including which implementation
   slices are safe for fast execution, which tests belong with each slice, and
   which choices must not be revisited.
6. Mark the artifact's refine pass complete while preserving both implementation
   refinement and PR review budget status as `unused`.
7. Commit the refined phase execution plan with a `plan:` commit.

Rules:

- Do not implement product code.
- Do not open a PR.
- Do not perform repeated review/refinement loops.
- Do not consume the implementation refinement or PR-review budget; this role is
  a planning handoff, not a validation fixer or PR reviewer.
- Do not expand the phase scope or implement future phases in the plan.
- Do not leave missing package, unit, contract, integration, e2e, or opt-in
  suite decisions for implementation. Explicitly require or defer each suite.
- If the plan cannot be made decision-complete, document the exact blocker and
  stop for the manager.
