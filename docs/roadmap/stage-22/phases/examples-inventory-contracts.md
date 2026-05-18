# Phase 1 Execution Plan: Example Inventory And Metadata Contracts

## Metadata

- Status: final phase execution plan
- Feature focus: Examples And Validation
- PR title: `Examples And Validation - Phase 1: Inventory Contracts`
- Branch: `codex/examples-inventory-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/examples-inventory-contracts`
- Phase execution plan path: `docs/roadmap/stage-22/phases/examples-inventory-contracts.md`
- Full plan: `docs/roadmap/stage-22/implementation-plan.md`
- Source phase: Phase 1, "Example Inventory And Metadata Contracts"
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR; merge-eligible after automated review, required validation, CI, and target-branch checks pass against `develop`
- Workflow path: fast path
- Successor dependency notes: Phase 2 should branch from `develop` after this PR merges, or from `codex/examples-inventory-contracts` only if this phase is validated and open but not yet mergeable.
- Plan quality gate: passed on 2026-05-18 in `docs/roadmap/stage-22/implementation-plan.md`
- Plan quality gate loop budget: already consumed and passed before this phase plan; no further plan-review pass requested
- Draft pass: completed in this artifact
- Refine pass: not needed on fast path; phase scope is docs/examples/tests-only and no blockers are recorded
- Setup limitations: none for implementation; worktree was created from local `origin/develop` at `ac95cf8`
- Blockers: none

## Objective

Define a stable, docs-owned example inventory contract so every existing example advertises its ID, status, validation tier, public surface, owning feature documentation, owning roadmap stage, prerequisites, and validation path, with lightweight checks that keep `examples/README.md`, group READMEs, feature coverage docs, and manifests aligned.

## Full-Plan Context

Stage 22 hardens examples, integration tests, e2e tests, and documentation for behavior that already exists. Phase 1 creates the inventory and consistency baseline that later phases depend on when they add stronger runnable-example coverage, representative e2e workflows, and final documentation cleanup. Later phases must remain out of scope here: do not add new example workflows, broaden integration behavior, add e2e journeys, or perform the final feature-doc audit beyond changes needed to make the inventory contract truthful.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 1 is the first Stage 22 phase, the open PR list was empty before selection, and `origin/develop` records the passed Stage 22 plan-quality gate.
- Retarget/rebase plan after predecessor merge: none; this phase targets `develop` directly.
- Branch cleanup constraints: no successor should depend on this branch after it is merged and Phase 2 branches from updated `develop`.

## Source Phase Summary

- Goal: define example inventory shape, status/tier vocabulary, and lightweight consistency validation.
- Required scope: `examples/README.md`, `examples/**/example.yaml`, existing or new docs/example validation tests, and targeted `docs/features/*-example-coverage.md` updates needed by metadata ownership and validation-path fields.
- Required checkpoints: metadata conventions, manifest/README consistency checks, feature-doc link consistency, and preservation of existing runnable smoke-example behavior.
- Acceptance criteria: manifests expose stable IDs, statuses, validation tiers, public surfaces, owning docs/stages, prerequisites, and validation commands; catalog and feature coverage docs are internally consistent; checks treat metadata as docs/test inputs with no runtime imports.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `examples/README.md` defines authoring, execution, and operations groups plus `smoke`, `full`, and `manual` validation tiers.
  - `examples/authoring/README.md`, `examples/execution/README.md`, and `examples/operations/README.md` list primary user-facing examples and internal demos.
  - There are 26 current `examples/**/example.yaml` manifests with fields such as `id`, `title`, `summary`, `capability`, `level`, `introduced_in`, `status`, `validation`, `surface`, `entrypoints`, and `tags`.
  - Focused coverage docs already exist for config, SLURM, authority, and containers under `docs/features/*-example-coverage.md`.
- Existing tests or harness behavior:
  - `tests/integration/docs/test_v0_python_examples.py` validates manifest shape, ID/path agreement, status/tier/surface vocabulary, README presence, selected feature-coverage docs, primary-catalog exclusions for `internal_demo`, and `smoke` Python entrypoint execution.
  - Existing vocabulary is `status: runnable|illustrative|deferred`, `validation: smoke|full|manual`, and `surface: cli|python_api|internal_demo`.
  - Suite layout includes package, unit, contract, integration, e2e, and opt-in container/SLURM acceptance hooks; default checks must stay local/fake-backed.
- Import-boundary or dependency constraints:
  - Core runtime modules must not import examples or docs validation helpers.
  - Metadata remains plain YAML and docs/test-owned, not a runtime schema or public API.
  - Validation may use existing test dependencies such as PyYAML through the docs integration harness; no heavyweight runtime dependency should be added.

## In-Scope Work

- Extend the manifest contract in `examples/**/example.yaml` with explicit ownership and validation metadata needed by Stage 22, using plain YAML fields.
- Document the metadata vocabulary in `examples/README.md` and keep group README catalog rows consistent with manifest IDs and surfaces.
- Add or update lightweight validation in `tests/integration/docs/test_v0_python_examples.py`, or a small docs-only helper plus focused tests if that keeps the harness clearer.
- Ensure manual or illustrative examples record external prerequisites and rationale, while runnable examples record a named validation path or command.
- Update only targeted feature coverage docs needed to keep manifest `owner_docs` and validation-path references true.

## Out-of-Scope Work

- Adding new runtime behavior, CLI behavior, executor behavior, stores, authority behavior, cleanup/retention behavior, plugin behavior, or provider integrations.
- Adding new robust example workflows, broadening example scripts, or converting manual external-system examples into default-runnable examples.
- Adding representative e2e journeys or broad integration coverage planned for Phases 2 and 3.
- Replacing in-repo YAML manifests with generated docs tooling, a package export, or a runtime schema.
- Performing the final Stage 22 documentation audit or implementation-plan completion metadata updates planned for Phase 4.

## Assumptions

- `example.yaml` remains the inventory source of truth, with README and feature-doc tables treated as projections that validation checks for drift.
- The current status/tier vocabulary remains valid for this phase; any new field should clarify ownership or validation evidence rather than rename existing concepts.
- A validation command/path can be a Make target, pytest path, or specific test node where that is the clearest durable evidence.
- Existing `internal_demo` examples remain runnable regression coverage but stay out of primary user-facing catalogs.

## Scope Contract

No runtime public API changes are in scope. The only contract this phase may introduce is a docs/test metadata contract for example manifests. That contract should stay plain-data and reviewable:

- Stable `id` values continue to match the example directory path.
- `status`, `validation`, and `surface` keep their current vocabularies unless the implementation plan explicitly forces a small docs-only addition.
- Ownership metadata must point to existing repository docs or roadmap stages and must be validated for path existence where practical.
- Validation metadata must distinguish default runnable evidence from manual or opt-in evidence.
- Manual, illustrative, or deferred examples must continue to explain why default validation cannot run them.
- Validation failures should be ordinary test assertion failures with actionable paths, not runtime exceptions from imported `loom` internals.

## Design Impact

- Maintainability: centralizing manifest and README consistency checks reduces silent drift as later phases add or reclassify examples.
- Extensibility: plain YAML fields allow later example groups or validation tiers without adding a runtime framework.
- Domain neutrality: metadata should describe generic Loom workflows and validation paths, not domain-specific datasets, models, metrics, or downstream packages.
- Source-tree boundaries: changes stay in `examples/`, `docs/features/`, and tests/docs validation; `src/loom` should remain untouched.

## Future Compatibility

This phase should leave room for Phases 2 through 4 to add stronger integration/e2e evidence and final docs cleanup by making validation paths precise but not overfitting them to current test names when a suite-level path is more durable. If metadata pressure grows beyond YAML assertions, the revisit trigger is a future docs-tooling phase, not a Phase 1 runtime helper.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Generate a separate examples database or docs site index | Too much tooling for Stage 22 and outside the in-repo docs/examples/tests scope. |
| Move example metadata parsing into `src/loom` | Would create a runtime import boundary and public-contract risk for docs-only data. |
| Treat every `full` or manual example as default-runnable | Conflicts with deterministic local validation and external-system boundaries. |
| Defer README consistency checks to final docs refinement | Later phases need a stable inventory baseline before expanding coverage. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Manifest metadata remains enforced by tests rather than a typed schema package | The metadata is docs/test-owned and should not become runtime surface during Stage 22 | Multiple tools need to consume the metadata outside tests, or validation logic becomes difficult to review. |
| Some validation evidence may initially point at suite/test paths rather than per-example assertions | Phase 1 is inventory-focused; Phases 2 and 3 own deeper runnable and e2e evidence | A runnable example lacks meaningful backing evidence after Phase 3. |

## Reviewability

- Expected PR size and shape: a docs/examples/tests PR touching manifests, catalog docs, targeted feature coverage docs, and focused docs validation tests.
- Files and areas to inspect: `examples/**/example.yaml`, `examples/README.md`, group READMEs, `docs/features/*-example-coverage.md`, and `tests/integration/docs/test_v0_python_examples.py` or the chosen docs-only helper tests.
- Scope-control checks: no `src/loom` changes, no new example workflow implementation, no new external dependency in default validation, and no broad feature-doc rewrite.

## Implementation Steps

1. Define the minimal manifest metadata additions and document the vocabulary in `examples/README.md`.
2. Normalize existing manifests and catalog/group README references to the agreed inventory fields without changing example behavior.
3. Add consistency checks for manifest ownership fields, README catalog membership, feature coverage doc references, validation paths, and manual prerequisite rationale.
4. Update targeted feature coverage docs only where needed for the new ownership or validation-path references to be true.
5. Run targeted docs/example validation, then leave final `make validate-pr` and `make test-summary` evidence for PR preparation after implementation.

## Test Plan

### Package Suite

- Status: deferred
- Expected paths: none
- Required assertions or deferral reason: this phase must not add public package exports or import-surface behavior; run package checks only if implementation unexpectedly touches package metadata, which should be a stop condition.

### Unit Suite

- Status: required if a reusable docs-only helper is introduced; otherwise deferred
- Expected paths: likely `tests/unit/tools/` or another existing test-only helper location if used
- Required assertions or deferral reason: validate helper parsing and error messages without importing runtime modules. If assertions stay inside `tests/integration/docs/test_v0_python_examples.py`, separate unit coverage is intentionally deferred because no reusable unit exists.

### Contract Suite

- Status: deferred
- Expected paths: none
- Required assertions or deferral reason: the manifest shape is not a runtime extension-point contract. Do not add `tests/contracts` coverage unless implementation creates a stable public schema, which is out of scope.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/docs/test_v0_python_examples.py`
- Required assertions or deferral reason: manifest fields, status/tier/surface vocabulary, owner doc paths, owning roadmap stages, validation path/command references, README catalog membership, feature coverage doc references, manual prerequisite rationale, and preservation of existing smoke example execution.

### E2E Suite

- Status: deferred
- Expected paths: none
- Required assertions or deferral reason: Phase 3 owns representative user journeys. Phase 1 may reference existing e2e paths as validation metadata but should not add new e2e tests.

### Opt-In Suites

- Status: deferred
- Markers affected: container and SLURM acceptance hooks remain manual/opt-in
- Required assertions or deferral reason: real Docker, Apptainer, SLURM, network, hosted service, or provider-backed checks are outside default Stage 22 Phase 1 validation. Manual examples should name these prerequisites instead.

## Risks

- Metadata additions could become too broad and make manifests noisy.
- README consistency checks could overfit prose instead of validating durable IDs, links, and sections.
- Existing examples may need reclassification, which could accidentally drift into Phase 2 coverage work.
- Validation path fields may become stale if they point at overly specific test nodes.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/integration/docs/test_v0_python_examples.py
make test-integration
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: metadata vocabulary/docs, manifest normalization, consistency tests, targeted feature-doc link updates.
- Tests to run with each slice: run `uv run pytest tests/integration/docs/test_v0_python_examples.py` after manifest/test changes; run `make test-integration` if the docs harness is reorganized.
- Decisions the executor must not revisit: no runtime imports from examples/docs tooling, no new runtime behavior, no e2e expansion, and no replacement of YAML manifests with generated tooling.
- Conditions that require stopping for the manager: a required field cannot be populated without implementing product behavior, a validation check needs external services in the default suite, or a metadata schema would need to become public runtime surface.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on fast path in this artifact
- Final phase execution plan: completed on fast path; refine pass not needed
- Implementation summary: added docs-owned inventory metadata to all 26 existing example manifests, documented field vocabulary in `examples/README.md`, added/expanded integration checks in `tests/integration/docs/test_v0_python_examples.py` for ownership, README/catalog consistency, feature-coverage references, validation evidence pointers, and manual rationale requirements. No runtime behavior changes or new examples were introduced.
- Implementation validation: required command run with full suite produced socket-restricted child-process failures in this environment (`PermissionError: [Errno 1] Operation not permitted` from `_socket.socket.__init__`) during example execution; metadata/contract checks passed. Verified non-execution checks explicitly with `UV_CACHE_DIR=.uv-cache uv run --active pytest tests/integration/docs/test_v0_python_examples.py -k 'not smoke_example_scripts_execute'` (12 passed, 23 deselected).
- Refinement summary: not used
- Blocker-resolution summary: none used
- PR preparation: pending
- Stack maintenance: root phase targeting `develop`; no predecessor maintenance needed
- Remaining blockers: none
