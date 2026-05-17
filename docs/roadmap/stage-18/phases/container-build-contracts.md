# Phase 1 Execution Plan: Shared Build Contracts And Config Semantics

## Metadata

- Status: implemented; PR pending
- Feature focus: HPC Container Execution
- PR title: `HPC Container Execution - Phase 1: Container Build Contracts`
- Branch: `codex/container-build-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/container-build-contracts`
- Phase execution plan path: `docs/roadmap/stage-18/phases/container-build-contracts.md`
- Full plan: `docs/roadmap/stage-18/implementation-plan.md`
- Source phase: Stage 18 Phase 1, `container-build-contracts`
- Stack predecessor: none
- Base branch: `origin/develop` at `7367e39`
- Target branch: `develop`
- Merge eligibility: root phase; merge to `develop` after validation and automated review
- Workflow path: expanded path
- Successor dependency notes: Phase 2 depends on this phase's shared build records and namespace contract.
- Plan quality gate: passed in the implementation plan on 2026-05-17
- Plan quality gate loop budget: consumed before phase code changes; no additional plan-quality review assigned here
- Draft pass: completed by manager before implementation
- Refine pass: completed in this planning pass because this phase creates public adapter contracts
- Setup limitations: Stage 18 planning artifacts were copied from the dirty control checkout because Stage 18 is not yet on `develop`; implementation starts from current `origin/develop`.
- Blockers: none

## Objective

Establish the shared `container_build` contract for named Docker and Apptainer build targets without running build commands. This phase adds import-light build records, output refs, policy validation, deterministic build-key summaries, descriptor namespace claims, and tests for whole-namespace replacement semantics so later phases can implement local builders, Apptainer execution, SLURM composition, and diagnostics without inventing public config behavior.

## Full-Plan Context

Stage 18 has five phases. Phase 1 creates the build contract and config semantics. Phase 2 uses these records to implement local fake/Docker/Apptainer builders. Phase 3 adds direct Apptainer/Singularity execution. Phase 4 composes resolved Apptainer commands with existing SLURM dry-run/live paths. Phase 5 adds selected preflight, docs, examples, and optional smoke hooks.

Future-phase work that must stay out of this PR includes Docker or Apptainer command execution, local build-service orchestration, direct Apptainer executor behavior, SLURM script wrapping, preflight checks, docs broadening, image conversion, registry auth, global cache, image locks, path translation, and MPI/rank policy.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: Stage 17 and Stage 19 are already merged on `origin/develop`; Phase 1 has no earlier Stage 18 predecessor.
- Retarget/rebase plan after predecessor merge: not applicable for the root phase.
- Branch cleanup constraints: do not delete `codex/container-build-contracts` while successor branches depend on it.

## Source Phase Summary

- Goal: establish `container_build` contracts and whole-namespace replacement behavior.
- Required scope: shared build records, build source/output/policy validation, build request/result records, redacted metadata projection, deterministic build-key summaries, descriptor namespace claims, and focused package/unit/contract tests.
- Required checkpoints: Stage 17 source refresh, no duplicate shared package, no runtime command imports in shared records, `container_build` separate from Stage 17 `container`, and profile merge tests proving namespace replacement semantics.
- Acceptance criteria: records validate, serialize, redact, reject invalid source/policy/output combinations, and remain generic enough for Docker and Apptainer builders in Phase 2.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/pipeline/executors/containers.py` owns Stage 17 import-light shared container execution records and should be extended rather than duplicated.
  - `src/loom/pipeline/executors/docker/` owns Docker runtime command/executor behavior; Phase 1 may define shared build records but must not add Docker build execution there.
  - `src/loom/pipeline/runtime/capabilities.py` owns built-in executor descriptors and namespace claims.
  - `src/loom/pipeline/runtime/profiles.py` already preserves adapter namespaces as opaque plain data and applies whole-namespace replacement through mapping update semantics.
  - `src/loom/pipeline/runtime/options.py` owns run/stage adapter option parsing as plain data.
- Existing tests or harness behavior:
  - `tests/unit/loom/pipeline/executors/test_containers.py` covers Stage 17 shared container records and import boundaries.
  - `tests/unit/loom/pipeline/test_runtime_profiles.py` and `tests/contracts/test_runtime_profiles_contract.py` cover profile namespace normalization and merge behavior.
  - `tests/unit/loom/pipeline/test_executor_capabilities.py` and `tests/contracts/test_executor_capabilities_contract.py` cover descriptor claims and unclaimed namespace diagnostics.
  - `tests/package` covers import surfaces and optional dependency boundaries.
- Import-boundary or dependency constraints: shared build records must not import Docker, Apptainer, SLURM, diagnostics, CLI, config composition, plugin discovery, subprocess runners, optional SDKs, registry clients, or network behavior.

## In-Scope Work

- Extend `loom.pipeline.executors.containers` with shared `container_build` value records and helpers.
- Define build source, output ref, policy, target, request, result, command projection, failure, and build-key summary records with schema-versioned plain-data serialization.
- Support Docker image output refs and Apptainer SIF output refs without runtime-specific command execution.
- Validate target names, runtime kinds, source kinds, local paths/URIs, output kinds, output refs, policy names, redaction-safe metadata, and unknown fields.
- Add deterministic build-key summary helpers that hash authored source/output/policy/options without fetching network-backed sources.
- Preserve and test adapter namespace replacement for `container_build` at run/profile and stage-option levels.
- Update executor descriptors so Docker, Apptainer, Singularity, and SLURM modes claim the namespaces needed by Stage 18 without importing runtime behavior.
- Add focused examples or test fixtures showing named build targets and complete namespace override behavior.

## Out-of-Scope Work

- Running Docker or Apptainer build commands.
- Local build-service execution, fake service behavior, stale-file checks, or output existence decisions.
- Direct Apptainer/Singularity stage execution.
- SLURM plus Apptainer dry-run/live composition.
- Preflight check IDs or diagnostics execution.
- Per-target deep merge, deletion, global cache, image locks, registry/auth helpers, automatic conversion, external/site build services, path translation, and MPI/rank orchestration.

## Assumptions

- `container_build` uses existing opaque adapter namespace replacement semantics; per-target overlay is deferred.
- Build evidence is run-local by default; output refs identify Docker images or Apptainer SIF paths and are not committed stage outputs.
- Docker and Apptainer command semantics remain adapter-specific in Phase 2.
- The landed Stage 17 `containers.py` module is the correct shared executor-owned extension point.

## Scope Contract

Shared build records must be frozen, deterministic, plain-data value objects with strict unknown-field rejection and redacted projections. They may describe Docker and Apptainer build inputs and outputs, but they must not execute commands or import runtime-specific command modules.

Target serialized shapes:

- `ContainerBuildSource`: `{kind, path, uri, context_path, recipe_path, metadata}` with exactly the fields required by the selected source kind.
- `ContainerBuildOutputRef`: `{kind, reference, path, metadata}` where Docker image outputs use `kind: docker_image` and `reference`, and Apptainer outputs use `kind: apptainer_sif` and `path`.
- `ContainerBuildPolicy`: `{mode}` with `if_stale`, `always`, and `never`.
- `ContainerBuildTarget`: `{name, runtime, source, output, policy, build_args, metadata}`.
- `ContainerBuildRequest`: `{target, requested_by, build_key}`.
- `ContainerBuildResult`: `{target_name, status, output, build_key, command, evidence, failure}`.
- Redacted command projection stores argv length, command name, redacted argv, environment key names, and redacted build args only.

Adapter namespace contract:

- `adapter_options.container_build` owns build targets and local build-service options.
- Profile shorthand `container_build:` normalizes into `adapter_options.container_build`.
- Merge behavior replaces the entire `container_build` namespace when an explicit source provides that namespace; this phase does not merge individual targets.
- `container_build` is separate from Stage 17 `container` execution options.
- Docker, Apptainer, Singularity, and SLURM descriptors claim only namespaces they consume; unclaimed namespace diagnostics must remain payload-inspection-free.

## Design Impact

- Maintainability: later build adapters consume typed shared records instead of repeatedly parsing raw dictionaries.
- Extensibility: future external/site build services can implement the same request/result contract without moving command behavior into shared records.
- Domain neutrality: records describe generic build targets and output refs, not domain-specific package or environment recipes.
- Source-tree boundaries: executor-owned records stay below diagnostics, CLI, stores, plugin discovery, and runtime command modules.

## Future Compatibility

- Stage 19 can classify build failure, launch failure, process failure, scheduler failure, and worker failure separately using these records.
- Stage 20 can project build request/result facts into runtime events without parsing command logs.
- Stage 21 can distinguish run-local build evidence from reusable output refs during cleanup planning.
- A future path-translation, image-lock, external builder, or registry-auth stage can extend records through explicit schema-versioned changes.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put build targets inside `container` | Would widen the Stage 17 execution namespace and blur build versus launch behavior. |
| Put Docker and Apptainer build targets only under runtime-specific namespaces | Would duplicate named target selection and prevent shared build/reuse behavior. |
| Add per-target deep merge now | Existing adapter namespace semantics are opaque replacement; typed target merge needs its own design. |
| Add a universal command-runner abstraction in Phase 1 | Phase 1 only defines records; runtime command runners remain adapter-local. |
| Make build outputs stage artifacts by default | Build evidence is derived run-local evidence; stage outputs remain worker-owned artifacts. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No per-target merge semantics | Avoids inventing a hidden public merge model during contract setup | Users need overlays, deletion, or target-level profile composition. |
| Build key summary is local/plain-data only | Keeps default checks deterministic and network-free | Strong image identity, registry metadata, or image-lock policy is selected. |
| Descriptor claims may arrive before full behavior | Lets profile/capability tests accept Stage 18 namespaces before later phases implement execution | A later phase cannot implement claimed behavior without changing namespace ownership. |

## Reviewability

- Expected PR size and shape: medium public-contract PR touching shared container records, runtime descriptors, profile tests, contract tests, package import tests, Stage 18 plan metadata, and the Phase 1 execution plan.
- Files and areas to inspect: record shapes, validation, redaction, build-key determinism, descriptor namespace claims, profile merge expectations, and import boundaries.
- Scope-control checks: no Docker/Apptainer command execution, no SLURM wrapping, no preflight checks, no global cache, no image locks, no registry/auth helpers, no path translation, and no MPI policy.

## Implementation Steps

1. Extend shared container records with `container_build` models, validation helpers, redacted projection, and build-key summary helpers.
2. Add descriptor namespace claims for Stage 18 executor combinations without importing runtime behavior.
3. Add runtime/profile tests for `container_build` shorthand, opaque namespace replacement, and stage-level overrides.
4. Add unit/contract tests for record round trips, invalid shapes, redaction, output refs, policy modes, deterministic build keys, and import boundaries.
5. Run targeted suites, update completion notes, and commit a coherent Phase 1 implementation checkpoint.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package`.
- Required assertions or deferral reason: importing shared container records and runtime descriptors must not import Docker/Apptainer/SLURM command modules, diagnostics, CLI, optional SDKs, registries, or network-facing modules.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/executors/test_containers.py`, `tests/unit/loom/pipeline/test_runtime_profiles.py`, `tests/unit/loom/pipeline/test_executor_capabilities.py`.
- Required assertions or deferral reason: build record serialization, validation, policy/output/source errors, redaction, build-key summaries, descriptor namespace claims, and profile merge behavior.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_container_executor_contract.py`, `tests/contracts/test_runtime_profiles_contract.py`, `tests/contracts/test_executor_capabilities_contract.py`.
- Required assertions or deferral reason: stable plain-data contract, namespace separation, whole-namespace replacement, and payload-inspection-free diagnostics.

### Integration Suite

- Status: deferred.
- Expected paths: none required before Phase 2.
- Required assertions or deferral reason: this phase does not build, execute, or stage outputs; integration begins with local builders.

### E2E Suite

- Status: deferred.
- Expected paths: none.
- Required assertions or deferral reason: CLI behavior and SLURM script composition are later phases.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: real Docker/Apptainer/SIF/SLURM smoke remains optional Phase 5 work.

## Risks

- `container_build` records accidentally encode Docker- or Apptainer-only behavior.
- Namespace merge tests imply per-target overlays instead of whole-namespace replacement.
- Build metadata leaks raw build args or environment values.
- Descriptor claims overpromise behavior before later phases implement it.
- Shared records import runtime command modules or diagnostics presentation.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/test_containers.py
uv run pytest tests/unit/loom/pipeline/test_runtime_profiles.py tests/unit/loom/pipeline/test_executor_capabilities.py
uv run pytest tests/contracts/test_container_executor_contract.py tests/contracts/test_runtime_profiles_contract.py tests/contracts/test_executor_capabilities_contract.py
uv run pytest tests/package
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: shared build records first, descriptor namespace claims second, profile semantics third, tests throughout.
- Tests to run with each slice: closest unit tests after records, descriptor unit/contract tests after registry changes, profile contract tests after namespace behavior, package tests after imports/exports.
- Decisions the executor must not revisit: keep `container_build` separate from `container`, use whole-namespace replacement, keep runtime command runners adapter-local, keep build evidence separate from output refs, and avoid real runtime/network requirements.
- Conditions that require stopping for the manager: Stage 17 shared records disappear, per-target merge becomes necessary, build records require Docker/Apptainer imports, command execution leaks into Phase 1, or public behavior requires path translation, registry auth, global cache, or image locks.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted suite and full PR gate passed
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by manager in this file before code changes.
- Final phase execution plan: refined in this planning pass; ready for implementation.
- Implementation summary: extended `loom.pipeline.executors.containers` with
  schema-versioned `container_build` records for build sources, output refs,
  policies, targets, options, build keys, requests, results, redacted command
  projections, evidence, and failures; added Apptainer/Singularity and
  container-build namespace claims to the import-light descriptor registry; and
  added focused unit, contract, profile, descriptor, and package coverage.
- Implementation validation:
  - Targeted Phase 1 suite passed:
    `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/test_containers.py tests/unit/loom/pipeline/test_runtime_profiles.py tests/unit/loom/pipeline/test_executor_capabilities.py tests/contracts/test_container_executor_contract.py tests/contracts/test_runtime_profiles_contract.py tests/contracts/test_executor_capabilities_contract.py tests/package`:
    172 passed, 1 skipped.
  - Targeted Ruff and Pyright checks passed for touched implementation and
    test files.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed outside the sandbox
    after sandboxed authority service tests hung: Ruff passed; Pyright passed;
    default harness passed with 1818 passed, 26 skipped, 18 deselected;
    config-extra harness passed with 447 passed, 1855 deselected; `uv build`
    produced the source distribution and wheel.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed outside the sandbox
    and wrote `build/test-summary.md`; overall summary: 2293 passed, 18
    skipped, 1871 deselected.
- Refinement summary: not needed; validation passed after manager
  implementation.
- Blocker-resolution summary: none used
- PR preparation: PR body drafted in
  `docs/roadmap/stage-18/phases/container-build-contracts-pr-body.md`
- Stack maintenance: root phase from `develop`
- Remaining blockers: none
