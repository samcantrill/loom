# Phase 10 Execution Plan: Hardening And Documentation

## Metadata

- Status: refined phase execution plan
- Branch: `codex/harden-v0-docs`
- Worktree: `/home/samcantrill/work/loom-worktrees/harden-v0-docs`
- Phase execution plan path: `docs/phases/harden-v0-docs.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`
- Source phase: `Phase 10 - Hardening And Documentation`
- Stack predecessor: `codex/add-local-execution`
- Base branch: `codex/add-local-execution` at `da3cb5f4547ccf01a56bc6dc33f742228d0ffd72`
- Target branch: `codex/add-local-execution`
- Merge eligibility: stacked PR; reviewable against `codex/add-local-execution`; not merge-eligible until Phase 7 PR #11, Phase 8 PR #12, and Phase 9 PR #13 land or the Phase 10 branch is replayed/rebased onto the latest valid base and retargeted to `develop`.
- Successor dependency notes: no successor phase is recorded. Keep `codex/harden-v0-docs` until any later branch has been retargeted or rebased away from it.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no blocking findings remain in the canonical v0 implementation plan.
- Plan quality gate loop budget: initial review used, automated plan refinement pass used, confirmation review used. Do not rerun or consume the plan-quality gate for this phase.
- Draft pass: completed by `loom_phase_planner` on 2026-05-04 local time in draft commit `91904e74207f89a8507573774470f1c23a6b7df9`.
- Refine pass: completed by `loom_phase_planner` on 2026-05-04 local time in this plan-only refinement commit.
- Phase implementation refinement budget: used by `loom_phase_refiner` on 2026-05-04 local time.
- PR review budget: unused.
- PR body draft/refine budget: draft completed on 2026-05-04 local time in
  `docs/phases/harden-v0-docs-pr-body.md`; refine completed on 2026-05-04
  local time by `loom_pr_preparer`.
- Setup limitations: no remote operations or validation commands were run during the draft or refine planning passes. The worktree was created from the local recorded predecessor branch because the manager supplied the exact Phase 9 base head.
- Blockers: none.

## Objective

Harden the completed v0 local runtime kernel after Phase 9 made the Python local execution path runnable. This phase should improve representative path-aware errors, recovery behavior for interrupted or partial run state, extension contract guardrails, documentation, and permanent import-boundary tests without widening v0 into new runtime features.

The resulting PR should make the v0 surface easier for downstream packages to adopt: users should see clear paths in failures, understand trusted config and stage contracts, and have executable or explicitly bounded examples for artifacts, output specs, selectors, run directories, checksums, fingerprints, and same-run-directory resume.

## Full-Plan Context

Phases 1 through 6 are merged and provide the package skeleton, public primitives, serialization, local I/O/codecs, trusted config composition, recipes and instantiation, static pipeline specs, graph validation, status records, and pipeline imports. Phase 7 PR #11 adds local stores and the inspectable run layout. Phase 8 PR #12 adds planning, selectors, stage fingerprints, conservative same-run-directory resume, and downstream invalidation. Phase 9 PR #13 adds local in-process execution, runner lifecycle, output validation, failure persistence, and e2e local Python API coverage.

Phase 10 builds on that full local stack. It should harden existing behavior and document existing contracts. It must not add functional CLI commands, new execution backends, remote stores, cross-run cache reuse, dashboards, domain codecs/stages/recipes, config sandboxing, plugin discovery, retries, lock managers, or other deferred features unless an existing Phase 10 acceptance criterion is impossible without the smallest supporting fix.

## Stack Context

- Root or stacked phase: stacked phase.
- Current predecessor branch or PR: `codex/add-local-execution`, GitHub PR #13, recorded as open against `codex/add-planning-resume-selectors`.
- Why this base branch is correct: Phase 7 PR #11, Phase 8 PR #12, and Phase 9 PR #13 remain open, and Phase 10 must harden the local execution behavior introduced in Phase 9. The manager assignment explicitly requires branching from `codex/add-local-execution` at `da3cb5f4547ccf01a56bc6dc33f742228d0ffd72` and targeting `codex/add-local-execution`.
- Retarget/rebase plan after predecessor merge: after Phase 7 lands, Phase 8 must be replayed or rebased onto updated `develop`; after Phase 8 lands, Phase 9 must be replayed or rebased onto the latest valid base; after Phase 9 lands, replay or rebase Phase 10 onto updated `develop`, retarget its PR to `develop`, rerun validation, and record stack maintenance in this artifact and the PR body.
- Branch cleanup constraints: do not delete Phase 9 while Phase 10 depends on it. Do not delete Phase 10 until every successor branch has been retargeted or rebased away from it.

## Source Phase Summary

- Goal: tighten errors, recovery, contracts, and docs once the local execution path works.
- Required scope:
  - Improve path-aware errors across config, recipes, instantiation, pipeline parsing, graph bindings, artifact store, run store, resume planner, and local runner.
  - Harden interrupted-run behavior.
  - Add extension contract tests for dummy stages, codecs, recipes, and stores.
  - Update README and docs for trusted configs, `_target_`, `_recipe_`, stage contract, artifact saving/registering, output specs with optional codecs, run directory layout, checksums vs fingerprints, selectors, and same-run-directory resume.
  - Make import-boundary tests permanent guardrails.
- Required checkpoints:
  - Representative errors include config paths such as `pipeline.stages[2]._target_`, stage names, artifact keys such as `train.best_checkpoint`, target paths, and filesystem paths.
  - Stale `RUNNING`, missing `outputs.json`, corrupt JSON, partial artifacts, checksum mismatch, and failed prior stages are not reusable.
  - Extension contract tests prove downstream-style stages, codecs, recipes, and stores satisfy protocols structurally without inheritance.
  - README/docs snippets document trusted configs, `_target_`, `_recipe_`, stage contract, artifact saving/registering, output specs, run directory layout, checksums vs fingerprints, selectors, and same-run-directory resume.
- Acceptance criteria:
  - Representative errors include useful config paths, stage names, artifact keys, target paths, or file paths.
  - Stale `RUNNING`, missing or corrupt files, partial artifacts, invalid checksums, and failed prior stages are not skipped.
  - Downstream-style extension classes satisfy protocols structurally without inheritance.
  - Docs examples execute where feasible.
  - Full import-boundary tests still pass after all subsystems exist.
- Source references: `docs/implementation-plans/implementation-plan-v0.md` Phase 10; `docs/structure.md` sections "Review Checklist", "Test Layout", "Runtime Dependency Policy", and "What Stays Out of loom"; `docs/loom.md` sections 9 through 16; `docs/features/config.md` sections 14, 16, and 19; `docs/features/errors.md`; `docs/features/reliability.md`; `docs/features/run-store.md`; `docs/features/artifacts.md`; `docs/features/io.md`; `docs/features/fingerprints.md`; `docs/features/resume.md`; `docs/features/provenance.md`; `docs/features/testing.md`; and `docs/features/cli.md` only for import-safe v0 CLI boundaries.

## Current Source And Harness Findings

- The Phase 9 stack branch contains the local runtime modules under `src/loom/pipeline/execution/` and `src/loom/pipeline/executors/`, planning under `src/loom/pipeline/planning/`, stores under `src/loom/pipeline/stores/`, strict specs and graph helpers under `src/loom/pipeline/`, and config composition/recipe/instantiation modules under `src/loom/config/`.
- The shared root error hierarchy in `src/loom/errors.py` is intentionally small and has no structured `ErrorContext` implementation yet. Subsystem error modules contain concrete errors near the raising code.
- Existing tests already cover package imports, public API stability, config behavior, recipes, pipeline specs/graph, stores, planning/resume, local execution, contracts, integration, and one e2e local pipeline run.
- Contract tests currently exist for executor, store, codec, data source, stage, and recipe protocols. Phase 10 should extend or tighten these contracts with downstream-style dummy implementations rather than requiring inheritance.
- Current resume unit coverage proves valid reuse, no-prior-state rerun, missing-artifact rerun, and corrupt status failure. Phase 10 must add the missing representative cases for stale `RUNNING`, missing `outputs.json`, corrupt `outputs.json`, partial artifacts, checksum mismatch, and failed prior stages.
- Current local execution integration coverage proves same-run reuse, config-change rerun, stage exception persistence, invalid-output failure state, target contract failure, and skip-status store failure. Phase 10 should extend this coverage only where it proves hardening or docs examples, not retest every predecessor behavior.
- `README.md` is minimal and points to design docs. Phase 10 should turn it into a useful v0 quickstart and contract overview without promising deferred CLI behavior.
- `docs/loom.md` already names run directory, fingerprints/resume, public API, CLI deferral, and error model. It should be updated to match the implemented v0 Python API and final run layout.
- `tests/README.md` documents suite names and Make targets. The suite-level obligations below must remain visible to PR preparation through `make test-summary`.

## In-Scope Work

- Improve representative error messages and wrapping at the current subsystem boundaries:
  - config load/merge/override/interpolation/validation/redaction;
  - recipe catalog and expansion;
  - `_target_` import and recursive instantiation;
  - pipeline spec parsing and graph input binding;
  - local artifact store and run store state/documents;
  - planner resume checks and plan persistence;
  - local executor, runner target construction, output validation, lifecycle, and failure persistence.
- Add or refine tests that assert useful path context in high-traffic failures, including config paths, stage names, target paths, logical artifact keys, persisted document names, and file paths.
- Harden same-run-directory recovery and resume around stale `RUNNING` state, missing `outputs.json`, corrupt JSON, partial artifact files, checksum mismatches, failed prior stages, and unverifiable prior state.
- Strengthen extension contract tests with minimal downstream-style dummy stages, codecs, recipes, artifact stores, and run stores that satisfy protocols structurally without subclassing `loom` concrete implementations.
- Update `README.md`, `docs/loom.md`, and targeted feature docs where they describe implemented v0 behavior or examples that users are likely to copy.
- Add or update docs/example tests where feasible. If an example cannot execute without deferred behavior or project-specific code, keep it explicitly marked as illustrative and record the reason in completion notes.
- Keep import-boundary tests as permanent guardrails for root `loom`, config, serialization, I/O, pipeline, planning, stores, execution, executors, and CLI stub boundaries.

## Out-of-Scope Work

- No functional CLI commands, parser entry points, terminal output, or exit-code mapping beyond preserving import-safe unsupported CLI stubs.
- No new execution backends, subprocess execution, SLURM, distributed execution, containers, or executor registries.
- No remote artifact/run stores, global run catalog, cross-run cache reuse, dashboards, database orchestration, or repair commands.
- No config sandbox, import allow list, plugin discovery, entry-point discovery, Hydra defaults, include graph, expression language, or sweep behavior.
- No domain stages, domain codecs, domain recipes, schema inference, model/report/dataset helpers, or research-specific examples in runtime code.
- No broad rewrite of the error hierarchy unless the refine pass proves a narrow shared helper is necessary and reviewable.
- No unrelated formatting churn across design documents that are not needed to document the v0 user contract.

## Assumptions

- The local Phase 9 branch at `da3cb5f4547ccf01a56bc6dc33f742228d0ffd72` is the correct base because the manager supplied that exact stack state.
- Error hardening may be message/context improvements and targeted wrapping; Phase 10 does not need to introduce a full structured error-code system for v0.
- Docs examples should be executable when they use only generic in-repo test helpers or public Python APIs. Examples involving project-provided stage classes may remain illustrative if they are clearly labeled as project code.
- Conservative resume is more important than aggressive reuse. Any ambiguous, partial, corrupt, failed, or unverifiable state should produce `RUN`, `STALE`, `BLOCKED`, or a clear error rather than `REUSE`.
- No lock manager is required unless targeted interrupted-run tests expose a concrete race that cannot be handled with atomic writes and conservative planning.
- Import-boundary tests should not force `loom.__init__` to export runtime-heavy names.
- Corrupt persisted JSON should fail planning or run opening with a clear store/resume error by default. Missing or unverifiable prior files can rerun when existing planner/store contracts support rerun without silent repair.
- "Partial artifact" means a prior `outputs.json` or artifact index references an artifact whose file is missing, whose URI is unsupported for the local store, whose path is not a regular file when checksum validation is required, or whose checksum no longer matches stored bytes.
- Documentation may mirror tested examples manually instead of adding a generic Markdown code-block extraction harness in this phase. A docs extraction harness is not required for v0.

## Implementation Boundaries

- Allowed source areas: `src/loom/errors.py` only if a shared minimal helper is justified; targeted subsystem modules under `src/loom/config/`, `src/loom/io/`, `src/loom/pipeline/`, `src/loom/pipeline/stores/`, `src/loom/pipeline/planning/`, `src/loom/pipeline/execution/`, and `src/loom/pipeline/executors/` where error or recovery behavior is already owned.
- Allowed docs areas: `README.md`, `docs/loom.md`, targeted sections in `docs/features/config.md`, `docs/features/errors.md`, `docs/features/run-store.md`, `docs/features/artifacts.md`, `docs/features/io.md`, `docs/features/fingerprints.md`, `docs/features/resume.md`, `docs/features/provenance.md`, `docs/features/testing.md`, `docs/features/cli.md`, `tests/README.md`, and Phase 10 artifacts under `docs/phases/`.
- Allowed tests: `tests/package/`, `tests/unit/loom/`, `tests/contracts/`, `tests/integration/`, `tests/e2e/`, and generic support helpers under `tests/support/`.
- Avoid changing public APIs unless required to expose already-implemented v0 behavior or preserve stable import paths. If a public contract change is needed, document it in this plan during refinement before implementation.
- Keep all runtime and test examples domain-neutral; project-specific classes may appear only as illustrative docs placeholders, not in package code.

## Decision-Complete Contract

The implementation handoff is decision-complete. Executor work should implement the exact targets below and stop if an acceptance criterion appears to require new public API, a broad error framework, a lock manager, a functional CLI, remote stores, cross-run cache reuse, new execution backends, or domain-specific runtime behavior.

### Error-Hardening Targets

The executor must add or tighten tests before changing behavior. Each row is representative; do not attempt to standardize every possible error message.

| Area | Source files allowed | Test files to add or extend | Required representative assertions |
| --- | --- | --- | --- |
| Config load/merge/overrides/interpolation/redaction | `src/loom/config/load.py`, `merge.py`, `overrides.py`, `interpolation.py`, `validation.py`, `redaction.py`, `compose.py`, `errors.py` | `tests/unit/loom/config/test_config_errors.py`, `tests/unit/loom/config/test_compose.py`, `tests/unit/loom/config/test_overrides.py`, `tests/unit/loom/config/test_interpolation.py`, `tests/unit/loom/config/test_redaction.py`, `tests/integration/config/test_compose_config.py` | Invalid authored values identify a config path such as `$.pipeline.stages[2].config.limit`; override failures name the dot path supplied by the user; interpolation failures name the unresolved token and config path; redaction tests prove `password`, `secret`, `token`, and `api_key` values are not printed in error text. |
| Recipes | `src/loom/config/recipes/catalog.py`, `expansion.py`, `errors.py`, `manifest.py` | `tests/unit/loom/config/recipes/test_catalog.py`, `tests/unit/loom/config/recipes/test_expansion.py`, `tests/contracts/test_recipe_contract.py`, `tests/integration/config/test_compose_recipes.py` | Unknown recipe, recipe exception, nested recipe rejection, and non-mapping recipe output include the recipe name and path such as `$.pipeline.stages[0]` without leaking raw secret arguments. |
| Target import and recursive instantiation | `src/loom/config/instantiate/targets.py`, `recursive.py`, `injection.py`, `errors.py` | `tests/unit/loom/config/instantiate/test_targets.py`, `tests/unit/loom/config/instantiate/test_recursive.py`, `tests/unit/loom/config/instantiate/test_injection.py`, `tests/integration/pipeline/test_local_execution_failures.py` | Import failures include the target path and config path, especially `pipeline.stages[2]._target_`; constructor failures include the target path and nested parameter path; stage target failures include the stage name and do not imply constructor kwargs are supported in v0. |
| Pipeline specs and graph bindings | `src/loom/pipeline/specs.py`, `src/loom/pipeline/graph/bindings.py`, `src/loom/pipeline/errors.py` | `tests/unit/loom/pipeline/test_specs.py`, `tests/unit/loom/pipeline/graph/test_bindings.py`, `tests/integration/pipeline/test_pipeline_config.py` | Missing or invalid `_target_`, duplicate stage names, malformed inputs, unknown stages, and unknown outputs include paths such as `$.pipeline.stages[2]._target_`, consumer stage names, input names, and logical artifact keys such as `train.best_checkpoint`. |
| Artifact store | `src/loom/pipeline/stores/local_artifacts.py`, `indexes.py`, `_paths.py`, `errors.py` | `tests/unit/loom/pipeline/stores/test_local_artifacts.py`, `tests/unit/loom/pipeline/stores/test_indexes.py`, `tests/unit/loom/pipeline/stores/test_store_errors.py` | Missing files, unsupported URI schemes, outside-stage registration, codec-less load, directory checksum validation, and checksum mismatch include a filesystem path or URI and, when available through `ArtifactRef.artifact_id`, the logical artifact key. |
| Run store documents | `src/loom/pipeline/stores/local_runs.py`, `run_store.py`, `errors.py` | `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/stores/test_store_errors.py`, `tests/integration/pipeline/test_local_stores.py` | Missing `run.json`, malformed `status.json`, corrupt `outputs.json`, malformed `fingerprint.json`, schema mismatch, stage/run id mismatch, and invalid artifact refs include the exact document path where the current implementation can know it, plus run id and stage name. |
| Resume planner and plan persistence | `src/loom/pipeline/planning/resume.py`, `planner.py`, `models.py`, `errors.py` | `tests/unit/loom/pipeline/planning/test_resume.py`, `tests/unit/loom/pipeline/planning/test_planner.py`, `tests/unit/loom/pipeline/planning/test_planning_errors.py`, `tests/integration/pipeline/test_planning_resume.py`, `tests/integration/pipeline/test_plan_persistence.py` | Resume reasons name stage, output, artifact key, and reason code; corrupt persisted state raises `ResumeStateError` with document context; plan persistence failures name the run id and `plan.json` when available. |
| Local runner and executor | `src/loom/pipeline/execution/runner.py`, `outputs.py`, `lifecycle.py`, `models.py`, `errors.py`, `src/loom/pipeline/executors/local.py` | `tests/unit/loom/pipeline/execution/test_outputs.py`, `tests/unit/loom/pipeline/executors/test_local_executor.py`, `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_local_execution_failures.py`, `tests/e2e/test_local_pipeline_run.py` | Target construction, input binding, invalid returned outputs, artifact validation, stage exceptions, and store commit failures include stage name, target path, config path or output path, and persisted failure/log paths where available. |

### Resume And Recovery Targets

Use existing `StageStatus`, `PlanAction`, `PlanReasonCode`, `LocalRunStore`, and `LocalArtifactStore` contracts. Do not add repair commands, cleanup commands, retries, or locks.

| Case | Required behavior | Required tests |
| --- | --- | --- |
| Prior stage status is `RUNNING` | Never `REUSE`; direct check returns `RUN` when eligible or `BLOCKED` when not eligible, with `PlanReasonCode.PRIOR_STATUS_RUNNING` and stage name. | Add to `tests/unit/loom/pipeline/planning/test_resume.py` and an integration rerun case in `tests/integration/pipeline/test_local_execution_resume.py`. |
| Prior stage status is `FAILED`, `CANCELLED`, `STALE`, or `SKIPPED` | Never `REUSE`; use `PlanReasonCode.PRIOR_STATUS_NOT_SUCCEEDED` unless a more specific existing selector/blocking reason applies. | Add table-style unit coverage in `tests/unit/loom/pipeline/planning/test_resume.py`; add one failed-prior-stage integration case. |
| `outputs.json` missing after prior `SUCCEEDED` status | Never `REUSE`; direct check returns stale/run-or-blocked with `PlanReasonCode.MISSING_OUTPUTS`. | Extend `tests/unit/loom/pipeline/planning/test_resume.py`; add same-run integration check if not already covered by unit. |
| `outputs.json`, `fingerprint.json`, `inputs.json`, or `artifacts.json` contains malformed JSON or invalid serialized refs | Do not silently repair or ignore; raise `ResumeStateError` or a store error with the document path, run id, and stage name. | Extend `tests/unit/loom/pipeline/planning/test_resume.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, and `tests/integration/pipeline/test_planning_resume.py`. |
| Prior output artifact file is missing | Never `REUSE`; use `PlanReasonCode.ARTIFACT_MISSING` and include logical key `stage.output` plus file path/URI. | Existing missing-artifact unit test should be tightened for key/path assertions; add integration coverage if runner behavior is not already visible. |
| Prior output artifact is partial or not a regular file when checksum is present | Never `REUSE`; use `PlanReasonCode.ARTIFACT_VALIDATION_FAILED` or a more specific existing store error, with path and `stage.output`. | Add unit coverage in `tests/unit/loom/pipeline/planning/test_resume.py` and store coverage in `tests/unit/loom/pipeline/stores/test_local_artifacts.py`. |
| Prior output checksum mismatches stored bytes | Never `REUSE`; use `PlanReasonCode.ARTIFACT_CHECKSUM_MISMATCH` and include expected/actual digests plus `stage.output`. | Add unit coverage in `tests/unit/loom/pipeline/planning/test_resume.py` and an integration runner rerun or blocked case in `tests/integration/pipeline/test_local_execution_resume.py`. |
| Artifact index conflicts with stage `outputs.json` | Fail planning clearly with `ResumeStateError`; do not pick one source of truth silently. | Add to `tests/unit/loom/pipeline/planning/test_resume.py` and keep `tests/integration/pipeline/test_plan_persistence.py` passing. |

### Extension Contract Targets

Protocols remain structural. Tests must prove downstream-style classes work without inheriting concrete `loom` implementations.

- `tests/contracts/test_stage_contract.py`: add a stage that uses `StageContext.save_artifact` and a stage that manually writes/registers an artifact through `StageContext.register_artifact`; both should satisfy `Stage` and be accepted by a `PipelineRunner` synthetic config in an integration or e2e example.
- `tests/contracts/test_codec_contract.py`: keep the current downstream codec and add one metadata-aware dummy codec that round-trips with `CodecRegistry` without subclassing `Codec`.
- `tests/contracts/test_recipe_contract.py`: keep class/function/protocol recipe coverage and add a failing downstream recipe assertion that expansion preserves recipe name/path context.
- `tests/contracts/test_store_contract.py`: keep structural `DummyArtifactStore`/`DummyRunStore` and add assertions that public planner/runner APIs accept protocol instances or fail with a clear protocol message when required methods are absent. Do not require dummy stores to inherit `LocalArtifactStore` or `LocalRunStore`.
- Do not add new protocols or registry systems unless a current public API cannot express the existing v0 contract.

### Documentation And Example Targets

Update documentation only where it describes implemented v0 behavior or copyable examples. Keep postponed behavior explicitly deferred.

| File | Required update scope | Executable vs illustrative |
| --- | --- | --- |
| `README.md` | Replace the minimal overview with a v0 Python API quickstart: trusted config composition, `_recipe_`, stage `_target_`, local `PipelineRunner`, same-run resume, artifact save/register, and validation commands. State that functional CLI, remote stores, and cross-run reuse are post-v0. | Import snippets and generic helper examples should be mirrored by tests. YAML using `project.stages.*` remains illustrative and must be labeled as project code. |
| `docs/loom.md` sections 7-14 | Align config, execution model, run directory layout, fingerprints/resume, provenance, public API, CLI deferral, and error model with the implemented local Python API and current run layout. | Generic Python snippets should execute through tests if they use `tests.support` helpers or public APIs. Project package snippets remain illustrative. |
| `docs/features/config.md` sections 14, 16, and 19 | Tighten trusted-config, redaction, `_target_`, `_recipe_`, and error-message language to match v0. Remove or mark post-v0 examples that imply include graphs, schema inference, CLI commands, or stage constructor kwargs. | Config composition examples that use in-repo helpers can execute in integration tests; project target snippets are illustrative. |
| `docs/features/errors.md` sections 6, 12, 14, 18, and 19 | Document the Phase 10 message-oriented error policy, representative context expectations, cause preservation, and no-secret rule. Keep structured `ErrorContext`, error codes, and JSON CLI output as future work. | Error examples are illustrative unless directly mirrored by unit assertions. |
| `docs/features/run-store.md` sections 14, 17, and 18 | Record actual run-store recovery behavior for opening existing runs, old `RUNNING` state, corrupt JSON, and no silent repair. | Layout snippets should match e2e assertions. Recovery examples should be mirrored by store/planning tests. |
| `docs/features/artifacts.md` sections 7, 8, 11, 12, 18, and 21 | Clarify managed save vs manual register, optional `codec_key`, artifact type validation, checksum validation, directory checksum deferral, and output spec validation. | Save/register examples using `StageContext` should execute through tests. Domain artifact examples remain illustrative. |
| `docs/features/io.md` codec/source sections and `docs/features/fingerprints.md` sections 6, 12, 18, and 19 | Ensure checksum vs fingerprint wording matches implemented `ArtifactRef`, local stores, and same-run resume. Do not introduce remote checksum behavior. | Hash helper snippets can remain illustrative unless already covered by unit tests. |
| `docs/features/resume.md` sections 8, 9, 11, 13, and 19 | Align selector names with Python fields `force_stages`, `from_stage`, `only_stages`, `skip_stages`; document same-run-only reuse, corrupt-state failure, stale `RUNNING`, and missing/partial artifacts. | Resume examples should be mirrored by planning/integration tests where feasible. |
| `docs/features/provenance.md` persistence and pipeline integration sections | Align persisted document names with current run layout and explain provenance as evidence, not a resume policy replacement. | Layout snippets should match e2e file checks. |
| `docs/features/testing.md`, `tests/README.md`, and `docs/features/cli.md` v0 scope sections | Make suite obligations, import-boundary tests, and CLI deferral explicit. Do not add parser/command expectations for v0. | No new executable docs requirement unless the docs include public API snippets that are easy to mirror. |

### Import-Boundary Guardrails

Extend `tests/package/test_import_boundaries.py` and package API tests so they permanently cover the final v0 stack:

- `import loom` must not import `loom.config`, `loom.pipeline`, `loom.cli`, `omegaconf`, `yaml`, `pydantic`, project packages, pipeline runners, stores, or executors.
- `import loom.serialization` must not import `loom.io`, `loom.config`, `loom.pipeline`, or CLI modules.
- `import loom.io` must not import `loom.config`, `loom.pipeline`, runners, stores, executors, or CLI modules.
- `import loom.config` may import its hard config dependencies after Phase 4, but must not import `loom.pipeline`, execution modules, stores, executors, CLI modules, or project modules.
- `import loom.pipeline` may expose static specs, stage/context/status/planning/store/execution public names that are intentionally exported, but must not import `loom.cli` or project modules. If current public exports require local runner/store imports, record the boundary as intentional in tests rather than weakening root import.
- `import loom.cli` must remain import-safe and unsupported; it must not cause config composition, pipeline execution, project import, or remote/backend discovery side effects.

## Design Impact

- Maintainability: concentrates hardening around existing subsystem ownership and test files, reducing ambiguity before v0 users depend on the local runtime. Avoiding a broad error-framework rewrite keeps the PR reviewable.
- Extensibility: stronger contracts and docs make downstream stages, codecs, recipes, and stores easier to implement without subclass coupling. Conservative recovery behavior leaves room for future lock managers and repair commands without weakening v0 correctness.
- Domain neutrality: examples, tests, and runtime code must remain generic. Documentation may say "project stage" but should not bake in a domain dataset, model, metric, report, or file format beyond generic JSON/text/bytes examples.
- Source-tree boundaries: config owns trusted composition and `_target_` errors; I/O owns codecs and URI/file errors; stores own persisted state and artifact integrity; planning owns resume decisions; execution owns lifecycle/output validation; docs/tests mirror those boundaries.

## Future Compatibility

- A future functional CLI can format the improved errors without moving subsystem-specific error classes into a large root module.
- Future remote stores can implement the same artifact/run-store contracts and report unsupported validation clearly without changing same-run resume policy.
- Future subprocess or SLURM executors can reuse failure metadata, logs paths, extension contracts, and docs boundaries without changing local-run semantics.
- Future cross-run cache reuse can build on the checksum/fingerprint distinction and explicit same-run limitation documented here.
- Future config sandboxing or allow-list mode can be added without revising v0 docs that state authored configs are trusted project code.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add a full shared `ErrorContext`, error-code registry, and JSON error framework in Phase 10 | Too broad for hardening; functional CLI and machine output are post-v0, and subsystem-local errors can carry useful message context now. |
| Add lock files, repair commands, or interrupted-run cleanup tooling | The v0 plan accepts atomic writes plus conservative resume. Add a lock manager only if targeted tests prove the current model cannot preserve correctness. |
| Convert README/docs into CLI-first documentation | Functional CLI commands are post-v0. V0 docs should teach the public Python API and import-safe CLI deferral. |
| Implement remote stores or cross-run cache reuse while documenting resume | These are deferred features. Phase 10 should document same-run-directory resume and keep remote/cross-run behavior out of scope. |
| Require every illustrative project-code snippet to run as an in-repo doctest | Some snippets necessarily reference downstream project stages. Feasible generic examples should execute; project-specific snippets should be labeled and bounded. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Error context may remain message-oriented rather than a structured shared model | Keeps Phase 10 focused on hardening behavior without a cross-cutting error framework rewrite. | Functional CLI, JSON error output, or multi-error aggregation needs stable machine-readable fields. |
| Some docs examples may remain illustrative if they require downstream project code | `loom` must stay domain-neutral and cannot ship project stages. | Users need a runnable examples package or a future tutorial repository. |
| No run lock manager unless tests prove one is required | The v0 implementation plan accepts atomic writes and conservative resume first. | Interrupted-run or concurrent-run tests expose duplicate execution, unsafe reuse, or unrecoverable state ambiguity. |
| No Markdown code-block extraction harness in this phase | Manual mirrored docs/example tests keep Phase 10 focused and avoid adding tooling while docs are still stabilizing. | Multiple docs start carrying long runnable examples that drift from tested snippets. |
| Corrupt state fails rather than auto-repairs | V0 favors explicit inspection and conservative correctness over silent mutation of ambiguous run state. | A future `loom repair` command or store-maintenance API is designed and tested. |

## Reviewability

- Expected PR size and shape: focused hardening/docs PR with targeted source edits, new/updated tests across suites, and documentation updates. The PR should not introduce new subsystems or broad refactors.
- Files and areas to inspect: error messages and wrapping in config, pipeline, stores, planning, and execution; resume/recovery edge cases; contract tests; README and docs examples; import-boundary tests.
- Scope-control checks: no new backend, CLI command, remote-store, plugin, domain, or cross-run cache behavior; root `loom.__init__` remains cheap; deferred features remain documented as deferred.

## Implementation Steps

1. Add failing focused tests for the exact error-hardening targets above. Group them by subsystem so each source change has a narrow test signal: config/recipes/instantiate, pipeline specs/bindings, stores, planning/resume, execution/output validation.
2. Implement only local message/wrapping fixes in the owning subsystem modules. Prefer adding path, stage, target, artifact id, document path, and cause text to existing exceptions over introducing shared error machinery. Preserve exception chaining with `from exc`.
3. Add resume/recovery tests and fixes for the exact prior-state cases: `RUNNING`, non-succeeded statuses, missing `outputs.json`, corrupt stage docs, missing artifacts, partial artifacts, checksum mismatch, and artifact-index conflict. Keep behavior conservative and do not add repair, cleanup, retry, or locking features.
4. Strengthen structural contract tests for stages, codecs, recipes, artifact stores, and run stores. Reuse existing `tests/support/pipeline_execution_*` helpers when possible; add support helpers only if they keep examples domain-neutral.
5. Extend package import-boundary tests for root, serialization, I/O, config, pipeline, execution, executors, stores, planning, and CLI stub boundaries. Record any intentional `loom.pipeline` public import side effect explicitly in the test name or assertion comment.
6. Update README and targeted docs/feature sections listed above. Keep examples Python-API-first, same-run-local-only, and domain-neutral; mark downstream project snippets as illustrative.
7. Add or extend executable example coverage by mirroring copyable public API snippets in `tests/e2e/test_local_pipeline_run.py`, `tests/integration/pipeline/test_local_execution.py`, or a new `tests/integration/docs/test_v0_python_examples.py`. Do not build a generic docs parser.
8. Run narrow tests after each slice. Run suite-level commands before handing to PR preparation when practical, and leave final `make validate-pr` and `make test-summary` evidence for the PR-preparation stage.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import.py`, `tests/package/test_import_boundaries.py`, `tests/package/test_public_api.py`, `tests/package/test_config_api.py`, `tests/package/test_pipeline_api.py`, `tests/package/test_pipeline_store_api.py`, `tests/package/test_pipeline_planning_api.py`, `tests/package/test_pipeline_execution_api.py`, and `tests/package/test_pipeline_executor_api.py`.
- Required assertions: `import loom` remains cheap; root import does not load config, pipeline, pipeline runners, stores, executors, CLI, plugin discovery, project modules, or config dependencies; serialization and I/O imports preserve lower-layer boundaries; config import does not import pipeline/execution/CLI; CLI imports remain unsupported and side-effect free; public import paths remain stable after all v0 subsystems exist.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_config_errors.py`, `tests/unit/loom/config/test_compose.py`, `tests/unit/loom/config/test_overrides.py`, `tests/unit/loom/config/test_interpolation.py`, `tests/unit/loom/config/test_redaction.py`, `tests/unit/loom/config/recipes/test_catalog.py`, `tests/unit/loom/config/recipes/test_expansion.py`, `tests/unit/loom/config/instantiate/test_targets.py`, `tests/unit/loom/config/instantiate/test_recursive.py`, `tests/unit/loom/pipeline/test_specs.py`, `tests/unit/loom/pipeline/graph/test_bindings.py`, `tests/unit/loom/pipeline/planning/test_resume.py`, `tests/unit/loom/pipeline/planning/test_planner.py`, `tests/unit/loom/pipeline/planning/test_planning_errors.py`, `tests/unit/loom/pipeline/stores/test_local_artifacts.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/stores/test_store_errors.py`, `tests/unit/loom/pipeline/execution/test_outputs.py`, `tests/unit/loom/pipeline/executors/test_local_executor.py`, `tests/unit/loom/io/`, and `tests/unit/loom/test_errors.py`.
- Required assertions: representative errors include config paths, target paths, stage names, artifact keys, document names, and file paths; secrets are not leaked in error text; resume helpers refuse every unsafe prior-state case listed in this plan; output validation and target construction failures are path-aware; store errors include document paths and logical artifact ids where available.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_stage_contract.py`, `tests/contracts/test_codec_contract.py`, `tests/contracts/test_recipe_contract.py`, `tests/contracts/test_store_contract.py`, plus existing `tests/contracts/test_executor_contract.py` and `tests/contracts/test_data_source_contract.py` if import or protocol changes touch them.
- Required assertions: downstream-style dummy stages, codecs, recipes, artifact stores, and run stores satisfy protocols structurally without inheriting concrete `loom` classes; public APIs accept those structural implementations where v0 promises protocol support; failure cases preserve recipe/stage/store context without requiring subclass-specific behavior.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_config.py`, `tests/integration/config/test_compose_recipes.py`, `tests/integration/pipeline/test_pipeline_config.py`, `tests/integration/pipeline/test_planning_resume.py`, `tests/integration/pipeline/test_local_stores.py`, `tests/integration/pipeline/test_plan_persistence.py`, `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_local_execution_failures.py`, `tests/integration/pipeline/test_local_execution_resume.py`, and optional new `tests/integration/docs/test_v0_python_examples.py`.
- Required assertions: config-to-pipeline errors preserve useful paths; store/planner/runner collaboration refuses stale `RUNNING`, failed, corrupt, missing-output, partial-artifact, and checksum-mismatched state; same-run resume stays conservative and inspectable; docs-mirrored examples use public APIs and generic support stages only.

### E2E Suite

- Status: required.
- Expected paths: `tests/e2e/test_local_pipeline_run.py` plus only tightly scoped additional e2e coverage if integration tests cannot exercise a copyable docs example.
- Required assertions: public Python API examples run a synthetic local pipeline, inspect the run directory, rerun the same run directory with `REUSE`, exercise selectors where feasible through `PlanSelectors`, and fail clearly for one representative invalid output or corrupted reusable artifact if that behavior is not already covered at integration level.

### Opt-In Suites

- Status: deferred.
- Markers affected: `slow`, `network`, `slurm`, `optional_dependency`, and any future remote/external markers.
- Required assertions or deferral reason: Phase 10 is local-only hardening and documentation. It must not require network services, SLURM, remote stores, optional executor dependencies, slow external fixtures, or a functional CLI. Do not introduce new opt-in markers. If an opt-in marker appears necessary, stop and report the blocker before implementation.

## Risks

- Error hardening can become a broad refactor if it tries to standardize every error class rather than representative user-facing failures.
- Interrupted-run behavior can be subtle because v0 has no lock manager; tests should prove conservative refusal to reuse rather than introduce ad hoc cleanup.
- Documentation can drift from implementation if examples are not covered or clearly marked as illustrative.
- Stacked branch maintenance is required before merge eligibility because Phase 10 depends on unmerged Phase 9, which depends on unmerged Phase 8 and Phase 7.
- Broad import-boundary tests may expose predecessor issues; fix only issues that affect Phase 10 acceptance and record any predecessor blocker instead of widening scope.

## Validation Commands

Targeted development commands:

```sh
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
```

Focused commands likely useful during implementation:

```sh
uv run pytest tests/unit/loom/config tests/unit/loom/pipeline/test_specs.py tests/unit/loom/pipeline/graph/test_bindings.py -q
uv run pytest tests/unit/loom/pipeline/planning/test_resume.py tests/unit/loom/pipeline/stores/test_local_artifacts.py tests/unit/loom/pipeline/stores/test_local_runs.py -q
uv run pytest tests/unit/loom/pipeline/execution/test_outputs.py tests/unit/loom/pipeline/executors/test_local_executor.py -q
uv run pytest tests/package/test_import_boundaries.py tests/contracts -q
uv run pytest tests/integration/config tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_planning_resume.py -q
uv run pytest tests/integration/pipeline tests/e2e/test_local_pipeline_run.py -q
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - config/recipe/target/spec/binding error-message tests and fixes;
  - store/resume/runner recovery hardening for the exact prior-state cases;
  - structural contract-test strengthening;
  - import-boundary guardrails;
  - README/docs updates plus mirrored executable example coverage.
- Tests to run with each slice: run the narrowest corresponding unit or package tests first, then contract/integration/e2e slices before final PR-preparation validation. Use `make validate-pr` and `make test-summary` only when the implementation is ready for PR preparation or when a broad source change needs full-gate confidence.
- Decisions the executor must not revisit: Phase 10 stays local-only and Python-API-first; configs are trusted; output `codec_key` remains optional; stage constructor kwargs remain deferred; resume is same-run-directory only; corrupt state fails clearly rather than silently repairing; remote stores, CLI commands, new executors, cross-run reuse, retries, lock managers, and domain behavior are deferred.
- Conditions that require stopping for the manager: a required acceptance criterion appears to need a public API expansion, broad error-framework rewrite, lock manager, repair command, predecessor-branch change, remote/GitHub operation, functional CLI behavior, or implementation outside the Phase 10 scope.

## Refinement And Review Budget Status

- Phase execution plan draft: completed by `loom_phase_planner` on 2026-05-04 local time in draft commit `91904e74207f89a8507573774470f1c23a6b7df9`.
- Phase execution plan refine: completed by `loom_phase_planner` on 2026-05-04 local time in this plan-only refinement commit.
- Phase implementation refinement: used by `loom_phase_refiner` on 2026-05-04 local time; no automated implementation refinement budget remains for this phase.
- PR review: unused.
- PR body draft/refine: draft completed on 2026-05-04 local time in
  `docs/phases/harden-v0-docs-pr-body.md`; refine completed on 2026-05-04
  local time by `loom_pr_preparer`.

## Completion Notes

- Draft plan: created by `loom_phase_planner` in `docs/phases/harden-v0-docs.md` on 2026-05-04 local time.
- Final phase execution plan: refined by `loom_phase_planner` in `docs/phases/harden-v0-docs.md` on 2026-05-04 local time. The artifact is ready for `loom_phase_executor` unless stack state changes before implementation begins.
- Implementation summary:
  - Added hardening coverage for conservative resume edge cases in `tests/unit/loom/pipeline/planning/test_resume.py`:
    - stale `RUNNING` and failed prior statuses,
    - missing `outputs.json`,
    - corrupt outputs/state documents,
    - prior fingerprint corruption,
    - artifact checksum mismatch,
    - artifact index conflict.
  - Strengthened import-boundary guardrails in `tests/package/test_import_boundaries.py` for `loom.config`, `loom.pipeline`, `loom.pipeline.stores`, `loom.pipeline.execution`, `loom.pipeline.executors`, and `loom.cli`.
  - Added executor/store protocol structural guard tests in `tests/contracts/test_store_contract.py`.
  - Added executable docs example in `tests/integration/docs/test_v0_python_examples.py` for README reuse semantics.
  - Hardened import boundaries in implementation to support the phase:
    - removed runtime execution-model type dependencies from `loom.pipeline.executors.base` and `loom.pipeline.executors.local`,
    - converted `loom.pipeline.execution` to lazy `__getattr__` exports to avoid execution-time planning import side effects during executor import.
  - Updated `README.md` and `docs/loom.md` for v0 run-layout, resume semantics, and same-run conservative reuse documentation.
- Implementation validation:
  - Focused slices:
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning/test_resume.py tests/contracts/test_store_contract.py tests/package/test_import_boundaries.py tests/integration/docs/test_v0_python_examples.py -q`
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_executor_api.py tests/package/test_pipeline_planning_api.py tests/package/test_pipeline_store_api.py -q`
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning -q`
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py -q`
  - Results: all passed in the commands above.
- Refinement summary: implementation refinement pass used by `loom_phase_refiner` on 2026-05-04 local time. The pass fixed executor import-boundary hardening regressions, tightened README quickstart setup, reran focused Phase 10 checks, and ran the full validation gate.
- PR preparation: deferred to manager/next stage.
- PR body draft: created at `docs/phases/harden-v0-docs-pr-body.md` on
  2026-05-04 local time. Draft confirms branch `codex/harden-v0-docs`, target
  branch `codex/add-local-execution`, stack predecessor
  `codex/add-local-execution`, stacked merge eligibility, Phase 10 scope,
  implementation refinement budget used, PR review budget unused, refreshed
  `make test-summary` suite evidence, and that no PR was opened in the draft
  pass.
- PR body refine: completed by `loom_pr_preparer` on 2026-05-04 local time.
  Refine pass verified the PR body against the actual stacked diff from
  `codex/add-local-execution`, confirmed Phase 10 hardening/docs/contracts
  scope with no deferred feature work, reran final PR validation, and prepared
  explicit push/PR creation against `codex/add-local-execution`.
- PR preparation validation:
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed during PR body
    refinement: Ruff passed, Pyright reported 0 errors, default pytest passed
    with 368 tests, and build succeeded.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed during PR body
    refinement: package, unit, contract, integration, and e2e suites passed.
- Stack maintenance: Phase 10 is stacked on `codex/add-local-execution` and targets `codex/add-local-execution`; retarget to `develop` only after predecessor phases land and validation is rerun.
- Remaining blockers: none observed.

## Phase Refinement Report

## Metadata

- Phase: Phase 10 - Hardening And Documentation.
- Branch: `codex/harden-v0-docs`.
- Worktree: `/home/samcantrill/work/loom-worktrees/harden-v0-docs`.
- Phase execution plan: `docs/phases/harden-v0-docs.md`.
- Refiner: `loom_phase_refiner`.
- Refinement date: 2026-05-04 local time.
- Phase implementation refinement budget status after this pass: used.

## Refinement Scope

- Validation output reviewed: executor-provided passing focused Phase 10 commands from the manager assignment, local focused reruns, `make validate-pr`, and `make test-summary`.
- Blocking issues caused by this phase:
  - `Executor.execute` had been widened from `StageExecutionRequest -> StageExecutionResult` to `object -> object` while removing import-time execution coupling.
  - `LocalExecutor.execute` could rely on an unrelated `loom.pipeline.execution.logs` package side effect instead of importing the log helper directly at execution time.
  - The README quickstart wrote `tmp/demo_pipeline.yaml` before creating the `tmp/` directory.
- Issues confirmed out of scope: no functional CLI, remote stores, cross-run cache reuse, new backends, lock managers, repair commands, broad error framework changes, or domain-specific behavior were needed.

## Fixes Made

| Issue | Change | Evidence |
| --- | --- | --- |
| Executor protocol type regression | Restored type-only `StageExecutionRequest` / `StageExecutionResult` annotations in `loom.pipeline.executors.base` without runtime execution imports. | `make validate-pr` passed with Pyright `0 errors`; package import-boundary tests passed. |
| Local executor log helper side effect | Imported `write_text_file` from `loom.pipeline.execution.logs` inside `LocalExecutor.execute` and adjusted the local executor unit test to import `StageExecutionRequest` from `loom.pipeline.execution.models`. | `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/test_local_executor.py -q` passed with `3 passed`. |
| README quickstart parent directory | Added `config_path.parent.mkdir(parents=True, exist_ok=True)` before writing the example config. | `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/docs/test_v0_python_examples.py -q` passed with `1 passed`. |

## Tests Or Validation Re-Run

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/test_local_executor.py -q
result: passed, 3 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py -q
result: passed, 9 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/executors/base.py src/loom/pipeline/executors/local.py tests/unit/loom/pipeline/executors/test_local_executor.py README.md
result: passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/docs/test_v0_python_examples.py -q
result: passed, 1 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/test_local_executor.py tests/unit/loom/pipeline/planning/test_resume.py tests/contracts/test_store_contract.py tests/package/test_import_boundaries.py tests/integration/docs/test_v0_python_examples.py -q
result: passed, 29 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_executor_api.py tests/package/test_pipeline_planning_api.py tests/package/test_pipeline_store_api.py -q
result: passed, 27 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning -q
result: passed, 23 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py -q
result: passed, 10 passed

command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 368 tests, and build succeeded

command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; package, unit, contract, integration, and e2e suites passed
```

## Remaining Blockers

- None observed in this bounded refinement pass.

## PR Preparation Handoff

- Completion notes updated in phase execution plan: yes.
- Budget status updated: yes, implementation refinement budget is used.
- Final validation recommended: rerun `make validate-pr` and `make test-summary` after any stack rebase or retarget to `develop`.
- Suite evidence still needed: none for the current local branch state; PR preparation should reuse or refresh the evidence depending on stack maintenance timing.
