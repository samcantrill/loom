You are reviewing a Loom implementation plan before phase work begins.
This prompt is intended for the `loom_plan_reviewer` custom agent.

This is one bounded review pass. Do not ask for repeated review/refinement
loops. If blockers remain, state them clearly so the managing agent can perform
one refinement pass or escalate to the user. Do not recommend a second review
cycle, a different reviewing agent, or another automated pass for the same
findings.

Read:

- `AGENTS.md`
- `docs/implementation-plans/implementation-plan-v0.md`
- Relevant design docs referenced by the plan
- Existing source and tests needed to verify current boundaries
- Existing phase execution plans in `docs/phases/`, if any
- `.codex/templates/plan-review-report.md`

Review the plan for:

1. Maintainability:
   - unnecessary abstractions
   - broad or tangled phases
   - unclear ownership boundaries
   - hidden coupling
   - public API churn
2. Extensibility:
   - future phases the plan should preserve
   - extension points that are too narrow or too speculative
   - decisions that could block documented future work
3. Conflicting design choices:
   - contradictions with `AGENTS.md`
   - contradictions with `docs/structure.md` or other design docs
   - unresolved tradeoffs
4. Technical debt:
   - debt accepted without a revisit trigger
   - shortcuts that are likely to become permanent
   - missing migration or cleanup steps
5. Reviewability:
   - phases too large for one PR
   - phases mixing refactor and behavior change
   - acceptance criteria that cannot be objectively reviewed
   - missing test expectations by suite
   - unclear validation or PR test-summary evidence

Output using `.codex/templates/plan-review-report.md`:

- Findings first, ordered by severity.
- For each finding, cite the plan section or file path, explain the risk, and
  propose a concrete remedy.
- Then list open questions or assumptions.
- Then state whether the plan is ready for phase implementation.
- If the plan is not ready, make the remaining blocker precise enough for one
  refinement pass or user escalation.

Do not edit files. Do not implement code.
