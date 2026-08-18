# Prepare Phase Execution Plan

Manager-local setup pass for an existing phase plan.

1. Verify the phase matches the manifest and earlier dependencies are merged.
2. Discover the current repository and GitHub identity.
3. Create or verify branch agent/stage-<N>-p<P>-<phase-slug> and its dedicated
   worktree from current develop.
4. Record base revision, worktree, PR target develop, intended title, and
   workflow path.
5. Refresh only stale source/test paths and current harness facts.
6. Confirm the executor packet is 800-1,600 words when practical and contains
   scope, fixed contracts, private discretion, tests, validation, risks, and
   stop conditions.
7. Mark expanded planning not needed on fast path or pending with the exact
   trigger.
8. Commit the prepared phase plan and stop.

Return an incomplete contract to plan quality review. Do not invent behavior,
implement code, run broad validation, or create an assignment artifact.
