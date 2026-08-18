# Prepare Phase PR

Manager-local checklist.

Read the manifest summary, selected phase plan, current diff, current validation
evidence, and .github/PULL_REQUEST_TEMPLATE.md.

1. Confirm branch, scope, tests, fixed contracts, and no future-phase work.
2. Reuse current make validate-pr and make test-summary evidence; rerun only
   stale or missing evidence.
3. Perform the pre-submit blocker gate against plan, diff, body, tests, risks,
   domain neutrality, import boundaries, and unnecessary complexity.
4. Resolve qualified blockers within budget before submission.
5. Prepare a concise body directly for GitHub. Do not commit a PR-body file.
6. Push and open with explicit repository, base develop, head, and phase title.
7. Verify base, head, title, state, and URL.
8. Record concise PR facts in the phase completion record.

Do not spawn loom_pr_preparer, add tests here, request human reviewers, merge, or
create a sidecar.
