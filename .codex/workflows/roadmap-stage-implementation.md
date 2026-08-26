# Roadmap Stage Implementation

## Goal

Execute one approved compact implementation manifest through isolated phase
worktrees, tests, validation, PRs, automatic merge to develop, metadata, and
cleanup.

## Read

- AGENTS.md
- .codex/prompts/subagent-lifecycle.md
- .codex/prompts/phase-loop-management.md
- the selected manifest and current phase execution plan
- current source, tests, diff, PR, and local validation evidence

Do not load planning.md, unrelated phase plans, completed lifecycle detail, or
superseded discussion unless a current blocker cites it.

## Preconditions

- Planning and implementation-plan quality gates are passed.
- The manifest links one complete phase plan per phase.
- The current develop base and worktree root are known.
- Any legacy active plan has been audited before resumption.

## Normal Phase Cost

- Manager-local setup and pre-submit work.
- One loom_phase_executor.
- No planner, refiner, PR preparer, or reviewer spawn by default.

Use loom_phase_planner only for an expanded-path contract risk,
loom_phase_refiner only for a qualified blocker, and loom_phase_reviewer only
for expanded-path or material residual-risk review.

## Execution

Follow .codex/prompts/phase-loop-management.md as the canonical procedure.
Every normal phase gets one branch, one worktree, and one PR targeting develop.
Routine stacked PRs and new workflow sidecars are not used.

A phase is complete only after remote merge, concise metadata update, and
cleanup or an explicitly recorded cleanup blocker.
