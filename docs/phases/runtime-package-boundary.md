# Phase 1 Execution Plan: Runtime Package Boundary

## Metadata

- Status: refined phase execution plan
- Feature focus: Runtime Options
- PR title: `Runtime Options - Phase 1: Runtime Package Boundary`
- Branch: `codex/runtime-package-boundary`
- Worktree: `/home/samcantrill/work/loom-worktrees/runtime-package-boundary`
- Phase execution plan path: `docs/phases/runtime-package-boundary.md`
- Full plan: `docs/implementation-plans/implementation-plan-v4.md`
- Source phase: Phase 1 - Runtime Package Boundary
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop`, automated review passes, and validation/CI pass.
- Workflow path: expanded path because this is an import/source-tree boundary phase.
- Successor dependency notes: Phase 2 and later v4 runtime-options phases may build on this branch after its PR is open or prepared, validated, and recorded as `pr_open`; no predecessor branch is required for this root phase.
- Plan quality gate: passed on 2026-05-07 after initial `loom_plan_reviewer` review, one refinement pass, and confirmation review.
- Plan quality gate loop budget: initial review used, refinement used, confirmation review used; do not reopen unless the manager reports a new blocker.
- Draft pass: completed by `loom_phase_planner` on 2026-05-07.
- Refine pass: completed by `loom_phase_planner` on 2026-05-07; this pass refined scope boundaries, import-light test obligations, documentation obligations, and budget/status records without consuming implementation refinement or PR-review budget.
- Setup limitations: sandboxed `gh auth status` reported an invalid token, `gh auth setup-git` could not write `/home/samcantrill/.gitconfig`, and `git fetch`/`git worktree add` could not write Git metadata. Approved escalation verified GitHub auth, ran `gh auth setup-git`, fetched `origin`, and created this worktree. Local `develop` and `origin/develop` both resolved to `f461c017f2512c9efdbfede303dd773810140657` before branching.
- Blockers: none known.

## Objective

Convert the existing local runtime request module into an import-light runtime package with a stable public facade, preserving current runtime/resource behavior while documenting the package and executor descriptor boundary that later v4 phases will populate.

## Full-Plan Context

This is the first v4 runtime-options phase. It creates the source-tree boundary that later phases use for typed resources, `RunOptions`, profiles, environment requests, executor descriptors, validation, registry, serialization, preflight, and runtime metadata. The phase must not add those models early; its value is keeping public imports stable while giving future runtime modules a clear package home and import direction.

Future-phase work remains out of scope: Phase 2 owns the hard resource schema refactor, Phase 3 owns `RunOptions` and environment models, later phases own profiles, descriptor/capability records, preflight integration, `runtime.json`, and CLI/config mapping.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: this is the first v4 phase, all earlier roadmap work needed for v4 is merged into `develop`, and the v4 implementation plan quality gate has passed on `develop`.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete after this phase PR is merged only if no successor phase branch depends on `codex/runtime-package-boundary`.

## Source Phase Summary

- Goal: establish the split runtime package/facade and source-structure boundary before adding new runtime models.
- Required scope: convert `loom.pipeline.runtime` from a module into an import-light package with a stable public facade; preserve existing `RuntimeRequest`, `RuntimeKind`, and `parse_runtime_request` public imports; preserve the current package-level re-exports from `loom.pipeline`; add only package scaffolding needed by later phases; update package imports and `__all__`; update `docs/structure.md` for the runtime package and executor descriptor boundary.
- Required checkpoints: public runtime imports remain stable and cheap; existing behavior is unchanged; docs describe the runtime package boundary and import direction; forbidden layers are not imported through runtime; no `RunOptions`, new resource schema, executor descriptor behavior, config/CLI mapping, preflight integration, or runtime metadata behavior appears in the diff.
- Acceptance criteria: public runtime imports remain stable and cheap after the package split; existing runtime/resource behavior and tests remain unchanged; `docs/structure.md` describes the new package boundary and import direction; runtime package imports do not import CLI, diagnostics, executor implementations, plugins, or optional backends.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/runtime.py` currently owns `RUNTIME_SCHEMA_VERSION`, `RuntimeKind`, `RuntimeRequest`, `parse_runtime_request`, and runtime validation helpers; `src/loom/pipeline/__init__.py` imports and re-exports the public runtime names; `src/loom/pipeline/resources.py` remains a sibling module; `src/loom/pipeline/specs.py` and tests consume existing resource/runtime behavior.
- Existing tests or harness behavior: `tests/package/test_import_boundaries.py` already has runtime/resource import-light coverage that should be strengthened for the new runtime package facade; package pipeline exports are covered by `tests/package/test_pipeline_api.py` and public API tests; runtime/resource behavior is covered by `tests/unit/loom/pipeline/test_runtime_resources.py`; local pipeline behavior is covered by integration and e2e suites.
- Import-boundary or dependency constraints: runtime models currently depend only on serialization helpers, pipeline errors, and resources. The package facade must preserve that light dependency profile and must not import `loom.cli`, `loom.diagnostics`, `loom.pipeline.execution`, `loom.pipeline.executors`, `loom.plugins`, optional config dependencies, optional executor backends, or project packages.

## In-Scope Work

- Replace the single `src/loom/pipeline/runtime.py` module with a package at `src/loom/pipeline/runtime/` while preserving `import loom.pipeline.runtime` and `from loom.pipeline.runtime import RuntimeRequest, RuntimeKind, parse_runtime_request`.
- Move the existing runtime request implementation into a focused private package leaf, with `models.py` preferred unless the local source pattern points to a clearer name. Tests and docs must lock the public facade, not the private leaf path.
- Keep the runtime package facade import-light with explicit `__all__` exports for existing public names and only package scaffolding needed by later v4 phases.
- Update `src/loom/pipeline/__init__.py` only as needed to preserve current package-level exports.
- Add or strengthen package tests for runtime facade public exports, import-path compatibility, and forbidden import boundaries.
- Preserve existing `RuntimeRequest`, `RuntimeKind`, `parse_runtime_request`, `RUNTIME_SCHEMA_VERSION`, runtime validation errors, serialization shape, and resource behavior.
- Update `docs/structure.md` to show `runtime/` as the package boundary and to describe the future executor descriptor boundary/import direction without implementing descriptors.

## Out-of-Scope Work

- Resource schema refactor or typed `ResourceEntry` work.
- `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, runtime profiles, environment models, executor descriptors, descriptor registries, capability validation, or preflight checks.
- `runtime.json`, run-store metadata persistence, runner request rewiring, stage execution request changes, or local executor behavior changes.
- CLI/config runtime mapping, new CLI flags, config schema changes, or profile selection.
- Optional backend imports, plugin discovery, subprocess/SLURM/container implementation, or adapter schema interpretation.
- Placeholder modules that have no immediate import contract or near-term implementation use.
- Any new public import names beyond preserving current runtime names and current `loom.pipeline` re-exports.

## Assumptions

- The existing runtime request implementation can be moved with no behavior changes and no public serialization changes.
- A package facade plus one implementation leaf is enough scaffolding for this phase; future submodules should be added only when later phases introduce real behavior.
- Tests should lock the import contract and forbidden imports rather than over-specify the internal leaf module name.
- `docs/structure.md` may describe future descriptor ownership and import direction, but implementation of descriptors belongs to a later phase.

## Scope Contract

No public runtime behavior changes are in scope. The executor must preserve the current public import contract:

```python
import loom.pipeline.runtime
from loom.pipeline.runtime import RuntimeKind, RuntimeRequest, parse_runtime_request
from loom.pipeline import RuntimeKind, RuntimeRequest, parse_runtime_request
```

`RuntimeRequest.to_dict()`/`from_dict()`, `parse_runtime_request(None)`, local-only `RuntimeKind.LOCAL`, deferred runtime field rejection, schema-version behavior, error type, and `ResourceRequest` handling must remain unchanged. The package split may change private file placement, but callers must not need to know whether runtime is backed by a module or package.

The runtime package facade must remain a lower-layer model boundary. Importing `loom.pipeline.runtime` may import serialization helpers, pipeline errors, and resources, but must not import CLI, diagnostics, execution runners, executor implementations, plugin discovery, optional config dependencies, optional executor backends, or project code. If an implementation decision would require those imports, stop for the manager.

`docs/structure.md` should describe that future runtime option, profile, environment, validation, registry, descriptor, and serialization modules live under the runtime package when phases add real behavior. It should also describe that descriptor records are import-light metadata owned below executor implementations; concrete executor implementations and plugin discovery must depend on descriptors, not the other way around. The docs update must use future-tense or boundary language for descriptors because descriptor records, registries, and capability behavior are not implemented in Phase 1.

The following future-phase names or behaviors must not be introduced in product code, tests as implemented behavior, or public exports during Phase 1: `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, `ResourceEntry`, typed resource entry parsing, old-resource-field migration, runtime profiles, environment request models, descriptor records, descriptor registries, capability diagnostics, preflight check IDs, `runtime.json`, CLI runtime flags, or config runtime/profile schema handling.

## Design Impact

- Maintainability: creates a focused runtime package before v4 adds multiple model and validation areas, reducing pressure to grow a single broad `runtime.py` file.
- Extensibility: leaves room for later `options`, `profiles`, `environment`, `registry`, `validation`, descriptor, and serialization modules while preserving the facade as the stable public import.
- Domain neutrality: only generic invocation/runtime boundaries are documented; no scheduler, container, project, or domain-specific behavior is introduced.
- Source-tree boundaries: runtime remains below planning/execution/diagnostics/CLI presentation and sibling to resources; executor descriptors are documented as import-light metadata, not concrete backend implementations.

## Future Compatibility

- Phase 2 can update `RuntimeRequest.resources` behavior through the resource model without also changing the runtime package structure.
- Phase 3 can add public runtime option and environment models under the package facade without breaking current runtime request imports.
- Later descriptor/capability phases can add import-light descriptor records without causing runtime package imports to load executor implementations or plugins.
- Later CLI/config/preflight phases can consume the runtime facade as a stable lower-layer API instead of importing internal files.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep `loom.pipeline.runtime` as one broad module while adding v4 models | The implementation plan identifies runtime as likely to grow several ownership areas; delaying the package split increases churn and review risk later. |
| Add all future runtime submodule placeholders now | Empty placeholders add public surface and maintenance noise without behavior; the phase brief allows only scaffolding needed by later phases. |
| Move runtime request models into resources or execution | Runtime request compatibility and future invocation options need a runtime-owned facade; resources and execution have separate ownership. |
| Implement executor descriptors in Phase 1 | Descriptors are explicitly out of scope; this phase only documents their boundary to prevent import-direction drift. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Runtime package initially contains mostly the existing runtime request foundation | The phase intentionally establishes structure before behavior while keeping the diff small. | Revisit in Phase 3 when `RunOptions` and related runtime models are added. |
| Executor descriptor boundary is documented before descriptor records exist | Import direction needs to be clear before descriptor implementation, but behavior belongs to a later phase. | Revisit in the descriptor/capability phase when concrete public names and tests are added. |

## Reviewability

- Expected PR size and shape: small package-boundary and documentation diff with targeted package/unit tests; no behavior or schema changes.
- Files and areas to inspect: `src/loom/pipeline/runtime/`, removal or replacement of `src/loom/pipeline/runtime.py`, `src/loom/pipeline/__init__.py`, `docs/structure.md`, `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_api.py`, and `tests/unit/loom/pipeline/test_runtime_resources.py`.
- Scope-control checks: no `RunOptions`, profiles, environment models, typed resource entries, descriptors, registries, preflight checks, CLI/config mapping, run-store metadata, executor implementation imports, plugin discovery, optional backend imports, or behavior-changing resource/runtime validation.

## Implementation Steps

1. Convert `src/loom/pipeline/runtime.py` into a package while moving the existing runtime request implementation into a focused leaf and preserving facade exports.
2. Update `src/loom/pipeline/__init__.py` and package `__all__` definitions so existing public imports stay stable and cheap.
3. Add or adjust package import-boundary tests that import the runtime facade in a fresh interpreter, exercise the preserved public imports, and assert forbidden layers are not loaded.
4. Add or adjust unit/package compatibility tests for `RuntimeRequest`, `RuntimeKind`, `parse_runtime_request`, and package-level pipeline re-exports without asserting the private implementation leaf path.
5. Update `docs/structure.md` to document the runtime package layout, import direction, and future executor descriptor boundary without claiming descriptor implementation exists.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_api.py`, and `tests/package/test_public_api.py` only if public export coverage requires adjustment.
- Required assertions or deferral reason: `import loom.pipeline.runtime` and `from loom.pipeline.runtime import RuntimeRequest, RuntimeKind, parse_runtime_request` work after the package split; `from loom.pipeline import RuntimeRequest, RuntimeKind, parse_runtime_request` remains stable; runtime facade imports do not load `loom.cli`, `loom.diagnostics`, `loom.pipeline.execution`, `loom.pipeline.executors`, `loom.plugins`, optional config dependencies such as `yaml`, `omegaconf`, or `pydantic`, optional backends, or project modules. Add the runtime-facade subprocess check directly to `tests/package/test_import_boundaries.py` so import-light behavior is tested in a fresh interpreter.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/test_runtime_resources.py`.
- Required assertions or deferral reason: existing runtime request construction, parsing, serialization, schema-version errors, deferred-field rejection, and resource behavior remain unchanged. Add focused import-path compatibility coverage here only if package tests do not already lock it.

### Contract Suite

- Status: deferred
- Expected paths: none beyond package import-boundary contracts for this phase.
- Required assertions or deferral reason: no new public data shape or persistence contract is introduced. Existing runtime serialization behavior remains covered by unit tests; descriptor, typed resource-entry, runtime metadata, and `RunOptions` contracts belong to later phases. The only contract-like assertion in this phase is the package import/public export contract covered by the package suite.

### Integration Suite

- Status: required
- Expected paths: existing integration suites that exercise runtime/resource parsing through pipeline/config flows, especially `tests/integration/pipeline/` and existing config-to-pipeline integration tests as selected during implementation.
- Required assertions or deferral reason: existing local runtime/resource behavior remains green after the import move; no new integration behavior is expected. Select the smallest existing integration targets that exercise runtime/resource parsing through pipeline/config flows; do not add new integration behavior for `RunOptions`, resources v4, descriptors, preflight, or CLI/config runtime mapping.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_local_pipeline_run.py`.
- Required assertions or deferral reason: the existing local pipeline e2e remains green, proving the package split did not change local run behavior. No new e2e scenario should be added for this boundary-only phase.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected.
- Required assertions or deferral reason: no optional backend, config-extra-only, scheduler, container, plugin, descriptor discovery, or opt-in runtime behavior is implemented in this phase; opt-in suites are intentionally not required.

## Risks

- Moving a module to a package can break import compatibility for callers or tests that rely on `loom.pipeline.runtime` as a module; preserve facade imports and avoid locking private leaf paths.
- Package-level exports can accidentally import future-heavy layers; use explicit exports and import-boundary tests.
- Documentation can overpromise descriptor behavior; describe ownership and direction only, with implementation deferred.
- Adding too much scaffolding can create public surface before later phases settle model names; keep package files minimal.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py
uv run pytest tests/package/test_pipeline_api.py
uv run pytest tests/unit/loom/pipeline/test_runtime_resources.py
uv run pytest tests/integration/pipeline/test_pipeline_config.py tests/integration/pipeline/test_local_execution.py
uv run pytest tests/e2e/test_local_pipeline_run.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: package conversion and facade exports first, package-level export compatibility second, import-boundary tests third, runtime behavior compatibility tests fourth, `docs/structure.md` update last.
- Tests to run with each slice: run package import-boundary tests after package/export edits; run runtime/resource unit tests after moving implementation; run targeted integration/e2e after all source and docs changes are complete.
- Decisions the executor must not revisit: no behavior changes; no `RunOptions`; no typed resource entries; no descriptor implementation; no CLI/config/preflight/runtime metadata wiring; runtime facade must remain import-light; descriptor boundary is documented only; public tests should assert the facade and current package re-exports, not a private leaf module.
- Conditions that require stopping for the manager: preserving `loom.pipeline.runtime` imports proves impossible, runtime import needs any forbidden layer, implementation appears to require placeholder modules beyond immediate package scaffolding, tests require changing runtime/resource behavior instead of preserving it, or the docs cannot describe descriptor direction without claiming descriptor behavior exists.
- Expanded-path refinement notes: completed on 2026-05-07. The refined plan keeps the package leaf private, makes import-light tests and docs obligations explicit, and records that Phase 1 remains free of `RunOptions`, typed resource schema, and descriptor behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: unused; planning refinement did not consume this later implementation/test fixer budget.
- PR review: unused; no PR review has been requested or performed.
- Blocker resolution: 0/3 used; no blocker-resolution pass has been needed.

## Completion Notes

- Draft plan: completed on 2026-05-07 by `loom_phase_planner`.
- Final phase execution plan: completed on 2026-05-07 by expanded-path refine pass.
- Implementation summary: completed on 2026-05-07 by fallback executor in commit
  `1059967 feat: split runtime package facade`. Converted
  `loom.pipeline.runtime` from a module into an import-light package facade,
  moved the existing runtime request implementation into a private package leaf,
  preserved `RuntimeKind`, `RuntimeRequest`, `parse_runtime_request`, and
  `RUNTIME_SCHEMA_VERSION` exports, strengthened runtime facade import-boundary
  and public import-path tests, and updated `docs/structure.md` for the runtime
  package and future descriptor import direction. No `RunOptions`, typed
  resource entries, profiles, environment models, executor descriptor behavior,
  registries, preflight wiring, CLI/config mapping, `runtime.json`, or runner
  request rewiring was introduced.
- Implementation validation: targeted package/unit command
  `uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py tests/unit/loom/pipeline/test_runtime_resources.py`
  passed with 42 tests. Targeted integration command
  `uv run pytest tests/integration/pipeline/test_pipeline_config.py tests/integration/pipeline/test_local_execution.py`
  skipped both modules in the default environment because config optional
  dependencies were not installed. Targeted e2e command
  `uv run pytest tests/e2e/test_local_pipeline_run.py` skipped the module in
  the default environment for the same optional dependency reason. Full
  `make validate-pr` passed: Ruff, Pyright, default harness
  (552 passed, 13 skipped, 12 deselected), config-extra harness (396 passed,
  567 deselected), and `uv build`.
- Refinement summary: scope boundaries tightened; preserved public runtime imports made explicit; `RunOptions`, resource schema, and descriptor behavior excluded; import-light package tests and `docs/structure.md` boundary updates made required; implementation refinement, PR review, and blocker-resolution budgets remain unused.
- Blocker-resolution summary: none used.
- PR preparation: not performed per fallback executor handoff; pending for
  `loom_pr_preparer`.
- Stack maintenance: pending.
- Remaining blockers: none known.
