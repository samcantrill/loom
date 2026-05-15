# Phase 1 Execution Plan: Sweep Contracts And Manifests

## Metadata

- Status: merged
- Feature focus: Deterministic Sweeps
- PR title: `Deterministic Sweeps - Phase 1: Sweep Contracts And Manifests`
- Branch: `codex/sweep-contracts-manifests`
- Worktree: `/home/samcantrill/work/loom-worktrees/sweep-contracts-manifests`
- Phase execution plan path:
  `docs/roadmap/stage-13/phases/sweep-contracts-manifests.md`
- Full plan: `docs/roadmap/stage-13/implementation-plan.md`
- Source phase: Phase 1, `sweep-contracts-manifests`
- Stack predecessor: none
- Base branch: `origin/develop` at `73fef42064ecfab4f898993816b6765954892dee`
- Target branch: `develop`
- PR: [#151](https://github.com/samcantrill/loom/pull/151)
- Merge eligibility: root phase PR targets `develop`; merge-eligible only
  after implementation, phase validation, automated review, CI or justified
  unavailable checks, and target-branch verification pass.
- Workflow path: expanded path
- Successor dependency notes: Phase 2 should branch from this phase branch if
  Phase 1 is `pr_open` or `approved` but not merged; otherwise Phase 2 should
  branch from updated `develop`.
- Plan quality gate: passed in the implementation plan on 2026-05-14.
- Plan quality gate loop budget: implementation-plan review, refinement, and
  confirmation were used before this phase; no blocking findings remain.
- Draft pass: complete for this phase execution plan.
- Refine pass: complete for this expanded-path phase; no further planning pass
  is required before implementation.
- Setup limitations: no product code was implemented and no broad validation
  was run during planning. The control checkout has unrelated dirty/untracked
  files; phase work is isolated in the worktree above.
- Blockers: none.

## Objective

Establish the public sweep contract foundation for deterministic sweeps:
domain-neutral provider/proposal, feedback, dispatch, extraction, sweep/trial,
and manifest records that later phases can implement against without inventing
grid/manual, execution, queue, status, collection, or CLI behavior early.

## Full-Plan Context

This is the first of five Stage 13 phases. It creates the contract and
persistence surface that Phase 2 uses for grid/manual planning, Phase 3 uses
for early-stop and direct dispatch, Phase 4 uses for coordination, queue
dispatch, and status, and Phase 5 uses for collection and CLI hardening. Future
phase work must remain out of scope here: no expansion logic, no trial
execution, no queue enqueue behavior, no status aggregation, no collection, no
CLI commands, no plugin discovery, and no concrete optimizer or extraction
adapter.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: Phase 1 has no earlier Stage 13 predecessor,
  and the user assigned `origin/develop` as the clean current remote develop
  tip.
- Retarget/rebase plan after predecessor merge: none for this phase.
- Branch cleanup constraints: this branch can be deleted after merge only if no
  successor phase still targets or branches from it.

## Source Phase Summary

- Goal: establish public sweep contracts and persisted record schemas without
  expansion implementation, execution behavior, queue behavior, or CLI
  commands.
- Required scope: new `loom.pipeline.sweep` package boundary; import-light
  public exports; provider/proposal protocols with optional finite capability;
  sweep/trial/provider/feedback/extraction/dispatch value records; versioned
  manifest schemas; structured compatibility and unsupported-extraction
  diagnostics; package, unit, and contract tests.
- Required checkpoints: public records round-trip as plain data; provider
  protocol supports fake finite and unsized providers without mandatory
  `len()`; dispatch request/result records are shared and adapter-neutral;
  manifests reject unsupported schema versions; extraction default is explicit
  unsupported/not implemented; no optional optimizer, queue controller, CLI, or
  project-code imports leak into the sweep contract package.
- Acceptance criteria: Phase 1 evidence must prove contract reuse,
  domain-neutral metadata, stable manifest versioning, future-provider metadata
  space, and scope control against later phase behavior.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/pipeline/sweep/` does not exist on `origin/develop`; Phase 1
    should create it behind the `loom.pipeline.sweep` package boundary.
  - `src/loom/serialization/` already provides plain-data and schema-version
    helpers such as `PlainData`, `ensure_plain_data`, `stable_json_dumps`, and
    `load_versioned_document`; manifests should reuse these patterns.
  - `src/loom/pipeline/execution/models.py` exposes `RunRequest` and
    metadata-compatible execution records that later dispatch adapters will
    consume; Phase 1 should define planned-trial dispatch intent/result records
    without constructing real `RunRequest` values.
  - `src/loom/pipeline/status.py` already defines `CANCELLED` run/stage states
    but no `EARLY_STOPPED` core status; Phase 1 feedback/outcome records should
    leave lifecycle mapping to Phase 3 and status derivation to Phase 4.
  - `src/loom/pipeline/stores/coordination.py` already defines
    `SweepIdentity`, `TrialReference`, and `TrialState`; Phase 1 should preserve
    compatible identity fields without implementing coordination writes.
  - `src/loom/refs.py` and run/catalog modules provide resource and artifact
    reference vocabulary; extraction records should stay metadata/ref oriented.
- Existing tests or harness behavior:
  - Package/import-boundary tests live under `tests/package/`, including checks
    that root imports avoid CLI, execution, queue, optional services, and heavy
    dependencies.
  - Unit sweep tests should be added under
    `tests/unit/loom/pipeline/sweep/`; contract tests should be added under
    `tests/contracts/`.
  - Existing integration and e2e harnesses exist, but this phase is contract
    only and should not require integration or e2e execution.
- Import-boundary or dependency constraints:
  - Keep `loom.pipeline.sweep` below CLI and project code.
  - Do not import Optuna, Ray Tune, W&B, MLflow, DVC, Hydra sweepers, queue
    controllers, SLURM wrappers, FastAPI, or downstream project packages.
  - Avoid top-level `loom.__init__` re-exports; public Phase 1 contracts should
    be stable from `loom.pipeline.sweep` and import-light submodules.

## In-Scope Work

- Create `src/loom/pipeline/sweep/` with import-light package exports.
- Define public sweep, trial, provider identity, provider metadata, proposal,
  plan, dispatch intent/result, feedback/observation, extraction request/result,
  compatibility diagnostic, and manifest value models.
- Define a contextful provider/proposal protocol and optional finite-provider
  capability. The base contract must not require every provider to expose
  length or materialized plans.
- Define the minimal planned-trial dispatch request/result records consumed by
  later direct and queue dispatch adapters. Phase 1 owns record shape only.
- Define versioned `sweep.json` and `trials.json` manifest models, read/write
  helpers where appropriate, schema-version checks, and compatibility
  diagnostics.
- Define explicit unsupported/not-implemented extraction diagnostics as
  machine-readable records.
- Add package, unit, and contract tests that prove serialization,
  import-boundary, protocol, manifest, dispatch-record, feedback, and
  extraction-diagnostic behavior.

## Out-of-Scope Work

- Grid or manual provider expansion.
- Trial ID generation policy beyond the record fields/contracts needed to
  represent canonical `trial_id`, `trial_index`, and `run_uri` binding.
- Config override parsing, composition, or merge behavior.
- `context.stop_early(...)`, typed early-stop signal handling, or execution
  lifecycle changes.
- Direct sequential dispatch, queue dispatch, queue controller behavior, or
  `RunRequest` construction.
- Authority-backed coordination writes or status aggregation.
- Collection APIs, artifact payload extraction, metric parsing, or CSV output.
- `loom sweep` CLI commands, CLI parser registration, and command formatting.
- Plugin discovery and concrete external optimizer/extraction adapters.

## Assumptions

- Dataclasses, `Protocol`, `StrEnum`, plain-data mappings, and existing
  serialization helpers are sufficient for v13 public contracts.
- Manifest schemas can start at version `1` with explicit unsupported-version
  errors rather than migrations in this phase.
- Provider-supplied IDs remain metadata; Loom-owned canonical `trial_id`,
  `trial_index`, and `run_uri` binding are represented by sweep/trial records.
- The dispatch record can carry enough sweep/trial facts for later direct and
  queue adapters without importing queue models in Phase 1.
- Extraction default can be modeled as a result/diagnostic record without a real
  adapter implementation.

## Scope Contract

The executor may choose exact class and function names that fit local patterns,
but must preserve these public decisions:

- `loom.pipeline.sweep` is the stable public package for Phase 1 contracts; CLI,
  queue controller, optimizer, and project-code dependencies are forbidden.
- All persisted or feedback-compatible records are plain-data-compatible,
  versioned where durable, and inspectable without project imports.
- Provider contracts are contextful proposal streams with optional finite
  capabilities. A provider that cannot expose a finite count must still be a
  valid provider contract participant.
- Dispatch contracts are separate from provider contracts. They represent
  planned trial run intents and dispatch/submission outcomes, but do not
  execute, enqueue, or control runs.
- Loom owns canonical `trial_id`, `trial_index`, sweep manifest identity, and
  concrete `run_uri` mapping; provider/external IDs remain metadata fields.
- Feedback records may carry generic outcome/status/reason, artifact refs or
  metadata, and optional plain-data observations, but no objective, metric, or
  optimizer semantics are required fields.
- Extraction contracts must report unsupported/not-implemented behavior
  explicitly and machine-readably. No default payload parsing is allowed.
- Manifest compatibility errors must be structured enough for later plan,
  resume, run, and CLI layers to identify the sweep dir, schema version, trial
  id when applicable, and compatibility cause.

## Design Impact

- Maintainability: keeps foundational contracts in one small sweep package so
  later behavior phases consume shared records instead of inventing parallel
  request, result, and manifest shapes.
- Extensibility: reserves minimal provider metadata, feedback, dispatch, and
  extraction seams for future plugins, external optimizers, queue/distributed
  dispatch, and artifact materialization without adding those behaviors now.
- Domain neutrality: records plain metadata, observations, statuses, reasons,
  and artifact refs only; no project metric, objective, model, or report
  semantics belong in Phase 1.
- Source-tree boundaries: `loom.pipeline.sweep` may use public pipeline,
  serialization, IDs, status, refs, and artifact vocabulary, but must not depend
  on CLI, queue controller internals, SLURM wrappers, plugin discovery, optional
  optimizer packages, or project code.

## Future Compatibility

- V14 plugin discovery should be able to load providers later because Phase 1
  provider contracts are public, minimal, and plugin-free.
- Future Optuna-like providers should be able to express external IDs and
  provider facts through metadata and consume results through generic feedback
  records without changing grid/manual manifest shape.
- Phase 3 early-stop work can map controlled stops onto `CANCELLED` plus
  `early_stop` reason and report that through Phase 1 feedback records.
- Phase 4 direct/queue status and coordination work can reuse canonical
  `trial_id` and `run_uri` mapping without making coordination the only sweep
  authority.
- V15/V16 artifact work can attach real extraction/materialization adapters to
  the unsupported extraction seam later.
- V12 bundle/export compatibility remains ordinary-run compatibility. Phase 1
  must not create a sweep-specific export or bundle format.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement grid/manual expansion in Phase 1 | Would blur public contract review with behavior and make the provider protocol harder to inspect independently. |
| Use a bare iterable provider as the public contract | Cannot carry planning context, provider identity, diagnostics, metadata, optional finite capability, or future feedback cleanly. |
| Require every provider to implement `len()` or materialize all trials | Overfits to grid/manual and blocks future unsized or incremental providers. |
| Let providers own canonical trial IDs | Would destabilize sweep-local identity and run/catalog mapping; providers may record external IDs in metadata instead. |
| Merge generation and dispatch contracts | Would couple optimizer/provider logic to execution backend choice and queue policy. |
| Implement default artifact payload extraction now | Would imply metric/codecs/project-code semantics that v13 explicitly defers. |
| Add optimizer/plugin imports or concrete Optuna support | User confirmed concrete external providers are deferred and core must stay dependency-light. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Public provider and feedback contracts land before a concrete external optimizer adapter | User wants stable v13 contracts now, and fake finite/unsized providers plus grid/manual in Phase 2 can validate the shape without dependencies | A real Optuna/Ray Tune/etc. adapter cannot express proposals or feedback through context, metadata, and plain-data records |
| Manifest schema starts narrow and versioned before all later behavior exists | Later phases need a stable record to implement against, and v13 can preserve compatibility with explicit version checks | Phase 2-5 behavior requires fields that cannot be added compatibly or represented as metadata/extension fields |
| Extraction seam exists before extraction behavior | Future artifact work needs an attachment point, while v13 collection stays metadata/ref only | A later artifact/materialization stage selects safe plain-data extraction behavior |
| Dispatch request/result records are defined before direct and queue adapters | Prevents Phase 3 and Phase 4 from inventing divergent shapes | Queue or direct dispatch cannot represent required trial facts through the Phase 1 record |

## Reviewability

- Expected PR size and shape: medium foundational PR with new sweep package
  modules and focused package/unit/contract tests; no runtime behavior changes
  outside public export/import-boundary touch points.
- Files and areas to inspect:
  - `src/loom/pipeline/sweep/`
  - `src/loom/pipeline/__init__.py` only if export policy requires it
  - `tests/package/`
  - `tests/unit/loom/pipeline/sweep/`
  - `tests/contracts/`
- Scope-control checks:
  - No `src/loom/cli/sweep.py` or CLI parser behavior.
  - No `grid.py` or `manual.py` expansion behavior unless only empty module
    placeholders are justified by exports.
  - No `PipelineRunner` calls, queue enqueue calls, coordination writes, or
    early-stop lifecycle handling.
  - No optional optimizer, plugin, network, remote-service, SLURM, or
    project-code dependencies.

## Implementation Steps

1. Create the sweep package skeleton and public export boundary with import
   tests that keep `loom.pipeline.sweep` lightweight and optimizer-free.
2. Add value models for sweep/trial identity, provider metadata, proposals,
   plans, dispatch intent/result records, feedback/observation records, and
   extraction diagnostics using plain-data validation patterns already present
   in the repository.
3. Add provider/proposal protocols and optional finite capability contracts,
   plus fake finite and unsized provider tests that prove no mandatory `len()`
   assumption exists.
4. Add manifest models and compatibility diagnostics for `sweep.json` and
   `trials.json`, including schema-version validation and round-trip tests.
5. Add unsupported extraction request/result helpers and contract tests for
   machine-readable diagnostics.
6. Run targeted tests during implementation, then leave final PR-preparation
   validation to `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required
- Expected paths:
  - `tests/package/test_pipeline_api.py` or a new package API test
  - `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason:
  - `loom.pipeline.sweep` imports without importing CLI, queue controllers,
    execution runners, SLURM wrappers, optimizer packages, plugin discovery, or
    project packages.
  - Public sweep contract exports are explicit and stable.

### Unit Suite

- Status: required
- Expected paths:
  - `tests/unit/loom/pipeline/sweep/`
- Required assertions or deferral reason:
  - Value model validation, plain-data metadata normalization, required/unknown
    field diagnostics, provider metadata, trial/run URI mapping records,
    dispatch request/result records, feedback records, extraction diagnostics,
    and manifest round trips.

### Contract Suite

- Status: required
- Expected paths:
  - `tests/contracts/test_sweep_provider_contract.py`
  - `tests/contracts/test_sweep_manifest_contract.py`
  - `tests/contracts/test_sweep_dispatch_contract.py`
  - `tests/contracts/test_sweep_extraction_contract.py`
- Required assertions or deferral reason:
  - Fake finite and unsized providers satisfy the public provider protocol.
  - Optional finite capability is detected or consumed only when available.
  - Dispatch request/result records are adapter-neutral.
  - Feedback and extraction diagnostics serialize as plain data.
  - Manifests reject invalid or unsupported schema versions with structured
    errors.

### Integration Suite

- Status: deferred for Phase 1
- Expected paths:
  - none required in this phase
- Required assertions or deferral reason:
  - Phase 1 defines contracts only. Integration with `PipelineRunner`,
    queue service, coordination stores, status readers, collection, and CLI is
    owned by Phases 3-5. Do not add integration tests unless needed to protect
    an import boundary or serialization behavior that cannot be covered by
    package/unit/contract tests.

### E2E Suite

- Status: deferred for Phase 1
- Expected paths:
  - none required in this phase
- Required assertions or deferral reason:
  - No user-facing sweep workflow, CLI command, execution path, or collection
    path exists in Phase 1. Limited e2e coverage starts in later phases once
    planning/run/status/collect behavior exists.

### Opt-In Suites

- Status: deferred for Phase 1
- Markers affected:
  - `slurm_acceptance`
  - any network, real service, remote store, external optimizer, or downstream
    project suite
- Required assertions or deferral reason:
  - Phase 1 must remain local, deterministic, dependency-light, and
    domain-neutral. No real SLURM, queue service daemon, remote authority,
    Optuna, network, or project package validation is required.

## Risks

- Provider protocol surface may become too broad before grid/manual and fake
  providers prove the useful minimum.
- Manifest schemas may overfit future behavior or under-specify required
  compatibility diagnostics.
- Dispatch records may accidentally include direct-runner or queue-specific
  concepts that later adapters should own.
- Import-light exports can regress if contract modules import execution,
  queue, CLI, or optional optimizer dependencies for type convenience.
- Feedback records can drift into metric/objective semantics if generic
  observations are not kept plain and optional.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py
uv run pytest tests/unit/loom/pipeline/sweep tests/contracts/test_sweep_provider_contract.py tests/contracts/test_sweep_manifest_contract.py tests/contracts/test_sweep_dispatch_contract.py tests/contracts/test_sweep_extraction_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - package/public exports and import-boundary tests;
  - value records and plain-data validation;
  - provider and optional finite-capability protocols;
  - dispatch and feedback record contracts;
  - manifest schema and compatibility diagnostics;
  - unsupported extraction diagnostics.
- Tests to run with each slice:
  - package tests after export/import changes;
  - unit tests after value model and manifest changes;
  - contract tests after provider, dispatch, feedback, and extraction seams.
- Decisions the executor must not revisit:
  - no concrete Optuna or external provider implementation;
  - no mandatory provider `len()`;
  - no provider-owned canonical trial IDs;
  - no merged generation/dispatch interface;
  - no default artifact payload extraction;
  - no CLI, queue dispatch behavior, coordination writes, direct execution, or
    early-stop lifecycle handling in Phase 1.
- Conditions that require stopping for the manager:
  - provider contracts cannot represent both fake finite and fake unsized
    providers without special cases;
  - contract records require optional optimizer, queue controller, CLI, or
    project-code imports;
  - manifest compatibility cannot distinguish unsupported schema versions from
    malformed records;
  - planned-trial dispatch records cannot stay adapter-neutral;
  - implementation requires changing core lifecycle statuses, config merge
    semantics, queue policy, or run-store truth.

## Refinement And Review Budget Status

- Phase execution plan draft: complete
- Phase execution plan refine: complete for expanded path
- Phase implementation refinement: used as manager-local completion and
  pre-submit correction after executor checkpoint; no separate refiner subagent
  was run.
- PR review: used by manager pre-submit review
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: complete on 2026-05-14 in the phase worktree.
- Final phase execution plan: complete on 2026-05-14; ready for
  `loom_phase_executor`.
- Implementation summary: complete on 2026-05-14. Added the import-light
  `loom.pipeline.sweep` contract package with provider/proposal protocols,
  optional finite-provider capability, trial records, adapter-neutral dispatch
  request/result records, feedback/observation records, unsupported extraction
  request/result diagnostics, and versioned sweep/trials manifest models with
  compatibility diagnostics and JSON read/write helpers. Added package, unit,
  and contract coverage for exports, import boundaries, plain-data
  round-trips, provider capabilities, dispatch records, manifest compatibility,
  feedback, and unsupported extraction.
- Implementation validation: targeted package tests passed
  (`45 passed`); targeted sweep unit and contract tests passed
  (`16 passed`); targeted Ruff passed; `make validate-pr` passed
  (Ruff, Pyright, default harness, config-extra harness, build); `make
  test-summary` passed and wrote `build/test-summary.md` with package
  `79 passed`, unit `1061 passed`, contract `190 passed`, integration
  `149 passed`, e2e `42 passed`, and config-extra `438 passed`.
- Refinement summary: manager-local refinement tightened the finite-provider
  runtime capability so plain sized objects do not count as finite providers,
  and corrected trials-manifest malformed-record compatibility diagnostics to
  report `sweep_id` rather than `trial_id`.
- Blocker-resolution summary: none; 0/3 blocker-resolution passes used.
- PR preparation: complete; opened
  [#151](https://github.com/samcantrill/loom/pull/151) against `develop` and
  verified `baseRefName=develop`, `headRefName=codex/sweep-contracts-manifests`,
  `state=OPEN`.
- Stack maintenance: root phase; no predecessor. Squash merged into `develop`
  as `6facf9d6e5d94d56e3073f787fde6b6ea44a091d`; remote phase branch deleted
  after merge because no successor branch depended on it.
- Remaining blockers: none.
