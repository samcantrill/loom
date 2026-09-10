# Prepare Phase Execution Plan

Manager-local setup pass for an existing phase plan.

1. Verify the phase matches the manifest and earlier dependencies are merged.
2. Consume the manager's successful shared-Git-gate handoff from
   phase-loop-management.md before startup review or writes.
3. Verify the assigned phase branch in the persistent stage worktree. Do not
   create another worktree or duplicate the manager's transition procedure.
4. Record base revision, manifest execution context, coordination branch, PR
   target develop, intended title and any named refinement trigger.
5. Refresh only stale source/test paths and current harness facts.
6. Confirm the executor packet is 800-1,600 words when practical and contains
   scope, fixed contracts, private discretion, tests, validation, risks, and
   stop conditions.
7. Mark expanded planning not needed on fast path or pending with the exact
   trigger.
8. Commit the prepared phase plan and stop.

Return an incomplete contract to plan quality review. Do not invent behavior,
implement code, run broad validation, or create an assignment artifact.
