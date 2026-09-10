# Loom Phase Loop Management

You are the manager executing one approved Loom implementation manifest.
Read AGENTS.md, the implementation workflow, subagent-lifecycle.md, the selected
manifest and current phase card with exact referenced contracts. Use current
source/test evidence and immediate predecessor merge facts, not whole history.

## Stage Isolation And Shared Git Gate

All stage work uses one persistent stage-<N> worktree: startup review/corrections,
artifacts, implementation, tests, metadata and closeout. Each phase has branch
agent/stage-<N>-p<P>-<phase-slug> and a PR to develop. agent/stage-<N> is the named
coordination branch for post-merge metadata in that worktree. Never edit or
commit local develop. Control access is limited to read-only inspection,
worktree administration and clean fast-forward synchronization.

tools/phase_workflow.py owns mechanical checks. Use Python 3.12 and each command's
--help. Record the clean control path and worktree root once in the manifest;
pass them explicitly as --root and --worktree-root. The tool verifies origin is
samcantrill/loom and the actual stage cwd shares the control Git repository.
Do not replace a failed gate with an unchecked manual bypass. It is an admission
check, not a sandbox against later arbitrary shell commands. The manager owns
phase order, dependency completeness, metadata contents and review judgment.

For command examples below, LOOM_CONTROL and LOOM_WORKTREE_ROOT contain the
manifest paths; LOOM_STAGE, LOOM_PHASE, LOOM_BRANCH and LOOM_BASE contain the
selected stage, canonical phase suffix, full branch and fetched approved SHA.
LOOM_COORDINATION is agent/stage-<N>. Supply actual values, not placeholders.

1. Discover the registered worktrees and origin. Select a clean control checkout
   on develop, or create a linked control checkout if develop/path are available
   and can fast-forward. Preserve unrelated dirty checkouts; never reset or
   repurpose an occupied path/branch. Confirm authorization and approved packet
   paths are published, then run from control before startup review or writes:

   ```bash
   python3.12 tools/phase_workflow.py setup \
     --root "$LOOM_CONTROL" --worktree-root "$LOOM_WORKTREE_ROOT" \
     --stage "$LOOM_STAGE" --phase "$LOOM_PHASE" --base "$LOOM_BASE"
   ```

   Add repeated --dependency arguments for required full merge SHAs. Enter the
   returned worktree immediately. Setup creates the phase and coordination
   branches. Occupied or partially created state must be inspected and resumed
   with preflight; do not recreate it by resetting. Verify the coordination ref
   and published base after partial startup. Startup receipts join the phase PR.
2. Before every assignment or manager write/test/review pass, run in the stage:

   ```bash
   python3.12 tools/phase_workflow.py preflight \
     --root "$LOOM_CONTROL" --worktree-root "$LOOM_WORKTREE_ROOT" \
     --stage "$LOOM_STAGE" --branch "$LOOM_BRANCH"
   ```

   Check reported edits belong to the task. Pass verified cwd/branch, evidence
   revision and absolute artifact paths to agents. Supporting prompts consume
   that handoff and do not create another Git procedure.
3. Finish or stop all agents/background processes before changing branches.
   After delivery verifies remote merge, run transition with the merged PR:

   ```bash
   python3.12 tools/phase_workflow.py transition \
     --root "$LOOM_CONTROL" --worktree-root "$LOOM_WORKTREE_ROOT" \
     --stage "$LOOM_STAGE" --phase "$LOOM_PHASE" --pr "$LOOM_PR"
   ```

   It requires clean work, the correct remotely merged PR/head and merge
   ancestry, switches to coordination and fast-forwards published state and
   local develop. Extra phase commits and unrelated edits are preserved and
   block transition. Squash-merged phase branches are not reset to develop.
4. On coordination, use preflight with LOOM_BRANCH set to LOOM_COORDINATION,
   record/commit required phase metadata and final closeout when applicable.
   Publish with git push origin HEAD:refs/heads/develop. No force push or local
   develop edits. If remote advanced, reconcile only unpublished metadata onto
   the new base, inspect and retry. Failed publication retains the named branch
   and stops continuation; an inter-phase docs-only PR is not a substitute.
5. After metadata publication, including interrupted or final closeout, run:

   ```bash
   python3.12 tools/phase_workflow.py sync \
     --root "$LOOM_CONTROL" --worktree-root "$LOOM_WORKTREE_ROOT" \
     --stage "$LOOM_STAGE"
   ```

   Stage HEAD, local develop, fetched origin/develop and advertised remote
   develop must match. Dirty/divergent/unpublished work or remote advancement
   stops the gate. Reconcile then retry; do not manufacture a self-referential
   SHA receipt. Record returned facts in the existing handoff.
6. After synchronization and verified phase-branch retirement, start the next
   selected phase in the same worktree. LOOM_PHASE is now the next phase suffix;
   LOOM_PREVIOUS_BRANCH and LOOM_PR identify the merged predecessor:

   ```bash
   python3.12 tools/phase_workflow.py start \
     --root "$LOOM_CONTROL" --worktree-root "$LOOM_WORKTREE_ROOT" \
     --stage "$LOOM_STAGE" --phase "$LOOM_PHASE" \
     --pr "$LOOM_PR" --previous-branch "$LOOM_PREVIOUS_BRANCH"
   ```

   This repeats predecessor and synchronization checks before creating the fresh
   branch. Equality applies between phases; active implementation differs from
   develop. A blocked predecessor does not authorize continuation. There is no
   local-continuation exception while a remote merge remains unverified.

## Phase Identity

The manifest's approved Stage descriptor and the phase-card heading own PR
identity. Use `Stage <N> <Stage-Descriptor> - Phase <P>: <Phase-Descriptor>`.
Record that exact title in the card and use it for PR creation, review, and the
delivery gate. For a resumed manifest missing the descriptor, derive it from
the accepted roadmap heading and record it during stage startup; ask only when
no unambiguous accepted descriptor exists. Do not rename branches to match titles.

## Startup And Per-Phase Procedure

1. Verify the exact approved packet paths are published on the selected base.
   Reuse the manifest's Implementation Plan Review receipt (Quality Gate for
   grandfathered packets). Compare relevant source/contracts with its evidence
   revision; unrelated changes or layout metadata do not invalidate it. Missing
   review or material drift gets one bounded loom_plan_reviewer pass/correction,
   not a new full planning loop. Do not fabricate missing historical review SHAs.
2. Prepare the existing phase card using phase-execution-plan-draft.md. Record
   execution facts and current references without reopening fixed contracts.
3. Implement manager-locally using implementation-phase-execution.md. Delegate to
   one loom_phase_executor only when size/context isolation justifies it.
   Named uncertainty may use one loom_phase_planner; a qualified blocker may
   use one loom_phase_refiner. Use pointer-only handoffs and no child delegation.
4. Use `$loom-targeted-validation` for selected checks and expansion triggers,
   then run the recorded final gates when stable. Preserve approved obligations.
   Reuse fresh evidence. Record changed paths, selectors, validated tree,
   skipped/unavailable cases and residual risks in the existing phase card.
5. Prepare the PR manager-locally with pr-body-draft.md. Resolve blockers within
   budget before submission. Push/open with explicit repository, head, develop
   base and canonical title, then verify those fields and the actual diff.
6. Spawn one independent loom_phase_reviewer using pull-request-review.md after
   the PR exists. It reviews the actual head and current evidence. Record its
   reviewed SHA and findings in the PR or phase record. Affected corrections
   return to the same reviewer within budget; do not claim manager self-review
   is independent or start another review loop.
7. Deliver the current reviewed head using the gate below. Then follow shared
   transition, metadata publication and synchronization before the next phase.

## Delivery

Run deliver from the stage worktree, supplying explicit PR identity and existing
nonempty evidence (phase card or PR summary). LOOM_REVIEWED_HEAD is the current
independently reviewed head; LOOM_VALIDATED_HEAD is the head to which local
validation was reconciled. Inspect metadata-only deltas; relevant changes need
fresh affected checks and independent review of corrections.

```bash
python3.12 tools/phase_workflow.py deliver \
     --root "$LOOM_CONTROL" --worktree-root "$LOOM_WORKTREE_ROOT" \
     --stage "$LOOM_STAGE" --pr "$LOOM_PR" --branch "$LOOM_BRANCH" \
     --title "$LOOM_TITLE" --reviewed-head "$LOOM_REVIEWED_HEAD" \
     --validated-head "$LOOM_VALIDATED_HEAD" --evidence-file "$LOOM_EVIDENCE" \
     --review-approved --local-validation-passed
```

Flags attest to manager acceptance judgment; the helper cannot infer coverage
from prose. It requires clean matching local HEAD, explicit live PR identity,
non-draft/mergeable state, then squash-merges with --match-head-commit. It rechecks
remote state even after command failure. Never infer merge from CLI success.
Remote branch retirement is leased to the reviewed SHA; moved/unknown refs stay
preserved. The tool does not delete local branches or worktrees.

If GitHub rejects delivery, inspect the specific protection/authorization rule.
Do not enable CI, bypass failing checks or automatically add --admin. Only the
AGENTS.md review-only protection exception permits a manually verified admin
merge with the same reviewed head after all gates pass; rerun delivery to verify
remote outcome. Missing review requires a recorded maintainer override or stops.
No remote failure authorizes starting the next phase early.

## Findings, Budgets And Completion

Use the AGENTS.md correction budget: at most three scoped corrections per phase,
including at most one refiner. Each needs a qualified blocker and concrete remedy.
Optional hardening does not widen scope. Review confirmations remain within the
existing independent pass; do not restart budgets or relabel exhausted blockers.

After each synchronized merge, retire only exact phase branches whose local head
matches the merged PR head and whose merge is in published develop. Preserve
extra commits or unknown remote refs; squash history alone is not ancestry proof.
Keep the stage path and coordination branch through final metadata publication
and sync. At stage closeout, verify all phase dispositions, required evidence and
exact branch/worktree ownership. Remove the clean stage worktree from outside
it and delete only verified published refs. Do not edit local develop to record
cleanup. Report actual cleanup in the handoff; unknown/unmerged work blocks
completion. No wildcard/prefix cleanup or new lifecycle sidecars.

Disposition relevant reusable improvement entries with `$loom-process-improvement`
in the existing phase/manifest state; technical blockers stay at their owner.
Optional terminal compaction follows the planning workflow, using verified facts
and the same stage publication/synchronization gate when selected before cleanup.
