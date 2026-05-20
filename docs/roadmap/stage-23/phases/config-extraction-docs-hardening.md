# Phase 6 Execution Plan: Documentation And Final Hardening

## Metadata

- Status: implementation complete; ready for PR preparation
- Feature focus: Config Extraction
- PR title: `Config Extraction - Phase 6: Documentation And Final Hardening`
- Branch: `codex/config-extraction-docs-hardening`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-extraction-docs-hardening`
- Phase execution plan path: `docs/roadmap/stage-23/phases/config-extraction-docs-hardening.md`
- Full plan: `docs/roadmap/stage-23/implementation-plan.md`
- Planning artifact: `docs/roadmap/stage-23/planning.md`
- Source phase: Stage 23 Phase 6, Documentation And Final Hardening
- Stack predecessor: none; Phases 1 through 5 are merged
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible only after automated
  review, required validation, and CI pass while targeting `develop`; phase
  agents must not merge.
- Workflow path: expanded path
- Expanded-path reason: this phase changes broad user-facing docs, final
  roadmap metadata, and durable validation evidence for the completed package
  split.
- Plan quality gate: passed on 2026-05-20 in the implementation plan, with no
  blocking findings after confirmation review.
- Draft pass: completed and committed.
- Refine pass: completed in this artifact.
- Blockers: none known. Docs changes did not reopen config semantics, require
  package publication work, or contradict the confirmed no-shim package split.

## Refinement Summary

- Treat current user-facing docs as the primary target; leave historical roadmap
  references intact only when they clearly describe pre-extraction state.
- Keep `examples/authoring/README.md` as a root handoff page, but make
  `packages/weave/examples/README.md` and package-local validation the canonical
  config authoring example surface.
- Prefer reference sweeps plus existing docs/example tests over adding broad new
  docs tooling; add or adjust tests only when they protect final import paths or
  example ownership.
- Final validation evidence should include both package-local `weave` health and
  root Loom adapter/runtime health.

## Objective

Align repository docs, examples, roadmap metadata, and final validation evidence
with the completed `weave` extraction while keeping Loom framed as the
domain-neutral workflow/runtime package.

## Full-Plan Context

Phases 1 through 5 created and hard-switched `weave`, removed `src/loom/config`,
and moved config-owned tests and examples beside the package. Phase 6 is the
final docs and validation hardening pass: users should now see `weave` as the
trusted config authoring package and Loom as the runtime that uses `weave`
through explicit adapter edges.

This phase must not introduce new config behavior, package publishing, a
`loom.config` shim, or extra package splits.

## Scope

### In Scope

- Update source-tree and package-boundary docs, especially
  `docs/structure.md` and `docs/loom.md`.
- Update config feature docs and examples from `loom.config` to `weave` where
  they are current user instructions.
- Update serialization, fingerprint, and error docs to explain that Loom and
  `weave` own separate helper behavior where needed.
- Update plugin docs to describe `weave` recipe loading while preserving the
  Stage 23 `loom.recipes` entry-point group name.
- Update CLI docs to describe config adapter behavior and error translation.
- Update testing docs and config test matrix with `make validate-weave`,
  `make test-weave-examples`, and `make test-summary` evidence.
- Update roadmap metadata and this implementation plan with final completion
  evidence.
- Run final root and package validation and record suite-level evidence.

### Out Of Scope

- New config semantics or examples beyond import/path/documentation hardening.
- Package publication, release automation, or registry availability checks.
- Additional package splits or runtime architecture redesign.
- Rewriting unrelated roadmap stages or unrelated feature documentation.

## Assumptions

- Historical roadmap notes may keep `loom.config` references when they clearly
  describe pre-Stage-23 history.
- Current user-facing instructions should use `weave` for direct config
  authoring and Loom CLI/runtime docs should describe adapter behavior.
- The root `docs/roadmap.md` may already have local user edits in the control
  checkout; Phase 6 docs work happens only in this phase worktree.

## Acceptance Criteria

- Current docs no longer instruct users to import `loom.config`.
- Docs consistently describe `weave` as the config authoring distribution and
  import package.
- Loom docs describe explicit config adapter edges rather than config ownership.
- Example catalog and coverage docs point config authoring examples at
  `packages/weave/examples`.
- Testing docs and matrices include package-local `weave` validation and final
  summary evidence.
- Stage 23 roadmap metadata records Phase 6 completion, final validation, and
  accepted follow-ups.
- `rg "loom\\.config" docs examples tests src packages` leaves only historical
  notes or intentional absence assertions.

## Design Impact

- Maintainability: docs, tests, and package layout will agree on ownership,
  reducing future extraction confusion.
- Extensibility: future standalone `weave` work can use package-local docs,
  tests, and examples as the movable unit.
- Reviewability: docs changes are bounded to Stage 23 ownership and validation
  language; unrelated content should remain untouched.
- Public contract clarity: direct config users import `weave`; Loom config
  workflows consume `weave` through adapters.

## Future Compatibility

- Future runtime-only Loom packaging can build from docs that already separate
  config authoring from runtime ownership.
- A future standalone `weave` repository can lift `packages/weave/src`,
  `packages/weave/tests`, and `packages/weave/examples` with less doc churn.
- A future recipe entry-point migration can start from the recorded Stage 23
  debt that `loom.recipes` remains the compatibility group.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Leave docs hardening for a later roadmap stage | Users would see stale import paths after the no-shim hard switch. |
| Rewrite all feature docs broadly | Phase 6 is about package-boundary accuracy, not unrelated prose cleanup. |
| Rename the recipe entry-point group now | The implementation plan explicitly defers that compatibility migration. |
| Add a `loom.config` compatibility note as a current path | The confirmed Stage 23 behavior is no default shim. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Historical docs still mention pre-extraction paths | Preserves roadmap traceability. | A historical mention appears in current user instructions. |
| `loom.recipes` remains the plugin group name | Preserves existing plugin metadata for Stage 23. | Standalone `weave` publication needs a config-named group or dual-group migration. |

## Reviewability

- Expected PR shape: docs and roadmap updates plus any narrow docs/example
  validation test adjustments needed to keep current references accurate.
- Primary review areas: `docs/structure.md`, `docs/loom.md`,
  `docs/features/config.md`, example coverage docs, testing docs, roadmap
  metadata, and final validation evidence.
- Scope-control checks: no source behavior changes unless a docs/example test
  needs a narrow update to validate current paths.

## Implementation Steps

1. Inventory current `loom.config`, `examples/authoring`, and config ownership
   references across docs, examples, tests, and package docs.
2. Update source-tree, Loom overview, config feature, plugin, CLI, helper
   ownership, testing, and example coverage docs for the final `weave` split.
3. Update example catalog or docs tests only where needed to validate current
   package-local example references.
4. Run targeted docs/example checks and import-reference sweeps.
5. Run package-local and combined validation.
6. Update implementation-plan completion metadata and prepare the PR body with
   final suite evidence.

## Test Plan

- Package suite: `make validate-weave` and `make test-weave-examples`.
- Docs/example suite: targeted docs/example tests that validate runnable
  examples and example manifests.
- Root combined gate: `make validate-pr`.
- Suite evidence: `make test-summary`.
- Reference sweeps: `rg "loom\\.config" docs examples tests src packages` plus
  focused `examples/authoring` / `packages/weave/examples` checks.

## Validation Commands

```sh
make validate-weave
make test-weave-examples
uv run pytest tests/integration/docs/test_v0_python_examples.py tests/integration/examples/test_example_workflows.py
rg "loom\\.config" docs examples tests src packages
rg "examples/authoring|authoring\\." docs examples tests packages
make validate-pr
make test-summary
```

## Validation Evidence

| Command/check | Result |
| --- | --- |
| `make validate-weave` | Passed: package Ruff, Pyright, 375 package tests, 8 package examples, and package build. |
| `uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py tests/integration/examples/test_example_workflows.py` | Passed outside sandbox with 33 tests. |
| Active public import sweep | Passed: no current docs/examples/source references to `loom.config` except intentional absence assertions in `tests/package/test_import_boundaries.py`. |
| Authoring example sweep | Passed: no `examples/authoring` or `authoring.` references remain in active docs/examples/tests. |
| Full historical sweep | Reviewed: remaining `loom.config` references are historical roadmap/planning notes or intentional absence assertions. |
| `make validate-pr` | Passed outside sandbox: Ruff, Pyright, default suite, config-extra suite, `validate-weave`, root build. |
| `make test-summary` | Passed; wrote `build/test-summary.md` with package, unit, contract, integration, e2e, config-extra, weave, and weave-examples rows. |

## Risks And Stop Conditions

- Stop if final docs contradict confirmed design decisions from the planning
  artifact or implementation plan.
- Stop if current user docs still require `loom.config` after edits.
- Stop if final validation cannot run, or if package-local `weave` evidence
  disappears from `make test-summary`.
- Stop if docs changes require publishing, release automation, new config
  semantics, or broad unrelated roadmap rewrites.

## Refinement And Review Budget Status

- Planning/refinement budget: used; expanded-path draft and refine completed.
- Phase implementation refinement: not needed; targeted and full validation
  passed after manager implementation.
- PR review: unused.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: completed in commit `10461fb`.
- Refine plan: completed in commit `d4e9a52`.
- Implementation: updated current user-facing docs, README examples, structure
  docs, feature docs, package docs, example catalog references, testing docs,
  roadmap metadata, and a narrow docs/example test expectation so repository
  instructions now present `weave` as the config authoring package and Loom as
  the runtime using explicit config adapter paths.
- Validation: `make validate-weave`, targeted docs/example tests,
  import-reference sweeps, `make validate-pr`, and `make test-summary` passed.
