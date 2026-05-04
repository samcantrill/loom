# Phase 3 Execution Plan: Stage Factory And Semantic Fingerprint Policy

## Metadata

- Status: draft phase execution plan
- Branch: `codex/v0-post-stage-factory`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-stage-factory`
- Phase execution plan path: `docs/phases/v0-post-stage-factory.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Source phase: `Phase 3 - Stage Factory And Semantic Fingerprint Policy`
- Stack predecessor: none
- Base branch: `develop` at `4611a877e38bc3997565352d81c40bc79801cd7c`
- Target branch: `develop`
- Merge eligibility: human-owned serial merge gate. The PR must target `develop`, request review from `samcantrill`, mention `@samcantrill` in the PR body or an immediate PR comment, and is merge-eligible only after human approval and human merge into `develop`. Codex must not approve or merge.
- Successor dependency notes: Phase 4 must not start while this phase is only `pr_open` or `approved`; no successor phase starts until the Phase 3 PR is verified as `MERGED` into `develop` and the implementation plan records Phase 3 as `merged`.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v0-post.md`; no blocking plan-review findings remain.
- Plan quality gate loop budget: initial plan review used, automated plan refinement pass used, confirmation review used. Do not consume another plan-quality review loop without explicit manager instruction.
- Draft pass: completed by `loom_phase_planner` in this pass.
- Refine pass: pending; the refine pass must make implementation details decision-complete before executor handoff.
- Setup limitations: local `develop` matched the manager-provided Phase 3 base commit. Creating the worktree required approved git worktree permissions because the sandbox exposed `.git/refs/heads` as read-only for new nested refs. No remote synchronization was attempted because the assignment provided the updated develop base.
- Blockers: none.

## Objective

Add explicit stage construction semantics before planner policy extraction and runner lifecycle decomposition depend on the current no-argument construction contract. This phase separates constructor-time `factory.init` values from runtime invocation `config`, while preserving the project stage execution contract of `run(context, inputs)`.

The same PR must implement the semantic-only fingerprint policy for stage reuse. Factory target, factory init config, runtime stage config, input artifact refs, selected environment identity, and explicit fingerprint fields are semantic. CPU, memory, logging, scheduling, and other operational hints remain non-semantic by default.

## Full-Plan Context

Phase 1 is merged and established recursive immutability, shared schema helpers, and no-extra/config-extra validation evidence. Phase 2 is merged and established capability-oriented stores, run-scoped artifact stores, `ArtifactAddress`, and a narrower stage-author `StageContext` facade.

Phase 3 builds on those corrected contracts by resolving finding 11 from the implementation plan: no-argument stage construction. It must also lock in the stage fingerprint policy before Phase 5 extracts planner helpers, Phase 7 decomposes runner lifecycle, and future plugin or worker-side construction paths reuse the stage factory contract.

Runtime/resource foundations, concrete event and lock behavior, planner decomposition, explicit recipe catalogs, runner lifecycle refactoring, subprocess/container/SLURM execution, retries, timeouts, remote stores, catalogs, bundles, sweeps, and final migration notes remain future-phase work.

## Stack Context

- Root or stacked phase: root serial phase.
- Current predecessor branch or PR: none; Phase 2 was human-merged into `develop`.
- Why this base branch is correct: serial human-merge-gate mode starts each phase from updated `develop`; Phase 2 merge notes say Phase 3 must continue from updated `develop`, and the control checkout verified `develop` at `4611a877e38bc3997565352d81c40bc79801cd7c`.
- Retarget/rebase plan after predecessor merge: not applicable because there is no unmerged predecessor and the PR target is already `develop`.
- Branch cleanup constraints: keep the phase branch and worktree until the human-owned PR has merged into `develop` and no successor branch depends on it.

## Source Phase Summary

- Goal: add stage construction semantics before planner policy is extracted, so fingerprints and runner lifecycle work do not build on a soon-to-change no-argument construction contract.
- Required scope:
  - Add explicit authored `factory: {_target_: ..., init: {...}}` blocks.
  - Preserve `config` as runtime invocation config exposed through `StageContext.stage_config`.
  - Preserve `run(context, inputs)` as the stage execution contract.
  - Add a stage factory protocol or construction helper that execution can use without importing optional config dependency paths.
  - Define and implement the semantic-only stage fingerprint policy.
  - Update parsing, validation, fingerprint construction, tests, `docs/structure.md`, `docs/features/pipeline.md`, `docs/features/execution.md`, and `docs/features/fingerprints.md`.
- Required checkpoints:
  - Factory parsing and value objects exist before runner construction changes.
  - Stage construction remains import-safe for no-extra installs.
  - Fingerprint payload and reuse tests change in the same phase as factory parsing.
  - Existing no-argument stage examples either migrate to the factory shape or continue through the documented compatibility path chosen below.
- Acceptance criteria:
  - Authored configs can construct stages with `factory._target_` and `factory.init` without routing constructor values through `StageContext.stage_config`.
  - Stage construction remains import-safe for installs without the `config` optional extra unless the caller explicitly uses config composition.
  - Fingerprint tests prove semantic fields affect reuse and non-semantic operational hints do not.
  - Existing no-argument stage examples migrate to the factory shape or continue through the compatibility path chosen by this phase execution plan.

## Current Source And Harness Findings

- `src/loom/pipeline/specs.py` currently stores `StageSpec.target_path`, parses top-level `_target_`, maps authored `config` to `stage_config`, accepts `resources`, and rejects deferred `runtime`, `retry`, `when`, and `metadata`.
- `StageSpec` and `PipelineSpec` already freeze nested plain data through Phase 1 helpers, so `factory.init`, runtime `config`, and explicit fingerprint fields should use the same plain-data validation and freezing path.
- `src/loom/pipeline/execution/runner.py` currently imports `loom.config.instantiate.targets.import_target` inside `_construct_stage()`, resolves `stage.target_path`, and constructs targets with no arguments.
- `src/loom/config/instantiate/targets.py` is a lightweight importlib helper, but it lives under `loom.config`; package import-boundary tests currently expect importing execution modules not to import `loom.config`.
- `src/loom/pipeline/stage.py` defines the structural `Stage` protocol with `run(context, inputs)`; this protocol should remain unchanged.
- `src/loom/pipeline/planning/fingerprints.py` currently builds `StageFingerprintPayload` from `target_path`, `stage_config`, declared and bound inputs, declared outputs, Python version, loom version, git, dependencies, and `FingerprintContext.extra`.
- Existing fingerprint tests in `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py` already prove `resources` are excluded and input checksum or runtime stage config changes are included.
- `src/loom/pipeline/planning/models.py` currently persists `StageFingerprintPayload.target_path` and `stage_config`; Phase 3 must update payload schema/policy version and tests when adding factory target/init and explicit fingerprint fields.
- `tests/support/pipeline_execution_configs.py` and local execution integration/e2e tests currently author top-level `_target_` stages with no constructor kwargs.
- `tests/package/test_import_boundaries.py` is the main harness for proving stage factory construction and pipeline/execution imports remain safe without config extras.
- `Makefile` has required suite targets for `test-no-extra`, `test-config-extra`, `test-package`, `test-unit`, `test-contract`, `test-integration`, `test-e2e`, `lint`, `typecheck`, `build`, `validate-pr`, and `test-summary`.

## In-Scope Work

- Add a stage factory value object or equivalent explicit spec surface in `loom.pipeline.specs` for `factory._target_` and `factory.init`.
- Update pipeline config parsing so authored stages use `factory` for construction and `config` only for runtime `StageContext.stage_config`.
- Migrate Phase 3 examples, tests, and feature docs to the factory shape.
- Choose the narrow pre-v1 compatibility path: authored top-level `_target_` should be rejected in new pipeline config with a path-aware message after tests/docs are migrated; a direct Python compatibility property such as `StageSpec.target_path` may remain only as a derived convenience if needed to keep internal churn reviewable.
- Add a lightweight stage target import and construction helper that the runner can call without pulling optional config dependencies into no-extra execution.
- Support constructor kwargs by passing `factory.init` as keyword arguments to stage class or callable construction.
- Preserve already-instantiated stage objects only when they still satisfy `Stage` and `factory.init` is empty; non-empty `init` with a pre-instantiated object should fail clearly.
- Add explicit stage-level fingerprint fields as a plain-data mapping, provisionally named `fingerprint`, and include those fields in the semantic fingerprint payload.
- Update stage fingerprint payload, persisted serialization tests, and policy versioning so factory target/init and explicit fingerprint fields are visible in persisted `fingerprint.json`.
- Ensure non-semantic operational hints remain excluded from the semantic hash by default, including existing `resources` and future `runtime`, logging, scheduling, CPU, memory, retry, timeout, executor, SLURM, and container hints.
- Update docs that define the changed public contracts: `docs/structure.md`, `docs/features/pipeline.md`, `docs/features/execution.md`, and `docs/features/fingerprints.md`.

## Out-of-Scope Work

- No runtime/resource model implementation, runtime profile semantics, event models, append-only event JSONL, concrete lock protocol, local lock files, or blocked descendant status persistence.
- No planner policy decomposition, `PlanExplanation`, selector behavior changes, resume policy extraction, or CLI diagnostics.
- No generic OmegaConf/Pydantic object graph instantiation for stages. The stage factory helper should import the target and call it with plain keyword args only.
- No plugin discovery, plugin-managed factory resolution, recipe catalog redesign, fresh-catalog composition path, or global registry changes.
- No subprocess, SLURM, container, remote executor, remote store, catalog, bundle, sweep, retry, timeout, cleanup, or retention behavior.
- No change to the project stage execution protocol beyond construction; `run(context, inputs)` remains unchanged.
- No future phase implementation or PR preparation in this planning pass.

## Assumptions

- Breaking pre-v1 pipeline config changes are acceptable when they correct the public contract before v1 and v2 build more surface on top.
- Existing direct `StageSpec(...)` tests can be migrated to construct whatever factory value object Phase 3 introduces, while retaining a small derived target-path convenience only if it avoids noisy internal churn.
- Stage factory `init` values are trusted project-authored plain data and should not require config extras.
- Constructor kwargs should be passed exactly as a shallow keyword mapping; recursive target instantiation, dependency injection, and `_inject_` handling remain config-layer behavior outside this phase.
- The selected environment identity already flows through `FingerprintContext`; this phase should preserve that model while clarifying which context fields are semantic.
- Existing `resources` behavior is treated as an operational hint and remains non-semantic unless a later phase explicitly changes that decision.

## Decision-Complete Contract

This is a draft-level contract for the refine pass to make mechanically complete. The refine pass may tighten names or call signatures to match repository patterns, but it must not reopen the selected remediation decisions without explicit manager instruction.

### Authored Stage Shape

Supported authored pipeline stages should use:

```yaml
name: build
factory:
  _target_: project.stages.BuildStage
  init:
    constructor_key: value
config:
  runtime_key: value
outputs:
  result:
    artifact_type: json
fingerprint:
  semantic_key: value
resources:
  slots: cpu
```

- `factory` is required for authored stages.
- `factory._target_` is a non-empty import path.
- `factory.init` defaults to an empty mapping and must be plain-data-compatible.
- `config` remains the runtime invocation config exposed through `StageContext.stage_config`.
- `fingerprint` is an explicit stage-level plain-data mapping whose values are semantic by declaration.
- `resources` remains accepted as an operational hint and is not part of the semantic fingerprint.
- Top-level `_target_` in authored pipeline config should fail with a path-aware pre-v1 migration message after tests and docs are migrated to `factory`.

### Stage Construction

- Stage construction must resolve `factory._target_` with a lightweight import helper that is safe in no-extra installs.
- If the imported target is a class or callable, construct it with `**factory.init`.
- If the imported target is already a `Stage` instance, accept it only when `factory.init` is empty.
- The constructed object must satisfy the existing `Stage` protocol.
- Constructor import and construction errors must identify the stage name and config path.
- The executor must not route constructor values through `StageContext.stage_config`.

### Fingerprint Semantics

The semantic hash input must include:

- stage name and fingerprint policy metadata;
- factory target;
- factory init config;
- runtime stage config;
- declared input bindings;
- bound input artifact identities, including checksum and producer fields already represented by `ArtifactRef`;
- declared outputs, unless the refine pass records a narrow reason to exclude output declarations from reuse semantics;
- selected environment identity from `FingerprintContext`, including Python version, loom version, git, dependency versions, and context `extra`;
- explicit stage-level fingerprint fields.

The semantic hash input must exclude by default:

- `resources`;
- future runtime, retry, timeout, executor, CPU, memory, logging, scheduling, SLURM, container, and operational lifecycle hints;
- local paths, run directory paths, attempt numbers, timestamps, log paths, stdout/stderr capture choices, and artifact URIs when checksum/fingerprint identity is available.

The persisted fingerprint payload must make the included fields inspectable so review can verify policy without comparing opaque hashes only.

## Design Impact

- Maintainability: moving construction into a small factory contract prevents constructor kwargs, stage runtime config, and generic config-instantiation behavior from being mixed in runner code.
- Extensibility: plugin-discovered stages, subprocess workers, and future worker-side construction can reuse the same factory target/init surface without depending on import side effects or no-arg wrappers.
- Domain neutrality: factory/init and fingerprint fields are plain-data orchestration metadata; they do not encode project-domain behavior.
- Source-tree boundaries: `loom.pipeline` owns stage specs, factory semantics, `Stage` protocol compatibility, and fingerprint policy; `loom.config` keeps full config composition and recursive target-instantiation behavior.

## Future Compatibility

- Phase 5 planner decomposition can wrap the finalized fingerprint policy in helpers without changing which fields are semantic.
- Phase 7 runner decomposition can move stage construction behind lifecycle collaborators without changing authored stage shape.
- Future subprocess and container workers can construct stage objects from the same plain factory payload sent across process boundaries.
- Future plugin discovery can produce factory targets or aliases that resolve into the same explicit factory contract.
- Future runtime/resource phases can add operational hints without accidentally invalidating resume unless they explicitly declare a hint semantic.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep only top-level `_target_` and continue no-arg construction | It preserves the ambiguity this phase is meant to remove and encourages constructor data to be smuggled through runtime `stage_config`. |
| Treat authored stage mappings as full generic config object graphs | It would couple pipeline execution to optional config dependencies and recursive instantiation behavior that belongs to `loom.config`. |
| Put constructor kwargs under `config` | It breaks the selected remediation that `config` remains `StageContext.stage_config` for runtime invocation. |
| Include `resources` or all operational hints in the stage fingerprint | CPU, memory, logs, scheduling, and similar hints should not force reruns unless a later phase explicitly marks them semantic. |
| Compare only opaque fingerprint strings in tests | Opaque comparisons can miss policy drift; payload tests must assert which fields are included or excluded. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Short-lived migration churn from top-level `_target_` to `factory` in tests and docs | Breaking pre-v1 config shape is allowed to correct the public contract before v1 and CLI work. | Revisit only if refine finds removal creates excessive unrelated churn; any compatibility bridge must be documented and temporary. |
| A lightweight target import helper may duplicate part of `loom.config.instantiate.targets` | Execution must remain import-safe without config extras, and full config instantiation remains out of scope. | Revisit in Phase 6 or plugin discovery work if target resolution policy needs shared aliases or catalogs. |
| Explicit fingerprint fields are a minimal plain-data mapping, not a full include/exclude policy language | The phase needs declared semantic fields without expanding into planner diagnostics or config expression language. | Revisit when CLI/preflight explanations or project-level fingerprint policy need richer controls. |

## Reviewability

- Expected PR size and shape: one focused contract PR touching pipeline specs, stage construction, fingerprint models/helpers, targeted tests, and the four named docs. It should not include runner lifecycle decomposition or planner helper extraction.
- Files and areas to inspect:
  - `src/loom/pipeline/specs.py`
  - `src/loom/pipeline/stage.py`
  - `src/loom/pipeline/execution/runner.py`
  - `src/loom/pipeline/planning/fingerprints.py`
  - `src/loom/pipeline/planning/models.py`
  - `src/loom/config/instantiate/targets.py` or any new lightweight import helper
  - `tests/package/test_import_boundaries.py`
  - `tests/unit/loom/pipeline/test_specs.py`
  - `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`
  - `tests/unit/loom/pipeline/planning/test_models.py`
  - `tests/integration/pipeline/test_local_execution.py`
  - `tests/integration/pipeline/test_local_execution_resume.py`
  - `tests/integration/pipeline/test_planning_resume.py`
  - `tests/e2e/test_local_pipeline_run.py`
  - `tests/support/pipeline_execution_configs.py`
  - `tests/support/pipeline_execution_stages.py`
  - `docs/structure.md`
  - `docs/features/pipeline.md`
  - `docs/features/execution.md`
  - `docs/features/fingerprints.md`
- Scope-control checks:
  - No concrete event, lock, runtime/resource, blocked-outcome, or runner decomposition work.
  - No optional config dependency import through pipeline or execution imports.
  - No constructor values in `StageContext.stage_config`.
  - No change to `Stage.run(context, inputs)`.
  - No semantic fingerprint invalidation from `resources` changes.

## Implementation Steps

1. Add or refine stage factory spec models in `src/loom/pipeline/specs.py`, using existing plain-data validation and recursive freezing helpers.
2. Update pipeline config parsing to accept `factory` blocks, parse `factory._target_` and `factory.init`, parse explicit `fingerprint` fields, and reject top-level `_target_` with a migration-oriented error.
3. Update direct `StageSpec` construction tests and support fixtures to use the selected factory spec surface.
4. Add a lightweight stage construction helper and update `PipelineRunner._construct_stage()` to import the target, call it with `factory.init`, validate `Stage`, and keep errors path-aware.
5. Update fingerprint payload models, policy constants/versioning, `build_stage_fingerprint()`, and persisted model round-trip tests for factory target/init and explicit fingerprint fields.
6. Update planning/resume tests so semantic factory target/init/config/input/fingerprint fields rerun and non-semantic resources or operational hints do not.
7. Migrate local execution support configs, integration tests, and e2e tests to authored `factory` blocks, adding a constructor-init test stage where needed.
8. Update docs and structure ownership notes for the new factory shape, runtime config separation, execution construction policy, and semantic fingerprint inclusion/exclusion policy.
9. Run targeted package, unit, contract, integration, e2e, config-extra, lint/type/build checks during implementation and leave final `make validate-pr` plus `make test-summary` to PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_api.py`, `tests/package/test_pipeline_execution_api.py`, `tests/package/test_pipeline_planning_api.py`.
- Required assertions: importing `loom.pipeline` and `loom.pipeline.execution` must not import optional config dependency paths or heavy config modules; public exports for any new factory spec or helper are intentional; no-extra import behavior remains visible in package tests.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/test_specs.py`, `tests/unit/loom/pipeline/test_stage.py`, `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`, `tests/unit/loom/pipeline/planning/test_models.py`, and a focused stage construction test if the helper is extracted.
- Required assertions: `factory` parsing, default empty init, plain-data validation, recursive immutability, top-level `_target_` rejection, constructor error paths, `Stage` protocol preservation, fingerprint payload round trip, semantic field inclusion, and non-semantic resource exclusion.

### Contract Suite

- Status: required.
- Expected paths: existing `tests/contracts/` plus a new or updated fingerprint/pipeline contract test if needed.
- Required assertions: persisted `fingerprint.json` payload shape remains strict, versioned, inspectable, and compatible with store read/write contracts. Store capability contracts are not broadly reopened unless signature fallout requires a targeted update.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_pipeline_config.py`, `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_local_execution_resume.py`, `tests/integration/pipeline/test_planning_resume.py`, and `tests/integration/pipeline/test_plan_persistence.py`.
- Required assertions: local `PipelineRunner` constructs a stage with `factory.init`, runtime `config` remains available as `StageContext.stage_config`, resume reruns when factory target/init changes, resume does not rerun when only resources or other non-semantic hints change, and persisted plans/fingerprints remain readable.

### E2E Suite

- Status: required but focused.
- Expected paths: `tests/e2e/test_local_pipeline_run.py`.
- Required assertions: the public local pipeline path works with authored factory blocks and no constructor values are routed through runtime stage config. Broader hardening e2e coverage for final migration notes remains Phase 8 work.

### Config-Extra Suite

- Status: required.
- Expected paths: config composition tests that materialize pipeline configs, likely `tests/integration/config/test_compose_config.py`, plus any config-extra harness fixtures touched by migrated examples.
- Required assertions: config composition with the `config` extra preserves authored `factory` blocks, optional config dependencies remain behind the `loom[config]` extra, and composed pipeline execution still parses factory/runtime config separation.

### Pyright, Ruff, And Build

- Status: required before PR preparation.
- Expected commands: `make lint`, `make typecheck`, `make build`, and final `make validate-pr`.
- Required assertions: new dataclasses/protocols are typed without ignores, import-boundary changes do not rely on dynamic typing shortcuts, Ruff passes, Pyright passes with config extra enabled, and source distribution/wheel builds.

### Explicit Deferrals

- Runtime/resource/event/lock tests are deferred because Phase 4 owns those foundations.
- Planner explanation and policy-helper tests are deferred because Phase 5 owns planner decomposition.
- Runner lifecycle subcomponent tests are deferred because Phase 7 owns lifecycle decomposition.
- Plugin discovery, subprocess, SLURM, container, retry, timeout, remote store, catalog, bundle, sweep, cleanup, and retention tests are deferred because they are future roadmap work.

## Risks

- The main implementation risk is accidentally importing `loom.config` or optional config dependencies from pipeline/execution import paths while reusing the target import helper.
- Removing top-level `_target_` may touch many tests and docs; keep the migration mechanical and avoid unrelated cleanups.
- Fingerprint payload changes can silently alter resume behavior if tests only compare digests. Tests must inspect payload fields and prove both positive and negative invalidation cases.
- Constructor kwargs may tempt recursive instantiation or dependency injection. Keep `factory.init` as plain keyword data only.
- Documentation may already contain older stage context and `_target_` wording. Update only the four docs named by the source phase unless a directly affected reference would become misleading.

## Validation Commands

Targeted development commands:

```sh
make test-package
uv run pytest tests/unit/loom/pipeline/test_specs.py tests/unit/loom/pipeline/planning/test_planning_fingerprints.py tests/unit/loom/pipeline/planning/test_models.py
uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py
uv run pytest tests/e2e/test_local_pipeline_run.py
make test-config-extra
make lint
make typecheck
make build
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - specs and parsing first;
  - construction helper and runner wiring second;
  - fingerprint payload and resume behavior third;
  - support fixture, integration, e2e, and docs migration last.
- Tests to run with each slice:
  - specs slice: unit spec tests and package import-boundary tests;
  - construction slice: stage construction unit tests and local execution integration tests;
  - fingerprint slice: fingerprint unit tests, planning resume integration tests, and plan persistence tests;
  - docs/final slice: config-extra, e2e, lint, typecheck, and build.
- Decisions the executor must not revisit:
  - `factory.init` is constructor input;
  - `config` is runtime `StageContext.stage_config`;
  - `run(context, inputs)` remains the stage execution contract;
  - operational hints are non-semantic by default;
  - no optional config dependency import is allowed through pipeline/execution imports.
- Conditions that require stopping for the manager:
  - the implementation cannot preserve no-extra import safety;
  - the selected top-level `_target_` migration creates broad unrelated churn;
  - a public API decision beyond the documented factory/fingerprint contract is needed;
  - validation shows existing Phase 1 or Phase 2 contracts would need to be reopened.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed in the plan commit containing this file.
- Final phase execution plan: pending refine pass.
- Implementation summary: pending implementation pass.
- Implementation validation: pending implementation and PR-preparation passes.
- Refinement summary: pending implementation refinement pass if used.
- PR preparation: pending PR-preparer pass.
- Stack maintenance: serial human merge gate active; no successor may start until the Phase 3 PR is human-merged into `develop`.
- Remaining blockers: none.
