## Phase

- Phase: Phase 3 - Stage Factory And Semantic Fingerprint Policy
- Branch: `codex/v0-post-stage-factory`
- Target branch: `develop`
- PR: pending
- Stack predecessor: none
- Merge eligibility: serial human merge gate. This PR must target `develop`,
  request review from `samcantrill` or mention `@samcantrill` if GitHub rejects
  the reviewer request, and must be approved and merged by a human. Codex must
  not approve or merge.
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-stage-factory`
- Plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Phase execution plan: `docs/phases/v0-post-stage-factory.md`
- Phase execution plan draft pass: complete in commit `ed907e7`
- Phase execution plan refine pass: complete in commit `ad70e99`
- Implementation commits: `1470775`, `11aad0f`, `2315e9c`, `9f392d0`
- Phase implementation refinement: complete in commit `fbe3b48`
- PR body draft pass: complete in this artifact
- PR body refine pass: complete in this artifact

## Summary

This PR implements Phase 3 of the v0-post hardening plan. It replaces the old
top-level no-argument stage construction shape with explicit authored
`factory._target_` and `factory.init` semantics while keeping authored `config`
as runtime `StageContext.stage_config`.

The diff also adds an import-safe pipeline-owned stage construction helper,
wires `PipelineRunner` through that helper, bumps stage fingerprints to the v2
semantic policy, records factory target/init and explicit fingerprint fields in
the fingerprint payload, and migrates in-scope examples, fixtures, tests, and
docs to the factory contract.

## Acceptance Criteria

- [x] Authored configs construct stages with `factory._target_` and
  `factory.init`.
- [x] Constructor values stay out of runtime `StageContext.stage_config`.
- [x] `run(context, inputs)` remains the project stage execution contract.
- [x] Stage construction is owned by `loom.pipeline.stage_factory` and remains
  import-safe without optional config dependencies.
- [x] Legacy top-level `_target_` authored stages are rejected with a
  migration-oriented error.
- [x] Fingerprint tests prove factory target/init, runtime config, declared
  outputs, bound input identity, selected environment identity, and explicit
  `fingerprint` fields are semantic.
- [x] Fingerprint tests prove operational `resources` and artifact URI changes
  are non-semantic by default.
- [x] In-scope no-argument examples and fixtures use `factory._target_`.
- [x] Final `make validate-pr` and `make test-summary` pass.

## Implementation Notes

- Added frozen `StageFactorySpec` and migrated `StageSpec` so construction data
  lives under `factory`, runtime invocation data remains under `stage_config`,
  and explicit authored fingerprint fields live under `fingerprint_fields`.
- Kept `StageSpec.target_path` as a derived read-only compatibility property,
  but removed the old `target_path=` constructor path and rejected authored
  top-level `_target_`.
- Added `loom.pipeline.stage_factory` with dotted and single-colon target import
  support, class/callable construction with `**factory.init`, instance
  acceptance only when init is empty, and final `Stage` protocol validation.
- Updated `PipelineRunner` to construct stages through the pipeline helper and
  expose `factory_target` in stage context metadata rather than constructor
  init values.
- Bumped stage fingerprint schema and policy metadata to
  `loom.stage.semantic` v2. The v2 payload records `factory_target`,
  `factory_init`, runtime `stage_config`, declared and bound inputs, declared
  outputs, explicit `fingerprint_fields`, and selected environment identity.
- Kept v1 fingerprint records stale under the v2 policy instead of treating
  them as reusable matches.
- Updated `docs/structure.md`, `docs/features/pipeline.md`,
  `docs/features/execution.md`, `docs/features/fingerprints.md`, and the local
  run example for the new factory and semantic fingerprint contracts.

## Tests And Validation

```text
command: git diff --check develop...HEAD
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed
details: Ruff passed; Pyright passed with 0 errors; isolated default no-extra harness passed with 325 passed and 9 skipped; isolated config-extra harness passed with 103 passed and 326 deselected; source distribution and wheel built successfully.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.84s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run package` |
| unit | passed | 2.40s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run unit` |
| contract | passed | 1.02s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run contract` |
| integration | passed | 1.42s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run integration` |
| e2e | passed | 1.68s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run e2e` |
| config-extra | passed | 5.86s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run config-extra` |

Suite counts from `make test-summary`:

- package: 33 passed, 1 skipped
- unit: 271 passed, 1 skipped
- contract: 13 passed, 1 skipped
- integration: 8 passed, 5 skipped
- e2e: 1 passed
- config-extra: 103 passed, 326 deselected

Focused implementation and refinement evidence is recorded in
`docs/phases/v0-post-stage-factory.md`.

## Scope Control

- [x] Implements only the assigned Phase 3 work.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

Scope check:

- No runtime/resource model implementation, runtime profiles, event models,
  append-only event JSONL, concrete lock protocol, local lock files, or blocked
  descendant status persistence.
- No planner policy decomposition, `PlanExplanation`, selector behavior
  changes, resume policy extraction, or CLI diagnostics.
- No generic OmegaConf/Pydantic recursive object graph instantiation for stage
  factories.
- No plugin discovery, plugin-managed aliases, recipe catalog redesign, fresh
  catalog composition path, or global registry changes.
- No subprocess, SLURM, container, remote executor, remote store, run catalog,
  bundle, sweep, retry, timeout, cleanup, or retention behavior.
- No compatibility bridge that silently accepts legacy authored top-level
  `_target_` pipeline configs.
- No Phase 4 work was started.

## Budget Status

- Plan quality gate: passed; initial review used, automated plan refinement
  pass used, confirmation review used.
- Phase execution plan draft pass: complete.
- Phase execution plan refine pass: complete.
- Phase implementation refinement: used in commit `fbe3b48`; no blockers
  reported.
- PR review: unused.
- PR body draft pass: complete in this artifact.
- PR body refine pass: complete in this artifact.

## Assumptions

- Serial human merge gate mode is active.
- Phase 2 is already merged into `develop`; this branch starts from `develop`
  at `4611a877e38bc3997565352d81c40bc79801cd7c`.
- Breaking pre-v1 authored pipeline config changes are allowed where they
  correct the v0-post contracts.
- `factory.init` is trusted project-authored plain data. It is not recursively
  instantiated, injected, interpolated, or treated as a config-layer object
  graph.
- Existing v1 fingerprint records are intentionally stale under the v2 semantic
  policy.
- Phase 4 and later phases remain unstarted until this PR is human-approved and
  human-merged into `develop`.

## Risks / Follow-Ups

- Legacy authored top-level `_target_` pipeline configs now fail and must move
  to `factory._target_` plus optional `factory.init`.
- Existing v1 stage fingerprint records are not reusable matches under the v2
  semantic policy and should rerun.
- Stage factory construction intentionally supports plain keyword init only;
  plugin-managed target aliases, recursive object graph instantiation, and
  dependency injection remain future work.
- Runtime/resource/event/lock foundations, planner decomposition, explicit
  recipe catalogs, runner lifecycle decomposition, non-local executors, remote
  stores, catalogs, bundles, sweeps, cleanup, and final migration notes remain
  future-phase work.

## PR Creation Status

- PR opened: pending.
- PR URL: pending.
- Command to run:

```sh
gh pr create --base develop --head codex/v0-post-stage-factory --title "Phase 3: Stage Factory and Semantic Fingerprint Policy" --body-file docs/phases/v0-post-stage-factory-pr-body.md
```

- Verification: pending `gh pr view <PR> --json baseRefName,headRefName,state,url`.
- Target verification result: pending; the PR must target `develop`.
- Merge eligibility: root serial-gate PR targeting `develop`; human review and
  human merge are required. Codex must not approve or merge.
- Current blocker: none.

## Review Notification

- Reviewer request: pending PR creation.
- Fallback if GitHub rejects the request: add a PR comment mentioning
  `@samcantrill` and record the comment URL here.
- Notification result: pending.

## Stack Maintenance

- Current predecessor branch: none.
- Current target branch: `develop`.
- Retarget/rebase needed after predecessor merge: none; this is a root serial
  phase with no predecessor.
- Successor branches depending on this phase: none should start until this PR
  is human-approved and human-merged into `develop`.
- Branch cleanup constraints: keep `codex/v0-post-stage-factory` until the
  human-owned PR has merged into `develop` and no successor branch depends on
  it.
