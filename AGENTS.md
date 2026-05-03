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

- `loom_phase_planner`: uses `gpt-5.5` with `xhigh` reasoning to create the
  phase worktree/branch, draft the phase execution plan, refine the same
  artifact after context compaction or reset, and commit those planning passes.
- `loom_phase_executor`: uses `gpt-5.3-codex-spark` with `high` reasoning to
  execute well-specified implementation slices from the finalized phase
  execution plan with multiple coherent commits.
- `loom_phase_refiner`: uses `gpt-5.5` with `xhigh` reasoning to perform one
  bounded implementation/test refinement pass and commit fixes.
- `loom_pr_preparer`: uses `gpt-5.5` with `xhigh` reasoning to inspect the final
  diff, run checks, record PR facts and stack state, prepare the PR body, and
  open or prepare the PR.
- `loom_phase_reviewer`: uses `gpt-5.5` with `xhigh` reasoning for read-only
  phase PR review.
- `loom_plan_reviewer`: uses `gpt-5.5` with `xhigh` reasoning for read-only
  implementation plan review before phase work begins.
- `loom_architecture_explorer`: uses `gpt-5.4-mini` with `medium` reasoning for
  read-only architecture and boundary exploration.

Use `.codex/prompts/` for repeatable workflow prompts. Do not add extra
agent-directory content outside the current custom-agent structure.
Name prompt files with the artifact and action first using
`<artifact>-<action>.md`, for example `feature-brief-draft.md`,
`phase-execution-plan-refine.md`, and `pr-body-draft.md`.
Use `.codex/templates/` for reusable handoff artifact templates that agents
complete during the stacked workflow. Custom agents define role authority,
sandbox, and model. Prompts define behavior for a draft, refine, review,
implementation, or preparation pass. Templates define durable Markdown
artifacts passed between stages.

### Artifact-Centered Workflow

The workflow is organized around durable stage artifacts, not one file per
agent invocation. Multiple prompts or agents may work on the same artifact.
Each first-class artifact must have a high-level draft pass and a lower-level
refine pass before the next stage depends on it.

First-class artifacts:

- Roadmap-version planning notes, usually in
  `docs/implementation-plans/roadmap-v<N>-planning-notes.md`, when a roadmap
  version needs interactive human discussion before feature or implementation
  planning.
- Feature brief, usually in `docs/briefs/`.
- Specification, usually in `docs/features/`.
- Implementation plan, in `docs/implementation-plans/`.
- Phase execution plan, in `docs/phases/`.
- PR body, usually in `docs/phases/<summary>-pr-body.md`.
- Merge notes, recorded in implementation-plan completion metadata.

Testing plans are embedded by default in specifications, implementation plans,
phase execution plans, and PR evidence. Create a standalone testing plan only
when the assigned work is too large or cross-cutting for embedded suite
obligations to remain reviewable.

For roadmap-version work that needs human discussion, facilitate and complete
roadmap-version planning notes before drafting or changing downstream artifacts.
For new work, draft and refine the feature brief before drafting or changing a
specification. Draft and refine the specification before drafting an
implementation plan. Draft and refine the implementation plan, including its
plan quality gate, before creating phase execution plans.

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

Phase work may continue before human review or merge of earlier phase PRs. Use
stacked PRs to preserve small phase diffs while letting later phases build on
unmerged work.

- A root phase PR targets `develop`.
- A phase that depends on an unmerged predecessor branches from that predecessor
  branch and opens its PR against that predecessor branch.
- The next phase may start once the current phase PR is open or prepared,
  validated, and recorded as `pr_open`; human review and merge are not required
  to start the next phase.
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
- Create phase PRs with explicit base and head branches. Use `develop` only for
  root PRs or PRs already rebased onto `develop`; use the stack predecessor
  branch for stacked PRs:

```sh
gh pr create --base <target-branch> --head codex/<summary-of-feature> --body-file <body>
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
- Create and refine a phase execution plan before implementation.
- Follow the stacked phase handoff. Do not collapse planning, implementation,
  refinement, and PR preparation into one agent unless explicitly instructed.
- Make frequent commits at coherent checkpoints.
- Do not ask the user for feedback during the phase.
- If something is ambiguous, make the smallest reasonable assumption, document
  it in the phase execution plan and PR body, and continue.
- Do not implement future phases early.
- Do not do broad refactors unless required by the assigned phase.
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

Each phase uses this strict sequence:

```text
manager selects next pending phase and stack base
loom_phase_planner drafts and commits the phase execution plan with suite-level test obligations
context is compacted or reset for the refine pass when practical
loom_phase_planner refines and commits the same phase execution plan with decision-complete implementation details
loom_phase_executor implements and commits phase work and phase-scoped tests
loom_phase_refiner performs one bounded refinement pass and commits fixes
loom_pr_preparer runs checks, drafts the PR body, and records suite evidence
context is compacted or reset for the PR body refine pass when practical
loom_pr_preparer refines the PR body, records PR metadata, and opens/prepares PR
manager mirrors pr_open metadata in the control checkout
manager applies any workflow refinements in the control checkout, outside product phase branches
manager may move to the next pending phase using the current phase branch as stack base
loom_phase_reviewer or manager reviews PR
manager approves, retargets/rebases stack children when predecessors land, merges merge-eligible PRs, or escalates to the user
manager records merged metadata and cleans worktree/branch only after successor branches no longer depend on it
```

Do not loop indefinitely. Each gate allows at most one automated refinement
attempt:

- Plan quality gate: one `loom_plan_reviewer` review, one refinement pass, and
  one confirmation review. If blocking findings remain, mark the plan `blocked`
  or leave the phase unstarted and report the blocker to the user.
- Phase implementation: one `loom_phase_refiner` pass after implementation. If
  the PR is still unacceptable, the managing agent must report the blocker to
  the user instead of spawning another fixer.
- Phase PR review: one reviewer pass. The managing agent may merge only if no
  blocking findings remain and checks pass or unavailable checks are justified.

The managing agent owns this loop budget. Before assigning any reviewer or
refiner, confirm the relevant gate has not already consumed its allowed pass in
the current thread, phase execution plan, PR body, or implementation-plan notes.
If the history is unclear, assume the budget is consumed and escalate rather than
starting another automated review/refine cycle. No phase agent may reassign
itself, spawn a replacement fixer, or request another automated pass for the
same gate without an explicit user instruction.

Phase execution plans must record the phase implementation refinement and PR
review budget status so later handoffs can see whether a pass is unused, used,
or explicitly not needed.

Model policy:

- Use `gpt-5.5` with `xhigh` reasoning for whole-phase ownership, ambiguous
  design translation, artifact refinement, review, PR preparation, and
  correctness decisions.
- Use `gpt-5.3-codex-spark` with `high` reasoning for fast implementation from
  a decision-complete phase execution plan. Spark agents must stop and report
  blockers instead of making public API or phase-scope decisions.

### Automatic Merge Policy

Automatic merging is allowed only for the managing agent after phase review
approval.

Before merging, the managing agent must confirm:

- The PR targets `develop`, verified with `gh pr view <PR> --json
  baseRefName,headRefName,state,url`.
- Any successor phase branches have been rebased or are ready to be retargeted
  after the merge.
- The phase PR has passed `loom_phase_reviewer` review, or the managing agent
  has performed the same review locally.
- Required validation commands or CI checks pass, or any unavailable checks are
  clearly justified.
- The PR implements only the assigned phase and does not include future phase
  work.
- The PR body and phase execution plan accurately summarize the implementation,
  suite-level test evidence, assumptions, risks, branch, and worktree path.

After merging, the managing agent must:

- Update the phase status in the selected implementation plan on `develop` to
  `merged`.
- Record the PR link or branch, implementation summary, checks, and follow-up
  notes, including any stack rebase or retargeting work.
- Commit the metadata update with a `docs:` commit message and push it when
  permissions allow. If direct pushes to `develop` are disallowed, prepare a
  small metadata PR without blocking already-open successor phase work.
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

### Plan Quality Gate

Before any phase implementation begins, the selected implementation plan must be
reviewed for
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
managing agent may update a phase to `approved` after review, even if the PR is
still stacked on a predecessor branch, but may update it to `merged` only after
the approved PR is retargeted to and merged into `develop`.

### Phase Checks

Use the repository's existing PR gate commands:

```sh
make validate-pr
make test-summary
```

`make validate-pr` wraps the required Ruff, Pyright, default Pytest, and build
commands. `make test-summary` writes the suite evidence used in PR bodies.
Agents may run narrower suite targets such as `make test-unit`,
`make test-integration`, or direct `uv run pytest ...` commands during
implementation, but PR preparation must report the final validation gate.

If a command cannot be run, record why in the phase execution plan and PR body.

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
- The PR body summarizes implementation, suite-level test evidence, validation,
  assumptions, and risks.
