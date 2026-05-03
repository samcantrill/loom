## Phase

- Phase: Phase 6 - Pipeline Specs And Graph
- Branch: `codex/add-pipeline-specs-graph`
- Target: `codex/add-recipes-instantiation`
- Stack predecessor: `codex/add-recipes-instantiation`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-pipeline-specs-graph`
- Plan: `docs/implementation-plans/implementation-plan-v0.md`
- Expanded phase plan: `docs/phases/add-pipeline-specs-graph.md`
- PR body draft pass: complete
- PR body refine pass: complete
- PR creation status: prepared, not opened; remote push and PR creation blocked by invalid GitHub credentials.
- Merge eligibility: reviewable against `codex/add-recipes-instantiation`; not merge-eligible until Phase 5 lands and Phase 6 is retargeted or rebased onto `develop`.
- Head commit prepared for draft: `5dbd6af9964c7abffc6f0dba28645fd82dd070ff`
- Implementation commits: `fee1274` plan draft, `d1e0e3a` plan refinement, `888043f` implementation, `5dbd6af` validation refinement.

## Summary

This PR implements the Phase 6 static pipeline model and graph primitives. It adds frozen pipeline, stage, and output specs; a minimal stage context; the structural `Stage` protocol; run/stage status values and serializable status records; strict `stage.output` input bindings; and pure graph construction, dependency traversal, cycle detection, and deterministic topological sorting.

The work is intentionally limited to static parsing, validation, status modeling, and graph behavior. It does not add persistent stores, stage target instantiation, runner behavior, CLI behavior, artifact path allocation, resume planning, selectors, Phase 7+ helpers, domain-specific behavior, or root `loom.__init__` pipeline exports.

## Acceptance Criteria

- [x] Documented inline stage YAML shape parses into `PipelineSpec`, `StageSpec`, and `OutputSpec`.
- [x] Unknown stage-level orchestration keys are rejected with path-aware validation errors.
- [x] Deferred fields such as pipeline defaults, stage `runtime`, `retry`, `when`, stage metadata, output `path`, and output `required` fail clearly.
- [x] Duplicate stages, missing outputs, bad output specs, bad references, unknown stages, unknown outputs, cycles, and self-dependencies fail clearly.
- [x] Strict `stage.output` input references create data dependencies and authored `depends_on` creates control dependencies.
- [x] Topological sort works for single, linear, branching, and diamond DAGs with deterministic authored-order tie-breaking.
- [x] Dummy stages satisfy the `Stage` protocol structurally without inheritance.

## Implementation Notes

- Added `loom.pipeline.errors` with pipeline-specific validation, graph, cycle, input-binding, status-serialization, and stage-contract errors under the existing broad error hierarchy.
- Added `loom.pipeline.specs` with frozen `OutputSpec`, `StageSpec`, `PipelineSpec`, and `parse_pipeline_config()`, including plain-data normalization, identifier validation, strict allowed/deferred field handling, duplicate-stage checks, and output validation.
- Added `StageContext` as a frozen minimal value object containing IDs, paths, resolved config, stage config, provenance, and metadata only.
- Added `Stage` as a runtime-checkable structural protocol with `run(context, inputs) -> Mapping[str, ArtifactRef]`.
- Added `RunStatus`, `StageStatus`, `RunStatusRecord`, `StageStatusRecord`, and parse/serialization helpers without lifecycle transition logic or filesystem I/O.
- Added graph binding helpers for syntactic `stage.output` parsing and semantic binding resolution against `PipelineSpec`.
- Added graph node/edge/dataclass primitives, data-vs-control edge reasons, upstream/downstream helpers, cycle detection, and deterministic topological sorting.
- Exported the Phase 6 static API from `loom.pipeline` and `loom.pipeline.graph` while preserving the root import boundary.

## Tests And Validation

Final validation evidence recorded for PR preparation:

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed. Ruff passed; Pyright passed with 0 errors; default pytest passed with 264 passed; uv build produced source and wheel distributions.

command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed. Wrote build/test-summary.md; package, unit, contract, and integration suites passed; e2e is not present.
```

Earlier refinement checks also passed:

```text
command: UV_CACHE_DIR=/tmp/uv-cache make lint
result: passed

command: UV_CACHE_DIR=/tmp/uv-cache make typecheck
result: passed, 0 errors

command: UV_CACHE_DIR=/tmp/uv-cache make test-unit
result: passed, 227 passed

command: UV_CACHE_DIR=/tmp/uv-cache make test-package
result: passed, 16 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline tests/unit/loom/pipeline/graph
result: passed, 38 passed

command: UV_CACHE_DIR=/tmp/uv-cache make test-contract
result: passed, 11 passed

command: UV_CACHE_DIR=/tmp/uv-cache make test-integration
result: passed, 10 passed
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 0.76s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 0.73s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | passed | 0.38s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | passed | 0.45s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | not present | 0.00s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

Suite details:

- Package: 16 passed, including public pipeline API and import-boundary coverage.
- Unit: 227 passed, including specs, context, stage protocol, status, binding, DAG, and topology coverage.
- Contract: 11 passed, including the new structural stage contract.
- Integration: 10 passed, including composed config feeding static `PipelineSpec` and graph construction.
- E2E: no test files are present for this suite yet; Phase 6 has no runnable user workflow, CLI command, runner, or run directory behavior.

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.
- [x] Keeps persistent stores, run layout, artifact path allocation, resume planning, selectors, runner/execution behavior, stage target instantiation, CLI, config persistence, and Phase 7+ helpers out of scope.
- [x] Keeps `loom.__init__` free of pipeline exports.

## Budget Status

- Phase implementation refinement: used by `loom_phase_refiner` in commit `5dbd6af` (`fix: refine after validation`).
- PR review before this PR: unused.

## Risks / Follow-Ups

- This is a stacked PR targeting `codex/add-recipes-instantiation`; it is reviewable now but must not be merged until Phase 5 lands and Phase 6 is retargeted or rebased onto `develop`.
- `gh auth status` is known to report the configured `samcantrill` token as invalid in this environment. Live PR inspection, push, and PR creation may be unavailable until credentials are refreshed.
- Status records are intentionally minimal and transition-free until store and runner phases prove the persistence and lifecycle policy.
- Only compact `stage.output` input references are supported in v0; literal inputs, external artifacts, optional outputs, and richer input specs remain deferred.
- Store-backed `StageContext` helpers, output path allocation, save/register helpers, local stores, planning, resume, selectors, and execution behavior remain owned by later phases.

## PR Creation Status

Prepared but not opened.

Credential preflight was performed before any push or PR operation:

```text
command: gh auth status
result: unavailable. GitHub CLI reports the configured github.com account `samcantrill` token in `/home/samcantrill/.config/gh/hosts.yml` is invalid and recommends `gh auth login -h github.com`.
```

Because credentials are unavailable, no push or PR creation command was attempted and no unsafe authentication workaround was used. After credentials are refreshed, push the branch and open the stacked PR with the recorded target:

```sh
git push -u origin codex/add-pipeline-specs-graph
gh pr create --base codex/add-recipes-instantiation --head codex/add-pipeline-specs-graph --body-file docs/phases/add-pipeline-specs-graph-pr-body.md
```

Verify the PR target before handoff:

```sh
gh pr view <PR> --json baseRefName,headRefName,state,url
```

Required verification facts once opened:

- `baseRefName` must be `codex/add-recipes-instantiation`.
- `headRefName` must be `codex/add-pipeline-specs-graph`.
- The PR is stacked for review only and is not merge-eligible until Phase 5 lands and stack maintenance retargets or rebases Phase 6 onto `develop`.
