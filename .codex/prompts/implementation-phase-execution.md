# Execute Phase

Procedure for manager implementation or an optional loom_phase_executor.

Read AGENTS.md and only the selected phase plan sections from current source
findings through executor handoff. Read manifest shared constraints only when
the phase plan cites them.

1. Consume the verified stage cwd/branch and Git-gate handoff from
   phase-loop-management.md. Stay in that stage worktree and assigned phase
   branch; do not switch branches while another agent/process uses it.
2. Implement the smallest change satisfying fixed contracts and acceptance.
3. Add the required phase-scoped tests with the related behavior.
4. Use targeted validation while developing.
5. Run the recorded final gate once when the validation-relevant tree is stable.
6. Make coherent commits.
7. Record implementation, changed paths, tests, validated revision/tree state,
   evidence paths, and residual blocker in the phase completion record.

You may simplify private helpers and wiring without reopening the plan. Do not
add optional hardening, future capability, new public decisions, PR preparation,
review, merge, sidecars, or user questions to an executor assignment. The manager
handles later delivery separately. Stop on a missing contract.
