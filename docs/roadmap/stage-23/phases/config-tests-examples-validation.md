# Phase 5 Execution Plan: Config Tests, Examples, And Validation Relocation

## Metadata

- Status: draft phase execution plan; ready for refinement
- Feature focus: Config Extraction
- PR title: `Config Extraction - Phase 5: Tests Examples And Validation`
- Branch: `codex/config-tests-examples-validation`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-tests-examples-validation`
- Phase execution plan path: `docs/roadmap/stage-23/phases/config-tests-examples-validation.md`
- Full plan: `docs/roadmap/stage-23/implementation-plan.md`
- Planning artifact: `docs/roadmap/stage-23/planning.md`
- Source phase: Stage 23 Phase 5, Test, Example, And Validation Relocation
- Stack predecessor: none; Phases 1 through 4 are merged
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible only after automated review, required validation, and CI pass while targeting `develop`; phase agents must not merge.
- Workflow path: expanded path
- Expanded-path reason: this phase moves many test/example files, changes validation summaries, and defines the durable package-local evidence shape used by final docs.
- Plan quality gate: passed on 2026-05-20 in the implementation plan, with no blocking findings after confirmation review.
- Draft pass: completed in this artifact.
- Refine pass: pending.
- Blockers: none known. Stop if package-local tests or examples require Loom runtime imports, if root adapter coverage would be lost, or if summary reporting needs a broad harness rewrite.

## Objective

Move config-owned tests and examples beside `packages/weave`, keep Loom-owned adapter/runtime coverage in root suites, and make validation targets and summary output report package-local `weave` evidence clearly.

## Full-Plan Context

Phases 1 through 4 pinned config artifacts, created and ported `weave`, and hard-switched Loom adapters with no `loom.config` shim. Phase 5 now removes the migration-era ownership confusion left in tests and examples: root paths should prove Loom behavior, while package-local paths should prove `weave` config behavior and examples.

This phase must not rewrite broad feature docs; Phase 6 owns final documentation hardening. It also must not reintroduce any `loom.config` import path or make package-local `weave` tests depend on Loom runtime modules.

## Scope

### In Scope

- Move config-owned unit tests from `tests/unit/loom/config/**` to package-local `packages/weave/tests/**`.
- Move pure config composition/integration contracts from root suites into package-local `weave` test tiers where they do not require Loom CLI, pipeline, store, or runtime behavior.
- Keep root tests that exercise Loom CLI adapters, queue config adapters, pipeline handoff, runtime fingerprints, or import boundaries.
- Move config authoring examples from root `examples/authoring/**` into `packages/weave/examples/**`.
- Add package-local example validation, preferably through a `make test-weave-examples` target backed by package-local pytest tests.
- Update package-local tests and examples to import `weave` and package-local helper modules, not `loom`.
- Update root example/catalog tests so moved config authoring examples are no longer treated as root Loom runtime examples.
- Update `make test-weave`, `make validate-weave`, `make test-summary`, and harness grouping so PR bodies can report package-local `weave` tests/examples separately.

### Out Of Scope

- Broad feature-doc, README, roadmap, or architecture copy rewrites beyond narrow references needed to keep moved examples discoverable.
- New config semantics or new example behavior.
- New package publication or release automation.
- Moving Loom runtime examples, CLI adapter tests, pipeline/store integration tests, or authority/queue/sweep workflows into `weave`.
- Reintroducing `loom.config` by shim, alias, test fixture, or compatibility path.

## Assumptions

- Package-local tests may keep synthetic fixtures copied from root when those fixtures are config-owned or target-instantiation-only.
- Root `tests/support/config_samples.py` remains available for Loom adapter tests, while a package-local support copy can serve standalone `weave` tests.
- Root CLI config tests remain under root because they prove Loom adapters call `weave`.
- Root pipeline fingerprint and runtime-profile tests remain under root when they prove Loom runtime compatibility with resolved config data.

## Acceptance Criteria

- Config-owned unit tests no longer live under `tests/unit/loom/config`.
- Package-local `weave` tests cover composition, includes, overlays, overrides, recipes, target instantiation/checks, artifacts, provenance, redaction, fingerprints, source maps, validation, and structured errors.
- Package-local `weave` examples exist under `packages/weave/examples` and use `weave` imports.
- `make test-weave-examples` exists and validates relocated config authoring examples.
- `make validate-weave` includes package-local tests, examples, type checks, lint, and build.
- `make test-summary` reports package-local `weave` evidence separately enough for PR bodies and final docs.
- Root suites still cover Loom config adapter workflows and import boundaries.
- `rg "loom\\.config" src tests packages examples pyproject.toml` finds only historical notes or intentional absence assertions.

## Design Impact

- Maintainability: package-owned tests and examples move with package-owned implementation, reducing future extraction work.
- Extensibility: package-local examples become reusable as future standalone `weave` docs/examples.
- Reviewability: root diffs should separate mechanical moves from targeted harness/validation changes.
- Source-tree boundaries: root tests remain focused on Loom adapter/runtime behavior rather than config internals.

## Future Compatibility

- Phase 6 can update docs against final package-local evidence instead of explaining transitional root test paths.
- A future standalone `weave` repository can lift `packages/weave/src`, `packages/weave/tests`, and `packages/weave/examples` together.
- Future runtime-only Loom packaging remains easier to reason about because root tests no longer double as config implementation tests.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Leave root config tests in place until docs hardening | Keeps ownership ambiguous after the hard switch and weakens future repository extraction. |
| Move every config-consuming root test into `weave` | Would lose Loom adapter, CLI, queue, pipeline, and runtime compatibility coverage. |
| Rewrite the whole test harness | Phase 5 needs package evidence, not a broad test-platform redesign. |
| Keep config authoring examples under root with `weave` imports | Makes root examples mix authored-config package docs with Loom runtime workflows. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Some root adapter tests still use config sample fixtures | They prove Loom adapter behavior and do not own config implementation semantics. | Adapter tests begin asserting config internals instead of CLI/runtime outcomes. |
| Package-local tests may initially mirror root fixture names | Preserves behavior while moving ownership. | A standalone `weave` repo starts and wants renamed fixture taxonomy. |

## Reviewability

- Expected PR shape: mostly `git mv` file relocation plus narrow import/support rewrites, package-local example tests, and Make/harness summary updates.
- Primary review areas: moved package-local tests, package-local examples, `make/test/targets.mk`, `make/dev/targets.mk`, `tools/test_harness/cli.py`, and root tests retained for Loom adapters.
- Scope-control checks: no `src/loom/config`, no `loom.config` shim, no new config semantics, no runtime example moves into `weave`, and no broad docs rewrite.

## Implementation Steps

1. Move pure config unit tests into package-local `packages/weave/tests/unit/config`.
2. Add package-local test support fixtures and replace remaining Loom helper imports with `weave` helpers where tests are package-owned.
3. Move pure config integration/contract tests into package-local tiers; leave root Loom adapter/runtime tests in place.
4. Move config authoring examples to `packages/weave/examples` and adjust their paths/imports.
5. Add package-local example validation tests and a `make test-weave-examples` target.
6. Update `make validate-weave` and `make test-summary` to include package-local tests/examples evidence.
7. Run import/reference sweeps and package/root validation.

## Test Plan

- Package suite: `make test-weave`, package-local example tests, and import-boundary package tests.
- Unit suite: root unit tests after moving config-owned tests; package-local unit tests for moved config behavior.
- Contract suite: root contracts for Loom adapters/plugins remain; package-local config contracts move or are mirrored where Loom-free.
- Integration suite: root config CLI adapter tests remain; package-local config composition integration tests move.
- E2E suite: root Loom CLI/e2e config workflows remain.
- Opt-in suite: `make test-config-extra` must still prove root adapter workflows through `weave`.

## Validation Commands

```sh
make test-weave
make test-weave-examples
make validate-weave
uv run pytest tests/package/test_import_boundaries.py
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
make test-config-extra
make validate-pr
make test-summary
rg "loom\\.config" src tests packages examples pyproject.toml
```

## Risks And Stop Conditions

- Stop if package-local tests need Loom runtime modules rather than package-owned `weave` helpers.
- Stop if moved examples cannot run without root Loom runtime context.
- Stop if root adapter coverage for CLI validate/plan/run/sweep, queue config, diagnostics, or plugins would be removed.
- Stop if `make validate-weave` or `make test-summary` requires a broad harness redesign instead of a bounded suite addition.

## Refinement And Review Budget Status

- Planning/refinement budget: draft used; refine pass pending.
- Phase implementation refinement: unused.
- PR review: unused.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: completed in this artifact.
- Refine plan: pending.
