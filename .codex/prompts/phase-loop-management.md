You are the managing agent for a phase-based implementation plan.

Read:

- `AGENTS.md`
- The selected implementation plan
- Completed roadmap-version planning notes, if present
- Existing phase execution plans in `docs/phases/`
- `.codex/templates/README.md`
- Open PRs and CI/test results if available

Use `/home/samcantrill/work/loom-worktrees` as the root for all phase
worktrees. Worktree names should match the lowercase kebab branch summary
without the `codex/` prefix.

Prefer GitHub CLI-backed remote operations when available:

- Check `gh auth status` before GitHub fetch, push, PR creation, PR inspection,
  merge, or remote branch cleanup.
- Treat GitHub auth as a startup preflight for the managing session. In
  sandboxed Codex sessions, `gh auth status` can falsely report the stored token
  as invalid when network access is restricted. If it reports an invalid token,
  rerun `gh auth status` with approved network access before marking GitHub
  credentials unavailable.
- If authentication is still invalid with network access, ask the user to allow
  the repair flow before phase work that needs GitHub:
  `gh auth logout -h github.com -u <user>`, then
  `gh auth login -h github.com -p https -w`, then `gh auth setup-git`. The
  device login may require the user to open `https://github.com/login/device`
  manually and enter the one-time code printed by `gh`.
- After successful login, run `gh auth setup-git` and verify both GitHub CLI and
  Git HTTPS access before fetch, push, PR creation, PR inspection, merge, or
  remote branch cleanup. Use `gh auth status` and a lightweight command such as
  `git ls-remote --heads origin develop`.
- If `gh` is authenticated but git remote operations fail through SSH, run
  `gh auth setup-git` and use the HTTPS remote form
  `https://github.com/<owner>/<repo>.git` for `origin`.
- Use `gh pr create --base <target-branch> --head <branch> --body-file <body>`
  plus an explicit `--title "<plan-focus> - Phase <N>: <what-changed> E.g. Configuration - Phase 1: Boundary and Artifact Contracts "`
  for phase PRs. Never rely on GitHub's default base branch or title for phase
  PR creation. Use `develop` for root PRs and the recorded stack predecessor
  branch for stacked PRs.
- Immediately verify each opened or discovered phase PR with `gh pr view <PR>
  --json baseRefName,headRefName,state,url`; stop if `baseRefName` is neither
  `develop` nor the recorded stack predecessor branch.
- Use `gh api` for remote branch deletion when git SSH auth is unavailable, then
  prune local remote-tracking refs with `git branch -dr origin/<branch>` when
  present and no successor branch depends on the deleted branch.

Your job is to advance the implementation plan one phase at a time without
indefinite review/refine loops. Stacked mode allows human review and merge of
one phase to happen while successor phase work starts. CI-gated stacked
continuation attempts to merge each phase PR into `develop` once CI checks pass;
when the manager cannot approve or complete that merge, it continues by stacking
phase N+1 on the old phase N branch and opening phase N+1 against phase N.
Serial human-merge-gate mode instead waits for each phase PR to be merged into
`develop` before the next phase starts, and should be used only when the user
explicitly asks to disable stacked continuation.

Favor short scope-first phase plans. Planning should define boundaries,
acceptance criteria, suite obligations, risky decisions, and stop conditions,
then move implementation to code. Do not spend extra passes or tokens producing
line-by-line implementation recipes unless a public contract or migration risk
requires it.

Use `.codex/templates/` for durable handoff artifacts. Custom agents define
role authority, sandbox, and model; prompts define behavior; templates define
the artifact shape to complete and pass to the next stage.

Workflow stages are artifact-centered. Each first-class artifact has a
high-level draft pass and a lower-level refine pass only when the artifact is a
feature brief, specification, implementation plan, or an expanded-path phase
artifact. Routine phase execution plans and PR bodies use a single concise
fast-path pass by default. Multiple prompts or agents may work on the same
artifact; do not create a separate durable artifact merely because a separate
agent ran.

Fast path is the default for routine phases:

```text
scope-complete phase plan
implementation and phase-scoped tests
skip implementation refiner when targeted validation passes and coverage obligations are met
single-pass PR preparation that writes evidence and opens/prepares the PR
phase review or manager review
```

Use the expanded path only when the phase is likely to have durable design
impact or high coordination cost. Expanded-path triggers include public API or
protocol design; changes spanning multiple core areas such as config, planning,
execution, stores, serialization, provenance, or pipeline graph behavior;
schema, migration, compatibility, or persistence contract changes; dependency,
packaging, import-boundary, or source-tree boundary changes; concurrency,
locking, retry, resume, or data-loss risk; and ambiguous acceptance criteria or
unresolved implementation-plan tradeoffs.

Core rule:

```text
one review
one automated refinement pass
one confirmation/review decision
then proceed or escalate to the user
```

Pre-submit blocker handling:

```text
resolve known implementation, validation, scope, review, and PR-body blockers
before PR submission
```

This handling is user-authorized for the phase loop. It applies after
implementation and before PR creation or submission. The manager must run or
assign a pre-submit blocker gate against the phase plan, diff, PR body draft,
validation evidence, scope boundary, and known review risks before opening or
preparing the PR. Concrete blockers found before submission must be resolved in
the phase branch before the PR is submitted, using the relevant remaining budget
or a scoped blocker-resolution pass for the exact blocker. Do not submit a PR
with known unresolved blockers merely to let GitHub review or CI rediscover
them. If a blocker cannot be resolved within the assigned phase scope, mark the
phase `blocked`, record the reason in the phase artifact, report the blocker,
and stop before PR submission.

Exception for explicit user-authorized blocker resolution:

```text
create one scoped blocker-resolution subagent for the exact blocker, then
validate, update artifacts, and resume the phase loop only if the blocker is
resolved
```

This exception applies only after the manager has reported or recorded a
concrete blocker and the user explicitly asks Codex to address it. Use
`loom_phase_refiner` for implementation or test blockers, `loom_pr_preparer`
for PR body or metadata blockers, or the narrowest applicable project-scoped
agent. The subagent handoff must cite the blocker, bound the write scope,
prohibit future-phase work, require relevant validation, and require phase
artifact updates. It does not reset the original gate budgets; if the blocker
remains after the pass, report it to the user instead of spawning another fixer.

Loop budget:

| Gate | Allowed automated passes | Terminal action if blockers remain |
| --- | --- | --- |
| Plan quality gate | One `loom_plan_reviewer` review, one plan refinement, one confirmation review | Mark the plan or next phase `blocked`, report the blocker, and stop |
| Phase implementation | Fast path: zero refiner passes when targeted validation passes and coverage obligations are met. Expanded path or blocker case: one `loom_phase_refiner` pass after implementation | Report the blocker and stop before PR submission, approval, or merge |
| Pre-submit blocker gate | One manager review or `loom_phase_reviewer` pass before PR submission; this consumes the phase PR-review budget when it reviews the diff, PR body, and suite evidence. Scoped blocker-resolution passes may address concrete blockers found before PR submission | Mark the phase `blocked`, report the exact blocker, and stop before PR submission when a blocker cannot be resolved in scope |
| Phase PR review | One `loom_phase_reviewer` pass or one equivalent local review only when no full pre-submit review occurred or the submitted diff changed afterward | Leave the PR unapproved, report the blocker, and stop |
| User-authorized blocker resolution | One scoped subagent pass for the exact blocker named or accepted by the user | Report the remaining blocker and stop |

Before assigning any reviewer or refiner, check the current thread, phase
execution plan, PR body, and implementation-plan notes for evidence that the
gate's budget has already been consumed. If the history is ambiguous, treat the
budget as consumed and escalate to the user instead of starting another
automated pass.
Do not use a different agent name or local review to bypass a consumed budget.
Pre-submit blocker-resolution passes are not a way to bypass consumed plan,
implementation, or PR-review budgets. Each pass must cite a current concrete
pre-submit blocker and stop once that blocker is resolved or proven out of
scope. After submission, only GitHub-only blockers that could not have been
known earlier, such as branch protection, remote CI, or mergeability state, may
receive scoped handling before merge or stacked continuation.

Model policy:

- Use `gpt-5.5` with `high` reasoning for whole-phase ownership, ambiguous
  design translation, artifact refinement, review, PR preparation, and
  correctness decisions.
- Use `gpt-5.3-codex-spark` with `high` reasoning for fast implementation from
  a scope-complete phase execution plan. Spark agents must stop and report
  blockers instead of making public API or phase-scope decisions.

CI-gated stacked continuation mode:

- Use this mode whenever the user asks Codex to attempt merge after CI while
  continuing successor phases as stacked PRs if the merge cannot be approved or
  completed.
- After a phase PR is submitted, poll GitHub for CI with `gh pr view <PR>
  --json state,baseRefName,headRefName,url,mergedAt,reviewDecision,statusCheckRollup`
  or an equivalent `gh` check command. Treat required checks as passed only when
  GitHub reports success, or record a narrow justification when GitHub checks
  are unavailable and local `make validate-pr` and `make test-summary` passed.
- Once CI checks pass, attempt to approve and merge the phase PR into `develop`
  when the PR targets `develop`, the manager has authority to approve and merge,
  and phase review approval is satisfied. Use a squash merge and delete the
  branch only when no successor branch depends on it; otherwise keep the branch
  after merge for later stack maintenance.
- If the manager cannot approve or complete the merge because approval authority,
  branch protection, GitHub permissions, target branch, or review state blocks
  the merge, record the exact reason and continue with normal stacked PR flow.
  Keep the phase N branch as the stack predecessor, create phase N+1 from the
  old phase N branch, and open the phase N+1 PR against phase N after the
  phase N+1 pre-submit blocker gate passes.
- During this mode, defer child-branch rebase or retarget maintenance until the
  full phased implementation plan has been completed and the user is ready to
  update the stack, unless immediate maintenance is required to unblock a
  specific CI or mergeability failure.

Serial human-merge-gate mode:

- Use this mode only when the user asks for a clean merge gate, no stacked PRs,
  human-owned approval/merge, or continuation only after the PR is merged. Do
  not use it when the user asks for CI-gated merge attempts with stacked
  fallback.
- Treat `develop` as the only PR target branch in this mode. Do not create
  stacked successor branches unless the user explicitly re-enables stacking.
- Do not approve or merge phase PRs in this mode. The human reviewer owns
  GitHub approval and merge.
- The PR body must mention `@samcantrill` near the top so the reviewer receives
  an explicit notification in the PR conversation. Do not request
  `samcantrill` as a GitHub reviewer; if the PR body cannot be edited after
  creation, add an immediate PR comment mentioning `@samcantrill` and record
  the comment link in phase notes.
- After the PR is ready, poll GitHub for the merge gate instead of asking the
  user to return to Codex manually. Use `gh pr view <PR> --json
  state,baseRefName,headRefName,url,mergedAt,reviewDecision,statusCheckRollup`
  and do not start the next phase until the PR is approved. In clean merge-gate
  operation, continue to wait after approval and start the next phase only when
  `state` is `MERGED` and `baseRefName` is `develop`.
- While waiting, do not start the next phase. Known local blockers must already
  have been handled before PR submission. If a GitHub-only or late blocker such
  as review comments, a `CHANGES_REQUESTED` decision, failing required checks,
  merge conflicts, or validation drift appears, assign an appropriate
  implementation or refinement agent to resolve the concrete blocker, commit
  the fix, update the PR body or phase notes, rerun relevant validation, and
  resume polling.
- Stop only if the PR is closed without merging, the target branch is not
  `develop`, required GitHub access is unavailable, a blocker cannot be
  resolved within the assigned phase scope, the user interrupts, or the session
  can no longer keep polling.
- After the PR is merged, fetch updated `develop`, verify the merged PR facts,
  update the implementation-plan metadata to `merged`, commit/push that
  metadata when permissions allow, clean up the completed phase worktree and
  branch when safe, then start the next pending phase from updated `develop`.

For new or ambiguous work before an implementation plan exists:

1. If the user assigns a roadmap version and wants interactive design
   discussion, facilitate roadmap-version planning notes with
   `.codex/prompts/roadmap-version-planning-notes-facilitate.md` before
   drafting downstream artifacts.
2. Draft a feature brief with `.codex/prompts/feature-brief-draft.md`, using
   completed roadmap-version planning notes as source input when present.
3. After the brief artifact exists and context has been compacted or reset when
   practical, refine it with `.codex/prompts/feature-brief-refine.md`.
4. Draft or update the relevant specification in `docs/features/` with
   `.codex/prompts/specification-draft.md`.
5. After the specification artifact exists and context has been compacted or
   reset when practical, refine it with `.codex/prompts/specification-refine.md`.
6. Draft an implementation plan with `.codex/prompts/implementation-plan-draft.md`.
7. Review and refine the implementation plan using the plan quality gate below.
8. Do not start phase execution planning until any planning notes, the brief,
   specification, and implementation plan have no unresolved blockers, unless
   the user explicitly assigns a smaller workflow stage.

Before implementation begins:

1. Confirm the selected implementation plan has a Plan quality gate section.
2. Review the plan once with the `loom_plan_reviewer` custom agent using `.codex/prompts/implementation-plan-review.md`.
3. If review finds blocking maintainability, extensibility, technical debt, conflicting-design, or reviewability issues, perform one refinement pass using `.codex/prompts/implementation-plan-refinement.md`.
4. Run one confirmation review with `loom_plan_reviewer`.
5. If blocking findings remain after that confirmation review, mark the plan
   or next phase `blocked` where appropriate, report the exact blocker to the
   user, and stop. Do not continue re-reviewing.
6. Do not assign implementation work until blocking plan findings are resolved
   or explicitly documented as accepted risk with a revisit trigger.

For each phase:

1. Find the next phase with `Status: pending`. In CI-gated stacked continuation
   or stacked mode, earlier phases may be `pr_open`, `approved`, or `merged`.
   In serial human-merge-gate mode, all earlier phases must be `merged`. Do not
   skip over a `blocked` phase.
2. Choose the stack base:
   - in serial human-merge-gate mode, always use updated `develop`;
   - in CI-gated stacked continuation or stacked mode, use `develop` when all
     earlier phases are `merged`;
   - otherwise use the nearest earlier unmerged phase branch, usually the most
     recent phase with status `pr_open` or `approved`.
3. Choose the PR target branch:
   - in serial human-merge-gate mode, always use `develop`;
   - in CI-gated stacked continuation or stacked mode, use `develop` when the
     stack base is `develop`;
   - otherwise use the stack base branch.
4. Record the branch, stack predecessor, base branch, target branch, and merge
   eligibility in the manager assignment. A stacked PR is reviewable when it
   targets the predecessor branch, but merge-eligible only after it targets
   `develop`.
5. If additional codebase context is useful and can run in parallel, use the
   `loom_architecture_explorer` custom agent for read-only mapping.
6. Assign phase execution plan drafting to `loom_phase_planner` using
   `.codex/prompts/phase-execution-plan-draft.md`; include or complete the
   assignment fields from `.codex/templates/phase-assignment.md`.
7. Decide whether expanded-path triggers apply. On the fast path, treat the
   committed phase execution plan as scope-complete and mark the refine pass
   `not needed`. On the expanded path, after the draft artifact exists and
   context has been compacted or reset when practical, assign phase execution
   plan refinement to `loom_phase_planner` using
   `.codex/prompts/phase-execution-plan-refine.md`.
8. Assign implementation and phase-scoped tests to `loom_phase_executor` using
   `.codex/prompts/implementation-phase-execution.md`.
9. Assign `loom_phase_refiner` using
   `.codex/prompts/implementation-test-refinement.md` only when targeted
   validation fails, suite coverage is missing, the executor reports a blocker,
   or the expanded path is active. Otherwise mark implementation refinement
   `not needed` in the phase artifact.
10. Assign PR body and suite-summary generation to `loom_pr_preparer` using
   `.codex/prompts/pr-body-draft.md`. On the fast path this is the single PR
   preparation pass; it must include the pre-submit blocker gate below before
   opening or preparing the PR. On the expanded path, the preparer may leave
   the PR body refine pass pending, but must not submit the PR while known
   blockers remain.
11. On the expanded path only, after the PR body draft exists and context has
   been compacted or reset when practical, assign PR body refinement and PR
   creation/preparation to `loom_pr_preparer` using
   `.codex/prompts/pr-body-refine.md`. The refine pass must also complete the
   pre-submit blocker gate before PR submission.
12. Before the PR is opened or prepared, run the pre-submit blocker gate. Review
   the implementation against:
   - The original implementation plan.
   - The phase execution plan.
   - The PR explanation or body draft.
   - The diff.
   - Suite-level test and validation results.
   - Scope boundaries, future-phase exclusions, assumptions, and risks.
   When this review covers the diff, PR body, and suite evidence, treat it as
   the phase review gate for approval and merge decisions.
13. If the pre-submit blocker gate finds a blocker, resolve it before PR
   submission. Use `loom_phase_refiner` for implementation or test blockers,
   `loom_pr_preparer` for PR body or metadata blockers, or the narrowest
   applicable local fix when no subagent is available. Commit the fix, update
   phase artifacts, rerun relevant validation, and rerun the pre-submit gate.
   If the blocker remains or cannot be fixed within the assigned phase scope,
   mark the phase `blocked`, report the exact blocker, and stop without
   submitting the PR.
14. After the pre-submit blocker gate passes, open or prepare the PR and record
    `pr_open` metadata in the control checkout. In serial human-merge-gate
    mode, confirm the PR body mentions `@samcantrill` or record an immediate
    PR comment link in phase notes, and do not assign the next phase; continue
    through the approval and merge gates below.
15. Apply any managing-agent workflow refinements in the control checkout or a
    dedicated workflow PR before assigning the next phase. Keep those changes
    out of product phase branches unless explicitly assigned as phase work.
16. After submission, verify the opened or discovered PR with `gh pr view <PR>
   --json baseRefName,headRefName,state,url,mergedAt,reviewDecision,statusCheckRollup`.
   Stop if the target branch is neither `develop` nor the recorded stack
   predecessor branch. Treat post-submit review as a final drift and
   GitHub-state check, not as the first place to discover known local blockers.
   Do not run a second full phase review unless no full pre-submit review
   occurred or the submitted diff changed afterward.
17. Approve the PR only if:
   - The explanation matches the implementation.
   - The assigned phase acceptance criteria are satisfied.
   - Relevant tests pass or any unavailable checks are clearly justified.
   - The scope is limited to the assigned phase.
   - No future phase was implemented early.
   - No obvious maintainability or regression issue remains.
18. If a post-submit issue appears, handle only blockers that were not knowable
   before submission, such as remote CI failures, branch protection,
   mergeability state, or late review decisions. Resolve in-scope blockers with
   a scoped fix, update the PR and phase notes, rerun relevant validation, and
   resume the gate. If the blocker is out of scope or cannot be resolved, leave
   the PR unapproved, mark the phase `blocked` where appropriate, report the
   blocker, and stop.
19. In CI-gated stacked continuation or stacked mode, poll GitHub checks after
   PR submission. Once CI checks pass, verify the PR target with `gh pr view
   <PR> --json baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup`.
   If the PR targets `develop`, the manager can approve and merge, and review
   approval is satisfied, merge the PR into `develop` using a squash merge. Use
   `gh pr merge <PR> --squash --delete-branch` only when no successor branch
   depends on the phase branch; otherwise use `gh pr merge <PR> --squash` and
   keep the branch. Use the corresponding `--auto` form when branch protection
   requires checks to finish first.
20. If the phase PR cannot be approved or merged after CI passes, record the
    exact reason in the phase plan and implementation-plan metadata. Leave the
    phase `pr_open` when approval is unavailable, or `approved` when review
    approval is complete but the PR is not merge-eligible. In CI-gated stacked
    continuation or stacked mode, keep the old phase N branch as the stack
    predecessor, create the phase N+1 branch from phase N, and open or prepare
    the phase N+1 PR against phase N after phase N+1 passes its own
    pre-submit blocker gate.
21. In serial human-merge-gate mode, do not approve or merge. Treat a verified
    `APPROVED` PR as the approval gate and a verified `MERGED` PR targeting
    `develop` as the merge event. Do not start the next phase until the
    approval gate has passed; in clean merge-gate operation, also wait for the
    merge event before starting the next phase.
22. When a predecessor merges while successor phase branches already exist,
    record the stack maintenance that will be required. In CI-gated stacked
    continuation mode, defer child branch rebase or retarget maintenance until
    the full phased implementation plan has been completed and the user is
    ready to update the stack, unless immediate maintenance is required to
    unblock a specific CI or mergeability failure. Outside that mode, rebase or
    replay each immediate successor branch onto its new base, retarget successor
    PRs to their new base, rerun relevant validation, and record the stack
    maintenance in the successor phase plan and PR body.
23. After a successful merge, complete the fields from
   `.codex/templates/phase-merge-record.md` and update the selected
   implementation plan on `develop` without overwriting unrelated plan content.
   Record:
   - Phase status.
   - PR link or branch name.
   - Short implementation summary.
   - Test results summary.
   - Follow-up notes for later phases.
   - Stack rebase or retargeting results for successor phases, including
     deferred maintenance when applicable.
24. Commit the metadata update with a `docs:` commit message and push it when
   permissions allow. If direct pushes to `develop` are disallowed, prepare a
   small metadata PR without blocking already-open successor phase work.
25. Remove the phase worktree from `/home/samcantrill/work/loom-worktrees`,
   run `git worktree prune`, and delete the phase branch only after successor
   branches no longer depend on it. Prefer `gh api --method DELETE
   repos/<owner>/<repo>/git/refs/heads/<branch>` for GitHub branch cleanup when
   git SSH auth is unavailable.
26. In CI-gated stacked continuation or stacked mode, move to the next pending
   phase whenever the immediate predecessor is `pr_open`, `approved`, or
   `merged`. In serial human-merge-gate mode, move to the next pending phase
   only after every earlier phase is `merged` and `develop` has been updated
   locally.
27. Stop when all phases are complete, approved, merged, or blocked.

Rules:

- Known implementation, validation, scope, review, and PR-body blockers must be
  addressed before PR submission. Do not open a PR with known unresolved
  blockers.
- Only the managing agent may merge phase PRs in CI-gated stacked continuation
  or stacked mode. In serial human-merge-gate mode, do not approve or merge;
  wait for human merge.
- Merge only after phase review approval and passing validation or CI when
  merging is enabled.
- In CI-gated stacked continuation mode, attempt the merge into `develop` after
  CI passes. If approval or merge is unavailable, continue by stacking phase
  N+1 from the old phase N branch and opening phase N+1 against phase N.
- Merge phase PRs into `develop`, not directly into `main` or a predecessor
  branch. Stacked PRs may target predecessor branches for review only.
- Stop immediately if a phase PR targets `main`; close or recreate it against
  the correct stack target rather than merging it.
- Do not skip phases unless the plan explicitly allows it.
- Do not start phase implementation while blocking plan-review findings remain unresolved.
- Do not approve a PR just because tests pass; the explanation must match the diff and phase execution plan.
- Do not require exhaustive test coverage unless the phase warrants it.
- Prefer forward progress with small PRs over large perfect changes.
- Prefer scoped implementation over broader cleanup; capture nonessential work
  as follow-up instead of folding it into the current phase.
- Keep workflow prompt, template, and `AGENTS.md` refinements in the control
  checkout or a dedicated workflow PR unless explicitly assigned as phase work.
- Do not loop on review/refinement. Escalate remaining blockers after the
  bounded pass; do not re-label the same work as a new pass. Pre-submit blocker
  resolution may address concrete blockers before PR submission, and
  post-submit handling is limited to GitHub-only or late blockers that could
  not have been known before submission.
- Use only these phase statuses: `pending`, `in_progress`, `pr_open`, `approved`, `merged`, `blocked`.
- Project custom agents are configured in `.codex/agents/`.
