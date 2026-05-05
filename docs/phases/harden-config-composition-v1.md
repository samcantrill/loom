# Phase 16 Execution Plan: Hardening, Documentation, And End-To-End Coverage

## Metadata

- Status: draft phase execution plan
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
- Merge eligibility: root phase PR targets `develop`; eligible for merge only after refine, implementation, phase-scoped validation, PR preparation, and review complete with no blocking findings
- Workflow path: expanded path
- Successor dependency notes: no v1 successor phase is planned; branch can be deleted after merge if no later ad hoc branch depends on it
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v1.md` on 2026-05-05; no blocking findings remain
- Plan quality gate loop budget: fully used before Phase 16 assignment; do not reopen
- Draft pass: completed by `loom_phase_planner`
- Refine pass: pending because the manager selected the expanded path
- Setup limitations: sandboxed `gh auth status` reported an invalid token, but network-enabled `gh auth status` succeeded; `gh auth setup-git`, `git fetch origin`, and worktree creation required approved filesystem/network access and then succeeded
- Blockers: none for the draft plan

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
- Existing docs to audit: `docs/features/config.md`, `docs/features/provenance.md`, `docs/features/fingerprints.md`, `docs/features/resume.md`, `docs/features/testing.md`, plus `examples/config/**` and docs integration checks for examples.
- Existing docs still include pre-v1 or future-looking text around `_copy_`, resolved config snapshots, source snapshots, CLI resume examples, and pipeline/resume dependence. Phase 16 should align those passages to v1 without rewriting unrelated roadmap material.
- Existing tests or harness behavior: config package/public API checks live in `tests/package/`; artifact and inspection contracts live under `tests/contracts/`; composition integration coverage lives in `tests/integration/config/`; example validation lives in `tests/integration/docs/`; e2e coverage currently lives in `tests/e2e/test_local_pipeline_run.py` and exercises local pipeline runs through Python APIs.
- Import-boundary or dependency constraints: `loom.config` remains persistence-free and must not import pipeline execution, run stores, CLI, plugin discovery, or project code. `loom.pipeline` must not depend on `loom.config` or composition manifests.

## In-Scope Work

- Align the named feature docs so they describe only accepted v1 behavior and clearly label future roadmap or out-of-scope behavior where it remains useful context.
- Update examples or example documentation only where they demonstrate stale config semantics or need v1-safe wording.
- Add or extend realistic, domain-neutral public-API tests that exercise strict composition trees with includes, overlays, user composition overrides, recipes, artifact-safe records, redaction, fingerprints, source metadata, and raw source snapshot opt-in where appropriate.
- Audit structured error coverage for high-risk strict-composition failures and add focused regressions when current coverage misses accepted v1 behavior.
- Add final hardening assertions that default artifacts do not persist resolver outputs, raw source bytes, or full resolved-config snapshots by default.
- Keep any product-code changes limited to bug fixes exposed by docs/test/error audit against accepted v1 contracts.

## Out-of-Scope Work

- Public CLI commands or CLI docs that imply available v1 command behavior.
- Plugin-discovered include resolvers, custom include resolvers, remote include sources, global search paths, sweeps, and `_copy_`.
- New public API shape, manifest schema redesign, persistence ownership changes, or new run-store config artifact writing.
- Changes that make `loom.pipeline` depend on `loom.config`, manifests, or composition source artifacts.
- New default persistence of resolver outputs, raw source bytes, or full resolved config snapshots.

## Assumptions

- The implementation plan is the source of truth where older feature docs still describe deferred or superseded behavior.
- Documentation can retain future roadmap concepts only when the text clearly says they are future work and not v1-supported behavior.
- E2E composition coverage should use public Python APIs and temporary domain-neutral config trees rather than invoking CLI commands.
- If the error audit finds missing diagnostics, small structured-error fixes are in scope only when they preserve accepted v1 semantics.

## Scope Contract

No new public contract changes are planned. The executor must preserve `compose_config`, `compose_config_with_catalog`, `inspect_config_composition`, `ComposedConfig`, composition manifest, provenance, source artifact, raw snapshot, fingerprint, and resume comparison semantics already established by Phases 1-15. The accepted v1 contract remains security-first: resolver outputs and raw source bytes are not persisted by default, raw source snapshots require explicit opt-in, fingerprinting uses artifact-safe authored inputs, `_copy_` is unsupported, and config composition is Python-API-only. Any code change must be a bug fix against those contracts, not a new semantic extension.

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
2. Add representative e2e coverage for strict composition through public Python APIs, using domain-neutral temporary config trees and existing optional dependency markers.
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
- Required assertions or deferral reason: cover a realistic domain-neutral config tree through public Python APIs, including base plus overlays, nested includes, user include swaps or strict add/update overrides, recipe expansion, resolver expression handling, redacted output, manifest/provenance/source records, fingerprint comparison, and raw source snapshot limitations. Avoid CLI invocation.

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

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: docs/examples audit first; e2e coverage second; regression/contract gaps third; narrow product fixes only if new or existing tests reveal behavior that violates accepted v1 contracts.
- Tests to run with each slice: docs/example changes should run `tests/integration/docs/test_v0_python_examples.py` when examples change; e2e additions should run the new/changed e2e tests; artifact or API changes should run the relevant package, contract, integration, and unit paths above.
- Decisions the executor must not revisit: persistence-free `loom.config`; no pipeline dependency on config/manifests; `_copy_` unsupported; default artifacts are security-first; resolver outputs and raw source bytes not persisted by default; v1 Python-API-only; no plugin, remote, global search, or custom include resolver behavior.
- Conditions that require stopping for the manager: a required fix needs public API/schema redesign, a docs claim conflicts with the accepted v1 implementation plan in a way that cannot be resolved by scoped wording, validation reveals cross-phase behavior outside config hardening, or remote/auth limitations prevent required PR-preparation evidence.
- Expanded-path refinement notes: refine this draft before implementation to confirm exact docs passages, the chosen e2e test shape, and any high-risk audit findings. Keep the refined plan concise and do not convert it into a file-by-file edit recipe.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in this commit
- Final phase execution plan: pending expanded-path refine pass
- Implementation summary: pending
- Implementation validation: pending
- Refinement summary: pending
- PR preparation: pending
- Stack maintenance: pending
- Remaining blockers: none known at draft time
