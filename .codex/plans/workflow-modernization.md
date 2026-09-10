# Loom Workflow Modernization

Status: refined stage isolation and delivery implemented; validation and delivery
facts are recorded in [the refinement plan](refined-stage-implementation.md).

## Current Shape

- Lean planning remains manager-local with bounded expanded reviews.
- Each implementation stage uses one persistent worktree and a coordination
  branch, with separate phase branches/PRs.
- Manager implementation is the default; execution delegation is optional.
- One independent review is required for every phase PR.
- The manager prompt owns sequencing; tools/phase_workflow.py owns mandatory
  repository, cwd/branch, merge and synchronization checks.
- Metadata is authored on coordination and published before continuation;
  local develop only fast-forwards. There is no local continuation fallback.
- Existing Loom validation gates, compact manifests, phase cards, pointer-only
  handoffs and no-sidecar rules remain authoritative.
- Other unfinished legacy stages are audited only when resumed. Completed
  history and unrelated code-intelligence work remain outside this change.
