## Phase

- Phase: Phase 9 - Local Execution
- Branch: `codex/add-local-execution`
- PR: https://github.com/samcantrill/loom/pull/13
- Target branch: `codex/add-planning-resume-selectors`
- Stack predecessor: `codex/add-planning-resume-selectors`
- Merge eligibility: stacked phase PR; reviewable against `codex/add-planning-resume-selectors`; not merge-eligible until Phase 7 and Phase 8 land and this branch is rebased or replayed onto `develop`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-local-execution`
- Plan: `docs/implementation-plans/implementation-plan-v0.md`
- Phase execution plan: `docs/phases/add-local-execution.md`
- Phase execution plan draft pass: complete
- Phase execution plan refine pass: complete
- PR body draft pass: complete
- PR body refine pass: complete
- PR open metadata: complete; `gh pr view 13 --json baseRefName,headRefName,state,url` returned `baseRefName=codex/add-planning-resume-selectors`, `headRefName=codex/add-local-execution`, `state=OPEN`, and `url=https://github.com/samcantrill/loom/pull/13`

## Summary

Adds the Phase 9 local execution runtime. The PR turns the existing config,
pipeline spec, graph, local store, and Phase 8 planning layers into the first
end-to-end in-process runner for v0.

The stacked diff against `codex/add-planning-resume-selectors` adds execution
models, lifecycle helpers, log helpers, output validation, an executor protocol,
`LocalExecutor`, store-backed `StageContext` artifact helpers, `PipelineRunner`,
`run_pipeline`, scoped public exports, and package/unit/contract/integration/e2e
coverage. It keeps CLI behavior, subprocess or SLURM execution, remote stores,
parallel scheduling, retries, cross-run cache reuse, stage constructor kwargs,
and context-collected outputs out of scope.

## Acceptance Criteria

- [x] A synthetic local pipeline can run end to end from YAML.
- [x] Run directories contain expected config, provenance, status, fingerprint, input, output, artifact, plan, and index files.
- [x] Same-run-directory reruns produce `REUSE` planner decisions for valid unchanged stages without persisting `SKIPPED` status.
- [x] Changed stage config or upstream artifacts rerun the changed stage and downstream dependents.
- [x] Invalid stage outputs fail with path-aware errors.
- [x] Stage exceptions persist failure state before failed status and leave inspectable run state.

## Implementation Notes

The runner owns lifecycle, planning invocation, target construction, pending
input rebinding, final fingerprint persistence, output validation, artifact
index updates, stage provenance writes, and root run finalization. Stages remain
trusted project objects that satisfy the structural `Stage.run(context, inputs)`
contract and return a direct mapping of declared output names to `ArtifactRef`s.

`LocalExecutor` is deliberately narrow. It validates the stage object, invokes
`stage.run()` in the current Python process, optionally captures stdout/stderr,
and converts Python exceptions into structured `ExecutionFailure` results. It
does not decide selector behavior, resume behavior, status writes, artifact
index policy, retries, or downstream invalidation.

`StageContext` was extended compatibly with defaulted `run_store`,
`artifact_store`, and `output_specs` runtime fields plus `output_path()`,
`save_artifact()`, and `register_artifact()` helpers. The helpers validate
declared output names when specs are present, but they do not collect implicit
outputs or let a stage succeed without returning the output mapping.

The single bounded implementation refinement pass aligned
`loom.pipeline.execution.__all__` with the locked Phase 9 public API, rejected
non-bool `failure_policy` mapping values instead of silently coercing them,
preserved failure `started_at` timestamps after `RUNNING`, distinguished stage
contract failures from target construction failures, and prevented `REUSE` or
`SKIP` handling failures from being overwritten by a final `SUCCEEDED` run
status.

## Tests And Validation

Final validation evidence after refinement:

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright passed with 0 errors, default pytest passed with 353 passed, and uv build produced source and wheel distributions.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md.
```

Targeted implementation and refinement evidence is recorded in
`docs/phases/add-local-execution.md`, including focused Phase 9 slices,
package, unit, contract, integration, e2e, Ruff, and Pyright checks.

Pre-open stack-target verification from the draft pass:

```text
command: gh pr view 12 --json number,state,baseRefName,headRefName,url
result: passed; PR #12 is OPEN, head is codex/add-planning-resume-selectors, base is codex/add-local-stores-run-layout, url is https://github.com/samcantrill/loom/pull/12.
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.18s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 1.51s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | passed | 0.50s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | passed | 2.33s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | passed | 0.80s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

Suite output totals from `build/test-summary.md`:

- package: 28 passed
- unit: 285 passed
- contract: 16 passed
- integration: 23 passed
- e2e: 1 passed

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.
- [x] Does not add runtime dependencies.
- [x] Does not add functional CLI behavior, subprocess/SLURM/container execution, remote stores, parallel scheduling, retries, cross-run cache reuse, stage constructor kwargs, or context-collected outputs.

## Budget Status

- Plan quality gate: passed on 2026-05-03; initial review used, automated plan refinement pass used, confirmation review used.
- Phase execution plan draft pass: complete.
- Phase execution plan refine pass: complete.
- Phase implementation refinement: used on 2026-05-04 local time.
- PR review before this PR: unused.
- PR body draft pass: complete in this artifact.
- PR body refine pass: complete in this artifact.
- PR open metadata: complete; PR #13 is open and verified against `codex/add-planning-resume-selectors`.

## Assumptions

- The correct PR target remains `codex/add-planning-resume-selectors` because Phase 8 PR #12 remains open and Phase 9 depends on Phase 8 planner, resume, selector, fingerprint, and plan persistence contracts.
- Same-run-directory resume is the only v0 reuse mode.
- Stage targets are trusted project code; import sandboxing and target allow lists remain deferred.
- Local execution is serial and stop-on-first-failure.
- Config resolved/redacted snapshots may be rendered as pretty JSON in YAML-named files because JSON is valid YAML and no generic YAML dump helper exists yet.
- `StageSpec.resources` remain opaque metadata and are not interpreted by the local executor.

## Risks / Follow-Ups

- This PR is stacked and must be rebased or replayed after Phase 8 lands, retargeted to `develop`, and revalidated before it becomes merge-eligible.
- The initial v0 executor is in-process only. Subprocess, SLURM, container, distributed, parallel, retry, timeout, cancellation, and continue-on-failure behavior remain deferred.
- No run-level lock manager exists; Phase 9 relies on the file-level atomic writes provided by the local stores.
- Store files keep latest-attempt state rather than attempt history. Retry/audit history can be added later if the state model needs it.
- Raw, overlay, and CLI config snapshot persistence depends on caller-supplied source text.
- Rich interrupted-run recovery and broader error-message hardening remain Phase 10 work.

## PR Creation Status

Opened the stacked PR with the explicit recorded base and head:

```sh
gh pr create --base codex/add-planning-resume-selectors --head codex/add-local-execution --body-file docs/phases/add-local-execution-pr-body.md --title "Phase 9: Local Execution"
```

Result:

```text
https://github.com/samcantrill/loom/pull/13
```

Immediate verification:

```json
{"baseRefName":"codex/add-planning-resume-selectors","headRefName":"codex/add-local-execution","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/13"}
```

Live body synchronization: `gh pr edit 13 --body-file
docs/phases/add-local-execution-pr-body.md` hit GitHub CLI's known Projects
Classic `repository.pullRequest.projectCards` deprecation path, so the live PR
body was synchronized with `gh api --method PATCH
repos/samcantrill/loom/pulls/13 -F
body=@docs/phases/add-local-execution-pr-body.md`.

## Stack Maintenance

- Current predecessor branch: `codex/add-planning-resume-selectors`
- Current target branch: `codex/add-planning-resume-selectors`
- Predecessor PR: Phase 8 PR #12 is open
- Live predecessor verification: `gh pr view 12` returned `state=OPEN`, `headRefName=codex/add-planning-resume-selectors`, and `baseRefName=codex/add-local-stores-run-layout`
- Retarget/rebase needed after predecessor merge: yes; after Phase 8 lands, rebase or replay this branch onto updated `develop`, retarget the PR to `develop`, rerun validation, and record stack maintenance
- Successor branches depending on this phase: none recorded
- Branch cleanup constraints: do not delete the Phase 8 predecessor branch while this branch depends on it; do not delete the Phase 9 branch until every successor branch has been retargeted or rebased away from it
