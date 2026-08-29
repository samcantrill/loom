# Agent Guide

This repository contains Loom, a generic Python runtime for composing, running,
and tracing reproducible research pipelines.

## Repository Rules

- Keep Loom domain-neutral.
- Follow docs/structure.md for source ownership and import direction.
- Use docs/GLOSSARY.md for repository vocabulary.
- Treat authored configs as trusted project code.
- Keep public imports intentional, typed, and cheap.
- Do not add heavyweight runtime dependencies without a current design reason.
- Preserve unrelated work and never rewrite user changes to simplify a task.

## Design And Validation

Implement the smallest maintainable behavior that satisfies current accepted
requirements.

- Start from the existing end-to-end path.
- Add a public surface, shared abstraction, durable artifact, state, or schema
  only for a current consumer, accepted requirement, real boundary, or
  demonstrated failure.
- Future reuse preserves room for change; it does not justify current machinery.
- Give each invariant one authoritative owner.
- Revalidate at public, serialization/process, filesystem, external dependency,
  or mutable concurrency boundaries only when a reachable invalid producer has
  a material consequence.
- Use a Cartesian test matrix only when dimensions causally interact.
- Keep observable behavior, durable formats, trust boundaries, reproducibility,
  and cross-phase contracts explicit.
- Leave private helpers, local wiring, and intermediate representations to the
  implementer.
- Review cannot invent new acceptance criteria. Classify speculative resilience
  as optional hardening and defer it.

Relevant Loom contracts include pipeline graph behavior, planner actions,
lifecycle status, authored and composed config, artifact and run identity,
serialization, authority and store ownership, provenance, resume, execution,
diagnostics, failure behavior, dependency direction, and public imports.

## Local Checks

Use:

    make validate-pr
    make test-summary

make validate-pr is the implementation gate. make test-summary writes
build/test-summary.md for PR evidence. Reuse a successful receipt only while no
source, test, dependency, build, or validation configuration change has made it
stale.

## Workflow Layers

- .codex/workflows owns entry conditions, sequencing, gates, and manager choices.
- .codex/prompts owns bounded task procedures.
- .codex/agents owns model, sandbox, and stable role authority.
- .codex/templates owns durable artifact shape.
- .codex/plans owns reusable project-scoped workflow plans.

Do not duplicate full procedures across these layers.

## Lean Subagent Policy

Manager-local work is the default.

A normal planning workflow uses no subagent. A normal implementation phase uses
one spawned loom_phase_executor. Spawn another role only when the workflow names
a concrete expanded-path risk, independent-review need, or qualified blocker.

- Use fork_turns=none for every workflow subagent.
- Hand off paths and exact headings, not conversation history, prompt bodies,
  diffs, logs, or copied artifact content.
- Give one bounded task, one write boundary, one expected result, and explicit
  stop conditions.
- Do not ask children to report progress unless blocked.
- Use event-driven maximum-duration waits rather than polling, heartbeats, or
  list-agents checks.
- Verify the returned artifact or finding before advancing.
- Reuse a healthy agent only for one directly related repair; otherwise stop.
- Every custom agent must not delegate or spawn children.
- Use loom_architecture_explorer only for a specific codebase question whose
  answer would materially reduce direct exploration.

Keep durable pass receipts to a result and status. Record runtime IDs, wait
history, and fallback mechanics only when an anomaly affects the gate.

## Roadmap Planning

Start with .codex/workflows/roadmap-stage-planning.md.

Durable artifacts:

- docs/roadmap/stage-<N>/planning.md
- docs/roadmap/stage-<N>/implementation-plan.md
- docs/roadmap/stage-<N>/phases/<phase-slug>.md

planning.md is current authoritative state, not a transcript. Update sections in
place and use Git history for superseded wording. Target 1,500-3,500 words unless
irreducible contract detail requires more.

Use the lean route unless current evidence shows a novel or unresolved public,
durable, trust-boundary, cross-owner, irreversible migration, or causally
interacting validation decision with material consequences.

Lean planning is manager-local:

1. Evidence, minimum useful outcome, requirements, and functionality agreement.
2. Minimum design, complexity delta, design agreement, validation, and phase
   shaping.
3. Compact implementation manifest and phase execution plans.
4. Manager quality gate and maintainer approval.

On the expanded route, use at most:

- one loom_design_safety_reviewer pass for removal-first design implications;
- one loom_plan_reviewer pass when the manifest or linked phase plans need
  independent quality review; and
- one bounded correction for concrete findings.

Ask the maintainer only about ambiguous product, public-contract, durable,
compatibility, or material future-refactor choices. Ask one question at a time,
state the recommendation and tradeoff, record the answer, and continue. Resolve
repository-backed workflow mechanics locally.

Use the artifact layout marker manifest-and-phase-plans-v1. The implementation
plan is a compact manifest. Phase-specific detail belongs in one linked phase
execution plan. Prefer one to three vertical phases, with a recorded reason for
larger stage shapes.

Do not rewrite completed historical plans solely to use the current layout.
Audit a legacy plan with pending, pr_open, approved, or blocked phases before
resuming it.

## Phase Implementation

Start with .codex/workflows/roadmap-stage-implementation.md and follow
.codex/prompts/phase-loop-management.md.

Every phase uses:

- Branch: agent/stage-<N>-p<P>-<phase-slug>
- One dedicated worktree
- One PR targeting develop

Discover the control checkout and GitHub repository from the current
environment. The manager must record one worktree root. If none is provided,
use a loom-worktrees sibling of the control checkout. Do not repeat host-specific
absolute paths across prompts and templates.

Routine stacked PRs are not supported. A later phase starts after its predecessor
is remotely merged, explicitly blocked, or eligible for the narrow local
continuation fallback. Local continuation may support local work after a
transient remote-merge failure, but the next PR cannot open until the prior merge
lands and the next branch is based on current origin/develop.

Normal phase path:

1. Manager verifies the manifest and prepares the existing phase plan.
2. Optional loom_phase_planner refinement only for an expanded-path risk.
3. One loom_phase_executor implementation and phase-test pass.
4. Optional loom_phase_refiner only for a qualified blocker.
5. Manager-local validation evidence, pre-submit gate, and PR preparation.
6. Manager-local review on the fast path; optional independent
   loom_phase_reviewer on the expanded path or for a material residual risk.
7. Local-validation-gated automatic squash merge to develop.
8. Concise manifest/phase metadata update and cleanup.

Do not create new assignment, implementation handoff, PR-body, PR-review,
refinement, or merge-record sidecars. Record concise current state in the phase
execution plan and send the PR body directly to GitHub.

## Budgets And Findings

- Plan review: zero spawned passes on the lean path; one review and one bounded
  correction on the expanded path.
- Phase planning: zero spawned passes on the fast path; one refinement on the
  expanded path.
- Implementation: one executor.
- Implementation refinement: at most one refiner for a qualified blocker.
- PR review: manager-local on fast path; at most one spawned reviewer on
  expanded path.
- Blocker resolution: at most three total scoped corrections per phase,
  including any refiner pass.

A product blocker must name a supported reachable path, accepted contract or
repository invariant, material consequence, evidence, and smallest in-scope
fix. Optional hardening and future capability do not consume correction budget.

If the same blocker remains without a concrete new remedy, stop rather than
relabeling or respawning work.

## GitHub And Merge Policy

Use gh with explicit repository, base, head, and title values. Verify PR target
and title immediately after creation and again before merge.

Merge automatically when:

- base is exactly develop;
- the PR is not draft and is mergeable;
- scope matches the phase;
- required local validation passes with a fresh receipt;
- manager review or the required expanded review has no blocker; and
- the PR body matches the diff and tests.

Hosted CI is intentionally disabled; do not wait for or require GitHub-hosted
checks. Do not wait for human GitHub approval. Use admin merge only for a
review-only protection rule after local validation and review pass. Never bypass
failing local validation, a wrong target, conflicts, or known blockers.

After merge, safely update the control checkout, record concise status and
evidence, commit the metadata directly to develop when permitted, and remove the
worktree and branch. Never reset or discard unrelated work to update develop.

Use only these phase statuses:

    pending
    in_progress
    pr_open
    approved
    merged
    blocked

## Definition Of Done

Planning is ready when behavior and design agreements, proportionality,
validation, phase shaping, manifest/phase consistency, risks, and maintainer
approval are current with no unresolved blocker.

A phase is done when its implementation and tests match the phase plan,
validation and review gates pass, its PR is remotely merged into develop,
metadata is current, and cleanup is complete or explicitly blocked.
