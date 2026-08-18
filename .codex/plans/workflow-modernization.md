# Loom Workflow Modernization

Status: core lean conversion applied; validation not run

## Goal

Adopt the useful RPhys workflow improvements while reducing context, artifacts,
and routine subagent cost.

## Applied Shape

- Manager-local roadmap planning on the lean path.
- Zero normal planning spawns.
- One normal phase spawn: loom_phase_executor.
- Optional design reviewer, phase planner, refiner, plan reviewer, and PR
  reviewer only for a named expanded risk or qualified blocker.
- fork_turns=none and pointer-only handoffs.
- Current-state planning, compact manifest, and one phase execution plan per
  phase.
- No new assignment, PR-body, review, refinement, or merge sidecars.
- Direct-to-develop phase PRs with no routine stack.
- Current Loom validation commands retained.
- Legacy paths remain as small compatibility stubs.

## Follow-Ups

1. Run reference and repository validation.
2. Audit legacy pr_open roadmap metadata before resuming an old plan.
3. Decide whether to consolidate suite evidence into make validate-pr.
4. Consider optional Loom code intelligence separately.
5. Dry-run planning on the next unstarted roadmap stage before product execution.
