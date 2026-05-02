# Agent Guide

This repository contains `loom`, a generic Python runtime for composing,
running, and tracing reproducible research pipelines.

## Working Rules

- Keep `loom` domain-neutral.
- Prefer the source-tree layout and boundaries described in `docs/structure.md`.
- Do not introduce heavyweight runtime dependencies without an explicit design reason.
- Treat authored configs as trusted project code.

## Local Checks

Use these commands before committing setup or implementation changes:

```sh
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

## Codex Phase Implementation Workflow

This repository uses a phase-based Codex workflow for larger implementation
plans. The canonical implementation plan lives in `docs/implementation-plan.md`.
Individual expanded phase plans live in `docs/phases/`.
Reusable project-scoped Codex plans live in `.codex/plans/`.

When assigned a phase, implement only that phase.

### Project-Scoped Agents

Project-scoped custom agents live in `.codex/agents/`:

- `loom_phase_implementer`: uses `gpt-5.5` with `high` reasoning for one-phase
  implementation work in a writable worktree.
- `loom_phase_reviewer`: uses `gpt-5.5` with `xhigh` reasoning for read-only
  phase PR review.
- `loom_plan_reviewer`: uses `gpt-5.5` with `xhigh` reasoning for read-only
  implementation plan review before phase work begins.
- `loom_architecture_explorer`: uses `gpt-5.4-mini` with `medium` reasoning for
  read-only architecture and boundary exploration.

Use `.codex/prompts/` for repeatable workflow prompts. Do not add legacy
agent-directory content.
Name prompt files with the workflow stage first using `<stage>-<substage>.md`,
for example `implementation-plan-review.md`, `pull-request-review.md`, and
`implementation-test-refinement.md`.

### Branches And Worktrees

- Create a feature branch using `codex/<summary-of-feature>`.
- Use lowercase kebab case for the branch summary.
- Do all phase work in a separate git worktree.
- Do not implement phase work directly in the original checkout.
- Record the branch and worktree path in the expanded phase plan.

### Phase Rules

- Read the full implementation plan before writing code.
- Confirm the implementation plan has passed the plan quality gate before
  starting phase work.
- Create an expanded phase plan before implementation.
- Make frequent commits at coherent checkpoints.
- Do not ask the user for feedback during the phase.
- If something is ambiguous, make the smallest reasonable assumption, document
  it in the phase plan and PR body, and continue.
- Do not implement future phases early.
- Do not do broad refactors unless required by the assigned phase.
- Prefer direct, maintainable code over clever abstractions.
- Make maintainability, extensibility, conflicting design choices, accepted
  technical debt, and future compatibility explicit in plans.
- Add or update tests for the behavior changed in the phase.
- Run relevant checks before opening a PR.
- Open or prepare a PR targeting `develop` and stop. Implementation agents must
  not merge phase PRs.

### Automatic Merge Policy

Automatic merging is allowed only for the managing agent after phase review
approval.

Before merging, the managing agent must confirm:

- The PR targets `develop`.
- The phase PR has passed `loom_phase_reviewer` review, or the managing agent
  has performed the same review locally.
- Required validation commands or CI checks pass, or any unavailable checks are
  clearly justified.
- The PR implements only the assigned phase and does not include future phase
  work.
- The PR body and expanded phase plan accurately summarize the implementation,
  tests, assumptions, risks, branch, and worktree path.

After merging, the managing agent must:

- Update the phase status in `docs/implementation-plan.md` on `develop` to
  `merged`.
- Record the PR link or branch, implementation summary, checks, and follow-up
  notes.
- Commit the metadata update with a `docs:` commit message and push it when
  permissions allow. If direct pushes to `develop` are disallowed, prepare a
  small metadata PR and stop before starting the next phase.
- Remove the phase worktree and prune stale worktree metadata.
- Delete the phase branch if it was not deleted by the merge command.

Prefer GitHub squash merges with branch deletion when available:

```sh
gh pr merge --squash --delete-branch
```

If branch protection requires checks to finish first, use:

```sh
gh pr merge --auto --squash --delete-branch
```

### Plan Quality Gate

Before any phase implementation begins, `docs/implementation-plan.md` must be
reviewed for maintainability, extensibility, future compatibility, conflicting
design choices, technical debt, test strategy, and reviewability.

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

Use only these status values in `docs/implementation-plan.md`:

```text
pending
in_progress
pr_open
approved
merged
blocked
```

The implementation agent may update a phase from `pending` to `pr_open` after
opening or preparing the PR. The managing agent may update it to `approved`
after review and to `merged` after the approved PR is merged into `develop`.

### Phase Checks

Use the repository's existing commands:

```sh
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

If a command cannot be run, record why in the expanded phase plan and PR body.

### Commit Style

Make frequent commits after coherent units of work. Recommended prefixes:

```text
plan: add expanded phase plan
feat: implement phase behavior
test: add phase coverage
fix: refine implementation after validation
docs: update implementation plan
```

### Definition Of Done

A phase is done when:

- The expanded phase plan exists.
- The expanded phase plan documents design impact, future compatibility,
  alternatives rejected, debt introduced, and reviewability.
- The implementation matches the selected phase.
- Relevant tests are added or updated.
- Relevant checks have been run.
- Failing checks are fixed or clearly explained.
- The PR body summarizes implementation, tests, assumptions, and risks.
