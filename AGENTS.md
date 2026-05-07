# Agent Guide

This repository contains `loom`, a generic Python runtime for composing,
running, and tracing reproducible research pipelines.

## Working Rules

- Keep `loom` domain-neutral.
- Prefer the source-tree layout and boundaries described in `docs/structure.md`.
- Do not introduce heavyweight runtime dependencies without an explicit design reason.
- Treat authored configs as trusted project code.

## Local Checks

Use this command before committing setup or implementation changes:

```sh
make validate-pr
```

Use `make test-summary` before preparing a PR so the review body has
suite-level evidence.

## Codex Phase Implementation Workflow

This repository uses a phase-based Codex workflow for larger implementation
plans. The canonical v0 implementation plan lives in
`docs/implementation-plans/implementation-plan-v0.md`.
Individual phase execution plans live in `docs/phases/`.
Reusable project-scoped Codex plans live in `.codex/plans/`.

When assigned a phase, implement only that phase.

### Project-Scoped Agents

Project-scoped custom agents live in `.codex/agents/`:

- `loom_phase_planner`: uses `gpt-5.5` with `high` reasoning to create the
  phase worktree/branch, draft the phase execution plan, refine the same
  artifact after context compaction or reset, and commit those planning passes.
- `loom_phase_executor`: uses `gpt-5.3-codex-spark` with `high` reasoning to
  execute well-specified implementation slices from the finalized phase
  execution plan with multiple coherent commits.
- `loom_phase_refiner`: uses `gpt-5.5` with `high` reasoning to perform one
  bounded implementation/test refinement pass and commit fixes.
- `loom_pr_preparer`: uses `gpt-5.5` with `high` reasoning to inspect the final
  diff, run checks, record PR facts and stack state, prepare the PR body, and
  open or prepare the PR.
- `loom_phase_reviewer`: uses `gpt-5.5` with `high` reasoning for read-only
  phase PR review.
- `loom_plan_reviewer`: uses `gpt-5.5` with `high` reasoning for read-only
  implementation plan review before phase work begins.
- `loom_architecture_explorer`: uses `gpt-5.4-mini` with `medium` reasoning for
  read-only architecture and boundary exploration.

Use `.codex/workflows/` for short user-facing entrypoints that explain how to
start common workflows. Use `.codex/prompts/` for repeatable role/action
prompts. Do not add extra agent-directory content outside the current
custom-agent structure.
Name prompt files with the artifact and action first using
`<artifact>-<action>.md`, for example `implementation-plan-draft.md`,
`phase-execution-plan-refine.md`, and `pr-body-draft.md`.
Use `.codex/templates/` for reusable handoff artifact templates that agents
complete during the stacked workflow. Custom agents define role authority,
sandbox, and model. Workflow entrypoints define how users start a workflow.
Prompts define behavior for a draft, refine, review, implementation, or
preparation pass. Templates define durable Markdown artifacts passed between
stages.

### Artifact-Centered Workflow

The workflow is organized around durable stage artifacts, not one file per
agent invocation. Multiple prompts or agents may work on the same artifact.
Implementation plans should have a high-level draft pass and a lower-level
refine pass before phase execution depends on them. Phase execution plans and
PR bodies use the fast path by default: one concise, scope-complete pass is
enough unless the expanded-path triggers below apply.

First-class artifacts:

- Roadmap-version planning notes, usually in
  `docs/implementation-plans/roadmap-v<N>-planning-notes.md`, when a roadmap
  version needs interactive human discussion before implementation planning.
- Implementation plan, in `docs/implementation-plans/`.
- Phase execution plan, in `docs/phases/`.
- PR body, usually in `docs/phases/<summary>-pr-body.md`.
- Merge notes, recorded in implementation-plan completion metadata.

Testing plans are embedded by default in implementation plans, phase execution
plans, and PR evidence. Create a standalone testing plan only when the assigned
work is too large or cross-cutting for embedded suite obligations to remain
reviewable.

For roadmap-version work that needs human discussion, facilitate and complete
roadmap-version planning notes before drafting or changing downstream artifacts.
When the planning discussion is complete and the user explicitly confirms they
are happy with the notes, the roadmap-version planning workflow may continue
directly into `implementation-plan-draft.md` using the confirmed notes as the
primary source. Draft and refine the implementation plan, including its plan
quality gate, before creating phase execution plans. For phase execution and PR
preparation, prefer the fast path unless the phase has broad design or
long-term compatibility risk.

### Branches And Worktrees

- Create a feature branch using `codex/<summary-of-feature>`.
- Use lowercase kebab case for the branch summary.
- Create phase branches from the current stack base:
  - use `develop` when all earlier phases are merged;
  - otherwise use the nearest earlier unmerged phase branch, usually the most
    recent phase with status `pr_open` or `approved`.
- Do all phase work in a separate git worktree under
  `/home/samcantrill/work/loom-worktrees/`.
- Name each worktree with the branch summary, without the `codex/` prefix, for
  example `/home/samcantrill/work/loom-worktrees/config-recipes`.
- Do not implement phase work directly in the original checkout.
- Record the branch, stack predecessor, base branch, PR target branch, and
  worktree path in the phase execution plan.

### Stacked Phase PRs

Phase work may continue before earlier phase PRs merge when a GitHub-side
blocker prevents immediate merge. Human GitHub review is not a workflow gate.
Use stacked PRs to preserve small phase diffs while letting later phases build
on unmerged work.

- A root phase PR targets `develop`.
- A phase that depends on an unmerged predecessor branches from that predecessor
  branch and opens its PR against that predecessor branch.
- The next phase may start once the current phase PR is open or prepared,
  validated, and recorded as `pr_open`; human review is not required to start
  the next phase.
- A stacked PR may be reviewed while it targets a predecessor branch, but it is
  merge-eligible only after it is retargeted to `develop`.
- When a predecessor PR lands, rebase or otherwise replay each immediate
  successor branch onto its new base. Use updated `develop` when that successor
  no longer has an unmerged predecessor; otherwise use the updated predecessor
  branch. Retarget the successor PR as needed, rerun validation, and record the
  stack maintenance in the phase artifacts.
- Do not delete a phase branch until every successor branch has been retargeted
  or rebased away from it.
- Keep managing-agent workflow refinements in the original control checkout or
  a dedicated workflow PR. Do not include workflow prompt, template, or
  `AGENTS.md` refinements in product phase PR diffs unless explicitly assigned.

### No Human Merge Gate

Implementation phase progress must not be gated on human GitHub review or human
merge. The managing agent owns the automated review and merge decision.

- Do not select or invent a serial human-owned merge workflow for phase
  implementation.
- Open phase PRs for reviewability and CI, but treat `loom_phase_reviewer` or
  equivalent manager review plus validation/CI as the approval gate.
- If GitHub branch protection blocks solely because a human review approval is
  required, use available merge authority, including `gh pr merge --admin`,
  after automated review, validation, CI, target-branch, and scope gates pass.
- Do not use admin bypass for failing CI, wrong target branch, unresolved merge
  conflicts, or known implementation/review blockers.
- If admin merge authority is unavailable for a review-only protection blocker,
  record the exact blocker and continue with stacked phase flow instead of
  waiting for human approval.
- If a later user asks for human visibility, mention or comment only for
  awareness. Do not request GitHub reviewers and do not wait for human approval
  unless the user explicitly asks Codex to stop automated implementation.

### GitHub CLI And Remote Operations

- Prefer GitHub CLI-backed authentication for GitHub operations when available.
  Before fetch, push, PR creation, PR inspection, merge, or remote branch
  cleanup, check `gh auth status`. In sandboxed Codex sessions,
  `gh auth status` can falsely report the stored token as invalid when network
  access is restricted. If the command reports an invalid token, rerun
  `gh auth status` with approved network access before treating credentials as
  unavailable. If authentication is still invalid outside the sandbox, ask the
  user to allow `gh auth logout -h github.com -u <user>` followed by
  `gh auth login -h github.com -p https -w`, then run
  `gh auth setup-git`.
- After a successful `gh auth login`, run `gh auth setup-git` before GitHub
  fetch, push, PR creation, PR inspection, merge, or remote branch cleanup.
  Verify both `gh` and Git access with `gh auth status` and a lightweight remote
  command such as `git ls-remote --heads origin develop`. If `gh` is
  authenticated but git remote operations fail through SSH, run
  `gh auth setup-git` and use the HTTPS remote form
  `https://github.com/<owner>/<repo>.git` for `origin`.
- Use `git` for local worktree and commit operations. Use `gh` wherever it
  provides safer GitHub state checks or avoids SSH-only behavior.
- Create phase PRs with explicit base, head, and title. PR titles must use
  `<feature-focus> - Phase <X>: <Words to scope>`, for example
  `Configuration - Phase 1: Boundary and Artifact Contracts`. Use `develop`
  only for root PRs or PRs already rebased onto `develop`; use the stack
  predecessor branch for stacked PRs:

```sh
gh pr create --base <target-branch> --head codex/<summary-of-feature> --title "<feature-focus> - Phase <X>: <Words to scope>" --body-file <body>
```

- Immediately verify the created or existing PR with:

```sh
gh pr view <PR> --json baseRefName,headRefName,state,url
```

  Stop if `baseRefName` is neither `develop` nor the recorded stack
  predecessor branch. Do not approve or merge a phase PR targeting `main` or an
  unrecorded branch.
- Before every merge, verify the PR target again with `gh pr view <PR>
  --json baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup`.
  The managing agent must record this check in the review or merge notes. Merge
  only when `baseRefName` is exactly `develop`.
- Prefer `gh pr merge <PR> --squash --delete-branch` for phase merges only
  when no successor branch depends on the phase branch. If successors still
  target or branch from it, use `gh pr merge <PR> --squash` and keep the
  branch until stack maintenance retargets successors. Use the corresponding
  `--auto` form only when branch protection requires queued/auto merge.
- If a merged phase branch is not deleted by `gh pr merge` and no successor
  branch depends on it, prefer deleting the GitHub branch through `gh api
  --method DELETE repos/<owner>/<repo>/git/refs/heads/<branch>` before falling
  back to `git push origin --delete <branch>`. Then remove stale local tracking
  refs with `git branch -dr origin/<branch>` when present.

### Phase Rules

- Read the full implementation plan before writing code.
- Confirm the implementation plan has passed the plan quality gate before
  starting phase work.
- Create a scope-complete phase execution plan before implementation. Keep
  phase plans scope-first: define boundaries, acceptance criteria, suite
  obligations, risky decisions, and stop conditions without turning the plan
  into an exhaustive implementation recipe. Refine the phase plan only when the
  expanded-path triggers below apply.
- Record the PR feature focus and intended PR title in the phase execution plan
  before implementation begins so PR preparation does not invent title scope.
- Follow the stacked phase handoff and automatic merge policy. Do not collapse
  role ownership into one agent unless explicitly instructed, but skip optional
  second passes on the fast path.
- Make frequent commits at coherent checkpoints.
- Do not ask the user for feedback during the phase.
- If something is ambiguous, make the smallest reasonable assumption, document
  it in the phase execution plan and PR body, and continue.
- Do not implement future phases early.
- Do not do broad refactors unless required by the assigned phase.
- Prefer the smallest maintainable diff that satisfies the assigned phase and
  tests.
- Prefer direct, maintainable code over clever abstractions.
- Make maintainability, extensibility, conflicting design choices, accepted
  technical debt, and future compatibility explicit in plans.
- Add or update tests for the behavior changed in the phase. Phase execution
  plans must identify required package, unit, contract, integration, e2e, and
  opt-in test coverage, or explicitly defer suites that do not apply.
- Run relevant checks before opening a PR.
- Open or prepare a PR targeting the recorded stack target branch and stop.
  Phase agents must not merge phase PRs.

### Stacked Phase Handoff

Default fast path for a routine phase:

```text
manager selects next pending phase and stack base
loom_phase_planner creates one concise scope-complete phase execution plan with suite-level test obligations
loom_phase_executor implements and commits phase work and phase-scoped tests
manager skips loom_phase_refiner when targeted validation passes and coverage obligations are met
loom_pr_preparer runs checks, writes a concise human-readable PR body with suite evidence, and opens/prepares PR in one pass
manager mirrors pr_open metadata in the control checkout
manager applies any workflow refinements in the control checkout, outside product phase branches
loom_phase_reviewer or manager reviews PR
manager waits for GitHub CI, merges the phase PR into develop when checks pass, records merged metadata, and cleans worktree/branch when no successor depends on it
manager uses stacked continuation only when a GitHub-side blocker prevents the merge and the blocker cannot be resolved in scope
```

Use the expanded path when the phase is likely to have durable design impact or
high coordination cost. Expanded-path triggers include:

- public API or public protocol design;
- changes spanning multiple core areas such as config, planning, execution,
  stores, serialization, provenance, or pipeline graph behavior;
- schema, migration, compatibility, or persistence contract changes;
- dependency, packaging, import-boundary, or source-tree boundary changes;
- concurrency, locking, retry, resume, or data-loss risk;
- ambiguous acceptance criteria or unresolved implementation-plan tradeoffs.

Expanded path adds the optional second passes:

```text
loom_phase_planner drafts the phase execution plan
context is compacted or reset for the refine pass when practical
loom_phase_planner refines the same phase execution plan
loom_phase_refiner performs one bounded refinement pass after implementation
loom_pr_preparer may draft then refine the PR body before opening/preparing the PR
```

Do not loop indefinitely. Review and refinement gates stay bounded, while
blocker resolution has a separate scoped phase budget:

- Plan quality gate: one `loom_plan_reviewer` review, one refinement pass, and
  one confirmation review. If blocking findings remain, mark the plan `blocked`
  or leave the phase unstarted and report the blocker to the user.
- Phase implementation: zero `loom_phase_refiner` passes on the fast path, or
  one pass when targeted validation fails, suite coverage is missing, or the
  expanded path is active. If the PR is still unacceptable, the managing agent
  may use the separate blocker-resolution budget only for concrete blockers
  with bounded remedies.
- Phase PR review: one reviewer pass. The managing agent may merge only if no
  blocking findings remain and checks pass or unavailable checks are justified.
- Blocker resolution: up to three scoped blocker-resolution passes per phase
  may be used for concrete implementation, test, PR-body, validation, CI, or
  mergeability blockers. Each pass must target one concrete blocker or a tight
  cluster with the same root cause. If blockers remain after the third pass,
  mark the phase or PR `blocked` and report the remaining blocker.

The managing agent owns this loop budget. Before assigning any reviewer or
refiner, confirm the relevant gate has not already consumed its allowed pass in
the current thread, phase execution plan, PR body, or implementation-plan notes.
If the history is unclear, assume the budget is consumed and escalate rather than
starting another automated review/refine cycle. No phase agent may reassign
itself, spawn a replacement fixer, or request another automated pass for the
same gate without an explicit user instruction.

When blocker resolution is needed after a gate has stopped, the managing agent
may use the phase's blocker-resolution budget to create a scoped
blocker-resolution subagent or perform an equivalent scoped local fix. Use
`loom_phase_refiner` for implementation or test fixes, `loom_pr_preparer` for
PR body or metadata fixes, or the narrowest applicable project-scoped agent. The
handoff must cite the concrete blocker, bound the write scope, prohibit
future-phase work, require validation, and require phase artifact updates. These
passes do not reset the original review or refinement budgets. If the same
blocker remains after its scoped pass, spend another blocker-resolution pass
only when there is a concrete new remedy; otherwise report the blocker instead
of looping.

Phase execution plans must record the phase implementation refinement, PR
review, and blocker-resolution budget status so later handoffs can see whether a
pass is unused, used, or explicitly not needed.

Model policy:

- Use `gpt-5.5` with `high` reasoning for whole-phase ownership, ambiguous
  design translation, artifact refinement, review, PR preparation, and
  correctness decisions.
- Use `gpt-5.3-codex-spark` with `high` reasoning for fast implementation from
  a scope-complete phase execution plan. Spark agents must stop and report
  blockers instead of making public API or phase-scope decisions.

### Automatic Merge Policy

Automatic merging is mandatory for phase PRs whenever GitHub permissions and
checks allow it. The managing agent owns the review and merge decision and must
not wait for human GitHub approval.

Before merging, the managing agent must confirm:

- The PR targets `develop`, verified with `gh pr view <PR> --json
  baseRefName,headRefName,state,url`.
- Any successor phase branches have been rebased or are ready to be retargeted
  after the merge.
- The phase PR has passed `loom_phase_reviewer` review, or the managing agent
  has performed the same review locally. This automated review satisfies the
  phase approval gate; GitHub review approval is not required.
- Required validation commands or CI checks pass, or any unavailable checks are
  clearly justified.
- The PR implements only the assigned phase and does not include future phase
  work.
- The PR body accurately summarizes the implementation, suite-level test
  evidence, assumptions, and risks. The phase execution plan records workflow
  metadata such as branch and worktree path.
- If GitHub blocks merge only because repository branch protection requires a
  human approval, the managing agent must use available merge authority,
  including `gh pr merge --admin`, after recording the blocker and confirming
  all automated review and validation gates above. If that authority is
  unavailable, record the blocker and continue with stacked phase flow rather
  than waiting for human approval. Do not use admin bypass for failing CI, wrong
  target branch, unresolved merge conflicts, or known implementation/review
  blockers.

After merging, the managing agent must:

- Update the phase status in the selected implementation plan on `develop` to
  `merged`.
- Record the PR link or branch, implementation summary, checks, and follow-up
  notes, including any stack rebase or retargeting work.
- Commit the metadata update on `develop` with a `docs:` commit message and
  push it directly to `develop` when permissions allow. Do not open a separate
  "Post Phase <N> Merge" or other metadata-only PR for this bookkeeping update.
  If direct pushes to `develop` are disallowed or fail, record the exact blocker
  and ask the user how to proceed instead of creating a fallback PR.
- Remove the phase worktree from `/home/samcantrill/work/loom-worktrees/` and
  prune stale worktree metadata only after successor branches no longer depend
  on that worktree or branch.
- Delete the phase branch if it was not deleted by the merge command and no
  successor branch depends on it. Prefer `gh api --method DELETE
  repos/<owner>/<repo>/git/refs/heads/<branch>` when git SSH auth is
  unavailable, then remove stale local tracking refs.

Prefer GitHub squash merges with branch deletion only when no successor branch
depends on the phase branch:

```sh
gh pr merge <PR> --squash --delete-branch
```

Keep the branch during the merge when successor branches still depend on it:

```sh
gh pr merge <PR> --squash
```

If branch protection requires checks to finish first, use:

```sh
gh pr merge <PR> --auto --squash
```

Add `--delete-branch` to the auto-merge command only when no successor branch
depends on the phase branch.

If branch protection blocks solely on human approval and the managing account has
admin merge authority, use the corresponding `--admin` form after the automated
review and validation gates pass:

```sh
gh pr merge <PR> --squash --delete-branch --admin
```

### Plan Quality Gate

Before any phase selection or implementation begins, the managing agent must
perform the selected implementation plan's quality gate. If the gate already
records a current passed result for the selected plan, verify that evidence;
otherwise run the review/refinement/confirmation sequence and stop on blocking
findings.

The selected implementation plan must be reviewed for
maintainability, extensibility, future compatibility, conflicting design
choices, technical debt, test strategy, and reviewability.

The implementation plan should include, where relevant:

- Design principles.
- Key design choices.
- Conflicts and tradeoffs.
- Maintainability assessment.
- Extensibility assessment.
- Technical debt ledger with revisit triggers.
- Plan quality gate status.

Each phase should include, where relevant:

- Design impact.
- Future compatibility.
- Alternatives rejected.
- Debt introduced.
- Reviewability.

Do not start implementation while blocking plan-review findings remain
unresolved. If a risk is accepted, record why and define the trigger for
revisiting it.

### Phase Statuses

Use only these status values in implementation plans:

```text
pending
in_progress
pr_open
approved
merged
blocked
```

The managing agent updates a phase from `pending` or `in_progress` to `pr_open`
in the control checkout after the PR is opened or prepared. In stacked
workflows, `pr_open` means the PR is submitted or ready against its recorded
target branch and the phase branch is valid as a continuation base. The
managing agent may update a phase to `approved` after automated review, even if
the PR is still stacked on a predecessor branch, but may update it to `merged`
only after the approved PR is retargeted to and merged into `develop`.

### Phase Checks

Use the repository's existing PR gate commands:

```sh
make validate-pr
make test-summary
```

`make validate-pr` wraps the required Ruff, Pyright, default Pytest, and build
commands. `make test-summary` writes the suite evidence used in PR bodies; PR
bodies should summarize this evidence with compact Markdown tables rather than
box-drawing output or long command tails.
Agents may run narrower suite targets such as `make test-unit`,
`make test-integration`, or direct `uv run pytest ...` commands during
implementation, but PR preparation must report the final validation gate.

If a command cannot be run, record why in the phase execution plan and PR body.
Keep detailed workflow internals such as commit lists, budget accounting,
GitHub JSON, and notification mechanics in phase execution notes, not in the
public PR body.

### Commit Style

Make frequent commits after coherent units of work. Recommended prefixes:

```text
plan: add phase execution plan
feat: implement phase behavior
test: add phase coverage
fix: refine implementation after validation
docs: update implementation plan
```

### Definition Of Done

A phase is done when:

- The phase execution plan exists.
- The phase execution plan documents design impact, future compatibility,
  alternatives rejected, debt introduced, and reviewability.
- The phase execution plan records draft/refine status and refinement/review
  budget status.
- The implementation matches the selected phase.
- Relevant tests are added or updated.
- Relevant checks have been run.
- Failing checks are fixed or clearly explained.
- The PR body summarizes implementation, new tests added for changed behavior,
  suite-level test evidence, validation, assumptions, and risks.
