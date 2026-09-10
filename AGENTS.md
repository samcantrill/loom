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

Use `$loom-targeted-validation` for behavior changes and coverage planning.
Select checks by affected contracts and consumers. Bounded changes need selected
tests and applicable static checks; wider changes need affected suites. Use
`make validate-pr` for broad/unbounded impact or explicitly required gates.
Ordinary prose changes normally need diff and affected documentation checks.

Preserve approved phase obligations until deliberately revised with rationale
at their owner. This includes both `make validate-pr` and `make test-summary`
where existing cards require them. Summary targets execute tests again; use them
when explicitly required or when their report is needed, not as an automatic
second run. tests/README.md owns commands and environments.

Record selections, validated revision/tree, results, skipped/unavailable cases,
and subsequent relevant changes. Reuse fresh evidence across handoffs. Repeat
or expand only for relevant changes, failures, missing evidence, or unresolved
risk. Never present a subset or skipped physical acceptance as full coverage.

## Workflow Layers

- .agents/skills owns intent routing and reusable selection guidance.
- .codex/workflows owns entry conditions, sequencing, gates, and manager choices.
- .codex/prompts owns bounded task procedures.
- .codex/agents owns model, sandbox, and stable role authority.
- .codex/templates owns durable artifact shape.
- .codex/plans owns reusable project-scoped workflow plans.
- docs/improvement-log.md owns reusable pattern evidence and promotion state.

Do not duplicate full procedures across these layers.

## Lean Subagent Policy

Manager-local work is the default.

A normal planning workflow uses manager authorship and one independent
loom_plan_reviewer of the complete packet. A normal implementation phase uses
manager implementation and one independent loom_phase_reviewer. Delegate execution
to loom_phase_executor only when size or context isolation justifies it. Other
roles require a named unresolved question or qualified blocker.

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

Use `$loom-roadmap-planning`, which routes to
.codex/workflows/roadmap-stage-planning.md. The workflow owns complete drafting,
independent final review, maintainer approval, and landing before implementation.
Functionality and design prompts are authoring guidance, not intermediate
approval gates. Ask about material product choices; resolve repository-backed
mechanics locally and reuse existing approval when it applies.

Planning manifests route to coherent domain cards; implementation manifests own
phase order and readiness; execution cards own phase scope and evidence. Keep
one authoritative owner for each contract and ID. No word, phase-count, or slice
quota applies. Prefer independently mergeable outcomes with supported boundaries.
Keep producer, consumer, docs, and tests together when they establish one invariant.

Grandfather existing approved layouts and review receipts. Audit pending legacy
work when resumed without rewriting completed history. Planning does not execute
product phases. Optional terminal compaction belongs to planning and consumes
verified implementation facts; it is not a product-completion requirement.

## Phase Implementation

Use `$loom-roadmap-implementation`, which routes to
.codex/workflows/roadmap-stage-implementation.md, and follow
.codex/prompts/phase-loop-management.md.

Every stage uses one persistent worktree, including startup review, code/tests,
metadata and closeout. Each phase keeps branch agent/stage-<N>-p<P>-<phase-slug>
and one PR targeting develop. The named agent/stage-<N> coordination branch owns
post-merge metadata and closeout in that same worktree.

Record the clean control checkout, worktree root and stage path once in the
manifest. Preserve unrelated checkouts. Bootstrap before startup review or any
writes. The manager prompt owns the mandatory tools/phase_workflow.py Git gate;
use its verified cwd/branch before each assignment or manager write/test/review
pass. Never edit or commit local develop; only clean fast-forwards are allowed.

A later phase starts only after predecessor remote merge, published metadata and
matching stage/local/remote revisions. Routine stacked PRs and local continuation
before remote merge are not supported. Finish all agents/background processes
before a stage branch transition.

Normal phase path:

1. Manager verifies readiness in the stage worktree and prepares the phase plan.
2. Optional loom_phase_planner refinement for a named uncertainty.
3. Manager implementation and phase tests; optional loom_phase_executor.
4. Optional loom_phase_refiner for a qualified blocker.
5. Manager validation evidence, pre-submit gate and PR preparation.
6. One independent loom_phase_reviewer reviews the actual PR head.
7. Local-validation-gated automatic squash merge to develop.
8. Publish phase metadata on the coordination branch, synchronize, then continue.

Do not create new assignment, implementation handoff, PR-body, PR-review,
refinement, or merge-record sidecars. Record concise current state in the phase
execution plan and send the PR body directly to GitHub.

## Budgets And Findings

- Plan review: one required independent final pass; manager correction and at
  most one targeted confirmation for substantive changes (one runtime replacement
  if unavailable). Optional named design help does not replace this review.
- Phase planning: manager preparation; at most one refinement for a named
  unresolved question.
- Implementation: manager-local; at most one executor when justified.
- Implementation refinement: at most one refiner for a qualified blocker.
- Phase PR review: one required independent reviewer; affected corrections
  return to that reviewer within the existing correction budget.
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
- the required independent phase review has no blocker; and
- the PR body matches the diff and tests.

Hosted CI is intentionally disabled; do not wait for or require GitHub-hosted
checks. Do not wait for human GitHub approval. Use admin merge only for a
review-only protection rule after local validation and review pass. Never bypass
failing local validation, a wrong target, conflicts, or known blockers.

After merge, use the manager's transition gate, record concise metadata on the
coordination branch and publish to develop when permitted, then synchronize.
Retire only verified merged phase branches. Retain the stage worktree and
coordination branch until final closeout is published and synchronized. Never
reset or discard unrelated work. A missing required independent review needs an
explicit recorded maintainer override with accepted risk; manager review alone
is not independent. Ordinary non-phase work retains proportionate review.

Hosted-check or protection rejections must be inspected and reported. The narrow
review-only admin exception never bypasses failing checks or known blockers.

Use only these phase statuses:

    pending
    in_progress
    pr_open
    approved
    merged
    blocked

## Definition Of Done

Planning is ready when accepted contracts, proportionality, validation, phase
boundaries, traceability, and independent readiness review have no blocker, the
maintainer has approved the concrete packet, and the exact artifacts are landed
and available on the selected implementation base.

A phase is done when its implementation and tests match the phase plan,
validation and review gates pass, its PR is remotely merged into develop,
metadata is published, and the synchronization gate passes. A stage is done
only after final closeout is published and exact stage cleanup is verified;
unresolved dirty, unknown or unmerged work blocks completion.

## Process Improvement

Use `$loom-process-improvement` for recurring or demonstrated shared workflow,
design, contract, skill, or tooling weaknesses. The improvement log records the
reusable lesson, one promotion owner, action, and verification. Technical defects
and phase acceptance stay with their immediate owner. Logging adds no phase
scope or delivery gate.
