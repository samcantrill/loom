# Phase 2 Execution Plan: Store, Artifact, And Stage Context Capabilities

## Metadata

- Status: pr_open
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
- Draft pass: completed by `loom_phase_planner` in commit `25d9d2b7eb4c090c263bb04491afab957825e015`.
- Refine pass: completed by `loom_phase_planner` in this pass; implementation-ready handoff decisions are recorded below.
- Setup limitations: none for local planning. The assigned branch/worktree already existed at the requested `develop` base commit; no remote synchronization was needed for this planning pass.
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
- Reserve the lock-capability boundary by keeping lock behavior out of the current store protocols; do not define a concrete lock API, local lock behavior, or lock tests in Phase 2.
- Rename run metadata APIs so the full `run.json` wrapper is read through a run-document method and nested user-authored metadata is read through a user-metadata method.
- Make `ArtifactStore` run-scoped by removing `run_id` from generic `save()`, `register()`, path allocation, and validation operations.
- Update `LocalArtifactStore` construction and tests so the run-scoped root remains explicit while saved refs keep `artifact_id` shaped like `stage/output`.
- Add immutable `ArtifactAddress` in `loom.artifacts` with `run_id` and `artifact_id`, plain-data serialization, validation, and public exports.
- Redesign `StageContext` as a stage-author facade: config and metadata access, declared output validation, artifact save/register/load helpers, declared local output/workspace path helpers, and no direct generic store attributes.
- Update runner, planner/resume helpers, dummy stages, and tests to depend on stage/context and capability methods rather than broad store internals.
- Update docs that define the changed contracts: `docs/structure.md`, `docs/features/artifacts.md`, `docs/features/run-store.md`, and `docs/features/pipeline.md`.

## Out-of-Scope Work

- No concrete lock protocol, local lock files, stale-lock cleanup, distributed lock semantics, lock documentation, or lock tests; Phase 4 owns the concrete lock API, local behavior, tests, and docs.
- No runtime/resource models, runtime event models, append-only event JSONL, event readers, or blocked descendant outcome persistence.
- No stage factory block, constructor kwargs, stage target import policy redesign, or semantic fingerprint policy change.
- No planner decomposition, `PlanExplanation`, CLI diagnostics, planner action/reason semantics, or planning behavior changes beyond adapting to run-scoped artifact stores and renamed capability methods.
- No recipe catalog design, explicit catalog objects, global registry redesign, or recipe discovery policy.
- No runner lifecycle decomposition beyond the minimal caller updates required for this contract break.
- No remote artifact store or run-store implementation, object-store URI backend, remote executor, subprocess/SLURM/container executor behavior, run catalog, bundle, sweep, retry, timeout, cleanup, or plugin discovery.
- No embedding run identity into `ArtifactRef.artifact_id`; cross-run identity belongs only to `ArtifactAddress`.
- No compatibility promise for removed pre-v1 local path, context, artifact-store, or metadata names.
- No product-code implementation in this planning pass.

## Assumptions

- The branch starts from `develop` at `617e53f9ddf96ccea7aaa00a8f0776db7ae3652f`, with Phase 1 already merged.
- Breaking pre-v1 API changes are allowed by the source plan, so the implementation can remove or rename old generic store/context APIs rather than preserving compatibility indefinitely.
- Local path helpers remain supported on explicit local-only types because inspectable local directories are still a reference behavior.
- Stage authors still need a way to write large files manually in the local executor, but that access must be named as local workspace/output access and must not imply a generic remote-store path contract.
- Stage authors still need managed artifact loading for inputs; this should be through `StageContext` artifact helpers rather than `context.artifact_store`.
- Artifact stores remain run-scoped; cross-run cache reuse remains out of scope.
- The executor may make purely mechanical signature adjustments only when Python typing requires them, but it must keep the protocol names, method names, alias policy, and phase boundaries below.

## Decision-Complete Contract

The executor must implement these contracts and must not repartition or rename them while implementing the phase. If a low-level typing issue requires a narrow adjustment, keep the behavior and public names intact and document the adjustment in the PR body.

### Artifact identity

- Add `ArtifactAddress` to `src/loom/artifacts.py` as `@dataclass(frozen=True, slots=True)` with fields `run_id: RunID` and `artifact_id: ArtifactID`.
- `ArtifactAddress.__post_init__()` validates both fields as non-empty strings. It does not validate existence in a store and does not embed URI, artifact type, checksum, producer, or run-directory information.
- `ArtifactAddress.to_dict()` returns exactly `{"run_id": ..., "artifact_id": ...}`. `ArtifactAddress.from_dict(data)` accepts only those two fields, rejects missing or unknown fields, and raises `ArtifactValidationError` for malformed input.
- Export `ArtifactAddress` from `loom.artifacts` and the root `loom` package alongside `ArtifactRef`. Do not add it to `ArtifactRef` and do not change the meaning of `ArtifactRef.artifact_id`.

### Run-store capability protocols

- Keep protocol definitions in `src/loom/pipeline/stores/run_store.py`; export them from `loom.pipeline.stores`.
- Redefine `RunStore` as an aggregate runtime-checkable protocol that inherits only non-local capabilities. It must not include local `Path` helpers.
- Add these runtime-checkable protocols with the listed method groups:
  - `RunLifecycleStore`: `create_run(run_id: str, *, metadata: Mapping[str, PlainData] | None = None) -> None` and `open_run(run_id: str) -> None`.
  - `RunDocumentStore`: `read_run_document(run_id: str) -> dict[str, PlainData]`, `read_run_user_metadata(run_id: str) -> dict[str, PlainData]`, and `write_run_user_metadata(run_id: str, metadata: Mapping[str, PlainData]) -> None`.
  - `RunStatusStore`: existing `read_run_status()` / `write_run_status()` signatures.
  - `RunPlanStore`: existing `read_plan()` / `write_plan()` signatures.
  - `RunArtifactIndexStore`: existing `read_artifact_index()` / `write_artifact_index()` signatures.
  - `RunConfigStore`: existing config snapshot and recipe manifest read/write signatures.
  - `RunProvenanceStore`: existing provenance document read/write signatures.
  - `StageStateStore`: existing stage status, inputs, outputs, fingerprint, failure, and provenance read/write signatures.
  - `StageLogStore`: existing `read_stage_log()` / `write_stage_log()` signatures.
  - `StageWorkspaceStore`: `prepare_stage_workspace(run_id: str, stage_name: str) -> None` only; no generic path return.
- The retained non-local method signatures are:

```python
def read_run_status(run_id: str) -> RunStatusRecord | None: ...
def write_run_status(run_id: str, status: RunStatusRecord) -> None: ...
def read_plan(run_id: str) -> dict[str, PlainData] | None: ...
def write_plan(run_id: str, plan: Mapping[str, PlainData]) -> None: ...
def read_artifact_index(run_id: str) -> dict[str, ArtifactRef]: ...
def write_artifact_index(run_id: str, index: Mapping[str, ArtifactRef]) -> None: ...
def read_config_snapshot(run_id: str, name: str) -> str | None: ...
def write_config_snapshot(run_id: str, name: str, content: str) -> None: ...
def read_recipe_manifest(run_id: str) -> tuple[dict[str, PlainData], ...] | None: ...
def write_recipe_manifest(run_id: str, records: Sequence[Mapping[str, PlainData]]) -> None: ...
def read_provenance_document(run_id: str, name: str) -> dict[str, PlainData] | None: ...
def write_provenance_document(run_id: str, name: str, document: Mapping[str, PlainData]) -> None: ...
def read_stage_status(run_id: str, stage_name: str) -> StageStatusRecord | None: ...
def write_stage_status(run_id: str, stage_name: str, status: StageStatusRecord) -> None: ...
def read_stage_inputs(run_id: str, stage_name: str) -> dict[str, ArtifactRef] | None: ...
def write_stage_inputs(run_id: str, stage_name: str, inputs: Mapping[str, ArtifactRef], *, attempt: int) -> None: ...
def read_stage_outputs(run_id: str, stage_name: str) -> dict[str, ArtifactRef] | None: ...
def write_stage_outputs(run_id: str, stage_name: str, outputs: Mapping[str, ArtifactRef], *, attempt: int) -> None: ...
def read_stage_fingerprint(run_id: str, stage_name: str) -> dict[str, PlainData] | None: ...
def write_stage_fingerprint(run_id: str, stage_name: str, fingerprint: Mapping[str, PlainData], *, attempt: int) -> None: ...
def read_stage_failure(run_id: str, stage_name: str) -> dict[str, PlainData] | None: ...
def write_stage_failure(run_id: str, stage_name: str, failure: Mapping[str, PlainData], *, attempt: int) -> None: ...
def read_stage_provenance(run_id: str, stage_name: str) -> dict[str, PlainData] | None: ...
def write_stage_provenance(run_id: str, stage_name: str, provenance: Mapping[str, PlainData], *, attempt: int) -> None: ...
def read_stage_log(run_id: str, stage_name: str, stream: str) -> str | None: ...
def write_stage_log(run_id: str, stage_name: str, stream: str, content: str) -> None: ...
```

- Add `LocalRunStorePaths` as the only protocol in `run_store.py` that returns local paths. It must include exactly these helpers:

```python
def local_run_dir(run_id: str) -> Path: ...
def local_stage_dir(run_id: str, stage_name: str) -> Path: ...
def local_artifact_root(run_id: str) -> Path: ...
def local_stage_artifact_dir(run_id: str, stage_name: str) -> Path: ...
def local_config_path(run_id: str, name: str) -> Path: ...
def local_provenance_path(run_id: str, name: str) -> Path: ...
def local_stage_log_path(run_id: str, stage_name: str, stream: str) -> Path: ...
def local_stage_workspace_dir(run_id: str, stage_name: str) -> Path: ...
```

- `LocalRunStore` must satisfy `RunStore` and `LocalRunStorePaths`. Its local helper names must replace old generic path helpers in callers and tests.
- Remove `read_run_metadata()` and `write_run_metadata()` instead of keeping compatibility aliases. `read_run_document()` owns the full `run.json` wrapper; `read_run_user_metadata()` / `write_run_user_metadata()` own the nested user metadata mapping.

### Artifact-store contract

- Keep `ArtifactStore` in `src/loom/pipeline/stores/artifact_store.py` as a run-scoped artifact payload protocol.
- `ArtifactStore.save()` signature must drop `run_id` and keep `stage_name`, `name`, `artifact_type`, `codec_key`, `schema_version`, `metadata`, and `fingerprint`.
- `ArtifactStore.register()` signature must drop `run_id`; the protocol-level source parameter is a URI string. `LocalArtifactStore.register()` may accept `str | Path` as a wider local convenience, but generic callers must not require non-local stores to accept `Path`.
- `load()`, `exists()`, `verify_checksum()`, and `validate()` keep their current behavior and signatures except for any import-name fallout.
- The protocol method signatures are:

```python
def save(
    obj: object,
    *,
    stage_name: str,
    name: str,
    artifact_type: str,
    codec_key: str,
    schema_version: int = 1,
    metadata: Mapping[str, PlainData] | None = None,
    fingerprint: str | None = None,
) -> ArtifactRef: ...
def register(
    uri: str,
    *,
    stage_name: str,
    name: str,
    artifact_type: str,
    codec_key: str | None = None,
    schema_version: int = 1,
    metadata: Mapping[str, PlainData] | None = None,
    fingerprint: str | None = None,
    checksum: str | None = None,
    allow_external: bool = False,
) -> ArtifactRef: ...
def load(ref: ArtifactRef, *, expected_type: str | None = None, codec_key: str | None = None) -> object: ...
def exists(ref: ArtifactRef) -> bool: ...
def verify_checksum(ref: ArtifactRef) -> bool: ...
def validate(ref: ArtifactRef, *, expected_type: str | None = None) -> None: ...
```

- `LocalArtifactStore` remains constructed from one run's artifact root. Add local-only helpers `local_stage_dir(stage_name)`, `local_artifact_path(stage_name, name, codec_key)`, and keep `local_path(ref)`; remove `run_id` from local allocation and validation flows.
- Saved and registered refs must keep `artifact_id == f"{stage_name}/{name}"`. Cross-run identity is only `ArtifactAddress(run_id, artifact_id)`.

### StageContext facade

- `StageContext` remains exported from `loom.pipeline`, but its public stage-author surface is limited to identity, plain-data mappings, inputs, declared-output helpers, artifact helpers, and explicitly local path helpers.
- Public attributes may include `run_id`, `stage_name`, `resolved_config`, `stage_config`, `inputs`, `provenance`, and `metadata`. They must not include `run_dir`, `stage_dir`, `run_store`, or `artifact_store`.
- Construction may accept implementation-injected services such as `artifact_store`, `output_specs`, `local_output_dir`, and `local_workspace_dir`, but they must be stored privately or through `InitVar` so the stage-author object has no direct store escape hatches.
- Required methods:
  - `input_artifact(name: str) -> ArtifactRef`
  - `load_input(name: str, *, expected_type: str | None = None, codec_key: str | None = None) -> object`
  - `load_artifact(ref: ArtifactRef, *, expected_type: str | None = None, codec_key: str | None = None) -> object`
  - `save_artifact(name, obj, *, artifact_type, codec_key, schema_version=1, metadata=None, fingerprint=None) -> ArtifactRef`
  - `register_artifact(name, uri: str, *, artifact_type, codec_key=None, schema_version=1, metadata=None, fingerprint=None, checksum=None, allow_external=False) -> ArtifactRef`
  - `register_local_artifact(name, path: str | Path, *, artifact_type, codec_key=None, schema_version=1, metadata=None, fingerprint=None, checksum=None, allow_external=False) -> ArtifactRef`
  - `local_output_path(name: str, *, suffix: str = "") -> Path`
  - `local_workspace_path(*parts: str) -> Path`
- `output_path()` is removed rather than retained as an alias; the replacement name is `local_output_path()` so local filesystem behavior is explicit.
- Artifact helpers must validate declared output `artifact_type`, `codec_key`, and `schema_version` exactly as the current helpers do. `local_output_path()` validates the declared output name and suffix, creates its parent directory, and fails with `PipelineValidationError` if the context lacks local paths. `local_workspace_path()` validates every path part against separators, NUL, and parent traversal, creates the workspace directory, and fails with `PipelineValidationError` if local workspace access is unavailable.
- `load_input()` must fail with `PipelineValidationError` for an unknown input name before calling the store. `load_input()` and `load_artifact()` must fail with `PipelineValidationError` if no artifact store was injected.

### Caller adaptation

- `PipelineRunner` remains the public facade and must not be decomposed. Its changes are limited to using run-store capability methods and explicit local helpers.
- The default local artifact store factory must be wired from `LocalRunStorePaths.local_artifact_root(run_id)`. Local executor log paths must be wired through `local_stage_log_path()`. If a non-local run store is supplied with the current local executor/default local artifact factory, raise `PipelineExecutionError` rather than adding remote-store support.
- Planner and resume call sites may adapt to run-scoped `ArtifactStore` methods and renamed run-store methods only. They must not change plan actions, reasons, conservative reuse semantics, fingerprint semantics, or explanation surfaces.
- Test support stages must consume managed inputs with `context.load_input()` or `context.load_artifact()` and must not access private context store services.

### Lock boundary

- Phase 2 reserves the future lock boundary only by keeping locking out of the aggregate `RunStore` contract and documenting that Phase 4 may add a separate lock capability. Do not add `RunLockStore`, lock tokens, lease records, lock files, stale-lock cleanup, or lock tests in this phase.

## Design Impact

- Maintainability: smaller capability protocols should reduce broad dummy implementations and prevent every caller from depending on the full local run-store surface.
- Extensibility: remote stores, subprocess workers, and future container/cluster executors can implement honest capabilities without fabricating shared local paths.
- Domain neutrality: all changes are about generic run state, artifact payloads, logs, workspace access, and stage-author APIs; no domain artifact types or stage subclasses are introduced.
- Source-tree boundaries: artifact identity stays in `loom.artifacts`; store capability protocols and local implementations stay under `loom.pipeline.stores`; stage-author behavior stays in `loom.pipeline.context`; execution code only adapts to the new boundaries.

## Future Compatibility

- Phase 3 can add stage factories without also fixing stage context leakage.
- Phase 4 can add a separate concrete lock capability without undoing Phase 2 store segregation or changing non-lock protocol names.
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
| Keep `read_run_metadata()`, `write_run_metadata()`, `output_path()`, or old `get_*` path aliases | Phase 2 is the pre-v1 contract break; aliases would let ambiguous metadata and generic path-shaped names survive into tests and docs. |
| Add remote-store, executor, retry, timeout, catalog, or recipe-catalog abstractions while touching stores | Those are future roadmap phases and would make this PR unreviewable as a store/context contract correction. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Explicit local path helpers remain available on local-only surfaces. | Local stores must remain inspectable and local stages need an intentional manual-write path. | Revisit if generic protocols, docs examples, or project-stage guidance start depending on local helpers as the normal portable path. |
| Lock capability is reserved but concrete behavior is absent. | The source plan assigns concrete locks to Phase 4 to keep Phase 2 focused on store/context boundaries. | Revisit at Phase 4 implementation; stop if Phase 4 would need to undo the Phase 2 capability split. |
| Some caller updates may be mechanical and broad. | The contract break touches runner, planner tests, context tests, support stages, and docs. | Revisit during refinement if the PR grows beyond store/context/artifact boundaries or starts changing planning semantics. |
| No compatibility aliases are kept for renamed metadata, local path, or context helper names. | The source plan allows breaking pre-v1 APIs and clear names are the purpose of this phase. | Revisit only if a package import cycle or impossible staged migration blocks implementation; otherwise old names must disappear from runtime, tests, and docs. |

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
  - `tests/unit/loom/pipeline/planning/test_planner.py`
  - `tests/unit/loom/pipeline/executors/test_local_executor.py`
  - `tests/integration/pipeline/test_local_stores.py`
  - `tests/integration/pipeline/test_local_execution.py`
  - `tests/integration/pipeline/test_local_execution_resume.py`
  - `tests/integration/pipeline/test_planning_resume.py`
  - `tests/integration/pipeline/test_plan_persistence.py`
  - package API tests under `tests/package/`
  - `docs/structure.md`, `docs/features/artifacts.md`, `docs/features/run-store.md`, and `docs/features/pipeline.md`
- Scope-control checks: no concrete lock behavior; no runtime/event files; no stage factory or fingerprint policy; no planner decomposition or `PlanExplanation`; no recipe catalogs; no remote backend or executor; no retry/timeout behavior; no broad runner lifecycle decomposition; no changes to Phase 1 optional dependency policy except preserving tests.

## Implementation Steps

1. Add `ArtifactAddress` tests first in `tests/unit/loom/test_artifacts.py` and package export assertions in `tests/package/test_public_api.py`. Then implement the frozen value object and exports from `loom.artifacts` and `loom`.
2. Rewrite `tests/contracts/test_store_contract.py` around the refined protocol names. Use dummy generic implementations that do not implement local path helpers, and separate assertions for `LocalRunStorePaths`.
3. Split `src/loom/pipeline/stores/run_store.py` into the capability protocols listed above. Redefine `RunStore` as the non-local aggregate. Update `src/loom/pipeline/stores/__init__.py` and `tests/package/test_pipeline_store_api.py` with the new exports.
4. Update `LocalRunStore` to implement the new method names: `create_run()` / `open_run()` return no generic path value, metadata access becomes `read_run_document()` plus user-metadata methods, and old `get_*` path helpers become explicit `local_*` helpers. Keep the on-disk layout unchanged.
5. Update `ArtifactStore` and `LocalArtifactStore` to be run-scoped. Remove `run_id` from `save()`, `register()`, local allocation, and stage-directory helpers. Keep `stage/output` artifact IDs, file URI behavior, checksum validation, and local path safety.
6. Narrow `StageContext`. Add input and artifact loading helpers, replace `output_path()` with `local_output_path()`, add `local_workspace_path()`, and ensure direct store/path attributes are absent from the public object. Keep declared-output validation behavior.
7. Adapt `PipelineRunner`, local executor request construction, planner/resume helpers, and tests to use run-scoped artifact stores, `LocalRunStorePaths` for local-only paths, renamed metadata APIs, and the context facade. Do not change plan actions, plan reasons, fingerprints, or runner lifecycle responsibilities.
8. Update support stages and examples in tests so consumers use `context.load_input()` or `context.load_artifact()` instead of `context.artifact_store`.
9. Update unit, integration, contract, and package tests to assert the new boundaries while preserving local inspectable file layout evidence.
10. Update `docs/structure.md`, `docs/features/artifacts.md`, `docs/features/run-store.md`, and `docs/features/pipeline.md` for capability ownership, run-scoped artifact stores, `ArtifactAddress`, renamed metadata APIs, explicit local helpers, and the stage-author context facade.
11. Run focused store/context/artifact/planning tests during implementation. Leave final `make validate-pr` and `make test-summary` evidence for PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_public_api.py`
  - `tests/package/test_pipeline_api.py`
  - `tests/package/test_pipeline_store_api.py`
  - `tests/package/test_import_boundaries.py`
- Required assertions:
  - Root and `loom.artifacts` exports include `ArtifactAddress` next to `ArtifactRef`.
  - `loom.pipeline.stores.__all__` includes `RunLifecycleStore`, `RunDocumentStore`, `RunStatusStore`, `RunPlanStore`, `RunArtifactIndexStore`, `RunConfigStore`, `RunProvenanceStore`, `StageStateStore`, `StageLogStore`, `StageWorkspaceStore`, `LocalRunStorePaths`, `RunStore`, `ArtifactStore`, `LocalRunStore`, and `LocalArtifactStore`.
  - Store capability protocol exports are stable and do not import config, CLI, execution internals, executors, optional dependency paths, or project code.
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
  - Run-scoped artifact-store `save()` and `register()` no longer accept or require `run_id`, still write under the run artifact root, still produce `stage/output` artifact IDs, and still enforce local path safety through local-only helpers.
  - `LocalArtifactStore.local_stage_dir()`, `local_artifact_path()`, and `local_path()` cover local path needs without adding path methods to `ArtifactStore`.
  - `StageContext` exposes `input_artifact()`, `load_input()`, `load_artifact()`, `save_artifact()`, `register_artifact()`, `register_local_artifact()`, `local_output_path()`, and `local_workspace_path()`, rejects undeclared outputs and unknown inputs, rejects non-plain config, and has no direct `run_dir`, `stage_dir`, `run_store`, `artifact_store`, or `output_path` attribute.
  - Renamed run-document/user-metadata APIs preserve full wrapper and nested metadata behavior; old `read_run_metadata()` / `write_run_metadata()` names are absent from runtime and tests.
  - `LocalRunStore.local_*` helpers return the same inspectable paths that old `get_*` helpers exposed, while old `get_*` names are absent from generic protocols and tests.
  - Planner/resume unit tests adapt to run-scoped artifact stores without changing action selection or conservative reuse decisions.

### Contract Suite

- Status: required.
- Expected paths:
  - `tests/contracts/test_store_contract.py`
- Required assertions:
  - Dummy generic store capabilities can satisfy `RunStore`, `RunLifecycleStore`, `RunDocumentStore`, state, artifact-index, log, and workspace protocols without implementing local `Path` helpers.
  - `LocalRunStore` satisfies `RunStore` and `LocalRunStorePaths`; dummy generic stores must not need `LocalRunStorePaths`.
  - `LocalArtifactStore` satisfies the run-scoped artifact payload protocol.
  - Incomplete implementations are rejected for missing required capability methods.
  - No contract test requires a generic backend to expose `get_run_dir()`, `get_stage_dir()`, `get_artifact_root()`, `get_stage_artifact_dir()`, `local_run_dir()`, `local_stage_dir()`, `local_artifact_root()`, or `local_stage_artifact_dir()` unless the test is explicitly about `LocalRunStorePaths`.

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
  - `PipelineRunner` still handles successful local runs, selector skips, failed stages, and resume/reuse with the same plan actions and status documents.
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
  - No `slurm`, `network`, `slow`, remote-store, remote-executor, retry/timeout, or lock opt-in suites are added in this phase.

## Risks

- The capability split may grow larger than planned if every caller depends on the old broad `RunStore`. Keep implementation changes mechanical and stop if planner or runner behavior decisions are required.
- The stage-author facade may accidentally become too narrow and break legitimate manual-write/register workflows. Preserve explicit local workspace/output helpers for local behavior.
- Removing compatibility aliases may touch many call sites at once. Keep the migration mechanical and verify old ambiguous names are absent from runtime, tests, and docs.
- Artifact-store run scoping can be confused with cross-run artifact identity. Tests should assert both run-local `ArtifactRef.artifact_id` and cross-run `ArtifactAddress`.
- Store capability names can become abstract too early. Use only the protocol names in this plan, keep locking absent, and let Phase 4 add concrete lock behavior later.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_public_api.py tests/package/test_pipeline_api.py tests/package/test_pipeline_store_api.py
uv run pytest tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/test_artifacts.py tests/unit/loom/pipeline/test_context.py tests/unit/loom/pipeline/stores
uv run pytest tests/contracts/test_store_contract.py
uv run pytest tests/unit/loom/pipeline/planning/test_resume.py tests/unit/loom/pipeline/planning/test_planner.py
uv run pytest tests/unit/loom/pipeline/executors/test_local_executor.py
uv run pytest tests/integration/pipeline/test_local_stores.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py
make test-config-extra
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - Slice 1: `ArtifactAddress` plus root/artifact package exports and tests.
  - Slice 2: run-store capability protocols and store package export/contract tests.
  - Slice 3: `LocalRunStore` method rename, local path helpers, run-document/user-metadata tests, and caller updates that only touch method names.
  - Slice 4: run-scoped `ArtifactStore` / `LocalArtifactStore` and artifact-store unit/integration tests.
  - Slice 5: `StageContext` facade, support-stage updates, local executor/runner path wiring, and context/execution tests.
  - Slice 6: docs for changed public boundaries and final focused suite sweep.
- Tests to run with each slice:
  - Slice 1: `uv run pytest tests/unit/loom/test_artifacts.py tests/package/test_public_api.py`
  - Slice 2: `uv run pytest tests/contracts/test_store_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py`
  - Slice 3: `uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py tests/unit/loom/pipeline/planning/test_resume.py tests/unit/loom/pipeline/planning/test_planner.py`
  - Slice 4: `uv run pytest tests/unit/loom/pipeline/stores/test_local_artifacts.py tests/integration/pipeline/test_local_stores.py`
  - Slice 5: `uv run pytest tests/unit/loom/pipeline/test_context.py tests/unit/loom/pipeline/executors/test_local_executor.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py`
  - Slice 6: package, contract, store/context/planning integration commands listed above, then PR preparation runs `make validate-pr` and `make test-summary`.
- Decisions the executor must not revisit:
  - Artifact stores are run-scoped.
  - Artifact IDs remain run-local.
  - `ArtifactAddress` owns cross-run identity.
  - Generic `RunStore` and `ArtifactStore` protocols do not expose local path return values.
  - Local path helpers use `local_*` names and live only on explicit local surfaces.
  - `StageContext` does not expose direct stores, `run_dir`, `stage_dir`, or `output_path()`.
  - Old `read_run_metadata()`, `write_run_metadata()`, and `get_*` path helper aliases are not kept.
  - Phase 4 owns every concrete lock API, implementation, test, and doc.
  - Runtime/events, stage factory/fingerprints, planner decomposition, recipe catalogs, runner lifecycle decomposition, remote stores/executors, retry, and timeout are out of scope.
- Conditions that require stopping for the manager:
  - A required StageContext helper cannot be expressed without re-exposing generic stores.
  - Runner or planner behavior changes beyond caller adaptation are needed.
  - Concrete lock behavior appears necessary to make capability protocols coherent.
  - A package import cycle forces changing the agreed export surface or adding optional dependencies.
  - The PR scope starts including Phase 3, Phase 4, Phase 5, Phase 7, recipe catalog, remote backend, executor, retry, or timeout work.

## Refinement And Review Budget Status

- Phase implementation refinement: used in this pass
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in commit `25d9d2b7eb4c090c263bb04491afab957825e015`.
- Final phase execution plan: refined in this pass; ready for `loom_phase_executor`.
- Implementation summary:
  - Slice 1: `ArtifactAddress` and public exports.
  - Slice 2: run-store protocol capability split and exports.
  - Slice 3: local run API migration and run-document/user-metadata naming support.
  - Slice 4: run-scoped `ArtifactStore`/`LocalArtifactStore` updates.
  - Slice 5: `StageContext` facade and local runtime path wiring.
- Implementation validation:
  - Slice 1-5 were validated during executor work using the slice matrix in this plan.
  - Refinement targeted checks:
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_public_api.py tests/package/test_import.py tests/package/test_pipeline_api.py tests/package/test_pipeline_store_api.py tests/contracts/test_store_contract.py tests/unit/loom/test_artifacts.py tests/unit/loom/pipeline/test_context.py tests/unit/loom/pipeline/stores/test_local_artifacts.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/unit/loom/pipeline/planning/test_resume.py tests/unit/loom/pipeline/planning/test_planner.py tests/unit/loom/pipeline/executors/test_local_executor.py` passed: 69 passed.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_local_stores.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py` passed: 6 passed, 2 skipped under the default environment.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/execution/test_outputs.py tests/unit/loom/pipeline/executors/test_local_executor.py tests/contracts/test_store_contract.py tests/unit/loom/pipeline/stores/test_local_runs.py` passed: 23 passed.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_store_errors.py tests/package/test_pipeline_store_api.py` passed: 5 passed.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` passed.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pyright` passed: 0 errors.
    - `make test-no-extra` passed: 308 passed, 9 skipped.
    - `make test-config-extra` passed: 102 passed, 309 deselected.
    - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed, including Ruff, Pyright, default harness, config-extra harness, and package build. A first sandboxed `make validate-pr` attempt without the cache override failed before validation because uv could not create a temporary file under read-only `~/.cache/uv`.
- Refinement summary:
  - Fixed typed local-helper usage in `PipelineRunner` so stdout, stderr, and traceback paths flow through `LocalRunStorePaths` after the generic `RunStore` split.
  - Narrowed `LocalRunStore.read_run_user_metadata()` typing to the nested user metadata mapping.
  - Updated stale tests that still passed removed `run_id` arguments to run-scoped `LocalArtifactStore.save()`.
  - Updated store export expectations for the new capability protocols.
  - Replaced a stale `context.output_path()` docs example with `context.local_output_path()`.
- PR preparation: complete.
- Stack maintenance: serial human merge gate active; no successor phase may start until this phase is approved and human-merged into `develop`.
- Residual risks: none identified in this refinement pass. Phase 4 still owns concrete lock behavior; Phase 3+ work remains unstarted.
- Remaining blockers: none.

## PR Preparation Notes

- PR body artifact: `docs/phases/v0-post-store-capabilities-pr-body.md`
- PR body draft pass: complete in this PR-preparation pass.
- PR body refine pass: complete in this PR-preparation pass.
- Final diff scope check:
  - Diff against `develop` is limited to Phase 2 store protocols, local stores, `ArtifactAddress`, `StageContext`, runner/planner call-site adaptation, focused tests, support stages, and affected docs.
  - No concrete lock protocol, runtime/event foundations, stage factory or fingerprint policy change, planner decomposition, recipe catalog work, remote backend, executor expansion, retry/timeout behavior, or Phase 3 implementation was added.
- PR validation:
  - `git diff --check develop...HEAD` passed.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed: Ruff passed, Pyright reported 0 errors, default harness passed with 308 passed and 9 skipped, config-extra harness passed with 102 passed and 309 deselected, and `uv build` produced source and wheel distributions.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed and wrote `build/test-summary.md`.
  - `gh pr checks 16` reported `checks pass` in 36s.
- Suite evidence from `make test-summary`:
  - package: passed, 32 passed and 1 skipped.
  - unit: passed, 255 passed and 1 skipped.
  - contract: passed, 13 passed and 1 skipped.
  - integration: passed, 8 passed and 5 skipped.
  - e2e: passed, 1 passed.
  - config-extra: passed, 102 passed and 309 deselected.
- PR creation: complete.
- PR URL: https://github.com/samcantrill/loom/pull/16
- PR creation command: `gh pr create --base develop --head codex/v0-post-store-capabilities --title "Phase 2: Store, Artifact, and Stage Context Capabilities" --body-file docs/phases/v0-post-store-capabilities-pr-body.md`
- PR target verification: `gh pr view 16 --json baseRefName,headRefName,state,url` returned `{"baseRefName":"develop","headRefName":"codex/v0-post-store-capabilities","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/16"}`.
- GitHub checks: `gh pr checks 16` reported `checks pass` in 36s.
- Review notification: `gh pr edit 16 --add-reviewer samcantrill` failed with GitHub GraphQL project-card deprecation output; `gh pr view 16 --json reviewRequests,author,url` showed PR author `samcantrill` and no recorded review requests, so fallback comment `https://github.com/samcantrill/loom/pull/16#issuecomment-4369304096` was posted mentioning `@samcantrill`.
- Serial merge gate state: active. Codex must not approve or merge this PR, and Phase 3 must not start until this PR is human-approved and human-merged into `develop`.
