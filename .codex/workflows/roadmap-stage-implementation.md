# Roadmap Stage Implementation

## Goal And Preconditions

Execute an approved Loom stage in one persistent worktree, with separate phase
branches/PRs, local validation, independent review, merge and synchronized
closeout. Keep accepted behavior and private implementation discretion intact.

Read AGENTS.md, .codex/prompts/subagent-lifecycle.md,
.codex/prompts/phase-loop-management.md, the selected manifest and current phase
card plus exact referenced contracts. Do not preload unrelated planning history.
Require recorded approval, current readiness, consistent manifest/card scope and
known control/origin/develop state. Reuse current plan reviews; only missing
review or relevant contract drift requires a bounded independent plan pass.

Bootstrap the stage worktree before startup review or writes. Record control,
worktree root, stage path and coordination branch in the manifest. The manager
prompt owns the mandatory shared Git gate. Local develop only fast-forwards;
all metadata is authored on the coordination branch. No later phase starts
before remote merge, published metadata and synchronization.

## Roles

Manager-local implementation is the default. Use one loom_phase_executor only
when size/context isolation justifies delegation. A named uncertainty may use
loom_phase_planner and a qualified blocker may use loom_phase_refiner. Every
phase requires one independent loom_phase_reviewer of the actual PR head.
Specialists do not author and approve the same work. Agent definitions own model
and authority; the manager prompt owns the procedure and correction budgets.

## Validation And Merge

Preserve the phase's targeted checks and required make validate-pr and
make test-summary gates. Record selectors, results, skipped/unavailable cases,
validated revision/tree and relevant subsequent changes in the phase card.
Reuse fresh evidence; relevant changes require affected checks. Physical
container/fleet/Slurm qualification remains distinct from local fixtures.

Hosted CI is disabled. Do not enable or wait for it. Merge requires accepted
scope, passing required local evidence, independent review, the correct live
PR/head/target/title and mergeability. The helper verifies Git/GitHub facts;
the manager judges coverage and acceptance. Inspect protection rejections;
AGENTS.md's narrow review-only admin exception is not an automatic fallback.

## Completion And Stops

Follow .codex/prompts/phase-loop-management.md. Stop for broken isolation, failed
validation, missing required review, unverified merges, unpublished metadata,
dirty/divergent control state or ambiguous accepted contracts. Preserve work.

A phase needs remote merge, published metadata and synchronized revisions. Keep
the stage worktree through final closeout. Remove only exact verified worktrees
and branches after publication and synchronization. Unknown/unmerged work blocks
completion. Do not add lifecycle sidecars or rewrite historical plans.
