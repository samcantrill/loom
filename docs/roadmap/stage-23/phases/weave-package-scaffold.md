# Phase 2 Execution Plan: Weave Package Scaffold

## Metadata

- Status: refined phase execution plan; ready for implementation
- Feature focus: Config Extraction
- PR title: `Config Extraction - Phase 2: Weave Package Scaffold`
- Branch: `codex/weave-package-scaffold`
- Worktree: `/home/samcantrill/work/loom-worktrees/weave-package-scaffold`
- Phase execution plan path: `docs/roadmap/stage-23/phases/weave-package-scaffold.md`
- Full plan: `docs/roadmap/stage-23/implementation-plan.md`
- Planning artifact: `docs/roadmap/stage-23/planning.md`
- Source phase: Stage 23 Phase 2, Package Scaffold And Config Helper Foundations
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible only after automated review, required validation, and CI pass while targeting `develop`; phase agents must not merge.
- Workflow path: expanded path
- Successor dependency notes: Phase 3 should branch from updated `develop` after this phase merges. If GitHub-side blockers leave this PR open, Phase 3 may stack on `codex/weave-package-scaffold` only after this phase is opened or prepared, validated, and recorded as `pr_open`.
- Plan quality gate: passed on 2026-05-20 in the implementation plan, with no blocking findings after confirmation review.
- Plan quality gate loop budget: consumed and passed before this phase plan; do not rerun unless the manager explicitly reopens the stage plan.
- Draft pass: completed in this artifact.
- Refine pass: completed in this artifact; expanded-path planning budget is consumed for this phase unless the manager explicitly reopens planning.
- Setup limitations: branch was created from local `develop` at `ab4855c`; no network fetch was performed. Initial worktree creation needed sandbox escalation because git refs in the control checkout were read-only to the sandbox.
- Blockers: none; implementation must stop if the package cannot build or typecheck without heavyweight tooling, if `weave` must import `loom` to provide the helper foundations, or if root validation requires changing config semantics.

## Objective

Add the initial independently importable `weave` package scaffold and the config-owned helper foundations needed before the config implementation is ported, without changing Loom runtime behavior, Loom adapter imports, or the existing `src/loom/config` implementation.

## Full-Plan Context

Phase 1 has merged the golden artifact baseline and current-state import-boundary inventory. Phase 2 creates the movable package shell and small helper surfaces that later phases will use: Phase 3 ports the config implementation into `weave`, Phase 4 hard-switches Loom adapters and removes `src/loom/config`, Phase 5 relocates tests/examples and finalizes package-local validation, and Phase 6 updates docs and final validation metadata. This phase must not port composition modules, rewrite user import paths, remove `src/loom/config`, or make Loom runtime internals depend on `weave`.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1 is recorded as merged in the implementation plan and local `develop` includes the Phase 1 metadata commit `ab4855c`.
- Why this base branch is correct: the user assigned Phase 2 from current `develop`, with no stack predecessor, after Phase 1 merged.
- Retarget/rebase plan after predecessor merge: not applicable for this root phase.
- Branch cleanup constraints: branch may be deleted after the phase PR is merged and no successor branch depends on it; keep it if a stacked successor is created before merge.

## Source Phase Summary

- Goal: add an independently importable `weave` package shell and the duplicated config-owned helper foundations required before implementation porting.
- Required scope: package metadata, source package skeleton, `py.typed`, version metadata, config-owned plain-data/stable-JSON/digest/error helpers, package-local helper/import tests, initial Makefile and tool configuration for `test-weave`, `build-weave`, and `validate-weave`.
- Required checkpoints: `import weave` succeeds without importing `loom`; helper APIs are package-owned and do not become Loom runtime dependencies; root Loom behavior and current `loom.config` baseline remain unchanged.
- Acceptance criteria: package import/build/helper tests pass; package-local validation target exists; root import-boundary tests and `make validate-pr` remain green or any inability to run them is recorded by executor and PR preparer.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: root `pyproject.toml` defines only the `loom` distribution, `src/loom`, the `loom[config]` optional dependency group, root Ruff/Pyright/Pytest coverage configuration, and root build metadata. `Makefile` includes `make/dev/*.mk` and `make/test/*.mk`; current validation targets are root-oriented and do not yet know about `packages/weave`.
- Existing helper behavior: Loom-owned helpers live in `src/loom/serialization/plain.py`, `src/loom/serialization/json.py`, `src/loom/fingerprints.py`, `src/loom/errors.py`, and config-specific structured errors in `src/loom/config/errors.py`. The `weave` helpers should be equivalent only where config artifacts need them, not a generic utility package for Loom.
- Existing tests or harness behavior: package/import-boundary tests live in `tests/package/test_import_boundaries.py`; config API tests currently assert `loom.config` exports under optional dependency markers; the test harness suite map currently names root suites only and writes root suite summaries.
- Import-boundary or dependency constraints: `weave` must import no `loom`; `import loom`, `import loom.pipeline`, `import loom.serialization`, `import loom.plugins`, and other core runtime imports must not import `weave`; Phase 2 may add package-local tests that run against the new package but must not force Loom adapters to consume it yet.

## In-Scope Work

- Create `packages/weave/pyproject.toml` with distribution name `weave`, Python support aligned with Loom, package-local dependencies for config-owned helpers and later config implementation needs, and build metadata consistent with existing repository tooling. If root workspace or lock metadata must change for the new targets to run, keep that change limited to discovering/building the local package; do not make root `loom` depend on `weave` until Phase 4.
- Create `packages/weave/src/weave/__init__.py`, `packages/weave/src/weave/py.typed`, and package-local version metadata initially aligned with the repository version while not reading `loom.__version__`.
- Add package-owned helper modules such as `weave.plain`, `weave.json`, `weave.digests`, and `weave.errors`, or equivalent names that keep config ownership clear.
- Add focused package-local tests under `packages/weave/tests/` for import behavior, version/typing marker, plain-data validation and normalization, stable JSON bytes/text, digest formatting/hash behavior, and structured config error payloads. These tests should execute against the package-local source or installed package, not by relying on root `tests` path tricks that would hide packaging problems.
- Add initial repository tooling so `make test-weave`, `make build-weave`, and `make validate-weave` run package-local checks without moving the root config suite.
- Extend root import-boundary coverage only as needed to prove `weave` imports no `loom` and core Loom imports do not import `weave`; use subprocess isolation where useful so module state from a prior root import cannot hide an eager import.
- Keep root Loom behavior and existing `loom.config` tests unchanged except for non-behavioral tooling needed to coexist with the new package tree.

## Out-of-Scope Work

- Porting config composition, overlays, includes, recipes, target instantiation, redaction, provenance, source artifacts, raw source snapshots, or config fingerprint implementation into `weave`.
- Updating Loom CLI, queue, diagnostics, plugin, or sweep adapter paths to import `weave`.
- Removing or renaming `src/loom/config`.
- Adding a `loom.config` compatibility shim or changing the confirmed hard-switch policy.
- Moving root config tests or authoring examples into `packages/weave`.
- Changing config semantics, golden artifact shapes, recipe plugin entry-point ownership, or CLI diagnostics.
- Adding placeholder public composition APIs such as `compose_config`, `RecipeCatalog`, or `instantiate` before Phase 3 implements them for real.
- Creating a PR body, opening a PR, or updating implementation-plan phase status.

## Assumptions

- The package can use the same Python version support and lightweight build backend family as the root project unless implementation evidence shows a local monorepo tooling conflict.
- Phase 2 helper modules may duplicate small Loom helper behavior because the planning artifact explicitly accepts package-owned duplication.
- Package-local tests can be introduced without requiring the Phase 5 summary tooling split to be complete.
- Existing optional config dependencies remain the dependency families for the future package; this phase should not broaden dependencies beyond OmegaConf, Pydantic, and PyYAML unless a concrete packaging reason is recorded.

## Scope Contract

This phase introduces a new package boundary, not new config semantics. Public behavior in scope is limited to an importable `weave` package, package metadata, a typing marker, package-local version metadata, and config-owned helper APIs that later config records can use. The helper APIs may mirror Loom behavior where artifact compatibility requires it, but Loom runtime code must not import these helpers for runtime-owned serialization, fingerprinting, or error behavior.

`weave.__init__` should expose only real Phase 2 surfaces. Do not add stubs for future config composition APIs such as `compose_config`, `compose_config_with_catalog`, `RecipeCatalog`, `inspect_config_composition`, `instantiate`, or `check_config_targets`; those APIs become real in Phase 3.

`weave.plain` or its equivalent should define package-owned `PlainData` typing and validation/normalization helpers with the config artifact semantics needed by current records: string mapping keys, finite floats, tuple-to-list normalization, `to_dict()` object conversion when supported, and explicit rejection of set-like, bytes-like, path, datetime, mapping-proxy, callable, and otherwise non-plain values. It must raise package-owned errors rather than Loom errors.

`weave.json` or its equivalent should provide stable JSON behavior compatible with config artifact hashing: sorted keys, compact separators for stable bytes, UTF-8 bytes output, no NaN/Infinity, and pretty JSON with deterministic sort behavior where implemented.

`weave.digests` or its equivalent should provide package-owned digest aliases and helpers for canonical `sha256:<hex>` formatting, validation, constant-time comparison, byte/text/plain-data hashing, and mapping hashing. It must not import `loom.ids`, `loom.fingerprints`, or `loom.serialization`.

`weave.errors` should define config-owned error roots and structured context behavior without inheriting from or importing Loom error roots. Exact class names may follow the current config error names where they are clearly config-owned, but the executor must avoid moving the full config error hierarchy if doing so pulls in composition-specific behavior from Phase 3.

Package tooling changes must preserve the current root validation contract. New Make targets can be initial and package-scoped, but final repository-wide summary integration belongs to Phase 5 unless a small harness addition is needed for `test-weave`. Prefer package-specific commands such as building or testing the `packages/weave` project directly over making package tests pass only because the repository root is on `PYTHONPATH`.

## Design Impact

- Maintainability: establishes package ownership before code movement, reducing Phase 3 import and dependency churn.
- Extensibility: keeps `packages/weave` movable as a future standalone repository unit with source, tests, typing marker, and package metadata colocated.
- Domain neutrality: helpers and tests should use neutral structured data and synthetic errors only.
- Source-tree boundaries: `packages/weave` becomes the config package root; Loom runtime helper modules remain under `src/loom` and must not depend on `weave`.

## Future Compatibility

- Phase 3 can port config implementation against the package-owned helper surface without importing Loom runtime helpers.
- Phase 4 can make root `loom` depend on the local `weave` package after the package exists and has build evidence.
- Phase 5 can expand package-local tests/examples and suite summaries without reworking the package skeleton.
- A future separate `weave` repository should be able to lift `packages/weave` with minimal dependency on root Loom tooling.
- If package metadata or workspace wiring cannot support local validation without broad tooling churn, stop and record the specific blocker instead of inventing a heavyweight monorepo framework.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Wait for Phase 3 to create `packages/weave` while porting implementation | Combining scaffold, helpers, and implementation movement would make import-boundary and packaging failures harder to isolate. |
| Move Loom runtime helper modules wholesale into `weave` | Violates the confirmed ownership split and would make Loom runtime internals depend on the config package for runtime behavior. |
| Add a shared core package for helper behavior | Explicitly out of scope unless duplicated helpers grow beyond small package-owned implementations. |
| Wire Loom adapters to `weave` immediately | Adapter rewiring and `src/loom/config` removal belong to Phase 4 after the package implementation exists. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Initial duplicated helper behavior between Loom and `weave` | Clean package ownership is required before moving config implementation. | Helper behavior grows broad, golden fixtures expose drift, or a future separate release cadence makes duplication painful. |
| Initial package validation targets may not yet be part of final `test-summary` output | Phase 5 owns full test/example relocation and summary evidence. | PR preparation cannot report package evidence clearly, or Phase 5 would need to redesign targets created here. |
| `weave` package metadata is local-workspace oriented, not publication-proven | Publishing is explicitly deferred for Stage 23. | A future publication step or isolated install smoke resolves an unintended external `weave` package or naming conflict. |

## Reviewability

- Expected PR size and shape: focused package-scaffold and helper-foundation PR, with new `packages/weave` files, narrow Make/tooling updates, and targeted import-boundary tests.
- Files and areas to inspect: `packages/weave/pyproject.toml`, `packages/weave/src/weave/**`, `packages/weave/tests/**`, Makefile fragments, root tool configuration in `pyproject.toml`, and root import-boundary tests.
- Scope-control checks: no implementation port from `src/loom/config`, no Loom adapter import rewrites, no deletion of `src/loom/config`, no authoring example relocation, and no golden fixture schema updates.

## Implementation Steps

1. Add the package skeleton, metadata, typing marker, and version surface under `packages/weave`.
2. Add small config-owned helper modules for plain data, stable JSON, digests/fingerprints, and structured config errors, keeping them free of Loom imports.
3. Add package-local tests for import behavior and helper contracts, using neutral data and no composition implementation.
4. Wire initial `test-weave`, `build-weave`, and `validate-weave` targets using existing local tooling patterns, with minimal Pytest/Ruff/Pyright configuration needed for `packages/weave`.
5. Extend import-boundary tests to prove `weave` imports no `loom` and core Loom imports still avoid `weave`.
6. Run targeted package/root validation and stop on heavyweight tooling, dependency, or import-boundary blockers.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `packages/weave/tests/` and root package/import-boundary tests as needed.
- Required assertions or deferral reason: verify `import weave`, version metadata, `py.typed`, package metadata, helper contracts, `weave` imports no `loom`, and core Loom imports do not import `weave`.

### Unit Suite

- Status: required
- Expected paths: `packages/weave/tests/test_plain.py`, `packages/weave/tests/test_json.py`, `packages/weave/tests/test_digests.py`, `packages/weave/tests/test_errors.py`, or equivalent package-local helper tests.
- Required assertions or deferral reason: cover finite plain-data validation, mapping-key validation, tuple-to-list normalization, immutable/mutable round trips where implemented, stable JSON sorting and non-finite rejection, digest canonicalization and comparison, hash bytes/text/plain data behavior, and structured error context serialization.

### Contract Suite

- Status: required
- Expected paths: `packages/weave/tests/` helper contract tests and `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: assert package boundary contracts rather than config composition semantics; Phase 1 golden artifact contract remains rooted in `loom.config` and should continue passing through `make validate-pr`.

### Integration Suite

- Status: deferred for new behavior
- Expected paths: existing root `tests/integration/**`
- Required assertions or deferral reason: no Loom adapter or workflow behavior changes are in scope; existing integration coverage remains part of `make validate-pr`.

### E2E Suite

- Status: deferred for new behavior
- Expected paths: existing root `tests/e2e/**`
- Required assertions or deferral reason: no CLI hard-switch or end-to-end authored-config workflow changes are in scope; existing e2e coverage remains indirect through final repository validation.

### Opt-In Suites

- Status: required only for package checks that need optional config dependencies; otherwise deferred
- Markers affected: package-local marker strategy may mirror `package`, `unit`, and `optional_dependency`; root `config-extra` should remain unchanged unless dependency metadata requires a narrow update.
- Required assertions or deferral reason: the new helper tests should avoid optional config dependencies where practical; package metadata may declare future config dependencies, but composition-dependent tests wait for Phase 3.

## Risks

- Package metadata or workspace configuration may require more root tooling changes than expected.
- Helper duplication can drift if tests only assert trivial behavior.
- Import-boundary tests could accidentally force the future hard switch early.
- Build/typecheck wiring can become too broad if it tries to solve Phase 5 summary and example validation ahead of time.
- Introducing `weave` can mask accidental imports if tests run in-process after `loom` has already been imported.
- Publishing-oriented package-name availability for `weave` is intentionally unverified in this phase; isolated local build/import evidence is enough unless the local build resolves an external package unexpectedly.

## Validation Commands

Targeted development commands:

```sh
make test-weave
make build-weave
make validate-weave
uv run pytest tests/package/test_import_boundaries.py
uv run pyright packages/weave
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: package skeleton and metadata; helper modules; package-local helper tests; Make/tooling targets; root import-boundary checks.
- Tests to run with each slice: package import/helper tests after skeleton and helper changes, `make test-weave` after package-local tests, `make build-weave` after metadata changes, import-boundary tests after root boundary edits, and `make validate-weave` before final PR preparation.
- Decisions the executor must not revisit: hard switch with no `loom.config` shim, no adapter rewiring in Phase 2, no config implementation port in Phase 2, no placeholder public composition APIs, no shared core package, no Loom runtime imports from `weave`, and no broad validation harness redesign.
- Conditions that require stopping for the manager: package build requires heavyweight tooling, `weave` cannot be imported or built without importing Loom, helper behavior must become broader than config-owned foundations, package metadata cannot coexist with root `uv`/build tooling, or root validation requires changing config semantics.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in commit `ee1710c`.
- Refine plan: completed in this artifact.
- Final phase execution plan: ready for implementation after this refinement.
- Implementation summary: Added `packages/weave` scaffold with `pyproject.toml`, `src/weave` package, `py.typed`, version metadata, and helper modules (`plain`, `json`, `digests`, `errors`) without importing `loom`; added package-local tests for imports, plain-data behavior, stable JSON, digests, and structured config errors; added make targets for `test-weave`, `build-weave`, and `validate-weave`; extended import-boundary tests to assert weave boundary behavior.
- Implementation validation:
  - `make test-weave` → PASS (22 passed).
  - `make build-weave` → PASS (`weave-0.1.0` source/wheel artifacts produced).
  - `make validate-weave` → PASS (ruff, pyright, tests).
  - `uv run pytest tests/package/test_import_boundaries.py` → PASS (60 passed).
  - `uv run pyright packages/weave` → BLOCKED by offline lock/cache/environment (DNS/build env conflict); reran package-local equivalent as `cd packages/weave && PYTHONPATH=src pyright .` → PASS.
- Refinement summary: No phase-plan scope changes required; all changes remained in the scaffold and boundary scope.
- Blocker-resolution summary: No blocking scope issues for code movement; non-blocking tool-environment limitations were recorded around `uv run` for pyright with workspace-level package resolution.
- PR preparation: Not created for this phase pass.
- Stack maintenance: branch created from local `develop` at `ab4855c`; no predecessor.
- Remaining blockers: none.
