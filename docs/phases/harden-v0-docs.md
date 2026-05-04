# Phase 10 Execution Plan: Hardening And Documentation

## Metadata

- Status: draft phase execution plan
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
- Draft pass: completed by `loom_phase_planner` on 2026-05-04 local time in this plan commit.
- Refine pass: pending; the refine pass must make implementation choices decision-complete before executor work begins.
- Phase implementation refinement budget: unused.
- PR review budget: unused.
- PR body draft/refine budget: unused until PR-preparation workflow stages.
- Setup limitations: no remote operations or validation commands were run during this draft pass. The worktree was created from the local recorded predecessor branch because the manager supplied the exact Phase 9 base head.
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

## Implementation Boundaries

- Allowed source areas: `src/loom/errors.py` only if a shared minimal helper is justified; targeted subsystem modules under `src/loom/config/`, `src/loom/io/`, `src/loom/pipeline/`, `src/loom/pipeline/stores/`, `src/loom/pipeline/planning/`, `src/loom/pipeline/execution/`, and `src/loom/pipeline/executors/` where error or recovery behavior is already owned.
- Allowed docs areas: `README.md`, `docs/loom.md`, relevant `docs/features/*.md`, `tests/README.md`, and Phase 10 artifacts under `docs/phases/`.
- Allowed tests: `tests/package/`, `tests/unit/loom/`, `tests/contracts/`, `tests/integration/`, `tests/e2e/`, and generic support helpers under `tests/support/`.
- Avoid changing public APIs unless required to expose already-implemented v0 behavior or preserve stable import paths. If a public contract change is needed, document it in this plan during refinement before implementation.
- Keep all runtime and test examples domain-neutral; project-specific classes may appear only as illustrative docs placeholders, not in package code.

## Decision-Complete Contract

The refine pass must turn this draft into exact implementation slices before executor work begins. The current draft contract is:

- Error behavior: representative high-traffic errors must include enough context for a user to locate the bad config key, stage, target, artifact, persisted document, or filesystem path. Messages must not print unredacted secret values.
- Recovery behavior: same-run resume must refuse reuse for stale `RUNNING`, failed, missing, corrupt, partial, checksum-mismatched, or unverifiable prior state. It may rerun or fail clearly depending on whether the state is recoverable through existing store/planner contracts.
- Extension contracts: protocols remain structural. Tests should instantiate downstream-style classes without inheriting from concrete `loom` classes and prove public APIs accept them where v0 promises protocol support.
- Documentation: docs must describe the implemented Python API and v0 limitations. They must not imply that functional CLI commands, remote stores, cross-run reuse, or deferred config language features exist.
- Import boundaries: `import loom` remains cheap and must not import config composition, pipeline runners, CLI modules, plugin discovery, project packages, or optional/heavy future paths.

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

## Reviewability

- Expected PR size and shape: focused hardening/docs PR with targeted source edits, new/updated tests across suites, and documentation updates. The PR should not introduce new subsystems or broad refactors.
- Files and areas to inspect: error messages and wrapping in config, pipeline, stores, planning, and execution; resume/recovery edge cases; contract tests; README and docs examples; import-boundary tests.
- Scope-control checks: no new backend, CLI command, remote-store, plugin, domain, or cross-run cache behavior; root `loom.__init__` remains cheap; deferred features remain documented as deferred.

## Implementation Steps

1. Inventory current high-traffic errors and select representative coverage targets across config, recipes, instantiation, specs/bindings, stores, planning/resume, output validation, and runner target construction.
2. Add focused unit tests for missing path context, unsafe secret exposure, target/stage/artifact names, persisted document paths, and checksum/file-path failures before changing behavior.
3. Improve local messages and wrapping in the owning subsystem modules, keeping changes narrow and preserving broad root inheritance.
4. Add interrupted-run and partial-state tests for `RUNNING` prior status, missing `outputs.json`, corrupt JSON, partial artifact files, checksum mismatch, and failed prior stages; update planner/runner/store behavior only where tests expose unsafe reuse or unclear errors.
5. Extend contract tests with downstream-style dummy stages, codecs, recipes, artifact stores, and run stores that satisfy protocols structurally without inheritance.
6. Update package import-boundary tests so the final v0 stack permanently protects cheap imports and lower-layer independence from CLI, execution, config, and project modules.
7. Update README and targeted docs for trusted configs, `_target_`, `_recipe_`, stage contract, artifacts, optional codec keys, run layout, checksums vs fingerprints, selectors, and same-run resume.
8. Add docs/example execution coverage where feasible, or explicitly mark examples that require downstream project code and record the deferral.
9. Run targeted suites during implementation, then leave final `make validate-pr` and `make test-summary` evidence for PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import.py`, `tests/package/test_import_boundaries.py`, `tests/package/test_public_api.py`, and package API tests for pipeline/config/store/planning/execution imports.
- Required assertions: `import loom` remains cheap; root import does not load config, pipeline runners, CLI, plugin discovery, or project modules; public import paths remain stable; CLI modules are import-safe unsupported stubs only.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/`, `tests/unit/loom/pipeline/`, `tests/unit/loom/pipeline/planning/`, `tests/unit/loom/pipeline/stores/`, `tests/unit/loom/pipeline/execution/`, `tests/unit/loom/io/`, `tests/unit/loom/test_errors.py`, and any focused docs/example unit helpers added in refinement.
- Required assertions: representative errors include config paths, target paths, stage names, artifact keys, document names, and file paths; secrets are not leaked in error text; resume helpers refuse unsafe prior state; output validation and target construction failures are path-aware.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_stage_contract.py`, `tests/contracts/test_codec_contract.py`, `tests/contracts/test_recipe_contract.py`, `tests/contracts/test_store_contract.py`, and existing executor/data-source contracts where import or protocol changes touch them.
- Required assertions: downstream-style dummy stages, codecs, recipes, artifact stores, and run stores satisfy protocols structurally without inheriting concrete `loom` classes; public APIs accept those structural implementations where v0 promises protocol support.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/`, `tests/integration/pipeline/test_pipeline_config.py`, `tests/integration/pipeline/test_planning_resume.py`, `tests/integration/pipeline/test_local_stores.py`, `tests/integration/pipeline/test_plan_persistence.py`, `tests/integration/pipeline/test_local_execution*.py`, and any new docs/example integration tests.
- Required assertions: config-to-pipeline errors preserve useful paths; store/planner/runner collaboration refuses stale `RUNNING`, failed, corrupt, missing-output, partial-artifact, and checksum-mismatched state; same-run resume stays conservative and inspectable.

### E2E Suite

- Status: required.
- Expected paths: `tests/e2e/test_local_pipeline_run.py` plus any new e2e docs/example coverage added during refinement.
- Required assertions: public Python API examples run a synthetic local pipeline, inspect the run directory, rerun the same run directory with `REUSE`, exercise selectors where feasible, and fail clearly for representative invalid outputs or corrupted reusable artifacts.

### Opt-In Suites

- Status: deferred.
- Markers affected: `slow`, `network`, `slurm`, `optional_dependency`, and any future remote/external markers.
- Required assertions or deferral reason: Phase 10 is local-only hardening and documentation. It must not require network services, SLURM, remote stores, optional executor dependencies, or slow external fixtures. If any new opt-in marker is introduced, the phase plan must be refined with a concrete reason before implementation.

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
uv run pytest tests/unit/loom/config tests/unit/loom/pipeline -q
uv run pytest tests/contracts -q
uv run pytest tests/integration/pipeline tests/e2e -q
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - error-message tests and fixes by subsystem;
  - interrupted-run/resume hardening;
  - contract-test strengthening;
  - import-boundary guardrails;
  - README/docs updates and executable example coverage.
- Tests to run with each slice: run the narrowest corresponding unit or package tests first, then contract/integration/e2e slices before final PR-preparation validation.
- Decisions the executor must not revisit: Phase 10 stays local-only and Python-API-first; configs are trusted; output `codec_key` remains optional; resume is same-run-directory only; remote stores, CLI commands, new executors, cross-run reuse, lock managers, and domain behavior are deferred.
- Conditions that require stopping for the manager: a required acceptance criterion appears to need a public API expansion, broad error-framework rewrite, lock manager, predecessor-branch change, remote/GitHub operation, or implementation outside the Phase 10 scope.

## Refinement And Review Budget Status

- Phase execution plan draft: completed by `loom_phase_planner` on 2026-05-04 local time in this plan commit.
- Phase execution plan refine: unused.
- Phase implementation refinement: unused.
- PR review: unused.
- PR body draft/refine: unused.

## Completion Notes

- Draft plan: created by `loom_phase_planner` in `docs/phases/harden-v0-docs.md` on 2026-05-04 local time.
- Final phase execution plan: pending refine pass.
- Implementation summary: pending implementation stage.
- Implementation validation: pending implementation and PR-preparation stages.
- Refinement summary: pending one bounded implementation refinement pass.
- PR preparation: pending.
- Stack maintenance: Phase 10 is stacked on `codex/add-local-execution` and targets `codex/add-local-execution`; retarget to `develop` only after predecessor phases land and validation is rerun.
- Remaining blockers: none.
