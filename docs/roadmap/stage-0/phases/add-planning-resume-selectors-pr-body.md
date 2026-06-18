## Phase

- Phase: Phase 8 - Planning, Resume, And Selectors
- Branch: `codex/add-planning-resume-selectors`
- PR: https://github.com/samcantrill/loom/pull/12
- Target branch: `develop`
- Stack predecessor: none; Phase 7 has landed in `develop`
- Merge eligibility: root phase PR after stack maintenance; PR #12 targets `develop` and the recorded Phase 8 `from_stage` blocker has been fixed with validation rerun. Merge only after human approval and current checks; do not delete the branch while Phase 9 PR #13 depends on it.
- Worktree: `/home/samcantrill/work/loom-worktrees/add-planning-resume-selectors`
- Plan: `docs/roadmap/stage-0/implementation-plan.md`
- Phase execution plan: `docs/roadmap/stage-0/phases/add-planning-resume-selectors.md`
- Phase execution plan draft pass: complete
- Phase execution plan refine pass: complete
- PR body draft pass: complete
- PR body refine pass: complete
- PR open metadata: complete; verified base/head/state on 2026-05-04 local time

## Summary

Adds the Phase 8 planning layer without executing user stages. The PR turns the
`loom.pipeline.planning` skeleton into the public planning API for deterministic
stage fingerprints, selector normalization, same-run-directory resume checks,
topological execution plans, downstream invalidation, structured plan reasons,
and `RunStore.write_plan()` persistence.

The diff against `develop` adds the planning package implementation and focused
package, unit, and integration coverage. It does not add runner, executor, CLI,
remote-store, cross-run cache, target instantiation, or lifecycle behavior.

## Acceptance Criteria

- [x] Planner computes bound inputs and deterministic topological stage plans.
- [x] Selectors `force_stages`, `from_stage`, `only_stages`, and `skip_stages` affect plan decisions deterministically and record explanations.
- [x] Resume returns `REUSE` only for prior `SUCCEEDED` stages with matching fingerprints, required `outputs.json`, required output refs, existing artifacts, and successful checksum validation where supported.
- [x] Interrupted, corrupt, stale, failed, partial, or unverifiable prior state is never reusable.
- [x] Downstream invalidation propagates for changed fingerprints, selector decisions, skipped or blocked upstreams, pending upstream outputs, and unavailable upstream reuse providers.
- [x] Plan files can be persisted and read through the Phase 7 run store.
- [x] Public exports remain scoped to `loom.pipeline.planning`; root `loom` and `loom.pipeline` do not grow planning exports in this phase.

## Implementation Notes

The public API exports planning constants, errors, dataclasses, action/reason
enums, `build_stage_fingerprint()`, and `plan_pipeline()` from
`loom.pipeline.planning` only. The implementation keeps planning as a pure policy
layer over existing pipeline specs, graph helpers, status records,
`ArtifactRef`, and Phase 7 store protocols.

Fingerprints include deterministic semantic inputs such as stage name, target
path, stage config, output specs, bound input identities, Python version, loom
version, and explicit git/dependency/extra context. Noisy values and
`StageSpec.resources` are excluded from the default semantic fingerprint policy.

Planner decisions use `RUN`, `REUSE`, `SKIP`, `STALE`, and `BLOCKED` with
structured `PlanReason` entries. Stages with unavailable upstream reusable
inputs block clearly rather than implicitly widening `only_stages`; skipped or
blocked upstream data and control dependencies propagate downstream.

Plan persistence writes only the current plan through `RunStore.write_plan()`.
It does not write stage status, stage inputs, outputs, fingerprints, failures,
logs, lifecycle state, or runner-owned files.

Post-review blocker fix: `from_stage` now forces the selected stage to `RUN`
even when direct resume found valid reusable state. The selected stage preserves
its `REUSE` base action and fingerprint-match explanation, clears reusable
outputs for the forced rerun, records `FROM_STAGE_SELECTED`, and invalidates
downstream consumers with pending upstream-output reasons.

## Tests And Validation

Final validation evidence after the user-authorized post-review blocker fix:

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright passed with 0 errors, default pytest passed with 333 passed, and uv build produced source and wheel distributions.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; package 24 passed, unit 278 passed, contract 15 passed, integration 16 passed, and e2e was not present.
```

Focused blocker-fix evidence:

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning/test_planner.py tests/integration/pipeline/test_planning_resume.py -q
result: passed with 8 passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py tests/package/test_pipeline_planning_api.py -q
result: passed with 27 passed
```

Current GitHub check evidence after the blocker fix:

```text
command: gh pr view 12 --json statusCheckRollup,mergeStateStatus,isDraft
result: passed; PR is not draft, mergeStateStatus is CLEAN, and CI check "checks" completed with conclusion SUCCESS after the blocker-fix push.
```

Earlier targeted evidence recorded in the phase execution plan:

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall src/loom/pipeline/planning
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning tests/integration/pipeline -q
result: passed after refinement with 22 passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/planning tests/unit/loom/pipeline/planning tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py tests/package/test_pipeline_planning_api.py
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pyright
result: passed with 0 errors
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-package
result: passed with 24 passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-unit
result: passed with 273 passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-integration
result: passed with 15 passed
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 1.49s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 1.39s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | passed | 0.40s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | passed | 0.81s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | not present | 0.00s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

Suite output totals from `build/test-summary.md`:

- package: 24 passed
- unit: 278 passed
- contract: 15 passed
- integration: 16 passed
- e2e: no test files are present for this suite yet

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.
- [x] Does not add runtime dependencies.
- [x] Does not add actual stage execution, `PipelineRunner`, executor behavior, lifecycle writes, target instantiation, functional CLI behavior, remote stores, or cross-run cache reuse.

## Budget Status

- Phase implementation refinement: used on 2026-05-04 local time.
- PR review: used. The reviewer found the blocking `from_stage` selector issue; this user-authorized post-review fix addresses it. Do not consume a second automated PR review without explicit user instruction.
- PR body draft pass: complete in commit `0f9c581`.
- PR body refine pass: complete for stacked PR creation.
- PR open metadata: complete in this artifact.

## Assumptions

- The correct PR target is now `develop` because Phase 7 PR #11 has landed and
  Phase 8 was rebased onto updated `develop`.
- Same-run-directory resume is the only v0 reuse mode. Cross-run cache lookup remains deferred.
- Phase 9 will consume pending plan inputs, execute stages, validate returned outputs, and write final runner-owned lifecycle state.
- Phase 7 PR #11 has landed in `develop`; this PR was retargeted to `develop`
  during stack maintenance.

## Risks / Follow-Ups

- The recorded blocking `from_stage` selector review finding is fixed and
  validation has been rerun. A separate unsupported schema-version strictness
  review note remains non-blocking future hardening unless explicitly pulled
  into this phase.
- Detailed fingerprint diff rendering and CLI display remain deferred until a later CLI/status phase needs them.
- Plan persistence stores only the current plan, not plan attempt history.
- Downstream fingerprints with pending upstream outputs remain deferred until Phase 9 can bind actual produced artifacts during execution.

## PR Creation Status

Opened PR: https://github.com/samcantrill/loom/pull/12

Initially created with explicit base/head while Phase 7 was open:

```sh
gh pr create --base codex/add-local-stores-run-layout --head codex/add-planning-resume-selectors --body-file docs/roadmap/stage-0/phases/add-planning-resume-selectors-pr-body.md --title "Phase 8: Planning, Resume, And Selectors"
```

Verified immediately after creation:

```json
{"baseRefName":"codex/add-local-stores-run-layout","headRefName":"codex/add-planning-resume-selectors","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/12"}
```

Live PR body update used a direct `gh api --method PATCH
repos/samcantrill/loom/pulls/12 -F
body=@docs/roadmap/stage-0/phases/add-planning-resume-selectors-pr-body.md` fallback after
`gh pr edit --body-file docs/roadmap/stage-0/phases/add-planning-resume-selectors-pr-body.md`
failed with the GitHub Projects Classic deprecation GraphQL error.

After Phase 7 landed, the managing agent rebased this branch onto updated
`develop`, retargeted the PR to `develop`, reran validation, and recorded stack
maintenance below.

## Stack Maintenance

- Current predecessor branch: none
- Current target branch: `develop`
- Predecessor PR: Phase 7 PR #11 has landed in `develop`
- Retarget/rebase needed after predecessor merge: completed on 2026-05-04 local time
- Successor branches depending on this phase: Phase 9 PR #13, branch `codex/add-local-execution`
- Branch cleanup constraints: do not delete the Phase 8 branch until Phase 9 is retargeted or rebased away from it

Stack-maintenance evidence after Phase 7 landed:

```text
command: git rebase origin/develop
result: conflicts resolved by preserving merged Phase 7 files from develop and replaying Phase 8 planning/resume/selector commits

command: git push --force-with-lease origin codex/add-planning-resume-selectors
result: pushed rebased branch at 07f8a8f

command: gh api --method PATCH repos/samcantrill/loom/pulls/12 -f base=develop
result: PR #12 retargeted to develop after gh pr edit --base develop hit the known Projects Classic deprecation GraphQL error

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py tests/package/test_pipeline_planning_api.py -q
result: passed, 25 passed

command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 331 tests, and build succeeded

command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; package 24 passed, unit 277 passed, contract 15 passed, integration 15 passed, e2e not present
```

Known review status:

- Phase 8 PR review found a blocking `from_stage` selector bug. This
  user-authorized post-review fix addresses it by forcing a reusable
  `from_stage` selection to rerun while preserving the direct resume evidence
  and invalidating downstream stages.
- Validation after the blocker fix passed: focused planner/resume tests,
  focused Phase 8 planning tests, `make validate-pr`, and `make test-summary`.
- PR review budget has been consumed; no second automated review pass was run.
