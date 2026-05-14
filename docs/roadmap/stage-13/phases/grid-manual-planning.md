# Phase 2 Execution Plan: Grid And Manual Planning

## Metadata

- Status: implementation complete; PR preparation pending
- Feature focus: Deterministic Sweeps
- PR title: `Deterministic Sweeps - Phase 2: Grid And Manual Planning`
- Branch: `codex/grid-manual-planning`
- Worktree: `/home/samcantrill/work/loom-worktrees/grid-manual-planning`
- Phase execution plan path:
  `docs/roadmap/stage-13/phases/grid-manual-planning.md`
- Full plan: `docs/roadmap/stage-13/implementation-plan.md`
- Source phase: Phase 2, `grid-manual-planning`
- Stack predecessor: none; Phase 1 is merged into `develop`.
- Base branch:
  `origin/develop` at `376fdec35d45be3016933b775c3e76e4b3266e67`
- Target branch: `develop`
- Merge eligibility: root phase PR targets `develop`; merge-eligible only
  after implementation, phase validation, automated review, CI or justified
  unavailable checks, and target-branch verification pass.
- Workflow path: expanded path
- Successor dependency notes: Phase 3 should branch from
  `codex/grid-manual-planning` if Phase 2 is `pr_open` or `approved` but not
  merged; otherwise Phase 3 should branch from updated `develop`.
- Plan quality gate: passed in the implementation plan on 2026-05-14.
- Plan quality gate loop budget: implementation-plan review, refinement, and
  confirmation were used before Phase 1; no blocking findings remain.
- Draft pass: complete for this phase execution plan.
- Refine pass: complete for this expanded-path phase; the artifact is final
  for implementation.
- Setup limitations: no product code was implemented and no validation was run
  during planning. The original control checkout has unrelated dirty/untracked
  files; phase work is isolated in the worktree above.
- Blockers: none.

## Objective

Implement deterministic finite sweep planning for first-party grid and manual
providers over the Phase 1 sweep contracts, including trusted spec
normalization, stable trial ordering and identities, guarded plan
materialization, run URI mapping, and plan-only manifest/spec artifact writes
without adding execution, queue, status, collection, or full CLI behavior.

## Full-Plan Context

Phase 1 landed the import-light `loom.pipeline.sweep` contract package with
provider/proposal protocols, trial records, dispatch records, feedback,
unsupported extraction diagnostics, and versioned sweep/trials manifests.
Phase 2 proves those contracts with built-in grid/manual planning. Phase 3
will add cooperative early-stop lifecycle handling and direct sequential
dispatch. Phase 4 will add authority coordination, queue dispatch, and status
aggregation. Phase 5 will add collection, CLI, docs, and final hardening.

Future-phase work must remain out of scope here: no trial execution, no
`RunRequest` construction, no early-stop helper or lifecycle mapping, no queue
enqueue behavior, no coordination writes, no status aggregation, no collection,
no full `loom sweep` CLI, no plugin discovery, and no concrete optimizer
adapter.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 1 PR
  [#151](https://github.com/samcantrill/loom/pull/151) was squash-merged into
  `develop` and recorded by `376fdec`.
- Why this base branch is correct: the assigned base is the current
  `origin/develop` tip at or after Phase 1 merge metadata; local
  `origin/develop` is `376fdec35d45be3016933b775c3e76e4b3266e67`.
- Retarget/rebase plan after predecessor merge: none for this root phase.
- Branch cleanup constraints: this branch can be deleted after merge only if no
  successor phase still targets or branches from it.

## Source Phase Summary

- Goal: implement deterministic finite sweep planning through first-party grid
  and manual providers over Phase 1 contracts.
- Required scope: trusted grid/manual spec parsing and normalization,
  deterministic cartesian grid expansion, explicit manual trial expansion,
  stable trial IDs/names, override values, run URI mapping, default generated
  trial guard of `100` with explicit override, built-in provider protocol
  conformance, and plan-only APIs that write/copy authored specs plus generated
  manifests.
- Required checkpoints: identical specs produce identical trial order, IDs,
  overrides, and run URI mapping; grid/manual providers satisfy the public
  provider protocol and finite capability; large plans fail unless explicitly
  opted in; generated manifests can be read and compatibility-checked; manual
  trials can represent externally generated lists without optimizer imports.
- Acceptance criteria: unit, contract, package, and narrow plan-only
  integration evidence proves deterministic planning, contract reuse,
  domain-neutral override facts, manifest compatibility, and strict scope
  control against execution or CLI behavior.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/pipeline/sweep/__init__.py` exports the Phase 1 public contract
    surface. Phase 2 public additions must update stable package export tests
    without making the package import execution, queue, CLI, authority,
    project, or optimizer modules.
  - `src/loom/pipeline/sweep/providers.py` defines
    `SweepProviderIdentity`, `SweepProviderContext`,
    `SweepProposalProvider`, `FiniteSweepProposalProvider`,
    `TrialProposal`, `provider_is_finite`, and `provider_trial_count`.
    Grid/manual providers must use these contracts rather than bypassing them.
  - `src/loom/pipeline/sweep/trials.py` defines `SweepTrialRecord` with
    canonical `trial_id`, `trial_index`, `sweep_id`, optional `run_uri`,
    optional `provider_trial_id`, `proposal_overrides`, and metadata.
  - `src/loom/pipeline/sweep/manifest.py` defines versioned `SweepManifest`
    and `TrialsManifest`, JSON read/write helpers, schema constants, and
    compatibility diagnostic helpers. Phase 2 should extend or reuse these
    helpers for plan-only writes and compatible open-existing checks instead
    of inventing a second manifest path.
  - `src/loom/pipeline/sweep/spec.py`, `grid.py`, `manual.py`, and
    `runner.py` do not exist yet on the Phase 2 base. Create only the modules
    needed for planning behavior.
  - `src/loom/config/overrides.py` owns override parsing and merge semantics.
    Sweep planning may validate or format ordinary override facts through
    existing override syntax/helpers, but must not implement config merging.
- Existing tests or harness behavior:
  - `tests/package/test_import_boundaries.py` already checks that
    `loom.pipeline.sweep` remains lightweight and does not import execution,
    queue, CLI, authority, project, or Optuna modules.
  - `tests/package/test_pipeline_api.py` locks `loom.pipeline.sweep.__all__`;
    public Phase 2 exports need matching package test updates.
  - Existing sweep unit tests live under `tests/unit/loom/pipeline/sweep/`.
  - Existing sweep contract tests cover provider, dispatch, manifest, and
    extraction contracts under `tests/contracts/`.
  - There is no `src/loom/cli/sweep.py`; CLI smoke is optional only if a
    parser shell already exists during implementation. Do not create CLI just
    for Phase 2.
- Import-boundary or dependency constraints:
  - Keep `loom.pipeline.sweep` below CLI and project code.
  - Do not import Optuna, Ray Tune, W&B, MLflow, DVC, Hydra sweepers, queue
    controllers, SLURM wrappers, FastAPI, or downstream project packages.
  - Preserve ordinary-run vocabulary: use `run_uri`, keep `trial_id` as
    sweep-local identity, and do not describe catalogs or manifests as
    authoritative run lifecycle truth.

## In-Scope Work

- Add trusted sweep spec value/normalization support for grid and manual
  modes, including plain-data metadata and a clear error surface for malformed
  specs.
- Implement first-party grid and manual providers over
  `SweepProposalProvider` and `FiniteSweepProposalProvider`.
- Implement deterministic grid cartesian expansion with stable axis ordering
  from the authored spec and deterministic value order within each axis.
- Implement explicit manual trial expansion with optional display names,
  optional provider/external trial IDs, plain-data metadata, and override
  facts.
- Implement canonical trial materialization from provider proposals into
  `SweepTrialRecord` values with stable index-based `trial_id` values,
  optional display names kept as metadata, separate provider IDs, and
  deterministic `run_uri` mapping.
- Enforce the default materialized-plan guard of `100` trials unless the
  caller/spec explicitly opts into a higher limit.
- Add plan-only APIs that can return an in-memory plan and write a sweep
  directory containing a copied authored spec when a spec path is supplied,
  plus generated `sweep.json` and `trials.json` manifests.
- Add plan-only compatibility/readback behavior for existing sweep directories:
  compatible manifests may be opened or reused for planning; incompatible
  manifests must return or raise structured diagnostics. Do not implement run
  resume or failed-trial filtering.
- Add focused package, unit, contract, and narrow integration tests for the
  behavior above.

## Out-of-Scope Work

- Executing planned trials or constructing real `RunRequest` values.
- Direct sequential dispatch, queue dispatch, queue controller behavior, or
  queue status.
- `context.stop_early(...)`, typed early-stop signal handling, lifecycle
  mapping, or derived `early_stopped` status.
- Authority-backed coordination writes or `SweepIdentity`/`TrialReference`
  projection.
- Status aggregation, collection, extraction adapters, artifact payload
  parsing, metrics, or result summaries.
- Full `loom sweep` CLI parser/handlers, CLI output formatting, and user
  workflow docs beyond any minimal doc/test updates needed for planning APIs.
- Rich rerun/filtering/retry policy, failed-only reruns, from-trial selection,
  scheduled-trial cancellation, bounded concurrency, distributed controllers,
  SLURM per-trial submission, plugin discovery, or concrete external optimizer
  adapters.

## Assumptions

- Authored sweep specs are trusted project code, consistent with repository
  config policy.
- Phase 1 records are the public persistence and provider contract foundation;
  Phase 2 may add planning-specific public records only when needed to express
  grid/manual behavior.
- Canonical trial IDs are Loom-owned, index-based, stable for a given
  normalized plan, and independent of provider IDs, manual names, parameter
  values, and filesystem paths.
- Manual trial names are display metadata, not identity.
- Override facts can be represented as plain path-to-value mappings and
  validated or converted through existing override syntax/helpers without
  implementing merge behavior.
- Plan-only filesystem writes can use local `Path` operations and the existing
  manifest JSON helpers; no remote store or run-store integration is required
  in this phase.

## Scope Contract

The executor may choose exact class/function names that fit local patterns,
but must preserve these public and persisted behavior decisions:

- Grid and manual planning must use the public provider/proposal contracts.
  Built-ins may have convenience APIs, but their expansion path must produce
  `TrialProposal` values through `SweepProposalProvider`.
- Both built-in providers are finite providers. `provider_trial_count()` must
  return the deterministic trial count for grid and manual providers.
- Normalized specs are plain-data-compatible and domain-neutral. Supported
  shapes must cover a grid axes mapping of config paths to ordered values and
  a manual trial sequence of override mappings with optional name, provider
  trial ID, and metadata.
- Override keys are config override paths; override values are `PlainData`.
  Planning may validate paths and values through existing config override
  helpers, but sweep code must not apply overrides or implement config merge
  semantics.
- Grid expansion order is deterministic: preserve authored axis order and
  value order, and produce cartesian products in a documented stable order.
  Do not sort by parameter name unless that is the only available normalized
  order for a mapping constructed without source ordering.
- Canonical `trial_id` values are generated from final trial indexes using a
  stable, index-based format. Provider/external IDs and manual names are
  metadata or `provider_trial_id`; they must not replace canonical
  `trial_id`.
- `run_uri` mapping is deterministic from the sweep output root and canonical
  trial ID. It must be persisted in trials manifests and remain separate from
  `trial_id`.
- The default max materialized trial count is `100`. Plans above the limit
  fail with a structured sweep planning error or diagnostic unless the spec/API
  explicitly supplies a larger limit.
- Plan-only APIs write versioned manifests through the Phase 1 manifest
  helpers. Existing manifests are opened through compatibility checks; do not
  silently overwrite incompatible manifests.
- Plan-only compatibility is not execution resume. Phase 3 owns run resume and
  dispatch behavior.

## Design Impact

- Maintainability: centralizes planning behavior in `loom.pipeline.sweep`
  spec/grid/manual/trial planning modules, keeping later execution and queue
  phases on the same records rather than duplicating expansion or identity
  logic.
- Extensibility: proves the provider seam with first-party finite providers
  while leaving room for future plugin-loaded or optimizer-backed providers to
  emit manual-like proposals and provider metadata.
- Domain neutrality: treats axes, manual trials, overrides, and metadata as
  generic config facts; no metric, objective, model, dataset, or report
  semantics are introduced.
- Source-tree boundaries: sweep planning may use serialization, config
  override parsing/validation, refs/path vocabulary, and Phase 1 sweep
  contracts, but must not depend on CLI, execution runners, queue controllers,
  authority stores, plugin discovery, optional optimizer packages, or project
  code.

## Future Compatibility

- Phase 3 can construct direct dispatch requests and `RunRequest` values from
  the Phase 2 `SweepTrialRecord`/manifest outputs without re-expanding specs.
- Phase 4 can record coordination facts from the persisted `trial_id` to
  `run_uri` mapping without treating coordination as the planning authority.
- Phase 5 can wrap the plan-only APIs in `loom sweep plan` without moving
  business logic into CLI handlers.
- Manual trial specs can represent externally generated or optimizer-suggested
  finite trial lists through provider trial IDs and metadata, with no Optuna or
  optimizer import.
- Future adaptive or unsized providers remain compatible because Phase 2 only
  claims finite materialization for built-in grid/manual providers and does
  not narrow the base provider protocol.
- V12 bundle/export compatibility remains ordinary-run compatibility; Phase 2
  writes sweep manifests and run URI mappings only, not a sweep-specific export
  format.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement grid/manual expansion as private helpers that skip the provider protocol | Would fail the Stage 13 adapter-first design goal and leave future providers without tested reuse evidence. |
| Derive `trial_id` from parameter names, values, or manual names | Makes identity brittle when values are renamed, redacted, reordered, or display names change. |
| Let manual specs supply canonical `trial_id` values | Conflicts with Loom-owned sweep-local identity; external IDs can be preserved as `provider_trial_id` or metadata. |
| Apply config overrides to composed configs during planning | Duplicates config merge semantics and couples planning to config composition instead of producing ordinary override facts. |
| Make large grid/manual plans warn but continue by default | The user selected a default guard of `100`; silent or warning-only behavior risks accidental large local plans. |
| Add a Phase 2 CLI command to smoke-test planning | Full CLI is Phase 5. Creating CLI now would expand scope and duplicate planning presentation decisions. |
| Treat compatible manifest open as execution resume | Execution resume belongs with dispatch in Phase 3; Phase 2 should only prove plan/manifests compatibility. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Spec shape is introduced before full CLI and docs hardening | Planning APIs need a stable authored/normalized shape now; Phase 5 will make the user-facing CLI/docs complete | CLI ergonomics require aliases or compatibility rules not represented by the Phase 2 spec records |
| Built-in providers validate only finite deterministic planning | V13 Phase 2 scope is grid/manual planning; adaptive and unsized behavior remains represented by Phase 1 contracts | A future external provider needs non-finite planning hooks in built-in planner paths |
| Plan-only compatibility stops before run resume | Keeps Phase 2 focused on manifests and planning while Phase 3 owns execution resume | Direct dispatch cannot reuse compatible manifests without changing Phase 2 plan records |
| Run URI mapping policy lands before direct dispatch | Later dispatch needs stable mapping; Phase 2 can validate it without executing runs | Runner integration in Phase 3 exposes a mismatch between planned run URIs and `RunRequest` requirements |

## Reviewability

- Expected PR size and shape: medium behavior PR that adds spec/grid/manual
  planning modules, public exports where needed, manifest/readback helpers or
  small extensions, and focused tests. No execution, queue, coordination,
  status, collection, or CLI handlers.
- Files and areas to inspect:
  - `src/loom/pipeline/sweep/spec.py`
  - `src/loom/pipeline/sweep/grid.py`
  - `src/loom/pipeline/sweep/manual.py`
  - `src/loom/pipeline/sweep/trials.py`
  - `src/loom/pipeline/sweep/manifest.py`
  - `src/loom/pipeline/sweep/__init__.py`
  - `tests/package/`
  - `tests/unit/loom/pipeline/sweep/`
  - `tests/contracts/test_sweep_provider_contract.py`
  - new or updated sweep planning/manifest contract tests
  - narrow plan-only integration tests if filesystem API behavior is not fully
    covered by unit tests
- Scope-control checks:
  - No `src/loom/cli/sweep.py` or CLI parser registration unless an existing
    parser shell appears before implementation and only a smoke hook is needed.
  - No `PipelineRunner` calls, `RunRequest` construction, queue enqueue calls,
    coordination writes, status aggregation, collection, or early-stop
    lifecycle changes.
  - No optional optimizer, plugin, network, remote-service, SLURM, or
    project-code dependencies.
  - No config merge/apply behavior inside sweep planning.

## Implementation Steps

1. Add normalized grid/manual spec records and planning errors/diagnostics,
   using plain-data validation and existing config override parsing helpers for
   path/value validation.
2. Implement grid and manual providers as finite `SweepProposalProvider`
   implementations, with deterministic proposal order and provider identity
   metadata.
3. Add trial materialization helpers that convert proposals into
   `SweepTrialRecord` values with stable IDs, optional names in metadata,
   provider trial IDs, override facts, and deterministic `run_uri` mappings.
4. Add the plan-only API layer that produces in-memory plans, enforces the
   default `100` trial guard with explicit override, and writes/copied authored
   specs plus generated manifests.
5. Add compatible open-existing/readback checks for plan directories using the
   Phase 1 manifest compatibility helpers.
6. Add/update package, unit, contract, and narrow integration tests, then leave
   final PR-preparation validation to `make validate-pr` and
   `make test-summary`.

## Test Plan

### Package Suite

- Status: required
- Expected paths:
  - `tests/package/test_import_boundaries.py`
  - `tests/package/test_pipeline_api.py`
- Required assertions or deferral reason:
  - Any new public sweep planning exports are listed in `loom.pipeline.sweep`
    package API tests.
  - Importing `loom.pipeline.sweep` after Phase 2 still does not import
    execution, queue, CLI, authority, project, Optuna, or other optional
    optimizer/service modules.

### Unit Suite

- Status: required
- Expected paths:
  - `tests/unit/loom/pipeline/sweep/`
- Required assertions or deferral reason:
  - Grid spec normalization rejects malformed axes and preserves deterministic
    axis/value order.
  - Manual spec normalization rejects malformed trial entries and preserves
    explicit order, names, provider IDs, metadata, and overrides.
  - Trial materialization generates stable index-based `trial_id` values,
    stable display metadata, separate provider IDs, deterministic run URIs,
    and expected `proposal_overrides`.
  - The default `100` trial guard fails above the limit and accepts an explicit
    larger limit.
  - Plan-only manifest writes and readback round-trip generated records and
    copied authored spec metadata.
  - Existing manifest compatibility checks distinguish compatible readback from
    unsupported schema, malformed manifests, sweep ID mismatch, and changed
    plan facts.

### Contract Suite

- Status: required
- Expected paths:
  - `tests/contracts/test_sweep_provider_contract.py`
  - new or updated `tests/contracts/test_sweep_planning_contract.py`
  - `tests/contracts/test_sweep_manifest_contract.py`
- Required assertions or deferral reason:
  - Built-in grid and manual providers satisfy `SweepProposalProvider` and
    `FiniteSweepProposalProvider`.
  - `provider_trial_count()` returns deterministic counts for both built-ins.
  - Grid/manual proposals serialize as plain-data `TrialProposal` records.
  - Planned trial records remain compatible with Phase 1 manifest contracts.
  - Manual provider records can represent externally generated trial lists
    through provider IDs and metadata without importing optimizer packages.

### Integration Suite

- Status: required, narrow plan-only coverage
- Expected paths:
  - `tests/integration/pipeline/sweep/` or an equivalent current integration
    location
- Required assertions or deferral reason:
  - Planning from an authored spec path writes the copied authored spec and
    generated `sweep.json`/`trials.json` files under a temporary sweep root.
  - Replanning or opening an existing compatible plan reads the manifests
    without execution.
  - Incompatible existing manifests produce structured diagnostics and do not
    silently overwrite generated records.
  - No `PipelineRunner`, queue service, authority store, or project code is
    required.

### E2E Suite

- Status: deferred for Phase 2
- Expected paths:
  - none required in this phase
- Required assertions or deferral reason:
  - No end-user sweep CLI, execution path, status command, or collection
    workflow exists yet. Limited e2e coverage belongs to Phase 5 after
    `loom sweep` commands exist.

### Opt-In Suites

- Status: deferred for Phase 2
- Markers affected:
  - `slurm_acceptance`
  - any network, real service, remote store, external optimizer, or downstream
    project suite
- Required assertions or deferral reason:
  - Phase 2 is local, deterministic, manifest/planning-only work. No real
    SLURM, queue daemon, authority service, remote store, Optuna, network, or
    project package validation is required.

## Risks

- Spec shape could become too broad before CLI/docs hardening; keep aliases
  and compatibility promises minimal.
- Override normalization could accidentally duplicate config parsing or merge
  semantics; use existing override helpers for validation and leave merge to
  `loom.config`.
- Trial ID or run URI mapping could bake in unstable display names or absolute
  temp paths; identity must be index-based and deterministic from explicit
  inputs.
- Manifest compatibility checks could accept changed plans too loosely or
  reject compatible manifests too aggressively; tests must cover both paths.
- Built-in providers could overfit the provider protocol to finite providers;
  preserve Phase 1 support for unsized providers even though grid/manual are
  finite.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py
uv run pytest tests/unit/loom/pipeline/sweep
uv run pytest tests/contracts/test_sweep_provider_contract.py tests/contracts/test_sweep_manifest_contract.py tests/contracts/test_sweep_planning_contract.py
uv run pytest tests/integration/pipeline/sweep
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - spec records, validation errors, and package exports;
  - grid/manual provider implementations and provider contract tests;
  - trial materialization, ID/name/run URI mapping, and guard behavior;
  - plan-only manifest/spec write/read APIs and compatibility checks;
  - focused package/unit/contract/integration coverage.
- Tests to run with each slice:
  - package tests after export/import changes;
  - unit tests after spec, provider, trial materialization, and manifest
    helpers;
  - contract tests after provider protocol and plan record changes;
  - narrow integration tests after plan-only filesystem writes/readback.
- Decisions the executor must not revisit:
  - grid/manual must use the provider protocol;
  - default trial guard is `100` unless explicitly overridden;
  - canonical `trial_id` is Loom-owned, index-based, and separate from
    `run_uri`, manual names, and provider IDs;
  - sweep planning produces override facts and must not apply config merges;
  - no execution, early stop, queue, coordination, status, collection, full
    CLI, plugin discovery, or optimizer implementation in Phase 2.
- Conditions that require stopping for the manager:
  - existing config override APIs cannot validate or represent required trial
    override facts without a new merge language;
  - Phase 1 manifest contracts cannot represent generated plans and compatible
    readback without incompatible schema changes;
  - deterministic run URI mapping cannot be defined without changing runner or
    run-store public contracts;
  - implementation would require importing execution, queue, CLI, authority,
    optional optimizer, remote service, or project-code modules into
    `loom.pipeline.sweep`;
  - satisfying Phase 2 requires implementing run resume, dispatch, status,
    collection, or CLI behavior from later phases.

## Refinement And Review Budget Status

- Phase execution plan draft: complete
- Phase execution plan refine: complete for expanded path
- Phase implementation refinement: used locally after the first full
  validation run reported Pyright findings in manual-trial typing and
  plain-data payload indexing
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: complete on 2026-05-14 in the phase worktree.
- Final phase execution plan: complete on 2026-05-14; ready for
  `loom_phase_executor`.
- Implementation summary: Added trusted grid/manual sweep spec records,
  first-party finite grid/manual providers, deterministic proposal
  materialization into `SweepTrialRecord` values, stable index-based
  `trial_id` generation, deterministic run URI mapping, default
  `100`-trial guard with explicit override, authored-spec/manifests plan-only
  writes, compatible readback, and incompatible-plan diagnostics.
- Implementation validation: Targeted Phase 2 validation passed
  (`uv run pytest tests/unit/loom/pipeline/sweep
  tests/contracts/test_sweep_provider_contract.py
  tests/contracts/test_sweep_manifest_contract.py
  tests/contracts/test_sweep_planning_contract.py
  tests/package/test_pipeline_api.py tests/package/test_import_boundaries.py
  tests/integration/pipeline/sweep`: 70 passed). Targeted Ruff passed.
  `make validate-pr` passed after the local type-check fix. `make
  test-summary` passed and wrote `build/test-summary.md`: package 79 passed,
  unit 1068 passed, contract 194 passed, integration 151 passed, e2e 42
  passed, config-extra 438 passed.
- Refinement summary: one local implementation refinement was used to address
  Pyright findings from the first full validation run; no scope expansion was
  introduced.
- Blocker-resolution summary: none; 0/3 blocker-resolution passes used.
- PR preparation: pending.
- Stack maintenance: root phase; no predecessor because Phase 1 is merged.
- Remaining blockers: none.
