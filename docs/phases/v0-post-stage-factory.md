# Phase 3 Execution Plan: Stage Factory And Semantic Fingerprint Policy

## Metadata

- Status: PR preparation in progress
- Branch: `codex/v0-post-stage-factory`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-stage-factory`
- Phase execution plan path: `docs/phases/v0-post-stage-factory.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Source phase: `Phase 3 - Stage Factory And Semantic Fingerprint Policy`
- Stack predecessor: none
- Base branch: `develop` at `4611a877e38bc3997565352d81c40bc79801cd7c`
- Target branch: `develop`
- Merge eligibility: serial human merge gate. The Phase 3 PR must target
  `develop`, request review from `samcantrill` when GitHub allows it, and
  mention `@samcantrill` in the PR body or an immediate fallback PR comment.
  Codex must not approve or merge. The PR is merge-eligible only after human
  approval and human merge into `develop`.
- Successor dependency notes: Phase 4 must not start while Phase 3 is only
  `pr_open` or `approved`; no successor phase starts until the Phase 3 PR is
  verified as `MERGED` into `develop` and the implementation plan records Phase
  3 as `merged`.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v0-post.md`;
  no blocking plan-review findings remain.
- Plan quality gate loop budget: initial plan review used, automated plan
  refinement pass used, confirmation review used. Do not consume another
  plan-quality review loop without explicit manager instruction.
- Draft pass: completed by `loom_phase_planner` in commit `ed907e7`.
- Refine pass: completed by `loom_phase_planner` in this pass; this document is
  decision-complete for executor handoff.
- Phase implementation refinement budget: used in this pass.
- PR review budget: unused.
- Setup limitations: local `develop` matched the manager-provided Phase 3 base
  commit. No remote synchronization was attempted during planning because the
  assignment provided the updated `develop` base.
- Blockers: none.

## Objective

Add explicit stage construction semantics before planner policy extraction and
runner lifecycle decomposition depend on the current no-argument construction
contract. Constructor-time values move under `factory.init`; runtime invocation
configuration remains authored as `config` and exposed through
`StageContext.stage_config`. The project stage execution protocol remains
`run(context, inputs)`.

The same implementation must lock in the semantic-only stage fingerprint policy.
Factory target, factory init config, runtime stage config, input artifact
identities, selected environment identity, declared outputs, and explicit
fingerprint fields are semantic. Resources and other operational hints remain
non-semantic by default.

## Full-Plan Context

Phase 1 is merged and established recursive immutability, shared strict schema
helpers, and no-extra/config-extra validation evidence. Phase 2 is merged and
established capability-oriented stores, run-scoped artifact stores,
`ArtifactAddress`, and the narrower stage-author `StageContext` facade.

Phase 3 resolves finding 11 from the implementation plan: no-argument stage
construction. It must also define the stage fingerprint policy before Phase 5
extracts planner policy helpers, Phase 7 decomposes runner lifecycle, and future
plugin or worker-side construction paths reuse the stage factory contract.

Runtime/resource foundations, concrete event and lock behavior, planner
decomposition, explicit recipe catalogs, runner lifecycle refactoring,
subprocess/container/SLURM execution, retries, timeouts, remote stores,
catalogs, bundles, sweeps, cleanup, retention, and final migration notes remain
future-phase work.

## Stack Context

- Root or stacked phase: root serial phase.
- Current predecessor branch or PR: none; Phase 2 was human-merged into
  `develop`.
- Why this base branch is correct: serial human-merge-gate mode starts each
  phase from updated `develop`; Phase 2 merge notes say Phase 3 must continue
  from updated `develop`, and this worktree records `develop` at
  `4611a877e38bc3997565352d81c40bc79801cd7c`.
- Retarget/rebase plan after predecessor merge: not applicable because there is
  no unmerged predecessor and the PR target is already `develop`.
- Branch cleanup constraints: keep the phase branch and worktree until the
  human-owned PR has merged into `develop` and no successor branch depends on
  it.

## Source Phase Summary

- Goal: add stage construction semantics before planner policy is extracted, so
  fingerprints and runner lifecycle work do not build on a soon-to-change
  no-argument construction contract.
- Required scope:
  - Add explicit authored `factory: {_target_: ..., init: {...}}` blocks.
  - Preserve `config` as runtime invocation config exposed through
    `StageContext.stage_config`.
  - Preserve `run(context, inputs)` as the stage execution contract.
  - Add a stage factory protocol or construction helper that execution can use
    without importing optional config dependency paths.
  - Define and implement the semantic-only stage fingerprint policy.
  - Update parsing, validation, fingerprint construction, tests,
    `docs/structure.md`, `docs/features/pipeline.md`,
    `docs/features/execution.md`, and `docs/features/fingerprints.md`.
- Required checkpoints:
  - Factory parsing and value objects exist before runner construction changes.
  - Stage construction remains import-safe for no-extra installs.
  - Fingerprint payload and reuse tests change in the same phase as factory
    parsing.
  - Existing no-argument examples migrate to the factory shape.
- Acceptance criteria:
  - Authored configs can construct stages with `factory._target_` and
    `factory.init` without routing constructor values through
    `StageContext.stage_config`.
  - Stage construction remains import-safe for installs without the `config`
    optional extra unless the caller explicitly uses config composition.
  - Fingerprint tests prove semantic fields affect reuse and non-semantic
    operational hints do not.
  - Existing no-argument examples use `factory._target_` with omitted or empty
    `factory.init`; legacy top-level `_target_` authored config is rejected with
    a migration-oriented message.

## Current Source And Harness Findings

- `src/loom/pipeline/specs.py` currently stores `StageSpec.target_path`, parses
  top-level `_target_`, maps authored `config` to `stage_config`, accepts
  `resources`, and rejects deferred `runtime`, `retry`, `when`, and `metadata`.
- Phase 1 helpers already freeze plain data recursively. `factory.init`,
  runtime `config`, and explicit fingerprint fields must use the same validation
  and freezing behavior.
- `src/loom/pipeline/execution/runner.py` currently imports
  `loom.config.instantiate.targets.import_target` inside `_construct_stage()`,
  resolves `stage.target_path`, and constructs classes/callables with no
  arguments.
- `src/loom/config/instantiate/targets.py` is lightweight but lives under
  `loom.config`. Phase 3 must not route execution construction through
  `loom.config`, because package tests assert pipeline/execution imports remain
  safe without optional config dependencies.
- `src/loom/pipeline/stage.py` defines the structural `Stage` protocol with
  `run(context, inputs)`. This protocol remains unchanged.
- `src/loom/pipeline/planning/fingerprints.py` currently builds
  `StageFingerprintPayload` from `target_path`, `stage_config`, declared and
  bound inputs, declared outputs, Python version, loom version, git,
  dependencies, and `FingerprintContext.extra`.
- `src/loom/pipeline/planning/models.py` currently has stage fingerprint schema
  and policy version `1` and persists `target_path` plus `stage_config`.
  Phase 3 must bump the persisted fingerprint schema/policy and make factory
  target/init plus explicit fingerprint fields inspectable.
- Existing fingerprint tests already prove `resources` are excluded and input
  checksum or runtime stage config changes are included. They must be expanded
  to inspect payload fields, not only compare opaque hashes.
- `tests/support/pipeline_execution_configs.py`, planning fixtures, graph tests,
  integration tests, e2e tests, and docs examples currently author top-level
  `_target_` stages. These in-scope fixtures must migrate to `factory`.
- `tests/package/test_import_boundaries.py` is the main harness for proving
  no-extra import safety. It must cover the new factory helper path.
- The Makefile already exposes the required suite targets:
  `test-no-extra`, `test-config-extra`, `test-package`, `test-unit`,
  `test-contract`, `test-integration`, `test-e2e`, `lint`, `typecheck`,
  `build`, `validate-pr`, and `test-summary`.

## In-Scope Work

- Add `StageFactorySpec` in `loom.pipeline.specs` with:
  - `target_path: str`
  - `init: Mapping[str, PlainData] = field(default_factory=dict)`
  - `from_config()` support for authored `factory._target_` and
    `factory.init`.
- Update `StageSpec` so construction data is owned by `factory`, runtime data is
  owned by `stage_config`, operational hints remain under `resources`, and
  authored `fingerprint` is stored internally as `fingerprint_fields`.
- Keep a read-only `StageSpec.target_path` compatibility property that returns
  `stage.factory.target_path` for reviewable internal churn. Do not keep the
  old `target_path=` dataclass constructor parameter.
- Update pipeline config parsing so authored stages require `factory`, reject
  top-level `_target_`, and parse no-argument stages as `factory` with omitted
  or empty `init`.
- Add a pipeline-owned stage construction helper in
  `src/loom/pipeline/stage_factory.py` and update `PipelineRunner._construct_stage()`
  to use it.
- Support constructor kwargs by calling imported stage classes or callables with
  `**stage.factory.init`.
- Accept already-instantiated stage objects only when they satisfy `Stage` and
  `factory.init` is empty; non-empty init for a pre-instantiated object fails
  clearly.
- Add explicit stage-level authored fingerprint fields under the `fingerprint`
  key. Values are plain-data-compatible and semantic by declaration.
- Update `StageFingerprintPayload`, policy constants, payload serialization
  tests, and resume tests for the v2 semantic policy.
- Keep declared outputs in the semantic fingerprint payload. Output declarations
  define the stage contract, and existing resume checks already treat output
  shape as reuse-relevant.
- Preserve non-semantic operational hints exclusion by default, including
  existing `resources` and future runtime, logging, scheduling, CPU, memory,
  retry, timeout, executor, SLURM, and container hints.
- Update docs that define the changed public contracts:
  `docs/structure.md`, `docs/features/pipeline.md`,
  `docs/features/execution.md`, and `docs/features/fingerprints.md`.

## Out-of-Scope Work

- No runtime/resource model implementation, runtime profiles, event models,
  append-only event JSONL, concrete lock protocol, local lock files, or blocked
  descendant status persistence.
- No planner policy decomposition, `PlanExplanation`, selector behavior changes,
  resume policy extraction, or CLI diagnostics.
- No generic OmegaConf/Pydantic object graph instantiation for stages. The stage
  factory helper imports a target and calls it with plain keyword args only.
- No plugin discovery, plugin-managed target aliases, recipe catalog redesign,
  fresh-catalog composition path, or global registry changes.
- No subprocess, SLURM, container, remote executor, remote store, catalog,
  bundle, sweep, retry, timeout, cleanup, or retention behavior.
- No change to the project stage execution protocol beyond construction;
  `run(context, inputs)` remains unchanged.
- No compatibility bridge that silently accepts legacy authored top-level
  `_target_` pipeline configs.
- No future phase implementation or PR preparation in this planning pass.

## Assumptions

- Breaking pre-v1 authored pipeline config changes are acceptable when they
  correct the public contract before v1 and CLI work.
- Existing no-argument stages remain supported by authoring:

  ```yaml
  factory:
    _target_: project.stages.NoArgStage
  ```

  or by using `init: {}`. They do not continue through top-level `_target_`.
- Direct Python `StageSpec(...)` call sites are migrated to pass
  `factory=StageFactorySpec(...)`. The only short-term compatibility surface is
  the read-only `StageSpec.target_path` property.
- `factory.init` values are trusted project-authored plain data. They are not
  recursively instantiated, injected, interpolated, or treated as config-layer
  object graphs.
- The stage factory helper supports the same dotted and single-colon import
  syntax as the config target helper for continuity, but it does not import from
  `loom.config`.
- `FingerprintContext` remains the source of selected environment identity.
  Phase 3 preserves that model and clarifies which context fields are semantic.
- Existing `resources` behavior is treated as operational and remains
  non-semantic unless a later phase explicitly changes that decision.
- Prior v1 fingerprint records from pre-Phase-3 runs are not reusable under the
  v2 policy. The implementation should parse them narrowly enough to report
  `FINGERPRINT_POLICY_CHANGED` and rerun when practical; it must not treat a v1
  fingerprint as a match for the new factory policy.

## Decision-Complete Contract

### Authored Stage Shape

Supported authored pipeline stages use this shape:

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
- `factory._target_` is required and must be a non-empty import path.
- `factory.init` defaults to an empty mapping and must be plain-data-compatible.
- `config` remains the runtime invocation config exposed through
  `StageContext.stage_config`.
- `fingerprint` is an explicit stage-level plain-data mapping. Values under
  this key are semantic because the author declared them fingerprint-relevant.
- `resources` remains accepted as an operational hint and is not part of the
  semantic stage fingerprint.
- The allowed authored stage fields after this phase are `name`, `factory`,
  `config`, `depends_on`, `inputs`, `outputs`, `resources`, and `fingerprint`.
  Deferred `runtime`, `retry`, `when`, and `metadata` remain rejected.
- Top-level `_target_` in authored pipeline config must fail with a path-aware
  pre-v1 migration message such as:
  `$.pipeline.stages[0] uses legacy top-level _target_; use factory._target_ and factory.init`.
- If `factory` is missing and legacy `_target_` is also absent, fail with a
  path-aware required-field message for `factory`.
- Unknown keys inside `factory` fail strictly; no `_args_`, `_partial_`,
  `_inject_`, recursive target blocks, or config-instantiation directives are
  accepted there.

### Python Value Objects

- Add `StageFactorySpec` as a frozen, slots dataclass in
  `src/loom/pipeline/specs.py`.
- Export `StageFactorySpec` from `loom.pipeline.specs` and `loom.pipeline`.
- `StageFactorySpec.__post_init__()` validates `target_path` with
  `_require_non_empty_string()` and freezes `init` with the same plain-data path
  used by `stage_config` and `resources`.
- `StageFactorySpec.from_config(config, path)` accepts only `_target_` and
  `init`, with path-aware errors.
- `StageSpec` owns these fields after migration:
  - `name`
  - `factory: StageFactorySpec`
  - `outputs`
  - `stage_config`
  - `dependencies`
  - `inputs`
  - `resources`
  - `fingerprint_fields`
- `StageSpec.from_config()` maps authored `config` to `stage_config` and
  authored `fingerprint` to `fingerprint_fields`.
- `StageSpec.target_path` remains as a read-only derived property for existing
  internal references and public introspection. It is not a constructor field.
- A convenience `StageSpec.factory_init` property may be added only if it reduces
  noisy call-site code; it must return the frozen mapping from
  `stage.factory.init`.
- `PipelineSpec`, graph code, planning code, and execution code should use the
  new `factory` object where construction semantics matter.

### Import-Safe Target Resolution And Stage Construction

- Add `src/loom/pipeline/stage_factory.py` with no imports from `loom.config`,
  optional config dependencies, CLI modules, stores, executors, or project code.
  Standard-library `importlib`, `Stage`, `StageFactorySpec`, and pipeline errors
  are enough.
- The helper supports:
  - dotted object paths, for example `package.module.ClassName`;
  - single-colon object paths, for example `package.module:ClassName`.
- The helper rejects:
  - empty target paths;
  - target paths without a module and object component;
  - multiple colons;
  - colon form with dotted object traversal;
  - unknown modules or objects, with path-aware messages.
- Construction order is fixed:
  1. If the imported target is a class, call `target(**factory.init)`.
  2. Else if the imported target is already a `Stage` instance, accept it only
     when `factory.init` is empty.
  3. Else if the target is callable, call `target(**factory.init)`.
  4. Else fail because the target is neither a class/callable nor a `Stage`.
- After construction or instance acceptance, validate `isinstance(candidate,
  Stage)`. Fail with `StageContractError` or the existing private runner
  construction subclass if it does not satisfy the protocol.
- Import, constructor, and protocol errors must name the stage, target path, and
  authored path, for example
  `pipeline.stages[1].factory._target_` or `pipeline.stages[1].factory.init`.
- `PipelineRunner._construct_stage()` should compute the stage index for error
  paths, delegate to the pipeline-owned helper, and stop importing
  `loom.config.instantiate.targets`.
- Constructor values must not be copied into `StageContext.stage_config`.
- `StageContext.metadata` may record `factory_target` for inspection, replacing
  or supplementing the existing `target_path` metadata key. It must not expose
  constructor init as runtime stage config.

### Semantic Fingerprint Policy

- Bump the persisted stage fingerprint schema and default policy:
  - `STAGE_FINGERPRINT_SCHEMA_VERSION = 2`
  - `STAGE_FINGERPRINT_POLICY_NAME = "loom.stage.semantic"`
  - `STAGE_FINGERPRINT_POLICY_VERSION = 2`
- `StageFingerprintPayload` v2 fields are:
  - `schema_version`
  - `policy_name`
  - `policy_version`
  - `stage_name`
  - `factory_target`
  - `factory_init`
  - `stage_config`
  - `declared_inputs`
  - `bound_inputs`
  - `declared_outputs`
  - `fingerprint_fields`
  - `python_version`
  - `loom_version`
  - `git`
  - `dependencies`
  - `extra`
- Do not keep `target_path` as a v2 payload field. Use `factory_target` so the
  persisted JSON reflects the new construction contract.
- `to_hash_input()` returns the full inspectable payload dict. Tests must assert
  key presence and selected values, not only digest inequality.
- Semantic hash input includes:
  - stage name and fingerprint policy metadata;
  - factory target;
  - factory init config;
  - runtime stage config;
  - declared input bindings;
  - bound input artifact identities;
  - declared output specs;
  - selected environment identity from `FingerprintContext`: Python version,
    loom version, git, dependencies, and context `extra`;
  - explicit stage-level `fingerprint` fields.
- Bound input identity includes the existing reusable semantic fields:
  `source_stage`, `source_output`, `artifact_id`, `artifact_type`, `codec_key`,
  `schema_version`, `checksum`, `fingerprint`, `producer_stage`, and metadata.
- Bound input identity excludes artifact URI, local path, created timestamp, run
  directory, attempt number, log paths, and other location/lifecycle values when
  checksum or fingerprint identity is available.
- Semantic hash input excludes by default:
  - `resources`;
  - future runtime, retry, timeout, executor, CPU, memory, logging, scheduling,
    SLURM, container, and lifecycle hints;
  - local paths, run directory paths, attempt numbers, timestamps, log paths,
    stdout/stderr capture choices, and artifact URIs.
- Prior v1 fingerprint records should be treated as policy-changed stale state,
  not reusable state. Add the narrow parser compatibility needed for resume to
  report `FINGERPRINT_POLICY_CHANGED` instead of treating parseable v1 records
  as corrupt, unless the prior file is genuinely malformed JSON or structurally
  invalid.

### Documentation Contract

- `docs/structure.md` must record that `loom.pipeline` owns stage factory specs,
  target resolution for execution, and semantic stage fingerprint policy. It
  must also preserve the `loom.config` optional-extra boundary and clarify that
  config-layer instantiation is separate from stage execution construction.
- `docs/features/pipeline.md` must show authored stages with `factory`, explain
  no-argument stages as omitted/empty `init`, document top-level `_target_`
  rejection, and keep `config` as runtime `StageContext.stage_config`.
- `docs/features/execution.md` must explain runner construction behavior,
  constructor kwargs, pre-instantiated stage handling, import-safe target
  resolution, and the unchanged `run(context, inputs)` protocol.
- `docs/features/fingerprints.md` must document the v2 payload, semantic
  inclusion list, non-semantic exclusions, declared output inclusion, explicit
  `fingerprint` fields, and the policy-changed behavior for old v1 records.
- Do not update runtime/resources, events, locks, catalogs, bundles, sweeps,
  remote stores, plugin discovery, or executor policy docs beyond avoiding
  misleading references directly caused by the factory/fingerprint change.

## Design Impact

- Maintainability: moving construction into `StageFactorySpec` and a small
  pipeline-owned helper prevents constructor kwargs, runtime stage config, and
  generic config-instantiation behavior from being mixed in runner code.
- Extensibility: plugin-discovered stages, subprocess workers, and future
  worker-side construction can reuse the same factory target/init surface
  without depending on import side effects or no-arg wrappers.
- Domain neutrality: factory/init and fingerprint fields are plain-data
  orchestration metadata; they do not encode project-domain behavior.
- Source-tree boundaries: `loom.pipeline` owns stage specs, stage construction,
  `Stage` protocol compatibility, and fingerprint policy; `loom.config` keeps
  config composition and recursive target-instantiation behavior behind the
  optional config extra.

## Future Compatibility

- Phase 5 planner decomposition can move the finalized fingerprint call behind
  helpers without changing which fields are semantic.
- Phase 7 runner decomposition can move construction behind lifecycle
  collaborators without changing authored stage shape.
- Future subprocess and container workers can construct stage objects from the
  same plain factory payload sent across process boundaries.
- Future plugin discovery can produce factory targets or aliases that resolve
  into the same explicit factory contract.
- Future runtime/resource phases can add operational hints without accidentally
  invalidating resume unless they explicitly declare a hint semantic.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep top-level `_target_` as accepted authored syntax | It preserves the ambiguous construction contract this phase exists to remove. No-argument stages have a clear `factory` shape with empty `init`. |
| Preserve `target_path=` as a direct `StageSpec` constructor argument | The dataclass should reflect the public contract. A read-only `target_path` property is enough to keep internal churn reviewable. |
| Reuse `loom.config.instantiate.targets.import_target` from execution | It routes execution construction through `loom.config` and weakens the no-extra import boundary, even if the helper itself is lightweight. |
| Treat authored stage mappings as full generic config object graphs | It would couple pipeline execution to optional config dependencies and recursive instantiation behavior that belongs to `loom.config`. |
| Put constructor kwargs under `config` | It breaks the selected remediation that `config` remains `StageContext.stage_config` for runtime invocation. |
| Include `resources` or all operational hints in the stage fingerprint | CPU, memory, logs, scheduling, and similar hints should not force reruns unless a later phase explicitly marks them semantic. |
| Drop declared outputs from the fingerprint payload | Output declarations are part of the stage contract and are already reuse-relevant through resume checks. Keeping them inspectable avoids policy drift. |
| Compare only opaque fingerprint strings in tests | Opaque comparisons can miss policy drift; payload tests must assert which fields are included or excluded. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Short-lived migration churn from top-level `_target_` to `factory` in tests and docs | Breaking pre-v1 config shape is allowed to correct the public contract before v1 and CLI work. | Revisit only if implementation discovers generated or third-party fixtures that cannot be migrated within Phase 3 scope. |
| A lightweight pipeline target import helper duplicates part of `loom.config.instantiate.targets` | Execution must remain import-safe without config extras, and full config instantiation remains out of scope. | Revisit in Phase 6 or plugin discovery work if target aliases, catalogs, or shared resolution policy become necessary. |
| `StageSpec.target_path` remains as a derived compatibility property | It keeps the Phase 3 diff reviewable while model users migrate to `stage.factory.target_path`. | Remove or deprecate after Phase 7 if no internal callers or docs rely on it. |
| v1 fingerprint records are only compatible enough to become stale, not reusable | The factory policy changes semantic inputs, so reusing old records would be incorrect. | Revisit only if a pre-v1 migration tool is added in the Phase 8 hardening notes. |
| Explicit fingerprint fields are a minimal plain-data mapping, not a full include/exclude policy language | The phase needs declared semantic fields without expanding into planner diagnostics or config expression language. | Revisit when CLI/preflight explanations or project-level fingerprint policy need richer controls. |

## Reviewability

- Expected PR size and shape: one focused contract PR touching pipeline specs,
  stage construction, fingerprint models/helpers, targeted tests, and the four
  named docs. It should not include runner lifecycle decomposition, planner
  helper extraction, runtime/events/locks, catalogs, bundles, sweeps, remote
  stores, or executor policy work.
- Files and areas to inspect:
  - `src/loom/pipeline/specs.py`
  - `src/loom/pipeline/stage_factory.py`
  - `src/loom/pipeline/stage.py`
  - `src/loom/pipeline/execution/runner.py`
  - `src/loom/pipeline/planning/fingerprints.py`
  - `src/loom/pipeline/planning/models.py`
  - `src/loom/pipeline/planning/resume.py`
  - `src/loom/pipeline/__init__.py`
  - `tests/package/test_import_boundaries.py`
  - `tests/package/test_pipeline_api.py`
  - `tests/package/test_pipeline_execution_api.py`
  - `tests/package/test_pipeline_planning_api.py`
  - `tests/unit/loom/pipeline/test_specs.py`
  - `tests/unit/loom/pipeline/test_stage.py`
  - a focused unit test module for `loom.pipeline.stage_factory`
  - `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`
  - `tests/unit/loom/pipeline/planning/test_models.py`
  - `tests/unit/loom/pipeline/planning/test_resume.py`
  - `tests/integration/pipeline/test_pipeline_config.py`
  - `tests/integration/pipeline/test_local_execution.py`
  - `tests/integration/pipeline/test_local_execution_resume.py`
  - `tests/integration/pipeline/test_planning_resume.py`
  - `tests/integration/pipeline/test_plan_persistence.py`
  - `tests/integration/docs/test_v0_python_examples.py`
  - `tests/integration/config/test_compose_config.py`
  - `tests/e2e/test_local_pipeline_run.py`
  - `tests/support/pipeline_execution_configs.py`
  - `tests/support/pipeline_execution_stages.py`
  - `docs/structure.md`
  - `docs/features/pipeline.md`
  - `docs/features/execution.md`
  - `docs/features/fingerprints.md`
- Scope-control checks:
  - No concrete event, lock, runtime/resource, blocked-outcome, or runner
    decomposition work.
  - No planner policy extraction or `PlanExplanation` work.
  - No optional config dependency import through pipeline or execution imports.
  - No constructor values in `StageContext.stage_config`.
  - No change to `Stage.run(context, inputs)`.
  - No semantic fingerprint invalidation from `resources` changes.
  - No authored top-level `_target_` compatibility bridge.

## Implementation Steps

1. Add `StageFactorySpec` in `src/loom/pipeline/specs.py`, export it, and cover
   direct construction, `from_config()`, immutability, and plain-data validation
   with unit tests.
2. Update `StageSpec` parsing and construction to require `factory`, reject
   legacy top-level `_target_`, parse `fingerprint` into `fingerprint_fields`,
   and retain `target_path` as a derived property.
3. Migrate direct `StageSpec(...)` call sites and authored test fixtures from
   `target_path` or top-level `_target_` to `StageFactorySpec` or authored
   `factory`.
4. Add `src/loom/pipeline/stage_factory.py` with import and construction helper
   behavior defined above. Add focused unit tests for dotted/colon target
   import, constructor kwargs, callable factories, pre-instantiated stages,
   non-empty init with instance failure, protocol failure, and error paths.
5. Update `PipelineRunner._construct_stage()` to use the new helper and ensure
   `StageContext.stage_config` receives only authored runtime `config`.
6. Update package import-boundary tests so importing `loom.pipeline`,
   `loom.pipeline.stage_factory`, and `loom.pipeline.execution` does not import
   `loom.config`, optional config dependencies, CLI layers, stores through the
   factory helper, or project packages.
7. Update fingerprint constants, `StageFingerprintPayload`, record
   serialization, payload hash input, and v1 policy-changed handling.
8. Update `build_stage_fingerprint()` to include `factory_target`,
   `factory_init`, `fingerprint_fields`, runtime `stage_config`, declared and
   bound inputs, declared outputs, and environment identity while excluding
   `resources`.
9. Update planning/resume tests so factory target/init, runtime config, input
   checksums/fingerprints, explicit fingerprint fields, declared outputs, and
   environment context changes rerun; resources and artifact URI changes do not.
10. Migrate local execution support stages/configs and add a constructor-init
    stage or factory callable that proves `factory.init` reaches construction
    while `StageContext.stage_config` remains runtime-only.
11. Update config-extra composition tests and docs example tests so composed
    pipeline configs preserve the authored `factory` shape and remain parseable.
12. Update `docs/structure.md`, `docs/features/pipeline.md`,
    `docs/features/execution.md`, and `docs/features/fingerprints.md` for the
    new public contract and semantic policy.
13. During implementation, run targeted package/unit/integration/e2e/config
    checks after each slice. Leave final `make validate-pr` and
    `make test-summary` evidence for PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`,
  `tests/package/test_pipeline_api.py`,
  `tests/package/test_pipeline_execution_api.py`, and
  `tests/package/test_pipeline_planning_api.py`.
- Required assertions: importing `loom.pipeline`,
  `loom.pipeline.stage_factory`, and `loom.pipeline.execution` must not import
  `loom.config`, `yaml`, `omegaconf`, `pydantic`, `loom.cli`, or project
  packages. `StageFactorySpec` public export is intentional. Pipeline planning
  and execution APIs remain lazy enough to preserve no-extra import safety.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/test_specs.py`,
  `tests/unit/loom/pipeline/test_stage.py`, a new focused
  `tests/unit/loom/pipeline/test_stage_factory.py`,
  `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`,
  `tests/unit/loom/pipeline/planning/test_models.py`, and
  `tests/unit/loom/pipeline/planning/test_resume.py`.
- Required assertions: `factory` parsing, default empty init, strict
  `factory` unknown-key rejection, top-level `_target_` rejection, direct
  `StageFactorySpec` construction, recursive immutability, explicit
  `fingerprint` parsing, `Stage` protocol preservation, constructor error
  paths, callable/class/instance construction behavior, v2 fingerprint payload
  round trip, v1 policy-changed stale behavior, semantic field inclusion, and
  non-semantic resource/URI exclusion.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_stage_contract.py`,
  `tests/contracts/test_executor_contract.py`, and
  `tests/contracts/test_store_contract.py`.
- Required assertions: the stage contract remains `run(context, inputs)`,
  executor request/result contracts remain compatible with a constructed stage
  object, and stores can persist/read the v2 `fingerprint.json` mapping without
  widening store protocols. No broad store capability changes are in scope.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_pipeline_config.py`,
  `tests/integration/pipeline/test_local_execution.py`,
  `tests/integration/pipeline/test_local_execution_resume.py`,
  `tests/integration/pipeline/test_planning_resume.py`,
  `tests/integration/pipeline/test_plan_persistence.py`, and
  `tests/integration/docs/test_v0_python_examples.py`.
- Required assertions: composed and plain pipeline configs parse with
  `factory`; local `PipelineRunner` constructs a stage with `factory.init`;
  runtime `config` remains available through `StageContext.stage_config`;
  resume reruns when factory target/init, explicit fingerprint fields, runtime
  config, input checksum/fingerprint, output declaration, or environment
  identity changes; resume does not rerun when only `resources` or artifact URI
  changes; persisted plans/fingerprints remain readable and inspectable.

### E2E Suite

- Status: required but focused.
- Expected paths: `tests/e2e/test_local_pipeline_run.py`.
- Required assertions: the public local pipeline path works with authored
  `factory` blocks, persisted `fingerprint.json` uses the v2 semantic payload,
  and constructor values are not routed through runtime stage config. Broader
  hardening e2e coverage for final migration notes remains Phase 8 work.

### Opt-In Suites

- Status: required.
- Markers affected: `optional_dependency`; Makefile target `make
  test-config-extra`.
- Required assertions: config composition with the `config` extra preserves
  authored `factory` blocks, optional config dependencies remain behind the
  `loom[config]` extra, composed pipeline execution still parses
  factory/runtime config separation, and no-extra package tests remain distinct
  from config-extra coverage.

### Pyright, Ruff, And Build

- Status: required before PR preparation.
- Expected commands: `make lint`, `make typecheck`, `make build`, and final
  `make validate-pr`.
- Required assertions: new dataclasses/protocol helpers are typed without
  ignores, import-boundary changes do not rely on dynamic typing shortcuts,
  Ruff passes, Pyright passes with config extra enabled, and source
  distribution/wheel builds.

### Explicit Deferrals

- Runtime/resource/event/lock tests are deferred because Phase 4 owns those
  foundations.
- Planner explanation and policy-helper tests are deferred because Phase 5 owns
  planner decomposition.
- Runner lifecycle subcomponent tests are deferred because Phase 7 owns
  lifecycle decomposition.
- Recipe catalog/fresh composition policy tests are deferred because Phase 6
  owns catalogs.
- Plugin discovery, subprocess, SLURM, container, retry, timeout, remote store,
  run catalog, bundle, sweep, cleanup, and retention tests are deferred because
  they are future roadmap work.

## Risks

- The main implementation risk is accidentally importing `loom.config` or
  optional config dependencies from pipeline/execution import paths while
  reusing target import behavior.
- Removing top-level `_target_` touches many tests and docs. Keep the migration
  mechanical and avoid unrelated cleanups.
- Fingerprint payload changes can silently alter resume behavior if tests only
  compare digests. Tests must inspect payload fields and prove both positive and
  negative invalidation cases.
- Constructor kwargs may tempt recursive instantiation or dependency injection.
  Keep `factory.init` as plain keyword data only.
- Narrow v1 fingerprint parsing should make old policy state stale, not
  reusable. Avoid overbuilding a migration framework in this phase.
- Documentation may already contain older `StageContext` and `_target_` wording.
  Update only the four named docs plus directly exercised docs examples.

## Validation Commands

Targeted development commands:

```sh
make test-package
uv run pytest tests/unit/loom/pipeline/test_specs.py tests/unit/loom/pipeline/test_stage.py tests/unit/loom/pipeline/test_stage_factory.py
uv run pytest tests/unit/loom/pipeline/planning/test_planning_fingerprints.py tests/unit/loom/pipeline/planning/test_models.py tests/unit/loom/pipeline/planning/test_resume.py
uv run pytest tests/contracts/test_stage_contract.py tests/contracts/test_executor_contract.py tests/contracts/test_store_contract.py
uv run pytest tests/integration/pipeline/test_pipeline_config.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py
uv run pytest tests/integration/docs/test_v0_python_examples.py
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
  - stage factory helper and runner wiring second;
  - fingerprint payload, policy versioning, and resume behavior third;
  - support fixtures, integration/e2e migration, config-extra coverage, and
    docs last.
- Tests to run with each slice:
  - specs slice: unit spec tests and package API/import-boundary tests;
  - construction slice: `test_stage_factory`, local execution integration
    tests, and package import-boundary tests;
  - fingerprint slice: fingerprint/model/resume unit tests, planning resume
    integration tests, and plan persistence tests;
  - docs/final slice: docs example integration tests, config-extra, e2e, lint,
    typecheck, and build.
- Decisions the executor must not revisit:
  - `factory.init` is constructor input;
  - authored `config` is runtime `StageContext.stage_config`;
  - authored top-level `_target_` is rejected;
  - direct `StageSpec(target_path=...)` compatibility is not preserved;
  - `StageSpec.target_path` is derived from `stage.factory.target_path`;
  - `run(context, inputs)` remains the stage execution contract;
  - operational hints are non-semantic by default;
  - declared outputs remain semantic;
  - no optional config dependency import is allowed through pipeline/execution
    imports;
  - v1 fingerprint records are stale under v2 policy, never reusable matches.
- Conditions that require stopping for the manager:
  - the implementation cannot preserve no-extra import safety;
  - the selected top-level `_target_` rejection creates broad unrelated churn
    outside tests/docs/source areas named here;
  - a public API decision beyond the documented factory/fingerprint contract is
    needed;
  - validation shows existing Phase 1 or Phase 2 contracts would need to be
    reopened;
  - implementation would require runtime/events/locks, planner decomposition,
    catalogs, bundles, sweeps, remote stores, or executor policy work.

## Refinement And Review Budget Status

- Phase implementation refinement: used
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in commit `ed907e7`.
- Final phase execution plan: completed by this refine pass; ready for
  `loom_phase_executor`.
- Implementation summary: completed in four implementation slices covering
  factory specs/target resolution, runner construction wiring, semantic
  fingerprint policy v2, fixture/docs migration, and config-extra local
  execution validation for constructor/runtime separation.
- Implementation validation: targeted package, unit, contract, integration,
  e2e, config-extra, Ruff, Pyright, build, and diff-check evidence recorded
  below. `make validate-pr` passed during implementation refinement; final
  `make test-summary` remains for PR preparation.
- Refinement summary: completed in the single allowed implementation refinement
  pass. Fixed phase-scoped documentation contract drift in `docs/structure.md`
  and `docs/features/fingerprints.md`, and cleaned formatting regressions in
  touched integration tests. No source behavior changes were required.
- PR preparation: in progress. The PR body artifact was drafted and refined in
  `docs/phases/v0-post-stage-factory-pr-body.md`; PR creation and reviewer
  notification are pending.
- Stack maintenance: serial human merge gate active; no successor may start
  until the Phase 3 PR is human-merged into `develop`.
- Remaining blockers: none.

## Slice 1 Evidence

- Slice 1 completed: factory model parsing plus import-safe stage factory target
  resolution helper.
- Files changed: `src/loom/pipeline/specs.py`, `src/loom/pipeline/stage_factory.py`,
  `src/loom/pipeline/__init__.py`, `tests/unit/loom/pipeline/test_specs.py`,
  `tests/unit/loom/pipeline/test_stage_factory.py`,
  `tests/package/test_import_boundaries.py`,
  `tests/package/test_pipeline_api.py`.
- Evidence command:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_specs.py tests/unit/loom/pipeline/test_stage_factory.py tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py`
  (40 passed).

## Slice 2 Evidence

- Slice 2 completed: runner construction wiring to `loom.pipeline.stage_factory`.
- Files changed: `src/loom/pipeline/execution/runner.py`,
  `tests/unit/loom/pipeline/execution/test_runner.py`.
- Evidence commands:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_stage_factory.py tests/unit/loom/pipeline/execution/test_runner.py`
    (10 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_api.py`
    (16 passed).

## Slice 3 Evidence

- Slice 3 completed: semantic fingerprint policy v2, v1 policy-changed resume
  handling, in-scope fixture migration from top-level `_target_` to `factory`,
  and public docs for the factory/fingerprint contract.
- Files changed: `src/loom/pipeline/planning/fingerprints.py`,
  `src/loom/pipeline/planning/models.py`, planning/graph/integration fixtures
  and tests, `examples/pipelines/local-run/pipeline.yaml`,
  `docs/structure.md`, `docs/features/pipeline.md`,
  `docs/features/execution.md`, and `docs/features/fingerprints.md`.
- Evidence commands:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_specs.py tests/unit/loom/pipeline/planning/test_planning_fingerprints.py tests/unit/loom/pipeline/planning/test_resume.py tests/package/test_pipeline_api.py tests/package/test_import_boundaries.py`
    (49 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_stage_factory.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/execution/test_execution_models.py tests/unit/loom/pipeline/graph/test_bindings.py tests/unit/loom/pipeline/graph/test_dag.py tests/unit/loom/pipeline/graph/test_topology.py tests/unit/loom/pipeline/planning/test_models.py tests/unit/loom/pipeline/planning/test_planner.py tests/unit/loom/pipeline/planning/test_planning_errors.py tests/unit/loom/pipeline/planning/test_selectors.py tests/integration/pipeline/test_pipeline_config.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_plan_persistence.py tests/integration/pipeline/test_planning_resume.py tests/integration/docs/test_v0_python_examples.py`
    (43 passed, 3 skipped in the no-extra environment).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` passed.
  - `git diff --check` passed.

## Slice 4 Evidence

- Slice 4 completed: config-extra/local execution cleanup, docs example YAML
  correction, integration proof that `factory.init` reaches the constructor
  while authored runtime `config` remains `StageContext.stage_config`, and
  Pyright migration of remaining test helpers away from `target_path=`.
- Files changed: `tests/support/pipeline_execution_stages.py`,
  `tests/integration/pipeline/test_local_execution.py`,
  `tests/integration/docs/test_v0_python_examples.py`,
  `tests/integration/pipeline/test_local_execution_failures.py`,
  `tests/unit/loom/pipeline/execution/test_outputs.py`,
  `tests/unit/loom/pipeline/executors/test_local_executor.py`, and
  `tests/unit/loom/pipeline/execution/test_runner.py`.
- Evidence commands:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/pipeline/test_pipeline_config.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/docs/test_v0_python_examples.py tests/integration/config/test_compose_config.py tests/e2e/test_local_pipeline_run.py`
    (21 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/execution/test_outputs.py tests/unit/loom/pipeline/executors/test_local_executor.py tests/unit/loom/pipeline/execution/test_runner.py`
    (9 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pyright` passed with 0
    errors.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` passed.
  - `git diff --check` passed.

## Implementation Refinement Evidence

- Refinement completed: docs and test-formatting cleanup after review of the
  Phase 3 diff against `develop`.
- Files changed: `docs/structure.md`, `docs/features/fingerprints.md`,
  `tests/integration/pipeline/test_pipeline_config.py`,
  `tests/integration/pipeline/test_planning_resume.py`, and this phase
  execution plan.
- Fixes:
  - Corrected `docs/structure.md` so `loom.pipeline` remains the owner of stage
    factory construction and only config composition / recursive target
    instantiation internals remain outside the pipeline import boundary.
  - Aligned `docs/features/fingerprints.md` with the implemented v2
    `StageFingerprintRecord` shape by removing a non-persisted top-level
    `stage_name`, using `policy_name`, documenting persisted `payload`, and
    clarifying that v0 stage fingerprints exclude artifact URI/location
    metadata when stronger semantic identity is available.
  - Restored readable indentation in two integration fixtures touched by the
    implementation.
- Evidence commands:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_planning_api.py`
    (21 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_specs.py tests/unit/loom/pipeline/test_stage.py tests/unit/loom/pipeline/test_stage_factory.py tests/unit/loom/pipeline/execution/test_runner.py`
    (31 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning/test_planning_fingerprints.py tests/unit/loom/pipeline/planning/test_models.py tests/unit/loom/pipeline/planning/test_resume.py`
    (18 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/pipeline/test_pipeline_config.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py tests/integration/docs/test_v0_python_examples.py tests/integration/config/test_compose_config.py tests/e2e/test_local_pipeline_run.py`
    (26 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_stage_contract.py tests/contracts/test_executor_contract.py tests/contracts/test_store_contract.py`
    (9 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/pipeline/test_pipeline_config.py tests/integration/pipeline/test_planning_resume.py tests/integration/docs/test_v0_python_examples.py tests/integration/config/test_compose_config.py tests/e2e/test_local_pipeline_run.py`
    (15 passed after the refinement patch).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning/test_planning_fingerprints.py tests/unit/loom/pipeline/planning/test_models.py tests/unit/loom/pipeline/planning/test_resume.py tests/package/test_import_boundaries.py`
    (29 passed after the refinement patch).
  - `git diff --check` passed.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed: Ruff, Pyright,
    default no-extra harness (325 passed, 9 skipped), config-extra harness
    (103 passed, 326 deselected), and build.
- Residual risks: none identified within Phase 3 scope. PR preparation should
  still run `make test-summary` for suite-level PR body evidence.

## PR Preparation Evidence

- PR preparer pass: in progress.
- Final diff and scope inspection: completed against `develop`; the diff is
  limited to Phase 3 factory parsing/construction, runner construction wiring,
  semantic fingerprint policy v2, in-scope fixtures/tests/examples, and the
  required docs.
- Scope guard: no Phase 4 runtime/resource/event/lock work, planner
  decomposition, recipe catalog changes, runner lifecycle decomposition,
  non-local executors, remote stores, catalogs, bundles, sweeps, retry,
  timeout, cleanup, retention, or migration closeout work was started.
- Validation command:
  `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`
  passed during PR preparation. Ruff passed; Pyright passed with 0 errors; the
  isolated default no-extra harness passed with 325 passed and 9 skipped; the
  isolated config-extra harness passed with 103 passed and 326 deselected; the
  source distribution and wheel built successfully.
- Suite summary command:
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary`
  passed and wrote `build/test-summary.md`.
- Suite summary rows: package passed (33 passed, 1 skipped), unit passed (271
  passed, 1 skipped), contract passed (13 passed, 1 skipped), integration
  passed (8 passed, 5 skipped), e2e passed (1 passed), config-extra passed
  (103 passed, 326 deselected).
- PR body artifact: `docs/phases/v0-post-stage-factory-pr-body.md`.
- PR creation status: pending push and GitHub PR creation.
- Review notification status: pending PR creation.
- Stack state: root serial phase; stack predecessor none; base and PR target
  are `develop`; no successor phase may start until the PR is human-approved
  and human-merged into `develop`.
- Remaining blockers: none.
