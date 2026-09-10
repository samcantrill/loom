---
name: loom-process-improvement
description: Capture and promote recurring Loom failures or demonstrated shared weaknesses into reusable workflow, design, contract, skill, or tooling improvements. Use for retrospectives and systemic improvements, not as a technical blocker or incident tracker.
---

# Loom Process Improvement

Use `docs/improvement-log.md` as the cross-workflow pattern and promotion queue.
Source/tests, stage artifacts, PRs, and validation evidence retain ownership of
immediate technical state and acceptance.

1. Admit an entry only for recurrence, a problem crossing multiple supported
   consumers/boundaries, or a demonstrated missing shared rule. Severity or a
   long diagnosis alone does not qualify.
2. Search by reusable lesson and promotion owner before allocating `RI-###`.
   Consolidate examples of the same pattern under one entry.
3. Record concise evidence, the reusable lesson, one canonical promotion owner,
   the smallest useful action, verification trigger/evidence, and uncertainty.
   Do not copy diagnostic history or phase blocker state.
4. Choose the smallest owner: architecture/common contracts for shared design;
   `AGENTS.md` for repository invariants; workflows for gates; prompts/templates
   for handoffs; agent definitions for runtime authority; skills for routing;
   focused scripts/tests for mechanical checks. Do not duplicate procedures.
5. Use the log's states. Close only after realistic later use or a deterministic
   contract verifies the improvement, with its evidence recorded.

Read-only reviewers may return a candidate; the manager verifies admission and
writes the log. A local defect/regression fix alone stays with its normal owner.
Logging does not authorize an out-of-scope fix or add a product requirement.
