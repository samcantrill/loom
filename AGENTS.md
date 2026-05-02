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
Reusable project-scoped Codex plans and workflow notes live in `.codex/plans/`.

When assigned a phase, implement only that phase.

### Project-Scoped Agents

Project-scoped custom agents live in `.codex/agents/`:

- `loom_phase_implementer`: uses `gpt-5.5` with `high` reasoning for one-phase
  implementation work in a writable worktree.
- `loom_phase_reviewer`: uses `gpt-5.5` with `xhigh` reasoning for read-only
  phase PR review.
- `loom_architecture_explorer`: uses `gpt-5.4-mini` with `medium` reasoning for
  read-only architecture and boundary exploration.

Use `.codex/prompts/` for repeatable workflow prompts and `.codex/plans/` for
Codex workflow source plans. Do not add legacy agent-directory content.

### Branches And Worktrees

- Create a feature branch using `codex/<summary-of-feature>`.
- Use lowercase kebab case for the branch summary.
- Do all phase work in a separate git worktree.
- Do not implement phase work directly in the original checkout.
- Record the branch and worktree path in the expanded phase plan.

### Phase Rules

- Read the full implementation plan before writing code.
- Create an expanded phase plan before implementation.
- Make frequent commits at coherent checkpoints.
- Do not ask the user for feedback during the phase.
- If something is ambiguous, make the smallest reasonable assumption, document
  it in the phase plan and PR body, and continue.
- Do not implement future phases early.
- Do not do broad refactors unless required by the assigned phase.
- Prefer direct, maintainable code over clever abstractions.
- Add or update tests for the behavior changed in the phase.
- Run relevant checks before opening a PR.
- Open or prepare a PR and stop. Do not merge directly to `main`.

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
opening or preparing the PR. The managing agent may update it to `approved` or
`merged` after review.

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
- The implementation matches the selected phase.
- Relevant tests are added or updated.
- Relevant checks have been run.
- Failing checks are fixed or clearly explained.
- The PR body summarizes implementation, tests, assumptions, and risks.
