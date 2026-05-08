# Phase 3 Execution Plan: SLURM Models, Options, Resources, And Manifest Schema

## Metadata

- Status: draft phase execution plan
- Feature focus: SLURM Script Planning
- PR title: `SLURM Script Planning - Phase 3: SLURM Models and Manifest Schema`
- Branch: `codex/slurm-dry-run-models`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-dry-run-models`
- Phase execution plan path: `docs/phases/slurm-dry-run-models.md`
- Full plan: `docs/implementation-plans/implementation-plan-v6.md`
- Source phase: Phase 3 - SLURM Models, Options, Resources, And Manifest Schema
- Stack predecessor: none; Phase 2 is merged into `develop`
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase; merge-eligible when the PR targets `develop`, automated review passes, and validation/CI passes
- Workflow path: expanded path
- Expanded-path status: draft pass complete; refine pass pending before implementation handoff
- Successor dependency notes: Phase 4 consumes the model, resource-mapping, logical dependency, manifest, launcher argv, and generated-artifact path contracts from this phase to render scripts and write dry-run artifacts.
- Plan quality gate: passed on 2026-05-08 after initial review, one refinement pass, and confirmation review
- Plan quality gate loop budget: initial review used, refinement used, confirmation review used
- Draft pass: completed by `loom_phase_planner`
- Refine pass: pending for expanded path
- Setup limitations: Worktree was created from local `develop` at `de75ffe`; no remote synchronization or validation was run in this planning-only pass.
- Blockers: none known for the refine pass or implementation handoff

## Objective

Add the pure SLURM dry-run vocabulary under `loom.pipeline.executors.slurm`: modes, structured options, validated `extra_sbatch`, launcher argv records, resource-to-SBATCH mapping, logical job/dependency records, and schema-versioned planned submission manifests. This phase must not generate scripts, expose CLI behavior, call scheduler commands, or persist submitted scheduler state.

## Full-Plan Context

V6 builds dry-run SLURM script planning in small layers. Phase 1 merged generic prepared-run metadata, lifecycle helpers, and the store-owned generated-artifact path helper. Phase 2 merged generic continuation commands, including `loom prepared-run continue` and `loom stage-job run`. This phase creates the SLURM model and mapper contracts that later phases render into scripts and expose through the CLI.

Phase 3 is intentionally side-effect free. It may validate and serialize planned submission data, construct logical paths through store-owned helpers, and map generic resource requests to planned SBATCH directive records, but it must not write shell scripts or invoke `sbatch`.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 2 merged in PR #83 and the v6 implementation plan records the merge metadata on `develop`
- Why this base branch is correct: Phase 1 and Phase 2 are both recorded as merged into `develop`, and the manager assigned `develop` as both base and target.
- Retarget/rebase plan after predecessor merge: none required unless `develop` moves before PR preparation, in which case rebase this branch onto updated `develop`.
- Branch cleanup constraints: branch can be deleted after merge if no successor branch depends on it.

## Source Phase Summary

- Goal: add structured SLURM dry-run vocabulary and mapper layer without script generation or CLI wiring.
- Required scope: `SlurmMode`, `SlurmOptions`, structured `extra_sbatch` validation, generated-command launcher argv, resource-to-SBATCH mapper, logical job keys, planned dependency records, planned job records, and planned submission manifest models under `loom.pipeline.executors.slurm`.
- Required store interaction: consume `LocalRunStorePaths.local_generated_artifact_path(run_uri, relative_path)` for paths under `slurm/submissions/<planning_id>/...`; do not add adapter-local run-directory path walking or import local-store internals.
- Acceptance criteria: structured option parsing rejects unknown fields and conflicts; `extra_sbatch` accepts only validated mapping entries and cannot override generated/modeled directives; resource conflicts fail with structured path-aware errors; manifest models round-trip with job IDs absent/null and dependencies expressed by logical job keys; SLURM planning code can request safe dry-run paths through the store contract.

## Current Source And Harness Findings

- Existing package shape: `src/loom/pipeline/executors/` currently has `base.py`, `errors.py`, `local.py`, `subprocess.py`, and an import-light `__init__.py`; there is no SLURM package yet.
- Existing resource model: `src/loom/pipeline/resources.py` defines `ResourceRequest` and `ResourceEntry` with default validators for `cpu`, `memory`, and `gpu`. Phase 3 should map those typed entries rather than reading old resource fields.
- Existing store helper: `src/loom/pipeline/stores/run_store.py` exposes `LocalRunStorePaths.local_generated_artifact_path(run_uri, relative_path)`, and `src/loom/pipeline/stores/local_runs.py` resolves safe relative paths under the run directory through `validate_safe_relative_path`.
- Existing path constraints: generated artifact relative paths reject absolute paths, traversal, empty components, whitespace, control characters, backslashes, and containment escapes. SLURM code should supply relative paths such as `slurm/submissions/<planning_id>/manifest.json`.
- Import-boundary constraints: lower executor code may import pipeline resources, stores protocols, serialization plain-data helpers, and executor errors. It must not import `loom.cli`, local-store implementation details, scheduler libraries, or future Phase 4 script rendering code that does not exist yet.

## In-Scope Work

- Add a new `loom.pipeline.executors.slurm` package with import-light public exports for Phase 3 model and mapper types.
- Add `SlurmMode` values for v6 dry-run planning modes: single-job and afterok. The public wire values should match the later executor names closely enough that Phase 5 CLI integration does not need an adapter translation table.
- Add `SlurmOptions` as a structured, schema-versioned model for common SBATCH options: `partition`, `account`, `qos`, `constraint`, `nodes`, `ntasks`, `cpus_per_task`, `mem`, `mem_per_cpu`, `gres`, `time`, `prelude`, `extra_sbatch`, and any narrowly required launcher-related fields.
- Add structured `extra_sbatch` validation as a mapping escape hatch. Valueless flags use `true`; valued flags use strings. Reject unknown value types, `false`, null, empty flags, whitespace/control characters, duplicate flags, and conflicts with generated or modeled directives.
- Define the generated-command launcher argv model as a structured sequence, defaulting to `["loom"]`, and validate configured launchers such as `["uv", "run", "loom"]` without shell parsing.
- Add a resource-to-SBATCH mapper for generic `cpu`, `memory`, and `gpu` `ResourceEntry` values, including structured path-aware errors for unsupported units, ambiguous option/resource conflicts, invalid amounts, and unsupported resource kinds.
- Add logical job key helpers or types for `pipeline` and `stage:<stage_name>` identities. Stage job keys must use existing stage-name validation where possible and remain independent of scheduler job IDs.
- Add planned dependency records using logical job keys and dependency type `afterok` for v6.
- Add planned job records with logical key, mode, command argv, planned script/log/manifest-relative paths where applicable, resource summary, SBATCH directive summary, dependency key references, and scheduler fields absent or explicitly null.
- Add planned submission manifest models with schema version, run URI, SLURM mode, dry-run flag, planning ID, created time, plan path, logical jobs, dependencies, generated command argv, resource summaries, script/log relative paths, and sanitized options.
- Add helper APIs that ask a `LocalRunStorePaths` implementation for safe generated artifact paths under `slurm/submissions/<planning_id>/...` without constructing absolute run-directory paths directly.
- Add focused package, unit, contract, and integration tests for model validation, deterministic serialization, resource mapping, logical dependencies, manifest round trips, and store path helper interaction.

## Out-of-Scope Work

- No shell script rendering, script file writing, executable-bit handling, shell quoting, wrapper bodies, or `#SBATCH` text generation; those belong to Phase 4.
- No CLI integration, `loom run --executor slurm-single-job`, `loom run --executor slurm-afterok`, text output, JSON CLI envelopes, or preflight presentation; those belong to Phase 5.
- No live command runner, `sbatch`, `squeue`, `sacct`, `scancel`, scheduler API dependency, real scheduler calls, or subprocess submission.
- No scheduler job ID parsing, scheduler job ID placeholders, submitted status, queued/running scheduler state, cancellation, polling, partial-submission recovery, or fake submitted records.
- No changes to generic continuation commands, `loom prepared-run continue`, `loom stage-job run`, or the v5 `loom stage run` handoff-only worker contract.
- No generated dry-run planning API that writes scripts/manifests for a real run; Phase 3 may model paths and validate manifests, but Phase 4 owns artifact generation.
- No generic wall-time resource, container command composition, controller mode, job arrays, MPI orchestration, remote stores, plugin discovery, or real cluster acceptance tests.

## Assumptions

- Phase 3 can introduce a SLURM-specific executor subpackage because the v6 plan explicitly assigns SLURM option, resource mapping, and manifest contracts there.
- `SlurmOptions.time` remains SLURM-specific and should not become a generic runtime resource in this phase.
- Memory mapping should prefer deterministic SBATCH strings from existing resource units and fail loudly for unsupported or ambiguous units rather than guessing site policy.
- GPU mapping can produce a conservative default such as a `gres` summary when no structured SLURM override conflicts; exact site-specific GPU syntax remains an `extra_sbatch` or later typed-field concern.
- Manifest records should preserve logical identity and dry-run facts, not raw adapter payloads or secret-bearing resolved values.

## Scope Contract

`loom.pipeline.executors.slurm` is a pure planning-model package in this phase. Public exports should be cheap to import, typed, deterministic to serialize, and free of scheduler dependencies. Model constructors and `from_dict` helpers must reject unknown fields rather than silently preserving opaque adapter payloads.

`SlurmOptions` is the single source of structured option truth. Modeled directives and generated directives take precedence over `extra_sbatch`. `extra_sbatch` must not override generated job names, output paths, error paths, dependency directives, launcher commands, modeled CPU/memory/GPU/time directives, or any other directive that the mapper owns. Validation should report conflicts with enough field-path detail for CLI/preflight layers to present useful errors later.

The resource mapper translates generic Loom resources to planned SBATCH directive records. It must not mutate `ResourceRequest`, add generic resource kinds, consult cluster state, or rely on site discovery. Unsupported resource kinds or units are structured mapper errors, not warnings.

Manifest models represent planned dry-run submissions only. Scheduler job IDs, raw job IDs, submitted status, scheduler state, and command-runner results must be absent or null in v6 Phase 3 serialization. Dependencies are expressed only through logical job keys and dependency type `afterok`.

Generated artifact path helpers remain store-owned. SLURM code supplies safe relative paths under `slurm/submissions/<planning_id>/...` to `LocalRunStorePaths.local_generated_artifact_path`; it must not inspect local run directory layout, import `LocalRunStore`, or use `Path(run_dir) / ...` path walking.

## Design Impact

- Maintainability: Creates a focused SLURM model layer before script rendering, keeping validation and serialization separate from later file generation.
- Extensibility: Gives v7 live submission a stable planned-submission schema that can be extended with scheduler job IDs and command results without replacing logical job keys.
- Domain neutrality: Keeps SLURM-specific vocabulary under the executor adapter package while preserving generic resource and store contracts.
- Source-tree boundaries: Executors own adapter vocabulary, stores own path safety, resources own scheduler-neutral resource entries, execution owns continuation commands, and CLI remains untouched.

## Future Compatibility

- Phase 4 can render deterministic scripts from typed planned jobs and manifest records without inventing option or dependency semantics.
- Phase 5 can adapt CLI/profile input into `SlurmOptions` and present structured mapper errors without duplicating validation rules.
- V7 can add live submission records by filling scheduler job IDs and submission results as extensions to planned records while preserving v6 logical job keys.
- Future site-specific options can graduate from `extra_sbatch` to typed fields when repeated use justifies stable semantics.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Use raw strings or raw `#SBATCH` line lists as the primary model | The v6 plan requires structured, reviewable validation and conflict detection before script rendering. |
| Store fake scheduler job IDs in dry-run manifests | V6 logical job keys are the identity until v7 live submission maps them to real scheduler IDs. |
| Let `extra_sbatch` override modeled/generated directives | Silent override would make resource mapping and path safety unreproducible and hard to review. |
| Build absolute run-directory paths in SLURM code | The store owns run layout and safe path resolution; adapter-local path walking would bypass Phase 1's helper contract. |
| Model every possible SLURM directive in v6 | A bounded typed set plus validated `extra_sbatch` keeps Phase 3 reviewable while preserving a site escape hatch. |
| Add script-rendering conveniences now | Phase 4 owns shell quoting, directive ordering as text, script files, and generated wrapper bodies. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Some site-specific SBATCH options remain in `extra_sbatch` | V6 needs a reviewable escape hatch without modeling all SLURM directives up front. | Repeated real-world use of the same option or v7 live submission needing typed semantics. |
| Resource-to-SBATCH mapping is conservative and local-only | Phase 3 cannot inspect a cluster or site policy. | Phase 5 preflight or v7 live submission needs cluster-aware diagnostics. |
| Manifest schema carries planned paths and logical IDs but no script contents | Script generation belongs to Phase 4, and manifests should avoid duplicating large generated artifacts. | Phase 4 contract tests show script digests or content summaries are needed for reviewability. |

## Reviewability

- Expected PR size and shape: small to moderate pure-model PR with a new SLURM executor package and focused tests; no scheduler side effects, CLI, scripts, or broad runtime changes.
- Files and areas to inspect: `src/loom/pipeline/executors/slurm/`, `src/loom/pipeline/executors/__init__.py` only if public lazy exports are needed, `tests/package/`, `tests/unit/loom/pipeline/executors/slurm/`, `tests/contracts/`, and a small integration test for store path interaction.
- Scope-control checks: no `sbatch`, `squeue`, `sacct`, `scancel`, generated shell files, CLI parser changes, executor selection behavior, live command runner, scheduler status, job ID parsing, fake IDs, local-store path walking, `loom.cli` imports from lower layers, continuation command changes, or v7 submission behavior.

## Implementation Steps

1. Add the import-light `loom.pipeline.executors.slurm` package, error types, schema constants, mode values, and serialization helpers using existing dataclass/plain-data patterns.
2. Implement `SlurmOptions`, launcher argv validation, and `extra_sbatch` validation with explicit modeled/generated directive conflict checks.
3. Implement resource mapper records and mapping from `ResourceRequest`/`ResourceEntry` to planned SBATCH directive summaries with path-aware structured errors.
4. Implement logical job keys, planned dependency records, planned job records, and planned submission manifest round-trip models with scheduler fields absent or null.
5. Add store-path helper functions for relative `slurm/submissions/<planning_id>/...` locations that call `LocalRunStorePaths.local_generated_artifact_path`.
6. Add focused package, unit, contract, and integration coverage, then run the targeted commands below.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`, `tests/package/test_public_api.py`, `tests/package/test_pipeline_execution_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: SLURM model package imports without optional scheduler dependencies; public exports are import-light; lower layers do not import `loom.cli`; introducing `loom.pipeline.executors.slurm` does not force subprocess or scheduler imports through `loom.pipeline.executors`.

### Unit Suite

- Status: required
- Expected paths: new `tests/unit/loom/pipeline/executors/slurm/test_options.py`, new `tests/unit/loom/pipeline/executors/slurm/test_resources.py`, new `tests/unit/loom/pipeline/executors/slurm/test_manifest.py`, and new `tests/unit/loom/pipeline/executors/slurm/test_paths.py` if path helpers are not covered elsewhere
- Required assertions or deferral reason: `SlurmMode` wire values; `SlurmOptions` accepts modeled fields and rejects unknown fields; prelude is structured trusted text; launcher argv defaults to `["loom"]` and rejects empty/non-string entries; `extra_sbatch` accepts `true` flags and string values, rejects false/null/non-scalar values, whitespace/control characters, duplicate flags, and modeled/generated directive conflicts; CPU/memory/GPU mapping is deterministic; unsupported resources or ambiguous overrides raise path-aware errors; logical job keys validate `pipeline` and `stage:<stage_name>` forms; planned dependency records use `afterok`; manifest round trips omit or null scheduler job IDs.

### Contract Suite

- Status: required
- Expected paths: new or updated `tests/contracts/test_slurm_manifest_contract.py` and relevant public API contract tests if exports are added
- Required assertions or deferral reason: manifest serialization is schema-versioned, deterministic, plain-data compatible, and stable for planned jobs, dependencies, generated command argv, sanitized options, resource summaries, run URI, planning ID, dry-run flag, and planned paths; v6 serialization has no submitted status, raw scheduler job IDs, raw adapter payloads, or scheduler state.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/pipeline/test_slurm_model_store_paths.py` or equivalent focused integration coverage
- Required assertions or deferral reason: SLURM path helper builds relative paths under `slurm/submissions/<planning_id>/...` through a real `LocalRunStore`; returned paths stay under the run directory; unsafe planning IDs or relative path pieces fail through store-owned validation; no local-store internals or adapter-local run-directory walking are used.

### E2E Suite

- Status: deferred
- Expected paths: none
- Required assertions or deferral reason: Phase 3 has no public CLI behavior, generated scripts, or dry-run artifact-writing workflow. E2E coverage begins in Phase 5 and is hardened in Phase 6.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: Phase 3 is deterministic and cluster-free; no real SLURM, scheduler, remote-store, container, or cluster acceptance suite applies.

## Risks

- `extra_sbatch` can become an unreviewable escape hatch if validation is too permissive; mitigate with deny-by-default conflict checks and stable unit tests.
- Resource mapping can encode site policy accidentally; keep defaults conservative and fail on ambiguous units or unsupported resource kinds.
- Manifest models can leak raw adapter payloads or future scheduler state; keep fields explicit, schema-versioned, and dry-run-only.
- Path helper convenience functions can drift into local-store path walking; require tests that use only the `LocalRunStorePaths` protocol method.
- Public exports can make the executor package import-heavy; use lazy exports or direct subpackage imports consistent with existing executor patterns.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import.py tests/package/test_public_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/slurm/test_options.py tests/unit/loom/pipeline/executors/slurm/test_resources.py tests/unit/loom/pipeline/executors/slurm/test_manifest.py tests/unit/loom/pipeline/executors/slurm/test_paths.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_slurm_manifest_contract.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_slurm_model_store_paths.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: package/errors/schema constants first, options and launcher validation second, resource mapper third, planned job/dependency/manifest models fourth, store path helpers fifth, tests throughout.
- Tests to run with each slice: run the matching unit test after each model/mapper slice; run contract tests after manifest serialization lands; run integration path coverage after store helper integration lands.
- Decisions the executor must not revisit: no script generation; no CLI wiring; no scheduler calls; no live command runner; no scheduler job IDs except absent/null manifest fields; no fake submitted status; no `loom stage run` or continuation command changes; no path walking outside the store helper; no generic wall-time resource.
- Conditions that require stopping for the manager: resource mapping requires a new generic resource field; `extra_sbatch` cannot be made conflict-safe without changing the plan; manifest schema needs to persist raw scheduler or adapter payloads; path helper use requires importing local-store internals; required package/unit/contract/integration tests cannot run for a non-environmental reason.
- Expanded-path refinement notes: pending. The refine pass should confirm exact model names, wire values, schema constants, serialization shapes, and path-helper API names before implementation begins.

## Refinement And Review Budget Status

- Phase implementation refinement: unused; expanded-path implementation refinement remains available after implementation if targeted validation fails, suite coverage is missing, or design-risk review finds a concrete blocker
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this draft pass and committed with `plan: add phase execution plan`
- Final phase execution plan: pending expanded-path refine pass
- Implementation summary: pending
- Implementation validation: pending
- PR preparation: pending
- Remaining blockers: none known
