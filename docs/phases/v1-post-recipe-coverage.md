# Phase 6 Execution Plan: Recipe Residual Risk And Coverage Hardening

## Metadata

- Status: fast-path phase execution plan; ready for implementation
- Feature focus: V1 Post Configuration
- PR title: `V1 Post Configuration - Phase 6: Recipe Residual Risk And Coverage Hardening`
- Branch: `codex/v1-post-recipe-coverage`
- Worktree: `/home/samcantrill/work/loom-worktrees/v1-post-recipe-coverage`
- Phase execution plan path: `docs/phases/v1-post-recipe-coverage.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1-post.md`
- Source phase: Phase 6. Recipe Residual Risk And Coverage Hardening
- Stack predecessor: none; Phases 1-5 have merged into `develop`.
- Base branch: `develop` / `origin/develop` at `963724a` (`docs: record v1-post phase 5 merged (#54)`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after review and checks because the target is `develop`.
- Workflow path: fast path
- Successor dependency notes: Phase 7 final sweep may start from this branch only after this phase PR is opened or prepared, validated, and recorded as `pr_open`. Phase 7 docs/evidence cleanup must not be pulled into this phase.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v1-post.md`; no blocking plan-review findings remain.
- Plan quality gate loop budget: initial review used, automated refinement used, confirmation review used.
- Draft pass: completed by `loom_phase_planner` in this commit.
- Refine pass: not needed; source inspection found residual-risk documentation and coverage hardening only, with no durable design, schema, persistence, or public API changes required.
- Setup limitations: `git worktree add` needed approved Git metadata access after the sandbox could not create the nested `refs/heads/codex/...` directory. No product-code setup blocker remains.
- Blockers: none for implementation.

## Objective

Make the remaining recipe artifact-safety limits explicit and close focused coverage gaps around recipe manifests, recipe fingerprint inputs, explicit relative include escapes, include sibling local customizations, and v1-post packaging metadata without changing recipe semantics.

## Full-Plan Context

V1-post has already merged source boundary cleanup, strict authoring, structured diagnostics, artifact-safe provenance/fingerprint ordering, and pipeline/run-store persistence. This phase is the residual-risk and coverage-hardening pass for behavior that is already intentionally constrained: recipes are trusted Python, resolver-shaped recipe output keys are rejected, default artifacts stay artifact-safe, and v1 remains Python-API-only.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: the manager selected `develop`; Phases 1-5 are merged, and the control checkout is clean at `963724a`.
- Retarget/rebase plan after predecessor merge: none needed because there is no predecessor.
- Branch cleanup constraints: this branch may be deleted after merge only if no successor branch has been created from it.

## Source Phase Summary

- Goal: make recipe artifact-safety limits explicit and close coverage gaps that do not require new recipe semantics.
- Required scope: record opaque Python recipe branching on unresolved resolver text as accepted debt; keep the existing recipe output-key guard for resolver-shaped keys; add missing tests for recipe manifest artifact-safe arguments and output hashes; add public compose/provenance coverage for explicit `../shared/foo.yaml` include escapes; assert exact include sibling local-customization path/kind/value payloads in public provenance/manifest records; optionally guard package metadata so v1-post still has no console script entry point.
- Required checkpoints: no recipe sandboxing, no recipe argument override syntax, no arbitrary trusted-Python branch proof, no CLI, no `_copy_`, no plugin/remote resolver, no persistence or runtime replay changes.

## Current Source And Harness Findings

- Recipe output-key protection already exists in `src/loom/config/recipes/expansion.py` through `_reject_resolver_shape_dependency(...)`, with focused unit/contract/integration coverage in `tests/unit/loom/config/recipes/test_expansion.py`, `tests/contracts/test_recipe_contract.py`, and `tests/integration/config/test_compose_recipes.py`.
- Recipe resolver-argument artifact-safety coverage already exists in `tests/integration/config/test_compose_recipes.py`, but Phase 6 should tighten gaps by asserting the same authored resolver argument facts through the composition manifest, provenance metadata, and fingerprint record metadata where those public artifacts expose recipe payloads.
- Public fingerprint coverage exists in `tests/integration/config/test_compose_config.py` and unit fingerprint tests, but Phase 6 should add an output-hash-sensitive recipe case if current assertions only prove the top-level digest changes and not that recipe manifest/output-hash facts participate in artifact-safe fingerprint records.
- Unit include resolution already covers explicit parent segments such as `../shared/optimizer.yaml`; Phase 6 should add public compose/provenance coverage for an actual sibling escape like `../shared/foo.yaml`, including target kind/path facts in emitted artifact metadata.
- Local customization records are produced by include expansion and exposed in provenance/manifest source facts, with redaction coverage for secret-like values. Phase 6 should add exact public assertions for sibling customization `path`, `kind`, and safe `value` payloads for a non-secret local customization.
- `pyproject.toml` currently has no `[project.scripts]` or console-script entry point. The optional metadata guard can live in package tests and should inspect installed/project metadata or the project table without adding packaging behavior.

## In-Scope Work

- Add a concise accepted-debt note to `docs/implementation-plans/implementation-plan-v1-post.md` metadata or Phase 6 completion notes when implementation finishes: Loom cannot prove arbitrary trusted Python recipes did not branch on unresolved resolver text, and this remains accepted v1-post debt.
- Preserve the current resolver-shaped recipe output-key guard and add regression coverage only if the existing guard is not already asserted at the right public level.
- Add focused tests proving recipe manifest arguments remain artifact-safe when recipe arguments contain unresolved resolver text: public `recipe_manifest`, provenance metadata, composition manifest payload, and fingerprint metadata should preserve the authored resolver expression and avoid resolved environment values.
- Add focused tests proving recipe manifest/output facts influence artifact-safe hashes. Prefer extending existing recipe fingerprint tests with a stable recipe that changes output shape or output facts while keeping the assertion tied to public fingerprint records, not a private digest helper.
- Add public compose/provenance coverage for an explicit relative include that escapes to a sibling directory, for example `configs/base.yaml` including `../shared/foo.yaml`.
- Add public provenance and manifest assertions for exact include sibling local-customization records: source path, include-site path, sibling path, kind such as `add` or `override`, and safe value payload. Keep redaction behavior intact for secret-like values.
- Add an optional package metadata test proving no console script entry point is exposed by v1-post.

## Out-of-Scope Work

- Recipe sandboxing or restrictions on trusted Python internals.
- Recipe argument override syntax.
- Proving arbitrary recipe functions did not branch on unresolved resolver text.
- CLI commands or console script entry points.
- `_copy_` support.
- Plugin or remote resolvers.
- Persistence changes, runtime replay, bundle/catalog behavior, or future Phase 7 final sweep work.

## Accepted Decisions To Preserve

- `loom.config` remains persistence-free.
- `loom.pipeline` must not depend on `loom.config` or manifests.
- `_copy_` remains unsupported in v1.
- Default artifacts are security-first and artifact-safe.
- Resolver outputs and raw source bytes are not persisted by default.
- V1 is Python-API-only; no CLI commands are added.
- Recipes remain trusted project Python; v1-post records opaque branching risk as debt rather than adding sandboxing or introspection.

## Assumptions

- The executor can satisfy Phase 6 through tests and documentation/metadata notes only. If a real behavior gap appears, keep the fix narrowly scoped to existing recipe/include artifact contracts.
- The current recipe output-key guard is the accepted behavior. Do not broaden it into general proof of recipe determinism or shape independence.
- Public artifact assertions should use `compose_config(...)` or `inspect_config_composition(...)` and serialized `to_dict()` payloads where available, so tests describe the public contract rather than private implementation structure.
- Package metadata guard is optional in the source phase. Add it if existing package test patterns make the assertion cheap and stable; otherwise record the deferral in the PR body.

## Scope Contract

The implementation must not add new public recipe semantics. A recipe that returns resolver-shaped output keys must still fail. A recipe that accepts resolver expressions as values may still execute as trusted Python; Loom records the authored resolver expression in artifact-safe recipe manifests and default fingerprints without persisting resolver outputs by default. Loom does not certify that arbitrary recipe internals avoided branching on the unresolved resolver string.

Explicit relative include targets with parent segments, such as `../shared/foo.yaml`, must remain allowed when they resolve within the configured/root-authorized include boundary. Public provenance and manifest records must make the include target kind and local sibling customization facts observable without leaking secret-like values.

## Design Impact

- Maintainability: locks residual-risk decisions into tests and plan metadata instead of leaving recipe artifact-safety expectations implicit.
- Extensibility: preserves the current recipe contract so future sandboxing, deterministic recipe certification, or recipe argument override syntax can be designed as additive v2 work.
- Security: keeps default artifacts artifact-safe and confirms recipe/include records do not persist resolver outputs or raw source bytes by default.
- Source-tree boundaries: keeps the phase inside config tests/docs and optional package metadata checks; no pipeline or persistence boundary changes are expected.
- Public contract impact: no new public API, schema, CLI, or protocol surface is intended.

## Future Compatibility

- Future deterministic recipe certification can revisit the accepted debt if users need stronger guarantees around recipe output shape and unresolved resolver text.
- Future recipe argument override syntax can build on existing recipe manifest records without changing this phase's artifact-safe defaults.
- Future CLI/package entry points should be introduced deliberately in v2 or a dedicated phase; this phase guards that v1-post remains Python-API-only.
- Future include provenance extensions should preserve the exact local-customization facts asserted here or add versioned/metadata-scoped fields.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add recipe sandboxing or inspect recipe source/bytecode for branching | Too broad and unreliable for trusted Python recipes; explicitly out of scope. |
| Reject all resolver expressions passed as recipe arguments | Conflicts with accepted artifact-safe behavior that preserves authored resolver expressions and resolves only runtime values for in-memory results. |
| Expand the output-key guard into arbitrary output-shape certification | Loom cannot prove arbitrary trusted Python internals without a new recipe execution model. |
| Add a CLI or console script for inspecting recipe artifacts | V1-post is Python-API-only; package metadata should remain entry-point-free. |
| Change persistence to prove artifact safety | Phase 5 already settled persistence boundaries; Phase 6 is coverage hardening only. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Opaque Python recipe branching on unresolved resolver text remains possible. | Recipes are trusted project code, and v1-post can guard resolver-shaped output keys but cannot prove arbitrary internals did not branch on string content. | Users need deterministic recipe shape certification, sandboxed recipe execution, or reproducibility guarantees for unreviewed third-party recipes. |
| Package metadata guard may remain test-only rather than a new packaging policy document. | The accepted v1 policy is already Python-API-only; adding a package test is enough for this phase. | A future CLI or entry point is proposed. |

## Reviewability

- Expected PR size and shape: small config-test/docs PR with focused coverage additions and one accepted-debt metadata note; product code changes should be minimal or absent.
- Files and areas to inspect: `docs/implementation-plans/implementation-plan-v1-post.md`, `tests/integration/config/test_compose_recipes.py`, `tests/integration/config/test_compose_provenance.py`, `tests/integration/config/test_compose_includes.py`, `tests/integration/config/test_compose_config.py`, `tests/unit/loom/config/recipes/test_expansion.py` only if needed, `tests/unit/loom/config/test_config_fingerprints.py` only if output-hash assertions fit better there, and package metadata tests under `tests/package/`.
- Scope-control checks: no recipe sandboxing, no CLI or `[project.scripts]`, no `_copy_`, no plugin/remote resolver support, no pipeline/run-store changes, no persistence changes, no broad config refactor, no future Phase 7 documentation sweep.

## Implementation Steps

1. Add the accepted-debt note for opaque recipe branching in the implementation plan or phase completion metadata.
2. Extend recipe artifact-safety tests to assert authored resolver arguments and absence of resolved environment values across public recipe manifest, provenance metadata, composition manifest, and fingerprint metadata.
3. Extend recipe fingerprint/output-hash coverage where current tests do not directly prove recipe output facts participate in artifact-safe fingerprint records.
4. Add a public compose/provenance test for a base config including `../shared/foo.yaml`, and assert explicit-relative target facts in provenance/manifest metadata.
5. Add exact public assertions for include sibling local-customization records, including path, kind, and safe value payload.
6. Add the optional package metadata guard for absent console script entry points if it fits existing package test patterns.
7. Run targeted config/package tests before handing off to PR preparation.

## Test Plan

### Package Suite

- Status: required if the metadata guard is added; otherwise explicitly deferred in the PR body.
- Expected paths: `tests/package/test_package_metadata.py` or an existing package metadata/API test file.
- Required assertions or deferral reason: assert v1-post exposes no console script entry point and `pyproject.toml` has no `[project.scripts]` entry. If packaging metadata is not readily inspectable in the existing harness, defer with the source-phase note that this guard was optional.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/recipes/test_expansion.py`, `tests/unit/loom/config/test_config_fingerprints.py`, and `tests/unit/loom/config/test_includes.py` only where integration coverage would duplicate too much setup.
- Required assertions or deferral reason: preserve resolver-shaped recipe output-key rejection; prove recipe output or recipe manifest facts alter artifact-safe fingerprint records where a focused unit test is the clearest level; keep explicit parent-segment include resolution behavior covered. Do not add unit tests that depend on private implementation details if a public integration test can assert the contract directly.

### Contract Suite

- Status: deferred.
- Expected paths: `tests/contracts/test_recipe_contract.py` and `tests/contracts/test_config_artifact_contract.py` only if implementation changes public contract fixtures.
- Required assertions or deferral reason: recipe protocol shape and config artifact schemas are unchanged. Existing contract coverage for resolver-shaped recipe output keys and artifact plain-data validation remains sufficient unless implementation touches those contracts.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_recipes.py`, `tests/integration/config/test_compose_provenance.py`, `tests/integration/config/test_compose_includes.py`, and `tests/integration/config/test_compose_config.py`.
- Required assertions or deferral reason: public compose/inspect coverage must prove recipe manifest arguments preserve authored resolver expressions and avoid resolved environment values in default artifacts; recipe output/manifest facts participate in artifact-safe hashes; explicit `../shared/foo.yaml` include escapes produce correct public provenance/manifest target facts; include sibling local customizations expose exact path/kind/value payloads.

### E2E Suite

- Status: deferred.
- Expected paths: none.
- Required assertions or deferral reason: this phase changes no full workflow behavior, runner behavior, CLI surface, or persistence path. Public config integration tests cover the affected behavior more directly.

### Opt-In Suites

- Status: required for config-extra rows touched by recipe/include compose coverage.
- Markers affected: config optional dependency markers.
- Required assertions or deferral reason: config-extra evidence must include the new recipe artifact-safety and include provenance tests. No opt-in runtime replay, raw source snapshot, plugin/remote resolver, or CLI suite is required.

## Risks

- Tests could assert private metadata layout too tightly. Prefer existing public `to_dict()` payloads and documented metadata keys already emitted by Phase 4/5.
- Recipe output-hash coverage could accidentally depend on environment-resolved values. Keep authored config stable and assert default artifacts remain env-free.
- Include sibling customization coverage could duplicate redaction tests without checking exact safe values. Use a non-secret value for exact payload assertions and leave existing secret redaction coverage intact.
- Package metadata checks can be brittle if they require building/installing the package. Prefer a stable project metadata or importlib metadata pattern already used by the package suite.
- Any need to change persistence, CLI, or public recipe semantics is a scope blocker and should stop implementation.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_recipes.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_provenance.py tests/integration/config/test_compose_includes.py tests/integration/config/test_compose_config.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/recipes/test_expansion.py tests/unit/loom/config/test_config_fingerprints.py tests/unit/loom/config/test_includes.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/package
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: accepted-debt metadata note first, recipe artifact/hash tests second, include/provenance tests third, optional package metadata guard last.
- Decisions the executor must not revisit: no recipe sandboxing, no recipe argument override syntax, no arbitrary recipe branch proof, no CLI, no `_copy_`, no plugin/remote resolver, no persistence changes, no pipeline dependency on config, no raw source or resolver output persistence by default.
- Conditions that require stopping for the manager: implementation appears to require changing public recipe semantics, altering provenance/manifest schemas, changing pipeline/run-store persistence, adding a console script, broadening resolver support, or implementing Phase 7 final sweep docs.
- Fast-path notes: no refinement pass is needed unless targeted validation reveals missing coverage that cannot be fixed locally within this phase.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed on the fast path; unused.
- PR review: unused.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed with `plan: add phase execution plan`.
- Executor: workflow-authorized fallback executor; completed on 2026-05-06 in
  `/home/samcantrill/work/loom-worktrees/v1-post-recipe-coverage`.
- Implementation summary: added public coverage for artifact-safe recipe
  resolver arguments across recipe manifests, provenance metadata, composition
  manifests, and fingerprint metadata; tightened public fingerprint assertions
  so recipe argument and output-hash facts drive artifact-safe mismatch records;
  added public provenance/manifest coverage for `../shared/foo.yaml` explicit
  relative include escapes and exact non-secret sibling local-customization
  path/kind/value payloads; added a package metadata guard that v1-post exposes
  no console script entry points.
- Accepted debt: opaque Python recipe branching on unresolved resolver text
  remains accepted v1-post debt. Loom preserves authored resolver expressions in
  artifact-safe records and rejects resolver-shaped output keys, but does not
  prove arbitrary trusted recipe internals avoided branching on unresolved
  resolver text.
- Commits:
  - `bab118b` - `test: harden recipe artifact coverage`
  - `docs: record phase 6 implementation notes`
- Scope control: product code was unchanged; no recipe sandboxing, recipe
  argument override syntax, CLI, console script entry point, `_copy_`,
  plugin/remote resolver, persistence, runtime replay, or Phase 7 work was
  added. Public contract decisions were not changed.
- Tests added or updated:
  - Package: `tests/package/test_import.py` asserts `pyproject.toml` exposes no
    `[project.scripts]` or GUI script entry points.
  - Unit: no unit files changed; existing unit recipe output-key, fingerprint,
    and include coverage was run as phase evidence.
  - Contract: deferred because recipe protocol shape and config artifact schemas
    were unchanged.
  - Integration: `tests/integration/config/test_compose_recipes.py`,
    `tests/integration/config/test_compose_config.py`, and
    `tests/integration/config/test_compose_provenance.py` add the required
    public artifact-safe recipe, fingerprint, include escape, and local
    customization assertions.
  - E2E: deferred because this phase changed no full workflow, runner,
    persistence, or CLI behavior.
  - Opt-in: config-extra integration coverage was run with `--extra config`.
- Validation run:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_config.py tests/integration/config/test_compose_provenance.py`
    passed, `31 passed`.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/package` passed,
    `43 passed`.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_includes.py tests/unit/loom/config/recipes/test_expansion.py tests/unit/loom/config/test_config_fingerprints.py tests/unit/loom/config/test_includes.py`
    passed, `75 passed`.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run ruff check tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_config.py tests/integration/config/test_compose_provenance.py tests/package/test_import.py`
    passed.
  - `make validate-pr` passed with Ruff, Pyright, default harness
    `448 passed, 11 skipped`, config-extra harness `363 passed, 455 deselected`,
    and `uv build`.
- PR-preparation validation:
  - `make validate-pr` passed with Ruff, Pyright `0 errors, 0 warnings, 0
    informations`, default harness `448 passed, 11 skipped`, config-extra
    harness `363 passed, 455 deselected`, and `uv build`.
  - `make test-summary` passed and wrote `build/test-summary.md`: overall
    `818 passed, 9 skipped, 455 deselected` across package, unit, contract,
    integration, e2e, and config-extra suites.
- PR body artifact: `docs/phases/v1-post-recipe-coverage-pr-body.md`.
- PR preparation status: fast-path draft completed; refine pass not needed.
  Branch, stack predecessor (`none`), target branch (`develop`), merge
  eligibility, and scope were confirmed before PR creation.
- PR: https://github.com/samcantrill/loom/pull/55
- GitHub verification:
  - `gh pr view 55 --json baseRefName,headRefName,state,url` returned
    `baseRefName=develop`, `headRefName=codex/v1-post-recipe-coverage`,
    `state=OPEN`, `url=https://github.com/samcantrill/loom/pull/55`.
  - `gh pr checks 55` reported GitHub `checks` completed successfully.
- Known issues or blockers: none.
- Refiner handoff: no failing or unavailable checks. Phase implementation
  refinement remains unused on the fast path.
