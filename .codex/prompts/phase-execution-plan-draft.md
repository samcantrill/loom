# Prepare Phase Execution Plan

Manager-local setup pass for an existing phase plan.

1. Verify the phase matches the manifest and earlier dependencies are merged.
2. Consume the manager's successful shared-Git-gate handoff from
   phase-loop-management.md before startup review or writes.
3. Verify the assigned phase branch in the persistent stage worktree. Do not
   create another worktree or duplicate the manager's transition procedure.
4. Record base revision, manifest execution context, coordination branch, PR
   target develop, canonical title under phase-loop-management.md, and any named
   refinement uncertainty. Reuse the manifest readiness receipt.
5. Refresh only stale source/test paths and current harness facts.
6. Confirm scope, fixed contracts, exact upstream references, merge boundary,
   private discretion, tests, risks, and stop conditions. No word target applies.
   Refine check selectors and expansion triggers with `$loom-targeted-validation`
   while retaining accepted coverage and explicitly approved final gates.
7. Record no refinement needed, or the one named unresolved question.
8. Commit the prepared phase plan and stop.

Return an incomplete contract to plan quality review. Do not invent behavior,
implement code, run broad validation, or create an assignment artifact.
