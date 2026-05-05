# Phase 16 Execution Plan: Hardening, Documentation, And End-To-End Coverage

## Metadata

- Status: final phase execution plan
- Feature focus: Configuration
- PR title: `Configuration - Phase 16: Hardening, Documentation, And End-To-End Coverage`
- Branch: `codex/harden-config-composition-v1`
- Worktree: `/home/samcantrill/work/loom-worktrees/harden-config-composition-v1`
- Phase execution plan path: `docs/phases/harden-config-composition-v1.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 16 - Hardening, Documentation, And End-To-End Coverage
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Base commit: `89749de201ac5ef045fac16818aacdcdc90ab6a7`
- Merge eligibility: root phase PR targets `develop`; eligible for merge only after implementation, phase-scoped validation, PR preparation, and review complete with no blocking findings
- Workflow path: expanded path
- Successor dependency notes: no v1 successor phase is planned; branch can be deleted after merge if no later ad hoc branch depends on it
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v1.md` on 2026-05-05; no blocking findings remain
- Plan quality gate loop budget: fully used before Phase 16 assignment; do not reopen
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed by `loom_phase_planner`; no additional automated plan refinement budget remains
- Setup limitations: sandboxed `gh auth status` reported an invalid token, but network-enabled `gh auth status` succeeded; `gh auth setup-git`, `git fetch origin`, and worktree creation required approved filesystem/network access and then succeeded
- Blockers: none

## Objective

Harden the completed v1 configuration composition surface by aligning feature docs and examples with supported v1 behavior, adding representative end-to-end and regression coverage through public APIs, auditing user-facing errors and limitations, and preparing final validation evidence without adding new product semantics beyond fixes revealed by that audit.

## Full-Plan Context

Phases 1-15 are merged into `develop` and supply the v1 config contracts: persistence-free `loom.config`, pipeline independence from config artifacts, unsupported `_copy_`, strict local/file include resolution, strict/add overrides, artifact-safe provenance and fingerprints, metadata-only source records by default, opt-in raw source snapshots, and Python API-only composition. Phase 16 is the closeout phase. It should consolidate docs, tests, and review evidence around those accepted decisions and should not design public CLI behavior, plugin discovery, remote include sources, sweeps, global include search, `_copy_`, or default persistence of resolved configs or raw source bytes.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phases 1-15 are merged
- Why this base branch is correct: `develop` is at the assigned base commit `89749de201ac5ef045fac16818aacdcdc90ab6a7`, which records Phase 15 merged
- Retarget/rebase plan after predecessor merge: not applicable because there is no predecessor
- Branch cleanup constraints: safe to delete after the Phase 16 PR is merged and no successor or blocker-resolution branch depends on it

## Source Phase Summary

- Goal: harden full v1 behavior, update docs, and close reviewability gaps.
- Required scope: feature docs and examples; alignment updates for `docs/features/config.md`, `docs/features/provenance.md`, `docs/features/fingerprints.md`, `docs/features/resume.md`, and `docs/features/testing.md`; end-to-end composition coverage; error audit; security and resume limitation docs; final validation evidence.
- Required checkpoints: docs no longer promise unsupported v1 behavior; strict composition flows have representative public-API coverage; limitations around resolver values, raw source snapshots, and resume are explicit; final PR preparation runs `make validate-pr` and `make test-summary`.
- Acceptance criteria: docs cover supported v1 behavior only; existing docs no longer promise `_copy_` in v1, default raw source snapshots, default resolved-config persistence, or pipeline dependence on config artifacts; e2e tests cover representative strict composition flows; limitations are clear; final validation passes.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/compose.py`, `src/loom/config/artifacts.py`, `src/loom/config/provenance.py`, `src/loom/config/fingerprints.py`, `src/loom/config/includes.py`, `src/loom/config/overrides.py`, `src/loom/config/interpolation.py`, `src/loom/config/validation.py`, and `src/loom/config/__init__.py`.
- Existing docs to audit, with updates limited to stale v1 claims and explicit limitation notes:
  - `docs/features/config.md`: Purpose and "Soon After v0" text that still lists `_copy_` and rebuildable source snapshots as part of the current post-v0 path; Package Boundary language that says `loom.pipeline` should call `loom.config`; Terminology sections for Resolved Config, Copy, and Composition Manifest; "Make Resolved Config Explicit"; recursive composition design constraints and examples that show `_copy_`; Composition Order text that treats CLI overrides and resolved snapshots as current runner/run-store behavior; Secrets and Redaction persistence wording; CLI Integration examples; Test Strategy bullets for `_copy_`, source snapshots, and resolved-config persistence.
  - `docs/features/provenance.md`: config provenance responsibilities around CLI overrides and full resolved config locations; Full Versus Public Provenance; Relationship to Config fields such as `resolved config hash/path`; Phase 7 CLI Integration. Clarify that v1 config returns provenance/manifest/source/fingerprint records but does not persist run provenance or own CLI display.
  - `docs/features/fingerprints.md`: Core Position dependency diagram if it implies config coupling; fingerprint record/payload guidance; Comparison/structured-input testing text only if it conflicts with artifact-safe config fingerprints. Add limitation wording that v1 config fingerprints preserve authored resolver expressions and do not persist resolved resolver outputs by default.
  - `docs/features/resume.md`: `loom.config` responsibilities that say it persists snapshots; Required Inputs and fingerprint-input text that says "current resolved config" without allowing artifact-safe config fingerprint views; CLI Integration examples for `loom plan --resume` and `loom run --resume`. Clarify that v1 provides comparison artifacts for future resume policy, while resume remains pipeline-owned and does not depend on `loom.config` or manifests.
  - `docs/features/testing.md`: suite ownership and e2e descriptions that make CLI e2e look current; public-Python guidance; CLI test sections; phase plan/test-structure sections that still list `_copy_`, broad CLI behavior, or future suites as current v1 obligations.
  - `examples/config/**`: audit only examples referenced by docs/tests or claiming v1 behavior; update stale wording or examples that imply `_copy_`, default raw source bytes, default resolved-config persistence, CLI behavior, plugin/remote/global resolvers, or pipeline dependence on config artifacts.
- Existing tests or harness behavior: config package/public API checks live in `tests/package/`; artifact and inspection contracts live under `tests/contracts/`; composition integration coverage lives in `tests/integration/config/`; example validation lives in `tests/integration/docs/`; e2e coverage currently lives in `tests/e2e/test_local_pipeline_run.py` and exercises local pipeline runs through Python APIs.
- Import-boundary or dependency constraints: `loom.config` remains persistence-free and must not import pipeline execution, run stores, CLI, plugin discovery, or project code. `loom.pipeline` must not depend on `loom.config` or composition manifests.

## In-Scope Work

- Align the named feature docs so they describe only accepted v1 behavior and clearly label future roadmap or out-of-scope behavior where it remains useful context.
- Update examples or example documentation only where they demonstrate stale config semantics or need v1-safe wording.
- Add or extend realistic, domain-neutral public-API tests that exercise strict composition trees with includes, overlays, user composition overrides, recipes, artifact-safe records, redaction, fingerprints, source metadata, and raw source snapshot opt-in where appropriate.
- Audit structured error coverage for high-risk strict-composition failures and add focused regressions when current coverage misses accepted v1 behavior.
- Add final hardening assertions that default artifacts do not persist resolver outputs, raw source bytes, or full resolved-config snapshots by default.
- Keep any product-code changes limited to bug fixes exposed by docs/test/error audit against accepted v1 contracts.
- Add concise limitation notes where needed instead of rewriting broad roadmap material; future-looking sections may remain when they are clearly labeled as future or post-v1.

## Out-of-Scope Work

- Public CLI commands or CLI docs that imply available v1 command behavior.
- Plugin-discovered include resolvers, custom include resolvers, remote include sources, global search paths, sweeps, and `_copy_`.
- New public API shape, manifest schema redesign, persistence ownership changes, or new run-store config artifact writing.
- Changes that make `loom.pipeline` depend on `loom.config`, manifests, or composition source artifacts.
- New default persistence of resolver outputs, raw source bytes, or full resolved config snapshots.
- Broad roadmap rewrites in the named docs, wholesale renaming of CLI terminology, or deletion of future planning material that can be made accurate with scoped v1 limitation notes.

## Assumptions

- The implementation plan is the source of truth where older feature docs still describe deferred or superseded behavior.
- Documentation can retain future roadmap concepts only when the text clearly says they are future work and not v1-supported behavior.
- E2E composition coverage should use public Python APIs and temporary domain-neutral config trees rather than invoking CLI commands.
- If the error audit finds missing diagnostics, small structured-error fixes are in scope only when they preserve accepted v1 semantics.
- A representative e2e test can be config-composition-only. It does not need to run a full pipeline, because Phase 16 is hardening the public config composition surface and v1 explicitly avoids pipeline dependence on config artifacts.

## Scope Contract

No new public contract changes are planned. The executor must preserve `compose_config`, `compose_config_with_catalog`, `inspect_config_composition`, `ComposedConfig`, composition manifest, provenance, source artifact, raw snapshot, fingerprint, and resume comparison semantics already established by Phases 1-15. The accepted v1 contract remains security-first: resolver outputs and raw source bytes are not persisted by default, raw source snapshots require explicit opt-in, fingerprinting uses artifact-safe authored inputs, `_copy_` is unsupported, and config composition is Python-API-only. Any code change must be a bug fix against those contracts, not a new semantic extension.

The error audit is deliberately narrow. It may add regressions or fixes for accepted v1 failures such as unsupported `_copy_`, missing includes, include cycles, include swaps without `_replace_`, invalid `_replace_`, strict update/add override misuse, custom resolver expressions, resolver expressions in include targets, raw snapshot flag misuse, and artifact-safety violations. It must not create new error classes or public semantics unless the accepted contract already requires them and the current implementation is plainly incomplete.

## Design Impact

- Maintainability: concentrates final hardening in docs and tests, using existing source-mirrored test files and harnesses instead of adding broad new abstractions.
- Extensibility: keeps future CLI, sweeps, plugins, remote sources, and `_copy_` available for later roadmap phases by documenting v1 limits explicitly rather than filling gaps with temporary behavior.
- Domain neutrality: examples and e2e fixtures should use generic model/dataset/stage-like mappings or existing neutral pipeline support helpers, not domain-specific research assumptions.
- Source-tree boundaries: docs and tests may reference public config APIs, but product fixes must stay within `src/loom/config/` unless an audit proves an accepted v1 boundary is already violated.

## Future Compatibility

- Future CLI documentation should be able to point at the same Python API semantics without relying on v1 CLI commands.
- Future run-store persistence can consume manifest/source/fingerprint records without retroactively depending on `loom.config` writing run directories.
- Future plugin and remote resolver designs remain free to define explicit resolver contracts because v1 docs should not imply ambient search or remote source behavior.
- Future `_copy_` work should start from a clearly deferred state, not from half-documented unsupported behavior.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add new composition features while hardening | Phase 16 is evidence-focused; new semantics would expand the final PR and bypass earlier phase review boundaries. |
| Rewrite all feature docs into v1-only specs | The named docs include broader roadmap context; Phase 16 should align stale or misleading v1 behavior without erasing unrelated future planning content. |
| Add CLI-based e2e coverage | v1 is Python-API-only, and CLI behavior is explicitly out of scope. |
| Persist resolved configs or raw source snapshots by default to simplify rebuildability | Rejected by accepted v1 security-first decisions; docs/tests must make the limitation visible. |
| Treat `tests/integration/config/` coverage as enough and skip e2e | Phase 16 specifically requires representative e2e coverage through public APIs. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| None planned | Phase 16 should close documentation and coverage debt rather than introduce new debt. | If implementation discovers unavoidable deferred docs or coverage gaps, record them here and in the PR body with a concrete owner/trigger. |

## Reviewability

- Expected PR size and shape: docs alignment plus focused test additions and narrow bug fixes only; no broad refactors or public API redesign.
- Files and areas to inspect: named feature docs; `examples/config/**`; `tests/e2e/`; `tests/integration/config/`; `tests/integration/docs/`; `tests/contracts/test_config_artifact_contract.py`; `tests/contracts/test_config_composition_inspection_contract.py`; `tests/contracts/test_config_error_contract.py`; `tests/package/test_config_api.py`; `tests/package/test_import_boundaries.py`; any touched `src/loom/config/**` files.
- Scope-control checks: verify the diff does not add CLI commands, plugin/remote resolver behavior, `_copy_`, default raw bytes, default resolved-config persistence, pipeline imports from config, or config imports from pipeline/run-store persistence.

## Implementation Steps

1. Audit and align v1 documentation in the named feature docs and examples, focusing on `_copy_`, source snapshots, resolver-value persistence, resolved-config persistence, resume limitations, and Python-API-only behavior.
2. Add one representative e2e composition flow through public Python APIs, using a temporary domain-neutral config tree and existing optional dependency markers.
3. Fill regression gaps found by the docs/error audit with focused package, unit, contract, or integration tests in existing source-mirrored test files.
4. Apply only narrow product fixes required for current behavior to satisfy accepted v1 contracts and the new tests.
5. Run targeted suites during implementation, then leave final `make validate-pr` and `make test-summary` for PR preparation evidence.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py`, `tests/package/test_public_api.py`
- Required assertions or deferral reason: public imports and signatures remain stable; `loom.config` import behavior does not drag in pipeline, stores, CLI, plugin discovery, or project code; `loom.pipeline` remains independent from config composition artifacts.

### Unit Suite

- Status: required for audit-discovered gaps
- Expected paths: existing `tests/unit/loom/config/test_*.py` files, especially `test_compose.py`, `test_config_errors.py`, `test_load.py`, `test_includes.py`, `test_overrides.py`, `test_interpolation.py`, `test_config_fingerprints.py`, `test_config_provenance.py`, and `test_config_artifacts.py`
- Required assertions or deferral reason: add focused regressions for any missing strict failure, artifact-safe omission, raw snapshot default, resume comparison limitation, or documentation example behavior uncovered during audit. Do not duplicate already-covered matrices.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_config_composition_inspection_contract.py`, `tests/contracts/test_config_error_contract.py`, and `tests/contracts/test_recipe_contract.py` if recipe manifest behavior is touched
- Required assertions or deferral reason: manifest, provenance, source artifact, raw snapshot reference, fingerprint record, inspection, and structured-error serialization remain plain-data and artifact-safe; default records omit resolver outputs and raw source bytes unless explicit opt-in is under test.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/config/test_compose_config.py`, `tests/integration/config/test_compose_includes.py`, `tests/integration/config/test_compose_overrides.py`, `tests/integration/config/test_compose_recipes.py`, `tests/integration/config/test_compose_provenance.py`, `tests/integration/config/test_compose_fingerprints.py`, `tests/integration/config/test_compose_source_snapshots.py`, and `tests/integration/docs/test_v0_python_examples.py`
- Required assertions or deferral reason: public `compose_config` and `inspect_config_composition` flows preserve strict composition order, source-aware errors, artifact-safe provenance/fingerprints, metadata-only defaults, raw-source opt-in behavior, and examples that still claim validation coverage.

### E2E Suite

- Status: required
- Expected paths: extend `tests/e2e/` with representative config-composition coverage or extend `tests/e2e/test_local_pipeline_run.py` when a full pipeline run is necessary
- Required assertions or deferral reason: add a config-composition e2e that calls `compose_config` or `inspect_config_composition` directly, not the CLI. Use a small temporary tree with base config, overlay, nested `_include_`, a user include swap with `_replace_: true` or an equivalent strict add/update override pair, a local recipe catalog, one built-in resolver expression, redaction, manifest/provenance/source metadata, artifact-safe fingerprint comparison, and raw source snapshot opt-in/default limitation assertions. Keep this representative instead of duplicating every integration matrix, and avoid running stages unless an existing e2e helper is clearly the smallest way to prove the public Python workflow.

### Opt-In Suites

- Status: required only for existing opt-in markers affected by the change
- Markers affected: `optional_dependency`, `contract`, `integration`, `e2e`; raw source snapshot behavior is an explicit API opt-in, not a separate slow suite
- Required assertions or deferral reason: run or update opt-in-marked tests relevant to changed docs/examples and composition behavior. Defer external service, remote URI, plugin, or CLI suites because those capabilities are out of scope for v1.

## Risks

- Documentation may contain broad future-roadmap text that is easy to over-edit; keep changes limited to stale v1 claims and explicit limitation notes.
- E2E tests could become too broad or slow; keep them representative and public-API focused rather than recreating every integration matrix.
- Error-audit fixes can drift into new semantics; stop for the manager if satisfying a test requires a public contract decision not already made in the v1 plan.
- Security wording must be precise: v1 can record source metadata and hashes by default, but must not imply raw bytes or resolver outputs are persisted by default.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py
uv run pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py tests/contracts/test_config_error_contract.py
uv run pytest tests/integration/config tests/integration/docs/test_v0_python_examples.py
uv run pytest tests/e2e -m e2e
uv run pytest tests/unit/loom/config
```

Use `UV_CACHE_DIR=/tmp/loom_uv_cache` for targeted `uv run` commands when the sandboxed/default uv cache is unavailable or when the command would otherwise write outside the worktree, for example:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/e2e -m e2e
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr
UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: docs/examples audit first; one representative public-Python e2e second; focused error/artifact regression gaps third; narrow product fixes only if new or existing tests reveal behavior that violates accepted v1 contracts.
- Tests to run with each slice: docs/example changes should run `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/integration/docs/test_v0_python_examples.py` when examples change; e2e additions should run the new/changed e2e path with `UV_CACHE_DIR=/tmp/loom_uv_cache`; artifact or API changes should run the relevant package, contract, integration, and unit paths above.
- Decisions the executor must not revisit: persistence-free `loom.config`; no pipeline dependency on config/manifests; `_copy_` unsupported; artifact-safe defaults; resolver outputs and raw source bytes not persisted by default; v1 Python-API-only; no plugin, remote, global search, custom include resolver, or CLI behavior.
- Conditions that require stopping for the manager: a required fix needs public API/schema redesign, a docs claim conflicts with the accepted v1 implementation plan in a way that cannot be resolved by scoped wording, validation reveals cross-phase behavior outside config hardening, a representative e2e would require CLI or pipeline-coupled config semantics, satisfying an error audit requires new public semantics rather than a focused regression/bug fix, or remote/auth limitations prevent required PR-preparation evidence.
- Final stop conditions before PR preparation: do not proceed if docs still promise `_copy_`, default raw source bytes, default resolved-config persistence, resolver-output persistence, config-owned run-store writes, CLI behavior, plugin/remote/global resolvers, or pipeline dependence on config artifacts; do not proceed if package, unit, contract, integration, e2e, or opt-in suite obligations above are unaddressed or intentionally deferring a suite without the explicit reason recorded in the PR body.

## Refinement And Review Budget Status

- Phase implementation refinement: used by `loom_phase_refiner`; no additional automated implementation refinement budget remains
- Pre-submit blocker gate: used for the exact Secret Redaction wording blocker
- Blocker-resolution: used by user-authorized scoped pre-submit docs blocker pass; no additional automated blocker-resolution budget remains
- PR body draft: completed by `loom_pr_preparer`; durable draft created at `docs/phases/harden-config-composition-v1-pr-body.md`
- PR body refine: pending for the expanded-path PR opening pass
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in commit `e2632a2`
- Final phase execution plan: completed by `loom_phase_planner`; scope-complete for implementation
- Implementation summary: aligned stale v1 claims in the named feature docs,
  added one public-Python config-composition e2e covering base/overlay/nested
  includes, user include replacement, strict/add overrides, recipe catalog,
  built-in resolver expressions, redaction, manifest/provenance/source metadata,
  artifact-safe fingerprint comparison, and raw snapshot default/opt-in
  behavior; fixed a narrow `CompositionManifest.to_dict()` bug where nested
  frozen recipe-manifest mappings were not thawed before serialization.
- Implementation validation: targeted package/import-boundary checks passed
  with 18 tests; targeted config unit/integration optional-dependency checks
  passed with 271 tests; targeted e2e plus config artifact contract checks
  passed with 10 tests; touched-file Ruff and Pyright checks passed;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed with Ruff, Pyright,
  default suite 430 passed/11 skipped, config-extra suite 301 passed/436
  deselected, and package build success; `UV_CACHE_DIR=/tmp/loom_uv_cache make
  test-summary` wrote `build/test-summary.md` with package 36 passed/1 skipped,
  unit 354 passed/1 skipped, contract 31 passed/2 skipped, integration 9
  passed/5 skipped, e2e 6 passed, and config-extra 301 passed/436 deselected.
- Refinement summary: expanded-path plan refine pass confirmed exact documentation audit targets, representative public-Python e2e shape, focused error-audit limits, final validation obligations, and explicit executor stop conditions
- Implementation refinement summary: bounded expanded-path implementation refine
  pass inspected the final diff, removed the remaining top-level docs wording
  that implied handing config results to `loom.pipeline`, and renamed the
  representative e2e fixture and related artifact-contract paths from
  `pipeline` to domain-neutral `workflow` so the coverage stays public-Python
  and config-only. No public API/schema redesign, CLI behavior, pipeline/store
  behavior, remote/plugin/global resolver behavior, `_copy_`, default raw-byte
  persistence, or default resolved-config persistence was added.
- Implementation refinement validation: `UV_CACHE_DIR=/tmp/loom_uv_cache uv run
  pytest tests/contracts/test_config_artifact_contract.py
  tests/e2e/test_config_composition_public_api.py` passed with 10 tests;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed with Ruff, Pyright,
  default suite 430 passed/11 skipped, config-extra suite 301 passed/436
  deselected, and package build success; `UV_CACHE_DIR=/tmp/loom_uv_cache make
  test-summary` wrote `build/test-summary.md` with package 36 passed/1 skipped,
  unit 354 passed/1 skipped, contract 31 passed/2 skipped, integration 9
  passed/5 skipped, e2e 6 passed, and config-extra 301 passed/436 deselected.
- PR preparation: expanded-path draft PR body completed at
  `docs/phases/harden-config-composition-v1-pr-body.md`; PR opening is
  intentionally deferred to the later PR-body refine/opening pass.
- PR facts: title `Configuration - Phase 16: Hardening, Documentation, And
  End-To-End Coverage`; branch `codex/harden-config-composition-v1`; target
  branch `develop`; stack predecessor none/root phase; merge eligibility remains
  root PR to `develop` after PR-body refine, PR opening, remote verification,
  and review with no blocking findings.
- Draft PR-body scope confirmation: public body summarizes docs alignment,
  representative public-Python e2e coverage, and the focused
  `CompositionManifest.to_dict()` artifact-contract bug fix only. No future CLI,
  plugin, remote, sweep, `_copy_`, run-store persistence, default raw-source
  persistence, default resolved-config persistence, or pipeline dependency scope
  is included.
- Draft PR-body validation evidence: reused current recorded evidence:
  targeted config artifact contract plus public-Python e2e passed with 10 tests;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed with Ruff, Pyright,
  default suite 430 passed/11 skipped, config-extra suite 301 passed/436
  deselected, and build success; `UV_CACHE_DIR=/tmp/loom_uv_cache make
  test-summary` wrote `build/test-summary.md` with package 36 passed/1 skipped,
  unit 354 passed/1 skipped, contract 31 passed/2 skipped, integration 9
  passed/5 skipped, e2e 6 passed, and config-extra 301 passed/436 deselected.
- Blocker-resolution summary: user-authorized scoped pass changed the Secret
  Redaction wording in `docs/features/config.md` from `Persist both:` to
  `Expose both:` so the section no longer promises default resolved-config
  persistence while preserving the following `resolved` in-memory caller result
  and `redacted` artifact-safe view content.
- Blocker-resolution evidence: quick named-feature-doc search found no
  remaining `Persist both` wording; close-variant hits were existing negative
  or limitation statements such as `not a default persistence artifact` and
  `do not persist resolved resolver outputs by default`; `git diff --check`
  passed; focused text sanity checks for `Persist both`, `Expose both`,
  `resolved:`, and `redacted:` passed.
- Stack maintenance: none needed in this draft pass; root phase has no stack
  predecessor
- Remaining blockers: none
