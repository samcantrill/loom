# Phase 2 Execution Plan: Store, Artifact, And Stage Context Capabilities

## Metadata

- Status: draft phase execution plan
- Branch: `codex/v0-post-store-capabilities`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-store-capabilities`
- Phase execution plan path: `docs/phases/v0-post-store-capabilities.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Source phase: `Phase 2 - Store, Artifact, And Stage Context Capabilities`
- Stack predecessor: none
- Base branch: `develop` at `617e53f9ddf96ccea7aaa00a8f0776db7ae3652f`
- Target branch: `develop`
- Merge eligibility: human-owned serial merge gate. The PR must target `develop`, request review from `samcantrill`, mention `@samcantrill` in the PR body or an immediate PR comment, and is merge-eligible only after human approval and human merge into `develop`. Codex must not approve or merge.
- Successor dependency notes: Phase 3 must not start while this phase is only `pr_open` or `approved`; no successor phase starts until the Phase 2 PR is approved and human-merged into `develop`.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v0-post.md`; no blocking plan-review findings remain.
- Plan quality gate loop budget: initial plan review used, automated plan refinement pass used, confirmation review used. Do not consume another plan-quality review loop without explicit manager instruction.
- Draft pass: completed by `loom_phase_planner` in this draft pass.
- Refine pass: pending.
- Setup limitations: none for local planning. The assigned branch/worktree already existed at the requested `develop` base commit; no remote synchronization was needed for this draft.
- Blockers: none.

## Objective

Replace generic local path assumptions with backend-neutral store and stage-author capabilities while preserving the local stores as inspectable reference implementations. This phase is the main pre-v1 contract break for local path-shaped store APIs, run-scoped artifact storage, cross-run artifact identity, and stage-facing context boundaries.

The result should make local paths explicit local-only helpers instead of generic protocol requirements. Project stages should use `StageContext` helpers for declared outputs, managed artifact save/register, artifact loading, stage config, and intentionally local workspace access, without receiving direct generic run-store or artifact-store escape hatches.

## Full-Plan Context

Phase 1 is merged and established recursive immutability, shared schema helpers, and the no-extra/config-extra validation split. Phase 2 builds on those corrected foundations by fixing findings 1, 2, and 8 from the source plan: local path-shaped store contracts, artifact-store run scope and identity, and ambiguous run metadata naming.

This phase must happen before Phase 3 stage factory/fingerprint policy, Phase 4 runtime/event/lock foundations, Phase 5 planner decomposition, Phase 7 runner lifecycle decomposition, and Phase 8 migration notes. It must reserve only the capability boundary needed for future locking; concrete lock protocols, local lock behavior, event JSONL, runtime/resource models, blocked descendant persistence, runner decomposition, remote store implementations, subprocess/container/SLURM behavior, run catalogs, bundles, sweeps, planner decomposition, and recipe-catalog policy remain future-phase work.

## Stack Context

- Root or stacked phase: root serial phase.
- Current predecessor branch or PR: none; Phase 1 was merged into `develop` and no successor branch depended on it.
- Why this base branch is correct: serial human-merge-gate mode starts each phase from updated `develop`; Phase 1 merge notes record that Phase 2 must continue from updated `develop`.
- Retarget/rebase plan after predecessor merge: not applicable because there is no unmerged predecessor.
- Branch cleanup constraints: keep the phase branch until the human-owned PR has merged into `develop` and no successor branch depends on it.

## Source Phase Summary

- Goal: replace generic local path assumptions with backend-neutral capabilities while preserving local stores as inspectable reference implementations.
- Required scope:
  - Break generic `RunStore` and `StageContext` path-shaped contracts.
  - Split store-facing behavior into focused capability protocols for durable run-state documents, artifact payloads, logs, workspace/temp access, and explicit local-path helpers.
  - Reserve the lock capability boundary only; Phase 4 owns the concrete lock protocol, implementation, docs, and tests.
  - Redefine `StageContext` as a narrow stage-author facade with config, input/output helpers, artifact save/register/load helpers, and explicitly named local workspace helpers.
  - Remove generic `StageContext` access to run-store and artifact-store internals.
  - Make `ArtifactStore` explicitly run-scoped and remove `run_id` from artifact-store operations.
  - Add `loom.artifacts.ArtifactAddress` as an immutable cross-run `(run_id, artifact_id)` value object while keeping `ArtifactRef.artifact_id` run-local.
  - Rename ambiguous run-store metadata APIs to distinguish the whole run document from nested user metadata.
  - Update `docs/structure.md`, `docs/features/artifacts.md`, `docs/features/run-store.md`, and `docs/features/pipeline.md`.
- Required checkpoints:
  - Capability protocols exist before local implementations and callers are rewritten.
  - Local stores remain inspectable through ordinary run directories and explicit local helpers.
  - Stage author helpers cover existing supported stage workflows without direct store handles.
  - Tests prove generic protocols no longer require local `Path` return values or `run_id` artifact operations.
- Acceptance criteria:
  - Store protocol tests no longer require generic implementations to return local `Path` values.
  - Local stores still create an ordinary inspectable run directory.
  - Local artifact IDs remain human-readable and run-local.
  - Catalog/bundle-facing references can carry `ArtifactAddress`.
  - No code outside explicit local-store helpers depends on the old `read_run_metadata()` semantics.
  - Project stages cannot mutate durable run state except through stage-author helpers explicitly exposed on `StageContext`.

## Current Source And Harness Findings

- `src/loom/pipeline/stores/run_store.py` currently defines one broad `RunStore` protocol with local `Path` methods such as `create_run()`, `open_run()`, `get_run_dir()`, `get_stage_dir()`, `get_artifact_root()`, `get_stage_artifact_dir()`, `get_config_path()`, `get_provenance_path()`, and `get_stage_log_path()`.
- `src/loom/pipeline/stores/local_runs.py` uses those path methods as the local reference implementation and currently names the whole `run.json` wrapper `read_run_metadata()` / `write_run_metadata()`.
- `src/loom/pipeline/stores/artifact_store.py` currently requires `run_id` on `save()` and `register()` even though `LocalArtifactStore` is constructed with one run's artifact root.
- `src/loom/pipeline/stores/local_artifacts.py` ignores run identity in layout after validation and writes human-readable `stage/output` artifact IDs under a run-scoped root.
- `src/loom/pipeline/context.py` currently exposes `run_dir`, `stage_dir`, direct `run_store`, direct `artifact_store`, `output_path()`, `save_artifact()`, and `register_artifact()` to project stages.
- `tests/support/pipeline_execution_stages.py` includes a dummy consumer stage that directly calls `context.artifact_store.load(...)`, proving the current stage contract leaks the store.
- `src/loom/pipeline/execution/runner.py` constructs `LocalArtifactStore` from `run_store.get_artifact_root(run_id)`, passes direct stores into `StageContext`, and uses run-store path helpers for stage directories and logs.
- Planner/resume tests seed reusable artifacts through `LocalArtifactStore(run_store.get_artifact_root("run1"))` and call artifact-store methods with `run_id`; these tests will need run-scoped helper updates.
- `tests/contracts/test_store_contract.py` currently verifies the broad path-shaped protocols with dummy stores, so it is the main contract suite to rewrite around capability segregation.
- `tests/integration/pipeline/test_local_stores.py` intentionally asserts concrete local files and paths. Those checks should remain, but they should target `LocalRunStore` explicit local helpers rather than generic protocol obligations.
- Package API tests in `tests/package/test_pipeline_store_api.py`, `tests/package/test_pipeline_api.py`, and `tests/package/test_public_api.py` will need stable export updates for any new capability protocols and `ArtifactAddress`.
- Phase 1's optional dependency split is present in `Makefile`, `tools/test_harness/cli.py`, and `tests/README.md`; Phase 2 should preserve those validation surfaces.

## In-Scope Work

- Introduce focused store capability protocols in `loom.pipeline.stores`, keeping names and module placement aligned with the existing source-tree boundaries.
- Keep `LocalRunStore` as the inspectable local implementation that can satisfy multiple capabilities and expose explicit local-only path helpers.
- Replace generic path-returning `RunStore` requirements with narrower state/document, artifact-index, config/provenance document, log, workspace/temp, and explicit local-helper surfaces.
- Reserve a lock-capability boundary as a protocol placeholder or documented extension point only if needed for capability composition; do not define concrete lock behavior.
- Rename run metadata APIs so the full `run.json` wrapper is read through a run-document method and nested user-authored metadata is read through a user-metadata method.
- Make `ArtifactStore` run-scoped by removing `run_id` from generic `save()`, `register()`, path allocation, and validation operations.
- Update `LocalArtifactStore` construction and tests so the run-scoped root remains explicit while saved refs keep `artifact_id` shaped like `stage/output`.
- Add immutable `ArtifactAddress` in `loom.artifacts` with `run_id` and `artifact_id`, plain-data serialization, validation, and public exports.
- Redesign `StageContext` as a stage-author facade: config and metadata access, declared output validation, artifact save/register/load helpers, declared local output/workspace path helpers, and no direct generic store attributes.
- Update runner, planner/resume helpers, dummy stages, and tests to depend on stage/context and capability methods rather than broad store internals.
- Update docs that define the changed contracts: `docs/structure.md`, `docs/features/artifacts.md`, `docs/features/run-store.md`, and `docs/features/pipeline.md`.

## Out-of-Scope Work

- No concrete lock protocol, local lock files, stale-lock cleanup, distributed lock semantics, or lock tests; Phase 4 owns those.
- No runtime/resource models, event models, append-only event JSONL, or blocked descendant outcome persistence.
- No stage factory block, constructor kwargs, stage target import policy redesign, or semantic fingerprint policy change.
- No planner policy decomposition, `PlanExplanation`, CLI diagnostics, or planning behavior changes beyond adapting to the run-scoped artifact store and capability method names.
- No runner lifecycle decomposition beyond the minimal caller updates required for this contract break.
- No remote artifact store or run-store implementation, object-store URI backend, subprocess/SLURM/container executor behavior, run catalog, bundle, sweep, retry, timeout, cleanup, or plugin discovery.
- No embedding run identity into `ArtifactRef.artifact_id`; cross-run identity belongs only to `ArtifactAddress`.
- No compatibility promise for removed pre-v1 local path or metadata names except where a short internal migration shim is explicitly chosen in the refine pass.
- No product-code implementation in this draft planning pass.

## Assumptions

- The branch starts from `develop` at `617e53f9ddf96ccea7aaa00a8f0776db7ae3652f`, with Phase 1 already merged.
- Breaking pre-v1 API changes are allowed by the source plan, so the implementation can remove or rename old generic store/context APIs rather than preserving compatibility indefinitely.
- Local path helpers remain supported on explicit local-only types because inspectable local directories are still a reference behavior.
- Stage authors still need a way to write large files manually, but that access should be named as local workspace/output access and should not imply a generic remote-store path contract.
- Stage authors still need managed artifact loading for inputs; this should be through `StageContext` artifact helpers rather than `context.artifact_store`.
- Artifact stores remain run-scoped; cross-run cache reuse remains out of scope.
- The refine pass should decide exact protocol names and any temporary alias policy after checking import impact, but it must not reopen the closed architecture decisions.

## Decision-Complete Contract

The refine pass must fill in exact names and method signatures before implementation. These draft-level decisions are fixed:

- Generic store protocols must not require local `Path` return values.
- Any local `Path` return methods must live on explicit local-only helpers or local implementations, with names that signal local filesystem behavior.
- `ArtifactStore.save()` and `ArtifactStore.register()` must not accept `run_id`; the store instance is bound to one run at construction or runner setup time.
- `ArtifactRef.artifact_id` remains run-local. Cross-run references use `ArtifactAddress(run_id, artifact_id)`.
- `StageContext` must not expose direct `run_store` or `artifact_store` attributes to project stages.
- `StageContext` must expose enough stage-author helpers to preserve supported local execution workflows: reading `stage_config`, inspecting inputs, saving/loading/registering artifacts, validating declared outputs, and obtaining explicitly local output/workspace paths when local behavior is intentional.
- The old `read_run_metadata()` name must not remain the generic way to read the full run wrapper. Public/store-facing names must distinguish full run documents from nested user metadata.
- The local run directory remains inspectable through ordinary files. Generic capability interfaces describe state, artifacts, logs, and workspace needs without requiring remote backends to fake local paths.
- Concrete lock behavior is explicitly deferred to Phase 4.

## Design Impact

- Maintainability: smaller capability protocols should reduce broad dummy implementations and prevent every caller from depending on the full local run-store surface.
- Extensibility: remote stores, subprocess workers, and future container/cluster executors can implement honest capabilities without fabricating shared local paths.
- Domain neutrality: all changes are about generic run state, artifact payloads, logs, workspace access, and stage-author APIs; no domain artifact types or stage subclasses are introduced.
- Source-tree boundaries: artifact identity stays in `loom.artifacts`; store capability protocols and local implementations stay under `loom.pipeline.stores`; stage-author behavior stays in `loom.pipeline.context`; execution code only adapts to the new boundaries.

## Future Compatibility

- Phase 3 can add stage factories without also fixing stage context leakage.
- Phase 4 can attach a concrete lock protocol to the reserved store capability boundary without undoing Phase 2 store segregation.
- Phase 5 can decompose planner policy against run-scoped artifact stores and capability-shaped state access.
- Phase 7 can decompose runner lifecycle around established context, store, artifact, and local-helper boundaries instead of carrying local path assumptions forward.
- Future catalogs, bundles, and run comparisons can use `ArtifactAddress` for cross-run identity without changing run-local artifact IDs or artifact-index keys.
- Remote stores can choose URI or staged-file capabilities later while local stores remain inspectable.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep broad `RunStore` returning local `Path` values | This is the core Phase 2 problem and would force remote stores or workers to fake local filesystem semantics. |
| Keep direct `context.run_store` and `context.artifact_store` for convenience | It lets project stages mutate durable state or rely on backend internals outside the stage-author contract. |
| Make artifact IDs globally unique by embedding run IDs | The source plan explicitly keeps artifact IDs run-local and uses `ArtifactAddress` for cross-run references. |
| Make `ArtifactStore` multi-run now | Cross-run cache reuse and shared artifact stores are deferred; the current local store is already run-rooted. |
| Implement concrete locks while splitting capabilities | Phase 4 owns lock behavior, tests, and docs; adding it here would expand the PR and blur phase ownership. |
| Remove all local path helpers | Local inspectability is still a reference implementation requirement; the issue is generic protocol leakage, not local helper existence. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Explicit local path helpers remain available on local-only surfaces. | Local stores must remain inspectable and local stages need an intentional manual-write path. | Revisit if generic protocols, docs examples, or project-stage guidance start depending on local helpers as the normal portable path. |
| Lock capability is reserved but concrete behavior is absent. | The source plan assigns concrete locks to Phase 4 to keep Phase 2 focused on store/context boundaries. | Revisit at Phase 4 implementation; stop if Phase 4 would need to undo the Phase 2 capability split. |
| Some caller updates may be mechanical and broad. | The contract break touches runner, planner tests, context tests, support stages, and docs. | Revisit during refinement if the PR grows beyond store/context/artifact boundaries or starts changing planning semantics. |
| Any temporary compatibility aliases for renamed metadata APIs would be transitional. | A short alias may keep internal migration reviewable, but the public contract must move to clear names before v1. | Remove or document aliases in Phase 8 migration notes; revisit earlier if tests or docs keep using the old name. |

## Reviewability

- Expected PR size and shape: moderate contract-breaking PR touching store protocols, local store implementations, `ArtifactAddress`, `StageContext`, runner/planner call sites, focused tests, package exports, and contract docs. Avoid mixing in future lock, event, runtime, planner-decomposition, factory, or runner-lifecycle behavior.
- Files and areas to inspect:
  - `src/loom/artifacts.py`
  - `src/loom/pipeline/context.py`
  - `src/loom/pipeline/stores/run_store.py`
  - `src/loom/pipeline/stores/artifact_store.py`
  - `src/loom/pipeline/stores/local_runs.py`
  - `src/loom/pipeline/stores/local_artifacts.py`
  - `src/loom/pipeline/stores/__init__.py`
  - `src/loom/pipeline/execution/runner.py`
  - `src/loom/pipeline/planning/`
  - `tests/contracts/test_store_contract.py`
  - `tests/unit/loom/test_artifacts.py`
  - `tests/unit/loom/pipeline/test_context.py`
  - `tests/unit/loom/pipeline/stores/test_local_artifacts.py`
  - `tests/unit/loom/pipeline/stores/test_local_runs.py`
  - `tests/unit/loom/pipeline/planning/test_resume.py`
  - `tests/integration/pipeline/test_local_stores.py`
  - `tests/integration/pipeline/test_local_execution.py`
  - package API tests under `tests/package/`
  - `docs/structure.md`, `docs/features/artifacts.md`, `docs/features/run-store.md`, and `docs/features/pipeline.md`
- Scope-control checks: no concrete lock behavior; no event files; no stage factory; no remote backend; no changed fingerprint semantics; no broad runner decomposition; no changes to Phase 1 optional dependency policy except preserving tests.

## Implementation Steps

1. Add or update package/unit/contract tests that describe the target API boundaries: segregated store capabilities do not require local paths, `ArtifactStore` operations are run-scoped, `ArtifactAddress` serializes cleanly, and `StageContext` no longer exposes direct stores.
2. Add `ArtifactAddress` in `src/loom/artifacts.py`, export it from the appropriate public paths, and update package tests.
3. Split store capability protocols in `src/loom/pipeline/stores/run_store.py` and `artifact_store.py`, preserving public imports where appropriate and adding new explicit local-helper protocol names.
4. Update `LocalArtifactStore` to be explicitly run-scoped: constructor/root describes one run's artifact root, `save()` / `register()` / allocation helpers drop `run_id`, and local artifact IDs remain `stage/output`.
5. Update `LocalRunStore` to satisfy the new capability protocols, rename run-document/user-metadata APIs, and keep path methods as local-only helpers.
6. Redesign `StageContext` around stage-author helpers. Move direct artifact loading behind a context method, keep declared output validation, retain managed save/register paths, and rename any local path helpers so local behavior is explicit.
7. Update `PipelineRunner`, planner/resume tests, execution support stages, and store/index call sites to use the new capability methods and context facade without changing planning semantics.
8. Update contract, unit, integration, package, and docs tests to assert the new boundaries while preserving local inspectable file layout evidence.
9. Update `docs/structure.md`, `docs/features/artifacts.md`, `docs/features/run-store.md`, and `docs/features/pipeline.md` for capability ownership, run-scoped artifact stores, `ArtifactAddress`, renamed metadata APIs, and the stage-author context facade.
10. Run focused store/context/artifact tests during implementation, then leave final `make validate-pr` and `make test-summary` evidence for PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_public_api.py`
  - `tests/package/test_pipeline_api.py`
  - `tests/package/test_pipeline_store_api.py`
  - `tests/package/test_import_boundaries.py`
- Required assertions:
  - Public exports include `ArtifactAddress` where documented.
  - Store capability protocol exports are stable and do not import config, CLI, execution internals, or optional dependency paths.
  - `StageContext` remains available from `loom.pipeline`.
  - Import-boundary tests preserve Phase 1 no-extra behavior.

### Unit Suite

- Status: required.
- Expected paths:
  - `tests/unit/loom/test_artifacts.py`
  - `tests/unit/loom/pipeline/test_context.py`
  - `tests/unit/loom/pipeline/stores/test_local_artifacts.py`
  - `tests/unit/loom/pipeline/stores/test_local_runs.py`
  - `tests/unit/loom/pipeline/planning/test_resume.py`
  - `tests/unit/loom/pipeline/planning/test_planner.py`
- Required assertions:
  - `ArtifactAddress` validates non-empty run/artifact IDs, rejects malformed plain data, is immutable, and round-trips through `to_dict()` / `from_dict()`.
  - Run-scoped artifact-store `save()` and `register()` no longer accept or require `run_id`, still write under the run artifact root, still produce `stage/output` artifact IDs, and still enforce local path safety.
  - `StageContext` exposes stage-author helpers for save/register/load and declared local workspace/output paths, rejects undeclared outputs, rejects non-plain config, and has no direct `run_store` or `artifact_store` attributes.
  - Renamed run-document/user-metadata APIs preserve full wrapper and nested metadata behavior without old ambiguous semantics.
  - Planner/resume unit tests adapt to run-scoped artifact stores without changing action selection or conservative reuse decisions.

### Contract Suite

- Status: required.
- Expected paths:
  - `tests/contracts/test_store_contract.py`
- Required assertions:
  - Dummy generic store capabilities can satisfy state/artifact/log/workspace protocols without implementing local `Path` helpers.
  - `LocalRunStore` satisfies the relevant durable state, document, artifact-index, log, workspace, and explicit local-helper protocols.
  - `LocalArtifactStore` satisfies the run-scoped artifact payload protocol.
  - Incomplete implementations are rejected for missing required capability methods.
  - No contract test requires a generic backend to expose `get_run_dir()`, `get_stage_dir()`, `get_artifact_root()`, or `get_stage_artifact_dir()`.

### Integration Suite

- Status: required.
- Expected paths:
  - `tests/integration/pipeline/test_local_stores.py`
  - `tests/integration/pipeline/test_local_execution.py`
  - `tests/integration/pipeline/test_local_execution_resume.py`
  - `tests/integration/pipeline/test_planning_resume.py`
  - `tests/integration/pipeline/test_plan_persistence.py`
- Required assertions:
  - Local run execution still writes inspectable files under `run.json`, `status.json`, `plan.json`, `artifacts.json`, `config/`, `provenance/`, `stages/`, and `artifacts/`.
  - Successful local runs, selector skips, and resume/reuse paths still pass through `PipelineRunner`.
  - Local artifact stores remain run-scoped and integrate with run-store artifact indexes.
  - Stage support code consumes artifacts through `StageContext` helpers, not direct store attributes.
  - Existing config-backed integration tests remain marked/routed through `config-extra` where applicable.

### E2E Suite

- Status: deferred for this phase.
- Expected paths:
  - `tests/e2e/`
- Required assertions or deferral reason: Phase 2 changes internal contracts and local Python API boundaries but does not add a new user-facing CLI workflow. Existing e2e coverage, if present, should continue to pass through final validation; new end-to-end coverage for the completed hardening sequence is assigned to Phase 8.

### Opt-In Suites

- Status: required for existing config-extra preservation; no new opt-in marker is introduced.
- Markers affected:
  - `optional_dependency`
- Required assertions or deferral reason:
  - Config-backed local execution/docs tests continue to run under `make test-config-extra` and `make test-summary`.
  - No `slurm`, `network`, `slow`, remote-store, or lock opt-in suites are added in this phase.

## Risks

- The capability split may grow larger than planned if every caller depends on the old broad `RunStore`. Keep implementation changes mechanical and stop if planner or runner behavior decisions are required.
- The stage-author facade may accidentally become too narrow and break legitimate manual-write/register workflows. Preserve explicit local workspace/output helpers for local behavior.
- Compatibility aliases for renamed metadata APIs could let old ambiguous names survive into docs/tests. The refine pass should set a clear alias policy.
- Artifact-store run scoping can be confused with cross-run artifact identity. Tests should assert both run-local `ArtifactRef.artifact_id` and cross-run `ArtifactAddress`.
- Store capability names can become abstract too early. Prefer names tied to actual Phase 2 behavior and let Phase 4 add concrete lock behavior later.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_public_api.py tests/package/test_pipeline_api.py tests/package/test_pipeline_store_api.py
uv run pytest tests/unit/loom/test_artifacts.py tests/unit/loom/pipeline/test_context.py tests/unit/loom/pipeline/stores
uv run pytest tests/contracts/test_store_contract.py
uv run pytest tests/unit/loom/pipeline/planning/test_resume.py tests/unit/loom/pipeline/planning/test_planner.py
uv run pytest tests/integration/pipeline/test_local_stores.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_planning_resume.py
make test-config-extra
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - Add `ArtifactAddress` and public export/package tests.
  - Split store protocols and update contract tests.
  - Make `LocalArtifactStore` run-scoped and update unit/integration tests.
  - Rename `LocalRunStore` run-document/user-metadata APIs and preserve explicit local helper behavior.
  - Narrow `StageContext` and update runner/support stages.
  - Update docs for changed public boundaries.
- Tests to run with each slice:
  - `uv run pytest tests/unit/loom/test_artifacts.py` after `ArtifactAddress`.
  - `uv run pytest tests/contracts/test_store_contract.py` after protocol changes.
  - `uv run pytest tests/unit/loom/pipeline/stores/test_local_artifacts.py tests/integration/pipeline/test_local_stores.py` after artifact-store changes.
  - `uv run pytest tests/unit/loom/pipeline/test_context.py tests/integration/pipeline/test_local_execution.py` after context/runner updates.
- Decisions the executor must not revisit:
  - Artifact stores are run-scoped.
  - Artifact IDs remain run-local.
  - `ArtifactAddress` owns cross-run identity.
  - Generic stores do not expose local paths.
  - `StageContext` does not expose direct stores.
  - Lock implementation is Phase 4 work.
- Conditions that require stopping for the manager:
  - A required StageContext helper cannot be expressed without re-exposing generic stores.
  - Runner or planner behavior changes beyond caller adaptation are needed.
  - Concrete lock behavior appears necessary to make capability protocols coherent.
  - The PR scope starts including Phase 3, Phase 4, Phase 5, Phase 7, or remote backend work.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in this pass.
- Final phase execution plan: pending refine pass.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- PR preparation: pending.
- Stack maintenance: serial human merge gate active; no successor phase may start until this phase is approved and human-merged into `develop`.
- Remaining blockers: none.
