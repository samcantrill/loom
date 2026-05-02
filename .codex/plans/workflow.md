# Simplified Codex Phase Implementation Workflow

## Purpose

Set up a lightweight workflow for an agent to implement one phase of a larger implementation plan autonomously.

The team provides a larger implementation plan and tells the agent which phase to focus on. The agent reads the full plan, expands the selected phase into a concrete phase plan, creates a separate git worktree and feature branch, implements the phase, writes tests, validates the implementation through tests, refines based on failures, opens a PR, and records the result.

A managing agent can then review the PR against the phase plan and test results. If the explanation matches the implementation and the checks pass, the managing agent approves the PR, updates the implementation plan, and starts the next phase.

This workflow is intentionally simple. It should not require a large orchestration system, complex schemas, dashboards, or exhaustive test matrices.

---

## Core Workflow

One phase should move through this loop:

```text
Full implementation plan
        ↓
Selected phase assignment
        ↓
Agent creates separate git worktree + feature branch
        ↓
Agent writes expanded phase plan
        ↓
Agent implements with frequent commits
        ↓
Agent writes/updates tests
        ↓
Agent runs validation commands
        ↓
Agent refines based on failures
        ↓
Agent opens PR
        ↓
Managing agent reviews PR against plan + tests
        ↓
Managing agent approves, updates plan, starts next phase
```

The implementation agent should not ask the user for feedback during the phase. If the plan is ambiguous, it should make the smallest reasonable assumption, document it in the phase plan and PR body, and continue.

---

## Minimal Repository Setup

Add or update these files as needed:

```text
AGENTS.md

.codex/
  config.toml
  agents/
    loom-phase-implementer.toml
    loom-phase-reviewer.toml
    loom-architecture-explorer.toml
  plans/
    workflow.md
    v0-implementation-plan.md
  prompts/
    convert-plan-to-phases.md
    phase-assignment.md
    create-phase-plan.md
    implement-phase.md
    refine-from-tests.md
    create-pr.md
    review-phase-pr.md
    manage-phase-loop.md

.github/
  PULL_REQUEST_TEMPLATE.md

docs/
  implementation-plan.md
  phases/
    .gitkeep
```

Optional but useful:

```text
.github/workflows/ci.yml
```

Do not add more structure until it is needed.

---

## Project-Scoped Custom Agents

Project-specific custom agents live in `.codex/agents/`. Keep this set small
and role-specific:

```text
.codex/agents/loom-phase-implementer.toml
  name = "loom_phase_implementer"
  model = "gpt-5.5"
  model_reasoning_effort = "high"
  sandbox_mode = "workspace-write"

.codex/agents/loom-phase-reviewer.toml
  name = "loom_phase_reviewer"
  model = "gpt-5.5"
  model_reasoning_effort = "xhigh"
  sandbox_mode = "read-only"

.codex/agents/loom-architecture-explorer.toml
  name = "loom_architecture_explorer"
  model = "gpt-5.4-mini"
  model_reasoning_effort = "medium"
  sandbox_mode = "read-only"
```

Use custom agents for reusable roles with different behavior or sandbox
settings. Keep repeatable task instructions in `.codex/prompts/`.

---

## Non-Destructive Setup Rules

The setup agent must adapt to the existing repository instead of overwriting it.

Rules:

* Inspect existing files before editing them.
* Do not replace an existing `AGENTS.md`; add only the missing workflow guidance needed for this process.
* Do not replace an existing pull request template; update it only if it is missing the fields needed for phase-based Codex PRs.
* Do not replace an existing implementation plan; align it with the phased structure or add a new phased section if needed.
* Do not overwrite existing CI. If CI already exists, document the existing validation commands in `AGENTS.md` and use them.
* Create new prompt files under `.codex/prompts/` if they do not exist.
* If a file exists with conflicting instructions, preserve the existing project-specific guidance and add the smallest compatible workflow addition.
* If uncertain, prefer appending a clearly labeled section over rewriting the file.

Preferred heading for appended content:

```md
## Codex phase implementation workflow
```

---

## Branch and Worktree Scheme

Every implementation phase gets its own feature branch and separate git worktree.

Use this branch pattern:

```text
codex/<summary-of-feature>
```

Examples:

```text
codex/add-billing-domain-types
codex/refactor-invoice-calculation
codex/add-validation-errors
codex-migrate-user-settings
```

Use lowercase kebab case. The summary should be specific enough to avoid collisions, but short enough to read in a PR list.

Correct:

```text
codex/add-invoice-service
codex/add-payment-validation
codex/refactor-auth-session-store
```

Avoid:

```text
codex/fix
codex/phase-1
codex/a001-api
codex/implementation
```

If the intended branch already exists, choose a more specific summary rather than adding random numbers.

Worktree pattern:

```text
../<repo-name>-codex-<summary-of-feature>
```

Example:

```bash
git fetch origin
BRANCH="codex/add-invoice-service"
WORKTREE="../$(basename "$(git rev-parse --show-toplevel)")-codex-add-invoice-service"
git worktree add -b "$BRANCH" "$WORKTREE"
cd "$WORKTREE"
```

Rules:

* Do all phase work inside the worktree, not in the original checkout.
* Run implementation, tests, commits, and PR preparation from the worktree.
* Keep one worktree per active phase.
* Remove the worktree only after the PR is merged or abandoned.
* Record the branch and worktree path in the expanded phase plan and PR body.

---

## `AGENTS.md`

Create or update `AGENTS.md` with the following workflow guidance. If `AGENTS.md` already exists, do not overwrite it. Merge in the missing content under a heading such as `## Codex phase implementation workflow`.

````md
## Codex phase implementation workflow

This repository uses a phase-based Codex workflow.

A larger implementation plan lives in `docs/implementation-plan.md`. Individual expanded phase plans live in `docs/phases/`.

When assigned a phase, implement only that phase.

### Branches and worktrees

- Create a feature branch using `codex/<summary-of-feature>`.
- Use lowercase kebab case for the branch summary.
- Do all phase work in a separate git worktree.
- Do not implement directly in the original checkout.
- Record the branch and worktree path in the phase plan.

### Rules

- Read the full implementation plan before writing code.
- Create an expanded phase plan before implementation.
- Work on a dedicated branch and worktree.
- Make frequent commits at coherent checkpoints.
- Do not ask the user for feedback during the phase.
- If something is ambiguous, make the smallest reasonable assumption, document it, and continue.
- Do not implement future phases early.
- Do not do broad refactors unless required by the assigned phase.
- Prefer direct, maintainable code over clever abstractions.
- Add or update tests for the behavior changed in the phase.
- Run relevant checks before opening a PR.
- Open a PR and stop. Do not merge directly to main.

### Checks

Use the repository’s existing commands. Prefer these when available:

```bash
npm run lint
npm run typecheck
npm test
````

If this is not a Node project, inspect the repository and use the equivalent commands.

Do not invent package scripts. If a command does not exist, record that in the PR body.

### Commit style

Make frequent commits after coherent units of work.

Recommended commit prefixes:

```text
plan: add expanded phase plan
feat: implement phase behavior
test: add phase coverage
fix: refine implementation after validation
docs: update implementation plan
```

### Definition of done

A phase is done when:

* The expanded phase plan exists.
* The implementation matches the selected phase.
* Relevant tests are added or updated.
* Relevant checks have been run.
* Failing checks are fixed or clearly explained.
* The PR body summarizes implementation, tests, assumptions, and risks.

````

---

## `docs/implementation-plan.md`

This is the human-authored larger plan. Keep it clear enough for Codex to execute phase by phase.

If this file already exists, do not overwrite it. Align it with the structure below by adding missing sections or adding a clearly labeled phased implementation section.

Template:

```md
# Implementation Plan

## Goal

Describe the feature, refactor, migration, or system change.

## Context

Explain why this work is needed and how the current system behaves.

## Desired outcome

Describe the target behavior or architecture once all phases are complete.

## Non-goals

List things that should not be included.

## Constraints

List compatibility, migration, security, performance, API, UX, or rollout constraints.

## Phased implementation

### Phase 1 — Short title

Status: pending
Branch: `codex/short-feature-summary`
PR: pending

Goal:
- Describe what this phase should accomplish.

Scope:
- List what should be changed.

Out of scope:
- List what should not be changed yet.

Acceptance criteria:
- Criterion 1.
- Criterion 2.

Test expectations:
- Unit tests for changed behavior.
- Integration tests if this crosses a boundary.

Notes:
- Any relevant implementation guidance.

Completion summary:
- Filled in by the managing agent after PR approval or merge.

### Phase 2 — Short title

Status: pending
Branch: `codex/another-feature-summary`
PR: pending

Goal:
- ...

Scope:
- ...

Acceptance criteria:
- ...
````

Allowed phase statuses:

```text
pending
in_progress
pr_open
approved
merged
blocked
```

The implementation agent may update a phase from `pending` to `pr_open` after opening the PR. The managing agent may update it to `approved` or `merged` after review.

---

## Template: Convert a Plan Into a Structured Phased Plan

Use this when the team has a rough plan, design document, issue, or feature description and wants Codex to turn it into an implementation plan.

The conversion should produce or update `docs/implementation-plan.md`. If that file already exists, preserve its content and add or align the phased implementation section instead of replacing the file.

````md
You are converting an existing plan into a structured phased implementation plan.

Inputs:

- Existing repository files.
- Existing `docs/implementation-plan.md`, if present.
- Existing design docs, issues, README files, or comments relevant to the requested feature.
- The rough plan or feature description provided by the user.

Task:

1. Read the relevant existing files first.
2. Identify the current architecture, conventions, test setup, and existing implementation boundaries.
3. Convert the rough plan into a sequence of small, reviewable phases.
4. Each phase should be suitable for one PR.
5. Each phase should have a clear branch name using `codex/<summary-of-feature>`.
6. Each phase should have concrete acceptance criteria.
7. Each phase should define what is in scope and out of scope.
8. Each phase should define expected tests or validation.
9. Preserve any existing implementation plan content.
10. Add or update only the missing structured phase content.

Planning principles:

- Prefer smaller phases over large phases.
- Keep behavior-preserving refactors separate from behavior changes.
- Put risky migrations, compatibility layers, and rollout changes in their own phases.
- Do not introduce unnecessary architecture.
- Do not create phases that depend on unspecified future decisions.
- Make assumptions explicit.
- If the rough plan conflicts with existing repo patterns, align with the existing repo unless the plan explicitly says to change them.

Output format:

```md
## Phased implementation

### Phase 1 — <Short title>

Status: pending
Branch: `codex/<summary-of-feature>`
PR: pending

Goal:
- ...

Scope:
- ...

Out of scope:
- ...

Acceptance criteria:
- ...

Test expectations:
- ...

Notes:
- ...

Completion summary:
- Pending.
````

````

---

## Prompt: Convert Plan to Phases

Create `.codex/prompts/convert-plan-to-phases.md`.

```md
You are converting a rough implementation plan into a structured phased plan for autonomous Codex implementation.

Read existing repository files before editing:

- `AGENTS.md`, if present
- `docs/implementation-plan.md`, if present
- README or project documentation
- Existing tests and package/build configuration
- Any user-provided plan or design document

Task:

1. Preserve existing files and project guidance.
2. Do not overwrite `docs/implementation-plan.md` if it already exists.
3. Add or align a `## Phased implementation` section.
4. Break the plan into small phases, each suitable for one PR.
5. Assign each phase a branch using `codex/<summary-of-feature>`.
6. For each phase, include:
   - Status
   - Branch
   - Goal
   - Scope
   - Out of scope
   - Acceptance criteria
   - Test expectations
   - Notes
   - Completion summary
7. Keep phases ordered so the implementation can proceed from top to bottom.
8. Separate refactors, behavior changes, migrations, and cleanup into distinct phases where practical.

Rules:

- Do not ask the user for feedback.
- If the plan is ambiguous, make the smallest reasonable assumption and document it.
- Do not invent requirements not supported by the plan or existing repo.
- Align with existing repository patterns.
- Keep the plan lightweight and executable.
````

---

## Expanded Phase Plan Template

For each phase, the implementation agent creates a document in `docs/phases/`.

Use this filename pattern:

```text
docs/phases/<summary-of-feature>.md
```

Examples:

```text
docs/phases/add-invoice-service.md
docs/phases/add-payment-validation.md
```

Template:

````md
# Phase Plan: <Phase Title>

## Branch

`codex/<summary-of-feature>`

## Worktree

`../<repo-name>-codex-<summary-of-feature>`

## Source phase

Reference the phase from `docs/implementation-plan.md`.

## Objective

State the specific outcome for this phase.

## Full-plan context

Summarize how this phase fits into the larger implementation plan.

## In scope

- Item 1
- Item 2

## Out of scope

- Future phase work that should not be implemented yet
- Refactors that are not needed for this phase

## Assumptions

List assumptions made to proceed without asking the user.

## Files and areas to inspect

- Path or module 1
- Path or module 2

## Implementation steps

1. Step one.
2. Step two.
3. Step three.

## Test plan

Unit tests:
- What unit behavior should be covered.

Integration tests:
- What integration behavior should be covered, if relevant.

Manual or smoke validation:
- Any lightweight manual check, if relevant.

## Risks

- Known risk 1
- Known risk 2

## Validation commands

```bash
# Fill in actual commands discovered in the repo
````

## Completion notes

Filled in after implementation:

* Summary of what changed.
* Tests run.
* Known limitations.
* Follow-up work for later phases.

````

---

## Prompt: Phase Assignment

Create `.codex/prompts/phase-assignment.md`.

Use this when assigning a phase to an implementation subagent.

```md
You are an autonomous implementation agent for this repository.

You are assigned one phase from a larger implementation plan.
This prompt is intended for the `loom_phase_implementer` custom agent.

Inputs:

- Full implementation plan: `docs/implementation-plan.md`
- Assigned phase: `<PHASE_ID_OR_TITLE>`
- Required branch name: `codex/<summary-of-feature>`

Your task:

1. Read the full implementation plan.
2. Locate the assigned phase.
3. Create a separate git worktree for this phase.
4. Create and switch to the required feature branch inside that worktree.
5. Create an expanded phase plan in `docs/phases/`.
6. Implement the phase.
7. Add or update relevant tests.
8. Run relevant validation commands.
9. Refine the implementation based on test failures.
10. Update the expanded phase plan with completion notes.
11. Prepare a PR.

Worktree requirement:

```bash
git fetch origin
BRANCH="codex/<summary-of-feature>"
WORKTREE="../<repo-name>-codex-<summary-of-feature>"
git worktree add -b "$BRANCH" "$WORKTREE"
cd "$WORKTREE"
````

Rules:

* Do all work inside the separate worktree.
* Do not ask the user for feedback.
* Do not implement future phases.
* Do not make broad unrelated refactors.
* Make frequent commits at coherent checkpoints.
* If the plan is ambiguous, make the smallest reasonable assumption, document it, and continue.
* Stop after opening or preparing the PR.

````

---

## Prompt: Create Expanded Phase Plan

Create `.codex/prompts/create-phase-plan.md`.

```md
You are planning the assigned phase before implementation.

Read:

- `AGENTS.md`
- `docs/implementation-plan.md`
- The assigned phase

Create an expanded phase plan in `docs/phases/` using the repository’s phase plan template.

The phase plan must include:

1. Branch name using `codex/<summary-of-feature>`.
2. Worktree path.
3. Objective.
4. Full-plan context.
5. In-scope work.
6. Out-of-scope work.
7. Assumptions.
8. Files and areas to inspect.
9. Implementation steps.
10. Test plan.
11. Risks.
12. Validation commands.

Planning rules:

- Be specific enough that implementation can proceed without more user input.
- Do not expand the phase beyond its stated scope.
- Identify future-phase work and explicitly keep it out of scope.
- Prefer a plan that produces a small, reviewable PR.
- Commit the phase plan from inside the worktree with:

```bash
git commit -m "plan: add phase plan"
````

````

---

## Prompt: Implement Phase

Create `.codex/prompts/implement-phase.md`.

```md
You are implementing the assigned phase.

Read:

- `AGENTS.md`
- `docs/implementation-plan.md`
- The expanded phase plan in `docs/phases/`

Task:

1. Confirm you are inside the dedicated git worktree for this phase.
2. Inspect the files identified in the phase plan.
3. Implement the phase step by step.
4. Add or update tests as described in the phase plan.
5. Keep changes limited to the phase scope.
6. Make frequent commits after coherent units of work.
7. Run relevant validation commands.
8. Record results in the phase plan completion notes.

Commit guidance:

- Commit the implementation after meaningful checkpoints.
- Commit tests separately when practical.
- Use clear commit messages.

Examples:

```bash
git commit -m "feat: implement core behavior"
git commit -m "test: add phase coverage"
````

Rules:

* Do not ask the user for feedback.
* Do not implement future phases.
* Do not rewrite unrelated code.
* Do not hide failing tests.
* Do not remove tests just to make the suite pass.
* If a validation command is unavailable, document that in the phase plan and PR body.

````

---

## Prompt: Refine From Tests

Create `.codex/prompts/refine-from-tests.md`.

```md
You are refining the current phase implementation based on validation results.

Read:

- `AGENTS.md`
- The expanded phase plan in `docs/phases/`
- The current diff
- Test and validation output

Task:

1. Confirm you are inside the dedicated git worktree for this phase.
2. Identify failing tests, lint errors, type errors, build errors, or obvious runtime problems.
3. Determine whether each failure is caused by the current phase.
4. Fix failures caused by the current phase.
5. Add regression coverage when useful.
6. Re-run the relevant validation commands.
7. Update the phase plan completion notes.
8. Commit refinements.

Rules:

- Fix blocking issues only.
- Do not expand the phase scope.
- Do not implement later phases.
- Do not paper over failures.
- Do not weaken tests unless the test is clearly obsolete because of the intended phase behavior; if so, explain why.

Use commit messages like:

```bash
git commit -m "fix: refine after validation"
````

````

---

## Prompt: Create PR

Create `.codex/prompts/create-pr.md`.

```md
You are preparing the PR for the completed phase.

Read:

- `AGENTS.md`
- `docs/implementation-plan.md`
- The expanded phase plan in `docs/phases/`
- The current diff
- Validation results

Task:

1. Confirm you are inside the dedicated git worktree for this phase.
2. Confirm the branch name follows `codex/<summary-of-feature>`.
3. Confirm the implementation matches the assigned phase.
4. Confirm future phases were not implemented early.
5. Confirm relevant tests were added or updated.
6. Confirm validation commands were run or explain why not.
7. Update `docs/implementation-plan.md` phase status to `pr_open` without overwriting unrelated plan content.
8. Ensure the expanded phase plan has completion notes.
9. Create a PR body using `.github/PULL_REQUEST_TEMPLATE.md`.
10. Open the PR if GitHub tooling is available. Otherwise, leave the PR body ready to use.

Do not merge.
````

---

## Pull Request Template

Create or update `.github/PULL_REQUEST_TEMPLATE.md`.

If the repository already has a PR template, do not replace it. Add the missing phase-related fields in the smallest compatible way.

````md
## Phase

- Phase:
- Branch:
- Worktree:
- Plan:
- Expanded phase plan:

## Summary

Describe what this PR implements.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Implementation notes

Describe important implementation choices, assumptions, or tradeoffs.

## Tests and validation

List commands run and results.

```text
command:
result:
````

If a command could not be run, explain why.

## Scope control

* [ ] Implements only the assigned phase.
* [ ] Does not implement future phases early.
* [ ] Does not include unrelated refactors.

## Risks / follow-ups

List known risks, limitations, or follow-up work for later phases.

````

---

## Prompt: Managing Agent Phase Loop

Create `.codex/prompts/manage-phase-loop.md`.

This prompt is for the managing agent that coordinates sequential phases.

```md
You are the managing agent for a multi-phase implementation plan.

Read:

- `AGENTS.md`
- `docs/implementation-plan.md`
- Existing phase plans in `docs/phases/`
- Open PRs and CI/test results if available

Your job is to advance the implementation plan one phase at a time.

For each phase:

1. Find the next phase with `Status: pending` whose earlier phases are complete, approved, or merged.
2. If additional codebase context is useful and can run in parallel, use the `loom_architecture_explorer` custom agent for read-only mapping.
3. Assign that phase to the `loom_phase_implementer` custom agent using `.codex/prompts/phase-assignment.md`.
4. Require the subagent to create a separate worktree, create a branch, write an expanded phase plan, implement, test, refine, and prepare a PR.
5. Review the PR with the `loom_phase_reviewer` custom agent using `.codex/prompts/review-phase-pr.md` when subagents are explicitly requested or available. Otherwise perform the same review locally.
6. Review the PR against:
   - The original implementation plan.
   - The expanded phase plan.
   - The PR explanation.
   - The diff.
   - Unit test and validation results.
7. Approve the PR only if:
   - The explanation matches the implementation.
   - The assigned phase acceptance criteria are satisfied.
   - Relevant tests pass.
   - The scope is limited to the assigned phase.
   - No future phase was implemented early.
   - No obvious maintainability or regression issue remains.
8. If the PR is not acceptable, ask the `loom_phase_implementer` to refine using `.codex/prompts/refine-from-tests.md` or leave a concise blocking review.
9. If the PR is acceptable, approve it.
10. Update `docs/implementation-plan.md` without overwriting unrelated plan content. Record:
   - Phase status.
   - PR link or branch name.
   - Short implementation summary.
   - Test results summary.
   - Follow-up notes for later phases.
11. Move to the next pending phase.
12. Stop when all phases are complete, approved, merged, or blocked.

Rules:

- Do not merge directly unless explicitly configured to do so by repository owners.
- Do not skip phases unless the plan explicitly allows it.
- Do not approve a PR just because tests pass; the explanation must match the diff and the phase plan.
- Do not require exhaustive test coverage unless the phase warrants it.
- Prefer forward progress with small PRs over large perfect changes.
- Project custom agents are configured in `.codex/agents/`.
````

---

## Managing Agent Approval Checklist

The managing agent should use this checklist before approval:

```md
# Managing Agent Approval Checklist

## Plan match

- [ ] PR corresponds to the assigned phase.
- [ ] PR branch follows `codex/<summary-of-feature>`.
- [ ] PR was implemented in a separate worktree.
- [ ] PR does not include future phase work.
- [ ] Expanded phase plan exists.
- [ ] PR body accurately summarizes the implementation.

## Implementation quality

- [ ] Acceptance criteria are satisfied.
- [ ] Implementation is reasonably simple.
- [ ] No broad unrelated refactor.
- [ ] No obvious maintainability regression.

## Tests

- [ ] Relevant unit tests were added or updated.
- [ ] Relevant validation commands were run.
- [ ] Test results are included in the PR body.
- [ ] Failures are fixed or clearly explained.

## Plan update

- [ ] `docs/implementation-plan.md` phase status is updated.
- [ ] Summary of completed work is recorded.
- [ ] Follow-up notes are captured for later phases.
```

---

## Context Compaction Rules

Agents should keep context compact as the phase progresses.

When handing work from one subagent to another, include only:

```text
- Assigned phase title
- Branch name
- Worktree path
- Link/path to full implementation plan
- Path to expanded phase plan
- Current status
- Files changed
- Commands run and results
- Failing tests or blocking issues
- Assumptions made
- Remaining tasks
```

Do not pass the entire conversation history unless necessary. The durable source of truth should be the repository files:

```text
docs/implementation-plan.md
docs/phases/<phase>.md
PR body
commit history
CI output
```

---

## Single-Phase Assignment Template

Use this when manually asking Codex to implement a phase:

```md
Implement one phase of the larger plan autonomously.

Full plan: `docs/implementation-plan.md`
Assigned phase: `<PHASE_ID_OR_TITLE>`
Required branch: `codex/<summary-of-feature>`
Required worktree: `../<repo-name>-codex-<summary-of-feature>`

Follow the repository workflow:

1. Read the full implementation plan.
2. Create a separate git worktree.
3. Create and switch to the required branch inside that worktree.
4. Create an expanded phase plan in `docs/phases/`.
5. Commit the phase plan.
6. Implement the phase only.
7. Add or update relevant tests.
8. Commit coherent units of work frequently.
9. Run validation commands.
10. Refine based on test failures.
11. Update phase plan completion notes.
12. Update the implementation plan status to `pr_open` without overwriting unrelated content.
13. Prepare or open a PR using the PR template.

Do not ask for feedback during implementation.
If ambiguous, make the smallest reasonable assumption, document it, and continue.
Do not merge.
```

---

## Setup Instruction for Codex

Use this prompt to ask Codex to set up the workflow in a repository:

```md
Set up a simplified Codex workflow for implementing one phase of a larger implementation plan autonomously.

Create or update these files:

- `AGENTS.md`
- `docs/implementation-plan.md`
- `docs/phases/.gitkeep`
- `.codex/config.toml`
- `.codex/agents/loom-phase-implementer.toml`
- `.codex/agents/loom-phase-reviewer.toml`
- `.codex/agents/loom-architecture-explorer.toml`
- `.codex/plans/workflow.md`
- `.codex/prompts/convert-plan-to-phases.md`
- `.codex/prompts/phase-assignment.md`
- `.codex/prompts/create-phase-plan.md`
- `.codex/prompts/implement-phase.md`
- `.codex/prompts/refine-from-tests.md`
- `.codex/prompts/create-pr.md`
- `.codex/prompts/review-phase-pr.md`
- `.codex/prompts/manage-phase-loop.md`
- `.github/PULL_REQUEST_TEMPLATE.md`

Non-destructive setup requirements:

- Inspect existing files first.
- Do not overwrite `AGENTS.md`; add only missing guidance needed for this workflow.
- Do not overwrite an existing implementation plan; align it or add a phased implementation section.
- Do not overwrite an existing PR template; add missing phase-related fields only if needed.
- Do not replace existing CI or project commands.
- Preserve existing project-specific instructions over generic workflow text.

The workflow should support this loop:

1. Agent receives a full implementation plan and one assigned phase.
2. Agent creates a separate worktree.
3. Agent creates a feature branch using `codex/<summary-of-feature>`.
4. Agent creates an expanded phase plan in `docs/phases/`.
5. Agent implements the phase with frequent commits.
6. Agent adds or updates tests.
7. Agent validates through tests and relevant checks.
8. Agent refines based on failures.
9. Agent prepares or opens a PR.
10. Managing agent approves only if tests pass and the PR explanation matches the implementation.
11. Managing agent updates the implementation plan and starts the next phase.

Keep the setup lightweight. Do not add complex schemas, dashboards, comprehensive test matrices, or fully autonomous merging.
```

---

## What Not to Add Yet

Do not add these at this stage:

* Complex machine-readable schemas.
* Large multi-agent frameworks.
* Fully autonomous merge to main.
* Extensive test matrices.
* Dashboards.
* Heavy ADR requirements.
* Automatic phase execution on every push.
* Mandatory exhaustive coverage thresholds.

The workflow should remain small enough that it increases implementation speed rather than becoming a second project.
