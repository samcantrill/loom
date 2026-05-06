# Phase 1 Execution Plan: Run URI Runtime Addressing

## Metadata

- Status: final phase execution plan; implementation pending
- Feature focus: CLI Core
- PR title: `CLI Core - Phase 1: Run URI Runtime Addressing`
- Branch: `codex/add-run-uri-addressing`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-run-uri-addressing`
- Phase execution plan path: `docs/phases/add-run-uri-addressing.md`
- Full plan: `docs/implementation-plans/implementation-plan-v2.md`
- Source phase: Phase 1 - Run URI Runtime Addressing
- Stack predecessor: none; this is the first v2 phase.
- Base branch: local `develop` at `e2f0d80` (`docs: record v2 plan quality gate`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after review and checks because the target is `develop`.
- Workflow path: expanded path, selected because this phase is a breaking public/protocol/persisted schema migration spanning artifacts, planning, execution, stores, locks, events, provenance, and tests.
- Successor dependency notes: Phase 2 must build CLI infrastructure on the migrated `run_uri` surfaces. No validate/plan/run command behavior should be started in this phase.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v2.md`; no blocking plan-review findings remain.
- Plan quality gate loop budget: initial review used; refinement completed during v2 plan refinement; confirmation review not needed because no blocking findings remained.
- Draft pass: completed by the managing agent in this artifact.
- Refine pass: completed in the same artifact before implementation; no unresolved phase-plan blocker remains.
- Setup limitations: `gh auth status` succeeded outside the sandbox, `git fetch origin` succeeded with approved git metadata access, and `git worktree add` required approved git metadata access after the sandbox could not create `refs/heads/codex/add-run-uri-addressing`.
- Blockers: none known.

## Objective

Replace the public, protocol, and persisted run identity from `run_id` to `run_uri`, while keeping the runtime/store ownership boundary intact and leaving CLI command implementation to later phases.

## Full-Plan Context

V2 exposes a CLI over the existing v0 runtime and v1 config composition. This first phase removes the soon-obsolete `run_id` identity before command flags, JSON output, and user-facing docs can depend on it. Later phases add CLI scaffolding, validate, plan, run, and final docs/e2e coverage; they should consume the migrated runtime/store APIs rather than reimplement run addressing.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: Phase 1 is the first pending phase in `implementation-plan-v2.md`, all earlier roadmap work is already represented on local `develop`, and the v2 plan-quality gate commit is included in the base.
- Retarget/rebase plan after predecessor merge: none needed.
- Branch cleanup constraints: this branch can be deleted after merge because no successor branch should depend on it until Phase 2 starts.

## Source Phase Summary

- Goal: replace public/protocol/persisted `run_id` identity with `run_uri` before CLI behavior is exposed.
- Required scope: add local `file://` run URI validation/resolution helpers, migrate run-store protocols and local persisted wrappers, migrate execution/planning/status/event/lock/result models, migrate `ArtifactAddress`, add default local run URI allocation owned by the store/runtime facade, and preserve fingerprint exclusion.
- Required checkpoints: strict accepted/rejected URI forms, relative URI resolution to absolute persisted/displayed URIs, local store create/open/read/write against the resolved target directory, `ArtifactAddress(run_uri, artifact_id)`, unchanged `ArtifactRef`, and no ambient `run_uri` in semantic fingerprints.
- Acceptance criteria: public/protocol/persisted run identity uses `run_uri`; v2 local forms are validated; default allocation is collision-safe; contract and integration tests prove local planning/resume/execution still work.

## Current Source And Harness Findings

- `src/loom/pipeline/stores/run_store.py` defines every store protocol method with `run_id` parameters and `LocalRunStorePaths` path helpers using `run_id`.
- `src/loom/pipeline/stores/local_runs.py` validates path components through `validate_run_id`, stores wrapper fields named `run_id`, writes `run_dir`, and maps local paths as `root / run_id`.
- `src/loom/artifacts.py` defines `ArtifactAddress(run_id, artifact_id)` while `ArtifactRef` is already run-agnostic and should remain unchanged.
- `src/loom/pipeline/status.py`, `src/loom/pipeline/events.py`, and `src/loom/pipeline/locks.py` serialize `run_id` in status, event, and lock records.
- `src/loom/pipeline/execution/models.py`, `runner.py`, `lifecycle.py`, `eventing.py`, `run_locks.py`, `outputs.py`, and `executors/local.py` carry `run_id` through requests, results, failures, stage execution, events, locks, artifacts, and local executor contexts.
- `src/loom/pipeline/planning/models.py`, `planner.py`, `resume.py`, `actions.py`, and `explanations.py` use `run_id` in plans, resume checks, and persisted plan views.
- `src/loom/pipeline/planning/fingerprints.py` derives fingerprints from stage specs, artifact refs, Python/Loom versions, git, dependencies, and `FingerprintContext.extra`; it does not currently include ambient run identity and should remain that way.
- Existing tests mirror the old identity across package, unit, contract, integration, e2e, and docs example suites. Phase 1 should migrate these references instead of adding a compatibility matrix.

## In-Scope Work

- Add run URI parsing and resolution helpers in the owning store/runtime area, likely `loom.pipeline.stores`, with a small public surface for strict v2 local `file://` URIs.
- Accept only `file:///absolute/run`, `file://./relative/run`, and `file://../relative/run`.
- Reject plain paths, `file://localhost/...`, other file authorities, query strings, fragments, empty paths, and non-local schemes.
- Resolve relative run URIs against the current working directory before store use and persist/display the resolved absolute `file:///...` form.
- Migrate type aliases, dataclasses, method parameters, serialized fields, wrapper validation, and local path helpers from `run_id` to `run_uri`.
- Store local runs at the exact resolved target directory, not below `root / run_uri` as a path component.
- Add store-owned default local run URI allocation under `LocalRunStore.root`, using timestamped names and collision handling.
- Migrate `ArtifactAddress` to `run_uri + artifact_id`; keep `ArtifactRef` serialization unchanged.
- Update tests and feature docs that directly contradict the migrated runtime/store behavior.
- Preserve import boundaries and avoid adding CLI modules or dependencies.

## Out-of-Scope Work

- Any `loom` CLI command implementation, console script wiring, JSON envelopes, or command parser behavior.
- Compatibility with v0 run directories or persisted documents that contain only `run_id`.
- Remote store support, non-local URI schemes, `file://localhost`, run migration/import tooling, or cross-run cache reuse.
- Adding `run_uri` to `ArtifactRef`.
- Changing semantic stage fingerprint inputs beyond tests that assert `run_uri` is excluded.
- Broad cleanup of unrelated feature-doc examples that are not contradicted by Phase 1 behavior.

## Assumptions

- The hard swap is intentional: tests and docs should move to `run_uri` rather than accepting either field.
- `LocalRunStore.root` remains the store-owned default root. It may be cwd-relative when constructed that way; allocation should resolve the selected run URI before persistence/display.
- A `file://` run URI identifies a local run directory. Local helpers may expose the resolved path for store use, but public records should persist the URI string.
- Existing run IDs such as `run1` in tests can be mechanically replaced by explicit local URIs derived from `tmp_path`.
- Where variable renaming would make a diff too large, internal local variables may be migrated in coherent slices, but public signatures and serialized fields must be `run_uri`.

## Scope Contract

Public and protocol-level behavior after this phase:

- The public run identifier field is named `run_uri`.
- `RunRequest.run_uri` is optional; when absent for execution, the runner/store facade allocates a new local run URI under the store-owned root.
- `RunRequest.open_existing=True` opens the exact run URI and fails if the run is missing or invalid.
- `RunStatusRecord`, `StageStatusRecord`, `PipelineEventRecord`, `RunLockRecord`, `ExecutionFailure`, stage execution requests/results, `RunResult`, `ExecutionPlan`, and persisted local-store wrappers serialize `run_uri`, not `run_id`.
- `RunStore` and `LocalRunStorePaths` protocol methods accept `run_uri: str`.
- `LocalRunStore` resolves valid local file URIs into paths and uses those exact paths for all run files.
- `ArtifactAddress.to_dict()` returns `{"run_uri": ..., "artifact_id": ...}` and rejects old `run_id` fields.
- `ArtifactRef.to_dict()` remains unchanged and contains no `run_uri`.
- Stage fingerprints continue to exclude ambient run identity.

Error behavior:

- Invalid run URI syntax should fail through store/runtime errors, not generic `ValueError`.
- Old `run_id` persisted documents should fail as malformed or missing required `run_uri` fields.
- Non-local schemes and disallowed file authorities should fail loudly before path access.

## Design Impact

- Maintainability: concentrates run-addressing behavior in store/runtime APIs so later CLI phases can call one public facade instead of parsing paths.
- Extensibility: URI-shaped identity gives future diagnostics, catalogs, bundles, and remote stores an address model without requiring CLI contract churn.
- Domain neutrality: run URIs describe runtime storage locations only and do not encode project semantics.
- Source-tree boundaries: changes stay within artifacts, pipeline, stores, planning, execution, provenance-facing records, docs, and tests; no downstream project imports or CLI business logic.

## Future Compatibility

- Phase 2 can add `--run-uri` parsing without owning path semantics.
- Phase 4 read-only planning can pass `run_uri` through planner/store facades and reject existing or missing state consistently.
- Phase 5 execution can request default allocation from the store/runtime facade when no explicit run URI is supplied.
- V8 catalogs and V9 bundles can pair `ArtifactAddress(run_uri, artifact_id)` with `ArtifactRef` when cross-run identity is needed.
- V12/V13 remote stores can add non-local URI adapters behind the same public identity without changing current local-only validation defaults.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Write both `run_id` and `run_uri` during a compatibility period | The v2 plan explicitly chooses a hard swap to avoid carrying two public identities. |
| Treat `run_uri` as a display-only alias over `root / run_id` | This keeps local layout coupled to public identity and blocks later remote stores. |
| Accept plain paths as run URIs | The CLI contract requires explicit URI syntax so scripts do not depend on ambiguous local path parsing. |
| Add `run_uri` to `ArtifactRef` | `ArtifactRef` is physical artifact metadata; cross-run identity belongs in `ArtifactAddress` alongside the ref when needed. |
| Include `run_uri` in stage fingerprints | Run identity is not semantic input; stochastic behavior must be represented through config, seeds, runtime inputs, or provenance. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Old `run_id` persisted runs become unreadable. | The implementation plan chose a hard schema/API swap before CLI contracts exist. | A later explicit import/migration feature is planned for historical v0 runs. |
| Local-only URI support rejects remote-looking URIs. | V2 needs a stable local contract before remote store adapters exist. | V12/V13 remote-store work defines adapter ownership and validation policy. |
| Default allocation uses local timestamped directories. | It is sufficient for v2 local execution and keeps allocation store-owned. | Collision pressure, multi-process allocation, or remote stores require stronger allocation semantics. |

## Reviewability

- Expected PR size and shape: broad but mechanical migration with a small amount of new run URI helper logic and focused docs/test updates.
- Files and areas to inspect: `src/loom/artifacts.py`, `src/loom/ids.py`, `src/loom/pipeline/stores/`, `src/loom/pipeline/status.py`, `src/loom/pipeline/events.py`, `src/loom/pipeline/locks.py`, `src/loom/pipeline/planning/`, `src/loom/pipeline/execution/`, `src/loom/pipeline/executors/local.py`, package exports, and migrated tests.
- Scope-control checks: no CLI package changes beyond incidental import-boundary tests, no old-field compatibility, no remote schemes, no `ArtifactRef.run_uri`, and no fingerprint inclusion of ambient run identity.

## Implementation Steps

1. Add the local run URI value/helper surface and tests for accepted/rejected forms, path resolution, and default allocation behavior.
2. Migrate artifact address and shared record models (`ids`, artifacts, status, events, locks) plus unit tests from `run_id` to `run_uri`.
3. Migrate run-store protocols and `LocalRunStore` path/persistence behavior, including wrapper field names and malformed old-document failures.
4. Migrate planning and execution models/helpers/runner/local executor surfaces to use `run_uri` and default allocation.
5. Migrate contract, integration, e2e, package, and docs example tests; add explicit fingerprint-exclusion coverage.
6. Update owning feature docs and Phase 1 metadata after implementation evidence exists.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import.py`, `tests/package/test_public_api.py`, `tests/package/test_pipeline_api.py`, `tests/package/test_pipeline_execution_api.py`, `tests/package/test_pipeline_store_api.py`.
- Required assertions or deferral reason: public imports remain cheap; `ArtifactAddress` exports and round-trips with `run_uri`; migrated pipeline/store/execution APIs import without loading CLI or downstream project code.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/test_artifacts.py`, `tests/unit/loom/test_ids.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/stores/test_store_errors.py`, `tests/unit/loom/pipeline/test_status.py`, `tests/unit/loom/pipeline/test_events.py`, `tests/unit/loom/pipeline/test_locks.py`, `tests/unit/loom/pipeline/planning/test_models.py`, `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`, `tests/unit/loom/pipeline/planning/test_resume.py`, `tests/unit/loom/pipeline/execution/test_execution_models.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, `tests/unit/loom/pipeline/execution/test_lifecycle.py`, `tests/unit/loom/pipeline/execution/test_eventing.py`, `tests/unit/loom/pipeline/execution/test_run_locks.py`, and `tests/unit/loom/pipeline/executors/test_local_executor.py`.
- Required assertions or deferral reason: accepted/rejected URI forms, resolved absolute serialization, default allocation collision handling, record serialization with `run_uri`, old `run_id` field rejection, unchanged `ArtifactRef`, and no `run_uri` in stage fingerprint hash inputs.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_store_contract.py`, `tests/contracts/test_executor_contract.py`, and artifact/stage contracts touched by the migration.
- Required assertions or deferral reason: `RunStore` protocol methods use `run_uri`, local path protocol uses `run_uri`, artifact index/stage-state contracts round-trip with `run_uri`, and dummy/incomplete stores reflect the new protocol.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_local_stores.py`, `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_local_execution_resume.py`, `tests/integration/pipeline/test_planning_resume.py`, `tests/integration/pipeline/test_plan_persistence.py`, and `tests/integration/docs/test_v0_python_examples.py`.
- Required assertions or deferral reason: local planning/resume/execution work with resolved absolute run URIs, explicit target directories are used exactly, existing URI failures are loud, and persisted plans/status/events/locks use `run_uri`.

### E2E Suite

- Status: conditional for this phase, final required in Phase 6.
- Expected paths: `tests/e2e/test_local_pipeline_run.py` if existing e2e coverage breaks during migration.
- Required assertions or deferral reason: migrate existing e2e tests for coverage continuity, but do not add broad CLI e2e behavior until command phases.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: Phase 1 is local runtime/store behavior with no opt-in executor or external service suites.

## Risks

- The migration is broad and easy to make inconsistent by changing public fields but missing persisted wrapper validation or test fixtures.
- Default allocation must not silently recreate old `run_id` semantics by treating URI strings as path components.
- Existing docs/tests may contain many legitimate historical `run_id` mentions; implementation should update current public/runtime behavior without broad unrelated doc churn.
- Public API hard swaps can leave stale `from_dict` compatibility behavior if old fields are accidentally accepted.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/test_artifacts.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py
uv run pytest tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/test_events.py tests/unit/loom/pipeline/test_locks.py
uv run pytest tests/unit/loom/pipeline/planning tests/unit/loom/pipeline/execution tests/unit/loom/pipeline/executors/test_local_executor.py
uv run pytest tests/integration/pipeline/test_local_stores.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py
uv run pytest tests/package/test_public_api.py tests/package/test_pipeline_api.py tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: helper surface first, records second, store migration third, planning/execution fourth, broad test/docs migration last.
- Tests to run with each slice: use the targeted commands above, starting with the unit files closest to the edited module.
- Decisions the executor must not revisit: hard swap only, local `file://` only, no old `run_id` compatibility, no CLI command work, no `ArtifactRef.run_uri`, and no `run_uri` in fingerprints.
- Conditions that require stopping for the manager: inability to represent exact local target paths from `file://` URIs, a need for remote URI policy, a conflict with existing v1 persisted composition behavior, or a test failure that implies scope must expand into CLI or migration tooling.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed in this commit.
- Final phase execution plan: completed in this commit.
- Implementation summary:
- Implementation validation:
- Refinement summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
